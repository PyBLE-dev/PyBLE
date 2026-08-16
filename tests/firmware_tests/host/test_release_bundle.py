#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] X-10/X-11 — Host contract for the browser-flashing release bundle.
#
# Frozen sources:
#   docs/specifications/firmware/browser-flashing.md §§1–10
#   docs/specifications/firmware/specs.md BLD-5…8, BLD-14, BLD-17…22
#   docs/specifications/firmware/TDD.md §10
#
# Production interface pinned by this suite:
#
#   firmware/scripts/release_bundle.py
#     ReleaseError
#     validate_build(target: str, build_dir: Path) -> object
#     create_bundle(
#         build_root: Path,
#         output_dir: Path,
#         repo_root: Path,
#         installer_version: str,
#         built_at: str,
#         provenance: dict,
#         audited_notice: Path,
#         license_evidence_dir: Path,
#         license_build_root: Path,
#         public: bool = False,
#     ) -> Path
#     validate_bundle(bundle_dir: Path, public: bool = False) -> dict
#     compare_build_roots(left: Path, right: Path) -> None
#     generate_third_party_licenses(build_root: Path, repo_root: Path) -> str
#
# `public=False` is the access-controlled candidate state and permits only the
# HIL status `pending` or `passed`; `public=True` requires every exact profile
# to be `passed`. Public/candidate state is never inferred from file presence.
#
# The tests deliberately generate all binary fixtures in TemporaryDirectory.
# No opaque binary, generated release, local firmware build, or hardware result
# is checked into the repository.

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
import struct
import subprocess
import tempfile
import tomllib
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "release_bundle.py"
BUILD_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "build.sh"
OVERLAYS = REPO_ROOT / "firmware" / "board_overlays"
WEB_RELEASE_SCHEMA = (
    REPO_ROOT / "tools" / "web" / "src" / "lib" / "firmware-release-schema.json"
)
HIL_MARKER = re.compile(
    r"<!--\s*PYBLE_HIL_RECORDS_V([24])\s*(\{.*?\})\s*-->",
    re.DOTALL,
)

HISTORICAL_V042_PROFILE_ORDER = ("esp32-4mb", "esp32-s3-n16r8")
PROSPECTIVE_FIRMWARE_VERSION = "0.5.1"
RELEASE_PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
    "waveshare-esp32-s3-lcd-147b",
)
V060_RELEASE_PROFILE_ORDER = (
    *RELEASE_PROFILE_ORDER,
    "esp32-c3-4mb",
    "rpi-pico2-w",
)
QUALIFICATION_POLICY_RELATIVE = "firmware/qualification/oi1-gates.json"
QUALIFICATION_WORKLOAD = {
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
    "required_put_window": 8,
    "required_chunk_bytes": 229,
}
QUALIFICATION_DERIVATION_V1 = {
    "application_image": "exact-byte-identical-two-root-v1",
    "application_headroom": "factory-minus-application-v1",
    "heap_floor": "floor-min-1024-v1",
    "boot_ceiling": "ceil-max-10-v1",
    "goodput_floor": "floor-min-100-v1",
}
QUALIFICATION_DERIVATION = {
    "application_image": "exact-byte-identical-two-root-v1",
    "application_headroom": "factory-minus-application-v1",
    "heap_floor": "floor-min-1024-v1",
    "boot_ceiling": "fixed-product-slo-3000-v3",
    "goodput_floor": "floor-95pct-min-100-v2",
}
QUALIFICATION_THRESHOLDS = {
    "application_image_max_bytes": 4096,
    "application_headroom_min_bytes": 1024 * 1024,
    "gc_free_min_bytes": 4096,
    "idf_internal_free_min_bytes": 4096,
    "idf_internal_largest_block_min_bytes": 4096,
    "idf_internal_minimum_free_min_bytes": 4096,
    "reset_to_service_advertisement_max_ms": 1000,
    "put_committed_goodput_min_bytes_per_second": 60_000,
    "get_verified_goodput_min_bytes_per_second": 60_000,
}
ROLE_ORDER = ("bootloader", "partition-table", "application")
PROFILE_SPECS = {
    "esp32-4mb": {
        "target": "esp32",
        "idf_target": "esp32",
        "chip_family": "ESP32",
        "chip_id": 0,
        "flash_size": "4MB",
        "flash_size_bytes": 4 * 1024 * 1024,
        "flash_freq": "40m",
        "frequency_hz": 40_000_000,
        "header_size_freq": 0x20,
        "base_offset": 0x1000,
        "component_offsets": (0x1000, 0x8000, 0x10000),
        "psram": {"required": False, "size_bytes": 0, "type": "not-required"},
        "silicon_revision": {"minimum_full": 0, "maximum_full": 399},
    },
    "esp32-s3-n16r8": {
        "target": "esp32-s3",
        "idf_target": "esp32s3",
        "chip_family": "ESP32-S3",
        "chip_id": 9,
        "flash_size": "16MB",
        "flash_size_bytes": 16 * 1024 * 1024,
        "flash_freq": "80m",
        "frequency_hz": 80_000_000,
        "header_size_freq": 0x4F,
        "base_offset": 0,
        "component_offsets": (0, 0x8000, 0x10000),
        "psram": {
            "required": True,
            "size_bytes": 8 * 1024 * 1024,
            "type": "octal",
        },
        "silicon_revision": {"minimum_full": 0, "maximum_full": 99},
    },
    "waveshare-esp32-s3-lcd-147b": {
        "target": "waveshare-esp32-s3-lcd-147b",
        "idf_target": "esp32s3",
        "chip_family": "ESP32-S3",
        "chip_id": 9,
        "flash_size": "16MB",
        "flash_size_bytes": 16 * 1024 * 1024,
        "flash_freq": "80m",
        "frequency_hz": 80_000_000,
        "header_size_freq": 0x4F,
        "base_offset": 0,
        "component_offsets": (0, 0x8000, 0x10000),
        "psram": {
            "required": True,
            "size_bytes": 8 * 1024 * 1024,
            "type": "octal",
        },
        "silicon_revision": {"minimum_full": 0, "maximum_full": 99},
    },
    "esp32-c3-4mb": {
        "target": "esp32-c3",
        "idf_target": "esp32c3",
        "chip_family": "ESP32-C3",
        "chip_id": 5,
        "flash_size": "4MB",
        "flash_size_bytes": 4 * 1024 * 1024,
        "flash_freq": "80m",
        "frequency_hz": 80_000_000,
        "header_size_freq": 0x2F,
        "base_offset": 0,
        "component_offsets": (0, 0x8000, 0x10000),
        "psram": {"required": False, "size_bytes": 0, "type": "not-required"},
        "silicon_revision": {"minimum_full": 3, "maximum_full": 199},
    },
}
TARGET_TO_PROFILE = {
    spec["target"]: profile_id for profile_id, spec in PROFILE_SPECS.items()
}
BUILD_PROFILE_ORDER = tuple(PROFILE_SPECS)


def _load_release_module():
    if not RELEASE_SCRIPT.is_file():
        return None, "missing production script: %s" % RELEASE_SCRIPT
    spec = importlib.util.spec_from_file_location(
        "pyble_release_bundle", RELEASE_SCRIPT
    )
    if spec is None or spec.loader is None:
        return None, "cannot construct import spec for %s" % RELEASE_SCRIPT
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - reported by the presence test.
        return None, "cannot import release_bundle.py: %s" % exc
    return module, ""


RELEASE, RELEASE_LOAD_ERROR = _load_release_module()
HAVE_RELEASE = RELEASE is not None


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: Path, relative: str, **extra):
    result = {
        "path": relative,
        "size": path.stat().st_size,
        "sha256": sha256_path(path),
    }
    result.update(extra)
    return result


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def canonical_json_bytes(value) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def fixture_oi1_build(build_root: Path, profile_id: str) -> dict[str, int]:
    spec = PROFILE_SPECS[profile_id]
    application_bytes = (
        build_root / spec["target"] / "micropython.bin"
    ).stat().st_size
    factory_bytes = 0x200000 if spec["chip_family"] == "ESP32-S3" else 0x1F0000
    return {
        "application_image_bytes": application_bytes,
        "factory_partition_bytes": factory_bytes,
        "application_headroom_bytes": factory_bytes - application_bytes,
    }


def fixture_oi1_thresholds(
    build: dict[str, int],
    observation: dict,
    firmware_version: str = PROSPECTIVE_FIRMWARE_VERSION,
) -> dict[str, int]:
    heap_samples = (
        observation["heap_post_hello"]
        + observation["heap_post_roundtrip"]
        + [observation["heap_post_reliability"]]
    )
    source_core = RELEASE._firmware_release_core(
        firmware_version,
        "fixture firmware version",
    )
    reset_max = max(observation["reset_to_service_advertisement_ms"])
    put_min = min(
        observation["put_committed_goodput_bytes_per_second"]
    )
    get_min = min(
        observation["get_verified_goodput_bytes_per_second"]
    )
    if source_core >= (0, 5, 0):
        reset_threshold = 3000
        put_min = (put_min * 95) // 100
        get_min = (get_min * 95) // 100
    else:
        reset_threshold = ((reset_max + 9) // 10) * 10
    return {
        "application_image_max_bytes": build["application_image_bytes"],
        "application_headroom_min_bytes": build["application_headroom_bytes"],
        "gc_free_min_bytes": (
            min(sample["gc_free_bytes"] for sample in heap_samples) // 1024
        )
        * 1024,
        "idf_internal_free_min_bytes": (
            min(
                sample["idf_internal_free_bytes"]
                for sample in heap_samples
            )
            // 1024
        )
        * 1024,
        "idf_internal_largest_block_min_bytes": (
            min(
                sample["idf_internal_largest_block_bytes"]
                for sample in heap_samples
            )
            // 1024
        )
        * 1024,
        "idf_internal_minimum_free_min_bytes": (
            min(
                sample["idf_internal_minimum_free_bytes"]
                for sample in heap_samples
            )
            // 1024
        )
        * 1024,
        "reset_to_service_advertisement_max_ms": reset_threshold,
        "put_committed_goodput_min_bytes_per_second": (
            put_min // 100
        )
        * 100,
        "get_verified_goodput_min_bytes_per_second": (
            get_min // 100
        )
        * 100,
    }


def install_fixture_qualification_policy(
    repo: Path,
    build_root: Path | None = None,
) -> Path:
    builds = build_root if build_root is not None else repo.parent / "build"
    versions = tomllib.loads(
        (repo / "firmware" / "versions.lock").read_text(encoding="utf-8")
    )
    fixture_firmware_version = versions["pyble"]["agent_version"]
    source_core = RELEASE._firmware_release_core(
        fixture_firmware_version,
        "fixture firmware version",
    )
    profile_order = (
        HISTORICAL_V042_PROFILE_ORDER
        if source_core == (0, 4, 2)
        else RELEASE_PROFILE_ORDER
    )
    # Qualification evidence is a public, source-commit-scoped validation
    # input in every retained source era.  Keep these synthetic measurements
    # inside the temporary repository instead of modeling the old private
    # development-notes location that production rejects fail closed.
    baseline_relative = "docs/validation/firmware/oi1/%s.json" % ("1" * 40)
    baseline_profiles = []
    policy_profiles = []
    for profile_id in profile_order:
        spec = PROFILE_SPECS[profile_id]
        build = fixture_oi1_build(builds, profile_id)
        observation = fixture_oi1_observation()
        if RELEASE._firmware_release_core(
            fixture_firmware_version,
            "fixture firmware version",
        ) >= (0, 5, 0):
            observation["transfer_link_facts"] = (
                fixture_transfer_link_facts(profile_id)
            )
        manifest_bytes = (
            json.dumps(
                exact_manifest(fixture_firmware_version, profile_id),
                indent=2,
                sort_keys=False,
            )
            + "\n"
        ).encode("utf-8")
        baseline_profiles.append(
            {
                "profile_id": profile_id,
                "target": spec["target"],
                "board_manufacturer": "Fixture Boards",
                "board_model": "Fixture %s" % profile_id,
                "module_marking": profile_id,
                "device_flash_capacity_bytes": spec["flash_size_bytes"],
                "device_psram_capacity_bytes": spec["psram"]["size_bytes"],
                "firmware_sha256": sha256_path(
                    builds / spec["target"] / "firmware.bin"
                ),
                "manifest_sha256": hashlib.sha256(
                    manifest_bytes
                ).hexdigest(),
                "environment": {
                    "desktop_os": "FixtureOS 1",
                    "ble_backend": "Fixture BLE 1",
                    "ble_adapter": "Fixture Adapter 1",
                    "python_version": "3.13.5",
                },
                "oi1_build": build,
                "oi1_observation": observation,
            }
        )
        policy_profiles.append(
            {
                "profile_id": profile_id,
                "target": spec["target"],
                "thresholds": fixture_oi1_thresholds(
                    build,
                    observation,
                    fixture_firmware_version,
                ),
            }
        )
    baseline = {
        "schema_version": 1,
        "measurement_contract": "oi1-pre-v1-v1",
        "source_commit": "1" * 40,
        "firmware_version": fixture_firmware_version,
        "created_at": "2026-07-30T11:00:00Z",
        "profile_order": list(profile_order),
        "profiles": baseline_profiles,
    }
    baseline_path = repo / baseline_relative
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_bytes(canonical_json_bytes(baseline))
    policy = {
        "schema_version": 1 if source_core == (0, 4, 2) else 2,
        "qualification_scope": "pre-v1",
        "profile_order": list(profile_order),
        "deferred_profiles": ["esp32-c3-4mb"],
        "workload": copy.deepcopy(QUALIFICATION_WORKLOAD),
        "derivation": copy.deepcopy(
            QUALIFICATION_DERIVATION
            if RELEASE._firmware_release_core(
                fixture_firmware_version,
                "fixture firmware version",
            )
            >= (0, 5, 0)
            else QUALIFICATION_DERIVATION_V1
        ),
        "baseline_evidence": {
            "path": baseline_relative,
            "sha256": sha256_path(baseline_path),
        },
        "profiles": policy_profiles,
    }
    policy_path = repo / QUALIFICATION_POLICY_RELATIVE
    write_json(policy_path, policy)
    return policy_path


def fixture_oi1_observation() -> dict:
    heap = {
        "gc_free_bytes": 8192,
        "gc_allocated_bytes": 4096,
        "idf_internal_free_bytes": 8192,
        "idf_internal_largest_block_bytes": 8192,
        "idf_internal_minimum_free_bytes": 8192,
    }
    put_durations = [1_000_000_000] * 5
    get_durations = [1_000_000_000] * 5
    put_goodput = [65_536] * 5
    get_goodput = [65_536] * 5
    return {
        "observed_att_mtu": 247,
        "observed_window": 8,
        "observed_chunk_bytes": 229,
        "reset_to_service_advertisement_ms": [100] * 10,
        "heap_default_free_post_hello_bytes": [16_384] * 10,
        "heap_post_hello": [copy.deepcopy(heap) for _ in range(10)],
        "put_unique_committed_bytes": [65_536] * 5,
        "put_duration_ns": put_durations,
        "put_committed_goodput_bytes_per_second": put_goodput,
        "get_unique_verified_bytes": [65_536] * 5,
        "get_duration_ns": get_durations,
        "get_verified_goodput_bytes_per_second": get_goodput,
        "put_retransmitted_chunks": [0] * 5,
        "put_retransmitted_bytes": [0] * 5,
        "get_retransmitted_chunks": [0] * 5,
        "get_retransmitted_bytes": [0] * 5,
        "roundtrip_integrity_verified": 5,
        "get_offset_sequences_validated": 5,
        "roundtrip_unexpected_disconnects": 0,
        "roundtrip_integrity_failures": 0,
        "heap_post_roundtrip": [copy.deepcopy(heap) for _ in range(5)],
        "reliability": {
            "attempted_files": 20,
            "completed_files": 20,
            "verified_files": 20,
            "bytes_per_file": 16_384,
            "total_payload_bytes": 327_680,
            "unexpected_disconnects": 0,
            "integrity_failures": 0,
            "failed_statuses": 0,
            "retransmitted_chunks": 0,
            "retransmitted_bytes": 0,
            "rewinds": 0,
        },
        "heap_post_reliability": copy.deepcopy(heap),
        "physical_power_cycle_advertising": "passed",
        "raw_log_sha256": "4" * 64,
    }


def fixture_transfer_link_facts(profile_id: str) -> dict:
    if profile_id == "esp32-4mb":
        phy = {
            "required_2m": False,
            "request_attempts": 0,
            "updates": [],
            "settled_tx": 0,
            "settled_rx": 0,
        }
    elif profile_id in (
        "esp32-s3-n16r8",
        "waveshare-esp32-s3-lcd-147b",
        "esp32-c3-4mb",
    ):
        phy = {
            "required_2m": True,
            "request_attempts": 2,
            "updates": [
                {"status": 26, "tx": 1, "rx": 1},
                {"status": 0, "tx": 2, "rx": 2},
            ],
            "settled_tx": 2,
            "settled_rx": 2,
        }
    else:
        raise AssertionError("unsupported transfer-link fixture profile")
    return {
        "dle": {
            "request_attempts": 2,
            "max_tx_octets": 251,
            "max_tx_time_us": 2120,
        },
        "phy": phy,
        "connection_parameters": {
            "request_return_codes": [530, 0],
            "updates": [
                {"status": 554, "interval_units": 40},
                {"status": 0, "interval_units": 12},
            ],
            "settled_interval_units": 12,
        },
        "tx_mbuf_starve_count": 3,
    }


def complete_hil_payload(
    payload: dict,
    candidate_release_sha256: str,
    *,
    bundle: Path | None = None,
) -> dict:
    completed = copy.deepcopy(payload)
    completed["candidate_release_json_sha256"] = candidate_release_sha256
    for record in completed["records"]:
        profile_id = record["profile_id"]
        spec = PROFILE_SPECS[profile_id]
        observation = fixture_oi1_observation()
        if RELEASE._firmware_release_core(
            record["firmware_version"],
            "fixture HIL firmware version",
        ) >= (0, 5, 0):
            observation["transfer_link_facts"] = (
                fixture_transfer_link_facts(profile_id)
            )
        record.update(
            {
                "status": "passed",
                "board_manufacturer": "Fixture Boards",
                "board_model": "Fixture %s" % profile_id,
                "module_marking": profile_id,
                "device_flash_capacity_bytes": spec["flash_size_bytes"],
                "device_psram_capacity_bytes": spec["psram"]["size_bytes"],
                "tested_at": "2026-07-30T14:00:00Z",
                "operator": "Fixture Operator",
                "maintainer_signoff": "Fixture Maintainer",
                "desktop_os": "FixtureOS 1",
                "chromium_version": "Chrome 140.0.0.0",
                "ble_backend": "Fixture BLE 1",
                "ble_adapter": "Fixture Adapter 1",
                "python_version": "3.13.5",
                "checks": {
                    "browser_erase_install": "passed",
                    "family_offsets_reset": "passed",
                    "advertising_info_hello": "passed",
                    "app_workflow": "passed",
                    "neopixel_reboot": "passed",
                    "footprint_reliability": "passed",
                    "interrupted_flash_recovery": "passed",
                },
                "oi1_observation": observation,
                "redacted_console_log": (
                    "fixture: secrets and device labels removed"
                ),
            }
        )
    if completed["schema_version"] == 4 and bundle is not None:
        firmware = (
            Path(bundle)
            / "waveshare-esp32-s3-lcd-147b"
            / "firmware.bin"
        ).read_bytes()
        immutable = firmware[:0x9000] + firmware[0x10000:]
        completed["waveshare_lcd147b_qualification"] = {
            "schema_version": 1,
            "status": "passed",
            "profile_id": "waveshare-esp32-s3-lcd-147b",
            "board_model": "ESP32-S3-LCD-1.47B",
            "firmware_version": completed["records"][0]["firmware_version"],
            "candidate_release_json_sha256": candidate_release_sha256,
            "candidate_firmware_sha256": hashlib.sha256(firmware).hexdigest(),
            "candidate_firmware_size_bytes": len(firmware),
            "candidate_attestation_sha256": hashlib.sha256(immutable).hexdigest(),
            "candidate_attestation_size_bytes": len(immutable),
            "production_app_evidence_sha256": "5" * 64,
            "production_app_active_release_path": "/firmware/v%s/release.json"
            % completed["records"][0]["firmware_version"],
            "terminal_record_sha256": "6" * 64,
            "qualification_result_sha256": "7" * 64,
        }
    return completed


def read_hil_payload(path: Path) -> dict:
    match = HIL_MARKER.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise AssertionError("fixture HIL report lacks its embedded records")
    payload = json.loads(match.group(2))
    if payload.get("schema_version") != int(match.group(1)):
        raise AssertionError("fixture HIL marker/schema version disagrees")
    return payload


def write_hil_payload(path: Path, payload: dict) -> None:
    schema_version = payload["schema_version"]
    path.write_text(
        RELEASE.HIL_REPORT_SHELL_PREFIX
        + "<!-- PYBLE_HIL_RECORDS_V%d\n" % schema_version
        + json.dumps(payload, indent=2, sort_keys=False)
        + "\n-->"
        + RELEASE.HIL_REPORT_SHELL_SUFFIX,
        encoding="utf-8",
    )


def make_esp_image(
    chip_id: int,
    size_freq: int,
    application: bool,
    silicon_revision: dict[str, int],
    app_elf_sha256: bytes | None = None,
) -> bytes:
    """Return a small structurally valid ESP-IDF image.

    The first segment starts at byte 32. Application fixtures place the
    ESP_APP_DESC magic there; bootloader fixtures deliberately do not.
    """

    header = bytearray(24)
    header[0] = 0xE9
    header[1] = 1
    header[2] = 2  # DIO
    header[3] = size_freq
    header[4:8] = struct.pack("<I", 0x40080000)
    header[12:14] = struct.pack("<H", chip_id)
    header[14] = min(silicon_revision["minimum_full"], 0xFF)
    header[15:17] = struct.pack("<H", silicon_revision["minimum_full"])
    header[17:19] = struct.pack("<H", silicon_revision["maximum_full"])
    header[23] = 0  # no appended SHA in the synthetic fixture

    data = bytearray(512 if application else 256)
    if application:
        if app_elf_sha256 is None:
            raise ValueError("application fixture requires an ELF SHA-256")
        data[:4] = struct.pack("<I", 0xABCD5432)  # ESP_APP_DESC_MAGIC_WORD
        data[16:27] = b"micropython"
        if len(app_elf_sha256) != 32:
            raise ValueError("application ELF SHA-256 must contain 32 bytes")
        data[144:176] = app_elf_sha256
    elif app_elf_sha256 is not None:
        raise ValueError("bootloader fixture cannot contain an application ELF hash")
    else:
        data[:12] = b"bootloader\0"

    image = bytearray(header)
    image.extend(struct.pack("<II", 0x3F400020, len(data)))
    image.extend(data)
    checksum = 0xEF
    for octet in data:
        checksum ^= octet
    image.extend(b"\0" * ((15 - (len(image) % 16)) % 16))
    image.append(checksum)
    return bytes(image)


def make_partition_table(
    flash_size: int,
    *,
    application_size: int = 0x1F0000,
    overlap: bool = False,
    corrupt_md5: bool = False,
) -> bytes:
    def entry(part_type, subtype, offset, size, label):
        return struct.pack(
            "<HBBII16sI",
            0x50AA,
            part_type,
            subtype,
            offset,
            size,
            label.encode("ascii").ljust(16, b"\0"),
            0,
        )

    factory_offset = 0x10000
    vfs_offset = (
        0x18000
        if overlap
        else (0x210000 if flash_size == 16 * 1024 * 1024 else 0x200000)
    )
    vfs_size = flash_size - vfs_offset
    raw = b"".join(
        (
            entry(1, 2, 0x9000, 0x6000, "nvs"),
            entry(1, 1, 0xF000, 0x1000, "phy_init"),
            entry(0, 0, factory_offset, application_size, "factory"),
            entry(1, 0x81, vfs_offset, vfs_size, "vfs"),
        )
    )
    digest = bytearray(hashlib.md5(raw).digest())  # nosec - ESP table format.
    if corrupt_md5:
        digest[0] ^= 0xFF
    raw += b"\xeb\xeb" + b"\xff" * 14 + bytes(digest)
    return raw.ljust(0xC00, b"\xff")


def make_merged_image(base_offset: int, parts: list[tuple[int, bytes]]) -> bytes:
    end = max(offset + len(data) for offset, data in parts)
    merged = bytearray(b"\xff" * (end - base_offset))
    for offset, data in parts:
        start = offset - base_offset
        merged[start : start + len(data)] = data
    return bytes(merged)


def rebind_fixture_application_to_elf(build: Path, spec: dict) -> None:
    """Update a synthetic app and merged image after an intentional ELF edit."""

    elf = (build / "micropython.elf").read_bytes()
    application_path = build / "micropython.bin"
    application = bytearray(application_path.read_bytes())
    application[0xB0:0xD0] = hashlib.sha256(elf).digest()
    segment_length = struct.unpack_from("<I", application, 28)[0]
    segment_end = 32 + segment_length
    checksum_position = segment_end + ((15 - (segment_end % 16)) % 16)
    checksum = 0xEF
    for octet in application[32:segment_end]:
        checksum ^= octet
    application[checksum_position] = checksum
    application_path.write_bytes(application)
    bootloader = (build / "bootloader" / "bootloader.bin").read_bytes()
    partition_table = (
        build / "partition_table" / "partition-table.bin"
    ).read_bytes()
    (build / "firmware.bin").write_bytes(
        make_merged_image(
            spec["base_offset"],
            list(
                zip(
                    spec["component_offsets"],
                    (bootloader, partition_table, bytes(application)),
                )
            ),
        )
    )


def flasher_args_for(spec: dict) -> dict:
    boot_offset, partition_offset, application_offset = spec["component_offsets"]
    return {
        "write_flash_args": [
            "--flash_mode",
            "dio",
            "--flash_size",
            spec["flash_size"],
            "--flash_freq",
            spec["flash_freq"],
        ],
        "flash_settings": {
            "flash_mode": "dio",
            "flash_size": spec["flash_size"],
            "flash_freq": spec["flash_freq"],
        },
        "flash_files": {
            hex(boot_offset): "bootloader/bootloader.bin",
            hex(application_offset): "micropython.bin",
            hex(partition_offset): "partition_table/partition-table.bin",
        },
        "bootloader": {
            "offset": hex(boot_offset),
            "file": "bootloader/bootloader.bin",
            "encrypted": "false",
        },
        "app": {
            "offset": hex(application_offset),
            "file": "micropython.bin",
            "encrypted": "false",
        },
        "partition-table": {
            "offset": hex(partition_offset),
            "file": "partition_table/partition-table.bin",
            "encrypted": "false",
        },
        "extra_esptool_args": {
            "after": "hard_reset",
            "before": "default_reset",
            "stub": True,
            "chip": spec["idf_target"],
        },
    }


def exact_manifest(version: str, profile_id: str) -> dict:
    spec = PROFILE_SPECS[profile_id]
    return {
        "name": "PyBLE",
        "version": version,
        "new_install_prompt_erase": False,
        "new_install_improv_wait_time": 0,
        "builds": [
            {
                "chipFamily": spec["chip_family"],
                "parts": [
                    {
                        "path": "firmware.bin",
                        "offset": spec["base_offset"],
                    }
                ],
            },
        ],
    }


def exact_release_schema(version: str = PROSPECTIVE_FIRMWARE_VERSION) -> dict:
    profile_order = (
        HISTORICAL_V042_PROFILE_ORDER
        if version == "0.4.2"
        else RELEASE_PROFILE_ORDER
    )
    schema_version = 2 if version == "0.4.2" else 3
    sha = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    commit = {"type": "string", "pattern": "^[0-9a-f]{40}$"}
    relative_path = {
        "type": "string",
        "minLength": 1,
        "pattern": r"^(?!/)(?!.*(?:^|/)\.\.?(?:/|$))(?!.*[\\?#])(?!.*://).+$",
    }
    artifact_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["path", "size", "sha256"],
        "properties": {
            "path": relative_path,
            "size": {"type": "integer", "minimum": 1},
            "sha256": sha,
        },
    }
    offset_artifact = copy.deepcopy(artifact_schema)
    offset_artifact["required"].append("offset")
    offset_artifact["properties"]["offset"] = {"type": "integer", "minimum": 0}
    component = copy.deepcopy(offset_artifact)
    component["required"].insert(0, "role")
    component["properties"]["role"] = {
        "enum": ["bootloader", "partition-table", "application"]
    }

    profile = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "chip_family",
            "requirements",
            "flash",
            "silicon_revision",
            "hil_status",
            "manifest",
            "install",
            "components",
        ],
        "properties": {
            "id": {"enum": list(profile_order)},
            "chip_family": {"enum": ["ESP32", "ESP32-S3"]},
            "requirements": {
                "type": "object",
                "additionalProperties": False,
                "required": ["flash_size_bytes", "psram"],
                "properties": {
                    "flash_size_bytes": {"type": "integer", "minimum": 1},
                    "psram": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["required", "size_bytes", "type"],
                        "properties": {
                            "required": {"type": "boolean"},
                            "size_bytes": {"type": "integer", "minimum": 0},
                            "type": {"enum": ["not-required", "octal"]},
                        },
                    },
                },
            },
            "flash": {
                "type": "object",
                "additionalProperties": False,
                "required": ["mode", "frequency_hz"],
                "properties": {
                    "mode": {"const": "dio"},
                    "frequency_hz": {"type": "integer", "minimum": 1},
                },
            },
            "silicon_revision": {
                "type": "object",
                "additionalProperties": False,
                "required": ["minimum_full", "maximum_full"],
                "properties": {
                    "minimum_full": {
                        "type": "integer",
                        "minimum": 0,
                    },
                    "maximum_full": {
                        "type": "integer",
                        "minimum": 0,
                    },
                },
            },
            "hil_status": {"enum": ["pending", "passed"]},
            "manifest": artifact_schema,
            "install": offset_artifact,
            "components": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": component,
            },
        },
    }
    tool = {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "version"],
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "version": {"type": "string", "minLength": 1},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://pyble.dev/firmware/release.schema.json",
        "title": "PyBLE firmware release metadata v%d" % schema_version,
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "identity",
            "provenance",
            "installer",
            "profiles",
            "documents",
        ],
        "properties": {
            "schema_version": {"const": schema_version},
            "identity": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "version",
                    "tag",
                    "agent_version",
                    "protocol_version",
                    "built_at",
                ],
                "properties": {
                    "version": {
                        "type": "string",
                        "pattern": r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$",
                    },
                    "tag": {"type": "string", "pattern": r"^firmware-v.+$"},
                    "agent_version": {"type": "string", "minLength": 1},
                    "protocol_version": {"const": "PBLE/1"},
                    "built_at": {
                        "type": "string",
                        "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
                    },
                },
            },
            "provenance": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "pyble",
                    "micropython",
                    "esp_idf",
                    "patch_count",
                    "runner",
                    "tools",
                ],
                "properties": {
                    "pyble": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["commit", "clean"],
                        "properties": {
                            "commit": commit,
                            "clean": {"const": True},
                        },
                    },
                    "micropython": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["ref", "commit"],
                        "properties": {
                            "ref": {"type": "string", "minLength": 1},
                            "commit": commit,
                        },
                    },
                    "esp_idf": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["ref", "commit"],
                        "properties": {
                            "ref": {"type": "string", "minLength": 1},
                            "commit": commit,
                        },
                    },
                    "patch_count": {"type": "integer", "minimum": 0},
                    "runner": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["os", "architecture"],
                        "properties": {
                            "os": {"type": "string", "minLength": 1},
                            "architecture": {"type": "string", "minLength": 1},
                        },
                    },
                    "tools": {
                        "type": "array",
                        "minItems": 1,
                        "items": tool,
                    },
                },
            },
            "installer": {
                "type": "object",
                "additionalProperties": False,
                "required": ["package", "version"],
                "properties": {
                    "package": {"const": "esp-web-tools"},
                    "version": {"const": "10.4.0"},
                },
            },
            "profiles": {
                "type": "array",
                "minItems": len(profile_order),
                "maxItems": len(profile_order),
                "items": profile,
            },
            "documents": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "third_party_licenses",
                    "release_notes",
                    "recovery",
                    "hil_report",
                ],
                "properties": {
                    "third_party_licenses": artifact_schema,
                    "release_notes": artifact_schema,
                    "recovery": artifact_schema,
                    "hil_report": artifact_schema,
                },
            },
        },
    }


def hil_report_text(
    status: str,
    manifest_hashes: dict[str, str],
    install_hashes: dict[str, str],
    *,
    bundle: Path,
    policy_path: Path,
    version: str = PROSPECTIVE_FIRMWARE_VERSION,
) -> str:
    profile_order = (
        HISTORICAL_V042_PROFILE_ORDER
        if version == "0.4.2"
        else RELEASE_PROFILE_ORDER
    )
    schema_version = 2 if version == "0.4.2" else 4
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy_by_profile = {
        item["profile_id"]: item for item in policy["profiles"]
    }
    records = []
    for profile_id in profile_order:
        spec = PROFILE_SPECS[profile_id]
        application_bytes = (bundle / profile_id / "application.bin").stat().st_size
        factory_bytes = (
            0x200000 if spec["chip_family"] == "ESP32-S3" else 0x1F0000
        )
        records.append(
            {
                "profile_id": profile_id,
                "status": status,
                "board_manufacturer": "",
                "board_model": "",
                "module_marking": "",
                "device_flash_capacity_bytes": 0,
                "device_psram_capacity_bytes": 0,
                "firmware_version": version,
                "tag": "firmware-v%s" % version,
                "source_commit": "1" * 40,
                "manifest_sha256": manifest_hashes[profile_id],
                "firmware_sha256": install_hashes[profile_id],
                "tested_at": "",
                "operator": "",
                "maintainer_signoff": "",
                "desktop_os": "",
                "chromium_version": "",
                "ble_backend": "",
                "ble_adapter": "",
                "python_version": "",
                "checks": {
                    "browser_erase_install": "pending",
                    "family_offsets_reset": "pending",
                    "advertising_info_hello": "pending",
                    "app_workflow": "pending",
                    "neopixel_reboot": "pending",
                    "footprint_reliability": "pending",
                    "interrupted_flash_recovery": "pending",
                },
                "oi1_policy": copy.deepcopy(policy_by_profile[profile_id]),
                "oi1_build": {
                    "application_image_bytes": application_bytes,
                    "factory_partition_bytes": factory_bytes,
                    "application_headroom_bytes": (
                        factory_bytes - application_bytes
                    ),
                },
                "oi1_observation": None,
                "redacted_console_log": "",
            }
        )
    payload = {
        "schema_version": schema_version,
        "candidate_release_json_sha256": "",
        "qualification_policy_sha256": sha256_path(policy_path),
        "qualification_policy": policy,
        "records": records,
    }
    if schema_version == 4:
        payload["waveshare_lcd147b_qualification"] = None
    if status == "passed":
        payload = complete_hil_payload(payload, "0" * 64, bundle=bundle)
    return (
        RELEASE.HIL_REPORT_SHELL_PREFIX
        + "<!-- PYBLE_HIL_RECORDS_V%d\n" % schema_version
        + json.dumps(payload, indent=2)
        + "\n-->"
        + RELEASE.HIL_REPORT_SHELL_SUFFIX
    )


class ReleaseFixture:
    def __init__(self, firmware_version: str = PROSPECTIVE_FIRMWARE_VERSION):
        self.firmware_version = firmware_version
        self.profile_order = (
            HISTORICAL_V042_PROFILE_ORDER
            if firmware_version == "0.4.2"
            else RELEASE_PROFILE_ORDER
        )
        self._temporary = tempfile.TemporaryDirectory(prefix="pyble-release-tests-")
        self.root = Path(self._temporary.name)
        self.repo = self.root / "repo"
        self.build_root = self.root / "build"
        self.bundle = self.root / "bundle"
        self.repo.mkdir()
        self.build_root.mkdir()
        self._make_repo_inputs()
        self._make_builds()
        self.qualification_policy_path = install_fixture_qualification_policy(
            self.repo,
            self.build_root,
        )
        self.reproducibility_build_root = self.root / "build-reproducibility"
        shutil.copytree(
            self.build_root,
            self.reproducibility_build_root,
        )

    def cleanup(self):
        self._temporary.cleanup()

    def _make_repo_inputs(self):
        firmware = self.repo / "firmware"
        (firmware / ".esp-idf" / "components" / "esp_system").mkdir(parents=True)
        (
            firmware
            / "upstream"
            / "micropython"
            / "lib"
            / "micropython-lib"
            / "micropython"
            / "drivers"
            / "led"
            / "neopixel"
        ).mkdir(parents=True)
        (firmware / "patches").mkdir()
        (firmware / "versions.lock").write_text(
            """# SPDX-License-Identifier: MIT
[micropython]
repo = "https://github.com/micropython/micropython"
ref = "v1.28.0"
commit = "2222222222222222222222222222222222222222"
[esp_idf]
repo = "https://github.com/espressif/esp-idf"
ref = "v5.5.1"
commit = "3333333333333333333333333333333333333333"
[pyble]
agent_version = "%s"
protocol_version = "PBLE/1"
""" % self.firmware_version,
            encoding="utf-8",
        )
        mit = (
            "MIT License\n\nCopyright (c) Fixture MicroPython Authors\n\n"
            "Permission is hereby granted, free of charge, to any person "
            "obtaining a copy to use, copy, modify, merge, publish, "
            "distribute, sublicense, and/or sell copies.\n"
        )
        apache = (
            "Apache License\nVersion 2.0, January 2004\n\n"
            "Copyright 2015-2026 Fixture Espressif Authors\n\n"
            "Licensed under the Apache License, Version 2.0.\n"
        )
        mpy = firmware / "upstream" / "micropython"
        (mpy / "LICENSE").write_text(mit, encoding="utf-8")
        (mpy / "lib" / "micropython-lib" / "LICENSE").write_text(mit, encoding="utf-8")
        neopixel = (
            mpy
            / "lib"
            / "micropython-lib"
            / "micropython"
            / "drivers"
            / "led"
            / "neopixel"
            / "neopixel.py"
        )
        neopixel.write_text(
            "# SPDX-License-Identifier: MIT\n"
            "# Copyright (c) Fixture NeoPixel Authors\n",
            encoding="utf-8",
        )
        idf = firmware / ".esp-idf"
        (idf / "LICENSE").write_text(apache, encoding="utf-8")
        component = idf / "components" / "esp_system"
        (component / "LICENSE").write_text(apache, encoding="utf-8")
        (component / "fixture.c").write_text(
            "// SPDX-License-Identifier: Apache-2.0\n"
            "// Copyright 2015-2026 Fixture Espressif Authors\n",
            encoding="utf-8",
        )

    def _make_builds(self):
        component = self.repo / "firmware" / ".esp-idf" / "components" / "esp_system"
        for profile_id in BUILD_PROFILE_ORDER:
            spec = PROFILE_SPECS[profile_id]
            build = self.build_root / spec["target"]
            (build / "bootloader").mkdir(parents=True)
            (build / "partition_table").mkdir()
            boot = make_esp_image(
                spec["chip_id"],
                spec["header_size_freq"],
                application=False,
                silicon_revision=spec["silicon_revision"],
            )
            elf = b"\x7fELF\0PyBLE fixture " + spec["target"].encode("ascii")
            app = make_esp_image(
                spec["chip_id"],
                spec["header_size_freq"],
                application=True,
                silicon_revision=spec["silicon_revision"],
                app_elf_sha256=hashlib.sha256(elf).digest(),
            )
            table = make_partition_table(
                spec["flash_size_bytes"],
                application_size=(
                    0x200000
                    if spec["chip_family"] == "ESP32-S3"
                    else 0x1F0000
                ),
            )
            offsets = spec["component_offsets"]
            merged = make_merged_image(
                spec["base_offset"],
                list(zip(offsets, (boot, table, app))),
            )
            (build / "bootloader" / "bootloader.bin").write_bytes(boot)
            (build / "partition_table" / "partition-table.bin").write_bytes(table)
            (build / "micropython.elf").write_bytes(elf)
            (build / "micropython.bin").write_bytes(app)
            (build / "firmware.bin").write_bytes(merged)
            write_json(build / "flasher_args.json", flasher_args_for(spec))
            sdkconfig = "CONFIG_APP_REPRODUCIBLE_BUILD=y\n"
            if spec["idf_target"] in ("esp32s3", "esp32c3"):
                sdkconfig += "CONFIG_XTAL_FREQ_40=y\n" "CONFIG_XTAL_FREQ=40\n"
            (build / "sdkconfig").write_text(sdkconfig, encoding="utf-8")
            write_json(
                build / "pyble-build-provenance.json",
                {
                    "schema_version": 1,
                    "target": spec["target"],
                    "source_date_epoch": 1785326400,
                    "pyble": {"commit": "1" * 40, "clean": True},
                    "micropython": {"commit": "2" * 40},
                    "esp_idf": {"commit": "3" * 40},
                },
            )
            write_json(
                build / "project_description.json",
                {
                    "project_name": "micropython",
                    "project_version": "v1.28.0",
                    "build_dir": str(build),
                    "idf_path": str(self.repo / "firmware" / ".esp-idf"),
                    "target": spec["idf_target"],
                    "c_compiler": "/fixture/bin/%s-gcc" % spec["target"],
                    "build_components": ["esp_system"],
                    "build_component_info": {
                        "esp_system": {
                            "dir": str(component),
                            "type": "LIBRARY",
                            "file": str(build / "libesp_system.a"),
                            "sources": [str(component / "fixture.c")],
                        }
                    },
                },
            )
            (build / "libesp_system.a").write_bytes(b"fixture archive")

    def make_bundle(self, *, public: bool = False) -> Path:
        if self.bundle.exists():
            shutil.rmtree(self.bundle)
        self.bundle.mkdir()
        version = self.firmware_version
        for profile_id in self.profile_order:
            spec = PROFILE_SPECS[profile_id]
            src = self.build_root / spec["target"]
            dst = self.bundle / profile_id
            dst.mkdir()
            write_json(dst / "manifest.json", exact_manifest(version, profile_id))
            shutil.copyfile(src / "firmware.bin", dst / "firmware.bin")
            shutil.copyfile(
                src / "bootloader" / "bootloader.bin",
                dst / "bootloader.bin",
            )
            shutil.copyfile(
                src / "partition_table" / "partition-table.bin",
                dst / "partition-table.bin",
            )
            shutil.copyfile(src / "micropython.bin", dst / "application.bin")

        write_json(
            self.bundle / "release.schema.json",
            exact_release_schema(version),
        )
        (self.bundle / "THIRD_PARTY_LICENSES.txt").write_text(
            "PyBLE mechanically generated notices\n\n"
            "Name: MicroPython\nVersion/ref: v1.28.0\n"
            "Source URL: https://github.com/micropython/micropython\n"
            "SPDX identifier: MIT\n"
            "Copyright: Fixture MicroPython Authors\n"
            "Required notice: retain this notice\n"
            "Complete license text:\nMIT License fixture text\n\n"
            "Name: ESP-IDF component esp_system\nVersion/ref: v5.5.1\n"
            "Source URL: https://github.com/espressif/esp-idf\n"
            "SPDX identifier: Apache-2.0\n"
            "Copyright: Fixture Espressif Authors\n"
            "Required notice: retain this notice\n"
            "Complete license text:\nApache License Version 2.0 fixture text\n\n"
            "Name: micropython-lib NeoPixel\nVersion/ref: pinned by MicroPython\n"
            "Source URL: https://github.com/micropython/micropython-lib\n"
            "SPDX identifier: MIT\n"
            "Copyright: Fixture NeoPixel Authors\n"
            "Required notice: retain this notice\n"
            "Complete license text:\nMIT License fixture text\n",
            encoding="utf-8",
        )
        (self.bundle / "RELEASE_NOTES.md").write_text(
            "# PyBLE firmware %s — 2026-07-30\n\n"
            "Profiles: esp32-4mb (4 MiB), esp32-s3-n16r8 "
            "(16 MiB flash, 8 MiB Octal PSRAM; lean N16R8-class only)%s.\n\n"
            "Agent %s; PBLE/1; MicroPython v1.28.0 @ %s; "
            "ESP-IDF v5.5.1 @ %s; source %s; tag firmware-v%s.\n\n"
            "Installation erases the board. Back up files. Known limitation: "
            "wired provisioning needs desktop Chromium; iPadOS cannot flash. "
            "See RECOVERY.md. Upgrade uses the same exact profile. "
            "Support: https://pyble.dev/support/.\n"
            % (
                version,
                (
                    ", waveshare-esp32-s3-lcd-147b "
                    "(exact B-version board with bundled display stack)"
                    if "waveshare-esp32-s3-lcd-147b" in self.profile_order
                    else ""
                ),
                version,
                "2" * 40,
                "3" * 40,
                "1" * 40,
                version,
            ),
            encoding="utf-8",
        )
        waveshare_recovery = (
            "`python -m esptool --chip esp32s3 write_flash 0x0 "
            "waveshare-esp32-s3-lcd-147b/firmware.bin`\n"
            if "waveshare-esp32-s3-lcd-147b" in self.profile_order
            else ""
        )
        (self.bundle / "RECOVERY.md").write_text(
            "# Recovery\n\nBack up user files; install erases the board. Use a "
            "data-capable cable and stable power, close serial monitors, select "
            "the correct port, and retry the same verified profile. If automatic "
            "reset fails, hold BOOT, tap RESET, then release BOOT; labels vary. "
            "Permission denial, disconnect, timeout, interrupted erase/write, "
            "verification failure, and no-boot cases are safe to retry after "
            "reconnecting and entering the ROM bootloader.\n\n"
            "Merged recovery commands:\n"
            "`python -m esptool --chip esp32 write_flash 0x1000 "
            "esp32-4mb/firmware.bin`\n"
            "`python -m esptool --chip esp32s3 write_flash 0x0 "
            "esp32-s3-n16r8/firmware.bin`\n"
            + waveshare_recovery
            + "\n"
            "The component diagnostic bootloader offsets are 0x1000/0, "
            "partition table 0x8000, and application 0x10000. Power cycle after "
            "flashing and expect `PyBLE-XXXX`, then connect from the app. Stop "
            "on wrong-memory symptoms; do not try random images. Share only "
            "version, profile, module marking, browser/OS, stage, and redacted "
            "error text with https://pyble.dev/support/.\n",
            encoding="utf-8",
        )

        manifest_hashes = {
            profile_id: sha256_path(self.bundle / profile_id / "manifest.json")
            for profile_id in self.profile_order
        }
        install_hashes = {
            profile_id: sha256_path(self.bundle / profile_id / "firmware.bin")
            for profile_id in self.profile_order
        }
        hil_status = "passed" if public else "pending"
        (self.bundle / "HIL_REPORT.md").write_text(
            hil_report_text(
                hil_status,
                manifest_hashes,
                install_hashes,
                bundle=self.bundle,
                policy_path=self.qualification_policy_path,
                version=version,
            ),
            encoding="utf-8",
        )

        profiles = []
        for profile_id in self.profile_order:
            spec = PROFILE_SPECS[profile_id]
            directory = self.bundle / profile_id
            profiles.append(
                {
                    "id": profile_id,
                    "chip_family": spec["chip_family"],
                    "requirements": {
                        "flash_size_bytes": spec["flash_size_bytes"],
                        "psram": spec["psram"],
                    },
                    "flash": {
                        "mode": "dio",
                        "frequency_hz": spec["frequency_hz"],
                    },
                    "silicon_revision": spec["silicon_revision"],
                    "hil_status": hil_status,
                    "manifest": artifact(
                        directory / "manifest.json",
                        "%s/manifest.json" % profile_id,
                    ),
                    "install": artifact(
                        directory / "firmware.bin",
                        "%s/firmware.bin" % profile_id,
                        offset=spec["base_offset"],
                    ),
                    "components": [
                        artifact(
                            directory / filename,
                            "%s/%s" % (profile_id, filename),
                            role=role,
                            offset=offset,
                        )
                        for role, filename, offset in zip(
                            ROLE_ORDER,
                            (
                                "bootloader.bin",
                                "partition-table.bin",
                                "application.bin",
                            ),
                            spec["component_offsets"],
                        )
                    ],
                }
            )

        metadata = {
            "schema_version": 2 if version == "0.4.2" else 3,
            "identity": {
                "version": version,
                "tag": "firmware-v%s" % version,
                "agent_version": version,
                "protocol_version": "PBLE/1",
                "built_at": "2026-07-30T12:00:00Z",
            },
            "provenance": {
                "pyble": {"commit": "1" * 40, "clean": True},
                "micropython": {"ref": "v1.28.0", "commit": "2" * 40},
                "esp_idf": {"ref": "v5.5.1", "commit": "3" * 40},
                "patch_count": 0,
                "runner": {"os": "FixtureOS 1", "architecture": "fixture64"},
                "tools": [
                    {"name": "cmake", "version": "4.0.1"},
                    {"name": "esp-idf", "version": "5.5.1"},
                    {"name": "python", "version": "3.13.5"},
                ],
            },
            "installer": {
                "package": "esp-web-tools",
                "version": "10.4.0",
            },
            "profiles": profiles,
            "documents": {
                "third_party_licenses": artifact(
                    self.bundle / "THIRD_PARTY_LICENSES.txt",
                    "THIRD_PARTY_LICENSES.txt",
                ),
                "release_notes": artifact(
                    self.bundle / "RELEASE_NOTES.md", "RELEASE_NOTES.md"
                ),
                "recovery": artifact(self.bundle / "RECOVERY.md", "RECOVERY.md"),
                "hil_report": artifact(self.bundle / "HIL_REPORT.md", "HIL_REPORT.md"),
            },
        }
        write_json(self.bundle / "release.json", metadata)
        self.refresh_sums()
        return self.bundle

    def refresh_declared_hashes(self):
        metadata_path = self.bundle / "release.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        def refresh(record):
            path = self.bundle / record["path"]
            record["size"] = path.stat().st_size
            record["sha256"] = sha256_path(path)

        for profile in metadata["profiles"]:
            refresh(profile["manifest"])
            refresh(profile["install"])
            for component in profile["components"]:
                refresh(component)
        for document in metadata["documents"].values():
            refresh(document)
        write_json(metadata_path, metadata)
        self.refresh_sums()

    def refresh_sums(self):
        sums = []
        for path in sorted(p for p in self.bundle.rglob("*") if p.is_file()):
            relative = path.relative_to(self.bundle).as_posix()
            if relative == "SHA256SUMS":
                continue
            sums.append("%s  %s" % (sha256_path(path), relative))
        (self.bundle / "SHA256SUMS").write_text(
            "\n".join(sums) + "\n", encoding="utf-8"
        )


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.fixture = ReleaseFixture()

    def tearDown(self):
        self.fixture.cleanup()


class ReleaseProductionGatePresenceTest(unittest.TestCase):
    def test_release_bundle_production_entrypoint_exists_and_imports(self):
        self.assertTrue(
            RELEASE_SCRIPT.is_file(),
            "HAND-OFF build-smith [green]: %s (%s)"
            % (RELEASE_SCRIPT, RELEASE_LOAD_ERROR),
        )
        self.assertIsNotNone(RELEASE, RELEASE_LOAD_ERROR)
        if RELEASE is not None:
            for name in (
                "ReleaseError",
                "validate_build",
                "create_bundle",
                "validate_bundle",
                "compare_build_roots",
                "generate_third_party_licenses",
            ):
                self.assertTrue(
                    hasattr(RELEASE, name),
                    "release_bundle.py must expose %s" % name,
                )

    def test_release_profiles_are_distinct_from_all_initial_build_targets(self):
        self.assertIsNotNone(RELEASE, RELEASE_LOAD_ERROR)
        if RELEASE is None:
            return
        self.assertEqual(
            getattr(RELEASE, "RELEASE_PROFILE_ORDER", None),
            V060_RELEASE_PROFILE_ORDER,
            "the current source-selected bundle must expose the frozen v0.6 order",
        )
        self.assertEqual(
            set(RELEASE.TARGET_TO_PROFILE),
            {
                "esp32",
                "esp32-s3",
                "waveshare-esp32-s3-lcd-147b",
                "esp32-c3",
            },
            "all four build variants remain mandatory build/audit inputs",
        )


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class QualificationDerivationContractTests(unittest.TestCase):
    def test_source_era_selects_exact_runtime_derivation(self):
        build = {
            "application_image_bytes": 4096,
            "factory_partition_bytes": 8192,
            "application_headroom_bytes": 4096,
        }
        observation = fixture_oi1_observation()
        expected_static_and_heap = {
            "application_image_max_bytes": 4096,
            "application_headroom_min_bytes": 4096,
            "gc_free_min_bytes": 8192,
            "idf_internal_free_min_bytes": 8192,
            "idf_internal_largest_block_min_bytes": 8192,
            "idf_internal_minimum_free_min_bytes": 8192,
        }

        historical = RELEASE._derived_qualification_thresholds(
            build,
            observation,
            firmware_version="0.4.2",
        )
        current = RELEASE._derived_qualification_thresholds(
            build,
            observation,
            firmware_version=PROSPECTIVE_FIRMWARE_VERSION,
        )

        self.assertEqual(
            historical,
            {
                **expected_static_and_heap,
                "reset_to_service_advertisement_max_ms": 100,
                "put_committed_goodput_min_bytes_per_second": 65500,
                "get_verified_goodput_min_bytes_per_second": 65500,
            },
        )
        self.assertEqual(
            current,
            {
                **expected_static_and_heap,
                "reset_to_service_advertisement_max_ms": 3000,
                "put_committed_goodput_min_bytes_per_second": 62200,
                "get_verified_goodput_min_bytes_per_second": 62200,
            },
        )


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class CrossComponentSchemaParityTests(unittest.TestCase):
    def test_web_frozen_schema_equals_release_generator_exactly(self):
        self.assertTrue(
            WEB_RELEASE_SCHEMA.is_file(),
            "web flasher canonical release schema is missing",
        )
        web_schema = json.loads(WEB_RELEASE_SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(
            web_schema,
            RELEASE._release_schema(),
            "web flasher schema must exactly equal the release-tool generator",
        )


class ReproducibleBuildRedTests(unittest.TestCase):
    def test_plan_lists_every_authoritative_release_input(self):
        completed = subprocess.run(
            [str(BUILD_SCRIPT), "--plan", "esp32"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        for name in (
            "firmware.bin",
            "micropython.bin",
            "micropython.elf",
            "bootloader.bin",
            "partition-table.bin",
            "flasher_args.json",
        ):
            self.assertIn(name, completed.stdout)

    def test_plan_exposes_caller_selected_output_root(self):
        with tempfile.TemporaryDirectory(prefix="pyble-output-root-") as tmp:
            completed = subprocess.run(
                [str(BUILD_SCRIPT), "--plan", "esp32"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env={**os.environ, "PYBLE_BUILD_ROOT": tmp},
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertRegex(
                completed.stdout,
                r"(?m)^output_root=%s$" % re.escape(tmp),
                "release double-builds need isolated caller-selected roots",
            )

    def test_build_uses_commit_time_as_source_date_epoch(self):
        source = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("SOURCE_DATE_EPOCH", source)
        self.assertRegex(
            source,
            r"git.+(?:show|log).+%ct",
            "SOURCE_DATE_EPOCH must derive from the exact source commit",
        )

    def test_all_profiles_enable_esp_idf_reproducible_build(self):
        for target in ("esp32", "esp32-s3", "esp32-c3"):
            with self.subTest(target=target):
                config = (OVERLAYS / target / "sdkconfig.board").read_text(
                    encoding="utf-8"
                )
                self.assertRegex(
                    config,
                    r"(?m)^CONFIG_APP_REPRODUCIBLE_BUILD=y$",
                    "ESP-IDF compile timestamps/paths must not enter release bytes",
                )


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class BuildArtifactValidationTests(FixtureCase):
    def validate(self, target):
        return RELEASE.validate_build(target, self.fixture.build_root / target)

    def test_all_exact_build_profiles_validate(self):
        for target in TARGET_TO_PROFILE:
            with self.subTest(target=target):
                self.assertIsNotNone(self.validate(target))

    def test_build_requires_elf_bound_to_application_descriptor(self):
        target = "esp32"
        elf = self.fixture.build_root / target / "micropython.elf"
        original = elf.read_bytes()
        elf.unlink()
        with self.assertRaisesRegex(RELEASE.ReleaseError, r"lacks.*elf"):
            self.validate(target)
        elf.write_bytes(b"NOPE" + original[4:])
        with self.assertRaisesRegex(RELEASE.ReleaseError, r"wrong ELF magic"):
            self.validate(target)
        elf.write_bytes(original + b"changed")
        with self.assertRaisesRegex(
            RELEASE.ReleaseError,
            r"(?:ELF|elf).*(?:SHA|hash)|(?:SHA|hash).*(?:ELF|elf)",
        ):
            self.validate(target)

    def test_build_rejects_selected_build_root_remaining_in_elf(self):
        target = "esp32-s3"
        spec = PROFILE_SPECS[TARGET_TO_PROFILE[target]]
        build = self.fixture.build_root / target
        elf = build / "micropython.elf"
        elf.write_bytes(
            elf.read_bytes()
            + b"\0"
            + str(self.fixture.build_root.resolve()).encode("utf-8")
        )
        rebind_fixture_application_to_elf(build, spec)
        with self.assertRaisesRegex(
            RELEASE.ReleaseError,
            r"ELF retains unmapped.*build root",
        ):
            self.validate(target)

    def test_rejects_truncated_application_descriptor(self):
        target = "esp32-c3"
        spec = PROFILE_SPECS[TARGET_TO_PROFILE[target]]
        build = self.fixture.build_root / target
        application_path = build / "micropython.bin"
        original = bytearray(application_path.read_bytes())
        descriptor_prefix_length = 128
        application = bytearray(original[: 32 + descriptor_prefix_length])
        struct.pack_into("<I", application, 28, descriptor_prefix_length)
        checksum_position = len(application) + (
            (15 - (len(application) % 16)) % 16
        )
        application.extend(b"\0" * (checksum_position - len(application)))
        checksum = 0xEF
        for octet in application[32 : 32 + descriptor_prefix_length]:
            checksum ^= octet
        application.append(checksum)
        application_path.write_bytes(application)
        bootloader = (build / "bootloader" / "bootloader.bin").read_bytes()
        partition_table = (
            build / "partition_table" / "partition-table.bin"
        ).read_bytes()
        (build / "firmware.bin").write_bytes(
            make_merged_image(
                spec["base_offset"],
                list(
                    zip(
                        spec["component_offsets"],
                        (bootloader, partition_table, bytes(application)),
                    )
                ),
            )
        )
        with self.assertRaisesRegex(
            RELEASE.ReleaseError,
            r"application descriptor is truncated",
        ):
            self.validate(target)

    def test_build_provenance_schema_version_requires_the_exact_integer_one(self):
        target = "esp32"
        path = (
            self.fixture.build_root
            / target
            / "pyble-build-provenance.json"
        )
        original = json.loads(path.read_text(encoding="utf-8"))
        for invalid in (True, 1.0):
            with self.subTest(schema_version=repr(invalid)):
                changed = copy.deepcopy(original)
                changed["schema_version"] = invalid
                write_json(path, changed)
                with self.assertRaisesRegex(
                    RELEASE.ReleaseError,
                    r"build provenance schema_version",
                ):
                    self.validate(target)
        write_json(path, original)

    def test_flasher_args_offsets_settings_and_chip_are_authoritative(self):
        build = self.fixture.build_root / "esp32-s3"
        args_path = build / "flasher_args.json"
        args = json.loads(args_path.read_text(encoding="utf-8"))
        for mutation in (
            lambda value: value["app"].update(offset="0x20000"),
            lambda value: value["flash_settings"].update(flash_size="8MB"),
            lambda value: value["flash_settings"].update(flash_freq="40m"),
            lambda value: value["flash_settings"].update(flash_mode="qio"),
            lambda value: value["extra_esptool_args"].update(chip="esp32"),
            lambda value: value["flash_files"].update({"0x10000": "other.bin"}),
        ):
            with self.subTest(mutation=mutation):
                original = copy.deepcopy(args)
                mutation(args)
                write_json(args_path, args)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.validate("esp32-s3")
                args = original
                write_json(args_path, args)

    def test_rejects_wrong_chip_magic_truncation_and_swapped_image_roles(self):
        build = self.fixture.build_root / "esp32-c3"
        boot_path = build / "bootloader" / "bootloader.bin"
        app_path = build / "micropython.bin"
        original_boot = boot_path.read_bytes()
        original_app = app_path.read_bytes()

        cases = []
        wrong_chip = bytearray(original_app)
        wrong_chip[12:14] = struct.pack("<H", 9)
        cases.append(("wrong-chip", boot_path, bytes(wrong_chip)))
        wrong_magic = bytearray(original_boot)
        wrong_magic[0] = 0
        cases.append(("wrong-magic", boot_path, bytes(wrong_magic)))
        cases.append(("truncated", app_path, original_app[:30]))
        cases.append(("app-as-bootloader", boot_path, original_app))
        cases.append(("bootloader-as-app", app_path, original_boot))

        for name, path, replacement in cases:
            with self.subTest(case=name):
                before = path.read_bytes()
                path.write_bytes(replacement)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.validate("esp32-c3")
                path.write_bytes(before)

    def test_c3_silicon_revision_window_is_exact_and_fail_closed(self):
        build = self.fixture.build_root / "esp32-c3"
        spec = PROFILE_SPECS["esp32-c3-4mb"]
        boot_path = build / "bootloader" / "bootloader.bin"
        table_path = build / "partition_table" / "partition-table.bin"
        app_path = build / "micropython.bin"
        merged_path = build / "firmware.bin"
        originals = {
            boot_path: boot_path.read_bytes(),
            app_path: app_path.read_bytes(),
            merged_path: merged_path.read_bytes(),
        }

        def rewrite_merged():
            merged_path.write_bytes(
                make_merged_image(
                    spec["base_offset"],
                    list(
                        zip(
                            spec["component_offsets"],
                            (
                                boot_path.read_bytes(),
                                table_path.read_bytes(),
                                app_path.read_bytes(),
                            ),
                        )
                    ),
                )
            )

        def set_window(path, minimum, maximum):
            image = bytearray(path.read_bytes())
            image[14] = min(minimum, 0xFF)
            image[15:17] = struct.pack("<H", minimum)
            image[17:19] = struct.pack("<H", maximum)
            path.write_bytes(image)
            rewrite_merged()

        self.assertIsNotNone(self.validate("esp32-c3"))
        for name, path, minimum, maximum in (
            ("bootloader-minimum", boot_path, 2, 199),
            ("bootloader-maximum", boot_path, 3, 198),
            ("application-minimum", app_path, 2, 199),
            ("application-maximum", app_path, 3, 200),
        ):
            with self.subTest(case=name):
                for original_path, data in originals.items():
                    original_path.write_bytes(data)
                set_window(path, minimum, maximum)
                with self.assertRaisesRegex(
                    RELEASE.ReleaseError,
                    r"(?i)(silicon|revision|chip_rev)",
                ):
                    self.validate("esp32-c3")

        for path, data in originals.items():
            path.write_bytes(data)

    def test_partition_md5_ranges_fit_and_capacity_are_validated(self):
        build = self.fixture.build_root / "esp32"
        table_path = build / "partition_table" / "partition-table.bin"
        original = table_path.read_bytes()
        bad_tables = {
            "bad-md5": make_partition_table(4 * 1024 * 1024, corrupt_md5=True),
            "overlap": make_partition_table(4 * 1024 * 1024, overlap=True),
            "application-too-small": make_partition_table(
                4 * 1024 * 1024, application_size=64
            ),
            "beyond-capacity": make_partition_table(8 * 1024 * 1024),
        }
        for name, table in bad_tables.items():
            with self.subTest(case=name):
                table_path.write_bytes(table)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.validate("esp32")
        table_path.write_bytes(original)

    def test_merged_image_must_equal_exact_ff_padded_component_merge(self):
        for target in TARGET_TO_PROFILE:
            build = self.fixture.build_root / target
            path = build / "firmware.bin"
            original = path.read_bytes()
            corrupted = bytearray(original)
            corrupted[len(corrupted) // 2] ^= 0x01
            path.write_bytes(corrupted)
            with self.subTest(target=target):
                with self.assertRaises(RELEASE.ReleaseError):
                    self.validate(target)
            path.write_bytes(original)


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class BundleCreationTests(FixtureCase):
    def provenance(self):
        return {
            "pyble": {"commit": "1" * 40, "clean": True},
            "micropython": {"ref": "v1.28.0", "commit": "2" * 40},
            "esp_idf": {"ref": "v5.5.1", "commit": "3" * 40},
            "patch_count": 0,
            "runner": {"os": "FixtureOS 1", "architecture": "fixture64"},
            "tools": [
                {"name": "cmake", "version": "4.0.1"},
                {"name": "esp-idf", "version": "5.5.1"},
                {"name": "python", "version": "3.13.5"},
            ],
        }

    def create(self, **overrides):
        arguments = {
            "build_root": self.fixture.build_root,
            "reproducibility_build_root": (
                self.fixture.reproducibility_build_root
            ),
            "output_dir": (
                self.fixture.root
                / "created"
                / ("v" + PROSPECTIVE_FIRMWARE_VERSION)
            ),
            "repo_root": self.fixture.repo,
            "installer_version": "10.4.0",
            "built_at": "2026-07-30T12:00:00Z",
            "provenance": self.provenance(),
            "public": False,
        }
        arguments.update(overrides)
        return Path(RELEASE.create_bundle(**arguments))

    def test_candidate_requires_distinct_byte_identical_second_build_root(self):
        function = getattr(RELEASE, "create_bundle")
        self.assertIn(
            "reproducibility_build_root",
            inspect.signature(function).parameters,
        )
        with self.assertRaises(RELEASE.ReleaseError):
            self.create(
                output_dir=self.fixture.root / "same-build-root",
                reproducibility_build_root=self.fixture.build_root,
            )

        changed = self.fixture.reproducibility_build_root / "esp32" / "micropython.bin"
        changed.write_bytes(changed.read_bytes() + b"\x00")
        with self.assertRaises(RELEASE.ReleaseError):
            self.create(
                output_dir=self.fixture.root / "different-second-build",
            )

    def test_candidate_has_exact_layout_and_no_extra_files(self):
        bundle = self.create()
        actual = sorted(
            path.relative_to(bundle).as_posix()
            for path in bundle.rglob("*")
            if path.is_file()
        )
        expected = sorted(
            [
                "release.json",
                "release.schema.json",
                "SHA256SUMS",
                "THIRD_PARTY_LICENSES.txt",
                "RELEASE_NOTES.md",
                "RECOVERY.md",
                "HIL_REPORT.md",
            ]
            + [
                "%s/%s" % (profile_id, filename)
                for profile_id in RELEASE_PROFILE_ORDER
                for filename in (
                    "manifest.json",
                    "firmware.bin",
                    "bootloader.bin",
                    "partition-table.bin",
                    "application.bin",
                )
            ]
        )
        self.assertEqual(actual, expected)
        self.assertFalse(
            (bundle / "esp32-c3-4mb").exists(),
            "the deferred C3 profile must not leak into the release tree",
        )

    def test_manifest_is_exact_esp_web_tools_10_4_schema(self):
        bundle = self.create()
        for profile_id in RELEASE_PROFILE_ORDER:
            with self.subTest(profile_id=profile_id):
                manifest = json.loads(
                    (bundle / profile_id / "manifest.json").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    manifest,
                    exact_manifest(PROSPECTIVE_FIRMWARE_VERSION, profile_id),
                )
                self.assertEqual(manifest["new_install_improv_wait_time"], 0)
                for unsupported in (
                    "improv",
                    "improv_service_uuid",
                    "improv_configuration",
                ):
                    self.assertNotIn(unsupported, manifest)
                self.assertEqual(len(manifest["builds"]), 1)
                build = manifest["builds"][0]
                self.assertEqual(set(build), {"chipFamily", "parts"})
                self.assertEqual(len(build["parts"]), 1)
                self.assertEqual(build["parts"][0]["path"], "firmware.bin")

    def test_component_copy_and_application_rename_are_byte_exact(self):
        bundle = self.create()
        for profile_id in RELEASE_PROFILE_ORDER:
            spec = PROFILE_SPECS[profile_id]
            source = self.fixture.build_root / spec["target"]
            expected_pairs = (
                (source / "firmware.bin", bundle / profile_id / "firmware.bin"),
                (
                    source / "bootloader" / "bootloader.bin",
                    bundle / profile_id / "bootloader.bin",
                ),
                (
                    source / "partition_table" / "partition-table.bin",
                    bundle / profile_id / "partition-table.bin",
                ),
                (
                    source / "micropython.bin",
                    bundle / profile_id / "application.bin",
                ),
            )
            for source_path, bundled_path in expected_pairs:
                with self.subTest(path=bundled_path):
                    self.assertEqual(
                        sha256_path(source_path), sha256_path(bundled_path)
                    )

    def test_release_metadata_uses_exact_deterministic_shape_and_order(self):
        bundle = self.create()
        release = json.loads((bundle / "release.json").read_text(encoding="utf-8"))
        self.assertEqual(set(release), set(exact_release_schema()["required"]))
        self.assertEqual(release["schema_version"], 3)
        self.assertEqual(
            release["installer"],
            {
                "package": "esp-web-tools",
                "version": "10.4.0",
            },
        )
        self.assertEqual(
            [profile["id"] for profile in release["profiles"]],
            list(RELEASE_PROFILE_ORDER),
        )
        for profile in release["profiles"]:
            self.assertEqual(
                profile["silicon_revision"],
                PROFILE_SPECS[profile["id"]]["silicon_revision"],
            )
            self.assertEqual(
                [item["role"] for item in profile["components"]],
                list(ROLE_ORDER),
            )
        tools = release["provenance"]["tools"]
        self.assertEqual(
            [tool["name"] for tool in tools],
            sorted(tool["name"] for tool in tools),
        )
        hil = read_hil_payload(bundle / "HIL_REPORT.md")
        self.assertEqual(hil["schema_version"], 4)
        self.assertEqual(
            hil["qualification_policy_sha256"],
            sha256_path(self.fixture.qualification_policy_path),
        )
        self.assertEqual(
            hil["qualification_policy"],
            json.loads(
                self.fixture.qualification_policy_path.read_text(encoding="utf-8")
            ),
        )
        self.assertEqual(
            [record["profile_id"] for record in hil["records"]],
            list(RELEASE_PROFILE_ORDER),
        )
        self.assertTrue(
            all(record["oi1_observation"] is None for record in hil["records"])
        )
        self.assertIsNone(hil["waveshare_lcd147b_qualification"])
        self.assertNotIn(
            "esp32-c3-4mb",
            [record["profile_id"] for record in hil["records"]],
        )
        self.assertNotIn(
            "esp32-c3-4mb",
            [
                record["profile_id"]
                for record in hil["qualification_policy"]["profiles"]
            ],
        )
        self.assertEqual(
            hil["qualification_policy"]["deferred_profiles"],
            ["esp32-c3-4mb"],
        )

    def test_create_requires_exact_policy_workload_units_and_three_profile_scope(self):
        mutations = {
            "workload": lambda policy: policy["workload"].__setitem__(
                "required_att_mtu", 246
            ),
            "derivation": lambda policy: policy["derivation"].__setitem__(
                "heap_floor", "manual-margin"
            ),
            "bool-threshold": lambda policy: policy["profiles"][0][
                "thresholds"
            ].__setitem__("gc_free_min_bytes", True),
            "missing-threshold": lambda policy: policy["profiles"][0][
                "thresholds"
            ].pop("get_verified_goodput_min_bytes_per_second"),
            "c3-policy-row": lambda policy: policy["profiles"].append(
                {
                    "profile_id": "esp32-c3-4mb",
                    "target": "esp32-c3",
                    "thresholds": copy.deepcopy(QUALIFICATION_THRESHOLDS),
                }
            ),
            "c3-profile-order": lambda policy: policy["profile_order"].append(
                "esp32-c3-4mb"
            ),
        }
        original = self.fixture.qualification_policy_path.read_text(
            encoding="utf-8"
        )
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                policy = json.loads(original)
                mutate(policy)
                write_json(self.fixture.qualification_policy_path, policy)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.create(
                        output_dir=self.fixture.root / ("created-" + name)
                    )
        self.fixture.qualification_policy_path.write_text(
            original,
            encoding="utf-8",
        )

    def test_create_rejects_missing_changed_or_noncanonical_baseline_evidence(self):
        policy = json.loads(
            self.fixture.qualification_policy_path.read_text(encoding="utf-8")
        )
        baseline = self.fixture.repo / policy["baseline_evidence"]["path"]
        original = baseline.read_bytes()
        cases = {
            "missing": None,
            "changed": original + b" ",
            "noncanonical": json.dumps(
                json.loads(original),
                indent=2,
            ).encode("utf-8"),
        }
        for name, replacement in cases.items():
            with self.subTest(case=name):
                if replacement is None:
                    baseline.unlink()
                else:
                    baseline.write_bytes(replacement)
                    policy["baseline_evidence"]["sha256"] = sha256_path(baseline)
                    write_json(self.fixture.qualification_policy_path, policy)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.create(
                        output_dir=self.fixture.root / ("baseline-" + name)
                    )
                baseline.write_bytes(original)
                policy["baseline_evidence"]["sha256"] = sha256_path(baseline)
                write_json(self.fixture.qualification_policy_path, policy)

    def test_create_rejects_semantically_invalid_baseline_and_underived_thresholds(self):
        original_policy = json.loads(
            self.fixture.qualification_policy_path.read_text(encoding="utf-8")
        )
        baseline_path = (
            self.fixture.repo
            / original_policy["baseline_evidence"]["path"]
        )
        original_baseline = json.loads(
            baseline_path.read_text(encoding="utf-8")
        )
        baseline_mutations = {
            "source-commit": lambda baseline: baseline.__setitem__(
                "source_commit", "9" * 40
            ),
            "profile-order": lambda baseline: baseline["profile_order"].reverse(),
            "c3-profile": lambda baseline: baseline["profiles"].append(
                {
                    **copy.deepcopy(baseline["profiles"][0]),
                    "profile_id": "esp32-c3-4mb",
                    "target": "esp32-c3",
                }
            ),
            "environment": lambda baseline: baseline["profiles"][0][
                "environment"
            ].pop("ble_adapter"),
            "observation-count": lambda baseline: baseline["profiles"][0][
                "oi1_observation"
            ]["heap_post_hello"].pop(),
            "bool-build": lambda baseline: baseline["profiles"][0][
                "oi1_build"
            ].__setitem__("application_image_bytes", True),
        }
        for name, mutate in baseline_mutations.items():
            with self.subTest(case=name):
                baseline = copy.deepcopy(original_baseline)
                policy = copy.deepcopy(original_policy)
                mutate(baseline)
                baseline_path.write_bytes(canonical_json_bytes(baseline))
                policy["baseline_evidence"]["sha256"] = sha256_path(
                    baseline_path
                )
                write_json(self.fixture.qualification_policy_path, policy)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.create(
                        output_dir=self.fixture.root / ("semantic-" + name)
                    )

        baseline_path.write_bytes(canonical_json_bytes(original_baseline))
        policy = copy.deepcopy(original_policy)
        policy["profiles"][0]["thresholds"]["gc_free_min_bytes"] -= 1024
        write_json(self.fixture.qualification_policy_path, policy)
        with self.assertRaises(RELEASE.ReleaseError):
            self.create(
                output_dir=self.fixture.root / "underived-threshold"
            )

        baseline_path.write_bytes(canonical_json_bytes(original_baseline))
        write_json(self.fixture.qualification_policy_path, original_policy)

    def test_baseline_firmware_version_obeys_source_era_bounds(self):
        policy = json.loads(
            self.fixture.qualification_policy_path.read_text(encoding="utf-8")
        )
        baseline_path = self.fixture.repo / policy["baseline_evidence"]["path"]
        original = json.loads(baseline_path.read_text(encoding="utf-8"))
        cases = (
            ("historical-v042-v041", "0.4.2", "0.4.1", True),
            ("historical-future", "0.4.2", "0.5.0", False),
            ("v050-stale", "0.5.0", "0.4.1", False),
            ("v050-current", "0.5.0", "0.5.0", True),
            ("v050-future", "0.5.0", "0.6.0", False),
            ("v051-reuses-v050", "0.5.1", "0.5.0", True),
        )
        for name, source_version, baseline_version, accepted in cases:
            with self.subTest(case=name):
                baseline = copy.deepcopy(original)
                baseline["firmware_version"] = baseline_version
                source_policy = copy.deepcopy(policy)
                source_core = RELEASE._firmware_release_core(
                    source_version,
                    "fixture source version",
                )
                profile_order = (
                    HISTORICAL_V042_PROFILE_ORDER
                    if source_core == (0, 4, 2)
                    else RELEASE_PROFILE_ORDER
                )
                baseline["profile_order"] = list(profile_order)
                baseline["profiles"] = [
                    profile
                    for profile in baseline["profiles"]
                    if profile["profile_id"] in profile_order
                ]
                source_policy["schema_version"] = (
                    1 if source_core == (0, 4, 2) else 2
                )
                source_policy["profile_order"] = list(profile_order)
                source_policy["profiles"] = [
                    profile
                    for profile in source_policy["profiles"]
                    if profile["profile_id"] in profile_order
                ]
                source_policy["derivation"] = copy.deepcopy(
                    QUALIFICATION_DERIVATION
                    if source_core >= (0, 5, 0)
                    else QUALIFICATION_DERIVATION_V1
                )
                for profile, baseline_profile in zip(
                    source_policy["profiles"],
                    baseline["profiles"],
                ):
                    observation = baseline_profile["oi1_observation"]
                    if source_core >= (0, 5, 0):
                        observation["transfer_link_facts"] = (
                            fixture_transfer_link_facts(
                                baseline_profile["profile_id"]
                            )
                        )
                    else:
                        observation.pop("transfer_link_facts", None)
                    profile["thresholds"] = fixture_oi1_thresholds(
                        baseline_profile["oi1_build"],
                        observation,
                        source_version,
                    )
                invocation = lambda: RELEASE._validate_qualification_baseline(
                    baseline,
                    baseline["source_commit"],
                    source_policy,
                    firmware_version=source_version,
                )
                if accepted:
                    invocation()
                else:
                    with self.assertRaises(RELEASE.ReleaseError):
                        invocation()

    def test_schema_is_draft_2020_12_and_closes_every_object(self):
        bundle = self.create()
        schema = json.loads(
            (bundle / "release.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            schema.get("$schema"),
            "https://json-schema.org/draft/2020-12/schema",
        )

        def visit(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertIs(
                        node.get("additionalProperties"),
                        False,
                        "every release-schema object must reject unknown keys",
                    )
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)

        visit(schema)

    def test_sha256sums_covers_every_file_except_itself(self):
        bundle = self.create()
        lines = (bundle / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        covered = [line.split("  ", 1)[1] for line in lines]
        expected = sorted(
            path.relative_to(bundle).as_posix()
            for path in bundle.rglob("*")
            if path.is_file() and path.name != "SHA256SUMS"
        )
        self.assertEqual(covered, expected)
        for line in lines:
            digest, relative = line.split("  ", 1)
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertEqual(digest, sha256_path(bundle / relative))

    def test_recovery_uses_only_executable_pinned_esptool_commands(self):
        bundle = self.create()
        recovery = (bundle / "RECOVERY.md").read_text(encoding="utf-8")
        expected = (
            "python -m esptool --chip esp32 write_flash 0x1000 "
            "esp32-4mb/firmware.bin",
            "python -m esptool --chip esp32s3 write_flash 0x0 "
            "esp32-s3-n16r8/firmware.bin",
            "python -m esptool --chip esp32s3 write_flash 0x0 "
            "waveshare-esp32-s3-lcd-147b/firmware.bin",
        )
        for command in expected:
            with self.subTest(command=command):
                self.assertEqual(recovery.count(command), 1)
        self.assertNotIn("esp32-c3", recovery)
        self.assertNotIn("esp32c3", recovery)
        self.assertNotIn("write-flash", recovery)

    def test_release_notes_name_only_the_three_packaged_profiles(self):
        bundle = self.create()
        notes = (bundle / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        for profile_id in RELEASE_PROFILE_ORDER:
            with self.subTest(profile_id=profile_id):
                self.assertIn(profile_id, notes)
        self.assertIn("lean common runtime", notes)
        self.assertIn("no bundled board-specific display drivers", notes)
        self.assertIn("exact Waveshare ESP32-S3-LCD-1.47B B-version", notes)
        self.assertIn("ST7789 runtime", notes)
        self.assertNotIn("esp32-c3", notes)

    def test_create_rejects_wrong_installer_version_and_public_without_hil(self):
        with self.assertRaises(RELEASE.ReleaseError):
            self.create(installer_version="latest")
        with self.assertRaises(RELEASE.ReleaseError):
            self.create(public=True)


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class AuditedCandidateCreationRedTests(unittest.TestCase):
    def setUp(self):
        self.release_fixture = ReleaseFixture()
        self.license_module = self._load_license_fixture_module()
        self.license_fixture = self.license_module.ReleaseLicenseFixture()
        self._add_release_inputs_to_audited_build()

    def tearDown(self):
        self.license_fixture.close()
        self.release_fixture.cleanup()

    def _load_license_fixture_module(self):
        import sys

        path = Path(__file__).with_name(
            "test_release_license_policy_v2_integration.py"
        )
        spec = importlib.util.spec_from_file_location(
            "pyble_candidate_license_fixture",
            path,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(spec.name, None)
        return module

    def _add_release_inputs_to_audited_build(self):
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
        for target in TARGET_TO_PROFILE:
            for relative in release_inputs:
                source = self.release_fixture.build_root / target / relative
                destination = self.license_fixture.build_root / target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        install_fixture_qualification_policy(self.license_fixture.repo)
        self.license_fixture.rebind_build_provenance()
        self.reproducibility_build_root = (
            self.license_fixture.root / "build-reproducibility"
        )
        shutil.copytree(
            self.license_fixture.build_root,
            self.reproducibility_build_root,
        )

    def _provenance(self):
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

    def _create(self, output, notice, evidence):
        return Path(
            RELEASE.create_bundle(
                build_root=self.license_fixture.build_root,
                reproducibility_build_root=self.reproducibility_build_root,
                output_dir=output,
                repo_root=self.license_fixture.repo,
                installer_version="10.4.0",
                built_at="2026-07-30T12:00:00Z",
                provenance=self._provenance(),
                audited_notice=notice,
                license_evidence_dir=evidence,
                license_build_root=self.license_fixture.build_root,
                public=False,
            )
        )

    def test_pending_candidate_consumes_exact_fresh_audited_notice(self):
        result = RELEASE.audit_release_licenses(
            build_root=self.license_fixture.build_root,
            repo_root=self.license_fixture.repo,
            evidence_dir=self.license_fixture.evidence,
            runner=self.license_module.FakeOfflineSbomRunner(self.license_fixture),
        )
        receipt = json.loads(
            (self.license_fixture.evidence / "audit-receipt.json").read_text(
                encoding="utf-8"
            )
        )
        expected_identities = {
            (profile_id, role)
            for profile_id, _target, _idf_target in RELEASE.LICENSE_AUDIT_PROFILES
            for role in RELEASE.LICENSE_AUDIT_ROLES
        }
        observed_identities = {
            (entry["profile_id"], entry["role"])
            for entry in receipt["identities"]
        }
        self.assertEqual(len(observed_identities), 8)
        self.assertEqual(observed_identities, expected_identities)
        notice = self.license_module.extract_notice(result)
        notice_path = self.license_fixture.root / "audited-notice.txt"
        notice_path.write_text(notice, encoding="utf-8")

        output = self.license_fixture.root / "candidate-ok"
        candidate = self._create(
            output,
            notice_path,
            self.license_fixture.evidence,
        )
        self.assertEqual(
            (candidate / "THIRD_PARTY_LICENSES.txt").read_bytes(),
            notice_path.read_bytes(),
        )
        self.assertNotIn(
            self.license_module.CANDIDATE_MARKER,
            (candidate / "THIRD_PARTY_LICENSES.txt").read_text(encoding="utf-8"),
        )
        release = json.loads((candidate / "release.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [profile["hil_status"] for profile in release["profiles"]],
            ["pending"] * len(RELEASE_PROFILE_ORDER),
        )

        missing_output = self.license_fixture.root / "candidate-missing"
        with self.assertRaises(RELEASE.ReleaseError):
            self._create(
                missing_output,
                notice_path,
                self.license_fixture.root / "missing-evidence",
            )
        self.assertFalse(missing_output.exists())

        mismatched_evidence = self.license_fixture.root / "mismatched-evidence"
        shutil.copytree(self.license_fixture.evidence, mismatched_evidence)
        evidence_file = next(
            path for path in mismatched_evidence.rglob("*") if path.is_file()
        )
        evidence_file.write_bytes(evidence_file.read_bytes() + b"\n")
        mismatch_output = self.license_fixture.root / "candidate-mismatch"
        with self.assertRaises(RELEASE.ReleaseError):
            self._create(mismatch_output, notice_path, mismatched_evidence)
        self.assertFalse(mismatch_output.exists())

        stale_input = (
            self.license_fixture.build_root / "esp32" / "project_description.json"
        )
        original = stale_input.read_bytes()
        stale_input.write_bytes(original + b"\n")
        try:
            stale_output = self.license_fixture.root / "candidate-stale"
            with self.assertRaises(RELEASE.ReleaseError):
                self._create(
                    stale_output,
                    notice_path,
                    self.license_fixture.evidence,
                )
            self.assertFalse(stale_output.exists())
        finally:
            stale_input.write_bytes(original)


class CandidateCreationCliRedTests(unittest.TestCase):
    def test_create_candidate_requires_all_audited_notice_inputs(self):
        help_result = subprocess.run(
            [
                os.fspath(Path(os.sys.executable)),
                os.fspath(RELEASE_SCRIPT),
                "create-candidate",
                "--help",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        required = {
            "--reproducibility-build-root": "/reproducibility-build",
            "--audited-notice": "/notice",
            "--license-evidence-dir": "/evidence",
            "--license-build-root": "/license-build",
            "--repo-root": "/repo",
        }
        for option in required:
            with self.subTest(help_option=option):
                self.assertIn(option, help_result.stdout)

        for missing in required:
            with self.subTest(missing=missing):
                arguments = [
                    os.fspath(Path(os.sys.executable)),
                    os.fspath(RELEASE_SCRIPT),
                    "create-candidate",
                    "/build",
                    "/output",
                    "--built-at",
                    "2026-07-30T12:00:00Z",
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


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class BundleValidationTests(FixtureCase):
    def validate_candidate(self, bundle: Path):
        return RELEASE.validate_bundle(
            bundle,
            public=False,
            qualification_repo_root=self.fixture.repo,
        )

    def test_candidate_pending_passes_but_public_pending_fails(self):
        bundle = self.fixture.make_bundle(public=False)
        with self.assertRaisesRegex(
            RELEASE.ReleaseError,
            r"(?i)(qualification|policy|repository)",
        ):
            RELEASE.validate_bundle(bundle, public=False)
        self.assertIsNotNone(
            RELEASE.validate_bundle(
                bundle,
                public=False,
                qualification_repo_root=self.fixture.repo,
            )
        )
        with self.assertRaises(RELEASE.ReleaseError):
            RELEASE.validate_bundle(bundle, public=True)

    def test_candidate_rejects_policy_tampering_with_stale_embedded_digest(self):
        bundle = self.fixture.make_bundle(public=False)
        report = bundle / "HIL_REPORT.md"
        payload = read_hil_payload(report)
        for entry in (
            payload["qualification_policy"]["profiles"][0],
            payload["records"][0]["oi1_policy"],
        ):
            entry["thresholds"]["gc_free_min_bytes"] = 1
        write_hil_payload(report, payload)
        self.fixture.refresh_declared_hashes()
        with self.assertRaises(RELEASE.ReleaseError):
            RELEASE.validate_bundle(
                bundle,
                public=False,
                qualification_repo_root=self.fixture.repo,
            )

    def test_historical_public_bundle_rejects_current_qualification_root(self):
        historical = ReleaseFixture(firmware_version="0.4.2")
        self.addCleanup(historical.cleanup)
        bundle = historical.make_bundle(public=True)
        with self.assertRaises(RELEASE.ReleaseError):
            RELEASE.validate_bundle(bundle, public=True)

        import sys

        license_test_path = Path(__file__).with_name(
            "test_release_license_policy_v2_integration.py"
        )
        spec = importlib.util.spec_from_file_location(
            "pyble_release_license_fixture_for_bundle",
            license_test_path,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        test_release_license_audit = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = test_release_license_audit
        try:
            spec.loader.exec_module(test_release_license_audit)
        finally:
            sys.modules.pop(spec.name, None)

        license_fixture = test_release_license_audit.ReleaseLicenseFixture()
        try:
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
            for target in TARGET_TO_PROFILE:
                for relative in release_inputs:
                    source = historical.build_root / target / relative
                    destination = license_fixture.build_root / target / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
            install_fixture_qualification_policy(license_fixture.repo)
            license_fixture.rebind_build_provenance()

            result = RELEASE.audit_release_licenses(
                build_root=license_fixture.build_root,
                repo_root=license_fixture.repo,
                evidence_dir=license_fixture.evidence,
                runner=test_release_license_audit.FakeOfflineSbomRunner(
                    license_fixture
                ),
            )
            notice = test_release_license_audit.extract_notice(result)
            (bundle / "THIRD_PARTY_LICENSES.txt").write_text(
                notice,
                encoding="utf-8",
            )
            release_path = bundle / "release.json"
            release = json.loads(release_path.read_text(encoding="utf-8"))
            release["provenance"]["micropython"][
                "commit"
            ] = license_fixture.micropython_commit
            release["provenance"]["esp_idf"][
                "commit"
            ] = license_fixture.esp_idf_commit
            write_json(release_path, release)
            historical.refresh_declared_hashes()
            # This fixture is the intentionally retained V2/v0.4.2 bundle,
            # while the audited repository is the current V3/v0.5.0 source
            # era. They must not be combined. Current public success is covered
            # by test_waveshare_release_gate's v0.5 finalization integration.
            with self.assertRaisesRegex(
                RELEASE.ReleaseError,
                "HIL qualification policy differs",
            ):
                RELEASE.validate_bundle(
                    bundle,
                    public=True,
                    license_evidence_dir=license_fixture.evidence,
                    license_build_root=license_fixture.build_root,
                    repo_root=license_fixture.repo,
                )
        finally:
            license_fixture.close()

    def test_previously_activated_public_bundle_revalidates_without_build_evidence(
        self,
    ):
        bundle = self.fixture.make_bundle(public=True)
        result = RELEASE.validate_bundle(
            bundle,
            previously_activated_public=True,
            qualification_repo_root=self.fixture.repo,
        )
        self.assertEqual(
            result["identity"]["version"],
            PROSPECTIVE_FIRMWARE_VERSION,
        )

        with self.assertRaises(RELEASE.ReleaseError):
            RELEASE.validate_bundle(
                bundle,
                public=True,
                previously_activated_public=True,
                qualification_repo_root=self.fixture.repo,
            )

        pending = self.fixture.make_bundle(public=False)
        with self.assertRaises(RELEASE.ReleaseError):
            RELEASE.validate_bundle(
                pending,
                previously_activated_public=True,
                qualification_repo_root=self.fixture.repo,
            )

    def test_corrupt_truncated_missing_and_swapped_parts_fail_closed(self):
        mutations = {
            "corrupt": lambda bundle: (
                bundle / "esp32-4mb" / "firmware.bin"
            ).write_bytes((bundle / "esp32-4mb" / "firmware.bin").read_bytes() + b"x"),
            "truncated": lambda bundle: (
                bundle / "esp32-s3-n16r8" / "firmware.bin"
            ).write_bytes(b"\xe9"),
            "missing": lambda bundle: (
                bundle / "esp32-s3-n16r8" / "application.bin"
            ).unlink(),
            "swapped": lambda bundle: self._swap_components_and_rehash(bundle),
        }
        for name, mutation in mutations.items():
            with self.subTest(case=name):
                bundle = self.fixture.make_bundle(public=False)
                mutation(bundle)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.validate_candidate(bundle)

    def _swap_components_and_rehash(self, bundle):
        directory = bundle / "esp32-4mb"
        boot = directory / "bootloader.bin"
        app = directory / "application.bin"
        boot_bytes, app_bytes = boot.read_bytes(), app.read_bytes()
        boot.write_bytes(app_bytes)
        app.write_bytes(boot_bytes)
        self.fixture.refresh_declared_hashes()

    def test_manifest_metadata_disagreement_fails_even_when_hashes_are_fresh(self):
        bundle = self.fixture.make_bundle(public=False)
        manifest_path = bundle / "esp32-4mb" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["builds"][0]["parts"][0]["offset"] = 0
        write_json(manifest_path, manifest)
        self.fixture.refresh_declared_hashes()
        with self.assertRaises(RELEASE.ReleaseError):
            self.validate_candidate(bundle)

    def test_unknown_keys_fail_at_every_manifest_level(self):
        for location in ("top", "build", "part"):
            with self.subTest(location=location):
                bundle = self.fixture.make_bundle(public=False)
                path = bundle / "esp32-4mb" / "manifest.json"
                manifest = json.loads(path.read_text(encoding="utf-8"))
                target = {
                    "top": manifest,
                    "build": manifest["builds"][0],
                    "part": manifest["builds"][0]["parts"][0],
                }[location]
                target["unexpected"] = True
                write_json(path, manifest)
                self.fixture.refresh_declared_hashes()
                with self.assertRaises(RELEASE.ReleaseError):
                    self.validate_candidate(bundle)

    def test_unsafe_manifest_paths_fail_closed(self):
        unsafe_paths = (
            "../firmware.bin",
            "/firmware.bin",
            "https://example.test/firmware.bin",
            r"subdir\firmware.bin",
            "subdir/./firmware.bin",
            "firmware.bin?mutable=1",
            "firmware.bin#fragment",
        )
        for unsafe in unsafe_paths:
            with self.subTest(path=unsafe):
                bundle = self.fixture.make_bundle(public=False)
                path = bundle / "esp32-4mb" / "manifest.json"
                manifest = json.loads(path.read_text(encoding="utf-8"))
                manifest["builds"][0]["parts"][0]["path"] = unsafe
                write_json(path, manifest)
                self.fixture.refresh_declared_hashes()
                with self.assertRaises(RELEASE.ReleaseError):
                    self.validate_candidate(bundle)

    def test_profile_scoped_family_offset_and_single_build_part_are_exact(self):
        mutations = (
            lambda manifest: manifest["builds"][0].update(chipFamily="ESP32-S3"),
            lambda manifest: manifest["builds"][0]["parts"][0].update(offset=0),
            lambda manifest: manifest["builds"][0]["parts"].append(
                {
                    "path": "esp32-4mb/application.bin",
                    "offset": 0x10000,
                }
            ),
            lambda manifest: manifest["builds"].append(
                copy.deepcopy(manifest["builds"][0])
            ),
            lambda manifest: manifest["builds"].pop(0),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                bundle = self.fixture.make_bundle(public=False)
                path = bundle / "esp32-4mb" / "manifest.json"
                manifest = json.loads(path.read_text(encoding="utf-8"))
                mutation(manifest)
                write_json(path, manifest)
                self.fixture.refresh_declared_hashes()
                with self.assertRaises(RELEASE.ReleaseError):
                    self.validate_candidate(bundle)

    def test_release_unknown_placeholder_dirty_and_abbreviated_values_fail(self):
        mutations = (
            lambda release: release.update(unexpected=True),
            lambda release: release["provenance"]["pyble"].update(clean=False),
            lambda release: release["provenance"]["pyble"].update(commit="1234"),
            lambda release: release["provenance"]["tools"][0].update(version="unknown"),
            lambda release: release["identity"].update(version="v0.4.1"),
            lambda release: release["identity"].update(agent_version="0.4.2"),
            lambda release: release["identity"].update(built_at="2026-07-30 12:00:00"),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                bundle = self.fixture.make_bundle(public=False)
                path = bundle / "release.json"
                release = json.loads(path.read_text(encoding="utf-8"))
                mutation(release)
                write_json(path, release)
                self.fixture.refresh_sums()
                with self.assertRaises(RELEASE.ReleaseError):
                    self.validate_candidate(bundle)

    def test_release_schema_version_requires_the_exact_integer_three(self):
        for invalid in (True, 3.0, 2):
            with self.subTest(schema_version=repr(invalid)):
                bundle = self.fixture.make_bundle(public=False)
                path = bundle / "release.json"
                release = json.loads(path.read_text(encoding="utf-8"))
                release["schema_version"] = invalid
                write_json(path, release)
                self.fixture.refresh_sums()
                with self.assertRaisesRegex(
                    RELEASE.ReleaseError,
                    r"release schema_version",
                ):
                    self.validate_candidate(bundle)

    def test_deferred_c3_profile_cannot_be_added_to_schema_v3_metadata(self):
        bundle = self.fixture.make_bundle(public=False)
        path = bundle / "release.json"
        release = json.loads(path.read_text(encoding="utf-8"))
        deferred = copy.deepcopy(release["profiles"][-1])
        deferred["id"] = "esp32-c3-4mb"
        deferred["chip_family"] = "ESP32-C3"
        release["profiles"].append(deferred)
        write_json(path, release)
        self.fixture.refresh_sums()
        with self.assertRaises(RELEASE.ReleaseError):
            self.validate_candidate(bundle)

    def test_tool_names_must_be_unique_sorted_and_nonempty(self):
        mutations = (
            lambda tools: tools.reverse(),
            lambda tools: tools.append(copy.deepcopy(tools[0])),
            lambda tools: tools[0].update(name=""),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                bundle = self.fixture.make_bundle(public=False)
                path = bundle / "release.json"
                release = json.loads(path.read_text(encoding="utf-8"))
                mutation(release["provenance"]["tools"])
                write_json(path, release)
                self.fixture.refresh_sums()
                with self.assertRaises(RELEASE.ReleaseError):
                    self.validate_candidate(bundle)

    def test_sha256sums_missing_extra_or_wrong_entry_fails(self):
        for case in ("missing", "extra", "wrong"):
            with self.subTest(case=case):
                bundle = self.fixture.make_bundle(public=False)
                path = bundle / "SHA256SUMS"
                lines = path.read_text(encoding="utf-8").splitlines()
                if case == "missing":
                    lines.pop()
                elif case == "extra":
                    lines.append("%s  mutable-latest.bin" % ("0" * 64))
                else:
                    lines[0] = "%s  %s" % (
                        "0" * 64,
                        lines[0].split("  ", 1)[1],
                    )
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                with self.assertRaises(RELEASE.ReleaseError):
                    self.validate_candidate(bundle)

    def test_hil_report_hash_mismatch_missing_row_and_unsigned_row_fail_public(self):
        mutations = (
            lambda text: re.sub(
                r'("manifest_sha256": ")[0-9a-f]{64}(")',
                r"\g<1>%s\2" % ("0" * 64),
                text,
                count=1,
            ),
            lambda text: text.replace(
                '"profile_id": "esp32-s3-n16r8"',
                '"profile_id": "missing-s3"',
                1,
            ),
            lambda text: text.replace(
                '"maintainer_signoff": "Fixture Maintainer"',
                '"maintainer_signoff": ""',
                1,
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                bundle = self.fixture.make_bundle(public=True)
                report = bundle / "HIL_REPORT.md"
                report.write_text(
                    mutation(report.read_text(encoding="utf-8")),
                    encoding="utf-8",
                )
                self.fixture.refresh_declared_hashes()
                with self.assertRaises(RELEASE.ReleaseError):
                    RELEASE.validate_bundle(bundle, public=True)

    def test_hil_requires_one_v4_marker_and_exact_integer_schema_four(self):
        for invalid in (True, 4.0, 3):
            with self.subTest(schema_version=repr(invalid)):
                bundle = self.fixture.make_bundle(public=False)
                report = bundle / "HIL_REPORT.md"
                text = report.read_text(encoding="utf-8")
                text = text.replace(
                    '"schema_version": 4',
                    '"schema_version": %s' % json.dumps(invalid),
                    1,
                )
                report.write_text(text, encoding="utf-8")
                self.fixture.refresh_declared_hashes()
                with self.assertRaisesRegex(
                    RELEASE.ReleaseError,
                    r"HIL record schema version",
                ):
                    self.validate_candidate(bundle)

        for marker_text in (
            "PYBLE_HIL_RECORDS_V1",
            "PYBLE_HIL_RECORDS_V4\n{}\n-->\n"
            "<!-- PYBLE_HIL_RECORDS_V4",
        ):
            with self.subTest(marker=marker_text):
                bundle = self.fixture.make_bundle(public=False)
                report = bundle / "HIL_REPORT.md"
                report.write_text(
                    report.read_text(encoding="utf-8").replace(
                        "PYBLE_HIL_RECORDS_V4",
                        marker_text,
                        1,
                    ),
                    encoding="utf-8",
                )
                self.fixture.refresh_declared_hashes()
                with self.assertRaises(RELEASE.ReleaseError):
                    self.validate_candidate(bundle)

    def test_candidate_static_oi1_build_and_thresholds_are_recomputed(self):
        mutations = {
            "application-size": lambda payload: payload["records"][0][
                "oi1_build"
            ].__setitem__(
                "application_image_bytes",
                payload["records"][0]["oi1_build"]["application_image_bytes"] + 1,
            ),
            "factory-size": lambda payload: payload["records"][0][
                "oi1_build"
            ].__setitem__(
                "factory_partition_bytes",
                payload["records"][0]["oi1_build"]["factory_partition_bytes"] + 1,
            ),
            "headroom-arithmetic": lambda payload: payload["records"][0][
                "oi1_build"
            ].__setitem__(
                "application_headroom_bytes",
                payload["records"][0]["oi1_build"]["application_headroom_bytes"] + 1,
            ),
            "image-ceiling": lambda payload: [
                item["thresholds"].__setitem__(
                    "application_image_max_bytes",
                    payload["records"][0]["oi1_build"]["application_image_bytes"] - 1,
                )
                for item in (
                    payload["qualification_policy"]["profiles"][0],
                    payload["records"][0]["oi1_policy"],
                )
            ],
            "headroom-floor": lambda payload: [
                item["thresholds"].__setitem__(
                    "application_headroom_min_bytes",
                    payload["records"][0]["oi1_build"][
                        "application_headroom_bytes"
                    ]
                    + 1,
                )
                for item in (
                    payload["qualification_policy"]["profiles"][0],
                    payload["records"][0]["oi1_policy"],
                )
            ],
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                bundle = self.fixture.make_bundle(public=False)
                report = bundle / "HIL_REPORT.md"
                payload = read_hil_payload(report)
                mutate(payload)
                write_hil_payload(report, payload)
                self.fixture.refresh_declared_hashes()
                with self.assertRaises(RELEASE.ReleaseError):
                    self.validate_candidate(bundle)

    def test_candidate_rejects_c3_wrong_policy_binding_and_bool_integer(self):
        mutations = {
            "c3-record": lambda payload: payload["records"].append(
                {
                    **copy.deepcopy(payload["records"][0]),
                    "profile_id": "esp32-c3-4mb",
                }
            ),
            "c3-policy": lambda payload: payload["qualification_policy"][
                "profiles"
            ].append(
                {
                    "profile_id": "esp32-c3-4mb",
                    "target": "esp32-c3",
                    "thresholds": copy.deepcopy(QUALIFICATION_THRESHOLDS),
                }
            ),
            "wrong-policy-binding": lambda payload: payload["records"][0][
                "oi1_policy"
            ]["thresholds"].__setitem__("gc_free_min_bytes", 1),
            "bool-build": lambda payload: payload["records"][0][
                "oi1_build"
            ].__setitem__("application_image_bytes", True),
            "extra-key": lambda payload: payload["records"][0].__setitem__(
                "unknown", 1
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                bundle = self.fixture.make_bundle(public=False)
                report = bundle / "HIL_REPORT.md"
                payload = read_hil_payload(report)
                mutate(payload)
                write_hil_payload(report, payload)
                self.fixture.refresh_declared_hashes()
                with self.assertRaises(RELEASE.ReleaseError):
                    self.validate_candidate(bundle)


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class ReproducibilityComparisonTests(FixtureCase):
    def test_two_equivalent_clean_build_roots_compare_byte_identical(self):
        second = self.fixture.root / "build-second"
        shutil.copytree(self.fixture.build_root, second)
        self.assertIsNone(RELEASE.compare_build_roots(self.fixture.build_root, second))

    def test_any_released_part_change_breaks_reproducibility(self):
        for target, relative in (
            ("esp32", "firmware.bin"),
            ("esp32-s3", "bootloader/bootloader.bin"),
            ("esp32-c3", "partition_table/partition-table.bin"),
            ("esp32", "micropython.bin"),
            ("esp32-s3", "flasher_args.json"),
        ):
            with self.subTest(target=target, relative=relative):
                second = self.fixture.root / (
                    "build-second-%s-%s" % (target, relative.replace("/", "-"))
                )
                shutil.copytree(self.fixture.build_root, second)
                path = second / target / relative
                if path.suffix == ".json":
                    value = json.loads(path.read_text(encoding="utf-8"))
                    value["flash_settings"]["flash_freq"] = "40m"
                    write_json(path, value)
                else:
                    path.write_bytes(path.read_bytes() + b"x")
                with self.assertRaises(RELEASE.ReleaseError):
                    RELEASE.compare_build_roots(self.fixture.build_root, second)

    def test_whole_elf_is_compared_before_its_derived_flash_bytes(self):
        target = "esp32-c3"
        spec = PROFILE_SPECS[TARGET_TO_PROFILE[target]]
        second = self.fixture.root / "build-second-elf"
        shutil.copytree(self.fixture.build_root, second)
        elf = second / target / "micropython.elf"
        elf.write_bytes(elf.read_bytes() + b"\0stable diagnostic change")
        rebind_fixture_application_to_elf(second / target, spec)
        with self.assertRaisesRegex(
            RELEASE.ReleaseError,
            r"reproducibility mismatch: esp32-c3/micropython\.elf",
        ):
            RELEASE.compare_build_roots(self.fixture.build_root, second)


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class ThirdPartyLicenseTests(FixtureCase):
    def test_notices_are_mechanical_complete_and_cover_required_inputs(self):
        notice = RELEASE.generate_third_party_licenses(
            self.fixture.build_root, self.fixture.repo
        )
        for dependency in (
            "MicroPython",
            "ESP-IDF",
            "esp_system",
            "NeoPixel",
        ):
            self.assertIn(dependency, notice)
        for field in (
            "Name:",
            "Version/ref:",
            "Source URL:",
            "SPDX identifier:",
            "Copyright:",
            "Required notice:",
            "Complete license text:",
        ):
            self.assertIn(field, notice)
        self.assertIn("MIT License", notice)
        self.assertIn("Apache License", notice)

    def test_missing_license_or_unrecognized_incompatible_spdx_fails(self):
        component = (
            self.fixture.repo / "firmware" / ".esp-idf" / "components" / "esp_system"
        )
        source = component / "fixture.c"
        component_license = component / "LICENSE"
        idf_license = self.fixture.repo / "firmware" / ".esp-idf" / "LICENSE"

        component_license.unlink()
        idf_license.unlink()
        with self.assertRaises(RELEASE.ReleaseError):
            RELEASE.generate_third_party_licenses(
                self.fixture.build_root, self.fixture.repo
            )

        idf_license.write_text("Apache License Version 2.0", encoding="utf-8")
        source.write_text(
            "// SPDX-License-Identifier: GPL-3.0-only\n" "// Copyright Fixture\n",
            encoding="utf-8",
        )
        with self.assertRaises(RELEASE.ReleaseError):
            RELEASE.generate_third_party_licenses(
                self.fixture.build_root, self.fixture.repo
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
