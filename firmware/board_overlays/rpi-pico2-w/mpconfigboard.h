// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Layer-2 board header for the Raspberry Pi Pico 2 W (RP2350 + CYW43439).
// Reuses the upstream RPI_PICO2_W hardware config; PyBLE overrides only the
// board name (no pin/routing profile — hardware is exposed via standard
// MicroPython `machine`).

#include "../RPI_PICO2_W/mpconfigboard.h"

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

#define PBLE_TARGET_ID "rpi-pico2-w"
#undef MICROPY_HW_BOARD_NAME
#define MICROPY_HW_BOARD_NAME "PyBLE v" PBLE_AGENT_VERSION " rpi-pico2-w"
