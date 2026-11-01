# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Host-only ownership/restoration tests for the optional autorun HIL probe."""
import importlib.util
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[3]


def load_bench():
    path = ROOT / 'tests/firmware_tests/hil/v070_autorun_status_bench.py'
    if not path.is_file():
        raise AssertionError('missing optional autorun-origin probe')
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location('autorun_probe_test_subject', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Board:
    def __init__(self):
        self.main = None
        self.auto = 0
        self.boot_count = 1
        self.boot = bytes([self.boot_count]) * 8
        self.run_id = self.revision = self.state = self.origin = self.reason = 0
        self.calls = []
        self.sessions = []
        self.puts = self.gets = 0
        self.enable_fails = self.disable_fails = self.delete_noop = False
        self.replace_main_on_boot = False
        self.get_fails_once = False
        self.status_fails_once_after_boot = False
        self.successor_on_reconnect = False
        self.complete_before_stop = False

    def payload(self):
        return struct.pack('<B8sIQBBBB', 1, self.boot, self.run_id, self.revision,
                           self.state, self.origin, self.reason, 0)

    async def connect(self, _address):
        if self.successor_on_reconnect and len(self.sessions) == 2:
            self.run_id, self.revision, self.state, self.origin = 2, 4, 1, 3
        session = Session(self)
        self.sessions.append(session)
        return session

    async def put(self, central, path, data, **kwargs):
        assert path == '/main.py'
        assert self.main is None, 'probe must never overwrite an existing main.py'
        assert kwargs['chunk'] == 229 and kwargs['window'] == 4
        assert 1 <= kwargs['next_id']() <= 255
        self.puts += 1
        self.main = bytes(data)

    async def get(self, central, path, expected, **kwargs):
        assert path == '/main.py'
        self.gets += 1
        if self.get_fails_once:
            self.get_fails_once = False
            raise ValueError('injected GET verification failure')
        assert self.main == expected

    def count(self, opcode):
        return sum(op == opcode for op, _, _ in self.calls)


class Session:
    backend_mtu = 247
    def __init__(self, board):
        self.board = board
        self.closed = False
    def confirm_caps_mtu(self, _mtu):
        pass
    def limit_write_fragmentation(self, _mtu):
        pass
    async def disconnect(self):
        self.closed = True
    async def send_cmd(self, opcode, request_id, payload=b'', **_kwargs):
        b = self.board
        b.calls.append((opcode, request_id, bytes(payload)))
        result = b'\0'
        if opcode in (1, 2):
            result += ('chip=rpi-pico2-w\nagent=0.7.0-dev.1\nrun_status=1\n'
                       'mtu=247\nwindow=4\nchunk=229\nauto_run=%d\n' % b.auto).encode()
        elif opcode == 0x11:
            if b.main is None:
                result = b'\x02'
            else:
                result += struct.pack('<II', len(b.main), zlib.crc32(b.main) & 0xffffffff)
        elif opcode == 0x24:
            if b.complete_before_stop and b.count(0x24) == 4:
                b.state, b.reason, b.revision = 2, 1, b.revision + 1
            if b.status_fails_once_after_boot and b.boot_count > 1:
                b.status_fails_once_after_boot = False
                result = b'\x05'
            else:
                result += b.payload()
        elif opcode == 0x23:
            if payload == b'\1' and b.enable_fails:
                result = b'\x05'
            elif payload == b'\0' and b.disable_fails:
                result = b'\x05'
            else:
                b.auto = payload[0]
        elif opcode == 0x22:
            b.boot_count += 1
            b.boot = bytes([b.boot_count]) * 8
            b.run_id = b.revision = b.state = b.origin = b.reason = 0
            if b.auto and b.main is not None:
                b.run_id, b.revision, b.state, b.origin = 1, 2, 1, 3
                if b.replace_main_on_boot:
                    b.main = b'user-owned replacement; preserve me'
        elif opcode == 0x21:
            if b.state == 1:
                b.state, b.reason = 0, 3
                b.revision += 2
        elif opcode == 0x18:
            if not b.delete_noop:
                b.main = None
        else:
            raise AssertionError('unexpected autorun probe opcode: %r' % opcode)
        return SimpleNamespace(payload=result)


async def no_delay(_seconds):
    pass


class AutorunProbeTest(unittest.IsolatedAsyncioTestCase):
    async def run_probe(self, board):
        module = load_bench()
        args = SimpleNamespace(address='host-fake', expect_chip='rpi-pico2-w',
                               expect_agent='0.7.0-dev.1', mtu=23,
                               profile='rpi-pico2-w', source_commit='host-test')
        with patch.object(module.status_bench, 'PbleCentral', SimpleNamespace(connect=board.connect)), \
                patch.object(module.pble_bench, 'put_file', board.put), \
                patch.object(module.pble_bench, 'get_file', board.get), \
                patch.object(module.asyncio, 'sleep', no_delay):
            return await module.probe(args)

    async def test_complete_probe_proves_origin_reconnect_and_restores_baseline(self):
        b = Board()
        result = await self.run_probe(b)
        self.assertEqual('pass', result['status'])
        self.assertTrue(result['cleanup']['verified'])
        self.assertTrue(result['cleanup']['main_absent'])
        self.assertTrue(result['cleanup']['auto_run_restored'])
        self.assertTrue(result['cleanup']['idle_after_reboot'])
        self.assertEqual(1, b.puts)
        self.assertGreaterEqual(b.gets, 2)
        self.assertIsNone(b.main)
        self.assertEqual(0, b.auto)
        self.assertEqual(0, b.state)
        self.assertEqual(2, b.count(0x22))
        self.assertEqual(1, b.count(0x18))
        self.assertTrue(all(s.closed for s in b.sessions))
        self.assertIn('autorun-origin3-reconnect', result['observations'])
        snapshots = result['snapshots']
        self.assertEqual(3, snapshots['running']['origin'])
        self.assertEqual(snapshots['running'], snapshots['reconnected'])
        self.assertEqual(3, snapshots['stopped']['terminal_reason'])
        self.assertNotEqual(snapshots['initial']['boot_id'], snapshots['running']['boot_id'])
        self.assertNotEqual(snapshots['running']['boot_id'], snapshots['restored']['boot_id'])

    async def test_natural_completion_cannot_be_reported_as_stop_success(self):
        b = Board(); b.complete_before_stop = True
        result = await self.run_probe(b)
        self.assertEqual('fail', result['status'])
        self.assertTrue(result['cleanup']['verified'])
        self.assertNotIn('autorun-stopped-terminal', result['observations'])
        self.assertEqual(0, b.count(0x21))

    async def test_preexisting_main_refuses_without_any_mutation(self):
        b = Board(); original = b.main = b'owner code'
        result = await self.run_probe(b)
        self.assertEqual('fail', result['status'])
        self.assertEqual(original, b.main)
        self.assertEqual(0, b.puts)
        self.assertFalse(any(b.count(op) for op in (0x23, 0x22, 0x21, 0x18)))

    async def test_preexisting_autorun_flag_refuses_without_any_mutation(self):
        b = Board(); b.auto = 1
        result = await self.run_probe(b)
        self.assertEqual('fail', result['status'])
        self.assertEqual(1, b.auto)
        self.assertEqual(0, b.puts)
        self.assertFalse(any(b.count(op) for op in (0x23, 0x22, 0x21, 0x18)))

    async def test_preexisting_active_program_refuses_without_stop(self):
        b = Board(); b.run_id, b.revision, b.state, b.origin = 3, 8, 1, 2
        result = await self.run_probe(b)
        self.assertEqual('fail', result['status'])
        self.assertEqual(0, b.puts)
        self.assertEqual(0, b.count(0x21))
        self.assertEqual(0, b.count(0x22))

    async def test_foreign_replacement_main_is_never_deleted_or_stopped(self):
        b = Board(); b.replace_main_on_boot = True
        result = await self.run_probe(b)
        self.assertEqual('fail', result['status'])
        self.assertFalse(result['cleanup']['verified'])
        self.assertEqual(b'user-owned replacement; preserve me', b.main)
        self.assertEqual(0, b.auto)
        self.assertEqual(0, b.count(0x18))
        self.assertEqual(0, b.count(0x21))
        self.assertEqual(1, b.count(0x22))

    async def test_successor_autorun_is_not_adopted_during_cleanup(self):
        b = Board(); b.successor_on_reconnect = True
        result = await self.run_probe(b)
        self.assertEqual('fail', result['status'])
        self.assertFalse(result['cleanup']['verified'])
        self.assertEqual(2, b.run_id)
        self.assertEqual(1, b.state)
        self.assertIsNotNone(b.main)
        self.assertEqual(0, b.auto)
        self.assertEqual(0, b.count(0x21))
        self.assertEqual(0, b.count(0x18))
        self.assertEqual(1, b.count(0x22))

    async def test_restore_flag_failure_cannot_produce_a_pass(self):
        b = Board(); b.disable_fails = True
        result = await self.run_probe(b)
        self.assertEqual('fail', result['status'])
        self.assertFalse(result['cleanup']['verified'])
        self.assertFalse(result['cleanup']['auto_run_restored'])
        self.assertEqual(1, b.auto)
        self.assertIsNotNone(b.main)
        self.assertEqual(0, b.count(0x18))

    async def test_unverified_delete_cannot_produce_a_pass(self):
        b = Board(); b.delete_noop = True
        result = await self.run_probe(b)
        self.assertEqual('fail', result['status'])
        self.assertFalse(result['cleanup']['verified'])
        self.assertFalse(result['cleanup']['main_absent'])
        self.assertIsNotNone(b.main)
        self.assertEqual(0, b.auto)

    async def test_readback_failure_preserved_even_when_cleanup_succeeds(self):
        b = Board(); b.get_fails_once = True
        result = await self.run_probe(b)
        self.assertEqual('fail', result['status'])
        self.assertIn('GET verification', result['failure']['detail'])
        self.assertTrue(result['cleanup']['verified'])
        self.assertIsNone(b.main)
        self.assertEqual(0, b.auto)

    async def test_enable_failure_still_restores_original_configuration_and_file(self):
        b = Board(); b.enable_fails = True
        result = await self.run_probe(b)
        self.assertEqual('fail', result['status'])
        self.assertTrue(result['cleanup']['verified'])
        self.assertIsNone(b.main)
        self.assertEqual(0, b.auto)

    async def test_first_post_boot_query_failure_can_recover_owned_cleanup(self):
        b = Board(); b.status_fails_once_after_boot = True
        result = await self.run_probe(b)
        self.assertEqual('fail', result['status'])
        self.assertTrue(result['cleanup']['verified'])
        self.assertIsNone(b.main)
        self.assertEqual(0, b.auto)
        self.assertEqual(1, b.count(0x21))


if __name__ == '__main__':
    unittest.main(verbosity=2)
