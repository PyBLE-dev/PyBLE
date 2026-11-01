#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""PBLE/1 §6.1 portable committed-run snapshots through the real dispatcher."""

import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support
import pyble_agent
import pyble_info
import pyble_proto
import pyble_runner
from test_pyble_agent import FakeLink, HELLO_PAYLOAD

QUERY, CHANGED = 0x24, 0x42
RUN, STOP, SOFT = 0x20, 0x21, 0x22
BOOT = bytes.fromhex("0102030405060708")
VECTORS = Path(__file__).parent / "conformance/v070_run_status_vectors.json"


def unpack(body):
    return struct.unpack("<B8sIQBBBB", body)


def metadata(body):
    return unpack(body)[2:]


class SnapshotVectorsTest(unittest.TestCase):
    def test_shared_vectors_encode_and_decode(self):
        vectors = json.loads(VECTORS.read_text())
        for v in vectors["valid"]:
            with self.subTest(name=v["name"]):
                body = pyble_runner.encode_run_status(
                    bytes.fromhex(v["boot_id"]), v["run_id"], v["revision"],
                    v["state"], v["origin"], v["terminal_reason"], v["flags"])
                self.assertEqual(bytes.fromhex(v["hex"]), body)
                self.assertEqual(unpack(body), pyble_runner.decode_run_status(body))

    def test_shared_invalid_vectors_are_rejected(self):
        vectors = json.loads(VECTORS.read_text())
        for v in vectors["invalid"]:
            with self.subTest(name=v["name"]):
                with self.assertRaises(ValueError):
                    pyble_runner.decode_run_status(bytes.fromhex(v["hex"]))

    def test_invalid_boot_identity_fails_closed(self):
        for boot in (b"", b"\0" * 8, b"1234567", b"123456789"):
            with self.subTest(boot=boot):
                with self.assertRaises(ValueError):
                    pyble_runner.Runner(lambda _: None, lambda *_: None,
                                        boot_id=boot)

    def test_fresh_initializations_have_independent_nonzero_tokens(self):
        first = pyble_runner.Runner(lambda _: None, lambda *_: None)
        second = pyble_runner.Runner(lambda _: None, lambda *_: None)
        a, b = first.run_status(), second.run_status()
        self.assertNotEqual(unpack(a)[1], unpack(b)[1])
        self.assertNotEqual(bytes(8), unpack(a)[1])
        self.assertEqual((0, 0, 0, 0, 0, 0), metadata(a))


class AgentStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.link = FakeLink()
        self.agent = pyble_agent.Agent(self.link, self.tmp.name)
        self.link.connect_cb()
        self.send(0x01, HELLO_PAYLOAD)
        self.link.sent[:] = []
        self.next_id = 2

    def send(self, op, payload=b"", request_id=1):
        self.link.message_cb(pyble_proto.encode(pyble_proto.CMD, op,
                                               request_id, payload))
        frames = [pyble_proto.decode(raw) for raw in self.link.sent]
        matched = [f for f in frames if f.type == pyble_proto.RSP
                   and f.opcode == op and f.id == request_id]
        return matched[-1].payload if matched else None

    def query(self):
        self.next_id += 1
        response = self.send(QUERY, request_id=self.next_id)
        self.assertIsNotNone(response, "RUN_STATUS must answer during any run")
        self.assertEqual(0, response[0], "RUN_STATUS is capability advertised")
        self.assertEqual(26, len(response))
        return response[1:]

    def events(self):
        return [pyble_proto.decode(raw).payload for raw in self.link.sent
                if pyble_proto.decode(raw).type == pyble_proto.EVT
                and pyble_proto.decode(raw).opcode == CHANGED]

    def test_capability_is_additive_and_all_info_views_match(self):
        self.assertTrue(self.agent.info_payload().endswith(b"run_status=1\n"))
        self.assertEqual(self.agent.info_payload(), self.link.info_payload)
        self.assertEqual(self.agent.info_payload(), self.send(0x02)[1:])
        self.assertEqual(QUERY, pyble_proto.OPCODES["RUN_STATUS"])
        self.assertEqual(CHANGED, pyble_proto.OPCODES["RUN_STATUS_CHANGED"])

    def test_initial_query_and_malformed_query_do_not_change_state(self):
        before = self.query()
        self.assertEqual((0, 0, 0, 0, 0, 0), metadata(before))
        self.assertNotEqual(bytes(8), unpack(before)[1])
        self.assertEqual(b"\x01", self.send(QUERY, b"unexpected"))
        self.assertEqual(before, self.query())

    def test_no_unsolicited_extension_events_before_opt_in(self):
        self.agent._runner._exec_fn = lambda *_: None
        self.assertEqual(b"\0", self.send(RUN, b"\x01pass"))
        self.agent.poll()
        self.assertEqual([], self.events())
        self.assertEqual((1, 3, 2, 2, 1, 0), metadata(self.query()))

    def test_queued_running_and_completed_snapshots(self):
        self.query()
        seen = []
        self.agent._runner._exec_fn = lambda *_: seen.append(self.query())
        self.assertEqual(b"\0", self.send(RUN, b"\x01pass"))
        queued = self.query()
        self.assertEqual((1, 1, 1, 2, 0, 1), metadata(queued))
        self.agent.poll()
        self.assertEqual((1, 2, 1, 2, 0, 0), metadata(seen[0]))
        self.assertEqual((1, 3, 2, 2, 1, 0), metadata(self.query()))
        self.assertTrue(self.events())
        for body in self.events():
            self.assertEqual(unpack(queued)[1], unpack(body)[1])
        revisions = [unpack(body)[3] for body in self.events()]
        self.assertEqual(sorted(set(revisions)), revisions)

    def test_exception_and_successor_file_run_keep_distinct_identity(self):
        def fail(*_):
            raise RuntimeError("disposable")
        self.agent._runner._exec_fn = fail
        self.send(RUN, b"\x01raise RuntimeError()")
        self.agent.poll()
        failed = self.query()
        self.assertEqual((1, 3, 3, 2, 2, 0), metadata(failed))
        self.agent._runner._exec_fn = lambda *_: None
        self.send(RUN, b"\x00/main.py")
        self.assertEqual((2, 4, 1, 1, 0, 1), metadata(self.query()))
        self.agent.poll()
        self.assertEqual((2, 6, 2, 1, 1, 0), metadata(self.query()))

    def test_rejected_run_and_inactive_stop_are_snapshot_idempotent(self):
        initial = self.query()
        self.send(STOP)
        self.assertEqual(initial, self.query())
        self.assertEqual(b"\x01", self.send(RUN, b"\x07bad"))
        self.assertEqual(initial, self.query())
        self.send(RUN, b"\x01pass")
        queued = self.query()
        self.assertEqual(b"\x07", self.send(RUN, b"\x01pass"))
        self.assertEqual(queued, self.query())

    def test_failed_run_response_restores_previous_committed_snapshot(self):
        self.agent._runner._exec_fn = lambda *_: None
        self.send(RUN, b"\x01pass")
        self.agent.poll()
        prior = self.query()
        send = self.link.send_message
        def reject(msg, **kwargs):
            f = pyble_proto.decode(msg)
            if f.type == pyble_proto.RSP and f.opcode == RUN:
                return False
            return send(msg, **kwargs)
        self.link.send_message = reject
        self.send(RUN, b"\x01pass")
        self.link.send_message = send
        self.assertEqual(prior, self.query())
        self.agent.poll()
        self.assertEqual(prior, self.query())

    def test_response_encoding_failure_rolls_back_snapshot(self):
        before = self.query()
        send = self.link.send_message
        def fail(msg, **kwargs):
            if pyble_proto.decode(msg).opcode == RUN:
                raise RuntimeError("injected transport failure")
            return send(msg, **kwargs)
        self.link.send_message = fail
        with self.assertRaises(RuntimeError):
            self.send(RUN, b"\x01pass")
        self.link.send_message = send
        self.assertEqual(before, self.query())

    def test_stop_before_pickup_commits_once_without_running_code(self):
        seen = []
        self.agent._runner._exec_fn = lambda *_: seen.append(1)
        self.send(RUN, b"\x01pass")
        self.send(STOP)
        stopping = self.query()
        self.assertEqual((1, 2, 1, 2, 0, 3), metadata(stopping))
        self.send(STOP)
        self.assertEqual(stopping, self.query())
        self.agent.poll()
        stopped = self.query()
        self.assertEqual((1, 3, 0, 2, 3, 0), metadata(stopped))
        self.agent.poll()
        self.send(STOP)
        self.assertEqual(stopped, self.query())
        self.assertEqual([], seen)

    def test_stop_while_executing_is_queryable_before_terminal(self):
        seen = []
        def execute(*_):
            self.send(STOP)
            seen.append(self.query())
            raise KeyboardInterrupt()
        self.agent._runner._exec_fn = execute
        self.send(RUN, b"\x01while True: pass")
        self.agent.poll()
        self.assertEqual((1, 3, 1, 2, 0, 2), metadata(seen[0]))
        self.assertEqual((1, 4, 0, 2, 3, 0), metadata(self.query()))

    def test_stopped_terminal_retry_does_not_advance_revision_twice(self):
        self.query()
        self.link.interrupt_terminal_before_publish = True
        self.send(RUN, b"\x01pass")
        self.send(STOP)
        self.agent.poll()
        first = self.query()
        self.agent.poll()
        self.assertEqual(first, self.query())
        self.assertEqual((1, 3, 0, 2, 3, 0), metadata(first))

    def test_disconnect_retires_watch_and_preserves_current_run(self):
        self.query()
        self.send(RUN, b"\x01pass")
        queued = self.query()
        self.link.disconnect_cb()
        self.link.session = 2
        self.link.sent[:] = []
        self.agent._runner._exec_fn = lambda *_: None
        self.agent.poll()
        self.assertEqual([], self.events())
        self.link.connect_cb()
        self.send(0x01, HELLO_PAYLOAD)
        current = self.query()
        self.assertEqual(unpack(queued)[1], unpack(current)[1])
        self.assertEqual((1, 3, 2, 2, 1, 0), metadata(current))

    def test_autorun_is_identified_even_when_admitted_without_connection(self):
        Path(self.tmp.name, "main.py").write_text("pass\n")
        self.agent._config.auto_run = 1
        self.agent._runner._exec_fn = lambda *_: None
        self.assertTrue(self.agent.autorun())
        self.assertEqual((1, 1, 1, 3, 0, 1), metadata(self.query()))
        self.agent.poll()
        self.assertEqual((1, 3, 2, 3, 1, 0), metadata(self.query()))

    def test_counter_exhaustion_refuses_without_reusing_identity(self):
        runner = self.agent._runner
        maximum = pyble_runner.encode_run_status(
            BOOT, 0xffffffff, 4 * 0xffffffff, 2, 1, 1, 0)
        runner._status = maximum
        self.assertEqual(b"\x09", self.send(RUN, b"\x01pass"))
        self.assertEqual(maximum, self.query())

    def test_soft_reboot_closing_precedes_status(self):
        self.query()
        self.send(SOFT)
        self.assertEqual(b"\x07", self.send(QUERY))


if __name__ == "__main__":
    unittest.main(verbosity=2)
