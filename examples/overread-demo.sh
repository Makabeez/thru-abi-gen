#!/usr/bin/env bash
#
# overread-demo.sh — reproduce the v0.2 ambiguity bug in 2 seconds.
# Needs only python3 + git (a checkout with the v0.2.0 tag). No Thru CLI, no deploy.
#
#   bash examples/overread-demo.sh
#
# The point: a runtime-sized array's ABI size is an ELEMENT COUNT. When the C
# program sizes that array with a BYTE length and the element is wider than a
# byte, the two differ by sizeof(element). v0.2 emitted such an ABI silently.
# v0.3 refuses it and makes you say which the field means.
#
set -euo pipefail
cd "$(dirname "$0")/.."
GEN=src/thru_abi_gen.py
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# Multi-byte element (uint = 4 bytes) sized by a length field. The @abi:len
# spelling doesn't say whether the field counts elements or bytes.
cat > "$TMP/vec.h" <<'EOF'
#include <thru-sdk/c/tn_sdk.h>
typedef struct __attribute__((packed)) {
    uint instruction_type;
    uint data_len;
    uint values[]; // @abi:len=data_len
} tn_vec_submit_args_t;
EOF

echo "== v0.2: accepts the ambiguous annotation, emits an ABI, says nothing =="
python3 <(git show v0.2.0:"$GEN") "$TMP/vec.h" \
  --package thru.demo.vec --display-name "Vector (v0.2)" \
  --instruction-root VecInstruction --instructions "0=TnVecSubmitArgs:submit" \
  --out "$TMP/v2.yaml" >/dev/null 2>&1
echo "   -> wrote $TMP/v2.yaml   (field-ref size = element COUNT, no warning)"
grep -A5 'name: values' "$TMP/v2.yaml" | sed 's/^/   /'

echo
echo "== v0.3: refuses the same header and names the bug =="
if python3 "$GEN" "$TMP/vec.h" \
     --package thru.demo.vec --instruction-root VecInstruction \
     --instructions "0=TnVecSubmitArgs:submit" --out "$TMP/v3.yaml" 2>"$TMP/err"; then
  echo "   !! expected a refusal, got success"; exit 1
fi
sed 's/^/   /' "$TMP/err"

echo
echo "Fix is to say which the length field means:"
echo "   // @abi:count=data_len   (data_len is a number of elements)"
echo "   // @abi:bytes=data_len   (data_len is a number of bytes)"
