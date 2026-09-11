#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Host tests for the F-16 DISPATCH-side version + capability guard on
# `pyble_proto` (M1/G1, Sprint S3). Sole [red] author: firmware-test-author.
# Production module owner (HAND-OFF for [green]): protocol-engineer ->
# firmware/pyble/pyble_proto.py (native twin pble_proto.c). The HELLO-side of
# F-16 (version negotiation, FR-INFO-5) lives in test_pyble_info.py.
#
# FROZEN references: §3.1 VER=0x01, §3.2 validation precedence, §4 opcode set,
# §8 status set, and §9 refusal policy (amended 2026-09-02). This file NEVER
# redefines the wire; other-version frames use the zlib CRC oracle so each test
# can distinguish the CRC gate from direction and version refusal.
#
# INTERFACE PINNED (protocol-engineer implements to it, already pinned by
# test_pyble_proto.py): pyble_proto.decode / .Dispatcher().on_message.

import os
import sys
import unittest
import zlib  # test-side IEEE CRC-32 ORACLE (not production code)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

PROTO = _support.RedReason("pyble_proto", owner="protocol-engineer")

VER = 0x01
CMD, RSP, EVT = 1, 2, 3
HELLO = 0x01
EBADREQ, EUNSUPPORTED = 0x01, 0x0A


def oracle_frame(ver, type_, opcode, id_, payload):
    """Build a §3.1 frame with a CORRECT IEEE CRC-32 over the given VER, so a
    rejection is attributable to the VER guard rather than a CRC failure."""
    hdr = bytes([ver, type_, opcode, id_]) + len(payload).to_bytes(2, "little") + payload
    return hdr + (zlib.crc32(hdr) & 0xFFFFFFFF).to_bytes(4, "little")


class AcceptOnlyVer0x01Test(unittest.TestCase):
    """FR-PROTO-7: the agent MUST emit/accept ONLY VER=0x01 frames and MUST
    reject other versions per the versioning policy."""

    def test_wellformed_ver2_frame_is_not_dispatched(self):
        disp_cls = PROTO.attr(self, "Dispatcher", "F-16/FR-PROTO-7 reject VER!=0x01")
        d = disp_cls()
        called = {"n": 0}
        d.register(HELLO, lambda fr: called.__setitem__("n", called["n"] + 1) or b"\x00")
        # VER=0x02, otherwise well-formed with a correct CRC.
        d.on_message(oracle_frame(0x02, CMD, HELLO, 1, b""))
        self.assertEqual(called["n"], 0,
                         "a VER!=0x01 frame MUST NOT reach a handler (FR-PROTO-7)")

    def test_ver2_frame_is_refused_not_silently_accepted(self):
        disp_cls = PROTO.attr(self, "Dispatcher", "F-16/FR-PROTO-7 refuse VER!=0x01")
        decode = PROTO.attr(self, "decode", "F-16/FR-PROTO-7 decode")
        d = disp_cls()
        out = d.on_message(oracle_frame(0x02, CMD, HELLO, 1, b""))
        # A safely correlatable, direction-valid VER2 CMD is refused by a v1 RSP
        # that echoes its opcode/ID; it is never accepted or answered OK.
        self.assertIsNotNone(out, "a VER!=0x01 frame MUST be answered, not ignored silently")
        ans = decode(bytes(out))
        self.assertEqual(RSP, ans.type)
        self.assertEqual((HELLO, 1), (ans.opcode, ans.id))
        self.assertNotEqual(ans.payload[0], 0x00,
                            "a VER!=0x01 frame MUST NOT be answered OK")
        self.assertEqual(ans.payload[0], EBADREQ,
                         "per the dispatch guard, VER!=0x01 answers EBADREQ (0x01)")

    def test_ver1_frame_still_dispatches(self):
        # Regression guard: the version check MUST NOT reject valid v1 traffic.
        disp_cls = PROTO.attr(self, "Dispatcher", "F-16/FR-PROTO-7 v1 still accepted")
        d = disp_cls()
        seen = {"n": 0}
        d.register(HELLO, lambda fr: seen.__setitem__("n", seen["n"] + 1) or b"\x00")
        d.on_message(oracle_frame(VER, CMD, HELLO, 1, b""))
        self.assertEqual(seen["n"], 1, "a valid VER=0x01 CMD MUST still dispatch")

    def test_crc_failure_precedes_version_refusal(self):
        disp_cls = PROTO.attr(
            self, "Dispatcher", "v0.6.1 structure -> CRC -> VER precedence")
        decode = PROTO.attr(self, "decode", "v0.6.1 bad VER/bad CRC response")
        msg = oracle_frame(0x02, CMD, HELLO, 2, b"")
        msg = msg[:-1] + bytes((msg[-1] ^ 0x01,))
        out = disp_cls().on_message(msg)
        self.assertIsNotNone(out)
        answer = decode(bytes(out))
        self.assertEqual((EVT, HELLO, 0),
                         (answer.type, answer.opcode, answer.id))
        self.assertEqual(b"\x08", bytes(answer.payload),
                         "bad CRC is ECRC even when VER is also unsupported")

    def test_direction_gate_precedes_version_refusal(self):
        disp_cls = PROTO.attr(
            self, "Dispatcher", "v0.6.1 CRC -> direction -> VER precedence")
        out = disp_cls().on_message(oracle_frame(0x02, RSP, HELLO, 3, b"\x00"))
        self.assertIsNone(
            out,
            "a valid-CRC inbound RSP is silent; unsupported VER cannot turn it "
            "into a response loop")


class UnknownOpcodeEunsupportedTest(unittest.TestCase):
    """FR-PROTO-9: a well-formed request for an unsupported opcode MUST be
    answered EUNSUPPORTED. (Also covered at S2 dispatch scope; re-pinned here as
    the formal F-16 conformance obligation.)"""

    def test_unknown_opcode_answers_eunsupported(self):
        disp_cls = PROTO.attr(self, "Dispatcher", "F-16/FR-PROTO-9 unknown opcode -> EUNSUPPORTED")
        decode = PROTO.attr(self, "decode", "F-16/FR-PROTO-9 decode")
        d = disp_cls()
        unknown = 0x7E  # not in the FROZEN §4 set
        out = d.on_message(oracle_frame(VER, CMD, unknown, 5, b""))
        self.assertIsNotNone(out, "an unknown opcode MUST still produce a RSP")
        rsp = decode(bytes(out))
        self.assertEqual(rsp.type, RSP)
        self.assertEqual(rsp.payload[0], EUNSUPPORTED,
                         "unknown opcode MUST answer EUNSUPPORTED (0x0A)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
