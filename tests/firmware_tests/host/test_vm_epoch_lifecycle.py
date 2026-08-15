#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""RED contract for native state isolation across ESP MicroPython VMs."""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
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
MP_MODTHREAD = source(
    ROOT / "firmware" / "upstream" / "micropython" / "py" / "modthread.c"
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


def c_brace_depth(text: str, stop: int) -> int:
    """Return lexical C brace depth immediately before ``stop``."""
    depth = 0
    state = "code"
    index = 0
    while index < stop:
        char = text[index]
        nxt = text[index + 1] if index + 1 < stop else ""
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
        index += 1
    return depth


def c_function_names(text: str) -> list[str]:
    """Return only top-level source-defined C function names."""
    clean = code_only(text)
    names: list[str] = []
    for match in re.finditer(
        r"(?m)^[^\n;{}]*\b(?P<name>[A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{",
        clean,
    ):
        name = match.group("name")
        if (
            name in {"if", "for", "while", "switch"}
            or c_brace_depth(clean, match.start()) != 0
            or name in names
        ):
            continue
        if c_function(clean, name):
            names.append(name)
    return names


VFS_EFFECT_RE = re.compile(
    r"\bmp_vfs_(?:stat|open|ilistdir|remove|rmdir|mkdir|rename)\s*\("
    r"|\bmp_iternext\s*\("
    r"|(?:->|\.)\s*(?:read|write)\s*\("
    r"|\bmp_stream_close\s*\("
)
VFS_VALID_RE = re.compile(r"\bpble_fs_item_valid\s*\(")
VFS_TICKET_VALID_RE = re.compile(r"\bpble_fs_ticket_valid\s*\(")


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


@dataclass(frozen=True)
class VmSessionToken:
    conn: int
    generation: int
    epoch: int


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
        self.conn = 7
        self.generation = 41
        self.session_epoch = self.epoch
        self.session_live = True
        self.tickets = {self.current_session_token()}
        self.session_cut_held = False
        self.transitions: list[str] = []

    def current_session_token(self) -> VmSessionToken:
        return VmSessionToken(self.conn, self.generation, self.session_epoch)

    def session_token_valid(self, token: VmSessionToken) -> bool:
        return self.session_live and token == self.current_session_token()

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
        self.transitions.append("close-admission")
        self.session_live = False
        self.tickets.clear()
        self.current_response = None
        self.transitions.append("logical-invalidate")
        self.deadline_ms = now_ms + self.DEINIT_BUDGET_MS
        self.transitions.append("mint-deadline")

    def activity_drained(self, now_ms: int) -> bool:
        if self.deadline_ms is None:
            raise AssertionError("wrapper has not begun")
        if now_ms >= self.deadline_ms:
            raise ForcedRestart("activity drain deadline")
        return not self.active

    def wrapper_stage(self, stage: str, now_ms: int) -> None:
        if self.deadline_ms is None:
            raise AssertionError("wrapper has not begun")
        if now_ms >= self.deadline_ms:
            raise ForcedRestart("{} exhausted shared deadline".format(stage))

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

    def worker_try_tx(self, token: VmSessionToken | None = None) -> bool:
        token = self.current_session_token() if token is None else token
        if (
            not self.old_tasks_alive
            or self.tx_owner is not None
            or not self.session_token_valid(token)
        ):
            return False
        self.tx_owner = "old-worker"
        return True

    def attempt_termination(self) -> bool:
        if self.tx_owner is not None or self.session_cut_held:
            return False
        self.closing = True
        return True

    def port_init(self, during_cut: object | None = None) -> None:
        if self.old_tasks_alive:
            raise AssertionError("port init precedes old-task deletion")
        if self.tx_owner is not None:
            raise AssertionError("port init requires sole TX ownership")
        self.tx_owner = "port-init"
        self.transitions.append("take-tx")
        self.session_cut_held = True
        try:
            if self.closing:
                raise ForcedRestart("CLOSING cannot rotate open")
            if callable(during_cut):
                during_cut()
            if self.closing:
                raise ForcedRestart("CLOSING cannot rotate open")
            self.epoch += 1
            self.generation += 1
            if self.generation == 0:
                self.generation += 1
            self.session_epoch = self.epoch
            self.session_live = True
            self.transitions.append("rotate-session")
            self.tickets.clear()
            self.current_response = None
            self.transitions.append("recycle-response-pool")
            self.roots = {"runner": None, "fs": None}
            self.open = False
        finally:
            self.session_cut_held = False
            self.transitions.append("release-tx")
            self.tx_owner = None

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


@dataclass(frozen=True)
class RxRefusalCut:
    epoch: int


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
        self.refusal_cut: RxRefusalCut | None = None

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

    def begin_refused_fragment(self) -> RxRefusalCut:
        if self.open or self.refusal_cut is not None:
            raise AssertionError("refusal requires one closed lifecycle cut")
        self.refusal_cut = RxRefusalCut(self.epoch)
        return self.refusal_cut

    def finish_refused_fragment(self, cut: RxRefusalCut) -> None:
        if self.refusal_cut != cut:
            raise AssertionError("refusal no longer owns the lifecycle cut")
        if not self.open and self.epoch == cut.epoch:
            self._clear_run()
        self.refusal_cut = None

    def reset_if_drained(self) -> bool:
        if self.callbacks:
            return False
        self._clear_run()
        self.epoch += 1
        return True

    def ready(self) -> bool:
        if self.refusal_cut is not None:
            return False
        self.open = True
        return True


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
        self.gate_held = False

    def enqueue(self, opcode: str) -> bool:
        if self.gate_held or not self.open:
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
        if self.gate_held:
            return False
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
        self.lifecycle_open = True
        self.non_reboot_open = True
        self.response_submitted = False
        self.timer_armed = False
        self.pending = False
        self.reset_scheduled = False
        self.worker_stopped = False
        self.effects: list[str] = []

    def attempt(self, *, fs_idle: bool, tx_ok: bool, timer_ok: bool) -> str:
        if not self.lifecycle_open:
            return "DROP"
        if self.pending or not self.non_reboot_open:
            return "EBUSY"
        self.fs_open = False
        if not fs_idle:
            self.fs_open = True
            return "EBUSY"
        self.non_reboot_open = False
        if not tx_ok:
            self.fs_open = True
            self.non_reboot_open = True
            return "TX_REFUSED"

        self.response_submitted = True
        self.pending = True
        if not timer_ok:
            raise ForcedRestart("accepted reset timer-arm failure")
        self.timer_armed = True
        self.worker_stopped = True
        return "ACCEPTED"

    def dispatch(self, opcode: str, *, response_bearing: bool = True) -> str:
        if not self.lifecycle_open:
            return "DROP"
        if opcode == "SOFT_REBOOT" and self.pending:
            return "EBUSY"
        if opcode != "SOFT_REBOOT" and not self.non_reboot_open:
            return "EBUSY" if response_bearing else "DROP"
        self.effects.append(opcode)
        return "ADMITTED"

    def timer_fire(self) -> None:
        if not self.pending or not self.timer_armed:
            return
        self.timer_armed = False
        self.reset_scheduled = True

    def wrapper_close(self) -> None:
        self.lifecycle_open = False


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

        drained = VmLifecycleOracle()
        drained.begin_wrapper(50)
        with self.assertRaisesRegex(ForcedRestart, "deadline"):
            drained.activity_drained(2550)

    def test_every_wrapper_stage_consumes_one_absolute_deadline(self):
        model = VmLifecycleOracle()
        model.begin_wrapper(100)
        self.assertEqual(model.deadline_ms, 2600)
        for stage, now_ms in (
            ("activity drain", 200),
            ("soft timer disarm", 1200),
            ("identify timer disarm", 1800),
            ("response callout stop", 2300),
            ("TX lock", 2599),
        ):
            model.wrapper_stage(stage, now_ms)
            self.assertEqual(model.deadline_ms, 2600)
        with self.assertRaisesRegex(ForcedRestart, "shared deadline"):
            model.wrapper_stage("TX lock", 2600)

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

    def test_wrapper_logical_cut_precedes_deadline_and_blocks_old_worker_tx(self):
        model = VmLifecycleOracle()
        old_token = model.current_session_token()
        self.assertTrue(model.session_token_valid(old_token))
        self.assertIn(old_token, model.tickets)

        model.begin_wrapper(100)

        self.assertEqual(
            model.transitions,
            ["close-admission", "logical-invalidate", "mint-deadline"],
        )
        self.assertFalse(model.session_token_valid(old_token))
        self.assertNotIn(old_token, model.tickets)
        self.assertFalse(
            model.worker_try_tx(old_token),
            "an old off-GIL worker must not start TX while wrapper waits",
        )
        self.assertEqual(model.deadline_ms, 2600)

    def test_port_init_rotation_is_one_tx_session_cut(self):
        model = VmLifecycleOracle()
        model.old_tasks_alive = False
        old_token = model.current_session_token()
        attempted: list[bool] = []

        model.port_init(
            during_cut=lambda: attempted.append(model.attempt_termination())
        )

        new_token = model.current_session_token()
        self.assertEqual(attempted, [False])
        self.assertNotEqual(new_token.epoch, old_token.epoch)
        self.assertNotEqual(new_token.generation, old_token.generation)
        self.assertNotEqual(new_token.generation, 0)
        self.assertFalse(model.session_token_valid(old_token))
        self.assertTrue(model.session_token_valid(new_token))
        self.assertFalse(model.tickets, "old response tickets survive rotation")
        self.assertEqual(
            model.transitions,
            [
                "take-tx",
                "rotate-session",
                "recycle-response-pool",
                "release-tx",
            ],
        )
        self.assertIsNone(model.tx_owner)
        self.assertFalse(model.session_cut_held)

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

    def test_paused_rx_refusal_cannot_clear_a_fresh_epoch_first(self):
        rx = RxLifecycleOracle()
        rx.close()
        self.assertTrue(rx.reset_if_drained())

        refused = rx.begin_refused_fragment()
        self.assertFalse(
            rx.ready(),
            "final readiness cannot pass a refusal holding the lifecycle cut",
        )
        rx.finish_refused_fragment(refused)
        self.assertTrue(rx.ready())

        first = rx.begin_fragment(
            first=True,
            last=False,
            index=0,
            data=b"fresh-prefix",
        )
        self.assertIsNotNone(first)
        rx.finish_fragment(first, last=False)
        last = rx.begin_fragment(
            first=False,
            last=True,
            index=1,
            data=b"-suffix",
        )
        self.assertIsNotNone(last)
        rx.finish_fragment(last, last=True)
        self.assertEqual(rx.dispatches, [b"fresh-prefix-suffix"])

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

        contended = FsQuiescenceOracle()
        contended.gate_held = True
        self.assertFalse(contended.enqueue("FILE_LIST"))
        self.assertFalse(contended.enqueue("FILE_PUT_DATA"))
        self.assertFalse(contended.quiesce_try())
        self.assertTrue(contended.open)
        self.assertEqual(contended.queue, [])

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
        self.assertTrue(busy.lifecycle_open)
        self.assertTrue(busy.non_reboot_open)
        self.assertFalse(busy.response_submitted)
        self.assertFalse(busy.timer_armed)

        tx_refused = SoftRebootOracle()
        self.assertEqual(
            tx_refused.attempt(fs_idle=True, tx_ok=False, timer_ok=True),
            "TX_REFUSED",
        )
        self.assertTrue(tx_refused.fs_open)
        self.assertTrue(tx_refused.lifecycle_open)
        self.assertTrue(tx_refused.non_reboot_open)
        self.assertFalse(tx_refused.timer_armed)

        timer_failed = SoftRebootOracle()
        with self.assertRaisesRegex(ForcedRestart, "timer-arm"):
            timer_failed.attempt(fs_idle=True, tx_ok=True, timer_ok=False)
        self.assertTrue(timer_failed.response_submitted)
        self.assertFalse(timer_failed.fs_open)
        self.assertTrue(timer_failed.lifecycle_open)
        self.assertFalse(timer_failed.non_reboot_open)

        accepted = SoftRebootOracle()
        self.assertEqual(
            accepted.attempt(fs_idle=True, tx_ok=True, timer_ok=True),
            "ACCEPTED",
        )
        self.assertTrue(accepted.pending)
        self.assertTrue(accepted.timer_armed)
        self.assertTrue(accepted.worker_stopped)

    def test_soft_reboot_grace_refuses_non_reboot_but_routes_duplicate(self):
        accepted = SoftRebootOracle()
        self.assertEqual(
            accepted.attempt(fs_idle=True, tx_ok=True, timer_ok=True),
            "ACCEPTED",
        )
        self.assertTrue(accepted.lifecycle_open)
        self.assertFalse(accepted.non_reboot_open)

        self.assertEqual(accepted.dispatch("RUN"), "EBUSY")
        self.assertEqual(
            accepted.dispatch("CONSOLE_INPUT", response_bearing=False),
            "DROP",
        )
        self.assertEqual(accepted.dispatch("SOFT_REBOOT"), "EBUSY")
        self.assertEqual(accepted.effects, [])

        accepted.timer_fire()
        self.assertTrue(accepted.reset_scheduled)
        self.assertTrue(
            accepted.pending,
            "the committed closure, not the fired timer, ends duplicate EBUSY",
        )
        self.assertEqual(accepted.dispatch("SOFT_REBOOT"), "EBUSY")
        self.assertFalse(accepted.non_reboot_open)
        self.assertFalse(accepted.fs_open)

        accepted.wrapper_close()
        self.assertEqual(accepted.dispatch("SOFT_REBOOT"), "DROP")


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
                self.assertNotIn('#include "pble_vm_lifecycle.h"', header)
                self.assertRegex(
                    header,
                    r"(?m)^void\s+pble_vm_epoch_begin\s*\(\s*void\s*\)\s*;",
                )
                self.assertRegex(
                    header,
                    r"#define\s+MICROPY_PORT_INIT_FUNC\s+"
                    r"pble_vm_epoch_begin\s*\(\s*\)",
                )

    def test_every_esp_overlay_header_preprocesses_without_usermod_include_path(self):
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler, "host C preprocessor is required")
        probe = '#include "mpconfigboard.h"\n'
        for target in ESP_TARGETS:
            with self.subTest(target=target):
                completed = subprocess.run(
                    [
                        compiler,
                        "-E",
                        "-P",
                        "-I",
                        str(OVERLAYS / target),
                        "-x",
                        "c",
                        "-",
                    ],
                    input=probe,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    "sibling IDF component preprocessing failed:\n"
                    + completed.stderr,
                )
                self.assertIn("void pble_vm_epoch_begin(void);", completed.stdout)

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
        ordered(
            self,
            pre,
            "pble_vm_close_admission",
            "deadline_us",
            "pble_vm_wait_activity_idle",
            "pble_runner_vm_timer_disarm",
            "pble_dc_vm_timer_disarm",
            "pble_ble_vm_stop_response_callout",
            "pble_ble_vm_tx_lock",
        )
        self.assertEqual(
            pre.count("PBLE_VM_DEINIT_BUDGET_MS"),
            1,
            "the wrapper must mint its 2500 ms deadline exactly once",
        )
        self.assertIn("esp_timer_get_time", pre)
        for helper in (
            "pble_vm_wait_activity_idle",
            "pble_runner_vm_timer_disarm",
            "pble_dc_vm_timer_disarm",
            "pble_ble_vm_stop_response_callout",
            "pble_ble_vm_tx_lock",
        ):
            with self.subTest(deadline_helper=helper):
                self.assertRegex(
                    pre,
                    rf"\b{helper}\s*\([^;]*\bdeadline_us\b[^;]*\)",
                    "every quiescence helper must consume the shared deadline",
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

        helper_sources = {
            "pble_vm_wait_activity_idle": VM_C,
            "pble_runner_vm_timer_disarm": RUNNER,
            "pble_dc_vm_timer_disarm": DEVICE_CONFIG,
            "pble_ble_vm_stop_response_callout": BLE,
            "pble_ble_vm_tx_lock": BLE,
        }
        for helper, helper_source in helper_sources.items():
            body = code_only(c_function(helper_source, helper))
            signature, _brace, implementation = body.partition("{")
            with self.subTest(residual_deadline_helper=helper):
                self.assertTrue(body, "missing shared-deadline helper")
                self.assertRegex(signature, r"\bdeadline_us\b")
                self.assertRegex(
                    implementation,
                    r"(?:\besp_timer_get_time\s*\("
                    r"|\b[A-Za-z_]\w*deadline[A-Za-z_]\w*\s*\("
                    r"[^;]*\bdeadline_us\b)",
                    "helper must derive a residual from the supplied deadline",
                )
                for forbidden in (
                    "portMAX_DELAY",
                    "PBLE_VM_DEINIT_BUDGET_MS",
                    "PBLE_VM_READY_BUDGET_MS",
                ):
                    self.assertNotIn(forbidden, implementation)
                self.assertNotRegex(
                    implementation,
                    r"\b2500(?:[uUlL]*)\b",
                    "a helper must not mint a fresh wrapper budget",
                )

    def test_tx_lock_residual_uses_one_pre_acquire_clock_sample(self):
        tx_lock = code_only(c_function(BLE, "pble_ble_vm_tx_lock"))
        take = tx_lock.find("xSemaphoreTakeRecursive(pble_tx_mutex")
        self.assertGreaterEqual(take, 0)
        before_take = tx_lock[:take]
        now = re.search(
            r"\bint64_t\s+(?P<name>[A-Za-z_]\w*)\s*=\s*"
            r"esp_timer_get_time\s*\(\s*\)\s*;",
            before_take,
        )
        self.assertIsNotNone(
            now,
            "sample one pre-acquire instant before deriving the residual",
        )
        now_name = now.group("name")
        self.assertEqual(
            before_take.count("esp_timer_get_time()"),
            1,
            "a second pre-acquire sample can cross into a negative residual",
        )
        expired = re.search(
            rf"\b{re.escape(now_name)}\s*>=\s*deadline_us\b",
            before_take,
        )
        residual = re.search(
            rf"\bint64_t\s+[A-Za-z_]\w*\s*=\s*"
            rf"deadline_us\s*-\s*{re.escape(now_name)}\s*;",
            before_take,
        )
        self.assertIsNotNone(expired, "deadline equality is already expired")
        self.assertIsNotNone(residual)
        self.assertLess(now.start(), expired.start())
        self.assertLess(expired.start(), residual.start())
        self.assertRegex(
            tx_lock[take:],
            r"esp_timer_get_time\s*\(\s*\)\s*>=\s*deadline_us",
            "a successful semaphore take still needs a post-acquire check",
        )

    def test_every_shared_deadline_helper_rejects_exact_boundary(self):
        wait = code_only(c_function(VM_C, "pble_vm_wait_activity_idle"))
        expired = re.search(
            r"esp_timer_get_time\s*\(\s*\)\s*>=\s*deadline_us",
            wait,
        )
        idle = re.search(r"\bif\s*\(\s*count\s*==\s*0\s*\)", wait)
        self.assertIsNotNone(expired)
        self.assertIsNotNone(idle)
        self.assertLess(
            expired.start(),
            idle.start(),
            "an empty activity set at the exact deadline is still expired",
        )

        for helper, helper_source in (
            ("pble_runner_vm_timer_disarm", RUNNER),
            ("pble_dc_vm_timer_disarm", DEVICE_CONFIG),
            ("pble_ble_vm_stop_response_callout", BLE),
        ):
            body = code_only(c_function(helper_source, helper))
            with self.subTest(inclusive_deadline_helper=helper):
                self.assertRegex(
                    body,
                    r"\bif\s*\(\s*esp_timer_get_time\s*\(\s*\)\s*"
                    r">=\s*deadline_us\s*\)",
                )
                self.assertRegex(
                    body,
                    r"\breturn\s+esp_timer_get_time\s*\(\s*\)\s*"
                    r"<\s*deadline_us\s*;",
                )
                self.assertNotRegex(body, r"\breturn\b[^;]*<=\s*deadline_us")

    def test_wrapper_invalidates_logically_before_minting_shared_deadline(self):
        pre = code_only(c_function(VM_C, "pble_vm_epoch_pre_deinit"))
        invalidate = code_only(
            c_function(BLE, "pble_ble_vm_invalidate_session")
        )
        ordered(
            self,
            pre,
            "pble_vm_close_admission",
            "pble_ble_vm_invalidate_session",
            "deadline_us",
            "pble_vm_wait_activity_idle",
            "pble_runner_vm_timer_disarm",
            "pble_dc_vm_timer_disarm",
            "pble_ble_vm_stop_response_callout",
            "pble_ble_vm_tx_lock",
        )
        close = pre.index("pble_vm_close_admission")
        deadline = pre.index("deadline_us", close)
        pre_deadline_cut = pre[close:deadline]
        for blocking in (
            "portMAX_DELAY",
            "vTaskDelay",
            "ulTaskNotifyTake",
            "pble_ble_vm_tx_lock",
        ):
            with self.subTest(pre_deadline_blocking=blocking):
                self.assertNotIn(blocking, pre_deadline_cut)

        self.assertTrue(invalidate, "missing logical exact-session invalidation")
        tx_try_call = re.search(
            r"\b(?P<helper>pble_ble_vm_tx_[A-Za-z_]\w*nowait)\s*\(\s*\)",
            invalidate,
        )
        self.assertIsNotNone(
            tx_try_call,
            "logical invalidation must enter a named zero-wait TX cut",
        )
        tx_try_name = tx_try_call.group("helper")
        tx_try = code_only(c_function(BLE, tx_try_name))
        self.assertTrue(tx_try, "zero-wait TX helper must be source-defined")
        self.assertRegex(
            tx_try,
            r"\bxSemaphoreTakeRecursive\s*\(\s*pble_tx_mutex\s*,\s*0\s*\)",
        )
        self.assertRegex(
            tx_try,
            r"\bxSemaphoreTakeRecursive\s*\([^;]+\)\s*!=\s*pdTRUE",
            "zero-wait TX acquisition failure must be checked",
        )
        failure = re.search(
            r"\bif\s*\([^{}]*xSemaphoreTakeRecursive\s*\([^;{}]+\)"
            r"[^{}]*\)\s*\{(?P<body>[^{}]*)\}",
            tx_try,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(failure, "missing checked zero-wait failure branch")
        self.assertIn(
            "esp_restart()",
            failure.group("body"),
            "a busy pre-deadline TX cut must fail closed immediately",
        )
        self.assertRegex(
            invalidate,
            rf"\bif\s*\(\s*!\s*{re.escape(tx_try_name)}\s*\(\s*\)\s*\)",
            "logical invalidation must stop if fail-closed TX acquisition returns",
        )
        old_token = re.search(
            r"\bpble_session_token_t\s+([A-Za-z_]\w*)\b", invalidate
        )
        self.assertIsNotNone(old_token, "snapshot the exact old session token")
        token_name = old_token.group(1)
        ordered(
            self,
            invalidate,
            tx_try_name,
            "taskENTER_CRITICAL(&pble_session_mux)",
            ".conn = pble_conn_handle",
            ".generation = pble_conn_generation",
            ".vm_epoch = pble_session_vm_epoch",
            "pble_session_vm_epoch = 0",
            "taskEXIT_CRITICAL(&pble_session_mux)",
            "pble_rsp_cancel_session",
            "xSemaphoreGiveRecursive(pble_tx_mutex)",
        )
        self.assertRegex(
            invalidate,
            rf"\bpble_rsp_cancel_session\s*\(\s*&?\s*{re.escape(token_name)}\s*\)",
        )
        for blocking in (
            "portMAX_DELAY",
            "vTaskDelay",
            "ulTaskNotifyTake",
        ):
            with self.subTest(invalidation_blocking=blocking):
                self.assertNotIn(blocking, invalidate)
        self.assertNotRegex(
            invalidate,
            r"\bxSemaphoreTake(?:Recursive)?\s*\(",
            "all pre-deadline TX acquisition belongs in the audited zero-wait helper",
        )

    def test_epoch_begin_rotates_retained_session_in_one_tx_session_cut(self):
        reset = code_only(c_function(BLE, "pble_ble_vm_reset"))
        self.assertTrue(reset)
        tx_take = reset.find("xSemaphoreTakeRecursive(pble_tx_mutex")
        session_enter = reset.find("taskENTER_CRITICAL(&pble_session_mux)")
        session_exit = reset.find(
            "taskEXIT_CRITICAL(&pble_session_mux)", session_enter
        )
        cancel = reset.find("pble_rsp_cancel_session", session_exit)
        tx_give = reset.find("xSemaphoreGiveRecursive(pble_tx_mutex)", cancel)
        self.assertGreaterEqual(tx_take, 0, "VM reset must own physical TX")
        self.assertGreater(session_enter, tx_take, "session cut must follow TX")
        self.assertGreater(session_exit, session_enter)
        self.assertGreater(cancel, session_exit, "cancel outside session spinlock")
        self.assertGreater(tx_give, cancel, "old tickets cancel before TX exposure")

        session_cut = reset[session_enter:session_exit]
        for token in (
            "PBLE_TERM_PHASE_CLOSING",
            "PBLE_TERM_PHASE_RESTARTING",
            "pble_conn_generation_counter++",
            "pble_conn_generation_counter == 0",
            "pble_term_rotate_open",
            "pble_conn_generation =",
            "pble_session_vm_epoch = vm_epoch",
        ):
            with self.subTest(atomic_rotation_token=token):
                self.assertIn(token, session_cut)
        self.assertIn("esp_restart", reset)
        self.assertNotIn(
            "pble_ble_session_closing",
            reset,
            "a separate check before the TX/session cut has a check/use race",
        )

    def test_response_pool_recycles_before_port_init_releases_tx(self):
        begin = code_only(c_function(VM_C, "pble_vm_epoch_begin"))
        reset = code_only(c_function(BLE, "pble_ble_vm_reset"))
        self.assertNotIn(
            "pble_proto_vm_reset",
            begin,
            "lifecycle must not hard-recycle tickets after BLE releases TX",
        )
        tx_take = reset.find("xSemaphoreTakeRecursive(pble_tx_mutex")
        session_exit = reset.find("taskEXIT_CRITICAL(&pble_session_mux)")
        cancel = reset.find("pble_rsp_cancel_session", session_exit)
        proto_reset = reset.find("pble_proto_vm_reset", cancel)
        tx_give = reset.find("xSemaphoreGiveRecursive(pble_tx_mutex)", proto_reset)
        positions = (tx_take, session_exit, cancel, proto_reset, tx_give)
        self.assertTrue(
            all(position >= 0 for position in positions),
            "session rotation, exact-ticket cancel, and pool recycle share TX",
        )
        self.assertEqual(list(positions), sorted(positions))

    def test_lifecycle_counter_is_bounded_and_fails_closed(self):
        enter = code_only(c_function(VM_C, "pble_vm_dispatch_enter"))
        leave = code_only(c_function(VM_C, "pble_vm_dispatch_leave"))
        wait = code_only(c_function(VM_C, "pble_vm_wait_activity_idle"))
        self.assertIn("UINT32_MAX", enter)
        self.assertIn("esp_restart", enter)
        self.assertRegex(leave, r"(?:==|<=)\s*0")
        self.assertIn("esp_restart", leave)
        self.assertIn("deadline_us", wait.partition("{")[0])
        self.assertNotIn("PBLE_VM_DEINIT_BUDGET_MS", wait)
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
            "pble_vm_rx_callback_enter",
            "OS_MBUF_PKTLEN",
            "ble_hs_mbuf_to_flat",
            "pble_rx_ingest",
        )
        self.assertGreater(
            callback.rfind("pble_vm_callback_leave"),
            callback.find("pble_rx_ingest"),
            "the RX activity must cover reassembly and complete-CMD dispatch",
        )
        entry_pos = callback.find("pble_vm_rx_callback_enter")
        read_pos = callback.find("OS_MBUF_PKTLEN")
        refusal_cut = callback[entry_pos:read_pos]
        refused = re.search(
            r"if\s*\([^{}]*\)\s*\{(?P<body>.*?)\}",
            refusal_cut,
            re.DOTALL,
        )
        self.assertIsNotNone(refused)
        self.assertRegex(refused.group("body"), r"\breturn\b")
        self.assertNotIn(
            "pble_ble_vm_rx_reset",
            callback,
            "refusal reset outside lifecycle synchronization can clear a fresh FIRST",
        )

        rx_enter = code_only(c_function(VM_C, "pble_vm_rx_callback_enter"))
        self.assertTrue(rx_enter)
        critical_enter = rx_enter.find("taskENTER_CRITICAL")
        critical_exit = rx_enter.rfind("taskEXIT_CRITICAL")
        self.assertGreaterEqual(critical_enter, 0)
        self.assertGreater(critical_exit, critical_enter)
        atomic_cut = rx_enter[critical_enter:critical_exit]
        self.assertIn("pble_ble_vm_rx_reset", atomic_cut)
        self.assertIn("pble_vm_activity_enter_locked", atomic_cut)
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
        thread_entry = code_only(c_function(MP_MODTHREAD, "thread_entry"))
        ordered(
            self,
            thread_entry,
            "MP_THREAD_GIL_ENTER",
            "mp_thread_start",
            "mp_call_function_n_kw",
        )
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
        self.assertIn("deadline_us", ready.partition("{")[0])
        self.assertIn("esp_timer_get_time", ready)
        self.assertNotIn("portMAX_DELAY", ready)

        self.assertRegex(
            VM_H + VM_C + BLE,
            r"#\s*define\s+PBLE_VM_READY_BUDGET_MS\s+2500(?:[uUlL]*)\b",
        )
        binding = code_only(c_function(BLE, "pble_ble_vm_ready"))
        ordered(
            self,
            binding,
            "deadline_us",
            "MP_THREAD_GIL_EXIT",
            "pble_vm_ready",
            "MP_THREAD_GIL_ENTER",
        )
        self.assertIn("esp_timer_get_time", binding)
        self.assertIn("PBLE_VM_READY_BUDGET_MS", binding)
        self.assertNotIn("portMAX_DELAY", binding)
        self.assertIn("MP_QSTR_vm_ready", BLE)


class NativeFsEpochContractTests(unittest.TestCase):
    def test_fs_items_include_put_data_session_generation_and_vm_epoch(self):
        item = re.search(
            r"typedef\s+struct\s*\{(?P<body>[^{}]*)\}\s*pble_fs_req_t\s*;",
            FS,
            re.DOTALL,
        )
        self.assertIsNotNone(item)
        body = item.group("body")
        self.assertRegex(body, r"\bpble_session_token_t\s+session\b")
        self.assertRegex(body, r"\bvm_epoch\b")
        for name in (
            "pble_fs_list",
            "pble_fs_stat",
            "pble_fs_get_begin",
            "pble_fs_put_begin",
            "pble_fs_put_data",
            "pble_fs_put_end",
            "pble_fs_delete",
            "pble_fs_mkdir",
            "pble_fs_rename",
        ):
            handler = code_only(c_function(FS, name))
            handler_signature = handler.partition("{")[0]
            token_param = re.search(
                r"(?:const\s+)?pble_session_token_t\s*\*?\s*([A-Za-z_]\w*)",
                handler_signature,
            )
            with self.subTest(handler=name):
                self.assertIsNotNone(token_param)
                enqueue_call = re.search(r"fs_enqueue\s*\([^;]+\)", handler)
                self.assertIsNotNone(enqueue_call)
                self.assertRegex(
                    enqueue_call.group(0),
                    rf"\b{re.escape(token_param.group(1))}\b",
                )
        enqueue = code_only(c_function(FS, "fs_enqueue"))
        enqueue_signature = enqueue.partition("{")[0]
        self.assertIn("pble_session_token_t", enqueue_signature)
        self.assertNotIn("pble_ble_session_snapshot", enqueue)
        token_param = re.search(
            r"(?:const\s+)?pble_session_token_t\s*\*?\s*([A-Za-z_]\w*)",
            enqueue_signature,
        )
        self.assertIsNotNone(token_param)
        self.assertRegex(
            enqueue,
            rf"g_enq\.session\s*=\s*\*?{re.escape(token_param.group(1))}\b",
        )
        self.assertIn("pble_vm_epoch_current", enqueue)
        valid = code_only(c_function(FS, "pble_fs_item_valid"))
        self.assertNotIn("it->ticket", valid)
        self.assertNotIn("pble_rsp_ticket_", valid)
        self.assertRegex(
            valid,
            r"pble_ble_session_live\s*\(\s*&\s*it->session\s*\)",
        )
        self.assertRegex(
            valid,
            r"pble_vm_epoch_\w+\s*\(\s*it->vm_epoch\s*\)",
        )
        ticket_valid = code_only(c_function(FS, "pble_fs_ticket_valid"))
        self.assertRegex(
            ticket_valid,
            r"pble_fs_item_valid\s*\(\s*it\s*\)",
        )
        self.assertRegex(
            ticket_valid,
            r"pble_rsp_ticket_valid\s*\(\s*&\s*it->ticket\s*\)",
        )

    def test_fs_queue_pop_and_busy_transition_share_quiescence_lock(self):
        enqueue = code_only(c_function(FS, "fs_enqueue"))
        dequeue = code_only(c_function(FS, "pble_fs_dequeue_begin"))
        quiesce = code_only(c_function(FS, "pble_fs_quiesce_try"))
        for body in (enqueue, dequeue, quiesce):
            self.assertIn("g_fs_gate", body)
        for name, body in (("fs_enqueue", enqueue), ("quiesce", quiesce)):
            with self.subTest(zero_wait_host_gate=name):
                self.assertRegex(
                    body,
                    r"xSemaphoreTake\s*\(\s*g_fs_gate\s*,\s*0\s*\)",
                )
                self.assertNotIn("portMAX_DELAY", body)
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

    def test_soft_grace_uses_a_provisional_non_reboot_dispatch_gate(self):
        reboot_close = code_only(c_function(VM_C, "pble_vm_reboot_close"))
        reboot_abort = code_only(c_function(VM_C, "pble_vm_reboot_abort"))
        command_admitted = code_only(
            c_function(VM_C, "pble_vm_reboot_command_admitted")
        )
        global_close = code_only(c_function(VM_C, "pble_vm_close_admission"))
        global_open = code_only(c_function(VM_C, "pble_vm_open_admission"))
        epoch_begin = code_only(c_function(VM_C, "pble_vm_epoch_begin"))

        self.assertNotIn(
            "pble_vm_dispatch_open = false",
            reboot_close,
            "the 250 ms grace must keep complete-CMD lifecycle admission open",
        )
        self.assertNotIn(
            "pble_vm_lifecycle_active = false",
            reboot_close,
            "the 250 ms grace must keep callback/activity accounting alive",
        )
        gate_candidates = {
            name
            for name in re.findall(
                r"\b(pble_vm_[A-Za-z_]\w*)\s*=\s*false\b",
                reboot_close,
            )
            if name not in {"pble_vm_dispatch_open", "pble_vm_lifecycle_active"}
        }
        self.assertEqual(
            len(gate_candidates),
            1,
            "reboot-close needs one distinct provisional non-reboot gate",
        )
        gate = next(iter(gate_candidates))
        self.assertIn(f"{gate} = true", reboot_abort)
        self.assertIn(f"{gate} = true", global_open)
        self.assertIn(f"{gate} = false", global_close)
        self.assertIn(f"{gate} = false", epoch_begin)
        for global_flag in (
            "pble_vm_dispatch_open = false",
            "pble_vm_lifecycle_active = false",
        ):
            self.assertIn(
                global_flag,
                global_close,
                "the wrapper/global cut must still close every command",
            )

        self.assertTrue(
            command_admitted,
            "add an admitted-dispatch query for the provisional reboot gate",
        )
        signature = command_admitted.partition("{")[0]
        parameters = signature[
            signature.find("(") + 1 : signature.rfind(")")
        ]
        soft_param = re.search(r"\bbool\s+([A-Za-z_]\w*)\b", parameters)
        self.assertIsNotNone(soft_param)
        soft_name = soft_param.group(1)
        self.assertIn(gate, command_admitted)
        self.assertRegex(
            command_admitted,
            rf"(?:\b{re.escape(gate)}\b\s*\|\|\s*\b{re.escape(soft_name)}\b"
            rf"|\b{re.escape(soft_name)}\b\s*\|\|\s*\b{re.escape(gate)}\b)",
            "SOFT_REBOOT alone bypasses the provisional non-reboot gate",
        )
        self.assertIn("taskENTER_CRITICAL(&pble_vm_mux)", command_admitted)
        self.assertIn("taskEXIT_CRITICAL(&pble_vm_mux)", command_admitted)
        self.assertRegex(
            VM_H,
            r"\bbool\s+pble_vm_reboot_command_admitted\s*\(\s*bool\b",
        )

        dispatch = code_only(c_function(PROTO, "pble_proto_dispatch_admitted"))
        gate_call = re.search(
            r"pble_vm_reboot_command_admitted\s*\(\s*"
            r"f\.opcode\s*==\s*PBLE_OP_SOFT_REBOOT\s*\)",
            dispatch,
        )
        self.assertIsNotNone(
            gate_call,
            "admitted dispatch must exempt only SOFT_REBOOT from the gate",
        )
        crc = dispatch.find("pble_proto_crc32")
        self.assertGreater(gate_call.start(), crc)
        handler_calls = [
            position
            for marker in ("special_handler(", "deferred(&f", "h(&f")
            if (position := dispatch.find(marker)) >= 0
        ]
        self.assertTrue(handler_calls)
        first_handler = min(handler_calls)
        self.assertLess(gate_call.start(), first_handler)
        refusal = dispatch[gate_call.start() : first_handler]
        self.assertIn("PBLE_EBUSY", refusal)
        self.assertIn(
            "PBLE_HANDLER_NO_RESPONSE",
            refusal,
            "fire-and-forget commands remain effect-free and response-free",
        )
        self.assertGreater(dispatch.find("pble_rsp_publish"), gate_call.start())

    def test_duplicate_soft_remains_ebusy_through_committed_grace(self):
        soft = code_only(c_function(RUNNER, "pble_runner_soft_reboot"))
        callback = code_only(c_function(RUNNER, "soft_reboot_timer_cb"))
        disarm = code_only(c_function(RUNNER, "pble_runner_vm_timer_disarm"))
        pre_deinit = code_only(c_function(VM_C, "pble_vm_epoch_pre_deinit"))

        ordered(
            self,
            soft,
            "if (g_soft_reboot_pending)",
            "return PBLE_EBUSY",
            "pble_fs_quiesce_try",
        )
        self.assertIn("g_soft_reboot_pending", callback)
        self.assertIn("g_soft_reboot_epoch", callback)
        forbidden_commit_mutations = (
            "g_soft_reboot_pending = false",
            "g_soft_reboot_epoch = 0",
            "pble_vm_reboot_abort",
            "pble_fs_quiesce_abort",
        )
        self.assertEqual(
            [
                forbidden
                for forbidden in forbidden_commit_mutations
                if forbidden in callback
            ],
            [],
            "the fired timer must preserve the irreversible reboot closure",
        )
        for cleared in (
            "g_soft_reboot_pending = false",
            "g_soft_reboot_epoch = 0",
        ):
            self.assertIn(cleared, disarm)
        ordered(
            self,
            pre_deinit,
            "pble_vm_close_admission",
            "pble_runner_vm_timer_disarm",
        )
        committed = soft[soft.index("esp_timer_start_once") :]
        self.assertNotIn("pble_vm_reboot_abort", committed)
        self.assertNotIn("pble_fs_quiesce_abort", committed)

    def test_soft_reboot_quiesces_then_commits_at_accepted_rsp(self):
        soft = code_only(c_function(RUNNER, "pble_runner_soft_reboot"))
        ordered(
            self,
            soft,
            "pble_fs_quiesce_try",
            "pble_vm_reboot_close",
            "pble_proto_emit_rsp_status_try",
            "runner_control_attempt_resolve(true)",
            "esp_timer_start_once",
        )
        self.assertEqual(soft.count("esp_timer_start_once"), 1)
        self.assertEqual(soft.count("pble_fs_quiesce_abort"), 1)
        self.assertIn("PBLE_EBUSY", soft)
        for marker in (
            "if (tx_rc != PBLE_TX_OK)",
            "esp_restart",
            "runner_control_attempt_resolve(true)",
        ):
            self.assertIn(marker, soft)
        tx_failure = soft[
            soft.index("if (tx_rc != PBLE_TX_OK)") :
            soft.index("esp_timer_start_once")
        ]
        self.assertIn("pble_vm_reboot_abort", tx_failure)
        self.assertIn("pble_fs_quiesce_abort", tx_failure)
        self.assertIn("runner_control_attempt_resolve(false)", tx_failure)
        self.assertNotIn("esp_restart", tx_failure)

        self.assertNotIn("g_stop_requested = true", soft)
        self.assertNotIn("inject_worker_kbd_interrupt", soft)
        resolver = code_only(
            c_function(RUNNER, "runner_control_attempt_resolve")
        )
        ordered(
            self,
            resolver,
            "g_stop_requested = true",
            "inject_worker_kbd_interrupt",
        )

        after_timer_attempt = soft[soft.index("esp_timer_start_once") :]
        self.assertIn("esp_restart", after_timer_attempt)
        self.assertNotIn(
            "pble_fs_quiesce_abort",
            after_timer_attempt,
            "accepted RSP must never reopen admission",
        )

    def test_every_vfs_dispatch_revalidates_before_and_after_effect(self):
        function_names = c_function_names(FS)
        function_bodies = {
            name: code_only(c_function(FS, name)) for name in function_names
        }
        self.assertTrue(
            any(
                name == "fs_open" or name.startswith("fs_open_")
                for name in function_names
            ),
            "the definition scanner must retain raw open helpers",
        )
        for nested_call in (
            "mode",
            "nlr_push",
            "mp_iternext",
            "it",
            "file",
            "RENAME",
        ):
            self.assertNotIn(nested_call, function_names)

        def defined_calls(body: str, owner: str | None = None) -> set[str]:
            return {
                name
                for name in function_names
                if name != owner
                and re.search(rf"\b{re.escape(name)}\s*\(", body)
            }

        def reachable(seeds: set[str]) -> set[str]:
            seen: set[str] = set()
            pending = [name for name in seeds if name in function_bodies]
            while pending:
                name = pending.pop()
                if name in seen:
                    continue
                seen.add(name)
                pending.extend(
                    defined_calls(function_bodies[name], name) - seen
                )
            return seen

        get = function_bodies.get("fs_do_get", "")
        wait_call = re.search(r"\bpble_rsp_wait\s*\([^;]+\)", get)
        self.assertIsNotNone(wait_call)
        get_before_wait = get[: wait_call.start()]
        get_after_wait = get[wait_call.end() :]
        response_roots = {
            "fs_do_list",
            "fs_do_stat",
            "fs_do_put_begin",
            "fs_do_put_end",
            "fs_do_delete",
            "fs_do_mkdir",
            "fs_do_rename",
        }
        self.assertTrue(response_roots.issubset(function_bodies))
        ticket_context = reachable(
            response_roots | defined_calls(get_before_wait, "fs_do_get")
        )
        session_context = reachable(
            {"fs_do_put_data"} | defined_calls(get_after_wait, "fs_do_get")
        )
        raw_functions = {
            name
            for name, body in function_bodies.items()
            if VFS_EFFECT_RE.search(body)
        }
        mixed_raw_helpers = (
            ticket_context & session_context & raw_functions
        ) - {"fs_do_get"}
        mixed_validators: dict[str, str] = {}
        if mixed_raw_helpers:
            self.assertRegex(
                FS,
                r"typedef\s+bool\s*\(\s*\*\s*pble_fs_validator_t\s*\)\s*"
                r"\(\s*const\s+pble_fs_req_t\s*\*[^;]*\)\s*;",
                "a mixed raw helper needs an explicit phase validator",
            )
        for helper in mixed_raw_helpers:
            signature = function_bodies[helper].partition("{")[0]
            validator = re.search(
                r"\bpble_fs_validator_t\s+([A-Za-z_]\w*)\b",
                signature,
            )
            self.assertIsNotNone(
                validator,
                "{} must receive its ticket-vs-session validator".format(helper),
            )
            mixed_validators[helper] = validator.group(1)

            observed_contexts: set[str] = set()
            for caller, caller_body in function_bodies.items():
                if caller == helper:
                    continue
                calls = list(
                    re.finditer(
                        rf"\b{re.escape(helper)}\s*\((?P<args>[^;]*)\)",
                        caller_body,
                    )
                )
                if not calls:
                    continue
                required: str | None = None
                if caller in ticket_context and caller not in session_context:
                    required = "pble_fs_ticket_valid"
                    observed_contexts.add("ticket")
                elif caller in session_context and caller not in ticket_context:
                    required = "pble_fs_item_valid"
                    observed_contexts.add("session")
                if required is not None:
                    for call in calls:
                        self.assertRegex(call.group("args"), rf"\b{required}\b")

            for context, segment, required in (
                ("ticket", get_before_wait, "pble_fs_ticket_valid"),
                ("session", get_after_wait, "pble_fs_item_valid"),
            ):
                calls = list(
                    re.finditer(
                        rf"\b{re.escape(helper)}\s*\((?P<args>[^;]*)\)",
                        segment,
                    )
                )
                if calls:
                    observed_contexts.add(context)
                    for call in calls:
                        self.assertRegex(call.group("args"), rf"\b{required}\b")
            self.assertEqual(observed_contexts, {"ticket", "session"})

        guarded_functions = 0
        for name in function_names:
            body = function_bodies[name]
            effects = list(VFS_EFFECT_RE.finditer(body))
            if not effects or name == "fs_do_get":
                continue
            guarded_functions += 1
            with self.subTest(function=name):
                signature = body.partition("{")[0]
                self.assertIn(
                    "pble_fs_req_t",
                    signature,
                    "raw VFS helpers need the exact work-item token",
                )
                requires_ticket = name in ticket_context
                if name in mixed_validators:
                    guard_re = re.compile(
                        rf"\b{re.escape(mixed_validators[name])}\s*\("
                    )
                else:
                    guard_re = (
                        VFS_TICKET_VALID_RE if requires_ticket else VFS_VALID_RE
                    )
                guards = list(guard_re.finditer(body))
                self.assertTrue(guards, "raw VFS effects need token guards")
                if requires_ticket and name not in mixed_validators:
                    self.assertTrue(
                        VFS_TICKET_VALID_RE.search(body),
                        "response-bearing VFS effects need the whole ticket",
                    )
                for effect_index, effect in enumerate(effects):
                    previous_guard = max(
                        (
                            guard.start()
                            for guard in guards
                            if guard.end() <= effect.start()
                        ),
                        default=-1,
                    )
                    next_guard = min(
                        (
                            guard.start()
                            for guard in guards
                            if guard.start() >= effect.end()
                        ),
                        default=len(body) + 1,
                    )
                    previous_effect = max(
                        (
                            other.end()
                            for other in effects[:effect_index]
                            if other.end() <= effect.start()
                        ),
                        default=-1,
                    )
                    next_effect = min(
                        (
                            other.start()
                            for other in effects[effect_index + 1 :]
                            if other.start() >= effect.end()
                        ),
                        default=len(body) + 1,
                    )
                    self.assertGreater(
                        previous_guard,
                        previous_effect,
                        "{} lacks an operation-adjacent pre-check".format(
                            effect.group(0)
                        ),
                    )
                    self.assertLess(
                        next_guard,
                        next_effect,
                        "{} lacks an operation-adjacent post-check".format(
                            effect.group(0)
                        ),
                    )
        self.assertGreater(guarded_functions, 0, "no raw VFS effects were audited")

    def test_get_recycles_ticket_then_uses_only_immutable_session_epoch(self):
        get = code_only(c_function(FS, "fs_do_get"))
        wait_call = re.search(
            r"pble_rsp_wait\s*\(\s*&\s*it->ticket\s*\)",
            get,
        )
        self.assertIsNotNone(wait_call)
        before_wait = get[: wait_call.end()]
        after_wait = get[wait_call.end() :]

        ticket_guards = list(
            re.finditer(
                r"pble_rsp_ticket_valid\s*\(\s*&\s*it->ticket\s*\)",
                before_wait,
            )
        )
        pre_wait_effects = list(VFS_EFFECT_RE.finditer(before_wait))
        pre_wait_effects.extend(
            re.finditer(
                r"\bfs_(?:open|stat_path|crc_file|crc_prefix)[A-Za-z_]*\s*\(",
                before_wait,
            )
        )
        pre_wait_effects.sort(key=lambda match: match.start())
        self.assertTrue(pre_wait_effects)
        for effect_index, effect in enumerate(pre_wait_effects):
            previous_effect = (
                pre_wait_effects[effect_index - 1].end() if effect_index else -1
            )
            next_effect = (
                pre_wait_effects[effect_index + 1].start()
                if effect_index + 1 < len(pre_wait_effects)
                else len(before_wait) + 1
            )
            previous_guard = max(
                (
                    guard.start()
                    for guard in ticket_guards
                    if guard.end() <= effect.start()
                ),
                default=-1,
            )
            next_guard = min(
                (
                    guard.start()
                    for guard in ticket_guards
                    if guard.start() >= effect.end()
                ),
                default=len(before_wait) + 1,
            )
            with self.subTest(pre_wait_effect=effect.group(0)):
                self.assertGreater(
                    previous_guard,
                    previous_effect,
                    "pre-completion VFS work needs an adjacent whole-ticket check",
                )
                self.assertLess(
                    next_guard,
                    next_effect,
                    "pre-completion VFS work needs an adjacent whole-ticket post-check",
                )
        self.assertIn("pble_rsp_publish(&it->ticket", before_wait)
        self.assertNotIn(
            "it->ticket",
            after_wait,
            "pble_rsp_wait recycles the response slot",
        )
        self.assertNotRegex(after_wait, r"\bpble_rsp_ticket_\w*\s*\(")

        late_effects = list(VFS_EFFECT_RE.finditer(after_wait))
        late_effects.extend(
            re.finditer(
                r"\bfs_emit_paced\s*\(\s*it\s*,\s*"
                r"PBLE_OP_FILE_GET_(?:DATA|END)\b",
                after_wait,
            )
        )
        late_effects.sort(key=lambda match: match.start())
        self.assertGreaterEqual(
            len(late_effects),
            3,
            "GET must audit its later read chunks and DATA/END events",
        )
        guards = list(VFS_VALID_RE.finditer(after_wait))
        for effect_index, effect in enumerate(late_effects):
            previous_effect = (
                late_effects[effect_index - 1].end() if effect_index else -1
            )
            next_effect = (
                late_effects[effect_index + 1].start()
                if effect_index + 1 < len(late_effects)
                else len(after_wait) + 1
            )
            previous_guard = max(
                (
                    guard.start()
                    for guard in guards
                    if guard.end() <= effect.start()
                ),
                default=-1,
            )
            next_guard = min(
                (
                    guard.start()
                    for guard in guards
                    if guard.start() >= effect.end()
                ),
                default=len(after_wait) + 1,
            )
            with self.subTest(late_effect=effect.group(0)):
                self.assertGreater(previous_guard, previous_effect)
                self.assertLess(next_guard, next_effect)

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
