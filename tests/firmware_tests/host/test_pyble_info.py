#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Host tests for F-03 `pyble_info` (HELLO / DEVICE_INFO / caps) + the
# HELLO-side of F-16 (version negotiation, FR-INFO-5). M1/G1, Sprint S3.
# Sole [red] author: firmware-test-author. Production module owner (HAND-OFF for
# [green]): identity-engineer -> firmware/pyble/pyble_info.py (native twin
# pble_info.c). The C dispatch VER guard half of F-16 lives in
# test_pyble_proto_version_guard.py (owner: protocol-engineer).
#
# =====================================================================
# DoR STATUS — BLOCKED (do NOT commit this file [red] before the freeze):
#   protocol.md §7 (HELLO & capabilities) and §9 (Versioning) are DRAFT
#   (freeze ledger, 2026-07-01). Per the architect DoR, F-03/F-16 are
#   ready:false until §7/§9 freeze as [docs] commits AND are mirrored into
#   firmware specs.md FR-INFO-* / FR-PROTO-7/9/10. Until then this suite is
#   authored-but-gated: it asserts ONLY the FROZEN SEMANTICS (the FR-INFO-3
#   caps FIELD SET + typing, INFO==DEVICE_INFO equivalence, version
#   negotiation LOGIC) via the scaffold's own API — it NEVER hardcodes a
#   DRAFT payload byte. Byte-exact caps/HELLO wire vectors stay in
#   conformance/s3_pending.json until §6/§7/§9 freeze.
# =====================================================================
#
# Frozen references used here:
#   protocol.md §2/§4/§8 (FROZEN); specs.md FR-INFO-1..6 (requirement text
#   frozen), FR-PROTO-10; architect native contract: caps single-source,
#   put_window W=4, proto_version=1, chunk_size=MTU-4.
#
# ---------------------------------------------------------------------------
# INTERFACE PINNED BY THIS [red] TEST (identity-engineer implements to it):
#   pyble_info.PROTO_VERSION : int == 1        # supported PBLE/1 version
#   pyble_info.caps() -> Mapping               # HELLO-reply caps, single source
#   pyble_info.device_info() -> Mapping        # DEVICE_INFO fields (FR-INFO-1)
#   pyble_info.info_read_value() -> bytes      # INFO-char read == DEVICE_INFO
#   pyble_info.device_info_payload() -> bytes  # DEVICE_INFO-equivalent bytes
#   pyble_info.negotiate(offered: list[int]) -> int | None
#         # chosen supported version, or None when the offer is unsatisfiable
# ---------------------------------------------------------------------------

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

INFO = _support.RedReason("pyble_info", owner="identity-engineer")

# FR-INFO-3: the FROZEN caps field set the HELLO reply MUST carry, with the
# frozen type of each field. (Field NAMES + presence are frozen by §7 text +
# FR-INFO-3; the byte SERIALIZATION is §7-DRAFT and is NOT asserted here.)
CAPS_FIELDS = {
    "chip": str,
    "mpy_version": str,
    "fs_root": str,
    "max_file_size": int,
    "put_window": int,
    "chunk_size": int,
    "has_sd": bool,
    "free_mem": int,
    "device_id": str,
    "label": str,
    "has_identify": bool,
    # identify_led is int (GPIO) or None -> checked specially
}
# FR-INFO-1: the minimum DEVICE_INFO field set.
DEVICE_INFO_FIELDS = ("chip", "mpy_version", "free_mem", "fs_root", "mtu",
                      "device_id", "label")


class CapsCompletenessTest(unittest.TestCase):
    """FR-INFO-3: the HELLO caps MUST include every frozen field, correctly
    typed; the identity/identify caps are additive within PBLE/1."""

    def test_caps_contains_every_frozen_field(self):
        caps = INFO.attr(self, "caps", "F-03/FR-INFO-3 caps field set complete")()
        for field in list(CAPS_FIELDS) + ["identify_led"]:
            self.assertIn(field, caps, "caps missing frozen field '%s'" % field)

    def test_caps_fields_are_correctly_typed(self):
        caps = INFO.attr(self, "caps", "F-03/FR-INFO-3 caps field typing")()
        for field, typ in CAPS_FIELDS.items():
            self.assertIsInstance(caps[field], typ,
                                  "caps['%s'] must be %s" % (field, typ.__name__))
        self.assertTrue(caps["identify_led"] is None or isinstance(caps["identify_led"], int),
                        "identify_led must be a GPIO int or None")

    def test_put_window_default_is_8(self):
        # §5 + FR-FS-4/NFR-PERF-2 (frozen 2026-07-04): reference-agent default
        # sliding window W=8 (raised 4->8, no wire change; W lives in caps).
        caps = INFO.attr(self, "caps", "F-03/FR-INFO-3 put_window W default 8")()
        self.assertEqual(caps["put_window"], 8, "default put_window W MUST be 8")


class DeviceInfoTest(unittest.TestCase):
    """FR-INFO-1: DEVICE_INFO reports the minimum field set."""

    def test_device_info_has_minimum_fields(self):
        di = INFO.attr(self, "device_info", "F-03/FR-INFO-1 DEVICE_INFO minimum fields")()
        for field in DEVICE_INFO_FIELDS:
            self.assertIn(field, di, "DEVICE_INFO missing '%s'" % field)


class InfoReadEqualsDeviceInfoTest(unittest.TestCase):
    """FR-INFO-4: an INFO-characteristic read returns a DEVICE_INFO-equivalent
    payload so a client can identify a board BEFORE subscribing. Single source
    of caps (F-03 refactor) => the two payloads are byte-identical."""

    def test_info_read_value_equals_device_info_payload(self):
        read_val = INFO.attr(self, "info_read_value", "F-03/FR-INFO-4 INFO read == DEVICE_INFO")()
        di_payload = INFO.attr(self, "device_info_payload", "F-03/FR-INFO-4 DEVICE_INFO payload")()
        self.assertEqual(bytes(read_val), bytes(di_payload),
                         "INFO-char read MUST be byte-identical to the DEVICE_INFO payload")


class VersionNegotiationTest(unittest.TestCase):
    """FR-INFO-5: reply with a supported proto_version; REFUSE (not silently
    mis-speak) a client whose offered versions cannot be satisfied.
    Architect freeze: PROTO_VERSION = 1 (single supported version)."""

    def test_proto_version_constant_is_1(self):
        self.assertEqual(INFO.attr(self, "PROTO_VERSION", "F-16/FR-PROTO-7 PROTO_VERSION=1"), 1)

    def test_negotiate_picks_supported_version(self):
        negotiate = INFO.attr(self, "negotiate", "F-03/FR-INFO-5 negotiate supported version")
        self.assertEqual(negotiate([1]), 1, "offering v1 MUST negotiate to v1")
        self.assertEqual(negotiate([1, 2, 3]), 1,
                         "MUST choose a version the agent supports (v1) from the offer")

    def test_negotiate_refuses_unsatisfiable_offer(self):
        negotiate = INFO.attr(self, "negotiate", "F-03/FR-INFO-5 refuse unsatisfiable version")
        self.assertIsNone(negotiate([2, 3]),
                          "an offer without v1 MUST be REFUSED (None), never silently mis-spoken")
        self.assertIsNone(negotiate([]), "an empty offer MUST be refused")


class NeverExceedAdvertisedCapsTest(unittest.TestCase):
    """FR-PROTO-10: the agent MUST NOT require/assume a capability it did not
    advertise. Structural guard: caps() is the SINGLE source, so what HELLO
    advertises is exactly what DEVICE_INFO/INFO expose (no hidden features)."""

    def test_caps_is_single_source_stable(self):
        caps_fn = INFO.attr(self, "caps", "F-03/FR-PROTO-10 caps single source")
        self.assertEqual(dict(caps_fn()), dict(caps_fn()),
                         "caps() MUST be a stable single source (advertised == exposed)")

    def test_has_identify_gates_identify_led(self):
        # FR-INFO-3: an Identify action is offered ONLY when has_identify is set;
        # when unset, identify_led MUST be null (S3 ships no identify LED — F-23).
        caps = INFO.attr(self, "caps", "F-03/FR-PROTO-10 has_identify gates identify_led")()
        if not caps["has_identify"]:
            self.assertIsNone(caps["identify_led"],
                              "identify_led MUST be null when has_identify is false")


if __name__ == "__main__":
    unittest.main(verbosity=2)
