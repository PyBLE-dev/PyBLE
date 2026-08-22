#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for generating the heterogeneous v0.6 license receipt.

Verification of a hand-assembled receipt is covered separately.  This suite
starts with an empty evidence destination and exercises the production
``audit_release_licenses`` entry point.  The expensive ESP observer is replaced
with a deterministic eight-role producer, but the production orchestration
must replay the extracted *full* ESP semantic verifier before it may compose
the seven independently observed RP2 roles.

All firmware, SPDX, source, and license bytes are synthetic.  No test result is
a legal review or release approval, and no network, build, or hardware resource
is used.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import test_release_v060_license_inventory as inventory_fixture


RELEASE = inventory_fixture.RELEASE
RELEASE_LOAD_ERROR = inventory_fixture.RELEASE_LOAD_ERROR
V060_PROFILE_ORDER = inventory_fixture.V060_PROFILE_ORDER
ESP_TARGETS = inventory_fixture.ESP_TARGETS
RP2_ROLES = inventory_fixture.RP2_ROLES
ESP_ROLES = ("application", "bootloader")
ESP_NOTICE = "Synthetic reviewed v0.6.0 notice fixture.\n"
FINAL_NOTICE = (
    "Synthetic reviewed v0.6.0 notice fixture.\n\n"
    "RP2 / Raspberry Pi Pico 2 W\n"
)


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def write_canonical_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def schema1_review_json_bytes(value: object) -> bytes:
    """Match the exact normalized serializer used by the ESP audit."""

    return (json.dumps(value, indent=2, sort_keys=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def semantic_source_closure(function: object) -> str:
    """Collect source reachable through same-module function calls."""

    pending = [function]
    seen: set[int] = set()
    source: list[str] = []
    while pending:
        current = pending.pop()
        if not callable(current) or id(current) in seen:
            continue
        seen.add(id(current))
        try:
            source.append(inspect.getsource(current))
        except (OSError, TypeError):
            pass
        code = getattr(current, "__code__", None)
        if code is None:
            continue
        for name in code.co_names:
            referenced = getattr(RELEASE, name, None)
            if inspect.isfunction(referenced) and referenced.__module__ == current.__module__:
                pending.append(referenced)
    return "\n".join(source)


class GenerationFixture:
    def __init__(self) -> None:
        self.base = inventory_fixture.V060LicenseFixture()
        self.root = self.base.root
        self.repo = self.base.repo
        self.build = self.base.build
        self.evidence = self.base.evidence
        self.rp2_observation = copy.deepcopy(self.base.rp2_observation)
        shutil.rmtree(self.evidence)
        excluded = self.repo / "firmware" / "licenses" / "excluded-cves.json"
        excluded.parent.mkdir(parents=True, exist_ok=True)
        excluded.write_text("{}\n", encoding="utf-8")
        self.excluded = excluded
        self.tool_lock = copy.deepcopy(self.base.tool_lock)
        self.tool_lock["inputs"].update(
            {
                "excluded_cves_path": "firmware/licenses/excluded-cves.json",
                "license_policy_path": "firmware/licenses/license-policy.json",
            }
        )
        self.policy = {"schema_version": 2}
        self.esp_generation_calls: list[Path] = []
        self.esp_review_sha256: dict[str, str] = {}

    def close(self) -> None:
        self.base.close()

    def generate_esp_evidence(self, **kwargs):
        """Model the already-tested schema-v2 ESP producer's persisted output."""

        evidence = Path(kwargs["evidence_dir"])
        self.esp_generation_calls.append(evidence)
        evidence.mkdir(parents=True)
        identities = []
        for profile_id in ESP_TARGETS:
            for role in ESP_ROLES:
                identities.append({"profile_id": profile_id, "role": role})
                raw = evidence / "raw" / ("%s--%s.spdx.tag" % (profile_id, role))
                reviewed = evidence / "spdx" / (
                    "%s--%s.spdx.json" % (profile_id, role)
                )
                raw.parent.mkdir(parents=True, exist_ok=True)
                reviewed.parent.mkdir(parents=True, exist_ok=True)
                raw.write_text(
                    "SPDXVersion: SPDX-2.2\n"
                    "DocumentName: synthetic-%s-%s\n" % (profile_id, role),
                    encoding="utf-8",
                )
                reviewed.write_bytes(
                    schema1_review_json_bytes(
                        {
                            "spdxVersion": "SPDX-2.3",
                            "name": "synthetic-%s-%s" % (profile_id, role),
                            "reviewNote": "Kungliga Tekniska Högskolan",
                        }
                    )
                )
                relative = reviewed.relative_to(evidence).as_posix()
                self.esp_review_sha256[relative] = sha256_path(reviewed)
        evidence_hashes = {
            path.relative_to(evidence).as_posix(): sha256_path(path)
            for path in sorted(evidence.rglob("*"))
            if path.is_file()
        }
        write_canonical_json(
            evidence / "audit-receipt.json",
            {
                "schema_version": 1,
                "notice_sha256": sha256_bytes(ESP_NOTICE.encode("utf-8")),
                "input_sha256": {"semantic/esp-v2": "5" * 64},
                "executed_artifacts": {"esp-idf-sbom": "6" * 64},
                "execution_identity": {"fixture": "network-isolated"},
                "identities": identities,
                "evidence_sha256": evidence_hashes,
            },
        )
        return {
            "third_party_licenses": ESP_NOTICE,
            "input_sha256": {"semantic/esp-v2": "5" * 64},
        }

    def audit(self, verifier_side_effect=None):
        verifier = getattr(RELEASE, "_audit_verify_esp_release_evidence", None)
        with (
            mock.patch.object(
                RELEASE,
                "_audit_load_tool_lock",
                return_value=self.tool_lock,
            ),
            mock.patch.object(
                RELEASE,
                "_audit_load_policy",
                return_value=self.policy,
            ),
            mock.patch.object(
                RELEASE,
                "_audit_release_licenses_v2",
                side_effect=self.generate_esp_evidence,
            ) as esp_generator,
            mock.patch.object(
                RELEASE,
                "_audit_verify_esp_release_evidence",
                create=verifier is None,
                side_effect=verifier_side_effect,
            ) as esp_verifier,
            mock.patch.object(
                RELEASE,
                "_audit_observe_rp2_license_inputs",
                return_value=copy.deepcopy(self.rp2_observation),
            ),
        ):
            result = RELEASE.audit_release_licenses(
                build_root=self.build,
                repo_root=self.repo,
                evidence_dir=self.evidence,
                runner=lambda *_args, **_kwargs: None,
            )
        return result, esp_generator, esp_verifier


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class FullEspReplayContractTests(unittest.TestCase):
    def test_extracted_esp_replay_retains_the_complete_semantic_verifier(self) -> None:
        verifier = getattr(RELEASE, "_audit_verify_esp_release_evidence", None)
        self.assertTrue(
            callable(verifier),
            "v0.6 generation needs an extracted full ESP semantic replay seam",
        )
        if not callable(verifier):
            return
        closure = semantic_source_closure(verifier)
        for required in (
            "_audit_observe_policy_v2_context",
            "_audit_validate_policy_v2",
            "_audit_v2_reviewed_documents",
            "_audit_v2_release_notice_records",
            "_audit_notice_v2",
        ):
            with self.subTest(required=required):
                self.assertIn(
                    required,
                    closure,
                    "ESP generation replay must not replace the existing semantic verifier",
                )


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class V060LicenseGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = GenerationFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def assert_canonical(self, path: Path) -> dict[str, object]:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
        self.assertEqual(path.read_bytes(), canonical_json_bytes(value))
        return value

    def semantic_replay(self, **kwargs) -> None:
        evidence = Path(kwargs["evidence_dir"])
        receipt = json.loads(
            (evidence / "audit-receipt.json").read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["schema_version"], 1)
        self.assertEqual(kwargs["notice"], ESP_NOTICE)
        self.assertEqual(
            len(list((evidence / "raw").glob("*.spdx.tag"))),
            8,
        )
        self.assertEqual(
            len(list((evidence / "spdx").glob("*.spdx.json"))),
            8,
        )

    def test_entrypoint_generates_the_exact_canonical_schema2_inventory(self) -> None:
        result, esp_generator, esp_verifier = self.fixture.audit(
            verifier_side_effect=self.semantic_replay,
        )

        esp_generator.assert_called_once()
        esp_verifier.assert_called_once()
        self.assertEqual(result["third_party_licenses"], FINAL_NOTICE)
        self.assertTrue(self.fixture.evidence.is_dir())

        receipt_path = self.fixture.evidence / "audit-receipt.json"
        inventory_path = self.fixture.evidence / "release-inventory.json"
        receipt = self.assert_canonical(receipt_path)
        inventory = self.assert_canonical(inventory_path)
        self.assertEqual(
            set(receipt),
            {
                "schema_version",
                "notice_sha256",
                "input_sha256",
                "executed_artifacts",
                "execution_identity",
                "identities",
                "evidence_sha256",
                "release_inventory_path",
                "release_inventory_sha256",
            },
        )
        self.assertEqual(receipt["schema_version"], 2)
        self.assertEqual(receipt["release_inventory_path"], "release-inventory.json")
        self.assertEqual(receipt["release_inventory_sha256"], sha256_path(inventory_path))
        self.assertEqual(
            receipt["notice_sha256"],
            sha256_bytes(FINAL_NOTICE.encode("utf-8")),
        )

        self.assertEqual(
            set(inventory),
            {
                "schema_version",
                "firmware_version",
                "profile_order",
                "notice_sha256",
                "profiles",
            },
        )
        self.assertEqual(inventory["schema_version"], 1)
        self.assertEqual(inventory["firmware_version"], "0.6.0")
        self.assertEqual(inventory["profile_order"], list(V060_PROFILE_ORDER))
        self.assertEqual(inventory["notice_sha256"], receipt["notice_sha256"])

        expected_identities = [
            {"profile_id": profile_id, "role": role}
            for profile_id in V060_PROFILE_ORDER[:-1]
            for role in ESP_ROLES
        ] + [
            {"profile_id": "rpi-pico2-w", "role": role}
            for role in RP2_ROLES
        ]
        self.assertEqual(receipt["identities"], expected_identities)

        expected_evidence = {
            "raw/%s--%s.spdx.tag" % (profile_id, role)
            for profile_id in V060_PROFILE_ORDER[:-1]
            for role in ESP_ROLES
        } | {
            "spdx/%s--%s.spdx.json" % (profile_id, role)
            for profile_id in V060_PROFILE_ORDER[:-1]
            for role in ESP_ROLES
        } | {
            "rp2/rpi-pico2-w--%s.json" % role for role in RP2_ROLES
        } | {"release-inventory.json"}
        self.assertEqual(set(receipt["evidence_sha256"]), expected_evidence)
        for relative, digest in receipt["evidence_sha256"].items():
            path = self.fixture.evidence / relative
            self.assertTrue(path.is_file(), relative)
            self.assertEqual(digest, sha256_path(path))
            if relative in self.fixture.esp_review_sha256:
                self.assertEqual(
                    digest,
                    self.fixture.esp_review_sha256[relative],
                    "%s was reserialized during v0.6 composition" % relative,
                )
            elif path.suffix == ".json":
                self.assert_canonical(path)

        self.assertEqual(len(inventory["profiles"]), 5)
        for profile, profile_id in zip(inventory["profiles"], V060_PROFILE_ORDER):
            target = (
                "rpi-pico2-w"
                if profile_id == "rpi-pico2-w"
                else ESP_TARGETS[profile_id]
            )
            self.assertEqual(profile["profile_id"], profile_id)
            self.assertEqual(profile["target"], target)
            provenance = self.fixture.build / target / "pyble-build-provenance.json"
            self.assertEqual(
                profile["build_provenance_sha256"],
                sha256_path(provenance),
            )

        pico = inventory["profiles"][-1]
        self.assertEqual(pico["resource_kind"], "rp2")
        self.assertEqual(
            [record["role"] for record in pico["roles"]],
            list(RP2_ROLES),
        )
        tinyusb_path = self.fixture.evidence / "rp2" / (
            "rpi-pico2-w--tinyusb.json"
        )
        tinyusb = self.assert_canonical(tinyusb_path)
        self.assertEqual(tinyusb["role"], "tinyusb")
        self.assertEqual(
            {record["kind"] for record in tinyusb["inputs"]},
            {"linked-source"},
        )
        self.assertTrue(
            any("tinyusb" in record["logical_path"] for record in tinyusb["inputs"])
        )
        self.assertTrue(
            any("tinyusb" in record["logical_path"] for record in tinyusb["license_inputs"])
        )

        # The generated bytes must satisfy the already-frozen heterogeneous
        # verifier without any test-side repair or receipt rehash.
        with (
            mock.patch.object(
                RELEASE,
                "_audit_load_tool_lock",
                return_value=self.fixture.tool_lock,
            ),
            mock.patch.object(
                RELEASE,
                "_audit_observe_rp2_license_inputs",
                return_value=copy.deepcopy(self.fixture.rp2_observation),
            ),
        ):
            verified = RELEASE._audit_verify_release_inventory_evidence(
                evidence_dir=self.fixture.evidence,
                build_root=self.fixture.build,
                repo_root=self.fixture.repo,
                notice=FINAL_NOTICE,
                firmware_version="0.6.0",
            )
        self.assertEqual(verified, inventory)

    def test_exact_esp_review_bytes_survive_cross_process_semantic_replay(self) -> None:
        self.fixture.audit(verifier_side_effect=self.semantic_replay)
        expected_path = self.fixture.root / "expected-esp-review-sha256.json"
        write_canonical_json(expected_path, self.fixture.esp_review_sha256)
        probe = r'''
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

script, evidence, build, repo, notice, expected_path = sys.argv[1:]
spec = importlib.util.spec_from_file_location("pyble_v060_replay_probe", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
expected = json.loads(Path(expected_path).read_text(encoding="utf-8"))

def verify_exact_esp_bytes(**kwargs):
    replay = Path(kwargs["evidence_dir"])
    for relative, digest in sorted(expected.items()):
        actual = hashlib.sha256((replay / relative).read_bytes()).hexdigest()
        module._require(
            actual == digest,
            "%s changed across v0.6 composition/replay" % relative,
        )

module._audit_verify_esp_release_evidence = verify_exact_esp_bytes
module._audit_verify_v060_esp_semantic_replay(
    notice=notice,
    evidence_dir=Path(evidence),
    build_root=Path(build),
    repo_root=Path(repo),
)
'''
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                probe,
                str(inventory_fixture.RELEASE_SCRIPT),
                str(self.fixture.evidence),
                str(self.fixture.build),
                str(self.fixture.repo),
                FINAL_NOTICE,
                str(expected_path),
            ],
            check=False,
            cwd=inventory_fixture.REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(
            completed.returncode,
            0,
            "separate-process ESP semantic replay failed:\n%s"
            % completed.stderr,
        )

    def test_semantic_replay_failure_publishes_no_partial_evidence(self) -> None:
        sentinel = RELEASE.ReleaseError("full ESP semantic replay sentinel")
        with self.assertRaisesRegex(
            RELEASE.ReleaseError,
            "full ESP semantic replay sentinel",
        ):
            self.fixture.audit(verifier_side_effect=sentinel)
        self.assertFalse(
            self.fixture.evidence.exists(),
            "failed semantic replay must not publish partial v0.6 evidence",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
