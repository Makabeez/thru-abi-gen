# Deploy to alphanet & capture proof

End-to-end: build the reference program, deploy it, publish the **generated** ABI, run
one on-chain increment, and grab the addresses/signatures for the README proof table.
Fees are currently `0`, so the whole loop is free.

> All commands assume you start in the repo root. `ta…` = account address, `ts…` = tx
> signature. Anything in `<…>` is copied from the previous command's output.

---

## 0. Install the toolchain (once)

```bash
# CLI (needs Node 18+). Alternatively use the .deb from the Thru GitHub releases.
npm i -g thru
thru --help

# RISC-V toolchain + C SDK (installs under ~/.thru/sdk/)
thru dev toolchain install
thru dev sdk install c
```

Verify you can reach alphanet (this is the default RPC, `https://rpc.alphanet.thru.org`):

```bash
thru --json getversion     # prints thru-node version if reachable
```

## 1. Key + funded account (once)

```bash
thru keys generate default
thru account create default
thru faucet withdraw default 1000     # fund it so it can pay for writes
```

## 2. Build the program

```bash
cd examples/counter-program
make
ls build/thruvm/bin/                  # -> tn_counter_program_c.bin
```

## 3. Deploy the program

```bash
thru program create thru_counter ./build/thruvm/bin/tn_counter_program_c.bin
```

Copy the **Program account** from the output and keep the seed handy:

```bash
export PROGRAM=ta...<program id>      # from output ("Program account: ...")
export SEED=thru_counter
# (you can always re-derive: thru program derive-program-account $SEED)
```

## 4. Generate + publish the ABI

Back in the repo root. Generate the ABI from the same header the program was built
from, then publish it **under the same seed** (that seed match is how the explorer
associates program ↔ ABI):

```bash
cd ../..
python3 src/thru_abi_gen.py examples/counter-program/examples/tn_counter_program.h \
  --package thru.example.counter \
  --display-name "Counter Program" \
  --instruction-root CounterInstruction \
  --instructions "0=TnCounterCreateArgs:create,1=TnCounterIncrementArgs:increment" \
  --out examples/counter.abi.yaml --check          # --check runs `thru abi analyze`

thru abi account create $SEED examples/counter.abi.yaml
thru abi account get --include-data ta...<abi account>   # confirm the published artifact
export ABI_ACCT=ta...<abi account>
```

## 5. Exercise it — create + increment (this is the proof tx)

```bash
# 5a. derive the counter PDA
thru program derive-address $PROGRAM count_acc
export PDA=ta...<derived address>

# 5b. state proof for the account you're about to create
thru txn make-state-proof creating $PDA
#   note the Proof Size (e.g. 104) and Proof Data (hex) it prints

# 5c. seed as 32-byte hex
thru program seed-to-hex count_acc
#   e.g. 636f756e745f6163630000000000000000000000000000000000000000000000
```

Build the **create** instruction hex by concatenating, in order:

```
00000000                 # instruction_type = 0 (create), u32 LE
0200                     # account_index = 2 (0=fee payer, 1=program), u16 LE
<seed_hex_32_bytes>      # from 5c
68000000                 # proof_size, u32 LE  (0x68 = 104; use YOUR value from 5b)
<proof_bytes>            # exactly as printed in 5b
```

```bash
# 5d. create the counter
thru txn execute --fee 0 --readwrite-accounts $PDA $PROGRAM <CREATE_HEX>

# 5e. increment (fixed hex: type=1, account_index=2) -> emits the counter event
thru txn execute --fee 0 --readwrite-accounts $PDA $PROGRAM 010000000200
```

Copy the **Signature** from 5e — that increment tx emits the event your ABI decodes.

## 6. Verify reflection

- Explorer: open <https://scan.thru.org>, search the increment signature. The
  instruction and the emitted event should decode with the names from your ABI
  (`CounterInstruction` / `increment` / `counter_value`), not raw bytes.
- Or via Explorer MCP: `get_program_abi { program: $PROGRAM }` then
  `get_transaction { signature: ts... }`.

## 7. Fill the README proof table

```
Program account = $PROGRAM
ABI account     = $ABI_ACCT
Increment tx    = ts...<signature from 5e>
```

---

## Gotchas (from the docs, worth not re-learning the hard way)

- **Seed match:** the ABI account must use the same seed as the program, or explorer
  reflection won't associate them.
- **proof_size bytes:** the `68000000` above is `104` in u32 LE — use whatever
  `make-state-proof` actually returned, not the example value.
- **account_index 2:** index 0 is the fee payer, 1 is the program, so the first
  read/write account is 2.
- **No balance for writes:** if a write fails, `thru faucet withdraw default 1000` and retry.
- **Node 18+** is required for the npm install path.
