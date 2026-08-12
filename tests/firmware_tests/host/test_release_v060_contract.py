#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for the v0.6.0 five-profile qualified release.

This suite is intentionally hermetic.  It selects source-era helpers, inspects
the release catalog, and exercises reproducibility routing with tiny temporary
files.  It never builds firmware or talks to hardware.
"""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "release_bundle.py"

V042_PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
)
V05_PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
    "waveshare-esp32-s3-lcd-147b",
)
V060_PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
    "waveshare-esp32-s3-lcd-147b",
    "esp32-c3-4mb",
    "rpi-pico2-w",
)
ESP_TARGETS = (
    "esp32",
    "esp32-s3",
    "waveshare-esp32-s3-lcd-147b",
    "esp32-c3",
)
ESP_COMPARE_INPUTS = (
    "micropython.elf",
    "firmware.bin",
    "micropython.bin",
    "bootloader/bootloader.bin",
    "partition_table/partition-table.bin",
    "flasher_args.json",
    "pyble-build-provenance.json",
)
RP2_COMPARE_INPUTS = (
    "firmware.uf2",
    "firmware.elf",
    "firmware.bin",
    "pyble-build-provenance.json",
)
ESP_THRESHOLD_KEYS = (
    "application_image_max_bytes",
    "application_headroom_min_bytes",
    "gc_free_min_bytes",
    "idf_internal_free_min_bytes",
    "idf_internal_largest_block_min_bytes",
    "idf_internal_minimum_free_min_bytes",
    "reset_to_service_advertisement_max_ms",
    "put_committed_goodput_min_bytes_per_second",
    "get_verified_goodput_min_bytes_per_second",
)
RP2_THRESHOLD_KEYS = (
    "firmware_bin_max_bytes",
    "firmware_image_headroom_min_bytes",
    "gc_free_min_bytes",
    "reset_to_service_advertisement_max_ms",
    "put_committed_goodput_min_bytes_per_second",
    "get_verified_goodput_min_bytes_per_second",
)


def load_release_module():
    spec = importlib.util.spec_from_file_location(
        "pyble_release_v060_contract",
        RELEASE_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot construct release_bundle.py import spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELEASE = load_release_module()


class V060SourceEraContractTests(unittest.TestCase):
    def test_release_profile_order_preserves_history_and_adds_exact_v060_order(self):
        expected = {
            "0.4.2": V042_PROFILE_ORDER,
            "0.5.0": V05_PROFILE_ORDER,
            "0.5.1": V05_PROFILE_ORDER,
            "0.6.0-rc.1+qualification": V060_PROFILE_ORDER,
            "0.6.0": V060_PROFILE_ORDER,
            "1.0.0": V060_PROFILE_ORDER,
        }
        for version, order in expected.items():
            with self.subTest(version=version):
                self.assertEqual(
                    RELEASE._release_profile_order_for_version(version),
                    order,
                )

    def test_release_metadata_schema_is_v4_from_v060_only(self):
        expected = {
            "0.4.2": 2,
            "0.5.0": 3,
            "0.5.1": 3,
            "0.6.0-rc.1": 4,
            "0.6.0": 4,
            "1.0.0": 4,
        }
        for version, schema_version in expected.items():
            with self.subTest(version=version):
                self.assertEqual(
                    RELEASE._release_metadata_schema_version_for_version(version),
                    schema_version,
                )

    def test_hil_schema_is_v5_from_v060_only(self):
        expected = {
            "0.4.2": 2,
            "0.5.0": 4,
            "0.5.1": 4,
            "0.6.0-rc.1": 5,
            "0.6.0": 5,
            "1.0.0": 5,
        }
        for version, schema_version in expected.items():
            with self.subTest(version=version):
                self.assertEqual(
                    RELEASE._hil_schema_version_for_version(version),
                    schema_version,
                )

    def test_oi_policy_schema_is_v3_from_v060_only(self):
        expected = {
            "0.4.2": 1,
            "0.5.0": 2,
            "0.5.1": 2,
            "0.6.0-rc.1": 3,
            "0.6.0": 3,
            "1.0.0": 3,
        }
        for version, schema_version in expected.items():
            with self.subTest(version=version):
                self.assertEqual(
                    RELEASE._qualification_policy_schema_version_for_version(
                        version
                    ),
                    schema_version,
                )


class V060ProfileCatalogContractTests(unittest.TestCase):
    def test_v060_catalog_has_four_web_serial_profiles_and_one_rp2_profile(self):
        self.assertEqual(RELEASE.RELEASE_PROFILE_ORDER, V060_PROFILE_ORDER)

        for profile_id in V060_PROFILE_ORDER[:-1]:
            with self.subTest(profile_id=profile_id):
                self.assertEqual(
                    RELEASE.PROFILE_SPECS[profile_id].get("provisioning"),
                    "esp-web-tools",
                )

        pico = RELEASE.PROFILE_SPECS["rpi-pico2-w"]
        self.assertEqual(
            {
                key: pico.get(key)
                for key in (
                    "target",
                    "port",
                    "board",
                    "provisioning",
                    "primary_artifact",
                    "provenance",
                )
            },
            {
                "target": "rpi-pico2-w",
                "port": "rp2",
                "board": "RPI_PICO2_W",
                "provisioning": "uf2-bootsel",
                "primary_artifact": "firmware.uf2",
                "provenance": "pyble-build-provenance.json",
            },
        )

    def test_v060_release_layout_carries_only_public_rp2_image_bytes(self):
        files = set(RELEASE._expected_bundle_files(V060_PROFILE_ORDER))
        self.assertIn("rpi-pico2-w/firmware.uf2", files)
        self.assertIn("rpi-pico2-w/firmware.bin", files)
        self.assertNotIn("rpi-pico2-w/pyble-build-provenance.json", files)
        self.assertNotIn("rpi-pico2-w/manifest.json", files)
        self.assertNotIn("rpi-pico2-w/bootloader.bin", files)
        self.assertNotIn("rpi-pico2-w/partition-table.bin", files)
        self.assertNotIn("rpi-pico2-w/application.bin", files)


class V060QualificationPolicyContractTests(unittest.TestCase):
    @staticmethod
    def policy() -> dict:
        workload = copy.deepcopy(RELEASE.QUALIFICATION_WORKLOAD)
        workload.pop("required_put_window", None)

        profiles = []
        for profile_id in V060_PROFILE_ORDER:
            is_rp2 = profile_id == "rpi-pico2-w"
            profiles.append(
                {
                    "profile_id": profile_id,
                    "target": (
                        "rpi-pico2-w"
                        if is_rp2
                        else RELEASE.PROFILE_SPECS[profile_id]["target"]
                    ),
                    "resource_kind": "rp2" if is_rp2 else "esp-idf",
                    "transport": {
                        "required_att_mtu": 247,
                        "required_put_window": 4 if is_rp2 else 8,
                        "required_chunk_bytes": 229,
                        "link_facts_kind": (
                            "btstack-observed-v1"
                            if is_rp2
                            else "nimble-settled-v1"
                        ),
                    },
                    "thresholds": {
                        key: 1
                        for key in (
                            RP2_THRESHOLD_KEYS if is_rp2 else ESP_THRESHOLD_KEYS
                        )
                    },
                }
            )

        return {
            "schema_version": 3,
            "qualification_scope": "v0.6.0-five-profile",
            "profile_order": list(V060_PROFILE_ORDER),
            "workload": workload,
            "derivation": copy.deepcopy(RELEASE.QUALIFICATION_DERIVATION_V3),
            "baseline_evidence": {
                "path": "docs/validation/firmware/oi1/%s.json" % ("a" * 40),
                "sha256": "b" * 64,
            },
            "profiles": profiles,
        }

    def test_v060_policy_discriminates_esp_and_rp2_without_deferral(self):
        policy = self.policy()
        self.assertNotIn("deferred_profiles", policy)
        self.assertNotIn("required_put_window", policy["workload"])
        self.assertEqual(
            [profile["resource_kind"] for profile in policy["profiles"]],
            ["esp-idf", "esp-idf", "esp-idf", "esp-idf", "rp2"],
        )
        self.assertEqual(
            [set(profile) for profile in policy["profiles"]],
            [
                {"profile_id", "target", "resource_kind", "transport", "thresholds"}
            ]
            * 5,
        )
        self.assertEqual(
            [set(profile["transport"]) for profile in policy["profiles"]],
            [
                {
                    "required_att_mtu",
                    "required_put_window",
                    "required_chunk_bytes",
                    "link_facts_kind",
                }
            ]
            * 5,
        )
        self.assertEqual(
            [
                profile["transport"]["required_put_window"]
                for profile in policy["profiles"]
            ],
            [8, 8, 8, 8, 4],
        )
        self.assertEqual(
            [
                profile["transport"]["link_facts_kind"]
                for profile in policy["profiles"]
            ],
            [
                "nimble-settled-v1",
                "nimble-settled-v1",
                "nimble-settled-v1",
                "nimble-settled-v1",
                "btstack-observed-v1",
            ],
        )
        self.assertEqual(
            [set(profile["thresholds"]) for profile in policy["profiles"]],
            [set(ESP_THRESHOLD_KEYS)] * 4 + [set(RP2_THRESHOLD_KEYS)],
        )
        self.assertIs(
            RELEASE._validate_qualification_policy(
                policy,
                firmware_version="0.6.0",
            ),
            policy,
        )


class V060ReproducibilityRoutingContractTests(unittest.TestCase):
    @staticmethod
    def write_compare_tree(root: Path) -> None:
        for target in ESP_TARGETS:
            for relative in ESP_COMPARE_INPUTS:
                path = root / target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((target + "/" + relative).encode("utf-8"))
        for relative in RP2_COMPARE_INPUTS:
            path = root / "rpi-pico2-w" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("rpi-pico2-w/" + relative).encode("utf-8"))

    def test_compare_dispatches_rp2_without_passing_it_to_esp_validator(self):
        esp_calls: list[tuple[str, Path]] = []
        rp2_calls: list[tuple[str, Path]] = []

        def validate_esp(target, build_dir, **_kwargs):
            self.assertNotEqual(
                target,
                "rpi-pico2-w",
                "RP2 must never enter the ESP-IDF validate_build path",
            )
            esp_calls.append((target, Path(build_dir)))
            return {"target": target}

        def validate_rp2(target, build_dir, **_kwargs):
            self.assertEqual(target, "rpi-pico2-w")
            rp2_calls.append((target, Path(build_dir)))
            return {"target": target}

        with tempfile.TemporaryDirectory(prefix="pyble-v060-compare-") as tmp:
            temporary = Path(tmp)
            left = temporary / "left"
            right = temporary / "right"
            self.write_compare_tree(left)
            self.write_compare_tree(right)

            with (
                mock.patch.object(RELEASE, "validate_build", side_effect=validate_esp),
                mock.patch.object(
                    RELEASE,
                    "validate_rp2_build",
                    side_effect=validate_rp2,
                    create=True,
                ),
                mock.patch.object(
                    RELEASE,
                    "_require_one_build_source_identity",
                    return_value=None,
                ),
            ):
                RELEASE.compare_build_roots(left, right)

            self.assertEqual(
                [
                    (target, path.relative_to(temporary).as_posix())
                    for target, path in esp_calls
                ],
                [
                    (target, "%s/%s" % (side, target))
                    for target in ESP_TARGETS
                    for side in ("left", "right")
                ],
            )
            self.assertEqual(
                [(target, path.relative_to(temporary).as_posix()) for target, path in rp2_calls],
                [
                    ("rpi-pico2-w", "left/rpi-pico2-w"),
                    ("rpi-pico2-w", "right/rpi-pico2-w"),
                ],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
