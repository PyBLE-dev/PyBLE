#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""Bounded, session-bound generic RSP delivery at the minimum ATT MTU."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / "firmware" / "user_c_modules" / "pyble"
BLE = (NATIVE / "pble_ble.c").read_text(encoding="utf-8")
BLE_H = (NATIVE / "pble_ble.h").read_text(encoding="utf-8")
PROTO = (NATIVE / "pble_proto.c").read_text(encoding="utf-8")
PROTO_H = (NATIVE / "pble_proto.h").read_text(encoding="utf-8")
FS = (NATIVE / "pble_fs.c").read_text(encoding="utf-8")
RUNNER = (NATIVE / "pble_runner.c").read_text(encoding="utf-8")
ALL_NATIVE = "\n".join((BLE, BLE_H, PROTO, PROTO_H, FS, RUNNER))


def c_function(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^[^\n;{{}}]*\b{re.escape(name)}\s*\([^;{{}}]*\)\s*\{{",
        source,
    )
    if match is None:
        raise AssertionError("missing function {}".format(name))
    opening = source.find("{", match.start())
    depth = 0
    state = "code"
    index = opening
    while index < len(source):
        char = source[index]
        nxt = source[index + 1] if index + 1 < len(source) else ""
        if state == "line":
            if char == "\n":
                state = "code"
        elif state == "block":
            if char == "*" and nxt == "/":
                state = "code"
                index += 1
        elif state == "string":
            if char == "\\":
                index += 1
            elif char == '"':
                state = "code"
        elif state == "char":
            if char == "\\":
                index += 1
            elif char == "'":
                state = "code"
        elif char == "/" and nxt == "/":
            state = "line"
            index += 1
        elif char == "/" and nxt == "*":
            state = "block"
            index += 1
        elif char == '"':
            state = "string"
        elif char == "'":
            state = "char"
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[match.start() : index + 1]
        index += 1
    raise AssertionError("unterminated function {}".format(name))


def code_only(source: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)


def ordered(test: unittest.TestCase, source: str, *needles: str) -> None:
    positions = [source.find(needle) for needle in needles]
    for needle, position in zip(needles, positions):
        test.assertGreaterEqual(position, 0, "missing {!r}".format(needle))
    test.assertEqual(positions, sorted(positions), "wrong operation order")


class PumpOracle:
    """Small deterministic oracle for retained-offset and absolute-time rules."""

    OK = 0
    AGAIN = -2

    def __init__(self, lengths: tuple[int, ...], deadline_ms: int = 1000) -> None:
        self.lengths = lengths
        self.deadline_ms = deadline_ms
        self.offset = 0
        self.index = 0
        self.stream_generation = 7
        self.terminated = False

    def step(self, result: int, now_ms: int, stream_generation: int = 7) -> int:
        if now_ms >= self.deadline_ms:
            self.terminated = True
            return 0
        if stream_generation != self.stream_generation:
            self.stream_generation = stream_generation
            self.offset = 0
            self.index = 0
        if result == self.OK:
            self.offset += self.lengths[self.index]
            self.index += 1
            return 1
        if result == self.AGAIN:
            return min(15, self.deadline_ms - now_ms)
        raise AssertionError("unexpected transport result")


class CompletionWakeOracle:
    """Model transition-before-give ABA on one static binary semaphore."""

    FREE = 0
    RESERVED = 1
    READY = 2
    COMPLETE = 3

    def __init__(self) -> None:
        self.state = self.FREE
        self.incarnation = 1
        self.signal = 0

    def reserve(self) -> int:
        if self.state != self.FREE:
            raise AssertionError("slot is not free")
        # A recycled static binary semaphore can retain a delayed old wake.
        # Reservation must make the new incarnation start empty.
        self.signal = 0
        self.state = self.RESERVED
        return self.incarnation

    def transition_complete(self, incarnation: int) -> int | None:
        """Commit COMPLETE, but return a give that the test may delay."""
        if (
            incarnation != self.incarnation
            or self.state in (self.FREE, self.COMPLETE)
        ):
            return None
        self.state = self.COMPLETE
        return incarnation

    def deliver_give(self, producer_incarnation: int | None) -> bool:
        """Deliver an untagged FreeRTOS binary give from any incarnation."""
        del producer_incarnation
        if self.signal:
            return False
        self.signal = 1
        return True

    def hard_recycle(self) -> None:
        self.signal = 0
        self.state = self.FREE
        self.incarnation += 1

    def wait_nowait(self, incarnation: int) -> bool | None:
        if self.signal == 0:
            return None
        self.signal = 0
        if incarnation != self.incarnation:
            return False
        if self.state in (self.RESERVED, self.READY):
            return None
        if self.state != self.COMPLETE:
            return False
        self.state = self.FREE
        self.incarnation += 1
        return True


class FrozenResponsePumpOracleTests(unittest.TestCase):
    def test_largest_response_is_26_fragments_at_att_mtu_23(self):
        frame_bytes = 6 + 1 + 480 + 4
        fragment_bytes = 23 - 3 - 1
        self.assertEqual(frame_bytes, 491)
        self.assertEqual((frame_bytes + fragment_bytes - 1) // fragment_bytes, 26)

    def test_pressure_retries_exact_fragment_but_control_restarts_first(self):
        model = PumpOracle((19, 19, 7))
        self.assertEqual(model.step(model.OK, 0), 1)
        before = (model.offset, model.index)
        self.assertEqual(model.step(model.AGAIN, 10), 15)
        self.assertEqual((model.offset, model.index), before)
        self.assertEqual(model.step(model.OK, 20, stream_generation=8), 1)
        self.assertEqual((model.offset, model.index), (19, 1))

    def test_progress_never_extends_the_absolute_deadline(self):
        model = PumpOracle((1,) * 100)
        for now in range(0, 1000, 10):
            model.step(model.OK, now)
        self.assertEqual(model.deadline_ms, 1000)
        model.step(model.AGAIN, 1000)
        self.assertTrue(model.terminated)

    def test_duplicate_completion_owns_only_one_give(self):
        model = CompletionWakeOracle()
        first = model.reserve()
        give = model.transition_complete(first)
        self.assertIsNone(model.transition_complete(first))
        self.assertTrue(model.deliver_give(give))
        self.assertEqual(model.signal, 1, "COMPLETE owns exactly one wake")
        self.assertTrue(model.wait_nowait(first))

    def test_delayed_old_give_is_ignored_until_new_incarnation_completes(self):
        model = CompletionWakeOracle()
        first = model.reserve()
        delayed_first_give = model.transition_complete(first)

        # Reset/recycle runs after old COMPLETE was committed under the pool
        # mux but before its producer performs the physical give.
        model.hard_recycle()
        second = model.reserve()
        self.assertNotEqual(second, first)
        self.assertTrue(model.deliver_give(delayed_first_give))
        self.assertIsNone(
            model.wait_nowait(second),
            "new RESERVED waiter must consume and ignore the stale old give",
        )

        second_give = model.transition_complete(second)
        self.assertTrue(model.deliver_give(second_give))
        self.assertTrue(model.wait_nowait(second))

    def test_new_complete_state_survives_binary_full_delayed_old_give(self):
        model = CompletionWakeOracle()
        first = model.reserve()
        delayed_first_give = model.transition_complete(first)
        model.hard_recycle()
        second = model.reserve()

        second_give = model.transition_complete(second)
        self.assertTrue(model.deliver_give(second_give))
        self.assertFalse(
            model.deliver_give(delayed_first_give),
            "binary-full semaphore suppresses one of the physical gives",
        )
        self.assertTrue(
            model.wait_nowait(second),
            "authoritative COMPLETE state must still complete the new waiter",
        )

    def test_reserve_drains_an_already_delivered_old_signal(self):
        model = CompletionWakeOracle()
        model.signal = 1
        second = model.reserve()
        self.assertIsNone(model.wait_nowait(second))


class NativeResponsePoolContractTests(unittest.TestCase):
    def test_pool_bounds_and_ticket_identity_are_static(self):
        for macro, value in (
            ("PBLE_RSP_POOL_DEPTH", 2),
            ("PBLE_RSP_FRAME_MAX", 491),
            ("PBLE_RSP_TX_BUDGET_MS", 1000),
            ("PBLE_RSP_RETRY_SLICE_MS", 15),
        ):
            with self.subTest(macro=macro):
                self.assertRegex(
                    ALL_NATIVE,
                    rf"#\s*define\s+{macro}\s+{value}(?:[uUlL]*)\b",
                )
        ticket = re.search(
            r"typedef\s+struct\s*\{(?P<body>.*?)\}\s*pble_rsp_ticket_t\s*;",
            PROTO_H,
            re.DOTALL,
        )
        self.assertIsNotNone(ticket, "response reservations need a typed ticket")
        for field in ("slot", "incarnation", "conn", "generation"):
            self.assertRegex(ticket.group("body"), rf"\b{field}\b")

    def test_dispatch_reserves_before_handler_and_publishes_same_slot(self):
        dispatch = code_only(c_function(PROTO, "pble_proto_dispatch"))
        ordered(
            self,
            dispatch,
            "pble_rsp_reserve",
            "status = h(",
            "pble_rsp_publish",
        )
        self.assertIn("pble_ble_terminate_session", dispatch)
        self.assertNotIn("pble_ble_notify(s_out", PROTO)

    def test_callout_is_precreated_on_the_nimble_host_event_queue(self):
        self.assertRegex(
            ALL_NATIVE,
            r"static\s+struct\s+ble_npl_callout\s+pble_rsp_callout\s*;",
        )
        init = code_only(c_function(BLE, "pble_ble_init"))
        self.assertRegex(
            init,
            r"ble_npl_callout_init\s*\(\s*&pble_rsp_callout\s*,\s*"
            r"nimble_port_get_dflt_eventq\s*\(\s*\)\s*,\s*"
            r"pble_rsp_pump_callout\b",
        )

    def test_each_callout_attempts_one_zero_wait_fragment_and_returns(self):
        callback = code_only(c_function(ALL_NATIVE, "pble_rsp_pump_callout"))
        self.assertEqual(callback.count("pble_rsp_submit_one("), 1)
        self.assertNotRegex(callback, r"\b(?:for|while)\s*\(")
        self.assertNotIn("vTaskDelay", callback)
        self.assertIn("PBLE_RSP_RETRY_SLICE_MS", callback)
        self.assertIn("ble_npl_callout_reset", callback)

        submit = code_only(c_function(ALL_NATIVE, "pble_rsp_submit_one"))
        self.assertEqual(submit.count("pble_notify_packet("), 1)
        self.assertRegex(
            submit,
            r"xSemaphoreTakeRecursive\s*\(\s*pble_tx_mutex\s*,\s*0\s*\)",
        )

    def test_disconnect_cancels_and_deadline_expiry_terminates_live_session(self):
        gap = code_only(c_function(BLE, "pble_gap_event"))
        disconnect = gap[
            gap.index("case BLE_GAP_EVENT_DISCONNECT") :
            gap.index("case BLE_GAP_EVENT_ENC_CHANGE")
        ]
        ordered(
            self,
            disconnect,
            "pble_rsp_cancel_session",
            "pble_advertise",
        )
        callback = code_only(c_function(ALL_NATIVE, "pble_rsp_pump_callout"))
        self.assertIn("deadline", callback)
        self.assertIn("pble_ble_terminate_session", callback)

    def test_only_transaction_controls_bump_stream_generation_after_ok(self):
        control = code_only(
            c_function(BLE, "pble_ble_notify_control_try_for_conn")
        )
        ordered(
            self,
            control,
            "pble_notify_packet",
            "rc == PBLE_TX_OK",
            "pble_tx_stream_generation++",
            "xSemaphoreGiveRecursive",
        )
        for handler in (
            "pble_runner_run",
            "pble_runner_stop",
            "pble_runner_soft_reboot",
        ):
            with self.subTest(handler=handler):
                self.assertIn(
                    "pble_proto_emit_rsp_status_try",
                    c_function(RUNNER, handler),
                )

    def test_completion_transitions_once_and_reserve_drains_stale_token(self):
        cancel_session = code_only(c_function(PROTO, "pble_rsp_cancel_session"))
        cancel_ticket = code_only(c_function(PROTO, "pble_rsp_cancel_ticket"))
        self.assertIn("slot->state != PBLE_RSP_COMPLETE", cancel_session)
        self.assertIn("slot->state != PBLE_RSP_COMPLETE", cancel_ticket)

        reserve = code_only(c_function(PROTO, "pble_rsp_reserve"))
        ordered(
            self,
            reserve,
            "xSemaphoreTake(s_rsp_done[i], 0)",
            "slot->state = PBLE_RSP_RESERVED",
        )

    def test_completion_wait_rechecks_tagged_state_after_every_wake(self):
        cancel_session = code_only(c_function(PROTO, "pble_rsp_cancel_session"))
        cancel_ticket = code_only(c_function(PROTO, "pble_rsp_cancel_ticket"))
        wait = code_only(c_function(PROTO, "pble_rsp_wait"))
        self.assertRegex(wait, r"\b(?:while|for)\s*\(")
        ordered(
            self,
            wait,
            "xSemaphoreTake",
            "taskENTER_CRITICAL",
            "pble_rsp_ticket_matches_locked",
            "taskEXIT_CRITICAL",
        )
        self.assertIn("PBLE_RSP_RESERVED", wait)
        self.assertIn("PBLE_RSP_READY", wait)
        self.assertIn("PBLE_RSP_COMPLETE", wait)
        self.assertIn("continue;", wait)

        # Producers commit state under the pool mux and only then perform the
        # untagged give, so the waiter loop—not mutex-held signaling—closes ABA.
        for body in (cancel_session, cancel_ticket):
            give = body.find("xSemaphoreGive")
            self.assertGreater(give, body.rfind("taskEXIT_CRITICAL", 0, give))


class NativeDeferredResponseContractTests(unittest.TestCase):
    def test_fs_item_carries_ticket_and_queue_full_publishes_ebusy(self):
        item = re.search(
            r"typedef\s+struct\s*\{(?P<body>.*?)\}\s*pble_fs_req_t\s*;",
            FS,
            re.DOTALL,
        )
        self.assertIsNotNone(item)
        self.assertRegex(item.group("body"), r"pble_rsp_ticket_t\s+ticket\b")
        enqueue = code_only(c_function(FS, "fs_enqueue"))
        self.assertIn("pble_rsp_ticket_t", enqueue.partition("{")[0])
        ordered(
            self,
            enqueue,
            "xQueueSend",
            "PBLE_EBUSY",
            "pble_rsp_publish",
        )

    def test_worker_revalidates_ticket_and_get_waits_for_rsp_completion(self):
        dispatch = code_only(c_function(FS, "fs_dispatch"))
        ordered(
            self,
            dispatch,
            "pble_rsp_ticket_valid",
            "fs_do_",
            "pble_rsp_publish",
        )
        get = code_only(c_function(FS, "fs_do_get"))
        ordered(
            self,
            get,
            "pble_rsp_publish",
            "pble_rsp_wait",
            "PBLE_OP_FILE_GET_DATA",
            "PBLE_OP_FILE_GET_END",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
