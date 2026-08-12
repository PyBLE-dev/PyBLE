# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Device label + advertised-name derivation + persisted config store.
#
# The ESP32-family release firmware implements this in pble_device_config.c /
# pble_boot.c over NVS. The rpi-pico2-w port (ADR-0030, port spec P1/P5) has
# no NVS: this module persists {"label": str<=24 UTF-8 bytes, "autorun": 0|1}
# to <root>/pyble_conf.json on the LFS2 vfs instead. The pure decisions
# (label bound, advertised-name derivation) are unchanged from the scaffold.
# Runs on MicroPython v1.28 and CPython 3.9+ (host suite).

import json

PBLE_LABEL_MAX = 24            # OI-6 architect freeze (UTF-8 encoded bytes)

OK = 0x00
EBADREQ = 0x01
EIO = 0x05
ERANGE = 0x09

CONF_NAME = "pyble_conf.json"  # port spec P5: lives at <fs_root>/pyble_conf.json


def label_status(utf8):
    """Return the native label-bound decision for encoded UTF-8 bytes."""
    return OK if len(utf8) <= PBLE_LABEL_MAX else ERANGE


def adv_name(device_id, label):
    """Return the display-only advertised name used by the native agent."""
    return label if label else "PyBLE-" + device_id


class DeviceConfig:
    """Persisted device config (P5) + SET_LABEL / SET_AUTORUN handlers.

    `root` is the fs-root directory ("/" on device, a tmpdir on host);
    `device_id` is the "XXXX" suffix from machine.unique_id() (P1);
    `set_adv_name` is the optional BleLink.set_adv_name seam, called only
    after a successful SET_LABEL persist (pble_dc_set_label twin).
    """

    def __init__(self, root, device_id, set_adv_name=None):
        if root.endswith("/"):
            self.conf_path = root + CONF_NAME
        else:
            self.conf_path = root + "/" + CONF_NAME
        self._device_id = device_id
        self._set_adv_name = set_adv_name
        self.label = ""            # frozen defaults: never raise at boot (P5)
        self.auto_run = 0
        try:
            with open(self.conf_path, "r") as fh:
                data = json.load(fh)
            label = data.get("label")
            if isinstance(label, str) and len(label.encode("utf-8")) <= PBLE_LABEL_MAX:
                self.label = label
            if data.get("autorun") == 1:
                self.auto_run = 1
        except Exception:          # missing/corrupt conf -> defaults, no crash
            pass

    def _save(self):
        try:
            with open(self.conf_path, "w") as fh:
                fh.write(json.dumps({"label": self.label, "autorun": self.auto_run}))
            return OK
        except Exception:
            return EIO

    def set_label(self, utf8):
        """SET_LABEL persist: >24 encoded bytes -> ERANGE unstored; empty
        clears to default; on OK (and only OK) push the advertised name."""
        if len(utf8) > PBLE_LABEL_MAX:
            return ERANGE
        try:
            label = bytes(utf8).decode("utf-8")
        except Exception:
            return EBADREQ
        old = self.label
        self.label = label
        st = self._save()
        if st != OK:
            self.label = old       # a failed persist must not lie in RAM
            return st
        if self._set_adv_name is not None:
            self._set_adv_name(adv_name(self._device_id, self.label))
        return OK

    def set_autorun(self, enable):
        """SET_AUTORUN persist: any nonzero normalizes to 1 (pble_boot.c twin)."""
        old = self.auto_run
        self.auto_run = 1 if enable else 0
        st = self._save()
        if st != OK:
            self.auto_run = old
        return st

    # --- Dispatcher handler contract: handler(frame) -> RSP payload bytes ----

    def handle_set_label(self, frame):
        """0x50 SET_LABEL — RSP payload = [status:u8]."""
        return bytes((self.set_label(bytes(frame.payload)),))

    def handle_set_autorun(self, frame):
        """0x23 SET_AUTORUN [enable:u8] — shorter payload is malformed."""
        payload = bytes(frame.payload)
        if len(payload) < 1:
            return bytes((EBADREQ,))
        return bytes((self.set_autorun(payload[0]),))
