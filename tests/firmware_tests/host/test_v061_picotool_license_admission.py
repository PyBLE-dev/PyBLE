#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED admission contract for the v0.6.1 picotool build-tool evidence.

All generated license and provenance text in this suite is synthetic.  It
tests the release machinery and does not represent a legal review or physical
release qualification.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import test_release_v060_license_generation as generation_fixture


RELEASE = generation_fixture.RELEASE
RELEASE_LOAD_ERROR = generation_fixture.RELEASE_LOAD_ERROR
V060_ROLES = tuple(generation_fixture.RP2_ROLES)
V061_ROLES = (*V060_ROLES, "build-tools")
VERSION_LINE = (
    "picotool v2.3.0 "
    "(Darwin, AppleClang-15.0.0.15000309, Release)"
)
POLICY_PATH = "firmware/licenses/rp2-build-tools-license-policy.json"
ATTRIBUTION_PATH = (
    "firmware/licenses/evidence/rp2/picotool/2.3.0/"
    "distribution-attribution-v1.json"
)
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()

PICOTOOL_LOCK = {
    "version": "2.3.0",
    "version_line": VERSION_LINE,
    "source_repo": "https://github.com/raspberrypi/picotool.git",
    "source_ref": "2.3.0",
    "source_commit": "6f6458d792b93685a11423b244a585eaa99eafcf",
    "distribution_repo": "https://github.com/raspberrypi/pico-sdk-tools.git",
    "distribution_ref": "v2.3.0-0",
    "distribution_commit": "ad9e4a8375253cf4886bf168ea1a8d2746aadf24",
    "url": (
        "https://github.com/raspberrypi/pico-sdk-tools/releases/download/"
        "v2.3.0-0/picotool-2.3.0-mac.zip"
    ),
    "archive_filename": "picotool-2.3.0-mac.zip",
    "archive_bytes": 1_980_457,
    "archive_format": "zip",
    "sha256": "085ea99ccc2d64309e967a72e307fb113838713a46ba45bf7e156e519cca7d8e",
    "cmake_dir": "picotool",
    "executable_path": "picotool/picotool",
    "executable_sha256": (
        "a4b3c4e64dea7b99e810c5c777bf13fb2722b8d0355e0b64a28244ddc1b0f8b5"
    ),
    "cmake_config_path": "picotool/picotoolConfig.cmake",
    "cmake_config_sha256": (
        "ca12b6fee18e6583713cfdcb2e81886aaee741d40304ea2cc88c4f5b2df2b6c3"
    ),
    "bundled_libusb_path": "picotool/libusb-1.0.0.dylib",
    "bundled_libusb_sha256": (
        "b3d0c88bcb04fe61e4f56bc304a31fef56e19ee5ec2edaebd0fce44afb2b9237"
    ),
}

MEMBERS = [
    {
        "path": "picotool/",
        "kind": "directory",
        "mode": "040755",
        "bytes": 0,
        "sha256": EMPTY_SHA256,
    },
    {
        "path": "picotool/picotoolTargets-release.cmake",
        "kind": "regular",
        "mode": "100644",
        "bytes": 767,
        "sha256": "e40085002e565de850554e772c90f1a1c4cffb545f853eaa231b145e498f7c0f",
    },
    {
        "path": "picotool/picotoolConfigVersion.cmake",
        "kind": "regular",
        "mode": "100644",
        "bytes": 2_303,
        "sha256": "61485a18a59a186d7cb82ddf7686c5f1f4def81726568ae49fd0033db368f7e3",
    },
    {
        "path": "picotool/rp2350_otp_contents.json",
        "kind": "regular",
        "mode": "100644",
        "bytes": 367_931,
        "sha256": "1838713d5f94316c4c61558cb82d3346831235dc41f9b0f02151e6eda3f22fc2",
    },
    {
        "path": "picotool/libusb-1.0.0.dylib",
        "kind": "regular",
        "mode": "100444",
        "bytes": 328_336,
        "sha256": "b3d0c88bcb04fe61e4f56bc304a31fef56e19ee5ec2edaebd0fce44afb2b9237",
    },
    {
        "path": "picotool/enc_bootloader_mbedtls.elf",
        "kind": "regular",
        "mode": "100644",
        "bytes": 29_484,
        "sha256": "c5d17fcbb4f1ee41751dc782d86c1fc6629d8da3484e1a1cadc3ba4bec4d6044",
    },
    {
        "path": "picotool/picotoolTargets.cmake",
        "kind": "regular",
        "mode": "100644",
        "bytes": 3_856,
        "sha256": "043655d4bc215fb3a05d4a04f92cabc0be9bbdb0834717b0211e80106b4d1aae",
    },
    {
        "path": "picotool/picotoolConfig.cmake",
        "kind": "regular",
        "mode": "100644",
        "bytes": 96,
        "sha256": "ca12b6fee18e6583713cfdcb2e81886aaee741d40304ea2cc88c4f5b2df2b6c3",
    },
    {
        "path": "picotool/xip_ram_perms.elf",
        "kind": "regular",
        "mode": "100644",
        "bytes": 34_004,
        "sha256": "afac0e166ee9b632f84717c7db02e7e5e648f03a51cc4795938adcd282c6103b",
    },
    {
        "path": "picotool/picotool",
        "kind": "regular",
        "mode": "100755",
        "bytes": 5_673_800,
        "sha256": "a4b3c4e64dea7b99e810c5c777bf13fb2722b8d0355e0b64a28244ddc1b0f8b5",
    },
    {
        "path": "picotool/enc_bootloader.elf",
        "kind": "regular",
        "mode": "100644",
        "bytes": 20_104,
        "sha256": "9ce3c424d61226225d2c1f5b80a8854f15174b09dd447e58e4439240b274fb3d",
    },
    {
        "path": ".keep",
        "kind": "regular",
        "mode": "100644",
        "bytes": 0,
        "sha256": EMPTY_SHA256,
    },
]

NONSOFTWARE_MEMBERS = [
    {
        **next(item for item in MEMBERS if item["path"] == ".keep"),
        "classification": "packaging-metadata",
    },
    {
        **next(item for item in MEMBERS if item["path"] == "picotool/"),
        "classification": "packaging-metadata",
    },
]

COMPONENTS = [
    {"name": "CMake package scripts", "license": "CMake-package-script-grant"},
    {"name": "Mbed TLS", "license": "Apache-2.0"},
    {"name": "Pico SDK", "license": "BSD-3-Clause"},
    {"name": "clipp", "license": "MIT"},
    {"name": "littlefs", "license": "BSD-3-Clause"},
    {"name": "nlohmann JSON", "license": "MIT"},
    {"name": "ooFatFs R0.13c", "license": "LicenseRef-ooFatFs-R0.13c"},
    {"name": "picotool", "license": "BSD-3-Clause"},
    {"name": "whereami", "license": "MIT"},
]


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def recompute_semantic(observation: dict[str, object]) -> None:
    payload = {
        key: copy.deepcopy(value)
        for key, value in observation.items()
        if key != "semantic_sha256"
    }
    observation["semantic_sha256"] = sha256_bytes(canonical_json_bytes(payload))


def selected_roles(version: str) -> tuple[str, ...] | None:
    function = getattr(RELEASE, "_rp2_license_audit_roles_for_version", None)
    if not callable(function):
        return None
    try:
        return tuple(function(version))
    except Exception:
        return None


HAVE_SELECTOR = (
    selected_roles("0.6.0") == V060_ROLES
    and selected_roles("0.6.1") == V061_ROLES
)
HAVE_BUILD_POLICY = callable(
    getattr(RELEASE, "_audit_validate_rp2_build_tools_license_policy", None)
) and callable(
    getattr(RELEASE, "_audit_load_rp2_build_tools_license_policy", None)
)
HAVE_BUILD_OBSERVER = callable(
    getattr(RELEASE, "_audit_observe_rp2_build_tools_license_inputs", None)
)
HAVE_V061_ADMISSION = HAVE_SELECTOR and HAVE_BUILD_POLICY and HAVE_BUILD_OBSERVER


class PicotoolLicenseAdmissionSeamTests(unittest.TestCase):
    def test_roles_are_selected_by_candidate_version(self) -> None:
        selector = getattr(RELEASE, "_rp2_license_audit_roles_for_version", None)
        self.assertTrue(
            callable(selector),
            "[red] RP2 license roles are not selected by firmware version",
        )
        if callable(selector):
            self.assertEqual(tuple(selector("0.6.0")), V060_ROLES)
            self.assertEqual(tuple(selector("0.6.1")), V061_ROLES)

    def test_separate_policy_loader_validator_and_observer_exist(self) -> None:
        expected = {
            "_audit_validate_rp2_build_tools_license_policy": {
                "value",
                "repo_root",
                "build_root",
                "picotool_lock",
            },
            "_audit_load_rp2_build_tools_license_policy": {
                "repo_root",
                "build_root",
                "lock",
            },
            "_audit_observe_rp2_build_tools_license_inputs": {
                "build_root",
                "repo_root",
                "provenance",
                "policy",
            },
        }
        for name, parameters in expected.items():
            with self.subTest(function=name):
                function = getattr(RELEASE, name, None)
                self.assertTrue(callable(function), "[red] missing %s" % name)
                if callable(function):
                    self.assertEqual(
                        set(inspect.signature(function).parameters),
                        parameters,
                    )


class PicotoolPolicyFixture:
    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="pyble-v061-picotool-policy-red-"
        )
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.build = self.root / "build"
        self.repo.mkdir()
        self.build.mkdir()
        self.composite_license = (
            self.repo / "firmware/licenses/texts/picotool-composite.txt"
        )
        self.libusb_license = (
            self.repo / "firmware/licenses/texts/LGPL-2.1-or-later.txt"
        )
        self.libusb_attribution = (
            self.repo
            / "firmware/licenses/evidence/rp2/picotool/2.3.0/"
            "libusb-attribution-v1.json"
        )
        self.attribution = self.repo / ATTRIBUTION_PATH
        self.composite_license.parent.mkdir(parents=True)
        self.composite_license.write_text(
            "Synthetic complete picotool composite grant.\n",
            encoding="utf-8",
        )
        self.libusb_license.write_text(
            "Synthetic complete LGPL-2.1-or-later text.\n",
            encoding="utf-8",
        )
        write_json(
            self.libusb_attribution,
            {
                "source_archive_sha256": (
                    "fea36f34f9156400209595e300840767ab1a385ede1dc7ee893015aea9c6dbaf"
                ),
                "source_commit": "87a55632db62c9bdc58cd31d3ccfa673f1bb017f",
                "source_ref": "v1.0.30",
            },
        )
        write_json(
            self.attribution,
            {
                "schema_version": 1,
                "archive_sha256": PICOTOOL_LOCK["sha256"],
                "components": COMPONENTS,
                "packaging_provenance": {
                    "name": "pico-sdk-tools",
                    "license": "Apache-2.0",
                    "repo": PICOTOOL_LOCK["distribution_repo"],
                    "ref": PICOTOOL_LOCK["distribution_ref"],
                    "commit": PICOTOOL_LOCK["distribution_commit"],
                    "ownership": "packaging-only",
                },
            },
        )
        software_paths = sorted(
            item["path"]
            for item in MEMBERS
            if item["kind"] == "regular"
            and item["path"] not in {".keep", PICOTOOL_LOCK["bundled_libusb_path"]}
        )
        self.distribution_provenance = {
            "picotool_lock": copy.deepcopy(PICOTOOL_LOCK),
            "retained_archive": {
                "path": (
                    "firmware/.picotool/.pyble-dist/"
                    + PICOTOOL_LOCK["archive_filename"]
                ),
                "bytes": PICOTOOL_LOCK["archive_bytes"],
                "sha256": PICOTOOL_LOCK["sha256"],
            },
            "member_inventory": copy.deepcopy(MEMBERS),
            "runtime_version_line": VERSION_LINE,
            "source": {
                "repo": PICOTOOL_LOCK["source_repo"],
                "ref": PICOTOOL_LOCK["source_ref"],
                "commit": PICOTOOL_LOCK["source_commit"],
            },
            "distribution": {
                "repo": PICOTOOL_LOCK["distribution_repo"],
                "ref": PICOTOOL_LOCK["distribution_ref"],
                "commit": PICOTOOL_LOCK["distribution_commit"],
            },
            "attribution": {
                "path": ATTRIBUTION_PATH,
                "sha256": sha256_path(self.attribution),
            },
        }
        self.policy = {
            "schema_version": 1,
            "profile_id": "rpi-pico2-w",
            "target": "rpi-pico2-w",
            "distribution_provenance": copy.deepcopy(
                self.distribution_provenance
            ),
            "source_owners": [
                {
                    "id": "picotool-composite-build-tool",
                    "source_roots": [
                        {
                            "namespace": "picotool-distribution",
                            "path": path,
                        }
                        for path in software_paths
                    ],
                    "source_ref": "picotool-2.3.0-composite-v1",
                    "source_url": PICOTOOL_LOCK["source_repo"],
                    "source_spdx_expression": (
                        "LicenseRef-PyBLE-Picotool-2.3.0-Composite"
                    ),
                    "selected_spdx_expression": (
                        "LicenseRef-PyBLE-Picotool-2.3.0-Composite"
                    ),
                    "copyright": "Synthetic reviewed upstream attributions",
                    "license_texts": [
                        {
                            "identifier": (
                                "LicenseRef-PyBLE-Picotool-2.3.0-Composite"
                            ),
                            "path": self.composite_license.relative_to(
                                self.repo
                            ).as_posix(),
                            "sha256": sha256_path(self.composite_license),
                        }
                    ],
                    "notice_files": [
                        {
                            "path": ATTRIBUTION_PATH,
                            "sha256": sha256_path(self.attribution),
                        }
                    ],
                    "disposition": "allow",
                    "component_kind": "build-tool",
                },
                {
                    "id": "picotool-libusb-build-tool",
                    "source_roots": [
                        {
                            "namespace": "picotool-distribution",
                            "path": PICOTOOL_LOCK["bundled_libusb_path"],
                        }
                    ],
                    "source_ref": (
                        "v1.0.30@87a55632db62c9bdc58cd31d3ccfa673f1bb017f"
                    ),
                    "source_url": "https://github.com/libusb/libusb.git",
                    "source_spdx_expression": "LGPL-2.1-or-later",
                    "selected_spdx_expression": "LGPL-2.1-or-later",
                    "copyright": "Synthetic libusb attribution",
                    "license_texts": [
                        {
                            "identifier": "LGPL-2.1-or-later",
                            "path": self.libusb_license.relative_to(
                                self.repo
                            ).as_posix(),
                            "sha256": sha256_path(self.libusb_license),
                        }
                    ],
                    "notice_files": [
                        {
                            "path": self.libusb_attribution.relative_to(
                                self.repo
                            ).as_posix(),
                            "sha256": sha256_path(self.libusb_attribution),
                        }
                    ],
                    "disposition": "allow",
                    "component_kind": "build-tool",
                },
            ],
            "nonsoftware_members": copy.deepcopy(NONSOFTWARE_MEMBERS),
        }

    def close(self) -> None:
        self.temporary.cleanup()


@unittest.skipUnless(
    HAVE_BUILD_POLICY,
    "[red] the independent picotool build-tools policy is not implemented",
)
class PicotoolBuildToolsPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = PicotoolPolicyFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def validate(self, value: dict[str, object] | None = None):
        return RELEASE._audit_validate_rp2_build_tools_license_policy(
            self.fixture.policy if value is None else value,
            repo_root=self.fixture.repo,
            build_root=self.fixture.build,
            picotool_lock=copy.deepcopy(PICOTOOL_LOCK),
        )

    def test_exact_separate_policy_admits_both_nonredistributed_owners(self):
        value = self.validate()
        self.assertEqual(value["distribution_provenance"], self.fixture.distribution_provenance)
        self.assertEqual(
            [owner["id"] for owner in value["source_owners"]],
            [
                "picotool-composite-build-tool",
                "picotool-libusb-build-tool",
            ],
        )
        self.assertTrue(
            all(
                owner["component_kind"] == "build-tool"
                for owner in value["source_owners"]
            )
        )
        self.assertEqual(value["nonsoftware_members"], NONSOFTWARE_MEMBERS)
        attribution = json.loads(self.fixture.attribution.read_text(encoding="utf-8"))
        self.assertEqual(attribution["components"], COMPONENTS)
        self.assertEqual(
            attribution["packaging_provenance"]["ownership"],
            "packaging-only",
        )

    def test_policy_rejects_missing_extra_reordered_or_changed_frozen_data(self):
        cases = {
            "missing": lambda value: value.pop("nonsoftware_members"),
            "extra": lambda value: value.__setitem__("private_review", True),
            "schema-bool": lambda value: value.__setitem__("schema_version", True),
            "owner-order": lambda value: value["source_owners"].reverse(),
            "member-order": lambda value: value["distribution_provenance"][
                "member_inventory"
            ].reverse(),
            "archive": lambda value: value["distribution_provenance"][
                "retained_archive"
            ].__setitem__("sha256", "9" * 64),
            "config": lambda value: next(
                item
                for item in value["distribution_provenance"]["member_inventory"]
                if item["path"] == "picotool/picotoolConfig.cmake"
            ).__setitem__("sha256", "9" * 64),
            "targets": lambda value: next(
                item
                for item in value["distribution_provenance"]["member_inventory"]
                if item["path"] == "picotool/picotoolTargets.cmake"
            ).__setitem__("mode", "100755"),
            "libusb": lambda value: next(
                item
                for item in value["distribution_provenance"]["member_inventory"]
                if item["path"] == "picotool/libusb-1.0.0.dylib"
            ).__setitem__("sha256", "9" * 64),
            "version": lambda value: value["distribution_provenance"].__setitem__(
                "runtime_version_line", "picotool v2.3.1"
            ),
            "source-ref": lambda value: value["distribution_provenance"][
                "source"
            ].__setitem__("commit", "9" * 40),
            "distribution-ref": lambda value: value["distribution_provenance"][
                "distribution"
            ].__setitem__("ref", "v2.3.0-1"),
            "license": lambda value: value["source_owners"][0][
                "license_texts"
            ][0].__setitem__("sha256", "9" * 64),
            "provenance": lambda value: value["distribution_provenance"][
                "attribution"
            ].__setitem__("sha256", "9" * 64),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                value = copy.deepcopy(self.fixture.policy)
                mutate(value)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.validate(value)


class V061CompositionFixture:
    def __init__(self) -> None:
        self.generation = generation_fixture.GenerationFixture()
        self.root = self.generation.root
        self.repo = self.generation.repo
        self.build = self.generation.build
        self.policy_fixture = PicotoolPolicyFixture()
        self._advance_source_fixture()
        self.build_tools = self._build_tools_observation()
        self.combined = copy.deepcopy(self.generation.rp2_observation)
        self.combined["input_sha256"].update(self.build_tools["input_sha256"])
        self.combined["owners"].extend(copy.deepcopy(self.build_tools["owners"]))
        self.combined["role_documents"]["build-tools"] = copy.deepcopy(
            self.build_tools["role_document"]
        )
        recompute_semantic(self.combined)

    def close(self) -> None:
        self.policy_fixture.close()
        self.generation.close()

    def _advance_source_fixture(self) -> None:
        lock_path = self.repo / "firmware/versions.lock"
        text = lock_path.read_text(encoding="utf-8")
        text = text.replace('agent_version = "0.6.0"', 'agent_version = "0.6.1"')
        text += "\n[picotool]\n"
        for key, value in PICOTOOL_LOCK.items():
            if isinstance(value, int):
                text += "%s = %d\n" % (key, value)
            else:
                text += "%s = %s\n" % (key, json.dumps(value))
        lock_path.write_text(text, encoding="utf-8")

        provenance_path = (
            self.build / "rpi-pico2-w/pyble-build-provenance.json"
        )
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        provenance["picotool"] = VERSION_LINE
        write_json(provenance_path, provenance)
        provenance_sha256 = sha256_path(provenance_path)
        lock_sha256 = sha256_path(lock_path)
        observation = self.generation.rp2_observation
        for document in observation["role_documents"].values():
            document["build_provenance_sha256"] = provenance_sha256
            document["source_identity"]["arm_gnu_toolchain"][
                "versions_lock_sha256"
            ] = lock_sha256
        for record in observation["role_documents"]["arm-gnu-runtime"]["inputs"]:
            if record["kind"] == "toolchain-pin":
                record["sha256"] = lock_sha256
        recompute_semantic(observation)

        policy_path = self.repo / POLICY_PATH
        write_json(policy_path, self.policy_fixture.policy)
        attribution = self.repo / ATTRIBUTION_PATH
        attribution.parent.mkdir(parents=True, exist_ok=True)
        attribution.write_bytes(self.policy_fixture.attribution.read_bytes())
        for source in (
            self.policy_fixture.composite_license,
            self.policy_fixture.libusb_license,
            self.policy_fixture.libusb_attribution,
        ):
            destination = self.repo / source.relative_to(self.policy_fixture.repo)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        self.policy = copy.deepcopy(self.policy_fixture.policy)
        self.generation.tool_lock["inputs"].update(
            {
                "rp2_build_tools_license_policy_path": POLICY_PATH,
                "rp2_build_tools_license_policy_sha256": sha256_path(policy_path),
            }
        )

    def _build_tools_observation(self) -> dict[str, object]:
        provenance_path = (
            self.build / "rpi-pico2-w/pyble-build-provenance.json"
        )
        policy_path = self.repo / POLICY_PATH
        attribution = self.repo / ATTRIBUTION_PATH
        owners = copy.deepcopy(self.policy["source_owners"])
        input_sha256 = {
            "repo/firmware/versions.lock": sha256_path(
                self.repo / "firmware/versions.lock"
            ),
            "repo/" + POLICY_PATH: sha256_path(policy_path),
            "repo/" + ATTRIBUTION_PATH: sha256_path(attribution),
            "picotool-archive/" + PICOTOOL_LOCK["archive_filename"]: (
                PICOTOOL_LOCK["sha256"]
            ),
            **{
                "picotool-member/" + item["path"]: item["sha256"]
                for item in MEMBERS
            },
        }
        for owner in owners:
            for record in (*owner["license_texts"], *owner["notice_files"]):
                input_sha256["repo/" + record["path"]] = record["sha256"]
        document = {
            "schema_version": 1,
            "profile_id": "rpi-pico2-w",
            "target": "rpi-pico2-w",
            "resource_kind": "rp2",
            "role": "build-tools",
            "build_provenance_sha256": sha256_path(provenance_path),
            "distribution_provenance": copy.deepcopy(
                self.policy["distribution_provenance"]
            ),
            "owners": owners,
            "nonsoftware_members": copy.deepcopy(NONSOFTWARE_MEMBERS),
            "inputs": [
                {"logical_path": key, "sha256": value}
                for key, value in sorted(input_sha256.items())
            ],
            "license_inputs": sorted(
                {
                    record["path"]: {
                        "logical_path": "repo/" + record["path"],
                        "sha256": record["sha256"],
                    }
                    for owner in owners
                    for record in (
                        *owner["license_texts"],
                        *owner["notice_files"],
                    )
                }.values(),
                key=lambda item: item["logical_path"],
            ),
        }
        observation = {
            "input_sha256": input_sha256,
            "owners": owners,
            "notice_records": [],
            "role_document": document,
        }
        recompute_semantic(observation)
        return observation

    def make_esp(self, name: str) -> Path:
        path = self.root / name
        self.generation.generate_esp_evidence(evidence_dir=path)
        return path

    def compose(self, observation: dict[str, object], output: Path):
        return RELEASE._audit_compose_v060_license_evidence(
            esp_evidence=self.make_esp("esp-" + output.name),
            destination=output,
            build_root=self.build,
            repo_root=self.repo,
            esp_notice=generation_fixture.ESP_NOTICE,
            rp2_observation=observation,
            firmware_version="0.6.1",
        )


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class V060PicotoolIsolationTests(unittest.TestCase):
    def test_historical_composition_keeps_exact_seven_role_bytes(self) -> None:
        fixture = generation_fixture.GenerationFixture()
        try:
            esp = fixture.root / "historical-esp"
            fixture.generate_esp_evidence(evidence_dir=esp)
            output = fixture.root / "historical-composed"
            result = RELEASE._audit_compose_v060_license_evidence(
                esp_evidence=esp,
                destination=output,
                build_root=fixture.build,
                repo_root=fixture.repo,
                esp_notice=generation_fixture.ESP_NOTICE,
                rp2_observation=copy.deepcopy(fixture.rp2_observation),
                firmware_version="0.6.0",
            )
            self.assertEqual(
                result["third_party_licenses"], generation_fixture.FINAL_NOTICE
            )
            inventory = json.loads(
                (output / "release-inventory.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [role["role"] for role in inventory["profiles"][-1]["roles"]],
                list(V060_ROLES),
            )
            for role in V060_ROLES:
                path = output / "rp2" / ("rpi-pico2-w--%s.json" % role)
                self.assertEqual(
                    path.read_bytes(),
                    canonical_json_bytes(
                        fixture.rp2_observation["role_documents"][role]
                    ),
                )
            all_bytes = b"".join(
                path.read_bytes()
                for path in sorted(output.rglob("*"))
                if path.is_file()
            )
            self.assertNotIn(b"build-tools", all_bytes)
            self.assertNotIn(b"picotool-composite-build-tool", all_bytes)
        finally:
            fixture.close()

    @unittest.skipUnless(
        HAVE_BUILD_POLICY and HAVE_BUILD_OBSERVER,
        "[red] picotool policy seams are not implemented",
    )
    def test_historical_entrypoint_never_opens_picotool_policy_or_observer(
        self,
    ) -> None:
        fixture = generation_fixture.GenerationFixture()
        try:
            with mock.patch.object(
                RELEASE,
                "_audit_load_rp2_build_tools_license_policy",
                side_effect=AssertionError(
                    "v0.6.0 opened the v0.6.1-only build-tools policy"
                ),
            ) as load_policy, mock.patch.object(
                RELEASE,
                "_audit_observe_rp2_build_tools_license_inputs",
                side_effect=AssertionError(
                    "v0.6.0 invoked the v0.6.1-only build-tools observer"
                ),
            ) as observe_build_tools:
                result, _generator, _verifier = fixture.audit(
                    verifier_side_effect=lambda **_kwargs: None
                )
            load_policy.assert_not_called()
            observe_build_tools.assert_not_called()
            self.assertEqual(
                result["third_party_licenses"],
                generation_fixture.FINAL_NOTICE,
            )
            inventory = json.loads(
                (
                    fixture.evidence / "release-inventory.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                [role["role"] for role in inventory["profiles"][-1]["roles"]],
                list(V060_ROLES),
            )
        finally:
            fixture.close()


@unittest.skipUnless(
    HAVE_V061_ADMISSION,
    "[red] v0.6.1 picotool license admission is not implemented",
)
class V061PicotoolCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = V061CompositionFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_eighth_role_binds_exact_distribution_but_adds_no_public_notice(self):
        output = self.fixture.root / "v061-composed"
        result = self.fixture.compose(self.fixture.combined, output)
        inventory = json.loads(
            (output / "release-inventory.json").read_text(encoding="utf-8")
        )
        self.assertEqual(inventory["firmware_version"], "0.6.1")
        self.assertEqual(
            [role["role"] for role in inventory["profiles"][-1]["roles"]],
            list(V061_ROLES),
        )
        document_path = output / "rp2/rpi-pico2-w--build-tools.json"
        self.assertEqual(
            document_path.read_bytes(),
            canonical_json_bytes(self.fixture.build_tools["role_document"]),
        )
        document = json.loads(document_path.read_text(encoding="utf-8"))
        self.assertEqual(
            document["distribution_provenance"]["picotool_lock"],
            PICOTOOL_LOCK,
        )
        self.assertEqual(
            document["distribution_provenance"]["member_inventory"],
            MEMBERS,
        )
        self.assertEqual(document["nonsoftware_members"], NONSOFTWARE_MEMBERS)
        self.assertEqual(
            [owner["id"] for owner in document["owners"]],
            [
                "picotool-composite-build-tool",
                "picotool-libusb-build-tool",
            ],
        )
        notice = result["third_party_licenses"]
        for private_owner in (
            "picotool-composite-build-tool",
            "picotool-libusb-build-tool",
            "LicenseRef-PyBLE-Picotool-2.3.0-Composite",
            "LGPL-2.1-or-later",
        ):
            self.assertNotIn(private_owner, notice)

    def test_every_substitution_fails_before_evidence_publication(self) -> None:
        def member(value, path):
            return next(
                item
                for item in value["role_documents"]["build-tools"][
                    "distribution_provenance"
                ]["member_inventory"]
                if item["path"] == path
            )

        cases = {
            "none": lambda value: value["role_documents"].pop("build-tools"),
            "missing": lambda value: value["role_documents"]["build-tools"].pop(
                "license_inputs"
            ),
            "extra": lambda value: value["role_documents"]["build-tools"].__setitem__(
                "private_review", True
            ),
            "role-order": lambda value: value.__setitem__(
                "role_documents",
                {
                    "build-tools": value["role_documents"]["build-tools"],
                    **{
                        key: item
                        for key, item in value["role_documents"].items()
                        if key != "build-tools"
                    },
                },
            ),
            "member-missing": lambda value: value["role_documents"][
                "build-tools"
            ]["distribution_provenance"]["member_inventory"].pop(),
            "member-extra": lambda value: value["role_documents"]["build-tools"][
                "distribution_provenance"
            ]["member_inventory"].append(
                {
                    "path": "picotool/unreviewed",
                    "kind": "regular",
                    "mode": "100644",
                    "bytes": 1,
                    "sha256": "9" * 64,
                }
            ),
            "member-order": lambda value: value["role_documents"]["build-tools"][
                "distribution_provenance"
            ]["member_inventory"].reverse(),
            "archive": lambda value: value["role_documents"]["build-tools"][
                "distribution_provenance"
            ]["retained_archive"].__setitem__("sha256", "9" * 64),
            "config": lambda value: member(
                value, "picotool/picotoolConfig.cmake"
            ).__setitem__("sha256", "9" * 64),
            "targets": lambda value: member(
                value, "picotool/picotoolTargets.cmake"
            ).__setitem__("bytes", 3_855),
            "libusb": lambda value: member(
                value, "picotool/libusb-1.0.0.dylib"
            ).__setitem__("mode", "100644"),
            "version": lambda value: value["role_documents"]["build-tools"][
                "distribution_provenance"
            ].__setitem__("runtime_version_line", "picotool v2.3.1"),
            "source": lambda value: value["role_documents"]["build-tools"][
                "distribution_provenance"
            ]["source"].__setitem__("commit", "9" * 40),
            "distribution": lambda value: value["role_documents"]["build-tools"][
                "distribution_provenance"
            ]["distribution"].__setitem__("ref", "v2.3.0-1"),
            "owner-order": lambda value: value["role_documents"]["build-tools"][
                "owners"
            ].reverse(),
            "license": lambda value: value["role_documents"]["build-tools"][
                "license_inputs"
            ][0].__setitem__("sha256", "9" * 64),
            "provenance": lambda value: value["role_documents"]["build-tools"][
                "distribution_provenance"
            ]["attribution"].__setitem__("sha256", "9" * 64),
            "build-provenance": lambda value: value["role_documents"][
                "build-tools"
            ].__setitem__("build_provenance_sha256", "9" * 64),
        }
        for index, (name, mutate) in enumerate(cases.items()):
            with self.subTest(case=name):
                value = copy.deepcopy(self.fixture.combined)
                mutate(value)
                recompute_semantic(value)
                output = self.fixture.root / ("rejected-%02d-%s" % (index, name))
                with self.assertRaises(RELEASE.ReleaseError):
                    self.fixture.compose(value, output)
                self.assertFalse(output.exists() or output.is_symlink())


@unittest.skipUnless(
    HAVE_V061_ADMISSION,
    "[red] v0.6.1 picotool license orchestration is not implemented",
)
class V061PicotoolGenerationTests(unittest.TestCase):
    def test_entrypoint_uses_separate_observer_and_keeps_build_tools_private(self):
        fixture = V061CompositionFixture()
        try:
            loader = getattr(
                RELEASE, "_audit_load_rp2_build_tools_license_policy"
            )
            observer = getattr(
                RELEASE, "_audit_observe_rp2_build_tools_license_inputs"
            )
            with mock.patch.object(
                RELEASE,
                loader.__name__,
                return_value=copy.deepcopy(fixture.policy),
            ) as load_policy, mock.patch.object(
                RELEASE,
                observer.__name__,
                return_value=copy.deepcopy(fixture.build_tools),
            ) as observe_build_tools:
                result, _esp_generator, _esp_verifier = (
                    fixture.generation.audit(
                        verifier_side_effect=lambda **_kwargs: None
                    )
                )
            self.assertGreaterEqual(load_policy.call_count, 1)
            self.assertGreaterEqual(observe_build_tools.call_count, 2)
            inventory = json.loads(
                (
                    fixture.generation.evidence / "release-inventory.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                [role["role"] for role in inventory["profiles"][-1]["roles"]],
                list(V061_ROLES),
            )
            for owner_id in (
                "picotool-composite-build-tool",
                "picotool-libusb-build-tool",
            ):
                self.assertNotIn(owner_id, result["third_party_licenses"])
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
