/*
 * Counter program — adapted verbatim from the Thru "Build a C Program"
 * quickstart (thru.org/docs). Included here so the ABI thru-abi-gen generates
 * can be published and reflected against a program that actually compiles.
 */
#include <stddef.h>
#include <thru-sdk/c/tn_sdk.h>
#include <thru-sdk/c/tn_sdk_syscall.h>
#include "tn_counter_program.h"

static void handle_create_counter(uchar const *instruction_data, ulong instruction_data_sz TSDK_PARAM_UNUSED) {
    tn_counter_create_args_t const *args = (tn_counter_create_args_t const *)instruction_data;

    /* Use account index from instruction arguments (index 0 is the fee payer, index 1 is the program) */
    ushort account_idx = args->account_index;

    /* Get proof data pointer (follows the struct) */
    uchar const *proof_data = NULL;
    if (args->proof_size > 0) {
        proof_data = instruction_data + sizeof(tn_counter_create_args_t);
    }

    /* Create the account using seed and proof from instruction data */
    ulong result = tsys_account_create(account_idx, args->counter_program_seed, proof_data, args->proof_size);
    if (result != TSDK_SUCCESS) {
        tsdk_revert(TN_COUNTER_ERR_ACCOUNT_CREATE_FAILED);
    }

    /* Set account as writable so we can modify its data */
    result = tsys_set_account_data_writable(account_idx);
    if (result != TSDK_SUCCESS) {
        tsdk_revert(TN_COUNTER_ERR_ACCOUNT_SET_WRITABLE_FAILED);
    }

    /* Resize account to hold counter data */
    result = tsys_account_resize(account_idx, sizeof(tn_counter_account_t));
    if (result != TSDK_SUCCESS) {
        tsdk_revert(TN_COUNTER_ERR_ACCOUNT_RESIZE_FAILED);
    }

    /* Get account data pointer and initialize counter */
    void* account_data = tsdk_get_account_data_ptr(account_idx);
    if (account_data == NULL) {
        tsdk_revert(TN_COUNTER_ERR_ACCOUNT_DATA_ACCESS_FAILED);
    }

    tn_counter_account_t* counter_account = (tn_counter_account_t*)account_data;
    counter_account->counter_value = 0UL;

    tsdk_return(TSDK_SUCCESS);
}

static void handle_increment_counter(uchar const *instruction_data, ulong instruction_data_sz TSDK_PARAM_UNUSED) {
    tn_counter_increment_args_t const *args = (tn_counter_increment_args_t const *)instruction_data;

    ushort account_idx = args->account_index;

    /* Get account data pointer */
    void* account_data = tsdk_get_account_data_ptr(account_idx);
    if (account_data == NULL) {
        tsdk_revert(TN_COUNTER_ERR_ACCOUNT_DATA_ACCESS_FAILED);
    }

    /* Set account as writable so we can modify the counter value */
    ulong result = tsys_set_account_data_writable(account_idx);
    if (result != TSDK_SUCCESS) {
        tsdk_revert(TN_COUNTER_ERR_ACCOUNT_SET_WRITABLE_FAILED);
    }

    /* Increment the counter */
    tn_counter_account_t* counter_account = (tn_counter_account_t*)account_data;
    counter_account->counter_value++;

    /* Emit increment event - emit just the counter value */
    tsys_emit_event((uchar const *)&counter_account->counter_value, sizeof(ulong));

    tsdk_return(TSDK_SUCCESS);
}

TSDK_ENTRYPOINT_FN void start(void) {
    tsdk_txn_t const *txn = tsdk_get_txn();
    uchar const *instruction_data = tsdk_txn_get_instr_data(txn);
    ulong instruction_data_sz = tsdk_txn_get_instr_data_sz(txn);

    /* Check minimum size to safely read instruction type */
    if (instruction_data_sz < sizeof(uint)) {
        tsdk_revert(TN_COUNTER_ERR_INVALID_INSTRUCTION_DATA_SIZE);
    }

    uint const *instruction_type = (uint const *)instruction_data;

    switch (*instruction_type) {
        case TN_COUNTER_INSTRUCTION_CREATE:
            if (instruction_data_sz < sizeof(tn_counter_create_args_t)) {
                tsdk_revert(TN_COUNTER_ERR_INVALID_INSTRUCTION_DATA_SIZE);
            }
            tn_counter_create_args_t const *create_args = (tn_counter_create_args_t const *)instruction_data;
            ulong expected_size = sizeof(tn_counter_create_args_t) + create_args->proof_size;

            if (instruction_data_sz != expected_size) {
                tsdk_revert(TN_COUNTER_ERR_INVALID_INSTRUCTION_DATA_SIZE);
            }

            handle_create_counter(instruction_data, instruction_data_sz);
            break;

        case TN_COUNTER_INSTRUCTION_INCREMENT:
            if (instruction_data_sz != sizeof(tn_counter_increment_args_t)) {
                tsdk_revert(TN_COUNTER_ERR_INVALID_INSTRUCTION_DATA_SIZE);
            }
            handle_increment_counter(instruction_data, instruction_data_sz);
            break;

        default:
            tsdk_revert(TN_COUNTER_ERR_INVALID_INSTRUCTION_TYPE);
    }

    /* Should never reach here */
    tsdk_revert(TN_COUNTER_ERR_INVALID_INSTRUCTION_TYPE);
}
