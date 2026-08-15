#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""RED: bounded fail-closed teardown when GAP termination cannot complete."""

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


def _contains(
    test: unittest.TestCase, source: str, needle: str, criterion: str
) -> None:
    test.assertTrue(needle in source, f"[{criterion}] missing {needle!r}")


class FailedSessionTerminationReducerTest(unittest.TestCase):
    def test_host_compilable_reducer_covers_the_full_transition_matrix(self) -> None:
        self.assertTrue(
            POLICY_C.is_file() and POLICY_H.is_file(),
            "[FR-PROTO-6] missing host-compilable pble_termination.c/.h reducer",
        )
        compiler = shutil.which(os.environ.get("CC", "cc"))
        self.assertIsNotNone(compiler, "host C compiler is required for reducer test")
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

    def test_watchdog_uses_public_task_timer_and_whole_board_restart(self) -> None:
        _contains(self, self.ble, '#include "esp_timer.h"', "FR-PROTO-6")
        _contains(self, self.ble, '#include "esp_system.h"', "FR-PROTO-6")
        _contains(self, self.ble, '#include "pble_termination.h"', "FR-PROTO-6")
        _contains(self, self.ble, "esp_timer_create", "FR-PROTO-6")
        _contains(self, self.ble, "esp_timer_start_once", "FR-PROTO-6")
        _contains(self, self.ble, "esp_restart", "FR-PROTO-6")
        self.assertNotIn("esp_restart_noos", self.ble)
        init = _code(_function(self.ble, "pble_ble_init"))
        self.assertIn(".dispatch_method = ESP_TIMER_TASK", init)
        _ordered(self, init, "esp_timer_create", "nimble_port_freertos_init")

    def test_close_arms_watchdog_before_exactly_one_gap_call(self) -> None:
        close = _code(_function(self.ble, "pble_ble_terminate_session"))
        _ordered(
            self,
            close,
            "pble_term_begin",
            "esp_timer_start_once",
            "ble_gap_terminate",
        )
        self.assertEqual(close.count("ble_gap_terminate("), 1)
        self.assertNotIn("ble_npl_callout_reset", close)

    def test_only_success_or_ealready_waits(self) -> None:
        close = _code(_function(self.ble, "pble_ble_terminate_session"))
        self.assertRegex(
            close,
            r"rc\s*==\s*0\s*\|\|\s*rc\s*==\s*BLE_HS_EALREADY",
        )
        self.assertIn("pble_term_gap_result", close)
        self.assertIn("esp_restart", close)

    def test_snapshot_and_live_admit_only_open_state(self) -> None:
        snapshot = _code(_function(self.ble, "pble_ble_session_snapshot"))
        live = _code(_function(self.ble, "pble_ble_session_live"))
        self.assertIn("pble_term_admits", snapshot)
        self.assertIn("pble_term_admits", live)

    def test_dispatch_and_low_level_tx_gate_closing_before_work(self) -> None:
        dispatch = _code(_function(self.proto, "pble_proto_dispatch"))
        packet = _code(_function(self.ble, "pble_notify_packet"))
        _ordered(self, dispatch, "pble_ble_session_snapshot", "pble_proto_decode")
        self.assertIn("pble_ble_session_snapshot", packet)

    def test_disconnect_and_reset_cancel_before_invalidation_or_advertise(self) -> None:
        gap = _code(_function(self.ble, "pble_gap_event"))
        reset = _code(_function(self.ble, "pble_on_reset"))
        disconnect = gap[gap.index("case BLE_GAP_EVENT_DISCONNECT") :]
        self.assertIn("pble_term_disconnect", disconnect)
        _ordered(
            self,
            disconnect,
            "esp_timer_stop",
            "pble_term_disconnect",
            "pble_advertise",
        )
        self.assertIn("pble_term_reset", reset)
        _ordered(self, reset, "esp_timer_stop", "pble_term_reset")

    def test_watchdog_revalidates_token_and_absolute_deadline(self) -> None:
        watchdog = _code(_function(self.ble, "pble_termination_watchdog_cb"))
        self.assertIn("esp_timer_get_time", watchdog)
        self.assertIn("pble_term_watchdog_fired", watchdog)
        self.assertIn("PBLE_TERM_EFFECT_REARM_WATCHDOG", watchdog)
        self.assertIn("esp_timer_is_active", watchdog)
        self.assertIn("esp_timer_start_once", watchdog)
        self.assertIn("esp_restart", watchdog)

    def test_term_failure_cannot_clear_closing_or_cancel_watchdog(self) -> None:
        gap = _code(_function(self.ble, "pble_gap_event"))
        start = gap.find("case BLE_GAP_EVENT_TERM_FAILURE")
        self.assertGreaterEqual(start, 0, "missing explicit TERM_FAILURE case")
        following = gap.find("case ", start + len("case "))
        branch = gap[start : following if following >= 0 else len(gap)]
        self.assertNotIn("esp_timer_stop", branch)
        self.assertNotIn("pble_term_disconnect", branch)
        self.assertNotIn("pble_term_reset", branch)
        self.assertNotIn("pble_advertise", branch)

    def test_never_retries_or_duplicates_nimble_host_reset(self) -> None:
        all_native = "\n".join((self.ble, self.ble_h, self.proto))
        self.assertNotIn("ble_hs_sched_reset", _code(all_native))
        close = _code(_function(self.ble, "pble_ble_terminate_session"))
        self.assertNotIn("ble_npl_callout_reset", close)
        self.assertEqual(close.count("ble_gap_terminate("), 1)


if __name__ == "__main__":
    unittest.main()
