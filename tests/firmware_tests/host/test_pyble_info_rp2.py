#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Host tests for the rpi-pico2-w port increment of F-25 `pyble_info`
# (EPIC-PORT-RP2, gate GP1; port spec ports/rpi-pico2-w.md P1). Sole [red]
# author: firmware-test-author. Production module owner (HAND-OFF for [green]):
# identity-engineer -> firmware/pyble/pyble_info.py (plan C7 rewrite).
#
# The caps WIRE is FROZEN (protocol.md §7, serialization frozen 2026-07-02):
# newline-separated ASCII `key=value` with the SHORT key tokens the reference
# agent emits — the native twin pble_info.c is the byte-layout authority. The
# current scaffold emits the WRONG keys (`mpy_version`/`chunk_size`/... instead
# of `mpy`/`chunk`/...) and misses `proto`/`agent`/`mtu`/`window`/`auto_run` —
# this suite pins the §7 tokens exactly. Port-frozen values (P1): chip
# `rpi-pico2-w`, window 4, chunk = mtu − 18 (native twin PBLE_CHUNK_OVERHEAD),
# has_identify 0 (identify_led 255), device_id from machine.unique_id() —
# NEVER from the BLE MAC (BTstack may fall back to a per-boot random static
# address). agent_version single-sources from the build-generated _version.py
# (BLD-12 equivalent) with the C-twin dev fallback.
#
# ---------------------------------------------------------------------------
# INTERFACE PINNED BY THIS [red] TEST (identity-engineer implements to it):
#   pyble_info.device_id_from_unique_id(uid: bytes) -> str
#         # last two unique_id bytes as UPPERCASE zero-padded hex ("9F3A")
#   pyble_info.agent_version() -> str
#         # resolves _version.AGENT_VERSION AT CALL TIME (sys.modules-visible;
#         # the build-generated frozen module is the single source, BLD-12);
#         # falls back to "0.0.0-dev" when _version is absent (dev images)
#   pyble_info.caps_payload(mtu, free_mem, device_id, label, auto_run) -> bytes
#         # THE single §7 caps source: ASCII `key=value\n` lines, token order
#         # per the native twin pble_info.c:
#         #   proto,agent,chip,mpy,fs_root,mtu,window,chunk,free_mem,has_sd,
#         #   has_identify,identify_led,auto_run,device_id,label
#   pyble_info.hello_rsp_payload(...same kwargs...) -> bytes
#         # [status:u8 = OK] + caps_payload (the §7 HELLO RSP payload)
#   pyble_info.device_info_rsp_payload(...same kwargs...) -> bytes
#         # [status:u8 = OK] + the SAME caps bytes (single source)
#   pyble_info.info_char_payload(...same kwargs...) -> bytes
#         # the INFO characteristic Read value == the caps bytes VERBATIM
#         # (no status prefix; §7 INFO-read == DEVICE_INFO payload)
# ---------------------------------------------------------------------------

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

INFO = _support.RedReason("pyble_info", owner="identity-engineer")

# The frozen §7 short-token order, transliterated from the native twin
# pble_info.c (the byte-layout authority; referenced, not redefined).
FROZEN_TOKEN_ORDER = (
    "proto", "agent", "chip", "mpy", "fs_root", "mtu", "window", "chunk",
    "free_mem", "has_sd", "has_identify", "identify_led", "auto_run",
    "device_id", "label",
)

# Deterministic injected values (host tests never read hardware).
CAPS_KWARGS = dict(
    mtu=247, free_mem=131072, device_id="9F3A", label="", auto_run=0)


def parse_caps(testcase, payload, criterion):
    """Split the §7 `key=value\n` text into an ordered list of (key, value)."""
    try:
        text = payload.decode("ascii")
    except (UnicodeDecodeError, AttributeError):
        testcase.fail(
            "[{}] the caps payload must be ASCII bytes (§7 frozen "
            "serialization)".format(criterion))
    testcase.assertTrue(
        text.endswith("\n"),
        "[{}] every caps line is newline-terminated (§7)".format(criterion))
    pairs = []
    for line in text.splitlines():
        testcase.assertIn(
            "=", line,
            "[{}] caps line {!r} must be key=value".format(criterion, line))
        key, _, value = line.partition("=")
        pairs.append((key, value))
    return pairs


class DeviceIdFromUniqueIdTest(unittest.TestCase):
    """P1: device_id derives from machine.unique_id(), never the BLE MAC."""

    CRITERION = "F-25/P1 device_id from machine.unique_id()"

    def test_last_two_bytes_uppercase_hex(self):
        fn = INFO.attr(self, "device_id_from_unique_id", self.CRITERION)
        self.assertEqual(
            "9F3A", fn(bytes.fromhex("0102030405069f3a")),
            "[{}] device_id = last two unique_id bytes, UPPERCASE hex "
            "(the stable flash ID — never ble.config('mac'), which BTstack "
            "may randomize per boot)".format(self.CRITERION))

    def test_zero_padded(self):
        fn = INFO.attr(self, "device_id_from_unique_id", self.CRITERION)
        self.assertEqual(
            "000A", fn(b"\xde\xad\xbe\xef\x00\x00\x00\x0a"),
            "[{}] each byte is zero-padded to two hex digits".format(
                self.CRITERION))


class AgentVersionSourcingTest(unittest.TestCase):
    """BLD-12 twin: agent_version single-sources from generated _version.py."""

    CRITERION = "F-25/P1 agent_version single-sourced from _version.py"

    def tearDown(self):
        sys.modules.pop("_version", None)

    def test_fallback_without_generated_module(self):
        fn = INFO.attr(self, "agent_version", self.CRITERION)
        sys.modules.pop("_version", None)
        self.assertEqual(
            "0.0.0-dev", fn(),
            "[{}] without the build-generated _version.py the agent version "
            "falls back to the native twin's dev default (0.0.0-dev), never "
            "a hardcoded release string".format(self.CRITERION))

    def test_generated_module_wins(self):
        fn = INFO.attr(self, "agent_version", self.CRITERION)
        fake = types.ModuleType("_version")
        fake.AGENT_VERSION = "9.8.7"
        sys.modules["_version"] = fake
        self.assertEqual(
            "9.8.7", fn(),
            "[{}] agent_version() must resolve _version.AGENT_VERSION at "
            "call time — versions.lock [pyble] is the single source, "
            "build-injected (BLD-12)".format(self.CRITERION))


class CapsPayloadTest(unittest.TestCase):
    """P1 + §7: the frozen short-token caps text with port-frozen values."""

    CRITERION = "F-25/P1 frozen §7 caps tokens for rpi-pico2-w"

    def _caps(self, **overrides):
        fn = INFO.attr(self, "caps_payload", self.CRITERION)
        kwargs = dict(CAPS_KWARGS)
        kwargs.update(overrides)
        return parse_caps(self, fn(**kwargs), self.CRITERION)

    def test_token_set_and_order_match_native_twin(self):
        pairs = self._caps()
        self.assertEqual(
            list(FROZEN_TOKEN_ORDER), [k for k, _ in pairs],
            "[{}] caps keys must be the frozen §7 SHORT tokens in the native "
            "twin's emission order — the scaffold's long keys "
            "(mpy_version/chunk_size/...) are the pinned defect".format(
                self.CRITERION))

    def test_port_frozen_values(self):
        caps = dict(self._caps())
        self.assertEqual(
            "rpi-pico2-w", caps["chip"],
            "[{}] chip is the port's frozen §7 open identifier".format(
                self.CRITERION))
        self.assertEqual(
            "1", caps["proto"],
            "[{}] proto is PBLE_PROTO_VERSION decimal (native twin emits "
            "proto=1)".format(self.CRITERION))
        self.assertEqual(
            "/", caps["fs_root"],
            "[{}] fs_root is the workspace-jail root".format(self.CRITERION))
        self.assertEqual(
            "4", caps["window"],
            "[{}] put_window is 4 on this port (P1: initial, raised only on "
            "HIL evidence — NOT the ESP32 value)".format(self.CRITERION))
        self.assertEqual(
            "0", caps["has_sd"],
            "[{}] has_sd is 0".format(self.CRITERION))
        self.assertEqual(
            "0", caps["has_identify"],
            "[{}] has_identify is 0 this increment (IDENTIFY -> "
            "EUNSUPPORTED, spec-legal)".format(self.CRITERION))
        self.assertEqual(
            "255", caps["identify_led"],
            "[{}] identify_led is 255 (= none) while has_identify=0".format(
                self.CRITERION))
        self.assertTrue(
            caps["mpy"],
            "[{}] mpy carries the MicroPython version string "
            "(non-empty)".format(self.CRITERION))
        agent_fn = INFO.attr(self, "agent_version", self.CRITERION)
        self.assertEqual(
            agent_fn(), caps["agent"],
            "[{}] the agent token equals agent_version() — one "
            "source".format(self.CRITERION))

    def test_injected_values_flow_through(self):
        caps = dict(self._caps(mtu=247, free_mem=131072,
                               device_id="9F3A", label="", auto_run=0))
        self.assertEqual("247", caps["mtu"])
        self.assertEqual("131072", caps["free_mem"])
        self.assertEqual("9F3A", caps["device_id"])
        self.assertEqual("", caps["label"])
        self.assertEqual("0", caps["auto_run"])
        caps = dict(self._caps(label="bench-01", auto_run=1))
        self.assertEqual(
            "bench-01", caps["label"],
            "[{}] the persisted label is served verbatim".format(
                self.CRITERION))
        self.assertEqual(
            "1", caps["auto_run"],
            "[{}] auto_run serves the persisted flag".format(self.CRITERION))

    def test_chunk_is_mtu_minus_18(self):
        self.assertEqual(
            "229", dict(self._caps(mtu=247))["chunk"],
            "[{}] chunk = mtu − 18 (PBLE_CHUNK_OVERHEAD twin: one §3.1 file "
            "DATA message per notify packet; mtu−4 was the 11.9 kB download "
            "stall)".format(self.CRITERION))
        self.assertEqual(
            "5", dict(self._caps(mtu=23))["chunk"],
            "[{}] chunk tracks the LIVE negotiated MTU (23 -> 5)".format(
                self.CRITERION))
        self.assertEqual(
            "0", dict(self._caps(mtu=18))["chunk"],
            "[{}] chunk floors at 0, never negative (native twin "
            "guard)".format(self.CRITERION))


class SinglePayloadSourceTest(unittest.TestCase):
    """§7: HELLO RSP, DEVICE_INFO RSP, and the INFO characteristic serve the
    SAME caps bytes from ONE source; RSPs lead with [status:u8]."""

    CRITERION = "F-25/P1/§7 single caps source; [status]-prefixed HELLO"

    def test_hello_rsp_is_status_ok_plus_caps(self):
        hello = INFO.attr(self, "hello_rsp_payload", self.CRITERION)
        caps = INFO.attr(self, "caps_payload", self.CRITERION)
        payload = hello(**CAPS_KWARGS)
        self.assertGreater(
            len(payload), 1,
            "[{}] the HELLO RSP payload carries status + caps".format(
                self.CRITERION))
        self.assertEqual(
            0x00, payload[0],
            "[{}] the HELLO RSP payload LEADS with [status:u8]=OK (§7 "
            "frozen: '[status:u8] followed by this same caps text')".format(
                self.CRITERION))
        self.assertEqual(
            caps(**CAPS_KWARGS), payload[1:],
            "[{}] HELLO RSP caps bytes == caps_payload (single "
            "source)".format(self.CRITERION))

    def test_device_info_rsp_matches_hello(self):
        hello = INFO.attr(self, "hello_rsp_payload", self.CRITERION)
        device_info = INFO.attr(self, "device_info_rsp_payload",
                                self.CRITERION)
        self.assertEqual(
            hello(**CAPS_KWARGS), device_info(**CAPS_KWARGS),
            "[{}] DEVICE_INFO RSP == HELLO RSP byte-identically (one "
            "authoring function feeds both)".format(self.CRITERION))

    def test_info_characteristic_serves_caps_verbatim(self):
        info_char = INFO.attr(self, "info_char_payload", self.CRITERION)
        caps = INFO.attr(self, "caps_payload", self.CRITERION)
        self.assertEqual(
            caps(**CAPS_KWARGS), info_char(**CAPS_KWARGS),
            "[{}] an INFO characteristic READ returns the same DEVICE_INFO "
            "caps payload VERBATIM (§7 frozen; no status prefix on the "
            "characteristic value)".format(self.CRITERION))


if __name__ == "__main__":
    unittest.main(verbosity=2)
