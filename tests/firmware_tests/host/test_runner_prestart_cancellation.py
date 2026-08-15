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
    """Deterministic reservation/control/pickup interleaving model."""

    def __init__(self) -> None:
        self.next_run = 0
        self.reserved_run: int | None = None
        self.cancelled_run: int | None = None
        self.stale_intent = False
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

    def accept_control(self, control: str) -> None:
        self.responses.append(control + "_OK")
        self.cancelled_run = self.reserved_run

    def worker_pickup(self) -> None:
        if self.reserved_run is None:
            return
        if self.cancelled_run != self.reserved_run:
            self.effects.append(self.reserved_run)
        self.reserved_run = None


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
                    model.accept_control(control)
                    model.worker_pickup()
                    self.assertEqual(
                        model.effects,
                        [],
                        "accepted control must survive delayed worker pickup",
                    )
                    self.assertEqual(model.responses[-1], control + "_OK")


class NativePrestartCancellationContractTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
