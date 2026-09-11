#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for candidate-bound firmware-v0.6.1 hardening evidence.

The production gate is deliberately a pure, standard-library authority shared
by the physical runner, completion writer, and finalizer.  These fixtures are
synthetic and are never physical HIL evidence.
"""

from __future__ import annotations

import copy
import concurrent.futures
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
GATE_PATH = (
    ROOT / "firmware" / "qualification" / "v061_hardening_release_gate.py"
)
BENCH_PATH = ROOT / "tests/firmware_tests/hil/v061_hardening_bench.py"
sys.path.insert(0, str(HERE))
import test_v060_qualification_workflow as v060_fixture  # noqa: E402

PROFILE_TARGETS = {
    "esp32-4mb": "esp32",
    "esp32-s3-n16r8": "esp32-s3",
    "waveshare-esp32-s3-lcd-147b": "waveshare-esp32-s3-lcd-147b",
    "esp32-c3-4mb": "esp32-c3",
    "rpi-pico2-w": "rpi-pico2-w",
}
SCENARIO_ORDER = (
    "transport-session",
    "fragment-hardening",
    "run-isolation",
    "resource-stability",
    "stdin-isolation",
    "configuration-durability",
    "filesystem-hardening",
)
WORKSPACE_ORDER = (
    "erased-media-first-boot",
    "nonblank-media-refusal",
)
RESULT_KEYS = (
    "schema_version",
    "measurement_contract",
    "profile_id",
    "target",
    "firmware_version",
    "source_commit",
    "candidate_release_json_sha256",
    "install_sha256",
    "qualification_source_commit",
    "qualification_executable_sha256",
    "scenario_order",
    "scenarios",
    "workspace_provisioning",
    "raw_log_sha256",
    "status",
)
SUMMARY_KEYS = (
    "measurement_contract",
    "scenario_order",
    "scenarios",
    "sequential_runs",
    "workspace_provisioning",
    "private_result_sha256",
)
RECEIPT_KEYS = (
    "schema_version",
    "measurement_contract",
    "observation_kind",
    "profile_id",
    "target",
    "firmware_version",
    "source_commit",
    "candidate_release_json_sha256",
    "install_sha256",
    "qualification_source_commit",
    "qualification_executable_sha256",
    "acquisition_sha256",
    "raw_log_sha256",
    "status",
)


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=False,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def load_gate():
    if not GATE_PATH.is_file():
        return None, "missing production hardening gate: %s" % GATE_PATH
    spec = importlib.util.spec_from_file_location(
        "pyble_v061_hardening_release_gate",
        GATE_PATH,
    )
    if spec is None or spec.loader is None:
        return None, "cannot load production hardening gate"
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - reported by the seam test.
        return None, "cannot import production hardening gate: %s" % exc
    return module, ""


GATE, GATE_LOAD_ERROR = load_gate()
HAVE_GATE = GATE is not None


def valid_receipt(
    observation_kind: str,
    *,
    profile_id: str = "esp32-4mb",
) -> dict:
    return {
        "schema_version": 1,
        "measurement_contract": "v061-workspace-provisioning-receipt-v1",
        "observation_kind": observation_kind,
        "profile_id": profile_id,
        "target": PROFILE_TARGETS[profile_id],
        "firmware_version": "0.6.1",
        "source_commit": "1" * 40,
        "candidate_release_json_sha256": "2" * 64,
        "install_sha256": "3" * 64,
        "qualification_source_commit": "4" * 40,
        "qualification_executable_sha256": "5" * 64,
        "acquisition_sha256": "a" * 64 if observation_kind == WORKSPACE_ORDER[0] else "b" * 64,
        "raw_log_sha256": (
            "6" * 64
            if observation_kind == WORKSPACE_ORDER[0]
            else "7" * 64
        ),
        "status": "passed",
    }


def valid_result(*, profile_id: str = "esp32-4mb") -> dict:
    erased = canonical_json_bytes(
        valid_receipt(WORKSPACE_ORDER[0], profile_id=profile_id)
    )
    nonblank = canonical_json_bytes(
        valid_receipt(WORKSPACE_ORDER[1], profile_id=profile_id)
    )
    scenarios = {}
    for name in SCENARIO_ORDER:
        scenarios[name] = (
            {"status": "passed", "sequential_runs": 50}
            if name == "resource-stability"
            else {"status": "passed"}
        )
    return {
        "schema_version": 1,
        "measurement_contract": "v061-hardening-seven-scenario-v1",
        "profile_id": profile_id,
        "target": PROFILE_TARGETS[profile_id],
        "firmware_version": "0.6.1",
        "source_commit": "1" * 40,
        "candidate_release_json_sha256": "2" * 64,
        "install_sha256": "3" * 64,
        "qualification_source_commit": "4" * 40,
        "qualification_executable_sha256": "5" * 64,
        "scenario_order": list(SCENARIO_ORDER),
        "scenarios": scenarios,
        "workspace_provisioning": {
            WORKSPACE_ORDER[0]: {
                "status": "passed",
                "receipt_file": "erased.json",
                "receipt_sha256": hashlib.sha256(erased).hexdigest(),
                "acquisition_sha256": "a" * 64,
                "raw_log_sha256": "6" * 64,
            },
            WORKSPACE_ORDER[1]: {
                "status": "passed",
                "receipt_file": "nonblank.json",
                "receipt_sha256": hashlib.sha256(nonblank).hexdigest(),
                "acquisition_sha256": "b" * 64,
                "raw_log_sha256": "7" * 64,
            },
        },
        "raw_log_sha256": "8" * 64,
        "status": "passed",
    }


def validation_kwargs(profile_id: str = "esp32-4mb") -> dict:
    return {
        "expected_profile_id": profile_id,
        "expected_target": PROFILE_TARGETS[profile_id],
        "expected_version": "0.6.1",
        "expected_source_commit": "1" * 40,
        "candidate_release_json_sha256": "2" * 64,
        "expected_install_sha256": "3" * 64,
        "expected_qualification_source_commit": "4" * 40,
        "expected_qualification_executable_sha256": "5" * 64,
    }


def private_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o600)


def scenario_results() -> dict:
    return {
        name: (
            {"status": "passed", "sequential_runs": 50}
            if name == "resource-stability"
            else {"status": "passed"}
        )
        for name in SCENARIO_ORDER
    }


def canonical_json_lines(values: list[dict]) -> bytes:
    return b"".join(
        (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        for value in values
    )


def workspace_raw_log(observation_kind: str) -> bytes:
    if observation_kind == WORKSPACE_ORDER[0]:
        values = [
            {"event": "media-precondition", "state": "erased"},
            {"count": 1, "event": "lfs2-format"},
            {"count": 1, "event": "lfs2-remount"},
            {"event": "service-advertisement", "status": "observed"},
        ]
    elif observation_kind == WORKSPACE_ORDER[1]:
        values = [
            {
                "event": "media-precondition",
                "state": "nonblank-incompatible",
            },
            {"count": 0, "event": "media-write"},
            {"count": 1, "event": "recovery-message"},
            {"event": "service-advertisement", "status": "absent"},
        ]
    else:
        raise AssertionError("unknown workspace observation kind")
    return canonical_json_lines(values)


def write_acquisition_fixture(path, observation_kind, receipt, artifact_bytes):
    """Synthetic physical-byte fixture; it is never release/HIL evidence."""
    import test_v061_workspace_acquisition as acquisition
    validation = {
        "expected_profile_id": receipt["profile_id"],
        "expected_target": receipt["target"],
        "expected_version": receipt["firmware_version"],
        "expected_source_commit": receipt["source_commit"],
        "candidate_release_json_sha256": receipt["candidate_release_json_sha256"],
        "expected_install_sha256": receipt["install_sha256"],
        "expected_qualification_source_commit": receipt["qualification_source_commit"],
        "expected_qualification_executable_sha256": receipt["qualification_executable_sha256"],
    }
    _, _, _, value = acquisition.acquisition_fixture(
        path.parent, observation_kind, receipt_name=path.name,
        profile_id=receipt["profile_id"], validation=validation, install=artifact_bytes)
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def attach_result_workspace(path, value, artifact_bytes):
    """Attach synthetic measured-byte siblings to a private-result fixture."""
    for kind, suffix in zip(WORKSPACE_ORDER, ("erased", "nonblank")):
        receipt_path = path.with_name(path.stem + "-" + suffix + ".json")
        receipt = valid_receipt(kind, profile_id=value["profile_id"])
        for field in ("source_commit", "candidate_release_json_sha256", "install_sha256",
                      "qualification_source_commit", "qualification_executable_sha256"):
            receipt[field] = value[field]
        raw = workspace_raw_log(kind)
        private_write(receipt_path.with_name(receipt_path.stem + "-raw.jsonl"), raw)
        receipt["raw_log_sha256"] = hashlib.sha256(raw).hexdigest()
        receipt["acquisition_sha256"] = write_acquisition_fixture(
            receipt_path, kind, receipt, artifact_bytes)
        receipt_raw = canonical_json_bytes(receipt)
        private_write(receipt_path, receipt_raw)
        value["workspace_provisioning"][kind] = {
            "status": "passed", "receipt_file": receipt_path.name,
            "receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
            "acquisition_sha256": receipt["acquisition_sha256"],
            "raw_log_sha256": receipt["raw_log_sha256"],
        }


def writer_fixture(root: Path, profile_id: str) -> dict[str, object]:
    candidate = root / "candidate"
    filename = "firmware.uf2" if profile_id == "rpi-pico2-w" else "firmware.bin"
    artifact = candidate / profile_id / filename
    artifact_bytes = ("synthetic %s v0.6.1 firmware" % profile_id).encode("ascii")
    private_write(artifact, artifact_bytes)
    release = v060_fixture.candidate_release(
        artifact_bytes,
        version="0.6.1",
    )
    profile = next(item for item in release["profiles"] if item["id"] == profile_id)
    profile["install"]["path"] = "%s/%s" % (profile_id, filename)
    profile["install"]["size"] = len(artifact_bytes)
    profile["install"]["sha256"] = hashlib.sha256(artifact_bytes).hexdigest()
    release_path = candidate / "release.json"
    release_path.write_bytes(v060_fixture.canonical_json_bytes(release))
    candidate_digest = hashlib.sha256(release_path.read_bytes()).hexdigest()
    install_digest = hashlib.sha256(artifact_bytes).hexdigest()
    qualification_source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    qualification_executable_sha256 = hashlib.sha256(
        BENCH_PATH.read_bytes()
    ).hexdigest()
    receipts = []
    for observation_kind, stem in zip(WORKSPACE_ORDER, ("erased", "nonblank")):
        path = root / (stem + ".json")
        boot_log = root / (stem + "-raw.jsonl")
        private_write(boot_log, workspace_raw_log(observation_kind))
        receipt = valid_receipt(observation_kind, profile_id=profile_id)
        receipt["candidate_release_json_sha256"] = candidate_digest
        receipt["install_sha256"] = install_digest
        receipt["qualification_source_commit"] = qualification_source_commit
        receipt["qualification_executable_sha256"] = (
            qualification_executable_sha256
        )
        receipt["raw_log_sha256"] = hashlib.sha256(
            boot_log.read_bytes()
        ).hexdigest()
        receipt["acquisition_sha256"] = write_acquisition_fixture(
            path, observation_kind, receipt, artifact_bytes)
        private_write(path, canonical_json_bytes(receipt))
        receipts.append(path)
    raw_log = root / "hardening.jsonl"
    private_write(
        raw_log,
        canonical_json_lines(
            [
                (
                    {
                        "scenario": name,
                        "sequential_runs": 50,
                        "status": "passed",
                    }
                    if name == "resource-stability"
                    else {"scenario": name, "status": "passed"}
                )
                for name in SCENARIO_ORDER
            ]
        ),
    )
    return {
        "candidate": candidate,
        "artifact": artifact,
        "release_path": release_path,
        "candidate_digest": candidate_digest,
        "install_digest": install_digest,
        "qualification_source_commit": qualification_source_commit,
        "qualification_executable_sha256": qualification_executable_sha256,
        "erased": receipts[0],
        "nonblank": receipts[1],
        "raw_log": raw_log,
        "output": root / "hardening-result.json",
    }


class V061HardeningGateSeamTests(unittest.TestCase):
    def test_shared_gate_and_exact_public_functions_exist(self):
        self.assertIsNotNone(
            GATE,
            "[red] %s" % GATE_LOAD_ERROR,
        )
        if GATE is None:
            return
        expected = {
            "canonical_json_bytes": {"value"},
            "validate_workspace_receipt_payload": {
                "value",
                "observation_kind",
                *validation_kwargs(),
            },
            "validate_workspace_receipt_file": {
                "path",
                "observation_kind",
                *validation_kwargs(),
            },
            "validate_result_payload": {"value", *validation_kwargs()},
            "validate_result_file": {
                "path",
                "artifact_path",
                "expected_profile_id",
                "expected_target",
                "expected_version",
                "expected_source_commit",
                "candidate_release_json_sha256",
                "expected_qualification_source_commit",
                "expected_qualification_executable_sha256",
            },
            "create_result": {
                "candidate_dir",
                "profile_id",
                "scenario_results",
                "workspace_erased_receipt",
                "workspace_nonblank_receipt",
                "raw_log",
                "output_path",
                "qualification_repo_root",
            },
            "create_workspace_receipt": {
                "candidate_dir",
                "profile_id",
                "observation_kind",
                "raw_boot_log",
                "output_path",
                "qualification_repo_root",
            },
        }
        for name, parameters in expected.items():
            with self.subTest(function=name):
                function = getattr(GATE, name, None)
                self.assertTrue(callable(function), "missing %s" % name)
                if callable(function):
                    self.assertEqual(
                        set(inspect.signature(function).parameters),
                        set(parameters),
                    )

    def test_frozen_constant_inventory_is_exact(self):
        self.assertIsNotNone(GATE, GATE_LOAD_ERROR)
        if GATE is None:
            return
        self.assertEqual(GATE.PROFILE_TARGETS, PROFILE_TARGETS)
        self.assertEqual(GATE.SCENARIO_ORDER, SCENARIO_ORDER)
        self.assertEqual(GATE.WORKSPACE_PROVISIONING_ORDER, WORKSPACE_ORDER)
        self.assertEqual(GATE.RESULT_KEYS, RESULT_KEYS)
        self.assertEqual(GATE.PUBLIC_SUMMARY_KEYS, SUMMARY_KEYS)
        self.assertEqual(GATE.WORKSPACE_RECEIPT_KEYS, RECEIPT_KEYS)


@unittest.skipUnless(HAVE_GATE, "[red] v0.6.1 hardening gate is not implemented")
class V061HardeningPayloadValidationTests(unittest.TestCase):
    def validate(self, value: dict, *, profile_id: str = "esp32-4mb") -> dict:
        return GATE.validate_result_payload(
            value,
            **validation_kwargs(profile_id),
        )

    def test_exact_result_derives_only_the_privacy_safe_summary(self):
        value = valid_result()
        summary = self.validate(value)
        self.assertEqual(tuple(value), RESULT_KEYS)
        self.assertEqual(tuple(value["scenarios"]), SCENARIO_ORDER)
        self.assertEqual(
            tuple(value["workspace_provisioning"]),
            WORKSPACE_ORDER,
        )
        self.assertEqual(tuple(summary), SUMMARY_KEYS)
        self.assertEqual(
            summary,
            {
                "measurement_contract": "v061-hardening-seven-scenario-v1",
                "scenario_order": list(SCENARIO_ORDER),
                "scenarios": {name: "passed" for name in SCENARIO_ORDER},
                "sequential_runs": 50,
                "workspace_provisioning": {
                    name: "passed" for name in WORKSPACE_ORDER
                },
                "private_result_sha256": hashlib.sha256(
                    canonical_json_bytes(value)
                ).hexdigest(),
            },
        )
        encoded = canonical_json_bytes(summary)
        for private in (
            value["source_commit"],
            value["install_sha256"],
            value["qualification_source_commit"],
            value["qualification_executable_sha256"],
            value["raw_log_sha256"],
            "device_id",
            "address",
            "label",
            "console",
            "exception",
        ):
            self.assertNotIn(private.encode("ascii"), encoded)

    def test_missing_extra_reordered_or_nonpassing_scenario_is_rejected(self):
        mutations = {
            "missing": lambda value: value["scenarios"].pop(SCENARIO_ORDER[0]),
            "extra": lambda value: value["scenarios"].__setitem__(
                "future-scenario", {"status": "passed"}
            ),
            "reordered-list": lambda value: value["scenario_order"].reverse(),
            "reordered-map": lambda value: value.__setitem__(
                "scenarios",
                dict(reversed(tuple(value["scenarios"].items()))),
            ),
            "failed": lambda value: value["scenarios"][SCENARIO_ORDER[0]].__setitem__(
                "status", "failed"
            ),
            "scenario-extra": lambda value: value["scenarios"][
                SCENARIO_ORDER[0]
            ].__setitem__("detail", "private"),
            "runs-49": lambda value: value["scenarios"][
                "resource-stability"
            ].__setitem__("sequential_runs", 49),
            "runs-bool": lambda value: value["scenarios"][
                "resource-stability"
            ].__setitem__("sequential_runs", True),
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                value = valid_result()
                mutate(value)
                with self.assertRaises(GATE.QualificationError):
                    self.validate(value)

    def test_workspace_not_run_missing_shared_or_reordered_receipts_are_rejected(self):
        mutations = {
            "not-run": lambda value: value["workspace_provisioning"][
                WORKSPACE_ORDER[0]
            ].__setitem__("status", "NOT-RUN"),
            "missing": lambda value: value["workspace_provisioning"].pop(
                WORKSPACE_ORDER[1]
            ),
            "extra": lambda value: value["workspace_provisioning"].__setitem__(
                "configuration-corruption-proxy",
                {
                    "status": "passed",
                    "receipt_sha256": "9" * 64,
                    "raw_log_sha256": "a" * 64,
                },
            ),
            "reordered": lambda value: value.__setitem__(
                "workspace_provisioning",
                dict(reversed(tuple(value["workspace_provisioning"].items()))),
            ),
            "shared-receipt": lambda value: value["workspace_provisioning"][
                WORKSPACE_ORDER[1]
            ].__setitem__(
                "receipt_sha256",
                value["workspace_provisioning"][WORKSPACE_ORDER[0]][
                    "receipt_sha256"
                ],
            ),
            "shared-log": lambda value: value["workspace_provisioning"][
                WORKSPACE_ORDER[1]
            ].__setitem__(
                "raw_log_sha256",
                value["workspace_provisioning"][WORKSPACE_ORDER[0]][
                    "raw_log_sha256"
                ],
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                value = valid_result()
                mutate(value)
                with self.assertRaises(GATE.QualificationError):
                    self.validate(value)

    def test_every_candidate_and_qualification_identity_is_enforced(self):
        mutations = {
            "profile": ("profile_id", "esp32-s3-n16r8"),
            "target": ("target", "esp32-s3"),
            "version-old": ("firmware_version", "0.6.0"),
            "version-new": ("firmware_version", "0.6.1+local"),
            "source": ("source_commit", "9" * 40),
            "candidate": ("candidate_release_json_sha256", "9" * 64),
            "install": ("install_sha256", "9" * 64),
            "qualification-source": ("qualification_source_commit", "9" * 40),
            "qualification-executable": (
                "qualification_executable_sha256",
                "9" * 64,
            ),
            "raw-log-uppercase": ("raw_log_sha256", "A" * 64),
            "status": ("status", "pending"),
        }
        for name, (field, replacement) in mutations.items():
            with self.subTest(case=name):
                value = valid_result()
                value[field] = replacement
                with self.assertRaises(GATE.QualificationError):
                    self.validate(value)

        for name, mutation in (
            ("missing", lambda value: value.pop("raw_log_sha256")),
            ("extra", lambda value: value.__setitem__("private_address", "secret")),
            ("bool-schema", lambda value: value.__setitem__("schema_version", True)),
        ):
            with self.subTest(case=name):
                value = valid_result()
                mutation(value)
                with self.assertRaises(GATE.QualificationError):
                    self.validate(value)

    def test_workspace_receipts_are_exact_and_candidate_bound(self):
        for observation_kind in WORKSPACE_ORDER:
            receipt = valid_receipt(observation_kind)
            with self.subTest(kind=observation_kind):
                self.assertEqual(tuple(receipt), RECEIPT_KEYS)
                self.assertEqual(
                    GATE.validate_workspace_receipt_payload(
                        receipt,
                        observation_kind=observation_kind,
                        **validation_kwargs(),
                    ),
                    {
                        "status": "passed",
                        "receipt_sha256": hashlib.sha256(
                            canonical_json_bytes(receipt)
                        ).hexdigest(),
                        "acquisition_sha256": receipt["acquisition_sha256"],
                        "raw_log_sha256": receipt["raw_log_sha256"],
                    },
                )

        identity_fields = (
            "profile_id",
            "target",
            "firmware_version",
            "source_commit",
            "candidate_release_json_sha256",
            "install_sha256",
            "qualification_source_commit",
            "qualification_executable_sha256",
        )
        for field in identity_fields:
            with self.subTest(field=field):
                receipt = valid_receipt(WORKSPACE_ORDER[0])
                receipt[field] = "9" * len(receipt[field])
                with self.assertRaises(GATE.QualificationError):
                    GATE.validate_workspace_receipt_payload(
                        receipt,
                        observation_kind=WORKSPACE_ORDER[0],
                        **validation_kwargs(),
                    )

        swapped = valid_receipt(WORKSPACE_ORDER[1])
        with self.assertRaises(GATE.QualificationError):
            GATE.validate_workspace_receipt_payload(
                swapped,
                observation_kind=WORKSPACE_ORDER[0],
                **validation_kwargs(),
            )


@unittest.skipUnless(HAVE_GATE, "[red] v0.6.1 hardening gate is not implemented")
class V061WorkspaceReceiptWriterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="pyble-v061-workspace-receipt-"
        )
        self.root = Path(self.temporary.name)
        self.candidate = self.root / "candidate"
        self.profile_id = "esp32-c3-4mb"
        self.artifact = self.candidate / self.profile_id / "firmware.bin"
        private_write(self.artifact, b"synthetic v0.6.1 candidate firmware")
        release = v060_fixture.candidate_release(
            self.artifact.read_bytes(),
            version="0.6.1",
        )
        self.release_path = self.candidate / "release.json"
        self.release_path.write_bytes(v060_fixture.canonical_json_bytes(release))

    def tearDown(self):
        self.temporary.cleanup()

    def paths(self, observation_kind: str) -> tuple[Path, Path]:
        stem = "erased" if observation_kind == WORKSPACE_ORDER[0] else "nonblank"
        output = self.root / (stem + ".json")
        return output.with_name(output.stem + "-raw.jsonl"), output

    def create(self, observation_kind: str, *, raw_path=None, output_path=None):
        expected_raw, expected_output = self.paths(observation_kind)
        selected_raw = expected_raw if raw_path is None else Path(raw_path)
        selected_output = expected_output if output_path is None else Path(output_path)
        if not selected_raw.exists() and not selected_raw.is_symlink():
            private_write(selected_raw, workspace_raw_log(observation_kind))
        acquisition = selected_output.with_name(selected_output.stem + "-acquisition.json")
        if selected_output.parent == self.root and not acquisition.exists():
            receipt = valid_receipt(observation_kind, profile_id=self.profile_id)
            receipt["candidate_release_json_sha256"] = hashlib.sha256(self.release_path.read_bytes()).hexdigest()
            receipt["install_sha256"] = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
            receipt["qualification_source_commit"] = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                capture_output=True, text=True).stdout.strip()
            receipt["qualification_executable_sha256"] = hashlib.sha256(BENCH_PATH.read_bytes()).hexdigest()
            write_acquisition_fixture(selected_output, observation_kind, receipt, self.artifact.read_bytes())
        return GATE.create_workspace_receipt(
            candidate_dir=self.candidate,
            profile_id=self.profile_id,
            observation_kind=observation_kind,
            raw_boot_log=selected_raw,
            output_path=selected_output,
            qualification_repo_root=ROOT,
        )

    def test_writer_derives_both_exact_candidate_bound_receipts(self):
        qualification_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        for observation_kind in WORKSPACE_ORDER:
            with self.subTest(kind=observation_kind):
                raw_path, output = self.paths(observation_kind)
                self.assertEqual(self.create(observation_kind), output)
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
                value = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(tuple(value), RECEIPT_KEYS)
                self.assertEqual(value["observation_kind"], observation_kind)
                self.assertEqual(value["profile_id"], self.profile_id)
                self.assertEqual(value["target"], PROFILE_TARGETS[self.profile_id])
                self.assertEqual(value["firmware_version"], "0.6.1")
                self.assertEqual(value["source_commit"], "1" * 40)
                self.assertEqual(
                    value["candidate_release_json_sha256"],
                    hashlib.sha256(self.release_path.read_bytes()).hexdigest(),
                )
                self.assertEqual(
                    value["install_sha256"],
                    hashlib.sha256(self.artifact.read_bytes()).hexdigest(),
                )
                self.assertEqual(
                    value["qualification_source_commit"],
                    qualification_commit,
                )
                self.assertEqual(
                    value["qualification_executable_sha256"],
                    hashlib.sha256(BENCH_PATH.read_bytes()).hexdigest(),
                )
                self.assertEqual(
                    value["raw_log_sha256"],
                    hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                )
                self.assertEqual(output.read_bytes(), canonical_json_bytes(value))

    def test_writer_rejects_invalid_logs_links_paths_and_existing_output(self):
        invalid_values = {
            "empty": b"",
            "reordered": canonical_json_lines(
                list(
                    reversed(
                        [
                            {"event": "media-precondition", "state": "erased"},
                            {"count": 1, "event": "lfs2-format"},
                            {"count": 1, "event": "lfs2-remount"},
                            {
                                "event": "service-advertisement",
                                "status": "observed",
                            },
                        ]
                    )
                )
            ),
            "two-formats": canonical_json_lines(
                [
                    {"event": "media-precondition", "state": "erased"},
                    {"count": 2, "event": "lfs2-format"},
                    {"count": 1, "event": "lfs2-remount"},
                    {"event": "service-advertisement", "status": "observed"},
                ]
            ),
            "free-text": canonical_json_lines(
                [{"detail": "operator assertion", "status": "passed"}]
            ),
        }
        for label, raw in invalid_values.items():
            with self.subTest(log=label):
                raw_path = self.root / (label + "-raw.jsonl")
                output = self.root / (label + ".json")
                private_write(raw_path, raw)
                with self.assertRaises(GATE.QualificationError):
                    self.create(
                        WORKSPACE_ORDER[0],
                        raw_path=raw_path,
                        output_path=output,
                    )
                self.assertFalse(output.exists())

        raw_path, output = self.paths(WORKSPACE_ORDER[0])
        private_write(raw_path, workspace_raw_log(WORKSPACE_ORDER[0]))
        output.write_bytes(b"owner data\n")
        output.chmod(0o600)
        with self.assertRaises(GATE.QualificationError):
            self.create(WORKSPACE_ORDER[0])
        self.assertEqual(output.read_bytes(), b"owner data\n")

        output.unlink()
        raw_path.chmod(0o644)
        with self.assertRaises(GATE.QualificationError):
            self.create(WORKSPACE_ORDER[0])
        self.assertFalse(output.exists())
        raw_path.chmod(0o600)

        linked = self.root / "raw-second-link.jsonl"
        os.link(raw_path, linked)
        try:
            with self.assertRaises(GATE.QualificationError):
                self.create(WORKSPACE_ORDER[0])
            self.assertFalse(output.exists())
        finally:
            linked.unlink()

        inside = self.candidate / "workspace.json"
        with self.assertRaises(GATE.QualificationError):
            self.create(WORKSPACE_ORDER[0], output_path=inside)
        self.assertFalse(inside.exists())

        wrong_raw = self.root / "not-the-derived-name.jsonl"
        private_write(wrong_raw, workspace_raw_log(WORKSPACE_ORDER[0]))
        with self.assertRaises(GATE.QualificationError):
            self.create(WORKSPACE_ORDER[0], raw_path=wrong_raw)
        self.assertFalse(output.exists())

    def test_result_file_must_be_canonical_regular_private_and_unlinked(self):
        with tempfile.TemporaryDirectory(prefix="pyble-v061-gate-") as tmp:
            root = Path(tmp)
            artifact = root / "firmware.bin"
            artifact.write_bytes(b"candidate firmware")
            value = valid_result()
            value["install_sha256"] = hashlib.sha256(
                artifact.read_bytes()
            ).hexdigest()
            path = root / "result.json"
            attach_result_workspace(path, value, artifact.read_bytes())
            path.write_bytes(canonical_json_bytes(value))
            path.chmod(0o600)
            kwargs = validation_kwargs()
            kwargs.pop("expected_install_sha256")
            self.assertEqual(
                GATE.validate_result_file(
                    path,
                    artifact_path=artifact,
                    **kwargs,
                )["private_result_sha256"],
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )

            for case, prepare in (
                ("mode", lambda: path.chmod(0o644)),
                (
                    "noncanonical",
                    lambda: path.write_text(json.dumps(value) + "\n", encoding="utf-8"),
                ),
            ):
                path.write_bytes(canonical_json_bytes(value))
                path.chmod(0o600)
                prepare()
                with self.subTest(case=case), self.assertRaises(
                    GATE.QualificationError
                ):
                    GATE.validate_result_file(
                        path,
                        artifact_path=artifact,
                        **kwargs,
                    )

            path.write_bytes(canonical_json_bytes(value))
            path.chmod(0o600)
            linked = root / "linked.json"
            os.link(path, linked)
            with self.assertRaises(GATE.QualificationError):
                GATE.validate_result_file(
                    path,
                    artifact_path=artifact,
                    **kwargs,
                )


@unittest.skipUnless(HAVE_GATE, "[red] v0.6.1 hardening gate is not implemented")
class V061HardeningResultWriterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pyble-v061-writer-")
        self.root = Path(self.temporary.name)
        self.profile_id = "esp32-c3-4mb"
        fixture = writer_fixture(self.root, self.profile_id)
        for name, value in fixture.items():
            setattr(self, name, value)

    def tearDown(self):
        self.temporary.cleanup()

    def create(self, *, output: Path | None = None):
        return GATE.create_result(
            candidate_dir=self.candidate,
            profile_id=self.profile_id,
            scenario_results=scenario_results(),
            workspace_erased_receipt=self.erased,
            workspace_nonblank_receipt=self.nonblank,
            raw_log=self.raw_log,
            output_path=self.output if output is None else output,
            qualification_repo_root=ROOT,
        )

    def test_writer_derives_every_identity_and_publishes_one_private_result(self):
        self.assertEqual(self.create(), self.output)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        value = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(tuple(value), RESULT_KEYS)
        self.assertEqual(value["source_commit"], "1" * 40)
        self.assertEqual(
            value["candidate_release_json_sha256"],
            self.candidate_digest,
        )
        self.assertEqual(value["install_sha256"], self.install_digest)
        self.assertEqual(
            value["qualification_source_commit"],
            self.qualification_source_commit,
        )
        self.assertEqual(
            value["qualification_executable_sha256"],
            self.qualification_executable_sha256,
        )
        self.assertEqual(
            value["raw_log_sha256"],
            hashlib.sha256(self.raw_log.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            self.output.read_bytes(),
            canonical_json_bytes(value),
        )

    def test_writer_admits_each_exact_release_profile_and_install_shape(self):
        for profile_id in PROFILE_TARGETS:
            with self.subTest(profile_id=profile_id):
                case_root = self.root / ("profile-" + profile_id)
                fixture = writer_fixture(case_root, profile_id)
                output = GATE.create_result(
                    candidate_dir=fixture["candidate"],
                    profile_id=profile_id,
                    scenario_results=scenario_results(),
                    workspace_erased_receipt=fixture["erased"],
                    workspace_nonblank_receipt=fixture["nonblank"],
                    raw_log=fixture["raw_log"],
                    output_path=fixture["output"],
                    qualification_repo_root=ROOT,
                )
                value = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(value["profile_id"], profile_id)
                self.assertEqual(value["target"], PROFILE_TARGETS[profile_id])
                self.assertEqual(
                    value["install_sha256"],
                    fixture["install_digest"],
                )
                expected_name = (
                    "firmware.uf2"
                    if profile_id == "rpi-pico2-w"
                    else "firmware.bin"
                )
                self.assertEqual(Path(fixture["artifact"]).name, expected_name)

    def test_existing_or_candidate_internal_output_is_never_replaced(self):
        private_write(self.output, b"operator-owned bytes\n")
        with self.assertRaises(GATE.QualificationError):
            self.create()
        self.assertEqual(self.output.read_bytes(), b"operator-owned bytes\n")

        self.output.unlink()
        inside = self.candidate / "forbidden-result.json"
        with self.assertRaises(GATE.QualificationError):
            self.create(output=inside)
        self.assertFalse(inside.exists())

    def test_nonprivate_linked_or_noncanonical_inputs_mint_no_result(self):
        cases = {}
        self.raw_log.chmod(0o644)
        cases["public-raw-log"] = lambda: self.raw_log.chmod(0o600)

        for name, restore in cases.items():
            with self.subTest(case=name), self.assertRaises(
                GATE.QualificationError
            ):
                self.create()
            self.assertFalse(self.output.exists())
            restore()

        linked = self.root / "linked-erased.json"
        os.link(self.erased, linked)
        try:
            with self.assertRaises(GATE.QualificationError):
                self.create()
            self.assertFalse(self.output.exists())
        finally:
            linked.unlink()

        original = self.raw_log.read_bytes()
        invalid_logs = {
            "empty": b"",
            "whitespace": b'{"status": "passed"}\n',
            "missing-final-lf": b'{"status":"passed"}',
            "blank-line": b'{"status":"passed"}\n\n',
            "non-object": b'[]\n',
            "non-finite": b'{"measurement":NaN}\n',
            "invalid-utf8": b'{"status":"\xff"}\n',
            "private-field": canonical_json_lines(
                [{"address": "private-address", "status": "passed"}]
            ),
            "device-id": canonical_json_lines(
                [{"device_id": "private-id", "status": "passed"}]
            ),
            "label": canonical_json_lines(
                [{"label": "private-label", "status": "passed"}]
            ),
            "source": canonical_json_lines(
                [{"source": "print('secret')", "status": "passed"}]
            ),
            "file-content": canonical_json_lines(
                [{"file_content": "secret bytes", "status": "passed"}]
            ),
            "console": canonical_json_lines(
                [{"console": "private output", "status": "passed"}]
            ),
            "exception": canonical_json_lines(
                [{"exception": "private traceback", "status": "passed"}]
            ),
            "unbounded-free-text": canonical_json_lines(
                [{"detail": "operator supplied text", "status": "passed"}]
            ),
            "private-scenario-value": canonical_json_lines(
                [{"scenario": "private-label", "status": "passed"}]
            ),
            "unbounded-number": canonical_json_lines(
                [
                    {
                        "scenario": "resource-stability",
                        "sequential_runs": 10**100,
                        "status": "passed",
                    }
                ]
            ),
        }
        for name, raw in invalid_logs.items():
            with self.subTest(raw_log=name):
                self.raw_log.write_bytes(raw)
                self.raw_log.chmod(0o600)
                with self.assertRaises(GATE.QualificationError):
                    self.create()
                self.assertFalse(self.output.exists())
        self.raw_log.write_bytes(original)
        self.raw_log.chmod(0o600)

        self.erased.write_text(
            json.dumps(json.loads(self.erased.read_text(encoding="utf-8")))
            + "\n",
            encoding="utf-8",
        )
        self.erased.chmod(0o600)
        with self.assertRaises(GATE.QualificationError):
            self.create()
        self.assertFalse(self.output.exists())

    def test_link_special_and_symlink_parent_paths_mint_no_result(self):
        cases = (
            "raw-symlink",
            "raw-broken-symlink",
            "raw-hardlink",
            "raw-directory",
            "receipt-symlink",
            "receipt-broken-symlink",
            "receipt-public-mode",
            "receipt-hardlink",
            "output-symlink",
            "output-broken-symlink",
            "output-directory",
            "output-symlink-parent",
        )
        for label in cases:
            with self.subTest(path_case=label):
                case_root = self.root / ("unsafe-" + label)
                fixture = writer_fixture(case_root, self.profile_id)
                raw_log = Path(fixture["raw_log"])
                erased = Path(fixture["erased"])
                output = Path(fixture["output"])
                external_sentinel = None
                if label == "raw-symlink":
                    target = raw_log.with_name("real-hardening.jsonl")
                    raw_log.rename(target)
                    raw_log.symlink_to(target)
                elif label == "raw-broken-symlink":
                    raw_log.unlink()
                    raw_log.symlink_to(raw_log.with_name("missing.jsonl"))
                elif label == "raw-hardlink":
                    os.link(raw_log, raw_log.with_name("raw-second-link.jsonl"))
                elif label == "raw-directory":
                    raw_log.unlink()
                    raw_log.mkdir()
                elif label == "receipt-symlink":
                    target = erased.with_name("real-erased.json")
                    erased.rename(target)
                    erased.symlink_to(target)
                elif label == "receipt-broken-symlink":
                    erased.unlink()
                    erased.symlink_to(erased.with_name("missing.json"))
                elif label == "receipt-public-mode":
                    erased.chmod(0o644)
                elif label == "receipt-hardlink":
                    os.link(erased, erased.with_name("receipt-second-link.json"))
                elif label == "output-symlink":
                    external_sentinel = output.with_name("external-owner-data")
                    external_sentinel.write_bytes(b"owner bytes\n")
                    output.symlink_to(external_sentinel)
                elif label == "output-broken-symlink":
                    output.symlink_to(output.with_name("missing-output.json"))
                elif label == "output-directory":
                    output.mkdir()
                elif label == "output-symlink-parent":
                    external_parent = case_root / "external-parent"
                    external_parent.mkdir()
                    linked_parent = case_root / "linked-parent"
                    linked_parent.symlink_to(external_parent, target_is_directory=True)
                    output = linked_parent / "hardening-result.json"

                with self.assertRaises(GATE.QualificationError):
                    GATE.create_result(
                        candidate_dir=fixture["candidate"],
                        profile_id=self.profile_id,
                        scenario_results=scenario_results(),
                        workspace_erased_receipt=erased,
                        workspace_nonblank_receipt=fixture["nonblank"],
                        raw_log=raw_log,
                        output_path=output,
                        qualification_repo_root=ROOT,
                    )
                if external_sentinel is not None:
                    self.assertEqual(
                        external_sentinel.read_bytes(),
                        b"owner bytes\n",
                    )
                if label == "output-symlink-parent":
                    self.assertFalse(
                        (case_root / "external-parent" / output.name).exists()
                    )

    def test_concurrent_result_creators_have_exactly_one_winner(self):
        case_root = self.root / "concurrent-output"
        fixture = writer_fixture(case_root, self.profile_id)

        def attempt():
            try:
                return GATE.create_result(
                    candidate_dir=fixture["candidate"],
                    profile_id=self.profile_id,
                    scenario_results=scenario_results(),
                    workspace_erased_receipt=fixture["erased"],
                    workspace_nonblank_receipt=fixture["nonblank"],
                    raw_log=fixture["raw_log"],
                    output_path=fixture["output"],
                    qualification_repo_root=ROOT,
                )
            except GATE.QualificationError:
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: attempt(), range(2)))
        self.assertEqual(sum(value is not None for value in outcomes), 1)
        output = Path(fixture["output"])
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        value = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(output.read_bytes(), canonical_json_bytes(value))


if __name__ == "__main__":
    unittest.main(verbosity=2)
