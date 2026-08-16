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
#         waveshare_lcd147b_qualification_result: Path,
#         esp32_c3_qualification_result: Path,
#         rpi_pico2_w_qualification_result: Path,
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

import asyncio
import contextlib
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
V060_LICENSE_TEST_PATH = Path(__file__).with_name(
    "test_release_v060_license_inventory.py"
)
COMBINED_TEST_PATH = Path(__file__).with_name(
    "test_waveshare_boot_splash_bench.py"
)
WAVESHARE_PROFILE_ID = "waveshare-esp32-s3-lcd-147b"
C3_PROFILE_ID = "esp32-c3-4mb"
PICO_PROFILE_ID = "rpi-pico2-w"
RELEASE_PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
    WAVESHARE_PROFILE_ID,
    C3_PROFILE_ID,
    PICO_PROFILE_ID,
)
PROMOTION_ENVELOPE = {"HIL_REPORT.md", "release.json", "SHA256SUMS"}
HIL_MARKER = re.compile(
    r"<!--\s*PYBLE_HIL_RECORDS_V([245])\s*(\{.*?\})\s*-->",
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
    V060_LICENSE_TEST = load_module(
        "pyble_release_finalization_v060_license_fixture",
        V060_LICENSE_TEST_PATH,
    )
    COMBINED_TEST = load_module(
        "pyble_release_finalization_combined_fixture",
        COMBINED_TEST_PATH,
    )
    RELEASE = BUNDLE_TEST.RELEASE
    LOAD_ERROR = BUNDLE_TEST.RELEASE_LOAD_ERROR
except Exception as exc:  # pragma: no cover - rendered by the seam tests.
    BUNDLE_TEST = None
    LICENSE_TEST = None
    V060_LICENSE_TEST = None
    COMBINED_TEST = None
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


def canonical_json_bytes(value) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def read_hil_payload(path: Path) -> dict:
    match = HIL_MARKER.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise AssertionError("fixture HIL report lacks its embedded records")
    payload = json.loads(match.group(2))
    if payload.get("schema_version") != int(match.group(1)):
        raise AssertionError("fixture HIL marker/schema version disagrees")
    return payload


def write_hil_report(path: Path, payload: dict) -> None:
    schema_version = payload["schema_version"]
    path.write_text(
        RELEASE.HIL_REPORT_SHELL_PREFIX
        + "<!-- PYBLE_HIL_RECORDS_V%d\n" % schema_version
        + json.dumps(payload, indent=2, sort_keys=False)
        + "\n-->"
        + RELEASE.HIL_REPORT_SHELL_SUFFIX,
        encoding="utf-8",
    )


def transfer_link_facts(profile_id: str) -> dict:
    """Return the exact v0.6 transport evidence for one release profile."""
    if profile_id == PICO_PROFILE_ID:
        return {
            "ble_host": "btstack",
            "observed_att_mtu": 247,
            "observed_window": 4,
            "observed_chunk_bytes": 229,
            "console_tx_budget_ms": 103,
        }
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
        WAVESHARE_PROFILE_ID,
        C3_PROFILE_ID,
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
        raise AssertionError("unsupported finalization fixture profile")
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


def qualification_observation(profile_id: str) -> dict:
    """Build one valid source-era observation without hardware or private data."""

    observation = BUNDLE_TEST.fixture_oi1_observation()
    observation["transfer_link_facts"] = transfer_link_facts(profile_id)
    if profile_id == PICO_PROFILE_ID:
        observation["observed_window"] = 4
        for key in (
            "heap_post_hello",
            "heap_post_roundtrip",
        ):
            observation[key] = [
                {
                    "gc_free_bytes": sample["gc_free_bytes"],
                    "gc_allocated_bytes": sample["gc_allocated_bytes"],
                }
                for sample in observation[key]
            ]
        observation["heap_post_reliability"] = {
            "gc_free_bytes": observation["heap_post_reliability"][
                "gc_free_bytes"
            ],
            "gc_allocated_bytes": observation["heap_post_reliability"][
                "gc_allocated_bytes"
            ],
        }
    return observation


def qualification_build(build_root: Path, profile_id: str) -> dict:
    if profile_id == PICO_PROFILE_ID:
        firmware_bytes = (
            Path(build_root) / PICO_PROFILE_ID / "firmware.bin"
        ).stat().st_size
        image_limit = RELEASE.PROFILE_SPECS[PICO_PROFILE_ID][
            "image_limit_bytes"
        ]
        return {
            "firmware_bin_bytes": firmware_bytes,
            "firmware_image_limit_bytes": image_limit,
            "firmware_image_headroom_bytes": image_limit - firmware_bytes,
        }
    return BUNDLE_TEST.fixture_oi1_build(build_root, profile_id)


def install_v060_qualification_policy(repo: Path, build_root: Path) -> Path:
    """Install a canonical five-profile baseline/policy for this fixture."""

    source_commit = "1" * 40
    baseline_profiles = []
    policy_profiles = []
    for profile_id in RELEASE_PROFILE_ORDER:
        spec = RELEASE.PROFILE_SPECS[profile_id]
        is_rp2 = profile_id == PICO_PROFILE_ID
        build = qualification_build(build_root, profile_id)
        observation = qualification_observation(profile_id)
        thresholds = RELEASE._derived_qualification_thresholds(
            build,
            observation,
            firmware_version="0.6.0",
        )
        profile = {
            "profile_id": profile_id,
            "target": spec["target"],
            "resource_kind": "rp2" if is_rp2 else "esp-idf",
            "board_manufacturer": "Fixture Boards",
            "board_model": "Fixture %s" % profile_id,
            "module_marking": profile_id,
            "device_flash_capacity_bytes": spec["flash_size_bytes"],
            "device_psram_capacity_bytes": spec["psram"]["size_bytes"],
            "install_sha256": sha256_path(
                Path(build_root)
                / spec["target"]
                / ("firmware.uf2" if is_rp2 else "firmware.bin")
            ),
            "environment": {
                "desktop_os": "FixtureOS 1",
                "ble_backend": "Fixture BLE 1",
                "ble_adapter": "Fixture Adapter 1",
                "python_version": "3.13.5",
            },
            "oi1_build": build,
            "oi1_observation": observation,
        }
        if is_rp2:
            profile["resource_image_sha256"] = sha256_path(
                Path(build_root) / spec["target"] / "firmware.bin"
            )
        else:
            manifest = (
                json.dumps(
                    RELEASE._manifest("0.6.0", profile_id),
                    indent=2,
                    sort_keys=False,
                )
                + "\n"
            ).encode("utf-8")
            profile["manifest_sha256"] = hashlib.sha256(manifest).hexdigest()
        baseline_profiles.append(profile)
        policy_profiles.append(
            {
                "profile_id": profile_id,
                "target": spec["target"],
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
                "thresholds": thresholds,
            }
        )

    baseline = {
        "schema_version": 2,
        "measurement_contract": "oi1-five-profile-v1",
        "source_commit": source_commit,
        "firmware_version": "0.6.0",
        "created_at": "2026-08-12T08:00:00Z",
        "profile_order": list(RELEASE_PROFILE_ORDER),
        "profiles": baseline_profiles,
    }
    baseline_bytes = canonical_json_bytes(baseline)
    baseline_relative = "docs/validation/firmware/oi1/%s.json" % source_commit
    baseline_path = Path(repo) / baseline_relative
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_bytes(baseline_bytes)

    policy = {
        "schema_version": 3,
        "qualification_scope": "v0.6.0-five-profile",
        "profile_order": list(RELEASE_PROFILE_ORDER),
        "workload": {
            key: copy.deepcopy(value)
            for key, value in RELEASE.QUALIFICATION_WORKLOAD.items()
            if key != "required_put_window"
        },
        "derivation": copy.deepcopy(RELEASE.QUALIFICATION_DERIVATION_V3),
        "baseline_evidence": {
            "path": baseline_relative,
            "sha256": hashlib.sha256(baseline_bytes).hexdigest(),
        },
        "profiles": policy_profiles,
    }
    policy_path = Path(repo) / RELEASE.QUALIFICATION_POLICY_RELATIVE
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_bytes(canonical_json_bytes(policy))
    RELEASE._validate_qualification_policy(
        policy,
        repo_root=Path(repo),
        firmware_version="0.6.0",
    )
    return policy_path


def rp2350_uf2(raw_image: bytes) -> bytes:
    """Encode a tiny RP2350 Arm image with the required ignore block."""

    def block(
        *,
        flags: int,
        address: int,
        payload: bytes,
        number: int,
        total: int,
        family: int,
        extension: int | None = None,
    ) -> bytes:
        result = bytearray(512)
        struct.pack_into(
            "<IIIIIIII",
            result,
            0,
            0x0A324655,
            0x9E5D5157,
            flags,
            address,
            len(payload),
            number,
            total,
            family,
        )
        result[32 : 32 + len(payload)] = payload
        if extension is not None:
            struct.pack_into("<I", result, 32 + len(payload), extension)
        struct.pack_into("<I", result, 508, 0x0AB16F30)
        return bytes(result)

    chunks = [
        raw_image[offset : offset + 256].ljust(256, b"\0")
        for offset in range(0, len(raw_image), 256)
    ]
    extension = block(
        flags=0x0000A000,
        address=0x10FFFF00,
        payload=b"\xef" * 256,
        number=0,
        total=2,
        family=0xE48BFF57,
        extension=0x9957E304,
    )
    return extension + b"".join(
        block(
            flags=0x00002000,
            address=0x10000000 + index * 256,
            payload=payload,
            number=index,
            total=len(chunks),
            family=0xE48BFF59,
        )
        for index, payload in enumerate(chunks)
    )


def v060_profile_gates(profile_id: str) -> dict[str, str] | None:
    if profile_id == C3_PROFILE_ID:
        return {"C3-G%d" % index: "passed" for index in range(7)}
    if profile_id == PICO_PROFILE_ID:
        return {"GP%d" % index: "passed" for index in range(3)}
    return None


def write_v060_private_result(
    path: Path,
    *,
    profile_id: str,
    artifact: Path,
    candidate_release_sha256: str,
) -> Path:
    digest_key = (
        "candidate_uf2_sha256"
        if profile_id == PICO_PROFILE_ID
        else "candidate_firmware_sha256"
    )
    value = {
        "schema_version": 1,
        "status": "passed",
        "profile_id": profile_id,
        "firmware_version": "0.6.0",
        "candidate_release_json_sha256": candidate_release_sha256,
        digest_key: sha256_path(artifact),
        "gates": v060_profile_gates(profile_id),
    }
    path.write_bytes(canonical_json_bytes(value))
    path.chmod(0o600)
    return path


async def combined_result_for_firmware(firmware: Path) -> dict:
    """Generate private finalization evidence through the real HIL runner."""

    payload = firmware.read_bytes()
    size_bytes = len(payload)
    spans = [
        {"offset": 0, "size_bytes": 0x9000},
        {"offset": 0x10000, "size_bytes": size_bytes - 0x10000},
    ]
    immutable = b"".join(
        payload[item["offset"] : item["offset"] + item["size_bytes"]]
        for item in spans
    )
    attestation = {
        "sha256": hashlib.sha256(immutable).hexdigest(),
        "size_bytes": len(immutable),
        "spans": spans,
    }
    connections = [
        COMBINED_TEST.CombinedFakeCentral(
            "candidate/setup-disabled",
            live_candidate_sha256=attestation["sha256"],
        ),
        COMBINED_TEST.CombinedFakeCentral("setup-disabled/setup-enabled"),
        COMBINED_TEST.CombinedFakeCentral(
            "setup-enabled/exercise/cycle-1-arm"
        ),
        COMBINED_TEST.CombinedFakeCentral(
            "cycle-1/final-disable/cycle-2-arm"
        ),
        COMBINED_TEST.CombinedFakeCentral("cycle-2/cycle-3-arm"),
        COMBINED_TEST.CombinedFakeCentral("cycle-3/final-proof"),
    ]
    connector = COMBINED_TEST.CombinedFakeConnector(connections)

    async def confirm_splash(_phase, _pattern, qr_url):
        return qr_url

    async def confirm_tft(_pattern):
        connector.last.visual_confirmed = True
        return True

    return await COMBINED_TEST.bench.run_combined_qualification(
        connector,
        "private-input-only",
        COMBINED_TEST.preflight(),
        hashlib.sha256(payload).hexdigest(),
        size_bytes,
        attestation,
        timeout_s=2.0,
        poll_interval_s=0,
        production_app_probe=COMBINED_TEST.production_app_evidence,
        confirm_splash=confirm_splash,
        confirm_tft=confirm_tft,
        session_id="34" * 16,
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
        if "manifest" in profile:
            refresh(profile["manifest"])
        refresh(profile["install"])
        for component in profile.get("components", []):
            refresh(component)
        if "resource_image" in profile:
            refresh(profile["resource_image"])
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
        self.release_fixture = BUNDLE_TEST.ReleaseFixture(
            firmware_version="0.6.0"
        )
        self.license_fixture = V060_LICENSE_TEST.V060LicenseFixture()
        # Preserve the attribute names used by the finalization assertions.
        self.license_fixture.build_root = self.license_fixture.build
        self.license_fixture.micropython_commit = "2" * 40
        self.license_fixture.esp_idf_commit = "3" * 40
        self._add_release_inputs_to_audited_build()
        self.notice_path = self.license_fixture.root / "audited-notice.txt"
        self.notice_path.write_text(
            self.license_fixture.notice,
            encoding="utf-8",
        )

        self.candidate = self.license_fixture.root / "candidate"
        with self.license_replay():
            RELEASE.create_bundle(
                build_root=self.license_fixture.build_root,
                reproducibility_build_root=self.reproducibility_build_root,
                output_dir=self.candidate,
                repo_root=self.license_fixture.repo,
                installer_version="10.4.0",
                built_at="2026-08-12T12:00:00Z",
                provenance=self.provenance(),
                audited_notice=self.notice_path,
                license_evidence_dir=self.license_fixture.evidence,
                license_build_root=self.license_fixture.build_root,
                public=False,
            )
        exact_bundle = self.candidate / WAVESHARE_PROFILE_ID
        for required in ("firmware.bin", "manifest.json"):
            if not (exact_bundle / required).is_file():
                raise AssertionError(
                    "exact Waveshare candidate lacks %s" % required
                )
        self.candidate_release_sha256 = sha256_path(self.candidate / "release.json")
        gate_source = (
            REPO_ROOT
            / "firmware"
            / "qualification"
            / "waveshare_lcd147b_release_gate.py"
        )
        audited_gate = (
            self.license_fixture.repo
            / "firmware"
            / "qualification"
            / gate_source.name
        )
        audited_gate.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(gate_source, audited_gate)
        self.qualification_result = (
            self.license_fixture.root / "waveshare-lcd147b-result.json"
        )
        qualification = asyncio.run(
            combined_result_for_firmware(
                self.candidate
                / WAVESHARE_PROFILE_ID
                / "firmware.bin"
            )
        )
        if qualification.get("profile_id") != WAVESHARE_PROFILE_ID:
            raise AssertionError(
                "LCD qualification used a non-Waveshare release identity"
            )
        self.qualification_result.write_bytes(
            RELEASE._WAVESHARE_LCD147B_GATE.canonical_json_bytes(qualification)
        )
        self.qualification_result.chmod(0o600)
        self.c3_qualification_result = write_v060_private_result(
            self.license_fixture.root / "esp32-c3-result.json",
            profile_id=C3_PROFILE_ID,
            artifact=self.candidate / C3_PROFILE_ID / "firmware.bin",
            candidate_release_sha256=self.candidate_release_sha256,
        )
        self.pico_qualification_result = write_v060_private_result(
            self.license_fixture.root / "rpi-pico2-w-result.json",
            profile_id=PICO_PROFILE_ID,
            artifact=self.candidate / PICO_PROFILE_ID / "firmware.uf2",
            candidate_release_sha256=self.candidate_release_sha256,
        )
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
            "project_description.json",
            "libesp_system.a",
        )
        for target in BUNDLE_TEST.TARGET_TO_PROFILE:
            for relative in release_inputs:
                source = self.release_fixture.build_root / target / relative
                destination = self.license_fixture.build_root / target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        pico_build = self.license_fixture.build_root / PICO_PROFILE_ID
        pico_raw = b"RP2\n"
        (pico_build / "firmware.bin").write_bytes(pico_raw)
        (pico_build / "firmware.uf2").write_bytes(rp2350_uf2(pico_raw))
        install_v060_qualification_policy(
            self.license_fixture.repo,
            self.license_fixture.build_root,
        )
        gate_source = (
            REPO_ROOT
            / "firmware"
            / "qualification"
            / "waveshare_lcd147b_release_gate.py"
        )
        audited_gate = (
            audited_firmware / "qualification" / gate_source.name
        )
        audited_gate.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(gate_source, audited_gate)
        self.reproducibility_build_root = (
            self.license_fixture.root / "build-reproducibility"
        )
        shutil.copytree(
            self.license_fixture.build_root,
            self.reproducibility_build_root,
        )

    def license_replay(self):
        stack = contextlib.ExitStack()
        stack.enter_context(
            mock.patch.object(
                RELEASE,
                "_audit_load_tool_lock",
                return_value=self.license_fixture.tool_lock,
            )
        )
        stack.enter_context(
            mock.patch.object(
                RELEASE,
                "_audit_observe_rp2_license_inputs",
                return_value=copy.deepcopy(
                    self.license_fixture.rp2_observation
                ),
            )
        )
        stack.enter_context(
            mock.patch.object(
                RELEASE,
                "_audit_verify_v060_esp_semantic_replay",
                return_value=None,
            )
        )
        return stack

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
        completed = copy.deepcopy(pending)
        completed["candidate_release_json_sha256"] = (
            self.candidate_release_sha256
        )
        checks = {
            name: "passed"
            for name in (
                "provisioning_install",
                "provisioning_recovery",
                "advertising_info_hello",
                "pble_workflow",
                "safe_boot_reconnect",
                "filesystem_resume_reliability",
                "footprint_reliability",
            )
        }
        app_hil = {
            "ipad": {
                "app_version": "0.6.0",
                "app_build": "60",
                "os_major": "18",
                "status": "passed",
            },
            "android": {
                "app_version": "0.6.0",
                "app_build": "60",
                "os_major": "12",
                "status": "passed",
            },
        }
        for record in completed["records"]:
            profile_id = record["profile_id"]
            spec = RELEASE.PROFILE_SPECS[profile_id]
            record.update(
                {
                    "status": "passed",
                    "board_manufacturer": "Fixture Boards",
                    "board_model": "Fixture %s" % profile_id,
                    "module_marking": profile_id,
                    "device_flash_capacity_bytes": spec[
                        "flash_size_bytes"
                    ],
                    "device_psram_capacity_bytes": spec["psram"][
                        "size_bytes"
                    ],
                    "tested_at": "2026-08-12T14:00:00Z",
                    "operator": "Fixture Operator",
                    "maintainer_signoff": "Fixture Maintainer",
                    "desktop_os": "FixtureOS 1",
                    "chromium_version": "Chrome 140.0.0.0",
                    "ble_backend": "Fixture BLE 1",
                    "ble_adapter": "Fixture Adapter 1",
                    "python_version": "3.13.5",
                    "checks": copy.deepcopy(checks),
                    "app_hil": copy.deepcopy(app_hil),
                    "profile_gate_summary": v060_profile_gates(profile_id),
                    "oi1_observation": qualification_observation(profile_id),
                    "redacted_console_log": (
                        "fixture: secrets and device labels removed"
                    ),
                }
            )
        return completed

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
        with self.license_replay():
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
                waveshare_lcd147b_qualification_result=self.qualification_result,
                esp32_c3_qualification_result=self.c3_qualification_result,
                rpi_pico2_w_qualification_result=(
                    self.pico_qualification_result
                ),
                )
            )

    def validate_public(self, bundle: Path):
        with self.license_replay():
            return RELEASE.validate_bundle(
                bundle,
                public=True,
                license_evidence_dir=self.license_fixture.evidence,
                license_build_root=self.license_fixture.build_root,
                repo_root=self.license_fixture.repo,
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
                "waveshare_lcd147b_qualification_result",
                "esp32_c3_qualification_result",
                "rpi_pico2_w_qualification_result",
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

    def completed_hil_with_link_facts(self) -> dict:
        payload = self.fixture.completed_hil_payload()
        self.assertEqual(payload["schema_version"], 5)
        for record in payload["records"]:
            record["oi1_observation"]["transfer_link_facts"] = (
                transfer_link_facts(record["profile_id"])
            )
        return payload

    def test_v5_finalization_accepts_exact_transfer_link_facts(self):
        valid = self.completed_hil_with_link_facts()
        valid_report = self.fixture.write_completed_hil(
            self.fixture.license_fixture.root / "link-facts-valid-HIL.md",
            valid,
        )
        output = self.fixture.license_fixture.root / "link-facts-valid-output"
        self.assertEqual(
            self.fixture.finalize(output, completed_hil_report=valid_report),
            output,
        )

    def test_v5_accepts_nonzero_request_returns_when_final_update_settles(self):
        valid = self.completed_hil_with_link_facts()
        for record in valid["records"]:
            if record["profile_id"] == PICO_PROFILE_ID:
                continue
            record["oi1_observation"]["transfer_link_facts"][
                "connection_parameters"
            ]["request_return_codes"] = [530, 531]
        valid_report = self.fixture.write_completed_hil(
            self.fixture.license_fixture.root / "link-facts-nonzero-returns-HIL.md",
            valid,
        )
        output = self.fixture.license_fixture.root / "link-facts-nonzero-returns-output"
        self.assertEqual(
            self.fixture.finalize(output, completed_hil_report=valid_report),
            output,
        )

    def test_v5_finalization_rejects_missing_transfer_link_facts(self):
        missing = self.fixture.completed_hil_payload()
        for record in missing["records"]:
            record["oi1_observation"].pop("transfer_link_facts")
        missing_report = self.fixture.write_completed_hil(
            self.fixture.license_fixture.root / "link-facts-missing-HIL.md",
            missing,
        )
        self.assert_rejected_without_output(
            self.fixture.license_fixture.root / "link-facts-missing-output",
            completed_hil_report=missing_report,
        )

    def test_v5_finalization_rejects_nested_extra_profile_bool_and_bounds(self):
        def wrong_profile(record):
            other = (
                WAVESHARE_PROFILE_ID
                if record["profile_id"] == "esp32-4mb"
                else "esp32-4mb"
            )
            record["oi1_observation"]["transfer_link_facts"]["phy"] = (
                transfer_link_facts(other)["phy"]
            )

        mutations = {
            "extra": lambda record: record["oi1_observation"][
                "transfer_link_facts"
            ]["dle"].__setitem__("identifier", "private"),
            "missing-nested": lambda record: record["oi1_observation"][
                "transfer_link_facts"
            ]["dle"].pop("max_tx_time_us"),
            "wrong-profile": wrong_profile,
            "bool": lambda record: record["oi1_observation"][
                "transfer_link_facts"
            ]["dle"].__setitem__("request_attempts", True),
            "dle-bound": lambda record: record["oi1_observation"][
                "transfer_link_facts"
            ]["dle"].__setitem__("max_tx_octets", 243),
            "interval-bound": lambda record: (
                record["oi1_observation"]["transfer_link_facts"][
                    "connection_parameters"
                ]["updates"][-1].__setitem__("interval_units", 25),
                record["oi1_observation"]["transfer_link_facts"][
                    "connection_parameters"
                ].__setitem__("settled_interval_units", 25),
            ),
            "starve-bool": lambda record: record["oi1_observation"][
                "transfer_link_facts"
            ].__setitem__("tx_mbuf_starve_count", False),
            "starve-negative": lambda record: record["oi1_observation"][
                "transfer_link_facts"
            ].__setitem__("tx_mbuf_starve_count", -1),
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                payload = self.completed_hil_with_link_facts()
                mutate(payload["records"][0])
                report = self.fixture.write_completed_hil(
                    self.fixture.license_fixture.root
                    / ("link-facts-%s-HIL.md" % name),
                    payload,
                )
                self.assert_rejected_without_output(
                    self.fixture.license_fixture.root
                    / ("link-facts-%s-output" % name),
                    completed_hil_report=report,
                )

    def test_happy_path_is_exact_copy_on_write_and_public_valid(self):
        candidate_before = tree_bytes(self.fixture.candidate)
        candidate_release = read_json(self.fixture.candidate / "release.json")
        self.assertEqual(candidate_release["schema_version"], 4)
        self.assertEqual(
            [profile["id"] for profile in candidate_release["profiles"]],
            list(RELEASE_PROFILE_ORDER),
        )
        self.assertIn("esp32-c3-4mb/firmware.bin", candidate_before)
        self.assertIn("rpi-pico2-w/firmware.uf2", candidate_before)
        pending_payload = read_hil_payload(self.fixture.candidate / "HIL_REPORT.md")
        self.assertEqual(pending_payload["schema_version"], 5)
        self.assertTrue(
            all(
                pending_payload[name] is None
                for name in (
                    "waveshare_lcd147b_qualification",
                    "esp32_c3_qualification",
                    "rpi_pico2_w_qualification",
                )
            )
        )
        self.assertEqual(pending_payload["candidate_release_json_sha256"], "")
        self.assertEqual(
            [record["profile_id"] for record in pending_payload["records"]],
            list(RELEASE_PROFILE_ORDER),
        )
        self.assertEqual(
            pending_payload["qualification_policy"]["profile_order"],
            list(RELEASE_PROFILE_ORDER),
        )
        self.assertNotIn(
            "deferred_profiles",
            pending_payload["qualification_policy"],
        )
        self.assertTrue(
            all(
                record["oi1_observation"] is None
                for record in pending_payload["records"]
            )
        )

        output = self.fixture.license_fixture.root / "public-v0.6.0"
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
                "target",
                "resource_kind",
                "provisioning_kind",
                "firmware_version",
                "tag",
                "source_commit",
                "install_sha256",
                "oi1_policy",
                "oi1_build",
            ):
                self.assertEqual(
                    public_record[immutable],
                    pending_record[immutable],
                )
            if "manifest_sha256" in pending_record:
                self.assertEqual(
                    public_record["manifest_sha256"],
                    pending_record["manifest_sha256"],
                )
        self.assertIsNotNone(self.fixture.validate_public(finalized))

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
            "exact-floors": None,
            "put-floor-minus-one": "put",
            "get-floor-minus-one": "get",
        }
        metrics = {
            "put": (
                "put_committed_goodput_min_bytes_per_second",
                "put_unique_committed_bytes",
                "put_duration_ns",
                "put_committed_goodput_bytes_per_second",
            ),
            "get": (
                "get_verified_goodput_min_bytes_per_second",
                "get_unique_verified_bytes",
                "get_duration_ns",
                "get_verified_goodput_bytes_per_second",
            ),
        }
        for name, rejected_prefix in cases.items():
            with self.subTest(case=name):
                payload = self.fixture.completed_hil_payload()
                record = payload["records"][0]
                thresholds = record["oi1_policy"]["thresholds"]
                observation = record["oi1_observation"]
                for prefix, keys in metrics.items():
                    threshold_key, bytes_key, duration_key, measured_key = keys
                    floor = thresholds[threshold_key]
                    goodput = floor - int(prefix == rejected_prefix)
                    payload_bytes = observation[bytes_key][0]
                    duration_ns = (
                        payload_bytes * 1_000_000_000
                    ) // goodput
                    self.assertEqual(
                        (payload_bytes * 1_000_000_000) // duration_ns,
                        goodput,
                    )
                    observation[duration_key][0] = duration_ns
                    observation[measured_key][0] = goodput
                report = self.fixture.write_completed_hil(
                    self.fixture.license_fixture.root / ("%s-HIL.md" % name),
                    payload,
                )
                output = self.fixture.license_fixture.root / (
                    "%s-output" % name
                )
                if rejected_prefix is None:
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
