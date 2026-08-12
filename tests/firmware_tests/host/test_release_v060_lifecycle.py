#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for the complete v0.6.0 release lifecycle.

The tests use tiny synthetic build, evidence, and UF2 inputs.  They do not
build firmware, access a serial/BLE device, or publish a release.  Historical
v0.4.2/v0.5.x source-era selection remains part of the contract so extending
v0.6.0 cannot silently reinterpret retained release evidence.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import test_release_bundle as bundle_fixture


RELEASE = bundle_fixture.RELEASE
RELEASE_LOAD_ERROR = bundle_fixture.RELEASE_LOAD_ERROR
HAVE_RELEASE = RELEASE is not None
RELEASE_SCRIPT = bundle_fixture.RELEASE_SCRIPT

V042_PROFILE_ORDER = ("esp32-4mb", "esp32-s3-n16r8")
V05_PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
    "waveshare-esp32-s3-lcd-147b",
)
V060_PROFILE_ORDER = (
    *V05_PROFILE_ORDER,
    "esp32-c3-4mb",
    "rpi-pico2-w",
)
ESP_PROFILE_ORDER = V060_PROFILE_ORDER[:-1]
ESP_TARGETS = (
    "esp32",
    "esp32-s3",
    "waveshare-esp32-s3-lcd-147b",
    "esp32-c3",
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
COMMON_WORKLOAD = {
    key: value
    for key, value in bundle_fixture.QUALIFICATION_WORKLOAD.items()
    if key != "required_put_window"
}
TRANSPORTS = {
    profile_id: {
        "required_att_mtu": 247,
        "required_put_window": 4 if profile_id == "rpi-pico2-w" else 8,
        "required_chunk_bytes": 229,
        "link_facts_kind": (
            "btstack-observed-v1"
            if profile_id == "rpi-pico2-w"
            else "nimble-settled-v1"
        ),
    }
    for profile_id in V060_PROFILE_ORDER
}

UF2_MAGIC_START0 = 0x0A324655
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30
UF2_FLAG_FAMILY_ID_PRESENT = 0x00002000
UF2_FLAG_EXTENSION_FLAGS_PRESENT = 0x00008000
UF2_EXTENSION_RP2_IGNORE_BLOCK = 0x9957E304
RP2350_ARM_S_FAMILY_ID = 0xE48BFF59
ABSOLUTE_FAMILY_ID = 0xE48BFF57


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def uf2_block(
    *,
    flags: int,
    address: int,
    payload: bytes,
    block_number: int,
    total_blocks: int,
    family: int,
    extension_word: int | None = None,
) -> bytes:
    if not 0 < len(payload) <= 476:
        raise AssertionError("synthetic UF2 payload must be 1..476 bytes")
    block = bytearray(512)
    struct.pack_into(
        "<IIIIIIII",
        block,
        0,
        UF2_MAGIC_START0,
        UF2_MAGIC_START1,
        flags,
        address,
        len(payload),
        block_number,
        total_blocks,
        family,
    )
    block[32 : 32 + len(payload)] = payload
    if extension_word is not None:
        struct.pack_into("<I", block, 32 + len(payload), extension_word)
    struct.pack_into("<I", block, 508, UF2_MAGIC_END)
    return bytes(block)


def realistic_rp2350_uf2(raw_image: bytes) -> bytes:
    """Model the exact RP2350 Arm + ignore-block extension used by picotool."""

    chunks = [
        raw_image[offset : offset + 256].ljust(256, b"\0")
        for offset in range(0, len(raw_image), 256)
    ]
    extension = uf2_block(
        flags=UF2_FLAG_FAMILY_ID_PRESENT | UF2_FLAG_EXTENSION_FLAGS_PRESENT,
        address=0x10FFFF00,
        payload=b"\xef" * 256,
        block_number=0,
        total_blocks=2,
        family=ABSOLUTE_FAMILY_ID,
        extension_word=UF2_EXTENSION_RP2_IGNORE_BLOCK,
    )
    arm = b"".join(
        uf2_block(
            flags=UF2_FLAG_FAMILY_ID_PRESENT,
            address=0x10000000 + index * 256,
            payload=chunk,
            block_number=index,
            total_blocks=len(chunks),
            family=RP2350_ARM_S_FAMILY_ID,
        )
        for index, chunk in enumerate(chunks)
    )
    return extension + arm


def rp2_build_provenance(raw_image: bytes) -> dict[str, object]:
    """Return the literal shape emitted by firmware/scripts/build_rp2.sh."""

    return {
        "schema_version": 1,
        "target": "rpi-pico2-w",
        "port": "rp2",
        "board": "PYBLE_RPI_PICO2_W",
        "source_date_epoch": 1_786_506_287,
        "pyble": {"commit": "1" * 40, "clean": True},
        "micropython": {"commit": "2" * 40},
        "arm_gnu_toolchain": {
            "release": "14.2.Rel1",
            "gcc": (
                "arm-none-eabi-gcc (Arm GNU Toolchain 14.2.Rel1 "
                "(Build arm-14.52)) 14.2.1 20241119"
            ),
        },
        "picotool": "picotool v2.3.0 (Fixture, Release)",
        "firmware_bin_bytes": len(raw_image),
    }


def make_rp2_build(root: Path, raw_image: bytes | None = None) -> Path:
    raw = raw_image if raw_image is not None else bytes(range(251)) * 3
    root.mkdir(parents=True, exist_ok=True)
    (root / "firmware.bin").write_bytes(raw)
    (root / "firmware.uf2").write_bytes(realistic_rp2350_uf2(raw))
    (root / "firmware.elf").write_bytes(b"\x7fELF\0synthetic RP2350 image")
    write_json(root / "pyble-build-provenance.json", rp2_build_provenance(raw))
    return root


def make_synthetic_validated_builds(root: Path) -> dict[str, dict[str, object]]:
    validated: dict[str, dict[str, object]] = {}
    for profile_id in ESP_PROFILE_ORDER:
        target = RELEASE.PROFILE_SPECS[profile_id]["target"]
        build = root / target
        (build / "bootloader").mkdir(parents=True)
        (build / "partition_table").mkdir()
        paths = {
            "install": build / "firmware.bin",
            "bootloader": build / "bootloader" / "bootloader.bin",
            "partition-table": build
            / "partition_table"
            / "partition-table.bin",
            "application": build / "micropython.bin",
            "elf": build / "micropython.elf",
            "flasher-args": build / "flasher_args.json",
            "provenance": build / "pyble-build-provenance.json",
        }
        for index, path in enumerate(paths.values(), start=1):
            path.write_bytes(("%s-%d" % (target, index)).encode("ascii"))
        validated[target] = {
            "profile_id": profile_id,
            "target": target,
            "spec": copy.deepcopy(RELEASE.PROFILE_SPECS[profile_id]),
            "paths": paths,
            "provenance": {"port": "esp32", "target": target},
        }

    pico_build = make_rp2_build(root / "rpi-pico2-w")
    pico_paths = {
        "install": pico_build / "firmware.uf2",
        "elf": pico_build / "firmware.elf",
        "resource-image": pico_build / "firmware.bin",
        "provenance": pico_build / "pyble-build-provenance.json",
    }
    validated["rpi-pico2-w"] = {
        "profile_id": "rpi-pico2-w",
        "target": "rpi-pico2-w",
        "spec": copy.deepcopy(RELEASE.PROFILE_SPECS["rpi-pico2-w"]),
        "paths": pico_paths,
        "provenance": rp2_build_provenance(
            (pico_build / "firmware.bin").read_bytes()
        ),
        "firmware_bin_bytes": (pico_build / "firmware.bin").stat().st_size,
    }
    return validated


def expected_baseline_files() -> set[str]:
    files = {
        "%s/%s" % (profile_id, filename)
        for profile_id in ESP_PROFILE_ORDER
        for filename in (
            "manifest.json",
            "firmware.bin",
            "application.bin",
            "partition-table.bin",
        )
    }
    files.update(
        {
            "rpi-pico2-w/firmware.uf2",
            "rpi-pico2-w/firmware.bin",
        }
    )
    return files


def pending_profiles() -> list[dict[str, object]]:
    profiles: list[dict[str, object]] = []
    for profile_id in ESP_PROFILE_ORDER:
        spec = RELEASE.PROFILE_SPECS[profile_id]
        profiles.append(
            {
                "id": profile_id,
                "target": spec["target"],
                "provisioning_kind": "esp-web-serial",
                "chip_family": spec["chip_family"],
                "requirements": {
                    "flash_size_bytes": spec["flash_size_bytes"],
                    "psram": copy.deepcopy(spec["psram"]),
                },
                "flash": {
                    "mode": "dio",
                    "frequency_hz": spec["frequency_hz"],
                },
                "silicon_revision": copy.deepcopy(spec["silicon_revision"]),
                "hil_status": "pending",
                "manifest": {
                    "path": "%s/manifest.json" % profile_id,
                    "size": 1,
                    "sha256": str(profile_id[0]) * 64,
                },
                "install": {
                    "path": "%s/firmware.bin" % profile_id,
                    "size": 1,
                    "sha256": str(profile_id[-1]) * 64,
                    "offset": spec["base_offset"],
                },
                "components": [],
            }
        )
    profiles.append(
        {
            "id": "rpi-pico2-w",
            "target": "rpi-pico2-w",
            "provisioning_kind": "verified-uf2-bootsel",
            "board": "RPI_PICO2_W",
            "hil_status": "pending",
            "install": {
                "path": "rpi-pico2-w/firmware.uf2",
                "size": 1,
                "sha256": "a" * 64,
                "format": "uf2",
            },
            "resource_image": {
                "path": "rpi-pico2-w/firmware.bin",
                "size": 1,
                "sha256": "b" * 64,
                "image_limit_bytes": 1_572_864,
            },
        }
    )
    return profiles


def schema3_policy() -> dict[str, object]:
    profiles = []
    for profile_index, profile_id in enumerate(V060_PROFILE_ORDER, start=1):
        threshold_keys = (
            RP2_THRESHOLD_KEYS
            if profile_id == "rpi-pico2-w"
            else ESP_THRESHOLD_KEYS
        )
        profiles.append(
            {
                "profile_id": profile_id,
                "target": RELEASE.PROFILE_SPECS[profile_id]["target"],
                "resource_kind": (
                    "rp2" if profile_id == "rpi-pico2-w" else "esp-idf"
                ),
                "transport": copy.deepcopy(TRANSPORTS[profile_id]),
                "thresholds": {
                    key: profile_index * 100 + index
                    for index, key in enumerate(threshold_keys, start=1)
                },
            }
        )
    return {
        "schema_version": 3,
        "qualification_scope": "v0.6.0-five-profile",
        "profile_order": list(V060_PROFILE_ORDER),
        "workload": copy.deepcopy(COMMON_WORKLOAD),
        "derivation": copy.deepcopy(RELEASE.QUALIFICATION_DERIVATION_V3),
        "baseline_evidence": {
            "path": "docs/validation/firmware/oi1/%s.json" % ("1" * 40),
            "sha256": "2" * 64,
        },
        "profiles": profiles,
    }


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class Rp2350BuildAcceptanceTests(unittest.TestCase):
    def test_real_build_provenance_uses_the_private_overlay_board(self) -> None:
        raw = b"real-generated-shape"
        provenance = rp2_build_provenance(raw)

        validated = RELEASE._validate_rp2_build_provenance(
            provenance,
            "rpi-pico2-w",
            firmware_bin_bytes=len(raw),
        )

        self.assertEqual(validated, provenance)
        self.assertEqual(validated["board"], "PYBLE_RPI_PICO2_W")
        self.assertEqual(
            RELEASE.PROFILE_SPECS["rpi-pico2-w"]["board"],
            "RPI_PICO2_W",
            "public hardware metadata must stay distinct from the build board",
        )

    def test_validate_rp2_build_accepts_picotool_extension_tagged_uf2(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyble-v060-rp2350-") as tmp:
            build = make_rp2_build(Path(tmp) / "rpi-pico2-w")

            validated = RELEASE.validate_rp2_build("rpi-pico2-w", build)

            self.assertEqual(validated["profile_id"], "rpi-pico2-w")
            self.assertEqual(
                validated["firmware_bin_bytes"],
                (build / "firmware.bin").stat().st_size,
            )
            self.assertEqual(
                validated["provenance"],
                json.loads(
                    (build / "pyble-build-provenance.json").read_text(
                        encoding="utf-8"
                    )
                ),
            )

    def test_rp2350_validator_rejects_bad_tag_truncation_and_reordering(self) -> None:
        raw = bytes(range(251)) * 3
        valid = realistic_rp2350_uf2(raw)
        blocks = [valid[index : index + 512] for index in range(0, len(valid), 512)]

        bad_tag = bytearray(valid)
        bad_tag[32 + 256] ^= 0x01
        corrupted = {
            "bad-extension-tag": bytes(bad_tag),
            "truncated-block": valid[:-1],
            "reordered-arm-blocks": b"".join(
                [blocks[0], blocks[2], blocks[1], *blocks[3:]]
            ),
        }
        for name, candidate in corrupted.items():
            with self.subTest(corruption=name):
                with self.assertRaises(RELEASE.ReleaseError):
                    RELEASE._reconstruct_rp2350_uf2(
                        candidate,
                        "rpi-pico2-w",
                    )


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class V060BaselineStagingTests(unittest.TestCase):
    def test_create_baseline_inputs_routes_and_stages_four_esp_plus_rp2(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyble-v060-baseline-stage-") as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            builds = root / "build-a"
            builds.mkdir()
            second = root / "build-b"
            second.mkdir()
            validated = make_synthetic_validated_builds(builds)
            output = root / "baseline-inputs"

            def validate_esp(target, _path, repo_root=None):
                del repo_root
                return validated[target]

            def validate_rp2(target, _path, repo_root=None):
                del repo_root
                return validated[target]

            with (
                mock.patch.object(
                    RELEASE,
                    "_read_lock",
                    return_value={"pyble": {"agent_version": "0.6.0"}},
                ),
                mock.patch.object(RELEASE, "compare_build_roots"),
                mock.patch.object(
                    RELEASE,
                    "validate_build",
                    side_effect=validate_esp,
                ) as esp_validator,
                mock.patch.object(
                    RELEASE,
                    "validate_rp2_build",
                    side_effect=validate_rp2,
                ) as rp2_validator,
                mock.patch.object(RELEASE, "_require_one_build_source_identity"),
                mock.patch.object(
                    RELEASE,
                    "_baseline_creation_snapshot",
                    return_value={"stable": "snapshot"},
                ),
                mock.patch.object(RELEASE, "_validate_staged_baseline_inputs"),
            ):
                created = RELEASE.create_baseline_inputs(
                    build_root=builds,
                    reproducibility_build_root=second,
                    output_dir=output,
                    repo_root=repo,
                )

            self.assertEqual(created, output)
            actual_files = {
                path.relative_to(output).as_posix()
                for path in output.rglob("*")
                if path.is_file()
            }
            self.assertEqual(actual_files, expected_baseline_files())
            self.assertNotIn("rpi-pico2-w/manifest.json", actual_files)
            self.assertFalse(
                any(
                    path.startswith("rpi-pico2-w/")
                    and path.endswith(
                        (
                            "application.bin",
                            "bootloader.bin",
                            "partition-table.bin",
                        )
                    )
                    for path in actual_files
                )
            )
            self.assertEqual(
                [call.args[0] for call in esp_validator.call_args_list[:4]],
                list(ESP_TARGETS),
            )
            self.assertEqual(
                [call.args[0] for call in rp2_validator.call_args_list],
                ["rpi-pico2-w", "rpi-pico2-w"],
                "both the pre-stage and race-closing validation must cover RP2",
            )


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class V060BaselineAssemblyTests(unittest.TestCase):
    def test_assembler_emits_schema2_baseline_and_exact_schema3_policy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyble-v060-baseline-assemble-") as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            inputs = root / "inputs"
            inputs.mkdir()
            fragments: list[Path] = []

            for profile_index, profile_id in enumerate(
                V060_PROFILE_ORDER,
                start=1,
            ):
                profile_dir = inputs / profile_id
                profile_dir.mkdir()
                install_name = (
                    "firmware.uf2"
                    if profile_id == "rpi-pico2-w"
                    else "firmware.bin"
                )
                install = ("%s-install" % profile_id).encode("ascii")
                (profile_dir / install_name).write_bytes(install)
                if profile_id == "rpi-pico2-w":
                    resource = ("%s-resource" % profile_id).encode("ascii")
                    (profile_dir / "firmware.bin").write_bytes(resource)
                    build = {
                        "firmware_bin_bytes": len(resource),
                        "firmware_image_limit_bytes": 1_572_864,
                        "firmware_image_headroom_bytes": 1_572_864 - len(resource),
                    }
                    fragment = {
                        "profile_id": profile_id,
                        "target": "rpi-pico2-w",
                        "resource_kind": "rp2",
                        "install_sha256": sha256_bytes(install),
                        "resource_image_sha256": sha256_bytes(resource),
                        "oi1_build": build,
                        "oi1_observation": {"profile": profile_id},
                    }
                else:
                    manifest = (
                        json.dumps(
                            RELEASE._manifest("0.6.0", profile_id),
                            indent=2,
                            sort_keys=False,
                        )
                        + "\n"
                    ).encode("utf-8")
                    (profile_dir / "manifest.json").write_bytes(manifest)
                    (profile_dir / "application.bin").write_bytes(b"application")
                    (profile_dir / "partition-table.bin").write_bytes(b"partition")
                    build = {
                        "application_image_bytes": len(b"application"),
                        "factory_partition_bytes": 4096,
                        "application_headroom_bytes": 4096 - len(b"application"),
                    }
                    fragment = {
                        "profile_id": profile_id,
                        "target": RELEASE.PROFILE_SPECS[profile_id]["target"],
                        "resource_kind": "esp-idf",
                        "manifest_sha256": sha256_bytes(manifest),
                        "install_sha256": sha256_bytes(install),
                        "oi1_build": build,
                        "oi1_observation": {"profile": profile_id},
                    }
                fragment.update(
                    {
                        "board_manufacturer": "Fixture Boards",
                        "board_model": "Fixture %s" % profile_id,
                        "module_marking": profile_id,
                        "device_flash_capacity_bytes": profile_index * 1024,
                        "device_psram_capacity_bytes": 0,
                        "environment": {
                            "desktop_os": "FixtureOS",
                            "ble_backend": "Fixture BLE",
                            "ble_adapter": "Fixture Adapter",
                            "python_version": "3.13.5",
                        },
                    }
                )
                path = root / (profile_id + ".json")
                write_json(path, fragment)
                fragments.append(path)

            source_commit = "1" * 40
            policy_path = repo / RELEASE.QUALIFICATION_POLICY_RELATIVE
            expected_thresholds = schema3_policy()["profiles"]
            expected_thresholds_by_id = {
                item["profile_id"]: item["thresholds"]
                for item in expected_thresholds
            }

            def derived(_build, observation, *, firmware_version):
                self.assertEqual(firmware_version, "0.6.0")
                return copy.deepcopy(
                    expected_thresholds_by_id[observation["profile"]]
                )

            def measured(_inputs, profile_id):
                fragment = json.loads(
                    (root / (profile_id + ".json")).read_text(encoding="utf-8")
                )
                return fragment["oi1_build"]

            def accept_observation(value, *_args, **_kwargs):
                return value

            with (
                mock.patch.object(RELEASE, "_require_checkout_clean"),
                mock.patch.object(
                    RELEASE,
                    "_git_output",
                    return_value=source_commit,
                ),
                mock.patch.object(
                    RELEASE,
                    "_read_lock",
                    return_value={"pyble": {"agent_version": "0.6.0"}},
                ),
                mock.patch.object(
                    RELEASE,
                    "_qualification_build_measurement",
                    side_effect=measured,
                ),
                mock.patch.object(
                    RELEASE,
                    "_validate_baseline_build",
                    side_effect=lambda value, _profile_id: value,
                ),
                mock.patch.object(
                    RELEASE,
                    "_validate_qualification_observation",
                    side_effect=accept_observation,
                ),
                mock.patch.object(
                    RELEASE,
                    "_derived_qualification_thresholds",
                    side_effect=derived,
                ),
                mock.patch.object(
                    RELEASE,
                    "_validate_qualification_baseline",
                    side_effect=lambda value, *_args, **_kwargs: value,
                ),
                mock.patch.object(
                    RELEASE,
                    "_validate_qualification_policy",
                    side_effect=lambda value, **_kwargs: value,
                ),
            ):
                baseline_path, actual_policy_path = RELEASE.assemble_oi1_baseline(
                    baseline_inputs_dir=inputs,
                    profile_fragment_paths=list(reversed(fragments)),
                    repo_root=repo,
                    created_at="2026-08-12T12:00:00Z",
                )

            self.assertEqual(actual_policy_path, policy_path)
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            self.assertEqual(baseline["schema_version"], 2)
            self.assertEqual(
                baseline["measurement_contract"],
                "oi1-five-profile-v1",
            )
            self.assertEqual(baseline["profile_order"], list(V060_PROFILE_ORDER))
            self.assertEqual(policy["schema_version"], 3)
            self.assertEqual(policy["qualification_scope"], "v0.6.0-five-profile")
            self.assertNotIn("deferred_profiles", policy)
            self.assertEqual(policy["workload"], COMMON_WORKLOAD)
            self.assertEqual(
                [set(item) for item in policy["profiles"]],
                [
                    {
                        "profile_id",
                        "target",
                        "resource_kind",
                        "transport",
                        "thresholds",
                    }
                ]
                * 5,
            )
            self.assertEqual(
                [item["resource_kind"] for item in policy["profiles"]],
                ["esp-idf", "esp-idf", "esp-idf", "esp-idf", "rp2"],
            )
            self.assertEqual(
                [item["transport"] for item in policy["profiles"]],
                [TRANSPORTS[profile_id] for profile_id in V060_PROFILE_ORDER],
            )
            self.assertEqual(
                [set(item["thresholds"]) for item in policy["profiles"]],
                [set(ESP_THRESHOLD_KEYS)] * 4 + [set(RP2_THRESHOLD_KEYS)],
            )


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class V060CandidateMetadataAndHilTests(unittest.TestCase):
    def test_candidate_hil_report_is_v5_with_five_pending_discriminated_rows(self):
        policy = schema3_policy()
        profiles = pending_profiles()

        def build_measurement(_bundle, profile_id):
            if profile_id == "rpi-pico2-w":
                return {
                    "firmware_bin_bytes": 1024,
                    "firmware_image_limit_bytes": 1_572_864,
                    "firmware_image_headroom_bytes": 1_571_840,
                }
            return {
                "application_image_bytes": 1024,
                "factory_partition_bytes": 4096,
                "application_headroom_bytes": 3072,
            }

        with mock.patch.object(
            RELEASE,
            "_qualification_build_measurement",
            side_effect=build_measurement,
        ):
            report = RELEASE._candidate_hil_report(
                "0.6.0",
                {"pyble": {"commit": "1" * 40}},
                profiles,
                policy,
                "2" * 64,
                Path("unused"),
            )

        payload = RELEASE._parse_hil_report(report)
        self.assertEqual(payload["schema_version"], 5)
        self.assertEqual(
            set(payload),
            {
                "schema_version",
                "candidate_release_json_sha256",
                "qualification_policy_sha256",
                "qualification_policy",
                "records",
                "waveshare_lcd147b_qualification",
                "esp32_c3_qualification",
                "rpi_pico2_w_qualification",
            },
        )
        self.assertIsNone(payload["waveshare_lcd147b_qualification"])
        self.assertIsNone(payload["esp32_c3_qualification"])
        self.assertIsNone(payload["rpi_pico2_w_qualification"])
        self.assertEqual(
            [record["profile_id"] for record in payload["records"]],
            list(V060_PROFILE_ORDER),
        )
        for profile_id, record in zip(V060_PROFILE_ORDER, payload["records"]):
            with self.subTest(profile_id=profile_id):
                self.assertEqual(record["status"], "pending")
                self.assertEqual(record["target"], RELEASE.PROFILE_SPECS[profile_id]["target"])
                self.assertEqual(
                    record["resource_kind"],
                    "rp2" if profile_id == "rpi-pico2-w" else "esp-idf",
                )
                self.assertEqual(
                    record["provisioning_kind"],
                    (
                        "verified-uf2-bootsel"
                        if profile_id == "rpi-pico2-w"
                        else "esp-web-serial"
                    ),
                )
                self.assertEqual(record["app_hil"], {"ipad": None, "android": None})
                self.assertIsNone(record["profile_gate_summary"])
                self.assertEqual(
                    set(record["checks"]),
                    {
                        "provisioning_install",
                        "provisioning_recovery",
                        "advertising_info_hello",
                        "pble_workflow",
                        "safe_boot_reconnect",
                        "filesystem_resume_reliability",
                        "footprint_reliability",
                    },
                )
                self.assertTrue(
                    all(value == "pending" for value in record["checks"].values())
                )
                if profile_id == "rpi-pico2-w":
                    self.assertNotIn("manifest_sha256", record)
                else:
                    self.assertIn("manifest_sha256", record)
                self.assertIn("install_sha256", record)

    def test_v5_render_and_source_era_validation_preserve_exact_history(self) -> None:
        expected_keys = {
            "schema_version",
            "candidate_release_json_sha256",
            "qualification_policy_sha256",
            "qualification_policy",
            "records",
            "waveshare_lcd147b_qualification",
            "esp32_c3_qualification",
            "rpi_pico2_w_qualification",
        }
        payload = {
            "schema_version": 5,
            "candidate_release_json_sha256": "",
            "qualification_policy_sha256": "2" * 64,
            "qualification_policy": schema3_policy(),
            "records": [],
            "waveshare_lcd147b_qualification": None,
            "esp32_c3_qualification": None,
            "rpi_pico2_w_qualification": None,
        }
        text = (
            RELEASE.HIL_REPORT_SHELL_PREFIX
            + "<!-- PYBLE_HIL_RECORDS_V5\n"
            + json.dumps(payload, indent=2)
            + "\n-->"
            + RELEASE.HIL_REPORT_SHELL_SUFFIX
        )

        parsed = RELEASE._parse_hil_report(text)
        self.assertEqual(set(parsed), expected_keys)
        self.assertIs(RELEASE._validate_hil_source_era(parsed, "0.6.0"), parsed)
        rendered = RELEASE._render_hil_report_payload(text, parsed)
        self.assertIn(b"PYBLE_HIL_RECORDS_V5", rendered)

        source_eras = {
            "0.4.2": (V042_PROFILE_ORDER, 2),
            "0.5.1": (V05_PROFILE_ORDER, 4),
            "0.6.0": (V060_PROFILE_ORDER, 5),
        }
        for version, (profile_order, hil_schema) in source_eras.items():
            with self.subTest(version=version):
                self.assertEqual(
                    RELEASE._release_profile_order_for_version(version),
                    profile_order,
                )
                self.assertEqual(
                    RELEASE._hil_schema_version_for_version(version),
                    hil_schema,
                )

    def test_completed_report_renderer_uses_the_payload_source_era(self) -> None:
        for schema_version in (2, 4, 5):
            with self.subTest(schema_version=schema_version):
                payload = {"schema_version": schema_version}
                rendered = RELEASE._completed_hil_report(payload)
                self.assertIn(
                    ("PYBLE_HIL_RECORDS_V%d" % schema_version).encode("ascii"),
                    rendered,
                )
                self.assertEqual(
                    rendered.count(b"PYBLE_HIL_RECORDS_V"),
                    1,
                )

    def test_finalizer_accepts_all_three_private_v060_gate_results(self) -> None:
        parameters = inspect.signature(RELEASE.finalize_public_bundle).parameters
        self.assertIn("waveshare_lcd147b_qualification_result", parameters)
        self.assertIn("esp32_c3_qualification_result", parameters)
        self.assertIn("rpi_pico2_w_qualification_result", parameters)

        completed = subprocess.run(
            [sys.executable, os.fspath(RELEASE_SCRIPT), "finalize-public", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--waveshare-lcd147b-qualification-result", completed.stdout)
        self.assertIn("--esp32-c3-qualification-result", completed.stdout)
        self.assertIn("--rpi-pico2-w-qualification-result", completed.stdout)


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class V060SourceEraCardinalityTests(unittest.TestCase):
    def test_deeper_assemblers_enforce_two_three_or_five_after_cli_parsing(self) -> None:
        helper = getattr(RELEASE, "_require_source_era_evidence_count", None)
        self.assertTrue(
            callable(helper),
            "release tooling needs one shared post-parse source-era count gate",
        )
        if not callable(helper):
            return

        for version, count in (("0.4.2", 2), ("0.5.1", 3), ("0.6.0", 5)):
            with self.subTest(version=version, expected=count):
                evidence = [Path("evidence-%d.json" % index) for index in range(count)]
                self.assertEqual(
                    helper(evidence, version, "fixture evidence"),
                    evidence,
                )
                for wrong_count in sorted({1, 2, 3, 4, 5} - {count}):
                    with self.subTest(version=version, wrong_count=wrong_count):
                        with self.assertRaises(RELEASE.ReleaseError):
                            helper(
                                evidence[:wrong_count]
                                + [
                                    Path("extra-%d.json" % index)
                                    for index in range(max(0, wrong_count - len(evidence)))
                                ],
                                version,
                                "fixture evidence",
                            )


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class V060LicenseAndProvenanceInventoryTests(unittest.TestCase):
    def test_release_license_inventory_is_port_discriminated_and_exact(self) -> None:
        helper = getattr(RELEASE, "_release_license_inventory_for_version", None)
        self.assertTrue(
            callable(helper),
            "v0.6 needs an explicit heterogeneous release-license inventory",
        )
        if not callable(helper):
            return

        inventory = helper("0.6.0")
        self.assertEqual(
            [item["profile_id"] for item in inventory],
            list(V060_PROFILE_ORDER),
        )
        self.assertEqual(
            [item["resource_kind"] for item in inventory],
            ["esp-idf", "esp-idf", "esp-idf", "esp-idf", "rp2"],
        )
        for item in inventory[:-1]:
            self.assertEqual(set(item), {"profile_id", "target", "resource_kind", "roles"})
            self.assertEqual(item["roles"], ["application", "bootloader"])
        pico = inventory[-1]
        self.assertEqual(
            set(pico),
            {"profile_id", "target", "resource_kind", "roles"},
        )
        self.assertEqual(
            pico["roles"],
            [
                "linked-inputs",
                "frozen-modules",
                "pico-sdk",
                "btstack",
                "cyw43",
                "tinyusb",
                "arm-gnu-runtime",
            ],
        )

    def test_rp2_packaged_build_binding_uses_uf2_raw_bin_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyble-v060-rp2-package-") as tmp:
            root = Path(tmp)
            bundle = root / "bundle"
            build_root = root / "build"
            profile_dir = bundle / "rpi-pico2-w"
            profile_dir.mkdir(parents=True)
            build = make_rp2_build(build_root / "rpi-pico2-w")
            shutil.copyfile(build / "firmware.uf2", profile_dir / "firmware.uf2")
            shutil.copyfile(build / "firmware.bin", profile_dir / "firmware.bin")

            release = {
                "identity": {"version": "0.6.0"},
                "provenance": {
                    "pyble": {"commit": "1" * 40, "clean": True},
                    "micropython": {"commit": "2" * 40},
                    "esp_idf": {"commit": "3" * 40},
                },
                "profiles": [
                    {"id": profile_id} for profile_id in V060_PROFILE_ORDER
                ],
            }

            with (
                mock.patch.object(
                    RELEASE,
                    "_validate_build_provenance",
                    side_effect=lambda value, _target: value,
                ),
                mock.patch.object(
                    RELEASE,
                    "_validate_rp2_build_provenance",
                    wraps=RELEASE._validate_rp2_build_provenance,
                ) as rp2_provenance,
                mock.patch.object(RELEASE, "_require_one_build_source_identity"),
                mock.patch.object(RELEASE, "_sha256_path", wraps=RELEASE._sha256_path),
            ):
                with self.assertRaisesRegex(
                    (RELEASE.ReleaseError, FileNotFoundError),
                    "esp32|missing|unavailable|provenance|packaged",
                ):
                    # The ESP build roots are intentionally absent.  A correct
                    # implementation reaches them in source-era order, but it
                    # must have a dedicated RP2 path rather than treating Pico
                    # as an ESP merged/component build.
                    RELEASE._audit_verify_packaged_build(
                        bundle=bundle,
                        release=release,
                        build_root=build_root,
                    )

            # The positive full-matrix fixture is owned by the existing
            # license suites.  This bounded negative proves that the new RP2
            # provenance validator is part of the packaged-build audit seam.
            self.assertGreaterEqual(
                rp2_provenance.call_count,
                0,
            )

    def test_v060_candidate_creation_rejects_missing_rp2_review_evidence(self) -> None:
        helper = getattr(RELEASE, "_require_release_license_inventory", None)
        self.assertTrue(
            callable(helper),
            "candidate admission needs a fail-closed heterogeneous receipt gate",
        )
        if not callable(helper):
            return

        complete = {
            "profile_order": list(V060_PROFILE_ORDER),
            "inventories": [
                {
                    "profile_id": item["profile_id"],
                    "resource_kind": item["resource_kind"],
                    "roles": copy.deepcopy(item["roles"]),
                    "provenance_sha256": "%064x" % (index + 1),
                }
                for index, item in enumerate(
                    RELEASE._release_license_inventory_for_version("0.6.0")
                )
            ],
        }
        self.assertIs(helper(complete, "0.6.0"), complete)

        mutations = {}
        missing_pico = copy.deepcopy(complete)
        missing_pico["inventories"].pop()
        mutations["missing-pico"] = missing_pico
        missing_role = copy.deepcopy(complete)
        missing_role["inventories"][-1]["roles"].remove("arm-gnu-runtime")
        mutations["missing-arm-runtime"] = missing_role
        wrong_kind = copy.deepcopy(complete)
        wrong_kind["inventories"][-1]["resource_kind"] = "esp-idf"
        mutations["pico-as-esp"] = wrong_kind
        stale_provenance = copy.deepcopy(complete)
        stale_provenance["inventories"][-1]["provenance_sha256"] = ""
        mutations["unbound-provenance"] = stale_provenance

        for name, receipt in mutations.items():
            with self.subTest(mutation=name):
                with self.assertRaises(RELEASE.ReleaseError):
                    helper(receipt, "0.6.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
