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


def matching_brace(source: str, opening: int) -> int:
    depth = 0
    index = opening
    while index < len(source):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise AssertionError("unterminated braced statement")


def braced_statement(source: str, start: int) -> str:
    opening = source.find("{", start)
    if opening < 0:
        raise AssertionError("missing statement body")
    return source[start : matching_brace(source, opening) + 1]


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
    """Deterministic pinned timer dequeue/quiescence interleaving oracle."""

    OFF = "off"
    QUIESCE = "quiesce"
    ACTIVATE = "activate"
    ACTIVE = "active"

    def __init__(self, epoch: int = 7) -> None:
        self.epoch = epoch
        self.incarnation = 0
        self.epoch_open = True
        self.phase = self.OFF
        self.armed: BlinkTicket | None = None
        self.pending_ticks = 0
        self.ticks = 0
        self.toggles = 0
        self.stops = 0
        self.drains = 0

    def request_arm(self, ticks: int) -> None:
        self.pending_ticks = ticks
        self.phase = self.QUIESCE

    def dequeue_expiration(self) -> BlinkTicket | None:
        """IDF copies this identity before releasing its timer-list lock."""
        return self.armed if self.phase == self.ACTIVE else None

    def dispatch(self, dequeued: BlinkTicket | None) -> str:
        # Any invocation that starts after a request is first a drain boundary,
        # even when IDF dequeued it from the previous periodic arm.
        if self.phase == self.QUIESCE:
            self.phase = self.ACTIVATE
            self.drains += 1
            return "drained"
        if self.phase == self.ACTIVATE:
            if not self.epoch_open:
                self.invalidate()
                return "cancelled"
            self._activate()
            return "activated"
        if (
            self.phase == self.ACTIVE
            and dequeued is not None
            and dequeued == self.armed
            and self.ticks > 0
        ):
            self.ticks -= 1
            self.toggles += 1
            return "toggled"
        return "stale"

    def close_epoch_before_activation(self) -> None:
        self.epoch_open = False

    def invalidate(self) -> None:
        self.phase = self.OFF
        self.armed = None
        self.pending_ticks = 0
        self.ticks = 0

    def _activate(self) -> BlinkTicket:
        self.incarnation += 1
        self.armed = BlinkTicket(self.epoch, self.incarnation)
        self.ticks = self.pending_ticks
        self.pending_ticks = 0
        self.phase = self.ACTIVE
        return self.armed

    def terminal_stop(self, dequeued: BlinkTicket | None) -> bool:
        if (
            self.phase != self.ACTIVE
            or dequeued is None
            or dequeued != self.armed
            or self.ticks > 0
        ):
            return False
        self.armed = None
        self.phase = self.OFF
        self.stops += 1
        return True


class FrozenIdentifyTimerInterleavingTests(unittest.TestCase):
    def activate(self, timer: IdentifyTimerOracle, ticks: int) -> BlinkTicket:
        timer.request_arm(ticks)
        self.assertEqual(timer.dispatch(None), "drained")
        self.assertEqual(timer.dispatch(None), "activated")
        self.assertIsNotNone(timer.armed)
        return timer.armed

    def test_dequeued_old_periodic_is_only_the_successor_drain_boundary(self):
        timer = IdentifyTimerOracle()
        old_arm = self.activate(timer, 2)
        old_expiration = timer.dequeue_expiration()
        self.assertEqual(old_expiration, old_arm)

        timer.request_arm(1)
        self.assertEqual(timer.dispatch(old_expiration), "drained")
        self.assertEqual(timer.armed, old_arm)
        self.assertEqual(timer.phase, timer.ACTIVATE)
        self.assertEqual((timer.ticks, timer.toggles, timer.stops), (2, 0, 0))

        self.assertEqual(timer.dispatch(None), "activated")
        new = timer.armed
        self.assertNotEqual(new, old_arm)
        self.assertEqual(timer.ticks, 1)
        self.assertEqual(timer.toggles, 0)
        self.assertEqual(timer.dispatch(old_expiration), "stale")
        self.assertEqual((timer.armed, timer.ticks, timer.toggles), (new, 1, 0))

    def test_dequeued_activation_overtaken_by_new_request_becomes_drain_only(self):
        timer = IdentifyTimerOracle()
        timer.request_arm(4)
        self.assertEqual(timer.dispatch(None), "drained")
        dequeued_activation = timer.dequeue_expiration()

        timer.request_arm(1)
        self.assertEqual(timer.dispatch(dequeued_activation), "drained")
        self.assertIsNone(timer.armed)
        self.assertEqual((timer.ticks, timer.toggles, timer.stops), (0, 0, 0))
        self.assertEqual(timer.dispatch(None), "activated")
        self.assertEqual(timer.ticks, 1)

    def test_repeated_identify_keeps_only_the_latest_pending_request(self):
        timer = IdentifyTimerOracle()
        self.activate(timer, 5)
        stale_periodic = timer.dequeue_expiration()

        timer.request_arm(4)
        timer.request_arm(3)
        self.assertEqual(timer.dispatch(stale_periodic), "drained")
        timer.request_arm(2)  # overtake the already-queued activation
        self.assertEqual(timer.dispatch(None), "drained")
        self.assertEqual(timer.dispatch(None), "activated")
        self.assertEqual((timer.ticks, timer.toggles), (2, 0))

    def test_vm_refusal_or_config_clear_cancels_pending_and_old_callbacks(self):
        timer = IdentifyTimerOracle()
        timer.request_arm(2)
        self.assertEqual(timer.dispatch(None), "drained")
        timer.close_epoch_before_activation()
        self.assertEqual(timer.dispatch(None), "cancelled")
        self.assertEqual((timer.phase, timer.armed, timer.ticks), (timer.OFF, None, 0))

        timer = IdentifyTimerOracle()
        self.activate(timer, 2)
        old = timer.dequeue_expiration()
        timer.request_arm(1)
        timer.invalidate()  # SET_IDENTIFY_LED clear/reconfigure or VM disarm
        self.assertEqual(timer.dispatch(old), "stale")
        self.assertEqual((timer.phase, timer.armed, timer.ticks), (timer.OFF, None, 0))

    def test_old_terminal_stop_cannot_stop_a_new_same_epoch_arm(self):
        timer = IdentifyTimerOracle()
        old = self.activate(timer, 0)
        old_expiration = timer.dequeue_expiration()
        timer.request_arm(1)
        self.assertEqual(timer.dispatch(old_expiration), "drained")
        self.assertEqual(timer.dispatch(None), "activated")
        new = timer.armed

        self.assertFalse(timer.terminal_stop(old_expiration))
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
    def phase_contract(self) -> tuple[str, str, str, str, str]:
        native_code = code_only(DEVICE_CONFIG)
        phase = re.search(
            r"(?m)^\s*static\s+(?:volatile\s+)?[A-Za-z_]\w*\s+"
            r"(?P<name>dc_blink_[A-Za-z0-9_]*phase[A-Za-z0-9_]*)\s*;",
            native_code,
        )
        self.assertIsNotNone(
            phase,
            "identify needs an explicit quiesce/activate/active timer phase",
        )
        constants = {}
        for label in ("IDLE", "QUIESCE", "ACTIVATE", "ACTIVE"):
            match = re.search(
                rf"\b(?P<name>[A-Z][A-Z0-9_]*BLINK[A-Z0-9_]*{label}[A-Z0-9_]*)\b",
                native_code,
            )
            self.assertIsNotNone(match, "missing identify {} phase".format(label))
            constants[label] = match.group("name")
        self.assertEqual(len(set(constants.values())), 4)
        return (
            phase.group("name"),
            constants["IDLE"],
            constants["QUIESCE"],
            constants["ACTIVATE"],
            constants["ACTIVE"],
        )

    def test_handler_queues_quiescence_without_publishing_successor_arm(self):
        phase, _, quiesce, _, _ = self.phase_contract()
        handler = code_only(c_function(DEVICE_CONFIG, "pble_dc_identify_cmd"))
        sections = critical_sections(handler, "dc_blink_mux")
        request_cut = next(
            (
                section
                for section in sections
                if "esp_timer_stop" in section
                and re.search(
                    rf"\b{re.escape(phase)}\s*=\s*{re.escape(quiesce)}\s*;",
                    section,
                )
                and "esp_timer_start_once" in section
            ),
            None,
        )
        self.assertIsNotNone(
            request_cut,
            "IDENTIFY must stop, publish pending QUIESCE, and queue its drain "
            "boundary in one identify-domain cut",
        )
        self.assertNotIn(
            "esp_timer_start_periodic",
            handler,
            "the handler must not publish/start the successor active arm",
        )
        self.assertNotRegex(
            request_cut,
            r"(?:\+\+\s*dc_blink_\w*incarnation|"
            r"dc_blink_\w*incarnation\s*(?:\+\+|\+=|=\s*dc_blink_\w*incarnation\s*\+))",
            "active incarnation mint belongs only to the activation callback",
        )
        self.assertIn("ESP_ERR_INVALID_STATE", handler)
        self.assertIn("ESP_OK", handler)
        self.assertRegex(
            handler,
            r"[A-Za-z_]\w*\s*=\s*esp_timer_stop\s*\(",
            "handler must inspect stop instead of assuming it joined old work",
        )
        self.assertRegex(
            handler,
            r"[A-Za-z_]\w*\s*=\s*esp_timer_start_once\s*\(",
            "handler must inspect quiescence-boundary arm failure",
        )
        self.assertIn("PBLE_EINTERNAL", handler)

    def test_quiesce_and_activation_callbacks_are_distinct_no_effect_phases(self):
        phase, _, quiesce, activate, active = self.phase_contract()
        callback = code_only(c_function(DEVICE_CONFIG, "dc_blink_cb"))

        quiesce_if = re.search(
            rf"if\s*\(\s*{re.escape(phase)}\s*==\s*{re.escape(quiesce)}\s*\)",
            callback,
        )
        self.assertIsNotNone(quiesce_if)
        drain = braced_statement(callback, quiesce_if.start())
        self.assertRegex(
            drain,
            rf"\b{re.escape(phase)}\s*=\s*{re.escape(activate)}\s*;",
        )
        self.assertIn("esp_timer_stop", drain)
        self.assertIn("esp_timer_start_once", drain)
        self.assertLess(
            drain.find("esp_timer_stop"),
            drain.find("esp_timer_start_once"),
            "old dequeued work must remove the handler boundary before ACTIVATE",
        )
        self.assertIn("ESP_ERR_INVALID_STATE", drain)
        self.assertIn("ESP_OK", drain)
        self.assertRegex(drain, r"\breturn\s*;")
        for forbidden in (
            "esp_timer_start_periodic",
            "dc_led_write",
            "dc_blink_ticks--",
        ):
            self.assertNotIn(
                forbidden,
                drain,
                "dequeued old work must be drain-only",
            )

        activate_if = re.search(
            rf"if\s*\(\s*{re.escape(phase)}\s*==\s*{re.escape(activate)}\s*\)",
            callback,
        )
        self.assertIsNotNone(activate_if)
        activation = braced_statement(callback, activate_if.start())
        self.assertRegex(
            activation,
            rf"\b{re.escape(phase)}\s*=\s*{re.escape(active)}\s*;",
        )
        self.assertIn("esp_timer_start_periodic", activation)
        self.assertRegex(activation, r"\breturn\s*;")
        self.assertNotIn(
            "dc_blink_ticks--",
            activation,
            "activation publishes the arm but consumes no tick",
        )

        incarnation = re.search(
            r"(?m)^\s*static\s+uint64_t\s+"
            r"(?P<name>dc_blink_[A-Za-z0-9_]*incarnation[A-Za-z0-9_]*)\s*;",
            DEVICE_CONFIG,
        )
        self.assertIsNotNone(incarnation)
        incarnation_name = incarnation.group("name")
        self.assertRegex(
            activation,
            rf"(?:\+\+\s*{re.escape(incarnation_name)}|"
            rf"{re.escape(incarnation_name)}\s*\+\+|"
            rf"{re.escape(incarnation_name)}\s*\+=\s*1|"
            rf"{re.escape(incarnation_name)}\s*=\s*"
            rf"{re.escape(incarnation_name)}\s*\+\s*1)",
            "only ACTIVATE may mint the successor ticket",
        )
        mint = re.search(
            rf"(?:\+\+\s*{re.escape(incarnation_name)}|"
            rf"{re.escape(incarnation_name)}\s*\+\+|"
            rf"{re.escape(incarnation_name)}\s*\+=\s*1|"
            rf"{re.escape(incarnation_name)}\s*=\s*"
            rf"{re.escape(incarnation_name)}\s*\+\s*1)",
            activation,
        )
        self.assertIsNotNone(mint)
        skips_zero = re.search(
            rf"if\s*\(\s*{re.escape(incarnation_name)}\s*==\s*0\s*\)",
            activation[mint.end() :],
        )
        fails_before_wrap = re.search(
            rf"if\s*\(\s*{re.escape(incarnation_name)}\s*==\s*UINT64_MAX\s*\)"
            rf"[^}}]*esp_restart",
            activation[: mint.start()],
            re.DOTALL,
        )
        self.assertTrue(
            skips_zero or fails_before_wrap,
            "activation incarnation must never publish wrapped zero/ABA",
        )

    def test_activation_enters_and_revalidates_pending_epoch_or_cancels(self):
        phase, idle, _, activate, _ = self.phase_contract()
        pending = re.search(
            r"(?m)^\s*static\s+uint64_t\s+"
            r"(?P<name>dc_blink_[A-Za-z0-9_]*pending[A-Za-z0-9_]*epoch[A-Za-z0-9_]*)\s*;",
            code_only(DEVICE_CONFIG),
        )
        self.assertIsNotNone(
            pending,
            "pending request epoch must remain separate from the active arm",
        )
        pending_epoch = pending.group("name")
        handler = code_only(c_function(DEVICE_CONFIG, "pble_dc_identify_cmd"))
        self.assertRegex(
            handler,
            rf"\b{re.escape(pending_epoch)}\s*=\s*session->vm_epoch\s*;",
        )

        callback = code_only(c_function(DEVICE_CONFIG, "dc_blink_cb"))
        local = re.search(
            rf"\b(?P<name>[A-Za-z_]\w*)\s*=\s*"
            rf"{re.escape(pending_epoch)}\s*;",
            callback,
        )
        self.assertIsNotNone(local, "callback must snapshot the pending epoch")
        local_epoch = local.group("name")
        self.assertRegex(
            callback[: local.start()],
            rf"\buint64_t\s+{re.escape(local_epoch)}\s*(?:;|=)",
        )
        enter = re.search(
            rf"pble_vm_callback_enter\s*\(\s*{re.escape(local_epoch)}\s*,",
            callback,
        )
        self.assertIsNotNone(enter)
        activation_if = re.search(
            rf"if\s*\(\s*{re.escape(phase)}\s*==\s*{re.escape(activate)}\s*\)",
            callback,
        )
        self.assertIsNotNone(activation_if)
        self.assertLess(enter.start(), activation_if.start())
        exact_pending = re.compile(
            rf"(?:{re.escape(pending_epoch)}\s*==\s*{re.escape(local_epoch)}|"
            rf"{re.escape(local_epoch)}\s*==\s*{re.escape(pending_epoch)})"
        )
        self.assertTrue(
            any(
                re.search(
                    rf"\b{re.escape(phase)}\s*==\s*{re.escape(activate)}\b",
                    section,
                )
                and exact_pending.search(section)
                and "esp_timer_start_periodic" in section
                for section in critical_sections(callback, "dc_blink_mux")
            ),
            "activation must revalidate exact pending phase/epoch under the mux",
        )

        refused = re.search(
            r"if\s*\(\s*!\s*pble_vm_callback_enter\s*\([^)]*\)\s*\)",
            callback,
        )
        self.assertIsNotNone(refused)
        refused_body = braced_statement(callback, refused.start())
        cancel_cut = next(
            (
                section
                for section in critical_sections(refused_body, "dc_blink_mux")
                if re.search(
                    rf"\b{re.escape(phase)}\s*==\s*{re.escape(activate)}\b",
                    section,
                )
                and exact_pending.search(section)
                and re.search(
                    rf"\b{re.escape(phase)}\s*=\s*{re.escape(idle)}\s*;",
                    section,
                )
                and re.search(
                    rf"\b{re.escape(pending_epoch)}\s*=\s*0\s*;",
                    section,
                )
            ),
            None,
        )
        self.assertIsNotNone(
            cancel_cut,
            "lifecycle refusal may cancel only the same pending activation",
        )
        self.assertRegex(refused_body, r"\breturn\s*;")

    def test_clear_reconfigure_and_vm_disarm_invalidate_both_timer_phases(self):
        phase, idle, _, _, _ = self.phase_contract()
        set_config = code_only(c_function(DEVICE_CONFIG, "pble_dc_set_identify_led"))
        disarm = code_only(c_function(DEVICE_CONFIG, "pble_dc_vm_timer_disarm"))
        idle_write = re.compile(
            rf"\b{re.escape(phase)}\s*=\s*{re.escape(idle)}\s*;"
        )
        self.assertGreaterEqual(
            len(idle_write.findall(set_config)),
            2,
            "both clear and successful reconfiguration invalidate timer phases",
        )
        self.assertRegex(disarm, idle_write)
        for body in (set_config, disarm):
            self.assertRegex(body, r"\bdc_blink_\w*pending\w*\s*=\s*0\s*;")
            self.assertRegex(body, r"\bdc_blink_epoch\s*=\s*0\s*;")
            self.assertRegex(body, r"\bdc_blink_ticks\s*=\s*0\s*;")

    def test_active_callback_revalidates_ticket_phase_and_terminal_stop(self):
        phase, _, _, _, active = self.phase_contract()
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
                exact_match.search(section)
                and re.search(
                    rf"\b{re.escape(phase)}\s*==\s*{re.escape(active)}\b",
                    section,
                )
                and "dc_led_write" in section
                for section in callback_sections
            ),
            "ACTIVE callback must revalidate phase and exact arm under "
            "dc_blink_mux before consuming ticks or changing GPIO",
        )
        self.assertTrue(
            any(
                exact_match.search(section) and "esp_timer_stop" in section
                for section in callback_sections
            ),
            "terminal stop must revalidate and remain inside the timer-state cut",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
