#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""Per-event session binding for RUN_STATE and CONSOLE_DATA."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / "firmware" / "user_c_modules" / "pyble"
BLE = (NATIVE / "pble_ble.c").read_text(encoding="utf-8")
BLE_H = (NATIVE / "pble_ble.h").read_text(encoding="utf-8")
PROTO = (NATIVE / "pble_proto.c").read_text(encoding="utf-8")
RUNNER = (NATIVE / "pble_runner.c").read_text(encoding="utf-8")
CONSOLE = (NATIVE / "pble_console.c").read_text(encoding="utf-8")


def c_function(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^[^\n;{{}}]*\b{re.escape(name)}\s*\([^;{{}}]*\)\s*\{{",
        source,
    )
    if match is None:
        raise AssertionError("missing function {}".format(name))
    opening = source.find("{", match.start())
    return source[match.start() : matching_brace(source, opening) + 1]


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


def braced_statement(source: str, start: int) -> str:
    opening = source.find("{", start)
    if opening < 0:
        raise AssertionError("missing statement body")
    return source[start : matching_brace(source, opening) + 1]


def code_only(source: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)


def ordered(test: unittest.TestCase, source: str, *needles: str) -> None:
    positions = [source.find(needle) for needle in needles]
    for needle, position in zip(needles, positions):
        test.assertGreaterEqual(position, 0, "missing {!r}".format(needle))
    test.assertEqual(positions, sorted(positions), "wrong operation order")


@dataclass(frozen=True)
class SessionToken:
    conn: int
    generation: int
    vm_epoch: int


@dataclass(frozen=True)
class LogicalEvent:
    kind: str
    payload: bytes
    session: SessionToken


class EventBindingOracle:
    """Small deterministic model of event creation and paced retry."""

    def __init__(self, vm_epoch: int = 11) -> None:
        self.vm_epoch = vm_epoch
        self.generation = 0
        self.live: SessionToken | None = None
        self.deliveries: list[LogicalEvent] = []

    def connect(self, conn: int) -> SessionToken:
        self.generation += 1
        self.live = SessionToken(conn, self.generation, self.vm_epoch)
        return self.live

    def disconnect(self) -> None:
        self.live = None

    def create(self, kind: str, payload: bytes) -> LogicalEvent | None:
        if self.live is None:
            return None
        return LogicalEvent(kind, payload, self.live)

    def attempt(self, event: LogicalEvent, *, pressure: bool = False) -> str:
        if event.session != self.live:
            return "dropped"
        if pressure:
            return "retry"
        self.deliveries.append(event)
        return "sent"


class FrozenRunnerEventBindingOracleTests(unittest.TestCase):
    def test_offline_auto_run_omits_old_events_but_new_output_binds_on_connect(self):
        model = EventBindingOracle()

        # Opt-in auto-run starts before any central exists. These are events,
        # not a replay queue for a future connection.
        self.assertIsNone(model.create("RUN_STATE", b"running"))
        self.assertIsNone(model.create("CONSOLE_DATA", b"offline"))

        connected = model.connect(7)
        later = model.create("CONSOLE_DATA", b"after-connect")
        self.assertIsNotNone(later)
        self.assertEqual(later.session, connected)
        self.assertEqual(model.attempt(later), "sent")
        self.assertEqual([event.payload for event in model.deliveries], [b"after-connect"])

    def test_pressured_old_chunk_never_retargets_a_reused_handle(self):
        model = EventBindingOracle()
        first = model.connect(7)
        old = model.create("CONSOLE_DATA", b"old")
        self.assertIsNotNone(old)
        self.assertEqual(model.attempt(old, pressure=True), "retry")

        model.disconnect()
        successor = model.connect(7)  # same numeric handle, new generation
        self.assertNotEqual(first, successor)
        self.assertEqual(old.session, first)
        self.assertEqual(model.attempt(old), "dropped")
        self.assertEqual(model.deliveries, [])

        new = model.create("CONSOLE_DATA", b"new")
        self.assertIsNotNone(new)
        self.assertEqual(new.session, successor)
        self.assertEqual(model.attempt(new), "sent")
        self.assertEqual(model.deliveries, [new])


class NativeCurrentSessionSnapshotContractTests(unittest.TestCase):
    def test_snapshot_current_captures_one_full_live_token_under_session_lock(self):
        name = "pble_ble_session_snapshot_current"
        self.assertRegex(
            BLE_H,
            rf"\bbool\s+{name}\s*\(\s*pble_session_token_t\s*\*\s*\w+\s*\)\s*;",
        )
        body = code_only(c_function(BLE, name))
        self.assertEqual(body.count("taskENTER_CRITICAL(&pble_session_mux)"), 1)
        self.assertEqual(body.count("taskEXIT_CRITICAL(&pble_session_mux)"), 1)
        ordered(
            self,
            body,
            "taskENTER_CRITICAL(&pble_session_mux)",
            "pble_term_admits",
            "session->conn = pble_conn_handle",
            "session->generation = pble_conn_generation",
            "session->vm_epoch = pble_session_vm_epoch",
            "taskEXIT_CRITICAL(&pble_session_mux)",
        )
        self.assertIn("BLE_HS_CONN_HANDLE_NONE", body)
        self.assertIn("pble_session_vm_epoch != 0", body)


class NativeRunnerEventBindingContractTests(unittest.TestCase):
    def test_run_state_snapshots_at_creation_and_run_admission_keeps_origin(self):
        emit = code_only(c_function(RUNNER, "runner_emit_state"))
        local = re.search(r"\bpble_session_token_t\s+(?P<name>[A-Za-z_]\w*)\s*;", emit)
        self.assertIsNotNone(local, "RUN_STATE needs a call-local session token")
        token = local.group("name")
        refusal = re.search(
            rf"if\s*\(\s*!\s*pble_ble_session_snapshot_current\s*"
            rf"\(\s*&{re.escape(token)}\s*\)\s*\)\s*\{{?\s*return\s*;",
            emit,
        )
        self.assertIsNotNone(refusal, "no live session must omit RUN_STATE")
        self.assertEqual(emit.count("pble_ble_session_snapshot_current("), 1)
        ordered(
            self,
            emit,
            "pble_ble_session_snapshot_current",
            "MP_THREAD_GIL_EXIT()",
            "pble_proto_emit_control_paced",
            "MP_THREAD_GIL_ENTER()",
        )
        self.assertRegex(
            emit,
            rf"pble_proto_emit_control_paced\s*\([^;]*&{re.escape(token)}\s*\)",
        )
        self.assertNotIn("g_worker_session", emit)

        run = code_only(c_function(RUNNER, "pble_runner_run"))
        self.assertNotIn("pble_ble_session_snapshot_current", run)
        self.assertRegex(
            run,
            r"pble_proto_emit_rsp_status_try\s*\(\s*req->opcode\s*,\s*"
            r"req->id\s*,\s*PBLE_OK\s*,\s*conn\s*\)",
        )
        ordered(self, run, "pble_proto_emit_rsp_status_try", "xSemaphoreGive(g_run_sem)")

    def test_each_new_console_chunk_snapshots_once_and_old_retries_never_resnapshot(self):
        body = code_only(c_function(CONSOLE, "pble_console_out"))
        loop_start = body.find("while (off < len")
        self.assertGreaterEqual(loop_start, 0)
        loop = braced_statement(body, loop_start)

        local = re.search(r"\bpble_session_token_t\s+(?P<name>[A-Za-z_]\w*)\s*;", body)
        self.assertIsNotNone(local, "each console chunk needs a local session token")
        token = local.group("name")
        call = rf"pble_ble_session_snapshot_current\s*\(\s*&{re.escape(token)}\s*\)"
        self.assertEqual(len(re.findall(call, loop)), 1)

        positive = re.search(rf"if\s*\(\s*{call}\s*\)\s*\{{", loop)
        negative = re.search(rf"if\s*\(\s*!\s*{call}\s*\)\s*\{{", loop)
        guarded = False
        if positive is not None:
            guarded = "pble_proto_emit_paced" in braced_statement(loop, positive.start())
        if negative is not None:
            refusal = braced_statement(loop, negative.start())
            guarded = guarded or "continue;" in refusal or "return;" in refusal
        self.assertTrue(guarded, "no live session must omit the newly staged chunk")

        ordered(
            self,
            loop,
            "memcpy(g_stage + 1",
            "pble_ble_session_snapshot_current",
            "pble_proto_emit_paced",
            "off += n",
        )
        self.assertRegex(
            loop,
            rf"pble_proto_emit_paced\s*\([^;]*&{re.escape(token)}\s*\)",
        )
        self.assertNotIn("g_session", loop)

        # Retry loops consume the caller's immutable token; they never ask for
        # the current session and silently retarget an event after reconnect.
        for source, function in (
            (PROTO, "pble_proto_emit_paced"),
            (PROTO, "pble_proto_emit_control_paced"),
            (BLE, "pble_ble_notify_paced_with_reserve"),
        ):
            with self.subTest(function=function):
                retry_body = code_only(c_function(source, function))
                self.assertNotIn("pble_ble_session_snapshot_current", retry_body)


if __name__ == "__main__":
    unittest.main()
