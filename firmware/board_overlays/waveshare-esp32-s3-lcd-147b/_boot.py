# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
# Exact-board boot wrapper. Generic chip-family images contain no splash path.
import gc
import vfs
from flashbdev import bdev
import pyble_workspace

workspace_ready = False
try:
    if not bdev:
        raise OSError("workspace block device unavailable")
    vfs.mount(pyble_workspace.mount_lfs2(bdev, vfs, progsize=256), "/")
    workspace_ready = True
except Exception:
    print("PyBLE workspace recovery is required; reconnect by USB.")

try:
    if not workspace_ready:
        raise RuntimeError("workspace unavailable")
    import pble_ble

    pble_ble.init_agent()

    _pyble_saved_sys_path = None
    try:
        import sys

        _pyble_saved_sys_path = sys.path[:]
        sys.path[:] = [".frozen"]
        import pyble_waveshare_lcd147b

        pyble_waveshare_lcd147b._maybe_show_boot_splash(pble_ble.wait_ready)
    except Exception:
        pass
    finally:
        if _pyble_saved_sys_path is not None:
            sys.path[:] = _pyble_saved_sys_path
            _pyble_saved_sys_path = None

    import _thread
    import pble_runner

    _thread.start_new_thread(pble_runner.worker, ())

    import pble_fs

    _thread.start_new_thread(pble_fs.worker, ())

    import os
    import pble_console

    os.dupterm(pble_console.stream())

    import pble_boot

    pble_boot.maybe_autorun()

    # Open VM command admission only after every worker and boot-time binding
    # above is complete. A preceding exception intentionally leaves it closed.
    pble_ble.vm_ready()
except Exception:
    pass

gc.collect()
