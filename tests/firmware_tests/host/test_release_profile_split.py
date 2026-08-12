#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""ADR-0028 release-tool contract for distinct lean and exact S3 images."""

from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path
import re
import unittest
from unittest import mock


HOST_DIR = Path(__file__).resolve().parent
REPO_ROOT = HOST_DIR.parents[2]
FIRMWARE_DIR = REPO_ROOT / "firmware"
RELEASE_PATH = FIRMWARE_DIR / "scripts" / "release_bundle.py"
QUALIFICATION_POLICY_PATH = FIRMWARE_DIR / "qualification" / "oi1-gates.json"
WAVESHARE_GATE_PATH = (
    FIRMWARE_DIR / "qualification" / "waveshare_lcd147b_release_gate.py"
)
EXACT_PROFILE = "waveshare-esp32-s3-lcd-147b"
PROSPECTIVE_V051_PROFILES = (
    "esp32-4mb",
    "esp32-s3-n16r8",
    EXACT_PROFILE,
)
HISTORICAL_V042_PROFILES = ("esp32-4mb", "esp32-s3-n16r8")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load {}".format(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELEASE = _load(RELEASE_PATH, "pyble_release_profile_split")
WAVESHARE_GATE = _load(WAVESHARE_GATE_PATH, "pyble_waveshare_profile_split")


def _candidate_profile_records(profile_ids: tuple[str, ...]) -> list[dict]:
    return [
        {
            "id": profile_id,
            "manifest": {"sha256": "1" * 64},
            "install": {"sha256": "2" * 64},
        }
        for profile_id in profile_ids
    ]


def _synthetic_policy(
    profile_ids: tuple[str, ...],
    *,
    schema_version: int,
) -> dict:
    return {
        "schema_version": schema_version,
        "profiles": [
            {
                "profile_id": profile_id,
                "target": RELEASE.PROFILE_SPECS[profile_id]["target"],
                "thresholds": {},
            }
            for profile_id in profile_ids
        ],
    }


def _synthetic_v051_qualification_policy() -> dict:
    """Return policy-shaped data for admission tests, never release evidence."""

    return {
        "schema_version": 2,
        "qualification_scope": "pre-v1",
        "profile_order": list(PROSPECTIVE_V051_PROFILES),
        "deferred_profiles": ["esp32-c3-4mb"],
        "workload": dict(RELEASE.QUALIFICATION_WORKLOAD),
        "derivation": dict(RELEASE.QUALIFICATION_DERIVATION_V3),
        "baseline_evidence": {
            "path": "docs/validation/firmware/oi1/{}.json".format("5" * 40),
            "sha256": "6" * 64,
        },
        "profiles": [
            {
                "profile_id": profile_id,
                "target": RELEASE.PROFILE_SPECS[profile_id]["target"],
                "thresholds": {
                    key: 1 for key in RELEASE.QUALIFICATION_THRESHOLD_KEYS
                },
            }
            for profile_id in PROSPECTIVE_V051_PROFILES
        ],
    }


def _candidate_hil_payload(
    version: str,
    profile_ids: tuple[str, ...],
    *,
    policy_schema_version: int,
) -> tuple[int, dict]:
    with mock.patch.object(
        RELEASE,
        "_qualification_build_measurement",
        return_value={"synthetic_host_fixture": True},
    ):
        report = RELEASE._candidate_hil_report(
            version,
            {"pyble": {"commit": "3" * 40}},
            _candidate_profile_records(profile_ids),
            _synthetic_policy(
                profile_ids,
                schema_version=policy_schema_version,
            ),
            "4" * 64,
            Path("unused-host-fixture"),
        )
    match = re.search(
        r"<!--\s*PYBLE_HIL_RECORDS_V([0-9]+)\s*(\{.*?\})\s*-->",
        report,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError("candidate HIL report lacks its embedded payload")
    return int(match.group(1)), json.loads(match.group(2))


class ProspectiveV051ReleaseMatrixTests(unittest.TestCase):
    def test_prospective_order_and_build_variant_are_exact(self):
        self.assertEqual(
            RELEASE.RELEASE_PROFILE_ORDER,
            PROSPECTIVE_V051_PROFILES,
        )
        exact = RELEASE.PROFILE_SPECS[EXACT_PROFILE]
        self.assertEqual(exact["target"], EXACT_PROFILE)
        self.assertEqual(exact["idf_target"], "esp32s3")
        self.assertEqual(exact["chip_family"], "ESP32-S3")
        self.assertEqual(exact["base_offset"], 0)
        self.assertEqual(exact["flash_size_bytes"], 16 * 1024 * 1024)
        self.assertEqual(exact["psram"], {
            "required": True,
            "size_bytes": 8 * 1024 * 1024,
            "type": "octal",
        })
        self.assertEqual(
            RELEASE.TARGET_TO_PROFILE[EXACT_PROFILE],
            EXACT_PROFILE,
        )

    def test_v051_release_schema_is_v3_with_exactly_three_profiles(self):
        schema = RELEASE._release_schema("0.5.1")
        self.assertEqual(schema["properties"]["schema_version"], {"const": 3})
        profiles = schema["properties"]["profiles"]
        self.assertEqual(profiles["minItems"], 3)
        self.assertEqual(profiles["maxItems"], 3)
        self.assertEqual(
            profiles["items"]["properties"]["id"]["enum"],
            list(PROSPECTIVE_V051_PROFILES),
        )

    def test_four_build_variants_create_eight_license_roles(self):
        self.assertEqual(
            RELEASE.LICENSE_AUDIT_PROFILES,
            (
                ("esp32-4mb", "esp32", "esp32"),
                ("esp32-s3-n16r8", "esp32-s3", "esp32s3"),
                (EXACT_PROFILE, EXACT_PROFILE, "esp32s3"),
                ("esp32-c3-4mb", "esp32-c3", "esp32c3"),
            ),
        )
        self.assertEqual(len(RELEASE.LICENSE_AUDIT_ROLES), 2)
        self.assertEqual(
            len(RELEASE.LICENSE_AUDIT_PROFILES)
            * len(RELEASE.LICENSE_AUDIT_ROLES),
            8,
        )
        self.assertEqual(
            RELEASE.FROZEN_TARGET_SETTINGS[EXACT_PROFILE]["board"],
            "PYBLE_WAVESHARE_ESP32_S3_LCD_147B",
        )

    def test_display_sources_belong_only_to_exact_build_variant(self):
        sources = RELEASE._AUDIT_FIRST_PARTY_FROZEN_SOURCES
        self.assertEqual(sources["pyble_st7789.py"]["target"], EXACT_PROFILE)
        companion = sources["pyble_waveshare_lcd147b.py"]
        self.assertEqual(companion["target"], EXACT_PROFILE)
        self.assertEqual(
            companion["canonical_path"],
            "firmware/board_overlays/{}/pyble_waveshare_lcd147b.py".format(
                EXACT_PROFILE
            ),
        )

    def test_waveshare_finalizer_binds_only_exact_profile_firmware(self):
        source = RELEASE_PATH.read_text(encoding="utf-8")
        dedicated = 'candidate / "{}" / "firmware.bin"'.format(EXACT_PROFILE)
        rejected = 'candidate / "esp32-s3-n16r8" / "firmware.bin"'
        self.assertEqual(source.count(dedicated), 1)
        self.assertEqual(source.count(rejected), 0)


class HistoricalReplayTests(unittest.TestCase):
    def test_profile_order_is_selected_by_source_era(self):
        self.assertEqual(
            RELEASE._release_profile_order_for_version("0.4.2"),
            HISTORICAL_V042_PROFILES,
        )
        self.assertEqual(
            RELEASE._release_profile_order_for_version("0.5.1"),
            PROSPECTIVE_V051_PROFILES,
        )

    def test_release_and_hil_schema_versions_are_source_era_bound(self):
        self.assertEqual(
            RELEASE._release_metadata_schema_version_for_version("0.4.2"), 2
        )
        self.assertEqual(
            RELEASE._release_metadata_schema_version_for_version("0.5.1"), 3
        )
        self.assertEqual(RELEASE._hil_schema_version_for_version("0.4.2"), 2)
        self.assertEqual(RELEASE._hil_schema_version_for_version("0.5.1"), 4)


class CheckedInHistoricalV042QualificationPolicyTests(unittest.TestCase):
    def test_checked_in_policy_is_retained_schema_1_in_v042_order(self):
        policy = json.loads(
            QUALIFICATION_POLICY_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(policy["schema_version"], 1)
        self.assertEqual(
            policy["profile_order"],
            list(HISTORICAL_V042_PROFILES),
        )
        self.assertEqual(
            [entry["profile_id"] for entry in policy["profiles"]],
            list(HISTORICAL_V042_PROFILES),
        )
        self.assertIs(
            RELEASE._validate_qualification_policy(
                policy,
                firmware_version="0.4.2",
            ),
            policy,
        )

    def test_checked_in_policy_does_not_claim_waveshare_qualification(self):
        policy = json.loads(
            QUALIFICATION_POLICY_PATH.read_text(encoding="utf-8")
        )
        targets = {
            entry["profile_id"]: entry["target"]
            for entry in policy["profiles"]
        }
        self.assertEqual(
            targets,
            {
                "esp32-4mb": "esp32",
                "esp32-s3-n16r8": "esp32-s3",
            },
        )
        self.assertNotIn(EXACT_PROFILE, targets)


class ProspectiveV051AdmissionTests(unittest.TestCase):
    def test_synthetic_schema_2_policy_admits_exact_release_order(self):
        policy = _synthetic_v051_qualification_policy()
        self.assertIs(
            RELEASE._validate_qualification_policy(
                policy,
                firmware_version="0.5.1",
            ),
            policy,
        )
        with self.assertRaisesRegex(
            RELEASE.ReleaseError,
            "schema_version does not match the source era",
        ):
            RELEASE._validate_qualification_policy(
                policy,
                firmware_version="0.4.2",
            )

    def test_synthetic_policy_separates_both_s3_logical_builds(self):
        policy = _synthetic_v051_qualification_policy()
        targets = {
            entry["profile_id"]: entry["target"]
            for entry in policy["profiles"]
        }
        self.assertEqual(
            targets,
            {
                "esp32-4mb": "esp32",
                "esp32-s3-n16r8": "esp32-s3",
                EXACT_PROFILE: EXACT_PROFILE,
            },
        )
        self.assertEqual(
            RELEASE.PROFILE_SPECS["esp32-s3-n16r8"]["idf_target"],
            RELEASE.PROFILE_SPECS[EXACT_PROFILE]["idf_target"],
        )
        self.assertNotEqual(
            targets["esp32-s3-n16r8"],
            targets[EXACT_PROFILE],
        )

    def test_v051_candidate_hil_is_v4_with_three_independent_records(self):
        marker_version, payload = _candidate_hil_payload(
            "0.5.1",
            PROSPECTIVE_V051_PROFILES,
            policy_schema_version=2,
        )
        self.assertEqual(marker_version, 4)
        self.assertEqual(payload["schema_version"], 4)
        self.assertEqual(
            [record["profile_id"] for record in payload["records"]],
            list(PROSPECTIVE_V051_PROFILES),
        )
        exact_records = [
            record
            for record in payload["records"]
            if record["profile_id"] == EXACT_PROFILE
        ]
        self.assertEqual(len(exact_records), 1)
        self.assertEqual(
            exact_records[0]["oi1_policy"]["target"],
            EXACT_PROFILE,
        )
        self.assertIsNone(payload["waveshare_lcd147b_qualification"])

    def test_v4_hil_parser_and_source_era_admit_exact_three_profile_shape(self):
        payload = {
            "schema_version": 4,
            "candidate_release_json_sha256": "",
            "qualification_policy_sha256": "4" * 64,
            "qualification_policy": _synthetic_policy(
                PROSPECTIVE_V051_PROFILES,
                schema_version=2,
            ),
            "records": [
                {"profile_id": profile_id}
                for profile_id in PROSPECTIVE_V051_PROFILES
            ],
            "waveshare_lcd147b_qualification": None,
        }
        report = (
            RELEASE.HIL_REPORT_SHELL_PREFIX
            + "<!-- PYBLE_HIL_RECORDS_V4\n"
            + json.dumps(payload, indent=2)
            + "\n-->"
            + RELEASE.HIL_REPORT_SHELL_SUFFIX
        )
        with mock.patch.object(
            RELEASE,
            "_validate_qualification_policy",
            side_effect=lambda value: value,
        ):
            parsed = RELEASE._parse_hil_report(report)
        self.assertEqual(parsed, payload)
        self.assertIs(
            RELEASE._validate_hil_source_era(parsed, "0.5.1"),
            parsed,
        )

    def test_candidate_release_metadata_uses_source_era_schema(self):
        source = re.sub(r"\s+", "", inspect.getsource(RELEASE.create_bundle))
        self.assertIn(
            '"schema_version":_release_metadata_schema_version_for_version(version)',
            source,
        )

    def test_waveshare_gate_and_public_summary_bind_exact_profile_bytes(self):
        self.assertEqual(WAVESHARE_GATE.PROFILE_ID, EXACT_PROFILE)
        source = re.sub(r"\s+", "", inspect.getsource(RELEASE._validate_hil))
        self.assertIn(
            'Path(bundle)/"{}"/"firmware.bin"'.format(EXACT_PROFILE),
            source,
        )
        self.assertNotIn(
            'Path(bundle)/"esp32-s3-n16r8"/"firmware.bin"',
            source,
        )


class HistoricalV042ReplayRedTests(unittest.TestCase):
    def test_retained_release_schema_remains_exactly_two_profile_v2(self):
        schema = RELEASE._release_schema("0.4.2")
        self.assertEqual(schema["properties"]["schema_version"], {"const": 2})
        profiles = schema["properties"]["profiles"]
        self.assertEqual(profiles["minItems"], 2)
        self.assertEqual(profiles["maxItems"], 2)
        self.assertEqual(
            profiles["items"]["properties"]["id"]["enum"],
            list(HISTORICAL_V042_PROFILES),
        )

    def test_retained_candidate_hil_remains_exactly_two_profile_v2(self):
        marker_version, payload = _candidate_hil_payload(
            "0.4.2",
            HISTORICAL_V042_PROFILES,
            policy_schema_version=1,
        )
        self.assertEqual(marker_version, 2)
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(
            [record["profile_id"] for record in payload["records"]],
            list(HISTORICAL_V042_PROFILES),
        )
        self.assertNotIn("waveshare_lcd147b_qualification", payload)
        self.assertIs(
            RELEASE._validate_hil_source_era(payload, "0.4.2"),
            payload,
        )

    def test_bundle_validator_uses_source_era_profile_and_schema_helpers(self):
        source = inspect.getsource(RELEASE.validate_bundle)
        self.assertIn("_release_profile_order_for_version(", source)
        self.assertIn("_release_metadata_schema_version_for_version(", source)
        self.assertIn("_release_schema(", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
