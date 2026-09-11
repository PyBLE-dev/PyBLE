#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Actual host senders plus unchanged compiled native wire admission; no HIL.

Synthetic ACKs test sender orchestration only. Every captured valid CMD is
also admitted by the production C decision, so a permissive fake cannot hide
zero-ID frames. The raw codec remains available for deliberate negative tests.
"""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
HIL = HERE.parent / "hil"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HIL))
import test_v061_pble_wire_native as native_fixture
import _pble_bench as shared
import _pble_wire as wire
import f11_reliability_bench as reliability
import file_roundtrip_bench as roundtrip
import rp2_run_stop as rp2
import target_run_stop as target


class Clock:
    def __init__(self):
        self.value = 1.0

    def now(self):
        return self.value

    def ns(self):
        self.value += 0.001
        return int(self.value * 1_000_000_000)

    async def sleep(self, seconds):
        self.value += max(0.05, seconds)


class StrictCentral:
    def __init__(self, test, data, *, drop_first=False):
        self.test, self.data = test, data
        self.drop_first = drop_first
        self.dropped = False
        self.last_ack = 0
        self.calls, self.frames, self.offsets = [], [], []
        self.events = []
        self.chunk = 229

    def capture(self, opcode, request_id, payload, response):
        self.test.assertIs(type(request_id), int, "caller must allocate an integer CMD ID")
        self.test.assertTrue(1 <= request_id <= 255, "valid CMD ID must be 1..255 before encoding")
        raw = wire.encode(wire.CMD, opcode, request_id, payload)
        self.test.assertEqual(raw[3], request_id)
        self.calls.append((opcode, request_id, bytes(payload), response))
        self.frames.append(raw)

    async def send_cmd(self, opcode, request_id, payload=b"", **kwargs):
        self.test.assertNotEqual(opcode, wire.OP_FILE_PUT_DATA, "DATA must never wait for a RSP")
        self.capture(opcode, request_id, payload, True)
        result = b"\x00"
        if opcode == wire.OP_FILE_PUT_BEGIN:
            self.test.assertEqual(int.from_bytes(payload[:4], "little"), len(self.data))
            self.test.assertEqual(int.from_bytes(payload[4:8], "little"), wire.crc32(self.data))
            self.last_ack = 0
            result += b"\0" * 4
        elif opcode == wire.OP_FILE_PUT_END:
            self.test.assertEqual(payload, wire.crc32(self.data).to_bytes(4, "little"))
            self.test.assertEqual(self.last_ack, len(self.data))
        elif opcode == wire.OP_FILE_STAT:
            result += len(self.data).to_bytes(4, "little") + wire.crc32(self.data).to_bytes(4, "little")
        elif opcode == wire.OP_FILE_GET_BEGIN:
            result += len(self.data).to_bytes(4, "little")
            self.events.extend([
                wire.Frame(wire.EVT, wire.OP_FILE_GET_DATA, 0, b"\0" * 4 + self.data),
                wire.Frame(wire.EVT, wire.OP_FILE_GET_END, 0, wire.crc32(self.data).to_bytes(4, "little")),
            ])
        return wire.Frame(wire.RSP, opcode, request_id, result)

    async def send_cmd_no_rsp(self, opcode, request_id, payload=b""):
        self.test.assertEqual(opcode, wire.OP_FILE_PUT_DATA)
        self.capture(opcode, request_id, payload, False)
        offset = int.from_bytes(payload[:4], "little")
        piece = payload[4:]
        self.test.assertGreater(len(piece), 0)
        self.test.assertLessEqual(len(piece), self.chunk)
        self.test.assertEqual(piece, self.data[offset:offset + len(piece)])
        self.offsets.append(offset)
        if self.drop_first and not self.dropped:
            self.dropped = True
            return
        if offset == self.last_ack:
            self.last_ack += len(piece)

    def begin_ack_scope(self, watermark):
        self.test.assertEqual(watermark, 0)
        return SimpleNamespace(poll=lambda **kwargs: self.last_ack)


class ValidTransferCommandIDs(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = native_fixture.CompiledNativeWireTest()
        cls.native.setUp()
        cls.native.build_harness()

    @classmethod
    def tearDownClass(cls):
        cls.native.doCleanups()

    def assert_admitted(self, central):
        ids = [call[1] for call in central.calls]
        self.assertEqual(ids, [(index % 255) + 1 for index in range(len(ids))])
        hello = wire.encode(wire.CMD, wire.OP_HELLO, 255, native_fixture.CANONICAL_HELLO)
        output = self.native.run_harness([
            "RESET", "FRAME 1 " + hello.hex(),
            *["FRAME 1 " + raw.hex() for raw in central.frames],
        ])
        self.assertEqual(len(output), len(central.frames) + 2)
        for raw, decision in zip(central.frames, output[2:]):
            self.assertEqual(decision[1], "dispatch", decision)
            self.assertEqual(int(decision[3]), raw[3])
            self.assertEqual(decision[5], "0", "valid upload must not consume violation budget")

    def test_native_admission_rejects_zero_even_for_no_response_command(self):
        hello = wire.encode(wire.CMD, wire.OP_HELLO, 1, native_fixture.CANONICAL_HELLO)
        for request_id, action, violation in ((0, "drop", "1"), (1, "dispatch", "0"), (255, "dispatch", "0")):
            with self.subTest(request_id=request_id):
                raw = wire.encode(wire.CMD, wire.OP_FILE_PUT_DATA, request_id, b"\0" * 4 + b"x")
                result = self.native.run_harness(["RESET", "FRAME 1 " + hello.hex(), "FRAME 1 " + raw.hex()])[-1]
                self.assertEqual(result[1], action)
                self.assertEqual(result[5], violation)

    def test_allocator_wraps_through_three_complete_cycles_without_zero(self):
        ids = shared.CommandIds()
        self.assertEqual([ids.next() for _ in range(770)], [(i % 255) + 1 for i in range(770)])

    def test_valid_senders_have_no_literal_zero_cmd_ids(self):
        for module in (shared, reliability, roundtrip, target, rp2):
            with self.subTest(module=module.__name__):
                tree = ast.parse(Path(module.__file__).read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                        if node.func.attr in {"send_cmd", "send_cmd_no_rsp"} and len(node.args) > 1:
                            self.assertFalse(isinstance(node.args[1], ast.Constant) and node.args[1].value == 0,
                                             "%s:%d sends a valid CMD with ID zero" % (module.__name__, node.lineno))

    async def test_oi1_all_chunks_and_rewinds_share_wrapping_control_allocator(self):
        data = bytes(range(229)) * 260 + b"tail"
        for drop_first in (False, True):
            with self.subTest(drop_first=drop_first):
                central = StrictCentral(self, data, drop_first=drop_first)
                ids, clock = shared.CommandIds(), Clock()
                with mock.patch.object(shared, "time", SimpleNamespace(monotonic=clock.now)):
                    result = await shared.put_file(
                        central, "/host-only.bin", data, window=8, chunk=229,
                        next_id=ids.next, ack_timeout_s=0.1, operation_timeout_s=60,
                        clock_ns=clock.ns, sleep=clock.sleep)
                self.assertEqual(result.unique_committed_bytes, len(data))
                self.assertEqual(bool(result.retransmitted_chunks), drop_first)
                self.assertEqual(bool(result.rewinds), drop_first)
                self.assertGreater(len(central.offsets), 255)
                self.assert_admitted(central)

    async def test_f11_all_chunks_and_rewinds_share_wrapping_control_allocator(self):
        data = bytes(range(229)) * 260 + b"tail"
        for drop_first in (False, True):
            with self.subTest(drop_first=drop_first):
                central = StrictCentral(self, data, drop_first=drop_first)
                ids, clock = shared.CommandIds(), Clock()
                fake_asyncio = SimpleNamespace(get_event_loop=lambda: SimpleNamespace(time=clock.now), sleep=clock.sleep)
                with mock.patch.object(reliability, "asyncio", fake_asyncio):
                    result = await reliability._upload_one(central, "/host-only.bin", data, 8, 229, ids.next, 0.1, 1)
                self.assertTrue(result.ok)
                self.assertTrue(result.stat_verified)
                self.assertEqual(bool(result.retransmits), drop_first)
                self.assertGreater(len(central.offsets), 255)
                self.assert_admitted(central)

    async def test_roundtrip_put_get_and_rewinds_share_wrapping_allocator(self):
        data = bytes(range(229)) * 260 + b"tail"
        for drop_first in (False, True):
            with self.subTest(drop_first=drop_first):
                central = StrictCentral(self, data, drop_first=drop_first)
                ids, clock = shared.CommandIds(), Clock()
                with mock.patch.object(roundtrip, "time", SimpleNamespace(monotonic=clock.now)), \
                     mock.patch.object(roundtrip, "asyncio", SimpleNamespace(sleep=clock.sleep)):
                    await roundtrip._put(central, data, 229, 8, ids.next)
                    got, checksum, _duration = await roundtrip._get(central, data, ids.next)
                self.assertEqual(got, data)
                self.assertEqual(checksum, wire.crc32(data))
                self.assertEqual(len(central.offsets) != len(set(central.offsets)), drop_first)
                self.assertGreater(len(central.offsets), 255)
                self.assert_admitted(central)

    async def test_small_file_helpers_share_caller_allocator_across_wrap(self):
        data = b"print('host-only')\n"
        for module in (target, rp2):
            with self.subTest(module=module.__name__):
                ids = shared.CommandIds()
                central = StrictCentral(self, data)
                for _ in range(90):
                    await module.put_small_file(central, "/host-only.py", data, ids.next)
                self.assertEqual(len(central.frames), 270)
                self.assertEqual(len(central.offsets), 90)
                self.assert_admitted(central)


if __name__ == "__main__":
    unittest.main()
