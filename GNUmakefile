# Build config for the reference counter program.
BASEDIR:=$(CURDIR)/build

# Location of the installed Thru C SDK (default install path).
THRU_C_SDK_DIR:=$(HOME)/.thru/sdk/c/thru-sdk

# The SDK build normally finds the RISC-V toolchain by walking UP the directory
# tree from the build dir looking for a `.thru/sdk/toolchain` folder. That fails
# when the repo lives outside your home dir (e.g. a WSL checkout on /mnt/c), where
# the walk reaches / and errors with "RISC-V toolchain not found". Pin both roots
# explicitly so the build works from anywhere. Override via the environment if your
# install path differs.
RISCV_TOOLCHAIN_ROOT ?= $(HOME)/.thru/sdk/toolchain
RISCV_SYSROOT        ?= $(HOME)/.thru/sdk/toolchain/picolibc/thruvm
export RISCV_TOOLCHAIN_ROOT
export RISCV_SYSROOT

include $(THRU_C_SDK_DIR)/thru_c_program.mk
