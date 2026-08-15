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


class FrozenCapacityModelTests(unittest.TestCase):
    """Pure model: payload is allocated before the msys_1 reserve check."""

    @staticmethod
    def bulk_can_submit(msys1_free_after_payload: int) -> bool:
        wrapper_blocks = 1
        control_reserve_blocks = 2
        return msys1_free_after_payload >= wrapper_blocks + control_reserve_blocks

    def test_bulk_never_consumes_the_two_control_blocks(self):
        for free in (0, 1, 2):
            self.assertFalse(self.bulk_can_submit(free))
        self.assertTrue(self.bulk_can_submit(3))
        self.assertEqual(3 - 1, 2, "ATT wrapper submission leaves the reserve")

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


class NativeReserveSourceContractTests(unittest.TestCase):
    def test_bulk_reserve_uses_the_exact_msys1_pool(self):
        self.assertRegex(BLE, r"#\s*define\s+PBLE_TX_BULK_RESERVE_BLOCKS\s+2\b")
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
        for name in (
            "pble_control_tx_boundary_begin",
            "pble_control_tx_boundary_pending",
            "pble_control_tx_boundary_end",
        ):
            with self.subTest(helper=name):
                helper = code_only(function(BLE, name))
                self.assertIn("taskENTER_CRITICAL", helper)
                self.assertIn("taskEXIT_CRITICAL", helper)

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
        message = code_only(function(BLE, "pble_notify_message"))
        self.assertNotIn(
            "pble_control_tx_boundary_pending",
            message,
            "a pending control must not truncate an in-progress fragment run",
        )


class ConsoleAndStopSourceContractTests(unittest.TestCase):
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
