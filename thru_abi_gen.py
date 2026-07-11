#!/usr/bin/env python3
"""
thru-abi-gen
============
Generate a Thru ABI YAML artifact directly from the packed C structs a Thru
program already defines, so the hand-written ABI stops drifting from the source.

Thru ABIs are hand-authored today and do NOT auto-sync with the program
(see thru.org/docs -> ABI Overview). This tool closes the C -> ABI direction the
official codegen never covers (`thru abi codegen` only goes ABI -> C/Rust/TS).

What it does:
  * parses `typedef struct __attribute__((packed)) { ... } name_t;`
  * maps C primitives -> Thru ABI primitives (little-endian, packed)
  * resolves fixed arrays, including sizes given as #define constants
  * emits an explorer-compatible ABI: program-metadata.root-types + a single
    discriminated instruction envelope (the shape explorer reflection expects)
  * optional --check shells out to `thru abi analyze` to prove it resolves

Deliberately conservative: it converts the tedious, error-prone layout part and
scaffolds the metadata; it never invents authorization semantics (the ABI only
describes wire format, per the docs).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional

# --- C primitive -> Thru ABI primitive -------------------------------------
# Thru ABI primitives: signed/unsigned ints, floats, char (little-endian).
PRIMITIVES = {
    # explicit width (preferred, unambiguous)
    "uint8_t": "u8", "uint16_t": "u16", "uint32_t": "u32", "uint64_t": "u64",
    "int8_t": "i8", "int16_t": "i16", "int32_t": "i32", "int64_t": "i64",
    # SDK / classic C spellings used across Thru examples
    "uchar": "u8", "ushort": "u16", "uint": "u32", "ulong": "u64",
    "unsigned char": "u8", "unsigned short": "u16",
    "unsigned int": "u32", "unsigned long": "u64",
    "char": "char", "short": "i16", "int": "i32", "long": "i64",
    "float": "f32", "double": "f64", "bool": "u8", "_Bool": "u8",
}

# Constants shipped by the C SDK that show up in example headers.
SDK_CONSTANTS = {"TN_SEED_SIZE": 32}


@dataclass
class Field:
    name: str
    ctype: str
    array_size: Optional[int] = None          # resolved element count, if array
    array_size_expr: Optional[str] = None     # original expr, for diagnostics


@dataclass
class Struct:
    name: str          # ABI type name (PascalCase)
    c_name: str        # original C typedef name
    fields: list = field(default_factory=list)
    role: Optional[str] = None   # instruction | account | events | errors
    abi_override: Optional[str] = None


# --- parsing ---------------------------------------------------------------
DEFINE_RE = re.compile(r"^\s*#define\s+([A-Za-z_]\w*)\s+(.+?)\s*$")
STRUCT_RE = re.compile(
    r"typedef\s+struct\s*(?:__attribute__\s*\(\(\s*packed\s*\)\)\s*)?\{"
    r"(?P<body>.*?)\}\s*(?P<name>[A-Za-z_]\w*)\s*;",
    re.DOTALL,
)
# `type name` or `type name[SIZE]`  (type may be multi-word e.g. "unsigned char").
# Applied per-statement (body is split on ';'), so it is line-layout independent.
FIELD_RE = re.compile(
    r"^\s*(?P<type>[A-Za-z_][\w\s]*?)\s+(?P<name>[A-Za-z_]\w*)"
    r"\s*(?:\[\s*(?P<size>[A-Za-z_0-9]+)\s*\])?\s*$"
)
# inline annotations: // @abi:instruction-root  // @abi:account-root
#                     // @abi:events  // @abi:errors  // @abi:name=CreateArgs
ANNOT_RE = re.compile(r"//\s*@abi:([a-zA-Z0-9\-]+)(?:=([A-Za-z_]\w*))?")


def strip_block_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def collect_defines(text: str) -> dict:
    consts = dict(SDK_CONSTANTS)
    for line in text.splitlines():
        m = DEFINE_RE.match(line)
        if not m:
            continue
        name, raw = m.group(1), m.group(2)
        raw = raw.split("//")[0].strip().rstrip("uUlL")
        raw = raw.strip("()")
        try:
            consts[name] = int(raw, 0)
        except ValueError:
            pass  # non-numeric define, ignore
    return consts


def pascal_case(c_name: str) -> str:
    base = c_name[:-2] if c_name.endswith("_t") else c_name
    return "".join(p.capitalize() for p in base.split("_") if p)


def annotations_above(text: str, struct_start: int) -> dict:
    """Read `// @abi:...` lines in the handful of lines preceding a struct."""
    prefix = text[:struct_start].splitlines()[-6:]
    found = {}
    for line in prefix:
        for role, val in ANNOT_RE.findall(line):
            found[role] = val or True
    return found


def parse_header(source: str) -> tuple:
    consts = collect_defines(source)
    clean = strip_block_comments(source)  # keeps // line comments (annotations)
    structs = []
    for m in STRUCT_RE.finditer(clean):
        c_name = m.group("name")
        annots = annotations_above(clean, m.start())
        st = Struct(name=pascal_case(c_name), c_name=c_name)
        if isinstance(annots.get("name"), str):
            st.abi_override = annots["name"]
            st.name = annots["name"]
        for role in ("instruction-root", "account-root", "events", "errors"):
            if role in annots:
                st.role = role
        # strip // line comments, then treat each ';'-terminated statement as a field
        body = re.sub(r"//[^\n]*", "", m.group("body"))
        for stmt in body.split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            fm = FIELD_RE.match(stmt)
            if not fm:
                continue
            ctype = " ".join(fm.group("type").split())
            size_tok = fm.group("size")
            size_val, size_expr = None, None
            if size_tok is not None:
                size_expr = size_tok
                size_val = int(size_tok) if size_tok.isdigit() else consts.get(size_tok)
                if size_val is None:
                    raise ValueError(
                        f"array size '{size_tok}' in {c_name}.{fm.group('name')} "
                        f"is not a literal or known #define"
                    )
            st.fields.append(Field(fm.group("name"), ctype, size_val, size_expr))
        structs.append(st)
    return structs, consts


# --- ABI model emission ----------------------------------------------------
def abi_primitive(ctype: str) -> str:
    if ctype not in PRIMITIVES:
        raise ValueError(
            f"unmapped C type '{ctype}'. Add it to PRIMITIVES or use a stdint type."
        )
    return PRIMITIVES[ctype]


def field_to_abi(f: Field) -> dict:
    prim = abi_primitive(f.ctype)
    if f.array_size is not None:
        ft = {
            "array": {
                "size": {"literal": {"u64": f.array_size}},
                "element-type": {"primitive": prim},
            }
        }
    else:
        ft = {"primitive": prim}
    return {"name": f.name, "field-type": ft}


def struct_to_abi(st: Struct) -> dict:
    return {
        "name": st.name,
        "kind": {
            "struct": {
                "packed": True,
                "fields": [field_to_abi(f) for f in st.fields],
            }
        },
    }


def _pascal(word: str) -> str:
    return word[:1].upper() + word[1:] if word else word


def resolve_instruction_types(structs, variants, discriminator=None):
    """
    Decide how to model the discriminated instruction root so its wire layout
    matches the program's real bytes.

    Real Thru programs lead every instruction struct with the SAME discriminator
    field (e.g. `uint instruction_type`), and that field IS the tag on the wire —
    it is not a separate 1-byte value. So when every variant struct shares an
    identical first field, we:
      * set the envelope tag to that field's actual width (u32 for `uint`, etc.)
      * strip it from each variant, emitting a `<Variant>Payload` remainder type
    That yields `[tag][payload]` == the exact bytes the program reads.

    If the variants do NOT share a common leading field (e.g. the docs' idealized
    `InitializeArgs{seed}` / `IncrementArgs{amount}` shapes), we fall back to a
    separate `u8` tag and reference the full variant structs unchanged.

    Returns (tag_primitive, payload_types, consumed_names, variant_specs) where
    variant_specs is a list of (tag_value, payload_type_name, variant_name).
    """
    by_name = {s.name: s for s in structs}
    variant_structs = []
    for tv, tname, vname in variants:
        if tname not in by_name:
            raise ValueError(f"--instructions references unknown type '{tname}'")
        variant_structs.append((tv, by_name[tname], vname))

    # do all variants share an identical leading field?
    first_fields = [vs.fields[0] for _, vs, _ in variant_structs if vs.fields]
    shared = None
    if len(first_fields) == len(variant_structs) and first_fields:
        f0 = first_fields[0]
        want = discriminator or f0.name
        if all(f.name == want and f.ctype == f0.ctype for f in first_fields):
            shared = f0

    if shared is None:
        # fallback: separate u8 tag, full variant structs as payloads
        specs = [(tv, vs.name, vn) for tv, vs, vn in variant_structs]
        return "u8", [], set(), specs

    tag_primitive = abi_primitive(shared.ctype)
    payload_types, specs, consumed = [], [], set()
    for tv, vs, vn in variant_structs:
        consumed.add(vs.name)
        payload_name = f"{_pascal(vn)}Payload"
        payload_types.append({
            "name": payload_name,
            "kind": {"struct": {
                "packed": True,
                "fields": [field_to_abi(f) for f in vs.fields[1:]],  # drop discriminator
            }},
        })
        specs.append((tv, payload_name, vn))
    return tag_primitive, payload_types, consumed, specs


def build_instruction_envelope(root_name: str, tag_primitive: str, variant_specs: list) -> dict:
    """variant_specs: list of (tag_value:int, payload_type_name:str, variant_name:str)."""
    return {
        "name": root_name,
        "kind": {
            "struct": {
                "packed": True,
                "fields": [
                    {"name": "tag", "field-type": {"primitive": tag_primitive}},
                    {
                        "name": "payload",
                        "field-type": {
                            "enum": {
                                "packed": True,
                                "tag-ref": {"field-ref": {"path": ["tag"]}},
                                "variants": [
                                    {
                                        "name": vn,
                                        "tag-value": tv,
                                        "variant-type": {"type-ref": {"name": tn}},
                                    }
                                    for tv, tn, vn in variant_specs
                                ],
                            }
                        },
                    },
                ],
            }
        },
    }


def build_abi(structs, args, variants):
    root_types = {}
    # explicit flags win, else fall back to annotations
    inst_root = args.instruction_root
    acct_root = args.account_root or next(
        (s.name for s in structs if s.role == "account-root"), None
    )
    events = args.events or next(
        (s.name for s in structs if s.role == "events"), None
    )
    errors = args.errors or next(
        (s.name for s in structs if s.role == "errors"), None
    )
    if inst_root:
        root_types["instruction-root"] = inst_root
    if acct_root:
        root_types["account-root"] = acct_root
    root_types["errors"] = errors  # may be None -> explorer treats as absent
    root_types["events"] = events

    if inst_root and variants:
        tag_prim, payload_types, consumed, specs = resolve_instruction_types(
            structs, variants, getattr(args, "discriminator", None)
        )
        # pass-through every struct except the ones folded into the envelope
        types = [struct_to_abi(s) for s in structs if s.name not in consumed]
        types = [build_instruction_envelope(inst_root, tag_prim, specs)] + payload_types + types
        sys.stderr.write(
            f"  instruction root: tag={tag_prim}"
            + (f", stripped discriminator from {len(consumed)} variant(s)\n"
               if consumed else " (separate tag; variants unchanged)\n")
        )
    else:
        types = [struct_to_abi(s) for s in structs]

    abi = {
        "abi": {
            "package": args.package,
            "name": args.display_name or args.package,
            "abi-version": 1,
            "package-version": args.version,
            "description": args.description,
            "imports": [],
            "options": {"program-metadata": {"root-types": root_types}},
        },
        "types": types,
    }
    return abi


# --- minimal deterministic YAML emitter (matches Thru doc style) -----------
def emit_yaml(node, indent=0) -> str:
    pad = "  " * indent
    out = []
    if isinstance(node, dict):
        if not node:
            return "{}"
        lines = []
        for k, v in node.items():
            if isinstance(v, dict) and v:
                lines.append(f"{pad}{k}:")
                lines.append(emit_yaml(v, indent + 1))
            elif isinstance(v, list):
                if not v:
                    lines.append(f"{pad}{k}: []")
                else:
                    lines.append(f"{pad}{k}:")
                    lines.append(emit_yaml(v, indent))
            else:
                lines.append(f"{pad}{k}: {scalar(v)}")
        return "\n".join(lines)
    if isinstance(node, list):
        for item in node:
            if isinstance(item, dict):
                body = emit_yaml(item, indent + 1)
                first, *rest = body.split("\n")
                out.append(f"{pad}- {first.strip()}")
                out.extend(rest)
            else:
                out.append(f"{pad}- {scalar(item)}")
        return "\n".join(out)
    return f"{pad}{scalar(node)}"


def scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        if v == "" or re.search(r"[:#{}\[\],&*?|<>=!%@`\"']", v) or v != v.strip():
            return '"' + v.replace('"', '\\"') + '"'
        return v
    return str(v)


# --- roundtrip check via the real CLI --------------------------------------
def run_check(path: str) -> int:
    try:
        r = subprocess.run(
            ["thru", "abi", "analyze", "--files", path],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        print("! `thru` CLI not found on PATH; skipping analyze check.", file=sys.stderr)
        return 0
    sys.stderr.write(r.stdout + r.stderr)
    return r.returncode


# --- CLI -------------------------------------------------------------------
def parse_variants(spec: Optional[str]):
    """--instructions '0=TnCounterCreateArgs:create,1=TnCounterIncrementArgs:increment'"""
    if not spec:
        return []
    out = []
    for part in spec.split(","):
        tag, _, rest = part.partition("=")
        tname, _, vname = rest.partition(":")
        tname = tname.strip()
        vname = (vname or tname[:1].lower() + tname[1:]).strip()
        out.append((int(tag), tname, vname))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="thru-abi-gen",
        description="Generate a Thru ABI YAML artifact from packed C structs.",
    )
    p.add_argument("header", help="path to the program C header (.h)")
    p.add_argument("-o", "--out", help="write ABI YAML here (default: stdout)")
    p.add_argument("--package", required=True, help="ABI package, e.g. thru.example.counter")
    p.add_argument("--display-name", help="human 'name' field (default: package)")
    p.add_argument("--version", default="1.0.0", help="package-version (default 1.0.0)")
    p.add_argument("--description", default="Generated from C source by thru-abi-gen")
    p.add_argument("--instruction-root", help="name for the discriminated instruction envelope")
    p.add_argument("--instructions", help="tag map: '0=CreateArgs:create,1=IncArgs:increment'")
    p.add_argument("--discriminator", help="name of the leading discriminator field to use "
                                           "as the tag (default: infer the shared first field)")
    p.add_argument("--account-root", help="ABI type name that is the account root")
    p.add_argument("--events", help="ABI type name for emitted events")
    p.add_argument("--errors", help="ABI type name for the error enum")
    p.add_argument("--check", action="store_true", help="run `thru abi analyze` on the output")
    args = p.parse_args(argv)

    with open(args.header, "r", encoding="utf-8") as fh:
        source = fh.read()

    structs, _ = parse_header(source)
    if not structs:
        print("no packed structs found in header", file=sys.stderr)
        return 2

    variants = parse_variants(args.instructions)
    abi = build_abi(structs, args, variants)
    text = emit_yaml(abi) + "\n"

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {args.out}  ({len(structs)} types)", file=sys.stderr)
    else:
        sys.stdout.write(text)

    if args.check:
        target = args.out or "-"
        if target == "-":
            print("! --check needs --out (analyze reads a file)", file=sys.stderr)
            return 1
        return run_check(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
