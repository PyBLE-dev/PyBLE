#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] ADR-0027 — bounded, timer-progressed native link settlement.

from __future__ import annotations

from pathlib import Path
import re
import unittest


HOST_DIR = Path(__file__).resolve().parent
REPO_ROOT = HOST_DIR.parents[2]
SOURCE = (
    REPO_ROOT / "firmware" / "user_c_modules" / "pyble" / "pble_ble.c"
).read_text(encoding="utf-8")


def _strip_c_comments(text: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", " ", text, flags=re.DOTALL)


def _function(name: str) -> str:
    match = re.search(
        r"(?m)^[^\n;{{}}]*\b{}\s*\([^;{{}}]*\)\s*\{{".format(
            re.escape(name)
        ),
        SOURCE,
    )
    if match is None:
        raise AssertionError("missing native function {}".format(name))
    opening = SOURCE.find("{", match.start())
    depth = 0
    index = opening
    state = "code"
    while index < len(SOURCE):
        char = SOURCE[index]
        nxt = SOURCE[index + 1] if index + 1 < len(SOURCE) else ""
        if state == "line_comment":
            if char == "\n":
                state = "code"
        elif state == "block_comment":
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
            state = "line_comment"
            index += 1
        elif char == "/" and nxt == "*":
            state = "block_comment"
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
                return SOURCE[match.start() : index + 1]
        index += 1
    raise AssertionError("unterminated native function {}".format(name))


def _case(label: str, next_label: str) -> str:
    gap = _strip_c_comments(_function("pble_gap_event"))
    match = re.search(
        r"\bcase\s+{}\s*:(?P<body>.*?)"
        r"(?=\bcase\s+{}\s*:)".format(
            re.escape(label), re.escape(next_label)
        ),
        gap,
        re.DOTALL,
    )
    if match is None:
        raise AssertionError("missing GAP case {}".format(label))
    return match.group("body")


class LinkTuneStateContractTests(unittest.TestCase):
    def test_all_three_phase_budgets_and_state_are_explicit(self):
        clean = _strip_c_comments(SOURCE)
        for macro, value in (
            ("PBLE_DLE_ATTEMPT_MAX", 4),
            ("PBLE_PHY_ATTEMPT_MAX", 4),
            ("PBLE_CP_ATTEMPT_MAX", 3),
        ):
            self.assertRegex(
                clean,
                r"#\s*define\s+{}\s+{}\b".format(macro, value),
            )
        for declaration in (
            r"static\s+bool\s+pble_dle_confirmed",
            r"static\s+uint8_t\s+pble_dle_attempts",
            r"static\s+bool\s+pble_phy_confirmed_2m",
            r"static\s+uint8_t\s+pble_phy_attempts",
            r"static\s+bool\s+pble_cp_confirmed",
            r"static\s+uint8_t\s+pble_cp_attempts",
        ):
            self.assertRegex(clean, declaration)

    def test_timer_separates_phy_and_connection_parameter_submissions(self):
        tune = _strip_c_comments(_function("pble_link_tune"))
        phy = tune.find("pble_request_phy(")
        conn_param = tune.find("pble_request_conn_param(")
        self.assertGreaterEqual(phy, 0, "PHY submission must use one bounded helper")
        self.assertGreater(conn_param, phy)
        between = tune[phy:conn_param]
        self.assertIn("ble_npl_callout_reset(", between)
        self.assertRegex(
            between,
            r"\breturn\s*;",
            "PHY and connection-parameter procedures must not be submitted back-to-back",
        )

    def test_each_submission_is_counted_logged_and_timer_recoverable(self):
        dle = _strip_c_comments(_function("pble_request_dle"))
        phy = _strip_c_comments(_function("pble_request_phy"))
        conn_param = _strip_c_comments(_function("pble_request_conn_param"))
        for body, phase, counter, api in (
            (dle, "dle", "pble_dle_attempts", "ble_gap_set_data_len"),
            (phy, "phy", "pble_phy_attempts", "ble_gap_set_prefered_le_phy"),
            (conn_param, "conn-param", "pble_cp_attempts", "ble_gap_update_params"),
        ):
            with self.subTest(phase=phase):
                increment = body.find(counter + "++")
                submission = body.find(api + "(")
                self.assertGreaterEqual(increment, 0)
                self.assertGreater(submission, increment)
                self.assertIn(
                    "link tune req phase={} attempt=%u context=%s rc=%d".format(
                        phase
                    ),
                    body,
                )
        tune = _strip_c_comments(_function("pble_link_tune"))
        self.assertGreaterEqual(
            tune.count("ble_npl_callout_reset(&pble_link_tune_co"),
            3,
            "the timer must remain the progress guarantee for every live phase",
        )

    def test_completion_and_session_end_grammar_is_parser_owned(self):
        expected_literals = (
            "link tune complete phase=dle max_tx_octets=%u max_tx_time_us=%u",
            "link tune complete phase=phy status=%d tx=%u rx=%u",
            "link tune complete phase=conn-param status=%d interval_units=%u",
            "link tune skip phase=phy context=classic-compiled-out",
            "link tune session end tx_mbuf_starve_count=%lu",
        )
        for literal in expected_literals:
            with self.subTest(literal=literal):
                self.assertIn(literal, SOURCE)

    def test_completion_events_confirm_only_qualified_values(self):
        phy = _case("BLE_GAP_EVENT_PHY_UPDATE_COMPLETE", "BLE_GAP_EVENT_DATA_LEN_CHG")
        self.assertRegex(phy, r"event->phy_updated\.status\s*==\s*0")
        self.assertRegex(phy, r"event->phy_updated\.tx_phy\s*==\s*2")
        self.assertRegex(phy, r"event->phy_updated\.rx_phy\s*==\s*2")
        self.assertIn("pble_phy_confirmed_2m", phy)

        conn_param = _case("BLE_GAP_EVENT_CONN_UPDATE", "BLE_GAP_EVENT_NOTIFY_TX")
        self.assertRegex(conn_param, r"event->conn_update\.status\s*==\s*0")
        self.assertRegex(conn_param, r"itvl\s*>=\s*PBLE_CONN_ITVL_MIN")
        self.assertRegex(conn_param, r"itvl\s*<=\s*PBLE_CONN_ITVL_MAX")
        self.assertIn("pble_cp_confirmed", conn_param)

    def test_connect_and_disconnect_reset_the_entire_session_state(self):
        connect = _case("BLE_GAP_EVENT_CONNECT", "BLE_GAP_EVENT_DISCONNECT")
        disconnect = _case("BLE_GAP_EVENT_DISCONNECT", "BLE_GAP_EVENT_ENC_CHANGE")
        reset_assignments = (
            "pble_dle_confirmed = false",
            "pble_dle_attempts = 0",
            "pble_phy_confirmed_2m = false",
            "pble_phy_attempts = 0",
            "pble_cp_confirmed = false",
            "pble_cp_attempts = 0",
        )
        for assignment in reset_assignments:
            with self.subTest(assignment=assignment):
                self.assertIn(assignment, connect)
                self.assertIn(assignment, disconnect)
        self.assertIn("ble_npl_callout_stop(&pble_link_tune_co)", disconnect)


if __name__ == "__main__":
    unittest.main()
