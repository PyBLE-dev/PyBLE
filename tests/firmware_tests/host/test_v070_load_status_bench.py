# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Fake-peer safety tests for the optional physical load probe, not HIL proof."""
import contextlib
import importlib.util
import io
from pathlib import Path
import re
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


def load_bench():
    path = ROOT / 'tests/firmware_tests/hil/v070_load_status_bench.py'
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location('load_status_probe_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeBoard:
    def __init__(self):
        self.boot = b'\x01\x02\x03\x04\x05\x06\x07\x08'
        self.run = self.rev = self.state = self.origin = self.reason = self.flags = 0
        self.calls = []
        self.events = []
        self.disconnections = 0
        self.query_count = 0
        self.on_query = None
        self.omit_marker = False
        self.flood_copies = 3
        self.split_marker = False
        self.reject_run = False
        self.reject_stop = False
        self.reject_queries = set()
        self.agent = '0.7.0-dev.1'
        self.caps_mtu = 247
        self.backend_mtu = 247
        self.marker = None

    async def connect(self, address):
        return self

    async def disconnect(self):
        self.disconnections += 1

    def confirm_caps_mtu(self, mtu):
        self.confirmed = mtu

    def limit_write_fragmentation(self, mtu):
        if mtu > self.caps_mtu:
            raise ValueError('fragment limit exceeds actual MTU')
        self.fragment_limit = mtu

    def event_cursor(self):
        return len(self.events)

    def events_since(self, cursor):
        return len(self.events), self.events[cursor:]

    def stdout(self, data):
        self.events.append(SimpleNamespace(opcode=0x30, payload=b'\0' + data))

    def snapshot(self):
        return struct.pack('<B8sIQBBBB', 1, self.boot, self.run, self.rev,
                           self.state, self.origin, self.reason, self.flags)

    async def send_cmd(self, opcode, request_id, payload=b''):
        self.calls.append((opcode, request_id, payload))
        if opcode == 0x01:
            caps = ('chip=esp32-s3\nagent=%s\nrun_status=1\nmtu=%d\n'
                    % (self.agent, self.caps_mtu)).encode()
            return SimpleNamespace(payload=b'\0' + caps)
        if opcode == 0x24:
            self.query_count += 1
            if self.on_query:
                self.on_query(self)
            if self.query_count in self.reject_queries:
                return SimpleNamespace(payload=b'\x05')
            return SimpleNamespace(payload=b'\0' + self.snapshot())
        if opcode == 0x20:
            if self.reject_run:
                return SimpleNamespace(payload=b'\x07')
            self.run += 1
            self.rev += 2
            self.state, self.origin, self.reason = 1, 2, 0
            found = re.search(rb'PyBLE v070 load [0-9a-f]+ (tight|flood)', payload)
            assert found is not None, 'source has no unique execution marker'
            self.marker = found.group(0)
            copies = self.flood_copies if found.group(1) == b'flood' else 1
            if not self.omit_marker:
                output = (self.marker + b'\n') * copies
                if self.split_marker:
                    self.stdout(output[:7])
                    self.stdout(output[7:])
                else:
                    self.stdout(output)
            return SimpleNamespace(payload=b'\0')
        if opcode == 0x21:
            if self.reject_stop:
                return SimpleNamespace(payload=b'\x07')
            self.state, self.reason, self.flags = 0, 3, 0
            self.rev += 2
            return SimpleNamespace(payload=b'\0')
        raise AssertionError('unexpected mutating opcode %r' % opcode)

    def count(self, opcode):
        return sum(op == opcode for op, _, _ in self.calls)


class Clock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        self.value += .01
        return self.value


async def no_delay(_seconds):
    pass


class LoadProbeTests(unittest.IsolatedAsyncioTestCase):
    async def run_probe(self, board, mtu=23):
        module = load_bench()
        args = SimpleNamespace(address='fake', expect_chip='esp32-s3',
                               expect_agent='0.7.0-dev.1', mtu=mtu,
                               profile='host-fake', source_commit='firmware-sha')
        with patch.object(module.status_bench, 'PbleCentral', SimpleNamespace(connect=board.connect)), \
                patch.object(module.asyncio, 'sleep', no_delay), \
                patch.object(module, 'monotonic', Clock()):
            return await module.probe(args)

    async def test_both_loads_query_three_actual_running_snapshots_then_stop(self):
        for mtu in (23, 247):
            with self.subTest(mtu=mtu):
                board = FakeBoard()
                result = await self.run_probe(board, mtu)
                self.assertEqual('pass', result['status'], result)
                self.assertTrue(result['cleanup']['verified'])
                self.assertEqual(mtu, result['command_fragment_mtu'])
                self.assertEqual(247, result['backend_mtu'])
                self.assertEqual(247, result['negotiated_caps_mtu'])
                self.assertEqual(['tight', 'flood'], [r['case'] for r in result['cases']])
                self.assertTrue(result['bench_commit'])
                self.assertEqual('firmware-sha', result['source_commit'])
                for case in result['cases']:
                    self.assertEqual(3, len(case['queries']))
                    self.assertGreaterEqual(case['console']['marker_count'],
                                            2 if case['case'] == 'flood' else 1)
                    for query in case['queries']:
                        self.assertGreaterEqual(query['latency_ms'], 0)
                        self.assertEqual((1, 2, 0), tuple(query['snapshot'][key]
                                         for key in ('state', 'origin', 'flags')))
                    self.assertEqual((0, 3, 0), tuple(case['stopped'][key]
                                     for key in ('state', 'terminal_reason', 'flags')))
                self.assertEqual(2, board.count(0x20))
                self.assertEqual(2, board.count(0x21))
                self.assertEqual(1, board.disconnections)
                self.assertTrue(all(op in (1, 0x20, 0x21, 0x24)
                                    for op, _, _ in board.calls))

    async def test_console_marker_can_span_notifications(self):
        board = FakeBoard()
        board.split_marker = True
        self.assertEqual('pass', (await self.run_probe(board))['status'])

    async def test_preexisting_active_program_is_never_run_or_stopped(self):
        board = FakeBoard()
        board.run, board.rev, board.state, board.origin = 3, 8, 1, 1
        result = await self.run_probe(board)
        self.assertEqual('fail', result['status'])
        self.assertIn('pre-existing active', result['failure']['detail'])
        self.assertEqual((0, 0), (board.count(0x20), board.count(0x21)))
        self.assertEqual(1, board.disconnections)

    async def test_queued_snapshot_cannot_claim_execution_under_load(self):
        board = FakeBoard()
        board.flags = 1
        result = await self.run_probe(board)
        self.assertEqual('fail', result['status'])
        self.assertIn('running picked-up', result['failure']['detail'])
        self.assertTrue(result['cleanup']['verified'])
        self.assertEqual(1, board.count(0x21))

    async def test_status_alone_without_console_execution_marker_fails(self):
        board = FakeBoard()
        board.omit_marker = True
        result = await self.run_probe(board)
        self.assertEqual('fail', result['status'])
        self.assertIn('console execution marker', result['failure']['detail'])
        self.assertEqual(1, board.count(0x21))

    async def test_flood_requires_repeated_execution_marker(self):
        board = FakeBoard()
        board.flood_copies = 1
        result = await self.run_probe(board)
        self.assertEqual('fail', result['status'])
        self.assertEqual(2, board.count(0x20))
        self.assertEqual(2, board.count(0x21))
        self.assertIn('console execution marker', result['failure']['detail'])

    async def test_foreign_successor_is_never_stopped_in_failure_cleanup(self):
        for change in ('run', 'boot'):
            with self.subTest(change=change):
                board = FakeBoard()
                def foreign(b):
                    if b.query_count == 3:
                        if change == 'run':
                            b.run += 1
                            b.rev += 2
                        else:
                            b.boot = bytes(reversed(b.boot))
                board.on_query = foreign
                result = await self.run_probe(board)
                self.assertEqual('fail', result['status'])
                self.assertFalse(result['cleanup']['verified'])
                self.assertEqual(0, board.count(0x21))
                self.assertEqual(1, board.disconnections)

    async def test_lost_authoritative_cleanup_query_never_sends_stop(self):
        board = FakeBoard()
        board.reject_queries.update(range(3, 30))
        result = await self.run_probe(board)
        self.assertEqual('fail', result['status'])
        self.assertFalse(result['cleanup']['verified'])
        self.assertEqual(0, board.count(0x21))

    async def test_failed_probe_query_still_cleans_up_proven_owned_run(self):
        board = FakeBoard()
        board.reject_queries.add(3)
        result = await self.run_probe(board)
        self.assertEqual('fail', result['status'])
        self.assertTrue(result['cleanup']['verified'])
        self.assertEqual(1, board.count(0x21))

    async def test_stop_refusal_is_not_recorded_as_stopped_terminal(self):
        board = FakeBoard()
        board.reject_stop = True
        result = await self.run_probe(board)
        self.assertEqual('fail', result['status'])
        self.assertFalse(result['cleanup']['verified'])
        self.assertNotIn('stopped', result['cases'][0])

    async def test_candidate_mismatch_refuses_run_and_closes_link(self):
        board = FakeBoard()
        board.agent = '0.6.1'
        result = await self.run_probe(board)
        self.assertEqual('fail', result['status'])
        self.assertEqual((0, 0), (board.count(0x20), board.count(0x21)))
        self.assertEqual(1, board.disconnections)

    async def test_unknown_backend_mtu_remains_unknown(self):
        board = FakeBoard()
        board.backend_mtu = None
        result = await self.run_probe(board)
        self.assertEqual('pass', result['status'])
        self.assertIsNone(result['backend_mtu'])

    async def test_actual_caps_mtu_is_not_invented_from_requested_fragment_limit(self):
        board = FakeBoard()
        board.caps_mtu = board.backend_mtu = 23
        result = await self.run_probe(board)
        self.assertEqual('fail', result['status'])
        self.assertEqual((0, 0), (board.count(0x20), board.count(0x21)))


class BoundedSourceTests(unittest.TestCase):
    def test_actual_source_has_finite_fifteen_second_ticks_diff_loop(self):
        module = load_bench()
        for case in ('tight', 'flood'):
            with self.subTest(case=case):
                source, marker = module.source_for(case, '0123456789abcdef')
                self.assertIn(b'ticks_diff', source)
                self.assertIn(b'15000', source)
                ticks = iter((0, 0, 15000))
                fake_time = SimpleNamespace(ticks_ms=lambda: next(ticks),
                                            ticks_diff=lambda a, b: a - b)
                out = io.StringIO()
                with patch.dict(sys.modules, time=fake_time), contextlib.redirect_stdout(out):
                    exec(compile(source, '<bounded-load-probe>', 'exec'), {})
                self.assertEqual(2 if case == 'flood' else 1,
                                 out.getvalue().count(marker.decode()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
