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
import os

import pyble_proto

PBLE_LABEL_MAX = 24            # OI-6 architect freeze (UTF-8 encoded bytes)

OK = 0x00
EBADREQ = 0x01
EIO = 0x05
ERANGE = 0x09

CONF_NAME = "pyble_conf.json"  # port spec P5: lives at <fs_root>/pyble_conf.json
CONF_TMP_NAME = ".pyble_conf.json.pbltmp"
CONFIG_VERSION = 1
CONFIG_RECORD_MAX = 256

CONFIG_FAULT_NONE = 0
CONFIG_FAULT_CORRUPT = 1

_CRC_PREFIX = b"PBLECFG"


def label_status(utf8):
    """Validate the frozen encoded-length, UTF-8, and control-scalar rules."""
    if len(utf8) > PBLE_LABEL_MAX:
        return ERANGE
    label = pyble_proto.strict_utf8_decode(utf8)
    if label is None:
        return EBADREQ
    for char in label:
        scalar = ord(char)
        if scalar <= 0x1F or 0x7F <= scalar <= 0x9F:
            return EBADREQ
    return OK


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
            self.conf_tmp_path = root + CONF_TMP_NAME
        else:
            self.conf_path = root + "/" + CONF_NAME
            self.conf_tmp_path = root + "/" + CONF_TMP_NAME
        self._device_id = device_id
        self._set_adv_name = set_adv_name
        self.label = ""            # frozen defaults: never raise at boot (P5)
        self.auto_run = 0
        self.config_fault = CONFIG_FAULT_NONE
        self._load()

    @staticmethod
    def _canonical_crc(label, autorun):
        encoded = label.encode("utf-8")
        canonical = (_CRC_PREFIX + bytes((CONFIG_VERSION, autorun, len(encoded)))
                     + encoded)
        return pyble_proto.crc32(canonical) & 0xFFFFFFFF

    @staticmethod
    def _valid_autorun(value):
        return type(value) is int and (value == 0 or value == 1)

    @staticmethod
    def _missing_error(exc):
        code = getattr(exc, "errno", None)
        if code is None and getattr(exc, "args", None):
            code = exc.args[0]
        return code == 2

    @staticmethod
    def _valid_label_text(label):
        if type(label) is not str:
            return False
        try:
            encoded = label.encode("utf-8")
        except Exception:
            return False
        return label_status(encoded) == OK

    def _decode_record(self, data):
        if type(data) is not dict:
            return None
        keys = set(data)
        if keys == {"label", "autorun"}:
            label = data["label"]
            autorun = data["autorun"]
            if self._valid_label_text(label) and self._valid_autorun(autorun):
                return label, autorun
            return None
        if keys != {"version", "label", "autorun", "crc32"}:
            return None
        version = data["version"]
        label = data["label"]
        autorun = data["autorun"]
        crc = data["crc32"]
        if type(version) is not int or version != CONFIG_VERSION:
            return None
        if not self._valid_label_text(label) or not self._valid_autorun(autorun):
            return None
        if type(crc) is not int or crc < 0 or crc > 0xFFFFFFFF:
            return None
        if crc != self._canonical_crc(label, autorun):
            return None
        return label, autorun

    def _remove_temp(self):
        try:
            os.remove(self.conf_tmp_path)
        except Exception:
            pass

    def _load(self):
        try:
            with open(self.conf_path, "rb") as stream:
                encoded = stream.read(CONFIG_RECORD_MAX + 1)
        except OSError as exc:
            if not self._missing_error(exc):
                self.config_fault = CONFIG_FAULT_CORRUPT
            return
        except Exception:
            self.config_fault = CONFIG_FAULT_CORRUPT
            return
        if len(encoded) > CONFIG_RECORD_MAX:
            self.config_fault = CONFIG_FAULT_CORRUPT
            return
        try:
            data = json.loads(encoded.decode("utf-8"))
            loaded = self._decode_record(data)
        except Exception:
            self.config_fault = CONFIG_FAULT_CORRUPT
            return
        if loaded is None:
            self.config_fault = CONFIG_FAULT_CORRUPT
            return
        self.label, self.auto_run = loaded
        self._remove_temp()       # a valid primary wins; cleanup is best-effort

    def _record_bytes(self, label, autorun):
        record = {
            "version": CONFIG_VERSION,
            "label": label,
            "autorun": autorun,
            "crc32": self._canonical_crc(label, autorun),
        }
        return json.dumps(record).encode("utf-8")

    def _save_candidate(self, label, autorun):
        try:
            encoded = self._record_bytes(label, autorun)
        except Exception:
            self.config_fault = CONFIG_FAULT_CORRUPT
            return EIO
        if len(encoded) > CONFIG_RECORD_MAX:
            self.config_fault = CONFIG_FAULT_CORRUPT
            return EIO

        stream = None
        try:
            stream = open(self.conf_tmp_path, "wb")
            written = stream.write(encoded)
            if written != len(encoded):
                raise OSError("short config write")
            stream.flush()
            stream.close()
            stream = None
            os.sync()
            os.rename(self.conf_tmp_path, self.conf_path)
        except Exception:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            self._remove_temp()
            self.config_fault = CONFIG_FAULT_CORRUPT
            return EIO
        return OK

    def set_label(self, utf8):
        """SET_LABEL persist: >24 encoded bytes -> ERANGE unstored; empty
        clears to default; on OK (and only OK) push the advertised name."""
        status = label_status(utf8)
        if status != OK:
            return status
        try:
            label = bytes(utf8).decode("utf-8")
        except Exception:
            return EBADREQ
        st = self._save_candidate(label, self.auto_run)
        if st != OK:
            return st
        self.label = label
        self.config_fault = CONFIG_FAULT_NONE
        if self._set_adv_name is not None:
            self._set_adv_name(adv_name(self._device_id, self.label))
        return OK

    def set_autorun(self, enable):
        """Persist only the exact frozen Boolean integer domain, 0 or 1."""
        if not self._valid_autorun(enable):
            return EBADREQ
        st = self._save_candidate(self.label, enable)
        if st == OK:
            self.auto_run = enable
            self.config_fault = CONFIG_FAULT_NONE
        return st

    # --- Dispatcher handler contract: handler(frame) -> RSP payload bytes ----

    def handle_set_label(self, frame):
        """0x50 SET_LABEL — RSP payload = [status:u8]."""
        return bytes((self.set_label(bytes(frame.payload)),))

    def handle_set_autorun(self, frame):
        """0x23 SET_AUTORUN requires exactly one byte whose value is 0 or 1."""
        payload = bytes(frame.payload)
        if len(payload) != 1 or payload[0] > 1:
            return bytes((EBADREQ,))
        return bytes((self.set_autorun(payload[0]),))
