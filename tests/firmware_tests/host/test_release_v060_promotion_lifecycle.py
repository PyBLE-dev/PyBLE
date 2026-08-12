#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for the five-target v0.6.0 promotion lifecycle.

The fixture is hermetic: it models target-bound completion fragments and
release documents without building, flashing, publishing, or using hardware.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

import test_release_bundle as bundle_fixture
import test_release_v060_lifecycle as lifecycle_fixture


RELEASE = bundle_fixture.RELEASE
RELEASE_LOAD_ERROR = bundle_fixture.RELEASE_LOAD_ERROR
HAVE_RELEASE = RELEASE is not None
V042_PROFILES = lifecycle_fixture.V042_PROFILE_ORDER
V051_PROFILES = lifecycle_fixture.V05_PROFILE_ORDER
V060_PROFILES = lifecycle_fixture.V060_PROFILE_ORDER

V5_OPERATOR_CHECKS = (
    "provisioning_install",
    "provisioning_recovery",
    "advertising_info_hello",
    "pble_workflow",
    "safe_boot_reconnect",
    "filesystem_resume_reliability",
)
V5_ALL_CHECKS = (*V5_OPERATOR_CHECKS, "footprint_reliability")
V5_SUMMARIES = (
    "waveshare_lcd147b_qualification",
    "esp32_c3_qualification",
    "rpi_pico2_w_qualification",
)


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value))


def build_measurement(profile_id: str) -> dict[str, int]:
    if profile_id == "rpi-pico2-w":
        return {
            "firmware_bin_bytes": 100,
            "firmware_image_limit_bytes": 1_572_864,
            "firmware_image_headroom_bytes": 1_572_764,
        }
    return {
        "application_image_bytes": 100,
        "factory_partition_bytes": 200,
        "application_headroom_bytes": 100,
    }


def pending_v5_payload() -> dict[str, object]:
    policy = lifecycle_fixture.schema3_policy()
    policy_by_id = {item["profile_id"]: item for item in policy["profiles"]}
    profiles = {
        profile["id"]: profile for profile in lifecycle_fixture.pending_profiles()
    }
    records = []
    for profile_id in V060_PROFILES:
        spec = RELEASE.PROFILE_SPECS[profile_id]
        is_rp2 = spec["port"] == "rp2"
        profile = profiles[profile_id]
        record = {
            "profile_id": profile_id,
            "target": spec["target"],
            "resource_kind": "rp2" if is_rp2 else "esp-idf",
            "provisioning_kind": (
                "verified-uf2-bootsel" if is_rp2 else "esp-web-serial"
            ),
            "status": "pending",
            "board_manufacturer": "",
            "board_model": "",
            "module_marking": "",
            "device_flash_capacity_bytes": 0,
            "device_psram_capacity_bytes": 0,
            "firmware_version": "0.6.0",
            "tag": "firmware-v0.6.0",
            "source_commit": "1" * 40,
            "install_sha256": profile["install"]["sha256"],
            "tested_at": "",
            "operator": "",
            "maintainer_signoff": "",
            "desktop_os": "",
            "chromium_version": "",
            "ble_backend": "",
            "ble_adapter": "",
            "python_version": "",
            "checks": {name: "pending" for name in V5_ALL_CHECKS},
            "app_hil": {"ipad": None, "android": None},
            "profile_gate_summary": None,
            "oi1_policy": copy.deepcopy(policy_by_id[profile_id]),
            "oi1_build": build_measurement(profile_id),
            "oi1_observation": None,
            "redacted_console_log": "",
        }
        if not is_rp2:
            record["manifest_sha256"] = profile["manifest"]["sha256"]
        records.append(record)
    return {
        "schema_version": 5,
        "candidate_release_json_sha256": "",
        "qualification_policy_sha256": "f" * 64,
        "qualification_policy": policy,
        "records": records,
        **{name: None for name in V5_SUMMARIES},
    }


def app_hil() -> dict[str, dict[str, str]]:
    return {
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


def profile_gates(profile_id: str) -> dict[str, str] | None:
    if profile_id == "esp32-c3-4mb":
        return {"C3-G%d" % index: "passed" for index in range(7)}
    if profile_id == "rpi-pico2-w":
        return {"GP%d" % index: "passed" for index in range(3)}
    return None


def completion_fragment(profile_id: str) -> dict[str, object]:
    spec = RELEASE.PROFILE_SPECS[profile_id]
    return {
        "profile_id": profile_id,
        "board_manufacturer": "PyBLE fixture manufacturer",
        "board_model": "PyBLE fixture %s" % profile_id,
        "module_marking": "fixture-marking-%s" % profile_id,
        "device_flash_capacity_bytes": spec["flash_size_bytes"],
        "device_psram_capacity_bytes": spec["psram"]["size_bytes"],
        "tested_at": "2026-08-12T08:00:00Z",
        "operator": "PyBLE release operator",
        "maintainer_signoff": "PyBLE release maintainer",
        "desktop_os": "macOS 15",
        "chromium_version": "Chromium 140",
        "ble_backend": "platform BLE fixture",
        "ble_adapter": "fixture adapter",
        "python_version": "MicroPython v1.27.0",
        "checks": {name: "passed" for name in V5_OPERATOR_CHECKS},
        "app_hil": app_hil(),
        "profile_gate_summary": profile_gates(profile_id),
        "oi1_observation": {"fixture": profile_id},
        "redacted_console_log": "PBLE/1 completion succeeded",
    }


def operator_input(profile_id: str) -> dict[str, object]:
    fragment = completion_fragment(profile_id)
    for key in (
        "profile_id",
        "profile_gate_summary",
        "oi1_observation",
    ):
        fragment.pop(key)
    return fragment


def completed_v5_payload() -> dict[str, object]:
    payload = copy.deepcopy(pending_v5_payload())
    payload["candidate_release_json_sha256"] = "e" * 64
    for record in payload["records"]:
        fragment = completion_fragment(record["profile_id"])
        record["status"] = "passed"
        for key, value in fragment.items():
            if key != "profile_id":
                record[key] = copy.deepcopy(value)
        record["checks"] = {name: "passed" for name in V5_ALL_CHECKS}
    return payload


def hil_report(payload: dict[str, object]) -> str:
    return (
        RELEASE.HIL_REPORT_SHELL_PREFIX
        + "<!-- PYBLE_HIL_RECORDS_V5\n"
        + json.dumps(payload, indent=2)
        + "\n-->"
        + RELEASE.HIL_REPORT_SHELL_SUFFIX
    )


def provenance() -> dict[str, object]:
    return {
        "pyble": {"commit": "1" * 40, "clean": True},
        "micropython": {"ref": "v1.27.0", "commit": "2" * 40},
        "esp_idf": {"ref": "v5.4.2", "commit": "3" * 40},
        "patch_count": 0,
        "runner": {"os": "fixture", "architecture": "arm64"},
        "tools": [{"name": "fixture", "version": "1.0.0"}],
    }


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class V5CompletionAndPromotionContractTests(unittest.TestCase):
    def test_completion_writer_derives_profile_and_gate_fields(self) -> None:
        pending = pending_v5_payload()
        release = {
            "identity": {"version": "0.6.0", "tag": "firmware-v0.6.0"},
            "provenance": {"pyble": {"commit": "1" * 40}},
            "profiles": lifecycle_fixture.pending_profiles(),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            candidate = root / "candidate"
            candidate.mkdir()
            (candidate / "release.json").write_bytes(b"{}\n")
            (candidate / "HIL_REPORT.md").write_text(
                hil_report(pending), encoding="utf-8"
            )
            profile_id = "esp32-c3-4mb"
            operator_path = root / "operator.json"
            observation_path = root / "observation.json"
            result_path = root / "private-result.json"
            output = root / "completion.json"
            write_json(operator_path, operator_input(profile_id))
            write_json(observation_path, {"fixture": profile_id})
            result_path.write_bytes(b"private\n")
            result_path.chmod(0o600)
            gates = profile_gates(profile_id)

            with mock.patch.object(
                RELEASE, "validate_bundle", return_value=release
            ), mock.patch.object(
                RELEASE,
                "_validate_qualification_observation",
                side_effect=lambda value, *_args, **_kwargs: value,
            ), mock.patch.object(
                RELEASE._V060_PROFILE_GATE,
                "private_result_snapshot",
                return_value=("fixture-private-snapshot",),
            ), mock.patch.object(
                RELEASE._V060_PROFILE_GATE,
                "validate_result_file",
                return_value={"gates": gates},
            ) as validate_private:
                created = RELEASE.create_hil_completion_fragment(
                    candidate_dir=candidate,
                    profile_id=profile_id,
                    operator_input_path=operator_path,
                    oi1_observation_path=observation_path,
                    output_path=output,
                    qualification_repo_root=root,
                    profile_qualification_result=result_path,
                )

            self.assertEqual(Path(created), output)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(output.read_bytes(), canonical_json_bytes(payload))
            self.assertEqual(payload, completion_fragment(profile_id))
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(output.stat().st_nlink, 1)
            self.assertEqual(
                validate_private.call_args.kwargs["artifact_path"],
                candidate / profile_id / "firmware.bin",
            )
            with self.assertRaises(RELEASE.ReleaseError):
                RELEASE.create_hil_completion_fragment(
                    candidate_dir=candidate,
                    profile_id=profile_id,
                    operator_input_path=operator_path,
                    oi1_observation_path=observation_path,
                    output_path=output,
                    qualification_repo_root=root,
                    profile_qualification_result=result_path,
                )
            self.assertEqual(payload, json.loads(output.read_text(encoding="utf-8")))

    def test_completion_writer_rejects_operator_gate_fields_or_wrong_private_phase(
        self,
    ) -> None:
        pending = pending_v5_payload()
        release = {
            "identity": {"version": "0.6.0", "tag": "firmware-v0.6.0"},
            "provenance": {"pyble": {"commit": "1" * 40}},
            "profiles": lifecycle_fixture.pending_profiles(),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            candidate = root / "candidate"
            candidate.mkdir()
            (candidate / "release.json").write_bytes(b"{}\n")
            (candidate / "HIL_REPORT.md").write_text(
                hil_report(pending), encoding="utf-8"
            )
            observation_path = root / "observation.json"
            write_json(observation_path, {"fixture": "esp32-4mb"})

            cases = {
                "operator-gates": ("esp32-4mb", None, "profile_gate_summary"),
                "operator-footprint": ("esp32-4mb", None, "footprint_reliability"),
                "private-for-ordinary": ("esp32-4mb", root / "private.json", None),
                "missing-private-for-c3": ("esp32-c3-4mb", None, None),
            }
            for name, (profile_id, result_path, forbidden_key) in cases.items():
                with self.subTest(name=name):
                    value = operator_input(profile_id)
                    if forbidden_key == "profile_gate_summary":
                        value[forbidden_key] = {}
                    elif forbidden_key == "footprint_reliability":
                        value["checks"][forbidden_key] = "passed"
                    operator_path = root / (name + "-operator.json")
                    write_json(operator_path, value)
                    output = root / (name + "-completion.json")
                    with mock.patch.object(
                        RELEASE, "validate_bundle", return_value=release
                    ), mock.patch.object(
                        RELEASE,
                        "_validate_qualification_observation",
                        side_effect=lambda value, *_args, **_kwargs: value,
                    ), self.assertRaises(RELEASE.ReleaseError):
                        RELEASE.create_hil_completion_fragment(
                            candidate_dir=candidate,
                            profile_id=profile_id,
                            operator_input_path=operator_path,
                            oi1_observation_path=observation_path,
                            output_path=output,
                            qualification_repo_root=root,
                            profile_qualification_result=result_path,
                        )
                    self.assertFalse(output.exists())

    def test_promotion_envelope_uses_v5_discriminated_immutable_fields(self) -> None:
        pending = pending_v5_payload()
        completed = completed_v5_payload()

        RELEASE._validate_hil_promotion_envelope(pending, completed)

        self.assertTrue(all(completed[name] is None for name in V5_SUMMARIES))
        self.assertNotIn("manifest_sha256", completed["records"][-1])
        self.assertNotIn("firmware_sha256", completed["records"][-1])

        for field in (
            "target",
            "resource_kind",
            "provisioning_kind",
            "install_sha256",
        ):
            with self.subTest(tampered_v5_field=field):
                tampered = completed_v5_payload()
                tampered["records"][-1][field] = "tampered"
                with self.assertRaises(RELEASE.ReleaseError):
                    RELEASE._validate_hil_promotion_envelope(pending, tampered)

    def test_assembler_accepts_five_target_bound_v5_fragments(self) -> None:
        pending = pending_v5_payload()
        release = {
            "identity": {"version": "0.6.0", "tag": "firmware-v0.6.0"},
            "provenance": {"pyble": {"commit": "1" * 40}},
            "profiles": lifecycle_fixture.pending_profiles(),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            candidate = root / "candidate"
            candidate.mkdir()
            (candidate / "release.json").write_bytes(b"{}\n")
            (candidate / "HIL_REPORT.md").write_text(
                hil_report(pending), encoding="utf-8"
            )
            fragments = []
            for profile_id in reversed(V060_PROFILES):
                path = root / (profile_id + "-completion.json")
                write_json(path, completion_fragment(profile_id))
                fragments.append(path)
            output = root / "completed-HIL_REPORT.md"

            with mock.patch.object(RELEASE, "validate_bundle", return_value=release), mock.patch.object(
                RELEASE,
                "_validate_qualification_observation",
                side_effect=lambda value, *_args, **_kwargs: value,
            ), mock.patch.object(RELEASE, "_validate_hil", return_value=None):
                result = RELEASE.assemble_completed_hil_report(
                    candidate_dir=candidate,
                    profile_evidence_paths=fragments,
                    output_path=output,
                    qualification_repo_root=root,
                )

            self.assertEqual(Path(result), output)
            completed = RELEASE._parse_hil_report(output.read_text(encoding="utf-8"))
            self.assertEqual(
                completed["candidate_release_json_sha256"],
                hashlib.sha256((candidate / "release.json").read_bytes()).hexdigest(),
            )
            self.assertEqual(
                [record["profile_id"] for record in completed["records"]],
                list(V060_PROFILES),
            )
            for record in completed["records"]:
                self.assertEqual(record["status"], "passed")
                self.assertEqual(
                    record["checks"],
                    {name: "passed" for name in V5_ALL_CHECKS},
                )
                self.assertEqual(record["app_hil"], app_hil())
                self.assertEqual(
                    record["profile_gate_summary"],
                    profile_gates(record["profile_id"]),
                )
            self.assertTrue(all(completed[name] is None for name in V5_SUMMARIES))


@unittest.skipUnless(HAVE_RELEASE, RELEASE_LOAD_ERROR)
class SourceEraReleaseDocumentContractTests(unittest.TestCase):
    def test_release_notes_and_recovery_select_exact_source_era_profiles(self) -> None:
        eras = (
            ("0.4.2", V042_PROFILES, V051_PROFILES[2:]),
            ("0.5.1", V051_PROFILES, V060_PROFILES[3:]),
            ("0.6.0", V060_PROFILES, ()),
        )
        for version, expected, forbidden in eras:
            with self.subTest(version=version):
                notes = RELEASE._release_notes(
                    version, "2026-08-12T08:00:00Z", provenance()
                )
                recovery = RELEASE._recovery_guide(version)
                for profile_id in expected:
                    self.assertIn(profile_id, notes)
                    self.assertIn(profile_id, recovery)
                for profile_id in forbidden:
                    self.assertNotIn(profile_id, notes)
                    self.assertNotIn(profile_id, recovery)
                self.assertEqual(
                    recovery.count("python -m esptool"),
                    len([item for item in expected if item != "rpi-pico2-w"]),
                )

    def test_v060_distinguishes_esp_web_serial_from_pico_uf2_recovery(self) -> None:
        notes = RELEASE._release_notes(
            "0.6.0", "2026-08-12T08:00:00Z", provenance()
        )
        recovery = RELEASE._recovery_guide("0.6.0")

        self.assertIn("Web Serial", notes)
        self.assertIn("UF2", notes)
        self.assertIn("BOOTSEL", notes)
        self.assertEqual(recovery.count("python -m esptool"), 4)
        self.assertIn(
            "python -m esptool --chip esp32c3 write_flash 0x0 "
            "esp32-c3-4mb/firmware.bin",
            recovery,
        )
        self.assertIn("rpi-pico2-w/firmware.uf2", recovery)
        self.assertIn("BOOTSEL", recovery)


if __name__ == "__main__":
    unittest.main(verbosity=2)
