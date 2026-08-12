# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# pyble_boot — opt-in /main.py auto-run at boot for the rpi-pico2-w portable
# agent (plan C11; C reference twin pble_boot.c pble_boot_maybe_autorun).
#
# The persisted flag lives in the DeviceConfig store (/pyble_conf.json — port
# spec P5, no NVS on rp2); SET_AUTORUN (0x23) is handled by
# pyble_device_config. This module owns only the boot-time decision:
#   flag ON  AND  <fs_root>/main.py exists as a FILE  ->  hand /main.py to the
#   run MAILBOX exactly like a BLE RUN in file mode — NEVER executed inline
#   (FR-BOOT-4 twin), so the supervisor emits RUN_STATE(running) and the
#   program stays STOPpable over BLE (cold-boot safety, firmware.md §5).
#
# EBUSY (the runner already reserved) is ignored — fail-safe, no wedge
# (the C twin ignores pble_runner_run_file's status). A missing /main.py with
# the flag ON stays quietly idle: no spurious RUN_STATE(error).
#
# pyble_agent.main() calls maybe_autorun() LAST, after every handler is
# registered and the link is advertising. Runs on MicroPython v1.28 and
# imports under CPython 3.9+ (host suite).

import os

import pyble_runner

MAIN_PATH = "/main.py"      # the single opt-in auto-run entry at fs_root

_S_IFDIR = 0x4000           # stat st_mode directory bit (POSIX + MicroPython)


def _is_file(path):
    """True iff `path` exists and is a regular file (mp_import_stat FILE
    twin) — a directory named main.py must not be handed to the runner."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    return (st[0] & _S_IFDIR) == 0


def maybe_autorun(config, runner, root="/"):
    """Enqueue <root>/main.py on the run mailbox iff the persisted autorun
    flag is ON and the file exists. Returns True iff the run was reserved;
    EBUSY (or any non-OK reservation) is silently ignored (fail-safe, no
    wedge — pble_boot_maybe_autorun twin)."""
    if not config.auto_run:
        return False                    # opt-out default: advertise-and-wait
    if root != "/" and root.endswith("/"):
        root = root[:-1]
    host = MAIN_PATH if root == "/" else root + MAIN_PATH
    if not _is_file(host):
        return False                    # no /main.py: stay idle, no error
    payload = bytes((pyble_runner.MODE_FILE,)) + host.encode("utf-8")
    return runner.handle_run(payload) == pyble_runner.OK
