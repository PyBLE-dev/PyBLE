#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] X-10/X-11 — Mechanical OI-1 baseline/policy and completed-HIL
# evidence assembly.
#
# Frozen source:
#   docs/specifications/firmware/browser-flashing.md v1.27 §§2, 9

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import test_release_bundle as bundle_fixture
import test_release_finalization as finalization_fixture


RELEASE = bundle_fixture.RELEASE
RELEASE_LOAD_ERROR = bundle_fixture.RELEASE_LOAD_ERROR
HAVE_RELEASE = RELEASE is not None
HAVE_BASELINE_ASSEMBLER = HAVE_RELEASE and callable(
    getattr(RELEASE, "assemble_oi1_baseline", None)
)
HAVE_HIL_ASSEMBLER = HAVE_RELEASE and callable(
    getattr(RELEASE, "assemble_completed_hil_report", None)
)
PROFILE_ORDER = ("esp32-4mb", "esp32-s3-n16r8")
OPERATOR_CHECKS = {
    "browser_erase_install",
    "family_offsets_reset",
    "advertising_info_hello",
    "app_workflow",
    "neopixel_reboot",
    "interrupted_flash_recovery",
}
COMPLETION_KEYS = {
    "profile_id",
    "board_manufacturer",
    "board_model",
    "module_marking",
    "device_flash_capacity_bytes",
    "device_psram_capacity_bytes",
    "tested_at",
    "operator",
    "maintainer_signoff",
    "desktop_os",
    "chromium_version",
    "ble_backend",
    "ble_adapter",
    "python_version",
    "checks",
    "oi1_observation",
    "redacted_console_log",
}


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", os.fspath(repo), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "git %s failed:\n%s\n%s"
            % (" ".join(arguments), completed.stdout, completed.stderr)
        )
    return completed.stdout.strip()


def write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value))


class BaselineAssemblyFixture:
    def __init__(self) -> None:
        self.release_fixture = bundle_fixture.ReleaseFixture()
        self.repo = self.release_fixture.repo
        self.root = self.release_fixture.root
        self.inputs = self.root / "baseline-inputs"
        self.inputs.mkdir(mode=0o700)
        self.fragments: list[Path] = []

        existing_policy = json.loads(
            self.release_fixture.qualification_policy_path.read_text(encoding="utf-8")
        )
        existing_baseline = json.loads(
            (self.repo / existing_policy["baseline_evidence"]["path"]).read_text(
                encoding="utf-8"
            )
        )
        profiles = {
            profile["profile_id"]: profile for profile in existing_baseline["profiles"]
        }
        for profile_id in PROFILE_ORDER:
            spec = bundle_fixture.PROFILE_SPECS[profile_id]
            source = self.release_fixture.build_root / spec["target"]
            destination = self.inputs / profile_id
            destination.mkdir(mode=0o700)
            manifest = (
                json.dumps(
                    bundle_fixture.exact_manifest("0.4.1", profile_id),
                    indent=2,
                    sort_keys=False,
                )
                + "\n"
            ).encode("utf-8")
            (destination / "manifest.json").write_bytes(manifest)
            shutil.copyfile(source / "firmware.bin", destination / "firmware.bin")
            shutil.copyfile(
                source / "micropython.bin",
                destination / "application.bin",
            )
            shutil.copyfile(
                source / "partition_table" / "partition-table.bin",
                destination / "partition-table.bin",
            )
            for path in destination.iterdir():
                path.chmod(0o600)

            fragment = self.root / (profile_id + "-baseline.json")
            write_json(fragment, profiles[profile_id])
            self.fragments.append(fragment)

        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.name", "PyBLE Fixture")
        git(self.repo, "config", "user.email", "fixture@pyble.dev")
        git(self.repo, "add", ".")
        git(
            self.repo,
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "fixture baseline source",
        )
        self.source_commit = git(self.repo, "rev-parse", "HEAD")
        self.created_at = "2026-07-31T12:00:00Z"
        self.baseline_path = (
            self.repo
            / "docs"
            / "validation"
            / "firmware"
            / "oi1"
            / (self.source_commit + ".json")
        )
        self.policy_path = self.repo / bundle_fixture.QUALIFICATION_POLICY_RELATIVE
        self.original_policy = self.policy_path.read_bytes()

    def assemble(self):
        return RELEASE.assemble_oi1_baseline(
            baseline_inputs_dir=self.inputs,
            profile_fragment_paths=list(reversed(self.fragments)),
            repo_root=self.repo,
            created_at=self.created_at,
        )

    def close(self) -> None:
        self.release_fixture.cleanup()


def completion_fragment(record: dict) -> dict:
    fragment = {
        key: copy.deepcopy(record[key]) for key in COMPLETION_KEYS if key != "checks"
    }
    fragment["checks"] = {key: record["checks"][key] for key in sorted(OPERATOR_CHECKS)}
    return fragment


class ReleaseEvidenceAssemblySeamTests(unittest.TestCase):
    def test_exact_production_apis_exist(self) -> None:
        self.assertIsNotNone(RELEASE, RELEASE_LOAD_ERROR)
        if RELEASE is None:
            return
        baseline = getattr(RELEASE, "assemble_oi1_baseline", None)
        hil = getattr(RELEASE, "assemble_completed_hil_report", None)
        self.assertTrue(
            callable(baseline),
            "[red] release_bundle.assemble_oi1_baseline is missing",
        )
        self.assertTrue(
            callable(hil),
            "[red] release_bundle.assemble_completed_hil_report is missing",
        )
        if callable(baseline):
            self.assertEqual(
                set(inspect.signature(baseline).parameters),
                {
                    "baseline_inputs_dir",
                    "profile_fragment_paths",
                    "repo_root",
                    "created_at",
                },
            )
        if callable(hil):
            self.assertEqual(
                set(inspect.signature(hil).parameters),
                {
                    "candidate_dir",
                    "profile_evidence_paths",
                    "output_path",
                    "qualification_repo_root",
                },
            )

    def test_exact_cli_commands_exist_without_manual_identity_fields(self) -> None:
        for command, required, forbidden in (
            (
                "assemble-oi1-baseline",
                (
                    "baseline_inputs_dir",
                    "profile_fragment_paths",
                    "--repo-root",
                    "--created-at",
                ),
                ("--source-commit", "--firmware-version"),
            ),
            (
                "assemble-hil-report",
                (
                    "candidate_dir",
                    "profile_evidence_paths",
                    "output_path",
                    "--qualification-repo-root",
                ),
                ("--candidate-release-json-sha256",),
            ),
        ):
            with self.subTest(command=command):
                completed = subprocess.run(
                    [
                        sys.executable,
                        os.fspath(bundle_fixture.RELEASE_SCRIPT),
                        command,
                        "--help",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                for token in required:
                    self.assertIn(token, completed.stdout)
                for token in forbidden:
                    self.assertNotIn(token, completed.stdout)


@unittest.skipUnless(
    HAVE_BASELINE_ASSEMBLER,
    "[red] assemble_oi1_baseline is not implemented",
)
class BaselineEvidenceAssemblyTests(unittest.TestCase):
    def test_assembles_canonical_envelope_and_exact_derived_policy(self) -> None:
        fixture = BaselineAssemblyFixture()
        try:
            baseline_path, policy_path = fixture.assemble()
            self.assertEqual(Path(baseline_path), fixture.baseline_path)
            self.assertEqual(Path(policy_path), fixture.policy_path)

            baseline_bytes = fixture.baseline_path.read_bytes()
            baseline = json.loads(baseline_bytes)
            self.assertEqual(baseline_bytes, canonical_json_bytes(baseline))
            self.assertEqual(
                set(baseline),
                {
                    "schema_version",
                    "measurement_contract",
                    "source_commit",
                    "firmware_version",
                    "created_at",
                    "profile_order",
                    "profiles",
                },
            )
            self.assertEqual(baseline["source_commit"], fixture.source_commit)
            self.assertEqual(baseline["firmware_version"], "0.4.1")
            self.assertEqual(baseline["created_at"], fixture.created_at)
            self.assertEqual(
                [profile["profile_id"] for profile in baseline["profiles"]],
                list(PROFILE_ORDER),
            )

            policy_bytes = fixture.policy_path.read_bytes()
            policy = json.loads(policy_bytes)
            self.assertEqual(policy_bytes, canonical_json_bytes(policy))
            self.assertEqual(
                policy["baseline_evidence"],
                {
                    "path": fixture.baseline_path.relative_to(fixture.repo).as_posix(),
                    "sha256": hashlib.sha256(baseline_bytes).hexdigest(),
                },
            )
            for profile, baseline_profile in zip(
                policy["profiles"], baseline["profiles"]
            ):
                self.assertEqual(
                    profile["thresholds"],
                    RELEASE._derived_qualification_thresholds(
                        baseline_profile["oi1_build"],
                        baseline_profile["oi1_observation"],
                    ),
                )
            self.assertEqual(
                RELEASE._validate_qualification_policy(
                    policy,
                    repo_root=fixture.repo,
                ),
                policy,
            )
        finally:
            fixture.close()

    def test_dirty_checkout_or_fragment_input_mismatch_changes_nothing(self) -> None:
        for mutation in ("dirty", "duplicate-profile", "firmware-hash"):
            with self.subTest(mutation=mutation):
                fixture = BaselineAssemblyFixture()
                try:
                    if mutation == "dirty":
                        fixture.policy_path.write_bytes(fixture.original_policy + b"\n")
                    elif mutation == "duplicate-profile":
                        fixture.fragments[1].write_bytes(
                            fixture.fragments[0].read_bytes()
                        )
                    else:
                        payload = json.loads(
                            fixture.fragments[0].read_text(encoding="utf-8")
                        )
                        payload["firmware_sha256"] = "0" * 64
                        write_json(fixture.fragments[0], payload)

                    with self.assertRaises(RELEASE.ReleaseError):
                        fixture.assemble()
                    self.assertFalse(fixture.baseline_path.exists())
                    if mutation == "dirty":
                        self.assertEqual(
                            fixture.policy_path.read_bytes(),
                            fixture.original_policy + b"\n",
                        )
                    else:
                        self.assertEqual(
                            fixture.policy_path.read_bytes(),
                            fixture.original_policy,
                        )
                finally:
                    fixture.close()


@unittest.skipUnless(
    HAVE_HIL_ASSEMBLER,
    "[red] assemble_completed_hil_report is not implemented",
)
class CompletedHilEvidenceAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = finalization_fixture.FinalizationFixture()
        cls.completed = cls.fixture.completed_hil_payload()
        cls.root = cls.fixture.license_fixture.root
        cls.fragments = []
        for record in cls.completed["records"]:
            path = cls.root / (record["profile_id"] + "-completion.json")
            write_json(path, completion_fragment(record))
            cls.fragments.append(path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.close()

    def assemble(self, output: Path, fragments: list[Path] | None = None) -> Path:
        return Path(
            RELEASE.assemble_completed_hil_report(
                candidate_dir=self.fixture.candidate,
                profile_evidence_paths=(
                    list(reversed(self.fragments)) if fragments is None else fragments
                ),
                output_path=output,
                qualification_repo_root=self.fixture.license_fixture.repo,
            )
        )

    def test_assembles_candidate_bound_report_accepted_by_finalizer(self) -> None:
        candidate_before = finalization_fixture.tree_bytes(self.fixture.candidate)
        fragment_before = [path.read_bytes() for path in self.fragments]
        output = self.root / "assembled-HIL_REPORT.md"
        self.assertEqual(self.assemble(output), output)

        payload = finalization_fixture.read_hil_payload(output)
        self.assertEqual(payload, self.completed)
        self.assertEqual(
            payload["candidate_release_json_sha256"],
            sha256_path(self.fixture.candidate / "release.json"),
        )
        self.assertTrue(
            all(
                record["checks"]["footprint_reliability"] == "passed"
                for record in payload["records"]
            )
        )
        self.assertEqual(
            finalization_fixture.tree_bytes(self.fixture.candidate),
            candidate_before,
        )
        self.assertEqual(
            [path.read_bytes() for path in self.fragments], fragment_before
        )

        public = self.root / "public-from-assembled-HIL"
        self.fixture.finalize(public, completed_hil_report=output)
        self.assertTrue(public.is_dir())

    def test_frozen_fields_failed_checks_and_bad_observations_are_rejected(
        self,
    ) -> None:
        for mutation in ("frozen-field", "failed-check", "bad-observation"):
            with self.subTest(mutation=mutation):
                temporary = self.root / (mutation + "-completion.json")
                payload = json.loads(self.fragments[0].read_text(encoding="utf-8"))
                if mutation == "frozen-field":
                    payload["firmware_sha256"] = "0" * 64
                elif mutation == "failed-check":
                    payload["checks"]["app_workflow"] = "failed"
                else:
                    payload["oi1_observation"][
                        "put_committed_goodput_bytes_per_second"
                    ][0] = 0
                write_json(temporary, payload)
                output = self.root / (mutation + "-HIL_REPORT.md")
                with self.assertRaises(RELEASE.ReleaseError):
                    self.assemble(output, [temporary, self.fragments[1]])
                self.assertFalse(output.exists())

    def test_existing_output_is_never_replaced(self) -> None:
        output = self.root / "existing-HIL_REPORT.md"
        output.write_bytes(b"owner data\n")
        with self.assertRaises(RELEASE.ReleaseError):
            self.assemble(output)
        self.assertEqual(output.read_bytes(), b"owner data\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
