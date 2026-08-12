# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""Repository-level firmware agent version contract (BLD-12/13)."""

from __future__ import annotations

import json
import pathlib
import tomllib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
LOCK_PATH = ROOT / "firmware" / "versions.lock"
PACKAGE_PATH = ROOT / "firmware" / "pyble" / "__init__.py"
HISTORICAL_RECORD = (
    ROOT / "docs" / "validation" / "browser-flashing"
    / "v0.4.2-production.json"
)
CURRENT_VERSION = "0.6.0"


class AgentVersionLockTests(unittest.TestCase):
    def test_current_source_identity_is_selected_once_in_the_lock(self) -> None:
        lock = tomllib.loads(LOCK_PATH.read_text(encoding="utf-8"))
        self.assertEqual(lock["pyble"]["agent_version"], CURRENT_VERSION)

    def test_portable_runtime_uses_the_generated_version_module(self) -> None:
        source = PACKAGE_PATH.read_text(encoding="utf-8")
        self.assertIn("_version.AGENT_VERSION", source)
        self.assertNotIn(CURRENT_VERSION, source)

    def test_historical_v042_validation_record_is_not_relabelled(self) -> None:
        record = json.loads(HISTORICAL_RECORD.read_text(encoding="utf-8"))
        self.assertEqual(record["release"]["version"], "0.4.2")


if __name__ == "__main__":
    unittest.main()
