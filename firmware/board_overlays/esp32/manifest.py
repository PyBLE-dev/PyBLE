# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Frozen manifest for the classic ESP32. LEAN firmware (ADR-0006): we deliberately
# do NOT include the port's boards/manifest.py (which freezes networking / mqtt /
# sensor bundles the agent doesn't need). We freeze only the essential esp32 boot
# modules + asyncio + the PyBLE agent, and OVERRIDE _boot.py so the native BLE
# agent auto-starts from the image (un-deletable), not a vfs main.py.

# Essential esp32 boot modules (mount the vfs) — our _boot.py imports these.
module("flashbdev.py", base_path="$(PORT_DIR)/modules", opt=3)
module("inisetup.py", base_path="$(PORT_DIR)/modules", opt=3)
include("$(MPY_DIR)/extmod/asyncio")

# Standard upstream WS2812/NeoPixel user-code driver; pins remain explicit.
require("neopixel")

# PyBLE firmware-embedded boot: mounts the vfs, then launches the NATIVE agent
# (pble_ble.init_agent). Overrides upstream ports/esp32/modules/_boot.py.
module("_boot.py", base_path="$(BOARD_DIR)", opt=3)

# Freeze only the three on-device scaffolds. Pure native-twin host seams live
# beside them in firmware/pyble but are deliberately excluded from the image.
module("pyble/__init__.py", base_path="$(BOARD_DIR)", opt=3)
module("pyble/pyble_ble.py", base_path="$(BOARD_DIR)", opt=3)
module("pyble/pyble_proto.py", base_path="$(BOARD_DIR)", opt=3)
