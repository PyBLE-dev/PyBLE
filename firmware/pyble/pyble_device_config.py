# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Pure host seam for the native pble_device_config module.
#
# The release firmware implements persistence, advertising updates, and device
# identity in pble_device_config.c. This file mirrors only the deterministic
# decisions that can be unit-tested without NVS, NimBLE, or hardware. Board
# manifests deliberately do not freeze this host twin.

PBLE_LABEL_MAX = 24

OK = 0x00
ERANGE = 0x09


def label_status(utf8):
    """Return the native label-bound decision for encoded UTF-8 bytes."""
    return OK if len(utf8) <= PBLE_LABEL_MAX else ERANGE


def adv_name(device_id, label):
    """Return the display-only advertised name used by the native agent."""
    return label if label else "PyBLE-" + device_id
