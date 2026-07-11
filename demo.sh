#!/usr/bin/env bash
# Full cycle in well under 90s: C header -> generated ABI -> structural proof.
# If the `thru` CLI is installed, it also runs the real `thru abi analyze`.
set -euo pipefail
cd "$(dirname "$0")"

HDR=examples/counter-program/examples/tn_counter_program.h
OUT=examples/counter.abi.yaml

echo "▶ 1/3  generating ABI from C source ($HDR)"
python3 src/thru_abi_gen.py "$HDR" \
  --package thru.example.counter \
  --display-name "Counter Program" \
  --description "Explorer-compatible counter ABI (generated from C by thru-abi-gen)" \
  --instruction-root CounterInstruction \
  --instructions "0=TnCounterCreateArgs:create,1=TnCounterIncrementArgs:increment" \
  --out "$OUT"

echo "▶ 2/3  structural check (types + root-types + resolved array sizes)"
python3 - "$OUT" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
rt = d["abi"]["options"]["program-metadata"]["root-types"]
types = {t["name"]: t for t in d["types"]}
names = list(types)
seed = next(f for f in types["CreatePayload"]["kind"]["struct"]["fields"]
            if f["name"]=="counter_program_seed")
tag = types["CounterInstruction"]["kind"]["struct"]["fields"][0]["field-type"]["primitive"]
assert rt["instruction-root"] == "CounterInstruction"
assert rt["account-root"] == "TnCounterAccount"
assert seed["field-type"]["array"]["size"]["literal"]["u64"] == 32
assert tag == "u32"   # discriminator width inferred from instruction_type, not hardcoded u8
print("  types      :", ", ".join(names))
print("  root-types :", {k:v for k,v in rt.items() if v})
print("  seed[]     : u8 x 32  (TN_SEED_SIZE resolved from #define)")
print("  tag        : u32       (inferred from instruction_type; matches real wire)")
print("  OK")
PY

echo "▶ 3/3  real analyze (auto-skipped if the thru CLI is not installed)"
if command -v thru >/dev/null 2>&1; then
  thru abi analyze --files "$OUT"
else
  printf '  (thru CLI not on PATH — run: thru abi analyze --files %s)\n' "$OUT"
fi

echo "✓ done"
