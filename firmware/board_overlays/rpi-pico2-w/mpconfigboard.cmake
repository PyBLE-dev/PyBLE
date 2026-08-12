# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Layer-2 board overlay for the Raspberry Pi Pico 2 W (CON-4 pattern; port
# spec ports/rpi-pico2-w.md P9, ADR-0030). Copied into the pristine upstream
# ports/rp2/boards/PYBLE_RPI_PICO2_W/ at build prep. Reuses the upstream
# RPI_PICO2_W board config wholesale (PICO_BOARD, CYW43 radio, BTstack BLE);
# because MICROPY_BOARD_DIR resolves to THIS directory, the upstream config's
# frozen-manifest line automatically selects our manifest.py.

include(${MICROPY_PORT_DIR}/boards/RPI_PICO2_W/mpconfigboard.cmake)

# The upstream board's pin table — this overlay adds no pins of its own
# (PyBLE exposes hardware via standard MicroPython `machine`, no routing
# profile).
set(MICROPY_BOARD_PINS ${MICROPY_PORT_DIR}/boards/RPI_PICO2_W/pins.csv)
