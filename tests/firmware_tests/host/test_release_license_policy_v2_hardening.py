#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] BLD-8 — Harden schema-v2 release-license resolution.
#
# Frozen sources:
#   docs/specifications/firmware/browser-flashing.md §6 rules 1, 4–9
#   docs/specifications/firmware/TDD.md §10.7 and §14.3
#
# These regressions cover security boundaries deliberately kept separate from
# the basic schema-v2 contract suite.  A passing implementation must reject
# caller-selected provenance while still accepting the safe internal links
# present in the pinned Espressif toolchain distributions.

from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import unittest
from unittest import mock

from tests.firmware_tests.host import test_release_license_policy_v2 as V2


RELEASE = V2.RELEASE
BASE = V2.BASE
PROFILE_ROLES = V2.PROFILE_ROLES


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def safe_link_distribution(
    *,
    root_name: str,
    files: dict[str, bytes],
    include_directories: bool,
    include_links: bool,
) -> bytes:
    """Return a small real-shaped tar.xz with safe internal link entries."""

    output = io.BytesIO()
    with tarfile.open(
        fileobj=output,
        mode="w:xz",
        format=tarfile.PAX_FORMAT,
    ) as archive:
        if include_directories:
            directories = (
                root_name,
                "%s/bin" % root_name,
                "%s/lib" % root_name,
                "%s/share" % root_name,
                "%s/share/licenses" % root_name,
            )
            for name in directories:
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.mtime = 0
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                archive.addfile(info)

        for relative, value in sorted(files.items()):
            info = tarfile.TarInfo("%s/%s" % (root_name, relative))
            info.size = len(value)
            info.mode = 0o755 if relative.startswith("bin/") else 0o644
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            archive.addfile(info, io.BytesIO(value))

        copying_name = "%s/share/licenses/COPYING" % root_name
        copying = b"synthetic complete toolchain terms\n"
        info = tarfile.TarInfo(copying_name)
        info.size = len(copying)
        info.mode = 0o644
        info.mtime = 0
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        archive.addfile(info, io.BytesIO(copying))

        if include_links:
            # Espressif's pinned distributions contain both forms.  Both
            # targets remain within the declared archive root and are
            # intentionally not compiler/runtime inputs.
            info = tarfile.TarInfo("%s/share/licenses/LICENSE" % root_name)
            info.type = tarfile.SYMTYPE
            info.linkname = "COPYING"
            info.mode = 0o777
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            archive.addfile(info)

            info = tarfile.TarInfo(
                "%s/share/licenses/COPYING.alias" % root_name
            )
            info.type = tarfile.LNKTYPE
            info.linkname = copying_name
            info.mode = 0o644
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            archive.addfile(info)
    return output.getvalue()


@unittest.skipUnless(
    RELEASE is not None and callable(getattr(RELEASE, "_audit_validate_policy_v2", None)),
    "schema-v2 hardening waits for release_bundle.py",
)
class PolicyV2HardeningTests(unittest.TestCase):
    def setUp(self):
        self.fixture = V2.PolicyV2Fixture()

    def tearDown(self):
        self.fixture.close()

    def validate(self, *, observed_inputs=None, toolchain_roots=None):
        return RELEASE._audit_validate_policy_v2(
            self.fixture.policy,
            repo_root=self.fixture.repo,
            observed_documents=self.fixture.observed_documents,
            observed_inputs=(
                self.fixture.observed_inputs
                if observed_inputs is None
                else observed_inputs
            ),
            manifest_evidence=self.fixture.manifest_evidence,
            toolchain_roots=(
                self.fixture.toolchain_context()
                if toolchain_roots is None
                else toolchain_roots
            ),
        )

    def assert_rejected(self, **overrides):
        with self.assertRaises(RELEASE.ReleaseError):
            self.validate(**overrides)

    def assert_valid(self, **overrides):
        try:
            return self.validate(**overrides)
        except RELEASE.ReleaseError as exc:
            self.fail("valid schema-v2 evidence was rejected: %s" % exc)

    def replace_distribution(self, value: bytes):
        distribution = self.fixture.toolchain["distribution"]
        distribution.write_bytes(value)
        policy = self.fixture.policy["toolchains"][0]["distribution"]
        policy["size"] = len(value)
        policy["sha256"] = V2.sha256_bytes(value)

    def test_safe_distribution_root_directory_entries_are_accepted(self):
        payload = safe_link_distribution(
            root_name=self.fixture.toolchain["root_name"],
            files=self.fixture.toolchain["files"],
            include_directories=True,
            include_links=False,
        )
        self.replace_distribution(payload)
        self.assert_valid()

    def test_safe_internal_symlink_and_hardlink_entries_are_accepted(self):
        payload = safe_link_distribution(
            root_name=self.fixture.toolchain["root_name"],
            files=self.fixture.toolchain["files"],
            include_directories=False,
            include_links=True,
        )
        self.replace_distribution(payload)
        self.assert_valid()

    def test_distribution_validation_is_bounded_and_streaming(self):
        original_read = RELEASE.tarfile.ExFileObject.read

        def bounded_read(stream, size=-1):
            if size is None or size < 0:
                raise AssertionError(
                    "toolchain validation must not read an expanded member unbounded"
                )
            return original_read(stream, size)

        with mock.patch.object(
            RELEASE.tarfile.ExFileObject,
            "read",
            new=bounded_read,
        ):
            self.validate()

    def _toolchain_observations_below(
        self,
        root: Path,
    ) -> list[dict]:
        observed = copy.deepcopy(self.fixture.observed_inputs)
        for record in observed:
            if record["kind"] != "toolchain-archive":
                continue
            record["observed_path"] = str(root / record["relative_path"])
            record["compiler_paths"] = [
                str(root / relative)
                for relative in self.fixture.toolchain[
                    "compiler_relatives"
                ]
            ]
        return observed

    def _alternate_toolchain_root(self) -> tuple[Path, Path]:
        toolchain = self.fixture.toolchain
        alternate_parent = self.fixture.root / "caller-selected-tools"
        alternate_parent.mkdir()
        alternate = alternate_parent / toolchain["root_name"]
        shutil.copytree(toolchain["installed_root"], alternate)
        alias_parent = self.fixture.root / "symlinked-tool-parent"
        alias_parent.symlink_to(alternate_parent, target_is_directory=True)
        return alternate, alias_parent / toolchain["root_name"]

    def test_caller_selected_same_name_toolchain_root_is_rejected(self):
        candidate, _alias = self._alternate_toolchain_root()
        self.assert_rejected(
            observed_inputs=self._toolchain_observations_below(candidate),
            toolchain_roots={self.fixture.toolchain["id"]: candidate},
        )

    def test_toolchain_root_with_symlink_ancestor_is_rejected(self):
        _alternate, candidate = self._alternate_toolchain_root()
        self.assert_rejected(
            observed_inputs=self._toolchain_observations_below(candidate),
            toolchain_roots={self.fixture.toolchain["id"]: candidate},
        )

    def test_validated_result_contains_no_host_absolute_path(self):
        result = self.validate()
        for scalar in V2.deep_scalars(result):
            if not isinstance(scalar, str):
                continue
            self.assertFalse(
                Path(scalar).is_absolute(),
                "receipt-ready validation leaked host path %r" % scalar,
            )
            self.assertNotIn(str(self.fixture.root), scalar)

    def test_resolved_expression_must_have_its_exact_complete_texts(self):
        resolution = next(
            record
            for record in self.fixture.policy["resolutions"]
            if record["id"] == "resolve-core"
        )
        resolution["resolved_input_expression"] = "Apache-2.0"
        self.assert_rejected()

    def test_inputs_cannot_be_swapped_between_incompatible_packages(self):
        runtime = next(
            record
            for record in self.fixture.policy["resolutions"]
            if record["id"] == "resolve-runtime"
        )
        opaque = next(
            record
            for record in self.fixture.policy["resolutions"]
            if record["id"] == "resolve-opaque"
        )
        runtime_application = [
            identifier
            for identifier in runtime["input_refs"]
            if identifier.endswith("--application")
        ]
        runtime["input_refs"] = [
            identifier
            for identifier in runtime["input_refs"]
            if identifier not in runtime_application
        ] + list(opaque["input_refs"])
        opaque["input_refs"] = runtime_application
        self.assert_rejected()

    def _make_not_shipped_opaque(self) -> list[dict]:
        self.fixture.policy["resolved_inputs"] = [
            record
            for record in self.fixture.policy["resolved_inputs"]
            if not record["id"].startswith("opaque--")
        ]
        observed = [
            record
            for record in copy.deepcopy(self.fixture.observed_inputs)
            if not record["id"].startswith("opaque--")
        ]
        resolution = next(
            record
            for record in self.fixture.policy["resolutions"]
            if record["id"] == "resolve-opaque"
        )
        resolution["input_refs"] = []
        resolution["disposition"] = "not-shipped"

        proof_records = [
            {
                "profile_id": package_ref["profile_id"],
                "role": package_ref["role"],
                "matched_input_ids": [],
            }
            for package_ref in resolution["package_refs"]
        ]
        resolution["zero_input_proof"] = {
            "profile_roles": sorted(
                proof_records,
                key=lambda record: (record["profile_id"], record["role"]),
            )
        }
        self.fixture.refresh_shipment_review(self.fixture.policy)
        return observed

    def test_not_shipped_proof_is_collector_bound_and_omitted_from_notice(self):
        observed = self._make_not_shipped_opaque()
        result = self.assert_valid(observed_inputs=observed)

        self.assertNotIn(
            "opaque",
            {record["id"] for record in result["notice_records"]},
        )
        resolution = next(
            record
            for record in result["resolutions"]
            if record["id"] == "resolve-opaque"
        )
        self.assertIn("zero_input_proof", resolution)
        for proof in resolution["zero_input_proof"]["profile_roles"]:
            owner_id = "core--%s--%s" % (
                proof["profile_id"],
                proof["role"],
            )
            owner = next(record for record in observed if record["id"] == owner_id)
            binding = owner["generated_binding"]
            self.assertEqual(
                proof,
                {
                    "profile_id": proof["profile_id"],
                    "role": proof["role"],
                    "project_description_sha256": (
                        binding["project_description_sha256"]
                    ),
                    "compile_commands_sha256": (
                        binding["compile_commands_sha256"]
                    ),
                    "linker_map_sha256": binding["linker_map_sha256"],
                    "matched_input_ids": [],
                },
            )

        policy_resolution = next(
            record
            for record in self.fixture.policy["resolutions"]
            if record["id"] == "resolve-opaque"
        )
        policy_resolution["zero_input_proof"]["profile_roles"][0][
            "linker_map_sha256"
        ] = "0" * 64
        self.assert_rejected(observed_inputs=observed)

    def test_generated_supplemental_archives_require_member_proof(self):
        observed = copy.deepcopy(self.fixture.observed_inputs)
        for record in observed:
            if record["kind"] == "generated-supplemental-archive":
                record["generated_binding"].pop("members")
        self.assert_rejected(observed_inputs=observed)

    def test_generated_archive_members_are_a_counted_multiset(self):
        identifier = "mbedcrypto--esp32-4mb"
        observed = copy.deepcopy(self.fixture.observed_inputs)
        observed_record = next(
            record for record in observed if record["id"] == identifier
        )
        archive = Path(observed_record["observed_path"])
        value = BASE.make_ar_bytes(
            [
                ("aes.o", b"first duplicate member\n"),
                ("aes.o", b"second duplicate member\n"),
            ]
        )
        archive.write_bytes(value)
        observed_record["sha256"] = V2.sha256_bytes(value)
        observed_record["generated_binding"]["members"] = ["aes.o", "aes.o"]
        self.assert_valid(observed_inputs=observed)

    def test_generated_source_paths_are_canonical_and_unique(self):
        identifier = "core--esp32-4mb--application"
        observed = copy.deepcopy(self.fixture.observed_inputs)
        observed_record = next(
            record for record in observed if record["id"] == identifier
        )
        duplicate = copy.deepcopy(
            observed_record["generated_binding"]["sources"][0]
        )
        duplicate["sha256"] = "f" * 64
        observed_record["generated_binding"]["sources"].append(duplicate)
        self.assert_rejected(observed_inputs=observed)

    def test_receipt_result_hashes_every_validated_semantic_record_set(self):
        result = self.validate()
        result_scalars = {
            scalar
            for scalar in V2.deep_scalars(result)
            if isinstance(scalar, str)
        }
        collections = {
            "raw_documents": self.fixture.policy["raw_documents"],
            "review_files": self.fixture.policy["review_files"],
            "reviewed_packages": self.fixture.policy["reviewed_packages"],
            "resolved_inputs": self.fixture.policy["resolved_inputs"],
            "resolutions": result["resolutions"],
            "supplemental_packages": self.fixture.policy[
                "supplemental_packages"
            ],
            "toolchains": self.fixture.policy["toolchains"],
            "generated_bindings": result["generated_bindings"],
        }
        missing = [
            label
            for label, records in collections.items()
            if canonical_sha256(records) not in result_scalars
        ]
        self.assertEqual(
            missing,
            [],
            "receipt-ready result lacks semantic hashes for %s"
            % ", ".join(missing),
        )

    def test_supplemental_relationship_is_exactly_depends_on(self):
        package = next(
            record
            for record in self.fixture.policy["supplemental_packages"]
            if record["id"] == "supplemental-mbedtls"
        )
        package["relationship"]["relationship_type"] = (
            "NOT_A_REAL_SPDX_RELATIONSHIP"
        )
        self.assert_rejected()

    def test_observed_input_with_symlink_ancestor_is_rejected(self):
        identifier = "core--esp32-4mb--application"
        observed = copy.deepcopy(self.fixture.observed_inputs)
        record = next(item for item in observed if item["id"] == identifier)
        original = Path(record["observed_path"])
        relative = original.relative_to(self.fixture.build.resolve())
        alias = self.fixture.root / "symlinked-build-root"
        alias.symlink_to(self.fixture.build, target_is_directory=True)
        record["observed_path"] = str(alias / relative)
        self.assert_rejected(observed_inputs=observed)

    def test_normalized_metadata_always_names_its_review_attribution(self):
        result = self.validate()
        profile_id, role = PROFILE_ROLES[0]
        document = result["reviewed_documents"]["%s/%s" % (profile_id, role)]
        package = next(
            record
            for record in document["packages"]
            if record["SPDXID"] == V2.package_id("core")
        )
        resolution = next(
            record
            for record in self.fixture.policy["resolutions"]
            if record["id"] == "resolve-core"
        )
        self.assertIn(
            resolution["attribution"],
            package.get("attributionTexts", []),
        )

    def test_source_url_is_bound_to_the_full_immutable_ref(self):
        package = next(
            record
            for record in self.fixture.policy["reviewed_packages"]
            if record["id"] == "core"
        )
        package["dependency"]["source_url"] = (
            "https://example.invalid/core/latest"
        )
        package["source"]["url"] = package["dependency"]["source_url"]
        self.assert_rejected()

    def test_review_file_catalog_is_exact_hash_bound_and_source_identified(self):
        policy = copy.deepcopy(self.fixture.policy)
        evidence_path = self.fixture.notices / "source.txt"
        relative = evidence_path.relative_to(self.fixture.repo).as_posix()
        policy["review_files"] = [
            {
                "id": "fixture-source-attribution",
                "purpose": "Synthetic upstream attribution evidence.",
                "path": relative,
                "sha256": BASE.sha256_path(evidence_path),
                "source_identities": [
                    "a" * 40,
                    BASE.sha256_path(evidence_path),
                ],
            }
        ]

        def validate_catalog(candidate):
            return RELEASE._audit_validate_policy_v2(
                candidate,
                repo_root=self.fixture.repo,
                observed_documents=self.fixture.observed_documents,
                observed_inputs=self.fixture.observed_inputs,
                manifest_evidence=self.fixture.manifest_evidence,
                toolchain_roots=self.fixture.toolchain_context(),
            )

        result = validate_catalog(policy)
        self.assertEqual(
            result["semantic_sha256"]["review_files"],
            canonical_sha256(policy["review_files"]),
        )

        for mutation in ("duplicate-id", "duplicate-path", "no-source", "bad-hash"):
            candidate = copy.deepcopy(policy)
            if mutation == "duplicate-id":
                duplicate = copy.deepcopy(candidate["review_files"][0])
                duplicate["path"] = "firmware/licenses/notices/runtime.txt"
                duplicate["sha256"] = BASE.sha256_path(
                    self.fixture.notices / "runtime.txt"
                )
                candidate["review_files"].append(duplicate)
            elif mutation == "duplicate-path":
                duplicate = copy.deepcopy(candidate["review_files"][0])
                duplicate["id"] = "fixture-duplicate-path"
                candidate["review_files"].append(duplicate)
            elif mutation == "no-source":
                candidate["review_files"][0]["source_identities"] = []
            else:
                candidate["review_files"][0]["sha256"] = "0" * 64
            with self.subTest(mutation=mutation):
                with self.assertRaises(RELEASE.ReleaseError):
                    validate_catalog(candidate)


if __name__ == "__main__":
    unittest.main()
