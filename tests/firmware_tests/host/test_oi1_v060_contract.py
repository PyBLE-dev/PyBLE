#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for ADR-0033 five-profile OI-1 qualification tooling.

The suite imports the host-only HIL helpers and release CLI, but replaces every
assembler call with a mock.  It does not scan, reset, flash, or build a board.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


HOST_DIR = Path(__file__).resolve().parent
REPO_ROOT = HOST_DIR.parents[2]
HIL_DIR = HOST_DIR.parent / "hil"
RELEASE_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "release_bundle.py"
sys.path.insert(0, str(HIL_DIR))

import _pble_bench as bench  # noqa: E402
import oi1_profile_bench as profile_bench  # noqa: E402


PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
    "waveshare-esp32-s3-lcd-147b",
    "esp32-c3-4mb",
    "rpi-pico2-w",
)
PROFILE_TARGETS = {
    "esp32-4mb": "esp32",
    "esp32-s3-n16r8": "esp32-s3",
    "waveshare-esp32-s3-lcd-147b": "waveshare-esp32-s3-lcd-147b",
    "esp32-c3-4mb": "esp32-c3",
    "rpi-pico2-w": "rpi-pico2-w",
}
PROFILE_CHIPS = {
    "esp32-4mb": "esp32",
    "esp32-s3-n16r8": "esp32-s3",
    "waveshare-esp32-s3-lcd-147b": "esp32-s3",
    "esp32-c3-4mb": "esp32-c3",
    "rpi-pico2-w": "rpi-pico2-w",
}
PROFILE_RESOURCE_KINDS = {
    profile_id: "rp2" if profile_id == "rpi-pico2-w" else "esp-idf"
    for profile_id in PROFILE_ORDER
}
PROFILE_WINDOWS = {
    profile_id: 4 if profile_id == "rpi-pico2-w" else 8
    for profile_id in PROFILE_ORDER
}
COMMON_WORKLOAD = {
    "reset_samples": 10,
    "reset_hold_ms": 1000,
    "advertising_timeout_ms": 15000,
    "post_hello_heap_samples": 10,
    "roundtrip_samples": 5,
    "roundtrip_payload_bytes": 65536,
    "payload_generator": "sha256-counter-v1",
    "post_roundtrip_heap_samples": 5,
    "reliability_files": 20,
    "reliability_file_bytes": 16384,
    "post_reliability_heap_samples": 1,
    "required_att_mtu": 247,
    "required_chunk_bytes": 229,
}
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
        "pyble_release_oi1_v060_contract",
        RELEASE_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot construct release_bundle.py import spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELEASE = load_release_module()


def qualification_policy() -> dict:
    profiles = []
    for profile_index, profile_id in enumerate(PROFILE_ORDER, start=1):
        threshold_keys = (
            RP2_THRESHOLD_KEYS
            if PROFILE_RESOURCE_KINDS[profile_id] == "rp2"
            else ESP_THRESHOLD_KEYS
        )
        profiles.append(
            {
                "profile_id": profile_id,
                "target": PROFILE_TARGETS[profile_id],
                "resource_kind": PROFILE_RESOURCE_KINDS[profile_id],
                "transport": {
                    "required_att_mtu": 247,
                    "required_put_window": PROFILE_WINDOWS[profile_id],
                    "required_chunk_bytes": 229,
                    "link_facts_kind": (
                        "btstack-observed-v1"
                        if profile_id == "rpi-pico2-w"
                        else "nimble-settled-v1"
                    ),
                },
                "thresholds": {
                    key: profile_index * 100 + key_index
                    for key_index, key in enumerate(threshold_keys, start=1)
                },
            }
        )
    return {
        "schema_version": 3,
        "qualification_scope": "v0.6.0-five-profile",
        "profile_order": list(PROFILE_ORDER),
        "workload": copy.deepcopy(COMMON_WORKLOAD),
        "derivation": copy.deepcopy(bench.DERIVATION),
        "baseline_evidence": {
            "path": "docs/validation/firmware/oi1/%s.json" % ("a" * 40),
            "sha256": "b" * 64,
        },
        "profiles": profiles,
    }


def write_policy(root: Path, policy: dict, name: str = "policy.json") -> Path:
    path = root / name
    path.write_bytes(bench.canonical_json_bytes(policy))
    return path


class V060Oi1CatalogTests(unittest.TestCase):
    def test_exact_five_profile_order_targets_chips_and_common_workload(self):
        self.assertEqual(tuple(bench.PROFILE_ORDER), PROFILE_ORDER)
        self.assertEqual(bench.PROFILE_TARGETS, PROFILE_TARGETS)
        self.assertEqual(bench.PROFILE_CHIPS, PROFILE_CHIPS)
        self.assertEqual(bench.WORKLOAD, COMMON_WORKLOAD)

    def test_c3_has_the_exact_reference_capacity(self):
        self.assertEqual(
            profile_bench.PROFILE_CAPACITIES["esp32-c3-4mb"],
            (4 * 1024 * 1024, 0),
        )

    def test_v060_esp_baseline_fragment_uses_schema2_resource_identity(self):
        profile = profile_bench.build_baseline_profile(
            profile_id="esp32-4mb",
            board_manufacturer="Espressif",
            board_model="host-test board",
            module_marking="host-test module",
            device_flash_capacity_bytes=4 * 1024 * 1024,
            device_psram_capacity_bytes=0,
            firmware_sha256="1" * 64,
            manifest_sha256="2" * 64,
            install_sha256="3" * 64,
            environment={
                "desktop_os": "host-test",
                "ble_backend": "host-test",
                "ble_adapter": "host-test",
                "python_version": "host-test",
            },
            oi1_build={},
            oi1_observation={},
        )

        self.assertEqual(
            set(profile),
            {
                "profile_id",
                "target",
                "resource_kind",
                "board_manufacturer",
                "board_model",
                "module_marking",
                "device_flash_capacity_bytes",
                "device_psram_capacity_bytes",
                "install_sha256",
                "manifest_sha256",
                "environment",
                "oi1_build",
                "oi1_observation",
            },
        )
        self.assertEqual(profile["resource_kind"], "esp-idf")
        self.assertEqual(profile["install_sha256"], "3" * 64)
        self.assertNotIn("firmware_sha256", profile)

    def test_v060_esp_cli_requires_only_the_schema2_install_digest(self):
        common = [
            "--mode",
            "baseline",
            "--profile",
            "esp32-4mb",
            "--expect-chip",
            "esp32",
            "--address",
            "private-test-address",
            "--reset-port",
            "/dev/private-test-reset",
            "--application-bin",
            "application.bin",
            "--partition-table-bin",
            "partition-table.bin",
            "--raw-log",
            "raw.jsonl",
            "--output",
            "profile.json",
            "--board-manufacturer",
            "Espressif",
            "--board-model",
            "host-test board",
            "--module-marking",
            "host-test module",
            "--device-flash-capacity-bytes",
            str(4 * 1024 * 1024),
            "--device-psram-capacity-bytes",
            "0",
            "--manifest-sha256",
            "2" * 64,
            "--ble-backend",
            "host-test backend",
            "--ble-adapter",
            "host-test adapter",
        ]

        current = profile_bench._parse_args(
            [*common, "--install-sha256", "3" * 64]
        )
        profile_bench._validate_run_metadata(current)

        legacy = profile_bench._parse_args(
            [*common, "--firmware-sha256", "1" * 64]
        )
        with self.assertRaises(profile_bench.BenchError):
            profile_bench._validate_run_metadata(legacy)

        ambiguous = profile_bench._parse_args(
            [
                *common,
                "--firmware-sha256",
                "1" * 64,
                "--install-sha256",
                "3" * 64,
            ]
        )
        with self.assertRaises(profile_bench.BenchError):
            profile_bench._validate_run_metadata(ambiguous)

    def test_schema3_policy_accepts_five_target_discriminated_rows(self):
        policy = qualification_policy()
        self.assertNotIn("deferred_profiles", policy)
        self.assertEqual(
            [entry["resource_kind"] for entry in policy["profiles"]],
            ["esp-idf", "esp-idf", "esp-idf", "esp-idf", "rp2"],
        )
        self.assertEqual(
            [
                entry["transport"]["required_put_window"]
                for entry in policy["profiles"]
            ],
            [8, 8, 8, 8, 4],
        )
        self.assertEqual(
            [set(entry["thresholds"]) for entry in policy["profiles"]],
            [set(ESP_THRESHOLD_KEYS)] * 4 + [set(RP2_THRESHOLD_KEYS)],
        )

        with tempfile.TemporaryDirectory(prefix="pyble-oi1-v060-policy-") as tmp:
            path = write_policy(Path(tmp), policy)
            for entry in policy["profiles"]:
                with self.subTest(profile_id=entry["profile_id"]):
                    self.assertEqual(
                        profile_bench._load_policy_thresholds(
                            path,
                            entry["profile_id"],
                        ),
                        entry["thresholds"],
                    )

    def test_schema3_policy_rejects_deferral_or_target_inappropriate_rows(self):
        valid = qualification_policy()
        mutations = {}

        deferred = copy.deepcopy(valid)
        deferred["deferred_profiles"] = []
        mutations["deferred-profile-key"] = deferred

        pico_as_esp = copy.deepcopy(valid)
        pico_as_esp["profiles"][-1]["resource_kind"] = "esp-idf"
        mutations["pico-resource-kind"] = pico_as_esp

        pico_window = copy.deepcopy(valid)
        pico_window["profiles"][-1]["transport"]["required_put_window"] = 8
        mutations["pico-window"] = pico_window

        c3_window = copy.deepcopy(valid)
        c3_window["profiles"][-2]["transport"]["required_put_window"] = 4
        mutations["c3-window"] = c3_window

        pico_esp_thresholds = copy.deepcopy(valid)
        pico_esp_thresholds["profiles"][-1]["thresholds"] = {
            key: 1 for key in ESP_THRESHOLD_KEYS
        }
        mutations["pico-threshold-shape"] = pico_esp_thresholds

        c3_rp2_thresholds = copy.deepcopy(valid)
        c3_rp2_thresholds["profiles"][-2]["thresholds"] = {
            key: 1 for key in RP2_THRESHOLD_KEYS
        }
        mutations["c3-threshold-shape"] = c3_rp2_thresholds

        with tempfile.TemporaryDirectory(prefix="pyble-oi1-v060-negative-") as tmp:
            root = Path(tmp)
            valid_path = write_policy(root, valid, "valid.json")
            self.assertEqual(
                profile_bench._load_policy_thresholds(valid_path, "rpi-pico2-w"),
                valid["profiles"][-1]["thresholds"],
            )
            for name, policy in mutations.items():
                with self.subTest(mutation=name):
                    path = write_policy(root, policy, "%s.json" % name)
                    with self.assertRaises(bench.BenchError):
                        profile_bench._load_policy_thresholds(
                            path,
                            (
                                "rpi-pico2-w"
                                if name.startswith("pico")
                                else "esp32-c3-4mb"
                            ),
                        )

    def test_profile_cli_accepts_all_five_exact_profile_chip_pairs(self):
        for profile_id in PROFILE_ORDER:
            with self.subTest(profile_id=profile_id):
                target_args = (
                    [
                        "--operator-reset",
                        "--firmware-bin",
                        "firmware.bin",
                        "--firmware-uf2",
                        "firmware.uf2",
                    ]
                    if profile_id == "rpi-pico2-w"
                    else (
                        [
                            "--reset-port",
                            "/dev/private-test-reset",
                            "--application-bin",
                            "application.bin",
                            "--partition-table-bin",
                            "partition-table.bin",
                            *(
                                ["--operator-reset"]
                                if profile_id
                                == "waveshare-esp32-s3-lcd-147b"
                                else []
                            ),
                        ]
                    )
                )
                with redirect_stderr(io.StringIO()):
                    args = profile_bench._parse_args(
                        [
                            "--mode",
                            "baseline",
                            "--profile",
                            profile_id,
                            "--expect-chip",
                            PROFILE_CHIPS[profile_id],
                            "--address",
                            "private-test-address",
                            "--raw-log",
                            "raw.jsonl",
                            "--output",
                            "profile.json",
                            *target_args,
                        ],
                    )
                self.assertEqual(args.profile, profile_id)
                self.assertEqual(args.expect_chip, PROFILE_CHIPS[profile_id])


class V060ReleaseCliCardinalityTests(unittest.TestCase):
    def test_source_era_profile_counts_are_two_then_three_then_five(self):
        expected = {
            "0.4.2": 2,
            "0.5.1": 3,
            "0.6.0": 5,
        }
        for version, count in expected.items():
            with self.subTest(version=version):
                self.assertEqual(
                    len(RELEASE._release_profile_order_for_version(version)),
                    count,
                )

    def test_baseline_cli_parses_one_or_more_fragments_before_validation(self):
        for count in (1, 3, 5):
            with self.subTest(fragment_count=count):
                received = {}

                def assemble(**kwargs):
                    received.update(kwargs)
                    return Path("baseline.json"), Path("policy.json")

                argv = [
                    "assemble-oi1-baseline",
                    "baseline-inputs",
                    *("fragment-%d.json" % index for index in range(count)),
                    "--repo-root",
                    "repo",
                    "--created-at",
                    "2026-08-12T00:00:00Z",
                ]
                with (
                    mock.patch.object(RELEASE, "assemble_oi1_baseline", assemble),
                    redirect_stdout(io.StringIO()),
                    redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(RELEASE._main(argv), 0)
                self.assertEqual(
                    received["profile_fragment_paths"],
                    [Path("fragment-%d.json" % index) for index in range(count)],
                )

        with (
            self.assertRaises(SystemExit),
            redirect_stderr(io.StringIO()),
        ):
            RELEASE._main(
                [
                    "assemble-oi1-baseline",
                    "baseline-inputs",
                    "--repo-root",
                    "repo",
                    "--created-at",
                    "2026-08-12T00:00:00Z",
                ]
            )

    def test_hil_cli_parses_one_or_more_evidence_files_before_validation(self):
        for count in (1, 3, 5):
            with self.subTest(evidence_count=count):
                received = {}

                def assemble(**kwargs):
                    received.update(kwargs)
                    return Path("completed.md")

                argv = [
                    "assemble-hil-report",
                    "candidate",
                    *("evidence-%d.json" % index for index in range(count)),
                    "completed.md",
                    "--qualification-repo-root",
                    "repo",
                ]
                with (
                    mock.patch.object(
                        RELEASE,
                        "assemble_completed_hil_report",
                        assemble,
                    ),
                    redirect_stdout(io.StringIO()),
                    redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(RELEASE._main(argv), 0)
                self.assertEqual(
                    received["profile_evidence_paths"],
                    [Path("evidence-%d.json" % index) for index in range(count)],
                )

        with (
            self.assertRaises(SystemExit),
            redirect_stderr(io.StringIO()),
        ):
            RELEASE._main(
                [
                    "assemble-hil-report",
                    "candidate",
                    "completed.md",
                    "--qualification-repo-root",
                    "repo",
                ]
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
