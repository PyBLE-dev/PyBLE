#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""Exercise the physical probe's control ownership using a fake transport.

These host tests validate probe orchestration, never firmware or physical HIL.
"""

import importlib.util
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


def load_bench():
    path = ROOT / "tests/firmware_tests/hil/v070_run_status_bench.py"
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("status_probe_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeBoard:
    """A deterministic peer solely for testing command ordering and cleanup."""

    def __init__(self):
        self.boot = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        self.run_id = self.revision = self.state = self.origin = self.reason = 0
        self.calls = []
        self.sessions = []
        self.failed_connections = set()
        self.failed_queries = set()
        self.on_connect = None
        self.caps_agent = "0.7.0-dev.1"
        self.reject_cleanup_stop = False

    def snapshot(self):
        return struct.pack("<B8sIQBBBB", 1, self.boot, self.run_id,
                           self.revision, self.state, self.origin, self.reason, 0)

    async def connect(self, address):
        index = len(self.sessions) + 1
        if index in self.failed_connections:
            raise OSError("injected reconnect failure")
        session = FakeSession(self, index)
        self.sessions.append(session)
        if self.on_connect is not None:
            self.on_connect(index)
        return session

    def command_count(self, opcode):
        return sum(op == opcode for _, op, _, _ in self.calls)


class FakeSession:
    backend_mtu = 247

    def __init__(self, board, index):
        self.board, self.index = board, index
        self.disconnections = 0
        self.query_count = 0
        self.confirmed_mtu = None

    def confirm_caps_mtu(self, mtu):
        self.confirmed_mtu = mtu

    async def disconnect(self):
        self.disconnections += 1

    async def send_cmd(self, opcode, request_id, payload):
        b = self.board
        b.calls.append((self.index, opcode, request_id, payload))
        if opcode == 0x01:
            caps = ("chip=rpi-pico2-w\nagent=" + b.caps_agent +
                    "\nrun_status=1\nmtu=247\n").encode()
            return SimpleNamespace(payload=b"\0" + caps)
        if opcode == 0x24:
            self.query_count += 1
            if (self.index, self.query_count) in b.failed_queries:
                return SimpleNamespace(payload=b"\x05")
            return SimpleNamespace(payload=b"\x01" if payload else
                                   b"\0" + b.snapshot())
        if opcode == 0x20:
            if b.state == 1:
                return SimpleNamespace(payload=b"\x07")
            b.run_id += 1
            b.revision += 2  # admitted and picked up
            b.state, b.origin, b.reason = 1, 2, 0
            if payload == b"\1pass":
                b.state, b.reason = 2, 1
                b.revision += 1
            elif payload.startswith(b"\1raise ValueError"):
                b.state, b.reason = 3, 2
                b.revision += 1
            return SimpleNamespace(payload=b"\0")
        if opcode == 0x21:
            if b.reject_cleanup_stop:
                raise OSError("injected STOP transport failure")
            if b.state == 1:
                b.state, b.reason = 0, 3
                b.revision += 2  # stop accepted and terminal
            return SimpleNamespace(payload=b"\0")
        if opcode == 0x22:
            b.boot = b"\x08\x07\x06\x05\x04\x03\x02\x01"
            b.run_id = b.revision = b.state = b.origin = b.reason = 0
            return SimpleNamespace(payload=b"\0")
        raise AssertionError("unexpected probe opcode: %r" % opcode)


async def no_delay(_seconds):
    return None


class ProbeOrchestrationTest(unittest.IsolatedAsyncioTestCase):
    async def run_probe(self, board, mtu=23):
        module = load_bench()
        args = SimpleNamespace(address="host-fake", expect_chip="rpi-pico2-w",
                               expect_agent="0.7.0-dev.1", mtu=mtu,
                               profile="rpi-pico2-w", source_commit="host-test")
        with patch.object(module, "PbleCentral", SimpleNamespace(connect=board.connect)), \
                patch.object(module.asyncio, "sleep", no_delay):
            return await module.probe(args)

    async def test_full_probe_reconnects_checks_terminals_and_resets(self):
        for mtu in (23, 247):
            with self.subTest(mtu=mtu):
                board = FakeBoard()
                result = await self.run_probe(board, mtu)
                self.assertEqual("pass", result["status"])
                self.assertEqual(mtu, result["command_fragment_mtu"])
                self.assertEqual(247, result["backend_mtu"])
                self.assertEqual(["exact-empty-grammar", "reconnect-running-snapshot",
                                  "stop-terminal-idempotence", "normal-error-terminals",
                                  "vm-reset-identity"], result["observations"])
                self.assertEqual(3, board.command_count(0x20))
                self.assertEqual(2, board.command_count(0x21))
                self.assertEqual(1, board.command_count(0x22))
                self.assertEqual([1, 1, 1], [s.disconnections for s in board.sessions])
                self.assertEqual([mtu] * 3, [s.confirmed_mtu for s in board.sessions])
                self.assertTrue(all(1 <= request_id <= 255
                                    for _, _, request_id, _ in board.calls))

    async def test_preexisting_active_program_is_never_run_or_stopped(self):
        board = FakeBoard()
        board.run_id, board.revision, board.state, board.origin = 7, 20, 1, 1
        with self.assertRaisesRegex(RuntimeError, "pre-existing active"):
            await self.run_probe(board)
        self.assertEqual(0, board.command_count(0x20))
        self.assertEqual(0, board.command_count(0x21))
        self.assertEqual(1, board.sessions[0].disconnections)

    async def test_reconnect_failure_cannot_issue_stop_without_a_connection(self):
        board = FakeBoard()
        board.failed_connections.add(2)
        with self.assertRaisesRegex(OSError, "reconnect failure"):
            await self.run_probe(board)
        self.assertEqual(1, board.command_count(0x20))
        self.assertEqual(0, board.command_count(0x21))
        self.assertEqual(1, board.sessions[0].disconnections)

    async def test_unexpected_successor_after_reconnect_is_never_stopped(self):
        board = FakeBoard()
        def successor(index):
            if index == 2:
                board.run_id += 1
                board.revision += 1
        board.on_connect = successor
        with self.assertRaisesRegex(ValueError, "reconnect lost"):
            await self.run_probe(board)
        self.assertEqual(0, board.command_count(0x21))
        self.assertEqual([1, 1], [s.disconnections for s in board.sessions])

    async def test_rebooted_peer_after_reconnect_is_never_stopped(self):
        board = FakeBoard()
        def reboot(index):
            if index == 2:
                board.boot = b"\x08\x07\x06\x05\x04\x03\x02\x01"
        board.on_connect = reboot
        with self.assertRaisesRegex(ValueError, "reconnect lost"):
            await self.run_probe(board)
        self.assertEqual(0, board.command_count(0x21))
        self.assertEqual([1, 1], [s.disconnections for s in board.sessions])

    async def test_lost_authoritative_query_prevents_cleanup_stop(self):
        board = FakeBoard()
        board.failed_queries.update({(2, 1), (2, 2)})
        with self.assertRaisesRegex(ValueError, "status refused"):
            await self.run_probe(board)
        self.assertEqual(0, board.command_count(0x21))
        self.assertEqual([1, 1], [s.disconnections for s in board.sessions])

    async def test_proven_owned_run_is_stopped_after_probe_query_failure(self):
        board = FakeBoard()
        board.failed_queries.add((2, 1))
        with self.assertRaisesRegex(ValueError, "status refused"):
            await self.run_probe(board)
        self.assertEqual(1, board.command_count(0x21))
        self.assertEqual(0, board.state)
        self.assertEqual([1, 1], [s.disconnections for s in board.sessions])

    async def test_cleanup_transport_failure_preserves_original_probe_failure(self):
        board = FakeBoard()
        board.failed_queries.add((2, 1))
        board.reject_cleanup_stop = True
        with self.assertRaisesRegex(ValueError, "status refused"):
            await self.run_probe(board)
        self.assertEqual(1, board.command_count(0x21))
        self.assertEqual([1, 1], [s.disconnections for s in board.sessions])

    async def test_bad_candidate_caps_close_the_transport_before_any_run(self):
        board = FakeBoard()
        board.caps_agent = "0.6.1"
        with self.assertRaisesRegex(ValueError, "candidate chip/version"):
            await self.run_probe(board)
        self.assertEqual(0, board.command_count(0x20))
        self.assertEqual(0, board.command_count(0x21))
        self.assertEqual([1], [s.disconnections for s in board.sessions])


if __name__ == "__main__":
    unittest.main(verbosity=2)
