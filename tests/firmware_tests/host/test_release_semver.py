#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] BLD-12 — Release versions use canonical SemVer 2.0.0 syntax.

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "release_bundle.py"


def load_release_module():
    spec = importlib.util.spec_from_file_location(
        "pyble_release_semver_red",
        RELEASE_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load firmware release tool")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RELEASE = load_release_module()


def write_lock(root: Path, version: str) -> None:
    firmware = root / "firmware"
    firmware.mkdir()
    (firmware / "versions.lock").write_text(
        """
[micropython]
repo = "https://example.invalid/micropython"
ref = "v1.28.0"
commit = "1111111111111111111111111111111111111111"

[esp_idf]
repo = "https://example.invalid/esp-idf"
ref = "v5.5.1"
commit = "2222222222222222222222222222222222222222"

[pyble]
agent_version = "%s"
protocol_version = "PBLE/1"
"""
        % version,
        encoding="utf-8",
    )


class CanonicalReleaseSemverTests(unittest.TestCase):
    def assert_accepted(self, version: str) -> None:
        with tempfile.TemporaryDirectory(prefix="pyble-semver-") as temporary:
            root = Path(temporary)
            write_lock(root, version)
            self.assertEqual(
                RELEASE._read_lock(root)["pyble"]["agent_version"],
                version,
            )

    def assert_rejected(self, version: str) -> None:
        with tempfile.TemporaryDirectory(prefix="pyble-semver-") as temporary:
            root = Path(temporary)
            write_lock(root, version)
            with self.assertRaisesRegex(
                RELEASE.ReleaseError,
                r"(?i)canonical SemVer",
            ):
                RELEASE._read_lock(root)

    def test_canonical_semver_forms_are_accepted(self):
        for version in (
            "0.0.0",
            "1.2.3",
            "1.2.3-0",
            "1.2.3-alpha",
            "1.2.3-01a",
            "1.2.3-alpha.1",
            "1.2.3+build.01",
            "1.2.3-alpha.1+build.01",
        ):
            with self.subTest(version=version):
                self.assert_accepted(version)

    def test_noncanonical_semver_forms_are_rejected(self):
        for version in (
            "v1.2.3",
            "01.2.3",
            "1.02.3",
            "1.2.03",
            "1.2.3-",
            "1.2.3-01",
            "1.2.3-a..b",
            "1.2.3+",
            "1.2.3+foo..bar",
            "1.2.3_alpha",
            "1.2.3 ",
        ):
            with self.subTest(version=version):
                self.assert_rejected(version)


if __name__ == "__main__":
    unittest.main(verbosity=2)
