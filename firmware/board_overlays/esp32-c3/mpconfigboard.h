// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Layer-2 board header for the ESP32-C3 (RISC-V, generic board, no pin/routing
// profile). The C3 is the binding footprint target (NFR-FP-C3).

// Agent SemVer for the REPL banner + os.uname().machine — single-sourced from
// versions.lock via the build-generated pble_version.h (BLD-12); the
// __has_include-guarded default keeps dev/editor builds compiling.
#if defined(__has_include)
#if __has_include("pble_version.h")
#include "pble_version.h"
#endif
#endif
#ifndef PBLE_AGENT_VERSION
#define PBLE_AGENT_VERSION "0.0.0-dev"
#endif

#ifdef __cplusplus
extern "C" {
#endif
void pble_vm_epoch_begin(void);
#ifdef __cplusplus
}
#endif
#define MICROPY_PORT_INIT_FUNC pble_vm_epoch_begin()

#define PBLE_TARGET_ID                "esp32-c3"
#define MICROPY_HW_BOARD_NAME       "PyBLE v" PBLE_AGENT_VERSION " esp32-c3"
#define MICROPY_HW_MCU_NAME         "ESP32-C3"
#define MICROPY_HW_ENABLE_UART_REPL (1)
