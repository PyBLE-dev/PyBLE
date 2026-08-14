#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] ADR-0034 — exact-board retained OI-1 link-fact state.

from __future__ import annotations

from pathlib import Path
import re
import unittest


HOST_DIR = Path(__file__).resolve().parent
REPO_ROOT = HOST_DIR.parents[2]
FIRMWARE = REPO_ROOT / "firmware"
SOURCE_PATH = FIRMWARE / "user_c_modules" / "pyble" / "pble_ble.c"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
WAVE_HEADER = (
    FIRMWARE
    / "board_overlays"
    / "waveshare-esp32-s3-lcd-147b"
    / "mpconfigboard.h"
).read_text(encoding="utf-8")


def _strip_c_comments(text: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", " ", text, flags=re.DOTALL)


def _function(name: str) -> str:
    match = re.search(
        r"(?m)^static[^\n;{{}}]*\b{}\s*\([^;{{}}]*\)\s*\{{".format(
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
        following = SOURCE[index + 1] if index + 1 < len(SOURCE) else ""
        if state == "line-comment":
            if char == "\n":
                state = "code"
        elif state == "block-comment":
            if char == "*" and following == "/":
                state = "code"
                index += 1
        elif state == "string":
            if char == "\\":
                index += 1
            elif char == '"':
                state = "code"
        elif state == "character":
            if char == "\\":
                index += 1
            elif char == "'":
                state = "code"
        elif char == "/" and following == "/":
            state = "line-comment"
            index += 1
        elif char == "/" and following == "*":
            state = "block-comment"
            index += 1
        elif char == '"':
            state = "string"
        elif char == "'":
            state = "character"
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return SOURCE[match.start() : index + 1]
        index += 1
    raise AssertionError("unterminated native function {}".format(name))


def _gap_case(label: str, next_label: str) -> str:
    body = _strip_c_comments(_function("pble_gap_event"))
    match = re.search(
        r"\bcase\s+{}\s*:(?P<body>.*?)"
        r"(?=\bcase\s+{}\s*:)".format(
            re.escape(label), re.escape(next_label)
        ),
        body,
        re.DOTALL,
    )
    if match is None:
        raise AssertionError("missing GAP case {}".format(label))
    return match.group("body")


class WaveshareNativeLinkFactContractTests(unittest.TestCase):
    def test_exact_board_is_the_only_overlay_enabling_hidden_state(self):
        self.assertEqual(
            len(
                re.findall(
                    r"(?m)^\s*#\s*define\s+PBLE_ENABLE_OI1_LINK_FACTS\s+\(?1\)?\s*$",
                    WAVE_HEADER,
                )
            ),
            1,
        )
        for header in sorted((FIRMWARE / "board_overlays").glob("*/mpconfigboard.h")):
            if header.parent.name == "waveshare-esp32-s3-lcd-147b":
                continue
            with self.subTest(overlay=header.parent.name):
                self.assertNotIn(
                    "PBLE_ENABLE_OI1_LINK_FACTS",
                    header.read_text(encoding="utf-8"),
                )
        clean = _strip_c_comments(SOURCE)
        self.assertRegex(
            clean,
            r"#\s*ifndef\s+PBLE_ENABLE_OI1_LINK_FACTS\s+"
            r"#\s*define\s+PBLE_ENABLE_OI1_LINK_FACTS\s+0\b",
        )
        self.assertRegex(
            clean,
            r"#\s*if\s+PBLE_ENABLE_OI1_LINK_FACTS[\s\S]*"
            r"MP_QSTR__oi1_link_facts[\s\S]*#\s*endif",
        )

    def test_retained_state_is_fixed_bounded_and_overflow_latched(self):
        clean = _strip_c_comments(SOURCE)
        self.assertRegex(clean, r"#\s*define\s+PBLE_OI1_PHY_UPDATE_CAP\s+8\b")
        self.assertRegex(clean, r"#\s*define\s+PBLE_OI1_CP_UPDATE_CAP\s+8\b")
        self.assertRegex(
            clean,
            r"phy_updates\s*\[\s*PBLE_OI1_PHY_UPDATE_CAP\s*\]",
        )
        self.assertRegex(
            clean,
            r"cp_updates\s*\[\s*PBLE_OI1_CP_UPDATE_CAP\s*\]",
        )
        self.assertRegex(
            clean,
            r"cp_return_codes\s*\[\s*PBLE_CP_ATTEMPT_MAX\s*\]",
        )
        for helper, cap in (
            ("pble_oi1_note_phy", "PBLE_OI1_PHY_UPDATE_CAP"),
            ("pble_oi1_note_cp", "PBLE_OI1_CP_UPDATE_CAP"),
            ("pble_oi1_note_cp_request", "PBLE_CP_ATTEMPT_MAX"),
        ):
            with self.subTest(helper=helper):
                body = _strip_c_comments(_function(helper))
                self.assertIn(cap, body)
                self.assertIn("overflow = true", body)

    def test_every_session_mutation_is_private_handle_bound(self):
        for helper in (
            "pble_oi1_note_dle_request",
            "pble_oi1_note_phy_request",
            "pble_oi1_note_cp_request",
            "pble_oi1_note_dle",
            "pble_oi1_note_phy",
            "pble_oi1_note_cp",
            "pble_oi1_end_session",
        ):
            with self.subTest(helper=helper):
                body = _strip_c_comments(_function(helper))
                self.assertRegex(
                    body,
                    r"pble_oi1_active_handle\s*==\s*conn_handle",
                )

        connect = _gap_case("BLE_GAP_EVENT_CONNECT", "BLE_GAP_EVENT_DISCONNECT")
        disconnect = _gap_case("BLE_GAP_EVENT_DISCONNECT", "BLE_GAP_EVENT_ENC_CHANGE")
        phy = _gap_case(
            "BLE_GAP_EVENT_PHY_UPDATE_COMPLETE", "BLE_GAP_EVENT_DATA_LEN_CHG"
        )
        cp = _gap_case("BLE_GAP_EVENT_CONN_UPDATE", "BLE_GAP_EVENT_NOTIFY_TX")
        self.assertIn("pble_oi1_begin_session(event->connect.conn_handle)", connect)
        self.assertIn("pble_oi1_end_session(event->disconnect.conn.conn_handle)", disconnect)
        self.assertIn("event->phy_updated.conn_handle", phy)
        self.assertIn("event->conn_update.conn_handle", cp)

    def test_data_length_event_uses_one_live_cached_handle_snapshot(self):
        dle = _gap_case("BLE_GAP_EVENT_DATA_LEN_CHG", "BLE_GAP_EVENT_CONN_UPDATE")
        self.assertNotIn("event->data_len_chg.conn_handle", dle)

        snapshots = list(
            re.finditer(
                r"\buint16_t\s+(?P<name>[A-Za-z_]\w*)\s*=\s*"
                r"pble_conn_handle\s*;",
                dle,
            )
        )
        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[0]
        handle = snapshot.group("name")
        self.assertEqual(dle.count("pble_conn_handle"), 1)

        none_guard = re.search(
            r"\bif\s*\(\s*{}\s*==\s*BLE_HS_CONN_HANDLE_NONE\s*\)\s*"
            r"\{{\s*break\s*;\s*\}}".format(re.escape(handle)),
            dle,
        )
        self.assertIsNotNone(none_guard)
        self.assertGreater(none_guard.start(), snapshot.end())
        self.assertGreater(dle.find("pble_dle_confirmed"), none_guard.end())
        self.assertGreater(dle.find("pble_oi1_note_dle("), none_guard.end())
        self.assertRegex(
            dle,
            r"pble_oi1_note_dle\s*\(\s*{}\s*,".format(re.escape(handle)),
        )

        note = _strip_c_comments(_function("pble_oi1_note_dle"))
        self.assertRegex(
            note,
            r"pble_oi1_active\.valid\s*&&\s*"
            r"pble_oi1_active_handle\s*==\s*conn_handle",
        )

    def test_cross_task_starvation_uses_handle_and_epoch_once(self):
        clean = _strip_c_comments(SOURCE)
        self.assertRegex(
            clean,
            r"typedef\s+struct\s*\{[^}]*uint16_t\s+conn_handle\s*;"
            r"[^}]*uint64_t\s+epoch\s*;[^}]*\}\s*pble_oi1_session_token_t\s*;",
        )
        note = _strip_c_comments(_function("pble_oi1_note_starve"))
        self.assertIn("pble_oi1_active_handle == token.conn_handle", note)
        self.assertIn("pble_oi1_active.epoch == token.epoch", note)
        self.assertEqual(note.count("pble_tx_mbuf_starve++"), 1)
        self.assertEqual(note.count("tx_mbuf_starve_count++"), 1)

        notify = _strip_c_comments(_function("pble_notify_packet"))
        token = notify.find("pble_oi1_session_token(")
        allocation = notify.find("ble_hs_mbuf_from_flat(")
        self.assertGreaterEqual(token, 0)
        self.assertGreater(allocation, token)
        self.assertEqual(notify.count("pble_oi1_note_starve("), 2)
        self.assertNotIn("pble_tx_mbuf_starve++", notify)

        generic = re.search(
            r"#\s*else(?P<body>[\s\S]*?)#\s*endif\s+"
            r"static\s+int\s+pble_request_dle",
            clean,
        )
        self.assertIsNotNone(generic)
        self.assertRegex(
            generic.group("body"),
            r"#\s*define\s+pble_oi1_note_starve\([^)]*\)"
            r"[^\n]*pble_tx_mbuf_starve\+\+",
        )

    def test_epoch_and_reset_fail_closed_without_wrap(self):
        begin = _strip_c_comments(_function("pble_oi1_begin_session"))
        self.assertIn("pble_oi1_epoch == UINT64_MAX", begin)
        exhausted = begin.find("pble_oi1_epoch_exhausted = true")
        increment = begin.find("pble_oi1_epoch++")
        self.assertGreaterEqual(exhausted, 0)
        self.assertGreater(increment, exhausted)

        invalidate = _strip_c_comments(_function("pble_oi1_invalidate_active"))
        self.assertRegex(
            invalidate,
            r"if\s*\(\s*pble_oi1_active\.valid\s*\)\s*\{[^}]*"
            r"pble_oi1_epoch_exhausted\s*=\s*true",
        )
        reset = _strip_c_comments(_function("pble_on_reset"))
        self.assertIn("pble_oi1_invalidate_active()", reset)

    def test_getter_validates_atomic_pod_before_any_python_allocation(self):
        getter = _strip_c_comments(_function("pble_ble_oi1_link_facts"))
        enter = getter.find("taskENTER_CRITICAL(&pble_oi1_mux)")
        exit_ = getter.find("taskEXIT_CRITICAL(&pble_oi1_mux)")
        first_allocation = min(
            position
            for position in (
                getter.find("mp_obj_new_dict("),
                getter.find("pble_oi1_make_record("),
            )
            if position >= 0
        )
        self.assertGreaterEqual(enter, 0)
        self.assertGreater(exit_, enter)
        self.assertGreater(first_allocation, exit_)
        self.assertNotRegex(
            getter[enter:exit_],
            r"\bmp_obj_|\bmp_raise|\bmp_obj_new",
        )
        consistency = getter.find("bad_counts")
        shape = getter.find("bad_shape")
        self.assertGreater(consistency, exit_)
        self.assertGreater(shape, consistency)
        self.assertGreater(first_allocation, shape)
        for required in (
            "PBLE_OI1_PHY_UPDATE_CAP",
            "PBLE_OI1_CP_UPDATE_CAP",
            "PBLE_CP_ATTEMPT_MAX",
            "snapshot.active_handle_valid",
            "snapshot.current_epoch",
            "snapshot.last_ended.epoch + 1",
        ):
            self.assertIn(required, getter)


if __name__ == "__main__":
    unittest.main()
