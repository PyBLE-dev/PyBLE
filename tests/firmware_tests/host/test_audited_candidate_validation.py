#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] BLD-8/BLD-21 — Protected candidates must carry the final audited
# license notice before they are staged for real-board browser HIL.
#
# Frozen sources:
#   docs/specifications/firmware/browser-flashing.md §§6, 9
#   docs/specifications/firmware/specs.md BLD-8, BLD-19, BLD-21
#
# Production interface pinned by this suite:
#
#   release_bundle.py validate BUNDLE --audited-candidate
#       --license-evidence-dir EVIDENCE
#       --license-build-root BUILD
#       --repo-root REPO
#
# API callers select the same protected-candidate validation by supplying all
# three license inputs to validate_bundle(..., public=False). Every candidate
# validation must additionally bind its qualification policy to a repository.

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "release_bundle.py"


def _load_fixture_module(filename: str, module_name: str):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load fixture module: %s" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


BUNDLE_FIXTURES = _load_fixture_module(
    "test_release_bundle.py",
    "pyble_audited_candidate_bundle_fixtures",
)
LICENSE_FIXTURES = _load_fixture_module(
    "test_release_license_policy_v2_integration.py",
    "pyble_audited_candidate_license_fixtures",
)
RELEASE = LICENSE_FIXTURES.RELEASE
RELEASE_LOAD_ERROR = LICENSE_FIXTURES.RELEASE_LOAD_ERROR


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _refresh_notice_and_sums(bundle: Path) -> None:
    release_path = bundle / "release.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    notice_record = release["documents"]["third_party_licenses"]
    notice_path = bundle / notice_record["path"]
    notice_record["size"] = notice_path.stat().st_size
    notice_record["sha256"] = _sha256(notice_path)
    _write_json(release_path, release)

    lines = []
    for path in sorted(item for item in bundle.rglob("*") if item.is_file()):
        relative = path.relative_to(bundle).as_posix()
        if relative != "SHA256SUMS":
            lines.append("%s  %s" % (_sha256(path), relative))
    (bundle / "SHA256SUMS").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class AuditedCandidateApiRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.release_fixture = BUNDLE_FIXTURES.ReleaseFixture()
        cls.license_fixture = LICENSE_FIXTURES.ReleaseLicenseFixture()
        cls._add_release_inputs_to_audited_build()

        result = RELEASE.audit_release_licenses(
            build_root=cls.license_fixture.build_root,
            repo_root=cls.license_fixture.repo,
            evidence_dir=cls.license_fixture.evidence,
            runner=LICENSE_FIXTURES.FakeOfflineSbomRunner(cls.license_fixture),
        )
        cls.notice = LICENSE_FIXTURES.extract_notice(result)
        cls.notice_path = cls.license_fixture.root / "audited-notice.txt"
        cls.notice_path.write_text(cls.notice, encoding="utf-8")
        cls.candidate = Path(
            RELEASE.create_bundle(
                build_root=cls.license_fixture.build_root,
                reproducibility_build_root=(
                    cls.reproducibility_build_root
                ),
                output_dir=cls.license_fixture.root / "candidate",
                repo_root=cls.license_fixture.repo,
                installer_version="10.4.0",
                built_at="2026-07-29T12:00:00Z",
                provenance={
                    "pyble": {"commit": "1" * 40, "clean": True},
                    "micropython": {
                        "ref": "v1.28.0",
                        "commit": cls.license_fixture.micropython_commit,
                    },
                    "esp_idf": {
                        "ref": "v5.5.1",
                        "commit": cls.license_fixture.esp_idf_commit,
                    },
                    "patch_count": 0,
                    "runner": {
                        "os": "FixtureOS 1",
                        "architecture": "fixture64",
                    },
                    "tools": [{"name": "python", "version": "3.13.5"}],
                },
                audited_notice=cls.notice_path,
                license_evidence_dir=cls.license_fixture.evidence,
                license_build_root=cls.license_fixture.build_root,
                public=False,
            )
        )

    @classmethod
    def tearDownClass(cls):
        cls.license_fixture.close()
        cls.release_fixture.cleanup()

    @classmethod
    def _add_release_inputs_to_audited_build(cls):
        audited_firmware = cls.license_fixture.repo / "firmware"
        (audited_firmware / "patches").mkdir(exist_ok=True)
        for target in BUNDLE_FIXTURES.TARGET_TO_PROFILE:
            for relative in (
                "firmware.bin",
                "micropython.bin",
                "micropython.elf",
                "bootloader/bootloader.bin",
                "partition_table/partition-table.bin",
                "flasher_args.json",
                "sdkconfig",
                "pyble-build-provenance.json",
            ):
                source = cls.release_fixture.build_root / target / relative
                destination = cls.license_fixture.build_root / target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        BUNDLE_FIXTURES.install_fixture_qualification_policy(
            cls.license_fixture.repo
        )
        cls.license_fixture.rebind_build_provenance()
        cls.reproducibility_build_root = (
            cls.license_fixture.root / "build-reproducibility"
        )
        shutil.copytree(
            cls.license_fixture.build_root,
            cls.reproducibility_build_root,
        )

    def _validate_audited(self, bundle: Path, *, evidence=None, build=None):
        return RELEASE.validate_bundle(
            bundle,
            public=False,
            license_evidence_dir=evidence or self.license_fixture.evidence,
            license_build_root=build or self.license_fixture.build_root,
            repo_root=self.license_fixture.repo,
        )

    def _candidate_copy(self, root: Path) -> Path:
        destination = root / "candidate"
        shutil.copytree(self.candidate, destination)
        return destination

    def test_plain_local_requires_policy_binding_and_audited_validation_passes(self):
        with self.assertRaisesRegex(
            RELEASE.ReleaseError,
            r"(?i)(qualification|policy|repository)",
        ):
            RELEASE.validate_bundle(self.candidate, public=False)
        self.assertIsNotNone(
            RELEASE.validate_bundle(
                self.candidate,
                public=False,
                qualification_repo_root=self.license_fixture.repo,
            )
        )
        self.assertIsNotNone(self._validate_audited(self.candidate))

    def test_audited_candidate_rejects_candidate_only_or_replaced_notice(self):
        mutations = (
            (
                "candidate-only",
                LICENSE_FIXTURES.CANDIDATE_MARKER + "\n" + self.notice,
            ),
            ("replaced", self.notice + "Unreviewed replacement notice.\n"),
        )
        for label, replacement in mutations:
            with self.subTest(notice=label), tempfile.TemporaryDirectory(
                prefix="pyble-audited-candidate-notice-",
                dir=self.license_fixture.root,
            ) as temporary:
                candidate = self._candidate_copy(Path(temporary))
                (candidate / "THIRD_PARTY_LICENSES.txt").write_text(
                    replacement,
                    encoding="utf-8",
                )
                _refresh_notice_and_sums(candidate)
                with self.assertRaises(RELEASE.ReleaseError):
                    self._validate_audited(candidate)

    def test_audited_candidate_rejects_stale_or_tampered_evidence(self):
        stale_input = (
            self.license_fixture.build_root
            / "esp32"
            / "project_description.json"
        )
        with LICENSE_FIXTURES.patched_bytes(
            stale_input,
            stale_input.read_bytes() + b"\n",
        ):
            with self.assertRaises(RELEASE.ReleaseError):
                self._validate_audited(self.candidate)

        with tempfile.TemporaryDirectory(
            prefix="pyble-audited-candidate-evidence-",
            dir=self.license_fixture.root,
        ) as temporary:
            evidence = Path(temporary) / "evidence"
            shutil.copytree(self.license_fixture.evidence, evidence)
            evidence_file = next(
                path
                for path in evidence.rglob("*")
                if path.is_file() and path.name != "audit-receipt.json"
            )
            evidence_file.write_bytes(evidence_file.read_bytes() + b"\n")
            with self.assertRaises(RELEASE.ReleaseError):
                self._validate_audited(self.candidate, evidence=evidence)

    def test_audited_candidate_rejects_a_different_build_root(self):
        other = LICENSE_FIXTURES.ReleaseLicenseFixture()
        try:
            with self.assertRaises(RELEASE.ReleaseError):
                self._validate_audited(
                    self.candidate,
                    build=other.build_root,
                )
        finally:
            other.close()


class AuditedCandidateCliRedTests(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, os.fspath(RELEASE_SCRIPT), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_validate_help_exposes_explicit_audited_candidate_mode(self):
        completed = self._run("validate", "--help")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--audited-candidate", completed.stdout)
        self.assertIn("--qualification-repo-root", completed.stdout)

    def test_plain_candidate_requires_qualification_repository_binding(self):
        completed = self._run("validate", "/missing")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("--qualification-repo-root", completed.stderr)

    def test_public_and_audited_candidate_modes_are_mutually_exclusive(self):
        completed = self._run(
            "validate",
            "/missing",
            "--public",
            "--audited-candidate",
            "--license-evidence-dir",
            "/evidence",
            "--license-build-root",
            "/build",
            "--repo-root",
            "/repo",
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("not allowed with argument", completed.stderr)
        self.assertIn("--public", completed.stderr)
        self.assertIn("--audited-candidate", completed.stderr)

    def test_audited_candidate_requires_all_three_license_inputs(self):
        required = {
            "--license-evidence-dir": "/evidence",
            "--license-build-root": "/build",
            "--repo-root": "/repo",
        }
        for missing in required:
            with self.subTest(missing=missing):
                arguments = [
                    "validate",
                    "/missing",
                    "--audited-candidate",
                ]
                for option, value in required.items():
                    if option != missing:
                        arguments.extend((option, value))
                completed = self._run(*arguments)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(missing, completed.stderr)

    def test_license_inputs_without_a_release_mode_are_rejected(self):
        completed = self._run(
            "validate",
            "/missing",
            "--license-evidence-dir",
            "/evidence",
            "--license-build-root",
            "/build",
            "--repo-root",
            "/repo",
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("--public", completed.stderr)
        self.assertIn("--audited-candidate", completed.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
