/*
 * dynamic-shapes.h — the three variable-length payloads real Thru programs hit.
 *
 * Fixed structs cover basic flows; variable length shows up as soon as a program
 * touches proofs, signature batches, or metadata. Those are three *different*
 * decode problems, and the ABI has to say which one it is:
 *
 *   proof blob   -> opaque bytes, length in bytes      // @abi:bytes=
 *   sig batch    -> repeated struct, length in elements // @abi:count=
 *   metadata     -> text, not hex                       // @abi:text
 *
 * Generate:
 *   python3 src/thru_abi_gen.py examples/dynamic-shapes.h \
 *     --package thru.example.attest --display-name "Attestation Registry" \
 *     --instruction-root AttestInstruction \
 *     --instructions "0=TnAttestSubmitArgs:submit,1=TnAttestBatchArgs:batch,2=TnAttestLabelArgs:label" \
 *     --out examples/dynamic-shapes.abi.yaml
 */

#define TN_PUBKEY_SIZE 32

/* A fixed-size element type. Referenced by the batch below, so the ABI needs a
 * real type-ref here — not a flattened byte array. */
typedef struct __attribute__((packed)) {
    uchar signer[TN_PUBKEY_SIZE];
    uchar r[32];
    uchar s[32];
} tn_attestation_t;

/* @abi:account-root */
typedef struct __attribute__((packed)) {
    ulong attestation_count;
    uchar authority[TN_PUBKEY_SIZE];
} tn_attest_account_t;

/* 1. Opaque blob: proof_size counts BYTES, and the element is 1 byte, so bytes
 *    and element count coincide. */
typedef struct __attribute__((packed)) {
    uint  instruction_type;
    uint  proof_size;
    uchar proof_data[];   // @abi:bytes=proof_size
} tn_attest_submit_args_t;

/* 2. Repeated struct: sig_count counts ELEMENTS, each 96 bytes. Writing
 *    `len=` here would over-read by 96x — the tool refuses it. */
typedef struct __attribute__((packed)) {
    uint instruction_type;
    uint sig_count;
    tn_attestation_t signatures[];   // @abi:count=sig_count
} tn_attest_batch_args_t;

/* 3. Metadata: same wire bytes as a u8 array, but tagged so the explorer shows
 *    the label instead of a hex run. */
typedef struct __attribute__((packed)) {
    uint  instruction_type;
    uint  label_len;
    uchar label[];   // @abi:bytes=label_len @abi:text
} tn_attest_label_args_t;
