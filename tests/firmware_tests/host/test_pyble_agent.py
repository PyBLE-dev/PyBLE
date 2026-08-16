#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Host tests for the F-25/F-27 rpi-pico2-w agent wiring (port spec
# P1/P2/P3/P4;
# plan PART 3 test 8). Sole [red] author: firmware-test-author. Production
# module owner (HAND-OFF for [green]): agent-engineer ->
# firmware/pyble/pyble_agent.py (NEW; the init_agent()-equivalent wiring).
#
# FROZEN references: protocol.md §3/§4/§8 (the full opcode + status sets),
# §5 (PUT/GET wire, F-10 resume: link drop resets in-RAM transfer state but the
# jailed <dest>.pbltmp persists), §6 (STOP -> RSP{OK}, active STOP's response
# precedes interrupt delivery, idle STOP emits no RUN_STATE);
# ports/rpi-pico2-w.md P1 (has_identify=0 -> IDENTIFY EUNSUPPORTED), P2
# (transfers during an active RUN -> EBUSY; *_BEGIN validation/reservation is
# answered inline at dispatch, only streaming/window pumping is supervisor
# work), P4 (SOFT_REBOOT: RSP{OK} first, then the injected reset callable from
# the supervisor after a bounded TX-flush delay).
#
# Env-reality: the BLE link is the FakeLink below, which mimics ONLY the frozen
# BleLink seam (on_message/on_connect/on_disconnect registration,
# send_message, set_info_payload, set_adv_name, mtu, mac) — no BTstack
# behaviour is faked, and the Agent MUST NOT start the link (main() owns
# bring-up; FakeLink.start raises to pin that).
#
# ---------------------------------------------------------------------------
# INTERFACE PINNED BY THIS [red] TEST (agent-engineer implements to it):
#   pyble_agent.Agent(link, fs_root, unique_id=bytes, reset=callable,
#                     clock=callable, notify=callable, arm_reset=callable)
#     - the host-testable init_agent() equivalent. The constructor wires
#       everything: builds the Dispatcher, registers a handler for EVERY §4
#       CMD opcode, registers link.on_message(cb) so cb(msg) ->
#       dispatch -> link.send_message(rsp), registers link.on_disconnect(cb)
#       (resets in-RAM transfer state, keeps .pbltmp — F-10), and publishes
#       the caps payload via link.set_info_payload. It NEVER calls
#       link.start() and NEVER touches os.dupterm (device-only, main()).
#     - unique_id: the machine.unique_id() bytes injected for host runs
#       (device_id derivation, P1); reset: the machine.reset seam (P4);
#       clock() -> int milliseconds (TX-flush delay, pacing).
#   .emit(opcode, payload) -> None    # encode EVT (TYPE=0x03, ID=0) + send
#   .poll() -> None                   # ONE supervisor iteration: run mailbox,
#                                     # transfer pump, deferred SOFT_REBOOT reset
# ---------------------------------------------------------------------------

import os
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

# Guard-inject the MicroPython module surfaces before importing the scaffolds
# (tolerant: the `micropython` guard may not exist yet — never fake behaviour).
_support._inject_micropython_guards()
try:
    import importlib as _importlib

    if "micropython" not in sys.modules:
        sys.modules["micropython"] = _importlib.import_module("micropython")
except ImportError:
    pass

import pyble_proto  # noqa: E402  (S2-green frame codec; used to author frames)

AGENT = _support.RedReason("pyble_agent", owner="agent-engineer")

OK, EBADREQ, EBUSY, EUNSUPPORTED = 0x00, 0x01, 0x07, 0x0A
CMD, RSP, EVT = 0x01, 0x02, 0x03

# §4: every CMD-direction opcode the agent MUST register a handler for.
CMD_OPCODES = {
    "HELLO": 0x01, "DEVICE_INFO": 0x02,
    "FILE_LIST": 0x10, "FILE_STAT": 0x11, "FILE_GET_BEGIN": 0x12,
    "FILE_PUT_BEGIN": 0x15, "FILE_PUT_DATA": 0x16, "FILE_PUT_END": 0x17,
    "FILE_DELETE": 0x18, "MKDIR": 0x19, "FILE_RENAME": 0x1A,
    "RUN": 0x20, "STOP": 0x21, "SOFT_REBOOT": 0x22, "SET_AUTORUN": 0x23,
    "CONSOLE_INPUT": 0x31,
    "SET_LABEL": 0x50, "SET_IDENTIFY_LED": 0x51, "IDENTIFY": 0x52,
}
NO_RSP_OPCODES = {0x16, 0x31}   # CMD-only: the handler suppresses the RSP (§4)

UNIQUE_ID = b"\x12\x34\x56\x78\x9a\xbc\x9f\x3a"   # -> device_id "9F3A"


class FakeLink:
    """The frozen BleLink seam only — never BTstack behaviour."""

    def __init__(self, order=None):
        self.sent = []
        self.order = order            # optional shared journal for ordering
        self.message_cb = None
        self.connect_cb = None
        self.disconnect_cb = None
        self.info_payload = None
        self.adv_name = None
        self.interrupt_terminal_before_publish = False
        self.interrupt_terminal_after_publish = False
        self.omit_terminal = False
        self.session = 1
        self.replace_session_before_terminal_retry = False

    def on_message(self, cb):
        self.message_cb = cb

    def on_connect(self, cb):
        self.connect_cb = cb

    def on_disconnect(self, cb):
        self.disconnect_cb = cb

    def session_token(self):
        return self.session

    def send_message(self, msg, on_published=None, expected_session=None):
        msg = bytes(msg)
        frame = pyble_proto.decode(msg)
        terminal_idle = (frame.type == EVT and frame.opcode == 0x40
                         and frame.payload == b"\x00")
        if (expected_session is not None
                and expected_session != self.session_token()):
            return False
        if terminal_idle and self.omit_terminal:
            return False
        if terminal_idle and self.interrupt_terminal_before_publish:
            self.interrupt_terminal_before_publish = False
            if self.replace_session_before_terminal_retry:
                self.session += 1
            raise KeyboardInterrupt()
        self.sent.append(msg)
        if self.order is not None:
            self.order.append(("tx", msg))
        if on_published is not None:
            on_published()
        if terminal_idle and self.interrupt_terminal_after_publish:
            self.interrupt_terminal_after_publish = False
            raise KeyboardInterrupt()
        return True

    def set_info_payload(self, payload):
        self.info_payload = bytes(payload)

    def set_adv_name(self, name):
        self.adv_name = name

    def mtu(self):
        return 247

    def mac(self):
        return b"\x00" * 6

    def start(self, *a, **k):
        raise AssertionError(
            "Agent must NOT start the link — main() owns BLE bring-up")


def crc_ok(frame):
    return pyble_proto.crc32(frame[:-4]) == int.from_bytes(frame[-4:], "little")


def send(testcase, link, opcode, payload=b"", id_=1):
    testcase.assertIsNotNone(
        link.message_cb,
        "the Agent constructor MUST register link.on_message (wiring)")
    link.message_cb(pyble_proto.encode(CMD, opcode, id_, payload))


def pump(agent, n=3, now=None, step=1000):
    for _ in range(n):
        if now is not None:
            now[0] += step
        agent.poll()


def decoded(link):
    return [pyble_proto.decode(m) for m in link.sent]


def rsps(link, opcode=None, id_=None):
    out = []
    for f in decoded(link):
        if f.type != RSP:
            continue
        if opcode is not None and f.opcode != opcode:
            continue
        if id_ is not None and f.id != id_:
            continue
        out.append(f)
    return out


def evts(link, opcode=None):
    return [f for f in decoded(link)
            if f.type == EVT and (opcode is None or f.opcode == opcode)]


def run_states(link):
    return [f.payload[0] for f in evts(link, opcode=0x40) if f.payload]


def p_put_begin(total, crc, path):
    p = path.encode("utf-8")
    return struct.pack("<II", total, crc) + struct.pack("<H", len(p)) + p


def p_get_begin(offset, path):
    p = path.encode("utf-8")
    return struct.pack("<I", offset) + struct.pack("<H", len(p)) + p


class AgentTestBase(unittest.TestCase):
    CRIT = "F-25 agent wiring"

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pyble_agent_test_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.now = [0]
        self.resets = []

    def new_agent(self, criterion=None, order=None, reset=None, notify=None,
                  arm_reset=None):
        cls = AGENT.attr(self, "Agent", criterion or self.CRIT)
        link = FakeLink(order)
        kwargs = {
            "unique_id": UNIQUE_ID,
            "reset": (reset if reset is not None
                      else (lambda: self.resets.append(1))),
            "clock": lambda: self.now[0],
            "notify": notify,
        }
        if arm_reset is not None:
            kwargs["arm_reset"] = arm_reset
        agent = cls(link, self.root, **kwargs)
        return agent, link


class DispatchWiringTest(AgentTestBase):
    """on_message -> Dispatcher -> send_message; unknown opcode answered
    EUNSUPPORTED by the existing pyble_proto.Dispatcher (FR-PROTO-9)."""

    def test_unknown_opcode_round_trips_eunsupported(self):
        agent, link = self.new_agent("F-25 dispatch wiring")
        send(self, link, 0x7F, id_=11)          # not a §4 opcode
        frames = rsps(link, opcode=0x7F, id_=11)
        self.assertEqual(len(frames), 1,
                         "an unknown opcode MUST be answered with exactly one "
                         "RSP via link.send_message")
        self.assertEqual(frames[0].payload[0], EUNSUPPORTED)
        self.assertTrue(crc_ok(link.sent[-1]),
                        "every outbound frame carries a valid §3.1 CRC-32")

    def test_disconnect_hook_is_registered(self):
        agent, link = self.new_agent("F-25 disconnect hook wiring")
        self.assertIsNotNone(
            link.disconnect_cb,
            "the Agent constructor MUST register link.on_disconnect "
            "(F-10 in-RAM reset hook)")


class AllOpcodesRegisteredTest(AgentTestBase):
    """P1/§4: every §4 CMD opcode has a registered handler — none may fall
    through to the Dispatcher's EUNSUPPORTED default. IDENTIFY is the one
    opcode whose REGISTERED handler answers EUNSUPPORTED (has_identify=0)."""

    def test_every_cmd_opcode_is_registered(self):
        for name, op in sorted(CMD_OPCODES.items(), key=lambda kv: kv[1]):
            with self.subTest(opcode=name):
                agent, link = self.new_agent(
                    "F-25/§4 handler registered: {}".format(name))
                send(self, link, op, id_=7)
                pump(agent, 2, self.now)
                answers = rsps(link, opcode=op, id_=7)
                if op == CMD_OPCODES["IDENTIFY"]:
                    # P1: has_identify=0 -> the handler itself says so.
                    self.assertEqual(len(answers), 1,
                                     "IDENTIFY MUST be answered (registered)")
                    self.assertEqual(answers[0].payload[0], EUNSUPPORTED,
                                     "IDENTIFY -> EUNSUPPORTED while "
                                     "has_identify=0 (P1)")
                elif op in NO_RSP_OPCODES:
                    for f in answers:
                        self.assertNotEqual(
                            f.payload[0], EUNSUPPORTED,
                            "{} is CMD-only: an EUNSUPPORTED RSP means it was "
                            "never registered".format(name))
                else:
                    self.assertEqual(len(answers), 1,
                                     "{} MUST be answered with exactly one RSP "
                                     "echoing the request id".format(name))
                    self.assertNotEqual(
                        answers[0].payload[0], EUNSUPPORTED,
                        "{} answered EUNSUPPORTED — no handler is registered "
                        "for it".format(name))


class EmitTest(AgentTestBase):
    """emit() is the agent's EVT path: TYPE=EVT, ID=0, valid CRC (§3.1)."""

    def test_emit_sends_an_evt_frame(self):
        agent, link = self.new_agent("F-25 EVT emit")
        agent.emit(0x40, b"\x01")
        self.assertTrue(link.sent, "emit MUST call link.send_message")
        f = pyble_proto.decode(link.sent[-1])
        self.assertEqual(f.type, EVT)
        self.assertEqual(f.opcode, 0x40)
        self.assertEqual(f.id, 0, "EVT uses ID=0 (§3.1)")
        self.assertEqual(f.payload, b"\x01")
        self.assertTrue(crc_ok(link.sent[-1]))


class DeviceInfoWiringTest(AgentTestBase):
    """§7 plumbing at agent altitude: DEVICE_INFO answers [OK][caps text] with
    the port identity, and the INFO characteristic payload was published."""

    def test_device_info_carries_the_port_identity(self):
        agent, link = self.new_agent("F-25/P1 DEVICE_INFO wiring")
        send(self, link, CMD_OPCODES["DEVICE_INFO"], id_=6)
        pump(agent, 2, self.now)
        answers = rsps(link, opcode=0x02, id_=6)
        self.assertEqual(len(answers), 1)
        payload = answers[0].payload
        self.assertEqual(payload[0], OK)
        self.assertIn(b"chip=rpi-pico2-w", payload,
                      "the port's frozen chip token (P1)")
        # Frozen §7 serialization (2026-07-02): integers are decimal — the
        # reference agent emits `proto=1` (pble_info.c `proto=%d`; the app
        # parses it with intOf('proto'); test_pyble_info_rp2 pins "1").
        self.assertIn(b"proto=1\n", payload)

    def test_info_characteristic_payload_published(self):
        agent, link = self.new_agent("F-25/P1 INFO payload published")
        self.assertIsNotNone(
            link.info_payload,
            "the constructor MUST publish the caps payload via "
            "link.set_info_payload (§2: INFO read == DEVICE_INFO)")
        self.assertIn(b"chip=rpi-pico2-w", link.info_payload)


class DisconnectResetsPutStateTest(AgentTestBase):
    """F-10/§5: a link drop mid-PUT resets the in-RAM transfer state but the
    jailed <dest>.pbltmp persists on flash (resume seed)."""

    def test_disconnect_frees_the_slot_but_keeps_pbltmp(self):
        crit = "F-10 disconnect keeps .pbltmp, resets RAM state"
        with open(os.path.join(self.root, "g.txt"), "wb") as fh:
            fh.write(b"hello world")           # 11 bytes, for the later GET
        agent, link = self.new_agent(crit)

        # Open an upload and land one in-order window chunk.
        body = b"ABCDEFGH"
        send(self, link, 0x15,
             p_put_begin(len(body), pyble_proto.crc32(body), "/f.txt"), id_=2)
        pump(agent, 2, self.now)
        begin = rsps(link, opcode=0x15, id_=2)
        self.assertEqual(len(begin), 1)
        self.assertEqual(begin[0].payload[0], OK)
        self.assertEqual(begin[0].payload[1:5], struct.pack("<I", 0),
                         "a fresh PUT_BEGIN resumes at offset 0 (§5)")

        send(self, link, 0x16, struct.pack("<I", 0) + body[:4], id_=3)
        pump(agent, 2, self.now)
        acks = evts(link, opcode=0x41)
        self.assertTrue(acks, "an in-order chunk MUST be ACKed (0x41 EVT)")
        self.assertEqual(acks[-1].payload, struct.pack("<I", 4),
                         "cumulative ACK = highest contiguous byte written")

        # Link drop: in-RAM state resets, the temp file stays (F-10).
        self.assertIsNotNone(link.disconnect_cb, "disconnect hook not wired")
        link.disconnect_cb()
        temp = os.path.join(self.root, "f.txt.pbltmp")
        self.assertTrue(os.path.exists(temp),
                        "the jailed <dest>.pbltmp MUST survive the disconnect "
                        "(it seeds the §5 resume_offset)")

        # The single-transfer slot MUST be free again: a GET now succeeds.
        send(self, link, 0x12, p_get_begin(0, "/g.txt"), id_=5)
        pump(agent, 2, self.now)
        get = rsps(link, opcode=0x12, id_=5)
        self.assertEqual(len(get), 1)
        self.assertEqual(get[0].payload[0], OK,
                         "the disconnect MUST reset the in-RAM transfer state "
                         "— a new *_BEGIN is not EBUSY")
        self.assertEqual(get[0].payload[1:5], struct.pack("<I", 11),
                         "GET_BEGIN OK carries [total_size:u32] (§5)")


class TransfersDuringRunEbusyTest(AgentTestBase):
    """P2: while a RUN is active (reserved), FILE_GET_BEGIN / FILE_PUT_BEGIN
    are refused EBUSY inline (legal §8; concurrency returns with OI-P5)."""

    def test_get_and_put_begin_are_ebusy_during_a_run(self):
        crit = "F-25/P2 transfers-during-RUN EBUSY"
        with open(os.path.join(self.root, "g.txt"), "wb") as fh:
            fh.write(b"hello world")
        agent, link = self.new_agent(crit)

        send(self, link, 0x20, bytes((1,)) + b"x = 1", id_=1)
        run = rsps(link, opcode=0x20, id_=1)
        self.assertEqual(len(run), 1, "RUN is answered inline (P2 fast op)")
        self.assertEqual(run[0].payload[0], OK)

        # NO poll: the run stays reserved/active while these arrive.
        send(self, link, 0x12, p_get_begin(0, "/g.txt"), id_=2)
        get = rsps(link, opcode=0x12, id_=2)
        self.assertEqual(len(get), 1,
                         "*_BEGIN reservation is decided inline at dispatch")
        self.assertEqual(get[0].payload[0], EBUSY,
                         "FILE_GET_BEGIN during an active RUN -> EBUSY (P2)")

        send(self, link, 0x15, p_put_begin(4, 0, "/h.txt"), id_=3)
        put = rsps(link, opcode=0x15, id_=3)
        self.assertEqual(len(put), 1)
        self.assertEqual(put[0].payload[0], EBUSY,
                         "FILE_PUT_BEGIN during an active RUN -> EBUSY (P2)")


class SoftRebootOrderingTest(AgentTestBase):
    """P4: SOFT_REBOOT answers RSP{OK} FIRST; the injected reset callable runs
    from the supervisor after a bounded TX-flush delay — never before the RSP
    has been handed to the link."""

    def test_rsp_is_sent_before_the_reset_callable_runs(self):
        crit = "F-25/P4 RSP-before-reset"
        order = []
        agent, link = self.new_agent(
            crit, order=order, reset=lambda: order.append(("reset",)))

        send(self, link, 0x22, id_=9)
        answers = rsps(link, opcode=0x22, id_=9)
        self.assertEqual(len(answers), 1, "SOFT_REBOOT MUST answer inline")
        self.assertEqual(answers[0].payload[0], OK)

        pump(agent, 10, self.now, step=1000)   # bounded flush delay elapses
        resets = [i for i, e in enumerate(order) if e == ("reset",)]
        self.assertEqual(len(resets), 1,
                         "the injected reset seam MUST run exactly once "
                         "within the bounded TX-flush delay (P4)")
        rsp_idx = None
        for i, e in enumerate(order):
            if e[0] == "tx":
                f = pyble_proto.decode(e[1])
                if f.type == RSP and f.opcode == 0x22 and f.id == 9:
                    rsp_idx = i
                    break
        self.assertIsNotNone(rsp_idx, "the SOFT_REBOOT RSP never left the agent")
        self.assertLess(rsp_idx, resets[0],
                        "the RSP{OK} MUST be handed to the link BEFORE the "
                        "reset callable runs (P4)")

    def test_active_run_rsp_is_sent_before_interrupt_notify(self):
        crit = "F-27/P4 active SOFT_REBOOT RSP-before-interrupt"
        order = []
        agent, link = self.new_agent(
            crit, order=order, notify=lambda: order.append(("notify",)))

        send(self, link, 0x20, bytes((1,)) + b"while True: pass", id_=10)
        self.assertEqual(rsps(link, opcode=0x20, id_=10)[0].payload[0], OK)
        # The host cannot run Agent.poll concurrently with a command. Mark the
        # already-reserved runner at the exact executing seam this test targets.
        agent._runner._executing = True
        order[:] = []

        send(self, link, 0x22, id_=11)
        answers = rsps(link, opcode=0x22, id_=11)
        self.assertEqual(len(answers), 1, "SOFT_REBOOT MUST answer inline")
        self.assertEqual(answers[0].payload[0], OK)
        self.assertEqual(sum(1 for event in order if event == ("notify",)), 1,
                         "an active SOFT_REBOOT MUST arm exactly one interrupt")
        rsp_idx = next(
            i for i, event in enumerate(order)
            if event[0] == "tx"
            and pyble_proto.decode(event[1]).type == RSP
            and pyble_proto.decode(event[1]).opcode == 0x22
            and pyble_proto.decode(event[1]).id == 11)
        notify_idx = order.index(("notify",))
        self.assertLess(
            rsp_idx, notify_idx,
            "active SOFT_REBOOT MUST hand RSP{OK} to BLE TX before it arms "
            "the KeyboardInterrupt (P4)")


class ActiveStopOrderingTest(AgentTestBase):
    """P3: active STOP must hand RSP{OK} to BLE before arming the interrupt.

    On rp2 the BLE callback is synchronous. Reversing these two actions lets the
    pending KeyboardInterrupt unwind inside the protected BLE IRQ, losing the
    response and disabling the IRQ handler before the user run is stopped.
    """

    def test_rsp_is_sent_before_interrupt_notify(self):
        crit = "F-27/P3 active STOP RSP-before-interrupt"
        order = []
        agent, link = self.new_agent(
            crit, order=order, notify=lambda: order.append(("notify",)))

        # Reserve a tight run, then mark the exact executing seam: the host
        # cannot call Agent.poll concurrently with delivery of this command.
        send(self, link, 0x20, bytes((1,)) + b"while True: pass", id_=10)
        self.assertEqual(rsps(link, opcode=0x20, id_=10)[0].payload[0], OK)
        agent._runner._executing = True
        order[:] = []

        send(self, link, 0x21, id_=11)
        answers = rsps(link, opcode=0x21, id_=11)
        self.assertEqual(len(answers), 1, "STOP MUST answer exactly once")
        self.assertEqual(answers[0].payload[0], OK)
        self.assertEqual(sum(1 for event in order if event == ("notify",)), 1,
                         "an active STOP MUST arm exactly one interrupt")
        rsp_idx = next(
            i for i, event in enumerate(order)
            if event[0] == "tx"
            and pyble_proto.decode(event[1]).type == RSP
            and pyble_proto.decode(event[1]).opcode == 0x21
            and pyble_proto.decode(event[1]).id == 11)
        notify_idx = order.index(("notify",))
        self.assertLess(
            rsp_idx, notify_idx,
            "active STOP MUST hand RSP{OK} to BLE TX before it arms the "
            "KeyboardInterrupt (P3)")


class ScheduledDuptermNotifyTest(unittest.TestCase):
    """P3: creation of the pending KBI happens after the synchronous BLE IRQ.

    The zero-arg console seam must enqueue the native os.dupterm_notify callable
    itself; it must not invoke that callable inline in the BTstack callback.
    """

    def test_native_dupterm_notify_is_enqueued_not_called_inline(self):
        factory = AGENT.attr(
            self, "_make_scheduled_dupterm_notify",
            "F-27/P3 os.dupterm_notify deferred out of synchronous BLE IRQ")
        scheduled = []
        native_calls = []

        def schedule(callback, arg):
            scheduled.append((callback, arg))

        def native_notify(arg):
            native_calls.append(arg)

        notify = factory(schedule, native_notify)
        notify()
        self.assertEqual(native_calls, [],
                         "the BLE IRQ path MUST NOT call os.dupterm_notify inline")
        self.assertEqual(scheduled, [(native_notify, None)],
                         "enqueue the native callback directly with argument None")

        callback, arg = scheduled.pop()
        callback(arg)
        self.assertEqual(native_calls, [None],
                         "the scheduled native callback remains executable")


class ScheduledDuptermRetryTest(unittest.TestCase):
    """P3 print-flood recovery is deliberately two scheduler checkpoints:
    cp1 runs a locked trampoline; cp2 runs native dupterm_notify."""

    def test_retry_enqueues_trampoline_then_native_notify(self):
        factory = AGENT.attr(
            self, "_make_scheduled_dupterm_retry",
            "F-27/P3 two-stage dupterm STOP retry")
        scheduled = []
        native_calls = []
        failures = []

        def schedule(callback, arg):
            scheduled.append((callback, arg))

        def native_notify(arg):
            native_calls.append(arg)

        retry = factory(schedule, native_notify,
                        lambda: failures.append("failure"))
        retry()
        self.assertEqual(len(scheduled), 1)
        trampoline, arg = scheduled.pop(0)
        self.assertIsNot(trampoline, native_notify,
                         "cp1 must not create the pending KBI")
        trampoline(arg)
        self.assertEqual(native_calls, [])
        self.assertEqual(scheduled, [(native_notify, None)],
                         "locked cp1 queues native notify for cp2")
        callback, arg = scheduled.pop(0)
        callback(arg)
        self.assertEqual(native_calls, [None])
        self.assertEqual(failures, [])

    def test_native_admission_failure_inside_trampoline_uses_fail_safe(self):
        factory = AGENT.attr(
            self, "_make_scheduled_dupterm_retry",
            "F-27/P3 retry second-stage admission fail-safe")
        scheduled = []
        attempts = [0]
        failures = []

        class ResetNow(BaseException):
            pass

        def schedule(callback, arg):
            attempts[0] += 1
            if attempts[0] == 2:
                raise RuntimeError("queue filled before native stage")
            scheduled.append((callback, arg))

        def fail():
            failures.append("reset")
            raise ResetNow()

        retry = factory(schedule, lambda _arg: None, fail)
        retry()
        trampoline, arg = scheduled.pop(0)
        with self.assertRaises(ResetNow):
            trampoline(arg)
        self.assertEqual(failures, ["reset"])


class PrePickupControlCancellationTest(AgentTestBase):
    """P2/P3/P4: accepted control between RUN RSP and supervisor pickup
    cancels the mailbox item without scheduling a VM interrupt or touching the
    source. SOFT_REBOOT's normal deferred reset remains serviceable."""

    SOURCE = bytes((1,)) + b"raise RuntimeError('reserved source executed')"

    def test_stop_before_pickup_emits_only_idle_without_notify(self):
        order = []
        agent, link = self.new_agent(
            "F-27/P2 STOP before pickup", order=order,
            notify=lambda: order.append(("notify",)))
        send(self, link, 0x20, self.SOURCE, id_=60)
        order[:] = []

        send(self, link, 0x21, id_=61)
        agent.poll()

        self.assertNotIn(("notify",), order,
                         "reserved source needs cancellation, not a VM interrupt")
        self.assertEqual(run_states(link), [0],
                         "pre-pickup STOP emits idle only; source never starts")

    def test_soft_reboot_before_pickup_cancels_then_services_reset(self):
        order = []
        agent, link = self.new_agent(
            "F-27/P4 SOFT_REBOOT before pickup", order=order,
            notify=lambda: order.append(("notify",)),
            reset=lambda: order.append(("reset",)))
        send(self, link, 0x20, self.SOURCE, id_=62)
        order[:] = []

        send(self, link, 0x22, id_=63)
        agent.poll()                    # consume cancelled RUN; deadline not due
        self.now[0] = 250
        agent.poll()                    # service the deferred reset

        self.assertNotIn(("notify",), order,
                         "reserved source needs cancellation, not a VM interrupt")
        self.assertEqual(run_states(link), [0],
                         "pre-pickup SOFT_REBOOT emits idle only")
        self.assertEqual(order.count(("reset",)), 1,
                         "cancelled pickup MUST NOT strand the reboot deadline")


class InterruptIntentExceptionSafetyTest(AgentTestBase):
    """P3: the command-local post-RSP intent is cleared on every exceptional
    dispatch/encode/send exit and can never fire on a later command."""

    def test_dispatch_exception_clears_preexisting_intent(self):
        notifies = []
        agent, link = self.new_agent(
            "F-27/P3 dispatcher exception clears intent",
            notify=lambda: notifies.append(1))
        real_dispatch = agent._dispatcher.on_message
        agent._interrupt_after_rsp = True

        def fail_dispatch(msg):
            raise RuntimeError("deterministic dispatch failure")

        agent._dispatcher.on_message = fail_dispatch
        try:
            with self.assertRaisesRegex(RuntimeError, "dispatch failure"):
                send(self, link, 0x01, id_=70)
        finally:
            agent._dispatcher.on_message = real_dispatch

        send(self, link, 0x01, id_=71)
        self.assertEqual(notifies, [],
                         "a later HELLO MUST NOT inherit stale interrupt intent")

    def test_response_encode_exception_clears_stop_intent(self):
        notifies = []
        agent, link = self.new_agent(
            "F-27/P3 encode exception clears STOP intent",
            notify=lambda: notifies.append(1))
        send(self, link, 0x20, bytes((1,)) + b"x = 1", id_=72)
        agent._runner._executing = True
        real_encode = pyble_proto.encode

        def fail_stop_rsp(type_, opcode, id_, payload=b""):
            if type_ == RSP and opcode == 0x21 and id_ == 73:
                raise RuntimeError("deterministic encode failure")
            return real_encode(type_, opcode, id_, payload)

        pyble_proto.encode = fail_stop_rsp
        try:
            with self.assertRaisesRegex(RuntimeError, "encode failure"):
                send(self, link, 0x21, id_=73)
        finally:
            pyble_proto.encode = real_encode
        agent._runner._executing = False

        send(self, link, 0x01, id_=74)
        self.assertEqual(notifies, [],
                         "encode failure MUST clear the STOP post-RSP intent")

    def test_response_send_exception_clears_stop_intent(self):
        notifies = []
        agent, link = self.new_agent(
            "F-27/P3 send exception clears STOP intent",
            notify=lambda: notifies.append(1))
        send(self, link, 0x20, bytes((1,)) + b"x = 1", id_=75)
        agent._runner._executing = True
        real_send = link.send_message

        def fail_stop_send(msg):
            frame = pyble_proto.decode(msg)
            if frame.type == RSP and frame.opcode == 0x21 and frame.id == 76:
                raise RuntimeError("deterministic send failure")
            real_send(msg)

        link.send_message = fail_stop_send
        try:
            with self.assertRaisesRegex(RuntimeError, "send failure"):
                send(self, link, 0x21, id_=76)
        finally:
            link.send_message = real_send
        agent._runner._executing = False

        send(self, link, 0x01, id_=77)
        self.assertEqual(notifies, [],
                         "send failure MUST clear the STOP post-RSP intent")


class _ResetNow(BaseException):
    """Host sentinel for the device's non-returning machine.reset seam."""


class ControlCommitTransactionTest(AgentTestBase):
    """P3/P4: STOP/SOFT effects commit only after response handoff.

    A failed encode/send leaves the reserved run, VM, reboot deadline, and
    hardware alarm exactly as they were before the command.
    """

    def test_reserved_stop_encode_failure_leaves_source_runnable(self):
        agent, link = self.new_agent(
            "F-27/P3 STOP encode failure rolls back control")
        source = bytes((1,)) + b"x = 1"
        send(self, link, 0x20, source, id_=90)
        real_encode = pyble_proto.encode

        def fail_stop_rsp(type_, opcode, id_, payload=b""):
            if type_ == RSP and opcode == 0x21 and id_ == 91:
                raise RuntimeError("deterministic STOP encode failure")
            return real_encode(type_, opcode, id_, payload)

        pyble_proto.encode = fail_stop_rsp
        try:
            with self.assertRaisesRegex(RuntimeError, "STOP encode failure"):
                send(self, link, 0x21, id_=91)
        finally:
            pyble_proto.encode = real_encode

        agent.poll()
        self.assertEqual(run_states(link), [1, 2],
                         "unacknowledged STOP MUST NOT cancel reserved source")
        self.assertIsNone(agent._reboot_at)

    def test_reserved_soft_send_failure_leaves_run_and_deadline_unchanged(self):
        agent, link = self.new_agent(
            "F-27/P4 SOFT send failure rolls back control")
        send(self, link, 0x20, bytes((1,)) + b"x = 2", id_=92)
        real_send = link.send_message

        def fail_soft_rsp(msg):
            frame = pyble_proto.decode(msg)
            if frame.type == RSP and frame.opcode == 0x22 and frame.id == 93:
                raise RuntimeError("deterministic SOFT send failure")
            real_send(msg)

        link.send_message = fail_soft_rsp
        try:
            with self.assertRaisesRegex(RuntimeError, "SOFT send failure"):
                send(self, link, 0x22, id_=93)
        finally:
            link.send_message = real_send

        self.assertIsNone(agent._reboot_at,
                          "unacknowledged SOFT MUST NOT create a deadline")
        agent.poll()
        self.assertEqual(run_states(link), [1, 2],
                         "unacknowledged SOFT MUST NOT cancel reserved source")
        self.assertEqual(self.resets, [])


class TerminalInterruptRecoveryTest(AgentTestBase):
    """P3/P4: a deferred KBI at either side of the stopped transition is
    recovered idempotently by Agent.poll: one IDLE event and no RUNNING wedge.
    """

    def _exercise_transition_cut(self, after_state_change):
        order = []
        agent, link = self.new_agent(
            "F-27/P3 post-exec KBI terminal recovery", order=order,
            notify=lambda: order.append(("notify",)),
            reset=lambda: order.append(("reset",)))
        send(self, link, 0x20, bytes((1,)) + b"x = 3", id_=94)
        real_stopped = agent._runner.rsm.on_stopped
        injected = [False]

        def interrupt_at_transition():
            if not injected[0]:
                injected[0] = True
                if after_state_change:
                    real_stopped()
                raise KeyboardInterrupt()
            return real_stopped()

        def acknowledge_soft_then_return(mode, data):
            send(self, link, 0x22, id_=95)

        agent._runner.rsm.on_stopped = interrupt_at_transition
        agent._runner._exec_fn = acknowledge_soft_then_return
        agent.poll()

        self.assertEqual(run_states(link), [1, 0],
                         "post-exec KBI MUST publish exactly one terminal idle")
        self.assertEqual(agent._runner.rsm.events.count(0), 1,
                         "idempotent recovery MUST transition to idle once")
        self.assertNotEqual(agent._runner.rsm.state, 1,
                            "escaped KBI MUST NOT strand the RSM in RUNNING")
        self.assertFalse(agent._runner.is_executing())
        self.now[0] = 250
        agent.poll()
        self.assertEqual(order.count(("reset",)), 1,
                         "terminal recovery MUST leave SOFT reset serviceable")

    def test_interrupt_before_stopped_transition_recovers_once(self):
        self._exercise_transition_cut(after_state_change=False)

    def test_interrupt_after_state_before_idle_publication_recovers_once(self):
        self._exercise_transition_cut(after_state_change=True)

    def _exercise_publication_cut(self, after_publish):
        agent, link = self.new_agent(
            "F-27/P3 terminal send publication handshake")
        send(self, link, 0x20, bytes((1,)) + b"x = 5", id_=118)

        def stop_then_return(mode, data):
            agent._runner.handle_stop()

        agent._runner._exec_fn = stop_then_return
        if after_publish:
            link.interrupt_terminal_after_publish = True
        else:
            link.interrupt_terminal_before_publish = True
        agent.poll()

        self.assertEqual(run_states(link), [1, 0],
                         "pre-send KBI retries; post-send KBI does not duplicate")
        self.assertEqual(agent._runner.rsm.state, 0)
        self.assertFalse(agent._runner.is_executing())

    def test_interrupt_before_terminal_send_retries_once(self):
        self._exercise_publication_cut(after_publish=False)

    def test_interrupt_after_terminal_send_does_not_retry(self):
        self._exercise_publication_cut(after_publish=True)

    def test_offline_terminal_is_omitted_not_replayed_to_successor(self):
        agent, link = self.new_agent(
            "FR-CON-4 no-live terminal event is never retained")
        send(self, link, 0x20, bytes((1,)) + b"x = 5", id_=119)

        def stop_then_disconnect(mode, data):
            agent._runner.handle_stop()
            link.omit_terminal = True

        agent._runner._exec_fn = stop_then_disconnect
        agent.poll()
        self.assertEqual(run_states(link), [1])

        link.omit_terminal = False
        agent.poll()
        self.assertEqual(
            run_states(link), [1],
            "an omitted old-session IDLE must not target a successor session")

    def test_unpublished_terminal_never_retargets_reused_handle_session(self):
        agent, link = self.new_agent(
            "FR-CON-4 unpublished terminal retains its creation session")
        send(self, link, 0x20, bytes((1,)) + b"x = 6", id_=120)

        def stop_then_return(mode, data):
            agent._runner.handle_stop()

        agent._runner._exec_fn = stop_then_return
        link.interrupt_terminal_before_publish = True
        link.replace_session_before_terminal_retry = True
        agent.poll()
        agent.poll()

        self.assertEqual(
            run_states(link), [1],
            "session A's unpublished IDLE must not be sent to session B")


class SoftRebootClosingTest(AgentTestBase):
    """P4: one acknowledged SOFT fixes one deadline and closes admissions."""

    def test_duplicate_is_ebusy_without_extending_original_deadline(self):
        agent, link = self.new_agent(
            "F-27/P4 duplicate SOFT preserves deadline")
        send(self, link, 0x22, id_=96)
        self.assertEqual(rsps(link, 0x22, 96)[0].payload[0], OK)
        self.assertEqual(agent._reboot_at, 250)

        self.now[0] = 200
        send(self, link, 0x22, id_=97)
        self.assertEqual(rsps(link, 0x22, 97)[0].payload[0], EBUSY)
        self.assertEqual(agent._reboot_at, 250,
                         "duplicate SOFT MUST NOT move the first deadline")

        self.now[0] = 250
        agent.poll()
        self.assertEqual(self.resets, [1],
                         "the original t=250 deadline remains authoritative")

    def test_pending_reboot_rejects_run_and_skips_filesystem_pump(self):
        agent, link = self.new_agent(
            "F-27/P4 closing state rejects work")
        pumps = []
        agent._fs.pump = lambda: pumps.append(1)
        send(self, link, 0x22, id_=98)

        send(self, link, 0x20, bytes((1,)) + b"raise RuntimeError", id_=99)
        self.assertEqual(rsps(link, 0x20, 99)[0].payload[0], EBUSY)
        agent.poll()

        self.assertEqual(pumps, [],
                         "closing supervisor MUST NOT start filesystem work")
        self.assertEqual(run_states(link), [],
                         "RUN after acknowledged SOFT MUST never execute")

    def test_closing_gate_covers_every_non_soft_command_and_unknown(self):
        agent, link = self.new_agent(
            "F-27/P4 global closing admission matrix")
        send(self, link, 0x22, id_=120)

        request_id = 121
        for name, opcode in sorted(CMD_OPCODES.items()):
            if opcode == CMD_OPCODES["SOFT_REBOOT"]:
                continue
            with self.subTest(opcode=name):
                payload = b"z" if opcode == CMD_OPCODES["CONSOLE_INPUT"] else b""
                send(self, link, opcode, payload, id_=request_id)
                answers = rsps(link, opcode, request_id)
                if opcode in NO_RSP_OPCODES:
                    self.assertEqual(answers, [],
                                     "no-RSP command is dropped while closing")
                else:
                    self.assertEqual(len(answers), 1)
                    self.assertEqual(
                        answers[0].payload[0], EBUSY,
                        "every response-bearing command is gated before handler")
                request_id += 1

        send(self, link, 0x7F, id_=150)
        self.assertEqual(rsps(link, 0x7F, 150)[0].payload[0], EBUSY,
                         "unknown valid commands are gated while closing too")

    def test_closing_gate_prevents_inline_persistent_and_console_mutation(self):
        keep = os.path.join(self.root, "keep.txt")
        with open(keep, "wb") as fh:
            fh.write(b"keep")
        agent, link = self.new_agent(
            "F-27/P4 closing gate blocks handler side effects")
        send(self, link, 0x22, id_=151)

        def path_payload(path):
            raw = path.encode("utf-8")
            return struct.pack("<H", len(raw)) + raw

        commands = (
            (0x18, path_payload("/keep.txt"), 152),
            (0x19, path_payload("/newdir"), 153),
            (0x50, b"mutated", 154),
            (0x23, b"\x01", 155),
        )
        statuses = []
        for opcode, payload, id_ in commands:
            send(self, link, opcode, payload, id_=id_)
            statuses.append(rsps(link, opcode, id_)[0].payload[0])
        send(self, link, 0x31, b"z", id_=156)

        self.assertEqual(statuses, [EBUSY] * len(commands))
        self.assertTrue(os.path.isfile(keep),
                        "closing FILE_DELETE MUST NOT reach filesystem handler")
        self.assertFalse(os.path.exists(os.path.join(self.root, "newdir")),
                         "closing MKDIR MUST NOT reach filesystem handler")
        self.assertEqual(agent._config.label, "")
        self.assertEqual(agent._config.auto_run, 0)
        self.assertIsNone(agent.console.readinto(bytearray(1)),
                          "closing CONSOLE_INPUT is dropped before ring mutation")

    def test_closing_exception_resets_instead_of_losing_deadline(self):
        order = []

        def reset_now():
            order.append(("reset",))
            raise _ResetNow()

        agent, link = self.new_agent(
            "F-27/P4 closing exception fail-safe", reset=reset_now)
        send(self, link, 0x20, bytes((1,)) + b"x = 4", id_=100)
        send(self, link, 0x22, id_=101)

        def fail_idle_emit(state, published):
            raise RuntimeError("deterministic terminal send failure")

        agent._runner._emit_terminal = fail_idle_emit
        with self.assertRaises(_ResetNow,
                               msg="closing exception MUST reset, not rebuild"):
            agent.poll()
        self.assertEqual(order, [("reset",)])


class HardResetAlarmTest(AgentTestBase):
    """P4: the RP2 alarm is a hard one-shot and does not depend on poll/KBI."""

    def test_timer_factory_uses_hard_one_shot_and_direct_reset(self):
        factory = AGENT.attr(
            self, "_make_hard_reset_alarm",
            "F-27/P4 RP2 hard reset alarm factory")
        timers = []
        resets = []

        class FakeTimer:
            ONE_SHOT = 0

            def __init__(self):
                self.kwargs = None
                timers.append(self)

            def init(self, **kwargs):
                self.kwargs = kwargs

        arm = factory(FakeTimer, lambda: resets.append(1))
        arm(250)

        self.assertEqual(len(timers), 1)
        self.assertEqual(timers[0].kwargs["period"], 250)
        self.assertEqual(timers[0].kwargs["mode"], FakeTimer.ONE_SHOT)
        self.assertIs(timers[0].kwargs["hard"], True)
        timers[0].kwargs["callback"](timers[0])
        self.assertEqual(resets, [1],
                         "hard callback invokes reset without Agent.poll")

    def test_soft_arms_alarm_only_after_response_handoff(self):
        order = []
        armed = []

        def arm(delay_ms):
            order.append(("arm", delay_ms))
            armed.append(delay_ms)

        agent, link = self.new_agent(
            "F-27/P4 response-before-hard-alarm", order=order,
            arm_reset=arm)
        send(self, link, 0x22, id_=102)

        rsp_index = next(
            i for i, event in enumerate(order)
            if event[0] == "tx"
            and pyble_proto.decode(event[1]).type == RSP
            and pyble_proto.decode(event[1]).opcode == 0x22)
        self.assertEqual(armed, [250])
        self.assertLess(rsp_index, order.index(("arm", 250)),
                        "hard deadline is armed only after SOFT RSP handoff")

    def test_timer_admission_failure_resets_after_response(self):
        order = []

        def arm_fail(delay_ms):
            order.append(("arm-fail", delay_ms))
            raise RuntimeError("alarm pool full")

        def reset_now():
            order.append(("reset",))
            raise _ResetNow()

        agent, link = self.new_agent(
            "F-27/P4 timer admission reset fail-safe", order=order,
            reset=reset_now, arm_reset=arm_fail)
        with self.assertRaises(_ResetNow):
            send(self, link, 0x22, id_=103)

        rsp_index = next(
            i for i, event in enumerate(order)
            if event[0] == "tx"
            and pyble_proto.decode(event[1]).type == RSP
            and pyble_proto.decode(event[1]).opcode == 0x22)
        self.assertLess(rsp_index, order.index(("arm-fail", 250)))
        self.assertLess(order.index(("arm-fail", 250)),
                        order.index(("reset",)))


class SchedulerFailureFailSafeTest(AgentTestBase):
    """P3/P4: after RSP handoff, scheduler-full rolls back 0x03 and invokes
    the injected non-returning hardware reset for STOP and SOFT_REBOOT."""

    def _exercise(self, opcode, id_):
        order = []

        def queue_full():
            order.append(("notify-attempt",))
            raise RuntimeError("schedule queue full")

        def reset_now():
            order.append(("reset",))
            raise _ResetNow()

        agent, link = self.new_agent(
            "F-27/P3 scheduler-full reset fail-safe", order=order,
            notify=queue_full, reset=reset_now)
        send(self, link, 0x20, bytes((1,)) + b"while True: pass", id_=id_ - 1)
        agent._runner._executing = True
        order[:] = []

        with self.assertRaises(_ResetNow,
                               msg="scheduler-full MUST enter non-returning reset"):
            send(self, link, opcode, id_=id_)

        rsp_idx = next(
            i for i, event in enumerate(order)
            if event[0] == "tx"
            and pyble_proto.decode(event[1]).type == RSP
            and pyble_proto.decode(event[1]).opcode == opcode
            and pyble_proto.decode(event[1]).id == id_)
        self.assertLess(rsp_idx, order.index(("notify-attempt",)))
        self.assertLess(order.index(("notify-attempt",)), order.index(("reset",)))
        self.assertIsNone(agent.console.readinto(bytearray(1)),
                          "failed schedule MUST leave no latent armed 0x03")

    def test_stop_scheduler_full_resets_after_rsp(self):
        self._exercise(0x21, 81)

    def test_soft_reboot_scheduler_full_resets_after_rsp(self):
        self._exercise(0x22, 83)

    def test_print_flood_retry_scheduler_full_uses_agent_reset(self):
        """A schedule failure after dupterm-write swallowed the first KBI is
        later than Agent._commit_control, so the console must retain the
        Agent's injected reset seam for that acknowledged-STOP fail-safe."""
        order = []

        def notify():
            order.append(("notify",))

        def retry():
            order.append(("retry",))
            raise RuntimeError("schedule queue full on print retry")

        def reset_now():
            order.append(("reset",))
            raise _ResetNow()

        agent, link = self.new_agent(
            "F-27/P3 print-flood retry reset wiring", order=order,
            notify=notify, reset=reset_now)
        agent.console.set_stop_retry(retry)
        send(self, link, 0x20,
             bytes((1,)) + b"while True: print('flood')", id_=84)
        agent._runner._executing = True
        order[:] = []

        send(self, link, 0x21, id_=85)
        buf = bytearray(1)
        self.assertEqual(agent.console.readinto(buf), 1)
        self.assertEqual(buf[0], 0x03)
        agent.console.set_run_active(True)

        def pending_stop_lands(stream, data):
            raise KeyboardInterrupt()

        agent.console._emit = pending_stop_lands
        try:
            with self.assertRaises(
                    _ResetNow,
                    msg="retry admission failure must use Agent's reset seam"):
                agent.console.write(b"flood")
        except KeyboardInterrupt:
            self.fail("delivered STOP escaped into upstream's dupterm catch "
                      "instead of reaching retry/reset recovery")

        rsp_idx = next(
            i for i, event in enumerate(order)
            if event[0] == "tx"
            and pyble_proto.decode(event[1]).type == RSP
            and pyble_proto.decode(event[1]).opcode == 0x21
            and pyble_proto.decode(event[1]).id == 85)
        self.assertLess(rsp_idx, order.index(("notify",)))
        self.assertLess(order.index(("retry",)), order.index(("reset",)))
        self.assertIsNone(agent.console.readinto(buf),
                          "failed retry must leave no latent armed 0x03")


class StopWhileIdleTest(AgentTestBase):
    """§6/P3: STOP while idle is a no-op RSP{OK} — and NO RUN_STATE is emitted
    (idle STOP must not fabricate a lifecycle transition)."""

    def test_idle_stop_is_ok_with_no_run_state(self):
        side_effects = []
        agent, link = self.new_agent(
            "F-25/§6 idle STOP: OK, no RUN_STATE",
            notify=lambda: side_effects.append("notify"),
            reset=lambda: side_effects.append("reset"))
        send(self, link, 0x21, id_=4)
        pump(agent, 3, self.now)
        answers = rsps(link, opcode=0x21, id_=4)
        self.assertEqual(len(answers), 1, "STOP MUST always be answered")
        self.assertEqual(answers[0].payload[0], OK,
                         "STOP is idempotent: RSP{OK} even while idle (§6)")
        self.assertEqual(evts(link, opcode=0x40), [],
                         "an idle STOP MUST NOT emit any RUN_STATE EVT")
        self.assertEqual(side_effects, [],
                         "idle STOP arms no interrupt and no reset fail-safe")


class UsbActivationTest(unittest.TestCase):
    """P2: the supervisor must activate the builtin USB device itself.

    rp2's main.c calls mp_usbd_init() only AFTER _boot.py returns; the
    supervisor never returns, so without this the board runs BLE-only with no
    USB CDC console (hardware-observed 2026-08-11 on the first flashed image).
    """

    def test_activate_usb_selects_builtin_cdc_then_activates(self):
        calls = []

        class FakeUSBDevice:
            BUILTIN_DEFAULT = object()   # sentinel, as on a real build

            def __init__(self):
                # machine_usb_device.c:69 — the singleton starts BUILTIN_NONE;
                # activating without selecting the builtin driver enumerates a
                # device with NO interfaces (hardware-observed: no CDC at all).
                self._builtin = None

            @property
            def builtin_driver(self):
                return self._builtin

            @builtin_driver.setter
            def builtin_driver(self, v):
                calls.append(("builtin", v))
                self._builtin = v

            def active(self, on):
                calls.append(("active", on))

        class FakeMachine:
            USBDevice = FakeUSBDevice

        fn = AGENT.attr(self, "_activate_usb",
                        "P2: supervisor-side USB activation (rp2 usbd init "
                        "runs only after _boot.py returns)")
        fn(FakeMachine())
        self.assertEqual(
            calls,
            [("builtin", FakeUSBDevice.BUILTIN_DEFAULT), ("active", True)],
            "supervisor must select BUILTIN_DEFAULT (CDC) BEFORE active(True) "
            "— the singleton defaults to BUILTIN_NONE")

    def test_activate_usb_is_best_effort_when_absent(self):
        class BareMachine:
            pass

        # CPython / a build without runtime USB: must not raise.
        fn = AGENT.attr(self, "_activate_usb",
                        "P2: USB activation is best-effort")
        fn(BareMachine())


if __name__ == "__main__":
    unittest.main(verbosity=2)
