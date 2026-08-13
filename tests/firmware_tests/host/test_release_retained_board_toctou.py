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

        def race_after_board_consumption(*args, **kwargs):
            nonlocal raced
            command = [
                os.fspath(value)
                for value in (args[0] if args else kwargs.get("args", ()))
            ]
            completed = actual_run(*args, **kwargs)
            if (
                not raced
                and len(command) > 1
                and Path(command[1]).resolve() == makemanifest
                and "BOARD_DIR=%s" % retained_board in command
            ):
                # The real child has consumed BOARD_DIR, but subprocess.run has
                # not returned control to the auditor. A post-consumption tree
                # proof must catch this exact selected-copy drift.
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
        finally:
            retained_source.write_bytes(original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
