<div align="center">

<img src="./assets/banner.svg" alt="thru-abi-gen" width="720"/>

### Generate a **Thru** ABI straight from your program's C structs — so the ABI stops drifting from the source.

[![Built for Thru](https://img.shields.io/badge/built%20for-Thru-3DF5C4?style=for-the-badge)](https://thru.org/docs)
[![Fills the C → ABI gap](https://img.shields.io/badge/fills-C%20%E2%86%92%20ABI%20gap-4EA8FF?style=for-the-badge)](https://thru.org/docs/abi/overview/)
[![License MIT](https://img.shields.io/badge/license-MIT-EAF2FF?style=for-the-badge)](./LICENSE)

![Python](https://img.shields.io/badge/python-3.8%2B-2b5b84)
![Runtime deps](https://img.shields.io/badge/runtime%20deps-0-2b5b84)
![Output](https://img.shields.io/badge/output-ABI%20YAML%20v1-2b5b84)

</div>

> Thru's docs are blunt about it: **"Thru ABIs are handwritten today. They do not
> automatically stay in sync with a program the way macro-generated IDLs do in some
> other ecosystems."** Official `thru abi codegen` only runs *ABI → C/Rust/TS*.
> Nothing runs the other way. `thru-abi-gen` is that missing direction: **C → ABI.**

## Why

Every hand-authored ABI is a second copy of your struct layout that a human has to
keep byte-for-byte identical to the C the program actually compiles. Miss a field
width, forget that `uint` is `u32`, hardcode `32` instead of `TN_SEED_SIZE`, and the
schema still *looks* valid — it just decodes the wrong bytes at the explorer, in
codegen, and in every downstream client. `thru-abi-gen` reads the struct that already
exists and emits the ABI, so the layout has one source of truth.

It is deliberately conservative. It converts the tedious, error-prone part (packed
layout, primitive widths, fixed arrays, `#define` sizes) and scaffolds the
explorer-required metadata. It never invents authorization semantics — per the docs,
an ABI only describes wire format, not the account-access model.

## Architecture

```
  program.h  (typedef struct __attribute__((packed)) { ... })
       │
       ▼
  ┌─────────────────────────────────────────────┐
  │  thru-abi-gen                                │
  │   ├─ #define scan      TN_SEED_SIZE → 32     │
  │   ├─ packed-struct parser (layout-agnostic)  │
  │   ├─ C → ABI primitive map (little-endian)   │
  │   ├─ fixed-array resolver                     │
  │   └─ instruction envelope + root-types        │
  └─────────────────────────────────────────────┘
       │
       ▼
  program.abi.yaml ──▶ thru abi analyze  (roundtrip)
                   ──▶ thru abi codegen   (client types)
                   ──▶ thru abi account create <seed>  (publish)
```

## What it maps

| C type | ABI | C type | ABI |
| --- | --- | --- | --- |
| `uint8_t` / `uchar` | `u8` | `int8_t` | `i8` |
| `uint16_t` / `ushort` | `u16` | `int16_t` / `short` | `i16` |
| `uint32_t` / `uint` | `u32` | `int32_t` / `int` | `i32` |
| `uint64_t` / `ulong` | `u64` | `int64_t` / `long` | `i64` |
| `char` | `char` | `float` / `double` | `f32` / `f64` |
| `T name[N]` / `T name[#define]` | fixed `array` of the mapped element | | |

Unmapped types (`size_t`, unknown typedefs) **fail loudly** rather than guessing a
width — a wrong guess is worse than an error.

## Dynamic payloads

Fixed structs cover basic flows. Variable length shows up as soon as a program
touches **proofs, signature batches, or metadata** — and those are three *different*
decode problems, not one:

| Shape | C | Annotation | Emits |
| --- | --- | --- | --- |
| Opaque blob | `uchar proof_data[];` | `// @abi:bytes=proof_size` | `u8` array, `field-ref` size |
| Repeated struct | `tn_sig_t sigs[];` | `// @abi:count=sig_count` | `type-ref` element, `field-ref` size |
| Text | `uchar label[];` | `// @abi:bytes=label_len` + `// @abi:text` | `char` array — reads as text, not hex |

The distinction that matters is **what the length field counts**. An ABI `field-ref`
size is used verbatim as an *element count*, so a field holding a **byte length** only
works when elements are 1 byte wide. For a 96-byte signature, feeding a byte length
into a `field-ref` over-reads by 96×, and the ABI still *looks* valid — it just
decodes garbage. So the annotation has to say which:

- `@abi:count=f` — `f` holds an element count. Used verbatim.
- `@abi:bytes=f` — `f` holds a byte length. Accepted where elements are 1 byte;
  **refused** otherwise, with a message telling you to store a count instead.
- `@abi:len=f` — historical spelling. Still accepted on 1-byte elements (where the
  two are identical); **refused as ambiguous** on wider ones.

Refused rather than guessed, in the same spirit as unmapped types:

```
error: 'values[]' uses // @abi:len=data_bytes but each element is 4 bytes, so it is
ambiguous whether 'data_bytes' holds an element count or a byte length -- and the two
differ by 4x. Say which: // @abi:count=data_bytes  or  // @abi:bytes=data_bytes.
```

Layouts the wire format cannot express are rejected up front: a flexible member that
isn't last, more than one per struct, a length field that doesn't exist, and nested
variable-length data (a runtime-sized struct used as an array element — it has no
static element size, so ABI v1 can't address it).

Worked example covering all three: [`examples/dynamic-shapes.h`](./examples/dynamic-shapes.h)
→ [`examples/dynamic-shapes.abi.yaml`](./examples/dynamic-shapes.abi.yaml).

## Usage

```bash
python3 src/thru_abi_gen.py program.h \
  --package thru.example.counter \
  --instruction-root CounterInstruction \
  --instructions "0=TnCounterCreateArgs:create,1=TnCounterIncrementArgs:increment" \
  --out program.abi.yaml --check
```

`--check` shells out to the real `thru abi analyze` when the CLI is on PATH.

Point root types either with flags or with inline annotations in the header:

```c
// @abi:account-root
typedef struct __attribute__((packed)) { ulong counter_value; } tn_counter_account_t;
```

| Flag | Purpose |
| --- | --- |
| `--package` | ABI package name (required) |
| `--instruction-root` + `--instructions` | synthesize the single discriminated instruction envelope explorer reflection expects |
| `--account-root` / `--events` / `--errors` | set `program-metadata.root-types` (also settable via `// @abi:` annotations) |
| `--check` | run `thru abi analyze` on the output |

## Flow

1. Start from the packed C header your program already ships.
2. Run `thru-abi-gen` with your root-type mapping.
3. It emits explorer-compatible ABI YAML (`root-types` + one discriminated instruction envelope).
4. `thru abi analyze` / `abi reflect` to prove the bytes roundtrip.
5. `thru abi account create <seed> program.abi.yaml` to publish alongside the program.

## Proof

Run against Thru's own documented counter header, `thru-abi-gen` reproduces the exact
explorer-compatible shape the docs hand-author by hand — `CounterInstruction`
envelope, `TnCounterAccount` root, and `counter_program_seed` correctly resolved to
`u8 × 32` from `TN_SEED_SIZE`:

```bash
bash demo.sh      # full cycle in < 1s
```

### Live on alphanet

The same header compiles to a real program, and the generated ABI publishes and
reflects against it. Reproduce with [`DEPLOY.md`](./DEPLOY.md) (the buildable program
lives in [`examples/counter-program/`](./examples/counter-program/)):

| | |
| --- | --- |
| Program account | [`taLBRGzlvDoOBRPZlwQeMMizFrjWdYNw3Dnauw37N62dbm`](https://scan.thru.org/account/taLBRGzlvDoOBRPZlwQeMMizFrjWdYNw3Dnauw37N62dbm) |
| ABI account | [`taun_rrfX3-S6UXGTserajhnYAgLY-cW5j3I8jyPN8p-wB`](https://scan.thru.org/account/taun_rrfX3-S6UXGTserajhnYAgLY-cW5j3I8jyPN8p-wB) |
| Increment tx (event `0100000000000000` decoded via this ABI's `TnCounterEvent`) | [`ts3NObr…c4QQ60DiDM`](https://scan.thru.org/tx/ts3NObr__SFDZQ6PDR7R5BRySmpTtlJTon3k7mhOs8vO2AK1XYf6r8drA5abKpb-K6Osj5hCMxPTIyctc4QQ60DiDM) |

The generated ABI was validated by Thru's own `thru abi analyze` (no layout or
validation errors), published on-chain, read back byte-identical, and the emitted
increment event decodes against the tool-generated `TnCounterEvent` type. Transaction
fees on alphanet are currently 0, so the full deploy → publish → reflect loop costs
nothing.

## Scope & roadmap

- ✅ packed structs, primitive widths, fixed arrays, `#define` sizes, annotations
- ✅ discriminated instruction root with the tag **width inferred from the program's own leading field** (`instruction_type`), and that field stripped from each payload — so instruction reflection decodes against the real wire bytes, not a hardcoded `u8` tag
- ✅ flexible-array members — runtime `field-ref` sizes, with **element-count vs byte-length disambiguation** so a multi-byte element can't silently over-read
- ✅ struct-typed elements (`type-ref`), fixed and runtime-sized — signature batches and other repeated records
- ✅ `@abi:text` so metadata decodes as text instead of a hex run
- ✅ layout guards: trailing/unique flexible member, length-field existence, nested variable-length rejection
- 🔜 nested `type-ref` across imported packages; `--emit c-check` to diff a compiled struct's `sizeof` against the ABI footprint

## Local dev

```bash
git clone https://github.com/Makabeez/thru-abi-gen
cd thru-abi-gen
bash demo.sh                            # end-to-end against the counter header
python3 tests/test_dynamic_shapes.py    # 15 checks, no test framework needed
```

Zero runtime dependencies (Python stdlib + a hand-rolled deterministic YAML emitter).
`pyyaml` is used only by the demo's structural check.

## Attribution

Built against the public [Thru developer docs](https://thru.org/docs). The counter
header and target ABI shape are taken from Thru's own quickstart and
[Explorer Compatibility](https://thru.org/docs/abi/explorer-compatibility/) guide.
Independent community tool, not affiliated with Unto Labs.

## License

MIT — see [LICENSE](./LICENSE).
