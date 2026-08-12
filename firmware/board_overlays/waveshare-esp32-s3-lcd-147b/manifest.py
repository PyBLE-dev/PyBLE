# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
# Exact Waveshare ESP32-S3-LCD-1.47B frozen manifest (ADR-0028).

module("flashbdev.py", base_path="$(PORT_DIR)/modules", opt=3)
module("inisetup.py", base_path="$(PORT_DIR)/modules", opt=3)
include("$(MPY_DIR)/extmod/asyncio")
require("neopixel")

# These two modules belong only to this explicitly selected exact-board image.
module("pyble_st7789.py", base_path="$(BOARD_DIR)", opt=3)
module("pyble_waveshare_lcd147b.py", base_path="$(BOARD_DIR)", opt=3)

module("_boot.py", base_path="$(BOARD_DIR)", opt=3)
module("pyble/__init__.py", base_path="$(BOARD_DIR)", opt=3)
module("pyble/pyble_ble.py", base_path="$(BOARD_DIR)", opt=3)
module("pyble/pyble_proto.py", base_path="$(BOARD_DIR)", opt=3)
