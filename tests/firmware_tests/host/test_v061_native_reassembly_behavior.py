#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""Compiled behavior contract for the native ESP FR-BLE-10 reducer.

The probe below compiles the production reassembly, exact-session admission,
termination-latch, and violation-counter functions from ``pble_ble.c``.  Only
hardware boundaries (clock, critical section, dispatcher/refusal sink, and the
physical termination driver) are deterministic stubs.  The pure production
termination reducer is linked alongside the probe.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / "firmware" / "user_c_modules" / "pyble"
BLE_PATH = NATIVE / "pble_ble.c"
TERMINATION_PATH = NATIVE / "pble_termination.c"
BLE = BLE_PATH.read_text(encoding="utf-8")


def _matching_brace(source: str, opening: int) -> int:
    depth = 0
    state = "code"
    index = opening
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if state == "line":
            if char == "\n":
                state = "code"
        elif state == "block":
            if char == "*" and following == "/":
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
        elif char == "/" and following == "/":
            state = "line"
            index += 1
        elif char == "/" and following == "*":
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
    raise AssertionError("unterminated C block")


def _c_function(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^[^\n;{{}}]*\b{re.escape(name)}\s*\([^;{{}}]*\)\s*\{{",
        source,
    )
    if match is None:
        raise AssertionError("missing function {}".format(name))
    opening = source.find("{", match.start())
    return source[match.start() : _matching_brace(source, opening) + 1]


def _macro_value(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^\s*#\s*define\s+{re.escape(name)}\s+([^\s/]+)", source
    )
    if match is None:
        raise AssertionError("missing macro {}".format(name))
    return match.group(1)


class NativeReassemblyBehaviorTests(unittest.TestCase):
    """Execute the native reducer at the FR-BLE-10 boundary cuts."""

    @classmethod
    def setUpClass(cls) -> None:
        compiler = shutil.which(os.environ.get("CC", "cc"))
        if compiler is None:
            raise unittest.SkipTest("a host C compiler is required for native RX")

        production_functions = "\n\n".join(
            _c_function(BLE, name)
            for name in (
                "pble_reset_reassembly",
                "pble_discard_reassembly_tail",
                "pble_session_matches_locked",
                "pble_session_token_equal",
                "pble_termination_pending_matches_locked",
                "pble_session_admits_locked",
                "pble_termination_clear_locked",
                "pble_termination_latch_locked",
                "pble_rx_ingest",
                "pble_ble_record_protocol_violation",
            )
        )
        preamble = textwrap.dedent(
            r'''
            #include <stdbool.h>
            #include <stddef.h>
            #include <stdint.h>
            #include <limits.h>
            #include <stdio.h>
            #include <string.h>

            #include "pble_termination.h"

            #define PBLE_MSG_MAX __MESSAGE_LIMIT__
            #define PBLE_RX_REASSEMBLY_DEADLINE_US __DEADLINE_US__
            #define PBLE_SESSION_VIOLATION_LIMIT __VIOLATION_LIMIT__
            #define PBLE_FRAG_FIRST 0x80
            #define PBLE_FRAG_LAST 0x40
            #define PBLE_FRAG_IDX_MASK 0x3f
            #define PBLE_FRAG_IDX_MOD 64
            #define PBLE_PROTO_VERSION 0x01
            #define PBLE_TYPE_CMD 0x01
            #define PBLE_ERANGE 0x09
            #define BLE_HS_CONN_HANDLE_NONE UINT16_MAX

            typedef int portMUX_TYPE;
            #define taskENTER_CRITICAL(mux) do { (void)(mux); } while (0)
            #define taskEXIT_CRITICAL(mux) do { (void)(mux); } while (0)

            static uint8_t pble_rx_buf[PBLE_MSG_MAX];
            static size_t pble_rx_len;
            static bool pble_rx_active;
            static uint8_t pble_rx_next_index;
            static int64_t pble_rx_started_us;
            static bool pble_rx_discard_tail;

            static uint16_t pble_conn_handle = BLE_HS_CONN_HANDLE_NONE;
            static uint64_t pble_conn_generation;
            static uint64_t pble_session_vm_epoch;
            static uint8_t pble_protocol_violation_count;
            static bool pble_termination_pending;
            static bool pble_termination_driver_claimed;
            static pble_session_token_t pble_termination_pending_session;
            static int64_t pble_termination_begin_us;
            static int64_t pble_termination_deadline_us;
            static portMUX_TYPE pble_session_mux;
            static pble_term_state_t pble_term_state;

            static int64_t fake_now_us;
            static int dispatch_calls;
            static size_t dispatched_len;
            static uint8_t dispatched[32];
            static int refuse_calls;
            static int termination_calls;
            static pble_session_token_t terminated_session;

            static int64_t esp_timer_get_time(void) { return fake_now_us; }
            static bool pble_vm_reboot_command_admitted(bool begin) {
                (void)begin;
                return true;
            }
            static void pble_proto_dispatch(const uint8_t *msg, size_t len,
                                            uint16_t conn) {
                (void)conn;
                dispatch_calls++;
                dispatched_len = len < sizeof(dispatched) ? len : sizeof(dispatched);
                memcpy(dispatched, msg, dispatched_len);
            }
            static void pble_proto_refuse(uint8_t op, uint8_t id,
                                          uint8_t status,
                                          const pble_session_token_t *session) {
                (void)op;
                (void)id;
                (void)status;
                (void)session;
                refuse_calls++;
            }

            bool pble_ble_record_protocol_violation(
                const pble_session_token_t *session);
            void pble_ble_terminate_session(
                const pble_session_token_t *session);
            '''
        )
        for marker, value in (
            ("__MESSAGE_LIMIT__", _macro_value(BLE, "PBLE_MSG_MAX")),
            (
                "__DEADLINE_US__",
                _macro_value(BLE, "PBLE_RX_REASSEMBLY_DEADLINE_US"),
            ),
            (
                "__VIOLATION_LIMIT__",
                _macro_value(BLE, "PBLE_SESSION_VIOLATION_LIMIT"),
            ),
        ):
            preamble = preamble.replace(marker, value)

        scenarios = textwrap.dedent(
            r'''
            void pble_ble_terminate_session(
                    const pble_session_token_t *session) {
                termination_calls++;
                terminated_session = *session;
            }

            static bool token_equal(pble_session_token_t left,
                                    pble_session_token_t right) {
                return left.conn == right.conn &&
                       left.generation == right.generation &&
                       left.vm_epoch == right.vm_epoch;
            }

            static bool model_open(uint16_t conn, uint64_t generation,
                                   uint64_t vm_epoch) {
                pble_term_init(&pble_term_state);
                if (!pble_term_open(&pble_term_state, conn, generation)) {
                    return false;
                }
                pble_conn_handle = conn;
                pble_conn_generation = generation;
                pble_session_vm_epoch = vm_epoch;
                pble_protocol_violation_count = 0;
                pble_termination_clear_locked();
                pble_reset_reassembly();
                dispatch_calls = 0;
                dispatched_len = 0;
                refuse_calls = 0;
                termination_calls = 0;
                memset(&terminated_session, 0, sizeof(terminated_session));
                return true;
            }

            static bool model_vm_rotation(uint64_t generation,
                                          uint64_t vm_epoch) {
                uint64_t old_generation = pble_conn_generation;
                if (!pble_term_rotate_open(&pble_term_state, pble_conn_handle,
                                           old_generation, generation)) {
                    return false;
                }
                pble_conn_generation = generation;
                pble_session_vm_epoch = vm_epoch;
                pble_protocol_violation_count = 0;
                pble_termination_clear_locked();
                pble_reset_reassembly();
                return true;
            }

            static bool model_disconnect_reconnect(uint16_t conn,
                                                   uint64_t generation,
                                                   uint64_t vm_epoch) {
                uint16_t old_conn = pble_conn_handle;
                uint64_t old_generation = pble_conn_generation;
                if (pble_term_disconnect(&pble_term_state, old_conn,
                                         old_generation) !=
                    PBLE_TERM_EFFECT_INVALIDATE) {
                    return false;
                }
                (void)pble_term_cleanup_complete(
                    &pble_term_state, old_conn, old_generation);
                if (pble_term_state.phase != PBLE_TERM_PHASE_CLOSED) {
                    return false;
                }
                pble_conn_handle = BLE_HS_CONN_HANDLE_NONE;
                pble_conn_generation = 0;
                pble_session_vm_epoch = 0;
                pble_protocol_violation_count = 0;
                pble_termination_clear_locked();
                pble_reset_reassembly();
                if (!pble_term_open(&pble_term_state, conn, generation)) {
                    return false;
                }
                pble_conn_handle = conn;
                pble_conn_generation = generation;
                pble_session_vm_epoch = vm_epoch;
                pble_protocol_violation_count = 0;
                pble_termination_clear_locked();
                return true;
            }

            static int scenario_deadline_boundary(void) {
                pble_session_token_t session = {7, 11, 21};
                uint8_t first[] = {PBLE_FRAG_FIRST, 'A'};
                uint8_t last[] = {PBLE_FRAG_LAST | 1, 'B'};
                if (!model_open(session.conn, session.generation,
                                session.vm_epoch)) return 10;

                fake_now_us = 100000;
                pble_rx_ingest(first, sizeof(first), &session);
                fake_now_us = 5099000;  /* elapsed 4,999 ms */
                pble_rx_ingest(last, sizeof(last), &session);
                if (dispatch_calls != 1 || dispatched_len != 2 ||
                    memcmp(dispatched, "AB", 2) != 0 ||
                    pble_protocol_violation_count != 0) return 11;

                fake_now_us = 10000000;
                pble_rx_ingest(first, sizeof(first), &session);
                fake_now_us = 15000000;  /* elapsed exactly 5,000 ms */
                pble_rx_ingest(last, sizeof(last), &session);
                if (dispatch_calls != 1 ||
                    pble_protocol_violation_count != 1 ||
                    !pble_rx_discard_tail) return 12;
                return 0;
            }

            static int scenario_non_extending(void) {
                pble_session_token_t session = {7, 11, 21};
                uint8_t first[] = {PBLE_FRAG_FIRST, 'A'};
                uint8_t progress[] = {1, 'B'};
                uint8_t last[] = {PBLE_FRAG_LAST | 2, 'C'};
                if (!model_open(session.conn, session.generation,
                                session.vm_epoch)) return 20;
                fake_now_us = 100000;
                pble_rx_ingest(first, sizeof(first), &session);
                fake_now_us = 4100000;
                pble_rx_ingest(progress, sizeof(progress), &session);
                if (pble_rx_started_us != 100000 ||
                    pble_rx_next_index != 2) return 21;
                fake_now_us = 5100000;
                pble_rx_ingest(last, sizeof(last), &session);
                if (dispatch_calls != 0 ||
                    pble_protocol_violation_count != 1 ||
                    !pble_rx_discard_tail) return 22;
                return 0;
            }

            static int scenario_discard_once(void) {
                pble_session_token_t session = {7, 11, 21};
                uint8_t first[] = {PBLE_FRAG_FIRST, 'A'};
                uint8_t gap[] = {PBLE_FRAG_LAST | 2, 'B'};
                uint8_t tail[] = {PBLE_FRAG_LAST | 3, 'C'};
                if (!model_open(session.conn, session.generation,
                                session.vm_epoch)) return 30;
                fake_now_us = 100;
                pble_rx_ingest(first, sizeof(first), &session);
                pble_rx_ingest(gap, sizeof(gap), &session);
                for (int index = 0; index < 32; index++) {
                    tail[0] = (uint8_t)((index + 3) & PBLE_FRAG_IDX_MASK);
                    if (index == 31) tail[0] |= PBLE_FRAG_LAST;
                    pble_rx_ingest(tail, sizeof(tail), &session);
                }
                if (dispatch_calls != 0 ||
                    pble_protocol_violation_count != 1 ||
                    !pble_rx_discard_tail) return 31;
                return 0;
            }

            static int scenario_first_replacement(void) {
                pble_session_token_t session = {7, 11, 21};
                uint8_t old_first[] = {PBLE_FRAG_FIRST, 'o', 'l', 'd'};
                uint8_t replacement[] = {
                    PBLE_FRAG_FIRST | PBLE_FRAG_LAST, 'n', 'e', 'w'
                };
                uint8_t gap[] = {2, 'x'};
                if (!model_open(session.conn, session.generation,
                                session.vm_epoch)) return 40;
                fake_now_us = 100;
                pble_rx_ingest(old_first, sizeof(old_first), &session);
                pble_rx_ingest(replacement, sizeof(replacement), &session);
                if (dispatch_calls != 1 || dispatched_len != 3 ||
                    memcmp(dispatched, "new", 3) != 0 ||
                    pble_protocol_violation_count != 0) return 41;

                pble_rx_ingest(old_first, sizeof(old_first), &session);
                pble_rx_ingest(gap, sizeof(gap), &session);
                if (!pble_rx_discard_tail ||
                    pble_protocol_violation_count != 1) return 42;
                pble_rx_ingest(replacement, sizeof(replacement), &session);
                if (dispatch_calls != 2 || dispatched_len != 3 ||
                    memcmp(dispatched, "new", 3) != 0 ||
                    pble_rx_discard_tail ||
                    pble_protocol_violation_count != 1) return 43;
                return 0;
            }

            static int scenario_terminal_budget(void) {
                pble_session_token_t session = {7, 11, 21};
                if (!model_open(session.conn, session.generation,
                                session.vm_epoch)) return 50;
                for (int index = 0; index < 7; index++) {
                    if (!pble_ble_record_protocol_violation(&session)) return 51;
                }

                memset(pble_rx_buf, 'x', sizeof(pble_rx_buf));
                pble_rx_buf[0] = PBLE_PROTO_VERSION;
                pble_rx_buf[1] = PBLE_TYPE_CMD;
                pble_rx_buf[2] = 0x20;
                pble_rx_buf[3] = 0x2a;
                pble_rx_buf[4] = 0;
                pble_rx_buf[5] = 0;
                pble_rx_len = sizeof(pble_rx_buf);
                pble_rx_active = true;
                pble_rx_next_index = 1;
                pble_rx_started_us = fake_now_us;
                pble_rx_discard_tail = false;
                uint8_t overflow[] = {1, 'z'};
                pble_rx_ingest(overflow, sizeof(overflow), &session);

                if (pble_protocol_violation_count != 8 || refuse_calls != 0 ||
                    termination_calls != 1 ||
                    !token_equal(terminated_session, session) ||
                    pble_session_admits_locked(&session)) return 52;
                if (pble_ble_record_protocol_violation(&session) ||
                    termination_calls != 1 ||
                    pble_protocol_violation_count != 8) return 53;
                return 0;
            }

            static int scenario_reset_budget(void) {
                pble_session_token_t original = {7, 11, 21};
                if (!model_open(original.conn, original.generation,
                                original.vm_epoch)) return 60;
                for (int index = 0; index < 7; index++) {
                    if (!pble_ble_record_protocol_violation(&original)) return 61;
                }

                if (!model_vm_rotation(12, 22)) return 62;
                pble_session_token_t rotated = {7, 12, 22};
                if (pble_ble_record_protocol_violation(&original) ||
                    pble_protocol_violation_count != 0 ||
                    !pble_session_admits_locked(&rotated)) return 63;
                for (int index = 0; index < 7; index++) {
                    if (!pble_ble_record_protocol_violation(&rotated)) return 64;
                }
                if (pble_protocol_violation_count != 7 ||
                    termination_calls != 0) return 65;

                if (!model_disconnect_reconnect(8, 13, 22)) return 66;
                pble_session_token_t reconnected = {8, 13, 22};
                if (pble_ble_record_protocol_violation(&rotated) ||
                    pble_protocol_violation_count != 0 ||
                    !pble_session_admits_locked(&reconnected)) return 67;
                for (int index = 0; index < 7; index++) {
                    if (!pble_ble_record_protocol_violation(&reconnected)) return 68;
                }
                if (pble_protocol_violation_count != 7 ||
                    termination_calls != 0) return 69;
                return 0;
            }

            int main(int argc, char **argv) {
                if (argc != 2) return 2;
                if (strcmp(argv[1], "deadline-boundary") == 0)
                    return scenario_deadline_boundary();
                if (strcmp(argv[1], "non-extending") == 0)
                    return scenario_non_extending();
                if (strcmp(argv[1], "discard-once") == 0)
                    return scenario_discard_once();
                if (strcmp(argv[1], "first-replacement") == 0)
                    return scenario_first_replacement();
                if (strcmp(argv[1], "terminal-budget") == 0)
                    return scenario_terminal_budget();
                if (strcmp(argv[1], "reset-budget") == 0)
                    return scenario_reset_budget();
                return 3;
            }
            '''
        )

        cls._temporary = tempfile.TemporaryDirectory(
            prefix="pyble-v061-native-rx-behavior-"
        )
        temporary = Path(cls._temporary.name)
        source = temporary / "native_rx_behavior_probe.c"
        cls._binary = temporary / "native_rx_behavior_probe"
        source.write_text(
            preamble + "\n" + production_functions + "\n" + scenarios,
            encoding="utf-8",
        )
        built = subprocess.run(
            [
                compiler,
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-Wno-unused-function",
                "-I",
                str(NATIVE),
                str(source),
                str(TERMINATION_PATH),
                "-o",
                str(cls._binary),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if built.returncode != 0:
            cls._temporary.cleanup()
            raise AssertionError(
                "native FR-BLE-10 probe did not compile:\n{}{}".format(
                    built.stdout, built.stderr
                )
            )

    @classmethod
    def tearDownClass(cls) -> None:
        temporary = getattr(cls, "_temporary", None)
        if temporary is not None:
            temporary.cleanup()

    def _assert_scenario(self, scenario: str) -> None:
        executed = subprocess.run(
            [str(self._binary), scenario],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(
            executed.returncode,
            0,
            "native FR-BLE-10 scenario {!r} failed at probe cut {}:\n{}{}".format(
                scenario, executed.returncode, executed.stdout, executed.stderr
            ),
        )

    def test_4999ms_is_accepted_but_5000ms_is_expired(self) -> None:
        self._assert_scenario("deadline-boundary")

    def test_fragment_progress_never_extends_the_first_deadline(self) -> None:
        self._assert_scenario("non-extending")

    def test_discarded_run_tails_debit_the_budget_once(self) -> None:
        self._assert_scenario("discard-once")

    def test_first_replaces_incomplete_and_discarded_runs(self) -> None:
        self._assert_scenario("first-replacement")

    def test_eighth_violation_suppresses_reply_and_terminates_once(self) -> None:
        self._assert_scenario("terminal-budget")

    def test_vm_rotation_and_reconnect_restore_only_the_new_budget(self) -> None:
        self._assert_scenario("reset-budget")


if __name__ == "__main__":
    unittest.main(verbosity=2)
