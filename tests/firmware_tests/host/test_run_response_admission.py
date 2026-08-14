#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""Transactional RUN response admission (protocol §6 / FR-RUN-1)."""

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
RUNNER = (NATIVE / "pble_runner.c").read_text(encoding="utf-8")


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


class AdmissionOracle:
    """Small behavioral oracle for the frozen admission cut."""

    RUNNING = 1
    TX_OK = 0
    TX_NO_CONN = -1
    TX_AGAIN = -2
    NO_RSP = 0xFE

    def __init__(self, state: int) -> None:
        self.state = state
        self.attempts = 0
        self.wakes = 0
        self.executions = 0
        self.events = 0

    def admit(self, tx_result: int, *, same_connection: bool = True) -> int:
        prior = self.state
        self.state = self.RUNNING  # provisional and non-observable
        self.attempts += 1
        if not same_connection or tx_result != self.TX_OK:
            self.state = prior
            return self.NO_RSP
        self.wakes += 1
        return self.NO_RSP

    def worker_pickup(self) -> None:
        if self.wakes:
            self.events += 1
            self.executions += 1


class FrozenAdmissionOracleTests(unittest.TestCase):
    def test_exact_ok_response_is_one_fragment_at_minimum_att_mtu(self):
        mtu = 23
        fragment_message_bytes = mtu - 3 - 1
        response_frame_bytes = 6 + 1 + 4
        self.assertEqual(fragment_message_bytes, 19)
        self.assertEqual(response_frame_bytes, 11)
        self.assertLessEqual(response_frame_bytes, fragment_message_bytes)

    def test_ok_is_the_only_cut_that_wakes_and_then_executes(self):
        model = AdmissionOracle(state=2)
        self.assertEqual(model.admit(model.TX_OK), model.NO_RSP)
        self.assertEqual((model.attempts, model.wakes), (1, 1))
        self.assertEqual((model.executions, model.events), (0, 0))
        model.worker_pickup()
        self.assertEqual((model.executions, model.events), (1, 1))

    def test_every_local_failure_is_one_attempt_and_exact_state_rollback(self):
        cases = (
            (AdmissionOracle.TX_AGAIN, True),
            (AdmissionOracle.TX_NO_CONN, True),
            (AdmissionOracle.TX_OK, False),
        )
        for prior in (0, 2, 3):
            for tx_result, same_connection in cases:
                with self.subTest(prior=prior, result=tx_result, same=same_connection):
                    model = AdmissionOracle(state=prior)
                    self.assertEqual(
                        model.admit(tx_result, same_connection=same_connection),
                        model.NO_RSP,
                    )
                    model.worker_pickup()
                    self.assertEqual(model.state, prior)
                    self.assertEqual(model.attempts, 1)
                    self.assertEqual((model.wakes, model.executions, model.events), (0, 0, 0))


class NativeControlTryContractTests(unittest.TestCase):
    def test_ble_try_is_connection_bound_single_packet_and_zero_wait(self):
        name = "pble_ble_notify_control_try_for_conn"
        self.assertIn(name, BLE_H)
        body = code_only(c_function(BLE, name))

        ordered(
            self,
            body,
            "xSemaphoreTakeRecursive(pble_tx_mutex, 0)",
            "pble_conn_handle != expected_conn",
            "pble_notify_packet",
            "xSemaphoreGiveRecursive(pble_tx_mutex)",
        )
        self.assertIn("PBLE_FRAG_FIRST | PBLE_FRAG_LAST", body)
        self.assertIn("PBLE_TX_OVERSIZE", body)
        self.assertEqual(body.count("pble_notify_packet("), 1)
        self.assertNotIn("pble_notify_message", body)
        for forbidden in (
            "portMAX_DELAY",
            "pble_tx_drain_sem",
            "vTaskDelay(",
            "while (",
            "for (",
        ):
            self.assertNotIn(forbidden, body)

    def test_proto_try_builds_only_the_matching_status_response_on_stack(self):
        name = "pble_proto_emit_rsp_status_try"
        self.assertIn(name, PROTO_H)
        body = code_only(c_function(PROTO, name))
        compact = " ".join(body.split())

        self.assertRegex(
            compact,
            r"uint8_t buf\s*\[\s*PBLE_HDR_LEN\s*\+\s*1\s*\+\s*PBLE_CRC_LEN\s*\]",
        )
        self.assertNotIn("static uint8_t", body)
        self.assertRegex(
            compact,
            r"pble_proto_encode\s*\(\s*PBLE_TYPE_RSP\s*,\s*opcode\s*,\s*id_\s*,"
            r"\s*&status\s*,\s*1\s*,",
        )
        ordered(
            self,
            body,
            "pble_proto_encode",
            "pble_ble_notify_control_try_for_conn",
        )
        self.assertIn("expected_conn", body)


class NativeRunAdmissionContractTests(unittest.TestCase):
    def test_run_submits_exact_ok_before_the_only_worker_wake(self):
        body = code_only(c_function(RUNNER, "pble_runner_run"))
        self.assertNotIn("(void)conn", body)
        self.assertEqual(body.count("pble_proto_emit_rsp_status_try("), 1)
        ordered(
            self,
            body,
            "pble_rsm_on_run",
            "g_run_mode = mode",
            "g_run_len = dlen",
            "pble_proto_emit_rsp_status_try",
            "xSemaphoreGive(g_run_sem)",
            "return PBLE_NO_RSP",
        )
        self.assertRegex(
            body,
            r"pble_proto_emit_rsp_status_try\s*\(\s*req->opcode\s*,\s*req->id\s*,"
            r"\s*PBLE_OK\s*,\s*conn\s*\)",
        )
        self.assertNotRegex(body, r"return\s+PBLE_OK\s*;")
        self.assertNotIn("pble_proto_emit_id(", body)

    def test_failed_submit_restores_exact_prior_state_and_never_wakes(self):
        body = code_only(c_function(RUNNER, "pble_runner_run"))
        prior = re.search(r"(?P<name>[A-Za-z_]\w*)\s*=\s*g_rsm\.state\s*;", body)
        self.assertIsNotNone(prior, "RUN must remember the exact prior state")
        prior_name = prior.group("name")
        tx = re.search(
            r"(?P<name>[A-Za-z_]\w*)\s*=\s*pble_proto_emit_rsp_status_try\s*\(",
            body,
        )
        self.assertIsNotNone(tx, "RUN must capture the one response-submit result")
        tx_name = tx.group("name")
        failure = re.search(
            rf"if\s*\(\s*{re.escape(tx_name)}\s*!=\s*PBLE_TX_OK\s*\)\s*"
            rf"\{{(?P<body>.*?)\n\s*\}}",
            body,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(failure, "every non-OK submit result must fail closed")
        failure_body = failure.group("body")
        self.assertIn("taskENTER_CRITICAL(&g_mux)", failure_body)
        self.assertIn("g_rsm.state = {};".format(prior_name), failure_body)
        self.assertIn("taskEXIT_CRITICAL(&g_mux)", failure_body)
        self.assertIn("return PBLE_NO_RSP;", failure_body)
        self.assertNotIn("xSemaphoreGive", failure_body)

    def test_handoff_is_initialized_and_the_binary_give_is_an_invariant(self):
        body = code_only(c_function(RUNNER, "pble_runner_run"))
        sem_check = body.find("g_run_sem == NULL")
        reserve = body.find("pble_rsm_on_run")
        self.assertGreaterEqual(sem_check, 0, "RUN must reject an absent hand-off semaphore")
        self.assertLess(sem_check, reserve)
        self.assertIn("PBLE_EINTERNAL", body[sem_check:reserve])

        give = re.search(
            r"BaseType_t\s+(?P<name>[A-Za-z_]\w*)\s*=\s*"
            r"xSemaphoreGive\s*\(\s*g_run_sem\s*\)\s*;",
            body,
        )
        self.assertIsNotNone(give, "the semaphore-give result must be captured")
        self.assertRegex(
            body[give.end() :],
            rf"configASSERT\s*\(\s*{re.escape(give.group('name'))}\s*==\s*pdTRUE\s*\)",
        )

    def test_persistent_worker_events_follow_the_handoff(self):
        worker = code_only(c_function(RUNNER, "pble_runner_worker"))
        ordered(
            self,
            worker,
            "xSemaphoreTake(g_run_sem, portMAX_DELAY)",
            "runner_emit_state(pble_rsm_on_started(&g_rsm))",
            "runner_exec(mode, local, len)",
        )

    def test_auto_run_remains_response_free_direct_handoff(self):
        auto_run = code_only(c_function(RUNNER, "pble_runner_run_file"))
        self.assertNotIn("pble_proto_emit", auto_run)
        self.assertNotIn("PBLE_TYPE_RSP", auto_run)
        self.assertNotIn("PBLE_NO_RSP", auto_run)
        ordered(
            self,
            auto_run,
            "pble_rsm_on_run",
            "g_run_mode = PBLE_RUN_MODE_FILE",
            "memcpy(g_run_buf, path, plen)",
            "xSemaphoreGive(g_run_sem)",
            "return PBLE_OK",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
