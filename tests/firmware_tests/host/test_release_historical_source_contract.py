#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Preserve the exact source-era release contract when the current
# canonical release tool revalidates the retained v0.4.2 checkout.

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
BASE_TEST = HERE / "test_release_bundle.py"
POLICY_INTEGRATION_TEST = HERE / "test_release_license_policy_v2_integration.py"


def _load_base_module():
    spec = importlib.util.spec_from_file_location(
        "pyble_historical_release_contract_fixture",
        BASE_TEST,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load release-bundle fixture module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def _load_policy_integration_module():
    spec = importlib.util.spec_from_file_location(
        "pyble_historical_manifest_proof_fixture",
        POLICY_INTEGRATION_TEST,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load policy-v2 integration fixture module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


BASE = _load_base_module()
RELEASE = BASE.RELEASE
RELEASE_LOAD_ERROR = BASE.RELEASE_LOAD_ERROR

PUBLIC_BASELINE_PREFIX = "docs/validation/firmware/oi1"
HISTORICAL_SOURCE_COMMIT = "2f38c43838b0f8cfbd10fab8e6561ae523927968"
CURRENT_SOURCE_COMMIT = "4444444444444444444444444444444444444444"
LEGACY_DERIVATION = {
    "application_image": "exact-byte-identical-two-root-v1",
    "application_headroom": "factory-minus-application-v1",
    "heap_floor": "floor-min-1024-v1",
    "boot_ceiling": "ceil-max-10-v1",
    "goodput_floor": "floor-min-100-v1",
}
CURRENT_DERIVATION = {
    "application_image": "exact-byte-identical-two-root-v1",
    "application_headroom": "factory-minus-application-v1",
    "heap_floor": "floor-min-1024-v1",
    "boot_ceiling": "fixed-product-slo-3000-v3",
    "goodput_floor": "floor-95pct-min-100-v2",
}
HISTORICAL_V042_PROFILE_ORDER = ("esp32-4mb", "esp32-s3-n16r8")
CURRENT_PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
    "waveshare-esp32-s3-lcd-147b",
)
GENERIC_S3_PROFILE_ID = "esp32-s3-n16r8"
WAVESHARE_PROFILE_ID = "waveshare-esp32-s3-lcd-147b"
WAVESHARE_TARGET = "waveshare-esp32-s3-lcd-147b"
DISPLAY_DESTINATIONS = ("pyble_st7789.py", "pyble_waveshare_lcd147b.py")


def _fixture_transfer_link_facts(profile_id: str) -> dict:
    source_profile = (
        GENERIC_S3_PROFILE_ID
        if profile_id == WAVESHARE_PROFILE_ID
        else profile_id
    )
    facts = copy.deepcopy(BASE.fixture_transfer_link_facts(source_profile))
    facts["phy"]["required_2m"] = profile_id in (
        GENERIC_S3_PROFILE_ID,
        WAVESHARE_PROFILE_ID,
    )
    return facts


def _write_versions_lock(repo: Path, version: str) -> None:
    path = repo / "firmware" / "versions.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """[micropython]
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
"""
        % version,
        encoding="utf-8",
    )


def _install_policy(
    repo: Path,
    version: str,
    source_commit: str,
    *,
    derivation_version: str | None = None,
) -> dict:
    _write_versions_lock(repo, version)
    current_era = (
        RELEASE._firmware_release_core(version, "fixture version")
        >= (0, 5, 0)
    )
    profile_order = (
        CURRENT_PROFILE_ORDER if current_era else HISTORICAL_V042_PROFILE_ORDER
    )
    source_policy_path = (
        REPO_ROOT / "firmware" / "qualification" / "oi1-gates.json"
    )
    policy = json.loads(source_policy_path.read_text(encoding="utf-8"))
    source_baseline = REPO_ROOT / policy["baseline_evidence"]["path"]
    baseline_relative = "%s/%s.json" % (
        PUBLIC_BASELINE_PREFIX,
        source_commit,
    )
    baseline = repo / baseline_relative
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline_document = json.loads(source_baseline.read_text(encoding="utf-8"))
    baseline_document["schema_version"] = 1
    baseline_document["measurement_contract"] = "oi1-pre-v1-v1"
    baseline_document["source_commit"] = source_commit
    baseline_document["firmware_version"] = (
        "0.5.0" if current_era
        else "0.4.1"
    )
    baseline_by_id = {
        item["profile_id"]: copy.deepcopy(item)
        for item in baseline_document["profiles"]
    }
    if current_era and WAVESHARE_PROFILE_ID not in baseline_by_id:
        waveshare = copy.deepcopy(baseline_by_id[GENERIC_S3_PROFILE_ID])
        waveshare.update(
            profile_id=WAVESHARE_PROFILE_ID,
            target=WAVESHARE_TARGET,
            board_model="Fixture Waveshare ESP32-S3-LCD-1.47B",
            module_marking="ESP32-S3-LCD-1.47B",
            firmware_sha256=hashlib.sha256(
                b"fixture waveshare firmware"
            ).hexdigest(),
            manifest_sha256=hashlib.sha256(
                b"fixture waveshare manifest"
            ).hexdigest(),
        )
        baseline_by_id[WAVESHARE_PROFILE_ID] = waveshare
    baseline_document["profile_order"] = list(profile_order)
    baseline_document["profiles"] = [
        baseline_by_id[profile_id] for profile_id in profile_order
    ]
    for profile in baseline_document["profiles"]:
        profile.pop("resource_kind", None)
        profile["firmware_sha256"] = profile.pop("install_sha256")
        profile.pop("resource_image_sha256", None)
        observation = profile["oi1_observation"]
        if current_era:
            observation["transfer_link_facts"] = (
                _fixture_transfer_link_facts(profile["profile_id"])
            )
        else:
            observation.pop("transfer_link_facts", None)
    baseline.write_bytes(BASE.canonical_json_bytes(baseline_document))
    policy["baseline_evidence"] = {
        "path": baseline_relative,
        "sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
    }
    policy["qualification_scope"] = "pre-v1"
    policy["deferred_profiles"] = ["esp32-c3-4mb"]
    policy["workload"] = copy.deepcopy(RELEASE.QUALIFICATION_WORKLOAD)
    selected_version = derivation_version or version
    selected_core = RELEASE._firmware_release_core(
        selected_version,
        "fixture derivation version",
    )
    policy["derivation"] = copy.deepcopy(
        CURRENT_DERIVATION if selected_core >= (0, 5, 0) else LEGACY_DERIVATION
    )
    policy_by_id = {
        item["profile_id"]: copy.deepcopy(item)
        for item in policy["profiles"]
    }
    if current_era and WAVESHARE_PROFILE_ID not in policy_by_id:
        waveshare_policy = copy.deepcopy(policy_by_id[GENERIC_S3_PROFILE_ID])
        waveshare_policy.update(
            profile_id=WAVESHARE_PROFILE_ID,
            target=WAVESHARE_TARGET,
        )
        policy_by_id[WAVESHARE_PROFILE_ID] = waveshare_policy
    policy["schema_version"] = 2 if current_era else 1
    policy["profile_order"] = list(profile_order)
    policy["profiles"] = [policy_by_id[profile_id] for profile_id in profile_order]
    for entry in policy["profiles"]:
        entry.pop("resource_kind", None)
        entry.pop("transport", None)
    baseline_by_id = {
        item["profile_id"]: item for item in baseline_document["profiles"]
    }
    for entry in policy["profiles"]:
        baseline_profile = baseline_by_id[entry["profile_id"]]
        entry["thresholds"] = BASE.fixture_oi1_thresholds(
            baseline_profile["oi1_build"],
            baseline_profile["oi1_observation"],
            selected_version,
        )
    BASE.write_json(
        repo / "firmware" / "qualification" / "oi1-gates.json",
        policy,
    )
    return policy


def _install_current_waveshare_sources(
    repo: Path,
) -> tuple[Path, dict[str, Path]]:
    settings = RELEASE.FROZEN_TARGET_SETTINGS[WAVESHARE_TARGET]
    board = (
        repo
        / "firmware"
        / "upstream"
        / "micropython"
        / "ports"
        / "esp32"
        / "boards"
        / settings["board"]
    )
    board.mkdir(parents=True, exist_ok=True)
    selections = {}
    for destination, contract in sorted(
        RELEASE._AUDIT_FIRST_PARTY_FROZEN_SOURCES.items()
    ):
        source = REPO_ROOT / contract["canonical_path"]
        canonical = repo / contract["canonical_path"]
        canonical.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, canonical)
        shutil.copyfile(source, board / destination)
        selections[destination] = canonical
    return board, selections


def _manifest_evidence_fixture(
    repo: Path,
    version: str,
    *,
    include_first_party_field: bool,
) -> list[dict]:
    """Create the smallest real-file-backed three-target evidence fixture."""

    _write_versions_lock(repo, version)
    generator_relatives = (
        "firmware/upstream/micropython/mpy-cross/mpy_cross/__init__.py",
        "firmware/upstream/micropython/py/makeqstrdata.py",
        "firmware/upstream/micropython/tools/makemanifest.py",
        "firmware/upstream/micropython/tools/manifestfile.py",
        "firmware/upstream/micropython/tools/mpy-tool.py",
    )
    for relative in generator_relatives:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# synthetic generator\n", encoding="utf-8")
    generators = [
        {
            "path": relative,
            "sha256": BASE.sha256_path(repo / relative),
        }
        for relative in generator_relatives
    ]
    mpy_cross_relative = (
        "firmware/upstream/micropython/mpy-cross/build/mpy-cross"
    )
    mpy_cross = repo / mpy_cross_relative
    mpy_cross.parent.mkdir(parents=True, exist_ok=True)
    mpy_cross.write_bytes(b"synthetic mpy-cross\n")

    base_relative = "firmware/python_modules/source_era_fixture.py"
    base_source = repo / base_relative
    base_source.parent.mkdir(parents=True, exist_ok=True)
    base_source.write_text(
        "# SPDX-License-Identifier: MIT\nVALUE = 1\n",
        encoding="utf-8",
    )
    if version == "0.5.0":
        for contract in RELEASE._AUDIT_FIRST_PARTY_FROZEN_SOURCES.values():
            canonical = repo / contract["canonical_path"]
            canonical.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / contract["canonical_path"], canonical)

    records = []
    targets = sorted(
        target
        for _profile_id, target, _idf_target in RELEASE.LICENSE_AUDIT_PROFILES
    )
    for target in targets:
        settings = RELEASE.FROZEN_TARGET_SETTINGS[target]
        board = (
            repo
            / "firmware"
            / "upstream"
            / "micropython"
            / "ports"
            / "esp32"
            / "boards"
            / settings["board"]
        )
        board.mkdir(parents=True, exist_ok=True)
        manifest = board / "manifest.py"
        manifest.write_text("# synthetic manifest\n", encoding="utf-8")
        selections = [
            {
                "destination": "source_era_fixture.py",
                "source_path": base_relative,
                "sha256": BASE.sha256_path(base_source),
                "optimization": None,
                "metadata_version": None,
            }
        ]
        if version == "0.5.0" and target == WAVESHARE_TARGET:
            for destination, contract in sorted(
                RELEASE._AUDIT_FIRST_PARTY_FROZEN_SOURCES.items()
            ):
                canonical = repo / contract["canonical_path"]
                shutil.copyfile(canonical, board / destination)
                selections.append(
                    {
                        "destination": destination,
                        "source_path": contract["canonical_path"],
                        "sha256": BASE.sha256_path(canonical),
                        "optimization": None,
                        "metadata_version": None,
                    }
                )
        selections.sort(key=lambda item: item["destination"])
        selected_paths = {
            item["destination"]: repo / item["source_path"]
            for item in selections
        }
        first_party = RELEASE._audit_first_party_frozen_source_evidence(
            repo_root=repo,
            target=target,
            board_dir=board,
            selections=selected_paths,
        )
        record = {
            "target": target,
            "architecture": settings["architecture"],
            "frozen_content_sha256": hashlib.sha256(
                ("frozen/%s" % target).encode()
            ).hexdigest(),
            "qstrdefs_sha256": hashlib.sha256(
                ("qstr/%s" % target).encode()
            ).hexdigest(),
            "mpy_cross": {
                "path": mpy_cross_relative,
                "sha256": BASE.sha256_path(mpy_cross),
            },
            "generator_tools": copy.deepcopy(generators),
            "frozen_mpy": [
                {
                    "destination": item["destination"][:-3] + ".mpy",
                    "sha256": hashlib.sha256(
                        ("mpy/%s/%s" % (target, item["destination"])).encode()
                    ).hexdigest(),
                }
                for item in selections
            ],
            "linked_frozen_object": {
                "component": "main",
                "archive_path": "%s/esp-idf/main/libmain.a" % target,
                "member": "frozen_content.c.obj",
                "sha256": hashlib.sha256(
                    ("linked/%s" % target).encode()
                ).hexdigest(),
            },
            "generated_board_manifest": manifest.relative_to(repo).as_posix(),
            "manifests": [
                {
                    "path": manifest.relative_to(repo).as_posix(),
                    "sha256": BASE.sha256_path(manifest),
                }
            ],
            "selections": selections,
        }
        if include_first_party_field:
            record["first_party_frozen_sources"] = first_party
        records.append(record)
    return records


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class QualificationPolicySourceEraTests(unittest.TestCase):
    def _load(
        self,
        version: str,
        source_commit: str,
        *,
        derivation_version: str | None = None,
    ):
        with tempfile.TemporaryDirectory(
            prefix="pyble-release-source-era-policy-"
        ) as temporary:
            repo = Path(temporary) / "repo"
            _install_policy(
                repo,
                version,
                source_commit,
                derivation_version=derivation_version,
            )
            return RELEASE._load_qualification_policy(repo)[0]

    def test_v042_uses_its_historical_source_scoped_public_baseline_path(self):
        policy = self._load("0.4.2", HISTORICAL_SOURCE_COMMIT)
        self.assertEqual(policy["schema_version"], 1)
        self.assertEqual(
            policy["profile_order"],
            list(HISTORICAL_V042_PROFILE_ORDER),
        )
        self.assertEqual(
            [entry["profile_id"] for entry in policy["profiles"]],
            list(HISTORICAL_V042_PROFILE_ORDER),
        )
        self.assertEqual(
            policy["baseline_evidence"]["path"],
            "%s/%s.json"
            % (PUBLIC_BASELINE_PREFIX, HISTORICAL_SOURCE_COMMIT),
        )

    def test_pre_v1_fixtures_are_independent_of_checked_in_policy_schema(self):
        for version, source_commit, schema_version, profile_order in (
            (
                "0.4.2",
                HISTORICAL_SOURCE_COMMIT,
                1,
                HISTORICAL_V042_PROFILE_ORDER,
            ),
            ("0.5.0", CURRENT_SOURCE_COMMIT, 2, CURRENT_PROFILE_ORDER),
        ):
            with self.subTest(version=version):
                policy = self._load(version, source_commit)
                self.assertEqual(policy["schema_version"], schema_version)
                self.assertEqual(policy["qualification_scope"], "pre-v1")
                self.assertEqual(policy["profile_order"], list(profile_order))
                self.assertEqual(
                    policy["deferred_profiles"],
                    ["esp32-c3-4mb"],
                )
                self.assertTrue(
                    all(
                        set(entry) == {"profile_id", "target", "thresholds"}
                        for entry in policy["profiles"]
                    )
                )

    def test_v050_uses_its_current_source_scoped_public_baseline_path(self):
        policy = self._load("0.5.0", CURRENT_SOURCE_COMMIT)
        self.assertEqual(policy["schema_version"], 2)
        self.assertEqual(policy["profile_order"], list(CURRENT_PROFILE_ORDER))
        self.assertEqual(
            [entry["profile_id"] for entry in policy["profiles"]],
            list(CURRENT_PROFILE_ORDER),
        )
        self.assertEqual(
            policy["baseline_evidence"]["path"],
            "%s/%s.json" % (PUBLIC_BASELINE_PREFIX, CURRENT_SOURCE_COMMIT),
        )
        self.assertNotEqual(
            policy["baseline_evidence"]["path"],
            "%s/%s.json"
            % (PUBLIC_BASELINE_PREFIX, HISTORICAL_SOURCE_COMMIT),
        )

    def test_each_source_era_rejects_the_other_derivation_revision(self):
        with self.assertRaises(RELEASE.ReleaseError):
            self._load(
                "0.4.2",
                HISTORICAL_SOURCE_COMMIT,
                derivation_version="0.5.0",
            )
        with self.assertRaises(RELEASE.ReleaseError):
            self._load(
                "0.5.0",
                CURRENT_SOURCE_COMMIT,
                derivation_version="0.4.2",
            )

    def test_v050_rejects_the_superseded_v2_derivation_revision(self):
        with tempfile.TemporaryDirectory(
            prefix="pyble-release-v050-v2-policy-"
        ) as temporary:
            repo = Path(temporary) / "repo"
            policy = _install_policy(
                repo,
                "0.5.0",
                CURRENT_SOURCE_COMMIT,
            )
            policy["derivation"] = copy.deepcopy(
                RELEASE.QUALIFICATION_DERIVATION_V2
            )
            BASE.write_json(
                repo / "firmware" / "qualification" / "oi1-gates.json",
                policy,
            )
            with self.assertRaisesRegex(
                RELEASE.ReleaseError,
                "derivation does not match the firmware source era",
            ):
                RELEASE._load_qualification_policy(repo)


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class QualificationObservationSourceEraTests(unittest.TestCase):
    def test_v042_omits_link_facts_and_rejects_the_v050_field(self):
        for profile_id in HISTORICAL_V042_PROFILE_ORDER:
            with self.subTest(profile_id=profile_id):
                historical = BASE.fixture_oi1_observation()
                RELEASE._validate_qualification_observation(
                    historical,
                    None,
                    profile_id,
                    firmware_version="0.4.2",
                )
                historical["transfer_link_facts"] = (
                    _fixture_transfer_link_facts(profile_id)
                )
                with self.assertRaises(RELEASE.ReleaseError):
                    RELEASE._validate_qualification_observation(
                        historical,
                        None,
                        profile_id,
                        firmware_version="0.4.2",
                    )

    def test_v050_requires_2m_link_facts_for_both_s3_profiles(self):
        for profile_id in CURRENT_PROFILE_ORDER:
            with self.subTest(profile_id=profile_id):
                observation = BASE.fixture_oi1_observation()
                observation["transfer_link_facts"] = (
                    _fixture_transfer_link_facts(profile_id)
                )
                normalized = RELEASE._validate_qualification_observation(
                    observation,
                    None,
                    profile_id,
                    firmware_version="0.5.0",
                )
                expected_2m = profile_id in (
                    GENERIC_S3_PROFILE_ID,
                    WAVESHARE_PROFILE_ID,
                )
                self.assertIs(
                    normalized["transfer_link_facts"]["phy"]["required_2m"],
                    expected_2m,
                )


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class FirstPartyFrozenSourceEraTests(unittest.TestCase):
    def test_v042_s3_contract_has_exactly_zero_later_first_party_sources(self):
        with tempfile.TemporaryDirectory(
            prefix="pyble-release-v042-frozen-sources-"
        ) as temporary:
            repo = Path(temporary) / "repo"
            _write_versions_lock(repo, "0.4.2")
            board = (
                repo
                / "firmware"
                / "upstream"
                / "micropython"
                / "ports"
                / "esp32"
                / "boards"
                / RELEASE.FROZEN_TARGET_SETTINGS["esp32-s3"]["board"]
            )
            board.mkdir(parents=True)

            records = RELEASE._audit_first_party_frozen_source_evidence(
                repo_root=repo,
                target="esp32-s3",
                board_dir=board,
                selections={},
            )

            self.assertEqual(records, [])
            later_destination = next(
                iter(RELEASE._AUDIT_FIRST_PARTY_FROZEN_SOURCES)
            )
            later_source = repo / "firmware" / "later_source.py"
            later_source.parent.mkdir(parents=True, exist_ok=True)
            later_source.write_text(
                "# SPDX-License-Identifier: MIT\n",
                encoding="utf-8",
            )
            with self.subTest(later_source="selected"):
                with self.assertRaises(RELEASE.ReleaseError):
                    RELEASE._audit_first_party_frozen_source_evidence(
                        repo_root=repo,
                        target="esp32-s3",
                        board_dir=board,
                        selections={later_destination: later_source},
                    )
            with self.subTest(later_source="generated"):
                shutil.copyfile(later_source, board / later_destination)
                with self.assertRaises(RELEASE.ReleaseError):
                    RELEASE._audit_first_party_frozen_source_evidence(
                        repo_root=repo,
                        target="esp32-s3",
                        board_dir=board,
                        selections={},
                    )

    def test_v050_exact_waveshare_contract_requires_both_current_sources(self):
        with tempfile.TemporaryDirectory(
            prefix="pyble-release-v050-frozen-sources-"
        ) as temporary:
            repo = Path(temporary) / "repo"
            _write_versions_lock(repo, "0.5.0")
            board, selections = _install_current_waveshare_sources(repo)

            records = RELEASE._audit_first_party_frozen_source_evidence(
                repo_root=repo,
                target=WAVESHARE_TARGET,
                board_dir=board,
                selections=selections,
            )
            self.assertEqual(
                [record["destination"] for record in records],
                ["pyble_st7789.py", "pyble_waveshare_lcd147b.py"],
            )
            self.assertTrue(
                all(
                    record["generated_path"].startswith(
                        "firmware/upstream/micropython/ports/esp32/boards/"
                        "PYBLE_WAVESHARE_ESP32_S3_LCD_147B/"
                    )
                    for record in records
                )
            )
            companion = next(
                record
                for record in records
                if record["destination"] == "pyble_waveshare_lcd147b.py"
            )
            self.assertEqual(
                companion["canonical_path"],
                "firmware/board_overlays/waveshare-esp32-s3-lcd-147b/"
                "pyble_waveshare_lcd147b.py",
            )

            for missing in tuple(selections):
                with self.subTest(missing=missing):
                    reduced = dict(selections)
                    reduced.pop(missing)
                    with self.assertRaises(RELEASE.ReleaseError):
                        RELEASE._audit_first_party_frozen_source_evidence(
                            repo_root=repo,
                            target=WAVESHARE_TARGET,
                            board_dir=board,
                            selections=reduced,
                        )

    def test_v050_generic_s3_contract_has_no_display_sources(self):
        with tempfile.TemporaryDirectory(
            prefix="pyble-release-v050-generic-s3-sources-"
        ) as temporary:
            repo = Path(temporary) / "repo"
            _write_versions_lock(repo, "0.5.0")
            for contract in RELEASE._AUDIT_FIRST_PARTY_FROZEN_SOURCES.values():
                canonical = repo / contract["canonical_path"]
                canonical.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(
                    REPO_ROOT / contract["canonical_path"],
                    canonical,
                )
            settings = RELEASE.FROZEN_TARGET_SETTINGS["esp32-s3"]
            board = (
                repo
                / "firmware"
                / "upstream"
                / "micropython"
                / "ports"
                / "esp32"
                / "boards"
                / settings["board"]
            )
            board.mkdir(parents=True)
            records = RELEASE._audit_first_party_frozen_source_evidence(
                repo_root=repo,
                target="esp32-s3",
                board_dir=board,
                selections={},
            )
            self.assertEqual(records, [])


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class ManifestEvidenceSourceEraTests(unittest.TestCase):
    def test_v042_producer_omits_post_era_field_entirely(self):
        integration = _load_policy_integration_module()
        fixture = integration.ObservationV2Fixture()
        try:
            _write_versions_lock(fixture.repo, "0.4.2")
            target = "esp32"
            mpy_cross = (
                fixture.repo
                / "firmware"
                / "upstream"
                / "micropython"
                / "mpy-cross"
                / "build"
                / "mpy-cross"
            )
            _selections, evidence = RELEASE._audit_manifest_evidence_record(
                fixture.firmware / "board_overlays" / target / "manifest.py",
                fixture.build_root / target / "frozen_content.c",
                repo_root=fixture.repo,
                target=target,
                trusted_mpy_cross_sha256=BASE.sha256_path(mpy_cross),
            )
            self.assertNotIn("first_party_frozen_sources", evidence)
        finally:
            fixture.close()

    def test_v042_consumer_omits_post_era_field_entirely(self):
        with tempfile.TemporaryDirectory(
            prefix="pyble-release-v042-manifest-evidence-"
        ) as temporary:
            repo = Path(temporary) / "repo"
            legacy = _manifest_evidence_fixture(
                repo,
                "0.4.2",
                include_first_party_field=False,
            )
            normalized = RELEASE._audit_v2_manifest_evidence(repo, legacy)
            self.assertTrue(
                all(
                    "first_party_frozen_sources" not in record
                    for record in normalized
                )
            )
            self.assertTrue(
                all(
                    not (
                        set(DISPLAY_DESTINATIONS)
                        & {
                            selection["destination"]
                            for selection in record["selections"]
                        }
                    )
                    for record in normalized
                )
            )

    def test_v042_consumer_rejects_even_empty_added_field(self):
        with tempfile.TemporaryDirectory(
            prefix="pyble-release-v042-empty-manifest-field-"
        ) as temporary:
            repo = Path(temporary) / "repo"
            with_empty_field = _manifest_evidence_fixture(
                repo,
                "0.4.2",
                include_first_party_field=True,
            )
            with self.assertRaises(RELEASE.ReleaseError):
                RELEASE._audit_v2_manifest_evidence(
                    repo,
                    with_empty_field,
                )

    def test_v050_consumer_requires_current_first_party_field(self):
        with tempfile.TemporaryDirectory(
            prefix="pyble-release-v050-manifest-evidence-"
        ) as temporary:
            repo = Path(temporary) / "repo"
            current = _manifest_evidence_fixture(
                repo,
                "0.5.0",
                include_first_party_field=True,
            )
            normalized = RELEASE._audit_v2_manifest_evidence(repo, current)
            self.assertTrue(
                all("first_party_frozen_sources" in record for record in normalized)
            )
            records_by_target = {
                record["target"]: record for record in normalized
            }
            self.assertEqual(
                records_by_target["esp32-s3"]["first_party_frozen_sources"],
                [],
            )
            self.assertEqual(
                [
                    item["destination"]
                    for item in records_by_target[WAVESHARE_TARGET][
                        "first_party_frozen_sources"
                    ]
                ],
                list(DISPLAY_DESTINATIONS),
            )
            self.assertTrue(
                all(
                    item["canonical_path"].startswith(
                        "firmware/board_overlays/"
                        "waveshare-esp32-s3-lcd-147b/"
                    )
                    or item["destination"] == "pyble_st7789.py"
                    for item in records_by_target[WAVESHARE_TARGET][
                        "first_party_frozen_sources"
                    ]
                )
            )

            missing_field = copy.deepcopy(current)
            for record in missing_field:
                record.pop("first_party_frozen_sources")
            with self.assertRaises(RELEASE.ReleaseError):
                RELEASE._audit_v2_manifest_evidence(repo, missing_field)


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class HistoricalCandidateValidationIntegrationTests(unittest.TestCase):
    def test_current_validator_revalidates_retained_v042_candidate_source(self):
        fixture = BASE.ReleaseFixture(firmware_version="0.4.2")
        try:
            bundle = fixture.make_bundle(public=False)
            declared = json.loads(
                (bundle / "release.json").read_text(encoding="utf-8")
            )
            self.assertEqual(declared["schema_version"], 2)
            self.assertEqual(
                [profile["id"] for profile in declared["profiles"]],
                list(HISTORICAL_V042_PROFILE_ORDER),
            )
            self.assertFalse((bundle / WAVESHARE_PROFILE_ID).exists())

            hil_path = bundle / "HIL_REPORT.md"
            self.assertIn(
                "PYBLE_HIL_RECORDS_V2",
                hil_path.read_text(encoding="utf-8"),
            )
            hil = BASE.read_hil_payload(hil_path)
            self.assertEqual(hil["schema_version"], 2)
            self.assertEqual(
                [record["profile_id"] for record in hil["records"]],
                list(HISTORICAL_V042_PROFILE_ORDER),
            )
            self.assertEqual(hil["qualification_policy"]["schema_version"], 1)
            self.assertEqual(
                hil["qualification_policy"]["profile_order"],
                list(HISTORICAL_V042_PROFILE_ORDER),
            )
            self.assertNotIn("waveshare_lcd147b_qualification", hil)

            release = RELEASE.validate_bundle(
                bundle,
                public=False,
                qualification_repo_root=fixture.repo,
            )

            self.assertEqual(release["identity"]["version"], "0.4.2")
            self.assertEqual(
                release["provenance"]["pyble"]["commit"],
                "1" * 40,
            )
        finally:
            fixture.cleanup()


if __name__ == "__main__":
    unittest.main()
