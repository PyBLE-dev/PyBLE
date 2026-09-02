#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""[red] v0.6.1 RUN/stdin isolation contracts.

This suite deliberately pins the new portable console lifecycle before the
production implementation lands.  CONSOLE_INPUT is response-free, so an idle
write cannot report an error; it must instead be discarded.  A live run owns
only bytes admitted during that run, and disconnect clears queued bytes without
ending a run that continues to execute.
"""

from __future__ import annotations

import os
import sys
import unittest


HOST_DIR = os.path.dirname(os.path.abspath(__file__))
if HOST_DIR not in sys.path:
    sys.path.insert(0, HOST_DIR)

import _support  # noqa: E402
import test_pyble_agent as agent_support  # noqa: E402


_support._inject_micropython_guards()
CONSOLE = _support.RedReason("pyble_console", owner="v0.6.1-runtime-engineer")

BIG = 1 << 30


def make_console(testcase):
    cls = CONSOLE.attr(
        testcase,
        "Console",
        "v0.6.1 stdin lifecycle requires the portable Console",
    )
    return cls(
        lambda _stream, _data: None,
        lambda: None,
        clock=lambda: 0,
        tx_capacity=BIG,
        tx_refill_per_ms=BIG,
    )


def require_method(testcase, obj, name):
    testcase.assertTrue(
        hasattr(obj, name),
        "v0.6.1 stdin lifecycle method Console.{}() is missing".format(name),
    )
    return getattr(obj, name)


def drain(testcase, console, limit=300):
    result = bytearray()
    buf = bytearray(1)
    for _ in range(limit):
        count = console.readinto(buf)
        if count is None:
            return bytes(result)
        testcase.assertEqual(count, 1, "dupterm reads remain exactly 1 or None")
        result.append(buf[0])
    testcase.fail("stdin ring did not drain within its fixed bound")


class PortableConsoleBoundaryTests(unittest.TestCase):
    def test_idle_input_is_discarded_without_a_response(self):
        console = make_console(self)
        self.assertIsNone(console.feed_input(b"idle"))
        self.assertEqual(
            drain(self, console),
            b"",
            "CONSOLE_INPUT while no run owns stdin must be silently discarded",
        )

    def test_begin_activates_and_clears_the_new_run_boundary(self):
        console = make_console(self)
        console.feed_input(b"stale-idle")
        require_method(self, console, "begin_input")()
        self.assertEqual(drain(self, console), b"", "RUN admission clears stdin")
        console.feed_input(b"new")
        self.assertEqual(drain(self, console), b"new")

    def test_end_clears_and_returns_to_idle_discard(self):
        console = make_console(self)
        require_method(self, console, "begin_input")()
        console.feed_input(b"old-run")
        require_method(self, console, "end_input")()
        self.assertEqual(drain(self, console), b"", "terminal/STOP clears stdin")
        console.feed_input(b"after-end")
        self.assertEqual(drain(self, console), b"", "ended run cannot accept input")

    def test_disconnect_clear_preserves_a_live_runs_admission(self):
        console = make_console(self)
        require_method(self, console, "begin_input")()
        console.feed_input(b"old-session")
        require_method(self, console, "clear_input")()
        self.assertEqual(drain(self, console), b"", "disconnect drops queued bytes")
        console.feed_input(b"new-session")
        self.assertEqual(
            drain(self, console),
            b"new-session",
            "disconnect does not stop a live run; its successor session may feed it",
        )

    def test_overflow_from_run_one_cannot_reach_run_two(self):
        console = make_console(self)
        require_method(self, console, "begin_input")()
        console.feed_input(b"A" * 256)
        require_method(self, console, "end_input")()
        require_method(self, console, "begin_input")()
        self.assertEqual(drain(self, console), b"")

    def test_end_also_invalidates_a_pending_stop_byte(self):
        console = make_console(self)
        require_method(self, console, "begin_input")()
        self.assertTrue(console.inject_stop())
        require_method(self, console, "end_input")()
        require_method(self, console, "begin_input")()
        self.assertEqual(
            drain(self, console),
            b"",
            "a terminal boundary must not inject the predecessor's STOP into a new run",
        )


class PortableAgentBoundaryTests(agent_support.AgentTestBase):
    """Exercise the real Agent callbacks, not just the Console primitive."""

    def test_agent_discards_idle_console_input(self):
        agent, link = self.new_agent("v0.6.1 idle CONSOLE_INPUT discard")
        agent_support.send(self, link, 0x31, b"idle", id_=201)
        self.assertEqual(drain(self, agent.console), b"")
        self.assertEqual(
            agent_support.rsps(link, opcode=0x31, id_=201),
            [],
            "discard remains fire-and-forget",
        )

    def test_successful_run_admission_opens_fresh_stdin(self):
        agent, link = self.new_agent("v0.6.1 RUN response admission opens stdin")
        agent_support.send(self, link, 0x20, bytes((1,)) + b"pass", id_=202)
        self.assertEqual(agent_support.rsps(link, opcode=0x20, id_=202)[0].payload, b"\x00")
        agent_support.send(self, link, 0x31, b"live", id_=203)
        self.assertEqual(drain(self, agent.console), b"live")

    def test_busy_run_does_not_clear_current_runs_input(self):
        agent, link = self.new_agent("v0.6.1 EBUSY RUN leaves stdin unchanged")
        agent_support.send(self, link, 0x20, bytes((1,)) + b"pass", id_=204)
        agent_support.send(self, link, 0x31, b"keep", id_=205)
        agent_support.send(self, link, 0x20, bytes((1,)) + b"pass", id_=206)
        self.assertEqual(agent_support.rsps(link, opcode=0x20, id_=206)[0].payload, b"\x07")
        self.assertEqual(drain(self, agent.console), b"keep")

    def test_accepted_stop_clears_and_closes_stdin(self):
        agent, link = self.new_agent("v0.6.1 accepted STOP closes stdin")
        agent_support.send(self, link, 0x20, bytes((1,)) + b"pass", id_=207)
        agent_support.send(self, link, 0x31, b"stale", id_=208)
        agent_support.send(self, link, 0x21, id_=209)
        self.assertEqual(agent_support.rsps(link, opcode=0x21, id_=209)[0].payload, b"\x00")
        self.assertEqual(drain(self, agent.console), b"")
        agent_support.send(self, link, 0x31, b"late", id_=210)
        self.assertEqual(drain(self, agent.console), b"")

    def test_disconnect_clears_but_keeps_pending_run_input_active(self):
        agent, link = self.new_agent("v0.6.1 disconnect stdin boundary")
        agent_support.send(self, link, 0x20, bytes((1,)) + b"pass", id_=211)
        agent_support.send(self, link, 0x31, b"old-session", id_=212)
        link.disconnect_cb()
        self.assertEqual(drain(self, agent.console), b"")
        link.session += 1
        link.connect_cb()
        agent_support.send(
            self, link, agent_support.CMD_OPCODES["HELLO"],
            agent_support.HELLO_PAYLOAD, id_=213)
        hello = agent_support.rsps(
            link, opcode=agent_support.CMD_OPCODES["HELLO"], id_=213)
        self.assertEqual(len(hello), 1)
        self.assertEqual(hello[0].payload[0], agent_support.OK)
        link.sent[:] = []
        agent_support.send(self, link, 0x31, b"new-session", id_=214)
        self.assertEqual(drain(self, agent.console), b"new-session")

    def test_natural_terminal_clears_and_closes_stdin(self):
        agent, link = self.new_agent("v0.6.1 terminal stdin boundary")
        agent_support.send(self, link, 0x20, bytes((1,)) + b"pass", id_=215)
        agent_support.send(self, link, 0x31, b"unread", id_=216)
        agent.poll()
        self.assertEqual(drain(self, agent.console), b"")
        agent_support.send(self, link, 0x31, b"after-terminal", id_=217)
        self.assertEqual(drain(self, agent.console), b"")


if __name__ == "__main__":
    unittest.main(verbosity=2)
