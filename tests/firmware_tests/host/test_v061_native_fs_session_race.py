#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""RED contract for native PUT ownership across disconnect/reconnect."""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FS_PATH = ROOT / "firmware" / "user_c_modules" / "pyble" / "pble_fs.c"


def _matching_brace(source: str, opening: int) -> int:
    depth = 0
    state = "code"
    index = opening
    while index < len(source):
        char = source[index]
        nxt = source[index + 1] if index + 1 < len(source) else ""
        if state == "line-comment":
            if char == "\n":
                state = "code"
        elif state == "block-comment":
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
            state = "line-comment"
            index += 1
        elif char == "/" and nxt == "*":
            state = "block-comment"
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
    raise AssertionError("unbalanced C braces")


def _function(source: str, name: str) -> str:
    match = re.search(
        r"(?m)^[ \t]*(?:static[ \t]+)?[A-Za-z_]"
        r"[A-Za-z0-9_ \t*]*\b"
        + re.escape(name)
        + r"[ \t]*\([^;{}]*\)[ \t]*\{",
        source,
    )
    if match is None:
        raise AssertionError("native function `{}` is missing".format(name))
    opening = source.find("{", match.start(), match.end())
    closing = _matching_brace(source, opening)
    return source[match.start() : closing + 1]


def _functions(source: str) -> dict[str, str]:
    names = re.findall(
        r"(?m)^[ \t]*(?:static[ \t]+)?[A-Za-z_]"
        r"[A-Za-z0-9_ \t*]*\b([A-Za-z_]\w*)"
        r"[ \t]*\([^;{}]*\)[ \t]*\{",
        source,
    )
    return {name: _function(source, name) for name in names}


def _called_helpers(body: str, functions: dict[str, str]) -> list[str]:
    return [
        candidate
        for name, candidate in functions.items()
        if re.search(r"\b{}\s*\(".format(re.escape(name)), body)
    ]


@dataclass(frozen=True)
class _QueuedPut:
    transfer_generation: int


class _PutGenerationOracle:
    """Minimal interleaving model for the required synchronized cut."""

    def __init__(self) -> None:
        self.transfer_generation = 1
        self.active_owner: int | None = None

    def enqueue(self) -> _QueuedPut:
        return _QueuedPut(self.transfer_generation)

    def disconnect(self) -> None:
        # The host callback invalidates ownership; it never edits worker state.
        self.transfer_generation += 1

    def commit_begin(self, request: _QueuedPut) -> bool:
        # This comparison and publication are one indivisible cut.
        if request.transfer_generation != self.transfer_generation:
            return False
        self.active_owner = request.transfer_generation
        return True

    def begin_successor(self, request: _QueuedPut) -> str:
        # Worker-side reconciliation makes an old committed owner non-busy.
        if self.active_owner != self.transfer_generation:
            self.active_owner = None
        if self.active_owner is not None:
            return "EBUSY"
        return "OK" if self.commit_begin(request) else "DROP"

    def owns(self, request: _QueuedPut) -> bool:
        return (
            request.transfer_generation == self.transfer_generation
            and self.active_owner == request.transfer_generation
        )


class NativePutSessionRaceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = FS_PATH.read_text(encoding="utf-8", errors="strict")
        cls.functions = _functions(cls.source)

    def test_interleaving_oracle_rejects_both_stale_commit_orders(self):
        # Cut 1: disconnect wins immediately before A's final publication.
        before_commit = _PutGenerationOracle()
        request_a = before_commit.enqueue()
        before_commit.disconnect()
        self.assertFalse(before_commit.commit_begin(request_a))
        request_b = before_commit.enqueue()
        self.assertEqual(before_commit.begin_successor(request_b), "OK")
        self.assertFalse(before_commit.owns(request_a))
        self.assertTrue(before_commit.owns(request_b))

        # Cut 2: A publishes first, then disconnect invalidates its owner. B
        # reconciles that stale worker state instead of observing false EBUSY.
        after_commit = _PutGenerationOracle()
        request_a = after_commit.enqueue()
        self.assertTrue(after_commit.commit_begin(request_a))
        after_commit.disconnect()
        request_b = after_commit.enqueue()
        self.assertEqual(after_commit.begin_successor(request_b), "OK")
        self.assertFalse(after_commit.owns(request_a))
        self.assertTrue(after_commit.owns(request_b))

    def test_disconnect_invalidates_generation_without_writing_put_state(self):
        disconnect = self.functions["pble_fs_on_disconnect"]
        self.assertNotRegex(
            disconnect,
            r"\bg_put_|\bfs_put_reset\s*\(",
            "the NimBLE host callback must not race the worker by writing "
            "worker-owned PUT state",
        )
        self.assertIn("g_fs_transfer_mux", disconnect)
        self.assertRegex(disconnect, r"\btaskENTER_CRITICAL\s*\(")
        self.assertRegex(disconnect, r"\btaskEXIT_CRITICAL\s*\(")
        self.assertRegex(
            disconnect,
            r"\bg_fs_transfer_generation\s*(?:\+\+|\+=\s*1\b|=)",
            "disconnect must invalidate queued/in-flight work with a bounded "
            "FS-local generation",
        )

    def test_queue_snapshots_generation_under_the_disconnect_mux(self):
        request_type = re.search(
            r"typedef\s+struct\s*\{(?P<body>.*?)\}\s*pble_fs_req_t\s*;",
            self.source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(request_type)
        self.assertRegex(
            request_type.group("body"),
            r"\buint64_t\s+transfer_generation\s*;",
            "each queued request needs an FS-local disconnect generation",
        )
        self.assertIsNotNone(
            re.search(
                r"\bstatic\s+portMUX_TYPE\s+g_fs_transfer_mux\b",
                self.source,
            ),
            "native FS needs one host/worker transfer-generation critical domain",
        )
        self.assertIsNotNone(
            re.search(
                r"\bstatic\s+uint64_t\s+g_fs_transfer_generation\b",
                self.source,
            ),
            "native FS needs a bounded local generation invalidated on disconnect",
        )

        enqueue = self.functions["fs_enqueue"]
        assignment = re.search(
            r"g_enq\.transfer_generation\s*=\s*"
            r"g_fs_transfer_generation\s*;",
            enqueue,
        )
        self.assertIsNotNone(
            assignment,
            "enqueue must snapshot the synchronized transfer generation",
        )
        enter = enqueue.rfind("taskENTER_CRITICAL", 0, assignment.start())
        leave = enqueue.find("taskEXIT_CRITICAL", assignment.end())
        self.assertTrue(
            0 <= enter < assignment.start() < leave,
            "the queue snapshot must use the same critical domain as disconnect",
        )
        self.assertIn(
            "g_fs_transfer_mux", enqueue[enter:leave],
            "the queue snapshot used a different synchronization domain",
        )

    def test_put_begin_publication_is_one_generation_checked_atomic_cut(self):
        publication_functions = [
            (name, body)
            for name, body in self.functions.items()
            if re.search(r"\bg_put_active\s*=\s*true\s*;", body)
        ]
        self.assertEqual(
            len(publication_functions),
            1,
            "PUT_BEGIN must have one auditable ownership-publication seam",
        )
        name, publication = publication_functions[0]
        active = publication.find("g_put_active")
        enter = publication.rfind("taskENTER_CRITICAL", 0, active)
        leave = publication.find("taskEXIT_CRITICAL", active)
        self.assertTrue(
            0 <= enter < active < leave,
            "{} must publish active PUT ownership inside the transfer-generation "
            "critical cut".format(name),
        )
        atomic_cut = publication[enter:leave]
        self.assertIn("g_fs_transfer_mux", atomic_cut)
        self.assertRegex(
            atomic_cut,
            r"it->transfer_generation\s*==\s*g_fs_transfer_generation|"
            r"g_fs_transfer_generation\s*==\s*it->transfer_generation",
            "the final publication must revalidate the queued generation",
        )
        self.assertRegex(
            atomic_cut,
            r"\bg_put_generation\s*=\s*(?:it->transfer_generation|"
            r"g_fs_transfer_generation)\s*;",
            "active PUT state must retain its exact owning generation",
        )
        for field in (
            "g_put_active",
            "g_put_total",
            "g_put_crc_target",
            "g_put_latched",
        ):
            with self.subTest(publication_field=field):
                self.assertRegex(atomic_cut, r"\b{}\s*=".format(field))

    def test_successor_reconciles_owner_and_data_end_require_exact_owner(self):
        self.assertIsNotNone(
            re.search(
                r"\bstatic\s+uint64_t\s+g_put_generation\b",
                self.source,
            ),
            "the worker must retain which transfer generation owns g_put_*",
        )

        begin = self.functions["fs_do_put_begin"]
        busy = begin.find("PBLE_EBUSY")
        self.assertGreaterEqual(busy, 0)
        pre_busy = begin[:busy]
        expanded_pre_busy = pre_busy + "\n" + "\n".join(
            _called_helpers(pre_busy, self.functions)
        )
        for token in (
            "g_put_generation",
            "transfer_generation",
            "fs_put_reset",
        ):
            with self.subTest(successor_reconciliation=token):
                self.assertIn(
                    token,
                    expanded_pre_busy,
                    "successor PUT_BEGIN must reconcile stale ownership before "
                    "the single-transfer EBUSY gate",
                )

        for function, first_effect in (
            ("fs_do_put_data", "sp->write"),
            ("fs_do_put_end", "fs_put_close"),
        ):
            body = self.functions[function]
            effect = body.find(first_effect)
            self.assertGreaterEqual(effect, 0)
            pre_effect = body[:effect]
            expanded = pre_effect + "\n" + "\n".join(
                _called_helpers(pre_effect, self.functions)
            )
            with self.subTest(owner_gate=function):
                self.assertIn("g_put_generation", expanded)
                self.assertIn("transfer_generation", expanded)
                self.assertRegex(
                    expanded,
                    r"PBLE_NO_RSP|\breturn\b",
                    "stale DATA/END must stop before any active-transfer effect",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
