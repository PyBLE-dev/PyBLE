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
    def test_pico_pacing_fact_is_one_positive_runtime_source_constant(self):
        runtime_budget = getattr(CONSOLE, "TX_BUDGET_MS", None)
        self.assertIs(
            type(runtime_budget),
            int,
            "P8/OI-P3 must first freeze a Pico runtime TX_BUDGET_MS; the "
            "ESP 250 ms constant and host fixture are not Pico evidence",
        )
        if type(runtime_budget) is not int:
            return
        self.assertGreater(runtime_budget, 0)
        self.assertEqual(
            getattr(PROFILE_BENCH, "RP2_CONSOLE_TX_BUDGET_MS", None),
            runtime_budget,
            "the bench fact must be bound to the frozen runtime value",
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
        self.assertEqual(
            args.console_tx_budget_ms,
            getattr(PROFILE_BENCH, "RP2_CONSOLE_TX_BUDGET_MS", None),
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
            root = Path(tmp)
            candidate = root / "candidate"
            (candidate / "esp32-c3-4mb").mkdir(parents=True)
            release_raw = canonical_json_bytes(
                {"identity": {"version": "0.6.0"}}
            )
            (candidate / "release.json").write_bytes(release_raw)
            artifact = b"candidate C3 firmware\0"
            (candidate / "esp32-c3-4mb" / "firmware.bin").write_bytes(artifact)
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
