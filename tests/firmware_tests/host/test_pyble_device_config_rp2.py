#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Host tests for the rpi-pico2-w device-config persistence layer
# (F-25 / port spec P1+P5, PART-3 test 7). Sole [red] author:
# firmware-test-author. Production module owner (HAND-OFF for [green]):
# rp2-agent-engineer -> firmware/pyble/pyble_device_config.py (grown from the
# pure scaffold; native twins pble_device_config.c + pble_boot.c).
#
# FROZEN references:
#   ports/rpi-pico2-w.md P5 — /pyble_conf.json on the LFS2 vfs:
#     {"label": str <=24 UTF-8 bytes, "autorun": 0|1}; survives reset.
#   ports/rpi-pico2-w.md P1 — auto_run served from the persisted flag;
#     advertised name label-else-default (FR-BLE-5 twin).
#   protocol.md §4 — 0x23 SET_AUTORUN [enable:u8] (0=off default, 1=on,
#     persisted); 0x50 SET_LABEL (empty clears; becomes the advertised name
#     and DEVICE_INFO.label). §7 — label max 24 UTF-8 bytes else ERANGE;
#     caps carry `label` + `auto_run`. §8 — status codes.
#   C reference invariants transliterated:
#     pble_device_config.c pble_dc_set_label: over-length -> ERANGE, NOT
#       stored; empty clears to default; on OK (and only on OK) the advertised
#       name is re-derived and pushed (pble_ble_set_adv_name).
#     pble_boot.c pble_boot_set_autorun_cmd: payload shorter than 1 byte ->
#       EBADREQ; enable = payload[0] != 0; persisted as a 0/1 flag, default
#       off when the key is absent.
#
# The PURE scaffold surface (PBLE_LABEL_MAX / label_status / adv_name) stays
# covered by the existing host/test_pyble_device_config.py — this suite does
# NOT duplicate it; it pins the rp2 persistence + plumbing layer on top.
#
# ---------------------------------------------------------------------------
# INTERFACE PINNED BY THIS [red] TEST (rp2-agent-engineer implements to it):
#   pyble_device_config.CONF_NAME : str == "pyble_conf.json"
#         # P5: the conf file lives at <fs_root>/pyble_conf.json; the jail's
#         # reserved top-level `pyble` prefix shields it from PBLE/1 clients
#         # (that negative is pinned by the fs suite, not here).
#   pyble_device_config.DeviceConfig(root, device_id, set_adv_name=None)
#         # root:          fs-root directory path (host tests pass a tmpdir;
#         #                on device this is "/").
#         # device_id:     "XXXX" suffix (from machine.unique_id per P1) —
#         #                used only to derive the default advertised name.
#         # set_adv_name:  callable(str) seam to the BLE link (BleLink
#         #                .set_adv_name on device); called ONLY after a
#         #                successful SET_LABEL persist.
#         # Construction loads any existing conf; a missing/corrupt file
#         # yields the frozen defaults (label "", auto_run 0) — never raises.
#     .label    : str  — current persisted label ("" = none)
#     .auto_run : int  — current persisted flag (0 default, 1 on)
#     .conf_path: str  — <root>/pyble_conf.json
#     .set_label(utf8: bytes) -> int §8 status
#         # >24 encoded bytes -> ERANGE, nothing persisted, no adv push.
#         # OK: persists, updates .label, pushes adv_name(device_id, label).
#     .set_autorun(enable: int) -> int §8 status
#         # persists 0/1 (any nonzero input normalizes to 1).
#     .handle_set_label(frame) -> bytes      # Dispatcher handler contract:
#     .handle_set_autorun(frame) -> bytes    # payload[0] = §8 status.
#         # handle_set_autorun: len(payload) < 1 -> EBADREQ (pble_boot.c twin).
# ---------------------------------------------------------------------------

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402
import pyble_proto as proto  # noqa: E402  (frozen scaffold — always importable)

DC = _support.RedReason("pyble_device_config", owner="rp2-agent-engineer")

OK, EBADREQ, ERANGE = 0x00, 0x01, 0x09
LABEL_MAX = 24            # protocol.md §7 freeze (OI-6, UTF-8 encoded bytes)
CONF_NAME = "pyble_conf.json"   # ports/rpi-pico2-w.md P5
OP_SET_LABEL = 0x50       # protocol.md §4 (FROZEN)
OP_SET_AUTORUN = 0x23     # protocol.md §4 (FROZEN, additive §9)


def cmd_frame(opcode, payload, id_=7):
    """A decoded §3.1 CMD frame as the Dispatcher hands it to a handler."""
    return proto.Frame(proto.VER, proto.CMD, opcode, id_, bytes(payload))


class _ConfCase(unittest.TestCase):
    """Shared tmpdir root + a recording set_adv_name seam."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pyble_dc_rp2_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.adv_calls = []

    def make(self, criterion, device_id="9F3A"):
        cls = DC.attr(self, "DeviceConfig", criterion)
        return cls(self.root, device_id, set_adv_name=self.adv_calls.append)

    def conf_path(self):
        return os.path.join(self.root, CONF_NAME)

    def read_conf(self):
        with open(self.conf_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)


class ConfFileContractTest(_ConfCase):
    """P5: the persisted store is <root>/pyble_conf.json with the frozen
    {"label": str, "autorun": 0|1} shape."""

    def test_conf_name_constant_is_frozen(self):
        self.assertEqual(
            DC.attr(self, "CONF_NAME", "P5 conf file name = pyble_conf.json"),
            CONF_NAME,
            "P5 freeze: the persisted store is /pyble_conf.json at the fs root")

    def test_conf_path_joins_root(self):
        cfg = self.make("P5 conf_path = <root>/pyble_conf.json")
        self.assertEqual(cfg.conf_path, self.conf_path(),
                         "conf_path MUST be the P5 path under the given root")

    def test_defaults_without_conf_file(self):
        # A fresh board has no conf file: label empty, autorun OFF (SEC/P5
        # default-off — an unowned board is inert).
        cfg = self.make("P5/P1 defaults: label empty, auto_run 0")
        self.assertEqual(cfg.label, "", "default label is empty (PyBLE-XXXX shows)")
        self.assertEqual(cfg.auto_run, 0, "auto_run MUST default OFF")

    def test_corrupt_conf_falls_back_to_defaults(self):
        # P5 crash-safety twin: a mangled conf file must never take the agent
        # down at boot — defaults win, no exception escapes construction.
        with open(self.conf_path(), "w", encoding="utf-8") as fh:
            fh.write("{not json !!")
        cfg = self.make("P5 corrupt conf -> defaults, never a boot crash")
        self.assertEqual(cfg.label, "")
        self.assertEqual(cfg.auto_run, 0)

    def test_persisted_json_shape_is_frozen(self):
        cfg = self.make("P5 on-disk shape {label, autorun}")
        self.assertEqual(cfg.set_label(b"Bench 2"), OK)
        self.assertEqual(cfg.set_autorun(1), OK)
        data = self.read_conf()
        self.assertEqual(data.get("label"), "Bench 2",
                         'P5: key "label" carries the persisted label string')
        self.assertEqual(data.get("autorun"), 1,
                         'P5: key "autorun" carries the 0|1 flag')


class SetLabelPersistTest(_ConfCase):
    """F-25/P5: SET_LABEL round-trip persists; over-length rejected unstored;
    empty clears; success (and only success) pushes the advertised name."""

    def test_label_round_trip_persists(self):
        cfg = self.make("P5 label round-trip persists to pyble_conf.json")
        self.assertEqual(cfg.set_label(b"Bench 2"), OK)
        self.assertEqual(cfg.label, "Bench 2")
        self.assertTrue(os.path.exists(self.conf_path()),
                        "a successful SET_LABEL MUST write the conf file")
        # A FRESH instance over the same root (a rebooted board) reloads it.
        cfg2 = self.make("P5 label survives reset (fresh load)")
        self.assertEqual(cfg2.label, "Bench 2",
                         "the label MUST survive soft/hard reset via the conf file")

    def test_label_at_limit_is_accepted_and_persisted(self):
        cfg = self.make("§7 label at exactly 24 bytes accepted")
        self.assertEqual(cfg.set_label(b"x" * LABEL_MAX), OK)
        self.assertEqual(self.make("§7 at-limit label reloads").label,
                         "x" * LABEL_MAX)

    def test_over_length_label_erange_and_not_stored(self):
        cfg = self.make("§7 over-length -> ERANGE, NOT stored")
        self.assertEqual(cfg.set_label(b"keep"), OK)
        self.adv_calls[:] = []
        self.assertEqual(cfg.set_label(b"x" * (LABEL_MAX + 1)), ERANGE,
                         "25 encoded bytes MUST be rejected with ERANGE (0x09)")
        self.assertEqual(cfg.label, "keep",
                         "a rejected label MUST NOT replace the stored one")
        self.assertEqual(self.read_conf().get("label"), "keep",
                         "a rejected label MUST NOT touch the persisted store")
        self.assertEqual(self.adv_calls, [],
                         "a failed SET_LABEL MUST NOT push an advertised name")

    def test_bound_is_encoded_bytes_not_codepoints(self):
        cfg = self.make("§7 bound is UTF-8 ENCODED bytes")
        over = "€".encode("utf-8") * 9      # 27 bytes, 9 codepoints
        self.assertGreater(len(over), LABEL_MAX)
        self.assertEqual(cfg.set_label(over), ERANGE,
                         "the 24-byte bound is encoded-byte length, not codepoints")

    def test_empty_label_clears_and_persists_the_clear(self):
        cfg = self.make("§4 SET_LABEL empty clears back to default")
        self.assertEqual(cfg.set_label(b"Bench 2"), OK)
        self.assertEqual(cfg.set_label(b""), OK,
                         "an empty label is the clear case, not an error")
        self.assertEqual(cfg.label, "")
        self.assertEqual(self.make("P5 cleared label survives reset").label, "",
                         "the CLEAR itself MUST persist across reset")


class SetLabelAdvNameTest(_ConfCase):
    """FR-BLE-12 twin: a successful SET_LABEL re-derives and pushes the
    advertised name through the link seam (BleLink.set_adv_name on device)."""

    def test_success_pushes_label_as_adv_name_exactly_once(self):
        cfg = self.make("P1/FR-BLE-12 SET_LABEL OK -> set_adv_name(label)")
        self.assertEqual(cfg.set_label(b"Bench 2"), OK)
        self.assertEqual(self.adv_calls, ["Bench 2"],
                         "success MUST push the new label as the advertised "
                         "name, exactly once")

    def test_clear_pushes_default_pyble_name(self):
        cfg = self.make("P1/FR-BLE-5 clear -> set_adv_name(PyBLE-XXXX)")
        self.assertEqual(cfg.set_label(b"Bench 2"), OK)
        self.adv_calls[:] = []
        self.assertEqual(cfg.set_label(b""), OK)
        self.assertEqual(self.adv_calls, ["PyBLE-9F3A"],
                         "clearing MUST push the PyBLE-XXXX default back out")

    def test_no_seam_is_tolerated(self):
        # The agent may construct the store before the link exists (boot
        # ordering); set_adv_name=None must not break persistence.
        cls = DC.attr(self, "DeviceConfig", "boot ordering: link seam optional")
        cfg = cls(self.root, "9F3A", set_adv_name=None)
        self.assertEqual(cfg.set_label(b"Bench 2"), OK)
        self.assertEqual(cfg.label, "Bench 2")


class SetAutorunTest(_ConfCase):
    """F-25/P5 + §4 0x23: single flag, default OFF, persists; the C twin's
    payload semantics (pble_boot.c) carried over exactly."""

    def test_autorun_defaults_off(self):
        cfg = self.make("§4 SET_AUTORUN default is OFF (0)")
        self.assertEqual(cfg.auto_run, 0, "absent key/file MUST read as 0")

    def test_enable_persists_across_reset(self):
        cfg = self.make("P5 autorun=1 persists")
        self.assertEqual(cfg.set_autorun(1), OK)
        self.assertEqual(cfg.auto_run, 1)
        self.assertEqual(self.make("P5 autorun survives reset").auto_run, 1,
                         "the flag MUST survive soft/hard reset via the conf file")

    def test_disable_persists_back_to_zero(self):
        cfg = self.make("§4 SET_AUTORUN 0 turns it back off, persisted")
        self.assertEqual(cfg.set_autorun(1), OK)
        self.assertEqual(cfg.set_autorun(0), OK)
        self.assertEqual(cfg.auto_run, 0)
        self.assertEqual(self.make("P5 autorun=0 survives reset").auto_run, 0)

    def test_nonzero_enable_normalizes_to_one(self):
        # pble_boot.c twin: enable = payload[0] != 0; the STORED value is the
        # frozen P5 0|1 domain, never the raw byte.
        cfg = self.make("P5 nonzero enable normalizes to 1 in the store")
        self.assertEqual(cfg.set_autorun(5), OK)
        self.assertEqual(cfg.auto_run, 1)
        self.assertEqual(self.read_conf().get("autorun"), 1,
                         'the persisted "autorun" domain is 0|1 (P5), not raw bytes')

    def test_autorun_and_label_do_not_clobber_each_other(self):
        cfg = self.make("P5 one conf file, two keys, no clobber")
        self.assertEqual(cfg.set_label(b"Bench 2"), OK)
        self.assertEqual(cfg.set_autorun(1), OK)
        cfg2 = self.make("P5 both keys reload together")
        self.assertEqual(cfg2.label, "Bench 2",
                         "SET_AUTORUN MUST NOT wipe the persisted label")
        self.assertEqual(cfg2.auto_run, 1,
                         "SET_LABEL/SET_AUTORUN share one conf file")


class HandlerContractTest(_ConfCase):
    """Dispatcher handler contract (handler(frame) -> RSP payload bytes,
    payload[0] = §8 status) for 0x50 SET_LABEL and 0x23 SET_AUTORUN —
    the pble_dc_set_label_cmd / pble_boot_set_autorun_cmd twins."""

    def test_set_label_handler_ok(self):
        cfg = self.make("§4 0x50 handler returns [OK] and persists")
        h = DC.attr(self, "DeviceConfig", "0x50 handler exists").handle_set_label
        rsp = h(cfg, cmd_frame(OP_SET_LABEL, b"Bench 2"))
        self.assertEqual(bytes(rsp)[0], OK)
        self.assertEqual(cfg.label, "Bench 2")
        self.assertEqual(self.adv_calls, ["Bench 2"],
                         "the handler path MUST trigger set_adv_name too")

    def test_set_label_handler_over_length_erange(self):
        cfg = self.make("§4 0x50 handler over-length -> [ERANGE]")
        rsp = cfg.handle_set_label(cmd_frame(OP_SET_LABEL, b"x" * (LABEL_MAX + 1)))
        self.assertEqual(bytes(rsp)[0], ERANGE)
        self.assertFalse(os.path.exists(self.conf_path()),
                         "a rejected label MUST NOT create/write the store")

    def test_set_autorun_handler_enable_u8(self):
        cfg = self.make("§4 0x23 handler [enable:u8] persists the flag")
        rsp = cfg.handle_set_autorun(cmd_frame(OP_SET_AUTORUN, b"\x01"))
        self.assertEqual(bytes(rsp)[0], OK)
        self.assertEqual(cfg.auto_run, 1)

    def test_set_autorun_handler_empty_payload_ebadreq(self):
        # pble_boot.c: "§4 SET_AUTORUN payload = [enable:u8]; anything shorter
        # is malformed."
        cfg = self.make("§4 0x23 empty payload -> [EBADREQ], flag untouched")
        rsp = cfg.handle_set_autorun(cmd_frame(OP_SET_AUTORUN, b""))
        self.assertEqual(bytes(rsp)[0], EBADREQ)
        self.assertEqual(cfg.auto_run, 0, "a malformed CMD MUST NOT flip the flag")


class DeviceInfoPlumbingTest(_ConfCase):
    """P1/§7: DEVICE_INFO (and the caps payload) serves `label` and `auto_run`
    from THIS persisted store — pinned here as the store's read surface that
    pyble_info consumes (pble_info.c reads pble_dc_label +
    pble_boot_autorun_enabled; the rp2 caps serialization itself is pinned by
    test_pyble_info_rp2)."""

    def test_fresh_store_serves_persisted_caps_values(self):
        cfg = self.make("§7 caps label/auto_run come from the persisted store")
        self.assertEqual(cfg.set_label(b"Bench 2"), OK)
        self.assertEqual(cfg.set_autorun(1), OK)
        served = self.make("P1 DEVICE_INFO plumbing: reload serves the truth")
        self.assertEqual(
            (served.label, served.auto_run), ("Bench 2", 1),
            "DEVICE_INFO/caps MUST serve label + auto_run from the persisted "
            "flag (P1), not from in-RAM state that dies at reset")

    def test_adv_name_derivation_stays_single_sourced(self):
        # FR-BLE-5 twin: the store + the pure adv_name derivation agree, so
        # DEVICE_INFO.label and the advertisement can never disagree.
        fn = DC.attr(self, "adv_name", "FR-BLE-5 single-source adv derivation")
        cfg = self.make("P1 store feeds the same adv derivation")
        self.assertEqual(fn("9F3A", cfg.label), "PyBLE-9F3A")
        self.assertEqual(cfg.set_label(b"Bench 2"), OK)
        self.assertEqual(fn("9F3A", cfg.label), "Bench 2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
