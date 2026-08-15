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
#                     clock=callable, notify=callable)
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

    def on_message(self, cb):
        self.message_cb = cb

    def on_connect(self, cb):
        self.connect_cb = cb

    def on_disconnect(self, cb):
        self.disconnect_cb = cb

    def send_message(self, msg):
        msg = bytes(msg)
        self.sent.append(msg)
        if self.order is not None:
            self.order.append(("tx", msg))

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

    def new_agent(self, criterion=None, order=None, reset=None, notify=None):
        cls = AGENT.attr(self, "Agent", criterion or self.CRIT)
        link = FakeLink(order)
        agent = cls(
            link, self.root,
            unique_id=UNIQUE_ID,
            reset=reset if reset is not None else (lambda: self.resets.append(1)),
            clock=lambda: self.now[0],
            notify=notify,
        )
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

        # Reserve a tight run without polling it: RUNNING covers both reserved
        # and executing, and keeps this host test independent of real VM IRQs.
        send(self, link, 0x20, bytes((1,)) + b"while True: pass", id_=10)
        self.assertEqual(rsps(link, opcode=0x20, id_=10)[0].payload[0], OK)
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


class StopWhileIdleTest(AgentTestBase):
    """§6/P3: STOP while idle is a no-op RSP{OK} — and NO RUN_STATE is emitted
    (idle STOP must not fabricate a lifecycle transition)."""

    def test_idle_stop_is_ok_with_no_run_state(self):
        agent, link = self.new_agent("F-25/§6 idle STOP: OK, no RUN_STATE")
        send(self, link, 0x21, id_=4)
        pump(agent, 3, self.now)
        answers = rsps(link, opcode=0x21, id_=4)
        self.assertEqual(len(answers), 1, "STOP MUST always be answered")
        self.assertEqual(answers[0].payload[0], OK,
                         "STOP is idempotent: RSP{OK} even while idle (§6)")
        self.assertEqual(evts(link, opcode=0x40), [],
                         "an idle STOP MUST NOT emit any RUN_STATE EVT")


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
