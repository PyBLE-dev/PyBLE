#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Host unit tests for F-01 `pyble_ble` (M1/G1, S2) — PURE, BLE-INDEPENDENT
# logic ONLY. Sole [red] author: firmware-test-author. Production module owner
# (HAND-OFF for [green]): ble-transport-engineer -> firmware/pyble/pyble_ble.py.
#
# ENVIRONMENT REALITY (S2): `pyble_ble` runs on MicroPython NimBLE + the board
# MAC and does NOT run on this host; it MUST NOT be faked. Only the module's PURE
# helpers are host-tested here:
#   - PyBLE-XXXX advertised-name derivation from the BLE MAC (FR-BLE-5)
#   - the INFO payload assembly/pass-through hook (FR-BLE-4)
#   - MTU payload sizing (FR-BLE-8)
# host/_fakes/{bluetooth,machine}.py are injected into sys.modules so importing
# these pure helpers does not require the real NimBLE module. The NimBLE
# PERIPHERAL itself (one GATT service, RX Write/WWR, TX Notify, INFO Read, scan-
# filtered advertising, MTU-247 accept, subscribe/notify) is HIL-DEFERRED to the
# classic-ESP32 bench (see gates/g1_check.sh), NEVER a host test.
#
# ---------------------------------------------------------------------------
# INTERFACE PINNED BY THIS [red] TEST (ble-transport-engineer implements to it):
#   pyble_ble.device_id_from_mac(mac: bytes) -> str
#         # last two BLE-MAC bytes as UPPERCASE, zero-padded hex ("9F3A")
#   pyble_ble.advertised_name(device_id: str, label: str = "") -> str
#         # "PyBLE-" + device_id by default; a non-empty label REPLACES it
#   pyble_ble.payload_size(mtu: int) -> int      # MTU-3 (ATT) - 1 (frag hdr)
#   pyble_ble.info_read_value(payload: bytes) -> bytes
#         # INFO characteristic read value == the DEVICE_INFO-equivalent payload,
#         # returned verbatim (no truncation/transform)
# The BleLink peripheral class (start/set_info_payload/set_adv_name/send_message/
# on_message/mtu/on_connect/on_disconnect) is the frozen ble<->proto contract but
# is HIL-verified, not exercised here (it touches NimBLE).
# ---------------------------------------------------------------------------

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

BLE = _support.RedReason("pyble_ble", owner="ble-transport-engineer")


class HostTestabilitySplitTest(unittest.TestCase):
    """S2 env-reality: pyble_ble's PURE helpers must import on the host without
    the real NimBLE `bluetooth` module (guarded/deferred import)."""

    def test_pure_helpers_import_under_cpython(self):
        mod = BLE.obj(self, "F-01 host-testability split (pure helpers import on host)")
        self.assertTrue(hasattr(mod, "device_id_from_mac") or hasattr(mod, "advertised_name"),
                        "pyble_ble must expose PURE, host-importable helpers")


class DeviceIdFromMacTest(unittest.TestCase):
    """FR-BLE-5: name suffix = last two BLE-MAC bytes in UPPERCASE hex."""

    def test_spec_example_9f3a(self):
        fn = BLE.attr(self, "device_id_from_mac", "F-01/FR-BLE-5 PyBLE-XXXX suffix from MAC")
        self.assertEqual(fn(b"\x24\x6f\x28\xab\x9f\x3a"), "9F3A",
                         "spec example: MAC ...9F:3A -> '9F3A'")

    def test_uppercase_and_zero_padded(self):
        fn = BLE.attr(self, "device_id_from_mac", "F-01/FR-BLE-5 uppercase, zero-padded hex")
        self.assertEqual(fn(b"\x00\x11\x22\x33\x0a\xbc"), "0ABC", "lowercase digits -> uppercase")
        self.assertEqual(fn(b"\xde\xad\xbe\xef\x03\x0a"), "030A", "must zero-pad each byte to 2 hex")

    def test_uses_only_the_last_two_bytes(self):
        fn = BLE.attr(self, "device_id_from_mac", "F-01/FR-BLE-5 last two bytes only")
        self.assertEqual(fn(b"\xff\xff\xff\xff\x9f\x3a"), "9F3A",
                         "leading MAC bytes must not affect the suffix")


class AdvertisedNameTest(unittest.TestCase):
    """FR-BLE-5: default advertised name is 'PyBLE-XXXX'.
    FR-BLE-12 (forward, F-22): a non-empty label REPLACES the default name."""

    def test_default_name_is_pyble_prefixed(self):
        fn = BLE.attr(self, "advertised_name", "F-01/FR-BLE-5 default name 'PyBLE-XXXX'")
        self.assertEqual(fn("9F3A"), "PyBLE-9F3A")
        self.assertEqual(fn("9F3A", ""), "PyBLE-9F3A", "empty label keeps the default name")

    def test_nonempty_label_replaces_default(self):
        # FR-BLE-12 name assembly (label-else-default). The label LENGTH BOUND is
        # OI-6 (not frozen at S2) and is enforced upstream in DeviceConfig, not by
        # this pure helper — so only the replacement rule is asserted here.
        fn = BLE.attr(self, "advertised_name", "F-01/FR-BLE-12 label replaces advertised name")
        self.assertEqual(fn("9F3A", "Bench 2"), "Bench 2",
                         "a non-empty label replaces the PyBLE-XXXX default")


class PayloadSizingTest(unittest.TestCase):
    """FR-BLE-8: usable payload = MTU-3 (ATT) minus the 1-byte fragmentation
    header."""

    def test_mtu_247_gives_243(self):
        fn = BLE.attr(self, "payload_size", "F-01/FR-BLE-8 MTU 247 -> 243-byte payload")
        self.assertEqual(fn(247), 243)

    def test_ble_default_mtu_23_gives_19(self):
        fn = BLE.attr(self, "payload_size", "F-01/FR-BLE-8 BLE default MTU 23 -> 19")
        self.assertEqual(fn(23), 19)

    def test_general_rule_mtu_minus_4(self):
        fn = BLE.attr(self, "payload_size", "F-01/FR-BLE-8 payload = MTU-4")
        for mtu in (23, 100, 185, 247):
            self.assertEqual(fn(mtu), mtu - 4, "payload_size(%d) must be MTU-4" % mtu)


class InfoPayloadPassThroughTest(unittest.TestCase):
    """FR-BLE-4: an INFO read returns the DEVICE_INFO-equivalent payload verbatim
    (the pure assembly/pass-through hook — the GATT Read itself is HIL-deferred).
    The DEVICE_INFO payload ENCODING is owned by pyble_info/F-03; this test only
    asserts pyble_ble does not alter the bytes it is handed."""

    def test_info_read_value_is_verbatim(self):
        fn = BLE.attr(self, "info_read_value", "F-01/FR-BLE-4 INFO read == DEVICE_INFO payload")
        for payload in (b"", b"\x00", bytes(range(200))):
            self.assertEqual(bytes(fn(payload)), payload,
                             "INFO read value must be the payload unchanged")


if __name__ == "__main__":
    unittest.main(verbosity=2)
