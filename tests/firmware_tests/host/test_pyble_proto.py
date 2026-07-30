#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Host unit + PBLE/1 conformance tests for F-02 `pyble_proto` (M1/G1, S2).
# Sole [red] author: firmware-test-author. Production module owner (HAND-OFF for
# [green]): protocol-engineer -> firmware/pyble/pyble_proto.py.
#
# `pyble_proto` is PURE PYTHON (no `bluetooth`/`machine`) and is therefore FULLY
# host-verifiable under CPython. These tests are RED now because the module does
# not exist yet; each behavioural test fails naming the FR-* acceptance criterion
# it captures (via _support.RedReason), not a bare ImportError.
#
# All wire facts are REFERENCED from protocol.md (FROZEN v1.0):
#   §3.1 frame, §3.2 fragmentation (G0 2026-07-01); §4 opcodes, §8 status (G1
#   2026-07-01). This file NEVER redefines the wire — it asserts the codec
#   matches the frozen bytes. Byte vectors live in the SHARED cross-language
#   corpus host/conformance/corpus.json (the single guard that firmware and the
#   Dart `pble` client agree on bytes).
#
# ---------------------------------------------------------------------------
# INTERFACE PINNED BY THIS [red] TEST (protocol-engineer implements to it):
#   pyble_proto.VER : int == 0x01
#   pyble_proto.OPCODES : dict{name->int}   exact protocol.md §4 set
#   pyble_proto.STATUS  : dict{name->int}   exact protocol.md §8 set
#   pyble_proto.crc32(buf: bytes) -> int    IEEE CRC-32 over the given bytes
#   pyble_proto.encode(type_, opcode, id_, payload) -> bytes   §3.1 frame
#   pyble_proto.decode(msg: bytes) -> Frame  # .ver .type .opcode .id .payload
#   pyble_proto.fragment(msg: bytes, mtu: int) -> list[bytes]  §3.2 split
#   pyble_proto.reassemble(packets: list[bytes]) -> bytes      §3.2 join
#   pyble_proto.Dispatcher():
#       .register(opcode: int, handler) -> None
#       .on_message(msg: bytes) -> bytes | None   # ble->proto inbound entry
#           handler(frame) -> bytes  # returns the RSP PAYLOAD (payload[0]=status)
#           unknown opcode  -> RSP  payload[0]=EUNSUPPORTED, echoes id+opcode
#           CRC failure     -> EVT  id=0, opcode=offending, payload[0]=ECRC
#           malformed frame -> RSP  payload[0]=EBADREQ
# ---------------------------------------------------------------------------

import os
import sys
import unittest
import zlib  # test-side IEEE CRC-32 ORACLE (not production code)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

PROTO = _support.RedReason("pyble_proto", owner="protocol-engineer")

VER = 0x01
CMD, RSP, EVT = 1, 2, 3

# The FROZEN protocol.md §4 opcode set (referenced, not redefined).
FROZEN_OPCODES = {
    "HELLO": 0x01, "DEVICE_INFO": 0x02,
    "FILE_LIST": 0x10, "FILE_STAT": 0x11, "FILE_GET_BEGIN": 0x12,
    "FILE_GET_DATA": 0x13, "FILE_GET_END": 0x14, "FILE_PUT_BEGIN": 0x15,
    "FILE_PUT_DATA": 0x16, "FILE_PUT_END": 0x17, "FILE_DELETE": 0x18,
    "MKDIR": 0x19, "FILE_RENAME": 0x1A,
    "RUN": 0x20, "STOP": 0x21, "SOFT_REBOOT": 0x22,
    "CONSOLE_DATA": 0x30, "CONSOLE_INPUT": 0x31,
    "RUN_STATE": 0x40, "FILE_PUT_ACK": 0x41,
    "SET_LABEL": 0x50, "SET_IDENTIFY_LED": 0x51, "IDENTIFY": 0x52,
}

# The FROZEN protocol.md §8 status set (referenced, not redefined).
FROZEN_STATUS = {
    "OK": 0x00, "EBADREQ": 0x01, "ENOENT": 0x02, "EACCES": 0x03,
    "ENOSPC": 0x04, "EIO": 0x05, "ENOMEM": 0x06, "EBUSY": 0x07,
    "ECRC": 0x08, "ERANGE": 0x09, "EUNSUPPORTED": 0x0A, "EINTERNAL": 0xFF,
}


def oracle_frame(type_, opcode, id_, payload):
    """Build a §3.1 frame with a correct IEEE CRC-32 using zlib as the oracle."""
    hdr = bytes([VER, type_, opcode, id_]) + len(payload).to_bytes(2, "little") + payload
    return hdr + (zlib.crc32(hdr) & 0xFFFFFFFF).to_bytes(4, "little")


class ConstantsTest(unittest.TestCase):
    """FR-PROTO-1: the full v1.0 opcode set; FR-PROTO-6: the full status set."""

    def test_ver_is_0x01(self):
        self.assertEqual(PROTO.attr(self, "VER", "F-02/FR-PROTO-2 VER=0x01"), 0x01)

    def test_full_opcode_set_frozen(self):
        opcodes = PROTO.attr(self, "OPCODES", "F-02/FR-PROTO-1 full v1.0 opcode set")
        self.assertEqual(
            dict(opcodes), FROZEN_OPCODES,
            "OPCODES must equal the FROZEN protocol.md §4 set exactly (numbers included)",
        )

    def test_full_status_set_frozen(self):
        status = PROTO.attr(self, "STATUS", "F-02/FR-PROTO-6 full 1-byte status set")
        self.assertEqual(
            dict(status), FROZEN_STATUS,
            "STATUS must equal the FROZEN protocol.md §8 set exactly, incl. every "
            "error code (EBADREQ..EUNSUPPORTED, EINTERNAL)",
        )


class Crc32Test(unittest.TestCase):
    """FR-PROTO-3: IEEE CRC-32 over VER..PAYLOAD."""

    def test_crc32_matches_ieee_over_corpus_headers(self):
        crc32 = PROTO.attr(self, "crc32", "F-02/FR-PROTO-3 IEEE CRC-32 over VER..PAYLOAD")
        for v in _support.frames():
            frame = _support.hx(v["frame_hex"])
            header = frame[:-4]  # VER..PAYLOAD
            self.assertEqual(
                crc32(header) & 0xFFFFFFFF, v["crc32"],
                "crc32 mismatch for corpus frame '%s'" % v["name"],
            )


class EncodeDecodeConformanceTest(unittest.TestCase):
    """FR-PROTO-2: encode/decode the §3.1 frame byte-for-byte, per opcode/TYPE
    shape, against the shared cross-language corpus (never redefining the wire)."""

    def test_encode_matches_corpus_bytes(self):
        encode = PROTO.attr(self, "encode", "F-02/FR-PROTO-2 §3.1 frame encode")
        for v in _support.frames():
            got = encode(v["type"], v["opcode"], v["id"], _support.hx(v["payload_hex"]))
            self.assertEqual(
                bytes(got), _support.hx(v["frame_hex"]),
                "encode() diverged from corpus bytes for '%s'" % v["name"],
            )

    def test_decode_recovers_all_fields(self):
        decode = PROTO.attr(self, "decode", "F-02/FR-PROTO-2 §3.1 frame decode")
        for v in _support.frames():
            fr = decode(_support.hx(v["frame_hex"]))
            self.assertEqual(fr.ver, VER, "ver for '%s'" % v["name"])
            self.assertEqual(fr.type, v["type"], "type for '%s'" % v["name"])
            self.assertEqual(fr.opcode, v["opcode"], "opcode for '%s'" % v["name"])
            self.assertEqual(fr.id, v["id"], "id for '%s'" % v["name"])
            self.assertEqual(
                bytes(fr.payload), _support.hx(v["payload_hex"]),
                "payload for '%s'" % v["name"],
            )

    def test_encode_decode_round_trip(self):
        encode = PROTO.attr(self, "encode", "F-02/FR-PROTO-2 encode")
        decode = PROTO.attr(self, "decode", "F-02/FR-PROTO-2 decode")
        for v in _support.frames():
            pl = _support.hx(v["payload_hex"])
            fr = decode(encode(v["type"], v["opcode"], v["id"], pl))
            self.assertEqual(bytes(fr.payload), pl, "round-trip payload '%s'" % v["name"])


class IdCorrelationTest(unittest.TestCase):
    """FR-PROTO-4: RSP echoes the CMD's 1-byte ID; EVT uses ID=0."""

    def test_rsp_echoes_cmd_id_and_opcode(self):
        disp_cls = PROTO.attr(self, "Dispatcher", "F-02/FR-PROTO-4 ID correlation")
        decode = PROTO.attr(self, "decode", "F-02/FR-PROTO-4 decode")
        d = disp_cls()
        d.register(FROZEN_OPCODES["HELLO"], lambda frame: bytes([FROZEN_STATUS["OK"]]))
        # HELLO CMD with id=1 (from corpus)
        out = d.on_message(oracle_frame(CMD, FROZEN_OPCODES["HELLO"], 1, b""))
        self.assertIsNotNone(out, "a CMD must produce a matching RSP")
        rsp = decode(bytes(out))
        self.assertEqual(rsp.type, RSP, "response TYPE must be RSP")
        self.assertEqual(rsp.id, 1, "RSP must echo the CMD's ID")
        self.assertEqual(rsp.opcode, FROZEN_OPCODES["HELLO"], "RSP echoes the CMD opcode")

    def test_events_use_id_zero(self):
        # EVT corpus frames all carry id==0; assert decode confirms it.
        decode = PROTO.attr(self, "decode", "F-02/FR-PROTO-4 EVT ID=0")
        evt = [v for v in _support.frames() if v["type"] == EVT]
        self.assertTrue(evt, "corpus must contain EVT frames")
        for v in evt:
            self.assertEqual(decode(_support.hx(v["frame_hex"])).id, 0,
                             "EVT '%s' must use ID=0" % v["name"])


class DispatchTest(unittest.TestCase):
    """FR-PROTO-5: each decoded CMD dispatches to its handler by OPCODE."""

    def test_registered_handler_receives_the_frame(self):
        disp_cls = PROTO.attr(self, "Dispatcher", "F-02/FR-PROTO-5 opcode dispatch")
        d = disp_cls()
        seen = {}

        def handler(frame):
            seen["opcode"] = frame.opcode
            seen["id"] = frame.id
            return bytes([FROZEN_STATUS["OK"]])

        d.register(FROZEN_OPCODES["DEVICE_INFO"], handler)
        d.on_message(oracle_frame(CMD, FROZEN_OPCODES["DEVICE_INFO"], 7, b""))
        self.assertEqual(seen.get("opcode"), FROZEN_OPCODES["DEVICE_INFO"],
                         "DEVICE_INFO CMD must route to its registered handler")
        self.assertEqual(seen.get("id"), 7)

    def test_unknown_opcode_answers_eunsupported(self):
        # FR-PROTO-9 (formally F-16/S3) — authored here per S2 dispatch scope.
        disp_cls = PROTO.attr(self, "Dispatcher", "F-02/FR-PROTO-9 unknown opcode -> EUNSUPPORTED")
        decode = PROTO.attr(self, "decode", "F-02/FR-PROTO-9 decode")
        d = disp_cls()
        unknown = 0x7E  # not in the FROZEN §4 set
        self.assertNotIn(unknown, FROZEN_OPCODES.values())
        out = d.on_message(oracle_frame(CMD, unknown, 5, b""))
        self.assertIsNotNone(out, "unknown opcode must still produce a RSP")
        rsp = decode(bytes(out))
        self.assertEqual(rsp.type, RSP)
        self.assertEqual(rsp.payload[0], FROZEN_STATUS["EUNSUPPORTED"],
                         "unknown opcode must answer EUNSUPPORTED (0x0A)")


class ErrorHandlingTest(unittest.TestCase):
    """FR-PROTO-3: CRC fail -> drop + EVT ERROR(ECRC) ref opcode.
    FR-PROTO-8: malformed -> EBADREQ."""

    def test_crc_failure_yields_ecrc_event_referencing_opcode(self):
        disp_cls = PROTO.attr(self, "Dispatcher", "F-02/FR-PROTO-3 CRC fail -> EVT ERROR(ECRC)")
        decode = PROTO.attr(self, "decode", "F-02/FR-PROTO-3 decode")
        v = _support.crc_reject_frames()[0]  # corrupt-CRC HELLO, opcode 0x01
        d = disp_cls()
        d.register(FROZEN_OPCODES["HELLO"], lambda frame: bytes([FROZEN_STATUS["OK"]]))
        out = d.on_message(_support.hx(v["frame_hex"]))
        self.assertIsNotNone(out, "a CRC-failed frame must be answered with EVT ERROR(ECRC)")
        evt = decode(bytes(out))
        self.assertEqual(evt.type, EVT, "CRC-fail answer must be an EVT")
        self.assertEqual(evt.id, 0, "EVT uses ID=0")
        self.assertEqual(evt.payload[0], FROZEN_STATUS["ECRC"], "status must be ECRC (0x08)")
        self.assertEqual(evt.opcode, v["opcode"],
                         "EVT ERROR must reference the offending opcode when known")

    def test_crc_failed_frame_is_not_dispatched(self):
        disp_cls = PROTO.attr(self, "Dispatcher", "F-02/FR-PROTO-3 CRC fail drops the frame")
        d = disp_cls()
        called = {"n": 0}
        d.register(FROZEN_OPCODES["HELLO"], lambda frame: called.__setitem__("n", called["n"] + 1) or b"\x00")
        d.on_message(_support.hx(_support.crc_reject_frames()[0]["frame_hex"]))
        self.assertEqual(called["n"], 0, "a CRC-failed frame must be dropped, not dispatched")

    def test_malformed_short_frame_answers_ebadreq(self):
        disp_cls = PROTO.attr(self, "Dispatcher", "F-02/FR-PROTO-8 malformed -> EBADREQ")
        decode = PROTO.attr(self, "decode", "F-02/FR-PROTO-8 decode")
        d = disp_cls()
        out = d.on_message(b"\x01\x01\x01")  # far too short for a §3.1 header
        self.assertIsNotNone(out, "a malformed frame must be answered")
        rsp = decode(bytes(out))
        self.assertEqual(rsp.type, RSP)
        self.assertEqual(rsp.payload[0], FROZEN_STATUS["EBADREQ"],
                         "structurally-invalid input must answer EBADREQ (0x01)")

    def test_malformed_len_mismatch_answers_ebadreq(self):
        disp_cls = PROTO.attr(self, "Dispatcher", "F-02/FR-PROTO-8 LEN mismatch -> EBADREQ")
        decode = PROTO.attr(self, "decode", "F-02/FR-PROTO-8 decode")
        d = disp_cls()
        # LEN says 5 payload bytes but zero are present; CRC over the lie is
        # computed so the failure is structural (LEN), not a CRC reject.
        hdr = bytes([VER, CMD, FROZEN_OPCODES["HELLO"], 1]) + (5).to_bytes(2, "little")
        bad = hdr + (zlib.crc32(hdr) & 0xFFFFFFFF).to_bytes(4, "little")
        rsp = decode(bytes(d.on_message(bad)))
        self.assertEqual(rsp.payload[0], FROZEN_STATUS["EBADREQ"],
                         "a LEN that overruns the buffer is malformed -> EBADREQ")


class FragmentationTest(unittest.TestCase):
    """FR-BLE-8: payload = MTU-3 (ATT) minus 1-byte frag header.
    FR-BLE-10: split + reassemble byte-identically over the MTU matrix."""

    # BLE default ATT MTU is 23; the app requests 247 (protocol.md §2).
    MTUS = [23, 100, 185, 247]

    def _payloads(self):
        # Opaque byte blobs — fragmentation wraps the §3.1 message opaquely.
        return {
            "single_short": b"\x01\x02\x03",
            "corpus_250b": _support.hx(
                [v for v in _support.frames() if v["name"] == "run_cmd_source_opaque_250b"][0]["frame_hex"]
            ),
            "wrap_index_mod64": bytes(range(256)) * 6,  # 1536 B -> >64 frags @ MTU 23
        }

    def test_round_trip_byte_identical_over_mtu_matrix(self):
        fragment = PROTO.attr(self, "fragment", "F-02/FR-BLE-10 fragment split")
        reassemble = PROTO.attr(self, "reassemble", "F-02/FR-BLE-10 reassemble")
        for label, msg in self._payloads().items():
            for mtu in self.MTUS:
                pkts = fragment(msg, mtu)
                back = reassemble(pkts)
                self.assertEqual(bytes(back), msg,
                                 "reassemble(fragment) must be byte-identical "
                                 "[%s @ MTU %d]" % (label, mtu))

    def test_fragment_data_respects_mtu_minus_4(self):
        fragment = PROTO.attr(self, "fragment", "F-02/FR-BLE-8 payload = MTU-3-1")
        msg = self._payloads()["corpus_250b"]
        for mtu in self.MTUS:
            pkts = fragment(msg, mtu)
            for i, pkt in enumerate(pkts):
                self.assertLessEqual(len(pkt), mtu - 3,
                                     "packet must fit MTU-3 ATT budget @ MTU %d" % mtu)
                data = len(pkt) - 1  # minus the 1-byte FRAG_HDR
                self.assertLessEqual(data, mtu - 4,
                                     "fragment DATA must be <= MTU-4 @ MTU %d" % mtu)
            if len(pkts) > 1:
                # every packet but the last carries a full MTU-4 data chunk
                self.assertEqual(len(pkts[0]) - 1, mtu - 4,
                                 "non-final fragments must be full MTU-4 @ MTU %d" % mtu)

    def test_frag_header_first_last_and_index_bits(self):
        # §3.2: bit7=FIRST, bit6=LAST, bits5..0 = index mod 64.
        fragment = PROTO.attr(self, "fragment", "F-02/FR-BLE-10 §3.2 frag header bits")
        # single packet: FIRST and LAST both set, index 0
        one = fragment(b"\x01\x02\x03", 247)
        self.assertEqual(len(one), 1)
        self.assertTrue(one[0][0] & 0x80, "single packet has FIRST bit")
        self.assertTrue(one[0][0] & 0x40, "single packet has LAST bit")
        self.assertEqual(one[0][0] & 0x3F, 0, "single packet index 0")
        # many packets that wrap index mod 64
        many = fragment(bytes(range(256)) * 6, 23)
        self.assertGreater(len(many), 64, "need >64 fragments to exercise mod-64 wrap")
        self.assertTrue(many[0][0] & 0x80, "first fragment has FIRST bit")
        self.assertFalse(many[0][0] & 0x40, "first of many has no LAST bit")
        self.assertTrue(many[-1][0] & 0x40, "last fragment has LAST bit")
        self.assertFalse(many[-1][0] & 0x80, "last of many has no FIRST bit")
        for i, pkt in enumerate(many):
            self.assertEqual(pkt[0] & 0x3F, i % 64,
                             "fragment %d must carry index (i mod 64)" % i)


if __name__ == "__main__":
    unittest.main(verbosity=2)
