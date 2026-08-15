#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""RED: bounded, exact-token, fail-closed GAP session termination."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / "firmware" / "user_c_modules" / "pyble"
BLE_PATH = NATIVE / "pble_ble.c"
BLE_H_PATH = NATIVE / "pble_ble.h"
PROTO_PATH = NATIVE / "pble_proto.c"
PROTO_H_PATH = NATIVE / "pble_proto.h"
POLICY_C = NATIVE / "pble_termination.c"
POLICY_H = NATIVE / "pble_termination.h"
HARNESS = Path(__file__).with_name("native") / "failed_session_termination_harness.c"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^[^\n;{{}}]*\b{re.escape(name)}\s*\([^;{{}}]*\)\s*\{{",
        source,
    )
    if match is None:
        raise AssertionError(f"missing function {name}")
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
    raise AssertionError(f"unterminated function {name}")


def _code(source: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)


def _ordered(test: unittest.TestCase, source: str, *needles: str) -> None:
    positions = [source.find(needle) for needle in needles]
    for needle, position in zip(needles, positions):
        test.assertGreaterEqual(position, 0, f"missing {needle!r}")
    test.assertEqual(positions, sorted(positions), "wrong operation order")


def _assert_between(
    test: unittest.TestCase,
    source: str,
    start_needle: str,
    end_needle: str,
    *needles: str,
) -> None:
    start = source.find(start_needle)
    end = source.find(end_needle, start + len(start_needle))
    test.assertGreaterEqual(start, 0, f"missing {start_needle!r}")
    test.assertGreater(end, start, f"missing ordered {end_needle!r}")
    for needle in needles:
        position = source.find(needle, start + len(start_needle), end)
        test.assertGreaterEqual(
            position,
            0,
            f"{needle!r} is not between {start_needle!r} and {end_needle!r}",
        )


def _case_branch(source: str, label: str) -> str:
    start = source.find(f"case {label}")
    if start < 0:
        raise AssertionError(f"missing explicit {label} case")
    following_case = source.find("case ", start + len("case "))
    following_default = source.find("default:", start + len("case "))
    ends = [position for position in (following_case, following_default) if position >= 0]
    return source[start : min(ends) if ends else len(source)]


def _assert_inside_session_critical(
    test: unittest.TestCase, source: str, needle: str
) -> None:
    enter_needle = "taskENTER_CRITICAL(&pble_session_mux)"
    leave_needle = "taskEXIT_CRITICAL(&pble_session_mux)"
    position = source.find(needle)
    test.assertGreaterEqual(position, 0, f"missing {needle!r}")
    enter = source.rfind(enter_needle, 0, position)
    prior_leave = source.rfind(leave_needle, 0, position)
    leave = source.find(leave_needle, position)
    test.assertGreaterEqual(enter, 0, f"{needle!r} is not after the session lock")
    test.assertGreater(
        enter,
        prior_leave,
        f"{needle!r} follows an intervening session unlock",
    )
    test.assertGreaterEqual(leave, 0, f"{needle!r} is not before session unlock")


def _assert_same_session_critical(
    test: unittest.TestCase, source: str, first: str, last: str
) -> None:
    enter_needle = "taskENTER_CRITICAL(&pble_session_mux)"
    leave_needle = "taskEXIT_CRITICAL(&pble_session_mux)"
    first_position = source.find(first)
    test.assertGreaterEqual(first_position, 0, f"missing {first!r}")
    last_position = source.find(last, first_position + len(first))
    test.assertGreater(last_position, first_position, f"missing ordered {last!r}")
    enter = source.rfind(enter_needle, 0, first_position)
    test.assertGreaterEqual(enter, 0, f"{first!r} is outside the session lock")
    intervening_leave = source.find(leave_needle, enter, last_position)
    test.assertEqual(
        intervening_leave,
        -1,
        f"session lock is released between {first!r} and {last!r}",
    )
    test.assertGreaterEqual(
        source.find(leave_needle, last_position),
        0,
        f"{last!r} has no following session unlock",
    )


def _assert_tx_serialized_session_call(
    test: unittest.TestCase, source: str, needle: str
) -> None:
    position = source.find(needle)
    test.assertGreaterEqual(position, 0, f"missing {needle!r}")
    take_needle = "xSemaphoreTakeRecursive(pble_tx_mutex"
    give_needle = "xSemaphoreGiveRecursive(pble_tx_mutex)"
    take = source.rfind(take_needle, 0, position)
    prior_give = source.rfind(give_needle, 0, position)
    enter = source.rfind("taskENTER_CRITICAL(&pble_session_mux)", 0, position)
    leave = source.find("taskEXIT_CRITICAL(&pble_session_mux)", position)
    give = source.find(give_needle, position)
    test.assertGreaterEqual(take, 0, f"{needle!r} is not under the TX mutex")
    test.assertGreater(
        take,
        prior_give,
        f"{needle!r} follows an intervening TX-mutex unlock",
    )
    test.assertGreater(enter, take, "session lock must follow TX-mutex acquisition")
    test.assertGreaterEqual(leave, 0, f"{needle!r} has no session unlock")
    test.assertGreaterEqual(give, 0, f"{needle!r} has no following TX unlock")
    test.assertLess(leave, give, "session lock must be released before the TX mutex")


class FailedSessionTerminationReducerTest(unittest.TestCase):
    def test_host_reducer_and_mock_adapter_cover_the_full_matrix(self) -> None:
        self.assertTrue(
            POLICY_C.is_file() and POLICY_H.is_file(),
            "[FR-PROTO-6] missing host-compilable pble_termination.c/.h",
        )
        compiler = shutil.which(os.environ.get("CC", "cc"))
        self.assertIsNotNone(compiler, "host C compiler is required")
        with tempfile.TemporaryDirectory(prefix="pble-term-") as temp_dir:
            executable = Path(temp_dir) / "failed_session_termination"
            build = subprocess.run(
                [
                    compiler,
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-pedantic",
                    "-I",
                    str(NATIVE),
                    str(HARNESS),
                    str(POLICY_C),
                    "-o",
                    str(executable),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                build.returncode,
                0,
                "host reducer compile failed:\n{}{}".format(
                    build.stdout, build.stderr
                ),
            )
            run = subprocess.run(
                [str(executable)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                run.returncode,
                0,
                "host reducer scenarios failed:\n{}{}".format(
                    run.stdout, run.stderr
                ),
            )


class FailedSessionTerminationIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ble = _source(BLE_PATH)
        cls.ble_h = _source(BLE_H_PATH)
        cls.proto = _source(PROTO_PATH)
        cls.proto_h = _source(PROTO_H_PATH)
        cls.policy_h = _source(POLICY_H) if POLICY_H.is_file() else ""
        cls.native_files = tuple(sorted(NATIVE.glob("*.c"))) + tuple(
            sorted(NATIVE.glob("*.h"))
        )
        cls.all_native = "\n".join(_source(path) for path in cls.native_files)
        cls.all_native_c = "\n".join(
            _source(path) for path in sorted(NATIVE.glob("*.c"))
        )

    def test_cold_init_creates_one_task_watchdog_before_nimble(self) -> None:
        self.assertIn('#include "esp_timer.h"', self.ble)
        self.assertIn('#include "esp_system.h"', self.ble)
        self.assertIn('#include "pble_termination.h"', self.ble)
        self.assertRegex(self.ble, r"static\s+bool\s+pble_term_initialized\b")
        self.assertRegex(
            self.ble,
            r"static\s+pble_term_watchdog_ticket_t\s+"
            r"pble_term_armed_ticket\b",
        )
        init = _code(_function(self.ble, "pble_ble_init"))
        self.assertRegex(init, r"if\s*\(\s*!pble_term_initialized\s*\)")
        self.assertEqual(init.count("pble_term_init("), 1)
        self.assertEqual(self.ble.count("pble_term_init("), 1)
        self.assertEqual(_code(self.all_native_c).count("pble_term_init("), 2)
        self.assertEqual(init.count("esp_timer_create("), 1)
        self.assertEqual(_code(self.ble).count("esp_timer_create("), 1)
        self.assertNotRegex(
            _code(self.all_native_c),
            r"pble_term_initialized\s*=\s*(?:false|0)\b",
        )
        self.assertEqual(
            len(re.findall(r"pble_term_initialized\s*=\s*true\b", self.ble)),
            1,
        )
        self.assertIn(".dispatch_method = ESP_TIMER_TASK", init)
        self.assertRegex(
            init,
            r"\.arg\s*=\s*(?:\(void\s*\*\)\s*)?&pble_term_armed_ticket",
        )
        _ordered(
            self,
            init,
            "pble_term_init",
            "esp_timer_create",
            "pble_term_initialized = true",
            "nimble_port_init",
            "nimble_port_freertos_init",
        )
        create_to_nimble = init[
            init.index("esp_timer_create") : init.index("nimble_port_init")
        ]
        self.assertRegex(
            create_to_nimble,
            r"if\s*\([^)]*(?:!=\s*ESP_OK|==\s*ESP_OK)[^)]*\)\s*\{",
        )
        self.assertRegex(create_to_nimble, r"mp_raise|esp_restart|return\s*;")
        self.assertNotIn("pble_term_init", _function(self.ble, "pble_ble_init_agent"))

    def test_gap_connect_opens_exact_token_before_exposure(self) -> None:
        gap = _code(_function(self.ble, "pble_gap_event"))
        connect = _case_branch(gap, "BLE_GAP_EVENT_CONNECT")
        self.assertIn("pble_term_open", connect)
        self.assertRegex(connect, r"if\s*\(\s*!\s*[A-Za-z_]\w*\s*\)")
        self.assertIn("esp_restart", connect)
        _assert_inside_session_critical(self, connect, "pble_term_open")
        _assert_tx_serialized_session_call(self, connect, "pble_term_open")
        _assert_same_session_critical(
            self, connect, "pble_term_open", "pble_conn_handle ="
        )
        self.assertRegex(
            connect,
            r"pble_conn_generation_counter\s*==\s*0",
        )
        _ordered(
            self,
            connect,
            "pble_conn_generation_counter++",
            "pble_term_open",
            "pble_conn_handle =",
            "taskEXIT_CRITICAL(&pble_session_mux)",
            "esp_restart",
            "pble_ready_refresh",
        )

    def test_open_to_closing_and_watchdog_arm_are_effect_driven(self) -> None:
        close = _code(_function(self.ble, "pble_ble_terminate_session"))
        _assert_inside_session_critical(self, close, "pble_term_begin")
        _assert_inside_session_critical(self, close, "pble_term_watchdog_armed")
        _assert_inside_session_critical(self, close, "pble_term_gap_result")
        _assert_tx_serialized_session_call(self, close, "pble_term_begin")
        _assert_same_session_critical(
            self, close, "pble_term_begin", "pble_term_watchdog_armed"
        )
        _ordered(
            self,
            close,
            "esp_timer_get_time",
            "pble_term_begin",
            "PBLE_TERM_EFFECT_ARM_WATCHDOG",
            "pble_term_watchdog_ticket",
            "pble_term_remaining_us",
            "esp_timer_start_once",
            "pble_term_watchdog_armed",
            "PBLE_TERM_EFFECT_CALL_GAP",
            "ble_gap_terminate",
            "pble_term_gap_result",
        )
        arm_ack = close.find("pble_term_watchdog_armed")
        arm_unlock = close.find(
            "taskEXIT_CRITICAL(&pble_session_mux)", arm_ack
        )
        tx_unlock = close.find("xSemaphoreGiveRecursive(pble_tx_mutex)", arm_unlock)
        gap_effect = close.find("PBLE_TERM_EFFECT_CALL_GAP", tx_unlock)
        gap_call = close.find("ble_gap_terminate", gap_effect)
        positions = [arm_ack, arm_unlock, tx_unlock, gap_effect, gap_call]
        self.assertTrue(all(position >= 0 for position in positions))
        self.assertEqual(
            positions,
            sorted(positions),
        )
        self.assertGreaterEqual(close.count("esp_timer_get_time("), 2)
        self.assertRegex(
            close,
            r"(?:initial_)?remaining_us\s*=\s*pble_term_remaining_us\s*\(",
        )
        self.assertRegex(
            close,
            r"esp_timer_start_once\s*\([^;]*\b(?:initial_)?remaining_us\b[^;]*\)",
        )
        self.assertRegex(
            close,
            r"if\s*\(\s*(?:initial_)?remaining_us\s*(?:==\s*0|<=\s*0)\s*\)",
        )
        self.assertIn("PBLE_TERM_EFFECT_RESTART", close)
        self.assertIn("esp_restart", close)
        self.assertIn("ESP_OK", close)
        self.assertEqual(close.count("ble_gap_terminate("), 1)
        self.assertNotRegex(close, r"\b(?:for|while)\s*\(")

    def test_gap_result_classification_is_exact_and_non_retrying(self) -> None:
        close = _code(_function(self.ble, "pble_ble_terminate_session"))
        self.assertRegex(
            close,
            r"rc\s*==\s*0\s*\|\|\s*rc\s*==\s*BLE_HS_EALREADY",
        )
        self.assertEqual(close.count("ble_gap_terminate("), 1)
        self.assertNotIn("ble_npl_callout_reset", close)
        self.assertNotIn("esp_timer_start_periodic", close)

    def test_snapshot_and_live_are_open_only_under_session_lock(self) -> None:
        for name in ("pble_ble_session_snapshot", "pble_ble_session_live"):
            with self.subTest(name=name):
                body = _code(_function(self.ble, name))
                _assert_inside_session_critical(self, body, "pble_term_admits")

    def test_dispatch_and_sole_notify_exit_require_exact_tokens(self) -> None:
        token = re.search(
            r"typedef\s+struct\s*\{(?P<body>.*?)\}\s*pble_session_token_t\s*;",
            self.ble_h + "\n" + self.policy_h,
            re.DOTALL,
        )
        self.assertIsNotNone(token, "BLE transport needs a full session token type")
        self.assertRegex(token.group("body"), r"\bconn\b")
        self.assertRegex(token.group("body"), r"\bgeneration\b")

        snapshot_decl = re.search(
            r"\bpble_ble_session_snapshot\s*\([^;]+\)\s*;", self.ble_h
        )
        self.assertIsNotNone(snapshot_decl)
        self.assertIn("pble_session_token_t", snapshot_decl.group(0))

        for handler_type in ("pble_handler_t", "pble_deferred_handler_t"):
            handler_decl = re.search(
                rf"typedef\s+[^;]+\(\s*\*\s*{handler_type}\s*\)\s*"
                r"\([^;]+\)\s*;",
                self.proto_h,
                re.DOTALL,
            )
            self.assertIsNotNone(handler_decl, f"missing {handler_type} ABI")
            self.assertIn("pble_session_token_t", handler_decl.group(0))

        dispatch = _code(_function(self.proto, "pble_proto_dispatch"))
        _ordered(self, dispatch, "pble_ble_session_snapshot", "pble_proto_decode")
        token_var_match = re.search(
            r"\bpble_session_token_t\s+([A-Za-z_]\w*)\b", dispatch
        )
        self.assertIsNotNone(token_var_match, "dispatch must retain its entry token")
        token_var = token_var_match.group(1)
        handler_vars = re.findall(
            r"\bpble_(?:deferred_)?handler_t\s+([A-Za-z_]\w*)\b", dispatch
        )
        handler_calls = []
        for handler_var in handler_vars:
            handler_calls.extend(
                re.findall(rf"\b{re.escape(handler_var)}\s*\([^;]+\)", dispatch)
            )
        self.assertGreaterEqual(len(handler_calls), 3)
        for call in handler_calls:
            with self.subTest(call=call[:40]):
                self.assertRegex(call, rf"\b{re.escape(token_var)}\b")
        self.assertEqual(
            _code(self.all_native_c).count("pble_ble_session_snapshot("),
            2,
            "only the snapshot definition and dispatch entry may snapshot",
        )

        packet = _code(_function(self.ble, "pble_notify_packet"))
        self.assertIn("pble_session_token_t", packet)
        self.assertIn("pble_term_admits", packet)
        self.assertNotIn("pble_ble_session_snapshot", packet)
        self.assertRegex(packet, r"if\s*\(\s*!\s*pble_tx_mutex_owned\s*\(\s*\)")
        self.assertNotIn("xSemaphoreGiveRecursive", packet)
        _assert_inside_session_critical(self, packet, "pble_term_admits")
        _ordered(
            self,
            packet,
            "pble_tx_mutex_owned",
            "pble_term_admits",
            "ble_hs_mbuf_from_flat",
            "ble_gatts_notify_custom",
        )
        owner_check = _code(_function(self.ble, "pble_tx_mutex_owned"))
        self.assertIn("xSemaphoreGetMutexHolder", owner_check)
        self.assertIn("xTaskGetCurrentTaskHandle", owner_check)
        self.assertEqual(_code(self.all_native).count("ble_gatts_notify_custom("), 1)

        tx_region = self.ble[
            self.ble.index("static int pble_notify_message") :
            self.ble.index("uint16_t pble_ble_mtu")
        ]
        self.assertNotIn("pble_ble_session_snapshot(", _code(tx_region))

    def test_all_public_tx_shapes_carry_the_originating_token(self) -> None:
        for name in (
            "pble_ble_notify",
            "pble_ble_notify_control_try_for_conn",
            "pble_ble_notify_paced",
            "pble_ble_notify_control_paced",
        ):
            with self.subTest(name=name):
                declaration = re.search(
                    rf"\b{re.escape(name)}\s*\([^;]+\)\s*;", self.ble_h
                )
                self.assertIsNotNone(declaration, f"missing declaration {name}")
                self.assertIn("pble_session_token_t", declaration.group(0))
        for name in (
            "pble_proto_refuse",
            "pble_proto_emit",
            "pble_proto_emit_id",
            "pble_proto_emit_rsp_status_try",
            "pble_proto_emit_paced",
            "pble_proto_emit_control_paced",
        ):
            with self.subTest(name=name):
                declaration = re.search(
                    rf"\b{re.escape(name)}\s*\([^;]+\)\s*;", self.proto_h
                )
                self.assertIsNotNone(declaration, f"missing declaration {name}")
                self.assertIn("pble_session_token_t", declaration.group(0))

        for name in (
            "pble_proto_refuse",
            "pble_proto_emit",
            "pble_proto_emit_id",
            "pble_proto_emit_rsp_status_try",
            "pble_proto_emit_paced",
            "pble_proto_emit_control_paced",
        ):
            with self.subTest(body=name):
                body = _code(_function(self.proto, name))
                self.assertNotIn("pble_ble_session_snapshot", body)

    def test_disconnect_claims_exact_cleanup_before_timer_or_invalidation(self) -> None:
        gap = _code(_function(self.ble, "pble_gap_event"))
        disconnect = _case_branch(gap, "BLE_GAP_EVENT_DISCONNECT")
        _assert_inside_session_critical(self, disconnect, "pble_term_disconnect")
        _assert_inside_session_critical(
            self, disconnect, "pble_term_watchdog_stopped"
        )
        _assert_inside_session_critical(
            self, disconnect, "pble_term_cleanup_complete"
        )
        _assert_tx_serialized_session_call(
            self, disconnect, "pble_term_disconnect"
        )
        _assert_tx_serialized_session_call(
            self, disconnect, "pble_term_cleanup_complete"
        )
        _ordered(
            self,
            disconnect,
            "pble_term_disconnect",
            "PBLE_TERM_EFFECT_STOP_WATCHDOG",
            "esp_timer_stop",
            "pble_term_watchdog_stopped",
            "pble_term_cleanup_complete",
            "pble_advertise",
        )
        _assert_between(
            self,
            disconnect,
            "pble_term_watchdog_stopped",
            "pble_term_cleanup_complete",
            "pble_rsp_cancel_session",
            "pble_rsp_owner_release_if_idle",
            "pble_reset_reassembly",
            "pble_lock_on_disconnect",
            "pble_fs_on_disconnect",
        )
        self.assertIn("ESP_OK", disconnect)
        self.assertIn("PBLE_TERM_EFFECT_RESTART", disconnect)
        self.assertIn("esp_restart", disconnect)
        self.assertEqual(disconnect.count("esp_timer_stop("), 1)

    def test_reset_claims_cleanup_before_timer_and_bound_work(self) -> None:
        reset = _code(_function(self.ble, "pble_on_reset"))
        _assert_inside_session_critical(self, reset, "pble_term_reset")
        _assert_inside_session_critical(self, reset, "pble_term_watchdog_stopped")
        _assert_inside_session_critical(self, reset, "pble_term_cleanup_complete")
        _assert_tx_serialized_session_call(self, reset, "pble_term_reset")
        _assert_tx_serialized_session_call(
            self, reset, "pble_term_cleanup_complete"
        )
        _ordered(
            self,
            reset,
            "pble_term_reset",
            "PBLE_TERM_EFFECT_STOP_WATCHDOG",
            "esp_timer_stop",
            "pble_term_watchdog_stopped",
            "pble_term_cleanup_complete",
        )
        _assert_between(
            self,
            reset,
            "pble_term_watchdog_stopped",
            "pble_term_cleanup_complete",
            "pble_rsp_cancel_session",
            "pble_rsp_owner_release_if_idle",
            "pble_reset_reassembly",
            "pble_lock_on_disconnect",
            "pble_fs_on_disconnect",
        )
        self.assertIn("ESP_OK", reset)
        self.assertIn("PBLE_TERM_EFFECT_RESTART", reset)
        self.assertIn("esp_restart", reset)
        self.assertEqual(reset.count("esp_timer_stop("), 1)

    def test_watchdog_uses_immutable_ticket_and_residual_rearm(self) -> None:
        watchdog = _code(_function(self.ble, "pble_termination_watchdog_cb"))
        self.assertIn("pble_term_watchdog_ticket_t", watchdog)
        ticket_match = re.search(
            r"const\s+pble_term_watchdog_ticket_t\s*\*\s*"
            r"([A-Za-z_]\w*)\s*=\s*"
            r"\(\s*const\s+pble_term_watchdog_ticket_t\s*\*\s*\)\s*arg",
            watchdog,
        )
        self.assertIsNotNone(ticket_match, "callback must retain its armed ticket")
        ticket_var = ticket_match.group(1)
        self.assertRegex(
            watchdog,
            rf"\b{re.escape(ticket_var)}\s*=\s*"
            r"\(\s*const\s+pble_term_watchdog_ticket_t\s*\*\s*\)\s*arg",
        )
        self.assertNotIn("pble_term_watchdog_ticket(", watchdog)
        self.assertNotIn("pble_ble_session_snapshot", watchdog)
        for name in (
            "pble_term_watchdog_fired",
            "pble_term_remaining_us",
            "pble_term_watchdog_rearmed",
        ):
            with self.subTest(ticket_call=name):
                self.assertRegex(
                    watchdog,
                    rf"\b{name}\s*\([^;]*\b{re.escape(ticket_var)}\b",
                )
        _assert_inside_session_critical(self, watchdog, "pble_term_watchdog_fired")
        _assert_inside_session_critical(self, watchdog, "pble_term_watchdog_rearmed")
        _ordered(
            self,
            watchdog,
            "esp_timer_get_time",
            "pble_term_watchdog_fired",
            "PBLE_TERM_EFFECT_REARM_WATCHDOG",
            "pble_term_remaining_us",
            "esp_timer_start_once",
            "pble_term_watchdog_rearmed",
        )
        self.assertIn("PBLE_TERM_EFFECT_RESTART", watchdog)
        self.assertIn("esp_restart", watchdog)
        self.assertEqual(watchdog.count("esp_timer_start_once("), 1)
        self.assertRegex(
            watchdog,
            r"esp_timer_start_once\s*\([^;]*\bremaining_us\b[^;]*\)",
        )

    def test_term_failure_is_an_explicit_no_op_without_fallthrough(self) -> None:
        gap = _code(_function(self.ble, "pble_gap_event"))
        branch = _case_branch(gap, "BLE_GAP_EVENT_TERM_FAILURE")
        body = branch.split(":", 1)[1]
        self.assertRegex(body, r"^\s*break\s*;\s*$")

    def test_no_unsafe_host_or_controller_reset_fallback_exists(self) -> None:
        native = _code(self.all_native)
        for forbidden in (
            "ble_hs_sched_reset",
            "nimble_port_stop(",
            "nimble_port_deinit(",
            "esp_nimble_deinit(",
            "esp_nimble_hci_deinit(",
            "esp_nimble_hci_and_controller_deinit",
            "esp_bt_controller_disable",
            "esp_bt_controller_deinit",
            "esp_restart_noos",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, native)
        self.assertEqual(native.count("ble_gap_terminate("), 1)

        host_task = _code(_function(self.ble, "pble_host_task"))
        self.assertEqual(host_task.count("nimble_port_freertos_deinit("), 1)
        _ordered(
            self,
            host_task,
            "nimble_port_run(",
            "nimble_port_freertos_deinit(",
        )
        outside_host_task = _code(self.all_native_c).replace(host_task, "", 1)
        self.assertNotIn("nimble_port_freertos_deinit(", outside_host_task)


if __name__ == "__main__":
    unittest.main()
