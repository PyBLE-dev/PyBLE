#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for heterogeneous v0.6 packaged-build verification.

The fixture uses structurally valid synthetic ESP-IDF and RP2350 outputs.  It
does not build firmware, access hardware, use the network, or publish files.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import unittest
from unittest import mock

import test_release_bundle as bundle_fixture
import test_release_v060_lifecycle as lifecycle_fixture


RELEASE = bundle_fixture.RELEASE
RELEASE_LOAD_ERROR = bundle_fixture.RELEASE_LOAD_ERROR
HAVE_RELEASE = RELEASE is not None
PROFILE_ORDER = lifecycle_fixture.V060_PROFILE_ORDER
ESP_PROFILE_ORDER = lifecycle_fixture.ESP_PROFILE_ORDER
PICO_PROFILE_ID = "rpi-pico2-w"


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: Path, relative: str) -> dict[str, object]:
    return {
        "path": relative,
        "size": path.stat().st_size,
        "sha256": sha256_path(path),
    }


class PackagedBuildFixture:
    def __init__(self) -> None:
        self.esp_fixture = bundle_fixture.ReleaseFixture("0.6.0")
        self.root = self.esp_fixture.root
        self.build_root = self.esp_fixture.build_root
        self.bundle = self.root / "packaged-v0.6.0"
        self.bundle.mkdir()

        pico_build = lifecycle_fixture.make_rp2_build(
            self.build_root / PICO_PROFILE_ID
        )
        pico_provenance_path = pico_build / "pyble-build-provenance.json"
        pico_provenance = json.loads(
            pico_provenance_path.read_text(encoding="utf-8")
        )
        pico_provenance["source_date_epoch"] = 1_785_326_400
        lifecycle_fixture.write_json(pico_provenance_path, pico_provenance)

        profiles = []
        for profile_id in ESP_PROFILE_ORDER:
            spec = RELEASE.PROFILE_SPECS[profile_id]
            source = self.build_root / spec["target"]
            destination = self.bundle / profile_id
            destination.mkdir()
            mappings = (
                ("firmware.bin", source / "firmware.bin"),
                ("application.bin", source / "micropython.bin"),
                ("bootloader.bin", source / "bootloader" / "bootloader.bin"),
                (
                    "partition-table.bin",
                    source / "partition_table" / "partition-table.bin",
                ),
            )
            for name, source_path in mappings:
                shutil.copyfile(source_path, destination / name)
            profiles.append(
                {
                    "id": profile_id,
                    "target": spec["target"],
                    "provisioning_kind": "esp-web-serial",
                    "install": artifact(
                        destination / "firmware.bin",
                        "%s/firmware.bin" % profile_id,
                    ),
                }
            )

        pico_destination = self.bundle / PICO_PROFILE_ID
        pico_destination.mkdir()
        for name in ("firmware.uf2", "firmware.bin"):
            shutil.copyfile(pico_build / name, pico_destination / name)
        profiles.append(
            {
                "id": PICO_PROFILE_ID,
                "target": PICO_PROFILE_ID,
                "provisioning_kind": "verified-uf2-bootsel",
                "install": {
                    **artifact(
                        pico_destination / "firmware.uf2",
                        "%s/firmware.uf2" % PICO_PROFILE_ID,
                    ),
                    "format": "uf2",
                },
                "resource_image": artifact(
                    pico_destination / "firmware.bin",
                    "%s/firmware.bin" % PICO_PROFILE_ID,
                ),
            }
        )
        self.release = {
            "identity": {"version": "0.6.0"},
            "provenance": {
                "pyble": {"commit": "1" * 40, "clean": True},
                "micropython": {"ref": "v1.28.0", "commit": "2" * 40},
                "esp_idf": {"ref": "v5.5.1", "commit": "3" * 40},
                "patch_count": 0,
                "runner": {"os": "FixtureOS 1", "architecture": "arm64"},
                "tools": [{"name": "fixture", "version": "1.0.0"}],
            },
            "profiles": profiles,
        }

    @property
    def pico_build(self) -> Path:
        return self.build_root / PICO_PROFILE_ID

    @property
    def pico_package(self) -> Path:
        return self.bundle / PICO_PROFILE_ID

    def verify(self) -> None:
        RELEASE._audit_verify_packaged_build(
            bundle=self.bundle,
            release=self.release,
            build_root=self.build_root,
        )

    def close(self) -> None:
        self.esp_fixture.cleanup()


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class V060PackagedBuildRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = PackagedBuildFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_routes_four_esp_profiles_and_pico_through_port_validators(self) -> None:
        with mock.patch.object(
            RELEASE, "validate_build", wraps=RELEASE.validate_build
        ) as validate_esp, mock.patch.object(
            RELEASE, "validate_rp2_build", wraps=RELEASE.validate_rp2_build
        ) as validate_pico:
            self.fixture.verify()

        self.assertEqual(
            [item.args[:2] for item in validate_esp.call_args_list],
            [
                (
                    RELEASE.PROFILE_SPECS[profile_id]["target"],
                    self.fixture.build_root
                    / RELEASE.PROFILE_SPECS[profile_id]["target"],
                )
                for profile_id in ESP_PROFILE_ORDER
            ],
        )
        self.assertEqual(
            [item.args[:2] for item in validate_pico.call_args_list],
            [(PICO_PROFILE_ID, self.fixture.pico_build)],
        )

    def test_packaged_pico_uf2_and_resource_image_are_exactly_bound(self) -> None:
        for name in ("firmware.uf2", "firmware.bin"):
            with self.subTest(artifact=name):
                fixture = PackagedBuildFixture()
                try:
                    path = fixture.pico_package / name
                    changed = bytearray(path.read_bytes())
                    changed[len(changed) // 2] ^= 0x01
                    path.write_bytes(changed)
                    with mock.patch.object(
                        RELEASE,
                        "validate_rp2_build",
                        wraps=RELEASE.validate_rp2_build,
                    ) as validate_pico:
                        with self.assertRaises(RELEASE.ReleaseError):
                            fixture.verify()
                    self.assertEqual(validate_pico.call_count, 1)
                finally:
                    fixture.close()

    def test_pico_artifact_and_source_substitution_fail_closed(self) -> None:
        substitutions = ("esp-bin-as-pico-bin", "different-source-provenance")
        for substitution in substitutions:
            with self.subTest(substitution=substitution):
                fixture = PackagedBuildFixture()
                try:
                    if substitution == "esp-bin-as-pico-bin":
                        shutil.copyfile(
                            fixture.build_root / "esp32-c3" / "firmware.bin",
                            fixture.pico_package / "firmware.bin",
                        )
                    else:
                        path = fixture.pico_build / "pyble-build-provenance.json"
                        provenance = json.loads(path.read_text(encoding="utf-8"))
                        provenance["pyble"]["commit"] = "4" * 40
                        lifecycle_fixture.write_json(path, provenance)
                    with mock.patch.object(
                        RELEASE,
                        "validate_rp2_build",
                        wraps=RELEASE.validate_rp2_build,
                    ) as validate_pico:
                        with self.assertRaises(RELEASE.ReleaseError):
                            fixture.verify()
                    self.assertEqual(validate_pico.call_count, 1)
                finally:
                    fixture.close()

    def test_pico_packaged_and_build_symlinks_are_rejected(self) -> None:
        cases = ("packaged-uf2", "packaged-bin", "build-provenance")
        for case in cases:
            with self.subTest(case=case):
                fixture = PackagedBuildFixture()
                try:
                    if case == "build-provenance":
                        path = fixture.pico_build / "pyble-build-provenance.json"
                        target = fixture.root / "external-rp2-provenance.json"
                    else:
                        name = (
                            "firmware.uf2" if case == "packaged-uf2" else "firmware.bin"
                        )
                        path = fixture.pico_package / name
                        target = fixture.pico_build / name
                    if path != target:
                        if case == "build-provenance":
                            shutil.copyfile(path, target)
                        path.unlink()
                        path.symlink_to(target)
                    with mock.patch.object(
                        RELEASE,
                        "validate_rp2_build",
                        wraps=RELEASE.validate_rp2_build,
                    ) as validate_pico:
                        with self.assertRaisesRegex(
                            RELEASE.ReleaseError,
                            r"(?i)symlink",
                        ):
                            fixture.verify()
                    self.assertEqual(validate_pico.call_count, 1)
                finally:
                    fixture.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
