#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Focused RED for workspace-receipt path and concurrency safety.

The raw boot logs are synthetic grammar fixtures, not physical HIL evidence.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import test_v061_hardening_release_gate as fixture  # noqa: E402


GATE = fixture.GATE
HAVE_GATE = GATE is not None


def noncanonical_workspace_log(observation_kind: str) -> bytes:
    values = [
        json.loads(line)
        for line in fixture.workspace_raw_log(observation_kind)
        .decode("utf-8")
        .splitlines()
    ]
    return "".join(
        json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n"
        for value in values
    ).encode("utf-8")


class V061WorkspaceReceiptWriterSafetySeamTests(unittest.TestCase):
    def test_workspace_receipt_writer_exists(self):
        self.assertIsNotNone(GATE, "[red] %s" % fixture.GATE_LOAD_ERROR)
        if GATE is not None:
            self.assertTrue(callable(getattr(GATE, "create_workspace_receipt", None)))


@unittest.skipUnless(HAVE_GATE, "[red] v0.6.1 hardening gate is not implemented")
class V061WorkspaceReceiptWriterSafetyTests(unittest.TestCase):
    PROFILE_ID = "esp32-c3-4mb"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="pyble-v061-workspace-writer-safety-"
        )
        self.root = Path(self.temporary.name)
        self.writer = fixture.writer_fixture(self.root, self.PROFILE_ID)
        self.candidate = Path(self.writer["candidate"])

    def tearDown(self):
        self.temporary.cleanup()

    def paths(self, observation_kind: str, case: str) -> tuple[Path, Path]:
        stem = (
            "erased"
            if observation_kind == fixture.WORKSPACE_ORDER[0]
            else "nonblank"
        )
        output = self.root / ("%s-%s.json" % (stem, case))
        raw = output.with_name(output.stem + "-raw.jsonl")
        return raw, output

    def write_valid_raw(self, observation_kind: str, path: Path) -> bytes:
        raw = fixture.workspace_raw_log(observation_kind)
        fixture.private_write(path, raw)
        return raw

    def create(
        self,
        observation_kind: str,
        *,
        raw: Path,
        output: Path,
        candidate: Path | None = None,
    ):
        return GATE.create_workspace_receipt(
            candidate_dir=self.candidate if candidate is None else candidate,
            profile_id=self.PROFILE_ID,
            observation_kind=observation_kind,
            raw_boot_log=raw,
            output_path=output,
            qualification_repo_root=fixture.ROOT,
        )

    def assert_no_output(self, output: Path):
        self.assertFalse(output.exists())
        self.assertFalse(output.is_symlink())

    def test_rejects_every_unsafe_raw_log_without_touching_external_bytes(self):
        for observation_kind in fixture.WORKSPACE_ORDER:
            for case in (
                "symlink",
                "broken-symlink",
                "hardlink",
                "directory",
                "public-mode",
                "noncanonical",
            ):
                with self.subTest(kind=observation_kind, case=case):
                    raw, output = self.paths(observation_kind, "raw-" + case)
                    expected = fixture.workspace_raw_log(observation_kind)

                    if case == "symlink":
                        external = self.root / (raw.stem + "-external.jsonl")
                        fixture.private_write(external, expected)
                        raw.symlink_to(external)
                        sentinel = external
                        sentinel_bytes = external.read_bytes()
                    elif case == "broken-symlink":
                        external = self.root / (raw.stem + "-missing.jsonl")
                        raw.symlink_to(external)
                        sentinel = None
                        sentinel_bytes = None
                    elif case == "hardlink":
                        fixture.private_write(raw, expected)
                        external = self.root / (raw.stem + "-second-link.jsonl")
                        os.link(raw, external)
                        sentinel = external
                        sentinel_bytes = external.read_bytes()
                    elif case == "directory":
                        raw.mkdir()
                        sentinel = raw / "operator-sentinel"
                        sentinel_bytes = b"do not replace\n"
                        sentinel.write_bytes(sentinel_bytes)
                        external = None
                    elif case == "public-mode":
                        fixture.private_write(raw, expected)
                        raw.chmod(0o644)
                        sentinel = raw
                        sentinel_bytes = raw.read_bytes()
                        external = None
                    else:
                        malformed = noncanonical_workspace_log(observation_kind)
                        self.assertNotEqual(malformed, expected)
                        fixture.private_write(raw, malformed)
                        sentinel = raw
                        sentinel_bytes = raw.read_bytes()
                        external = None

                    with self.assertRaises(GATE.QualificationError):
                        self.create(observation_kind, raw=raw, output=output)

                    self.assert_no_output(output)
                    if case in {"symlink", "broken-symlink"}:
                        self.assertTrue(raw.is_symlink())
                    if case == "broken-symlink":
                        self.assertFalse(external.exists())
                    if sentinel is not None:
                        self.assertEqual(sentinel.read_bytes(), sentinel_bytes)
                    if case == "hardlink":
                        self.assertEqual(raw.stat().st_nlink, 2)
                    if case == "directory":
                        self.assertTrue(raw.is_dir())
                    if case == "public-mode":
                        self.assertEqual(raw.stat().st_mode & 0o777, 0o644)

    def test_rejects_every_unsafe_output_without_replacing_owner_state(self):
        for observation_kind in fixture.WORKSPACE_ORDER:
            for case in (
                "symlink",
                "broken-symlink",
                "directory",
                "symlink-parent",
                "preexisting",
            ):
                with self.subTest(kind=observation_kind, case=case):
                    raw, output = self.paths(observation_kind, "output-" + case)

                    if case == "symlink-parent":
                        external_parent = self.root / (
                            output.stem + "-external-parent"
                        )
                        external_parent.mkdir()
                        sentinel = external_parent / "operator-sentinel"
                        sentinel.write_bytes(b"external owner bytes\n")
                        linked_parent = self.root / (output.stem + "-linked-parent")
                        linked_parent.symlink_to(
                            external_parent,
                            target_is_directory=True,
                        )
                        output = linked_parent / "receipt.json"
                        raw = output.with_name("receipt-raw.jsonl")
                        self.write_valid_raw(observation_kind, raw)
                        before = {
                            item.name: item.read_bytes()
                            for item in external_parent.iterdir()
                            if item.is_file()
                        }
                    else:
                        self.write_valid_raw(observation_kind, raw)
                        before = None

                    if case == "symlink":
                        external_parent = self.root / (output.stem + "-external")
                        external_parent.mkdir()
                        target = external_parent / "owner-receipt.json"
                        target.write_bytes(b"owner receipt bytes\n")
                        target.chmod(0o600)
                        output.symlink_to(target)
                        sentinel = target
                        sentinel_bytes = target.read_bytes()
                    elif case == "broken-symlink":
                        target = self.root / (output.stem + "-missing.json")
                        output.symlink_to(target)
                        sentinel = None
                        sentinel_bytes = None
                    elif case == "directory":
                        output.mkdir()
                        sentinel = output / "operator-sentinel"
                        sentinel_bytes = b"directory owner bytes\n"
                        sentinel.write_bytes(sentinel_bytes)
                    elif case == "preexisting":
                        sentinel = output
                        sentinel_bytes = b"pre-existing receipt bytes\n"
                        fixture.private_write(output, sentinel_bytes)
                    elif case == "symlink-parent":
                        target = None
                        sentinel_bytes = None

                    with self.assertRaises(GATE.QualificationError):
                        self.create(observation_kind, raw=raw, output=output)

                    if case in {"symlink", "broken-symlink"}:
                        self.assertTrue(output.is_symlink())
                    if case == "broken-symlink":
                        self.assertFalse(target.exists())
                    elif case == "symlink-parent":
                        after = {
                            item.name: item.read_bytes()
                            for item in external_parent.iterdir()
                            if item.is_file()
                        }
                        self.assertEqual(after, before)
                        self.assertTrue(linked_parent.is_symlink())
                    else:
                        self.assertEqual(sentinel.read_bytes(), sentinel_bytes)
                    if case == "directory":
                        self.assertTrue(output.is_dir())

    def test_rejects_symlinked_candidate_and_preserves_its_target(self):
        real_candidate = self.root / "external-candidate"
        self.candidate.rename(real_candidate)
        self.candidate.symlink_to(real_candidate, target_is_directory=True)
        sentinel = real_candidate / "operator-sentinel"
        sentinel.write_bytes(b"candidate owner bytes\n")
        before = sentinel.read_bytes()

        for observation_kind in fixture.WORKSPACE_ORDER:
            with self.subTest(kind=observation_kind):
                raw, output = self.paths(observation_kind, "candidate-symlink")
                self.write_valid_raw(observation_kind, raw)

                with self.assertRaises(GATE.QualificationError):
                    self.create(observation_kind, raw=raw, output=output)

                self.assert_no_output(output)
                self.assertTrue(self.candidate.is_symlink())
                self.assertEqual(sentinel.read_bytes(), before)

    def test_concurrent_creators_have_exactly_one_winner_for_each_kind(self):
        contenders = 8
        for observation_kind in fixture.WORKSPACE_ORDER:
            with self.subTest(kind=observation_kind):
                raw, output = self.paths(observation_kind, "concurrent")
                original_raw = self.write_valid_raw(observation_kind, raw)
                barrier = threading.Barrier(contenders)

                def attempt():
                    barrier.wait(timeout=10)
                    try:
                        created = self.create(
                            observation_kind,
                            raw=raw,
                            output=output,
                        )
                    except GATE.QualificationError:
                        return "rejected", None
                    return "created", Path(created)

                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=contenders
                ) as executor:
                    outcomes = list(
                        executor.map(lambda _index: attempt(), range(contenders))
                    )

                winners = [path for status, path in outcomes if status == "created"]
                rejected = [
                    status for status, _path in outcomes if status == "rejected"
                ]
                self.assertEqual(winners, [output])
                self.assertEqual(len(rejected), contenders - 1)
                self.assertTrue(output.is_file())
                self.assertFalse(output.is_symlink())
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
                self.assertEqual(output.stat().st_nlink, 1)
                value = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(tuple(value), fixture.RECEIPT_KEYS)
                self.assertEqual(value["observation_kind"], observation_kind)
                self.assertEqual(
                    output.read_bytes(),
                    fixture.canonical_json_bytes(value),
                )
                self.assertEqual(raw.read_bytes(), original_raw)
                self.assertEqual(raw.stat().st_mode & 0o777, 0o600)
                self.assertEqual(raw.stat().st_nlink, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
