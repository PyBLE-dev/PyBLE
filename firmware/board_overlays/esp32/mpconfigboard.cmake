# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Layer-2 board overlay for the classic ESP32 (CON-4). Copied into the pristine
# upstream ports/esp32/boards/PYBLE_ESP32/ at build prep. Chip-agnostic Layer-3
# agent is frozen via manifest.py; per-chip differences live ONLY in this dir.

set(IDF_TARGET esp32)

set(SDKCONFIG_DEFAULTS
    boards/sdkconfig.base
    boards/sdkconfig.ble
    ${CMAKE_CURRENT_LIST_DIR}/sdkconfig.board
)

set(MICROPY_FROZEN_MANIFEST ${CMAKE_CURRENT_LIST_DIR}/manifest.py)
