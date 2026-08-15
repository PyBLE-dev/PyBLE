#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""ESP identify-timer lifecycle and FreeRTOS include contracts."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / "firmware" / "user_c_modules" / "pyble"
DEVICE_CONFIG = (NATIVE / "pble_device_config.c").read_text(encoding="utf-8")


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


@dataclass(frozen=True)
class BlinkTicket:
    epoch: int
    incarnation: int


class IdentifyTimerOracle:
    """Deterministic same-epoch arm/callback interleaving oracle."""

    def __init__(self, epoch: int = 7) -> None:
        self.epoch = epoch
        self.incarnation = 0
        self.armed: BlinkTicket | None = None
        self.ticks = 0
        self.toggles = 0
        self.stops = 0

    def arm(self, ticks: int) -> BlinkTicket:
        self.incarnation += 1
        self.armed = BlinkTicket(self.epoch, self.incarnation)
        self.ticks = ticks
        return self.armed

    def callback_snapshot(self) -> BlinkTicket | None:
        return self.armed

    def callback_tick(self, ticket: BlinkTicket | None) -> bool:
        if ticket is None or ticket != self.armed or self.ticks <= 0:
            return False
        self.ticks -= 1
        self.toggles += 1
        return True

    def callback_terminal_stop(self, ticket: BlinkTicket | None) -> bool:
        if ticket is None or ticket != self.armed or self.ticks > 0:
            return False
        self.armed = None
        self.stops += 1
        return True


class FrozenIdentifyTimerInterleavingTests(unittest.TestCase):
    def test_old_same_epoch_callback_cannot_consume_a_new_arm(self):
        timer = IdentifyTimerOracle()
        timer.arm(2)
        old = timer.callback_snapshot()
        new = timer.arm(1)

        self.assertFalse(timer.callback_tick(old))
        self.assertEqual(timer.armed, new)
        self.assertEqual(timer.ticks, 1)
        self.assertEqual(timer.toggles, 0)

    def test_old_terminal_stop_cannot_stop_a_new_same_epoch_arm(self):
        timer = IdentifyTimerOracle()
        timer.arm(0)
        old = timer.callback_snapshot()
        new = timer.arm(1)

        self.assertFalse(timer.callback_terminal_stop(old))
        self.assertEqual(timer.armed, new)
        self.assertEqual(timer.ticks, 1)
        self.assertEqual(timer.stops, 0)


class NativeFreeRtosIncludeContractTests(unittest.TestCase):
    def test_task_critical_macros_have_their_defining_header(self):
        missing = []
        task_header = re.compile(
            r'(?m)^\s*#\s*include\s*[<"]freertos/task\.h[>"]'
        )
        task_macro = re.compile(r"\btask(?:ENTER|EXIT)_CRITICAL\s*\(")
        for path in sorted(NATIVE.glob("*.c")):
            source = path.read_text(encoding="utf-8")
            if task_macro.search(source) and not task_header.search(source):
                missing.append(path.name)
        self.assertEqual(
            missing,
            [],
            "sources using taskENTER/EXIT_CRITICAL must directly include "
            "freertos/task.h; freertos/FreeRTOS.h does not define those macros",
        )


class NativeIdentifyTimerContractTests(unittest.TestCase):
    def test_callback_ticket_and_timer_stop_start_share_one_arm_cut(self):
        declaration = re.search(
            r"(?m)^\s*static\s+uint64_t\s+"
            r"(?P<name>dc_blink_[A-Za-z0-9_]*incarnation[A-Za-z0-9_]*)\s*;",
            DEVICE_CONFIG,
        )
        self.assertIsNotNone(
            declaration,
            "identify timer needs a retained per-arm incarnation in addition "
            "to its VM epoch",
        )
        incarnation = declaration.group("name")

        callback = code_only(c_function(DEVICE_CONFIG, "dc_blink_cb"))
        handler = code_only(c_function(DEVICE_CONFIG, "pble_dc_identify_cmd"))

        local = re.search(
            rf"\buint64_t\s+(?P<name>[A-Za-z_]\w*incarnation\w*)\s*;",
            callback,
        )
        self.assertIsNotNone(local, "callback must snapshot the arm incarnation")
        local_name = local.group("name")
        snapshot = re.search(
            rf"\b{re.escape(local_name)}\s*=\s*{re.escape(incarnation)}\s*;",
            callback,
        )
        self.assertIsNotNone(snapshot)
        lifecycle_entry = callback.find("pble_vm_callback_enter")
        self.assertGreater(lifecycle_entry, snapshot.end())

        callback_sections = critical_sections(callback, "dc_blink_mux")
        self.assertTrue(
            any(snapshot.group(0) in section for section in callback_sections),
            "epoch and arm incarnation snapshot must be one timer-state cut",
        )
        exact_match = re.compile(
            rf"(?:{re.escape(incarnation)}\s*==\s*{re.escape(local_name)}|"
            rf"{re.escape(local_name)}\s*==\s*{re.escape(incarnation)})"
        )
        self.assertTrue(
            any(
                exact_match.search(section) and "dc_led_write" in section
                for section in callback_sections
            ),
            "callback must revalidate the exact arm under dc_blink_mux before "
            "consuming ticks or changing GPIO",
        )
        self.assertTrue(
            any(
                exact_match.search(section) and "esp_timer_stop" in section
                for section in callback_sections
            ),
            "terminal stop must revalidate and remain inside the timer-state cut",
        )

        handler_sections = critical_sections(handler, "dc_blink_mux")
        arm_sections = [
            section
            for section in handler_sections
            if "esp_timer_stop" in section and "esp_timer_start_periodic" in section
        ]
        self.assertEqual(
            len(arm_sections),
            1,
            "IDENTIFY stop, incarnation mint, state publish, and periodic start "
            "must be one serialized arm cut",
        )
        self.assertIn(incarnation, arm_sections[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
