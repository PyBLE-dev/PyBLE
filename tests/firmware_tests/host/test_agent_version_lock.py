# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""Repository-level firmware agent version contract (BLD-12/13)."""

from __future__ import annotations

import ast
import pathlib
import tomllib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
LOCK_PATH = ROOT / "firmware" / "versions.lock"
PACKAGE_PATH = ROOT / "firmware" / "pyble" / "__init__.py"
BASELINE_VERSION = "0.4.2"


def _package_version() -> str:
    tree = ast.parse(PACKAGE_PATH.read_text(encoding="utf-8"), filename=str(PACKAGE_PATH))
    values = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets):
            if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
                raise AssertionError("pyble.__version__ must be one literal string")
            values.append(node.value.value)
    if len(values) != 1:
        raise AssertionError("firmware/pyble/__init__.py must assign __version__ exactly once")
    return values[0]


class AgentVersionLockTests(unittest.TestCase):
    def test_runtime_version_equals_the_canonical_release_lock(self) -> None:
        lock = tomllib.loads(LOCK_PATH.read_text(encoding="utf-8"))
        self.assertEqual(_package_version(), lock["pyble"]["agent_version"])

    def test_public_baseline_selects_v042(self) -> None:
        lock = tomllib.loads(LOCK_PATH.read_text(encoding="utf-8"))
        self.assertEqual(lock["pyble"]["agent_version"], BASELINE_VERSION)


if __name__ == "__main__":
    unittest.main()
