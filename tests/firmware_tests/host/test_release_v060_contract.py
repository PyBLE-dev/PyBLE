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
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import subprocess
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
V060_SUPERSEDED_SOURCE_BOUNDARY = (
    "5620f2fdc672b440548119e3431cfa4f4ed3f5a3"
)
V060_ABANDONED_CANDIDATE_SOURCE = (
    "719b211345028e49aee9df9b11c4b5fd110913de"
)
QUALIFICATION_DERIVATION_V2 = {
    "application_image": "exact-byte-identical-two-root-v1",
    "application_headroom": "factory-minus-application-v1",
    "heap_floor": "floor-min-1024-v1",
    "boot_ceiling": "ceil-max-plus-300-10-v2",
    "goodput_floor": "floor-95pct-min-100-v2",
}
QUALIFICATION_DERIVATION_V3 = {
    "application_image": "exact-byte-identical-two-root-v1",
    "application_headroom": "factory-minus-application-v1",
    "heap_floor": "floor-min-1024-v1",
    "boot_ceiling": "fixed-product-slo-3000-v3",
    "goodput_floor": "floor-95pct-min-100-v2",
}
QUALIFICATION_DERIVATION_V4 = {
    "application_image": "exact-byte-identical-two-root-v1",
    "application_headroom": "factory-minus-application-v1",
    "heap_floor": "floor-min-1024-v1",
    "boot_ceiling": "fixed-profile-product-slo-esp3000-pico7000-v4",
    "goodput_floor": "fixed-product-slo-64k-under-10s-6600-v3",
}
V060_FIRST_REPLACEMENT_SOURCE_BOUNDARY = (
    "7d853289815751c7381c9fd0b9a9a4409bdb6879"
)
QUALIFICATION_DERIVATION_V5 = {
    "application_image": "exact-byte-identical-two-root-v1",
    "application_headroom": "factory-minus-application-v1",
    "heap_floor": "floor-min-1024-waveshare-block-98304-v2",
    "boot_ceiling": "fixed-profile-product-slo-esp3000-pico7000-v4",
    "goodput_floor": "fixed-product-slo-64k-under-10s-6600-v3",
}
V5_FIXED_WAVESHARE_LARGEST_BLOCK_MIN_BYTES = 98304
FIXED_PERFORMANCE_THRESHOLDS = {
    profile_id: {
        "reset_to_service_advertisement_max_ms": (
            7000 if profile_id == "rpi-pico2-w" else 3000
        ),
        "put_committed_goodput_min_bytes_per_second": 6600,
        "get_verified_goodput_min_bytes_per_second": 6600,
    }
    for profile_id in V060_PROFILE_ORDER
}
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


class V060ReplacementSourceEraContractTests(unittest.TestCase):
    """ADR-0038: the replacement era is a git-ancestry fact, not a SemVer.

    The superseded unpublished v0.6.0 source era ends at and includes
    ``5620f2f``.  Only strict descendants of that boundary may use the
    ADR-0037 fixed-SLO derivation; the boundary and its ancestors keep the
    historical arithmetic; unprovable ancestry fails closed.
    """

    @staticmethod
    def git_output(checkout: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(checkout), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    def selector(self):
        selector = getattr(
            RELEASE, "_qualification_derivation_for_source", None
        )
        self.assertIsNotNone(
            selector,
            "release tooling must select the qualification derivation from "
            "the bound source commit's ancestry, not from SemVer alone",
        )
        return selector

    def test_replacement_registry_preserves_history_and_freezes_v4(self):
        self.assertEqual(
            RELEASE.QUALIFICATION_DERIVATION_V2,
            QUALIFICATION_DERIVATION_V2,
        )
        self.assertEqual(
            RELEASE.QUALIFICATION_DERIVATION_V3,
            QUALIFICATION_DERIVATION_V3,
        )
        self.assertEqual(
            getattr(RELEASE, "QUALIFICATION_DERIVATION_V4", None),
            QUALIFICATION_DERIVATION_V4,
        )
        self.assertEqual(
            getattr(RELEASE, "V060_SUPERSEDED_SOURCE_BOUNDARY", None),
            V060_SUPERSEDED_SOURCE_BOUNDARY,
        )
        self.assertEqual(
            getattr(RELEASE, "V060_ABANDONED_CANDIDATE_SOURCE", None),
            V060_ABANDONED_CANDIDATE_SOURCE,
        )
        self.assertEqual(
            getattr(RELEASE, "QUALIFICATION_DERIVATION_V5", None),
            QUALIFICATION_DERIVATION_V5,
            "ADR-0039: the second-replacement derivation changes exactly "
            "the heap-floor identifier",
        )
        self.assertEqual(
            getattr(
                RELEASE, "V060_FIRST_REPLACEMENT_SOURCE_BOUNDARY", None
            ),
            V060_FIRST_REPLACEMENT_SOURCE_BOUNDARY,
            "ADR-0039: the first-replacement candidate source is the "
            "second era boundary",
        )
        self.assertEqual(
            getattr(
                RELEASE,
                "V5_FIXED_WAVESHARE_LARGEST_BLOCK_MIN_BYTES",
                None,
            ),
            V5_FIXED_WAVESHARE_LARGEST_BLOCK_MIN_BYTES,
        )

    def test_derivation_selection_routes_by_source_ancestry_not_semver(self):
        selector = self.selector()
        head = self.git_output(REPO_ROOT, "rev-parse", "HEAD")

        self.assertEqual(
            selector(REPO_ROOT, head, firmware_version="0.6.0"),
            QUALIFICATION_DERIVATION_V5,
            "a strict descendant of the first-replacement boundary is the "
            "second-replacement era (ADR-0039)",
        )
        self.assertEqual(
            selector(
                REPO_ROOT,
                V060_FIRST_REPLACEMENT_SOURCE_BOUNDARY,
                firmware_version="0.6.0",
            ),
            QUALIFICATION_DERIVATION_V4,
            "the first-replacement boundary itself keeps the V4 era; only "
            "strict descendants enter the second replacement",
        )
        for source_commit in (
            V060_SUPERSEDED_SOURCE_BOUNDARY,
            V060_ABANDONED_CANDIDATE_SOURCE,
        ):
            with self.subTest(source_commit=source_commit):
                self.assertEqual(
                    selector(
                        REPO_ROOT,
                        source_commit,
                        firmware_version="0.6.0",
                    ),
                    QUALIFICATION_DERIVATION_V3,
                    "the boundary and its ancestors keep historical "
                    "arithmetic; abandoned-candidate evidence can never "
                    "satisfy a V4 policy",
                )
        self.assertEqual(
            selector(
                REPO_ROOT,
                V060_ABANDONED_CANDIDATE_SOURCE,
                firmware_version="0.4.2",
            ),
            RELEASE.QUALIFICATION_DERIVATION_V1,
            "historical version routing inside the superseded era is "
            "unchanged",
        )

    def test_unknown_or_unrelated_source_ancestry_fails_closed(self):
        selector = self.selector()
        with self.assertRaises(RELEASE.ReleaseError):
            selector(REPO_ROOT, "f" * 40, firmware_version="0.6.0")

        with tempfile.TemporaryDirectory(prefix="pyble-v060-era-") as tmp:
            unrelated = Path(tmp) / "unrelated"
            unrelated.mkdir()
            subprocess.run(
                ["git", "init", "-q", str(unrelated)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(unrelated),
                    "-c",
                    "user.name=PyBLE Test",
                    "-c",
                    "user.email=test@invalid",
                    "commit",
                    "-q",
                    "--allow-empty",
                    "-m",
                    "unrelated",
                ],
                check=True,
                capture_output=True,
            )
            orphan = self.git_output(unrelated, "rev-parse", "HEAD")
            with self.assertRaises(RELEASE.ReleaseError):
                selector(unrelated, orphan, firmware_version="0.6.0")
            with self.assertRaises(RELEASE.ReleaseError):
                selector(
                    unrelated,
                    V060_SUPERSEDED_SOURCE_BOUNDARY,
                    firmware_version="0.6.0",
                )

            plain = Path(tmp) / "plain"
            plain.mkdir()
            with self.assertRaises(RELEASE.ReleaseError):
                selector(
                    plain,
                    V060_SUPERSEDED_SOURCE_BOUNDARY,
                    firmware_version="0.6.0",
                )

    def test_active_policy_is_exact_fixed_slo_delta_of_superseded_policy(self):
        historical_raw = subprocess.run(
            [
                "git",
                "-C",
                str(REPO_ROOT),
                "show",
                "%s:firmware/qualification/oi1-gates.json"
                % V060_SUPERSEDED_SOURCE_BOUNDARY,
            ],
            check=True,
            capture_output=True,
        ).stdout
        self.assertEqual(len(historical_raw), 4986)
        self.assertEqual(
            hashlib.sha256(historical_raw).hexdigest(),
            "09e208ab5069b2229d2ae0983df33bb9310de85a8aab83ee816db4456cf21bdd",
            "the superseded-era policy identity must stay auditable",
        )
        historical = json.loads(historical_raw.decode("utf-8"))
        self.assertEqual(historical["derivation"], QUALIFICATION_DERIVATION_V3)

        active_path = (
            REPO_ROOT / "firmware" / "qualification" / "oi1-gates.json"
        )
        active_raw = active_path.read_bytes()
        active = json.loads(active_raw.decode("utf-8"))
        self.assertEqual(
            (
                json.dumps(
                    active,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8"),
            active_raw,
            "the active policy must stay canonical sorted-key JSON",
        )
        self.assertEqual(active["derivation"], QUALIFICATION_DERIVATION_V5)

        first_replacement_raw = subprocess.run(
            [
                "git",
                "-C",
                str(REPO_ROOT),
                "show",
                "%s:firmware/qualification/oi1-gates.json"
                % V060_FIRST_REPLACEMENT_SOURCE_BOUNDARY,
            ],
            check=True,
            capture_output=True,
        ).stdout
        self.assertEqual(len(first_replacement_raw), 5015)
        self.assertEqual(
            hashlib.sha256(first_replacement_raw).hexdigest(),
            "b9b19ddc217598835185429d6d1f1da60bb3a504a447e32dcdeae15bf18bd0c5",
            "the first-replacement policy identity must stay auditable",
        )
        first_replacement = json.loads(first_replacement_raw.decode("utf-8"))
        self.assertEqual(
            first_replacement["derivation"], QUALIFICATION_DERIVATION_V4
        )

        expected = copy.deepcopy(historical)
        expected["derivation"] = copy.deepcopy(QUALIFICATION_DERIVATION_V4)
        changed_numeric_fields = 0
        for entry in expected["profiles"]:
            fixed = FIXED_PERFORMANCE_THRESHOLDS[entry["profile_id"]]
            for key, value in fixed.items():
                if entry["thresholds"][key] != value:
                    changed_numeric_fields += 1
                entry["thresholds"][key] = value
        self.assertEqual(
            changed_numeric_fields,
            11,
            "exactly the Pico reset ceiling and all ten transfer floors "
            "change between the superseded and first-replacement policies; "
            "the two derivation identifiers are separate string fields",
        )
        self.assertEqual(
            first_replacement,
            expected,
            "every static/heap threshold, schema field, and baseline "
            "binding must stay byte-identical to the superseded policy",
        )

        expected_active = copy.deepcopy(first_replacement)
        expected_active["derivation"] = copy.deepcopy(
            QUALIFICATION_DERIVATION_V5
        )
        second_changed_numeric_fields = 0
        for entry in expected_active["profiles"]:
            if entry["profile_id"] == "waveshare-esp32-s3-lcd-147b":
                self.assertEqual(
                    entry["thresholds"][
                        "idf_internal_largest_block_min_bytes"
                    ],
                    102400,
                )
                entry["thresholds"][
                    "idf_internal_largest_block_min_bytes"
                ] = V5_FIXED_WAVESHARE_LARGEST_BLOCK_MIN_BYTES
                second_changed_numeric_fields += 1
        self.assertEqual(
            second_changed_numeric_fields,
            1,
            "ADR-0039 changes exactly the Waveshare largest-block floor; "
            "the heap-floor identifier is a separate string field",
        )
        self.assertEqual(
            active,
            expected_active,
            "every other threshold, schema field, and baseline binding "
            "must stay byte-identical to the first-replacement policy",
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
