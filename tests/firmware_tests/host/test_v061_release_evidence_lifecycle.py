#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED integration contract for v0.6.1 private hardening evidence.

The tests in this file deliberately exercise the production release entry
points.  Synthetic files are used only as fixtures; they are not physical HIL
evidence and cannot qualify a release.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

import test_release_finalization as finalization_fixture
import test_release_v060_promotion_lifecycle as lifecycle_fixture
import test_v061_hardening_release_gate as hardening_fixture


RELEASE = lifecycle_fixture.RELEASE
RELEASE_LOAD_ERROR = lifecycle_fixture.RELEASE_LOAD_ERROR
REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILE_ORDER = tuple(lifecycle_fixture.V060_PROFILES)
HARDENING_PARAMETER = "v061_hardening_result"
FINALIZER_PARAMETER = "v061_hardening_result_paths"


def has_parameter(function: object, name: str) -> bool:
    return callable(function) and name in inspect.signature(function).parameters


HAVE_RELEASE = RELEASE is not None
HAVE_HARDENING_GATE = hardening_fixture.HAVE_GATE
HAVE_COMPLETION_HARDENING = HAVE_RELEASE and has_parameter(
    getattr(RELEASE, "create_hil_completion_fragment", None),
    HARDENING_PARAMETER,
)
HAVE_ASSEMBLY_HARDENING = HAVE_RELEASE and has_parameter(
    getattr(RELEASE, "_validate_v5_completion_fragment", None),
    "v061_hardening_summary",
)
HAVE_FINALIZER_HARDENING = HAVE_RELEASE and has_parameter(
    getattr(RELEASE, "finalize_public_bundle", None),
    FINALIZER_PARAMETER,
)
HAVE_RESULT_SET_VALIDATOR = HAVE_RELEASE and callable(
    getattr(RELEASE, "_validate_v061_hardening_result_set", None)
)


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object, *, private: bool = False) -> None:
    path.write_bytes(lifecycle_fixture.canonical_json_bytes(value))
    if private:
        path.chmod(0o600)


def git_head(root: Path = REPO_ROOT) -> str:
    return subprocess.run(
        ["git", "-C", os.fspath(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def hardening_summary(private_result: Path) -> dict[str, object]:
    return {
        "measurement_contract": "v061-hardening-seven-scenario-v1",
        "scenario_order": list(hardening_fixture.SCENARIO_ORDER),
        "scenarios": {
            name: "passed" for name in hardening_fixture.SCENARIO_ORDER
        },
        "sequential_runs": 50,
        "workspace_provisioning": {
            name: "passed" for name in hardening_fixture.WORKSPACE_ORDER
        },
        "private_result_sha256": sha256_path(private_result),
    }


class V061ReleaseLifecycleSeamTests(unittest.TestCase):
    def test_completion_api_accepts_one_profile_exact_hardening_result(self):
        self.assertIsNotNone(RELEASE, RELEASE_LOAD_ERROR)
        function = getattr(RELEASE, "create_hil_completion_fragment", None)
        self.assertTrue(callable(function))
        if callable(function):
            self.assertIn(
                HARDENING_PARAMETER,
                inspect.signature(function).parameters,
                "[red] v0.6.1 completion cannot yet consume its private result",
            )

    def test_finalizer_api_accepts_the_exact_five_result_set(self):
        self.assertIsNotNone(RELEASE, RELEASE_LOAD_ERROR)
        function = getattr(RELEASE, "finalize_public_bundle", None)
        self.assertTrue(callable(function))
        if callable(function):
            self.assertIn(
                FINALIZER_PARAMETER,
                inspect.signature(function).parameters,
                "[red] v0.6.1 finalization cannot yet reopen five results",
            )

    def test_assembler_uses_the_version_routed_completion_authority(self):
        self.assertIsNotNone(RELEASE, RELEASE_LOAD_ERROR)
        validator = getattr(RELEASE, "_validate_v5_completion_fragment", None)
        self.assertTrue(callable(validator))
        if callable(validator):
            self.assertIn(
                "v061_hardening_summary",
                inspect.signature(validator).parameters,
                "[red] report assembly cannot yet admit hardening summaries",
            )

    def test_finalizer_has_one_shared_result_set_authority(self):
        self.assertIsNotNone(RELEASE, RELEASE_LOAD_ERROR)
        validator = getattr(RELEASE, "_validate_v061_hardening_result_set", None)
        self.assertTrue(
            callable(validator),
            "[red] v0.6.1 lacks a shared five-result finalization authority",
        )


class CompletionFixture:
    def __init__(self, firmware_version: str) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="pyble-v061-completion-lifecycle-"
        )
        self.root = Path(self.temporary.name).resolve()
        self.candidate = self.root / "candidate"
        self.candidate.mkdir(mode=0o700)
        self.profile_id = "esp32-4mb"
        self.firmware_version = firmware_version
        self.source_commit = git_head()
        self.artifact = self.candidate / self.profile_id / "firmware.bin"
        self.artifact.parent.mkdir(mode=0o700)
        self.artifact.write_bytes(b"synthetic candidate install bytes\n")
        self.install_sha256 = sha256_path(self.artifact)

        self.pending = lifecycle_fixture.pending_v5_payload(firmware_version)
        for record in self.pending["records"]:
            record["source_commit"] = self.source_commit
            if record["profile_id"] == self.profile_id:
                record["install_sha256"] = self.install_sha256
        (self.candidate / "release.json").write_bytes(
            lifecycle_fixture.canonical_json_bytes(
                {
                    "fixture": "candidate-bound-release",
                    "firmware_version": firmware_version,
                }
            )
        )
        (self.candidate / "HIL_REPORT.md").write_text(
            lifecycle_fixture.hil_report(self.pending),
            encoding="utf-8",
        )
        self.candidate_release_sha256 = sha256_path(
            self.candidate / "release.json"
        )

        profiles = copy.deepcopy(lifecycle_fixture.lifecycle_fixture.pending_profiles())
        for profile in profiles:
            if profile["id"] == self.profile_id:
                profile["install"]["sha256"] = self.install_sha256
        self.release = {
            "identity": {
                "version": firmware_version,
                "tag": "firmware-v%s" % firmware_version,
            },
            "provenance": {
                "pyble": {"commit": self.source_commit, "clean": True}
            },
            "profiles": profiles,
        }

        self.operator = self.root / "operator.json"
        self.observation = self.root / "observation.json"
        write_json(
            self.operator,
            lifecycle_fixture.operator_input(self.profile_id),
            private=True,
        )
        write_json(
            self.observation,
            {"fixture": "fresh-physical-observation"},
            private=True,
        )
        self.output = self.root / "completion.json"
        self.hardening_result = self.root / "hardening-result.json"
        if firmware_version == "0.6.1":
            self._write_valid_hardening_result()

    def _write_valid_hardening_result(self) -> None:
        value = hardening_fixture.valid_result(profile_id=self.profile_id)
        value["source_commit"] = self.source_commit
        value["candidate_release_json_sha256"] = (
            self.candidate_release_sha256
        )
        value["install_sha256"] = self.install_sha256
        value["qualification_source_commit"] = git_head()
        value["qualification_executable_sha256"] = sha256_path(
            hardening_fixture.BENCH_PATH
        )
        self.hardening_value = value
        self.hardening_result.write_bytes(
            hardening_fixture.canonical_json_bytes(value)
        )
        self.hardening_result.chmod(0o600)
        hardening_fixture.GATE.validate_result_file(
            self.hardening_result,
            artifact_path=self.artifact,
            expected_profile_id=self.profile_id,
            expected_target=hardening_fixture.PROFILE_TARGETS[self.profile_id],
            expected_version="0.6.1",
            expected_source_commit=self.source_commit,
            candidate_release_json_sha256=self.candidate_release_sha256,
            expected_qualification_source_commit=git_head(),
            expected_qualification_executable_sha256=sha256_path(
                hardening_fixture.BENCH_PATH
            ),
        )

    def close(self) -> None:
        self.temporary.cleanup()

    def create(
        self,
        *,
        hardening_result: Path | None,
        output: Path | None = None,
    ) -> Path:
        with mock.patch.object(
            RELEASE,
            "validate_bundle",
            return_value=copy.deepcopy(self.release),
        ), mock.patch.object(
            RELEASE,
            "_validate_qualification_observation",
            side_effect=lambda value, *_args, **_kwargs: value,
        ):
            return Path(
                RELEASE.create_hil_completion_fragment(
                    candidate_dir=self.candidate,
                    profile_id=self.profile_id,
                    operator_input_path=self.operator,
                    oi1_observation_path=self.observation,
                    output_path=self.output if output is None else output,
                    qualification_repo_root=REPO_ROOT,
                    profile_qualification_result=None,
                    v061_hardening_result=hardening_result,
                )
            )


@unittest.skipUnless(
    HAVE_COMPLETION_HARDENING and HAVE_HARDENING_GATE,
    "[red] v0.6.1 completion hardening is not implemented",
)
class V061CompletionLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CompletionFixture("0.6.1")

    def tearDown(self) -> None:
        self.fixture.close()

    def assert_rejected_without_output(self, result: Path | None) -> None:
        with self.assertRaises(RELEASE.ReleaseError):
            self.fixture.create(hardening_result=result)
        self.assertFalse(self.fixture.output.exists())

    def test_actual_writer_derives_only_the_validated_public_summary(self):
        candidate_before = {
            path.relative_to(self.fixture.candidate).as_posix(): path.read_bytes()
            for path in self.fixture.candidate.rglob("*")
            if path.is_file()
        }
        result_before = self.fixture.hardening_result.read_bytes()

        self.assertEqual(
            self.fixture.create(
                hardening_result=self.fixture.hardening_result
            ),
            self.fixture.output,
        )
        value = json.loads(self.fixture.output.read_text(encoding="utf-8"))
        expected = lifecycle_fixture.completion_fragment(
            self.fixture.profile_id
        )
        expected["checks"]["v061_hardening"] = "passed"
        expected["v061_hardening"] = hardening_summary(
            self.fixture.hardening_result
        )
        self.assertEqual(value, expected)
        self.assertEqual(
            self.fixture.output.read_bytes(),
            lifecycle_fixture.canonical_json_bytes(value),
        )
        self.assertEqual(stat.S_IMODE(self.fixture.output.stat().st_mode), 0o600)
        self.assertEqual(self.fixture.output.stat().st_nlink, 1)
        self.assertEqual(self.fixture.hardening_result.read_bytes(), result_before)
        self.assertEqual(
            {
                path.relative_to(self.fixture.candidate).as_posix(): path.read_bytes()
                for path in self.fixture.candidate.rglob("*")
                if path.is_file()
            },
            candidate_before,
        )

    def test_missing_wrong_noncanonical_or_symlink_result_mints_nothing(self):
        self.assert_rejected_without_output(None)

        wrong = copy.deepcopy(self.fixture.hardening_value)
        wrong["profile_id"] = "esp32-s3-n16r8"
        wrong["target"] = hardening_fixture.PROFILE_TARGETS[
            "esp32-s3-n16r8"
        ]
        self.fixture.hardening_result.write_bytes(
            hardening_fixture.canonical_json_bytes(wrong)
        )
        self.fixture.hardening_result.chmod(0o600)
        self.assert_rejected_without_output(self.fixture.hardening_result)

        self.fixture._write_valid_hardening_result()
        self.fixture.hardening_result.write_text(
            json.dumps(self.fixture.hardening_value) + "\n",
            encoding="utf-8",
        )
        self.fixture.hardening_result.chmod(0o600)
        self.assert_rejected_without_output(self.fixture.hardening_result)

        self.fixture._write_valid_hardening_result()
        target = self.fixture.root / "hardening-target.json"
        self.fixture.hardening_result.rename(target)
        self.fixture.hardening_result.symlink_to(target)
        self.assert_rejected_without_output(self.fixture.hardening_result)

    def test_preexisting_output_is_never_replaced(self):
        owner_bytes = b"operator-owned output\n"
        self.fixture.output.write_bytes(owner_bytes)
        with self.assertRaises(RELEASE.ReleaseError):
            self.fixture.create(
                hardening_result=self.fixture.hardening_result
            )
        self.assertEqual(self.fixture.output.read_bytes(), owner_bytes)


@unittest.skipUnless(
    HAVE_COMPLETION_HARDENING,
    "[red] version-routed completion hardening is not implemented",
)
class V060CompletionCompatibilityTests(unittest.TestCase):
    def test_historical_success_is_unchanged_and_rejects_a_supplied_result(self):
        fixture = CompletionFixture("0.6.0")
        try:
            self.assertEqual(
                fixture.create(hardening_result=None),
                fixture.output,
            )
            value = json.loads(fixture.output.read_text(encoding="utf-8"))
            self.assertEqual(
                value,
                lifecycle_fixture.completion_fragment(fixture.profile_id),
            )
            self.assertNotIn("v061_hardening", value)
            self.assertNotIn("v061_hardening", value["checks"])

            fixture.output.unlink()
            supplied = fixture.root / "unexpected-hardening.json"
            supplied.write_bytes(b"unexpected v0.6.1 evidence\n")
            supplied.chmod(0o600)
            with self.assertRaises(RELEASE.ReleaseError):
                fixture.create(hardening_result=supplied)
            self.assertFalse(fixture.output.exists())
        finally:
            fixture.close()


def synthetic_summary(index: int) -> dict[str, object]:
    return {
        "measurement_contract": "v061-hardening-seven-scenario-v1",
        "scenario_order": list(hardening_fixture.SCENARIO_ORDER),
        "scenarios": {
            name: "passed" for name in hardening_fixture.SCENARIO_ORDER
        },
        "sequential_runs": 50,
        "workspace_provisioning": {
            name: "passed" for name in hardening_fixture.WORKSPACE_ORDER
        },
        "private_result_sha256": "%064x" % (index + 1),
    }


@unittest.skipUnless(
    HAVE_ASSEMBLY_HARDENING,
    "[red] v0.6.1 hardening report assembly is not implemented",
)
class V061AssemblyLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="pyble-v061-assembly-lifecycle-"
        )
        self.root = Path(self.temporary.name).resolve()
        self.candidate = self.root / "candidate"
        self.candidate.mkdir(mode=0o700)
        self.pending = lifecycle_fixture.pending_v5_payload("0.6.1")
        (self.candidate / "release.json").write_bytes(b"{}\n")
        (self.candidate / "HIL_REPORT.md").write_text(
            lifecycle_fixture.hil_report(self.pending),
            encoding="utf-8",
        )
        self.release = {
            "identity": {"version": "0.6.1", "tag": "firmware-v0.6.1"},
            "provenance": {"pyble": {"commit": "1" * 40}},
            "profiles": lifecycle_fixture.lifecycle_fixture.pending_profiles(),
        }
        self.fragments: list[Path] = []
        for index, profile_id in enumerate(PROFILE_ORDER):
            value = lifecycle_fixture.completion_fragment(profile_id)
            value["checks"]["v061_hardening"] = "passed"
            value["v061_hardening"] = synthetic_summary(index)
            path = self.root / (profile_id + "-completion.json")
            write_json(path, value, private=True)
            self.fragments.append(path)
        self.output = self.root / "completed-HIL_REPORT.md"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assemble(self, fragments: list[Path] | None = None) -> Path:
        with mock.patch.object(
            RELEASE,
            "validate_bundle",
            return_value=copy.deepcopy(self.release),
        ), mock.patch.object(
            RELEASE,
            "_validate_qualification_observation",
            side_effect=lambda value, *_args, **_kwargs: value,
        ), mock.patch.object(RELEASE, "_validate_hil", return_value=None):
            return Path(
                RELEASE.assemble_completed_hil_report(
                    candidate_dir=self.candidate,
                    profile_evidence_paths=(
                        list(reversed(self.fragments))
                        if fragments is None
                        else fragments
                    ),
                    output_path=self.output,
                    qualification_repo_root=self.root,
                )
            )

    def test_actual_assembler_preserves_five_distinct_exact_summaries(self):
        candidate_before = {
            path.relative_to(self.candidate).as_posix(): path.read_bytes()
            for path in self.candidate.rglob("*")
            if path.is_file()
        }
        fragment_before = [path.read_bytes() for path in self.fragments]

        self.assertEqual(self.assemble(), self.output)
        completed = RELEASE._parse_hil_report(
            self.output.read_text(encoding="utf-8")
        )
        self.assertEqual(
            [record["profile_id"] for record in completed["records"]],
            list(PROFILE_ORDER),
        )
        self.assertEqual(
            [record["v061_hardening"] for record in completed["records"]],
            [synthetic_summary(index) for index in range(len(PROFILE_ORDER))],
        )
        self.assertEqual(
            {
                record["v061_hardening"]["private_result_sha256"]
                for record in completed["records"]
            },
            {"%064x" % (index + 1) for index in range(len(PROFILE_ORDER))},
        )
        self.assertTrue(
            all(
                record["checks"]["v061_hardening"] == "passed"
                for record in completed["records"]
            )
        )
        self.assertEqual(
            {
                path.relative_to(self.candidate).as_posix(): path.read_bytes()
                for path in self.candidate.rglob("*")
                if path.is_file()
            },
            candidate_before,
        )
        self.assertEqual(
            [path.read_bytes() for path in self.fragments], fragment_before
        )

    def test_duplicate_summary_or_preexisting_output_is_rejected_atomically(self):
        duplicate = json.loads(self.fragments[1].read_text(encoding="utf-8"))
        duplicate["v061_hardening"]["private_result_sha256"] = (
            synthetic_summary(0)["private_result_sha256"]
        )
        replacement = self.root / "duplicate-completion.json"
        write_json(replacement, duplicate, private=True)
        with self.assertRaises(RELEASE.ReleaseError):
            self.assemble([self.fragments[0], replacement, *self.fragments[2:]])
        self.assertFalse(self.output.exists())

        owner_bytes = b"owner-completed-report\n"
        self.output.write_bytes(owner_bytes)
        with self.assertRaises(RELEASE.ReleaseError):
            self.assemble()
        self.assertEqual(self.output.read_bytes(), owner_bytes)


class SyntheticV061FinalizationFixture:
    """Small copy-on-write fixture with real hardening-result validation."""

    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="pyble-v061-finalization-lifecycle-"
        )
        self.root = Path(self.temporary.name).resolve()
        self.candidate = self.root / "candidate"
        self.candidate.mkdir(mode=0o700)
        self.source_commit = git_head()
        self.pending = lifecycle_fixture.pending_v5_payload("0.6.1")
        self.artifacts: dict[str, Path] = {}
        self.install_sha256: dict[str, str] = {}
        for profile_id in PROFILE_ORDER:
            filename = (
                "firmware.uf2" if profile_id == "rpi-pico2-w" else "firmware.bin"
            )
            artifact = self.candidate / profile_id / filename
            artifact.parent.mkdir(mode=0o700)
            artifact.write_bytes(
                ("synthetic %s candidate\n" % profile_id).encode("ascii")
            )
            self.artifacts[profile_id] = artifact
            self.install_sha256[profile_id] = sha256_path(artifact)
        for record in self.pending["records"]:
            profile_id = record["profile_id"]
            record["source_commit"] = self.source_commit
            record["install_sha256"] = self.install_sha256[profile_id]

        self.pending_report = self.candidate / "HIL_REPORT.md"
        self.pending_report.write_text(
            lifecycle_fixture.hil_report(self.pending), encoding="utf-8"
        )
        profiles = []
        for profile_id in PROFILE_ORDER:
            artifact = self.artifacts[profile_id]
            profiles.append(
                {
                    "id": profile_id,
                    "hil_status": "pending",
                    "install": {
                        "path": artifact.relative_to(self.candidate).as_posix(),
                        "size": artifact.stat().st_size,
                        "sha256": sha256_path(artifact),
                    },
                }
            )
        self.release = {
            "identity": {"version": "0.6.1", "tag": "firmware-v0.6.1"},
            "provenance": {
                "pyble": {"commit": self.source_commit, "clean": True}
            },
            "profiles": profiles,
            "documents": {
                "hil_report": RELEASE._artifact(
                    self.pending_report, "HIL_REPORT.md"
                )
            },
        }
        self.release_path = self.candidate / "release.json"
        write_json(self.release_path, self.release)
        self.candidate_release_sha256 = sha256_path(self.release_path)

        self.hardening_results: list[Path] = []
        self.summaries: list[dict[str, object]] = []
        qualification_commit = git_head()
        qualification_sha256 = sha256_path(hardening_fixture.BENCH_PATH)
        for index, profile_id in enumerate(PROFILE_ORDER):
            value = hardening_fixture.valid_result(profile_id=profile_id)
            value["source_commit"] = self.source_commit
            value["candidate_release_json_sha256"] = (
                self.candidate_release_sha256
            )
            value["install_sha256"] = self.install_sha256[profile_id]
            value["qualification_source_commit"] = qualification_commit
            value["qualification_executable_sha256"] = qualification_sha256
            path = self.root / ("%02d-%s-hardening.json" % (index, profile_id))
            path.write_bytes(hardening_fixture.canonical_json_bytes(value))
            path.chmod(0o600)
            summary = hardening_fixture.GATE.validate_result_file(
                path,
                artifact_path=self.artifacts[profile_id],
                expected_profile_id=profile_id,
                expected_target=hardening_fixture.PROFILE_TARGETS[profile_id],
                expected_version="0.6.1",
                expected_source_commit=self.source_commit,
                candidate_release_json_sha256=self.candidate_release_sha256,
                expected_qualification_source_commit=qualification_commit,
                expected_qualification_executable_sha256=qualification_sha256,
            )
            self.hardening_results.append(path)
            self.summaries.append(summary)

        completed = copy.deepcopy(self.pending)
        completed["candidate_release_json_sha256"] = (
            self.candidate_release_sha256
        )
        for index, record in enumerate(completed["records"]):
            fragment = lifecycle_fixture.completion_fragment(
                record["profile_id"]
            )
            record["status"] = "passed"
            for key, value in fragment.items():
                if key != "profile_id":
                    record[key] = copy.deepcopy(value)
            record["checks"] = {
                name: "passed" for name in lifecycle_fixture.V5_ALL_CHECKS
            }
            record["checks"]["v061_hardening"] = "passed"
            record["v061_hardening"] = copy.deepcopy(self.summaries[index])
        self.completed = completed
        self.completed_report = self.root / "completed-HIL_REPORT.md"
        self.completed_report.write_text(
            lifecycle_fixture.hil_report(completed), encoding="utf-8"
        )
        RELEASE._write_sha256sums(self.candidate)

        self.license_evidence = self.root / "license-evidence"
        self.license_build = self.root / "license-build"
        self.license_evidence.mkdir(mode=0o700)
        self.license_build.mkdir(mode=0o700)
        self.lcd_result = self.root / "lcd-result.json"
        self.c3_result = self.root / "c3-result.json"
        self.pico_result = self.root / "pico-result.json"
        for path in (self.lcd_result, self.c3_result, self.pico_result):
            path.write_bytes(b"synthetic private gate result\n")
            path.chmod(0o600)

    def close(self) -> None:
        self.temporary.cleanup()

    @property
    def bundle_files(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                path.relative_to(self.candidate).as_posix()
                for path in self.candidate.rglob("*")
                if path.is_file()
            )
        )

    def _validate_bundle(self, bundle: Path, *, public: bool = False, **_kwargs):
        if public:
            return json.loads(
                (Path(bundle) / "release.json").read_text(encoding="utf-8")
            )
        return copy.deepcopy(self.release)

    def runtime_patches(self) -> contextlib.ExitStack:
        stack = contextlib.ExitStack()
        stack.enter_context(
            mock.patch.object(
                RELEASE,
                "_expected_bundle_files",
                return_value=list(self.bundle_files),
            )
        )
        stack.enter_context(
            mock.patch.object(
                RELEASE,
                "validate_bundle",
                side_effect=self._validate_bundle,
            )
        )
        stack.enter_context(
            mock.patch.object(
                RELEASE, "_audit_verify_release_evidence", return_value=None
            )
        )
        stack.enter_context(
            mock.patch.object(RELEASE, "_require_checkout_clean", return_value=None)
        )
        stack.enter_context(
            mock.patch.object(
                RELEASE._WAVESHARE_LCD147B_GATE,
                "validate_result_file",
                return_value={"fixture": "waveshare-private-summary"},
            )
        )
        stack.enter_context(
            mock.patch.object(
                RELEASE, "_validate_lcd_report_privacy", return_value=None
            )
        )
        stack.enter_context(
            mock.patch.object(RELEASE, "_validate_lcd_gate_source", return_value=None)
        )
        stack.enter_context(
            mock.patch.object(
                RELEASE,
                "_lcd_qualification_snapshot",
                return_value=("fixture-lcd-snapshot",),
            )
        )
        stack.enter_context(
            mock.patch.object(
                RELEASE._V060_PROFILE_GATE,
                "private_result_snapshot",
                side_effect=lambda path: (
                    os.fspath(path),
                    sha256_path(Path(path)),
                ),
            )
        )
        stack.enter_context(
            mock.patch.object(
                RELEASE._V060_PROFILE_GATE,
                "post_oi_nvs_evidence_paths",
                return_value={
                    "post_oi_nvs_receipt_path": self.root / "unused-receipt",
                    "post_oi_nvs_slice_path": self.root / "unused-slice",
                    "post_oi_nvs_acquisition_log_path": self.root / "unused-log",
                },
            )
        )
        stack.enter_context(
            mock.patch.object(
                RELEASE._V060_PROFILE_GATE,
                "validate_c3_result_for_observation",
                return_value={
                    "profile_id": "esp32-c3-4mb",
                    "gates": lifecycle_fixture.profile_gates("esp32-c3-4mb"),
                },
            )
        )
        stack.enter_context(
            mock.patch.object(
                RELEASE._V060_PROFILE_GATE,
                "validate_result_file",
                return_value={
                    "profile_id": "rpi-pico2-w",
                    "gates": lifecycle_fixture.profile_gates("rpi-pico2-w"),
                },
            )
        )
        return stack

    def finalize(self, output: Path) -> Path:
        with self.runtime_patches():
            return Path(
                RELEASE.finalize_public_bundle(
                    candidate_dir=self.candidate,
                    completed_hil_report=self.completed_report,
                    output_dir=output,
                    candidate_release_json_sha256=(
                        self.candidate_release_sha256
                    ),
                    license_evidence_dir=self.license_evidence,
                    license_build_root=self.license_build,
                    repo_root=REPO_ROOT,
                    waveshare_lcd147b_qualification_result=self.lcd_result,
                    esp32_c3_qualification_result=self.c3_result,
                    rpi_pico2_w_qualification_result=self.pico_result,
                    v061_hardening_result_paths=list(self.hardening_results),
                )
            )


@unittest.skipUnless(
    HAVE_FINALIZER_HARDENING
    and HAVE_RESULT_SET_VALIDATOR
    and HAVE_HARDENING_GATE,
    "[red] v0.6.1 finalization hardening is not implemented",
)
class V061FinalizationLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = SyntheticV061FinalizationFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_actual_finalizer_reopens_all_five_results_before_publication(self):
        validator = RELEASE._validate_v061_hardening_result_set
        output = self.fixture.root / "public-v0.6.1"
        with mock.patch.object(
            RELEASE,
            "_validate_v061_hardening_result_set",
            wraps=validator,
        ) as validate:
            self.assertEqual(self.fixture.finalize(output), output)
        self.assertEqual(validate.call_count, 2)
        self.assertTrue(output.is_dir())
        self.assertFalse(
            any(
                path.name.endswith("-hardening.json")
                for path in output.rglob("*")
            )
        )
        public_hil = RELEASE._parse_hil_report(
            (output / "HIL_REPORT.md").read_text(encoding="utf-8")
        )
        self.assertEqual(
            [record["v061_hardening"] for record in public_hil["records"]],
            self.fixture.summaries,
        )

    def test_late_private_result_mutation_leaves_no_output_or_staging(self):
        validator = RELEASE._validate_v061_hardening_result_set
        attempts = 0

        def validate_then_mutate(**kwargs):
            nonlocal attempts
            attempts += 1
            value = validator(**kwargs)
            if attempts == 1:
                path = self.fixture.hardening_results[0]
                changed = json.loads(path.read_text(encoding="utf-8"))
                changed["raw_log_sha256"] = "9" * 64
                path.write_bytes(hardening_fixture.canonical_json_bytes(changed))
                path.chmod(0o600)
            return value

        output = self.fixture.root / "late-mutation-public-v0.6.1"
        with mock.patch.object(
            RELEASE,
            "_validate_v061_hardening_result_set",
            side_effect=validate_then_mutate,
        ), self.assertRaises(RELEASE.ReleaseError):
            self.fixture.finalize(output)
        self.assertEqual(attempts, 2)
        self.assertFalse(output.exists() or output.is_symlink())
        self.assertEqual(
            list(self.fixture.root.glob(".%s.*" % output.name)),
            [],
        )


@unittest.skipUnless(
    HAVE_FINALIZER_HARDENING,
    "[red] version-routed finalizer hardening is not implemented",
)
class V060FinalizationCompatibilityTests(unittest.TestCase):
    def test_none_preserves_historical_output_and_supplied_paths_are_rejected(self):
        fixture = finalization_fixture.FinalizationFixture()
        try:
            baseline = fixture.license_fixture.root / "historical-baseline"
            self.assertEqual(fixture.finalize(baseline), baseline)

            explicit_none = fixture.license_fixture.root / "historical-none"
            with fixture.license_replay():
                result = RELEASE.finalize_public_bundle(
                    candidate_dir=fixture.candidate,
                    completed_hil_report=fixture.completed_hil,
                    output_dir=explicit_none,
                    candidate_release_json_sha256=(
                        fixture.candidate_release_sha256
                    ),
                    license_evidence_dir=fixture.license_fixture.evidence,
                    license_build_root=fixture.license_fixture.build_root,
                    repo_root=fixture.license_fixture.repo,
                    waveshare_lcd147b_qualification_result=(
                        fixture.qualification_result
                    ),
                    esp32_c3_qualification_result=(
                        fixture.c3_qualification_result
                    ),
                    rpi_pico2_w_qualification_result=(
                        fixture.pico_qualification_result
                    ),
                    v061_hardening_result_paths=None,
                )
            self.assertEqual(Path(result), explicit_none)
            self.assertEqual(
                finalization_fixture.tree_bytes(explicit_none),
                finalization_fixture.tree_bytes(baseline),
            )

            unexpected = fixture.license_fixture.root / "unexpected-v061.json"
            unexpected.write_bytes(b"unexpected v0.6.1 result\n")
            unexpected.chmod(0o600)
            rejected = fixture.license_fixture.root / "historical-rejected"
            with fixture.license_replay(), self.assertRaises(RELEASE.ReleaseError):
                RELEASE.finalize_public_bundle(
                    candidate_dir=fixture.candidate,
                    completed_hil_report=fixture.completed_hil,
                    output_dir=rejected,
                    candidate_release_json_sha256=(
                        fixture.candidate_release_sha256
                    ),
                    license_evidence_dir=fixture.license_fixture.evidence,
                    license_build_root=fixture.license_fixture.build_root,
                    repo_root=fixture.license_fixture.repo,
                    waveshare_lcd147b_qualification_result=(
                        fixture.qualification_result
                    ),
                    esp32_c3_qualification_result=(
                        fixture.c3_qualification_result
                    ),
                    rpi_pico2_w_qualification_result=(
                        fixture.pico_qualification_result
                    ),
                    v061_hardening_result_paths=[unexpected],
                )
            self.assertFalse(rejected.exists() or rejected.is_symlink())
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
