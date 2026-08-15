#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Host tests for the rpi-pico2-w port increment of F-25 `pyble_ble`
# (EPIC-PORT-RP2, gate GP1; port spec ports/rpi-pico2-w.md P6/P7). Sole [red]
# author: firmware-test-author. Production module owner (HAND-OFF for [green]):
# ble-transport-engineer -> firmware/pyble/pyble_ble.py (plan C6).
#
# ENVIRONMENT REALITY: BTstack/BLE behaviour is NEVER faked. These tests
# exercise OUR OWN seams only — BleLink's irq dispatch, its §3.2 reassembly,
# and the exact MicroPython `bluetooth` module SURFACE it calls. The recording
# objects below record calls and return canned handles; they simulate no BLE
# semantics. Two HARDWARE-VERIFIED (2026-08-11) rp2 facts are pinned here:
#   * modbluetooth exports NO `_IRQ_*` attributes on rp2 — the module must
#     carry its own numeric constants (the AttributeError defect at the
#     scaffold's `bluetooth._IRQ_*` reads). The test bluetooth surface
#     deliberately has NO _IRQ_* names, matching the device.
#   * the default 20-byte GATTS attribute buffer silently truncates writes —
#     `gatts_set_buffer(rx, >=247, False)` is REQUIRED (port spec P7).
#
# ---------------------------------------------------------------------------
# INTERFACE PINNED BY THIS [red] TEST (ble-transport-engineer implements to it):
#   pyble_ble._IRQ_CENTRAL_CONNECT    == 1     # module-local numeric constants
#   pyble_ble._IRQ_CENTRAL_DISCONNECT == 2     # (MicroPython IRQ code values;
#   pyble_ble._IRQ_GATTS_WRITE        == 3     #  never read from `bluetooth`)
#   pyble_ble._IRQ_MTU_EXCHANGED      == 21
#   pyble_ble.RX_MAX == 4096                   # P6 reassembled-message cap
#   BleLink._irq(event, data): entire dispatch try/except-wrapped — NEVER
#         propagates (an uncaught raise permanently disables the handler);
#         never reads bluetooth._IRQ_* attributes.
#   BleLink.on_oversize(cb): cb(head: bytes) fires ONCE per oversize (>RX_MAX)
#         reassembled message, with head carrying at least the §3.1 header
#         bytes (head[2]=opcode, head[3]=id) so the agent can echo RSP ERANGE
#         (P6). The oversize message is dropped, never delivered; reassembly
#         recovers for the next FIRST fragment.
#   BleLink.start(info_payload=b""): after gatts_register_services and before
#         advertising calls gatts_set_buffer(rx_handle, n>=247, append=False);
#         after active(True) calls config(mtu=247) to pin the ceiling (P7).
#   BleLink.send_message(msg, on_published=None) -> bool: invokes on_published
#         exactly
#         once immediately after the final Notify is locally accepted. It does
#         not publish a receipt while disconnected or after a Notify error;
#         returns False only for the disconnected/no-live-session omission.
# ---------------------------------------------------------------------------

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

BLE = _support.RedReason("pyble_ble", owner="ble-transport-engineer")

RX_MAX_FROZEN = 4096  # ports/rpi-pico2-w.md P6 (FROZEN)
FRAG_FIRST = 0x80  # protocol.md §3.2 (FROZEN) — test-side oracle bits
FRAG_LAST = 0x40


def frag_packets(msg, size=243):
    """Test-side §3.2 fragmentation oracle (FIRST/LAST bits, index mod 64)."""
    if not msg:
        return [bytes((FRAG_FIRST | FRAG_LAST,))]
    out = []
    total = len(msg)
    index = 0
    for off in range(0, total, size):
        hdr = index % 64
        if index == 0:
            hdr |= FRAG_FIRST
        if off + size >= total:
            hdr |= FRAG_LAST
        out.append(bytes((hdr,)) + msg[off:off + size])
        index += 1
    return out


class RecordingBle:
    """Records the exact `bluetooth.BLE` SURFACE calls BleLink makes. No BLE
    semantics — canned handles only (env-reality rule)."""

    def __init__(self):
        self.ops = []                # ordered op names
        self.config_sets = []        # dicts of kwargs passed to config(...)
        self.set_buffer_calls = []   # (args, kwargs)
        self.notify_calls = []       # (conn, handle, bytes)
        self.written = {}            # handle -> bytes
        self.rx_value = b""          # served by gatts_read
        self.handles = (10, 11, 12)  # canned (rx, tx, info) value handles

    def active(self, on=None):
        self.ops.append("active")
        return True

    def irq(self, handler):
        self.ops.append("irq")
        self.irq_handler = handler

    def config(self, *args, **kwargs):
        if args:
            self.ops.append("config_get:%s" % args[0])
            if args[0] == "mac":
                return (0, b"\x00\x01\x02\x03\x04\x05")
            return None
        self.ops.append("config_set:%s" % ",".join(sorted(kwargs)))
        self.config_sets.append(dict(kwargs))
        return None

    def gatts_register_services(self, services):
        self.ops.append("register")
        return (self.handles,)

    def gatts_set_buffer(self, *args, **kwargs):
        self.ops.append("set_buffer")
        self.set_buffer_calls.append((args, kwargs))

    def gatts_write(self, handle, value):
        self.ops.append("gatts_write")
        self.written[handle] = bytes(value)

    def gatts_read(self, handle):
        self.ops.append("gatts_read")
        return self.rx_value

    def gatts_notify(self, conn_handle, value_handle, data):
        self.ops.append("notify")
        self.notify_calls.append((conn_handle, value_handle, bytes(data)))

    def gap_advertise(self, interval_us, adv_data=None, resp_data=None, **kw):
        self.ops.append("advertise")


def make_rp2_bluetooth_surface(recorder_factory):
    """A `bluetooth` module surface matching rp2 modbluetooth reality:
    UUID/FLAG_*/BLE exist; NO `_IRQ_*` attributes (hardware-verified)."""
    mod = types.ModuleType("bluetooth")
    mod.FLAG_READ = 0x0002
    mod.FLAG_WRITE_NO_RESPONSE = 0x0004
    mod.FLAG_WRITE = 0x0008
    mod.FLAG_NOTIFY = 0x0010
    mod.UUID = lambda value: value
    created = []
    mod._created = created

    def _ble():
        rec = recorder_factory()
        created.append(rec)
        return rec

    mod.BLE = _ble
    return mod


class _Rp2SurfaceTestCase(unittest.TestCase):
    """Swaps a no-_IRQ_* rp2 `bluetooth` surface into sys.modules for the test
    (BleLink imports `bluetooth` lazily, so the swap governs its lookups)."""

    def setUp(self):
        self._saved_bt = sys.modules.get("bluetooth")
        self.bt_surface = make_rp2_bluetooth_surface(RecordingBle)
        sys.modules["bluetooth"] = self.bt_surface

    def tearDown(self):
        if self._saved_bt is not None:
            sys.modules["bluetooth"] = self._saved_bt
        else:
            sys.modules.pop("bluetooth", None)

    def make_link(self, criterion):
        mod = BLE.obj(self, criterion)
        link = mod.BleLink()
        self.rec = RecordingBle()
        link._ble = self.rec
        link._rx_handle, link._tx_handle, link._info_handle = self.rec.handles
        link._service_uuid = getattr(
            mod, "SERVICE_UUID", "7079626c-1ab1-4d50-9e3a-000000000001")
        return mod, link

    def drive(self, link, event, data, criterion):
        """Call BleLink._irq and FAIL (never ERROR) if anything escapes: on the
        device an uncaught raise permanently disables the irq handler, and on
        rp2 there are no bluetooth._IRQ_* names to read."""
        try:
            link._irq(event, data)
        except BaseException as exc:  # noqa: BLE001 - the contract under test
            self.fail(
                "[{crit}] BleLink._irq must use module-local NUMERIC IRQ "
                "constants and wrap the whole dispatch in try/except (rp2 "
                "modbluetooth exports no _IRQ_* attributes; a raise disables "
                "the handler permanently) — got {exc!r}. HAND-OFF: "
                "ble-transport-engineer (plan C6).".format(
                    crit=criterion, exc=exc))


class IrqNumericConstantsTest(unittest.TestCase):
    """P7: module-local numeric IRQ constants (never bluetooth._IRQ_*)."""

    CRITERION = "F-25/P7 module-local numeric IRQ constants"

    def test_module_local_numeric_irq_constants(self):
        expected = {
            "_IRQ_CENTRAL_CONNECT": 1,
            "_IRQ_CENTRAL_DISCONNECT": 2,
            "_IRQ_GATTS_WRITE": 3,
            "_IRQ_MTU_EXCHANGED": 21,
        }
        for name, value in sorted(expected.items()):
            got = BLE.attr(self, name, self.CRITERION)
            self.assertEqual(
                value, got,
                "[{}] pyble_ble.{} must equal {} (MicroPython IRQ code; "
                "hardware-verified numeric values)".format(
                    self.CRITERION, name, value))


class IrqDispatchTest(_Rp2SurfaceTestCase):
    """P7: _irq handles the numeric events against a bluetooth surface with NO
    _IRQ_* attributes, and never lets an exception escape."""

    CRITERION = "F-25/P7 irq dispatch on rp2 numeric events"

    def test_central_connect_event_1_fires_on_connect(self):
        _, link = self.make_link(self.CRITERION)
        seen = []
        link.on_connect(lambda: seen.append("connect"))
        self.drive(link, 1, (11, 0, b"\xaa" * 6), self.CRITERION)
        self.assertEqual(
            ["connect"], seen,
            "[{}] numeric event 1 (CENTRAL_CONNECT) must fire the on_connect "
            "callback".format(self.CRITERION))

    def test_mtu_exchanged_event_21_updates_mtu(self):
        _, link = self.make_link(self.CRITERION)
        self.drive(link, 21, (11, 247), self.CRITERION)
        self.assertEqual(
            247, link.mtu(),
            "[{}] numeric event 21 (MTU_EXCHANGED) must update the negotiated "
            "MTU (FR-BLE-7 twin)".format(self.CRITERION))

    def test_gatts_write_event_3_delivers_reassembled_message(self):
        _, link = self.make_link(self.CRITERION)
        msgs = []
        link.on_message(msgs.append)
        self.drive(link, 1, (11, 0, b"\xaa" * 6), self.CRITERION)
        payload = b"opaque-pble1-frame-bytes"
        self.rec.rx_value = bytes((FRAG_FIRST | FRAG_LAST,)) + payload
        self.drive(link, 3, (11, self.rec.handles[0]), self.CRITERION)
        self.assertEqual(
            [payload], msgs,
            "[{}] numeric event 3 (GATTS_WRITE) on the RX handle must "
            "reassemble and deliver the message via on_message".format(
                self.CRITERION))

    def test_central_disconnect_event_2_resets_and_readvertises(self):
        mod, link = self.make_link(self.CRITERION)
        seen = []
        link.on_disconnect(lambda: seen.append("disconnect"))
        self.drive(link, 1, (11, 0, b"\xaa" * 6), self.CRITERION)
        self.drive(link, 21, (11, 247), self.CRITERION)
        self.assertEqual(247, link.mtu())
        self.drive(link, 2, (11, 0, b"\xaa" * 6), self.CRITERION)
        self.assertEqual(
            ["disconnect"], seen,
            "[{}] numeric event 2 (CENTRAL_DISCONNECT) must fire the "
            "on_disconnect callback".format(self.CRITERION))
        self.assertEqual(
            mod.DEFAULT_MTU, link.mtu(),
            "[{}] disconnect must reset the MTU to the BLE default".format(
                self.CRITERION))
        self.assertIn(
            "advertise", self.rec.ops,
            "[{}] disconnect must re-advertise (the link outlives the "
            "session, FR-BLE-11 twin)".format(self.CRITERION))

    def test_irq_swallows_callback_exceptions(self):
        _, link = self.make_link(self.CRITERION)

        def _boom(*a):
            raise RuntimeError("user callback fault")

        link.on_connect(_boom)
        link.on_message(_boom)
        self.drive(link, 1, (11, 0, b"\xaa" * 6), self.CRITERION)
        self.rec.rx_value = bytes((FRAG_FIRST | FRAG_LAST,)) + b"payload"
        self.drive(link, 3, (11, self.rec.handles[0]), self.CRITERION)

    def test_irq_tolerates_unknown_event_codes(self):
        _, link = self.make_link(self.CRITERION)
        self.drive(link, 99, (11,), self.CRITERION)


class TxPublicationCutTest(_Rp2SurfaceTestCase):
    """P3: terminal recovery needs a receipt at the actual TX record cut."""

    def test_send_message_commits_receipt_after_notify_record(self):
        _, link = self.make_link("F-27/P3 terminal TX publication receipt")
        link._conn_handle = 11
        link._mtu = 247
        receipts = []

        def published():
            receipts.append(len(self.rec.notify_calls))

        msg = b"terminal-frame" * 40
        link.send_message(msg, on_published=published)
        self.assertGreater(len(self.rec.notify_calls), 1)
        self.assertEqual(
            [call[2] for call in self.rec.notify_calls], frag_packets(msg))
        self.assertEqual(receipts, [len(self.rec.notify_calls)],
                         "receipt fires once, after all fragments are recorded")

    def test_send_message_never_receipts_without_local_acceptance(self):
        _, link = self.make_link("F-27/P3 no false terminal TX receipt")
        receipts = []

        accepted = link.send_message(
            b"offline", on_published=lambda: receipts.append(1))
        self.assertIs(accepted, False)
        self.assertEqual(receipts, [], "a disconnected drop is not publication")

        link._conn_handle = 11

        def fail_notify(*args):
            raise OSError("BTstack refused Notify")

        self.rec.gatts_notify = fail_notify
        with self.assertRaises(OSError):
            link.send_message(
                b"not-accepted", on_published=lambda: receipts.append(1))
        self.assertEqual(receipts, [], "a failed Notify is not publication")

    def test_reused_handle_has_new_session_and_rejects_old_event(self):
        _, link = self.make_link("FR-CON-4 exact RP2 event session binding")
        self.drive(link, 1, (11, 0, b"\xaa" * 6), "session A connect")
        session_a = link.session_token()
        self.drive(link, 2, (11, 0, b"\xaa" * 6), "session A disconnect")
        self.drive(link, 1, (11, 0, b"\xbb" * 6), "session B handle reuse")
        session_b = link.session_token()

        self.assertNotEqual(session_a, session_b)
        before = len(self.rec.notify_calls)
        accepted = link.send_message(
            b"old-session-event", expected_session=session_a)
        self.assertIs(accepted, False)
        self.assertEqual(len(self.rec.notify_calls), before)


class StartBindingsTest(_Rp2SurfaceTestCase):
    """P7: start() must arm the RX attribute buffer and pin the MTU ceiling —
    hardware-verified: without gatts_set_buffer the app's 71-byte HELLO arrives
    as 19 bytes (silent truncation)."""

    CRITERION = "F-25/P7 start() gatts_set_buffer + config(mtu=247)"

    def _started_link(self):
        mod = BLE.obj(self, self.CRITERION)
        link = mod.BleLink()
        try:
            link.start(info_payload=b"caps-bytes")
        except BaseException as exc:  # noqa: BLE001 - report as red, not error
            self.fail(
                "[{}] BleLink.start() must run against the rp2 bluetooth "
                "surface (no _IRQ_* attributes) — got {!r}".format(
                    self.CRITERION, exc))
        self.assertTrue(
            self.bt_surface._created,
            "[{}] start() must construct bluetooth.BLE()".format(
                self.CRITERION))
        return self.bt_surface._created[-1]

    def test_start_sets_rx_attribute_buffer(self):
        rec = self._started_link()
        self.assertTrue(
            rec.set_buffer_calls,
            "[{}] start() must call gatts_set_buffer for the RX handle — the "
            "default ~20-byte attribute buffer SILENTLY TRUNCATES writes "
            "(hardware-verified). HAND-OFF: ble-transport-engineer.".format(
                self.CRITERION))
        args, kwargs = rec.set_buffer_calls[0]
        self.assertEqual(
            rec.handles[0], args[0],
            "[{}] gatts_set_buffer must target the RX value handle".format(
                self.CRITERION))
        self.assertGreaterEqual(
            args[1], 247,
            "[{}] the RX attribute buffer must hold at least one full "
            "MTU-247 write".format(self.CRITERION))
        append = args[2] if len(args) > 2 else kwargs.get("append", False)
        self.assertFalse(
            append,
            "[{}] gatts_set_buffer append mode stays False (the blob "
            "reframer is a HIL-evidence contingency, not the default)".format(
                self.CRITERION))

    def test_start_orders_set_buffer_after_registration_before_advertising(self):
        rec = self._started_link()
        for op in ("register", "set_buffer", "advertise"):
            self.assertIn(
                op, rec.ops,
                "[{}] start() must perform {!r}".format(self.CRITERION, op))
        self.assertLess(
            rec.ops.index("register"), rec.ops.index("set_buffer"),
            "[{}] gatts_set_buffer comes immediately AFTER service "
            "registration (the handle exists only then)".format(
                self.CRITERION))
        self.assertLess(
            rec.ops.index("set_buffer"), rec.ops.index("advertise"),
            "[{}] the RX buffer must be armed BEFORE the board is "
            "connectable (advertising)".format(self.CRITERION))

    def test_start_pins_mtu_ceiling_247(self):
        rec = self._started_link()
        self.assertTrue(
            any(kw.get("mtu") == 247 for kw in rec.config_sets),
            "[{}] start() must call config(mtu=247) after active(True) to "
            "pin the ATT MTU ceiling (port spec P7)".format(self.CRITERION))
        config_ops = [i for i, op in enumerate(rec.ops)
                      if op == "config_set:mtu"]
        self.assertTrue(
            config_ops,
            "[{}] config(mtu=247) missing from the start() call "
            "sequence".format(self.CRITERION))
        self.assertIn("active", rec.ops)
        self.assertLess(
            rec.ops.index("active"), config_ops[0],
            "[{}] config(mtu=247) is only accepted AFTER active(True)".format(
                self.CRITERION))


class RxReassemblyCapTest(_Rp2SurfaceTestCase):
    """P6: reassembled RX messages are capped at 4096 bytes; oversize is
    dropped and reported (agent maps it to RSP ERANGE with opcode/id echo)."""

    CRITERION = "F-25/P6 4096-byte reassembly cap -> ERANGE path"

    def test_rx_max_constant_is_4096(self):
        rx_max = BLE.attr(self, "RX_MAX", self.CRITERION)
        self.assertEqual(
            RX_MAX_FROZEN, rx_max,
            "[{}] pyble_ble.RX_MAX must be the frozen P6 cap (4096)".format(
                self.CRITERION))

    def _feed(self, link, msg):
        for pkt in frag_packets(msg):
            link._on_rx(pkt)

    def test_message_at_exactly_4096_is_delivered(self):
        _, link = self.make_link(self.CRITERION)
        msgs = []
        link.on_message(msgs.append)
        msg = bytes((0x01, 0x01, 0x20, 0x2A, 0x00, 0x00)) + \
            b"\xa5" * (RX_MAX_FROZEN - 6)
        self._feed(link, msg)
        self.assertEqual(
            [msg], msgs,
            "[{}] a message of exactly RX_MAX bytes is legal and must be "
            "delivered byte-identically".format(self.CRITERION))

    def test_oversize_message_dropped_and_reported_once(self):
        _, link = self.make_link(self.CRITERION)
        msgs = []
        link.on_message(msgs.append)
        register = getattr(link, "on_oversize", None)
        if register is None:
            self.fail(
                "[{}] BleLink.on_oversize(cb) missing — the P6 cap needs a "
                "report seam so the agent can answer RSP ERANGE with a "
                "best-effort opcode/id echo. HAND-OFF: ble-transport-engineer "
                "(plan C6).".format(self.CRITERION))
        heads = []
        register(lambda head: heads.append(bytes(head)))
        msg = bytes((0x01, 0x01, 0x20, 0x2A, 0x00, 0x00)) + \
            b"\x5a" * (RX_MAX_FROZEN + 1 - 6)
        self._feed(link, msg)
        self.assertEqual(
            [], msgs,
            "[{}] an oversize (>RX_MAX) message must be DROPPED, never "
            "delivered".format(self.CRITERION))
        self.assertEqual(
            1, len(heads),
            "[{}] on_oversize must fire EXACTLY ONCE per oversize message "
            "(trailing fragments of the same message stay silent)".format(
                self.CRITERION))
        head = heads[0]
        self.assertGreaterEqual(
            len(head), 4,
            "[{}] the oversize report must carry at least the §3.1 header "
            "bytes for the opcode/id echo".format(self.CRITERION))
        self.assertEqual(
            (0x20, 0x2A), (head[2], head[3]),
            "[{}] head[2]/head[3] must expose the offending opcode/id so the "
            "agent can echo them in RSP ERANGE".format(self.CRITERION))

    def test_reassembly_recovers_after_oversize_drop(self):
        _, link = self.make_link(self.CRITERION)
        msgs = []
        link.on_message(msgs.append)
        register = getattr(link, "on_oversize", None)
        if register is None:
            self.fail(
                "[{}] BleLink.on_oversize(cb) missing (see "
                "test_oversize_message_dropped_and_reported_once)".format(
                    self.CRITERION))
        register(lambda head: None)
        oversize = bytes((0x01, 0x01, 0x20, 0x2A, 0x00, 0x00)) + \
            b"\x5a" * (RX_MAX_FROZEN + 1 - 6)
        self._feed(link, oversize)
        follow_up = b"next-normal-message"
        self._feed(link, follow_up)
        self.assertEqual(
            [follow_up], msgs,
            "[{}] after an oversize drop the reassembler must recover and "
            "deliver the next FIRST-flagged message".format(self.CRITERION))


if __name__ == "__main__":
    unittest.main(verbosity=2)
