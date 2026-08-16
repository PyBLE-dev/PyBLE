#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""ADR-0032 C3-G2: control traffic survives an ESP console flood."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / "firmware" / "user_c_modules" / "pyble"
BLE = (NATIVE / "pble_ble.c").read_text(encoding="utf-8")
BLE_H = (NATIVE / "pble_ble.h").read_text(encoding="utf-8")
CONSOLE = (NATIVE / "pble_console.c").read_text(encoding="utf-8")
RUNNER = (NATIVE / "pble_runner.c").read_text(encoding="utf-8")
PROTO = (NATIVE / "pble_proto.c").read_text(encoding="utf-8")


def function(source: str, name: str) -> str:
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


def ordered(test: unittest.TestCase, text: str, *needles: str) -> None:
    positions = [text.find(needle) for needle in needles]
    for needle, position in zip(needles, positions):
        test.assertGreaterEqual(position, 0, "missing {!r}".format(needle))
    test.assertEqual(positions, sorted(positions), "wrong operation order")


def code_only(source: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)


def braced_block(source: str, opening: int) -> tuple[str, int]:
    """Return one balanced C block and the index immediately after it."""
    if opening < 0 or source[opening] != "{":
        raise AssertionError("missing opening brace")
    depth = 0
    state = "code"
    index = opening
    while index < len(source):
        char = source[index]
        if state == "string":
            if char == "\\":
                index += 1
            elif char == '"':
                state = "code"
        elif state == "char":
            if char == "\\":
                index += 1
            elif char == "'":
                state = "code"
        elif char == '"':
            state = "string"
        elif char == "'":
            state = "char"
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[opening : index + 1], index + 1
        index += 1
    raise AssertionError("unterminated C block")


def pending_branch(source: str) -> tuple[str, str]:
    """Return explicit pending and non-pending branches from a TX sender."""
    match = re.search(
        r"if\s*\(\s*pble_control_tx_boundary_pending\s*\(\s*\)\s*\)\s*\{",
        source,
    )
    if match is None:
        raise AssertionError("missing explicit specialized-pending branch")
    pending, after_pending = braced_block(source, source.find("{", match.start()))
    alternate = re.match(r"\s*else\s*\{", source[after_pending:])
    if alternate is None:
        raise AssertionError("pending gate must have an explicit non-pending branch")
    opening = source.find("{", after_pending + alternate.start())
    non_pending, _ = braced_block(source, opening)
    return pending, non_pending


class FrozenCapacityModelTests(unittest.TestCase):
    """Pure model: payload is allocated before the msys_1 reserve check."""

    @staticmethod
    def bulk_can_submit(msys1_free_after_payload: int) -> bool:
        bulk_wrapper_blocks = 1
        acknowledged_stop_blocks = 4
        return (
            msys1_free_after_payload
            >= bulk_wrapper_blocks + acknowledged_stop_blocks
        )

    def test_bulk_preserves_the_full_acknowledged_stop_transaction(self):
        for free in range(5):
            self.assertFalse(self.bulk_can_submit(free))
        self.assertTrue(self.bulk_can_submit(5))

        free = 5 - 1  # the admitted bulk notification's ATT wrapper
        self.assertEqual(free, 4, "bulk submission must leave the exact reserve")
        for owner in (
            "incoming acknowledged-write request",
            "preallocated ATT write response",
            "PBLE/1 response data",
            "ATT notification wrapper",
        ):
            self.assertGreater(free, 0, owner)
            free -= 1
        self.assertEqual(free, 0)

    def test_console_payload_bound_is_one_fragment_at_every_valid_mtu(self):
        for mtu in range(23, 248):
            console_bytes = min(200, mtu - 15)
            encoded_message = 6 + 1 + console_bytes + 4
            fragment_payload = mtu - 4
            self.assertLessEqual(encoded_message, fragment_payload)

    def test_pending_control_owns_the_next_complete_message_boundary(self):
        current_bulk_message_active = True
        specialized_pending = True

        later_bulk_may_start = not specialized_pending
        self.assertFalse(later_bulk_may_start)

        # The current message remains atomic; only its completion releases the
        # physical boundary to the already-pending specialized response.
        current_bulk_message_active = False
        specialized_may_submit = specialized_pending and not current_bulk_message_active
        self.assertTrue(specialized_may_submit)
        self.assertEqual(1 if specialized_may_submit else 0, 1)


class FrozenConsolePacingModelTests(unittest.TestCase):
    """Pure model for the ESP console-only no-catch-up admission clock."""

    INTERVAL_US = 40_000

    @classmethod
    def attempt_starts(cls, durations_us: list[int]) -> list[int]:
        now_us = 0
        next_us = 0
        starts = []
        for duration_us in durations_us:
            now_us = max(now_us, next_us)
            starts.append(now_us)
            now_us += duration_us
            # Mint from actual completion, never advance an old schedule.
            next_us = now_us + cls.INTERVAL_US
        return starts

    def test_first_is_immediate_and_five_hundred_ms_has_no_burst(self):
        starts = self.attempt_starts([0] * 60)
        self.assertEqual(starts[0], 0)
        self.assertEqual(starts[:4], [0, 40_000, 80_000, 120_000])
        self.assertEqual(len([value for value in starts if value < 500_000]), 13)
        self.assertLessEqual(
            len([value for value in starts if value <= 2_000_000]),
            51,
        )

    def test_delayed_attempt_mints_from_completion_without_catch_up(self):
        starts = self.attempt_starts([0, 250_000, 0])
        self.assertEqual(starts, [0, 40_000, 330_000])
        self.assertEqual(starts[2] - (starts[1] + 250_000), self.INTERVAL_US)


class NativeReserveSourceContractTests(unittest.TestCase):
    def test_bulk_reserve_uses_the_exact_msys1_pool(self):
        self.assertRegex(BLE, r"#\s*define\s+PBLE_TX_BULK_RESERVE_BLOCKS\s+4\b")
        self.assertIn('"os/os_mempool.h"', BLE)
        pool = function(BLE, "pble_msys1_num_free")
        self.assertIn("os_mempool_info_get_next", pool)
        self.assertIn('"msys_1"', pool)
        self.assertNotIn("os_msys_num_free", BLE)

    def test_bulk_admission_allocates_data_then_preserves_wrapper_plus_reserve(self):
        packet = function(BLE, "pble_notify_packet")
        ordered(
            self,
            packet,
            "ble_hs_mbuf_from_flat",
            "pble_msys1_num_free",
            "ble_gatts_notify_custom",
        )
        self.assertRegex(
            packet,
            r"PBLE_TX_ATT_WRAPPER_BLOCKS\s*\+\s*reserve_blocks",
        )
        self.assertIn("os_mbuf_free_chain", packet)

    def test_paced_messages_are_one_fragment_and_wait_outside_the_tx_mutex(self):
        paced = function(BLE, "pble_ble_notify_paced_with_reserve")
        self.assertIn("PBLE_TX_OVERSIZE", BLE_H)
        self.assertRegex(paced, r"len\s*>\s*pble_payload_size")
        self.assertRegex(paced, r"PBLE_FRAG_FIRST\s*\|\s*PBLE_FRAG_LAST")
        self.assertNotRegex(paced, r"offset\s*<\s*len")
        ordered(
            self,
            paced,
            "xSemaphoreTakeRecursive",
            "pble_notify_packet",
            "xSemaphoreGiveRecursive",
            "xSemaphoreTake(pble_tx_drain_sem",
        )

    def test_bulk_and_control_paced_entrypoints_are_separate(self):
        self.assertIn("pble_ble_notify_control_paced", BLE_H)
        bulk = function(BLE, "pble_ble_notify_paced")
        control = function(BLE, "pble_ble_notify_control_paced")
        self.assertIn("PBLE_TX_BULK_RESERVE_BLOCKS", bulk)
        self.assertRegex(control, r"with_reserve\s*\([^;]+,\s*0\s*\)")
        self.assertIn("pble_proto_emit_control_paced", PROTO)
        self.assertIn("pble_proto_emit_control_paced", RUNNER)

    def test_specialized_pending_gate_is_owned_until_after_mutex_release(self):
        begin = code_only(function(BLE, "pble_control_tx_boundary_begin"))
        state_set = re.search(
            r"\b(?P<state>pble_[A-Za-z_]\w*)\s*=\s*true\s*;",
            begin,
        )
        self.assertIsNotNone(state_set, "begin must set the shared bool true")
        state = state_set.group("state")
        self.assertRegex(
            BLE,
            rf"static\s+bool\s+{re.escape(state)}(?:\s*=\s*false)?\s*;",
        )
        ordered(
            self,
            begin,
            "taskENTER_CRITICAL",
            "{} = true;".format(state),
            "taskEXIT_CRITICAL",
        )
        self.assertEqual(begin.count("{} = true;".format(state)), 1)

        pending = code_only(function(BLE, "pble_control_tx_boundary_pending"))
        state_read = re.search(
            rf"\b(?P<local>[A-Za-z_]\w*)\s*=\s*{re.escape(state)}\s*;",
            pending,
        )
        self.assertIsNotNone(
            state_read,
            "pending must read the exact shared bool under its critical section",
        )
        local = state_read.group("local")
        self.assertRegex(pending, rf"\bbool\s+{re.escape(local)}\b")
        ordered(
            self,
            pending,
            "taskENTER_CRITICAL",
            "{} = {};".format(local, state),
            "taskEXIT_CRITICAL",
            "return {};".format(local),
        )

        end = code_only(function(BLE, "pble_control_tx_boundary_end"))
        ordered(
            self,
            end,
            "taskENTER_CRITICAL",
            "{} = false;".format(state),
            "taskEXIT_CRITICAL",
        )
        self.assertEqual(end.count("{} = false;".format(state)), 1)

        for helper in (begin, pending, end):
            self.assertNotIn(
                "xSemaphoreTake",
                helper,
                "the pending-state critical section must never cover a TX wait",
            )

        control = code_only(
            function(BLE, "pble_ble_notify_control_try_for_conn")
        )
        ordered(
            self,
            control,
            "pble_control_tx_boundary_begin()",
            "xSemaphoreTakeRecursive(pble_tx_mutex",
            "pble_notify_packet",
            "xSemaphoreGiveRecursive(pble_tx_mutex)",
            "pble_control_tx_boundary_end()",
        )
        self.assertNotIn("taskENTER_CRITICAL", control)
        self.assertNotIn("taskEXIT_CRITICAL", control)

    def test_paced_bulk_rechecks_pending_after_lock_before_notify(self):
        paced = code_only(function(BLE, "pble_ble_notify_paced_with_reserve"))
        ordered(
            self,
            paced,
            "xSemaphoreTakeRecursive(pble_tx_mutex",
            "pble_control_tx_boundary_pending()",
            "pble_notify_packet",
            "xSemaphoreGiveRecursive(pble_tx_mutex)",
        )
        pending, non_pending = pending_branch(paced)
        self.assertIn("PBLE_TX_AGAIN", pending)
        self.assertNotIn("pble_notify_packet", pending)
        self.assertIn("pble_notify_packet", non_pending)
        self.assertIn("pble_rsp_owner_active", non_pending)
        self.assertEqual(paced.count("pble_notify_packet("), 1)

    def test_general_bulk_rechecks_pending_only_at_complete_message_boundary(self):
        general = code_only(function(BLE, "pble_ble_notify"))
        ordered(
            self,
            general,
            "xSemaphoreTakeRecursive(pble_tx_mutex",
            "pble_control_tx_boundary_pending()",
            "pble_notify_message",
            "xSemaphoreGiveRecursive(pble_tx_mutex)",
        )
        pending, non_pending = pending_branch(general)
        self.assertIn("PBLE_TX_AGAIN", pending)
        self.assertNotIn("pble_notify_message", pending)
        self.assertIn("pble_notify_message", non_pending)
        self.assertIn("pble_rsp_owner_active", non_pending)
        self.assertEqual(general.count("pble_notify_message("), 1)
        message = code_only(function(BLE, "pble_notify_message"))
        self.assertNotIn(
            "pble_control_tx_boundary_pending",
            message,
            "a pending control must not truncate an in-progress fragment run",
        )


class ConsoleAndStopSourceContractTests(unittest.TestCase):
    def test_console_has_exact_completion_based_no_burst_pacer(self):
        self.assertRegex(
            CONSOLE,
            r"#\s*define\s+PBLE_CONSOLE_NOTIFY_INTERVAL_MS\s+40u\b",
        )
        self.assertIn('"esp_timer.h"', CONSOLE)

        wait = code_only(function(CONSOLE, "console_wait_notify_interval"))
        self.assertIn("esp_timer_get_time()", wait)
        self.assertIn("vTaskDelay", wait)
        self.assertRegex(wait, r"while\s*\([^)]*deadline_us[^)]*\)")
        self.assertNotIn("pble_tx_mutex", wait)
        self.assertNotIn("xSemaphore", wait)

        complete = code_only(
            function(CONSOLE, "console_complete_notify_attempt")
        )
        self.assertIn("esp_timer_get_time()", complete)
        self.assertIn("PBLE_CONSOLE_NOTIFY_INTERVAL_MS", complete)
        self.assertNotIn("+=", complete)
        self.assertRegex(
            complete,
            r"g_console_next_notify_us\s*=\s*[^;]*esp_timer_get_time\s*\(\s*\)"
            r"[^;]*PBLE_CONSOLE_NOTIFY_INTERVAL_MS[^;]*;",
        )

    def test_console_wait_is_off_gil_then_rechecks_stop_before_submit(self):
        out = code_only(function(CONSOLE, "pble_console_out"))
        snapshot_at = out.index("pble_ble_session_snapshot_current")
        wait_at = out.index("console_wait_notify_interval", snapshot_at)
        stop_at = out.index("pble_runner_stop_requested()", wait_at)
        emit_at = out.index("pble_proto_emit_paced", stop_at)
        complete_at = out.index("console_complete_notify_attempt", emit_at)

        self.assertLess(snapshot_at, wait_at)
        self.assertLess(wait_at, stop_at)
        self.assertLess(stop_at, emit_at)
        self.assertLess(emit_at, complete_at)
        self.assertIn("MP_THREAD_GIL_EXIT()", out[snapshot_at:wait_at])
        self.assertIn("MP_THREAD_GIL_ENTER()", out[wait_at:stop_at])
        self.assertIn("MP_THREAD_GIL_EXIT()", out[stop_at:emit_at])
        self.assertIn("MP_THREAD_GIL_ENTER()", out[complete_at:])

    def test_console_pacer_omits_offline_without_wait_and_keeps_one_session(self):
        out = code_only(function(CONSOLE, "pble_console_out"))
        self.assertEqual(out.count("pble_ble_session_snapshot_current("), 1)
        offline = re.search(
            r"if\s*\(\s*!\s*pble_ble_session_snapshot_current\s*\("
            r"\s*&event_session\s*\)\s*\)\s*\{(?P<body>.*?)\}",
            out,
            re.DOTALL,
        )
        self.assertIsNotNone(offline)
        self.assertIn("continue", offline.group("body"))
        self.assertNotIn("console_wait_notify_interval", offline.group("body"))
        self.assertRegex(
            out,
            r"pble_proto_emit_paced\s*\([^;]+&event_session\s*\)",
        )

        reset = code_only(function(CONSOLE, "pble_console_vm_reset"))
        self.assertRegex(reset, r"g_console_next_notify_us\s*=\s*0\s*;")

    def test_console_chunk_is_dynamic_and_stops_emitting_after_stop(self):
        out = function(CONSOLE, "pble_console_out")
        self.assertIn("pble_ble_mtu()", out)
        self.assertRegex(CONSOLE, r"#\s*define\s+PBLE_CONSOLE_FRAME_OVERHEAD\s+15\b")
        self.assertIn("PBLE_CONSOLE_CHUNK", out)
        self.assertIn("PBLE_CONSOLE_FRAME_OVERHEAD", out)
        self.assertIn("pble_runner_stop_requested()", out)
        self.assertIn("pble_proto_emit_paced", out)

    def test_stop_submits_exact_rsp_before_interrupt_and_suppresses_duplicate(self):
        stop = function(RUNNER, "pble_runner_stop")
        signature = stop.partition("{")[0]
        token_param = re.search(
            r"(?:const\s+)?pble_session_token_t\s*\*?\s*([A-Za-z_]\w*)",
            signature,
        )
        self.assertIsNotNone(token_param, "STOP must receive the dispatch token")
        response_call = re.search(
            r"pble_proto_emit_rsp_status_try\s*\(\s*req->opcode\s*,\s*"
            r"req->id\s*,\s*PBLE_OK\s*,\s*&?\s*"
            rf"{re.escape(token_param.group(1))}\s*\)",
            stop,
        )
        self.assertIsNotNone(
            response_call,
            "STOP must submit its status with the originating token",
        )
        self.assertEqual(stop.count("pble_proto_emit_rsp_status_try("), 1)
        tx_result = re.search(
            r"\b(?:int|pble_tx_result_t)\s+([A-Za-z_]\w*)\s*=\s*"
            r"pble_proto_emit_rsp_status_try\s*\(",
            stop,
        )
        self.assertIsNotNone(
            tx_result,
            "STOP must retain the specialized submission result",
        )
        failure = re.search(
            rf"if\s*\(\s*{re.escape(tx_result.group(1))}\s*!=\s*"
            r"PBLE_TX_OK\s*\)\s*\{(?P<body>.*?)\}",
            stop,
            re.DOTALL,
        )
        self.assertIsNotNone(
            failure,
            "every non-OK STOP submission must fail closed",
        )
        self.assertIn(
            "runner_control_attempt_resolve(false)",
            failure.group("body"),
            "failed STOP submission must release pickup without stop intent",
        )
        self.assertIn("return PBLE_NO_RSP;", failure.group("body"))

        resolver = function(RUNNER, "runner_control_attempt_resolve")
        accepted_param = re.search(
            r"runner_control_attempt_resolve\s*\(\s*bool\s+"
            r"(?P<name>[A-Za-z_]\w*)",
            resolver,
        )
        self.assertIsNotNone(accepted_param)
        accepted_branch = re.search(
            rf"if\s*\(\s*{re.escape(accepted_param.group('name'))}\s*\)\s*"
            r"\{(?P<body>.*?)\}",
            resolver,
            re.DOTALL,
        )
        self.assertIsNotNone(accepted_branch)
        ordered(
            self,
            accepted_branch.group("body"),
            "g_stop_requested = true",
            "inject_worker_kbd_interrupt",
        )
        self.assertNotIn("g_stop_requested = true", stop)
        self.assertNotIn("inject_worker_kbd_interrupt", stop)
        ordered(
            self,
            stop,
            "pble_proto_emit_rsp_status_try",
            "runner_control_attempt_resolve(true)",
        )
        self.assertIn("return PBLE_NO_RSP", stop)
        self.assertNotRegex(stop, r"return\s+PBLE_OK\s*;")
        self.assertNotRegex(
            stop,
            r"pble_proto_emit_id\s*\(\s*PBLE_TYPE_RSP\b",
        )

    def test_expected_stop_interrupt_does_not_emit_a_traceback(self):
        execute = function(RUNNER, "runner_exec")
        self.assertIn("pble_runner_stop_requested()", execute)
        self.assertRegex(
            execute,
            r"if\s*\(\s*!\s*pble_runner_stop_requested\s*\(\s*\)\s*\)"
            r"\s*\{[^}]*mp_obj_print_exception",
        )
        self.assertIn("mp_obj_print_exception", execute)


if __name__ == "__main__":
    unittest.main(verbosity=2)
