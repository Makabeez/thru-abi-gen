#ifndef TN_COUNTER_PROGRAM_H
#define TN_COUNTER_PROGRAM_H

#include <thru-sdk/c/tn_sdk.h>

/* Error codes */
#define TN_COUNTER_ERR_INVALID_INSTRUCTION_DATA_SIZE (0x1000UL)
#define TN_COUNTER_ERR_INVALID_INSTRUCTION_TYPE      (0x1001UL)
#define TN_COUNTER_ERR_ACCOUNT_CREATE_FAILED         (0x1002UL)
#define TN_COUNTER_ERR_ACCOUNT_SET_WRITABLE_FAILED   (0x1003UL)
#define TN_COUNTER_ERR_ACCOUNT_RESIZE_FAILED         (0x1004UL)
#define TN_COUNTER_ERR_ACCOUNT_DATA_ACCESS_FAILED    (0x1005UL)

/* Instruction types */
#define TN_COUNTER_INSTRUCTION_CREATE    (0U)
#define TN_COUNTER_INSTRUCTION_INCREMENT (1U)

/* Create counter instruction arguments */
typedef struct __attribute__((packed)) {
    uint instruction_type;
    ushort account_index;
    uchar counter_program_seed[TN_SEED_SIZE];
    uint proof_size;
    /* proof_data follows dynamically based on proof_size */
} tn_counter_create_args_t;

/* Increment counter instruction arguments */
typedef struct __attribute__((packed)) {
    uint instruction_type;
    ushort account_index;
} tn_counter_increment_args_t;

// @abi:account-root
/* Counter account data structure */
typedef struct __attribute__((packed)) {
    ulong counter_value;
} tn_counter_account_t;

// @abi:events
/* Emitted on increment: the new counter value */
typedef struct __attribute__((packed)) {
    ulong counter_value;
} tn_counter_event_t;

#endif
