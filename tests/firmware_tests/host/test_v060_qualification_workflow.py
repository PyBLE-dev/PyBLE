#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for the operator-safe v0.6.0 qualification workflow.

This host-only suite reads the committed policy and exercises parser/writer
boundaries with synthetic files.  It never builds, scans, flashes, publishes,
or records a hardware pass.  Numeric resource thresholds remain generated
evidence: the tests assert their shape and provenance, never choose values.
"""

from __future__ import annotations

from contextlib import redirect_stderr
import hashlib
import importlib.util
import inspect
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
POLICY_PATH = REPO_ROOT / "firmware" / "qualification" / "oi1-gates.json"
GATE_PATH = (
    REPO_ROOT
    / "firmware"
    / "qualification"
    / "v060_profile_release_gate.py"
)
RELEASE_PATH = REPO_ROOT / "firmware" / "scripts" / "release_bundle.py"
CONSOLE_PATH = REPO_ROOT / "firmware" / "pyble" / "pyble_console.py"
HIL_DIR = HERE.parent / "hil"

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
ESP_THRESHOLD_KEYS = {
    "application_image_max_bytes",
    "application_headroom_min_bytes",
    "gc_free_min_bytes",
    "idf_internal_free_min_bytes",
    "idf_internal_largest_block_min_bytes",
    "idf_internal_minimum_free_min_bytes",
    "reset_to_service_advertisement_max_ms",
    "put_committed_goodput_min_bytes_per_second",
    "get_verified_goodput_min_bytes_per_second",
}
RP2_THRESHOLD_KEYS = {
    "firmware_bin_max_bytes",
    "firmware_image_headroom_min_bytes",
    "gc_free_min_bytes",
    "reset_to_service_advertisement_max_ms",
    "put_committed_goodput_min_bytes_per_second",
    "get_verified_goodput_min_bytes_per_second",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE = load_module("pyble_v060_workflow_gate", GATE_PATH)
RELEASE = load_module("pyble_v060_workflow_release", RELEASE_PATH)
CONSOLE = load_module("pyble_v060_workflow_console", CONSOLE_PATH)
sys.path.insert(0, str(HIL_DIR))
import oi1_profile_bench as PROFILE_BENCH  # noqa: E402


def canonical_json_bytes(value: object) -> bytes:
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


def candidate_release(artifact: bytes) -> dict[str, object]:
    esp_specs = {
        "esp32-4mb": (
            "esp32",
            "ESP32",
            {"minimum_full": 0, "maximum_full": 399},
            4 * 1024 * 1024,
            {"required": False, "size_bytes": 0, "type": "not-required"},
            40_000_000,
            (0x1000, 0x1000, 0x8000, 0x10000),
        ),
        "esp32-s3-n16r8": (
            "esp32-s3",
            "ESP32-S3",
            {"minimum_full": 0, "maximum_full": 99},
            16 * 1024 * 1024,
            {"required": True, "size_bytes": 8 * 1024 * 1024, "type": "octal"},
            80_000_000,
            (0, 0, 0x8000, 0x10000),
        ),
        "waveshare-esp32-s3-lcd-147b": (
            "waveshare-esp32-s3-lcd-147b",
            "ESP32-S3",
            {"minimum_full": 0, "maximum_full": 99},
            16 * 1024 * 1024,
            {"required": True, "size_bytes": 8 * 1024 * 1024, "type": "octal"},
            80_000_000,
            (0, 0, 0x8000, 0x10000),
        ),
        "esp32-c3-4mb": (
            "esp32-c3",
            "ESP32-C3",
            {"minimum_full": 3, "maximum_full": 199},
            4 * 1024 * 1024,
            {"required": False, "size_bytes": 0, "type": "not-required"},
            80_000_000,
            (0, 0, 0x8000, 0x10000),
        ),
    }
    roles = (
        ("bootloader", "bootloader.bin"),
        ("partition-table", "partition-table.bin"),
        ("application", "application.bin"),
    )
    profiles: list[dict[str, object]] = []
    for profile_id in PROFILE_ORDER[:-1]:
        (
            target,
            family,
            revisions,
            flash_bytes,
            psram,
            frequency_hz,
            offsets,
        ) = esp_specs[profile_id]
        install_sha256 = (
            hashlib.sha256(artifact).hexdigest()
            if profile_id == "esp32-c3-4mb"
            else profile_id[0].encode().hex().ljust(64, "0")[:64]
        )
        profiles.append(
            {
                "id": profile_id,
                "target": target,
                "provisioning_kind": "esp-web-serial",
                "chip_family": family,
                "silicon_revision": revisions,
                "requirements": {
                    "flash_size_bytes": flash_bytes,
                    "psram": psram,
                },
                "flash": {"mode": "dio", "frequency_hz": frequency_hz},
                "hil_status": "pending",
                "manifest": {
                    "path": "%s/manifest.json" % profile_id,
                    "size": 1,
                    "sha256": "1" * 64,
                },
                "install": {
                    "path": "%s/firmware.bin" % profile_id,
                    "size": len(artifact) if profile_id == "esp32-c3-4mb" else 1,
                    "sha256": install_sha256,
                    "offset": offsets[0],
                },
                "components": [
                    {
                        "path": "%s/%s" % (profile_id, filename),
                        "size": 1,
                        "sha256": str(index + 2) * 64,
                        "role": role,
                        "offset": offset,
                    }
                    for index, ((role, filename), offset) in enumerate(
                        zip(roles, offsets[1:])
                    )
                ],
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
    return {
        "schema_version": 4,
        "identity": {
            "version": "0.6.0",
            "tag": "firmware-v0.6.0",
            "agent_version": "0.6.0",
            "protocol_version": "PBLE/1",
            "built_at": "2026-08-12T00:00:00Z",
        },
        "provenance": {
            "pyble": {"commit": "1" * 40, "clean": True},
            "micropython": {"ref": "v1.28.0", "commit": "2" * 40},
            "esp_idf": {"ref": "v5.5.1", "commit": "3" * 40},
            "patch_count": 0,
            "runner": {"os": "FixtureOS", "architecture": "fixture64"},
            "tools": [{"name": "python", "version": "3.13.5"}],
        },
        "installer": {"package": "esp-web-tools", "version": "10.4.0"},
        "profiles": profiles,
        "documents": {
            key: {"path": path, "size": 1, "sha256": "f" * 64}
            for key, path in {
                "third_party_licenses": "THIRD_PARTY_LICENSES.txt",
                "release_notes": "RELEASE_NOTES.md",
                "recovery": "RECOVERY.md",
                "hil_report": "HIL_REPORT.md",
            }.items()
        },
    }


class CommittedPolicyReadinessTests(unittest.TestCase):
    def test_committed_policy_is_generated_schema3_five_profile_evidence(self):
        raw = POLICY_PATH.read_bytes()
        policy = json.loads(raw.decode("utf-8", errors="strict"))

        self.assertEqual(
            policy.get("schema_version"),
            3,
            "historical schema-1 policy remains release-blocking until the "
            "five real baseline fragments generate schema 3",
        )
        if policy.get("schema_version") != 3:
            return

        self.assertEqual(
            set(policy),
            {
                "schema_version",
                "qualification_scope",
                "profile_order",
                "workload",
                "derivation",
                "baseline_evidence",
                "profiles",
            },
        )
        self.assertEqual(policy["qualification_scope"], "v0.6.0-five-profile")
        self.assertEqual(tuple(policy["profile_order"]), PROFILE_ORDER)
        self.assertEqual(
            [entry["profile_id"] for entry in policy["profiles"]],
            list(PROFILE_ORDER),
        )
        self.assertNotIn("deferred_profiles", policy)

        for profile_id, row in zip(PROFILE_ORDER, policy["profiles"]):
            with self.subTest(profile_id=profile_id):
                self.assertEqual(
                    set(row),
                    {
                        "profile_id",
                        "target",
                        "resource_kind",
                        "transport",
                        "thresholds",
                    },
                )
                self.assertEqual(row["target"], PROFILE_TARGETS[profile_id])
                is_rp2 = profile_id == "rpi-pico2-w"
                self.assertEqual(
                    row["resource_kind"], "rp2" if is_rp2 else "esp-idf"
                )
                self.assertEqual(
                    set(row["thresholds"]),
                    RP2_THRESHOLD_KEYS if is_rp2 else ESP_THRESHOLD_KEYS,
                )
                self.assertTrue(
                    all(
                        type(value) is int and value >= 0
                        for value in row["thresholds"].values()
                    )
                )

        evidence = policy["baseline_evidence"]
        self.assertEqual(set(evidence), {"path", "sha256"})
        evidence_path = REPO_ROOT / evidence["path"]
        self.assertTrue(evidence_path.is_file())
        self.assertEqual(
            hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            evidence["sha256"],
        )


class PicoPacingSourceBindingTests(unittest.TestCase):
    def test_pico_pacing_fact_is_the_exact_runtime_refill_horizon(self):
        capacity = getattr(CONSOLE, "TX_CAPACITY", None)
        refill_per_ms = getattr(CONSOLE, "TX_REFILL_PER_MS", None)
        runtime_budget = getattr(CONSOLE, "TX_BUDGET_MS", None)
        self.assertEqual(
            (capacity, refill_per_ms, runtime_budget),
            (2048, 20, 103),
            "Pico pacing must use the frozen byte capacity, byte/ms refill, "
            "and empty-to-full horizon; ESP's 250 ms wait is unrelated",
        )
        if not all(
            type(value) is int and value > 0
            for value in (capacity, refill_per_ms, runtime_budget)
        ):
            return
        self.assertEqual(
            runtime_budget,
            (capacity + refill_per_ms - 1) // refill_per_ms,
            "TX_BUDGET_MS must be the exact integer ceiling refill horizon",
        )
        self.assertEqual(
            (
                getattr(PROFILE_BENCH, "RP2_CONSOLE_TX_CAPACITY", None),
                getattr(PROFILE_BENCH, "RP2_CONSOLE_TX_REFILL_PER_MS", None),
                getattr(PROFILE_BENCH, "RP2_CONSOLE_TX_BUDGET_MS", None),
            ),
            (capacity, refill_per_ms, runtime_budget),
            "the bench must import all three exact runtime pacing constants",
        )

    def test_pico_cli_has_no_operator_selectable_pacing_value(self):
        argv = [
            "--mode",
            "baseline",
            "--profile",
            "rpi-pico2-w",
            "--expect-chip",
            "rpi-pico2-w",
            "--address",
            "private-test-address",
            "--raw-log",
            "raw.jsonl",
            "--output",
            "profile.json",
            "--operator-reset",
            "--firmware-bin",
            "firmware.bin",
            "--firmware-uf2",
            "firmware.uf2",
        ]
        with redirect_stderr(io.StringIO()):
            try:
                args = PROFILE_BENCH._parse_args(argv)
            except SystemExit as exc:
                self.fail(
                    "Pico bench still requires an operator-supplied pacing "
                    "number (parser exit %s)" % exc.code
                )
        self.assertFalse(
            hasattr(args, "console_tx_budget_ms"),
            "the parsed CLI namespace must not carry an operator pacing fact",
        )
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            PROFILE_BENCH._parse_args(
                argv + ["--console-tx-budget-ms", "1"]
            )


class PrivateGateResultWriterContractTests(unittest.TestCase):
    def test_candidate_bound_no_replace_writer_api_exists(self):
        writer = getattr(GATE, "create_result_file", None)
        self.assertTrue(
            callable(writer),
            "v0.6 private gates need a canonical candidate-bound writer",
        )
        if not callable(writer):
            return
        self.assertEqual(
            set(inspect.signature(writer).parameters),
            {"candidate_dir", "profile_id", "passed_gates", "output_path"},
        )

    def test_private_gate_cli_exposes_only_derived_identity_inputs(self):
        completed = subprocess.run(
            [sys.executable, str(GATE_PATH), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("create-result", completed.stdout)
        self.assertIn("--passed-gate", completed.stdout)
        for forbidden in (
            "--status",
            "--firmware-version",
            "--candidate-release-json-sha256",
            "--candidate-firmware-sha256",
            "--candidate-uf2-sha256",
        ):
            self.assertNotIn(forbidden, completed.stdout)

    def test_writer_derives_exact_bytes_and_refuses_missing_gates(self):
        writer = getattr(GATE, "create_result_file", None)
        if not callable(writer):
            self.skipTest("RED: private gate writer has not landed")
        with tempfile.TemporaryDirectory(prefix="pyble-v060-workflow-gate-") as tmp:
            root = Path(tmp).resolve()
            candidate = root / "candidate"
            (candidate / "esp32-c3-4mb").mkdir(parents=True)
            artifact = b"candidate C3 firmware\0"
            (candidate / "esp32-c3-4mb" / "firmware.bin").write_bytes(artifact)
            release_raw = canonical_json_bytes(candidate_release(artifact))
            (candidate / "release.json").write_bytes(release_raw)
            output = root / "private" / "c3-result.json"
            gates = ["C3-G%d" % index for index in range(7)]

            created = writer(
                candidate_dir=candidate,
                profile_id="esp32-c3-4mb",
                passed_gates=gates,
                output_path=output,
            )
            expected = {
                "schema_version": 1,
                "status": "passed",
                "profile_id": "esp32-c3-4mb",
                "firmware_version": "0.6.0",
                "candidate_release_json_sha256": hashlib.sha256(
                    release_raw
                ).hexdigest(),
                "candidate_firmware_sha256": hashlib.sha256(artifact).hexdigest(),
                "gates": {name: "passed" for name in gates},
            }
            self.assertEqual(Path(created), output)
            self.assertEqual(output.read_bytes(), canonical_json_bytes(expected))
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(output.stat().st_nlink, 1)

            with self.assertRaises(GATE.QualificationError):
                writer(
                    candidate_dir=candidate,
                    profile_id="esp32-c3-4mb",
                    passed_gates=gates,
                    output_path=output,
                )
            missing_output = root / "private" / "missing.json"
            with self.assertRaises(GATE.QualificationError):
                writer(
                    candidate_dir=candidate,
                    profile_id="esp32-c3-4mb",
                    passed_gates=gates[:-1],
                    output_path=missing_output,
                )
            self.assertFalse(missing_output.exists())

    def test_writer_rejects_minimal_or_substituted_candidate_metadata(self):
        writer = GATE.create_result_file
        gates = ["C3-G%d" % index for index in range(7)]
        with tempfile.TemporaryDirectory(prefix="pyble-v060-gate-metadata-") as tmp:
            root = Path(tmp).resolve()
            candidate = root / "candidate"
            artifact_path = candidate / "esp32-c3-4mb" / "firmware.bin"
            artifact_path.parent.mkdir(parents=True)
            artifact = b"candidate C3 firmware\0"
            artifact_path.write_bytes(artifact)
            release_path = candidate / "release.json"
            invalid = {
                "minimal-release": {"identity": {"version": "0.6.0"}},
                "wrong-profile-digest": candidate_release(artifact),
            }
            invalid["wrong-profile-digest"]["profiles"][3]["install"][
                "sha256"
            ] = "0" * 64
            for name, release in invalid.items():
                with self.subTest(name=name):
                    release_path.write_bytes(canonical_json_bytes(release))
                    output = root / (name + ".json")
                    with self.assertRaises(GATE.QualificationError):
                        writer(
                            candidate_dir=candidate,
                            profile_id="esp32-c3-4mb",
                            passed_gates=gates,
                            output_path=output,
                        )
                    self.assertFalse(output.exists())

    def test_low_level_writer_is_durable_and_cleans_every_injected_failure(self):
        payload = b'{"fixture":true}\n'
        with tempfile.TemporaryDirectory(prefix="pyble-v060-gate-write-") as tmp:
            root = Path(tmp).resolve()
            real_fstat = GATE.os.fstat
            failures = {
                "fchmod": mock.patch.object(
                    GATE.os, "fchmod", side_effect=OSError("fixture fchmod")
                ),
                "write": mock.patch.object(
                    GATE.os, "write", side_effect=OSError("fixture write")
                ),
                "fsync": mock.patch.object(
                    GATE.os, "fsync", side_effect=OSError("fixture fsync")
                ),
                "fstat": mock.patch.object(
                    GATE.os,
                    "fstat",
                    side_effect=lambda descriptor: (
                        (_ for _ in ()).throw(OSError("fixture fstat"))
                        if stat.S_ISREG(real_fstat(descriptor).st_mode)
                        else real_fstat(descriptor)
                    ),
                ),
            }
            for name, patcher in failures.items():
                with self.subTest(name=name):
                    output = root / name / "result.json"
                    with patcher, self.assertRaises(GATE.QualificationError):
                        GATE._write_exclusive_result(output, payload)
                    self.assertFalse(output.exists())

            sync_modes: list[int] = []
            real_fsync = GATE.os.fsync

            def record_fsync(descriptor):
                sync_modes.append(real_fstat(descriptor).st_mode)
                return real_fsync(descriptor)

            output = root / "durable" / "result.json"
            with mock.patch.object(GATE.os, "fsync", side_effect=record_fsync):
                GATE._write_exclusive_result(output, payload)
            self.assertEqual(output.read_bytes(), payload)
            self.assertTrue(any(stat.S_ISREG(mode) for mode in sync_modes))
            self.assertTrue(any(stat.S_ISDIR(mode) for mode in sync_modes))

    def test_writer_rejects_symlink_ancestor_without_touching_target(self):
        with tempfile.TemporaryDirectory(prefix="pyble-v060-gate-link-") as tmp:
            root = Path(tmp).resolve()
            real_parent = root / "real"
            real_parent.mkdir()
            link = root / "linked"
            link.symlink_to(real_parent, target_is_directory=True)
            output = link / "private" / "result.json"
            with self.assertRaises(GATE.QualificationError):
                GATE._write_exclusive_result(output, b"safe\n")
            self.assertFalse((real_parent / "private" / "result.json").exists())

    def test_writer_rolls_back_candidate_or_output_parent_toctou(self):
        payload = b'{"fixture":true}\n'
        with tempfile.TemporaryDirectory(prefix="pyble-v060-gate-race-") as tmp:
            root = Path(tmp).resolve()
            candidate_output = root / "candidate-race" / "result.json"

            def changed_candidate():
                raise GATE.QualificationError("fixture candidate changed")

            with self.assertRaises(GATE.QualificationError):
                GATE._write_exclusive_result(
                    candidate_output,
                    payload,
                    post_write_check=changed_candidate,
                )
            self.assertFalse(candidate_output.exists())

            parent_output = root / "parent-race" / "result.json"
            real_verify_parent = GATE._verify_output_parent
            calls = 0

            def changed_parent(chain):
                nonlocal calls
                calls += 1
                if calls >= 3:
                    raise GATE.QualificationError("fixture parent changed")
                return real_verify_parent(chain)

            with mock.patch.object(
                GATE, "_verify_output_parent", side_effect=changed_parent
            ), self.assertRaises(GATE.QualificationError):
                GATE._write_exclusive_result(parent_output, payload)
            self.assertFalse(parent_output.exists())

    def test_writer_rejects_lexical_symlink_dotdot_output(self):
        with tempfile.TemporaryDirectory(prefix="pyble-v060-gate-dotdot-") as tmp:
            root = Path(tmp).resolve()
            real = root / "real" / "inner"
            real.mkdir(parents=True)
            link = root / "linked"
            link.symlink_to(real, target_is_directory=True)

            output = link / ".." / "private" / "result.json"
            with self.assertRaises(GATE.QualificationError):
                GATE._write_exclusive_result(output, b"safe\n")
            self.assertFalse((root / "private" / "result.json").exists())
            self.assertFalse((root / "real" / "private" / "result.json").exists())

    def test_writer_rejects_lexical_symlink_dotdot_candidate(self):
        gates = ["C3-G%d" % index for index in range(7)]
        with tempfile.TemporaryDirectory(prefix="pyble-v060-gate-dotdot-") as tmp:
            root = Path(tmp).resolve()
            real = root / "real" / "inner"
            real.mkdir(parents=True)
            link = root / "linked"
            link.symlink_to(real, target_is_directory=True)
            candidate = root / "candidate"
            artifact_path = candidate / "esp32-c3-4mb" / "firmware.bin"
            artifact_path.parent.mkdir(parents=True)
            artifact = b"candidate C3 firmware\0"
            artifact_path.write_bytes(artifact)
            (candidate / "release.json").write_bytes(
                canonical_json_bytes(candidate_release(artifact))
            )
            lexical_candidate = link / ".." / "candidate"
            candidate_output = root / "candidate-dotdot-result.json"
            with self.assertRaises(GATE.QualificationError):
                GATE.create_result_file(
                    candidate_dir=lexical_candidate,
                    profile_id="esp32-c3-4mb",
                    passed_gates=gates,
                    output_path=candidate_output,
                )
            self.assertFalse(candidate_output.exists())

    def test_candidate_writer_rolls_back_post_write_validation_failure(self):
        gates = ["C3-G%d" % index for index in range(7)]
        with tempfile.TemporaryDirectory(prefix="pyble-v060-gate-validate-") as tmp:
            root = Path(tmp).resolve()
            candidate = root / "candidate"
            artifact_path = candidate / "esp32-c3-4mb" / "firmware.bin"
            artifact_path.parent.mkdir(parents=True)
            artifact = b"candidate C3 firmware\0"
            artifact_path.write_bytes(artifact)
            (candidate / "release.json").write_bytes(
                canonical_json_bytes(candidate_release(artifact))
            )
            output = root / "private" / "result.json"
            with mock.patch.object(
                GATE,
                "validate_result_file",
                side_effect=GATE.QualificationError("fixture validation failure"),
            ), self.assertRaises(GATE.QualificationError):
                GATE.create_result_file(
                    candidate_dir=candidate,
                    profile_id="esp32-c3-4mb",
                    passed_gates=gates,
                    output_path=output,
                )
            self.assertFalse(output.exists())


class HilCompletionWriterContractTests(unittest.TestCase):
    def test_candidate_bound_completion_writer_api_exists(self):
        writer = getattr(RELEASE, "create_hil_completion_fragment", None)
        self.assertTrue(
            callable(writer),
            "five V5 fragments need a writer that validates observations and "
            "derives C3/Pico gate maps",
        )
        if not callable(writer):
            return
        self.assertEqual(
            set(inspect.signature(writer).parameters),
            {
                "candidate_dir",
                "profile_id",
                "operator_input_path",
                "oi1_observation_path",
                "output_path",
                "qualification_repo_root",
                "profile_qualification_result",
            },
        )

    def test_release_cli_exposes_completion_writer_without_gate_map_argument(self):
        completed = subprocess.run(
            [sys.executable, str(RELEASE_PATH), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("create-hil-completion", completed.stdout)

        command_help = subprocess.run(
            [
                sys.executable,
                str(RELEASE_PATH),
                "create-hil-completion",
                "--help",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(command_help.returncode, 0, command_help.stderr)
        self.assertIn("--profile-qualification-result", command_help.stdout)
        self.assertNotIn("--profile-gate-summary", command_help.stdout)
        self.assertNotIn("--footprint-reliability", command_help.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
