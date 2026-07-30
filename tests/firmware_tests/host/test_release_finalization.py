#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] BLD-19/20/21 — Candidate-to-public copy-on-write finalization.
#
# Frozen sources:
#   docs/specifications/firmware/browser-flashing.md v1.4 §§2, 6, 9
#   docs/specifications/firmware/specs.md BLD-19…21
#
# Production interface pinned by this suite:
#
#   firmware/scripts/release_bundle.py
#     finalize_public_bundle(
#         *,
#         candidate_dir: Path,
#         completed_hil_report: Path,
#         output_dir: Path,
#         candidate_release_json_sha256: str,
#         license_evidence_dir: Path,
#         license_build_root: Path,
#         repo_root: Path,
#     ) -> Path
#
#   firmware/scripts/release_bundle.py finalize-public
#       CANDIDATE_DIR COMPLETED_HIL_REPORT OUTPUT_DIR
#       --candidate-release-json-sha256 SHA256
#       --license-evidence-dir DIR
#       --license-build-root DIR
#       --repo-root DIR
#
# Finalization is deliberately unable to accept replacement notices, firmware,
# manifests, components, release notes, recovery instructions, or schemas.

from __future__ import annotations

import copy
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "release_bundle.py"
BUNDLE_TEST_PATH = Path(__file__).with_name("test_release_bundle.py")
LICENSE_TEST_PATH = Path(__file__).with_name(
    "test_release_license_policy_v2_integration.py"
)
RELEASE_PROFILE_ORDER = ("esp32-4mb", "esp32-s3-n16r8")
PROMOTION_ENVELOPE = {"HIL_REPORT.md", "release.json", "SHA256SUMS"}
HIL_MARKER = re.compile(
    r"<!--\s*PYBLE_HIL_RECORDS_V2\s*(\{.*?\})\s*-->",
    re.DOTALL,
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot construct import spec for %s" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


try:
    BUNDLE_TEST = load_module(
        "pyble_release_finalization_bundle_fixture",
        BUNDLE_TEST_PATH,
    )
    LICENSE_TEST = load_module(
        "pyble_release_finalization_license_fixture",
        LICENSE_TEST_PATH,
    )
    RELEASE = BUNDLE_TEST.RELEASE
    LOAD_ERROR = BUNDLE_TEST.RELEASE_LOAD_ERROR
except Exception as exc:  # pragma: no cover - rendered by the seam tests.
    BUNDLE_TEST = None
    LICENSE_TEST = None
    RELEASE = None
    LOAD_ERROR = str(exc)

HAVE_RELEASE = RELEASE is not None
HAVE_FINALIZER = HAVE_RELEASE and callable(
    getattr(RELEASE, "finalize_public_bundle", None)
)


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def read_hil_payload(path: Path) -> dict:
    match = HIL_MARKER.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise AssertionError("fixture HIL report lacks its embedded records")
    return json.loads(match.group(1))


def write_hil_report(path: Path, payload: dict) -> None:
    path.write_text(
        "# PyBLE firmware HIL report\n\n"
        "Machine-readable records are embedded below; the surrounding Markdown "
        "is the reviewed human-readable report.\n\n"
        "<!-- PYBLE_HIL_RECORDS_V2\n"
        + json.dumps(payload, indent=2, sort_keys=False)
        + "\n-->\n",
        encoding="utf-8",
    )


def refresh_candidate_hashes(candidate: Path) -> None:
    """Make a deliberately mutated candidate internally self-consistent."""

    release_path = candidate / "release.json"
    release = read_json(release_path)

    def refresh(record: dict) -> None:
        path = candidate / record["path"]
        record["size"] = path.stat().st_size
        record["sha256"] = sha256_path(path)

    for profile in release["profiles"]:
        refresh(profile["manifest"])
        refresh(profile["install"])
        for component in profile["components"]:
            refresh(component)
    for record in release["documents"].values():
        refresh(record)
    write_json(release_path, release)

    lines = []
    for path in sorted(candidate.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(candidate).as_posix()
        if relative == "SHA256SUMS":
            continue
        lines.append("%s  %s" % (sha256_path(path), relative))
    (candidate / "SHA256SUMS").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


class FinalizationFixture:
    def __init__(self):
        self.release_fixture = BUNDLE_TEST.ReleaseFixture()
        self.license_fixture = LICENSE_TEST.ReleaseLicenseFixture()
        self._add_release_inputs_to_audited_build()

        audit = RELEASE.audit_release_licenses(
            build_root=self.license_fixture.build_root,
            repo_root=self.license_fixture.repo,
            evidence_dir=self.license_fixture.evidence,
            runner=LICENSE_TEST.FakeOfflineSbomRunner(self.license_fixture),
        )
        notice = LICENSE_TEST.extract_notice(audit)
        self.notice_path = self.license_fixture.root / "audited-notice.txt"
        self.notice_path.write_text(notice, encoding="utf-8")

        self.candidate = self.license_fixture.root / "candidate"
        RELEASE.create_bundle(
            build_root=self.license_fixture.build_root,
            reproducibility_build_root=self.reproducibility_build_root,
            output_dir=self.candidate,
            repo_root=self.license_fixture.repo,
            installer_version="10.4.0",
            built_at="2026-07-30T12:00:00Z",
            provenance=self.provenance(),
            audited_notice=self.notice_path,
            license_evidence_dir=self.license_fixture.evidence,
            license_build_root=self.license_fixture.build_root,
            public=False,
        )
        self.candidate_release_sha256 = sha256_path(self.candidate / "release.json")
        self.completed_hil = self.license_fixture.root / "completed-HIL_REPORT.md"
        self.write_completed_hil(self.completed_hil)

    def close(self) -> None:
        self.license_fixture.close()
        self.release_fixture.cleanup()

    def _add_release_inputs_to_audited_build(self) -> None:
        audited_firmware = self.license_fixture.repo / "firmware"
        (audited_firmware / "patches").mkdir(exist_ok=True)
        release_inputs = (
            "firmware.bin",
            "micropython.bin",
            "micropython.elf",
            "bootloader/bootloader.bin",
            "partition_table/partition-table.bin",
            "flasher_args.json",
            "sdkconfig",
            "pyble-build-provenance.json",
        )
        for target in RELEASE.TARGET_TO_PROFILE:
            for relative in release_inputs:
                source = self.release_fixture.build_root / target / relative
                destination = self.license_fixture.build_root / target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        BUNDLE_TEST.install_fixture_qualification_policy(
            self.license_fixture.repo
        )
        self.license_fixture.rebind_build_provenance()
        self.reproducibility_build_root = (
            self.license_fixture.root / "build-reproducibility"
        )
        shutil.copytree(
            self.license_fixture.build_root,
            self.reproducibility_build_root,
        )

    def provenance(self) -> dict:
        return {
            "pyble": {"commit": "1" * 40, "clean": True},
            "micropython": {
                "ref": "v1.28.0",
                "commit": self.license_fixture.micropython_commit,
            },
            "esp_idf": {
                "ref": "v5.5.1",
                "commit": self.license_fixture.esp_idf_commit,
            },
            "patch_count": 0,
            "runner": {"os": "FixtureOS 1", "architecture": "fixture64"},
            "tools": [{"name": "python", "version": "3.13.5"}],
        }

    def completed_hil_payload(self) -> dict:
        pending = read_hil_payload(self.candidate / "HIL_REPORT.md")
        return BUNDLE_TEST.complete_hil_payload(
            pending,
            self.candidate_release_sha256,
        )

    def write_completed_hil(
        self,
        path: Path,
        payload: dict | None = None,
    ) -> Path:
        write_hil_report(
            path,
            payload if payload is not None else self.completed_hil_payload(),
        )
        return path

    def finalize(
        self,
        output: Path,
        *,
        completed_hil_report: Path | None = None,
        candidate_release_json_sha256: str | None = None,
        license_evidence_dir: Path | None = None,
        license_build_root: Path | None = None,
        candidate_dir: Path | None = None,
    ) -> Path:
        return Path(
            RELEASE.finalize_public_bundle(
                candidate_dir=(
                    candidate_dir if candidate_dir is not None else self.candidate
                ),
                completed_hil_report=(
                    completed_hil_report
                    if completed_hil_report is not None
                    else self.completed_hil
                ),
                output_dir=output,
                candidate_release_json_sha256=(
                    candidate_release_json_sha256
                    if candidate_release_json_sha256 is not None
                    else self.candidate_release_sha256
                ),
                license_evidence_dir=(
                    license_evidence_dir
                    if license_evidence_dir is not None
                    else self.license_fixture.evidence
                ),
                license_build_root=(
                    license_build_root
                    if license_build_root is not None
                    else self.license_fixture.build_root
                ),
                repo_root=self.license_fixture.repo,
            )
        )


class FinalizationSeamRedTests(unittest.TestCase):
    def test_finalize_public_api_exists_with_exact_keyword_contract(self):
        self.assertIsNotNone(RELEASE, LOAD_ERROR)
        function = getattr(RELEASE, "finalize_public_bundle", None)
        self.assertTrue(
            callable(function),
            "HAND-OFF build-smith [green]: implement finalize_public_bundle",
        )
        self.assertEqual(
            set(inspect.signature(function).parameters),
            {
                "candidate_dir",
                "completed_hil_report",
                "output_dir",
                "candidate_release_json_sha256",
                "license_evidence_dir",
                "license_build_root",
                "repo_root",
            },
        )

    def test_finalize_public_cli_command_exists(self):
        completed = subprocess.run(
            [sys.executable, os.fspath(RELEASE_SCRIPT), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("finalize-public", completed.stdout)


@unittest.skipUnless(
    HAVE_FINALIZER,
    "HAND-OFF build-smith [green]: finalize_public_bundle is not implemented",
)
class FinalizationLifecycleRedTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FinalizationFixture()

    def tearDown(self):
        self.fixture.close()

    def assert_rejected_without_output(self, output: Path, **overrides) -> None:
        with self.assertRaises(RELEASE.ReleaseError):
            self.fixture.finalize(output, **overrides)
        self.assertFalse(
            output.exists() or output.is_symlink(),
            "failed finalization exposed an output path",
        )

    def test_happy_path_is_exact_copy_on_write_and_public_valid(self):
        candidate_before = tree_bytes(self.fixture.candidate)
        candidate_release = read_json(self.fixture.candidate / "release.json")
        self.assertEqual(candidate_release["schema_version"], 2)
        self.assertEqual(
            [profile["id"] for profile in candidate_release["profiles"]],
            list(RELEASE_PROFILE_ORDER),
        )
        self.assertFalse(
            any(
                relative.startswith("esp32-c3-4mb/")
                for relative in candidate_before
            ),
            "the deferred C3 profile must not enter candidate finalization",
        )
        pending_payload = read_hil_payload(self.fixture.candidate / "HIL_REPORT.md")
        self.assertEqual(pending_payload["schema_version"], 2)
        self.assertEqual(pending_payload["candidate_release_json_sha256"], "")
        self.assertEqual(
            [record["profile_id"] for record in pending_payload["records"]],
            list(RELEASE_PROFILE_ORDER),
        )
        self.assertEqual(
            pending_payload["qualification_policy"]["profile_order"],
            list(RELEASE_PROFILE_ORDER),
        )
        self.assertEqual(
            pending_payload["qualification_policy"]["deferred_profiles"],
            ["esp32-c3-4mb"],
        )
        self.assertTrue(
            all(
                record["oi1_observation"] is None
                for record in pending_payload["records"]
            )
        )

        output = self.fixture.license_fixture.root / "public-v0.4.1"
        finalized = self.fixture.finalize(output)

        self.assertEqual(finalized, output)
        self.assertEqual(tree_bytes(self.fixture.candidate), candidate_before)
        public_bytes = tree_bytes(finalized)
        changed = {
            relative
            for relative in candidate_before
            if candidate_before[relative] != public_bytes[relative]
        }
        self.assertEqual(changed, PROMOTION_ENVELOPE)
        self.assertEqual(
            public_bytes["THIRD_PARTY_LICENSES.txt"],
            candidate_before["THIRD_PARTY_LICENSES.txt"],
        )

        expected_release = copy.deepcopy(candidate_release)
        for profile in expected_release["profiles"]:
            self.assertEqual(profile["hil_status"], "pending")
            profile["hil_status"] = "passed"
        expected_release["documents"]["hil_report"] = BUNDLE_TEST.artifact(
            finalized / "HIL_REPORT.md",
            "HIL_REPORT.md",
        )
        self.assertEqual(read_json(finalized / "release.json"), expected_release)

        candidate_sums = {
            line.split("  ", 1)[1]: line.split("  ", 1)[0]
            for line in candidate_before["SHA256SUMS"].decode("utf-8").splitlines()
        }
        public_sums = {
            line.split("  ", 1)[1]: line.split("  ", 1)[0]
            for line in public_bytes["SHA256SUMS"].decode("utf-8").splitlines()
        }
        self.assertEqual(set(candidate_sums), set(public_sums))
        self.assertEqual(
            {
                relative
                for relative in candidate_sums
                if candidate_sums[relative] != public_sums[relative]
            },
            {"HIL_REPORT.md", "release.json"},
        )
        self.assertEqual(
            read_hil_payload(finalized / "HIL_REPORT.md")[
                "candidate_release_json_sha256"
            ],
            self.fixture.candidate_release_sha256,
        )
        self.assertEqual(
            [
                record["profile_id"]
                for record in read_hil_payload(finalized / "HIL_REPORT.md")[
                    "records"
                ]
            ],
            list(RELEASE_PROFILE_ORDER),
        )
        public_hil = read_hil_payload(finalized / "HIL_REPORT.md")
        self.assertEqual(
            public_hil["qualification_policy_sha256"],
            pending_payload["qualification_policy_sha256"],
        )
        self.assertEqual(
            public_hil["qualification_policy"],
            pending_payload["qualification_policy"],
        )
        for pending_record, public_record in zip(
            pending_payload["records"],
            public_hil["records"],
        ):
            for immutable in (
                "profile_id",
                "firmware_version",
                "tag",
                "source_commit",
                "manifest_sha256",
                "firmware_sha256",
                "oi1_policy",
                "oi1_build",
            ):
                self.assertEqual(
                    public_record[immutable],
                    pending_record[immutable],
                )
        self.assertIsNotNone(
            RELEASE.validate_bundle(
                finalized,
                public=True,
                license_evidence_dir=self.fixture.license_fixture.evidence,
                license_build_root=self.fixture.license_fixture.build_root,
                repo_root=self.fixture.license_fixture.repo,
            )
        )

    def test_candidate_release_digest_mismatch_fails_closed(self):
        self.assert_rejected_without_output(
            self.fixture.license_fixture.root / "digest-mismatch",
            candidate_release_json_sha256="0" * 64,
        )

    def test_changed_or_candidate_only_notice_cannot_be_promoted(self):
        notice = self.fixture.candidate / "THIRD_PARTY_LICENSES.txt"
        notice.write_text(
            notice.read_text(encoding="utf-8")
            + "\nPUBLIC-NOTICE-STATUS: CANDIDATE-ONLY\n",
            encoding="utf-8",
        )
        refresh_candidate_hashes(self.fixture.candidate)
        changed_digest = sha256_path(self.fixture.candidate / "release.json")
        payload = self.fixture.completed_hil_payload()
        payload["candidate_release_json_sha256"] = changed_digest
        report = self.fixture.write_completed_hil(
            self.fixture.license_fixture.root / "changed-notice-HIL.md",
            payload,
        )
        self.assert_rejected_without_output(
            self.fixture.license_fixture.root / "changed-notice",
            completed_hil_report=report,
            candidate_release_json_sha256=changed_digest,
        )

    def test_missing_or_tampered_license_evidence_fails_closed(self):
        missing = self.fixture.license_fixture.root / "missing-evidence"
        self.assert_rejected_without_output(
            self.fixture.license_fixture.root / "missing-evidence-output",
            license_evidence_dir=missing,
        )

        evidence_file = next(
            path
            for path in self.fixture.license_fixture.evidence.rglob("*")
            if path.is_file() and path.name != "audit-receipt.json"
        )
        evidence_file.write_bytes(evidence_file.read_bytes() + b"\n")
        self.assert_rejected_without_output(
            self.fixture.license_fixture.root / "tampered-evidence-output",
        )

    def test_different_or_changed_build_root_fails_closed(self):
        different = self.fixture.license_fixture.root / "different-build"
        shutil.copytree(self.fixture.license_fixture.build_root, different)
        firmware = different / "esp32" / "firmware.bin"
        firmware.write_bytes(firmware.read_bytes() + b"\x00")
        self.assert_rejected_without_output(
            self.fixture.license_fixture.root / "different-build-output",
            license_build_root=different,
        )

    def test_immutable_candidate_mutation_after_hil_fails_closed(self):
        original_digest = self.fixture.candidate_release_sha256
        recovery = self.fixture.candidate / "RECOVERY.md"
        recovery.write_text(
            recovery.read_text(encoding="utf-8") + "\nchanged after HIL\n",
            encoding="utf-8",
        )
        refresh_candidate_hashes(self.fixture.candidate)
        self.assert_rejected_without_output(
            self.fixture.license_fixture.root / "mutated-candidate-output",
            candidate_release_json_sha256=original_digest,
        )

    def test_hil_identity_profile_hash_order_and_signoff_errors_fail(self):
        mutations = {
            "identity": lambda payload: payload["records"][0].__setitem__(
                "source_commit", "9" * 40
            ),
            "profile": lambda payload: payload["records"][0].__setitem__(
                "device_flash_capacity_bytes",
                payload["records"][0]["device_flash_capacity_bytes"] + 1,
            ),
            "hash": lambda payload: payload["records"][0].__setitem__(
                "manifest_sha256", "0" * 64
            ),
            "order": lambda payload: payload["records"].reverse(),
            "signoff": lambda payload: payload["records"][0].__setitem__(
                "maintainer_signoff", ""
            ),
            "placeholder-operator": lambda payload: payload["records"][
                0
            ].__setitem__("operator", "unknown"),
            "placeholder-signoff": lambda payload: payload["records"][
                0
            ].__setitem__("maintainer_signoff", "TODO"),
        }
        baseline = self.fixture.completed_hil_payload()
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                payload = copy.deepcopy(baseline)
                mutate(payload)
                report = self.fixture.write_completed_hil(
                    self.fixture.license_fixture.root / ("%s-HIL.md" % name),
                    payload,
                )
                self.assert_rejected_without_output(
                    self.fixture.license_fixture.root / ("%s-output" % name),
                    completed_hil_report=report,
                )

    def test_completed_hil_evaluates_every_runtime_threshold(self):
        heap_gates = {
            "gc_free_bytes": "gc_free_min_bytes",
            "idf_internal_free_bytes": "idf_internal_free_min_bytes",
            "idf_internal_largest_block_bytes": (
                "idf_internal_largest_block_min_bytes"
            ),
            "idf_internal_minimum_free_bytes": (
                "idf_internal_minimum_free_min_bytes"
            ),
        }
        baseline = self.fixture.completed_hil_payload()
        for metric, threshold in heap_gates.items():
            with self.subTest(gate=threshold):
                payload = copy.deepcopy(baseline)
                floor = payload["records"][0]["oi1_policy"]["thresholds"][
                    threshold
                ]
                payload["records"][0]["oi1_observation"]["heap_post_hello"][0][
                    metric
                ] = floor - 1
                report = self.fixture.write_completed_hil(
                    self.fixture.license_fixture.root / ("%s-HIL.md" % threshold),
                    payload,
                )
                self.assert_rejected_without_output(
                    self.fixture.license_fixture.root / ("%s-output" % threshold),
                    completed_hil_report=report,
                )

        scalar_cases = {
            "boot-ceiling": lambda record: record["oi1_observation"][
                "reset_to_service_advertisement_ms"
            ].__setitem__(
                0,
                record["oi1_policy"]["thresholds"][
                    "reset_to_service_advertisement_max_ms"
                ]
                + 1,
            ),
            "put-floor": lambda record: (
                record["oi1_observation"]["put_duration_ns"].__setitem__(
                    0, 2_000_000_000
                ),
                record["oi1_observation"][
                    "put_committed_goodput_bytes_per_second"
                ].__setitem__(0, 32_768),
            ),
            "get-floor": lambda record: (
                record["oi1_observation"]["get_duration_ns"].__setitem__(
                    0, 2_000_000_000
                ),
                record["oi1_observation"][
                    "get_verified_goodput_bytes_per_second"
                ].__setitem__(0, 32_768),
            ),
        }
        for name, mutate in scalar_cases.items():
            with self.subTest(gate=name):
                payload = copy.deepcopy(baseline)
                mutate(payload["records"][0])
                report = self.fixture.write_completed_hil(
                    self.fixture.license_fixture.root / ("%s-HIL.md" % name),
                    payload,
                )
                self.assert_rejected_without_output(
                    self.fixture.license_fixture.root / ("%s-output" % name),
                    completed_hil_report=report,
                )

    def test_goodput_accepts_exact_floor_and_rejects_floor_minus_one(self):
        cases = {
            "exact-floor": (1_000_549_615, 65_500, True),
            "floor-minus-one": (1_000_564_891, 65_499, False),
        }
        for name, (duration_ns, goodput, accepted) in cases.items():
            with self.subTest(case=name):
                payload = self.fixture.completed_hil_payload()
                for prefix in ("put", "get"):
                    payload["records"][0]["oi1_observation"][
                        "%s_duration_ns" % prefix
                    ][0] = duration_ns
                    payload["records"][0]["oi1_observation"][
                        (
                            "put_committed_goodput_bytes_per_second"
                            if prefix == "put"
                            else "get_verified_goodput_bytes_per_second"
                        )
                    ][0] = goodput
                report = self.fixture.write_completed_hil(
                    self.fixture.license_fixture.root / ("%s-HIL.md" % name),
                    payload,
                )
                output = self.fixture.license_fixture.root / (
                    "%s-output" % name
                )
                if accepted:
                    self.assertEqual(
                        self.fixture.finalize(
                            output,
                            completed_hil_report=report,
                        ),
                        output,
                    )
                else:
                    self.assert_rejected_without_output(
                        output,
                        completed_hil_report=report,
                    )

    def test_completed_hil_rejects_wrong_units_counts_hashes_and_reliability(self):
        mutations = {
            "mtu": lambda record: record["oi1_observation"].__setitem__(
                "observed_att_mtu", 246
            ),
            "window": lambda record: record["oi1_observation"].__setitem__(
                "observed_window", 4
            ),
            "chunk": lambda record: record["oi1_observation"].__setitem__(
                "observed_chunk_bytes", 228
            ),
            "reset-count": lambda record: record["oi1_observation"][
                "reset_to_service_advertisement_ms"
            ].pop(),
            "roundtrip-count": lambda record: record["oi1_observation"][
                "put_duration_ns"
            ].pop(),
            "goodput-arithmetic": lambda record: record["oi1_observation"][
                "put_committed_goodput_bytes_per_second"
            ].__setitem__(0, 65_535),
            "bool-integer": lambda record: record["oi1_observation"].__setitem__(
                "observed_att_mtu", True
            ),
            "unique-bytes": lambda record: record["oi1_observation"][
                "get_unique_verified_bytes"
            ].__setitem__(0, 65_535),
            "offset-integrity": lambda record: record["oi1_observation"].__setitem__(
                "get_offset_sequences_validated", 4
            ),
            "disconnect": lambda record: record["oi1_observation"].__setitem__(
                "roundtrip_unexpected_disconnects", 1
            ),
            "reliability-files": lambda record: record["oi1_observation"][
                "reliability"
            ].__setitem__("verified_files", 19),
            "reliability-bytes": lambda record: record["oi1_observation"][
                "reliability"
            ].__setitem__("total_payload_bytes", 327_679),
            "reliability-status": lambda record: record["oi1_observation"][
                "reliability"
            ].__setitem__("failed_statuses", 1),
            "power-cycle": lambda record: record["oi1_observation"].__setitem__(
                "physical_power_cycle_advertising", "pending"
            ),
            "raw-log-hash": lambda record: record["oi1_observation"].__setitem__(
                "raw_log_sha256", "not-a-digest"
            ),
        }
        baseline = self.fixture.completed_hil_payload()
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                payload = copy.deepcopy(baseline)
                mutate(payload["records"][0])
                report = self.fixture.write_completed_hil(
                    self.fixture.license_fixture.root / ("%s-HIL.md" % name),
                    payload,
                )
                self.assert_rejected_without_output(
                    self.fixture.license_fixture.root / ("%s-output" % name),
                    completed_hil_report=report,
                )

    def test_completed_hil_cannot_change_candidate_frozen_oi1_fields(self):
        def change_policy(payload):
            payload["qualification_policy"]["profiles"][0]["thresholds"][
                "gc_free_min_bytes"
            ] = 1
            payload["records"][0]["oi1_policy"]["thresholds"][
                "gc_free_min_bytes"
            ] = 1

        mutations = {
            "policy": change_policy,
            "policy-digest": lambda payload: payload.__setitem__(
                "qualification_policy_sha256", "0" * 64
            ),
            "record-policy": lambda payload: payload["records"][0][
                "oi1_policy"
            ]["thresholds"].__setitem__("gc_free_min_bytes", 1),
            "build": lambda payload: payload["records"][0][
                "oi1_build"
            ].__setitem__(
                "application_image_bytes",
                payload["records"][0]["oi1_build"]["application_image_bytes"] + 1,
            ),
            "c3-record": lambda payload: payload["records"].append(
                {
                    **copy.deepcopy(payload["records"][0]),
                    "profile_id": "esp32-c3-4mb",
                }
            ),
        }
        baseline = self.fixture.completed_hil_payload()
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                payload = copy.deepcopy(baseline)
                mutate(payload)
                report = self.fixture.write_completed_hil(
                    self.fixture.license_fixture.root / ("%s-HIL.md" % name),
                    payload,
                )
                self.assert_rejected_without_output(
                    self.fixture.license_fixture.root / ("%s-output" % name),
                    completed_hil_report=report,
                )

    def test_in_place_existing_and_symlink_outputs_are_rejected(self):
        candidate_before = tree_bytes(self.fixture.candidate)
        with self.assertRaises(RELEASE.ReleaseError):
            self.fixture.finalize(self.fixture.candidate)
        self.assertEqual(tree_bytes(self.fixture.candidate), candidate_before)

        existing = self.fixture.license_fixture.root / "existing-output"
        existing.mkdir()
        marker = existing / "owner-data"
        marker.write_text("preserve\n", encoding="utf-8")
        with self.assertRaises(RELEASE.ReleaseError):
            self.fixture.finalize(existing)
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve\n")

        target = self.fixture.license_fixture.root / "symlink-target"
        target.mkdir()
        linked = self.fixture.license_fixture.root / "linked-output"
        linked.symlink_to(target, target_is_directory=True)
        with self.assertRaises(RELEASE.ReleaseError):
            self.fixture.finalize(linked)
        self.assertTrue(linked.is_symlink())
        self.assertEqual(list(target.iterdir()), [])

    def test_candidate_mutation_during_finalization_is_detected(self):
        output = self.fixture.license_fixture.root / "concurrent-mutation-output"
        original_validate = RELEASE.validate_bundle
        mutated = False

        def mutate_after_candidate_validation(bundle, public=False, **kwargs):
            nonlocal mutated
            result = original_validate(bundle, public=public, **kwargs)
            if (
                not public
                and Path(bundle).resolve() == self.fixture.candidate.resolve()
                and not mutated
            ):
                path = self.fixture.candidate / "RECOVERY.md"
                path.write_bytes(path.read_bytes() + b"\nconcurrent change\n")
                mutated = True
            return result

        with mock.patch.object(
            RELEASE,
            "validate_bundle",
            side_effect=mutate_after_candidate_validation,
        ):
            self.assert_rejected_without_output(output)
        self.assertTrue(mutated, "fixture did not exercise candidate mutation")

    def test_late_public_validation_failure_is_atomic(self):
        output = self.fixture.license_fixture.root / "late-failure-output"
        candidate_before = tree_bytes(self.fixture.candidate)
        original_validate = RELEASE.validate_bundle
        saw_public = False

        def fail_public_validation(bundle, public=False, **kwargs):
            nonlocal saw_public
            if public:
                saw_public = True
                raise RELEASE.ReleaseError("synthetic late public failure")
            return original_validate(bundle, public=public, **kwargs)

        with mock.patch.object(
            RELEASE,
            "validate_bundle",
            side_effect=fail_public_validation,
        ):
            self.assert_rejected_without_output(output)
        self.assertTrue(saw_public, "fixture did not reach final public validation")
        self.assertEqual(tree_bytes(self.fixture.candidate), candidate_before)

    def test_cli_requires_every_evidence_flag_and_has_no_notice_override(self):
        help_result = subprocess.run(
            [
                sys.executable,
                os.fspath(RELEASE_SCRIPT),
                "finalize-public",
                "--help",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        required = {
            "--candidate-release-json-sha256": "0" * 64,
            "--license-evidence-dir": "/evidence",
            "--license-build-root": "/build",
            "--repo-root": "/repo",
        }
        for option in required:
            self.assertIn(option, help_result.stdout)
        for forbidden in (
            "--audited-notice",
            "--firmware",
            "--manifest",
            "--release-notes",
            "--recovery",
            "--schema",
        ):
            self.assertNotIn(forbidden, help_result.stdout)

        for missing in required:
            with self.subTest(missing=missing):
                arguments = [
                    sys.executable,
                    os.fspath(RELEASE_SCRIPT),
                    "finalize-public",
                    "/candidate",
                    "/completed-HIL_REPORT.md",
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
