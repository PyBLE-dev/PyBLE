# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Layer-2 board overlay for the ESP32-S3 (CON-4). Copied into the pristine
# upstream ports/esp32/boards/PYBLE_ESP32_S3/ at build prep. Chip-agnostic
# Layer-3 agent is frozen via manifest.py; per-chip differences live ONLY here.

set(IDF_TARGET esp32s3)

set(SDKCONFIG_DEFAULTS
    boards/sdkconfig.base
    boards/sdkconfig.ble
    boards/sdkconfig.spiram_sx
    boards/sdkconfig.240mhz
    boards/sdkconfig.spiram_oct
    ${CMAKE_CURRENT_LIST_DIR}/sdkconfig.board
)

set(MICROPY_FROZEN_MANIFEST ${CMAKE_CURRENT_LIST_DIR}/manifest.py)
