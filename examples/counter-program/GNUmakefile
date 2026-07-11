# Build config for the reference counter program.
BASEDIR:=$(CURDIR)/build
# Location of the installed Thru C SDK (default install path).
THRU_C_SDK_DIR:=$(HOME)/.thru/sdk/c/thru-sdk

RISCV_TOOLCHAIN_ROOT ?= $(HOME)/.thru/sdk/toolchain
RISCV_SYSROOT        ?= $(HOME)/.thru/sdk/toolchain/picolibc/thruvm
export RISCV_TOOLCHAIN_ROOT
export RISCV_SYSROOT

include $(THRU_C_SDK_DIR)/thru_c_program.mk
