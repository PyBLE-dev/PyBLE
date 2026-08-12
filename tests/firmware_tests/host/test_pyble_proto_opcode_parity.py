#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Host tests for the rpi-pico2-w port increment of F-25 `pyble_proto`
# (EPIC-PORT-RP2, gate GP1). Sole [red] author: firmware-test-author.
# Production module owner (HAND-OFF for [green]): protocol-engineer ->
# firmware/pyble/pyble_proto.py (plan C5).
#
# WHY THIS SUITE EXISTS (on top of test_pyble_proto.py, which stays green):
#   1. OPCODE PARITY — the scaffold's OPCODES table predates the S6 additive
#      opcode `SET_AUTORUN 0x23` (protocol.md §4, FROZEN; native twin
#      pble_proto.h PBLE_OP_SET_AUTORUN). The table must match the frozen §4
#      set EXACTLY — the pinned gap is the missing 0x23 entry.
#   2. CRC STREAMING — the rp2 port CRCs whole files incrementally (FILE_STAT /
#      GET-END / PUT resume re-CRC) and gains a native `binascii.crc32` fast
#      path. The frozen §3.1 CRC (IEEE, zlib-compatible, over VER..PAYLOAD)
#      must stay BIT-IDENTICAL in incremental form, chained exactly like
#      binascii.crc32(chunk, crc) from seed 0.
#
# All wire facts are REFERENCED from protocol.md §4/§8 (FROZEN v1.0 + the §9
# additive 0x23) and the SHARED conformance corpus
# host/conformance/corpus.json — never redefined here.
#
# ---------------------------------------------------------------------------
# INTERFACE PINNED BY THIS [red] TEST (protocol-engineer implements to it):
#   pyble_proto.OPCODES : dict{name->int}  == the frozen §4 set INCLUDING
#         "SET_AUTORUN": 0x23 (additive §9 opcode, auto_run-cap gated)
#   pyble_proto.crc32(buf) -> int          # unchanged whole-buffer form
#   pyble_proto.crc32_update(crc: int, chunk: bytes|bytearray|memoryview) -> int
#         # streaming form: seed 0, chain c = crc32_update(c, chunk);
#         # final value == crc32(b"".join(chunks)) == zlib/binascii.crc32.
#         # Native binascii fast path where available; the pure table stays
#         # the fallback — both BIT-IDENTICAL (this suite is the guard).
# ---------------------------------------------------------------------------

import os
import sys
import unittest
import zlib  # test-side IEEE CRC-32 ORACLE (not production code)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

PROTO = _support.RedReason("pyble_proto", owner="protocol-engineer")

# The FROZEN protocol.md §4 opcode set (referenced, not redefined) — the full
# v1.0 table INCLUDING the §9-additive SET_AUTORUN 0x23 (S6 F-12).
FROZEN_OPCODES_V1 = {
    "HELLO": 0x01, "DEVICE_INFO": 0x02,
    "FILE_LIST": 0x10, "FILE_STAT": 0x11, "FILE_GET_BEGIN": 0x12,
    "FILE_GET_DATA": 0x13, "FILE_GET_END": 0x14, "FILE_PUT_BEGIN": 0x15,
    "FILE_PUT_DATA": 0x16, "FILE_PUT_END": 0x17, "FILE_DELETE": 0x18,
    "MKDIR": 0x19, "FILE_RENAME": 0x1A,
    "RUN": 0x20, "STOP": 0x21, "SOFT_REBOOT": 0x22, "SET_AUTORUN": 0x23,
    "CONSOLE_DATA": 0x30, "CONSOLE_INPUT": 0x31,
    "RUN_STATE": 0x40, "FILE_PUT_ACK": 0x41,
    "SET_LABEL": 0x50, "SET_IDENTIFY_LED": 0x51, "IDENTIFY": 0x52,
}


class OpcodeParityTest(unittest.TestCase):
    """F-25 AC-1: the OPCODES table matches protocol.md §4 exactly."""

    def test_set_autorun_0x23_present(self):
        opcodes = PROTO.attr(self, "OPCODES", "F-25/§4 opcode parity")
        self.assertIn(
            "SET_AUTORUN", opcodes,
            "[F-25/§4] OPCODES must carry the §9-additive SET_AUTORUN opcode "
            "(protocol.md §4, native twin PBLE_OP_SET_AUTORUN) — the pinned "
            "scaffold gap. HAND-OFF: protocol-engineer (plan C5).")
        self.assertEqual(
            0x23, opcodes["SET_AUTORUN"],
            "[F-25/§4] SET_AUTORUN is frozen at 0x23")

    def test_opcode_table_matches_frozen_section4_exactly(self):
        opcodes = PROTO.attr(self, "OPCODES", "F-25/§4 opcode parity")
        self.assertEqual(
            FROZEN_OPCODES_V1, dict(opcodes),
            "[F-25/§4] OPCODES must equal the frozen protocol.md §4 set "
            "EXACTLY — no missing entries (SET_AUTORUN 0x23), no extras, no "
            "renumbering. The wire is frozen; only the table may move.")


class CrcStreamingTest(unittest.TestCase):
    """F-25 AC-1: crc32 gains a streaming form, bit-identical to §3.1 CRC."""

    CRITERION = "F-25/§3.1 streaming CRC-32 bit-identity"

    def test_crc32_update_seeds_from_zero(self):
        upd = PROTO.attr(self, "crc32_update", self.CRITERION)
        self.assertEqual(
            0, upd(0, b""),
            "[{}] crc32_update must chain like binascii.crc32(chunk, crc): "
            "seed 0, empty chunk is identity".format(self.CRITERION))

    def test_streaming_matches_corpus_and_whole_buffer(self):
        upd = PROTO.attr(self, "crc32_update", self.CRITERION)
        whole = PROTO.attr(self, "crc32", self.CRITERION)
        frames = _support.frames()
        self.assertTrue(frames, "shared conformance corpus must not be empty")
        for entry in frames:
            frame = _support.hx(entry["frame_hex"])
            body = frame[:-4]  # VER..PAYLOAD (the §3.1 CRC input)
            expected = entry["crc32"]
            self.assertEqual(
                expected, whole(body),
                "[{}] whole-buffer crc32 diverged from the corpus on frame "
                "{!r}".format(self.CRITERION, entry["name"]))
            for step in (1, 7):
                crc = 0
                for i in range(0, len(body), step):
                    crc = upd(crc, body[i:i + step])
                self.assertEqual(
                    expected, crc,
                    "[{}] incremental crc32_update (chunk={}B) diverged from "
                    "the corpus on frame {!r} — streaming and whole-buffer "
                    "forms must be BIT-IDENTICAL".format(
                        self.CRITERION, step, entry["name"]))

    def test_streaming_matches_zlib_oracle_on_arbitrary_chunking(self):
        upd = PROTO.attr(self, "crc32_update", self.CRITERION)
        data = bytes((i * 37 + 11) & 0xFF for i in range(4096))
        oracle = zlib.crc32(data) & 0xFFFFFFFF
        crc = 0
        offset = 0
        sizes = (0, 1, 2, 3, 5, 8, 13, 200, 229, 1024, 4096)
        i = 0
        while offset < len(data):
            size = sizes[i % len(sizes)]
            crc = upd(crc, data[offset:offset + size])
            offset += size
            i += 1
        self.assertEqual(
            oracle, crc,
            "[{}] crc32_update over uneven chunk sizes (incl. empty) must "
            "equal the zlib oracle".format(self.CRITERION))

    def test_streaming_accepts_memoryview_chunks(self):
        upd = PROTO.attr(self, "crc32_update", self.CRITERION)
        data = bytes(range(256)) * 4
        oracle = zlib.crc32(data) & 0xFFFFFFFF
        view = memoryview(data)
        crc = 0
        for i in range(0, len(data), 100):
            crc = upd(crc, view[i:i + 100])
        self.assertEqual(
            oracle, crc,
            "[{}] crc32_update must accept memoryview chunks (the rp2 file "
            "worker streams flash reads through memoryviews)".format(
                self.CRITERION))


if __name__ == "__main__":
    unittest.main(verbosity=2)
