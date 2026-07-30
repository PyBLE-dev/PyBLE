# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Layer-2 board overlay for the ESP32-C3 (RISC-V) (CON-4). Copied into the
# pristine upstream ports/esp32/boards/PYBLE_ESP32_C3/ at build prep. The C3 is
# the BINDING footprint constraint (NFR-FP-C3) — flash/heap ceilings are frozen
# on HIL and enforced by the size gate. Chip-agnostic Layer-3 agent is frozen via
# manifest.py; per-chip differences live ONLY here.

set(IDF_TARGET esp32c3)

set(SDKCONFIG_DEFAULTS
    boards/sdkconfig.base
    boards/sdkconfig.riscv
    boards/sdkconfig.ble
    ${CMAKE_CURRENT_LIST_DIR}/sdkconfig.board
)

set(MICROPY_FROZEN_MANIFEST ${CMAKE_CURRENT_LIST_DIR}/manifest.py)
