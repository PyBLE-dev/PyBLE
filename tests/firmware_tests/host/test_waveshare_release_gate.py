#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Host-only ADR-0024 private-result to public-release gate contract."""

import asyncio
import copy
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
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
    / "waveshare_lcd147b_release_gate.py"
)


def load_module(name, path):
    if not path.is_file():
        return None, "missing %s" % path
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None, "cannot construct import spec for %s" % path
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - surfaced by presence test.
        return None, "cannot import %s: %s" % (path, exc)
    return module, ""


RELEASE, RELEASE_ERROR = load_module("pyble_release_gate_release", RELEASE_PATH)
GATE, GATE_ERROR = load_module("pyble_waveshare_release_gate", GATE_PATH)
if RELEASE is not None and hasattr(RELEASE, "_WAVESHARE_LCD147B_GATE"):
    GATE = RELEASE._WAVESHARE_LCD147B_GATE
    GATE_ERROR = ""
COMBINED_TEST, COMBINED_TEST_ERROR = load_module(
    "pyble_release_gate_combined_fixture",
    HERE / "test_waveshare_boot_splash_bench.py",
)
BUNDLE_TEST, BUNDLE_TEST_ERROR = load_module(
    "pyble_release_gate_bundle_fixture",
    HERE / "test_release_bundle.py",
)
FINAL_TEST, FINAL_TEST_ERROR = load_module(
    "pyble_release_gate_finalization_fixture",
    HERE / "test_release_finalization.py",
)


def canonical_bytes(value):
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def production_app_evidence():
    artifact = {"status": 200, "size_bytes": 1024, "sha256": "1" * 64}
    return {
        "schema_version": 1,
        "app": copy.deepcopy(artifact),
        "qr": {
            "status": 200,
            "size_bytes": 2424,
            "sha256": (
                "4ab6c814a8526c4d69a3b330dc563298"
                "edf5bf7eadbea4babd262fa75568e305"
            ),
        },
        "flash": copy.deepcopy(artifact),
        "normalized_redirect": {
            "status": 308,
            "location": "/app?pyble_hil=1",
        },
        "link_facts": {
            "main_content": True,
            "testflight_href": True,
            "testflight_visible_fallback": True,
            "flash_href": True,
            "support_href": True,
            "qr_src": True,
        },
        "active_release_path": "/firmware/v0.4.2/release.json",
    }


def write_hil_report(path, payload, marker_version):
    prefix = (
        RELEASE.HIL_REPORT_SHELL_PREFIX
        if marker_version == 4
        else "# PyBLE firmware HIL report\n\n"
        "Machine-readable records are embedded below.\n\n"
    )
    path.write_text(
        prefix + "<!-- PYBLE_HIL_RECORDS_V%d\n" % marker_version
        + json.dumps(payload, indent=2, sort_keys=False)
        + "\n-->\n",
        encoding="utf-8",
    )


def upgrade_finalization_fixture_to_v050(fixture):
    """Move the synthetic finalization bundle to the exact V4 source era."""

    candidate = fixture.candidate
    for profile_id in RELEASE.RELEASE_PROFILE_ORDER:
        manifest_path = candidate / profile_id / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = "0.5.0"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )

    release_path = candidate / "release.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    release["identity"].update(
        version="0.5.0",
        tag="firmware-v0.5.0",
        agent_version="0.5.0",
    )
    release_path.write_text(
        json.dumps(release, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    pending = FINAL_TEST.read_hil_payload(candidate / "HIL_REPORT.md")
    pending["schema_version"] = 4
    pending["waveshare_lcd147b_qualification"] = None
    for record in pending["records"]:
        record["firmware_version"] = "0.5.0"
        record["tag"] = "firmware-v0.5.0"
    write_hil_report(candidate / "HIL_REPORT.md", pending, 4)
    FINAL_TEST.refresh_candidate_hashes(candidate)

    fixture.candidate_release_sha256 = hashlib.sha256(
        release_path.read_bytes()
    ).hexdigest()
    completed = BUNDLE_TEST.complete_hil_payload(
        pending,
        fixture.candidate_release_sha256,
    )
    write_hil_report(fixture.completed_hil, completed, 4)
    return completed


def firmware_measurement(firmware):
    payload = firmware.read_bytes()
    size_bytes = len(payload)
    candidate_sha256 = hashlib.sha256(payload).hexdigest()
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
    return {
        "sha256": candidate_sha256,
        "size_bytes": size_bytes,
        "attestation": attestation,
    }


async def make_result(firmware):
    """Generate the fixture through the real combined runner and strict validator."""

    if COMBINED_TEST is None:
        raise RuntimeError(COMBINED_TEST_ERROR)
    bench = COMBINED_TEST.bench
    measurement = firmware_measurement(firmware)
    connections = [
        COMBINED_TEST.CombinedFakeCentral(
            "candidate/setup-disabled",
            live_candidate_sha256=measurement["attestation"]["sha256"],
        ),
        COMBINED_TEST.CombinedFakeCentral("setup-disabled/setup-enabled"),
        COMBINED_TEST.CombinedFakeCentral("setup-enabled/exercise/cycle-1-arm"),
        COMBINED_TEST.CombinedFakeCentral("cycle-1/final-disable/cycle-2-arm"),
        COMBINED_TEST.CombinedFakeCentral("cycle-2/cycle-3-arm"),
        COMBINED_TEST.CombinedFakeCentral("cycle-3/final-proof"),
    ]
    connector = COMBINED_TEST.CombinedFakeConnector(connections)

    async def confirm_splash(_phase, _pattern, qr_url):
        return qr_url

    async def confirm_tft(_pattern):
        connector.last.visual_confirmed = True
        return True

    result = await bench.run_combined_qualification(
        connector,
        "private-input-only",
        COMBINED_TEST.preflight(),
        measurement["sha256"],
        measurement["size_bytes"],
        measurement["attestation"],
        timeout_s=2.0,
        poll_interval_s=0,
        production_app_probe=COMBINED_TEST.production_app_evidence,
        confirm_splash=confirm_splash,
        confirm_tft=confirm_tft,
        session_id="12" * 16,
    )
    if bench.validate_combined_qualification_result(result) is not result:
        raise AssertionError("combined production validator did not retain its result")
    return result


class PresenceTests(unittest.TestCase):
    def test_pure_release_gate_module_exists(self):
        self.assertIsNotNone(GATE, GATE_ERROR)
        if GATE is not None:
            self.assertTrue(callable(getattr(GATE, "validate_result_file", None)))
            self.assertTrue(callable(getattr(GATE, "validate_public_summary", None)))

    def test_finalize_api_and_cli_accept_private_result_path(self):
        self.assertIsNotNone(RELEASE, RELEASE_ERROR)
        function = getattr(RELEASE, "finalize_public_bundle", None)
        self.assertTrue(callable(function))
        self.assertIn(
            "waveshare_lcd147b_qualification_result",
            inspect.signature(function).parameters,
        )
        completed = subprocess.run(
            [sys.executable, os.fspath(RELEASE_PATH), "finalize-public", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(
            "--waveshare-lcd147b-qualification-result",
            completed.stdout,
        )

    def test_imported_validator_rejects_later_source_mutation(self):
        with tempfile.TemporaryDirectory(
            prefix="pyble-lcd147-source-"
        ) as temporary:
            root = Path(temporary)
            copied = (
                root
                / "firmware"
                / "qualification"
                / GATE_PATH.name
            )
            copied.parent.mkdir(parents=True)
            copied.write_bytes(GATE_PATH.read_bytes())
            isolated, error = load_module(
                "pyble_waveshare_release_gate_mutation_fixture",
                copied,
            )
            self.assertIsNotNone(isolated, error)
            copied.write_bytes(copied.read_bytes() + b"\n# changed after import\n")
            with self.assertRaises(isolated.QualificationError):
                isolated.validate_loaded_source(root)


@unittest.skipUnless(GATE is not None, "release-gate module is pending [green]")
class ResultValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pyble-lcd147-gate-")
        self.root = Path(self.temporary.name)
        self.firmware = self.root / "firmware.bin"
        payload = bytearray(b"B" * 0x12000)
        payload[0x9000:0x10000] = b"\xff" * 0x7000
        self.firmware.write_bytes(payload)
        self.candidate_release_digest = "ab" * 32
        self.result = asyncio.run(make_result(self.firmware))
        self.result_path = self.root / "qualification.json"
        self.write_result(self.result)

    def tearDown(self):
        self.temporary.cleanup()

    def write_result(self, value, *, canonical=True, mode=0o600):
        raw = canonical_bytes(value)
        if not canonical:
            raw = json.dumps(value).encode("utf-8")
        self.result_path.write_bytes(raw)
        self.result_path.chmod(mode)

    def validate(self):
        return GATE.validate_result_file(
            self.result_path,
            firmware_path=self.firmware,
            expected_version="0.5.0",
            candidate_release_json_sha256=self.candidate_release_digest,
            repo_root=REPO_ROOT,
        )

    def test_valid_result_returns_only_bound_public_summary(self):
        summary = self.validate()
        self.assertEqual(
            set(summary),
            {
                "schema_version",
                "status",
                "profile_id",
                "board_model",
                "firmware_version",
                "candidate_release_json_sha256",
                "candidate_firmware_sha256",
                "candidate_firmware_size_bytes",
                "candidate_attestation_sha256",
                "candidate_attestation_size_bytes",
                "production_app_evidence_sha256",
                "production_app_active_release_path",
                "terminal_record_sha256",
                "qualification_result_sha256",
            },
        )
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(
            summary["candidate_firmware_sha256"],
            hashlib.sha256(self.firmware.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            summary["candidate_release_json_sha256"],
            self.candidate_release_digest,
        )
        self.assertEqual(
            summary["qualification_result_sha256"],
            hashlib.sha256(self.result_path.read_bytes()).hexdigest(),
        )
        self.assertNotIn("session_id", summary)
        self.assertNotIn("production_app_evidence", summary)

    def test_exact_identity_and_candidate_bytes_are_release_blocking(self):
        mutations = {
            "status": lambda value: value.__setitem__("status", "pending"),
            "profile": lambda value: value.__setitem__("profile_id", "esp32-4mb"),
            "model": lambda value: value.__setitem__("board_model", "generic"),
            "version": lambda value: value.__setitem__("firmware_version", "0.5.1"),
            "full-hash": lambda value: value.__setitem__(
                "candidate_firmware_sha256", "0" * 64
            ),
            "size": lambda value: value.__setitem__(
                "candidate_firmware_size_bytes",
                value["candidate_firmware_size_bytes"] + 1,
            ),
            "attestation": lambda value: value["candidate_attestation"].__setitem__(
                "sha256", "0" * 64
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                value = copy.deepcopy(self.result)
                mutate(value)
                value["record_sha256"] = digest(
                    {key: item for key, item in value.items() if key != "record_sha256"}
                )
                self.write_result(value)
                with self.assertRaises(GATE.QualificationError):
                    self.validate()

    def test_production_app_and_terminal_chain_are_release_blocking(self):
        mutations = {
            "app": lambda value: value["production_app_evidence"][
                "link_facts"
            ].__setitem__("testflight_visible_fallback", False),
            "terminal": lambda value: value.__setitem__(
                "terminal_record_sha256", "0" * 64
            ),
            "predecessor": lambda value: value["records"][3].__setitem__(
                "predecessor_sha256", "0" * 64
            ),
            "result-digest": lambda value: value.__setitem__(
                "record_sha256", "0" * 64
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                value = copy.deepcopy(self.result)
                mutate(value)
                self.write_result(value)
                with self.assertRaises(GATE.QualificationError):
                    self.validate()

    def test_exclusive_writer_artifact_contract_is_enforced(self):
        self.write_result(self.result, mode=0o644)
        with self.assertRaises(GATE.QualificationError):
            self.validate()

        self.write_result(self.result, canonical=False)
        with self.assertRaises(GATE.QualificationError):
            self.validate()

        self.result_path.unlink()
        target = self.root / "target.json"
        target.write_bytes(canonical_bytes(self.result))
        target.chmod(0o600)
        self.result_path.symlink_to(target)
        with self.assertRaises(GATE.QualificationError):
            self.validate()

    def test_public_summary_rebinds_to_candidate_profile_and_firmware(self):
        summary = self.validate()
        validated = GATE.validate_public_summary(
            summary,
            firmware_path=self.firmware,
            expected_version="0.5.0",
            candidate_release_json_sha256=self.candidate_release_digest,
        )
        self.assertEqual(validated, summary)
        changed = copy.deepcopy(summary)
        changed["candidate_firmware_sha256"] = "0" * 64
        with self.assertRaises(GATE.QualificationError):
            GATE.validate_public_summary(
                changed,
                firmware_path=self.firmware,
                expected_version="0.5.0",
                candidate_release_json_sha256=self.candidate_release_digest,
            )

    def test_happy_fixture_and_release_gate_share_the_authoritative_validator(self):
        authoritative = COMBINED_TEST.bench.validate_combined_qualification_result
        self.assertIs(authoritative(self.result), self.result)
        self.assertEqual(self.validate()["status"], "passed")

    def test_fully_rehashed_semantic_tampering_fails_both_validators(self):
        mutations = {
            "boot-trace": lambda value: value["records"][2]["post_reboot"][
                "probe"
            ].__setitem__(
                "boot_evidence",
                [list(item) for item in COMBINED_TEST.bench.DISABLED_BOOT_EVIDENCE],
            ),
            "enable-action": lambda value: value["records"][2]["pre_reboot"][
                "enable"
            ].__setitem__("persisted", False),
            "tft-observation": lambda value: value["records"][3][
                "operator_observation"
            ].__setitem__("while_run_active", False),
            "resource-reclamation": lambda value: value[
                "resource_reclamation"
            ].__setitem__("framebuffer_reclaimed", False),
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                value = copy.deepcopy(self.result)
                mutate(value)
                value = COMBINED_TEST.rechain_combined_result(value)
                with self.assertRaises(COMBINED_TEST.bench.BenchError):
                    COMBINED_TEST.bench.validate_combined_qualification_result(value)
                self.write_result(value)
                with self.assertRaises(GATE.QualificationError):
                    self.validate()

    def test_bounded_strict_private_file_rejects_ambiguous_inputs(self):
        cases = {
            "empty": b"",
            "non-utf8": b"\xff\xfe",
            "oversize": b"x" * (4 * 1024 * 1024 + 1),
            "duplicate-key": b'{"schema_version":1,"schema_version":1}\n',
        }
        for name, raw in cases.items():
            with self.subTest(case=name):
                self.result_path.write_bytes(raw)
                self.result_path.chmod(0o600)
                with self.assertRaises(GATE.QualificationError):
                    self.validate()

        value = copy.deepcopy(self.result)
        value["raw_output"] = "must never enter a release"
        self.write_result(value)
        with self.assertRaises(GATE.QualificationError):
            self.validate()

        self.write_result(self.result)
        linked = self.root / "second-name.json"
        os.link(self.result_path, linked)
        with self.assertRaises(GATE.QualificationError):
            self.validate()


@unittest.skipUnless(
    RELEASE is not None and GATE is not None and FINAL_TEST is not None,
    "release finalization fixtures are unavailable",
)
class FinalizationIntegrationTests(unittest.TestCase):
    def setUp(self):
        FINAL_TEST.RELEASE = RELEASE
        self.fixture = FINAL_TEST.FinalizationFixture()
        upgrade_finalization_fixture_to_v050(self.fixture)
        self.result_path = self.fixture.license_fixture.root / "lcd147-result.json"
        self.result = asyncio.run(
            make_result(
                self.fixture.candidate
                / "waveshare-esp32-s3-lcd-147b"
                / "firmware.bin"
            )
        )
        self.result_path.write_bytes(canonical_bytes(self.result))
        self.result_path.chmod(0o600)

    def tearDown(self):
        self.fixture.close()

    def finalize(self, output, result_path=True):
        return RELEASE.finalize_public_bundle(
            candidate_dir=self.fixture.candidate,
            completed_hil_report=self.fixture.completed_hil,
            output_dir=output,
            candidate_release_json_sha256=self.fixture.candidate_release_sha256,
            license_evidence_dir=self.fixture.license_fixture.evidence,
            license_build_root=self.fixture.license_fixture.build_root,
            repo_root=self.fixture.license_fixture.repo,
            waveshare_lcd147b_qualification_result=(
                self.result_path if result_path else None
            ),
        )

    def test_v050_finalization_requires_and_consumes_exact_private_result(self):
        missing_output = self.fixture.license_fixture.root / "missing-result"
        with mock.patch.object(
            RELEASE,
            "_audit_verify_release_evidence",
            return_value=None,
        ), self.assertRaises(RELEASE.ReleaseError):
            self.finalize(missing_output, result_path=False)
        self.assertFalse(missing_output.exists())

        output = self.fixture.license_fixture.root / "public-v0.5.0"
        candidate_before = FINAL_TEST.tree_bytes(self.fixture.candidate)
        original_gate = GATE.validate_result_file
        with mock.patch.object(
            RELEASE,
            "_audit_verify_release_evidence",
            return_value=None,
        ), mock.patch.object(
            GATE,
            "validate_result_file",
            wraps=original_gate,
        ) as admitted:
            finalized = self.finalize(output)
        self.assertEqual(finalized, output)
        self.assertEqual(FINAL_TEST.tree_bytes(self.fixture.candidate), candidate_before)
        admitted.assert_called_once()
        call = admitted.call_args
        self.assertEqual(
            Path(call.kwargs["firmware_path"]),
            self.fixture.candidate
            / "waveshare-esp32-s3-lcd-147b"
            / "firmware.bin",
        )
        self.assertEqual(call.kwargs["expected_version"], "0.5.0")
        self.assertEqual(
            call.kwargs["candidate_release_json_sha256"],
            self.fixture.candidate_release_sha256,
        )

        public = FINAL_TEST.tree_bytes(finalized)
        changed = {
            relative
            for relative in candidate_before
            if candidate_before[relative] != public[relative]
        }
        self.assertEqual(changed, FINAL_TEST.PROMOTION_ENVELOPE)
        self.assertNotIn(self.result_path.name, public)
        self.assertNotIn(self.result_path.read_bytes(), public.values())
        payload = FINAL_TEST.read_hil_payload(finalized / "HIL_REPORT.md")
        self.assertEqual(payload["schema_version"], 4)
        summary = payload["waveshare_lcd147b_qualification"]
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(
            summary["candidate_release_json_sha256"],
            self.fixture.candidate_release_sha256,
        )
        profile = next(
            item
            for item in json.loads(
                (finalized / "release.json").read_text(encoding="utf-8")
            )["profiles"]
            if item["id"] == "waveshare-esp32-s3-lcd-147b"
        )
        self.assertEqual(
            summary["candidate_firmware_sha256"],
            profile["install"]["sha256"],
        )
        self.assertEqual(
            summary["candidate_firmware_size_bytes"],
            profile["install"]["size"],
        )

    def test_private_result_mutation_during_finalization_is_atomic(self):
        output = self.fixture.license_fixture.root / "result-toctou-output"
        original = GATE.validate_result_file

        def validate_then_mutate(*args, **kwargs):
            summary = original(*args, **kwargs)
            changed = copy.deepcopy(self.result)
            changed["record_sha256"] = "0" * 64
            replacement = canonical_bytes(changed)
            self.assertEqual(len(replacement), self.result_path.stat().st_size)
            self.result_path.write_bytes(replacement)
            self.result_path.chmod(0o600)
            return summary

        with mock.patch.object(
            RELEASE,
            "_audit_verify_release_evidence",
            return_value=None,
        ), mock.patch.object(
            GATE,
            "validate_result_file",
            side_effect=validate_then_mutate,
        ), self.assertRaises(RELEASE.ReleaseError):
            self.finalize(output)
        self.assertFalse(output.exists())

    def test_private_data_outside_hil_marker_is_rejected_atomically(self):
        output = self.fixture.license_fixture.root / "outside-marker-output"
        injected = self.fixture.license_fixture.root / "injected-HIL_REPORT.md"
        injected.write_text(
            self.fixture.completed_hil.read_text(encoding="utf-8")
            + "\nprivate session_id=%s raw_output=device-secret\n"
            % self.result["session_id"],
            encoding="utf-8",
        )
        with mock.patch.object(
            RELEASE,
            "_audit_verify_release_evidence",
            return_value=None,
        ), self.assertRaises(RELEASE.ReleaseError):
            RELEASE.finalize_public_bundle(
                candidate_dir=self.fixture.candidate,
                completed_hil_report=injected,
                output_dir=output,
                candidate_release_json_sha256=(
                    self.fixture.candidate_release_sha256
                ),
                license_evidence_dir=self.fixture.license_fixture.evidence,
                license_build_root=self.fixture.license_fixture.build_root,
                repo_root=self.fixture.license_fixture.repo,
                waveshare_lcd147b_qualification_result=self.result_path,
            )
        self.assertFalse(output.exists())

    def test_private_session_inside_public_hil_string_is_rejected_atomically(self):
        output = self.fixture.license_fixture.root / "embedded-session-output"
        injected = self.fixture.license_fixture.root / "embedded-session-HIL.md"
        payload = FINAL_TEST.read_hil_payload(self.fixture.completed_hil)
        payload["records"][0]["redacted_console_log"] += (
            " session_id=%s" % self.result["session_id"]
        )
        write_hil_report(injected, payload, 4)
        with mock.patch.object(
            RELEASE,
            "_audit_verify_release_evidence",
            return_value=None,
        ), self.assertRaises(RELEASE.ReleaseError):
            RELEASE.finalize_public_bundle(
                candidate_dir=self.fixture.candidate,
                completed_hil_report=injected,
                output_dir=output,
                candidate_release_json_sha256=(
                    self.fixture.candidate_release_sha256
                ),
                license_evidence_dir=self.fixture.license_fixture.evidence,
                license_build_root=self.fixture.license_fixture.build_root,
                repo_root=self.fixture.license_fixture.repo,
                waveshare_lcd147b_qualification_result=self.result_path,
            )
        self.assertFalse(output.exists())

    def test_ble_address_and_label_inside_public_log_are_rejected_atomically(self):
        output = self.fixture.license_fixture.root / "embedded-ble-output"
        injected = self.fixture.license_fixture.root / "embedded-ble-HIL.md"
        payload = FINAL_TEST.read_hil_payload(self.fixture.completed_hil)
        payload["records"][0]["redacted_console_log"] += (
            " BLE address AA:BB:CC:DD:EE:FF; label=Alice"
        )
        write_hil_report(injected, payload, 4)
        with mock.patch.object(
            RELEASE,
            "_audit_verify_release_evidence",
            return_value=None,
        ), self.assertRaises(RELEASE.ReleaseError):
            RELEASE.finalize_public_bundle(
                candidate_dir=self.fixture.candidate,
                completed_hil_report=injected,
                output_dir=output,
                candidate_release_json_sha256=(
                    self.fixture.candidate_release_sha256
                ),
                license_evidence_dir=self.fixture.license_fixture.evidence,
                license_build_root=self.fixture.license_fixture.build_root,
                repo_root=self.fixture.license_fixture.repo,
                waveshare_lcd147b_qualification_result=self.result_path,
            )
        self.assertFalse(output.exists())

    def test_uppercase_hyphen_ble_identity_is_rejected_atomically(self):
        output = self.fixture.license_fixture.root / "uppercase-ble-output"
        injected = self.fixture.license_fixture.root / "uppercase-ble-HIL.md"
        payload = FINAL_TEST.read_hil_payload(self.fixture.completed_hil)
        payload["records"][0]["redacted_console_log"] += (
            " BLE Address AA-BB-CC-DD-EE-FF; Label=Alice"
        )
        write_hil_report(injected, payload, 4)
        with mock.patch.object(
            RELEASE,
            "_audit_verify_release_evidence",
            return_value=None,
        ), self.assertRaises(RELEASE.ReleaseError):
            RELEASE.finalize_public_bundle(
                candidate_dir=self.fixture.candidate,
                completed_hil_report=injected,
                output_dir=output,
                candidate_release_json_sha256=(
                    self.fixture.candidate_release_sha256
                ),
                license_evidence_dir=self.fixture.license_fixture.evidence,
                license_build_root=self.fixture.license_fixture.build_root,
                repo_root=self.fixture.license_fixture.repo,
                waveshare_lcd147b_qualification_result=self.result_path,
            )
        self.assertFalse(output.exists())


@unittest.skipUnless(RELEASE is not None, "release script is unavailable")
class SourceEraTests(unittest.TestCase):
    def test_v042_remains_outside_the_new_gate_and_v050_is_inside(self):
        capable = getattr(RELEASE, "_waveshare_lcd147b_capable_version", None)
        self.assertTrue(callable(capable))
        self.assertFalse(capable("0.4.2"))
        self.assertTrue(capable("0.5.0"))
        self.assertTrue(capable("0.5.0-rc.1"))
        self.assertTrue(capable("1.0.0"))

    def test_historical_v2_and_capable_v4_are_exact_separate_eras(self):
        self.assertIsNotNone(BUNDLE_TEST, BUNDLE_TEST_ERROR)
        fixture = BUNDLE_TEST.ReleaseFixture()
        try:
            bundle = fixture.make_bundle(public=False)
            release = json.loads((bundle / "release.json").read_text(encoding="utf-8"))
            policy = json.loads(
                fixture.qualification_policy_path.read_text(encoding="utf-8")
            )
            policy_sha256 = hashlib.sha256(
                fixture.qualification_policy_path.read_bytes()
            ).hexdigest()
            provenance = {"pyble": {"commit": "1" * 40}}
            old_report = RELEASE._candidate_hil_report(
                "0.4.2",
                provenance,
                release["profiles"],
                policy,
                policy_sha256,
                bundle,
            )
            new_report = RELEASE._candidate_hil_report(
                "0.5.0",
                provenance,
                release["profiles"],
                policy,
                policy_sha256,
                bundle,
            )
        finally:
            fixture.cleanup()

        self.assertIn("PYBLE_HIL_RECORDS_V2", old_report)
        self.assertNotIn("waveshare_lcd147b_qualification", old_report)
        self.assertIn("PYBLE_HIL_RECORDS_V4", new_report)
        new_payload = RELEASE._parse_hil_report(new_report)
        self.assertEqual(new_payload["schema_version"], 4)
        self.assertIsNone(new_payload["waveshare_lcd147b_qualification"])
        with self.assertRaises(RELEASE.ReleaseError):
            RELEASE._validate_hil_source_era(
                RELEASE._parse_hil_report(old_report),
                "0.5.0",
            )
        self.assertEqual(
            RELEASE._validate_hil_source_era(
                RELEASE._parse_hil_report(old_report),
                "0.4.2",
            )["schema_version"],
            2,
        )
        old_marker = RELEASE.HIL_MARKER_RE.search(old_report)
        self.assertIsNotNone(old_marker)
        alternate_shell = (
            "# Retained v0.4.2 operator report\n\n"
            + old_marker.group(0)
            + "\nHistorical sign-off text remains replayable.\n"
        )
        self.assertEqual(
            RELEASE._parse_hil_report(alternate_shell),
            RELEASE._parse_hil_report(old_report),
        )

    def test_v4_summary_transition_is_null_to_derived_pass_only(self):
        capable = getattr(RELEASE, "_bind_waveshare_lcd147b_hil_summary", None)
        self.assertTrue(callable(capable))
        pending = {
            "schema_version": 4,
            "candidate_release_json_sha256": "ab" * 32,
            "qualification_policy_sha256": "cd" * 32,
            "qualification_policy": {},
            "records": [],
            "waveshare_lcd147b_qualification": None,
        }
        summary = {
            "schema_version": 1,
            "status": "passed",
            "qualification_result_sha256": "ef" * 32,
        }
        completed = capable(pending, summary, firmware_version="0.5.0")
        self.assertIsNone(pending["waveshare_lcd147b_qualification"])
        self.assertEqual(completed["waveshare_lcd147b_qualification"], summary)
        with self.assertRaises(RELEASE.ReleaseError):
            capable(completed, summary, firmware_version="0.5.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
