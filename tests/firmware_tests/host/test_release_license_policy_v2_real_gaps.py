# SPDX-License-Identifier: MIT
#
# [red] BLD-8 — Real schema-v2 policy-model gaps.
#
# These fixtures preserve the shapes observed in the pinned ESP-IDF build:
# optional managed-component versions, CONFIG_ONLY Mbed TLS nested targets,
# distinct raw/toolchain input terms, and shipped aggregate packages with no
# exclusive archive.  The policy deliberately contains only stable matchers;
# generated identities belong to the validated receipt.

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tests.firmware_tests.host.test_release_license_policy_v2 import (
    BASE,
    PROFILE_ROLES,
    RELEASE,
    PolicyV2Fixture,
    package_id,
    sha256_bytes,
)
from tests.firmware_tests.host.test_release_license_policy_v2_integration import (
    ObservationV2Fixture,
    PROFILE_TARGETS,
)


def stable_generated_policy(policy: dict) -> dict:
    """Replace build-specific generated bindings with stable component matchers."""

    result = copy.deepcopy(policy)
    for record in result["resolved_inputs"]:
        if not record["kind"].startswith("generated-"):
            continue
        if "generated_matcher" in record:
            continue
        binding = record.pop("generated_binding")
        record["generated_matcher"] = {"component": binding["component"]}
    return result


def validate_fixture(
    fixture: PolicyV2Fixture,
    policy: dict,
    *,
    observed_documents=None,
    observed_inputs=None,
) -> dict:
    return RELEASE._audit_validate_policy_v2(
        policy,
        repo_root=fixture.repo,
        observed_documents=(
            fixture.observed_documents
            if observed_documents is None
            else observed_documents
        ),
        observed_inputs=(
            fixture.observed_inputs if observed_inputs is None else observed_inputs
        ),
        manifest_evidence=fixture.manifest_evidence,
        toolchain_roots=fixture.toolchain_context(),
    )


def reviewed_record(policy: dict, identifier: str) -> dict:
    return next(
        record for record in policy["reviewed_packages"] if record["id"] == identifier
    )


def resolution_record(policy: dict, identifier: str) -> dict:
    return next(
        record for record in policy["resolutions"] if record["id"] == identifier
    )


def supplemental_record(policy: dict, identifier: str) -> dict:
    return next(
        record
        for record in policy["supplemental_packages"]
        if record["id"] == identifier
    )


@unittest.skipUnless(RELEASE is not None, "release_bundle.py is unavailable")
class PolicyV2RealGapTests(unittest.TestCase):
    def setUp(self):
        self.fixture = PolicyV2Fixture()
        self.policy = stable_generated_policy(self.fixture.policy)

    def tearDown(self):
        self.fixture.close()

    def assert_rejected(
        self,
        policy: dict,
        *,
        observed_documents=None,
        observed_inputs=None,
    ) -> None:
        with self.assertRaises(RELEASE.ReleaseError):
            validate_fixture(
                self.fixture,
                policy,
                observed_documents=observed_documents,
                observed_inputs=observed_inputs,
            )

    def assert_valid(
        self,
        policy: dict,
        *,
        observed_documents=None,
        observed_inputs=None,
    ) -> dict:
        try:
            return validate_fixture(
                self.fixture,
                policy,
                observed_documents=observed_documents,
                observed_inputs=observed_inputs,
            )
        except RELEASE.ReleaseError as exc:
            self.fail("valid real-shaped schema-v2 policy was rejected: %s" % exc)

    def test_absent_raw_package_version_is_preserved_not_invented(self):
        """A sparse raw package may legitimately omit PackageVersion."""

        documents = copy.deepcopy(self.fixture.observed_documents)
        identity = PROFILE_ROLES[0]
        observed = next(
            package
            for package in documents[identity]["packages"]
            if package["SPDXID"] == package_id("core")
        )
        observed.pop("versionInfo")

        policy = copy.deepcopy(self.policy)
        raw_document = next(
            document
            for document in policy["raw_documents"]
            if (document["profile_id"], document["role"]) == identity
        )
        expected = next(
            package
            for package in raw_document["packages"]
            if package["SPDXID"] == package_id("core")
        )
        expected.pop("versionInfo")

        validated = self.assert_valid(
            policy,
            observed_documents=documents,
        )
        normalized = next(
            package
            for package in validated["reviewed_documents"]["%s/%s" % identity][
                "packages"
            ]
            if package["SPDXID"] == package_id("core")
        )
        self.assertEqual(
            normalized["versionInfo"],
            reviewed_record(policy, "core")["dependency"]["version_ref"],
        )

        for invented in ("", "NOASSERTION", "managed-component@invented"):
            changed = copy.deepcopy(policy)
            package = next(
                package
                for document in changed["raw_documents"]
                if (document["profile_id"], document["role"]) == identity
                for package in document["packages"]
                if package["SPDXID"] == package_id("core")
            )
            package["versionInfo"] = invented
            with self.subTest(invented_version=invented):
                self.assert_rejected(changed, observed_documents=documents)

    def test_distinct_reviewed_input_expression_does_not_rewrite_raw_toolchain(self):
        """A concrete broad raw expression and linked runtime terms stay separate."""

        raw_expression = "MIT"
        input_expression = "GPL-3.0-or-later WITH GCC-exception-3.1"
        policy = copy.deepcopy(self.policy)
        documents = copy.deepcopy(self.fixture.observed_documents)

        for document in documents.values():
            package = next(
                package
                for package in document["packages"]
                if package["SPDXID"] == package_id("runtime")
            )
            package["licenseConcluded"] = raw_expression
        for document in policy["raw_documents"]:
            package = next(
                package
                for package in document["packages"]
                if package["SPDXID"] == package_id("runtime")
            )
            package["licenseConcluded"] = raw_expression

        runtime = reviewed_record(policy, "runtime")
        runtime["reviewed_raw_package_expression"] = raw_expression
        runtime["reviewed_input_expressions"] = [input_expression]
        mit_text = copy.deepcopy(reviewed_record(policy, "core")["license_texts"][0])
        runtime["license_texts"].append(mit_text)

        validated = self.assert_valid(
            policy,
            observed_documents=documents,
        )
        for document in validated["reviewed_documents"].values():
            package = next(
                package
                for package in document["packages"]
                if package["SPDXID"] == package_id("runtime")
            )
            self.assertEqual(package["licenseConcluded"], raw_expression)
        runtime_notice = next(
            record
            for record in validated["notice_records"]
            if record["id"] == "runtime"
        )
        self.assertEqual(runtime_notice["spdx_expression"], input_expression)

        unreviewed_subset = copy.deepcopy(policy)
        resolution_record(unreviewed_subset, "resolve-runtime")[
            "resolved_input_expression"
        ] = "GPL-3.0-or-later"
        self.assert_rejected(
            unreviewed_subset,
            observed_documents=documents,
        )

        falsified_raw = copy.deepcopy(policy)
        reviewed_record(falsified_raw, "runtime")[
            "reviewed_raw_package_expression"
        ] = input_expression
        self.assert_rejected(falsified_raw, observed_documents=documents)

    def test_mbedtls_retains_source_choice_and_emits_selected_notice_only(self):
        """Original dual-license evidence remains while redistribution selects Apache."""

        gpl_path = self.fixture.texts / "GPL-2.0-or-later.txt"
        gpl_path.write_text(
            "GPL-2.0-or-later\n\nComplete synthetic fixture text.\n",
            encoding="utf-8",
        )
        policy = copy.deepcopy(self.policy)
        mbed = supplemental_record(policy, "supplemental-mbedtls")
        mbed["source_spdx_expression"] = "(Apache-2.0 OR GPL-2.0-or-later)"
        mbed["selected_spdx_expression"] = "Apache-2.0"
        apache = copy.deepcopy(reviewed_record(policy, "opaque")["license_texts"][0])
        mbed["license_texts"] = [
            apache,
            {
                "spdx_id": "GPL-2.0-or-later",
                "path": "firmware/licenses/texts/GPL-2.0-or-later.txt",
                "sha256": RELEASE._sha256_path(gpl_path),
            },
        ]

        validated = self.assert_valid(policy)
        retained = next(
            record
            for record in validated["supplemental_packages"]
            if record["id"] == "supplemental-mbedtls"
        )
        self.assertEqual(
            retained["source_spdx_expression"],
            "(Apache-2.0 OR GPL-2.0-or-later)",
        )
        self.assertEqual(retained["selected_spdx_expression"], "Apache-2.0")
        notice = next(
            record
            for record in validated["notice_records"]
            if record["id"] == "supplemental-mbedtls"
        )
        self.assertEqual(notice["spdx_expression"], "Apache-2.0")
        self.assertEqual(
            {record["spdx_id"] for record in notice["license_texts"]},
            {"Apache-2.0"},
        )

        missing_source_arm = copy.deepcopy(policy)
        supplemental_record(
            missing_source_arm,
            "supplemental-mbedtls",
        )[
            "license_texts"
        ] = [apache]
        self.assert_rejected(missing_source_arm)

        invalid_selection = copy.deepcopy(policy)
        supplemental_record(
            invalid_selection,
            "supplemental-mbedtls",
        )["selected_spdx_expression"] = "Apache-2.0 AND GPL-2.0-or-later"
        self.assert_rejected(invalid_selection)

    def test_spdx_with_accepts_only_a_known_exception_on_one_license(self):
        self.assertEqual(
            RELEASE._audit_parse_spdx(
                "GPL-3.0-or-later WITH GCC-exception-3.1",
                set(),
            ),
            {"GPL-3.0-or-later", "GCC-exception-3.1"},
        )
        for expression in (
            "MIT WITH Apache-2.0",
            "GCC-exception-3.1",
            "(MIT OR Apache-2.0) WITH GCC-exception-3.1",
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(RELEASE.ReleaseError):
                    RELEASE._audit_parse_spdx(expression, set())

    def _aggregate_policy(self) -> tuple[dict, dict]:
        policy = copy.deepcopy(self.policy)
        documents = copy.deepcopy(self.fixture.observed_documents)
        aggregate_ids = (
            "nimble",
            "esp-idf",
            "freertos",
            "lwip",
            "project-micropython",
            "project-bootloader",
            "heap-tlsf",
        )
        package_refs = {identifier: [] for identifier in aggregate_ids}
        proof_records = {identifier: [] for identifier in aggregate_ids}
        for profile_id, role in PROFILE_ROLES:
            identity = (profile_id, role)
            raw_document = next(
                document
                for document in policy["raw_documents"]
                if (document["profile_id"], document["role"]) == identity
            )
            present = (
                (
                    "nimble",
                    "esp-idf",
                    "freertos",
                    "lwip",
                    "project-micropython",
                    "heap-tlsf",
                )
                if role == "application"
                else ("esp-idf", "project-bootloader")
            )
            by_id = {}
            for identifier in present:
                package = copy.deepcopy(documents[identity]["packages"][0])
                package.update(
                    {
                        "name": "Fixture shipped %s" % identifier,
                        "SPDXID": package_id(identifier),
                        "versionInfo": "aggregate-source",
                        "licenseConcluded": "MIT",
                        "checksums": [
                            {
                                "algorithm": "SHA256",
                                "checksumValue": sha256_bytes(
                                    (
                                        "%s/%s/%s" % (profile_id, role, identifier)
                                    ).encode()
                                ),
                            }
                        ],
                    }
                )
                by_id[identifier] = package
                documents[identity]["packages"].append(package)
                raw_document["packages"].append(copy.deepcopy(package))
                package_refs[identifier].append(
                    {
                        "profile_id": profile_id,
                        "role": role,
                        "spdx_id": package_id(identifier),
                    }
                )

            project_id = (
                "project-micropython" if role == "application" else "project-bootloader"
            )
            relationships = {
                "project-core": {
                    "spdxElementId": package_id(project_id),
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": package_id("core"),
                },
                "project-esp-idf": {
                    "spdxElementId": package_id(project_id),
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": package_id("esp-idf"),
                },
            }
            if role == "application":
                for identifier in ("nimble", "freertos", "lwip", "heap-tlsf"):
                    relationships[identifier] = {
                        "spdxElementId": package_id("core"),
                        "relationshipType": "DEPENDS_ON",
                        "relatedSpdxElement": package_id(identifier),
                    }
            for relationship in relationships.values():
                documents[identity]["relationships"].append(relationship)
                raw_document["relationships"].append(copy.deepcopy(relationship))

            paths = {
                project_id: [relationships["project-core"]],
                "esp-idf": [
                    relationships["project-esp-idf"],
                    relationships["project-core"],
                ],
            }
            if role == "application":
                paths.update(
                    {
                        identifier: [relationships[identifier]]
                        for identifier in (
                            "nimble",
                            "freertos",
                            "lwip",
                            "heap-tlsf",
                        )
                    }
                )
            for identifier, path in paths.items():
                proof_records[identifier].append(
                    {
                        "profile_id": profile_id,
                        "role": role,
                        "relationship_path": copy.deepcopy(path),
                        "input_owning_reviewed_package_id": "core",
                    }
                )

        for identifier in aggregate_ids:
            aggregate = self.fixture._reviewed_package("core", "MIT")
            aggregate["id"] = identifier
            aggregate["dependency"]["name"] = "Fixture shipped %s" % identifier
            policy["reviewed_packages"].append(aggregate)
            policy["resolutions"].append(
                {
                    "id": "resolve-%s" % identifier,
                    "reviewed_package_id": identifier,
                    "package_refs": package_refs[identifier],
                    "input_refs": [],
                    "resolved_input_expression": "MIT",
                    "disposition": "allow-aggregate",
                    "attribution": "Relationship-bound shipped aggregate.",
                    "aggregate_proof": {"profile_roles": proof_records[identifier]},
                }
            )
        self.fixture.refresh_shipment_review(policy)
        return policy, documents

    def test_shipped_aggregate_is_relationship_bound_without_reusing_inputs(self):
        policy, documents = self._aggregate_policy()
        validated = self.assert_valid(
            policy,
            observed_documents=documents,
        )
        aggregates = [
            record
            for record in validated["resolutions"]
            if record["disposition"] == "allow-aggregate"
        ]
        self.assertEqual(
            sum(len(record["package_refs"]) for record in aggregates),
            sum(
                6 if role == "application" else 2
                for _profile_id, role in PROFILE_ROLES
            ),
        )
        self.assertTrue(all(record["input_refs"] == [] for record in aggregates))
        self.assertEqual(
            {
                "nimble",
                "esp-idf",
                "freertos",
                "lwip",
                "project-micropython",
                "project-bootloader",
                "heap-tlsf",
            },
            {
                record["id"]
                for record in validated["notice_records"]
                if record["id"]
                in {
                    "nimble",
                    "esp-idf",
                    "freertos",
                    "lwip",
                    "project-micropython",
                    "project-bootloader",
                    "heap-tlsf",
                }
            },
        )

        bad_target = copy.deepcopy(policy)
        resolution_record(bad_target, "resolve-nimble")["aggregate_proof"][
            "profile_roles"
        ][0]["input_owning_reviewed_package_id"] = "freertos"
        self.assert_rejected(bad_target, observed_documents=documents)

        invented_edge = copy.deepcopy(policy)
        resolution_record(invented_edge, "resolve-nimble")["aggregate_proof"][
            "profile_roles"
        ][0]["relationship_path"][0]["relatedSpdxElement"] = package_id("runtime")
        self.assert_rejected(invented_edge, observed_documents=documents)

        cyclic = copy.deepcopy(policy)
        path = resolution_record(cyclic, "resolve-nimble")["aggregate_proof"][
            "profile_roles"
        ][0]["relationship_path"]
        path.append(copy.deepcopy(path[0]))
        self.assert_rejected(cyclic, observed_documents=documents)

        reused = copy.deepcopy(policy)
        resolution_record(reused, "resolve-nimble")["input_refs"] = [
            "core--esp32-4mb--application"
        ]
        self.assert_rejected(reused, observed_documents=documents)

        rewritten_terms = copy.deepcopy(policy)
        aggregate_review = reviewed_record(rewritten_terms, "nimble")
        aggregate_review["reviewed_input_expressions"] = ["Apache-2.0"]
        aggregate_review["license_texts"].append(
            copy.deepcopy(
                reviewed_record(rewritten_terms, "opaque")["license_texts"][0]
            )
        )
        resolution_record(rewritten_terms, "resolve-nimble")[
            "resolved_input_expression"
        ] = "Apache-2.0"
        self.assert_rejected(rewritten_terms, observed_documents=documents)

        masquerade = copy.deepcopy(policy)
        rewritten = resolution_record(masquerade, "resolve-nimble")
        rewritten["disposition"] = "not-shipped"
        rewritten.pop("aggregate_proof")
        rewritten["zero_input_proof"] = {
            "profile_roles": [
                {
                    "profile_id": package_ref["profile_id"],
                    "role": package_ref["role"],
                    "matched_input_ids": [],
                }
                for package_ref in rewritten["package_refs"]
            ]
        }
        self.assert_rejected(masquerade, observed_documents=documents)

    def test_zero_input_build_hashes_are_receipt_derived_and_semantic(self):
        policy = copy.deepcopy(self.policy)
        observations = copy.deepcopy(self.fixture.observed_inputs)
        opaque_ids = {
            record["id"]
            for record in policy["resolved_inputs"]
            if record["id"].startswith("opaque--")
        }
        policy["resolved_inputs"] = [
            record
            for record in policy["resolved_inputs"]
            if record["id"] not in opaque_ids
        ]
        observations = [
            record for record in observations if record["id"] not in opaque_ids
        ]
        resolution = resolution_record(policy, "resolve-opaque")
        resolution["input_refs"] = []
        resolution["disposition"] = "not-shipped"
        resolution["zero_input_proof"] = {
            "profile_roles": [
                {
                    "profile_id": profile_id,
                    "role": role,
                    "matched_input_ids": [],
                }
                for profile_id, role in PROFILE_ROLES
                if role == "application"
            ]
        }
        self.fixture.refresh_shipment_review(policy)
        self.assertNotIn(
            "project_description_sha256",
            json.dumps(resolution["zero_input_proof"], sort_keys=True),
        )

        first = self.assert_valid(
            policy,
            observed_inputs=observations,
        )
        first_resolution = resolution_record(
            {"resolutions": first["resolutions"]},
            "resolve-opaque",
        )
        for proof in first_resolution["zero_input_proof"]["profile_roles"]:
            self.assertRegex(
                proof["project_description_sha256"],
                r"^[0-9a-f]{64}$",
            )
            self.assertRegex(proof["compile_commands_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(proof["linker_map_sha256"], r"^[0-9a-f]{64}$")

        second_observations = copy.deepcopy(observations)
        changed_identity = PROFILE_ROLES[0]
        for record in second_observations:
            if (
                record["profile_id"],
                record["role"],
            ) != changed_identity or not record["kind"].startswith("generated-"):
                continue
            binding = record["generated_binding"]
            for field in (
                "project_description_sha256",
                "compile_commands_sha256",
                "linker_map_sha256",
            ):
                binding[field] = sha256_bytes(
                    ("second-root/%s/%s" % (field, changed_identity)).encode()
                )
        second = self.assert_valid(
            policy,
            observed_inputs=second_observations,
        )
        self.assertNotEqual(
            first["semantic_sha256"]["resolutions"],
            second["semantic_sha256"]["resolutions"],
        )

        predeclared = copy.deepcopy(policy)
        resolution_record(predeclared, "resolve-opaque")["zero_input_proof"][
            "profile_roles"
        ][0]["project_description_sha256"] = ("0" * 64)
        self.assert_rejected(predeclared, observed_inputs=observations)


@unittest.skipUnless(RELEASE is not None, "release_bundle.py is unavailable")
class StableGeneratedMatcherIntegrationTests(unittest.TestCase):
    @staticmethod
    def observe_context(fixture: ObservationV2Fixture, policy: dict) -> dict:
        return RELEASE._audit_observe_policy_v2_context(
            policy,
            repo_root=fixture.repo,
            build_root=fixture.build_root,
        )

    @staticmethod
    def validate_context(
        fixture: ObservationV2Fixture,
        policy: dict,
        context: dict,
    ) -> dict:
        return RELEASE._audit_validate_policy_v2(
            policy,
            repo_root=fixture.repo,
            observed_documents=fixture.observed_documents,
            observed_inputs=context["observed_inputs"],
            manifest_evidence=context["manifest_evidence"],
            toolchain_roots=context["toolchain_roots"],
            build_root=fixture.build_root,
        )

    def test_one_stable_policy_accepts_two_clean_absolute_build_roots(self):
        first = ObservationV2Fixture()
        second = ObservationV2Fixture()
        try:
            policy = stable_generated_policy(first.policy)
            self.assertEqual(policy, stable_generated_policy(second.policy))
            serialized = json.dumps(policy["resolved_inputs"], sort_keys=True)
            for forbidden in (
                "project_description_sha256",
                "compile_commands_sha256",
                "linker_map_sha256",
                "linker_command_sha256",
                "metadata_inputs",
                "direct_objects",
                '"sources"',
                '"members"',
            ):
                self.assertNotIn(forbidden, serialized)

            try:
                first_context = self.observe_context(first, policy)
                second_context = self.observe_context(second, policy)
                first_result = self.validate_context(first, policy, first_context)
                second_result = self.validate_context(second, policy, second_context)
            except RELEASE.ReleaseError as exc:
                self.fail(
                    "one stable policy rejected an equivalent clean build: %s" % exc
                )

            identifier = "app_core--esp32-4mb--application"
            first_binding = first_result["generated_bindings"][identifier]
            second_binding = second_result["generated_bindings"][identifier]
            self.assertNotEqual(
                first_binding["project_description_sha256"],
                second_binding["project_description_sha256"],
            )
            self.assertNotEqual(
                first_result["semantic_sha256"]["generated_bindings"],
                second_result["semantic_sha256"]["generated_bindings"],
            )

            predeclared = copy.deepcopy(policy)
            generated = next(
                record
                for record in predeclared["resolved_inputs"]
                if record["id"] == identifier
            )
            generated["generated_matcher"]["project_description_sha256"] = "0" * 64
            with self.assertRaises(RELEASE.ReleaseError):
                self.observe_context(first, predeclared)
        finally:
            first.close()
            second.close()

    @staticmethod
    def make_mbed_config_only(
        fixture: ObservationV2Fixture,
        policy: dict,
    ) -> dict:
        result = stable_generated_policy(policy)
        nested_targets = {"mbedcrypto", "mbedtls", "mbedx509"}
        for _profile_id, target, _idf_target in PROFILE_TARGETS:
            description_path = fixture.build_root / target / "project_description.json"
            description = json.loads(description_path.read_text(encoding="utf-8"))
            for component in nested_targets:
                description["build_component_info"].pop(component)
            description["build_component_info"]["mbedtls"] = {
                "alias": "idf::mbedtls",
                "target": "___idf_mbedtls",
                "prefix": "idf",
                "dir": str(fixture.mbed_root),
                "type": "CONFIG_ONLY",
                "lib": "__idf_mbedtls",
                "reqs": [],
                "priv_reqs": [],
                "managed_reqs": [],
                "managed_priv_reqs": [],
                "file": "",
                "sources": [],
                "include_dirs": [],
            }
            description["build_components"] = [
                component
                for component in description["build_components"]
                if component not in nested_targets
            ]
            description["build_components"].append("mbedtls")
            description_path.write_text(
                json.dumps(
                    description,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )

        for record in result["resolved_inputs"]:
            if record["kind"] != "generated-supplemental-archive":
                continue
            target = record["generated_matcher"]["component"]
            record["generated_matcher"] = {
                "component": "mbedtls",
                "nested_archive": {
                    "target": target,
                    "archive_build_path": (
                        "esp-idf/mbedtls/mbedtls/library/lib%s.a" % target
                    ),
                    "object_build_directory": (
                        "esp-idf/mbedtls/mbedtls/library/" "CMakeFiles/%s.dir" % target
                    ),
                },
            }
        return result

    def test_config_only_owner_requires_exact_nested_archive_topology(self):
        fixture = ObservationV2Fixture()
        try:
            policy = self.make_mbed_config_only(fixture, fixture.policy)
            try:
                context = self.observe_context(fixture, policy)
            except RELEASE.ReleaseError as exc:
                self.fail(
                    "valid CONFIG_ONLY nested archive topology was rejected: %s" % exc
                )
            nested = [
                record
                for record in context["observed_inputs"]
                if record["kind"] == "generated-supplemental-archive"
            ]
            self.assertEqual(len(nested), 3 * len(PROFILE_TARGETS))
            self.assertEqual(
                {
                    record["generated_binding"]["nested_archive"]["target"]
                    for record in nested
                },
                {"mbedcrypto", "mbedtls", "mbedx509"},
            )
            self.validate_context(fixture, policy, context)

            wrong_directory = copy.deepcopy(policy)
            record = next(
                record
                for record in wrong_directory["resolved_inputs"]
                if record["kind"] == "generated-supplemental-archive"
            )
            record["generated_matcher"]["nested_archive"][
                "object_build_directory"
            ] = "esp-idf/mbedtls/mbedtls/library/CMakeFiles/other.dir"
            with self.assertRaises(RELEASE.ReleaseError):
                self.observe_context(fixture, wrong_directory)

            path_only = copy.deepcopy(policy)
            record = next(
                record
                for record in path_only["resolved_inputs"]
                if record["kind"] == "generated-supplemental-archive"
            )
            record["generated_matcher"].pop("component")
            with self.assertRaises(RELEASE.ReleaseError):
                self.observe_context(fixture, path_only)

            raw_nested = copy.deepcopy(policy)
            record = next(
                record
                for record in raw_nested["resolved_inputs"]
                if record["kind"] == "generated-supplemental-archive"
            )
            record["kind"] = "generated-component-archive"
            with self.assertRaises(RELEASE.ReleaseError):
                self.observe_context(fixture, raw_nested)

            commands_path = fixture.build_root / "esp32" / "compile_commands.json"
            commands = json.loads(commands_path.read_text(encoding="utf-8"))
            nested_command = next(
                command
                for command in commands
                if "CMakeFiles/mbedcrypto.dir/" in command["output"]
            )
            original_source = nested_command["file"]
            ordinary = next(
                record
                for record in fixture.expected_inputs
                if record["id"] == "app_core--esp32-4mb--application"
            )
            outside_source = (
                fixture.repo / ordinary["generated_binding"]["sources"][0]["path"]
            )
            nested_command["file"] = str(outside_source)
            nested_command["command"] = nested_command["command"].replace(
                original_source,
                str(outside_source),
                1,
            )
            escaped_commands = (
                json.dumps(commands, sort_keys=True, separators=(",", ":")) + "\n"
            )
            with BASE.patched_text(commands_path, escaped_commands):
                with self.assertRaises(RELEASE.ReleaseError):
                    self.observe_context(fixture, policy)
        finally:
            fixture.close()

    def test_config_only_nested_archive_accepts_descendant_object_output(self):
        fixture = ObservationV2Fixture()
        try:
            policy = self.make_mbed_config_only(fixture, fixture.policy)
            role_build = fixture.build_root / "esp32"
            object_directory = (
                role_build
                / "esp-idf"
                / "mbedtls"
                / "mbedtls"
                / "library"
                / "CMakeFiles"
                / "mbedcrypto.dir"
            )
            original_output = object_directory / "aes.o"
            descendant_output = object_directory / "library" / original_output.name
            archive = object_directory.parent.parent / "libmbedcrypto.a"
            commands_path = role_build / "compile_commands.json"
            commands = json.loads(commands_path.read_text(encoding="utf-8"))
            command = next(
                item
                for item in commands
                if Path(item["output"]).resolve() == original_output.resolve()
            )

            self.assertEqual(
                set(BASE.parse_ar_members(archive.read_bytes())),
                {descendant_output.name},
            )
            descendant_output.parent.mkdir(parents=True, exist_ok=True)
            original_output.replace(descendant_output)
            command["output"] = str(descendant_output)
            command["command"] = command["command"].replace(
                str(original_output),
                str(descendant_output),
                1,
            )
            BASE.write_json(commands_path, commands)

            self.assertTrue(
                descendant_output.resolve().is_relative_to(
                    object_directory.resolve()
                )
            )
            self.assertNotEqual(
                descendant_output.parent.resolve(),
                object_directory.resolve(),
            )

            try:
                context = self.observe_context(fixture, policy)
            except RELEASE.ReleaseError as exc:
                self.assertEqual(
                    str(exc),
                    "generated input "
                    "mbedcrypto--esp32-4mb--application "
                    "nested object inventory is empty or escaped",
                )
                self.fail(
                    "valid descendant CONFIG_ONLY object output was rejected: %s"
                    % exc
                )

            observed = next(
                record
                for record in context["observed_inputs"]
                if record["id"]
                == "mbedcrypto--esp32-4mb--application"
            )
            self.assertEqual(
                observed["generated_binding"]["members"],
                [descendant_output.name],
            )
            self.validate_context(fixture, policy, context)
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()
