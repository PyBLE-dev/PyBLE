#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] X-10/X-11 — Pre-policy OI-1 baseline-input staging contract.
#
# Frozen source:
#   docs/specifications/firmware/browser-flashing.md §2 (FROZEN v1.25)
#
# This suite deliberately uses synthetic release inputs in temporary Git
# checkouts. It never reads, writes, or publishes a local firmware build.

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import test_release_bundle as bundle_fixture
import test_release_hardening as hardening_fixture


RELEASE = bundle_fixture.RELEASE
RELEASE_LOAD_ERROR = bundle_fixture.RELEASE_LOAD_ERROR
HAVE_RELEASE = RELEASE is not None
RELEASE_SCRIPT = bundle_fixture.RELEASE_SCRIPT
TARGETS = (
    "esp32",
    "esp32-s3",
    "waveshare-esp32-s3-lcd-147b",
    "esp32-c3",
)
PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
    "waveshare-esp32-s3-lcd-147b",
)
EXPECTED_FILES = {
    "%s/%s" % (profile_id, filename)
    for profile_id in PROFILE_ORDER
    for filename in (
        "manifest.json",
        "firmware.bin",
        "application.bin",
        "partition-table.bin",
    )
}


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", os.fspath(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "git -C %s %s failed:\n%s\n%s"
            % (
                repo,
                " ".join(args),
                completed.stdout,
                completed.stderr,
            )
        )
    return completed.stdout.strip()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _remove_policy_and_rebind_source(
    fixture: hardening_fixture.ActualCheckoutFixture,
) -> None:
    """Make the proof checkout a clean source state before the first policy."""

    policy_path = (
        fixture.repo
        / bundle_fixture.QUALIFICATION_POLICY_RELATIVE
    )
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    baseline_path = fixture.repo / policy["baseline_evidence"]["path"]
    policy_path.unlink()
    baseline_path.unlink()
    _git(fixture.repo, "add", "-A")
    _git(
        fixture.repo,
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "pre-policy baseline fixture",
    )

    fixture.pyble_commit = _git(fixture.repo, "rev-parse", "HEAD")
    fixture.source_date_epoch = int(
        _git(
            fixture.repo,
            "show",
            "-s",
            "--format=%ct",
            fixture.pyble_commit,
        )
    )
    for target in TARGETS:
        provenance_path = (
            fixture.release_fixture.build_root
            / target
            / "pyble-build-provenance.json"
        )
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        provenance["source_date_epoch"] = fixture.source_date_epoch
        provenance["pyble"]["commit"] = fixture.pyble_commit
        _write_json(provenance_path, provenance)

    if policy_path.exists() or baseline_path.exists():
        raise AssertionError("pre-policy fixture retained qualification inputs")
    if _git(fixture.repo, "status", "--porcelain"):
        raise AssertionError("pre-policy proof checkout is dirty")
    if _git(fixture.repo, "tag", "--list"):
        raise AssertionError("pre-policy proof checkout unexpectedly has a tag")


def _rebind_build_root(build_root: Path) -> None:
    """Bind copied project descriptions to their actual retained root."""

    for target in TARGETS:
        description_path = build_root / target / "project_description.json"
        description = json.loads(description_path.read_text(encoding="utf-8"))
        description["build_dir"] = os.fspath(build_root / target)
        description["project_path"] = os.fspath(
            build_root
            / ".sources"
            / target
            / "micropython"
            / "ports"
            / "esp32"
        )
        _write_json(description_path, description)


class BaselineInputFixture:
    """Two actual-checkout-bound clean roots with no OI-1 policy/evidence."""

    def __init__(self) -> None:
        self.actual = hardening_fixture.ActualCheckoutFixture()
        _remove_policy_and_rebind_source(self.actual)
        self.repo = self.actual.repo
        self.primary = self.actual.release_fixture.build_root
        self.second = self.actual.release_fixture.root / "baseline-second-build"
        shutil.copytree(self.primary, self.second)
        _rebind_build_root(self.second)
        self.output = self.actual.release_fixture.root / "baseline-inputs"

    def assert_roots_are_valid_and_reproducible(self) -> None:
        RELEASE.compare_build_roots(
            self.primary,
            self.second,
            repo_root=self.repo,
        )

    def create(self, output: Path | None = None) -> Path:
        function = getattr(RELEASE, "create_baseline_inputs", None)
        if function is None:
            raise AssertionError(
                "[red] release_bundle.create_baseline_inputs is missing"
            )
        return Path(
            function(
                build_root=self.primary,
                reproducibility_build_root=self.second,
                output_dir=self.output if output is None else output,
                repo_root=self.repo,
            )
        )

    def cleanup(self) -> None:
        self.actual.cleanup()


class BaselineInputsProductionGateTest(unittest.TestCase):
    def test_release_tool_exposes_baseline_inputs_api_and_cli(self) -> None:
        self.assertIsNotNone(RELEASE, RELEASE_LOAD_ERROR)
        if RELEASE is None:
            return
        self.assertTrue(
            hasattr(RELEASE, "create_baseline_inputs"),
            "[red] release_bundle.py must expose create_baseline_inputs",
        )

        completed = subprocess.run(
            [
                sys.executable,
                os.fspath(RELEASE_SCRIPT),
                "create-baseline-inputs",
                "--help",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for token in (
            "build_root",
            "output_dir",
            "--reproducibility-build-root",
            "--repo-root",
        ):
            with self.subTest(help_token=token):
                self.assertIn(token, completed.stdout)

    def test_baseline_inputs_cli_requires_both_proof_roots(self) -> None:
        required = {
            "--reproducibility-build-root": "/second-build",
            "--repo-root": "/repo",
        }
        for missing in required:
            with self.subTest(missing=missing):
                arguments = [
                    sys.executable,
                    os.fspath(RELEASE_SCRIPT),
                    "create-baseline-inputs",
                    "/primary-build",
                    "/output",
                ]
                for option, value in required.items():
                    if option != missing:
                        arguments.extend((option, value))
                completed = subprocess.run(
                    arguments,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(missing, completed.stderr)


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class BaselineInputsCreationTests(unittest.TestCase):
    def test_creates_exact_pre_policy_three_profile_measurement_tree(self) -> None:
        fixture = BaselineInputFixture()
        try:
            fixture.assert_roots_are_valid_and_reproducible()
            manifest_function = RELEASE._manifest
            with mock.patch.object(
                RELEASE,
                "_manifest",
                side_effect=manifest_function,
            ) as manifest_spy:
                output = fixture.create()

            self.assertEqual(output, fixture.output)
            self.assertTrue(output.is_dir())
            actual_files = {
                path.relative_to(output).as_posix()
                for path in output.rglob("*")
                if path.is_file()
            }
            self.assertEqual(actual_files, EXPECTED_FILES)
            self.assertEqual(
                {
                    path.relative_to(output).as_posix()
                    for path in output.iterdir()
                    if path.is_dir()
                },
                set(PROFILE_ORDER),
            )
            self.assertFalse((output / "esp32-c3-4mb").exists())

            manifest_calls = [
                call.args
                for call in manifest_spy.call_args_list
                if len(call.args) == 2
            ]
            for expected in (
                ("0.5.0", "esp32-4mb"),
                ("0.5.0", "esp32-s3-n16r8"),
                ("0.5.0", "waveshare-esp32-s3-lcd-147b"),
            ):
                self.assertIn(
                    expected,
                    manifest_calls,
                    "baseline staging must delegate to the production "
                    "manifest generator",
                )

            for profile_id in PROFILE_ORDER:
                with self.subTest(profile=profile_id):
                    spec = bundle_fixture.PROFILE_SPECS[profile_id]
                    source = fixture.primary / spec["target"]
                    profile = output / profile_id
                    expected_manifest = (
                        json.dumps(
                            bundle_fixture.exact_manifest(
                                "0.5.0",
                                profile_id,
                            ),
                            indent=2,
                            sort_keys=False,
                        )
                        + "\n"
                    ).encode("utf-8")
                    self.assertEqual(
                        (profile / "manifest.json").read_bytes(),
                        expected_manifest,
                    )
                    self.assertEqual(
                        (profile / "firmware.bin").read_bytes(),
                        (source / "firmware.bin").read_bytes(),
                    )
                    self.assertEqual(
                        (profile / "application.bin").read_bytes(),
                        (source / "micropython.bin").read_bytes(),
                    )
                    self.assertEqual(
                        (profile / "partition-table.bin").read_bytes(),
                        (
                            source
                            / "partition_table"
                            / "partition-table.bin"
                        ).read_bytes(),
                    )

            for path in (output, *output.rglob("*")):
                with self.subTest(access_control=path.relative_to(output)):
                    mode = path.lstat().st_mode
                    self.assertFalse(stat.S_ISLNK(mode))
                    self.assertEqual(
                        stat.S_IMODE(mode) & 0o077,
                        0,
                        "baseline measurement inputs must not be group/world "
                        "accessible",
                    )
        finally:
            fixture.cleanup()

    def test_cli_dispatches_pre_policy_baseline_creation(self) -> None:
        fixture = BaselineInputFixture()
        try:
            fixture.assert_roots_are_valid_and_reproducible()
            output = fixture.actual.release_fixture.root / "cli-baseline-inputs"
            completed = subprocess.run(
                [
                    sys.executable,
                    os.fspath(RELEASE_SCRIPT),
                    "create-baseline-inputs",
                    os.fspath(fixture.primary),
                    os.fspath(output),
                    "--reproducibility-build-root",
                    os.fspath(fixture.second),
                    "--repo-root",
                    os.fspath(fixture.repo),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), os.fspath(output))
            self.assertEqual(
                {
                    path.relative_to(output).as_posix()
                    for path in output.rglob("*")
                    if path.is_file()
                },
                EXPECTED_FILES,
            )
        finally:
            fixture.cleanup()

    def test_existing_output_is_immutable_and_unchanged(self) -> None:
        fixture = BaselineInputFixture()
        try:
            fixture.output.mkdir()
            sentinel = fixture.output / "keep.txt"
            sentinel.write_bytes(b"existing output must survive\n")
            before = {
                path.relative_to(fixture.output).as_posix(): path.read_bytes()
                for path in fixture.output.rglob("*")
                if path.is_file()
            }
            with self.assertRaisesRegex(
                RELEASE.ReleaseError,
                r"(?i)(already exists|immutable|no.replace|output)",
            ):
                fixture.create()
            after = {
                path.relative_to(fixture.output).as_posix(): path.read_bytes()
                for path in fixture.output.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)
        finally:
            fixture.cleanup()

    def test_transient_source_mutation_during_copy_publishes_nothing(
        self,
    ) -> None:
        fixture = BaselineInputFixture()
        try:
            source = fixture.primary / "esp32" / "firmware.bin"
            original = source.read_bytes()
            original_copy = RELEASE.shutil.copyfile
            mutation_was_copied = False

            def copy_transient_mutation(
                copy_source: str | os.PathLike[str],
                destination: str | os.PathLike[str],
                *args: object,
                **kwargs: object,
            ) -> str | os.PathLike[str]:
                nonlocal mutation_was_copied
                if Path(copy_source) == source and not mutation_was_copied:
                    mutation_was_copied = True
                    source.write_bytes(original + b"\0transient-copy-mutation")
                    try:
                        return original_copy(
                            copy_source,
                            destination,
                            *args,
                            **kwargs,
                        )
                    finally:
                        source.write_bytes(original)
                return original_copy(
                    copy_source,
                    destination,
                    *args,
                    **kwargs,
                )

            with mock.patch.object(
                RELEASE.shutil,
                "copyfile",
                side_effect=copy_transient_mutation,
            ):
                with self.assertRaisesRegex(
                    RELEASE.ReleaseError,
                    r"(?i)(baseline|staged|source|build|copy|mismatch|changed)",
                ):
                    fixture.create()

            self.assertTrue(
                mutation_was_copied,
                "the adversarial mutation did not reach the staged image",
            )
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(
                fixture.output.exists(),
                "a transiently corrupted staging tree must not be published",
            )
        finally:
            fixture.cleanup()

    def test_same_or_nested_build_roots_fail_closed(self) -> None:
        for relation in ("same", "nested"):
            with self.subTest(relation=relation):
                fixture = BaselineInputFixture()
                try:
                    if relation == "same":
                        fixture.second = fixture.primary
                    else:
                        nested = fixture.primary / "nested-second-build"
                        fixture.second.rename(nested)
                        fixture.second = nested
                        _rebind_build_root(fixture.second)
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        r"(?i)(distinct|same|nested|overlap|root)",
                    ):
                        fixture.create()
                    self.assertFalse(fixture.output.exists())
                finally:
                    fixture.cleanup()

    def test_reproducibility_or_retained_source_failure_publishes_nothing(
        self,
    ) -> None:
        for mutation in ("different-bytes", "missing-c3-retained-source"):
            with self.subTest(mutation=mutation):
                fixture = BaselineInputFixture()
                try:
                    if mutation == "different-bytes":
                        target = "esp32-s3"
                        elf = fixture.second / target / "micropython.elf"
                        elf.write_bytes(elf.read_bytes() + b"\0different-root")
                        bundle_fixture.rebind_fixture_application_to_elf(
                            fixture.second / target,
                            bundle_fixture.PROFILE_SPECS[
                                "esp32-s3-n16r8"
                            ],
                        )
                    else:
                        shutil.rmtree(
                            fixture.second
                            / ".sources"
                            / "esp32-c3"
                            / "micropython"
                        )

                    output_parent = fixture.output.parent
                    before = {
                        path.name
                        for path in output_parent.iterdir()
                    }
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        r"(?i)(reproduc|mismatch|source|checkout|missing|path)",
                    ):
                        fixture.create()
                    self.assertFalse(fixture.output.exists())
                    self.assertEqual(
                        {path.name for path in output_parent.iterdir()},
                        before,
                        "failed staging must remove every temporary output",
                    )
                finally:
                    fixture.cleanup()


if __name__ == "__main__":
    unittest.main()
