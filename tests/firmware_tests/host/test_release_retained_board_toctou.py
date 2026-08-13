#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] BLD-8 — Retained BOARD_DIR must remain stable through consumption.
#
# Frozen source:
#   docs/specifications/firmware/browser-flashing.md §6 rule 9

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest import mock


INTEGRATION_TEST = Path(__file__).with_name(
    "test_release_license_policy_v2_integration.py"
)


def load_integration_fixtures():
    spec = importlib.util.spec_from_file_location(
        "pyble_release_retained_board_toctou_fixtures",
        INTEGRATION_TEST,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load release-license integration fixtures")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


FIXTURES = load_integration_fixtures()
BASE = FIXTURES.BASE
RELEASE = FIXTURES.RELEASE
ObservationV2Fixture = FIXTURES.ObservationV2Fixture


@unittest.skipUnless(RELEASE is not None, "release_bundle.py is unavailable")
class RetainedBoardConsumptionRaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = ObservationV2Fixture()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.close()

    def test_rejects_retained_board_changed_before_makemanifest_returns(self):
        target = "esp32"
        board_name = RELEASE.FROZEN_TARGET_SETTINGS[target]["board"]
        retained_board = (
            self.fixture.build_root
            / ".sources"
            / target
            / "micropython"
            / "ports"
            / "esp32"
            / "boards"
            / board_name
        )
        retained_source = retained_board / "_boot.py"
        original = retained_source.read_bytes()
        makemanifest = (
            self.fixture.firmware
            / "upstream"
            / "micropython"
            / "tools"
            / "makemanifest.py"
        ).resolve()
        actual_run = RELEASE.subprocess.run
        raced = False
        consumed_board = None

        def race_after_board_consumption(*args, **kwargs):
            nonlocal consumed_board, raced
            command = [
                os.fspath(value)
                for value in (args[0] if args else kwargs.get("args", ()))
            ]
            completed = actual_run(*args, **kwargs)
            board_values = [
                value.removeprefix("BOARD_DIR=")
                for value in command
                if value.startswith("BOARD_DIR=")
            ]
            if not raced and len(command) > 1 and Path(command[1]).resolve() == makemanifest:
                self.assertEqual(len(board_values), 1)
                consumed_board = Path(board_values[0])
                self.assertEqual(
                    (consumed_board / "_boot.py").read_bytes(),
                    original,
                    "the private execution snapshot must contain the exact retained bytes",
                )
                # The real child has consumed its immutable BOARD_DIR snapshot,
                # but subprocess.run has not returned control to the auditor.
                # A post-consumption resnapshot of the original retained tree
                # must catch this exact selected-copy drift.
                retained_source.write_bytes(
                    original + b"# retained BOARD_DIR race\n"
                )
                raced = True
            return completed

        manifest = (
            self.fixture.firmware
            / "board_overlays"
            / target
            / "manifest.py"
        )
        frozen = self.fixture.build_root / target / "frozen_content.c"
        mpy_cross = (
            self.fixture.firmware
            / "upstream"
            / "micropython"
            / "mpy-cross"
            / "build"
            / "mpy-cross"
        )
        try:
            with mock.patch.object(
                RELEASE.subprocess,
                "run",
                side_effect=race_after_board_consumption,
            ):
                with self.assertRaisesRegex(
                    RELEASE.ReleaseError,
                    "retained generated board tree changed during audit",
                ):
                    RELEASE._audit_manifest_evidence_record(
                        manifest,
                        frozen,
                        repo_root=self.fixture.repo,
                        target=target,
                        trusted_mpy_cross_sha256=BASE.sha256_path(mpy_cross),
                    )
            self.assertTrue(
                raced,
                "the test did not reach the retained BOARD_DIR consumer",
            )
            self.assertIsNotNone(consumed_board)
            self.assertNotEqual(
                consumed_board.resolve(),
                retained_board.resolve(),
                "reconstruction must consume a private immutable snapshot, not the live retained tree",
            )
        finally:
            retained_source.write_bytes(original)

    def test_rejects_transient_parent_symlink_during_retained_capture(self):
        target = "esp32"
        board_name = RELEASE.FROZEN_TARGET_SETTINGS[target]["board"]
        retained_board = (
            self.fixture.build_root
            / ".sources"
            / target
            / "micropython"
            / "ports"
            / "esp32"
            / "boards"
            / board_name
        )
        real_parent = retained_board / "pyble"
        hidden_parent = retained_board / ".pyble-retained-race"
        leaf_name = "pyble_agent.py"
        leaf = real_parent / leaf_name
        decoy_parent = self.fixture.root / "retained-board-parent-decoy"
        decoy_parent.mkdir()
        # A hard link gives the decoy leaf the same device/inode, size, and
        # timestamps as the admitted file. Leaf-only O_NOFOLLOW plus before/
        # after fstat checks therefore cannot distinguish this parent swap.
        os.link(leaf, decoy_parent / leaf_name)

        actual_open = RELEASE.os.open
        raced = False
        unsafe_absolute_opens = []

        def fd_path(descriptor):
            for prefix in ("/proc/self/fd", "/dev/fd"):
                try:
                    return Path(os.readlink("%s/%d" % (prefix, descriptor))).resolve()
                except OSError:
                    continue
            return None

        def swap_parent_for_open(path, flags, *args, **kwargs):
            nonlocal raced
            raw = os.fspath(path)
            dir_fd = kwargs.get("dir_fd")
            raw_path = Path(raw)
            absolute_leaf = raw_path.is_absolute() and raw_path == leaf.absolute()
            if raw_path.is_absolute():
                try:
                    raw_path.relative_to(retained_board.absolute())
                except ValueError:
                    pass
                else:
                    unsafe_absolute_opens.append(raw_path)
            descriptor_parent = (
                raw == "pyble"
                and dir_fd is not None
                and fd_path(dir_fd) == retained_board.resolve()
            )
            if raced or not (absolute_leaf or descriptor_parent):
                return actual_open(path, flags, *args, **kwargs)

            real_parent.rename(hidden_parent)
            real_parent.symlink_to(decoy_parent, target_is_directory=True)
            raced = True
            try:
                return actual_open(path, flags, *args, **kwargs)
            finally:
                real_parent.unlink()
                hidden_parent.rename(real_parent)

        manifest = (
            self.fixture.firmware
            / "board_overlays"
            / target
            / "manifest.py"
        )
        frozen = self.fixture.build_root / target / "frozen_content.c"
        mpy_cross = (
            self.fixture.firmware
            / "upstream"
            / "micropython"
            / "mpy-cross"
            / "build"
            / "mpy-cross"
        )
        try:
            with mock.patch.object(RELEASE.os, "open", side_effect=swap_parent_for_open):
                with self.assertRaises(RELEASE.ReleaseError):
                    RELEASE._audit_manifest_evidence_record(
                        manifest,
                        frozen,
                        repo_root=self.fixture.repo,
                        target=target,
                        trusted_mpy_cross_sha256=BASE.sha256_path(mpy_cross),
                    )
            self.assertTrue(
                raced,
                "the test did not race a retained BOARD_DIR parent component",
            )
            self.assertEqual(
                unsafe_absolute_opens,
                [],
                "retained BOARD_DIR components must be opened descriptor-relatively",
            )
        finally:
            if real_parent.is_symlink():
                real_parent.unlink()
            if hidden_parent.exists():
                hidden_parent.rename(real_parent)
            shutil.rmtree(decoy_parent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
