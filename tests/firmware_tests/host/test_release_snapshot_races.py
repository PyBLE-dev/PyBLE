#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] BLD-8/14/19 — Immutable input snapshots for audit and packaging.
#
# Frozen sources:
#   docs/specifications/firmware/browser-flashing.md §§2, 6, 9
#   docs/specifications/firmware/specs.md BLD-8, BLD-14, BLD-19
#
# These adversarial tests mutate otherwise-valid inputs at exact phase
# boundaries. A release operation must reject the drift and publish nothing.

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import struct
import sys
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "release_bundle.py"
BUNDLE_TEST = Path(__file__).with_name("test_release_bundle.py")
LICENSE_TEST = Path(__file__).with_name(
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


RELEASE = load_module("pyble_release_snapshot_races", RELEASE_SCRIPT)
BUNDLE_FIXTURES = load_module("pyble_release_snapshot_bundle_fixtures", BUNDLE_TEST)
LICENSE_FIXTURES = load_module(
    "pyble_release_snapshot_license_fixtures",
    LICENSE_TEST,
)


def provenance() -> dict:
    return {
        "pyble": {"commit": "1" * 40, "clean": True},
        "micropython": {"ref": "v1.28.0", "commit": "2" * 40},
        "esp_idf": {"ref": "v5.5.1", "commit": "3" * 40},
        "patch_count": 0,
        "runner": {"os": "FixtureOS 1", "architecture": "fixture64"},
        "tools": [{"name": "python", "version": "3.13.5"}],
    }


def changed_esp32_application(fixture) -> tuple[bytes, bytes]:
    build = fixture.build_root / "esp32"
    original = bytearray((build / "micropython.bin").read_bytes())
    data_length = struct.unpack_from("<I", original, 28)[0]
    original[80] ^= 0x01
    checksum = 0xEF
    for octet in original[32 : 32 + data_length]:
        checksum ^= octet
    original[-1] = checksum
    application = bytes(original)

    spec = BUNDLE_FIXTURES.PROFILE_SPECS["esp32-4mb"]
    bootloader = (build / "bootloader" / "bootloader.bin").read_bytes()
    partition_table = (
        build / "partition_table" / "partition-table.bin"
    ).read_bytes()
    merged = BUNDLE_FIXTURES.make_merged_image(
        spec["base_offset"],
        list(
            zip(
                spec["component_offsets"],
                (bootloader, partition_table, application),
            )
        ),
    )
    return application, merged


class CandidateSnapshotRaceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = BUNDLE_FIXTURES.ReleaseFixture()

    def tearDown(self):
        self.fixture.cleanup()

    def create(self, output: Path):
        return RELEASE.create_bundle(
            build_root=self.fixture.build_root,
            reproducibility_build_root=(
                self.fixture.reproducibility_build_root
            ),
            output_dir=output,
            repo_root=self.fixture.repo,
            installer_version="10.4.0",
            built_at="2026-07-29T12:00:00Z",
            provenance=provenance(),
            public=False,
        )

    def test_candidate_rejects_build_bytes_changed_after_validation(self):
        build = self.fixture.build_root / "esp32"
        application_path = build / "micropython.bin"
        merged_path = build / "firmware.bin"
        original_sha256 = hashlib.sha256(application_path.read_bytes()).hexdigest()
        changed_application, changed_merged = changed_esp32_application(self.fixture)
        changed_sha256 = hashlib.sha256(changed_application).hexdigest()
        self.assertNotEqual(original_sha256, changed_sha256)

        original_copy = RELEASE.shutil.copyfile
        changed = False

        def mutate_before_first_copy(source, destination, *args, **kwargs):
            nonlocal changed
            if not changed:
                changed = True
                application_path.write_bytes(changed_application)
                merged_path.write_bytes(changed_merged)
            return original_copy(source, destination, *args, **kwargs)

        output = self.fixture.root / "raced-build-bundle"
        with mock.patch.object(
            RELEASE.shutil,
            "copyfile",
            side_effect=mutate_before_first_copy,
        ):
            with self.assertRaises(RELEASE.ReleaseError):
                self.create(output)
        self.assertFalse(output.exists())

    def test_candidate_rechecks_source_and_provenance_before_publication(self):
        mutations = {
            "source lock": self.fixture.repo / "firmware" / "versions.lock",
            "build provenance": (
                self.fixture.build_root
                / "esp32"
                / "pyble-build-provenance.json"
            ),
        }
        for label, mutation_path in mutations.items():
            with self.subTest(drift=label):
                output = self.fixture.root / (
                    "raced-" + label.replace(" ", "-") + "-bundle"
                )
                original_validate = RELEASE.validate_bundle
                original_bytes = mutation_path.read_bytes()

                def mutate_after_final_validation(*args, **kwargs):
                    result = original_validate(*args, **kwargs)
                    mutation_path.write_bytes(original_bytes + b"\n")
                    return result

                try:
                    with mock.patch.object(
                        RELEASE,
                        "validate_bundle",
                        side_effect=mutate_after_final_validation,
                    ):
                        with self.assertRaises(RELEASE.ReleaseError):
                            self.create(output)
                    self.assertFalse(output.exists())
                finally:
                    mutation_path.write_bytes(original_bytes)
                    if output.exists():
                        shutil.rmtree(output)

    def test_candidate_publish_is_atomic_no_replace(self):
        for contender in ("empty-directory", "dangling-symlink"):
            with self.subTest(contender=contender):
                output = self.fixture.root / ("contended-" + contender)
                dangling_target = self.fixture.root / "other-owner-target"
                original_validate = RELEASE.validate_bundle
                installed = False

                def install_contender_after_final_validation(*args, **kwargs):
                    nonlocal installed
                    result = original_validate(*args, **kwargs)
                    if not installed:
                        installed = True
                        if contender == "empty-directory":
                            output.mkdir()
                        else:
                            output.symlink_to(
                                dangling_target,
                                target_is_directory=True,
                            )
                    return result

                try:
                    with mock.patch.object(
                        RELEASE,
                        "validate_bundle",
                        side_effect=install_contender_after_final_validation,
                    ):
                        try:
                            self.create(output)
                        except RELEASE.ReleaseError:
                            pass
                        except OSError as exc:
                            self.fail(
                                "candidate publication leaked a raw OS race error: %s"
                                % exc
                            )
                        else:
                            self.fail(
                                "candidate publication replaced another owner's path"
                            )
                    if contender == "empty-directory":
                        self.assertTrue(output.is_dir())
                        self.assertFalse((output / "release.json").exists())
                    else:
                        self.assertTrue(output.is_symlink())
                        self.assertEqual(os.readlink(output), str(dangling_target))
                finally:
                    if output.is_symlink():
                        output.unlink()
                    elif output.exists():
                        shutil.rmtree(output)


class LicenseAuditSnapshotRaceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = LICENSE_FIXTURES.ReleaseLicenseFixture()

    def tearDown(self):
        self.fixture.close()

    def test_full_role_audit_rejects_input_changed_after_sbom_generation(self):
        runner = LICENSE_FIXTURES.FakeOfflineSbomRunner(self.fixture)
        expected_calls = (
            len(RELEASE.LICENSE_AUDIT_PROFILES)
            * len(RELEASE.LICENSE_AUDIT_ROLES)
        )
        observed_archive = Path(
            next(
                item
                for item in self.fixture.expected_inputs
                if item["kind"] == "generated-component-archive"
            )["observed_path"]
        )
        original = observed_archive.read_bytes()

        class RacingRunner:
            def __call__(inner_self, *args, **kwargs):
                result = runner(*args, **kwargs)
                if len(runner.calls) == expected_calls:
                    observed_archive.write_bytes(original + b"\n")
                return result

        with self.assertRaises(RELEASE.ReleaseError):
            RELEASE.audit_release_licenses(
                build_root=self.fixture.build_root,
                repo_root=self.fixture.repo,
                evidence_dir=self.fixture.evidence,
                runner=RacingRunner(),
            )
        self.assertFalse(any(self.fixture.evidence.iterdir()))

    def test_main_observation_context_is_rebuilt_after_sbom_generation(self):
        expected_calls = (
            len(RELEASE.LICENSE_AUDIT_PROFILES)
            * len(RELEASE.LICENSE_AUDIT_ROLES)
        )
        selectors = {
            "metadata header": lambda topology: topology[
                "generated_headers"
            ][0],
            "Ninja build graph": lambda topology: topology[
                "build_ninja_path"
            ],
            "Ninja rules graph": lambda topology: topology[
                "rules_ninja_path"
            ],
            "direct object": lambda topology: (
                topology["role_root"]
                / topology["direct_loads"]["project"]
            ),
            "direct source": lambda topology: topology["pyble_source"],
        }
        for label, select_path in selectors.items():
            with self.subTest(raced_input=label):
                with LICENSE_FIXTURES.real_idf_main_topology(
                    self.fixture
                ) as topology:
                    mutation_path = select_path(topology)
                    original = mutation_path.read_bytes()
                    runner = LICENSE_FIXTURES.FakeOfflineSbomRunner(
                        self.fixture
                    )

                    class RacingRunner:
                        def __call__(inner_self, *args, **kwargs):
                            result = runner(*args, **kwargs)
                            if len(runner.calls) == expected_calls:
                                mutation_path.write_bytes(
                                    original + b"\n"
                                )
                            return result

                    try:
                        with LICENSE_FIXTURES.installed_policy(
                            self.fixture.base,
                            topology["policy"],
                        ):
                            with self.assertRaises(RELEASE.ReleaseError):
                                RELEASE.audit_release_licenses(
                                    build_root=self.fixture.build_root,
                                    repo_root=self.fixture.repo,
                                    evidence_dir=self.fixture.evidence,
                                    runner=RacingRunner(),
                                )
                        self.assertEqual(len(runner.calls), expected_calls)
                        self.assertFalse(any(self.fixture.evidence.iterdir()))
                    finally:
                        mutation_path.write_bytes(original)


class PackagedBuildEvidenceBindingTests(unittest.TestCase):
    def setUp(self):
        self.bundle_fixture = BUNDLE_FIXTURES.ReleaseFixture()
        self.license_fixture = LICENSE_FIXTURES.ReleaseLicenseFixture()
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
        for target in BUNDLE_FIXTURES.TARGET_TO_PROFILE:
            for relative in release_inputs:
                source = self.bundle_fixture.build_root / target / relative
                destination = self.license_fixture.build_root / target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        self.license_fixture.rebind_build_provenance()

        changed_application, changed_merged = changed_esp32_application(
            self.bundle_fixture
        )
        audited_esp32 = self.license_fixture.build_root / "esp32"
        (audited_esp32 / "micropython.bin").write_bytes(changed_application)
        (audited_esp32 / "firmware.bin").write_bytes(changed_merged)

    def tearDown(self):
        self.license_fixture.close()
        self.bundle_fixture.cleanup()

    def test_public_validation_rejects_evidence_from_an_unrelated_build(self):
        result = RELEASE.audit_release_licenses(
            build_root=self.license_fixture.build_root,
            repo_root=self.license_fixture.repo,
            evidence_dir=self.license_fixture.evidence,
            runner=LICENSE_FIXTURES.FakeOfflineSbomRunner(self.license_fixture),
        )
        notice = LICENSE_FIXTURES.extract_notice(result)

        bundle = self.bundle_fixture.make_bundle(public=True)
        (bundle / "THIRD_PARTY_LICENSES.txt").write_text(
            notice,
            encoding="utf-8",
        )
        self.bundle_fixture.refresh_declared_hashes()

        with self.assertRaises(RELEASE.ReleaseError):
            RELEASE.validate_bundle(
                bundle,
                public=True,
                license_evidence_dir=self.license_fixture.evidence,
                license_build_root=self.license_fixture.build_root,
                repo_root=self.license_fixture.repo,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
