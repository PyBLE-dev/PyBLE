#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Host tests for F-22 `pyble_device_config` (device label + advertised-
# name derivation + bounded NVS label store). M1/G1, Sprint S3. Sole [red]
# author: firmware-test-author. Production module owner (HAND-OFF for [green]):
# identity-engineer -> firmware/pyble/pyble_device_config.py (native twin
# pble_device_config.c).
#
# =====================================================================
# DoR STATUS — BLOCKED (do NOT commit [red] before the freeze):
#   protocol.md §7 (label/device_id carried in caps) is DRAFT, and the OI-6
#   label max-length freeze [docs] mirror (architect froze PBLE_LABEL_MAX=24
#   in the native contract) has not landed in protocol.md §4/§7 + specs.md
#   FR-IDENT-1. Until then this suite asserts ONLY the FROZEN SEMANTICS via the
#   scaffold API: the 24-byte bound (architect freeze), advertised-name
#   derivation (§2 FROZEN, FR-BLE-5/12), empty-clears, over-length -> ERANGE
#   (§8 FROZEN), and never-gates-access (SEC-11/CON-7). It NEVER hardcodes a
#   DRAFT SET_LABEL body byte. NVS persist-across-reboot + scan-list visibility
#   are HIL-only (see gates/g1_s3_check.sh).
# =====================================================================
#
# FROZEN references: protocol.md §2 (advertising: label replaces name, MAC-
# suffix device_id), §4 (0x50 SET_LABEL), §8 (ERANGE 0x09); specs.md FR-BLE-5/12,
# FR-IDENT-1, SEC-10/11, CON-7; architect freeze OI-6 = 24 bytes UTF-8.
#
# ---------------------------------------------------------------------------
# INTERFACE PINNED BY THIS [red] TEST (identity-engineer implements to it):
#   pyble_device_config.PBLE_LABEL_MAX : int == 24   # UTF-8 encoded bytes
#   pyble_device_config.label_status(utf8: bytes) -> int
#         # PURE bound decision: OK(0x00) if len<=MAX (incl. empty=clear),
#         # ERANGE(0x09) if over. The NVS store/clear is layered on top (HIL).
#   pyble_device_config.adv_name(device_id: str, label: str) -> str
#         # SINGLE SOURCE: label if non-empty else "PyBLE-"+device_id
#         # (pyble_ble.advertised_name delegates here — F-22 refactor).
# ---------------------------------------------------------------------------

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

DC = _support.RedReason("pyble_device_config", owner="identity-engineer")

OK, ERANGE = 0x00, 0x09
LABEL_MAX = 24  # OI-6 architect freeze (UTF-8 encoded bytes)


class LabelBoundTest(unittest.TestCase):
    """FR-IDENT-1 / SEC-10 / OI-6: bounded UTF-8 label; over-length -> ERANGE
    and NOT stored; the bound is measured in ENCODED BYTES, not codepoints."""

    def test_frozen_bound_is_24_bytes(self):
        self.assertEqual(DC.attr(self, "PBLE_LABEL_MAX", "F-22/OI-6 label max = 24 bytes"),
                         LABEL_MAX, "OI-6 freeze: max label length is 24 UTF-8 bytes")

    def test_label_at_limit_is_accepted(self):
        fn = DC.attr(self, "label_status", "F-22/FR-IDENT-1 label at limit OK")
        self.assertEqual(fn(b"x" * LABEL_MAX), OK, "exactly MAX bytes MUST be accepted")

    def test_over_length_label_is_erange(self):
        fn = DC.attr(self, "label_status", "F-22/FR-IDENT-1 over-length -> ERANGE")
        self.assertEqual(fn(b"x" * (LABEL_MAX + 1)), ERANGE,
                         "MAX+1 bytes MUST be rejected with ERANGE (0x09), not stored")

    def test_bound_is_bytes_not_codepoints(self):
        # A 3-byte UTF-8 char (e.g. U+20AC EURO) repeated past the byte bound
        # MUST be rejected even though the codepoint count is under MAX.
        fn = DC.attr(self, "label_status", "F-22/SEC-10 bound is ENCODED bytes")
        euro = "€".encode("utf-8")            # 3 bytes each
        self.assertEqual(len(euro), 3)
        over = euro * 9                             # 27 bytes, 9 codepoints
        self.assertGreater(len(over), LABEL_MAX)
        self.assertEqual(fn(over), ERANGE,
                         "the bound MUST be encoded-byte length, not codepoint count")

    def test_empty_label_is_ok_and_clears(self):
        fn = DC.attr(self, "label_status", "F-22/FR-IDENT-1 empty clears to default")
        self.assertEqual(fn(b""), OK, "an empty label is the clear-to-default case, not an error")


class AdvertisedNameTest(unittest.TestCase):
    """FR-BLE-5/12: default advertised name is 'PyBLE-XXXX'; a non-empty label
    REPLACES it pre-connect; clearing restores the default."""

    def test_default_is_pyble_prefixed(self):
        fn = DC.attr(self, "adv_name", "F-22/FR-BLE-5 default 'PyBLE-XXXX'")
        self.assertEqual(fn("9F3A", ""), "PyBLE-9F3A", "empty label -> PyBLE-XXXX default")

    def test_label_replaces_default(self):
        fn = DC.attr(self, "adv_name", "F-22/FR-BLE-12 label replaces advertised name")
        self.assertEqual(fn("9F3A", "Bench 2"), "Bench 2",
                         "a non-empty label REPLACES PyBLE-XXXX in the advertisement")

    def test_clearing_restores_default(self):
        fn = DC.attr(self, "adv_name", "F-22/FR-BLE-12 clearing restores default")
        # set then clear: adv_name is pure, so clearing == empty label again
        self.assertEqual(fn("9F3A", "Bench 2"), "Bench 2")
        self.assertEqual(fn("9F3A", ""), "PyBLE-9F3A",
                         "clearing the label MUST restore PyBLE-XXXX")


class NeverGatesAccessTest(unittest.TestCase):
    """SEC-11 / CON-7: device_id + label are for recognition/display ONLY; the
    module MUST NOT expose any access-gating / authorization API keyed on MAC,
    device_id, or label. Verified as a STRUCTURAL negative (specs.md verify:
    'unit (structure)'). The behavioural 'a command runs regardless of label
    state' is exercised at the dispatcher/HIL level (gates/g1_s3_check.sh)."""

    FORBIDDEN_SUBSTRINGS = ("authoriz", "authenticat", "is_allowed", "is_trusted",
                            "gate_access", "check_access", "grant", "deny", "acl")

    def test_no_access_gating_surface_exists(self):
        mod = DC.obj(self, "F-22/SEC-11 identity NEVER gates access")
        for name in dir(mod):
            low = name.lower()
            for bad in self.FORBIDDEN_SUBSTRINGS:
                self.assertNotIn(
                    bad, low,
                    "SEC-11/CON-7: pyble_device_config exposes '%s' — device_id/label "
                    "MUST NOT gate access or authorize commands" % name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
