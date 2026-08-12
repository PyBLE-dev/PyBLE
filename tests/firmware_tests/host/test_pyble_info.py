#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Host tests for F-03 `pyble_info` (HELLO / DEVICE_INFO / caps) + the
# HELLO-side of F-16 (version negotiation, FR-INFO-5). Originally authored
# [red] M1/G1 Sprint S3 against the pre-freeze scaffold's long-key mapping
# API (caps()/device_info_payload() with mpy_version/chunk_size/...,
# put_window=8).
#
# ALIGNED 2026-08-11 (EPIC-PORT-RP2, plan C7): protocol.md §7's caps
# serialization froze (2026-07-02) on the SHORT key tokens, and
# firmware/pyble/pyble_info.py is now the rpi-pico2-w port's frozen-Python
# module (ADR-0030), governed by ports/rpi-pico2-w.md P1 — so this suite
# asserts the SAME FR-INFO-1/3/4/5 + FR-PROTO-10 criteria through the frozen
# §7 payload interface. The long-key twin behaviour this file used to pin is
# the defect test_pyble_info_rp2.py names; port-frozen values (window=4)
# come from P1, not the ESP32 reference agent (window=8 lives in pble_info.c,
# exercised by its own native-twin path).
#
# ---------------------------------------------------------------------------
# INTERFACE (pinned jointly with test_pyble_info_rp2.py):
#   pyble_info.PROTO_VERSION : int == 1        # supported PBLE/1 version
#   pyble_info.caps_payload(mtu, free_mem, device_id, label, auto_run) -> bytes
#         # THE single §7 caps source (`key=value\n` ASCII, short tokens)
#   pyble_info.device_info_rsp_payload(...) -> bytes   # [status] + caps
#   pyble_info.info_char_payload(...) -> bytes         # caps verbatim
#   pyble_info.negotiate(offered: list[int]) -> int | None
#         # chosen supported version, or None when the offer is unsatisfiable
# ---------------------------------------------------------------------------

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

INFO = _support.RedReason("pyble_info", owner="identity-engineer")

# FR-INFO-3: the frozen caps field set the HELLO reply MUST carry, as the
# frozen §7 short tokens (serialization frozen 2026-07-02).
CAPS_TOKENS = (
    "proto", "agent", "chip", "mpy", "fs_root", "mtu", "window", "chunk",
    "free_mem", "has_sd", "has_identify", "identify_led", "auto_run",
    "device_id", "label",
)
# FR-INFO-1: the minimum DEVICE_INFO field set, in §7 token spelling.
DEVICE_INFO_TOKENS = ("chip", "mpy", "free_mem", "fs_root", "mtu",
                      "device_id", "label")

# Deterministic injected values (host tests never read hardware).
CAPS_KWARGS = dict(
    mtu=247, free_mem=131072, device_id="0000", label="", auto_run=0)


def caps_dict(testcase, criterion, **overrides):
    """Decode the §7 `key=value\n` text into a dict for assertions."""
    fn = INFO.attr(testcase, "caps_payload", criterion)
    kwargs = dict(CAPS_KWARGS)
    kwargs.update(overrides)
    payload = fn(**kwargs)
    pairs = []
    for line in payload.decode("ascii").splitlines():
        key, _, value = line.partition("=")
        pairs.append((key, value))
    return dict(pairs)


class CapsCompletenessTest(unittest.TestCase):
    """FR-INFO-3: the HELLO caps MUST include every frozen field; the
    identity/identify caps are additive within PBLE/1."""

    def test_caps_contains_every_frozen_token(self):
        caps = caps_dict(self, "F-03/FR-INFO-3 caps field set complete")
        for token in CAPS_TOKENS:
            self.assertIn(token, caps,
                          "caps missing frozen §7 token '%s'" % token)

    def test_put_window_is_port_governed(self):
        # §5 + FR-FS-4: the sliding window W lives in caps. The value is
        # PORT-governed: ports/rpi-pico2-w.md P1 freezes W=4 for this module
        # (initial; raised only on HIL evidence — NOT the ESP32 native
        # agent's 8).
        caps = caps_dict(self, "F-03/P1 put_window W port value 4")
        self.assertEqual(caps["window"], "4",
                         "window MUST be the port-frozen P1 value (4)")


class DeviceInfoTest(unittest.TestCase):
    """FR-INFO-1: DEVICE_INFO reports the minimum field set."""

    def test_device_info_has_minimum_fields(self):
        caps = caps_dict(self, "F-03/FR-INFO-1 DEVICE_INFO minimum fields")
        for token in DEVICE_INFO_TOKENS:
            self.assertIn(token, caps, "DEVICE_INFO missing '%s'" % token)


class InfoReadEqualsDeviceInfoTest(unittest.TestCase):
    """FR-INFO-4: an INFO-characteristic read returns a DEVICE_INFO-equivalent
    payload so a client can identify a board BEFORE subscribing. Single source
    of caps => the INFO value equals the DEVICE_INFO caps bytes (the RSP adds
    only the leading [status:u8], §7 frozen)."""

    def test_info_read_value_equals_device_info_caps(self):
        info_char = INFO.attr(self, "info_char_payload",
                              "F-03/FR-INFO-4 INFO read == DEVICE_INFO")
        device_info = INFO.attr(self, "device_info_rsp_payload",
                                "F-03/FR-INFO-4 DEVICE_INFO payload")
        self.assertEqual(
            bytes(info_char(**CAPS_KWARGS)),
            bytes(device_info(**CAPS_KWARGS))[1:],
            "INFO-char read MUST be byte-identical to the DEVICE_INFO caps "
            "(the RSP payload minus its [status:u8] prefix)")


class VersionNegotiationTest(unittest.TestCase):
    """FR-INFO-5: reply with a supported proto_version; REFUSE (not silently
    mis-speak) a client whose offered versions cannot be satisfied.
    Architect freeze: PROTO_VERSION = 1 (single supported version)."""

    def test_proto_version_constant_is_1(self):
        self.assertEqual(INFO.attr(self, "PROTO_VERSION",
                                   "F-16/FR-PROTO-7 PROTO_VERSION=1"), 1)

    def test_negotiate_picks_supported_version(self):
        negotiate = INFO.attr(self, "negotiate",
                              "F-03/FR-INFO-5 negotiate supported version")
        self.assertEqual(negotiate([1]), 1, "offering v1 MUST negotiate to v1")
        self.assertEqual(negotiate([1, 2, 3]), 1,
                         "MUST choose a version the agent supports (v1) "
                         "from the offer")

    def test_negotiate_refuses_unsatisfiable_offer(self):
        negotiate = INFO.attr(self, "negotiate",
                              "F-03/FR-INFO-5 refuse unsatisfiable version")
        self.assertIsNone(negotiate([2, 3]),
                          "an offer without v1 MUST be REFUSED (None), "
                          "never silently mis-spoken")
        self.assertIsNone(negotiate([]), "an empty offer MUST be refused")


class NeverExceedAdvertisedCapsTest(unittest.TestCase):
    """FR-PROTO-10: the agent MUST NOT require/assume a capability it did not
    advertise. Structural guard: caps_payload() is the SINGLE source, so what
    HELLO advertises is exactly what DEVICE_INFO/INFO expose."""

    def test_caps_is_single_source_stable(self):
        fn = INFO.attr(self, "caps_payload",
                       "F-03/FR-PROTO-10 caps single source")
        self.assertEqual(fn(**CAPS_KWARGS), fn(**CAPS_KWARGS),
                         "caps_payload() MUST be a stable single source "
                         "(advertised == exposed)")

    def test_has_identify_gates_identify_led(self):
        # FR-INFO-3: an Identify action is offered ONLY when has_identify is
        # set; when unset, identify_led MUST be 255 (= none, §7 frozen byte).
        caps = caps_dict(
            self, "F-03/FR-PROTO-10 has_identify gates identify_led")
        if caps["has_identify"] == "0":
            self.assertEqual(caps["identify_led"], "255",
                             "identify_led MUST be 255 (none) when "
                             "has_identify is 0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
