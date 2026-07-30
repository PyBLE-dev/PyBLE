#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] BLD-8 — Bind every compiler frontend and runtime to one trusted cache.
#
# Frozen sources:
#   docs/specifications/firmware/browser-flashing.md §6 rule 5
#   docs/specifications/firmware/TDD.md §10.7 and §14.3

from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


POLICY_TEST = Path(__file__).with_name("test_release_license_policy_v2.py")


def load_policy_module():
    spec = importlib.util.spec_from_file_location(
        "pyble_release_license_toolchain_cache_v2_fixtures",
        POLICY_TEST,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load schema-v2 policy fixtures")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


V2 = load_policy_module()
RELEASE = V2.RELEASE
DERIVE_CACHE_CONTEXT = (
    getattr(RELEASE, "_audit_v2_derive_toolchain_cache_context", None)
    if RELEASE is not None
    else None
)
VALIDATE_V2 = (
    getattr(RELEASE, "_audit_validate_policy_v2", None)
    if RELEASE is not None
    else None
)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deep_strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from deep_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from deep_strings(child)
    elif isinstance(value, str):
        yield value


class TrustedCacheFixture:
    """Real-shaped ESP-IDF tools home without vendored distribution bytes."""

    def __init__(self):
        self.base = V2.PolicyV2Fixture()
        self.root = self.base.root
        self.repo = self.base.repo
        self.policy = copy.deepcopy(self.base.policy)
        original = self.base.toolchain

        self.name = "fixture-xtensa-esp-elf"
        self.version = "esp-14.2.0_20241119"
        self.platform = "macos-arm64"
        self.archive_root = original["root_name"]
        self.filename = original["distribution"].name
        self.tools_home = (self.root / "idf-tools-home").resolve()
        self.install_root_relative = (
            Path("tools")
            / self.name
            / self.version
            / self.archive_root
        ).as_posix()
        self.installed_root = (
            self.tools_home / self.install_root_relative
        )
        self.installed_root.parent.mkdir(parents=True)
        shutil.move(original["installed_root"], self.installed_root)
        self.frontend_relatives = list(original["compiler_relatives"])
        self.gcc_relative = next(
            relative
            for relative in self.frontend_relatives
            if relative.endswith("-gcc")
        )
        self.gxx_relative = next(
            relative
            for relative in self.frontend_relatives
            if relative.endswith("-g++")
        )
        self.frontends = {
            relative: self.installed_root / relative
            for relative in self.frontend_relatives
        }

        self.cache = self.tools_home / "dist" / self.filename
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(original["distribution"], self.cache)
        self.url = "https://example.invalid/toolchains/%s" % self.filename

        for observation in self.base.observed_inputs:
            if observation["kind"] != "toolchain-archive":
                continue
            observation["observed_path"] = str(
                (self.installed_root / observation["relative_path"]).resolve()
            )
            observation.pop("compiler_path", None)
            observation["compiler_paths"] = [
                str(self.frontends[relative].resolve())
                for relative in self.frontend_relatives
            ]
        self.observed_inputs = copy.deepcopy(self.base.observed_inputs)

        self.metadata_path = (
            self.repo / "firmware" / ".esp-idf" / "tools" / "tools.json"
        )
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_metadata()
        self._rewrite_toolchain_policy()

    def close(self):
        self.base.close()

    def _metadata(self):
        return {
            "version": 1,
            "tools": [
                {
                    "name": self.name,
                    "description": "Synthetic schema-v2 GCC fixture",
                    "export_paths": [[self.archive_root, "bin"]],
                    "export_vars": {},
                    "install": "always",
                    "license": "GPL-3.0-with-GCC-exception",
                    "supported_targets": ["esp32", "esp32s3"],
                    "version_cmd": ["fixture-gcc", "--version"],
                    "version_regex": "(fixture-[0-9._-]+)",
                    "versions": [
                        {
                            "name": self.version,
                            "status": "recommended",
                            self.platform: {
                                "url": self.url,
                                "size": self.cache.stat().st_size,
                                "sha256": sha256_path(self.cache),
                            },
                        }
                    ],
                }
            ],
        }

    def _write_metadata(self):
        V2.BASE.write_json(self.metadata_path, self._metadata())

    def _rewrite_toolchain_policy(self):
        toolchain = self.policy["toolchains"][0]
        toolchain["name"] = self.name
        toolchain["version"] = self.version
        toolchain["platform"] = self.platform
        toolchain["install_root_relative"] = self.install_root_relative
        toolchain.pop("compiler", None)
        toolchain["compiler_frontends"] = [
            {
                "relative_path": relative,
                "sha256": sha256_path(self.frontends[relative]),
            }
            for relative in self.frontend_relatives
        ]
        distribution = toolchain["distribution"]
        distribution["filename"] = self.filename
        distribution["archive_root"] = self.archive_root
        distribution["url"] = self.url
        distribution["size"] = self.cache.stat().st_size
        distribution["sha256"] = sha256_path(self.cache)
        toolchain["metadata"] = {
            "path": self.metadata_path.relative_to(self.repo).as_posix(),
            "sha256": sha256_path(self.metadata_path),
        }

    @contextmanager
    def changed_policy(self, mutation):
        before = copy.deepcopy(self.policy)
        try:
            mutation(self.policy)
            yield
        finally:
            self.policy = before

    @contextmanager
    def changed_metadata(self, mutation):
        before = self.metadata_path.read_bytes()
        try:
            value = json.loads(before)
            mutation(value)
            V2.BASE.write_json(self.metadata_path, value)
            self.policy["toolchains"][0]["metadata"]["sha256"] = sha256_path(
                self.metadata_path
            )
            yield
        finally:
            self.metadata_path.write_bytes(before)
            self.policy["toolchains"][0]["metadata"]["sha256"] = sha256_path(
                self.metadata_path
            )

    @contextmanager
    def cache_symlink_to_equal_bytes(self):
        outside = Path(
            tempfile.mkdtemp(prefix="pyble-untrusted-toolchain-cache-")
        ) / self.filename
        outside.write_bytes(self.cache.read_bytes())
        self.cache.unlink()
        self.cache.symlink_to(outside)
        try:
            yield
        finally:
            self.cache.unlink()
            self.cache.write_bytes(outside.read_bytes())
            shutil.rmtree(outside.parent)

    @contextmanager
    def frontend_symlink_to_equal_bytes(self, relative):
        frontend = self.frontends[relative]
        outside = Path(
            tempfile.mkdtemp(prefix="pyble-untrusted-toolchain-frontend-")
        ) / frontend.name
        outside.write_bytes(frontend.read_bytes())
        outside.chmod(0o755)
        frontend.unlink()
        frontend.symlink_to(outside)
        try:
            yield
        finally:
            frontend.unlink()
            frontend.write_bytes(outside.read_bytes())
            frontend.chmod(0o755)
            shutil.rmtree(outside.parent)


@unittest.skipUnless(RELEASE is not None, "release_bundle.py is unavailable")
class TrustedToolchainCachePolicyV2Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = TrustedCacheFixture()

    def tearDown(self):
        self.fixture.close()

    def derive(self, policy=None, compiler_paths=None):
        self.assertTrue(
            callable(DERIVE_CACHE_CONTEXT),
            "release_bundle.py lacks "
            "_audit_v2_derive_toolchain_cache_context",
        )
        return DERIVE_CACHE_CONTEXT(
            self.fixture.policy if policy is None else policy,
            repo_root=self.fixture.repo,
            compiler_paths=(
                set(self.fixture.frontends.values())
                if compiler_paths is None
                else compiler_paths
            ),
        )

    def assert_derive_rejected(self, policy=None, compiler_paths=None):
        with self.assertRaises(RELEASE.ReleaseError):
            self.derive(policy, compiler_paths)

    def assert_frontend_baseline(self):
        """Require the valid two-frontend contract before testing a negative."""

        contexts = self.derive()
        toolchain_id = self.fixture.policy["toolchains"][0]["id"]
        self.assertEqual(set(contexts), {toolchain_id})
        return contexts

    def test_policy_uses_logical_cache_identity_not_vendored_path(self):
        toolchain = self.fixture.policy["toolchains"][0]
        distribution = toolchain["distribution"]
        self.assertNotIn("compiler", toolchain)
        frontends = toolchain["compiler_frontends"]
        self.assertEqual(
            [record["relative_path"] for record in frontends],
            self.fixture.frontend_relatives,
        )
        self.assertEqual(
            [record["relative_path"] for record in frontends],
            sorted(record["relative_path"] for record in frontends),
        )
        self.assertEqual(
            [set(record) for record in frontends],
            [{"relative_path", "sha256"}, {"relative_path", "sha256"}],
        )
        self.assertEqual(len(frontends), 2)
        self.assertEqual(
            set(distribution),
            {
                "url",
                "filename",
                "size",
                "sha256",
                "archive_format",
                "archive_root",
            },
        )
        self.assertNotIn("path", distribution)
        self.assertNotEqual(
            self.fixture.policy["toolchains"][0]["install_root_relative"],
            distribution["archive_root"],
        )
        self.assertFalse(self.fixture.cache.is_relative_to(self.fixture.repo))

        contexts = self.assert_frontend_baseline()
        context = contexts[self.fixture.policy["toolchains"][0]["id"]]
        self.assertEqual(Path(context["root"]), self.fixture.installed_root)
        self.assertEqual(
            Path(context["distribution_cache_path"]),
            self.fixture.cache,
        )
        self.assertEqual(
            context["distribution_cache_relative"],
            "dist/%s" % self.fixture.filename,
        )
        self.assertEqual(
            Path(context["trusted_anchor"]),
            self.fixture.tools_home,
        )

    def test_missing_and_extra_compile_frontends_fail_closed(self):
        self.assert_frontend_baseline()

        self.assert_derive_rejected(
            compiler_paths={self.fixture.frontends[self.fixture.gcc_relative]}
        )

        extra = self.fixture.installed_root / "bin" / "fixture-extra-compiler"
        extra.write_bytes(b"#!/bin/sh\n# undeclared compiler frontend\n")
        extra.chmod(0o755)
        try:
            self.assert_derive_rejected(
                compiler_paths={
                    *self.fixture.frontends.values(),
                    extra,
                }
            )
        finally:
            extra.unlink()

    def test_consistent_gcc_only_catalog_still_requires_the_gxx_frontend(self):
        self.assert_frontend_baseline()

        def remove_gxx(policy):
            policy["toolchains"][0]["compiler_frontends"] = [
                record
                for record in policy["toolchains"][0]["compiler_frontends"]
                if record["relative_path"] == self.fixture.gcc_relative
            ]

        with self.fixture.changed_policy(remove_gxx):
            self.assert_derive_rejected(
                compiler_paths={
                    self.fixture.frontends[self.fixture.gcc_relative],
                }
            )

    def test_duplicate_or_noncanonical_frontend_catalog_fails_closed(self):
        self.assert_frontend_baseline()

        with self.fixture.changed_policy(
            lambda value: value["toolchains"][0].update(
                {"compiler_frontends": []}
            )
        ):
            self.assert_derive_rejected()

        with self.fixture.changed_policy(
            lambda value: value["toolchains"][0]["compiler_frontends"].append(
                copy.deepcopy(
                    value["toolchains"][0]["compiler_frontends"][0]
                )
            )
        ):
            self.assert_derive_rejected()

        with self.fixture.changed_policy(
            lambda value: value["toolchains"][0]["compiler_frontends"].reverse()
        ):
            self.assert_derive_rejected()

    def test_frontend_symlink_and_reviewed_hash_drift_fail_closed(self):
        self.assert_frontend_baseline()

        with self.fixture.frontend_symlink_to_equal_bytes(
            self.fixture.gxx_relative
        ):
            self.assert_derive_rejected()

        with self.fixture.changed_policy(
            lambda value: value["toolchains"][0]["compiler_frontends"][0].update(
                {"sha256": "0" * 64}
            )
        ):
            self.assert_derive_rejected()

    def test_frontend_must_be_byte_equal_to_cached_distribution(self):
        self.assert_frontend_baseline()
        relative = self.fixture.gxx_relative
        frontend = self.fixture.frontends[relative]
        before = frontend.read_bytes()
        changed = before + b"# locally replaced frontend\n"
        try:
            frontend.write_bytes(changed)
            frontend.chmod(0o755)
            with self.fixture.changed_policy(
                lambda value: next(
                    record
                    for record in value["toolchains"][0]["compiler_frontends"]
                    if record["relative_path"] == relative
                ).update({"sha256": hashlib.sha256(changed).hexdigest()})
            ):
                self.assert_derive_rejected()
        finally:
            frontend.write_bytes(before)
            frontend.chmod(0o755)

    def test_frontends_cannot_derive_different_trusted_roots(self):
        self.assert_frontend_baseline()
        alternate_home = self.fixture.root / "alternate-idf-tools-home"
        alternate_frontend = (
            alternate_home
            / self.fixture.install_root_relative
            / self.fixture.gxx_relative
        )
        alternate_frontend.parent.mkdir(parents=True)
        shutil.copyfile(
            self.fixture.frontends[self.fixture.gxx_relative],
            alternate_frontend,
        )
        alternate_frontend.chmod(0o755)
        try:
            self.assert_derive_rejected(
                compiler_paths={
                    self.fixture.frontends[self.fixture.gcc_relative],
                    alternate_frontend,
                }
            )
        finally:
            shutil.rmtree(alternate_home)

    def test_filename_and_archive_root_must_match_metadata_and_url(self):
        with self.fixture.changed_policy(
            lambda value: value["toolchains"][0]["distribution"].update(
                {"filename": "caller-selected.tar.xz"}
            )
        ):
            self.assert_derive_rejected()

        with self.fixture.changed_policy(
            lambda value: value["toolchains"][0]["distribution"].update(
                {"archive_root": "caller-selected-root"}
            )
        ):
            self.assert_derive_rejected()

        def change_metadata_url(value):
            value["tools"][0]["versions"][0][self.fixture.platform]["url"] = (
                "https://example.invalid/toolchains/unreviewed.tar.xz"
            )

        with self.fixture.changed_metadata(change_metadata_url):
            self.assert_derive_rejected()

    def test_cache_bytes_and_symlink_escape_fail_closed(self):
        before = self.fixture.cache.read_bytes()
        try:
            self.fixture.cache.write_bytes(before + b"tampered")
            self.assert_derive_rejected()
        finally:
            self.fixture.cache.write_bytes(before)

        with self.fixture.cache_symlink_to_equal_bytes():
            self.assert_derive_rejected()

    def test_caller_cannot_add_a_cache_path_to_policy(self):
        with self.fixture.changed_policy(
            lambda value: value["toolchains"][0]["distribution"].update(
                {"path": str(self.fixture.cache)}
            )
        ):
            self.assert_derive_rejected()

    def test_validated_result_never_contains_host_absolute_paths(self):
        contexts = self.assert_frontend_baseline()
        expected_paths = [
            str(self.fixture.frontends[relative].resolve())
            for relative in self.fixture.frontend_relatives
        ]
        toolchain_observations = [
            item
            for item in self.fixture.observed_inputs
            if item["kind"] == "toolchain-archive"
        ]
        self.assertTrue(toolchain_observations)
        self.assertTrue(
            all(
                item["compiler_paths"] == expected_paths
                for item in toolchain_observations
            )
        )
        result = VALIDATE_V2(
            self.fixture.policy,
            repo_root=self.fixture.repo,
            observed_documents=self.fixture.base.observed_documents,
            observed_inputs=self.fixture.observed_inputs,
            manifest_evidence=self.fixture.base.manifest_evidence,
            toolchain_roots=contexts,
        )
        strings = tuple(deep_strings(result))
        forbidden = (
            str(self.fixture.tools_home),
            str(self.fixture.cache),
            str(self.fixture.installed_root),
            *(str(path) for path in self.fixture.frontends.values()),
        )
        for absolute in forbidden:
            self.assertFalse(
                any(absolute in value for value in strings),
                "validated evidence leaked host path %s" % absolute,
            )


if __name__ == "__main__":
    unittest.main()
