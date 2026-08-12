# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Frozen manifest for PYBLE_RPI_PICO2_W (port spec ports/rpi-pico2-w.md P9;
# ADR-0030). LEAN firmware: we deliberately include NEITHER the upstream board
# manifest (bundle-networking / aioble) NOR the port modules dir wholesale —
# only the boot module our _boot.py needs, asyncio, and the PyBLE agent.
# The NeoPixel support claim is withheld until validated on rp2 (OI-P4), so
# no neopixel package is frozen here.

# Essential rp2 boot module: rp2.Flash() backs the LFS2 mount in _boot.py.
module("rp2.py", base_path="$(PORT_DIR)/modules", opt=3)
include("$(MPY_DIR)/extmod/asyncio")

# PyBLE firmware-embedded boot: mounts the vfs, then starts the frozen agent
# supervisor. Overrides upstream ports/rp2/modules/_boot.py; the agent is part
# of the IMAGE, never a user-deletable vfs file.
module("_boot.py", base_path="$(BOARD_DIR)", opt=3)

# The copied-in frozen-Python agent package (prepare.sh lands it in this board
# dir, including the build-generated pyble/_version.py). Keep the complete
# input set literal: release auditing resolves these exact files without
# executing this manifest or recursively trusting future directory contents.
# They remain top-level modules on-device (pyble_proto, pyble_ble, ...), which
# is the import surface used by the portable agent.
freeze(
    "$(BOARD_DIR)/pyble",
    (
        "__init__.py",
        "_version.py",
        "pyble_agent.py",
        "pyble_ble.py",
        "pyble_boot.py",
        "pyble_console.py",
        "pyble_device_config.py",
        "pyble_fs.py",
        "pyble_info.py",
        "pyble_proto.py",
        "pyble_runner.py",
    ),
    opt=3,
)
