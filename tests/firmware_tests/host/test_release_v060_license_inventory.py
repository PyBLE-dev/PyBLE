#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for the heterogeneous v0.6.0 release-license receipt.

The existing ESP audit remains authoritative for its eight offline SBOM
documents.  This suite freezes the additive persisted contract which joins
those documents to independently observed RP2 evidence.  All inputs are tiny,
synthetic, and legally neutral; no test result represents a completed release
review.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
RELEASE_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "release_bundle.py"

V042_PROFILE_ORDER = ("esp32-4mb", "esp32-s3-n16r8")
V05_PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
    "waveshare-esp32-s3-lcd-147b",
)
V060_PROFILE_ORDER = (
    *V05_PROFILE_ORDER,
    "esp32-c3-4mb",
    "rpi-pico2-w",
)
ESP_TARGETS = {
    "esp32-4mb": "esp32",
    "esp32-s3-n16r8": "esp32-s3",
    "waveshare-esp32-s3-lcd-147b": "waveshare-esp32-s3-lcd-147b",
    "esp32-c3-4mb": "esp32-c3",
}
RP2_ROLES = (
    "linked-inputs",
    "frozen-modules",
    "pico-sdk",
    "btstack",
    "cyw43",
    "tinyusb",
    "arm-gnu-runtime",
)


def load_release_module():
    spec = importlib.util.spec_from_file_location(
        "pyble_release_v060_license_inventory_red",
        RELEASE_SCRIPT,
    )
    if spec is None or spec.loader is None:
        return None, "cannot load release_bundle.py"
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - reported by skip reason.
        return None, "cannot import release_bundle.py: %s" % exc
    return module, ""


RELEASE, RELEASE_LOAD_ERROR = load_release_module()


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def tree_sha256(root: Path) -> str:
    """Hash a synthetic tree without trusting host absolute paths."""

    records = bytearray()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        records.extend(relative + b"\0" + path.read_bytes() + b"\0")
    return sha256_bytes(bytes(records))


class V060LicenseFixture:
    """Exact-byte fixture for the persisted receipt, not a passed audit."""

    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix="pyble-v060-license-inventory-red-"
        )
        self.root = Path(self._temporary.name)
        self.repo = self.root / "repo"
        self.build = self.root / "build"
        self.evidence = self.root / "evidence"
        self.repo.mkdir()
        self.build.mkdir()
        self.evidence.mkdir()
        self.notice = "Synthetic reviewed v0.6.0 notice fixture.\n"
        self._make_repository()
        self._make_builds()
        self._make_esp_evidence()
        self._make_rp2_evidence()
        self.rp2_observation = self._make_rp2_observation()
        self._make_release_inventory()
        self._make_receipt()

    def close(self) -> None:
        self._temporary.cleanup()

    def _make_repository(self) -> None:
        firmware = self.repo / "firmware"
        overlay = firmware / "board_overlays" / "rpi-pico2-w"
        overlay.mkdir(parents=True)
        (overlay / "manifest.py").write_text(
            "# SPDX-License-Identifier: MIT\n"
            'freeze("$(PORT_DIR)/modules")\n',
            encoding="utf-8",
        )
        (firmware / "versions.lock").write_text(
            "# SPDX-License-Identifier: MIT\n"
            "[micropython]\n"
            'repo = "https://github.com/micropython/micropython"\n'
            'ref = "v1.28.0"\n'
            'commit = "%s"\n'
            "[esp_idf]\n"
            'repo = "https://github.com/espressif/esp-idf"\n'
            'ref = "v5.5.1"\n'
            'commit = "%s"\n'
            "[pyble]\n"
            'agent_version = "0.6.0"\n'
            'protocol_version = "PBLE/1"\n'
            "[arm_gnu_toolchain]\n"
            'release = "14.2.Rel1"\n'
            'gcc_version = "14.2.1 20241119"\n'
            'sha256 = "%s"\n'
            'url = "https://example.invalid/arm-gnu.tar.xz"\n'
            % ("2" * 40, "3" * 40, "4" * 64),
            encoding="utf-8",
        )
        toolchain = firmware / ".arm-gnu"
        (toolchain / "lib").mkdir(parents=True)
        (toolchain / "licenses").mkdir()
        (toolchain / "lib" / "libgcc.a").write_bytes(
            b"synthetic ARM GNU runtime archive\n"
        )
        (toolchain / "licenses" / "COPYING3").write_text(
            "Synthetic complete GPLv3 fixture text.\n",
            encoding="utf-8",
        )
        (toolchain / "licenses" / "GCC-RUNTIME-LIBRARY-EXCEPTION").write_text(
            "Synthetic complete GCC Runtime Library Exception fixture text.\n",
            encoding="utf-8",
        )
        license_text = firmware / "licenses" / "rp2-fixture-mit.txt"
        license_text.parent.mkdir(parents=True)
        license_text.write_text(
            "Synthetic complete MIT fixture text.\n",
            encoding="utf-8",
        )
        policy_path = firmware / "licenses" / "rp2-license-policy.json"
        write_json(
            policy_path,
            {
                "schema_version": 1,
                "profile_id": "rpi-pico2-w",
                "target": "rpi-pico2-w",
                "source_owners": [
                    {
                        "id": "fixture-rp2",
                        "source_roots": [
                            {"namespace": "repo", "path": "firmware"}
                        ],
                        "source_ref": "0.6.0-fixture",
                        "source_url": "https://example.invalid/pyble-rp2-fixture",
                        "source_spdx_expression": "MIT",
                        "selected_spdx_expression": "MIT",
                        "copyright": "Synthetic PyBLE RP2 fixture",
                        "license_texts": [
                            {
                                "identifier": "MIT",
                                "path": "firmware/licenses/rp2-fixture-mit.txt",
                                "sha256": sha256_path(license_text),
                            }
                        ],
                        "notice_files": [],
                        "disposition": "allow",
                    }
                ],
            },
        )
        self.tool_lock = {
            "inputs": {
                "rp2_license_policy_path": (
                    "firmware/licenses/rp2-license-policy.json"
                ),
                "rp2_license_policy_sha256": sha256_path(policy_path),
            },
            "_artifact_hashes": {"esp-idf-sbom": "6" * 64},
        }

    def _provenance(self, target: str, rp2: bool = False) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": 1,
            "target": target,
            "source_date_epoch": 1786464000,
            "pyble": {"commit": "1" * 40, "clean": True},
            "micropython": {"commit": "2" * 40},
        }
        if rp2:
            value.update(
                {
                    "port": "rp2",
                    "board": "PYBLE_RPI_PICO2_W",
                    "arm_gnu_toolchain": {
                        "release": "14.2.Rel1",
                        "gcc": "arm-none-eabi-gcc 14.2.1 20241119",
                    },
                    "picotool": "picotool v2.3.0 (fixture)",
                    "firmware_bin_bytes": 4,
                }
            )
        else:
            value["esp_idf"] = {"commit": "3" * 40}
        return value

    def _make_builds(self) -> None:
        for profile_id, target in ESP_TARGETS.items():
            directory = self.build / target
            directory.mkdir()
            write_json(
                directory / "pyble-build-provenance.json",
                self._provenance(target),
            )

        pico = self.build / "rpi-pico2-w"
        (pico / "CMakeFiles" / "firmware.dir").mkdir(parents=True)
        (pico / "frozen_mpy").mkdir()
        (pico / "firmware.elf").write_bytes(b"\x7fELFsynthetic RP2350 fixture")
        (pico / "CMakeFiles" / "firmware.dir" / "link.txt").write_text(
            "arm-none-eabi-gcc rp2.o pico-sdk.o btstack.o cyw43.o "
            "tinyusb.o -lgcc -o firmware.elf\n",
            encoding="utf-8",
        )
        (pico / "frozen_content.c").write_text(
            "// synthetic frozen content\n",
            encoding="utf-8",
        )
        (pico / "frozen_mpy" / "pyble_agent.mpy").write_bytes(
            b"synthetic frozen pyble agent\n"
        )
        write_json(
            pico / "pyble-build-provenance.json",
            self._provenance("rpi-pico2-w", rp2=True),
        )

        source = self.build / ".sources" / "rpi-pico2-w" / "micropython"
        source_records = {
            "ports/rp2/modrp2.c": b"/* synthetic RP2 port source */\n",
            "py/compile.c": b"/* synthetic MicroPython core source */\n",
            "lib/pico-sdk/src/pico.c": b"/* synthetic pico-sdk source */\n",
            "lib/btstack/src/btstack.c": b"/* synthetic BTstack source */\n",
            "lib/cyw43-driver/src/cyw43.c": b"/* synthetic CYW43 source */\n",
            "lib/tinyusb/src/tusb.c": b"/* synthetic TinyUSB source */\n",
        }
        for relative, value in source_records.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        for relative in (
            "LICENSE",
            "lib/pico-sdk/LICENSE.TXT",
            "lib/btstack/LICENSE",
            "lib/cyw43-driver/LICENSE",
            "lib/tinyusb/LICENSE",
        ):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "Synthetic complete license fixture for %s.\n" % relative,
                encoding="utf-8",
            )

    def _make_esp_evidence(self) -> None:
        for profile_id in ESP_TARGETS:
            for role in ("application", "bootloader"):
                raw = self.evidence / "raw" / (
                    "%s--%s.spdx.tag" % (profile_id, role)
                )
                reviewed = self.evidence / "spdx" / (
                    "%s--%s.spdx.json" % (profile_id, role)
                )
                raw.parent.mkdir(parents=True, exist_ok=True)
                reviewed.parent.mkdir(parents=True, exist_ok=True)
                raw.write_text(
                    "SPDXVersion: SPDX-2.2\n"
                    "DocumentName: synthetic-%s-%s\n" % (profile_id, role),
                    encoding="utf-8",
                )
                write_json(
                    reviewed,
                    {
                        "spdxVersion": "SPDX-2.2",
                        "name": "synthetic-%s-%s" % (profile_id, role),
                    },
                )

    def _input(self, kind: str, path: Path, root: Path, prefix: str) -> dict[str, str]:
        return {
            "kind": kind,
            "logical_path": "%s/%s"
            % (prefix, path.relative_to(root).as_posix()),
            "sha256": sha256_path(path),
        }

    def _role_inputs(self, role: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        pico = self.build / "rpi-pico2-w"
        source = self.build / ".sources" / "rpi-pico2-w" / "micropython"
        firmware = self.repo / "firmware"
        if role == "linked-inputs":
            inputs = [
                self._input("linked-elf", pico / "firmware.elf", self.build, "build"),
                self._input(
                    "linker-command",
                    pico / "CMakeFiles" / "firmware.dir" / "link.txt",
                    self.build,
                    "build",
                ),
                self._input(
                    "micropython-rp2-source",
                    source / "ports" / "rp2" / "modrp2.c",
                    self.build,
                    "build",
                ),
            ]
            licenses = [self._input("license", source / "LICENSE", self.build, "build")]
        elif role == "frozen-modules":
            inputs = [
                self._input(
                    "frozen-manifest",
                    firmware / "board_overlays" / "rpi-pico2-w" / "manifest.py",
                    self.repo,
                    "repo",
                ),
                self._input(
                    "frozen-content", pico / "frozen_content.c", self.build, "build"
                ),
                self._input(
                    "frozen-mpy",
                    pico / "frozen_mpy" / "pyble_agent.mpy",
                    self.build,
                    "build",
                ),
            ]
            licenses = [self._input("license", source / "LICENSE", self.build, "build")]
        elif role == "arm-gnu-runtime":
            toolchain = firmware / ".arm-gnu"
            inputs = [
                self._input(
                    "linked-runtime-archive",
                    toolchain / "lib" / "libgcc.a",
                    self.repo,
                    "repo",
                ),
                self._input(
                    "toolchain-pin",
                    firmware / "versions.lock",
                    self.repo,
                    "repo",
                ),
            ]
            licenses = [
                self._input(
                    "license", toolchain / "licenses" / name, self.repo, "repo"
                )
                for name in ("COPYING3", "GCC-RUNTIME-LIBRARY-EXCEPTION")
            ]
        else:
            source_dir = {
                "pico-sdk": "pico-sdk",
                "btstack": "btstack",
                "cyw43": "cyw43-driver",
                "tinyusb": "tinyusb",
            }[role]
            source_name = {
                "pico-sdk": "pico.c",
                "btstack": "btstack.c",
                "cyw43": "cyw43.c",
                "tinyusb": "tusb.c",
            }[role]
            source_path = source / "lib" / source_dir / "src" / source_name
            license_name = "LICENSE.TXT" if role == "pico-sdk" else "LICENSE"
            inputs = [
                self._input("linked-source", source_path, self.build, "build")
            ]
            licenses = [
                self._input(
                    "license",
                    source / "lib" / source_dir / license_name,
                    self.build,
                    "build",
                )
            ]
        return inputs, licenses

    def _make_rp2_evidence(self) -> None:
        pico = self.build / "rpi-pico2-w"
        source = self.build / ".sources" / "rpi-pico2-w" / "micropython"
        provenance_digest = sha256_path(pico / "pyble-build-provenance.json")
        source_identity = {
            "micropython_commit": "2" * 40,
            "rp2_port_tree_sha256": tree_sha256(source / "ports" / "rp2"),
            "arm_gnu_toolchain": {
                "release": "14.2.Rel1",
                "gcc": "arm-none-eabi-gcc 14.2.1 20241119",
                "versions_lock_sha256": sha256_path(
                    self.repo / "firmware" / "versions.lock"
                ),
            },
        }
        for role in RP2_ROLES:
            inputs, licenses = self._role_inputs(role)
            write_json(
                self.evidence / "rp2" / ("rpi-pico2-w--%s.json" % role),
                {
                    "schema_version": 1,
                    "profile_id": "rpi-pico2-w",
                    "target": "rpi-pico2-w",
                    "resource_kind": "rp2",
                    "role": role,
                    "build_provenance_sha256": provenance_digest,
                    "source_identity": copy.deepcopy(source_identity),
                    "inputs": inputs,
                    "license_inputs": licenses,
                },
            )

    def _make_rp2_observation(self) -> dict[str, object]:
        role_documents = {
            role: json.loads(
                (
                    self.evidence
                    / "rp2"
                    / ("rpi-pico2-w--%s.json" % role)
                ).read_text(encoding="utf-8")
            )
            for role in RP2_ROLES
        }
        input_sha256 = {
            "repo/firmware/licenses/rp2-license-policy.json": (
                self.tool_lock["inputs"]["rp2_license_policy_sha256"]
            )
        }
        payload = {
            "input_sha256": input_sha256,
            "owners": [{"id": "fixture-rp2", "disposition": "allow"}],
            "notice_records": [],
            "role_documents": role_documents,
            "generated_object_derivations": [],
        }
        return {
            "semantic_sha256": sha256_bytes(canonical_json_bytes(payload)),
            **payload,
        }

    def _make_release_inventory(self) -> None:
        profiles = []
        for profile_id, target in ESP_TARGETS.items():
            roles = []
            for role in ("application", "bootloader"):
                raw_path = "raw/%s--%s.spdx.tag" % (profile_id, role)
                reviewed_path = "spdx/%s--%s.spdx.json" % (profile_id, role)
                roles.append(
                    {
                        "role": role,
                        "raw_path": raw_path,
                        "raw_sha256": sha256_path(self.evidence / raw_path),
                        "reviewed_path": reviewed_path,
                        "reviewed_sha256": sha256_path(
                            self.evidence / reviewed_path
                        ),
                    }
                )
            profiles.append(
                {
                    "profile_id": profile_id,
                    "target": target,
                    "resource_kind": "esp-idf",
                    "build_provenance_sha256": sha256_path(
                        self.build / target / "pyble-build-provenance.json"
                    ),
                    "roles": roles,
                }
            )
        pico_roles = []
        for role in RP2_ROLES:
            relative = "rp2/rpi-pico2-w--%s.json" % role
            pico_roles.append(
                {
                    "role": role,
                    "evidence_path": relative,
                    "evidence_sha256": sha256_path(self.evidence / relative),
                }
            )
        profiles.append(
            {
                "profile_id": "rpi-pico2-w",
                "target": "rpi-pico2-w",
                "resource_kind": "rp2",
                "build_provenance_sha256": sha256_path(
                    self.build
                    / "rpi-pico2-w"
                    / "pyble-build-provenance.json"
                ),
                "roles": pico_roles,
            }
        )
        write_json(
            self.evidence / "release-inventory.json",
            {
                "schema_version": 1,
                "firmware_version": "0.6.0",
                "profile_order": list(V060_PROFILE_ORDER),
                "notice_sha256": sha256_bytes(self.notice.encode("utf-8")),
                "profiles": profiles,
            },
        )

    def _make_receipt(self) -> None:
        evidence_hashes = {
            path.relative_to(self.evidence).as_posix(): sha256_path(path)
            for path in sorted(self.evidence.rglob("*"))
            if path.is_file() and path.name != "audit-receipt.json"
        }
        identities = [
            {"profile_id": profile_id, "role": role}
            for profile_id in ESP_TARGETS
            for role in ("application", "bootloader")
        ] + [
            {"profile_id": "rpi-pico2-w", "role": role}
            for role in RP2_ROLES
        ]
        write_json(
            self.evidence / "audit-receipt.json",
            {
                "schema_version": 2,
                "notice_sha256": sha256_bytes(self.notice.encode("utf-8")),
                "input_sha256": {
                    "semantic/rp2-license-closure": self.rp2_observation[
                        "semantic_sha256"
                    ],
                    **{
                        "rp2-input/%s" % name: digest
                        for name, digest in self.rp2_observation[
                            "input_sha256"
                        ].items()
                    },
                },
                "executed_artifacts": {"esp-idf-sbom": "6" * 64},
                "execution_identity": {"fixture": "network-isolated"},
                "identities": identities,
                "evidence_sha256": evidence_hashes,
                "release_inventory_path": "release-inventory.json",
                "release_inventory_sha256": evidence_hashes[
                    "release-inventory.json"
                ],
            },
        )

    def refresh_inventory_and_receipt(self) -> None:
        inventory = self.evidence / "release-inventory.json"
        receipt_path = self.evidence / "audit-receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["release_inventory_sha256"] = sha256_path(inventory)
        receipt["evidence_sha256"] = {
            path.relative_to(self.evidence).as_posix(): sha256_path(path)
            for path in sorted(self.evidence.rglob("*"))
            if path.is_file() and path != receipt_path
        }
        write_json(receipt_path, receipt)


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class V060LicenseInventoryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = V060LicenseFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def verifier(self):
        helper = getattr(
            RELEASE,
            "_audit_verify_release_inventory_evidence",
            None,
        )
        self.assertTrue(
            callable(helper),
            "v0.6 needs a persisted, recomputed heterogeneous receipt verifier",
        )
        return helper

    def verify(self):
        helper = self.verifier()
        if not callable(helper):
            return None
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
            return helper(
                evidence_dir=self.fixture.evidence,
                build_root=self.fixture.build,
                repo_root=self.fixture.repo,
                notice=self.fixture.notice,
                firmware_version="0.6.0",
            )

    def test_source_era_inventory_is_exact_and_preserves_history(self) -> None:
        helper = RELEASE._release_license_inventory_for_version
        for version, order in (
            ("0.4.2", V042_PROFILE_ORDER),
            ("0.5.1", V05_PROFILE_ORDER),
            ("0.6.0", V060_PROFILE_ORDER),
        ):
            with self.subTest(version=version):
                inventory = helper(version)
                self.assertEqual(
                    [record["profile_id"] for record in inventory],
                    list(order),
                )
                for record in inventory[:-1] if version == "0.6.0" else inventory:
                    self.assertEqual(record["resource_kind"], "esp-idf")
                    self.assertEqual(record["roles"], ["application", "bootloader"])

        pico = helper("0.6.0")[-1]
        self.assertEqual(pico["resource_kind"], "rp2")
        self.assertEqual(tuple(pico["roles"]), RP2_ROLES)

    def test_complete_schema2_receipt_is_recomputed_and_accepted(self) -> None:
        result = self.verify()
        if result is None:
            return
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["profile_order"], list(V060_PROFILE_ORDER))
        self.assertEqual(
            [record["resource_kind"] for record in result["profiles"]],
            ["esp-idf", "esp-idf", "esp-idf", "esp-idf", "rp2"],
        )
        self.assertEqual(
            [record["role"] for record in result["profiles"][-1]["roles"]],
            list(RP2_ROLES),
        )

    def test_missing_tinyusb_is_rejected_even_when_receipt_is_rehashed(self) -> None:
        inventory_path = self.fixture.evidence / "release-inventory.json"
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        inventory["profiles"][-1]["roles"] = [
            record
            for record in inventory["profiles"][-1]["roles"]
            if record["role"] != "tinyusb"
        ]
        write_json(inventory_path, inventory)
        tinyusb = self.fixture.evidence / "rp2" / "rpi-pico2-w--tinyusb.json"
        tinyusb.unlink()
        receipt_path = self.fixture.evidence / "audit-receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["identities"] = [
            record
            for record in receipt["identities"]
            if not (
                record["profile_id"] == "rpi-pico2-w"
                and record["role"] == "tinyusb"
            )
        ]
        write_json(receipt_path, receipt)
        self.fixture.refresh_inventory_and_receipt()
        with self.assertRaises(RELEASE.ReleaseError):
            self.verify()

    def test_tampered_role_evidence_is_rejected(self) -> None:
        path = self.fixture.evidence / "rp2" / "rpi-pico2-w--btstack.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(RELEASE.ReleaseError):
            self.verify()

    def test_stale_linked_source_is_rejected(self) -> None:
        source = (
            self.fixture.build
            / ".sources"
            / "rpi-pico2-w"
            / "micropython"
            / "ports"
            / "rp2"
            / "modrp2.c"
        )
        source.write_bytes(source.read_bytes() + b"/* drift */\n")
        with self.assertRaises(RELEASE.ReleaseError):
            self.verify()

    def test_stale_build_provenance_is_rejected(self) -> None:
        path = (
            self.fixture.build
            / "rpi-pico2-w"
            / "pyble-build-provenance.json"
        )
        provenance = json.loads(path.read_text(encoding="utf-8"))
        provenance["pyble"]["commit"] = "7" * 40
        write_json(path, provenance)
        with self.assertRaises(RELEASE.ReleaseError):
            self.verify()

    def test_symlinked_evidence_is_rejected(self) -> None:
        path = self.fixture.evidence / "rp2" / "rpi-pico2-w--cyw43.json"
        replacement = self.fixture.root / "outside-cyw43.json"
        replacement.write_bytes(path.read_bytes())
        path.unlink()
        os.symlink(replacement, path)
        with self.assertRaises(RELEASE.ReleaseError):
            self.verify()

    def test_notice_substitution_is_rejected(self) -> None:
        helper = self.verifier()
        if not callable(helper):
            return
        with self.assertRaises(RELEASE.ReleaseError):
            helper(
                evidence_dir=self.fixture.evidence,
                build_root=self.fixture.build,
                repo_root=self.fixture.repo,
                notice="Different notice bytes.\n",
                firmware_version="0.6.0",
            )

    def test_rp2_cannot_be_replaced_by_self_consistent_esp_evidence(self) -> None:
        inventory_path = self.fixture.evidence / "release-inventory.json"
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        pico = inventory["profiles"][-1]
        pico["resource_kind"] = "esp-idf"
        pico["roles"] = []
        for role in ("application", "bootloader"):
            raw_relative = "raw/rpi-pico2-w--%s.spdx.tag" % role
            reviewed_relative = "spdx/rpi-pico2-w--%s.spdx.json" % role
            shutil.copyfile(
                self.fixture.evidence / ("raw/esp32-4mb--%s.spdx.tag" % role),
                self.fixture.evidence / raw_relative,
            )
            shutil.copyfile(
                self.fixture.evidence / ("spdx/esp32-4mb--%s.spdx.json" % role),
                self.fixture.evidence / reviewed_relative,
            )
            pico["roles"].append(
                {
                    "role": role,
                    "raw_path": raw_relative,
                    "raw_sha256": sha256_path(self.fixture.evidence / raw_relative),
                    "reviewed_path": reviewed_relative,
                    "reviewed_sha256": sha256_path(
                        self.fixture.evidence / reviewed_relative
                    ),
                }
            )
        write_json(inventory_path, inventory)
        shutil.rmtree(self.fixture.evidence / "rp2")
        receipt_path = self.fixture.evidence / "audit-receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["identities"] = [
            record
            for record in receipt["identities"]
            if record["profile_id"] != "rpi-pico2-w"
        ] + [
            {"profile_id": "rpi-pico2-w", "role": role}
            for role in ("application", "bootloader")
        ]
        write_json(receipt_path, receipt)
        self.fixture.refresh_inventory_and_receipt()
        with self.assertRaises(RELEASE.ReleaseError):
            self.verify()

    def test_v060_candidate_and_public_audit_dispatch_consumes_receipt(self) -> None:
        helper = self.verifier()
        if not callable(helper):
            return
        sentinel = RELEASE.ReleaseError("heterogeneous receipt dispatch sentinel")
        with (
            mock.patch.object(
                RELEASE,
                "_audit_verify_release_inventory_evidence",
                side_effect=sentinel,
            ) as verifier,
            mock.patch.object(RELEASE, "_audit_verify_packaged_build") as packaged,
        ):
            with self.assertRaisesRegex(
                RELEASE.ReleaseError,
                "heterogeneous receipt dispatch sentinel",
            ):
                RELEASE._audit_verify_release_evidence(
                    notice=self.fixture.notice,
                    evidence_dir=self.fixture.evidence,
                    build_root=self.fixture.build,
                    repo_root=self.fixture.repo,
                    bundle=self.fixture.root / "bundle",
                    release={"identity": {"version": "0.6.0"}},
                )
            verifier.assert_called_once()
            packaged.assert_called_once()

        for public_seam in (
            RELEASE.create_bundle,
            RELEASE.validate_bundle,
            RELEASE.finalize_public_bundle,
        ):
            with self.subTest(public_seam=public_seam.__name__):
                self.assertIn(
                    "_audit_verify_release_evidence(",
                    inspect.getsource(public_seam),
                )

    def test_historical_audit_dispatch_does_not_require_v060_receipt(self) -> None:
        helper = self.verifier()
        if not callable(helper):
            return
        with mock.patch.object(
            RELEASE,
            "_audit_verify_release_inventory_evidence",
            side_effect=AssertionError("historical audit entered v0.6 verifier"),
        ) as verifier:
            with self.assertRaises(RELEASE.ReleaseError):
                RELEASE._audit_verify_release_evidence(
                    notice=self.fixture.notice,
                    evidence_dir=self.fixture.root / "missing-historical-evidence",
                    build_root=self.fixture.build,
                    repo_root=self.fixture.repo,
                    release={"identity": {"version": "0.5.1"}},
                )
            verifier.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
