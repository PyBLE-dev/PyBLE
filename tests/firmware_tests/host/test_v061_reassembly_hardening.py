#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED host contract for the portable PBLE/1 RX deadline and abuse budget.

No BLE behavior is faked.  A recording object supplies only the MicroPython
``bluetooth.BLE`` calls made by PyBLE-owned ``BleLink`` code.  Fragment timing,
run replacement, violation accounting, exact-session reset, and the request to
disconnect are therefore deterministic host-testable policy.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

BLE = _support.RedReason("pyble_ble", owner="ble-transport-engineer")

HERE = os.path.dirname(os.path.abspath(__file__))
VECTORS_PATH = os.path.join(HERE, "conformance", "v061_session_vectors.json")

FIRST = 0x80
LAST = 0x40
RX_MAX = 4096
TICKS_PERIOD = 1 << 30


class RecordingBle:
    """Call recorder only; it implements no controller or GATT semantics."""

    def __init__(self):
        self.disconnect_calls = []
        self.advertise_calls = 0

    def gap_disconnect(self, conn_handle):
        self.disconnect_calls.append(conn_handle)

    def gap_advertise(self, *args, **kwargs):
        self.advertise_calls += 1


class ReassemblyHardeningTest(unittest.TestCase):
    def setUp(self):
        with open(VECTORS_PATH, "r", encoding="utf-8") as fh:
            self.constants = json.load(fh)["constants"]
        self.now = [0]
        self.mod = BLE.obj(
            self, "v0.6.1 bounded portable RX reassembly/session budget")

    @staticmethod
    def wrap_ticks_diff(end, start):
        """MicroPython-compatible signed arithmetic for a 2**30 tick ring."""
        half = TICKS_PERIOD // 2
        return ((end - start + half) % TICKS_PERIOD) - half

    def new_link(self, conn=11):
        # D11 pins an injectable clock at construction.  Tests must never
        # mutate module globals: separate links/VM epochs need independent,
        # deterministic clocks and the production default remains ticks_ms.
        try:
            link = self.mod.BleLink(
                clock=lambda: self.now[0], ticks_diff=self.wrap_ticks_diff)
        except TypeError as exc:
            self.fail(
                "BleLink(clock=..., ticks_diff=...) is the required D11 "
                "injectable portable-clock constructor seam: {}".format(exc))
        recorder = RecordingBle()
        link._ble = recorder
        link._rx_handle = 10
        link._tx_handle = 11
        link._info_handle = 12
        messages = []
        link.on_message(messages.append)
        link._irq(1, (conn, 0, b"\xaa" * 6))  # rp2 CENTRAL_CONNECT
        self.assertEqual((conn, 1), link.session_token())
        return link, recorder, messages

    def record_violation(self, link, token=None):
        fn = getattr(link, "record_protocol_violation", None)
        self.assertIsNotNone(
            fn,
            "BleLink.record_protocol_violation(expected_session) is the one "
            "shared counter seam for reassembly and Agent semantic violations")
        return fn(link.session_token() if token is None else token)

    @staticmethod
    def first(data=b"A", index=0, last=False):
        return bytes((FIRST | (LAST if last else 0) | (index & 0x3F),)) + data

    @staticmethod
    def continuation(index, data=b"B", last=False):
        return bytes(((LAST if last else 0) | (index & 0x3F),)) + data

    def test_shared_constants_pin_inclusive_absolute_bounds(self):
        self.assertEqual(5000, self.constants["rx_reassembly_deadline_ms"])
        self.assertEqual(8, self.constants["session_violation_limit"])

    def test_deadline_is_absolute_non_extending_and_inclusive(self):
        link, recorder, messages = self.new_link()

        self.now[0] = 100
        link._on_rx(self.first(b"A"))
        self.now[0] = 3000
        link._on_rx(self.continuation(1, b"B"))
        self.now[0] = 5099  # 4,999 ms since FIRST: still admissible
        link._on_rx(self.continuation(2, b"C", last=True))
        self.assertEqual([b"ABC"], messages)

        self.now[0] = 10000
        link._on_rx(self.first(b"X"))
        self.now[0] = 12000
        link._on_rx(self.continuation(1, b"Y"))
        self.now[0] = 15000  # exactly 5,000 ms since FIRST: expired
        link._on_rx(self.continuation(2, b"Z", last=True))
        self.assertEqual(
            [b"ABC"], messages,
            "a fragment at elapsed >=5000 ms cannot complete the old run")
        self.assertEqual([], recorder.disconnect_calls)

        # The expiry consumed exactly one shared-budget unit. Its remaining
        # tails consume none; six explicit units reach seven, the next is eight.
        for index in range(3, 12):
            link._on_rx(self.continuation(index, b"tail", last=index == 11))
        for _ in range(6):
            self.assertTrue(self.record_violation(link))
        self.assertEqual([], recorder.disconnect_calls)
        self.assertFalse(self.record_violation(link))
        self.assertEqual([11], recorder.disconnect_calls)

    def test_deadline_arithmetic_is_safe_across_ticks_wrap(self):
        link, recorder, messages = self.new_link()

        self.now[0] = TICKS_PERIOD - 100
        link._on_rx(self.first(b"A"))
        self.now[0] = 2000
        link._on_rx(self.continuation(1, b"B"))
        self.now[0] = 4899  # 4,999 ms after FIRST across the wrap
        link._on_rx(self.continuation(2, b"C", last=True))
        self.assertEqual([b"ABC"], messages)

        self.now[0] = TICKS_PERIOD - 100
        link._on_rx(self.first(b"X"))
        self.now[0] = 2000
        link._on_rx(self.continuation(1, b"Y"))
        self.now[0] = 4900  # exactly 5,000 ms across the wrap: expired
        link._on_rx(self.continuation(2, b"Z", last=True))
        self.assertEqual([b"ABC"], messages)
        self.assertEqual([], recorder.disconnect_calls)

        for _ in range(6):
            self.assertTrue(self.record_violation(link))
        self.assertFalse(self.record_violation(link))
        self.assertEqual([11], recorder.disconnect_calls)

    def test_gap_and_all_discarded_tails_count_as_one_logical_violation(self):
        link, recorder, messages = self.new_link()
        link._on_rx(self.first(b"prefix"))
        link._on_rx(self.continuation(2, b"gap", last=True))  # expected index 1

        # These are tails of the already-discarded run, not fresh violations.
        for index in range(3, 40):
            link._on_rx(self.continuation(index, b"tail", last=index == 39))
        self.assertEqual([], messages)

        for _ in range(6):
            self.assertTrue(self.record_violation(link))
        self.assertEqual([], recorder.disconnect_calls)
        self.assertFalse(self.record_violation(link))
        self.assertEqual(
            [11], recorder.disconnect_calls,
            "the eighth logical violation must request one exact disconnect")

        self.assertFalse(self.record_violation(link))
        self.assertEqual(
            [11], recorder.disconnect_calls,
            "closed-session repeats cannot request disconnect twice")
        link._on_rx(self.first(b"closed", last=True))
        self.assertEqual([], messages, "eighth violation closes RX admission first")

    def test_orphan_run_and_empty_ble_write_have_bounded_accounting(self):
        link, recorder, messages = self.new_link()

        # One empty GATT write has no FRAG_HDR and is one malformed input.
        link._on_rx(b"")

        # One orphan continuation starts a discarded logical run.  Every tail
        # through LAST is suppressed; it is not a new violation per packet.
        link._on_rx(self.continuation(9, b"orphan"))
        for index in range(10, 16):
            link._on_rx(self.continuation(
                index, b"tail", last=index == 15))
        self.assertEqual([], messages)

        # Empty fragment DATA is legal transport syntax. A complete empty
        # message is handed upward and becomes exactly one structural-frame
        # violation at the Agent layer, not a second reassembly violation.
        link._on_rx(self.first(b"", last=True))
        self.assertEqual([b""], messages)

        # empty write + orphan run consumed exactly two link budget units.
        for _ in range(5):
            self.assertTrue(self.record_violation(link))
        self.assertEqual([], recorder.disconnect_calls)
        self.assertFalse(self.record_violation(link))
        self.assertEqual([11], recorder.disconnect_calls)

    def test_oversize_is_one_violation_and_all_tails_are_suppressed(self):
        link, recorder, messages = self.new_link()
        oversize_heads = []
        link.on_oversize(lambda head: oversize_heads.append(bytes(head)))

        safe_header = bytes((1, 1, 0x20, 0x2A, 0, 0))
        body = safe_header + (b"X" * (RX_MAX + 1 - len(safe_header)))
        offset = 0
        index = 0
        while offset < len(body):
            chunk = body[offset:offset + 243]
            offset += len(chunk)
            link._on_rx(bytes(((FIRST if index == 0 else 0) | index,)) + chunk)
            index = (index + 1) % 64

        # Tails from the already discarded run, including LAST, stay silent.
        for tail_index in range(index, index + 5):
            link._on_rx(self.continuation(
                tail_index % 64, b"tail", last=tail_index == index + 4))

        self.assertEqual([], messages)
        self.assertEqual([body[:8]], oversize_heads)
        for _ in range(6):
            self.assertTrue(self.record_violation(link))
        self.assertEqual([], recorder.disconnect_calls)
        self.assertFalse(self.record_violation(link))
        self.assertEqual([11], recorder.disconnect_calls)

    def test_first_replacement_is_legal_and_does_not_consume_budget(self):
        link, recorder, messages = self.new_link()
        for value in range(16):
            link._on_rx(self.first(bytes((value,))))
        link._on_rx(self.first(b"fresh", last=True))
        self.assertEqual([b"fresh"], messages)

        for _ in range(7):
            self.assertTrue(self.record_violation(link))
        self.assertEqual([], recorder.disconnect_calls)
        self.assertFalse(self.record_violation(link))
        self.assertEqual([11], recorder.disconnect_calls)

    def test_disconnect_reconnect_resets_budget_and_rejects_stale_token(self):
        link, recorder, _ = self.new_link(conn=11)
        old_token = link.session_token()
        self.assertTrue(self.record_violation(link, old_token))

        link._irq(2, (11, 0, b"\xaa" * 6))  # rp2 CENTRAL_DISCONNECT
        link._irq(1, (12, 0, b"\xbb" * 6))  # successor connection
        self.assertEqual((12, 2), link.session_token())
        self.assertFalse(
            self.record_violation(link, old_token),
            "stale session tokens cannot debit or terminate a successor")

        for _ in range(7):
            self.assertTrue(self.record_violation(link))
        self.assertEqual([], recorder.disconnect_calls)
        self.assertFalse(self.record_violation(link))
        self.assertEqual([12], recorder.disconnect_calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
