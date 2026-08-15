#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""STOP/SOFT_REBOOT accepted between RUN reservation and worker pickup."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNNER = (
    ROOT / "firmware" / "user_c_modules" / "pyble" / "pble_runner.c"
).read_text(encoding="utf-8")


def matching_brace(source: str, opening: int) -> int:
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
                return index
        index += 1
    raise AssertionError("unterminated block")


def c_function(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^[^\n;{{}}]*\b{re.escape(name)}\s*\([^;{{}}]*\)\s*\{{",
        source,
    )
    if match is None:
        raise AssertionError("missing function {}".format(name))
    opening = source.find("{", match.start())
    return source[match.start() : matching_brace(source, opening) + 1]


def braced_statement(source: str, start: int) -> str:
    opening = source.find("{", start)
    if opening < 0:
        raise AssertionError("missing statement body")
    return source[start : matching_brace(source, opening) + 1]


def code_only(source: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)


def critical_sections(source: str, mux: str) -> list[str]:
    enter = "taskENTER_CRITICAL(&{});".format(mux)
    leave = "taskEXIT_CRITICAL(&{});".format(mux)
    sections: list[str] = []
    offset = 0
    while True:
        start = source.find(enter, offset)
        if start < 0:
            return sections
        end = source.find(leave, start + len(enter))
        if end < 0:
            raise AssertionError("unterminated {} critical section".format(mux))
        sections.append(source[start : end + len(leave)])
        offset = end + len(leave)


class HandoffOracle:
    """Deterministic unresolved-control/pickup interleaving model."""

    def __init__(self) -> None:
        self.next_run = 0
        self.reserved_run: int | None = None
        self.cancelled_run: int | None = None
        self.stale_intent = False
        self.control_unresolved = False
        self.pickup_waiting = False
        self.events: list[int] = []
        self.effects: list[int] = []
        self.responses: list[str] = []

    def stop_while_idle(self) -> None:
        self.stale_intent = True

    def reserve(self, origin: str) -> int:
        self.next_run += 1
        self.reserved_run = self.next_run
        # The successful reservation consumes only intent that predates it.
        self.stale_intent = False
        self.cancelled_run = None
        self.responses.append("RUN_OK" if origin == "command" else "AUTORUN")
        return self.reserved_run

    def begin_control(self) -> None:
        if self.control_unresolved:
            raise AssertionError("only one host control attempt may be unresolved")
        self.control_unresolved = True

    def resolve_control(self, control: str, accepted: bool) -> None:
        if not self.control_unresolved:
            raise AssertionError("control resolution without an attempt")
        if accepted:
            self.responses.append(control + "_OK")
            self.cancelled_run = self.reserved_run
        self.control_unresolved = False
        if self.pickup_waiting:
            self.pickup_waiting = False
            self.worker_pickup()

    def worker_pickup(self) -> bool:
        if self.reserved_run is None:
            return False
        if self.control_unresolved:
            self.pickup_waiting = True
            return False
        if self.cancelled_run != self.reserved_run:
            self.events.append(self.reserved_run)
            self.effects.append(self.reserved_run)
        self.reserved_run = None
        return True


class FrozenPrestartCancellationOracleTests(unittest.TestCase):
    def test_successful_reservation_clears_only_older_idle_stop_intent(self):
        for origin in ("command", "autorun"):
            with self.subTest(origin=origin):
                model = HandoffOracle()
                model.stop_while_idle()
                run = model.reserve(origin)
                model.worker_pickup()
                self.assertEqual(model.effects, [run])

    def test_accepted_stop_or_soft_after_reservation_prevents_user_effects(self):
        for origin in ("command", "autorun"):
            for control in ("STOP", "SOFT_REBOOT"):
                with self.subTest(origin=origin, control=control):
                    model = HandoffOracle()
                    model.reserve(origin)
                    model.begin_control()
                    self.assertFalse(model.worker_pickup())
                    self.assertEqual((model.events, model.effects), ([], []))
                    model.resolve_control(control, accepted=True)
                    self.assertEqual(
                        (model.events, model.effects),
                        ([], []),
                        "accepted control must survive delayed worker pickup",
                    )
                    self.assertEqual(model.responses[-1], control + "_OK")

    def test_failed_control_attempt_releases_pickup_without_stop_effect(self):
        for origin in ("command", "autorun"):
            for control in ("STOP", "SOFT_REBOOT"):
                with self.subTest(origin=origin, control=control):
                    model = HandoffOracle()
                    run = model.reserve(origin)
                    model.begin_control()
                    self.assertFalse(model.worker_pickup())
                    model.resolve_control(control, accepted=False)
                    self.assertEqual(model.responses, [
                        "RUN_OK" if origin == "command" else "AUTORUN"
                    ])
                    self.assertEqual((model.events, model.effects), ([run], [run]))

    def test_pickup_first_linearizes_as_an_active_run_interrupt(self):
        model = HandoffOracle()
        run = model.reserve("command")
        self.assertTrue(model.worker_pickup())
        self.assertEqual((model.events, model.effects), ([run], [run]))
        model.begin_control()
        model.resolve_control("STOP", accepted=True)
        self.assertEqual(model.responses[-1], "STOP_OK")


class NativePrestartCancellationContractTests(unittest.TestCase):
    def control_gate_name(self) -> str:
        declaration = re.search(
            r"(?m)^\s*static\s+(?:volatile\s+)?bool\s+"
            r"(?P<name>g_[A-Za-z0-9_]*control[A-Za-z0-9_]*unresolved[A-Za-z0-9_]*)\s*;",
            RUNNER,
        )
        self.assertIsNotNone(
            declaration,
            "runner needs an explicit unresolved-control pickup gate",
        )
        return declaration.group("name")

    def assert_reservation_clears_stale_intent_atomically(self, function: str) -> None:
        body = code_only(c_function(RUNNER, function))
        reservation_sections = [
            section
            for section in critical_sections(body, "g_mux")
            if "pble_rsm_on_run" in section
        ]
        self.assertEqual(
            len(reservation_sections),
            1,
            "{} needs one RUN reservation cut".format(function),
        )
        section = reservation_sections[0]
        success = re.search(
            r"if\s*\(\s*status\s*==\s*PBLE_OK\s*\)\s*\{",
            section,
        )
        self.assertIsNotNone(
            success,
            "only a successful reservation may consume stale STOP intent",
        )
        success_body = braced_statement(section, success.start())
        self.assertIn("g_stop_requested = false", success_body)
        self.assertIn(
            "g_worker_state",
            success_body,
            "clear the retained worker's stale pending exception, not the caller's",
        )
        self.assertRegex(
            success_body,
            r"(?:->mp_pending_exception|MP_STATE_THREAD\s*\(\s*"
            r"mp_pending_exception\s*\))\s*=\s*MP_OBJ_NULL",
        )

        publication = body.find("g_run_mode")
        if publication < 0:
            publication = body.find("memcpy(g_run_buf")
        self.assertGreater(publication, body.find(success_body))

    def test_command_and_autorun_reservations_clear_only_preexisting_intent(self):
        self.assert_reservation_clears_stale_intent_atomically("pble_runner_run")
        self.assert_reservation_clears_stale_intent_atomically("pble_runner_run_file")

    def test_worker_pickup_never_erases_post_reservation_control(self):
        worker = code_only(c_function(RUNNER, "pble_runner_worker"))
        pickup = worker.find("xSemaphoreTake(g_run_sem")
        execute = worker.find("runner_exec(", pickup)
        self.assertGreaterEqual(pickup, 0)
        self.assertGreater(execute, pickup)
        pre_execute = worker[pickup:execute]

        self.assertNotIn(
            "g_stop_requested = false",
            pre_execute,
            "pickup must not erase an accepted STOP/SOFT after reservation",
        )
        self.assertNotRegex(
            pre_execute,
            r"mp_pending_exception\s*\)\s*=\s*MP_OBJ_NULL",
            "pickup must not erase the accepted control exception",
        )

        guard = re.search(
            r"if\s*\(\s*!\s*pble_runner_stop_requested\s*\(\s*\)\s*\)\s*\{",
            worker[pickup:],
        )
        self.assertIsNotNone(
            guard,
            "worker must suppress execution when control won before pickup",
        )
        guarded = braced_statement(worker[pickup:], guard.start())
        self.assertIn("runner_exec(", guarded)

    def test_control_attempt_resolution_bridges_tx_without_lock_inversion(self):
        gate = self.control_gate_name()
        begin = code_only(c_function(RUNNER, "runner_control_attempt_begin"))
        resolve = code_only(c_function(RUNNER, "runner_control_attempt_resolve"))
        accepted_param = re.search(
            r"runner_control_attempt_resolve\s*\(\s*bool\s+(?P<name>[A-Za-z_]\w*)",
            resolve,
        )
        self.assertIsNotNone(accepted_param)
        accepted_name = accepted_param.group("name")

        begin_sections = critical_sections(begin, "g_mux")
        self.assertTrue(
            any(re.search(rf"\b{re.escape(gate)}\s*=\s*true\s*;", s)
                for s in begin_sections),
            "begin must publish the unresolved gate under g_mux",
        )
        resolve_sections = critical_sections(resolve, "g_mux")
        accepted_if = re.search(
            rf"if\s*\(\s*{re.escape(accepted_name)}\s*\)",
            resolve,
        )
        self.assertIsNotNone(
            accepted_if,
            "only an accepted response may publish stop/KBI",
        )
        accepted_body = braced_statement(resolve, accepted_if.start())
        self.assertIn("g_stop_requested = true", accepted_body)
        self.assertIn("inject_worker_kbd_interrupt", accepted_body)
        failure_path = resolve.replace(accepted_body, "")
        self.assertNotIn("g_stop_requested = true", failure_path)
        self.assertNotIn("inject_worker_kbd_interrupt", failure_path)
        accepted_cut = next(
            (
                section
                for section in resolve_sections
                if "g_stop_requested = true" in section
                and "inject_worker_kbd_interrupt" in section
                and re.search(rf"\b{re.escape(gate)}\s*=\s*false\s*;", section)
            ),
            None,
        )
        self.assertIsNotNone(
            accepted_cut,
            "accepted stop intent, pending exception, and gate resolution must "
            "share one post-TX runner cut",
        )
        self.assertLess(
            accepted_cut.find("inject_worker_kbd_interrupt"),
            accepted_cut.find("{} = false".format(gate)),
            "accepted intent must be visible before pickup is released",
        )
        signal = re.search(
            r"\bxSemaphoreGive\s*\(\s*(?P<name>[A-Za-z_]\w*)\s*\)",
            resolve,
        )
        self.assertIsNotNone(
            signal,
            "both control outcomes must wake the precreated pickup waiter",
        )
        self.assertGreater(
            signal.start(),
            resolve.rfind("taskEXIT_CRITICAL(&g_mux)"),
            "wake only after the resolved predicate/intent cut",
        )
        register = code_only(c_function(RUNNER, "pble_runner_register"))
        self.assertRegex(
            register,
            rf"\b{re.escape(signal.group('name'))}\s*=\s*"
            rf"xSemaphoreCreateBinary(?:Static)?\s*\(",
            "control resolution signal must be created before handler use",
        )
        self.assertNotIn("xSemaphoreCreate", begin)
        self.assertNotIn("xSemaphoreCreate", resolve)

        for function in ("pble_runner_stop", "pble_runner_soft_reboot"):
            body = code_only(c_function(RUNNER, function))
            tx = body.find("pble_proto_emit_rsp_status_try")
            begin_call = body.find("runner_control_attempt_begin")
            resolve_call = body.find("runner_control_attempt_resolve", tx)
            with self.subTest(function=function):
                self.assertGreaterEqual(tx, 0)
                self.assertGreaterEqual(begin_call, 0)
                self.assertLess(begin_call, tx)
                self.assertGreater(resolve_call, tx)
                self.assertFalse(
                    any("pble_proto_emit_rsp_status_try" in section
                        for section in critical_sections(body, "g_mux")),
                    "TX domain must remain outside the runner critical section",
                )

        soft = code_only(c_function(RUNNER, "pble_runner_soft_reboot"))
        fs_close = soft.find("pble_fs_quiesce_try")
        vm_close = soft.find("pble_vm_reboot_close")
        begin = soft.find("runner_control_attempt_begin")
        tx = soft.find("pble_proto_emit_rsp_status_try")
        self.assertEqual([fs_close, vm_close, begin, tx], sorted((fs_close, vm_close, begin, tx)))
        failure = re.search(
            r"if\s*\(\s*tx_rc\s*!=\s*PBLE_TX_OK\s*\)",
            soft[begin:],
        )
        self.assertIsNotNone(failure)
        failure_body = braced_statement(soft[begin:], failure.start())
        for operation in (
            "pble_vm_reboot_abort",
            "pble_fs_quiesce_abort",
            "runner_control_attempt_resolve(false)",
            "return PBLE_NO_RSP",
        ):
            self.assertIn(operation, failure_body)
        self.assertLess(
            failure_body.find("pble_vm_reboot_abort"),
            failure_body.find("runner_control_attempt_resolve(false)"),
        )
        self.assertLess(
            failure_body.find("pble_fs_quiesce_abort"),
            failure_body.find("runner_control_attempt_resolve(false)"),
        )
        success_resolve = soft.find("runner_control_attempt_resolve(true)", tx)
        self.assertGreater(success_resolve, tx)
        self.assertLess(
            success_resolve,
            soft.find("esp_timer_start_once"),
            "accepted SOFT intent must resolve before timer arm",
        )

    def test_worker_waits_before_every_run_event_or_user_effect(self):
        gate = self.control_gate_name()
        wait = code_only(c_function(RUNNER, "pble_runner_stop_requested"))
        self.assertIn(gate, wait)
        self.assertRegex(wait, r"\b(?:while|for)\s*\(")
        self.assertIn("MP_THREAD_GIL_EXIT", wait)
        self.assertIn("MP_THREAD_GIL_ENTER", wait)
        wait_call = re.search(
            r"\bxSemaphoreTake\s*\(\s*(?P<name>[A-Za-z_]\w*)\s*,",
            wait,
        )
        self.assertIsNotNone(
            wait_call,
            "unresolved pickup must yield/block outside g_mux",
        )
        for section in critical_sections(wait, "g_mux"):
            self.assertNotRegex(
                section,
                r"\bxSemaphoreTake\s*\(",
                "worker must never wait while holding the runner domain",
            )
        synchronized_snapshot = next(
            (
                section
                for section in critical_sections(wait, "g_mux")
                if gate in section and "g_stop_requested" in section
            ),
            None,
        )
        self.assertIsNotNone(
            synchronized_snapshot,
            "gate predicate and stop snapshot must share one pickup cut",
        )
        resolve = code_only(c_function(RUNNER, "runner_control_attempt_resolve"))
        signal = re.search(
            r"\bxSemaphoreGive\s*\(\s*(?P<name>[A-Za-z_]\w*)\s*\)",
            resolve,
        )
        self.assertIsNotNone(signal)
        self.assertEqual(
            wait_call.group("name"),
            signal.group("name"),
            "worker must wait on the exact resolution signal the handler gives",
        )

        worker = code_only(c_function(RUNNER, "pble_runner_worker"))
        pickup = worker.find("xSemaphoreTake(g_run_sem")
        gate_assignment = re.search(
            r"bool\s+(?P<name>[A-Za-z_]\w*)\s*=\s*"
            r"pble_runner_stop_requested\s*\(\s*\)\s*;",
            worker[pickup:],
        )
        self.assertIsNotNone(gate_assignment)
        gate_call = pickup + gate_assignment.start()
        running_event = worker.find("runner_emit_state(pble_rsm_on_started", pickup)
        execute = worker.find("runner_exec(", pickup)
        self.assertGreater(gate_call, pickup)
        self.assertLess(gate_call, running_event)
        self.assertLess(gate_call, execute)
        guard = re.search(
            rf"if\s*\(\s*!\s*{re.escape(gate_assignment.group('name'))}\s*\)",
            worker[pickup:],
        )
        self.assertIsNotNone(guard)
        guarded = braced_statement(worker[pickup:], guard.start())
        self.assertIn("runner_emit_state(pble_rsm_on_started", guarded)
        self.assertIn("runner_exec(", guarded)

    def test_run_reservations_never_clear_an_unresolved_control(self):
        gate = self.control_gate_name()
        for function in ("pble_runner_run", "pble_runner_run_file"):
            body = code_only(c_function(RUNNER, function))
            reservation = next(
                section
                for section in critical_sections(body, "g_mux")
                if "pble_rsm_on_run" in section
            )
            with self.subTest(function=function):
                self.assertNotRegex(
                    reservation,
                    rf"\b{re.escape(gate)}\s*=\s*false\s*;",
                    "reservation may consume resolved stale STOP only",
                )


if __name__ == "__main__":
    unittest.main()
