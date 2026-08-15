#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""RED contract for native state isolation across ESP MicroPython VMs."""

from __future__ import annotations

import ast
import re
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / "firmware" / "user_c_modules" / "pyble"
OVERLAYS = ROOT / "firmware" / "board_overlays"
ESP_TARGETS = (
    "esp32",
    "esp32-s3",
    "esp32-c3",
    "waveshare-esp32-s3-lcd-147b",
)


def source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="strict")
    except FileNotFoundError:
        return ""


VM_C = source(NATIVE / "pble_vm_lifecycle.c")
VM_H = source(NATIVE / "pble_vm_lifecycle.h")
BLE = source(NATIVE / "pble_ble.c")
PROTO = source(NATIVE / "pble_proto.c")
PROTO_H = source(NATIVE / "pble_proto.h")
RUNNER = source(NATIVE / "pble_runner.c")
FS = source(NATIVE / "pble_fs.c")
CONSOLE = source(NATIVE / "pble_console.c")
DEVICE_CONFIG = source(NATIVE / "pble_device_config.c")
CMAKE = source(NATIVE / "micropython.cmake")
BUILD = source(ROOT / "firmware" / "scripts" / "build.sh")
LINK_GATE = source(
    ROOT / "firmware" / "scripts" / "verify_vm_lifecycle_linkage.py"
)
ESP_MAIN = source(
    ROOT / "firmware" / "upstream" / "micropython" / "ports" / "esp32" / "main.c"
)
ESP_CONFIG = source(
    ROOT
    / "firmware"
    / "upstream"
    / "micropython"
    / "ports"
    / "esp32"
    / "mpconfigport.h"
)
MP_RUNTIME = source(
    ROOT / "firmware" / "upstream" / "micropython" / "py" / "runtime.c"
)


def code_only(text: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.DOTALL)


def c_function(text: str, name: str) -> str:
    match = re.search(
        rf"(?m)^[^\n;{{}}]*\b{re.escape(name)}\s*\([^;{{}}]*\)\s*\{{",
        text,
    )
    if match is None:
        return ""
    opening = text.find("{", match.start())
    depth = 0
    state = "code"
    index = opening
    while index < len(text):
        char = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""
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
                return text[match.start() : index + 1]
        index += 1
    return ""


def ordered(test: unittest.TestCase, text: str, *needles: str) -> None:
    positions = [text.find(needle) for needle in needles]
    for needle, position in zip(needles, positions):
        test.assertGreaterEqual(position, 0, "missing {!r}".format(needle))
    test.assertEqual(positions, sorted(positions), "wrong operation order")


def dotted_name(node: ast.AST) -> str:
    names: list[str] = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        names.append(node.id)
    return ".".join(reversed(names))


class ForcedRestart(RuntimeError):
    """Oracle result for a fail-closed whole-board restart."""


@dataclass(frozen=True)
class ActivityToken:
    serial: int
    epoch: int
    kind: str


class VmLifecycleOracle:
    """Deterministic model of the admission/activity and deinit boundary."""

    MAX_ACTIVITY = (1 << 32) - 1
    DEINIT_BUDGET_MS = 2500

    def __init__(self) -> None:
        self.epoch = 9
        self.open = True
        self.closing = False
        self.active: dict[int, ActivityToken] = {}
        self.activity_count_override: int | None = None
        self.serial = 0
        self.deadline_ms: int | None = None
        self.effects: list[str] = []
        self.roots = {"runner": object(), "fs": object()}
        self.tx_owner: str | None = None
        self.old_tasks_alive = True
        self.detached = False
        self.real_deinit_called = False
        self.soft_pending = True
        self.soft_armed_epoch: int | None = self.epoch
        self.current_response = "old-frame"

    def enter(self, kind: str) -> ActivityToken | None:
        if not self.open:
            return None
        activity_count = (
            len(self.active)
            if self.activity_count_override is None
            else self.activity_count_override
        )
        if activity_count >= self.MAX_ACTIVITY:
            raise ForcedRestart("activity overflow")
        self.serial += 1
        token = ActivityToken(self.serial, self.epoch, kind)
        self.active[token.serial] = token
        return token

    def leave(self, token: ActivityToken) -> None:
        if self.active.pop(token.serial, None) != token:
            raise ForcedRestart("activity underflow or token mismatch")

    def effect(self, token: ActivityToken, name: str) -> None:
        if self.active.get(token.serial) != token or self.detached:
            raise AssertionError("handler effect escaped its lifecycle activity")
        self.effects.append(name)

    def begin_wrapper(self, now_ms: int) -> None:
        if self.closing:
            raise ForcedRestart("CLOSING cannot become a fresh VM session")
        self.open = False
        self.deadline_ms = now_ms + self.DEINIT_BUDGET_MS
        self.current_response = None

    def activity_drained(self, now_ms: int) -> bool:
        if self.deadline_ms is None:
            raise AssertionError("wrapper has not begun")
        if self.active and now_ms >= self.deadline_ms:
            raise ForcedRestart("activity drain deadline")
        return not self.active

    def disarm_timer(self, state: str) -> None:
        if state not in {"stopped", "inactive", "already-fired"}:
            raise ForcedRestart("unexpected timer disarm failure")
        self.soft_pending = False
        self.soft_armed_epoch = None

    def acquire_tx(self) -> bool:
        if self.tx_owner is not None:
            return False
        self.tx_owner = "wrapper"
        return True

    def detach_and_real_deinit(self) -> None:
        if self.tx_owner != "wrapper" or self.active:
            raise AssertionError("deinit requires drained activity and TX ownership")
        self.roots = {"runner": None, "fs": None}
        self.detached = True
        self.real_deinit_called = True
        self.old_tasks_alive = False

    def release_tx_after_real(self) -> None:
        if not self.real_deinit_called or self.old_tasks_alive:
            raise AssertionError("TX released before old tasks were deleted")
        self.tx_owner = None

    def worker_try_tx(self) -> bool:
        if not self.old_tasks_alive or self.tx_owner is not None:
            return False
        self.tx_owner = "old-worker"
        return True

    def port_init(self) -> None:
        if self.closing:
            raise ForcedRestart("CLOSING cannot rotate open")
        if self.old_tasks_alive:
            raise AssertionError("port init precedes old-task deletion")
        self.epoch += 1
        self.roots = {"runner": None, "fs": None}
        self.open = False
        self.current_response = None

    def ready(self) -> None:
        self.open = True
        self.current_response = "new-frame"

    def response_peek(self) -> tuple[ActivityToken, str] | None:
        token = self.enter("response-callout")
        if token is None:
            return None
        if self.current_response is None:
            self.leave(token)
            return None
        return token, self.current_response

    def response_resume(self, token: ActivityToken, frame: str) -> bool:
        submitted = self.open and token.epoch == self.epoch and frame == self.current_response
        self.leave(token)
        return submitted


@dataclass(frozen=True)
class RxFragmentToken:
    serial: int
    epoch: int
    valid_run: bool


class RxLifecycleOracle:
    """Model RX reassembly held inside one lifecycle activity."""

    def __init__(self) -> None:
        self.epoch = 3
        self.open = True
        self.serial = 0
        self.callbacks: dict[int, RxFragmentToken] = {}
        self.active_run = False
        self.next_index = 0
        self.buffer = bytearray()
        self.dispatches: list[bytes] = []
        self.activity_at_dispatch: list[int] = []

    def _clear_run(self) -> None:
        self.active_run = False
        self.next_index = 0
        self.buffer.clear()

    def begin_fragment(
        self,
        *,
        first: bool,
        last: bool,
        index: int,
        data: bytes,
    ) -> RxFragmentToken | None:
        # Lifecycle admission precedes every fragment read/copy. Refusal clears
        # the incomplete run and drops this fragment atomically.
        if not self.open:
            self._clear_run()
            return None

        self.serial += 1
        if first:
            self._clear_run()
            self.active_run = True
            valid_run = True
        else:
            valid_run = self.active_run and index == self.next_index
            if not valid_run:
                self._clear_run()

        token = RxFragmentToken(self.serial, self.epoch, valid_run)
        self.callbacks[token.serial] = token
        if valid_run:
            self.buffer.extend(data)
            self.next_index = (index + 1) % 64
        return token

    def finish_fragment(self, token: RxFragmentToken, *, last: bool) -> None:
        if self.callbacks.get(token.serial) != token:
            raise AssertionError("RX callback token is not active")
        if token.epoch != self.epoch:
            raise AssertionError("RX callback resumed in a recycled epoch")
        if token.valid_run and last:
            self.activity_at_dispatch.append(len(self.callbacks))
            self.dispatches.append(bytes(self.buffer))
            self._clear_run()
        self.callbacks.pop(token.serial)

    def close(self) -> None:
        self.open = False

    def reset_if_drained(self) -> bool:
        if self.callbacks:
            return False
        self._clear_run()
        self.epoch += 1
        return True

    def ready(self) -> None:
        self.open = True


class FsQuiescenceOracle:
    """Model the one-lock enqueue/dequeue/busy/quiescence cut."""

    def __init__(self) -> None:
        self.open = True
        self.queue: list[tuple[str, int, int]] = []
        self.busy: tuple[str, int, int] | None = None
        self.epoch = 4
        self.generation = 12
        self.vfs_started = False
        self.published = False

    def enqueue(self, opcode: str) -> bool:
        if not self.open:
            return False
        self.queue.append((opcode, self.generation, self.epoch))
        return True

    def dequeue_and_mark_busy(self) -> tuple[str, int, int] | None:
        # The queue pop and busy transition are one synchronization action.
        if not self.open or not self.queue:
            return None
        self.busy = self.queue.pop(0)
        return self.busy

    def quiesce_try(self) -> bool:
        self.open = False
        if self.busy is not None or self.queue:
            self.open = True
            return False
        return True

    def invalidate(self) -> None:
        self.open = False
        self.epoch += 1
        self.generation += 1

    def item_valid(self, item: tuple[str, int, int]) -> bool:
        return item[1:] == (self.generation, self.epoch)

    def vfs_begin(self, item: tuple[str, int, int]) -> bool:
        if not self.item_valid(item):
            return False
        self.vfs_started = True
        return True

    def vfs_finish_and_publish(self, item: tuple[str, int, int]) -> bool:
        # One already-started atomic call may finish, but its post-check gates
        # every publish and any subsequent operation.
        self.published = self.item_valid(item)
        self.busy = None
        return self.published


class SoftRebootOracle:
    """Freeze the response-first commit cut and its three failure outcomes."""

    def __init__(self) -> None:
        self.fs_open = True
        self.admission_open = True
        self.response_submitted = False
        self.timer_armed = False
        self.pending = False
        self.worker_stopped = False

    def attempt(self, *, fs_idle: bool, tx_ok: bool, timer_ok: bool) -> str:
        self.fs_open = False
        if not fs_idle:
            self.fs_open = True
            return "EBUSY"
        self.admission_open = False
        if not tx_ok:
            self.fs_open = True
            self.admission_open = True
            return "TX_REFUSED"

        self.response_submitted = True
        self.pending = True
        if not timer_ok:
            raise ForcedRestart("accepted reset timer-arm failure")
        self.timer_armed = True
        self.worker_stopped = True
        return "ACCEPTED"


class FrozenLifecycleInterleavingTests(unittest.TestCase):
    def test_passed_gate_handlers_leave_before_wrapper_detaches(self):
        for effect in (
            "RUN semaphore give",
            "STOP worker pointer read",
            "SOFT timer arm",
            "console enqueue",
            "filesystem enqueue",
        ):
            with self.subTest(effect=effect):
                model = VmLifecycleOracle()
                token = model.enter("complete-CMD")
                self.assertIsNotNone(token)
                model.begin_wrapper(100)
                self.assertFalse(model.activity_drained(2599))
                model.effect(token, effect)
                model.leave(token)
                self.assertTrue(model.activity_drained(2599))
                self.assertEqual(model.effects, [effect])

    def test_activity_underflow_overflow_and_deadline_restart(self):
        model = VmLifecycleOracle()
        with self.assertRaisesRegex(ForcedRestart, "underflow"):
            model.leave(ActivityToken(1, model.epoch, "forged"))

        model = VmLifecycleOracle()
        model.activity_count_override = model.MAX_ACTIVITY
        with self.assertRaisesRegex(ForcedRestart, "overflow"):
            model.enter("one-too-many")

        model = VmLifecycleOracle()
        self.assertIsNotNone(model.enter("stuck-callback"))
        model.begin_wrapper(50)
        self.assertFalse(model.activity_drained(2549))
        with self.assertRaisesRegex(ForcedRestart, "deadline"):
            model.activity_drained(2550)

    def test_wrapper_holds_tx_through_real_deinit(self):
        model = VmLifecycleOracle()
        model.begin_wrapper(0)
        self.assertTrue(model.activity_drained(0))
        self.assertTrue(model.acquire_tx())
        self.assertFalse(model.worker_try_tx())
        model.detach_and_real_deinit()
        self.assertEqual(model.tx_owner, "wrapper")
        model.release_tx_after_real()
        self.assertFalse(model.worker_try_tx(), "deleted worker cannot reacquire TX")

    def test_inactive_and_fired_timer_disarm_are_success(self):
        for state in ("inactive", "already-fired", "stopped"):
            with self.subTest(state=state):
                model = VmLifecycleOracle()
                model.disarm_timer(state)
                self.assertFalse(model.soft_pending)
                self.assertIsNone(model.soft_armed_epoch)
        with self.assertRaises(ForcedRestart):
            VmLifecycleOracle().disarm_timer("driver-error")

    def test_closing_session_restarts_at_both_lifecycle_seams(self):
        model = VmLifecycleOracle()
        model.closing = True
        with self.assertRaisesRegex(ForcedRestart, "CLOSING"):
            model.begin_wrapper(0)

        model = VmLifecycleOracle()
        model.old_tasks_alive = False
        model.closing = True
        with self.assertRaisesRegex(ForcedRestart, "CLOSING"):
            model.port_init()

    def test_both_custom_roots_are_cleared_before_and_after_vm_init(self):
        model = VmLifecycleOracle()
        model.begin_wrapper(0)
        self.assertTrue(model.acquire_tx())
        model.detach_and_real_deinit()
        self.assertEqual(model.roots, {"runner": None, "fs": None})
        model.release_tx_after_real()
        model.port_init()
        self.assertEqual(model.roots, {"runner": None, "fs": None})

    def test_response_peek_cannot_cross_wrapper_recycle(self):
        model = VmLifecycleOracle()
        peeked = model.response_peek()
        self.assertIsNotNone(peeked)
        token, frame = peeked
        model.begin_wrapper(0)
        self.assertFalse(model.activity_drained(0))
        self.assertFalse(model.response_resume(token, frame))
        self.assertTrue(model.activity_drained(0))
        self.assertIsNone(model.response_peek(), "queued kick is inert while closed")

        self.assertTrue(model.acquire_tx())
        model.detach_and_real_deinit()
        model.release_tx_after_real()
        model.port_init()
        model.ready()
        fresh = model.response_peek()
        self.assertIsNotNone(fresh)
        self.assertEqual(fresh[1], "new-frame")

    def test_rx_first_paused_before_reset_cannot_resume_into_fresh_run(self):
        rx = RxLifecycleOracle()
        first = rx.begin_fragment(
            first=True,
            last=False,
            index=0,
            data=b"old-prefix",
        )
        self.assertIsNotNone(first)
        self.assertTrue(rx.active_run)
        self.assertEqual(bytes(rx.buffer), b"old-prefix")

        rx.close()
        self.assertFalse(
            rx.reset_if_drained(),
            "reset must not clear state beneath the entered FIRST callback",
        )
        rx.finish_fragment(first, last=False)
        self.assertTrue(rx.reset_if_drained())
        rx.ready()

        last = rx.begin_fragment(
            first=False,
            last=True,
            index=1,
            data=b"fresh-suffix",
        )
        self.assertIsNotNone(last)
        rx.finish_fragment(last, last=True)
        self.assertEqual(rx.dispatches, [])
        self.assertFalse(rx.active_run)
        self.assertEqual(rx.buffer, b"")

    def test_rx_first_while_closed_cannot_pair_with_last_after_ready(self):
        rx = RxLifecycleOracle()
        rx.close()
        self.assertTrue(rx.reset_if_drained())
        self.assertIsNone(
            rx.begin_fragment(
                first=True,
                last=False,
                index=0,
                data=b"closed-prefix",
            )
        )
        self.assertFalse(rx.active_run)
        self.assertEqual(rx.buffer, b"")

        rx.ready()
        last = rx.begin_fragment(
            first=False,
            last=True,
            index=1,
            data=b"fresh-suffix",
        )
        self.assertIsNotNone(last)
        rx.finish_fragment(last, last=True)
        self.assertEqual(rx.dispatches, [])
        self.assertFalse(rx.active_run)
        self.assertEqual(rx.buffer, b"")

    def test_rx_activity_remains_held_through_complete_dispatch(self):
        rx = RxLifecycleOracle()
        only = rx.begin_fragment(
            first=True,
            last=True,
            index=0,
            data=b"complete",
        )
        self.assertIsNotNone(only)
        rx.finish_fragment(only, last=True)
        self.assertEqual(rx.dispatches, [b"complete"])
        self.assertEqual(rx.activity_at_dispatch, [1])
        self.assertEqual(rx.callbacks, {})

    def test_fs_pop_busy_and_quiescence_are_one_cut_including_put_data(self):
        for opcode in ("FILE_LIST", "FILE_PUT_DATA"):
            with self.subTest(opcode=opcode):
                fs = FsQuiescenceOracle()
                self.assertTrue(fs.enqueue(opcode))
                item = fs.dequeue_and_mark_busy()
                self.assertIsNotNone(item)
                self.assertEqual(fs.busy, item)
                self.assertFalse(fs.quiesce_try())
                self.assertTrue(fs.open)

        fs = FsQuiescenceOracle()
        self.assertTrue(fs.quiesce_try())
        self.assertFalse(fs.enqueue("FILE_PUT_DATA"))
        self.assertIsNone(fs.dequeue_and_mark_busy())

    def test_started_vfs_may_finish_but_cannot_publish_after_invalidation(self):
        fs = FsQuiescenceOracle()
        self.assertTrue(fs.enqueue("FILE_PUT_DATA"))
        item = fs.dequeue_and_mark_busy()
        self.assertTrue(fs.vfs_begin(item))
        fs.invalidate()
        self.assertFalse(fs.vfs_finish_and_publish(item))
        self.assertFalse(fs.published)

    def test_soft_reboot_response_is_the_irreversible_commit_cut(self):
        busy = SoftRebootOracle()
        self.assertEqual(
            busy.attempt(fs_idle=False, tx_ok=True, timer_ok=True), "EBUSY"
        )
        self.assertTrue(busy.fs_open)
        self.assertTrue(busy.admission_open)
        self.assertFalse(busy.response_submitted)
        self.assertFalse(busy.timer_armed)

        tx_refused = SoftRebootOracle()
        self.assertEqual(
            tx_refused.attempt(fs_idle=True, tx_ok=False, timer_ok=True),
            "TX_REFUSED",
        )
        self.assertTrue(tx_refused.fs_open)
        self.assertTrue(tx_refused.admission_open)
        self.assertFalse(tx_refused.timer_armed)

        timer_failed = SoftRebootOracle()
        with self.assertRaisesRegex(ForcedRestart, "timer-arm"):
            timer_failed.attempt(fs_idle=True, tx_ok=True, timer_ok=False)
        self.assertTrue(timer_failed.response_submitted)
        self.assertFalse(timer_failed.fs_open)
        self.assertFalse(timer_failed.admission_open)

        accepted = SoftRebootOracle()
        self.assertEqual(
            accepted.attempt(fs_idle=True, tx_ok=True, timer_ok=True),
            "ACCEPTED",
        )
        self.assertTrue(accepted.pending)
        self.assertTrue(accepted.timer_armed)
        self.assertTrue(accepted.worker_stopped)


class NativeVmLifecycleContractTests(unittest.TestCase):
    def test_pinned_esp_wrapper_entry_owns_the_micro_python_gil(self):
        self.assertRegex(
            ESP_CONFIG,
            r"#define\s+MICROPY_PY_THREAD_GIL\s+\(1\)",
        )
        ordered(self, ESP_MAIN, "mp_init();", "mp_thread_deinit();", "mp_deinit();")
        mp_init = code_only(c_function(MP_RUNTIME, "mp_init"))
        mp_deinit = code_only(c_function(MP_RUNTIME, "mp_deinit"))
        self.assertIn("MP_THREAD_GIL_ENTER", mp_init)
        self.assertIn("MP_THREAD_GIL_EXIT", mp_deinit)

    def test_lifecycle_module_is_built_with_forced_linker_wrap(self):
        self.assertTrue(VM_C, "add pble_vm_lifecycle.c")
        self.assertTrue(VM_H, "add pble_vm_lifecycle.h")
        self.assertIn("pble_vm_lifecycle.c", CMAKE)
        self.assertIn("target_link_options", CMAKE)
        self.assertIn("--wrap=mp_thread_deinit", CMAKE)
        self.assertIn("--undefined=__wrap_mp_thread_deinit", CMAKE)

    def test_release_build_proves_wrapper_and_port_hook_symbols(self):
        self.assertTrue(LINK_GATE, "add the map/nm lifecycle linkage verifier")
        self.assertIn("verify_vm_lifecycle_linkage.py", BUILD)
        for token in (
            "micropython.map",
            "nm",
            "__wrap_mp_thread_deinit",
            "pble_vm_epoch_begin",
        ):
            with self.subTest(token=token):
                self.assertIn(token, BUILD + LINK_GATE)
        for target in ESP_TARGETS:
            with self.subTest(target=target):
                self.assertIn(target, LINK_GATE)

    def test_every_esp_overlay_binds_port_init_to_epoch_begin(self):
        for target in ESP_TARGETS:
            header = source(OVERLAYS / target / "mpconfigboard.h")
            with self.subTest(target=target):
                self.assertIn('#include "pble_vm_lifecycle.h"', header)
                self.assertRegex(
                    header,
                    r"#define\s+MICROPY_PORT_INIT_FUNC\s+"
                    r"pble_vm_epoch_begin\s*\(\s*\)",
                )

    def test_boot_opens_ready_last_after_workers_dupterm_and_autorun(self):
        for target in ESP_TARGETS:
            boot = source(OVERLAYS / target / "_boot.py")
            tree = ast.parse(boot)
            calls = [
                (dotted_name(node.func), node.lineno)
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
            ]
            by_name: dict[str, list[int]] = {}
            for name, line in calls:
                by_name.setdefault(name, []).append(line)
            with self.subTest(target=target):
                self.assertEqual(len(by_name.get("pble_ble.vm_ready", [])), 1)
                runner = next(
                    line
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and dotted_name(node.func) == "_thread.start_new_thread"
                    and node.args
                    and dotted_name(node.args[0]) == "pble_runner.worker"
                    for line in (node.lineno,)
                )
                fs = next(
                    line
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and dotted_name(node.func) == "_thread.start_new_thread"
                    and node.args
                    and dotted_name(node.args[0]) == "pble_fs.worker"
                    for line in (node.lineno,)
                )
                sequence = (
                    by_name["pble_ble.init_agent"][0],
                    runner,
                    fs,
                    by_name["os.dupterm"][0],
                    by_name["pble_boot.maybe_autorun"][0],
                    by_name["pble_ble.vm_ready"][0],
                )
                self.assertEqual(sequence, tuple(sorted(sequence)))

    def test_wrapper_drains_then_holds_tx_across_exact_upstream_deinit(self):
        wrapper = code_only(c_function(VM_C, "__wrap_mp_thread_deinit"))
        pre = code_only(c_function(VM_C, "pble_vm_epoch_pre_deinit"))
        post = code_only(c_function(VM_C, "pble_vm_epoch_post_deinit"))
        self.assertTrue(wrapper)
        ordered(
            self,
            wrapper,
            "pble_vm_epoch_pre_deinit",
            "__real_mp_thread_deinit",
            "pble_vm_epoch_post_deinit",
        )
        self.assertNotIn("MP_THREAD_GIL_EXIT", wrapper + pre + post)
        self.assertRegex(
            VM_C,
            r"#\s*define\s+PBLE_VM_DEINIT_BUDGET_MS\s+2500(?:[uUlL]*)\b",
        )
        for token in (
            "pble_vm_close_admission",
            "pble_vm_wait_activity_idle",
            "pble_runner_vm_timer_disarm",
            "pble_dc_vm_timer_disarm",
            "pble_ble_vm_stop_response_callout",
            "pble_ble_vm_tx_lock",
            "pble_runner_vm_detach",
            "pble_console_vm_detach",
            "MP_STATE_VM(pble_runner_sysexit) = MP_OBJ_NULL",
            "MP_STATE_VM(pble_fs_put_file) = MP_OBJ_NULL",
        ):
            with self.subTest(token=token):
                self.assertIn(token, pre)
        self.assertIn("pble_ble_vm_tx_unlock", post)
        self.assertNotIn("pble_ble_vm_tx_unlock", pre)
        for allocation in ("malloc(", "calloc(", "m_new(", "xSemaphoreCreate"):
            self.assertNotIn(allocation, wrapper + pre + post)

    def test_lifecycle_counter_is_bounded_and_fails_closed(self):
        enter = code_only(c_function(VM_C, "pble_vm_dispatch_enter"))
        leave = code_only(c_function(VM_C, "pble_vm_dispatch_leave"))
        wait = code_only(c_function(VM_C, "pble_vm_wait_activity_idle"))
        self.assertIn("UINT32_MAX", enter)
        self.assertIn("esp_restart", enter)
        self.assertRegex(leave, r"(?:==|<=)\s*0")
        self.assertIn("esp_restart", leave)
        self.assertIn("PBLE_VM_DEINIT_BUDGET_MS", wait)
        self.assertIn("esp_timer_get_time", wait)
        self.assertIn("esp_restart", wait)

    def test_complete_command_dispatch_has_one_lifecycle_guard(self):
        outer = code_only(c_function(PROTO, "pble_proto_dispatch"))
        inner = code_only(c_function(PROTO, "pble_proto_dispatch_admitted"))
        self.assertTrue(inner, "move all complete-CMD effects into admitted helper")
        ordered(
            self,
            outer,
            "pble_vm_dispatch_enter",
            "pble_proto_dispatch_admitted",
            "pble_vm_dispatch_leave",
        )
        for effect in (
            "PBLE_HANDLER_NO_RESPONSE",
            "PBLE_HANDLER_SPECIAL",
            "special_handler(",
            "deferred(",
            "h(&f",
        ):
            with self.subTest(effect=effect):
                self.assertIn(effect, inner)
                self.assertNotIn(effect, outer)

    def test_rx_callback_enters_before_copy_and_leaves_after_dispatch(self):
        callback = code_only(c_function(BLE, "pble_rx_access"))
        self.assertTrue(callback)
        ordered(
            self,
            callback,
            "pble_vm_callback_enter",
            "OS_MBUF_PKTLEN",
            "ble_hs_mbuf_to_flat",
            "pble_rx_ingest",
        )
        self.assertGreater(
            callback.rfind("pble_vm_callback_leave"),
            callback.find("pble_rx_ingest"),
            "the RX activity must cover reassembly and complete-CMD dispatch",
        )
        entry_pos = callback.find("pble_vm_callback_enter")
        read_pos = callback.find("OS_MBUF_PKTLEN")
        refusal_cut = callback[entry_pos:read_pos]
        refused = re.search(
            r"if\s*\([^)]*\)\s*\{(?P<body>.*?)\}",
            refusal_cut,
            re.DOTALL,
        )
        self.assertIsNotNone(refused)
        self.assertIn("pble_ble_vm_rx_reset", refused.group("body"))
        self.assertRegex(refused.group("body"), r"\breturn\b")
        for blocking in ("portMAX_DELAY", "vTaskDelay", "ulTaskNotifyTake"):
            with self.subTest(blocking=blocking):
                self.assertNotIn(blocking, callback)

    def test_vm_reset_reuses_rx_clear_after_fragment_activity_drains(self):
        reset = code_only(c_function(BLE, "pble_ble_vm_reset"))
        rx_reset = code_only(c_function(BLE, "pble_ble_vm_rx_reset"))
        pre_deinit = code_only(c_function(VM_C, "pble_vm_epoch_pre_deinit"))
        self.assertTrue(rx_reset, "add one synchronized RX reset transaction")
        self.assertIn("pble_reset_reassembly", rx_reset)
        self.assertIn("pble_ble_vm_rx_reset", reset)
        ordered(
            self,
            pre_deinit,
            "pble_vm_close_admission",
            "pble_vm_wait_activity_idle",
        )

    def test_timer_callbacks_are_epoch_guarded_and_disarm_is_idempotent(self):
        soft_cb = code_only(c_function(RUNNER, "soft_reboot_timer_cb"))
        blink_cb = code_only(c_function(DEVICE_CONFIG, "dc_blink_cb"))
        ordered(
            self,
            soft_cb,
            "pble_vm_callback_enter",
            "MP_STATE_VM(pble_runner_sysexit)",
            "pble_vm_callback_leave",
        )
        ordered(
            self,
            blink_cb,
            "pble_vm_callback_enter",
            "dc_led_write",
            "pble_vm_callback_leave",
        )
        soft_disarm = code_only(
            c_function(RUNNER, "pble_runner_vm_timer_disarm")
        )
        identify_disarm = code_only(
            c_function(DEVICE_CONFIG, "pble_dc_vm_timer_disarm")
        )
        for body in (soft_disarm, identify_disarm):
            self.assertIn("ESP_ERR_INVALID_STATE", body)
        self.assertIn("g_soft_reboot_pending = false", soft_disarm)
        self.assertIn("g_soft_reboot_epoch = 0", soft_disarm)

    def test_static_response_kick_fresh_peeks_under_lifecycle_activity(self):
        callback = code_only(c_function(BLE, "pble_rsp_pump_callout"))
        ordered(
            self,
            callback,
            "pble_vm_callback_enter",
            "pble_rsp_tx_peek",
            "pble_rsp_submit_one",
            "pble_vm_callback_leave",
        )
        self.assertNotRegex(BLE, r"static\s+pble_rsp_tx_t\s+\w+")
        self.assertIn("pble_vm_admission_ready", callback)

    def test_closing_restarts_at_wrapper_and_port_init(self):
        guard = code_only(c_function(VM_C, "pble_vm_restart_if_closing"))
        pre = code_only(c_function(VM_C, "pble_vm_epoch_pre_deinit"))
        begin = code_only(c_function(VM_C, "pble_vm_epoch_begin"))
        self.assertIn("pble_ble_session_closing", guard)
        self.assertIn("esp_restart", guard)
        self.assertIn("pble_vm_restart_if_closing", pre)
        self.assertIn("pble_vm_restart_if_closing", begin)

    def test_epoch_begin_hard_resets_every_retained_owner_and_both_roots(self):
        begin = code_only(c_function(VM_C, "pble_vm_epoch_begin"))
        for root in ("pble_runner_sysexit", "pble_fs_put_file"):
            self.assertIn(
                "MP_STATE_VM({}) = MP_OBJ_NULL".format(root),
                begin,
            )
        for reset in (
            "pble_ble_vm_reset",
            "pble_proto_vm_reset",
            "pble_fs_vm_reset",
            "pble_runner_vm_reset",
            "pble_console_vm_reset",
        ):
            with self.subTest(reset=reset):
                self.assertIn(reset, begin)

        fs_reset = code_only(c_function(FS, "pble_fs_vm_reset"))
        for token in (
            "g_fs_admission_open = false",
            "g_fs_worker_busy = false",
            "g_fs_outstanding = 0",
            "g_fs_dequeue_claim = false",
            "xQueueReset",
        ):
            self.assertIn(token, fs_reset)

        runner_reset = code_only(c_function(RUNNER, "pble_runner_vm_reset"))
        for token in (
            "g_stop_requested = false",
            "g_soft_reboot_pending = false",
            "g_soft_reboot_epoch = 0",
            "g_worker_state = NULL",
            "pble_rsm_init",
            "xSemaphoreTake",
        ):
            self.assertIn(token, runner_reset)

        console_reset = code_only(c_function(CONSOLE, "pble_console_vm_reset"))
        for token in (
            "g_ring_head = 0",
            "g_ring_tail = 0",
            "g_ring_count = 0",
            "g_worker = NULL",
        ):
            self.assertIn(token, console_reset)

        proto_reset = code_only(c_function(PROTO, "pble_proto_vm_reset"))
        for token in (
            "s_rsp_active_slot = -1",
            "s_rsp_tx_owned = false",
            "xSemaphoreTake",
            "pble_rsp_recycle_locked",
        ):
            self.assertIn(token, proto_reset)

    def test_workers_enter_and_final_ready_requires_both(self):
        runner_worker = code_only(c_function(RUNNER, "pble_runner_worker"))
        fs_worker = code_only(c_function(FS, "pble_fs_worker"))
        self.assertIn(
            "pble_vm_worker_ready(PBLE_VM_WORKER_RUNNER)", runner_worker
        )
        self.assertIn("pble_vm_worker_ready(PBLE_VM_WORKER_FS)", fs_worker)
        ready = code_only(c_function(VM_C, "pble_vm_ready"))
        self.assertIn("PBLE_VM_WORKER_RUNNER", ready)
        self.assertIn("PBLE_VM_WORKER_FS", ready)
        self.assertIn("pble_vm_open_admission", ready)
        self.assertIn("MP_QSTR_vm_ready", BLE)


class NativeFsEpochContractTests(unittest.TestCase):
    def test_fs_items_include_put_data_session_generation_and_vm_epoch(self):
        item = re.search(
            r"typedef\s+struct\s*\{(?P<body>.*?)\}\s*pble_fs_req_t\s*;",
            FS,
            re.DOTALL,
        )
        self.assertIsNotNone(item)
        body = item.group("body")
        for field in ("conn", "generation", "vm_epoch"):
            self.assertRegex(body, rf"\b{field}\b")
        put_data = code_only(c_function(FS, "pble_fs_put_data"))
        self.assertIn("fs_enqueue", put_data)
        enqueue = code_only(c_function(FS, "fs_enqueue"))
        self.assertIn("pble_ble_session_snapshot", enqueue)
        self.assertIn("pble_vm_epoch_current", enqueue)

    def test_fs_queue_pop_and_busy_transition_share_quiescence_lock(self):
        enqueue = code_only(c_function(FS, "fs_enqueue"))
        dequeue = code_only(c_function(FS, "pble_fs_dequeue_begin"))
        quiesce = code_only(c_function(FS, "pble_fs_quiesce_try"))
        for body in (enqueue, dequeue, quiesce):
            self.assertIn("g_fs_gate", body)
        ordered(
            self,
            dequeue,
            "xSemaphoreTake(g_fs_work",
            "xSemaphoreTake(g_fs_gate",
            "xQueueReceive",
            "g_fs_dequeue_claim = true",
            "g_fs_worker_busy = true",
            "xSemaphoreGive(g_fs_gate",
        )
        ordered(
            self,
            quiesce,
            "xSemaphoreTake(g_fs_gate",
            "g_fs_admission_open = false",
            "g_fs_worker_busy",
            "uxQueueMessagesWaiting",
            "xSemaphoreGive(g_fs_gate",
        )
        self.assertIn("g_fs_admission_open = true", quiesce)

    def test_soft_reboot_quiesces_then_commits_at_accepted_rsp(self):
        soft = code_only(c_function(RUNNER, "pble_runner_soft_reboot"))
        ordered(
            self,
            soft,
            "pble_fs_quiesce_try",
            "pble_proto_emit_rsp_status_try",
            "esp_timer_start_once",
        )
        self.assertEqual(soft.count("esp_timer_start_once"), 1)
        self.assertEqual(soft.count("pble_fs_quiesce_abort"), 1)
        self.assertIn("PBLE_EBUSY", soft)
        for marker in (
            "if (tx_rc != PBLE_TX_OK)",
            "esp_restart",
            "g_stop_requested = true",
        ):
            self.assertIn(marker, soft)
        tx_failure = soft[
            soft.index("if (tx_rc != PBLE_TX_OK)") :
            soft.index("esp_timer_start_once")
        ]
        self.assertIn("pble_fs_quiesce_abort", tx_failure)
        self.assertNotIn("esp_restart", tx_failure)

        after_timer_attempt = soft[soft.index("esp_timer_start_once") :]
        restart = after_timer_attempt.index("esp_restart")
        stop_worker = after_timer_attempt.index("g_stop_requested = true")
        self.assertLess(restart, stop_worker)
        self.assertNotIn(
            "pble_fs_quiesce_abort",
            after_timer_attempt[:stop_worker],
            "accepted RSP must never reopen admission",
        )

    def test_every_vfs_dispatch_revalidates_before_and_after_effect(self):
        for name in (
            "fs_do_list",
            "fs_do_stat",
            "fs_do_get",
            "fs_do_put_begin",
            "fs_do_put_data",
            "fs_do_put_end",
            "fs_do_delete",
            "fs_do_mkdir",
            "fs_do_rename",
        ):
            body = code_only(c_function(FS, name))
            with self.subTest(function=name):
                self.assertGreaterEqual(
                    body.count("pble_fs_item_valid"),
                    2,
                    "each VFS operation/chunk needs adjacent pre/post checks",
                )

    def test_fs_data_end_and_ack_use_exact_session_event_submit(self):
        self.assertIn("pble_proto_emit_paced_for_session", PROTO_H)
        session_emit = code_only(
            c_function(PROTO, "pble_proto_emit_paced_for_session")
        )
        self.assertIn("pble_ble_notify_paced_for_session", session_emit)
        fs_emit = code_only(c_function(FS, "fs_emit_paced"))
        self.assertIn("const pble_fs_req_t *it", fs_emit)
        self.assertIn("pble_proto_emit_paced_for_session", fs_emit)
        get = code_only(c_function(FS, "fs_do_get"))
        self.assertIn("fs_emit_paced(it, PBLE_OP_FILE_GET_DATA", get)
        self.assertIn("fs_emit_paced(it, PBLE_OP_FILE_GET_END", get)
        ack = code_only(c_function(FS, "fs_put_ack"))
        self.assertIn("const pble_fs_req_t *it", ack)
        self.assertIn("fs_emit_paced(it, PBLE_OP_FILE_PUT_ACK", ack)
        put_data = code_only(c_function(FS, "fs_do_put_data"))
        self.assertIn("fs_put_ack(it)", put_data)


if __name__ == "__main__":
    unittest.main()
