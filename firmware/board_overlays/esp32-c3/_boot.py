# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Firmware-embedded boot. This FROZEN _boot.py OVERRIDES the upstream esp32
# ports/esp32/modules/_boot.py (which only mounts the vfs) so the PyBLE agent
# starts on every cold boot as part of the IMAGE — not a user-deletable /main.py
# (lean/fast/optimized firmware; ADR-0006). Keep the mount below in sync with
# upstream _boot.py.
#
# It mounts the filesystem, then launches the NATIVE agent via
# pble_ble.init_agent(). Silent + non-blocking + guarded, so a fault can never
# wedge the board or the REPL.
import gc
import vfs
from flashbdev import bdev

try:
    if bdev:
        vfs.mount(bdev, "/")
except OSError:
    import inisetup

    inisetup.setup()

# PyBLE native agent auto-start (firmware-embedded, un-deletable).
try:
    import pble_ble

    pble_ble.init_agent()
    # S4 (VM-thread model): run user code on a _thread WORKER so the main task
    # keeps the REPL + banner. Launched once, after the agent is up.
    import _thread
    import pble_runner

    _thread.start_new_thread(pble_runner.worker, ())

    # S5: the filesystem bridge runs its vfs ops on a second MP-stateful worker
    # (mp_vfs_* need a valid VM thread state, off the NimBLE host task).
    import pble_fs

    _thread.start_new_thread(pble_fs.worker, ())

    # S4 F-07: tee the worker's stdout into CONSOLE_DATA via os.dupterm. The
    # native tee stream forwards writes to pble_console_out(), which self-gates to
    # the worker thread, so REPL / UART output is never sent to BLE (observe-
    # anywhere, worker-only). esp32 dupterm requires a native stream, not a class.
    import os
    import pble_console

    os.dupterm(pble_console.stream())

    # S6 F-12: opt-in auto-run of /main.py — no-op unless SET_AUTORUN enabled it.
    # Runs LAST, after advertising + workers are up, and lands on the runner
    # worker, so a broken/looping main.py can never wedge the agent (fail-safe).
    import pble_boot

    pble_boot.maybe_autorun()
except Exception:
    pass

gc.collect()
