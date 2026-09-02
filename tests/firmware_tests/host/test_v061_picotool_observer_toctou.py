#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED races for the retained-picotool release observer.

The observer must bind one no-follow, descriptor-anchored distribution across
archive validation, installed-tree validation, the runtime version probe, and
the final evidence receipt.  These tests inject deterministic mutations at
the version-probe boundary.  A pre-probe path walk alone is not sufficient:
the observer must reopen and revalidate the exact archive and installed tree
after the probe before accepting the observation.

All bytes in this suite are synthetic.  The tests perform no network access,
firmware build, legal review, or physical release qualification.
"""

from __future__ import annotations

import copy
import hashlib
import os
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import test_v061_picotool_license_admission as admission_fixture


RELEASE = admission_fixture.RELEASE
RELEASE_LOAD_ERROR = admission_fixture.RELEASE_LOAD_ERROR

VERSION_LINE = "picotool v9.8.7 (synthetic observer fixture)"
ORIGINAL_TOOL = (
    b"#!/bin/sh\n"
    b"printf '%s\\n' 'picotool v9.8.7 (synthetic observer fixture)'\n"
)
CHANGED_TOOL = (
    b"#!/bin/sh\n"
    b"# Bytes substituted only after the trusted-tree check.\n"
    b"printf '%s\\n' 'picotool v9.8.7 (synthetic observer fixture)'\n"
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class PicotoolObserverRaceFixture:
    """Construct the smallest exact archive/install pair the observer accepts."""

    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="pyble-v061-picotool-observer-toctou-red-"
        )
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.build = self.root / "build"
        self.install = self.repo / "firmware" / ".picotool"
        self.distribution = self.install / ".pyble-dist"
        self.tool_directory = self.install / "picotool"
        self.executable = self.tool_directory / "picotool"
        self.archive = self.distribution / "picotool-synthetic.zip"
        self.repo.mkdir()
        self.build.mkdir()
        self.distribution.mkdir(parents=True)
        self.tool_directory.mkdir()
        self.install.chmod(0o755)
        self.distribution.chmod(0o755)
        self.tool_directory.chmod(0o755)
        self.executable.write_bytes(ORIGINAL_TOOL)
        self.executable.chmod(0o755)

        directory = zipfile.ZipInfo("picotool/")
        directory.create_system = 3
        directory.external_attr = (stat.S_IFDIR | 0o755) << 16
        executable = zipfile.ZipInfo("picotool/picotool")
        executable.create_system = 3
        executable.external_attr = (stat.S_IFREG | 0o755) << 16
        with zipfile.ZipFile(
            self.archive,
            "w",
            compression=zipfile.ZIP_STORED,
        ) as archive:
            archive.writestr(directory, b"")
            archive.writestr(executable, ORIGINAL_TOOL)
        self.archive.chmod(0o644)
        archive_bytes = self.archive.read_bytes()

        empty_sha256 = _sha256(b"")
        self.members = [
            {
                "path": "picotool/",
                "kind": "directory",
                "mode": "040755",
                "bytes": 0,
                "sha256": empty_sha256,
            },
            {
                "path": "picotool/picotool",
                "kind": "regular",
                "mode": "100755",
                "bytes": len(ORIGINAL_TOOL),
                "sha256": _sha256(ORIGINAL_TOOL),
            },
        ]
        self.archive_logical = (
            "firmware/.picotool/.pyble-dist/picotool-synthetic.zip"
        )
        self.lock = {
            "archive_bytes": len(archive_bytes),
            "archive_filename": self.archive.name,
            "executable_path": "picotool/picotool",
            "sha256": _sha256(archive_bytes),
            "version_line": VERSION_LINE,
        }
        self.policy = {
            "source_owners": [],
            "distribution_provenance": {
                "member_inventory": copy.deepcopy(self.members),
                "retained_archive": {
                    "path": self.archive_logical,
                },
            },
        }

    def close(self) -> None:
        self.temporary.cleanup()

    def expect_probe_boundary_mutation_rejected(self, mutate) -> None:
        """Run a synchronized mutation and require post-probe rejection."""

        observer = RELEASE._audit_observe_rp2_build_tools_license_inputs
        real_archive_inventory = RELEASE._audit_picotool_archive_inventory
        real_tree_validation = RELEASE._audit_picotool_installed_tree
        probe_calls = 0

        def version_probe(args, **_kwargs):
            nonlocal probe_calls
            if probe_calls == 0:
                mutate()
            probe_calls += 1
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=VERSION_LINE + "\n",
                stderr="",
            )

        with mock.patch.object(
            RELEASE,
            "_read_lock",
            return_value={"picotool": copy.deepcopy(self.lock)},
        ), mock.patch.object(
            RELEASE,
            "_validate_v061_picotool_lock",
            side_effect=lambda value, _label: copy.deepcopy(value),
        ), mock.patch.object(
            RELEASE,
            "_audit_validate_rp2_build_tools_license_policy",
            return_value=copy.deepcopy(self.policy),
        ), mock.patch.object(
            RELEASE,
            "_audit_rp2_logical_file",
            return_value=(self.archive_logical, self.archive),
        ), mock.patch.object(
            RELEASE,
            "_audit_picotool_archive_inventory",
            wraps=real_archive_inventory,
        ) as archive_validation, mock.patch.object(
            RELEASE,
            "_audit_picotool_installed_tree",
            wraps=real_tree_validation,
        ) as tree_validation, mock.patch.object(
            RELEASE,
            "_audit_expected_rp2_build_tools_role",
            return_value=(
                {"synthetic/input": "0" * 64},
                {"schema_version": 1, "role": "build-tools"},
            ),
        ), mock.patch.object(
            RELEASE.subprocess,
            "run",
            side_effect=version_probe,
        ):
            try:
                observer(
                    build_root=self.build,
                    repo_root=self.repo,
                    provenance={"synthetic": True},
                    policy=copy.deepcopy(self.policy),
                )
            except RELEASE.ReleaseError:
                self._assert_preflight_and_probe_ran(
                    archive_validation,
                    tree_validation,
                    probe_calls,
                )
                return

        self._assert_preflight_and_probe_ran(
            archive_validation,
            tree_validation,
            probe_calls,
        )
        raise AssertionError(
            "[red] retained-picotool observer accepted bytes/path identity "
            "changed at the runtime version-probe boundary"
        )

    def _assert_preflight_and_probe_ran(
        self,
        archive_validation,
        tree_validation,
        probe_calls: int,
    ) -> None:
        if archive_validation.call_count < 1:
            raise AssertionError(
                "fixture failed before exact retained-archive validation"
            )
        if tree_validation.call_count < 1:
            raise AssertionError(
                "fixture failed before exact installed-tree validation"
            )
        if probe_calls < 1:
            raise AssertionError(
                "fixture failed before the synchronized runtime version probe"
            )


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class V061PicotoolObserverToctouTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = PicotoolObserverRaceFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_rejects_in_place_executable_mutation_during_version_probe(self):
        def mutate() -> None:
            self.fixture.executable.write_bytes(CHANGED_TOOL)
            self.fixture.executable.chmod(0o755)

        self.fixture.expect_probe_boundary_mutation_rejected(mutate)

    def test_rejects_atomic_executable_replacement_during_version_probe(self):
        replacement = self.fixture.root / "replacement-picotool"
        replacement.write_bytes(CHANGED_TOOL)
        replacement.chmod(0o755)

        def mutate() -> None:
            os.replace(replacement, self.fixture.executable)

        self.fixture.expect_probe_boundary_mutation_rejected(mutate)

    def test_rejects_symlinked_parent_component_during_version_probe(self):
        checked_directory = self.fixture.root / "checked-picotool-directory"
        substituted_directory = self.fixture.root / "substituted-picotool-directory"
        substituted_directory.mkdir(mode=0o755)
        substituted_executable = substituted_directory / "picotool"
        substituted_executable.write_bytes(CHANGED_TOOL)
        substituted_executable.chmod(0o755)

        def mutate() -> None:
            os.replace(self.fixture.tool_directory, checked_directory)
            os.symlink(substituted_directory, self.fixture.tool_directory)

        self.fixture.expect_probe_boundary_mutation_rejected(mutate)

    def test_rejects_retained_archive_mutation_during_version_probe(self):
        def mutate() -> None:
            self.fixture.archive.write_bytes(b"changed after archive validation\n")
            self.fixture.archive.chmod(0o644)

        self.fixture.expect_probe_boundary_mutation_rejected(mutate)


if __name__ == "__main__":
    unittest.main(verbosity=2)
