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
import test_v061_hardening_release_gate as v061_fixture


RELEASE = bundle_fixture.RELEASE
RELEASE_LOAD_ERROR = bundle_fixture.RELEASE_LOAD_ERROR
HAVE_RELEASE = RELEASE is not None
HAVE_BASELINE_ASSEMBLER = HAVE_RELEASE and callable(
    getattr(RELEASE, "assemble_oi1_baseline", None)
)
HAVE_HIL_ASSEMBLER = HAVE_RELEASE and callable(
    getattr(RELEASE, "assemble_completed_hil_report", None)
)
PROFILE_ORDER = bundle_fixture.RELEASE_PROFILE_ORDER
OPERATOR_CHECKS = {
    "provisioning_install",
    "provisioning_recovery",
    "advertising_info_hello",
    "pble_workflow",
    "safe_boot_reconnect",
    "filesystem_resume_reliability",
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
    "app_hil",
    "profile_gate_summary",
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


def v061_public_summary(index: int) -> dict:
    return {
        "measurement_contract": "v061-hardening-seven-scenario-v1",
        "scenario_order": list(v061_fixture.SCENARIO_ORDER),
        "scenarios": {
            name: "passed" for name in v061_fixture.SCENARIO_ORDER
        },
        "sequential_runs": 50,
        "workspace_provisioning": {
            name: "passed" for name in v061_fixture.WORKSPACE_ORDER
        },
        "private_result_sha256": "%064x" % (index + 1),
    }


def v061_promotion_payloads() -> tuple[dict, dict]:
    historical_checks = (
        "provisioning_install",
        "provisioning_recovery",
        "advertising_info_hello",
        "pble_workflow",
        "safe_boot_reconnect",
        "filesystem_resume_reliability",
        "footprint_reliability",
    )
    records = []
    for index, profile_id in enumerate(v061_fixture.PROFILE_TARGETS):
        target = v061_fixture.PROFILE_TARGETS[profile_id]
        record = {
            "profile_id": profile_id,
            "target": target,
            "resource_kind": "rp2" if profile_id == "rpi-pico2-w" else "esp-idf",
            "provisioning_kind": (
                "verified-uf2-bootsel"
                if profile_id == "rpi-pico2-w"
                else "esp-web-serial"
            ),
            "status": "pending",
            "board_manufacturer": "",
            "board_model": "",
            "module_marking": "",
            "device_flash_capacity_bytes": 0,
            "device_psram_capacity_bytes": 0,
            "firmware_version": "0.6.1",
            "tag": "firmware-v0.6.1",
            "source_commit": "1" * 40,
            "install_sha256": "%064x" % (index + 10),
            "tested_at": "",
            "operator": "",
            "maintainer_signoff": "",
            "desktop_os": "",
            "chromium_version": "",
            "ble_backend": "",
            "ble_adapter": "",
            "python_version": "",
            "oi1_policy": {"profile_id": profile_id},
            "oi1_build": {"fixture": index},
            "checks": {
                **{name: "pending" for name in historical_checks},
                "v061_hardening": "pending",
            },
            "app_hil": {"ipad": None, "android": None},
            "profile_gate_summary": None,
            "oi1_observation": None,
            "redacted_console_log": "",
            "v061_hardening": None,
        }
        if profile_id != "rpi-pico2-w":
            record["manifest_sha256"] = "%064x" % (index + 20)
        records.append(record)
    candidate = {
        "schema_version": 5,
        "candidate_release_json_sha256": "",
        "qualification_policy_sha256": "2" * 64,
        "qualification_policy": {"schema_version": 3},
        "records": records,
        "waveshare_lcd147b_qualification": None,
        "esp32_c3_qualification": None,
        "rpi_pico2_w_qualification": None,
    }
    completed = copy.deepcopy(candidate)
    completed["candidate_release_json_sha256"] = "3" * 64
    for index, record in enumerate(completed["records"]):
        profile_id = record["profile_id"]
        record["status"] = "passed"
        record["board_manufacturer"] = "Fixture Boards"
        record["board_model"] = "Fixture " + profile_id
        record["module_marking"] = profile_id
        spec = RELEASE.PROFILE_SPECS[profile_id]
        record["device_flash_capacity_bytes"] = spec["flash_size_bytes"]
        record["device_psram_capacity_bytes"] = spec["psram"]["size_bytes"]
        record["tested_at"] = "2026-09-02T12:00:00Z"
        record["operator"] = "Fixture Operator"
        record["maintainer_signoff"] = "Fixture Maintainer"
        record["desktop_os"] = "FixtureOS 1"
        record["chromium_version"] = "Chrome 151"
        record["ble_backend"] = "Fixture BLE 1"
        record["ble_adapter"] = "Fixture Adapter 1"
        record["python_version"] = "3.13.5"
        record["checks"] = {
            name: "passed" for name in record["checks"]
        }
        record["app_hil"] = {
            platform: {
                "app_version": "0.2.0",
                "app_build": "6",
                "os_major": "12" if platform == "android" else "26",
                "status": "passed",
            }
            for platform in ("ipad", "android")
        }
        record["oi1_observation"] = {"fixture": profile_id}
        record["redacted_console_log"] = "private values removed"
        record["v061_hardening"] = v061_public_summary(index)
        if profile_id == "esp32-c3-4mb":
            record["profile_gate_summary"] = {
                "C3-G%d" % gate: "passed" for gate in range(7)
            }
        elif profile_id == "rpi-pico2-w":
            record["profile_gate_summary"] = {
                "GP%d" % gate: "passed" for gate in range(3)
            }
    return candidate, completed


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
                    bundle_fixture.exact_manifest(
                        bundle_fixture.PROSPECTIVE_FIRMWARE_VERSION,
                        profile_id,
                    ),
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


def v5_operator_input(profile_id: str = "esp32-4mb") -> dict:
    spec = RELEASE.PROFILE_SPECS[profile_id]
    return {
        "board_manufacturer": "Fixture Boards",
        "board_model": "Fixture ESP32",
        "module_marking": "fixture-module",
        "device_flash_capacity_bytes": spec["flash_size_bytes"],
        "device_psram_capacity_bytes": spec["psram"]["size_bytes"],
        "tested_at": "2026-09-02T12:00:00Z",
        "operator": "Fixture Operator",
        "maintainer_signoff": "Fixture Maintainer",
        "desktop_os": "FixtureOS 1",
        "chromium_version": "Chrome 151",
        "ble_backend": "Fixture BLE 1",
        "ble_adapter": "Fixture Adapter 1",
        "python_version": "3.13.5",
        "redacted_console_log": "private values removed",
        "checks": {name: "passed" for name in OPERATOR_CHECKS},
        "app_hil": {
            platform: {
                "app_version": "0.2.0",
                "app_build": "6",
                "os_major": "12" if platform == "android" else "26",
                "status": "passed",
            }
            for platform in ("ipad", "android")
        },
    }


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


class V061CompletionAndAssemblyRedTests(unittest.TestCase):
    def test_completion_validator_is_version_routed_and_derives_hardening(self):
        validator = getattr(RELEASE, "_validate_v5_completion_fragment", None)
        self.assertTrue(callable(validator))
        self.assertEqual(
            set(inspect.signature(validator).parameters),
            {
                "value",
                "profile_id",
                "firmware_version",
                "observation",
                "gate_summary",
                "v061_hardening_summary",
            },
        )

        completion = getattr(RELEASE, "create_hil_completion_fragment", None)
        self.assertTrue(callable(completion))
        self.assertIn(
            "v061_hardening_result",
            inspect.signature(completion).parameters,
        )

        observation = {"fixture": "candidate-bound-observation"}
        historical = {
            "profile_id": "esp32-4mb",
            **v5_operator_input(),
            "profile_gate_summary": None,
            "oi1_observation": observation,
        }
        self.assertEqual(
            validator(
                historical,
                profile_id="esp32-4mb",
                firmware_version="0.6.0",
                observation=observation,
                gate_summary=None,
                v061_hardening_summary=None,
            ),
            historical,
        )
        invalid_historical = copy.deepcopy(historical)
        invalid_historical["checks"]["v061_hardening"] = "passed"
        invalid_historical["v061_hardening"] = v061_public_summary(0)
        with self.assertRaises(RELEASE.ReleaseError):
            validator(
                invalid_historical,
                profile_id="esp32-4mb",
                firmware_version="0.6.0",
                observation=observation,
                gate_summary=None,
                v061_hardening_summary=None,
            )

        summary = v061_public_summary(0)
        current = copy.deepcopy(historical)
        current["checks"]["v061_hardening"] = "passed"
        current["v061_hardening"] = copy.deepcopy(summary)
        self.assertEqual(
            validator(
                current,
                profile_id="esp32-4mb",
                firmware_version="0.6.1",
                observation=observation,
                gate_summary=None,
                v061_hardening_summary=summary,
            ),
            current,
        )
        for mutation in ("missing-summary", "pending-check", "wrong-digest"):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(current)
                if mutation == "missing-summary":
                    changed.pop("v061_hardening")
                elif mutation == "pending-check":
                    changed["checks"]["v061_hardening"] = "pending"
                else:
                    changed["v061_hardening"]["private_result_sha256"] = "9" * 64
                with self.assertRaises(RELEASE.ReleaseError):
                    validator(
                        changed,
                        profile_id="esp32-4mb",
                        firmware_version="0.6.1",
                        observation=observation,
                        gate_summary=None,
                        v061_hardening_summary=summary,
                    )

    def test_operator_input_cannot_author_hardening_check_or_summary(self):
        profile_id = "esp32-4mb"
        value = v5_operator_input(profile_id)
        self.assertEqual(
            RELEASE._validate_v5_operator_input(value, profile_id),
            value,
        )
        for field in ("v061_hardening", "private_result_sha256"):
            with self.subTest(field=field):
                authored = copy.deepcopy(value)
                authored[field] = v061_public_summary(0)
                with self.assertRaises(RELEASE.ReleaseError):
                    RELEASE._validate_v5_operator_input(authored, profile_id)
        authored_check = copy.deepcopy(value)
        authored_check["checks"]["v061_hardening"] = "passed"
        with self.assertRaises(RELEASE.ReleaseError):
            RELEASE._validate_v5_operator_input(authored_check, profile_id)

    def test_assembly_envelope_requires_five_distinct_exact_summaries(self):
        candidate, completed = v061_promotion_payloads()
        RELEASE._validate_hil_promotion_envelope(candidate, completed)

        mutations = {
            "missing": lambda payload: payload["records"][0].__setitem__(
                "v061_hardening", None
            ),
            "pending-check": lambda payload: payload["records"][0][
                "checks"
            ].__setitem__("v061_hardening", "pending"),
            "duplicate-private-result": lambda payload: payload["records"][1][
                "v061_hardening"
            ].__setitem__(
                "private_result_sha256",
                payload["records"][0]["v061_hardening"][
                    "private_result_sha256"
                ],
            ),
            "runs": lambda payload: payload["records"][0][
                "v061_hardening"
            ].__setitem__("sequential_runs", 49),
            "scenario-order": lambda payload: payload["records"][0][
                "v061_hardening"
            ]["scenario_order"].reverse(),
            "workspace-not-run": lambda payload: payload["records"][0][
                "v061_hardening"
            ]["workspace_provisioning"].__setitem__(
                v061_fixture.WORKSPACE_ORDER[0], "NOT-RUN"
            ),
            "extra": lambda payload: payload["records"][0][
                "v061_hardening"
            ].__setitem__("raw_log_sha256", "9" * 64),
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                invalid = copy.deepcopy(completed)
                mutate(invalid)
                with self.assertRaises(RELEASE.ReleaseError):
                    RELEASE._validate_hil_promotion_envelope(candidate, invalid)

    def test_v060_envelope_rejects_the_v061_extension(self):
        candidate, completed = v061_promotion_payloads()
        for payload in (candidate, completed):
            for record in payload["records"]:
                record["firmware_version"] = "0.6.0"
                record["tag"] = "firmware-v0.6.0"
                record.pop("v061_hardening")
                record["checks"].pop("v061_hardening")
        RELEASE._validate_hil_promotion_envelope(candidate, completed)

        candidate["records"][0]["v061_hardening"] = None
        candidate["records"][0]["checks"]["v061_hardening"] = "pending"
        completed["records"][0]["v061_hardening"] = v061_public_summary(0)
        completed["records"][0]["checks"]["v061_hardening"] = "passed"
        with self.assertRaises(RELEASE.ReleaseError):
            RELEASE._validate_hil_promotion_envelope(candidate, completed)


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
            self.assertEqual(
                baseline["firmware_version"],
                bundle_fixture.PROSPECTIVE_FIRMWARE_VERSION,
            )
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
                        firmware_version=(
                            bundle_fixture.PROSPECTIVE_FIRMWARE_VERSION
                        ),
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
                    payload["checks"]["pble_workflow"] = "failed"
                else:
                    payload["oi1_observation"][
                        "put_committed_goodput_bytes_per_second"
                    ][0] = 0
                write_json(temporary, payload)
                output = self.root / (mutation + "-HIL_REPORT.md")
                with self.assertRaises(RELEASE.ReleaseError):
                    self.assemble(output, [temporary, *self.fragments[1:]])
                self.assertFalse(output.exists())

    def test_existing_output_is_never_replaced(self) -> None:
        output = self.root / "existing-HIL_REPORT.md"
        output.write_bytes(b"owner data\n")
        with self.assertRaises(RELEASE.ReleaseError):
            self.assemble(output)
        self.assertEqual(output.read_bytes(), b"owner data\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
