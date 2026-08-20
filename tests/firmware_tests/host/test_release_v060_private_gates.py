#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for the v0.6.0 C3/Pico private release gates.

The private input deliberately contains only the values that can be checked at
the release boundary.  The validator derives ``qualification_result_sha256``
from the canonical input bytes; putting that digest inside its own input would
create a circular hash.  No physical identifier or raw bench evidence is
admitted to the public summary.

This suite is host-only.  It uses tiny synthetic artifacts and never opens a
BLE, serial, USB, network, or publication resource.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
RELEASE_PATH = REPO_ROOT / "firmware" / "scripts" / "release_bundle.py"
GATE_PATH = (
    REPO_ROOT
    / "firmware"
    / "qualification"
    / "v060_profile_release_gate.py"
)

PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
    "waveshare-esp32-s3-lcd-147b",
    "esp32-c3-4mb",
    "rpi-pico2-w",
)
C3_PROFILE = "esp32-c3-4mb"
PICO_PROFILE = "rpi-pico2-w"
C3_GATES = tuple("C3-G%d" % index for index in range(7))
PICO_GATES = ("GP0", "GP1", "GP2")
VERSION = "0.6.0"
RELEASE_DIGEST = "ab" * 32
OI1_RAW_SHA256 = "cd" * 32


def load_module(name: str, path: Path):
    if not path.is_file():
        return None, "missing %s" % path
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None, "cannot construct an import spec for %s" % path
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - surfaced by presence tests.
        return None, "cannot import %s: %s" % (path, exc)
    return module, ""


RELEASE, RELEASE_ERROR = load_module("pyble_v060_gate_release", RELEASE_PATH)
GATE, GATE_ERROR = load_module("pyble_v060_profile_release_gate", GATE_PATH)


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


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def post_oi_nvs_binding(
    artifact: bytes,
    *,
    release_digest: str = RELEASE_DIGEST,
    oi1_raw_sha256: str = OI1_RAW_SHA256,
) -> dict[str, object]:
    summary = {
        "schema_version": 1,
        "profile_id": C3_PROFILE,
        "candidate_release_json_sha256": release_digest,
        "candidate_firmware_sha256": sha256_bytes(artifact),
        "oi1_raw_sha256": oi1_raw_sha256,
        "reset_samples": 10,
        "partition_offset": 0x9000,
        "partition_size": 0x6000,
        "integrity": "passed",
        "written_namespaces": [],
    }
    receipt = {"summary": summary, "inventory": []}
    raw = canonical_json_bytes(receipt)
    return {
        "receipt_sha256": sha256_bytes(raw),
        "receipt_size_bytes": len(raw),
        "summary": summary,
    }


def private_result(
    profile_id: str,
    artifact: bytes,
    *,
    release_digest: str = RELEASE_DIGEST,
) -> dict[str, object]:
    if profile_id == C3_PROFILE:
        digest_key = "candidate_firmware_sha256"
        gate_names = C3_GATES
    elif profile_id == PICO_PROFILE:
        digest_key = "candidate_uf2_sha256"
        gate_names = PICO_GATES
    else:  # pragma: no cover - fixture misuse.
        raise AssertionError("unsupported private-gate fixture profile")
    result = {
        "schema_version": 1,
        "status": "passed",
        "profile_id": profile_id,
        "firmware_version": VERSION,
        "candidate_release_json_sha256": release_digest,
        digest_key: sha256_bytes(artifact),
        "gates": {name: "passed" for name in gate_names},
    }
    if profile_id == C3_PROFILE:
        result["post_oi_nvs"] = post_oi_nvs_binding(
            artifact,
            release_digest=release_digest,
        )
    return result


def write_private_result(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value))
    path.chmod(0o600)


def expected_summary(
    profile_id: str,
    result_path: Path,
    artifact: bytes,
) -> dict[str, object]:
    value = private_result(profile_id, artifact)
    value.pop("post_oi_nvs", None)
    value["qualification_result_sha256"] = sha256_bytes(result_path.read_bytes())
    return value


class PresenceTests(unittest.TestCase):
    def test_pure_private_gate_module_and_api_exist(self) -> None:
        self.assertIsNotNone(GATE, GATE_ERROR)
        if GATE is None:
            return
        for name in (
            "validate_result_file",
            "validate_c3_result_for_observation",
            "validate_public_summary",
            "private_result_snapshot",
        ):
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(GATE, name, None)))
        self.assertTrue(
            isinstance(getattr(GATE, "QualificationError", None), type)
        )

    def test_release_finalizer_loads_the_pure_gate_and_has_no_placeholder_close(self):
        self.assertIsNotNone(RELEASE, RELEASE_ERROR)
        if RELEASE is None:
            return
        loaded = getattr(RELEASE, "_V060_PROFILE_GATE", None)
        self.assertIsNotNone(
            loaded,
            "release_bundle.py must load the pure v0.6 profile gate",
        )
        source = inspect.getsource(RELEASE.finalize_public_bundle)
        self.assertNotIn(
            "private-result validators are implemented",
            source,
            "the explicit v0.6 finalization placeholder must be replaced",
        )


class StrictPrivateResultTests(unittest.TestCase):
    def setUp(self) -> None:
        if GATE is None:
            self.fail(GATE_ERROR)
        self.temporary = tempfile.TemporaryDirectory(prefix="pyble-v060-gates-")
        self.root = Path(self.temporary.name)
        self.artifacts = {
            C3_PROFILE: b"synthetic C3 merged firmware\0" * 7,
            PICO_PROFILE: b"UF2\nsynthetic Pico 2 W image\0" * 9,
        }
        self.artifact_paths: dict[str, Path] = {}
        self.result_paths: dict[str, Path] = {}
        for profile_id, artifact in self.artifacts.items():
            artifact_name = "firmware.bin" if profile_id == C3_PROFILE else "firmware.uf2"
            artifact_path = self.root / profile_id / artifact_name
            artifact_path.parent.mkdir(parents=True)
            artifact_path.write_bytes(artifact)
            result_path = self.root / (profile_id + "-qualification.json")
            write_private_result(
                result_path,
                private_result(profile_id, artifact),
            )
            self.artifact_paths[profile_id] = artifact_path
            self.result_paths[profile_id] = result_path

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def validate(self, profile_id: str) -> dict[str, object]:
        return GATE.validate_result_file(
            self.result_paths[profile_id],
            artifact_path=self.artifact_paths[profile_id],
            expected_profile_id=profile_id,
            expected_version=VERSION,
            candidate_release_json_sha256=RELEASE_DIGEST,
        )

    def rewrite(self, profile_id: str, value: object, *, canonical: bool = True) -> None:
        path = self.result_paths[profile_id]
        raw = (
            canonical_json_bytes(value)
            if canonical
            else json.dumps(value, separators=(",", ":")).encode("utf-8")
        )
        path.write_bytes(raw)
        path.chmod(0o600)

    def test_valid_inputs_return_only_the_exact_public_summaries(self) -> None:
        for profile_id in (C3_PROFILE, PICO_PROFILE):
            with self.subTest(profile_id=profile_id):
                summary = self.validate(profile_id)
                self.assertEqual(
                    summary,
                    expected_summary(
                        profile_id,
                        self.result_paths[profile_id],
                        self.artifacts[profile_id],
                    ),
                )
                self.assertEqual(
                    set(summary),
                    {
                        "schema_version",
                        "status",
                        "profile_id",
                        "firmware_version",
                        "candidate_release_json_sha256",
                        (
                            "candidate_firmware_sha256"
                            if profile_id == C3_PROFILE
                            else "candidate_uf2_sha256"
                        ),
                        "gates",
                        "qualification_result_sha256",
                    },
                )

    def test_schema_identity_and_candidate_bindings_are_exact(self) -> None:
        mutations = {
            "schema": lambda value: value.__setitem__("schema_version", 2),
            "bool-schema": lambda value: value.__setitem__("schema_version", True),
            "status": lambda value: value.__setitem__("status", "pending"),
            "profile": lambda value: value.__setitem__("profile_id", "esp32-4mb"),
            "version": lambda value: value.__setitem__("firmware_version", "0.6.1"),
            "release-digest": lambda value: value.__setitem__(
                "candidate_release_json_sha256", "0" * 64
            ),
            "uppercase-release-digest": lambda value: value.__setitem__(
                "candidate_release_json_sha256", RELEASE_DIGEST.upper()
            ),
        }
        for profile_id in (C3_PROFILE, PICO_PROFILE):
            original = private_result(profile_id, self.artifacts[profile_id])
            for name, mutate in mutations.items():
                with self.subTest(profile_id=profile_id, mutation=name):
                    changed = copy.deepcopy(original)
                    mutate(changed)
                    self.rewrite(profile_id, changed)
                    with self.assertRaises(GATE.QualificationError):
                        self.validate(profile_id)

    def test_artifact_kind_digest_and_bytes_cannot_be_substituted(self) -> None:
        for profile_id in (C3_PROFILE, PICO_PROFILE):
            with self.subTest(profile_id=profile_id):
                digest_key = (
                    "candidate_firmware_sha256"
                    if profile_id == C3_PROFILE
                    else "candidate_uf2_sha256"
                )
                wrong_key = (
                    "candidate_uf2_sha256"
                    if profile_id == C3_PROFILE
                    else "candidate_firmware_sha256"
                )
                original = private_result(profile_id, self.artifacts[profile_id])

                changed = copy.deepcopy(original)
                changed[digest_key] = "0" * 64
                self.rewrite(profile_id, changed)
                with self.assertRaises(GATE.QualificationError):
                    self.validate(profile_id)

                changed = copy.deepcopy(original)
                changed[wrong_key] = changed.pop(digest_key)
                self.rewrite(profile_id, changed)
                with self.assertRaises(GATE.QualificationError):
                    self.validate(profile_id)

                self.rewrite(profile_id, original)
                self.artifact_paths[profile_id].write_bytes(
                    self.artifacts[profile_id] + b"changed"
                )
                with self.assertRaises(GATE.QualificationError):
                    self.validate(profile_id)

    def test_c3_post_oi_nvs_binding_is_exact_and_observation_bound(self) -> None:
        original = private_result(C3_PROFILE, self.artifacts[C3_PROFILE])
        observation = {
            "raw_log_sha256": OI1_RAW_SHA256,
            "reset_to_service_advertisement_ms": [1000] * 10,
        }
        summary = GATE.validate_c3_result_for_observation(
            self.result_paths[C3_PROFILE],
            artifact_path=self.artifact_paths[C3_PROFILE],
            expected_version=VERSION,
            candidate_release_json_sha256=RELEASE_DIGEST,
            observation=observation,
        )
        self.assertNotIn("post_oi_nvs", summary)

        mutations = {
            "missing": lambda value: value.pop("post_oi_nvs"),
            "receipt-digest": lambda value: value["post_oi_nvs"].__setitem__(
                "receipt_sha256", "0" * 64
            ),
            "receipt-size": lambda value: value["post_oi_nvs"].__setitem__(
                "receipt_size_bytes", 0
            ),
            "release": lambda value: value["post_oi_nvs"]["summary"].__setitem__(
                "candidate_release_json_sha256", "0" * 64
            ),
            "firmware": lambda value: value["post_oi_nvs"]["summary"].__setitem__(
                "candidate_firmware_sha256", "0" * 64
            ),
            "raw": lambda value: value["post_oi_nvs"]["summary"].__setitem__(
                "oi1_raw_sha256", "0" * 64
            ),
            "resets": lambda value: value["post_oi_nvs"]["summary"].__setitem__(
                "reset_samples", 9
            ),
            "offset": lambda value: value["post_oi_nvs"]["summary"].__setitem__(
                "partition_offset", 0
            ),
            "size": lambda value: value["post_oi_nvs"]["summary"].__setitem__(
                "partition_size", 0x5000
            ),
            "integrity": lambda value: value["post_oi_nvs"]["summary"].__setitem__(
                "integrity", "failed"
            ),
            "phy": lambda value: value["post_oi_nvs"]["summary"].__setitem__(
                "written_namespaces", ["phy"]
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                changed = copy.deepcopy(original)
                mutate(changed)
                self.rewrite(C3_PROFILE, changed)
                with self.assertRaises(GATE.QualificationError):
                    self.validate(C3_PROFILE)

        self.rewrite(C3_PROFILE, original)
        for name, changed_observation in {
            "wrong-raw": {**observation, "raw_log_sha256": "0" * 64},
            "nine-resets": {
                **observation,
                "reset_to_service_advertisement_ms": [1000] * 9,
            },
        }.items():
            with self.subTest(observation=name):
                with self.assertRaises(GATE.QualificationError):
                    GATE.validate_c3_result_for_observation(
                        self.result_paths[C3_PROFILE],
                        artifact_path=self.artifact_paths[C3_PROFILE],
                        expected_version=VERSION,
                        candidate_release_json_sha256=RELEASE_DIGEST,
                        observation=changed_observation,
                    )

    def test_gate_sets_require_every_exact_gate_passed(self) -> None:
        for profile_id, gate_names in (
            (C3_PROFILE, C3_GATES),
            (PICO_PROFILE, PICO_GATES),
        ):
            original = private_result(profile_id, self.artifacts[profile_id])
            cases: dict[str, dict[str, object]] = {}
            missing = copy.deepcopy(original)
            missing["gates"].pop(gate_names[-1])
            cases["missing"] = missing
            extra = copy.deepcopy(original)
            extra["gates"]["unexpected"] = "passed"
            cases["extra"] = extra
            failed = copy.deepcopy(original)
            failed["gates"][gate_names[0]] = "failed"
            cases["failed"] = failed
            boolean = copy.deepcopy(original)
            boolean["gates"][gate_names[0]] = True
            cases["boolean"] = boolean
            for name, changed in cases.items():
                with self.subTest(profile_id=profile_id, mutation=name):
                    self.rewrite(profile_id, changed)
                    with self.assertRaises(GATE.QualificationError):
                        self.validate(profile_id)

    def test_top_level_shape_and_canonical_utf8_are_strict(self) -> None:
        for profile_id in (C3_PROFILE, PICO_PROFILE):
            original = private_result(profile_id, self.artifacts[profile_id])

            extra = copy.deepcopy(original)
            extra["device_serial"] = "private-device-identifier"
            self.rewrite(profile_id, extra)
            with self.subTest(profile_id=profile_id, mutation="extra-private-key"):
                with self.assertRaises(GATE.QualificationError):
                    self.validate(profile_id)

            missing = copy.deepcopy(original)
            missing.pop("status")
            self.rewrite(profile_id, missing)
            with self.subTest(profile_id=profile_id, mutation="missing-key"):
                with self.assertRaises(GATE.QualificationError):
                    self.validate(profile_id)

            self.rewrite(profile_id, original, canonical=False)
            with self.subTest(profile_id=profile_id, mutation="noncanonical"):
                with self.assertRaises(GATE.QualificationError):
                    self.validate(profile_id)

            self.result_paths[profile_id].write_bytes(b"{\"bad\":\xff}\n")
            self.result_paths[profile_id].chmod(0o600)
            with self.subTest(profile_id=profile_id, mutation="invalid-utf8"):
                with self.assertRaises(GATE.QualificationError):
                    self.validate(profile_id)

    def test_private_files_are_exclusive_regular_inputs_and_snapshots_bind_bytes(self) -> None:
        profile_id = C3_PROFILE
        result_path = self.result_paths[profile_id]
        original = private_result(profile_id, self.artifacts[profile_id])

        first = GATE.private_result_snapshot(result_path)
        changed = copy.deepcopy(original)
        changed["candidate_release_json_sha256"] = "cd" * 32
        self.rewrite(profile_id, changed)
        second = GATE.private_result_snapshot(result_path)
        self.assertNotEqual(first, second)

        self.rewrite(profile_id, original)
        result_path.chmod(0o644)
        with self.assertRaises(GATE.QualificationError):
            GATE.private_result_snapshot(result_path)

        result_path.chmod(0o600)
        linked = self.root / "linked-result.json"
        os.link(result_path, linked)
        with self.assertRaises(GATE.QualificationError):
            GATE.private_result_snapshot(result_path)
        linked.unlink()

        symlink = self.root / "symlink-result.json"
        symlink.symlink_to(result_path)
        with self.assertRaises(GATE.QualificationError):
            GATE.private_result_snapshot(symlink)

    def test_public_summary_revalidation_is_exact_and_private_free(self) -> None:
        forbidden = {
            "device_serial",
            "ble_address",
            "device_label",
            "operator_input",
            "raw_info",
            "console_bytes",
        }
        for profile_id in (C3_PROFILE, PICO_PROFILE):
            summary = self.validate(profile_id)
            validated = GATE.validate_public_summary(
                summary,
                artifact_path=self.artifact_paths[profile_id],
                expected_profile_id=profile_id,
                expected_version=VERSION,
                candidate_release_json_sha256=RELEASE_DIGEST,
            )
            self.assertIs(validated, summary)
            self.assertTrue(forbidden.isdisjoint(summary))

            for name, mutate in {
                "extra-private-key": lambda value: value.__setitem__(
                    "ble_address", "private-identity"
                ),
                "result-digest": lambda value: value.__setitem__(
                    "qualification_result_sha256", "0" * 64
                ),
                "partial-gates": lambda value: value["gates"].pop(
                    next(iter(value["gates"]))
                ),
            }.items():
                with self.subTest(profile_id=profile_id, mutation=name):
                    changed = copy.deepcopy(summary)
                    mutate(changed)
                    with self.assertRaises(GATE.QualificationError):
                        GATE.validate_public_summary(
                            changed,
                            artifact_path=self.artifact_paths[profile_id],
                            expected_profile_id=profile_id,
                            expected_version=VERSION,
                            candidate_release_json_sha256=RELEASE_DIGEST,
                        )


@unittest.skipUnless(RELEASE is not None, RELEASE_ERROR)
class V5SummaryBindingTests(unittest.TestCase):
    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 5,
            "candidate_release_json_sha256": RELEASE_DIGEST,
            "qualification_policy_sha256": "1" * 64,
            "qualification_policy": {"fixture": True},
            "records": [
                {
                    "profile_id": profile_id,
                    "profile_gate_summary": None,
                }
                for profile_id in PROFILE_ORDER
            ],
            "waveshare_lcd147b_qualification": None,
            "esp32_c3_qualification": None,
            "rpi_pico2_w_qualification": None,
        }

    def summaries(self) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        waveshare = {"schema_version": 1, "status": "passed"}
        c3 = private_result(C3_PROFILE, b"c3")
        c3.pop("post_oi_nvs")
        c3["qualification_result_sha256"] = "2" * 64
        pico = private_result(PICO_PROFILE, b"pico")
        pico["qualification_result_sha256"] = "3" * 64
        return waveshare, c3, pico

    def binder(self):
        binder = getattr(
            RELEASE,
            "_bind_v060_hil_qualification_summaries",
            None,
        )
        self.assertTrue(
            callable(binder),
            "v0.6 finalization needs one atomic three-summary binder",
        )
        return binder

    def test_binder_cross_checks_profile_rows_and_sets_top_summaries_atomically(self) -> None:
        payload = self.payload()
        waveshare, c3, pico = self.summaries()
        by_id = {record["profile_id"]: record for record in payload["records"]}
        by_id[C3_PROFILE]["profile_gate_summary"] = copy.deepcopy(c3["gates"])
        by_id[PICO_PROFILE]["profile_gate_summary"] = copy.deepcopy(pico["gates"])
        original = copy.deepcopy(payload)
        bound = self.binder()(
            payload,
            waveshare_lcd147b_summary=waveshare,
            esp32_c3_summary=c3,
            rpi_pico2_w_summary=pico,
            firmware_version=VERSION,
        )

        self.assertEqual(payload, original, "the completed operator input is immutable")
        self.assertEqual(bound["waveshare_lcd147b_qualification"], waveshare)
        self.assertEqual(bound["esp32_c3_qualification"], c3)
        self.assertEqual(bound["rpi_pico2_w_qualification"], pico)
        by_id = {record["profile_id"]: record for record in bound["records"]}
        self.assertEqual(by_id[C3_PROFILE]["profile_gate_summary"], c3["gates"])
        self.assertEqual(by_id[PICO_PROFILE]["profile_gate_summary"], pico["gates"])
        for profile_id in PROFILE_ORDER[:3]:
            self.assertIsNone(by_id[profile_id]["profile_gate_summary"])

    def test_binder_rejects_partial_changed_or_wrong_phase_inputs(self) -> None:
        binder = self.binder()
        waveshare, c3, pico = self.summaries()

        cases: dict[str, tuple[dict[str, object], object, object, object, str]] = {}
        cases["missing-c3"] = (self.payload(), waveshare, None, pico, VERSION)
        cases["missing-pico"] = (self.payload(), waveshare, c3, None, VERSION)
        cases["missing-waveshare"] = (self.payload(), None, c3, pico, VERSION)
        mismatched_gates = self.payload()
        mismatched_by_id = {
            record["profile_id"]: record
            for record in mismatched_gates["records"]
        }
        mismatched_by_id[C3_PROFILE]["profile_gate_summary"] = copy.deepcopy(
            c3["gates"]
        )
        mismatched_by_id[PICO_PROFILE]["profile_gate_summary"] = {
            "GP0": "passed",
            "GP1": "passed",
            "GP2": "failed",
        }
        cases["mismatched-record-gates"] = (
            mismatched_gates,
            waveshare,
            c3,
            pico,
            VERSION,
        )
        already_bound = self.payload()
        already_bound["esp32_c3_qualification"] = copy.deepcopy(c3)
        cases["already-bound"] = (already_bound, waveshare, c3, pico, VERSION)
        wrong_schema = self.payload()
        wrong_schema["schema_version"] = 4
        cases["wrong-schema"] = (wrong_schema, waveshare, c3, pico, VERSION)
        cases["wrong-version"] = (self.payload(), waveshare, c3, pico, "0.6.1")
        missing_record = self.payload()
        missing_record["records"] = missing_record["records"][:-1]
        cases["missing-record"] = (missing_record, waveshare, c3, pico, VERSION)

        for name, (payload, lcd_value, c3_value, pico_value, version) in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(RELEASE.ReleaseError):
                    binder(
                        payload,
                        waveshare_lcd147b_summary=lcd_value,
                        esp32_c3_summary=c3_value,
                        rpi_pico2_w_summary=pico_value,
                        firmware_version=version,
                    )


class FinalizerBindingTests(unittest.TestCase):
    """Exercise the finalizer seam without constructing or publishing real bytes."""

    def test_finalizer_requires_both_private_results_before_any_output(self) -> None:
        self.assertIsNotNone(GATE, GATE_ERROR)
        source = inspect.getsource(RELEASE.finalize_public_bundle)
        self.assertIn("esp32_c3_qualification_result", source)
        self.assertIn("rpi_pico2_w_qualification_result", source)
        self.assertNotIn("strict C3 and Pico private-result validators", source)

    def test_finalizer_source_snapshots_validates_binds_and_rechecks_both_inputs(self) -> None:
        self.assertIsNotNone(GATE, GATE_ERROR)
        source = inspect.getsource(RELEASE.finalize_public_bundle)
        required_calls = (
            "_V060_PROFILE_GATE.validate_result_file",
            "_V060_PROFILE_GATE.private_result_snapshot",
            "_bind_v060_hil_qualification_summaries",
        )
        for call in required_calls:
            with self.subTest(call=call):
                self.assertIn(call, source)
        self.assertGreaterEqual(
            source.count("_V060_PROFILE_GATE.private_result_snapshot"),
            4,
            "each C3/Pico input must be snapshotted before and after promotion",
        )

    def test_completion_and_finalizer_bind_c3_receipt_to_the_oi_observation(self) -> None:
        seam = "_V060_PROFILE_GATE.validate_c3_result_for_observation"
        self.assertIn(
            seam,
            inspect.getsource(RELEASE.create_hil_completion_fragment),
        )
        self.assertIn(seam, inspect.getsource(RELEASE.finalize_public_bundle))

    def test_public_tree_validator_revalidates_both_derived_summaries(self) -> None:
        source = inspect.getsource(RELEASE._validate_hil)
        self.assertIn("_V060_PROFILE_GATE.validate_public_summary", source)
        self.assertIn("esp32_c3_qualification", source)
        self.assertIn("rpi_pico2_w_qualification", source)

    def test_promotion_envelope_remains_exactly_three_administrative_files(self) -> None:
        self.assertEqual(
            RELEASE.PROMOTION_ENVELOPE,
            frozenset({"HIL_REPORT.md", "release.json", "SHA256SUMS"}),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
