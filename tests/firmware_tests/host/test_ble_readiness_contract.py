#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] ADR-0024 / FR-SPLASH-4 — native BLE-readiness source contract.
#
# These host checks deliberately inspect the native source.  The asynchronous
# NimBLE callbacks cannot run on CPython, but their state transitions and the
# MicroPython wrapper are safety-critical enough to pin before cross-build/HIL.

from __future__ import annotations

from pathlib import Path
import re
import unittest


HOST_DIR = Path(__file__).resolve().parent
REPO_ROOT = HOST_DIR.parents[2]
PBLE_BLE_C = (
    REPO_ROOT / "firmware" / "user_c_modules" / "pyble" / "pble_ble.c"
)
SOURCE = PBLE_BLE_C.read_text(encoding="utf-8")

READY_EVENTS = "pble_ready_events"
READY_BIT = "PBLE_READY_BIT"


def _strip_c_comments(text: str) -> str:
    """Remove comments for structural matching while preserving line order."""

    return re.sub(r"//[^\n]*|/\*.*?\*/", " ", text, flags=re.DOTALL)


def _function(name: str) -> str:
    """Return one complete C function definition, including its braces."""

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
                return SOURCE[match.start():index + 1]
        index += 1
    raise AssertionError("unterminated native function {}".format(name))


def _case(function: str, label: str, next_label: str | None) -> str:
    clean = _strip_c_comments(function)
    tail = (
        r"(?=\bcase\s+{}\s*:|\bdefault\s*:|\Z)".format(
            re.escape(next_label)
        )
        if next_label is not None
        else r"(?=\bdefault\s*:|\Z)"
    )
    match = re.search(
        r"\bcase\s+{}\s*:(?P<body>.*?){}".format(
            re.escape(label), tail
        ),
        clean,
        re.DOTALL,
    )
    if match is None:
        raise AssertionError("missing switch case {}".format(label))
    return match.group("body")


def _ordered(test: unittest.TestCase, text: str, *needles: str) -> None:
    positions = []
    for needle in needles:
        position = text.find(needle)
        test.assertGreaterEqual(position, 0, "missing {!r}".format(needle))
        positions.append(position)
    test.assertEqual(
        positions,
        sorted(positions),
        "native operations must occur in order: {}".format(" -> ".join(needles)),
    )


def _return_is_checked(text: str, call: str) -> bool:
    """Accept an inline return check or a captured result checked afterward."""

    inline = re.search(
        r"if\s*\([^;{{}}]*{}\s*\([^;]+?\)\s*!=\s*0\s*\)".format(
            re.escape(call)
        ),
        text,
        re.DOTALL,
    )
    if inline is not None:
        return True
    captured = re.search(
        r"(?:int|int32_t|ble_hs_error_t)\s+(?P<rc>[A-Za-z_]\w*)\s*=\s*"
        r"{}\s*\([^;]+?\)\s*;".format(re.escape(call)),
        text,
        re.DOTALL,
    )
    if captured is None:
        return False
    return re.search(
        r"if\s*\([^;{{}}]*\b{}\b\s*!=\s*0".format(
            re.escape(captured.group("rc"))
        ),
        text[captured.end():],
        re.DOTALL,
    ) is not None


class ReadyEventAllocationContractTests(unittest.TestCase):
    def test_event_group_is_persistent_optional_and_idempotently_allocated(self):
        self.assertRegex(
            SOURCE,
            r'#include\s+"freertos/event_groups\.h"',
            "FR-SPLASH-4 requires the FreeRTOS Event Group API",
        )
        self.assertRegex(
            SOURCE,
            r"(?m)^\s*#\s*define\s+{}\s+(?:BIT0|\(?\s*1\s*<<\s*0\s*\)?)\s*$".format(
                READY_BIT
            ),
            "readiness must use one named Event Group bit",
        )
        self.assertRegex(
            SOURCE,
            r"(?m)^\s*static\s+EventGroupHandle_t\s+{}\s*(?:=\s*NULL\s*)?;".format(
                READY_EVENTS
            ),
            "the event handle must be native-static so it survives a VM reset",
        )

        init = _strip_c_comments(_function("pble_ble_init"))
        allocation = re.search(
            r"if\s*\(\s*{}\s*==\s*NULL\s*\)\s*\{{(?P<body>.*?)\}}".format(
                READY_EVENTS
            ),
            init,
            re.DOTALL,
        )
        self.assertIsNotNone(
            allocation,
            "pble_ble_init must allocate the persistent event only while null",
        )
        allocation_body = allocation.group("body")
        self.assertRegex(
            allocation_body,
            r"{}\s*=\s*xEventGroupCreate\s*\(\s*\)\s*;".format(
                READY_EVENTS
            ),
        )
        self.assertNotRegex(
            allocation_body,
            r"\bmp_raise|\breturn\b|\bgoto\b",
            "readiness allocation failure is nonfatal and must not abort BLE init",
        )
        clean_source = _strip_c_comments(SOURCE)
        self.assertEqual(
            clean_source.count("xEventGroupCreate("),
            1,
            "soft resets must not create duplicate Event Groups",
        )
        self.assertNotIn(
            "vEventGroupDelete(",
            clean_source,
            "the native readiness event persists across MicroPython soft resets",
        )
        self.assertRegex(
            init,
            r"(?s)if\s*\(\s*pble_started\s*\)\s*\{\s*"
            r"pble_ready_refresh\s*\(\s*\)\s*;\s*return\s*;\s*\}",
            "a recovered Event Group must reflect live advertising before soft-reset return",
        )
        _ordered(
            self,
            init,
            "xEventGroupCreate()",
            "if (pble_started)",
            "nimble_port_init()",
        )

    def test_set_clear_and_refresh_helpers_are_null_safe_and_truth_based(self):
        ready_set = _strip_c_comments(_function("pble_ready_set"))
        ready_clear = _strip_c_comments(_function("pble_ready_clear"))
        refresh = _strip_c_comments(_function("pble_ready_refresh"))

        self.assertRegex(
            ready_set,
            r"if\s*\(\s*{}\s*!=\s*NULL\s*\)".format(READY_EVENTS),
        )
        self.assertRegex(
            ready_set,
            r"xEventGroupSetBits\s*\(\s*{}\s*,\s*{}\s*\)".format(
                READY_EVENTS, READY_BIT
            ),
        )
        self.assertRegex(
            ready_clear,
            r"if\s*\(\s*{}\s*!=\s*NULL\s*\)".format(READY_EVENTS),
        )
        self.assertRegex(
            ready_clear,
            r"xEventGroupClearBits\s*\(\s*{}\s*,\s*{}\s*\)".format(
                READY_EVENTS, READY_BIT
            ),
        )
        self.assertRegex(
            refresh,
            r"{}\s*!=\s*BLE_HS_CONN_HANDLE_NONE\s*\|\|\s*"
            r"ble_gap_adv_active\s*\(\s*\)".format("pble_conn_handle"),
            "refresh must derive readiness only from a live connection or active adv",
        )
        self.assertIn("pble_ready_set();", refresh)
        self.assertIn("pble_ready_clear();", refresh)
        self.assertNotIn(
            "pble_synced",
            refresh,
            "NimBLE synchronization alone is not transport readiness",
        )
        self.assertEqual(
            _strip_c_comments(SOURCE).count("xEventGroupSetBits("),
            1,
            "all READY assertions must pass through the null-safe set helper",
        )
        self.assertEqual(
            _strip_c_comments(SOURCE).count("xEventGroupClearBits("),
            1,
            "all READY invalidations must pass through the null-safe clear helper",
        )


class AdvertisingReadinessTransitionContractTests(unittest.TestCase):
    def test_advertise_checks_every_return_and_accepts_active_ealready(self):
        advertise = _strip_c_comments(_function("pble_advertise"))
        for call in (
            "ble_gap_adv_set_fields",
            "ble_gap_adv_rsp_set_fields",
            "ble_gap_adv_start",
        ):
            with self.subTest(call=call):
                self.assertRegex(
                    advertise,
                    r"(?:int\s+\w+\s*=\s*)?{}\s*\(".format(call),
                    "advertising must call {}".format(call),
                )

        self.assertTrue(
            _return_is_checked(advertise, "ble_gap_adv_set_fields"),
            "advertising-field rejection must be checked",
        )
        self.assertTrue(
            _return_is_checked(advertise, "ble_gap_adv_rsp_set_fields"),
            "scan-response rejection must be checked",
        )
        start = re.search(
            r"int\s+(?P<rc>[A-Za-z_]\w*)\s*=\s*ble_gap_adv_start\s*\(",
            advertise,
        )
        self.assertIsNotNone(start, "the adv-start return code must be captured")
        rc = start.group("rc")
        self.assertRegex(
            advertise,
            r"{}\s*==\s*0".format(re.escape(rc)),
            "only an accepted start may assert readiness directly",
        )
        self.assertRegex(
            advertise,
            r"{}\s*==\s*BLE_HS_EALREADY".format(re.escape(rc)),
            "the start/active race must be distinguished from other failures",
        )
        self.assertRegex(
            advertise,
            r"{}\s*==\s*BLE_HS_EALREADY[^{{;]*"
            r"ble_gap_adv_active\s*\(\s*\)".format(re.escape(rc)),
            "EALREADY is ready only when NimBLE confirms advertising is active",
        )
        self.assertRegex(
            advertise,
            r"(?s)if\s*\(\s*{}\s*==\s*0\s*\|\|\s*\(\s*{}\s*==\s*"
            r"BLE_HS_EALREADY\s*&&\s*ble_gap_adv_active\s*\(\s*\)\s*\)\s*\)"
            r"\s*\{{\s*pble_ready_set\s*\(\s*\)\s*;".format(
                re.escape(rc), re.escape(rc)
            ),
            "READY assertion must be inside the accepted-start/active-race branch",
        )
        self.assertGreaterEqual(
            advertise.count("pble_ready_refresh();"),
            2,
            "every failed field/start path must recompute truth before returning",
        )

    def test_gap_connect_disconnect_and_adv_complete_refresh_in_exact_order(self):
        gap = _function("pble_gap_event")
        connect = _case(gap, "BLE_GAP_EVENT_CONNECT", "BLE_GAP_EVENT_DISCONNECT")
        disconnect = _case(gap, "BLE_GAP_EVENT_DISCONNECT", "BLE_GAP_EVENT_ENC_CHANGE")
        adv_complete = _case(gap, "BLE_GAP_EVENT_ADV_COMPLETE", "BLE_GAP_EVENT_MTU")

        success = re.search(
            r"if\s*\(\s*event->connect\.status\s*==\s*0\s*\)\s*\{"
            r"(?P<body>.*?)\}\s*else\s*\{(?P<failure>.*?)\}",
            connect,
            re.DOTALL,
        )
        self.assertIsNotNone(success, "CONNECT must distinguish success/failure")
        _ordered(
            self,
            success.group("body"),
            "pble_conn_handle = event->connect.conn_handle;",
            "pble_ready_refresh();",
        )
        _ordered(
            self,
            success.group("failure"),
            "pble_ready_clear();",
            "pble_advertise();",
        )

        _ordered(
            self,
            disconnect,
            "pble_conn_handle = BLE_HS_CONN_HANDLE_NONE;",
            "pble_ready_clear();",
            "pble_advertise();",
        )
        self.assertRegex(
            adv_complete,
            r"(?s)^\s*if\s*\(\s*pble_conn_handle\s*==\s*"
            r"BLE_HS_CONN_HANDLE_NONE\s*\)\s*\{\s*"
            r"pble_ready_clear\s*\(\s*\)\s*;.*?"
            r"pble_advertise\s*\(\s*\)\s*;.*?\}",
            "ADV_COMPLETE must invalidate readiness then restart only disconnected",
        )

    def test_nimble_reset_invalidates_sync_connection_and_ready_state(self):
        reset = _strip_c_comments(_function("pble_on_reset"))
        clear_at = reset.find("pble_ready_clear();")
        self.assertGreaterEqual(clear_at, 0, "reset must invalidate readiness")
        for assignment in (
            "pble_synced = false;",
            "pble_conn_handle = BLE_HS_CONN_HANDLE_NONE;",
        ):
            with self.subTest(assignment=assignment):
                position = reset.find(assignment)
                self.assertGreaterEqual(position, 0, "missing {}".format(assignment))
                self.assertLess(
                    position,
                    clear_at,
                    "reset must invalidate cached state before clearing READY",
                )
        self.assertNotIn(
            "pble_ready_set();",
            reset,
            "a reset cannot infer availability from stale state",
        )

    def test_ready_bit_can_only_be_asserted_from_truth_or_accepted_start(self):
        set_calls = [
            match.start()
            for match in re.finditer(
                r"\bpble_ready_set\s*\(\s*\)\s*;",
                _strip_c_comments(SOURCE),
            )
        ]
        self.assertEqual(
            len(set_calls),
            2,
            "READY may be set only by truth refresh or an accepted adv start",
        )
        owners = []
        for name in ("pble_ready_refresh", "pble_advertise"):
            body = _function(name)
            if "pble_ready_set();" in body:
                owners.append(name)
        self.assertEqual(owners, ["pble_ready_refresh", "pble_advertise"])


class WaitReadyMicroPythonContractTests(unittest.TestCase):
    def test_wait_ready_validates_exact_integer_range_and_exports_one_arg_api(self):
        wait = _strip_c_comments(_function("pble_ble_wait_ready"))
        self.assertRegex(
            wait,
            r"mp_obj_is_(?:int|integer)\s*\(",
            "bool/float/string coercion is forbidden: timeout must be an integer",
        )
        timeout = re.search(
            r"mp_int_t\s+(?P<name>[A-Za-z_]\w*)\s*=\s*mp_obj_get_int\s*\(",
            wait,
        )
        self.assertIsNotNone(timeout, "the exact integer timeout must be retained")
        timeout_name = re.escape(timeout.group("name"))
        self.assertRegex(wait, r"\b{}\s*<\s*0".format(timeout_name))
        self.assertRegex(wait, r"\b{}\s*>\s*1500".format(timeout_name))
        self.assertRegex(
            wait,
            r"mp_(?:raise_TypeError|raise_msg\s*\(\s*&mp_type_TypeError)",
        )
        self.assertRegex(
            wait,
            r"mp_(?:raise_ValueError|raise_msg\s*\(\s*&mp_type_ValueError)",
        )
        self.assertRegex(
            SOURCE,
            r"MP_DEFINE_CONST_FUN_OBJ_1\s*\(\s*pble_ble_wait_ready_obj\s*,\s*"
            r"pble_ble_wait_ready\s*\)",
        )
        self.assertRegex(
            SOURCE,
            r"(?s)MP_ROM_QSTR\s*\(\s*MP_QSTR_wait_ready\s*\).*?"
            r"MP_ROM_PTR\s*\(\s*&pble_ble_wait_ready_obj\s*\)",
        )

    def test_wait_ready_is_null_safe_bounded_gil_releasing_and_nonclearing(self):
        wait = _strip_c_comments(_function("pble_ble_wait_ready"))
        self.assertRegex(
            wait,
            r"(?s)if\s*\(\s*{}\s*==\s*NULL\s*\).*?"
            r"return\s+mp_const_false\s*;".format(READY_EVENTS),
            "allocation failure must turn every wait into false",
        )
        self.assertRegex(
            wait,
            r"pdMS_TO_TICKS\s*\(",
            "the validated millisecond deadline must be converted once to ticks",
        )
        timeout = re.search(
            r"mp_int_t\s+(?P<name>[A-Za-z_]\w*)\s*=\s*mp_obj_get_int\s*\(",
            wait,
        )
        ticks = re.search(
            r"TickType_t\s+(?P<name>[A-Za-z_]\w*)\s*=\s*pdMS_TO_TICKS\s*\(",
            wait,
        )
        self.assertIsNotNone(timeout, "wait_ready must retain the validated timeout")
        self.assertIsNotNone(ticks, "wait_ready must retain the bounded tick deadline")
        self.assertRegex(
            wait,
            r"(?s)if\s*\(\s*{}\s*>\s*0\s*&&\s*{}\s*==\s*0\s*\)\s*\{{?"
            r".*?{}\s*=\s*1\s*;".format(
                re.escape(timeout.group("name")),
                re.escape(ticks.group("name")),
                re.escape(ticks.group("name")),
            ),
            "a nonzero timeout must round up to one RTOS tick, never zero-wait",
        )
        self.assertNotIn("portMAX_DELAY", wait)
        _ordered(
            self,
            wait,
            "MP_THREAD_GIL_EXIT();",
            "xEventGroupWaitBits(",
            "MP_THREAD_GIL_ENTER();",
        )
        wait_call = re.search(
            r"xEventGroupWaitBits\s*\(\s*{}\s*,\s*{}\s*,\s*"
            r"pdFALSE\s*,\s*pdFALSE\s*,\s*[^)]+\)".format(
                READY_EVENTS, READY_BIT
            ),
            wait,
            re.DOTALL,
        )
        self.assertIsNotNone(
            wait_call,
            "xEventGroupWaitBits must use clear-on-exit=false and one bounded wait",
        )
        self.assertEqual(wait.count("xEventGroupWaitBits("), 1)
        self.assertNotIn(
            "xEventGroupClearBits(",
            wait,
            "observing READY must not consume it",
        )
        self.assertRegex(
            wait,
            r"return\s+mp_obj_new_bool\s*\([^;]*{}[^;]*\)\s*;".format(
                READY_BIT
            ),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
