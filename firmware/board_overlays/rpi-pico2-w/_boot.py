# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Firmware-embedded boot for PYBLE_RPI_PICO2_W. This FROZEN _boot.py OVERRIDES
# the upstream rp2 ports/rp2/modules/_boot.py (which only mounts the vfs) so
# the PyBLE agent supervisor starts on every cold boot as part of the IMAGE —
# never a user-deletable vfs file (ADR-0030 keeps the embedded-control-plane
# rule; port spec ports/rpi-pico2-w.md P2).
#
# Single-threaded port model (P2): the supervisor loop OWNS the main thread on
# core0 and replaces the local REPL; core1 stays free for user _thread code.
# No _thread launches here. Opt-in autorun of user code is the agent's
# maybe_autorun contract — cold-boot safe, stoppable over BLE — so this file
# never starts user code itself.
import rp2
import vfs

# Stock LFS2 mount (keep in sync with upstream ports/rp2/modules/_boot.py).
# The flash requires the programming size to be aligned to 256 bytes.
bdev = rp2.Flash()
try:
    fs = vfs.VfsLfs2(bdev, progsize=256)
except:  # noqa: E722 - bare except mirrors upstream (first boot: no fs yet)
    vfs.VfsLfs2.mkfs(bdev, progsize=256)
    fs = vfs.VfsLfs2(bdev, progsize=256)
vfs.mount(fs, "/")
del vfs, bdev, fs

# PyBLE agent auto-start (firmware-embedded, un-deletable). main() is the
# supervisor loop and normally never returns; if the agent is not frozen yet
# (bring-up images) or the supervisor hits a fatal fault, fall through to the
# REPL rather than wedging the board.
try:
    import pyble_agent

    pyble_agent.main()
except Exception:
    pass
