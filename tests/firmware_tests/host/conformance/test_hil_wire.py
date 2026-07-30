# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# HOST-RUNNABLE-NOW guard: the HIL bench's PBLE/1 wire codec (hil/_pble_wire.py)
# MUST agree BYTE-FOR-BYTE with the SHARED cross-language corpus (corpus.json)
# that the firmware `pble_proto` codec and the Dart `pble` client are held to.
# This extends the single cross-language byte-equality contract to the HIL
# harness itself: if the F-11 bench framed a byte differently from the firmware,
# a "reliability" run would be measuring the wrong protocol. No hardware needed.
#
# Captures (for the S6 HIL harness): FR-PROTO-2 (frame codec) + FR-PROTO-3 (IEEE
# CRC-32 over VER..PAYLOAD) + FR-BLE-8/10 (fragment/reassemble round-trip) as the
# bench implements them. Authored [chore] harness-plumbing guard by
# firmware-test-author.

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FT_DIR = os.path.dirname(os.path.dirname(HERE))            # tests/firmware_tests
CORPUS = os.path.join(HERE, "corpus.json")
HIL_DIR = os.path.join(FT_DIR, "hil")

if HIL_DIR not in sys.path:
    sys.path.insert(0, HIL_DIR)

import _pble_wire as wire  # noqa: E402


def _load_frames():
    with open(CORPUS, "r", encoding="utf-8") as fh:
        return json.load(fh)["frames"]


def _load_crc_reject():
    with open(CORPUS, "r", encoding="utf-8") as fh:
        return json.load(fh).get("crc_reject", [])


class TestBenchWireMatchesCorpus(unittest.TestCase):
    def test_encode_matches_corpus_bytes(self):
        for f in _load_frames():
            got = wire.encode(f["type"], f["opcode"], f["id"],
                              bytes.fromhex(f["payload_hex"]))
            self.assertEqual(
                got.hex(), f["frame_hex"],
                "encode(%s) diverged from the shared corpus wire" % f["name"])

    def test_crc32_matches_corpus(self):
        for f in _load_frames():
            frame = bytes.fromhex(f["frame_hex"])
            self.assertEqual(
                wire.crc32(frame[:-4]), f["crc32"],
                "CRC-32 for %s diverged from the corpus" % f["name"])

    def test_decode_roundtrips_corpus(self):
        for f in _load_frames():
            fr = wire.decode(bytes.fromhex(f["frame_hex"]))
            self.assertEqual(fr.type, f["type"], f["name"])
            self.assertEqual(fr.opcode, f["opcode"], f["name"])
            self.assertEqual(fr.id, f["id"], f["name"])
            self.assertEqual(fr.payload.hex(), f["payload_hex"], f["name"])

    def test_decode_rejects_corrupt_crc(self):
        for c in _load_crc_reject():
            with self.assertRaises(ValueError,
                                   msg="corrupt frame %s must be rejected" % c["name"]):
                wire.decode(bytes.fromhex(c["frame_hex"]))

    def test_fragment_reassemble_is_identity_over_mtu_matrix(self):
        # Every frozen frame must survive fragment->reassemble byte-identical at
        # a range of MTUs, including a tiny MTU that forces >64 fragments so the
        # index-mod-64 wrap in FRAG_HDR is exercised (FR-BLE-8/10).
        for mtu in (23, 27, 64, 185, 247, 512):
            re = wire.Reassembler()
            for f in _load_frames():
                frame = bytes.fromhex(f["frame_hex"])
                out = None
                pkts = wire.fragment(frame, mtu)
                # every non-last packet must carry no LAST bit; exactly one FIRST
                self.assertTrue(pkts[0][0] & 0x80, "first packet missing FIRST bit")
                self.assertTrue(pkts[-1][0] & 0x40, "last packet missing LAST bit")
                for p in pkts:
                    got = re.feed(p)
                    if got is not None:
                        out = got
                self.assertIsNotNone(out, "%s did not reassemble at MTU %d" % (f["name"], mtu))
                self.assertEqual(out.opcode, f["opcode"])
                self.assertEqual(out.payload.hex(), f["payload_hex"],
                                 "%s reassembled wrong at MTU %d" % (f["name"], mtu))

    def test_index_mod_64_wrap_present_for_large_frame(self):
        # The 250-byte RUN frame fragmented at MTU 23 (cap 19) needs 14 packets;
        # force the wrap by using MTU 5 (cap 1) on the same frame -> >64 packets.
        f = next(x for x in _load_frames() if x["name"] == "run_cmd_source_opaque_250b")
        frame = bytes.fromhex(f["frame_hex"])
        pkts = wire.fragment(frame, 5)  # cap = 1 byte/packet
        self.assertGreater(len(pkts), 64, "need >64 packets to exercise the mod-64 wrap")
        # packet 64 (index 64) must show index 0 in bits5..0
        self.assertEqual(pkts[64][0] & 0x3F, 0, "index did not wrap mod 64")
        re = wire.Reassembler()
        out = None
        for p in pkts:
            got = re.feed(p)
            if got is not None:
                out = got
        self.assertIsNotNone(out)
        self.assertEqual(out.payload.hex(), f["payload_hex"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
