#!/usr/bin/env python3
"""
Tests for thru-abi-gen dynamic-payload handling.

No test framework, no runtime deps -- run it directly:

    python3 tests/test_dynamic_shapes.py

Covers the three variable-length shapes real programs hit (opaque blob,
repeated struct, text) plus every layout the wire format cannot express.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import thru_abi_gen as g  # noqa: E402

PASS, FAIL = [], []


def build(src):
    structs, _ = g.parse_header(src)
    g.register_types(structs)
    return {s.c_name: g.struct_to_abi(s) for s in structs}


def field(abi_struct, name):
    for f in abi_struct["kind"]["struct"]["fields"]:
        if f["name"] == name:
            return f["field-type"]
    raise KeyError(name)


def check(label, fn):
    try:
        fn()
        PASS.append(label)
    except AssertionError as exc:
        FAIL.append(f"{label}: {exc}")
    except Exception as exc:  # noqa: BLE001
        FAIL.append(f"{label}: unexpected {type(exc).__name__}: {exc}")


def rejects(src, needle):
    """Assert the header is refused, with a message that names the problem."""
    try:
        build(src)
    except ValueError as exc:
        assert needle in str(exc), f"wrong error: {exc}"
        return
    raise AssertionError(f"expected rejection containing {needle!r}, got none")


def assert_eq(got, want):
    assert got == want, f"got {got!r}, want {want!r}"


SIG = """
typedef struct __attribute__((packed)) { uchar r[32]; uchar s[32]; } tn_sig_t;
"""

# --- shape 1: opaque byte blob --------------------------------------------
check("blob: len= on a 1-byte element stays valid (v0.2 back-compat)", lambda: (
    lambda ft: (
        assert_eq(ft["array"]["size"], {"field-ref": {"path": ["proof_size"]}}),
        assert_eq(ft["array"]["element-type"], {"primitive": "u8"}),
    )
)(field(build("""
typedef struct __attribute__((packed)) {
    uint proof_size;
    uchar proof_data[];   // @abi:len=proof_size
} tn_p_t;
""")["tn_p_t"], "proof_data")))


# --- shape 2: repeated struct ---------------------------------------------
check("sig batch: struct elements emit a type-ref, sized by an element count", lambda: (
    lambda ft: (
        assert_eq(ft["array"]["element-type"], {"type-ref": {"name": "TnSig"}}),
        assert_eq(ft["array"]["size"], {"field-ref": {"path": ["sig_count"]}}),
    )
)(field(build(SIG + """
typedef struct __attribute__((packed)) {
    uint sig_count;
    tn_sig_t sigs[];   // @abi:count=sig_count
} tn_batch_t;
""")["tn_batch_t"], "sigs")))

check("fixed struct array also resolves (not just flexible)", lambda: assert_eq(
    field(build(SIG + """
typedef struct __attribute__((packed)) { tn_sig_t sigs[4]; } tn_fixed_t;
""")["tn_fixed_t"], "sigs"),
    {"array": {"size": {"literal": {"u64": 4}},
               "element-type": {"type-ref": {"name": "TnSig"}}}},
))

# --- shape 3: text ---------------------------------------------------------
check("metadata: @abi:text renders as char, not an opaque u8 blob", lambda: assert_eq(
    field(build("""
typedef struct __attribute__((packed)) {
    uint name_len;
    uchar name[];   // @abi:bytes=name_len @abi:text
} tn_meta_t;
""")["tn_meta_t"], "name")["array"]["element-type"],
    {"primitive": "char"},
))

check("text on a multi-byte element is refused", lambda: rejects("""
typedef struct __attribute__((packed)) {
    uint n;
    uint words[];   // @abi:count=n @abi:text
} tn_bad_t;
""", "1-byte element"))

# --- the correctness fix ---------------------------------------------------
check("bare len= on a multi-byte element is refused, not silently over-read", lambda: rejects("""
typedef struct __attribute__((packed)) {
    uint data_bytes;
    uint values[];   // @abi:len=data_bytes
} tn_vec_t;
""", "ambiguous"))

check("bytes= on a multi-byte element is refused (field-ref cannot divide)", lambda: rejects("""
typedef struct __attribute__((packed)) {
    uint data_bytes;
    uint values[];   // @abi:bytes=data_bytes
} tn_vec_t;
""", "cannot divide"))

check("count= on a multi-byte element is accepted verbatim", lambda: assert_eq(
    field(build("""
typedef struct __attribute__((packed)) {
    uint n;
    uint values[];   // @abi:count=n
} tn_vec_t;
""")["tn_vec_t"], "values")["array"]["size"],
    {"field-ref": {"path": ["n"]}},
))

check("bytes= on a 1-byte element is fine (bytes == count)", lambda: assert_eq(
    field(build("""
typedef struct __attribute__((packed)) {
    uint blob_len;
    uchar blob[];   // @abi:bytes=blob_len
} tn_b_t;
""")["tn_b_t"], "blob")["array"]["size"],
    {"field-ref": {"path": ["blob_len"]}},
))

# --- layout guards ---------------------------------------------------------
check("flexible member must be last", lambda: rejects("""
typedef struct __attribute__((packed)) {
    uint n;
    uchar blob[];   // @abi:count=n
    uint trailing;
} tn_bad_t;
""", "must be the last field"))

check("only one flexible member per struct", lambda: rejects("""
typedef struct __attribute__((packed)) {
    uint a; uint b;
    uchar x[];   // @abi:count=a
    uchar y[];   // @abi:count=b
} tn_bad_t;
""", "at most one"))

check("length field must exist", lambda: rejects("""
typedef struct __attribute__((packed)) {
    uint n;
    uchar blob[];   // @abi:count=nope
} tn_bad_t;
""", "not a field"))

check("nested variable-length elements are refused", lambda: rejects("""
typedef struct __attribute__((packed)) {
    uint len;
    uchar body[];   // @abi:count=len
} tn_inner_t;
typedef struct __attribute__((packed)) {
    uint n;
    tn_inner_t items[];   // @abi:count=n
} tn_outer_t;
""", "no fixed size"))

check("unannotated flexible member is still refused", lambda: rejects("""
typedef struct __attribute__((packed)) { uint n; uchar blob[]; } tn_bad_t;
""", "no length field"))

check("unknown type still fails loudly", lambda: rejects("""
typedef struct __attribute__((packed)) { size_t n; } tn_bad_t;
""", "unmapped C type"))

# --- report ----------------------------------------------------------------
for label in PASS:
    print(f"  ok   {label}")
for line in FAIL:
    print(f"  FAIL {line}")
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
