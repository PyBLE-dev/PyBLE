#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] BLD-8 — One role observation must bind one directory identity.

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import stat
import sys
import unittest
from unittest import mock


INTEGRATION_TEST = Path(__file__).with_name(
    "test_release_license_policy_v2_integration.py"
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot construct import spec for %s" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


FIXTURES = load_module(
    "pyble_release_ninja_role_identity_race_fixtures",
    INTEGRATION_TEST,
)
RELEASE = FIXTURES.RELEASE


def tree_bytes(root: Path) -> dict[str, tuple[str, bytes | str | None]]:
    """Describe names and payload bytes without following tree symlinks."""

    snapshot: dict[str, tuple[str, bytes | str | None]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            snapshot[relative] = ("symlink", os.readlink(path))
        elif stat.S_ISDIR(mode):
            snapshot[relative] = ("directory", None)
        elif stat.S_ISREG(mode):
            snapshot[relative] = ("file", path.read_bytes())
        else:
            raise AssertionError("unexpected fixture entry: %s" % path)
    return snapshot


@unittest.skipUnless(RELEASE is not None, "release_bundle.py is unavailable")
class NinjaRoleDirectoryIdentityRaceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FIXTURES.ObservationV2Fixture()

    def tearDown(self):
        self.fixture.close()

    def test_full_observer_rejects_whole_role_replacement_before_ninja_replay(
        self,
    ) -> None:
        role_root = self.fixture.build_root / "esp32"
        replacement = self.fixture.root / "replacement-esp32-role"
        displaced = self.fixture.root / "displaced-esp32-role"
        consumed = self.fixture.root / "consumed-esp32-role"

        before = role_root.lstat()
        before_identity = (before.st_dev, before.st_ino)
        before_bytes = tree_bytes(role_root)
        shutil.copytree(
            role_root,
            replacement,
            symlinks=True,
            copy_function=shutil.copy2,
        )
        replacement_stat = replacement.lstat()
        replacement_identity = (
            replacement_stat.st_dev,
            replacement_stat.st_ino,
        )
        self.assertNotEqual(replacement_identity, before_identity)
        self.assertEqual(tree_bytes(replacement), before_bytes)

        original_link_audit = RELEASE._audit_ninja_link_command_evidence
        race_fired = False
        rejection: RELEASE.ReleaseError | None = None

        def replace_role_before_link_replay(*args, **kwargs):
            nonlocal race_fired
            audited_role = Path(kwargs["role_build"])
            if audited_role == role_root and not race_fired:
                # The full observer has already read this role's project,
                # compile, and map evidence before it enters this seam.
                role_root.rename(displaced)
                try:
                    replacement.rename(role_root)
                except BaseException:
                    displaced.rename(role_root)
                    raise
                race_fired = True
                visible = role_root.lstat()
                self.assertEqual(
                    (visible.st_dev, visible.st_ino),
                    replacement_identity,
                )
                self.assertEqual(tree_bytes(role_root), before_bytes)
            return original_link_audit(*args, **kwargs)

        try:
            with mock.patch.object(
                RELEASE,
                "_audit_ninja_link_command_evidence",
                side_effect=replace_role_before_link_replay,
            ):
                try:
                    RELEASE._audit_observe_policy_v2_context(
                        self.fixture.policy,
                        repo_root=self.fixture.repo,
                        build_root=self.fixture.build_root,
                    )
                except RELEASE.ReleaseError as exc:
                    rejection = exc
        finally:
            if displaced.exists():
                if role_root.exists():
                    role_root.rename(consumed)
                displaced.rename(role_root)
            if consumed.exists():
                shutil.rmtree(consumed)
            if replacement.exists():
                shutil.rmtree(replacement)

        self.assertTrue(race_fired, "the whole-role replacement race did not fire")
        self.assertEqual(
            (role_root.lstat().st_dev, role_root.lstat().st_ino),
            before_identity,
            "the original role directory identity was not restored",
        )
        self.assertEqual(tree_bytes(role_root), before_bytes)
        self.assertIsNotNone(
            rejection,
            "the full observer accepted one role assembled from distinct "
            "directory identities",
        )


if __name__ == "__main__":
    unittest.main()
