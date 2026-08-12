# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Mandatory platform pin for the RP2350: the upstream rp2 CMake loads
# mpconfigvariant.cmake ONLY from MICROPY_BOARD_DIR (this board dir), so the
# upstream RPI_PICO2_W variant file never applies to PYBLE_RPI_PICO2_W —
# without this pin the build would default to rp2040.
set(PICO_PLATFORM "rp2350")
