#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contracts for the remaining independent v0.6 release-audit gaps.

The fixtures contain only small synthetic source, license, archive, and SPDX
bytes.  Passing these engineering tests does not constitute legal review or
firmware qualification.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
from pathlib import Path
import shutil
import tempfile
import tomllib
import unittest
from unittest import mock

import test_release_v060_license_inventory as inventory_fixture
import test_release_v060_rp2_license_semantics as semantic_fixture


RELEASE = semantic_fixture.RELEASE
RELEASE_LOAD_ERROR = semantic_fixture.RELEASE_LOAD_ERROR


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def same_module_source_closure(function: object) -> str:
    """Return source for a helper and all same-module function callees."""

    pending = [function]
    seen: set[int] = set()
    result: list[str] = []
    while pending:
        current = pending.pop()
        if not callable(current) or id(current) in seen:
            continue
        seen.add(id(current))
        try:
            result.append(inspect.getsource(current))
        except (OSError, TypeError):
            pass
        code = getattr(current, "__code__", None)
        if code is None:
            continue
        for name in code.co_names:
            referenced = getattr(RELEASE, name, None)
            if (
                inspect.isfunction(referenced)
                and referenced.__module__ == current.__module__
            ):
                pending.append(referenced)
    return "\n".join(result)


class ControlInputFixture:
    """Install canonical synthetic RP2 policy and tool-lock control bytes."""

    def __init__(self) -> None:
        self.base = semantic_fixture.RP2SemanticFixture()
        self.policy_path = (
            self.base.repo / "firmware/licenses/rp2-license-policy.json"
        )
        self.lock_path = self.base.repo / "firmware/release-tools.lock"
        self.write_controls(generation=1)

    def close(self) -> None:
        self.base.close()

    def write_controls(self, *, generation: int) -> None:
        self.policy_path.parent.mkdir(parents=True, exist_ok=True)
        self.policy_path.write_bytes(canonical_json_bytes(self.base.policy))
        self.lock_path.write_text(
            "# SPDX-License-Identifier: MIT\n"
            "[inputs]\n"
            'rp2_license_policy_path = '
            '"firmware/licenses/rp2-license-policy.json"\n'
            'rp2_license_policy_sha256 = "%s"\n'
            "fixture_generation = %d\n"
            % (sha256_bytes(self.policy_path.read_bytes()), generation),
            encoding="utf-8",
        )

    def tool_lock(self) -> dict[str, object]:
        return {
            "inputs": {
                "rp2_license_policy_path": (
                    "firmware/licenses/rp2-license-policy.json"
                ),
                "rp2_license_policy_sha256": sha256_bytes(
                    self.policy_path.read_bytes()
                ),
            }
        }

    def mutate_unselected_license_and_rebind_controls(self) -> None:
        owner = next(
            item
            for item in self.base.policy["source_owners"]
            if item["id"] == "fixture-mbedtls-upstream"
        )
        record = next(
            item
            for item in owner["license_texts"]
            if item["identifier"] == "GPL-2.0-or-later"
        )
        prefix, relative = record["path"].split("/", 1)
        if prefix != "repo":
            raise AssertionError("synthetic unselected license is not repo-owned")
        path = self.base.repo / relative
        path.write_bytes(path.read_bytes() + b"Synthetic reviewed appendix.\n")
        record["sha256"] = sha256_bytes(path.read_bytes())
        self.write_controls(generation=2)


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class RP2ControlInputBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ControlInputFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_full_policy_and_tool_lock_bytes_are_semantic_inputs(self) -> None:
        observed = self.fixture.base.observe()
        received = set(observed["input_sha256"].values())
        self.assertIn(
            sha256_bytes(self.fixture.policy_path.read_bytes()),
            received,
            "the full canonical RP2 policy bytes are absent from the semantic input receipt",
        )
        self.assertIn(
            sha256_bytes(self.fixture.lock_path.read_bytes()),
            received,
            "the full release-tools.lock bytes are absent from the semantic input receipt",
        )

    def test_rebound_unselected_text_and_control_files_do_not_replay_old_receipt(
        self,
    ) -> None:
        baseline = self.fixture.base.observe()
        receipt_inputs = {
            "semantic/rp2-license-closure": baseline["semantic_sha256"],
            **{
                "rp2-input/%s" % name: digest
                for name, digest in baseline["input_sha256"].items()
            },
        }
        self.fixture.mutate_unselected_license_and_rebind_controls()

        with (
            mock.patch.object(
                RELEASE,
                "_audit_load_tool_lock",
                side_effect=lambda _root: self.fixture.tool_lock(),
            ),
            mock.patch.object(
                RELEASE,
                "_audit_load_rp2_license_policy",
                side_effect=lambda *_args: copy.deepcopy(
                    self.fixture.base.policy
                ),
            ),
        ):
            with self.assertRaisesRegex(
                RELEASE.ReleaseError,
                "policy|lock|semantic|receipt|input|changed",
            ):
                RELEASE._audit_verify_rp2_semantic_replay(
                    receipt_inputs=receipt_inputs,
                    persisted_documents=baseline["role_documents"],
                    build_root=self.fixture.base.build,
                    repo_root=self.fixture.base.repo,
                    provenance=self.fixture.base.provenance,
                )


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class OwnerScopedLicenseRefTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = semantic_fixture.RP2SemanticFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def validate(self, policy: dict[str, object]) -> dict[str, object]:
        return RELEASE._audit_validate_rp2_license_policy(
            policy,
            repo_root=self.fixture.repo,
            build_root=self.fixture.build,
        )

    def test_same_custom_identifier_cannot_mean_different_owner_texts(self) -> None:
        policy = copy.deepcopy(self.fixture.policy)
        owners = {
            owner["id"]: owner for owner in policy["source_owners"]
        }
        shared = "LicenseRef-PyBLE-Synthetic-Owner-Scoped"
        for owner_id in (
            "fixture-micropython-mit",
            "fixture-micropython-rp2-mit",
        ):
            owner = owners[owner_id]
            owner["source_spdx_expression"] = shared
            owner["selected_spdx_expression"] = shared
            owner["license_texts"][0]["identifier"] = shared

        first = owners["fixture-micropython-mit"]["license_texts"][0]
        second = owners["fixture-micropython-rp2-mit"]["license_texts"][0]
        first["sha256"] = sha256_bytes(
            (self.fixture.repo / first["path"].removeprefix("repo/")).read_bytes()
        )
        second["sha256"] = sha256_bytes(
            (self.fixture.repo / second["path"].removeprefix("repo/")).read_bytes()
        )
        self.assertNotEqual(first["sha256"], second["sha256"])
        with self.assertRaisesRegex(
            RELEASE.ReleaseError,
            "LicenseRef|ambiguous|different|digest|owner",
        ):
            self.validate(policy)

    def test_invented_custom_identifier_without_its_owner_text_is_rejected(
        self,
    ) -> None:
        policy = copy.deepcopy(self.fixture.policy)
        owner = next(
            item
            for item in policy["source_owners"]
            if item["id"] == "fixture-micropython-mit"
        )
        owner["source_spdx_expression"] = "LicenseRef-PyBLE-Invented"
        owner["selected_spdx_expression"] = "LicenseRef-PyBLE-Invented"
        with self.assertRaisesRegex(
            RELEASE.ReleaseError,
            "LicenseRef|license|cover|text",
        ):
            self.validate(policy)

    def test_review_required_remains_observable_but_release_blocking(self) -> None:
        baseline = self.fixture.observe()
        policy = copy.deepcopy(self.fixture.policy)
        owner = next(
            item
            for item in policy["source_owners"]
            if item["id"] == "fixture-libm-fdlibm"
        )
        owner["disposition"] = "review-required"
        observed = self.fixture.observe(policy)
        selected = next(
            item for item in observed["owners"] if item["id"] == owner["id"]
        )
        self.assertEqual(selected["disposition"], "review-required")
        self.assertNotEqual(observed["semantic_sha256"], baseline["semantic_sha256"])
        self.assertIn(
            "review-required",
            inspect.getsource(RELEASE.audit_release_licenses),
            "review-required observation is not release-blocking",
        )


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class PublicEspSemanticReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = inventory_fixture.V060LicenseFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_self_consistent_structural_esp_substitution_fails_public_replay(
        self,
    ) -> None:
        """The inventory fixture is structural evidence, never an ESP audit."""

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
            with self.assertRaisesRegex(
                RELEASE.ReleaseError,
                "ESP|SBOM|semantic|policy|tool|evidence|receipt",
            ):
                RELEASE._audit_verify_release_evidence(
                    notice=self.fixture.notice,
                    evidence_dir=self.fixture.evidence,
                    build_root=self.fixture.build,
                    repo_root=self.fixture.repo,
                )


def prepare_exact_board_copy(
    fixture: semantic_fixture.RP2SemanticFixture,
) -> Path:
    """Materialize the exact synthetic output of prepare.sh + build_rp2.sh."""

    overlay = fixture.repo / "firmware/board_overlays/rpi-pico2-w"
    overlay_files = {
        "_boot.py": b"# synthetic RP2 boot\n",
        "mpconfigboard.cmake": b"# synthetic board CMake input\n",
        "mpconfigboard.h": b"/* synthetic board config */\n",
        "mpconfigvariant.cmake": b"# synthetic variant config\n",
    }
    for relative, value in overlay_files.items():
        fixture.write(overlay, relative, value)
    (overlay / "manifest.py").write_text(
        'module("rp2.py", base_path="$(PORT_DIR)/modules", opt=3)\n'
        'include("$(MPY_DIR)/extmod/asyncio")\n'
        'module("_boot.py", base_path="$(BOARD_DIR)", opt=3)\n'
        'freeze("$(BOARD_DIR)/pyble", '
        '("_version.py", "pyble_agent.py"), opt=3)\n',
        encoding="utf-8",
    )
    canonical_pyble = fixture.repo / "firmware/pyble"
    fixture.write(canonical_pyble, "_version.py", b"# source-tree fallback\n")

    board = (
        fixture.source / "ports/rp2/boards/PYBLE_RPI_PICO2_W"
    )
    for source in sorted(overlay.iterdir()):
        if source.is_file():
            fixture.write(board, source.name, source.read_bytes())
    fixture.write(
        board,
        "pyble/pyble_agent.py",
        (canonical_pyble / "pyble_agent.py").read_bytes(),
    )
    fixture.write(
        board,
        "pyble/_version.py",
        (
            "# SPDX-License-Identifier: MIT\n"
            "# GENERATED by firmware/scripts/build_rp2.sh from "
            "firmware/versions.lock [pyble] — do not edit.\n"
            'AGENT_VERSION = "0.6.0"\n'
            'PROTOCOL_VERSION = "PBLE/1"\n'
        ).encode("utf-8"),
    )
    fixture.write(
        board,
        "pble_version.h",
        b"// SPDX-License-Identifier: MIT\n"
        b"// synthetic lock-derived board version header\n",
    )
    return board


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class RetainedBoardCopyClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = semantic_fixture.RP2SemanticFixture()
        self.board = prepare_exact_board_copy(self.fixture)
        self.fixture.observe()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_generated_version_and_config_copies_are_byte_exact(self) -> None:
        mutations = (
            self.board / "pyble/_version.py",
            self.board / "mpconfigboard.cmake",
            self.board / "mpconfigboard.h",
            self.board / "mpconfigvariant.cmake",
        )
        for path in mutations:
            with self.subTest(path=path.relative_to(self.board).as_posix()):
                original = path.read_bytes()
                path.write_bytes(original + b"# substituted board input\n")
                try:
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        "board|copy|version|config|inventory|generated|changed",
                    ):
                        self.fixture.observe()
                finally:
                    path.write_bytes(original)

    def test_arbitrary_generated_board_file_is_not_admitted(self) -> None:
        extra = self.board / "generated.c"
        extra.write_text("/* arbitrary generated source */\n", encoding="utf-8")
        try:
            with self.assertRaisesRegex(
                RELEASE.ReleaseError,
                "board|inventory|untracked|unowned|generated",
            ):
                self.fixture.observe()
        finally:
            extra.unlink(missing_ok=True)


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class ArmDistributionSourceContractTests(unittest.TestCase):
    def test_installed_runtime_is_proven_against_the_locked_official_archive(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[3]
        with (root / "firmware/versions.lock").open("rb") as handle:
            arm = tomllib.load(handle)["arm_gnu_toolchain"]
        self.assertTrue(
            {
                "archive_filename",
                "archive_bytes",
                "archive_format",
                "archive_root",
                "release_manifest_path",
                "release_manifest_sha256",
                "c_asm_frontend_path",
                "c_asm_frontend_sha256",
                "cxx_frontend_path",
                "cxx_frontend_sha256",
            }
            <= set(arm),
            "versions.lock does not yet describe the exact official ARM binary distribution",
        )

        installer = (root / "firmware/scripts/install_arm_toolchain.sh").read_text(
            encoding="utf-8", errors="strict"
        )
        observer_closure = same_module_source_closure(
            RELEASE._audit_observe_rp2_license_inputs
        )
        for required in (".pyble-dist", "archive_filename", "archive_bytes"):
            with self.subTest(installer=required):
                self.assertIn(required, installer)
        for required in (
            "toolchain_distribution",
            "release_manifest",
            "installed_inputs",
            "archive_filename",
        ):
            with self.subTest(observer=required):
                self.assertIn(required, observer_closure)


class FakeLockedRunner:
    def __init__(self, **_kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class EvidenceNoticeAtomicPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="pyble-v060-audit-publication-red-"
        )
        self.root = Path(self.temporary.name)
        self.build = self.root / "build"
        self.repo = self.root / "repo"
        self.wheelhouse = self.root / "wheelhouse"
        self.build.mkdir()
        self.repo.mkdir()
        self.wheelhouse.mkdir()
        self.outputs = self.root / "outputs"
        self.outputs.mkdir()
        self.publication = self.outputs / "license-audit"
        self.evidence = self.publication / "evidence"
        self.notice = self.publication / "THIRD_PARTY_LICENSES.txt"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def successful_audit(*, evidence_dir: Path, **_kwargs) -> dict[str, str]:
        Path(evidence_dir).mkdir()
        (Path(evidence_dir) / "audit-receipt.json").write_text(
            "{}\n", encoding="utf-8"
        )
        return {"third_party_licenses": "Synthetic reviewed notice.\n"}

    def publish(self) -> dict[str, object]:
        with (
            mock.patch.object(RELEASE, "LockedWheelSbomRunner", FakeLockedRunner),
            mock.patch.object(
                RELEASE,
                "audit_release_licenses",
                side_effect=self.successful_audit,
            ),
        ):
            return RELEASE.audit_release_licenses_from_lock(
                build_root=self.build,
                repo_root=self.repo,
                evidence_dir=self.evidence,
                wheelhouse=self.wheelhouse,
                notice_output=self.notice,
            )

    def test_existing_notice_is_never_replaced(self) -> None:
        contender = b"another publisher owns these notice bytes\n"
        self.publication.mkdir()
        self.notice.write_bytes(contender)
        with self.assertRaisesRegex(
            RELEASE.ReleaseError,
            "notice|destination|exist|replace|publication",
        ):
            self.publish()
        self.assertEqual(self.notice.read_bytes(), contender)
        self.assertFalse(self.evidence.exists())

    def test_interruption_before_the_single_commit_publishes_neither(self) -> None:
        with mock.patch.object(
            RELEASE,
            "_atomic_publish_no_replace",
            side_effect=SystemExit("synthetic publication interruption"),
        ):
            with self.assertRaises(SystemExit):
                self.publish()
        self.assertFalse(self.publication.exists())

    def test_interruption_after_the_single_commit_leaves_the_complete_pair(
        self,
    ) -> None:
        original_publish = RELEASE._atomic_publish_no_replace

        def publish_then_interrupt(source: Path, destination: Path, label: str):
            original_publish(source, destination, label)
            raise SystemExit("synthetic post-commit interruption")

        with mock.patch.object(
            RELEASE,
            "_atomic_publish_no_replace",
            side_effect=publish_then_interrupt,
        ):
            with self.assertRaises(SystemExit):
                self.publish()
        self.assertTrue((self.evidence / "audit-receipt.json").is_file())
        self.assertEqual(
            self.notice.read_text(encoding="utf-8"),
            "Synthetic reviewed notice.\n",
        )

    def test_notice_race_is_no_replace_and_rolls_back_evidence(self) -> None:
        original_publish = RELEASE._atomic_publish_no_replace
        contender = b"concurrent notice owner\n"

        def install_notice_contender(source: Path, destination: Path, label: str):
            self.publication.mkdir()
            self.notice.write_bytes(contender)
            original_publish(source, destination, label)

        with mock.patch.object(
            RELEASE,
            "_atomic_publish_no_replace",
            side_effect=install_notice_contender,
        ):
            with self.assertRaisesRegex(
                RELEASE.ReleaseError,
                "notice|destination|exist|replace|publication|race",
            ):
                self.publish()
        self.assertEqual(self.notice.read_bytes(), contender)
        self.assertFalse(self.evidence.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
