// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

#if defined(__has_include)
#if __has_include("pble_version.h")
#include "pble_version.h"
#endif
#endif
#ifndef PBLE_AGENT_VERSION
#define PBLE_AGENT_VERSION "0.0.0-dev"
#endif

// Provisioning identity is exact-board; PBLE/1 runtime identity remains chip-level.
#define PBLE_TARGET_ID                   "esp32-s3"
#define PBLE_ENABLE_SPLASH_READINESS     (1)
#define MICROPY_HW_BOARD_NAME            "PyBLE v" PBLE_AGENT_VERSION " Waveshare ESP32-S3-LCD-1.47B"
#define MICROPY_HW_MCU_NAME              "ESP32-S3"
#define MICROPY_HW_ENABLE_UART_REPL      (1)
