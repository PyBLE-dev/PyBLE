#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] BLD-8 — Complete, offline firmware release-license audit.
#
# Frozen sources:
#   docs/specifications/firmware/browser-flashing.md §6
#   docs/specifications/firmware/TDD.md §10.7
#   docs/specifications/firmware/specs.md BLD-8
#
# This suite deliberately pins only one new production seam:
#
#   firmware/scripts/release_bundle.py
#     audit_release_licenses(
#         *,
#         build_root: Path,
#         repo_root: Path,
#         evidence_dir: Path,
#         runner: Callable,
#     ) -> str | Mapping[str, object]
#
# A mapping result may call the notice "notice", "notices", or
# "third_party_licenses"; the tests care about the frozen semantics, not an
# invented result layout.  Normalized review evidence is discovered below
# evidence_dir rather than at a prescribed filename.
#
# The injected runner is the narrow process boundary used by these host tests.
# It is callable as `runner(argv, *, cwd, env, check, network_disabled)` and
# returns a subprocess-like object with `executed_artifacts` and
# `network_isolated` receipts.  The production adapter must obtain those
# receipts from the verified offline tool environment.  It is not enough to
# trust the executable's name or an unchecked boolean.
#
# Public validation remains `validate_bundle(..., public=True)`, extended with
# `license_evidence_dir`, `license_build_root`, and `repo_root` so promotion can
# bind the exact marker-free notice to fresh retained review evidence.  The
# public tree does not contain the intermediate evidence.
#
# All named dependencies and license texts created by this file are synthetic
# test fixtures.  In particular, fixture blob and newlib expressions make no
# claim about the license of any shipped Espressif or toolchain binary.

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import copy
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock
import uuid
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "release_bundle.py"
RELEASE_TOOLS_LOCK = REPO_ROOT / "firmware" / "release-tools.lock"
LICENSE_POLICY = REPO_ROOT / "firmware" / "licenses" / "license-policy.json"
EXCLUDED_CVES = REPO_ROOT / "firmware" / "licenses" / "excluded-cves.yaml"
RELEASE_BUNDLE_TEST = Path(__file__).with_name("test_release_bundle.py")

PROFILE_TARGETS = (
    ("esp32-4mb", "esp32", "esp32"),
    ("esp32-s3-n16r8", "esp32-s3", "esp32s3"),
    ("esp32-c3-4mb", "esp32-c3", "esp32c3"),
)
PROFILE_ROLES = tuple(
    (profile_id, role)
    for profile_id, _target, _idf_target in PROFILE_TARGETS
    for role in ("application", "bootloader")
)
PROFILE_ROLE_LABELS = tuple("%s/%s" % item for item in PROFILE_ROLES)

SBOM_NAME = "esp-idf-sbom"
SBOM_VERSION = "1.2.0"
SBOM_WHEEL = "esp_idf_sbom-1.2.0-py3-none-any.whl"
SBOM_WHEEL_SHA256 = "a1444a7f23740c44cacbce4845efb5cbcb08927878b6a3852c33a52d8b2b5da9"
SBOM_TAG = "v1.2.0"
SBOM_COMMIT = "d46a159ac239b9f843c59e0b4bfcfaff1859b862"
CANDIDATE_MARKER = "PUBLIC-NOTICE-STATUS: CANDIDATE-ONLY"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-" r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
SPDX_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

KNOWN_FIXTURE_SPDX = {
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "GCC-exception-3.1",
    "GPL-3.0-or-later",
    "MIT",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            raise AssertionError("fixture source tree contains symlink: %s" % item)
        if not item.is_file():
            continue
        relative = item.relative_to(path).as_posix().encode("utf-8")
        value = item.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def canonical_package_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def requirement_name(value: str) -> str:
    match = re.match(r"^\s*([A-Za-z0-9_.-]+)", value)
    if match is None:
        raise AssertionError("invalid locked requirement: %r" % value)
    return canonical_package_name(match.group(1))


def artifact_requirements(artifact: dict) -> list[str]:
    for key in ("requires", "dependencies", "requires_dist"):
        value = artifact.get(key)
        if value is not None:
            if not isinstance(value, list):
                raise AssertionError("%s must be an array" % key)
            return value
    return []


def deep_scalars(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from deep_scalars(child)
    elif isinstance(value, list):
        for child in value:
            yield from deep_scalars(child)
    elif isinstance(value, (str, int, float, bool)) or value is None:
        yield value


def deep_values_for_key(value: object, key: str):
    if isinstance(value, dict):
        for actual, child in value.items():
            if actual == key:
                yield child
            yield from deep_values_for_key(child, key)
    elif isinstance(value, list):
        for child in value:
            yield from deep_values_for_key(child, key)


def deep_strings_for_key_fragment(value: object, fragment: str):
    if isinstance(value, dict):
        for key, child in value.items():
            if fragment.lower() in key.lower() and isinstance(child, str):
                yield child
            yield from deep_strings_for_key_fragment(child, fragment)
    elif isinstance(value, list):
        for child in value:
            yield from deep_strings_for_key_fragment(child, fragment)


def safe_fixture_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise AssertionError("policy path is empty")
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or ".." in pure.parts
        or "." in pure.parts
        or "\\" in relative
        or pure.as_posix() != relative
    ):
        raise AssertionError("unsafe policy path: %s" % relative)
    resolved_root = root.resolve()
    candidate = root / pure
    if candidate.is_symlink():
        raise AssertionError("policy path is a symlink: %s" % relative)
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise AssertionError("policy path escapes fixture root: %s" % relative)
    return candidate


def load_release_module():
    if not RELEASE_SCRIPT.is_file():
        return None, "missing production script: %s" % RELEASE_SCRIPT
    spec = importlib.util.spec_from_file_location(
        "pyble_release_bundle_license_audit_red",
        RELEASE_SCRIPT,
    )
    if spec is None or spec.loader is None:
        return None, "cannot construct import spec for %s" % RELEASE_SCRIPT
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - presence test reports this.
        return None, "cannot import release_bundle.py: %s" % exc
    return module, ""


RELEASE, RELEASE_LOAD_ERROR = load_release_module()
HAS_AUDIT = RELEASE is not None and callable(
    getattr(RELEASE, "audit_release_licenses", None)
)
HAS_LOCKED_RUNNER = RELEASE is not None and callable(
    getattr(RELEASE, "LockedWheelSbomRunner", None)
)
HAS_LOCKED_AUDIT = RELEASE is not None and callable(
    getattr(RELEASE, "audit_release_licenses_from_lock", None)
)


def make_ar_bytes(members: list[tuple[str, bytes]]) -> bytes:
    """Create a deterministic, structurally valid System V/GNU ar archive."""

    output = bytearray(b"!<arch>\n")
    for name, value in members:
        encoded_name = name.encode("ascii")
        if len(encoded_name) > 16 or b" " in encoded_name:
            raise ValueError("fixture ar member name is too long: %s" % name)
        name_field = encoded_name
        if len(encoded_name) < 16:
            name_field += b"/"
        name_field = name_field.ljust(16, b" ")
        header = (
            name_field
            + b"0".ljust(12, b" ")
            + b"0".ljust(6, b" ")
            + b"0".ljust(6, b" ")
            + b"100644".ljust(8, b" ")
            + str(len(value)).encode("ascii").ljust(10, b" ")
            + b"`\n"
        )
        if len(header) != 60:
            raise AssertionError("invalid ar header length")
        output.extend(header)
        output.extend(value)
        if len(value) % 2:
            output.extend(b"\n")
    return bytes(output)


def parse_ar_members(value: bytes) -> dict[str, bytes]:
    if not value.startswith(b"!<arch>\n"):
        raise ValueError("archive lacks global ar header")
    result: dict[str, bytes] = {}
    position = 8
    while position < len(value):
        if position + 60 > len(value):
            raise ValueError("truncated ar member header")
        header = value[position : position + 60]
        position += 60
        if header[58:60] != b"`\n":
            raise ValueError("invalid ar member trailer")
        raw_name = header[:16].decode("ascii").strip()
        name = raw_name[:-1] if raw_name.endswith("/") else raw_name
        try:
            size = int(header[48:58].decode("ascii").strip())
        except ValueError as exc:
            raise ValueError("invalid ar member size") from exc
        if position + size > len(value):
            raise ValueError("truncated ar member")
        if not name or name in result:
            raise ValueError("empty or duplicate ar member")
        result[name] = value[position : position + size]
        position += size
        if size % 2:
            if value[position : position + 1] != b"\n":
                raise ValueError("invalid ar alignment byte")
            position += 1
    if position != len(value):
        raise ValueError("trailing ar bytes")
    return result


def map_archive_members(map_path: Path) -> list[tuple[Path, str]]:
    """Read the first-column archive-member records used by GNU ld maps."""

    records = []
    for line in map_path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"(\S+\.a)\(([^()]+)\)", line)
        if match is None:
            continue
        archive = Path(match.group(1))
        if not archive.is_absolute():
            archive = map_path.parent / archive
        records.append((archive, match.group(2)))
    return records


SPDX_TOKEN = re.compile(
    r"\s*(\(|\)|AND\b|OR\b|WITH\b|"
    r"(?:DocumentRef-[A-Za-z0-9.-]+:)?LicenseRef-[A-Za-z0-9.-]+|"
    r"[A-Za-z0-9][A-Za-z0-9.+-]*)"
)


class FixtureSpdxExpressionParser:
    """Small independent parser used only to prove fixture expression validity."""

    def __init__(self, value: str):
        self.value = value
        self.tokens: list[str] = []
        position = 0
        while position < len(value):
            match = SPDX_TOKEN.match(value, position)
            if match is None:
                raise ValueError("invalid SPDX token at %d" % position)
            self.tokens.append(match.group(1))
            position = match.end()
        self.index = 0
        self.identifiers: set[str] = set()

    def parse(self) -> set[str]:
        if self.value in ("NOASSERTION", "NONE") or not self.tokens:
            raise ValueError("non-license SPDX state")
        self._parse_or()
        if self.index != len(self.tokens):
            raise ValueError("trailing SPDX tokens")
        return self.identifiers

    def _peek(self) -> str | None:
        if self.index >= len(self.tokens):
            return None
        return self.tokens[self.index]

    def _take(self, expected: str | None = None) -> str:
        token = self._peek()
        if token is None or (expected is not None and token != expected):
            raise ValueError("expected %r, got %r" % (expected, token))
        self.index += 1
        return token

    def _parse_or(self) -> None:
        self._parse_and()
        while self._peek() == "OR":
            self._take("OR")
            self._parse_and()

    def _parse_and(self) -> None:
        self._parse_with()
        while self._peek() == "AND":
            self._take("AND")
            self._parse_with()

    def _parse_with(self) -> None:
        self._parse_primary()
        if self._peek() == "WITH":
            self._take("WITH")
            exception = self._take()
            if exception in ("(", ")", "AND", "OR", "WITH"):
                raise ValueError("invalid SPDX exception")
            self.identifiers.add(exception)

    def _parse_primary(self) -> None:
        token = self._peek()
        if token == "(":
            self._take("(")
            self._parse_or()
            self._take(")")
            return
        identifier = self._take()
        if identifier in (")", "AND", "OR", "WITH"):
            raise ValueError("expected SPDX identifier")
        self.identifiers.add(identifier)


def parse_fixture_spdx(
    expression: str,
    approved_license_refs: set[str],
) -> set[str]:
    identifiers = FixtureSpdxExpressionParser(expression).parse()
    for identifier in identifiers:
        if "LicenseRef-" in identifier:
            if identifier not in approved_license_refs:
                raise ValueError("unapproved LicenseRef: %s" % identifier)
        elif identifier not in KNOWN_FIXTURE_SPDX:
            raise ValueError("unknown SPDX identifier: %s" % identifier)
    return identifiers


def make_fixture_wheel(
    path: Path,
    *,
    distribution: str,
    version: str,
    requires: tuple[str, ...],
) -> None:
    normalized = distribution.replace("-", "_")
    dist_info = "%s-%s.dist-info" % (normalized, version)
    metadata = [
        "Metadata-Version: 2.1",
        "Name: %s" % distribution,
        "Version: %s" % version,
    ]
    metadata.extend("Requires-Dist: %s" % item for item in requires)
    metadata.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        for name, content in (
            (
                "%s/METADATA" % dist_info,
                "\n".join(metadata).encode("utf-8"),
            ),
            (
                "%s/WHEEL" % dist_info,
                (
                    "Wheel-Version: 1.0\n"
                    "Generator: PyBLE BLD-8 fixture\n"
                    "Root-Is-Purelib: true\n"
                    "Tag: py3-none-any\n"
                ).encode("utf-8"),
            ),
            ("%s/RECORD" % dist_info, b""),
            ("%s/__init__.py" % normalized, b""),
        ):
            info = zipfile.ZipInfo(name)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)


def make_runner_wheel(
    path: Path,
    *,
    distribution: str,
    version: str,
    requires: tuple[str, ...] = (),
    tag: str = "py3-none-any",
    files: dict[str, bytes] | None = None,
) -> None:
    """Create a deterministic wheel for the production-runner host contract."""

    normalized = distribution.replace("-", "_").replace(".", "_")
    dist_info = "%s-%s.dist-info" % (normalized, version)
    metadata = [
        "Metadata-Version: 2.1",
        "Name: %s" % distribution,
        "Version: %s" % version,
    ]
    metadata.extend("Requires-Dist: %s" % item for item in requires)
    metadata.append("")
    members = {
        "%s/METADATA" % dist_info: "\n".join(metadata).encode("utf-8"),
        "%s/WHEEL"
        % dist_info: (
            "Wheel-Version: 1.0\n"
            "Generator: PyBLE locked-runner fixture\n"
            "Root-Is-Purelib: true\n"
            "Tag: %s\n" % tag
        ).encode("utf-8"),
        "%s/RECORD" % dist_info: b"",
        "%s/__init__.py" % normalized: b"",
    }
    members.update(files or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        for name, content in sorted(members.items()):
            info = zipfile.ZipInfo(name)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)


LOCKED_RUNNER_MODULE = b"""\
import json
import os
from pathlib import Path
import socket
import sys

output = Path(sys.argv[sys.argv.index("--output-file") + 1])
probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    network_errno = probe.connect_ex(("1.1.1.1", 53))
finally:
    probe.close()
output.write_text(json.dumps({
    "argv": sys.argv,
    "isolated": sys.flags.isolated,
    "marker": "verified-locked-wheel",
    "network_errno": network_errno,
    "poison": {
        key: os.environ.get(key)
        for key in (
            "DYLD_INSERT_LIBRARIES",
            "HTTPS_PROXY",
            "PYTHONHOME",
            "PYTHONPATH",
            "PYTHONSTARTUP",
        )
    },
}, sort_keys=True) + "\\n", encoding="utf-8")
"""


class LockedRunnerFixture:
    """Small offline wheel closure for the real runner adapter."""

    def __init__(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="pyble-locked-runner-")
        self.root = Path(self._temporary.name)
        self.repo = self.root / "repo"
        self.build_root = self.root / "build"
        self.wheelhouse = self.root / "wheelhouse"
        self.repo.mkdir()
        self.build_root.mkdir()
        self.wheelhouse.mkdir()
        self.firmware = self.repo / "firmware"
        self.licenses = self.firmware / "licenses"
        self.licenses.mkdir(parents=True)
        self.excluded = self.licenses / "excluded-cves.yaml"
        self.policy = self.licenses / "license-policy.json"
        self.excluded.write_text("{}\n", encoding="utf-8")
        self.policy.write_text("{}\n", encoding="utf-8")
        self.description = self.build_root / "project_description.json"
        self.description.write_text("{}\n", encoding="utf-8")
        self.output = self.build_root / "runner-output.json"
        self.top = self.wheelhouse / SBOM_WHEEL
        self.dependency = self.wheelhouse / "fixture_dependency-1.0-py3-none-any.whl"
        make_runner_wheel(
            self.top,
            distribution=SBOM_NAME,
            version=SBOM_VERSION,
            requires=("fixture-dependency>=1",),
            files={"esp_idf_sbom/__main__.py": LOCKED_RUNNER_MODULE},
        )
        make_runner_wheel(
            self.dependency,
            distribution="fixture-dependency",
            version="1.0",
        )
        self.lock_path = self.firmware / "release-tools.lock"
        self.write_lock()

    def close(self):
        self._temporary.cleanup()

    @property
    def top_hash(self) -> str:
        return sha256_path(self.top)

    def artifact_hashes(self) -> dict[str, str]:
        return {
            SBOM_NAME: sha256_path(self.top),
            "fixture-dependency": sha256_path(self.dependency),
        }

    def write_lock(
        self,
        *,
        dependency_name: str = "fixture-dependency",
        dependency_filename: str | None = None,
        dependency_version: str = "1.0",
    ) -> None:
        filename = dependency_filename or self.dependency.name
        self.lock_path.write_text(
            """# SPDX-License-Identifier: MIT
schema_version = 1

[tool]
name = "esp-idf-sbom"
version = "1.2.0"
tag = "v1.2.0"
commit = "d46a159ac239b9f843c59e0b4bfcfaff1859b862"
filename = "esp_idf_sbom-1.2.0-py3-none-any.whl"
sha256 = "%s"

[inputs]
excluded_cves_path = "firmware/licenses/excluded-cves.yaml"
excluded_cves_sha256 = "%s"
license_policy_path = "firmware/licenses/license-policy.json"
license_policy_sha256 = "%s"

[[artifacts]]
name = "esp-idf-sbom"
version = "1.2.0"
filename = "esp_idf_sbom-1.2.0-py3-none-any.whl"
sha256 = "%s"
requires = ["fixture-dependency==1.0"]

[[artifacts]]
name = "%s"
version = "%s"
filename = "%s"
sha256 = "%s"
requires = []
"""
            % (
                self.top_hash,
                sha256_path(self.excluded),
                sha256_path(self.policy),
                self.top_hash,
                dependency_name,
                dependency_version,
                filename,
                sha256_path(self.dependency),
            ),
            encoding="utf-8",
        )

    def command(self) -> list[str]:
        return [
            sys.executable,
            "-m",
            "esp_idf_sbom",
            "create",
            str(self.description),
            "--output-file",
            str(self.output),
            "--rem-unused",
            "--rem-config",
            "--file-tags",
        ]


def validate_lock_semantics(
    testcase: unittest.TestCase,
    lock_path: Path,
    *,
    repo_root: Path,
    verify_cached_artifacts: bool = False,
) -> dict:
    testcase.assertTrue(lock_path.is_file(), "release-tools.lock is missing")
    with lock_path.open("rb") as handle:
        lock = tomllib.load(handle)

    tool = lock.get("tool")
    testcase.assertIsInstance(tool, dict)
    testcase.assertEqual(tool.get("name"), SBOM_NAME)
    testcase.assertEqual(tool.get("version"), SBOM_VERSION)
    testcase.assertEqual(tool.get("filename"), SBOM_WHEEL)
    testcase.assertEqual(tool.get("sha256"), SBOM_WHEEL_SHA256)
    lock_scalars = set(deep_scalars(lock))
    testcase.assertIn(SBOM_TAG, lock_scalars)
    testcase.assertIn(SBOM_COMMIT, lock_scalars)

    artifacts = lock.get("artifacts")
    testcase.assertIsInstance(artifacts, list)
    testcase.assertTrue(artifacts, "locked Python closure is empty")
    by_name: dict[str, list[dict]] = {}
    artifact_identities = set()
    for artifact in artifacts:
        testcase.assertIsInstance(artifact, dict)
        for field in ("name", "version", "filename", "sha256"):
            testcase.assertIn(field, artifact)
        name = canonical_package_name(artifact["name"])
        identity = (
            name,
            artifact["version"],
            artifact["filename"],
            artifact["sha256"],
        )
        testcase.assertNotIn(
            identity,
            artifact_identities,
            "duplicate locked artifact record",
        )
        artifact_identities.add(identity)
        testcase.assertRegex(artifact["sha256"], HEX64)
        requirements = artifact_requirements(artifact)
        testcase.assertTrue(all(isinstance(item, str) for item in requirements))
        by_name.setdefault(name, []).append(artifact)
        relative = artifact.get("path")
        if relative is not None and verify_cached_artifacts:
            cached = safe_fixture_path(repo_root, relative)
            testcase.assertTrue(cached.is_file())
            testcase.assertEqual(sha256_path(cached), artifact["sha256"])

    testcase.assertIn(SBOM_NAME, by_name)
    matching_top = [
        artifact
        for artifact in by_name[SBOM_NAME]
        if artifact["version"] == SBOM_VERSION
        and artifact["filename"] == SBOM_WHEEL
        and artifact["sha256"] == SBOM_WHEEL_SHA256
    ]
    testcase.assertEqual(len(matching_top), 1)
    top = matching_top[0]
    testcase.assertEqual(top["version"], SBOM_VERSION)
    testcase.assertEqual(top["filename"], SBOM_WHEEL)
    testcase.assertEqual(top["sha256"], SBOM_WHEEL_SHA256)

    reachable = {SBOM_NAME}
    pending = [SBOM_NAME]
    while pending:
        current = pending.pop()
        for artifact in by_name[current]:
            for requirement in artifact_requirements(artifact):
                dependency = requirement_name(requirement)
                testcase.assertIn(
                    dependency,
                    by_name,
                    "locked requirement %s has no hashed artifact" % requirement,
                )
                if dependency not in reachable:
                    reachable.add(dependency)
                    pending.append(dependency)
    testcase.assertEqual(
        set(by_name),
        reachable,
        "lock contains unreachable or omits reachable closure artifacts",
    )
    return lock


def validate_spdx_document(
    testcase: unittest.TestCase,
    document: dict,
    *,
    approved_license_refs: set[str],
) -> None:
    testcase.assertEqual(document.get("spdxVersion"), "SPDX-2.3")
    testcase.assertEqual(document.get("dataLicense"), "CC0-1.0")
    testcase.assertEqual(document.get("SPDXID"), "SPDXRef-DOCUMENT")
    testcase.assertRegex(
        document.get("documentNamespace", ""),
        r"^(?:https://|urn:)",
    )
    creation = document.get("creationInfo")
    testcase.assertIsInstance(creation, dict)
    testcase.assertRegex(creation.get("created", ""), SPDX_TIMESTAMP)
    testcase.assertIn("Tool: esp-idf-sbom-1.2.0", creation.get("creators", []))
    packages = document.get("packages")
    testcase.assertIsInstance(packages, list)
    testcase.assertTrue(packages)
    package_ids = set()
    referenced_license_refs = set()
    for package in packages:
        package_id = package.get("SPDXID")
        testcase.assertRegex(package_id, r"^SPDXRef-Package-[A-Za-z0-9.-]+$")
        testcase.assertNotIn(package_id, package_ids)
        package_ids.add(package_id)
        testcase.assertFalse(package.get("filesAnalyzed"))
        testcase.assertIsInstance(package.get("name"), str)
        testcase.assertIsInstance(package.get("versionInfo"), str)
        testcase.assertRegex(package.get("downloadLocation", ""), r"^https://")
        testcase.assertIsInstance(package.get("copyrightText"), str)
        testcase.assertNotIn(
            package.get("licenseDeclared"),
            ("NOASSERTION", "NONE"),
        )
        identifiers = parse_fixture_spdx(
            package["licenseDeclared"],
            approved_license_refs,
        )
        referenced_license_refs.update(
            identifier for identifier in identifiers if "LicenseRef-" in identifier
        )
        testcase.assertEqual(
            package.get("licenseConcluded"),
            package.get("licenseDeclared"),
        )
    described = {
        relationship.get("relatedSpdxElement")
        for relationship in document.get("relationships", [])
        if relationship.get("spdxElementId") == "SPDXRef-DOCUMENT"
        and relationship.get("relationshipType") == "DESCRIBES"
    }
    testcase.assertEqual(described, package_ids)
    extracted_ids = {
        item.get("licenseId") for item in document.get("hasExtractedLicensingInfos", [])
    }
    testcase.assertTrue(referenced_license_refs <= extracted_ids)


MIT_TEXT = """MIT License

Copyright (c) 2099 PyBLE synthetic fixture authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

BSD2_TEXT = """BSD 2-Clause License

Copyright (c) 2099, PyBLE synthetic fixture authors
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES ARE DISCLAIMED.
"""

SYNTHETIC_TEXTS = {
    "MIT.txt": MIT_TEXT,
    "BSD-2-Clause.txt": BSD2_TEXT,
    "Fixture-Controller.txt": (
        "LicenseRef-PyBLE-Test-Controller\n"
        "Complete synthetic controller-blob fixture terms.\n"
        "This is not a statement about an Espressif binary.\n"
    ),
    "Fixture-PHY.txt": (
        "LicenseRef-PyBLE-Test-PHY\n"
        "Complete synthetic PHY-blob fixture terms.\n"
        "This is not a statement about an Espressif binary.\n"
    ),
    "Fixture-WiFi.txt": (
        "LicenseRef-PyBLE-Test-WiFi\n"
        "Complete synthetic Wi-Fi-blob fixture terms.\n"
        "This is not a statement about an Espressif binary.\n"
    ),
    "Fixture-Coex.txt": (
        "LicenseRef-PyBLE-Test-Coex\n"
        "Complete synthetic coexistence-blob fixture terms.\n"
        "This is not a statement about an Espressif binary.\n"
    ),
    "GPL-3.0-or-later.fixture.txt": (
        "SYNTHETIC TEST REPRESENTATION — GNU GENERAL PUBLIC LICENSE\n"
        "Version 3, 29 June 2007\n"
        "Complete fixture document used to prove whole-file inclusion.\n"
        "Production policy must point to the complete reviewed GPLv3 text.\n"
        "END OF COMPLETE GPL-3.0-OR-LATER FIXTURE DOCUMENT\n"
    ),
    "GCC-exception-3.1.fixture.txt": (
        "SYNTHETIC TEST REPRESENTATION — GCC RUNTIME LIBRARY EXCEPTION\n"
        "Version 3.1, 31 March 2009\n"
        "Complete fixture document used to prove whole-file inclusion.\n"
        "Production policy must point to the complete reviewed exception text.\n"
        "END OF COMPLETE GCC-EXCEPTION-3.1 FIXTURE DOCUMENT\n"
    ),
    "COPYING.NEWLIB.fixture.txt": (
        "LicenseRef-PyBLE-Test-Newlib-Multilicense\n"
        "Complete synthetic multi-license newlib fixture input.\n"
        "This is not a statement about a shipped newlib archive.\n"
    ),
}

NOTICE_TEXTS = {
    "source.txt": (
        "Retain this synthetic source attribution and its complete license text.\n"
    ),
    "binary.txt": (
        "Retain this synthetic binary redistribution notice and exact terms.\n"
    ),
    "runtime.txt": (
        "Retain the complete runtime license texts and applicable exception.\n"
    ),
}


class ReleaseLicenseFixture:
    """A realistic, legally neutral six-inventory BLD-8 fixture."""

    def __init__(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="pyble-bld8-license-")
        self.root = Path(self._temporary.name)
        self.repo = self.root / "repo"
        self.build_root = self.root / "build"
        self.evidence = self.root / "review-evidence"
        self.repo.mkdir()
        self.build_root.mkdir()
        self.evidence.mkdir()
        self.firmware = self.repo / "firmware"
        self.licenses = self.firmware / "licenses"
        self.policy_path = self.licenses / "license-policy.json"
        self.lock_path = self.firmware / "release-tools.lock"
        self.excluded_cves = self.licenses / "excluded-cves.yaml"
        self._make_sources_and_license_texts()
        self._make_tool_artifacts()
        self._make_build_inputs()
        self._make_policy()
        self._make_excluded_cves()
        self._make_lock()

    def close(self) -> None:
        self._temporary.cleanup()

    def _make_sources_and_license_texts(self) -> None:
        text_root = self.licenses / "texts"
        notice_root = self.licenses / "notices"
        for name, value in SYNTHETIC_TEXTS.items():
            path = text_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-8")
        for name, value in NOTICE_TEXTS.items():
            path = notice_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-8")

        components = self.firmware / "components"
        (components / "app_core").mkdir(parents=True)
        (components / "boot_core").mkdir(parents=True)
        (components / "app_core" / "app_core.c").write_text(
            "// SPDX-License-Identifier: MIT\n"
            "// Copyright (c) 2099 PyBLE synthetic fixture authors\n"
            "int fixture_app_core(void) { return 1; }\n",
            encoding="utf-8",
        )
        (components / "boot_core" / "boot_core.c").write_text(
            "// SPDX-License-Identifier: BSD-2-Clause\n"
            "// Copyright (c) 2099 PyBLE synthetic fixture authors\n"
            "int fixture_boot_core(void) { return 2; }\n",
            encoding="utf-8",
        )

        mpy = self.firmware / "upstream" / "micropython"
        (mpy / "py").mkdir(parents=True)
        (mpy / "py" / "vm.c").write_text(
            "// SPDX-License-Identifier: MIT\n"
            "// Copyright (c) 2099 PyBLE synthetic fixture authors\n",
            encoding="utf-8",
        )
        esp32_modules = mpy / "ports" / "esp32" / "modules"
        esp32_modules.mkdir(parents=True)
        for name in ("flashbdev.py", "inisetup.py"):
            (esp32_modules / name).write_text(
                "# SPDX-License-Identifier: MIT\n"
                "# Copyright (c) 2099 PyBLE synthetic fixture authors\n",
                encoding="utf-8",
            )
        asyncio = mpy / "extmod" / "asyncio"
        asyncio.mkdir(parents=True)
        for name in ("__init__.py", "core.py"):
            (asyncio / name).write_text(
                "# SPDX-License-Identifier: MIT\n"
                "# Copyright (c) 2099 PyBLE synthetic fixture authors\n",
                encoding="utf-8",
            )
        (asyncio / "manifest.py").write_text(
            'package("asyncio", ("__init__.py", "core.py"), '
            'base_path="..", opt=3)\n',
            encoding="utf-8",
        )
        neopixel = (
            mpy
            / "lib"
            / "micropython-lib"
            / "micropython"
            / "drivers"
            / "led"
            / "neopixel"
        )
        neopixel.mkdir(parents=True)
        (neopixel / "neopixel.py").write_text(
            "# SPDX-License-Identifier: MIT\n"
            "# Copyright (c) 2099 PyBLE synthetic fixture authors\n"
            "class NeoPixel:\n"
            "    pass\n",
            encoding="utf-8",
        )
        (neopixel / "manifest.py").write_text(
            'metadata(description="Synthetic NeoPixel driver.", version="0.1.0")\n'
            'module("neopixel.py", opt=3)\n',
            encoding="utf-8",
        )

        vendor = self.firmware / "fixture-vendor"
        for category, member in (
            ("controller", "controller.o"),
            ("phy", "phy.o"),
            ("wifi", "wifi.o"),
            ("coex", "coex.o"),
        ):
            directory = vendor / category
            directory.mkdir(parents=True)
            (directory / ("libfixture_%s.a" % category)).write_bytes(
                make_ar_bytes(
                    [
                        (
                            member,
                            ("%s synthetic prebuilt object\n" % category).encode(
                                "utf-8"
                            ),
                        )
                    ]
                )
            )

        toolchain = self.firmware / "fixture-toolchain"
        toolchain.mkdir(parents=True)
        (toolchain / "libgcc.a").write_bytes(
            make_ar_bytes(
                [
                    ("_divsi3.o", b"synthetic libgcc application member\n"),
                    ("_clzsi2.o", b"synthetic libgcc boot member\n"),
                ]
            )
        )
        (toolchain / "libc.a").write_bytes(
            make_ar_bytes(
                [
                    ("memcpy.o", b"synthetic newlib application member\n"),
                    ("memset.o", b"synthetic newlib boot member\n"),
                ]
            )
        )

    def _make_tool_artifacts(self) -> None:
        cache = self.firmware / "release-tool-fixtures"
        make_fixture_wheel(
            cache / "fixture_schema-1.0-py3-none-any.whl",
            distribution="fixture-schema",
            version="1.0",
            requires=("fixture-transitive==3.0",),
        )
        make_fixture_wheel(
            cache / "fixture_expression-2.0-py3-none-any.whl",
            distribution="fixture-expression",
            version="2.0",
            requires=(),
        )
        make_fixture_wheel(
            cache / "fixture_transitive-3.0-py3-none-any.whl",
            distribution="fixture-transitive",
            version="3.0",
            requires=(),
        )

    def _make_build_inputs(self) -> None:
        for profile_id, target, idf_target in PROFILE_TARGETS:
            target_build = self.build_root / target
            boot_build = target_build / "bootloader"
            target_build.mkdir()
            boot_build.mkdir()

            app_archive = target_build / "esp-idf" / "app_core" / "libfixture_app.a"
            boot_archive = boot_build / "esp-idf" / "boot_core" / "libfixture_boot.a"
            mpy_archive = target_build / "micropython" / "libmicropython.a"
            app_archive.parent.mkdir(parents=True)
            boot_archive.parent.mkdir(parents=True)
            mpy_archive.parent.mkdir(parents=True)
            app_archive.write_bytes(
                make_ar_bytes([("app_core.o", b"synthetic app object\n")])
            )
            boot_archive.write_bytes(
                make_ar_bytes([("boot_core.o", b"synthetic boot object\n")])
            )
            mpy_archive.write_bytes(
                make_ar_bytes(
                    [
                        ("vm.o", b"synthetic MicroPython VM object\n"),
                        ("frozen.o", b"synthetic frozen-content object\n"),
                    ]
                )
            )

            manifest = self.firmware / "board_overlays" / target / "manifest.py"
            manifest.parent.mkdir(parents=True)
            (manifest.parent / "_boot.py").write_text(
                "# SPDX-License-Identifier: MIT\n",
                encoding="utf-8",
            )
            (manifest.parent / "pyble").mkdir()
            (manifest.parent / "pyble" / "pyble_agent.py").write_text(
                "# SPDX-License-Identifier: MIT\n",
                encoding="utf-8",
            )
            manifest.write_text(
                'module("flashbdev.py", base_path="$(PORT_DIR)/modules")\n'
                'module("inisetup.py", base_path="$(PORT_DIR)/modules")\n'
                'include("$(MPY_DIR)/extmod/asyncio")\n'
                'require("neopixel")\n'
                'module("_boot.py", base_path="$(BOARD_DIR)")\n'
                'module("pyble/pyble_agent.py", '
                'base_path="$(BOARD_DIR)")\n',
                encoding="utf-8",
            )
            (target_build / "frozen_content.c").write_text(
                "// Content for MICROPY_MODULE_FROZEN_MPY\n"
                "// - frozen file name: flashbdev.py\n"
                "// - frozen file name: inisetup.py\n"
                "// - frozen file name: asyncio/__init__.py\n"
                "// - frozen file name: asyncio/core.py\n"
                "// - frozen file name: _boot.py\n"
                "// - frozen file name: pyble/pyble_agent.py\n"
                "// - frozen file name: neopixel.py\n"
                "const char mp_frozen_names[] = {\n"
                '    "flashbdev.py\\0"\n'
                '    "inisetup.py\\0"\n'
                '    "asyncio/__init__.py\\0"\n'
                '    "asyncio/core.py\\0"\n'
                '    "_boot.py\\0"\n'
                '    "pyble/pyble_agent.py\\0"\n'
                '    "neopixel.py\\0"\n'
                "};\n",
                encoding="utf-8",
            )

            app_sources = [
                {
                    "directory": str(target_build),
                    "command": (
                        "/fixture/%s-gcc -c %s -o "
                        "esp-idf/app_core/CMakeFiles/app_core.dir/app_core.o"
                    )
                    % (
                        idf_target,
                        self.firmware / "components" / "app_core" / "app_core.c",
                    ),
                    "file": str(
                        self.firmware / "components" / "app_core" / "app_core.c"
                    ),
                    "output": str(
                        target_build
                        / "esp-idf"
                        / "app_core"
                        / "CMakeFiles"
                        / "app_core.dir"
                        / "app_core.o"
                    ),
                },
                {
                    "directory": str(target_build),
                    "command": (
                        "/fixture/%s-gcc -c %s -o "
                        "micropython/CMakeFiles/micropython.dir/vm.o"
                    )
                    % (
                        idf_target,
                        self.firmware / "upstream" / "micropython" / "py" / "vm.c",
                    ),
                    "file": str(
                        self.firmware / "upstream" / "micropython" / "py" / "vm.c"
                    ),
                    "output": str(
                        target_build
                        / "micropython"
                        / "CMakeFiles"
                        / "micropython.dir"
                        / "vm.o"
                    ),
                },
                {
                    "directory": str(target_build),
                    "command": (
                        "/fixture/%s-gcc -c %s -o "
                        "micropython/CMakeFiles/micropython.dir/frozen.o"
                    )
                    % (idf_target, target_build / "frozen_content.c"),
                    "file": str(target_build / "frozen_content.c"),
                    "output": str(
                        target_build
                        / "micropython"
                        / "CMakeFiles"
                        / "micropython.dir"
                        / "frozen.o"
                    ),
                },
            ]
            boot_sources = [
                {
                    "directory": str(boot_build),
                    "command": (
                        "/fixture/%s-gcc -c %s -o "
                        "esp-idf/boot_core/CMakeFiles/boot_core.dir/boot_core.o"
                    )
                    % (
                        idf_target,
                        self.firmware / "components" / "boot_core" / "boot_core.c",
                    ),
                    "file": str(
                        self.firmware / "components" / "boot_core" / "boot_core.c"
                    ),
                    "output": str(
                        boot_build
                        / "esp-idf"
                        / "boot_core"
                        / "CMakeFiles"
                        / "boot_core.dir"
                        / "boot_core.o"
                    ),
                }
            ]
            output_payloads = {
                Path(app_sources[0]["output"]): b"synthetic app object\n",
                Path(app_sources[1]["output"]): (
                    b"synthetic MicroPython VM object\n"
                ),
                Path(app_sources[2]["output"]): (
                    b"synthetic frozen-content object\n"
                ),
                Path(boot_sources[0]["output"]): b"synthetic boot object\n",
            }
            for output, payload in output_payloads.items():
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(payload)

            app_link = (
                target_build
                / "CMakeFiles"
                / "micropython.elf.dir"
                / "link.txt"
            )
            boot_link = (
                boot_build
                / "CMakeFiles"
                / "bootloader.elf.dir"
                / "link.txt"
            )
            app_link.parent.mkdir(parents=True, exist_ok=True)
            boot_link.parent.mkdir(parents=True, exist_ok=True)
            app_link.write_text(
                (
                    "/fixture/%s-g++ -o micropython.elf "
                    "esp-idf/app_core/libfixture_app.a "
                    "micropython/libmicropython.a\n"
                )
                % idf_target,
                encoding="utf-8",
            )
            boot_link.write_text(
                (
                    "/fixture/%s-gcc -o bootloader.elf "
                    "esp-idf/boot_core/libfixture_boot.a\n"
                )
                % idf_target,
                encoding="utf-8",
            )
            write_json(target_build / "compile_commands.json", app_sources)
            write_json(boot_build / "compile_commands.json", boot_sources)

            app_info = {
                "app_core": {
                    "dir": str(self.firmware / "components" / "app_core"),
                    "type": "LIBRARY",
                    "lib": "app_core",
                    "file": str(app_archive),
                    "sources": [app_sources[0]["file"]],
                },
                "micropython": {
                    "dir": str(self.firmware / "upstream" / "micropython"),
                    "type": "LIBRARY",
                    "lib": "micropython",
                    "file": str(mpy_archive),
                    "sources": [
                        app_sources[1]["file"],
                        app_sources[2]["file"],
                    ],
                },
            }
            boot_info = {
                "boot_core": {
                    "dir": str(self.firmware / "components" / "boot_core"),
                    "type": "LIBRARY",
                    "lib": "boot_core",
                    "file": str(boot_archive),
                    "sources": [boot_sources[0]["file"]],
                }
            }
            write_json(
                target_build / "project_description.json",
                {
                    "project_name": "micropython",
                    "project_version": "fixture-v1",
                    "project_dir": str(self.repo),
                    "build_dir": str(target_build),
                    "target": idf_target,
                    "app_elf": str(target_build / "micropython.elf"),
                    "build_components": list(app_info),
                    "build_component_info": app_info,
                },
            )
            write_json(
                boot_build / "project_description.json",
                {
                    "project_name": "bootloader",
                    "project_version": "fixture-v1",
                    "project_dir": str(self.repo),
                    "build_dir": str(boot_build),
                    "target": idf_target,
                    "app_elf": str(boot_build / "bootloader.elf"),
                    "build_components": list(boot_info),
                    "build_component_info": boot_info,
                },
            )

            app_map_entries = [
                (
                    "esp-idf/app_core/libfixture_app.a",
                    "app_core.o",
                    "fixture_app_core",
                ),
                (
                    "micropython/libmicropython.a",
                    "vm.o",
                    "mp_execute_bytecode",
                ),
                (
                    "micropython/libmicropython.a",
                    "frozen.o",
                    "mp_frozen_names",
                ),
            ]
            for category, member in (
                ("controller", "controller.o"),
                ("phy", "phy.o"),
                ("wifi", "wifi.o"),
                ("coex", "coex.o"),
            ):
                source = (
                    self.firmware
                    / "fixture-vendor"
                    / category
                    / ("libfixture_%s.a" % category)
                )
                destination = target_build / "vendor" / category / source.name
                destination.parent.mkdir(parents=True)
                shutil.copyfile(source, destination)
                app_map_entries.append(
                    (
                        destination.relative_to(target_build).as_posix(),
                        member,
                        "fixture_%s_symbol" % category,
                    )
                )
            app_map_entries.extend(
                [
                    (
                        str(self.firmware / "fixture-toolchain" / "libgcc.a"),
                        "_divsi3.o",
                        "__divsi3",
                    ),
                    (
                        str(self.firmware / "fixture-toolchain" / "libc.a"),
                        "memcpy.o",
                        "memcpy",
                    ),
                ]
            )
            boot_map_entries = [
                (
                    "esp-idf/boot_core/libfixture_boot.a",
                    "boot_core.o",
                    "call_start_cpu0",
                ),
                (
                    str(self.firmware / "fixture-toolchain" / "libgcc.a"),
                    "_clzsi2.o",
                    "__clzsi2",
                ),
                (
                    str(self.firmware / "fixture-toolchain" / "libc.a"),
                    "memset.o",
                    "memset",
                ),
            ]
            (target_build / "micropython.map").write_text(
                self._map_text(app_map_entries),
                encoding="utf-8",
            )
            (boot_build / "bootloader.map").write_text(
                self._map_text(boot_map_entries),
                encoding="utf-8",
            )

        spec = importlib.util.spec_from_file_location(
            "pyble_release_bundle_inputs_for_license_fixture",
            RELEASE_BUNDLE_TEST,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load release-bundle input fixtures")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(spec.name, None)
        release_fixture = module.ReleaseFixture()
        try:
            release_inputs = (
                "firmware.bin",
                "micropython.bin",
                "micropython.elf",
                "bootloader/bootloader.bin",
                "partition_table/partition-table.bin",
                "flasher_args.json",
                "sdkconfig",
                "pyble-build-provenance.json",
            )
            for _profile_id, target, _idf_target in PROFILE_TARGETS:
                for relative in release_inputs:
                    source = release_fixture.build_root / target / relative
                    destination = self.build_root / target / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
        finally:
            release_fixture.cleanup()

    @staticmethod
    def _map_text(entries: list[tuple[str, str, str]]) -> str:
        body = [
            "Archive member included to satisfy reference by file (symbol)",
            "",
        ]
        for archive, member, symbol in entries:
            body.append("%s(%s)" % (archive, member))
            body.append("                              (%s)" % symbol)
        body.extend(["", "Linker script and memory map", ""])
        body.extend("LOAD %s" % archive for archive, _member, _symbol in entries)
        return "\n".join(body) + "\n"

    def _record(
        self,
        *,
        identifier: str,
        name: str,
        version_ref: str,
        source_url: str,
        copyright_text: str,
        match_kind: str,
        match_path: Path,
        spdx_expression: str,
        applicability: list[dict[str, str]],
        license_files: list[str],
        notice_file: str,
    ) -> dict:
        return {
            "id": identifier,
            "dependency": {
                "name": name,
                "version_ref": version_ref,
                "source_url": source_url,
                "copyright": copyright_text,
            },
            "match": {
                "kind": match_kind,
                "sha256": (
                    sha256_tree(match_path)
                    if match_kind == "source-tree"
                    else sha256_path(match_path)
                ),
            },
            "source": {
                "ref": version_ref,
                "url": source_url,
            },
            "spdx_expression": spdx_expression,
            "applicability": applicability,
            "license_texts": [
                {
                    "path": "firmware/licenses/texts/%s" % filename,
                    "sha256": sha256_path(self.licenses / "texts" / filename),
                }
                for filename in license_files
            ],
            "notice": {
                "required": True,
                "path": "firmware/licenses/notices/%s" % notice_file,
                "sha256": sha256_path(self.licenses / "notices" / notice_file),
            },
            "disposition": "allow",
        }

    def _make_policy(self) -> None:
        application = [
            {"profile_id": profile_id, "role": "application"}
            for profile_id, _target, _idf_target in PROFILE_TARGETS
        ]
        bootloader = [
            {"profile_id": profile_id, "role": "bootloader"}
            for profile_id, _target, _idf_target in PROFILE_TARGETS
        ]
        all_six = application + bootloader
        first_build = self.build_root / "esp32"
        records = [
            self._record(
                identifier="fixture-app-core",
                name="Fixture application component",
                version_ref="fixture-v1@%s" % ("1" * 40),
                source_url=(
                    "https://example.invalid/fixture-app/commit/%s" % ("1" * 40)
                ),
                copyright_text=("Copyright (c) 2099 PyBLE synthetic fixture authors"),
                match_kind="archive",
                match_path=(first_build / "esp-idf" / "app_core" / "libfixture_app.a"),
                spdx_expression="MIT OR BSD-2-Clause",
                applicability=application,
                license_files=["MIT.txt", "BSD-2-Clause.txt"],
                notice_file="source.txt",
            ),
            self._record(
                identifier="fixture-boot-core",
                name="Fixture bootloader component",
                version_ref="fixture-v1@%s" % ("2" * 40),
                source_url=(
                    "https://example.invalid/fixture-boot/commit/%s" % ("2" * 40)
                ),
                copyright_text=("Copyright (c) 2099 PyBLE synthetic fixture authors"),
                match_kind="archive",
                match_path=(
                    first_build
                    / "bootloader"
                    / "esp-idf"
                    / "boot_core"
                    / "libfixture_boot.a"
                ),
                spdx_expression="BSD-2-Clause",
                applicability=bootloader,
                license_files=["BSD-2-Clause.txt"],
                notice_file="source.txt",
            ),
            self._record(
                identifier="micropython-runtime",
                name="Fixture upstream MicroPython runtime",
                version_ref="fixture-mpy@%s" % ("3" * 40),
                source_url=(
                    "https://example.invalid/micropython/commit/%s" % ("3" * 40)
                ),
                copyright_text=("Copyright (c) 2099 PyBLE synthetic fixture authors"),
                match_kind="archive",
                match_path=(first_build / "micropython" / "libmicropython.a"),
                spdx_expression="MIT",
                applicability=application,
                license_files=["MIT.txt"],
                notice_file="source.txt",
            ),
            self._record(
                identifier="fixture-neopixel",
                name="Fixture frozen NeoPixel package",
                version_ref="fixture-neopixel@%s" % ("4" * 40),
                source_url=(
                    "https://example.invalid/micropython-lib/commit/%s" % ("4" * 40)
                ),
                copyright_text=("Copyright (c) 2099 PyBLE synthetic fixture authors"),
                match_kind="source-tree",
                match_path=(
                    self.firmware
                    / "upstream"
                    / "micropython"
                    / "lib"
                    / "micropython-lib"
                    / "micropython"
                    / "drivers"
                    / "led"
                    / "neopixel"
                ),
                spdx_expression="MIT",
                applicability=application,
                license_files=["MIT.txt"],
                notice_file="source.txt",
            ),
        ]
        for category, display, expression, license_name, commit_digit in (
            (
                "controller",
                "Fixture ESP controller prebuilt blob",
                "LicenseRef-PyBLE-Test-Controller",
                "Fixture-Controller.txt",
                "5",
            ),
            (
                "phy",
                "Fixture ESP PHY prebuilt blob",
                "LicenseRef-PyBLE-Test-PHY",
                "Fixture-PHY.txt",
                "6",
            ),
            (
                "wifi",
                "Fixture ESP Wi-Fi prebuilt blob",
                "LicenseRef-PyBLE-Test-WiFi",
                "Fixture-WiFi.txt",
                "7",
            ),
            (
                "coex",
                "Fixture ESP coexistence prebuilt blob",
                "LicenseRef-PyBLE-Test-Coex",
                "Fixture-Coex.txt",
                "8",
            ),
        ):
            records.append(
                self._record(
                    identifier="fixture-%s-blob" % category,
                    name=display,
                    version_ref="fixture-blob@%s" % (commit_digit * 40),
                    source_url=(
                        "https://example.invalid/fixture-blobs/commit/%s"
                        % (commit_digit * 40)
                    ),
                    copyright_text=("Copyright (c) 2099 synthetic fixture vendor"),
                    match_kind="archive",
                    match_path=(
                        self.firmware
                        / "fixture-vendor"
                        / category
                        / ("libfixture_%s.a" % category)
                    ),
                    spdx_expression=expression,
                    applicability=application,
                    license_files=[license_name],
                    notice_file="binary.txt",
                )
            )
        records.extend(
            [
                self._record(
                    identifier="fixture-gcc-runtime",
                    name="Fixture GCC runtime archive",
                    version_ref="fixture-gcc@%s" % ("9" * 40),
                    source_url=(
                        "https://example.invalid/fixture-gcc/commit/%s" % ("9" * 40)
                    ),
                    copyright_text=("Copyright (c) synthetic fixture runtime authors"),
                    match_kind="archive",
                    match_path=(self.firmware / "fixture-toolchain" / "libgcc.a"),
                    spdx_expression=("GPL-3.0-or-later WITH GCC-exception-3.1"),
                    applicability=all_six,
                    license_files=[
                        "GPL-3.0-or-later.fixture.txt",
                        "GCC-exception-3.1.fixture.txt",
                    ],
                    notice_file="runtime.txt",
                ),
                self._record(
                    identifier="fixture-newlib-runtime",
                    name="Fixture newlib runtime archive",
                    version_ref="fixture-newlib@%s" % ("a" * 40),
                    source_url=(
                        "https://example.invalid/fixture-newlib/commit/%s" % ("a" * 40)
                    ),
                    copyright_text=("Copyright (c) synthetic fixture runtime authors"),
                    match_kind="archive",
                    match_path=(self.firmware / "fixture-toolchain" / "libc.a"),
                    spdx_expression=("LicenseRef-PyBLE-Test-Newlib-Multilicense"),
                    applicability=all_six,
                    license_files=["COPYING.NEWLIB.fixture.txt"],
                    notice_file="runtime.txt",
                ),
            ]
        )
        write_json(
            self.policy_path,
            {
                "schema_version": 1,
                "approved_license_refs": [
                    "LicenseRef-PyBLE-Test-Controller",
                    "LicenseRef-PyBLE-Test-PHY",
                    "LicenseRef-PyBLE-Test-WiFi",
                    "LicenseRef-PyBLE-Test-Coex",
                    "LicenseRef-PyBLE-Test-Newlib-Multilicense",
                ],
                "entries": records,
            },
        )

    def _make_excluded_cves(self) -> None:
        self.excluded_cves.parent.mkdir(parents=True, exist_ok=True)
        self.excluded_cves.write_text(
            "# Intentionally empty; the reviewed hash is pinned.\n{}\n",
            encoding="utf-8",
        )

    def _make_lock(self) -> None:
        cache = self.firmware / "release-tool-fixtures"
        schema_wheel = cache / "fixture_schema-1.0-py3-none-any.whl"
        expression_wheel = cache / "fixture_expression-2.0-py3-none-any.whl"
        transitive_wheel = cache / "fixture_transitive-3.0-py3-none-any.whl"
        self.lock_path.write_text(
            """# SPDX-License-Identifier: MIT
schema_version = 1

[tool]
name = "esp-idf-sbom"
version = "1.2.0"
tag = "v1.2.0"
commit = "d46a159ac239b9f843c59e0b4bfcfaff1859b862"
filename = "esp_idf_sbom-1.2.0-py3-none-any.whl"
sha256 = "a1444a7f23740c44cacbce4845efb5cbcb08927878b6a3852c33a52d8b2b5da9"

[inputs]
excluded_cves_path = "firmware/licenses/excluded-cves.yaml"
excluded_cves_sha256 = "%s"
license_policy_path = "firmware/licenses/license-policy.json"
license_policy_sha256 = "%s"

[[artifacts]]
name = "esp-idf-sbom"
version = "1.2.0"
filename = "esp_idf_sbom-1.2.0-py3-none-any.whl"
sha256 = "a1444a7f23740c44cacbce4845efb5cbcb08927878b6a3852c33a52d8b2b5da9"
requires = ["fixture-schema==1.0", "fixture-expression==2.0"]

[[artifacts]]
name = "fixture-schema"
version = "1.0"
filename = "fixture_schema-1.0-py3-none-any.whl"
path = "firmware/release-tool-fixtures/fixture_schema-1.0-py3-none-any.whl"
sha256 = "%s"
requires = ["fixture-transitive==3.0"]

[[artifacts]]
name = "fixture-expression"
version = "2.0"
filename = "fixture_expression-2.0-py3-none-any.whl"
path = "firmware/release-tool-fixtures/fixture_expression-2.0-py3-none-any.whl"
sha256 = "%s"
requires = []

[[artifacts]]
name = "fixture-transitive"
version = "3.0"
filename = "fixture_transitive-3.0-py3-none-any.whl"
path = "firmware/release-tool-fixtures/fixture_transitive-3.0-py3-none-any.whl"
sha256 = "%s"
requires = []
"""
            % (
                sha256_path(self.excluded_cves),
                sha256_path(self.policy_path),
                sha256_path(schema_wheel),
                sha256_path(expression_wheel),
                sha256_path(transitive_wheel),
            ),
            encoding="utf-8",
        )

    def project_descriptions(self) -> list[Path]:
        paths = []
        for _profile_id, target, _idf_target in PROFILE_TARGETS:
            target_build = self.build_root / target
            paths.extend(
                [
                    target_build / "project_description.json",
                    target_build / "bootloader" / "project_description.json",
                ]
            )
        return paths

    def identity_for_description(self, path: Path) -> tuple[str, str]:
        resolved = path.resolve()
        for profile_id, target, _idf_target in PROFILE_TARGETS:
            target_build = (self.build_root / target).resolve()
            if resolved == (target_build / "project_description.json").resolve():
                return profile_id, "application"
            if (
                resolved
                == (target_build / "bootloader" / "project_description.json").resolve()
            ):
                return profile_id, "bootloader"
        raise KeyError("unknown fixture description: %s" % path)

    def policy(self) -> dict:
        return json.loads(self.policy_path.read_text(encoding="utf-8"))

    def policy_by_id(self) -> dict[str, dict]:
        return {entry["id"]: entry for entry in self.policy()["entries"]}

    def packages_for(
        self,
        profile_id: str,
        role: str,
    ) -> list[dict]:
        records = []
        for entry in self.policy()["entries"]:
            if {
                "profile_id": profile_id,
                "role": role,
            } not in entry["applicability"]:
                continue
            records.append(
                {
                    "id": entry["id"],
                    "name": entry["dependency"]["name"],
                    "version": entry["dependency"]["version_ref"],
                    "download": entry["dependency"]["source_url"],
                    "spdx": entry["spdx_expression"],
                    "copyright": entry["dependency"]["copyright"],
                }
            )
        return records

    def lock_artifact_hashes(self) -> dict[str, str]:
        with self.lock_path.open("rb") as handle:
            lock = tomllib.load(handle)
        return {
            canonical_package_name(item["name"]): item["sha256"]
            for item in lock["artifacts"]
        }

    def refresh_locked_policy_hash(self) -> None:
        text = self.lock_path.read_text(encoding="utf-8")
        text = re.sub(
            r'(?m)^(license_policy_sha256 = ")[0-9a-f]{64}(")$',
            r"\g<1>%s\g<2>" % sha256_path(self.policy_path),
            text,
        )
        self.lock_path.write_text(text, encoding="utf-8")

    @contextmanager
    def mutate_policy(self, mutation):
        policy_before = self.policy_path.read_bytes()
        lock_before = self.lock_path.read_bytes()
        try:
            changed = json.loads(policy_before)
            mutation(changed)
            write_json(self.policy_path, changed)
            self.refresh_locked_policy_hash()
            yield
        finally:
            self.policy_path.write_bytes(policy_before)
            self.lock_path.write_bytes(lock_before)

    @contextmanager
    def mutate_lock(self, mutation):
        before = self.lock_path.read_bytes()
        try:
            with self.lock_path.open("rb") as handle:
                changed = tomllib.load(handle)
            mutation(changed)
            self._write_mutated_lock(changed)
            yield
        finally:
            self.lock_path.write_bytes(before)

    def _write_mutated_lock(self, lock: dict) -> None:
        tool = lock["tool"]
        inputs = lock["inputs"]
        lines = [
            "# SPDX-License-Identifier: MIT",
            "schema_version = %d" % lock.get("schema_version", 1),
            "",
            "[tool]",
        ]
        for key in ("name", "version", "tag", "commit", "filename", "sha256"):
            lines.append("%s = %s" % (key, json.dumps(tool[key])))
        lines.extend(["", "[inputs]"])
        for key in (
            "excluded_cves_path",
            "excluded_cves_sha256",
            "license_policy_path",
            "license_policy_sha256",
        ):
            lines.append("%s = %s" % (key, json.dumps(inputs[key])))
        for artifact in lock["artifacts"]:
            lines.extend(["", "[[artifacts]]"])
            for key in ("name", "version", "filename", "path", "sha256"):
                if key in artifact:
                    lines.append("%s = %s" % (key, json.dumps(artifact[key])))
            lines.append("requires = %s" % json.dumps(artifact.get("requires", [])))
        self.lock_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@contextmanager
def patched_bytes(path: Path, replacement: bytes):
    existed = path.exists() or path.is_symlink()
    was_symlink = path.is_symlink()
    link_target = path.readlink() if was_symlink else None
    before = None if was_symlink or not existed else path.read_bytes()
    try:
        if path.exists() or path.is_symlink():
            path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(replacement)
        yield
    finally:
        if path.exists() or path.is_symlink():
            path.unlink()
        if was_symlink:
            path.symlink_to(link_target)
        elif existed:
            path.write_bytes(before)


@contextmanager
def patched_text(path: Path, replacement: str):
    with patched_bytes(path, replacement.encode("utf-8")):
        yield


@contextmanager
def removed_file(path: Path):
    if path.is_symlink():
        target = path.readlink()
        try:
            path.unlink()
            yield
        finally:
            if path.exists() or path.is_symlink():
                path.unlink()
            path.symlink_to(target)
        return
    before = path.read_bytes()
    try:
        path.unlink()
        yield
    finally:
        if path.exists() or path.is_symlink():
            path.unlink()
        path.write_bytes(before)


@contextmanager
def new_file(path: Path, value: bytes):
    if path.exists() or path.is_symlink():
        raise AssertionError("temporary path already exists: %s" % path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        yield
    finally:
        if path.exists() or path.is_symlink():
            path.unlink()


@contextmanager
def symlink_instead(path: Path, target: Path):
    before = path.read_bytes()
    try:
        path.unlink()
        path.symlink_to(target)
        yield
    finally:
        if path.exists() or path.is_symlink():
            path.unlink()
        path.write_bytes(before)


@contextmanager
def new_symlink(path: Path, target: Path):
    if path.exists() or path.is_symlink():
        raise AssertionError("temporary symlink already exists: %s" % path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
        yield
    finally:
        if path.exists() or path.is_symlink():
            path.unlink()


@contextmanager
def swapped_file_bytes(left: Path, right: Path):
    left_before = left.read_bytes()
    right_before = right.read_bytes()
    try:
        left.write_bytes(right_before)
        right.write_bytes(left_before)
        yield
    finally:
        left.write_bytes(left_before)
        right.write_bytes(right_before)


@dataclass
class FakeProcess:
    returncode: int
    stdout: str
    stderr: str
    executed_artifacts: dict[str, str]
    network_isolated: bool
    execution_identity: dict[str, object]


class FakeOfflineSbomRunner:
    """Writes valid SPDX 2.3 JSON for the exact requested description."""

    def __init__(
        self,
        fixture: ReleaseLicenseFixture,
        *,
        reverse_packages: bool = False,
        identity_mode: str = "normal",
        license_override: str | None = None,
        extra_package: str | None = None,
        executed_artifacts: dict[str, str] | None = None,
        network_isolated: bool = True,
    ):
        self.fixture = fixture
        self.reverse_packages = reverse_packages
        self.identity_mode = identity_mode
        self.license_override = license_override
        self.extra_package = extra_package
        self.executed_artifacts = (
            dict(executed_artifacts)
            if executed_artifacts is not None
            else fixture.lock_artifact_hashes()
        )
        self.network_isolated = network_isolated
        self.execution_identity = {
            "runner": "pyble-fixture-locked-wheel-v1",
            "python": {
                "implementation": "cpython",
                "version": "fixture-3.13",
            },
            "isolation": {
                "kind": "fixture-network-deny",
                "policy_sha256": "a" * 64,
            },
            "artifacts": [
                {
                    "name": name,
                    "version": "fixture",
                    "filename": "%s.whl" % name,
                    "sha256": digest,
                }
                for name, digest in sorted(self.executed_artifacts.items())
            ],
        }
        self.calls: list[dict] = []
        self.temporary_paths: set[Path] = set()
        self.raw_namespaces: list[str] = []

    def __call__(
        self,
        argv,
        *,
        cwd=None,
        env=None,
        check=True,
        network_disabled=False,
        **_unused,
    ):
        command = [str(item) for item in argv]
        call = {
            "argv": command,
            "cwd": Path(cwd).resolve() if cwd is not None else None,
            "env": dict(env or {}),
            "check": check,
            "network_disabled": network_disabled,
        }
        self.calls.append(call)
        if not network_disabled:
            raise RuntimeError("fixture SBOM tool refuses a network-enabled run")

        if "--output-file" not in command:
            raise RuntimeError("fixture SBOM invocation lacks --output-file")
        output_index = command.index("--output-file") + 1
        if output_index >= len(command):
            raise RuntimeError("fixture SBOM invocation lacks output path")
        output_path = Path(command[output_index])
        descriptions = [
            Path(item) for item in command if item.endswith("project_description.json")
        ]
        if len(descriptions) != 1:
            raise RuntimeError("fixture SBOM invocation needs one description")
        requested = self.fixture.identity_for_description(descriptions[0])
        identities = list(PROFILE_ROLES)
        if self.identity_mode == "normal":
            identity = requested
        elif self.identity_mode == "rotate":
            identity = identities[(identities.index(requested) + 1) % len(identities)]
        elif self.identity_mode == "duplicate":
            identity = identities[0]
        else:
            raise ValueError("unknown identity mode")

        environment = call["env"]
        for key in ("HOME", "XDG_CACHE_HOME", "PIP_CACHE_DIR"):
            if key in environment:
                directory = Path(environment[key])
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "fixture-cache-marker").write_text(
                    "must not be retained as review evidence\n",
                    encoding="utf-8",
                )
                self.temporary_paths.add(directory.resolve())

        document = self.spdx_document(*identity)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(output_path, document)
        return FakeProcess(
            returncode=0,
            stdout="",
            stderr="",
            executed_artifacts=dict(self.executed_artifacts),
            network_isolated=self.network_isolated,
            execution_identity=copy.deepcopy(self.execution_identity),
        )

    def spdx_document(self, profile_id: str, role: str) -> dict:
        packages = copy.deepcopy(self.fixture.packages_for(profile_id, role))
        if self.license_override is not None and packages:
            packages[0]["spdx"] = self.license_override
        if self.extra_package is not None:
            packages.append(
                {
                    "id": self.extra_package,
                    "name": self.extra_package,
                    "version": "fixture-extra@%s" % ("b" * 40),
                    "download": (
                        "https://example.invalid/extra/commit/%s" % ("b" * 40)
                    ),
                    "spdx": "MIT",
                    "copyright": ("Copyright (c) 2099 synthetic fixture authors"),
                }
            )
        if self.reverse_packages:
            packages.reverse()
        package_values = []
        relationships = []
        extracted = {}
        for package in packages:
            spdx_id = "SPDXRef-Package-%s" % re.sub(
                r"[^A-Za-z0-9.-]",
                "-",
                package["id"],
            )
            package_values.append(
                {
                    "name": package["name"],
                    "SPDXID": spdx_id,
                    "versionInfo": package["version"],
                    "downloadLocation": package["download"],
                    "filesAnalyzed": False,
                    "licenseConcluded": package["spdx"],
                    "licenseDeclared": package["spdx"],
                    "copyrightText": package["copyright"],
                    "comment": (
                        "generated from %s for %s/%s"
                        % (self.fixture.root, profile_id, role)
                    ),
                }
            )
            relationships.append(
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": spdx_id,
                }
            )
            # Deliberately do not parse here: malformed expressions must reach
            # the production validator so that the negative tests exercise its
            # parser rather than failing inside this fake.
            for identifier in re.findall(
                r"(?:DocumentRef-[A-Za-z0-9.-]+:)?" r"LicenseRef-[A-Za-z0-9.-]+",
                package["spdx"],
            ):
                if "LicenseRef-" in identifier:
                    extracted[identifier] = {
                        "licenseId": identifier,
                        "name": identifier,
                        "extractedText": (
                            "Exact synthetic extracted text for %s." % identifier
                        ),
                    }
        namespace = "https://spdx.example.invalid/%s" % uuid.uuid4()
        self.raw_namespaces.append(namespace)
        return {
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "PyBLE fixture %s/%s" % (profile_id, role),
            "documentNamespace": namespace,
            "creationInfo": {
                "created": "2099-12-31T23:59:59Z",
                "creators": ["Tool: esp-idf-sbom-1.2.0"],
            },
            "packages": package_values,
            "relationships": relationships,
            "hasExtractedLicensingInfos": list(extracted.values()),
        }


def spdx22_tag_value_from_document(document: dict) -> str:
    """Render the subset emitted by esp-idf-sbom 1.2.0 for audit fixtures."""

    packages = document["packages"]
    if not packages:
        raise AssertionError("tag/value fixture requires packages")
    lines = [
        "# Generated by esp-idf-sbom 1.2.0",
        "",
        "# SPDX document for project %s" % document["name"],
        "SPDXVersion: SPDX-2.2",
        "DataLicense: %s" % document["dataLicense"],
        "SPDXID: %s" % document["SPDXID"],
        "DocumentName: %s" % document["name"],
        "DocumentNamespace: %s" % document["documentNamespace"],
        "Creator: Tool: ESP-IDF SBOM builder",
        "Created: %s" % document["creationInfo"]["created"],
        "CreatorComment: <text>Generated by the pinned offline tool.",
        "This deliberately spans two lines.</text>",
        "Relationship: SPDXRef-DOCUMENT DESCRIBES %s" % packages[0]["SPDXID"],
    ]
    for index, package in enumerate(packages):
        lines.extend(
            [
                "",
                "# package %s" % package["name"],
                "PackageName: %s" % package["name"],
                "SPDXID: %s" % package["SPDXID"],
                "PackageVersion: %s" % package["versionInfo"],
                "PackageDownloadLocation: %s" % package["downloadLocation"],
                "FilesAnalyzed: false",
                "PackageLicenseConcluded: NOASSERTION",
                "PackageLicenseDeclared: NOASSERTION",
                "PackageCopyrightText: <text>%s</text>" % package["copyrightText"],
                "PackageComment: <text>",
                "fixture-index: %d" % index,
                "source: project_description.json",
                "</text>",
            ]
        )
        if index == 0:
            lines.extend(
                "Relationship: %s DEPENDS_ON %s"
                % (package["SPDXID"], dependency["SPDXID"])
                for dependency in packages[1:]
            )
    return "\n".join(lines) + "\n"


class FakeTagValueSbomRunner(FakeOfflineSbomRunner):
    """Writes realistic SPDX 2.2 tag/value with unresolved raw licenses."""

    def __init__(
        self,
        fixture: ReleaseLicenseFixture,
        *,
        malformed: str | None = None,
        provenance_override: str | None = None,
        extra_package: str | None = None,
    ):
        super().__init__(fixture, extra_package=extra_package)
        self.malformed = malformed
        self.provenance_override = provenance_override
        self.raw_values: list[str] = []

    def __call__(self, argv, **kwargs):
        completed = super().__call__(argv, **kwargs)
        command = [str(item) for item in argv]
        output_path = Path(command[command.index("--output-file") + 1])
        document = json.loads(output_path.read_text(encoding="utf-8"))
        if self.provenance_override is not None:
            package = document["packages"][0]
            if self.provenance_override == "version":
                package["versionInfo"] += "-unreviewed"
            elif self.provenance_override == "source":
                package["downloadLocation"] += "?unreviewed=1"
            elif self.provenance_override == "copyright":
                package["copyrightText"] += " and an unreviewed author"
            else:
                raise AssertionError(
                    "unknown fixture provenance override: %s" % self.provenance_override
                )
        value = spdx22_tag_value_from_document(document)
        if self.malformed == "duplicate-document-field":
            value = value.replace(
                "SPDXVersion: SPDX-2.2\n",
                "SPDXVersion: SPDX-2.2\nSPDXVersion: SPDX-2.2\n",
                1,
            )
        elif self.malformed == "duplicate-package-field":
            first_name = "PackageName: %s\n" % document["packages"][0]["name"]
            value = value.replace(first_name, first_name + first_name, 1)
        elif self.malformed == "relationship":
            value = value.replace(
                "Relationship: SPDXRef-DOCUMENT DESCRIBES "
                + document["packages"][0]["SPDXID"],
                "Relationship: SPDXRef-DOCUMENT DESCRIBES",
                1,
            )
        elif self.malformed == "unterminated-text":
            value = value.replace(
                "This deliberately spans two lines.</text>",
                "This deliberately spans two lines.",
                1,
            )
        elif self.malformed is not None:
            raise AssertionError("unknown malformed fixture: %s" % self.malformed)
        self.raw_values.append(value)
        output_path.write_text(value, encoding="utf-8")
        return completed


def extract_notice(result: object) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("notice", "notices", "third_party_licenses"):
            value = result.get(key)
            if isinstance(value, str):
                return value
    raise AssertionError("audit result must expose the generated notice as text")


def evidence_semantics(evidence_dir: Path) -> dict[str, object]:
    values: dict[str, object] = {}
    for path in sorted(evidence_dir.rglob("*")):
        if path.is_symlink():
            raise AssertionError("review evidence contains symlink: %s" % path)
        if not path.is_file():
            continue
        relative = path.relative_to(evidence_dir).as_posix()
        raw = path.read_text(encoding="utf-8")
        try:
            values[relative] = json.loads(raw)
        except json.JSONDecodeError:
            values[relative] = raw.replace("\r\n", "\n")
    return values


def evidence_semantic_collection(evidence_dir: Path) -> list[str]:
    """Compare review content semantically without freezing evidence filenames."""

    canonical = []
    for value in evidence_semantics(evidence_dir).values():
        if isinstance(value, str):
            canonical.append("text:" + value)
        else:
            canonical.append(
                "json:"
                + json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
    return sorted(canonical)


def combined_evidence_text(evidence_dir: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(evidence_dir.rglob("*"))
        if path.is_file()
    )


def nested_spdx_documents(value: object) -> list[dict]:
    found = []
    if isinstance(value, dict):
        if value.get("spdxVersion") == "SPDX-2.3":
            found.append(value)
        else:
            for child in value.values():
                found.extend(nested_spdx_documents(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(nested_spdx_documents(child))
    return found


def find_policy_records(value: object) -> list[dict]:
    """Find normalized-looking records without freezing the policy root schema."""

    found = []
    if isinstance(value, dict):
        serialized_keys = set(value)
        if (
            any("spdx" in key.lower() for key in serialized_keys)
            and any("license" in key.lower() for key in serialized_keys)
            and any("source" in key.lower() for key in serialized_keys)
        ):
            found.append(value)
        for child in value.values():
            found.extend(find_policy_records(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(find_policy_records(child))
    return found


def join_schema_v2_policy_records(policy: dict) -> list[dict]:
    """Join v2 package reviews to the exact redistributed inputs they resolve."""

    packages = {
        package["id"]: package for package in policy.get("reviewed_packages", [])
    }
    inputs = {
        resolved_input["id"]: resolved_input
        for resolved_input in policy.get("resolved_inputs", [])
    }
    records = []
    for resolution in policy.get("resolutions", []):
        package = packages.get(resolution.get("reviewed_package_id"))
        input_refs = resolution.get("input_refs")
        if package is None or not isinstance(input_refs, list):
            continue
        resolved_inputs = [
            inputs[identifier] for identifier in input_refs if identifier in inputs
        ]
        if len(resolved_inputs) != len(input_refs):
            continue
        records.append(
            {
                "reviewed_package": package,
                "resolution": resolution,
                "resolved_inputs": resolved_inputs,
            }
        )
    return records


def referenced_hashed_files(record: object) -> list[tuple[str, str]]:
    result = []
    if isinstance(record, dict):
        path_value = record.get("path")
        hash_value = record.get("sha256")
        if isinstance(path_value, str) and isinstance(hash_value, str):
            result.append((path_value, hash_value))
        for child in record.values():
            result.extend(referenced_hashed_files(child))
    elif isinstance(record, list):
        for child in record:
            result.extend(referenced_hashed_files(child))
    return result


class RepositoryLicenseAuditInputsTests(unittest.TestCase):
    """Current repository inputs fail independently of the production seam."""

    def test_repository_policy_freezes_hydrated_managed_component_metadata(self):
        policy = json.loads(LICENSE_POLICY.read_text(encoding="utf-8"))
        documents = {
            (document["profile_id"], document["role"]): document
            for document in policy["raw_documents"]
        }

        def raw_package(profile_id: str, spdx_id: str) -> dict:
            return next(
                package
                for package in documents[(profile_id, "application")]["packages"]
                if package["SPDXID"] == spdx_id
            )

        self.assertEqual(
            raw_package(
                "esp32-4mb",
                "SPDXRef-COMPONENT-espressif--lan867x",
            ),
            {
                "SPDXID": "SPDXRef-COMPONENT-espressif--lan867x",
                "copyrightText": (
                    "2023 Espressif Systems (Shanghai) CO LTD\n"
                    "2024 Espressif Systems (Shanghai) CO LTD\n"
                    "2024-2025 Espressif Systems (Shanghai) CO LTD\n"
                    "2025 Espressif Systems (Shanghai) CO LTD"
                ),
                "downloadLocation": (
                    "https://github.com/espressif/esp-eth-drivers/tree/master/"
                    "lan867x"
                ),
                "externalRefs": [
                    {
                        "referenceCategory": "OTHER",
                        "referenceLocator": (
                            "git://github.com/espressif/esp-eth-drivers.git"
                        ),
                        "referenceType": "repository",
                    }
                ],
                "filesAnalyzed": False,
                "licenseConcluded": "Apache-2.0",
                "licenseDeclared": "NOASSERTION",
                "name": "component-espressif__lan867x",
                "summary": "LAN867x Ethernet PHY Driver",
                "supplier": "Organization: Espressif Systems (Shanghai) CO LTD",
                "versionInfo": "1.0.3",
            },
        )

        tinyusb_raw_expression = (
            "Apache-2.0 AND BSD-3-Clause AND MIT AND Unlicense"
        )
        self.assertEqual(
            raw_package(
                "esp32-s3-n16r8",
                "SPDXRef-COMPONENT-espressif--tinyusb",
            ),
            {
                "SPDXID": "SPDXRef-COMPONENT-espressif--tinyusb",
                "copyrightText": (
                    "2020 Diego Elio Pettenò\n"
                    "2022 Espressif Systems (Shanghai) CO LTD\n"
                    "2022-2023 Espressif Systems (Shanghai) CO LTD\n"
                    "2023 Espressif Systems (Shanghai) CO LTD\n"
                    "2025 Espressif Systems (Shanghai) CO LTD"
                ),
                "downloadLocation": "https://docs.tinyusb.org/en/latest/",
                "externalRefs": [
                    {
                        "referenceCategory": "OTHER",
                        "referenceLocator": (
                            "https://github.com/espressif/tinyusb.git"
                        ),
                        "referenceType": "repository",
                    },
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceLocator": (
                            "pkg:github/espressif/tinyusb@v1.28.0"
                        ),
                        "referenceType": "purl",
                    },
                ],
                "filesAnalyzed": False,
                "licenseConcluded": tinyusb_raw_expression,
                "licenseDeclared": "NOASSERTION",
                "name": "component-espressif__tinyusb",
                "originator": "Person: Ha Thach <thach@tinyusb.org>",
                "summary": "TinyUSB ported to Espressif's SoCs",
                "supplier": "Organization: Espressif Systems (Shanghai) CO LTD",
                "versionInfo": "v1.28.0",
            },
        )

        reviewed_tinyusb = next(
            package
            for package in policy["reviewed_packages"]
            if package["dependency"]["name"] == "component-espressif__tinyusb"
        )
        self.assertEqual(
            reviewed_tinyusb["reviewed_raw_package_expression"],
            tinyusb_raw_expression,
        )
        self.assertEqual(reviewed_tinyusb["reviewed_input_expressions"], ["MIT"])
        self.assertEqual(
            {item["spdx_id"] for item in reviewed_tinyusb["license_texts"]},
            {"Apache-2.0", "BSD-3-Clause", "MIT", "Unlicense"},
        )

        project_id = "SPDXRef-PROJECT-micropython"
        base_project_expression = (
            "Apache-2.0 AND BSD-2-Clause-Views AND BSD-3-Clause "
            "AND CC0-1.0 AND ISC AND MIT"
        )
        s3_project_expression = base_project_expression + " AND Unlicense"
        self.assertEqual(
            raw_package("esp32-s3-n16r8", project_id)["licenseConcluded"],
            s3_project_expression,
        )
        self.assertIn(
            "2020 Diego Elio Pettenò",
            raw_package("esp32-s3-n16r8", project_id)["copyrightText"],
        )
        self.assertEqual(
            raw_package("esp32-4mb", project_id)["licenseConcluded"],
            base_project_expression,
        )
        self.assertEqual(
            raw_package("esp32-c3-4mb", project_id)["licenseConcluded"],
            base_project_expression,
        )

        project_resolutions = [
            resolution
            for resolution in policy["resolutions"]
            if any(
                package_ref["spdx_id"] == project_id
                for package_ref in resolution["package_refs"]
            )
        ]
        self.assertEqual(len(project_resolutions), 2)
        resolution_by_profiles = {
            frozenset(
                package_ref["profile_id"]
                for package_ref in resolution["package_refs"]
            ): resolution
            for resolution in project_resolutions
        }
        self.assertEqual(
            resolution_by_profiles[
                frozenset({"esp32-4mb", "esp32-c3-4mb"})
            ]["resolved_input_expression"],
            base_project_expression,
        )
        s3_resolution = resolution_by_profiles[frozenset({"esp32-s3-n16r8"})]
        self.assertEqual(
            s3_resolution["resolved_input_expression"],
            s3_project_expression,
        )
        reviewed_by_id = {
            package["id"]: package for package in policy["reviewed_packages"]
        }
        s3_project_review = reviewed_by_id[s3_resolution["reviewed_package_id"]]
        self.assertEqual(
            s3_project_review["reviewed_raw_package_expression"],
            s3_project_expression,
        )
        self.assertIn(
            "Unlicense",
            {item["spdx_id"] for item in s3_project_review["license_texts"]},
        )

    def test_repository_lock_pins_tool_and_hashes_a_complete_closure(self):
        lock = validate_lock_semantics(
            self,
            RELEASE_TOOLS_LOCK,
            repo_root=REPO_ROOT,
        )
        scalars = set(deep_scalars(lock))
        for required in (
            SBOM_NAME,
            SBOM_VERSION,
            SBOM_WHEEL,
            SBOM_WHEEL_SHA256,
            SBOM_TAG,
            SBOM_COMMIT,
        ):
            self.assertIn(required, scalars)

    def test_repository_excluded_cves_is_empty_and_hash_bound(self):
        self.assertTrue(
            EXCLUDED_CVES.is_file(),
            "committed empty SBOM_EXCLUDED_CVES_FILE is missing",
        )
        payload = "\n".join(
            line.split("#", 1)[0].strip()
            for line in EXCLUDED_CVES.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        )
        self.assertIn(
            payload,
            ("", "{}", "[]", "null", "~"),
            "excluded CVE input is not semantically empty",
        )
        self.assertTrue(RELEASE_TOOLS_LOCK.is_file())
        with RELEASE_TOOLS_LOCK.open("rb") as handle:
            lock = tomllib.load(handle)
        self.assertIn(sha256_path(EXCLUDED_CVES), set(deep_scalars(lock)))

    def test_repository_policy_uses_exact_reviewed_runtime_and_blob_texts(self):
        self.assertTrue(
            LICENSE_POLICY.is_file(),
            "firmware/licenses/license-policy.json is missing",
        )
        policy = json.loads(LICENSE_POLICY.read_text(encoding="utf-8"))
        self.assertIs(type(policy.get("schema_version")), int)
        self.assertEqual(policy["schema_version"], 2)
        records = join_schema_v2_policy_records(policy)
        self.assertTrue(records, "policy has no resolved input records")

        categories = {
            "controller": ("controller",),
            "phy": ("phy",),
            "wifi": ("wi-fi", "wifi"),
            "coexistence": ("coexistence", "coex"),
            "gcc": ("gcc", "libgcc"),
            "newlib": ("newlib",),
        }
        selected: dict[str, dict] = {}
        for category, tokens in categories.items():
            matches = [
                record
                for record in records
                if record["reviewed_package"]["notice"].get("required") is True
                if any(
                    token in json.dumps(record, sort_keys=True).lower()
                    for token in tokens
                )
            ]
            self.assertTrue(
                matches,
                "policy lacks explicit %s input" % category,
            )
            selected[category] = matches[0]

        for category, record in selected.items():
            hashed_files = referenced_hashed_files(record)
            self.assertTrue(
                hashed_files,
                "%s record lacks exact hashed license/NOTICE input" % category,
            )
            reviewed_texts = [
                pair
                for pair in hashed_files
                if pair[0].startswith("firmware/licenses/")
            ]
            self.assertTrue(
                reviewed_texts,
                "%s record lacks a repository-reviewed license/NOTICE file" % category,
            )
            for relative, expected_hash in reviewed_texts:
                self.assertRegex(expected_hash, HEX64)
                path = safe_fixture_path(REPO_ROOT, relative)
                self.assertTrue(path.is_file(), "%s is missing" % relative)
                self.assertEqual(sha256_path(path), expected_hash)
            record_hashes = list(deep_values_for_key(record, "sha256"))
            self.assertGreaterEqual(
                len(record_hashes),
                2,
                "%s record must bind both resolved input and reviewed text" % category,
            )
            self.assertTrue(
                all(
                    isinstance(value, str) and HEX64.fullmatch(value)
                    for value in record_hashes
                )
            )
            serialized = json.dumps(record, sort_keys=True)
            self.assertIn("https://", serialized)
            self.assertIn(
                "notice",
                serialized.lower(),
                "%s policy must state whether NOTICE text is required" % category,
            )
            refs = list(deep_strings_for_key_fragment(record, "ref"))
            refs.extend(deep_strings_for_key_fragment(record, "commit"))
            self.assertTrue(
                any(
                    FULL_COMMIT.fullmatch(candidate.rsplit("@", 1)[-1])
                    for candidate in refs
                ),
                "%s source/ref is not bound to a full commit" % category,
            )
            self.assertNotIn("review-required", serialized.lower())
            self.assertNotIn('"deny"', serialized.lower())
            self.assertIn("application", serialized.lower())

        for category in ("gcc", "newlib"):
            self.assertIn(
                "bootloader",
                json.dumps(selected[category], sort_keys=True).lower(),
                "%s runtime policy omits bootloader applicability" % category,
            )

        gcc = selected["gcc"]
        gcc_serialized = json.dumps(gcc, sort_keys=True)
        self.assertIn("GPL-3.0", gcc_serialized)
        self.assertIn("GCC-exception-3.1", gcc_serialized)
        gcc_texts = [
            safe_fixture_path(REPO_ROOT, relative).read_text(encoding="utf-8")
            for relative, _digest in referenced_hashed_files(gcc)
            if relative.startswith("firmware/licenses/")
        ]
        canonical_gpl = REPO_ROOT / "firmware/licenses/texts/GPL-3.0-or-later.txt"
        self.assertEqual(
            sha256_path(canonical_gpl),
            "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903",
            "the complete GPLv3 text must be byte-faithful to the pinned "
            "toolchain distribution",
        )
        self.assertTrue(
            any(
                "GNU GENERAL PUBLIC LICENSE" in text
                and "Version 3" in text
                and len(text) > 20_000
                for text in gcc_texts
            ),
            "GCC runtime policy needs the complete GPLv3 text",
        )
        self.assertTrue(
            any(
                "GCC RUNTIME LIBRARY EXCEPTION" in text.upper()
                and "3.1" in text
                and len(text) > 1_000
                for text in gcc_texts
            ),
            "GCC runtime policy needs the complete GCC exception text",
        )
        # No SPDX value is guessed here for the reviewed newlib/blob inputs.


class SyntheticFixtureSelfCheckTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ReleaseLicenseFixture()

    def tearDown(self):
        self.fixture.close()

    def test_lock_graph_wheels_and_hashes_are_internally_consistent(self):
        lock = validate_lock_semantics(
            self,
            self.fixture.lock_path,
            repo_root=self.fixture.repo,
            verify_cached_artifacts=True,
        )
        self.assertIn(
            sha256_path(self.fixture.policy_path),
            set(deep_scalars(lock)),
        )
        self.assertIn(
            sha256_path(self.fixture.excluded_cves),
            set(deep_scalars(lock)),
        )
        for artifact in lock["artifacts"]:
            relative = artifact.get("path")
            if relative is None:
                continue
            wheel = safe_fixture_path(self.fixture.repo, relative)
            with zipfile.ZipFile(wheel) as archive:
                names = archive.namelist()
                self.assertTrue(any(name.endswith("/METADATA") for name in names))
                self.assertTrue(any(name.endswith("/WHEEL") for name in names))

    def test_archives_maps_compile_commands_and_roles_are_realistic(self):
        self.assertEqual(len(self.fixture.project_descriptions()), 6)
        identities = {
            self.fixture.identity_for_description(path)
            for path in self.fixture.project_descriptions()
        }
        self.assertEqual(identities, set(PROFILE_ROLES))
        for profile_id, target, _idf_target in PROFILE_TARGETS:
            target_build = self.fixture.build_root / target
            manifest_text = (
                self.fixture.firmware / "board_overlays" / target / "manifest.py"
            ).read_text(encoding="utf-8")
            for required_manifest_input in (
                "flashbdev.py",
                "inisetup.py",
                "extmod/asyncio",
                'require("neopixel")',
                "_boot.py",
                "pyble/pyble_agent.py",
            ):
                self.assertIn(required_manifest_input, manifest_text)
            generated_names = set(
                re.findall(
                    r"^// - frozen file name: (.+)$",
                    (target_build / "frozen_content.c").read_text(encoding="utf-8"),
                    re.MULTILINE,
                )
            )
            self.assertEqual(
                generated_names,
                {
                    "flashbdev.py",
                    "inisetup.py",
                    "asyncio/__init__.py",
                    "asyncio/core.py",
                    "_boot.py",
                    "pyble/pyble_agent.py",
                    "neopixel.py",
                },
            )
            app_map = (target_build / "micropython.map").read_text(encoding="utf-8")
            boot_map = (target_build / "bootloader" / "bootloader.map").read_text(
                encoding="utf-8"
            )
            self.assertIn(
                "Archive member included to satisfy reference by file",
                app_map,
            )
            self.assertIn("libfixture_controller.a(controller.o)", app_map)
            self.assertNotIn("libfixture_controller.a", boot_map)
            self.assertIn("libfixture_boot.a(boot_core.o)", boot_map)
            self.assertNotEqual(app_map, boot_map)
            role_cases = (
                (
                    target_build,
                    target_build / "micropython.map",
                    target_build / "compile_commands.json",
                ),
                (
                    target_build / "bootloader",
                    target_build / "bootloader" / "bootloader.map",
                    target_build / "bootloader" / "compile_commands.json",
                ),
            )
            command_counts = []
            for role_build, map_path, commands_path in role_cases:
                records = map_archive_members(map_path)
                self.assertTrue(records)
                linked_members = []
                for archive, member in records:
                    self.assertTrue(
                        archive.is_file(),
                        "map references missing archive %s" % archive,
                    )
                    self.assertIn(
                        member,
                        parse_ar_members(archive.read_bytes()),
                        "map references missing archive member",
                    )
                    linked_members.append(member)

                description = json.loads(
                    (role_build / "project_description.json").read_text(
                        encoding="utf-8"
                    )
                )
                components = description["build_component_info"]
                commands = json.loads(
                    commands_path.read_text(encoding="utf-8")
                )
                command_counts.append(len(commands))
                for command in commands:
                    directory = Path(command["directory"])
                    self.assertTrue(directory.is_dir())
                    argv = shlex.split(command["command"])
                    self.assertEqual(argv.count("-c"), 1)
                    self.assertEqual(argv.count("-o"), 1)

                    source = Path(command["file"])
                    if not source.is_absolute():
                        source = directory / source
                    compiler_source = Path(argv[argv.index("-c") + 1])
                    if not compiler_source.is_absolute():
                        compiler_source = directory / compiler_source
                    self.assertEqual(source.resolve(), compiler_source.resolve())
                    self.assertTrue(source.is_file())

                    output = Path(command["output"])
                    if not output.is_absolute():
                        output = role_build / output
                    compiler_output = Path(argv[argv.index("-o") + 1])
                    if not compiler_output.is_absolute():
                        compiler_output = directory / compiler_output
                    self.assertEqual(output.resolve(), compiler_output.resolve())
                    self.assertTrue(output.is_file())
                    self.assertFalse(output.is_symlink())
                    self.assertIn(output.name, linked_members)

                    owners = [
                        component
                        for component in components.values()
                        if source.resolve()
                        in {
                            Path(item).resolve()
                            for item in component["sources"]
                            if Path(item).is_file()
                        }
                    ]
                    self.assertEqual(len(owners), 1)
                    owner = owners[0]
                    self.assertIsInstance(owner.get("lib"), str)
                    self.assertTrue(owner["lib"])
                    expected_object_root = (
                        Path(owner["file"]).parent
                        / "CMakeFiles"
                        / ("%s.dir" % owner["lib"])
                    )
                    self.assertTrue(
                        output.resolve().is_relative_to(
                            expected_object_root.resolve()
                        )
                    )

                app_elf = Path(description["app_elf"]).name
                link_path = (
                    role_build
                    / "CMakeFiles"
                    / ("%s.dir" % app_elf)
                    / "link.txt"
                )
                self.assertTrue(link_path.is_file())
                self.assertFalse(link_path.is_symlink())
                link_argv = shlex.split(
                    link_path.read_text(encoding="utf-8")
                )
                self.assertFalse(
                    [
                        value
                        for value in link_argv
                        if value.endswith((".o", ".obj"))
                    ],
                    "the base fixture intentionally has no direct objects",
                )
            self.assertGreater(command_counts[0], command_counts[1])
            for archive in target_build.rglob("*.a"):
                self.assertTrue(parse_ar_members(archive.read_bytes()))

    def test_policy_hashes_paths_applicability_and_expressions_are_valid(self):
        policy = self.fixture.policy()
        approved = set(policy["approved_license_refs"])
        self.assertEqual(
            {entry["id"] for entry in policy["entries"]},
            {
                "fixture-app-core",
                "fixture-boot-core",
                "micropython-runtime",
                "fixture-neopixel",
                "fixture-controller-blob",
                "fixture-phy-blob",
                "fixture-wifi-blob",
                "fixture-coex-blob",
                "fixture-gcc-runtime",
                "fixture-newlib-runtime",
            },
        )
        for entry in policy["entries"]:
            parse_fixture_spdx(entry["spdx_expression"], approved)
            self.assertEqual(entry["disposition"], "allow")
            self.assertTrue(entry["applicability"])
            for relative, expected in referenced_hashed_files(entry):
                path = safe_fixture_path(self.fixture.repo, relative)
                self.assertTrue(path.is_file())
                self.assertEqual(sha256_path(path), expected)
            ref = entry["source"]["ref"]
            self.assertRegex(ref.rsplit("@", 1)[-1], FULL_COMMIT)

        records = self.fixture.policy_by_id()
        app = {
            "%s/%s" % (item["profile_id"], item["role"])
            for item in records["fixture-controller-blob"]["applicability"]
        }
        gcc = {
            "%s/%s" % (item["profile_id"], item["role"])
            for item in records["fixture-gcc-runtime"]["applicability"]
        }
        self.assertEqual(
            app,
            {
                "%s/application" % profile_id
                for profile_id, _target, _idf_target in PROFILE_TARGETS
            },
        )
        self.assertEqual(gcc, set(PROFILE_ROLE_LABELS))
        gcc_paths = {
            Path(item["path"]).name
            for item in records["fixture-gcc-runtime"]["license_texts"]
        }
        self.assertEqual(
            gcc_paths,
            {
                "GPL-3.0-or-later.fixture.txt",
                "GCC-exception-3.1.fixture.txt",
            },
        )

    def test_all_six_spdx_documents_are_valid_distinct_and_role_specific(self):
        runner = FakeOfflineSbomRunner(self.fixture)
        approved = set(self.fixture.policy()["approved_license_refs"])
        documents = {}
        for profile_id, role in PROFILE_ROLES:
            document = runner.spdx_document(profile_id, role)
            validate_spdx_document(
                self,
                document,
                approved_license_refs=approved,
            )
            documents[(profile_id, role)] = document
        self.assertEqual(len(documents), 6)
        for profile_id, _target, _idf_target in PROFILE_TARGETS:
            app_names = {
                item["name"]
                for item in documents[(profile_id, "application")]["packages"]
            }
            boot_names = {
                item["name"]
                for item in documents[(profile_id, "bootloader")]["packages"]
            }
            self.assertIn("Fixture frozen NeoPixel package", app_names)
            self.assertNotIn("Fixture frozen NeoPixel package", boot_names)
            self.assertNotEqual(app_names, boot_names)

    def test_every_mutation_helper_restores_its_fixture_state(self):
        policy_before = self.fixture.policy_path.read_bytes()
        lock_before = self.fixture.lock_path.read_bytes()

        def change_policy(policy):
            policy["entries"][0]["disposition"] = "deny"

        with self.fixture.mutate_policy(change_policy):
            self.assertNotEqual(
                self.fixture.policy_path.read_bytes(),
                policy_before,
            )
        self.assertEqual(self.fixture.policy_path.read_bytes(), policy_before)
        self.assertEqual(self.fixture.lock_path.read_bytes(), lock_before)

        def change_lock(lock):
            lock["tool"]["sha256"] = "0" * 64

        with self.fixture.mutate_lock(change_lock):
            self.assertNotEqual(self.fixture.lock_path.read_bytes(), lock_before)
        self.assertEqual(self.fixture.lock_path.read_bytes(), lock_before)

        source = self.fixture.firmware / "components" / "app_core" / "app_core.c"
        source_before = source.read_bytes()
        with patched_bytes(source, b"temporary replacement\n"):
            self.assertNotEqual(source.read_bytes(), source_before)
        self.assertEqual(source.read_bytes(), source_before)
        with removed_file(source):
            self.assertFalse(source.exists())
        self.assertEqual(source.read_bytes(), source_before)

        mirror = self.fixture.root / "mutation-mirror.c"
        with new_file(mirror, source_before):
            with symlink_instead(source, mirror):
                self.assertTrue(source.is_symlink())
            self.assertFalse(source.is_symlink())
            self.assertEqual(source.read_bytes(), source_before)
        self.assertFalse(mirror.exists())


class ReleaseLicenseAuditProductionGateTest(unittest.TestCase):
    def test_complete_license_audit_entrypoint_exists(self):
        self.assertIsNotNone(RELEASE, RELEASE_LOAD_ERROR)
        if RELEASE is not None:
            self.assertTrue(
                HAS_AUDIT,
                "[BLD-8 red] release_bundle.audit_release_licenses is missing",
            )

    def test_public_cli_requires_explicit_fresh_license_evidence_inputs(self):
        completed = subprocess.run(
            [sys.executable, str(RELEASE_SCRIPT), "validate", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for option in (
            "--license-evidence-dir",
            "--license-build-root",
            "--repo-root",
        ):
            with self.subTest(option=option):
                self.assertIn(option, completed.stdout)

    def test_production_audit_cli_is_explicit_and_candidate_cli_is_unambiguous(self):
        completed = subprocess.run(
            [sys.executable, str(RELEASE_SCRIPT), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("audit-licenses", completed.stdout)
        self.assertIn("candidate-licenses", completed.stdout)
        commands = completed.stdout.split("{", 1)[-1].split("}", 1)[0].split(",")
        self.assertNotIn("licenses", commands)

        audit_help = subprocess.run(
            [sys.executable, str(RELEASE_SCRIPT), "audit-licenses", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(audit_help.returncode, 0, audit_help.stderr)
        for option in (
            "--build-root",
            "--repo-root",
            "--evidence-dir",
            "--wheelhouse",
            "--notice-output",
        ):
            with self.subTest(option=option):
                self.assertIn(option, audit_help.stdout)

    def test_validate_cli_rejects_partial_or_candidate_evidence_arguments(self):
        cases = (
            (
                "public without evidence",
                ["validate", "/missing", "--public"],
                "--license-evidence-dir",
            ),
            (
                "candidate with evidence",
                [
                    "validate",
                    "/missing",
                    "--license-evidence-dir",
                    "/evidence",
                ],
                "--public",
            ),
        )
        for label, arguments, expected in cases:
            with self.subTest(case=label):
                completed = subprocess.run(
                    [sys.executable, str(RELEASE_SCRIPT), *arguments],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(expected, completed.stderr)


@unittest.skipUnless(
    sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file(),
    "production locked-runner success path requires Darwin sandbox-exec",
)
class ProductionLockedWheelRunnerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = LockedRunnerFixture()

    def tearDown(self):
        self.fixture.close()

    def runner(self):
        self.assertTrue(
            HAS_LOCKED_RUNNER,
            "[BLD-8 red] LockedWheelSbomRunner production adapter is missing",
        )
        return RELEASE.LockedWheelSbomRunner(
            repo_root=self.fixture.repo,
            build_root=self.fixture.build_root,
            wheelhouse=self.fixture.wheelhouse,
        )

    def patched_tool_hash(self):
        return mock.patch.object(
            RELEASE,
            "ESP_IDF_SBOM_WHEEL_SHA256",
            self.fixture.top_hash,
        )

    def test_verified_closure_runs_isolated_and_receipts_are_derived(self):
        self.assertTrue(
            HAS_LOCKED_RUNNER,
            "[BLD-8 red] LockedWheelSbomRunner production adapter is missing",
        )
        poisoned = os.environ.copy()
        poisoned.update(
            {
                "DYLD_INSERT_LIBRARIES": "/untrusted/injection.dylib",
                "HTTPS_PROXY": "http://untrusted.invalid:8080",
                "PYTHONHOME": "/untrusted/python",
                "PYTHONPATH": "/untrusted/modules",
                "PYTHONSTARTUP": "/untrusted/startup.py",
            }
        )
        with self.patched_tool_hash():
            with self.runner() as runner:
                completed = runner(
                    self.fixture.command(),
                    cwd=self.fixture.build_root,
                    env=poisoned,
                    check=True,
                    network_disabled=True,
                )
        payload = json.loads(self.fixture.output.read_text(encoding="utf-8"))
        self.assertEqual(payload["marker"], "verified-locked-wheel")
        self.assertEqual(payload["isolated"], 1)
        self.assertEqual(payload["network_errno"], 1)
        self.assertEqual(set(payload["poison"].values()), {None})
        self.assertEqual(
            completed.executed_artifacts,
            self.fixture.artifact_hashes(),
        )
        self.assertTrue(completed.network_isolated)
        identity = completed.execution_identity
        self.assertEqual(identity["runner"], "pyble-locked-wheel-v1")
        self.assertEqual(identity["python"]["implementation"], "cpython")
        self.assertEqual(
            identity["isolation"]["kind"],
            "darwin-sandbox-exec",
        )
        self.assertEqual(
            {
                (
                    item["name"],
                    item["version"],
                    item["filename"],
                    item["sha256"],
                )
                for item in identity["artifacts"]
            },
            {
                (
                    SBOM_NAME,
                    SBOM_VERSION,
                    SBOM_WHEEL,
                    self.fixture.top_hash,
                ),
                (
                    "fixture-dependency",
                    "1.0",
                    self.fixture.dependency.name,
                    sha256_path(self.fixture.dependency),
                ),
            },
        )

    def test_runner_rejects_unisolated_ambient_or_altered_invocation(self):
        with self.patched_tool_hash():
            with self.runner() as runner:
                with self.assertRaises(RELEASE.ReleaseError):
                    runner(
                        self.fixture.command(),
                        cwd=self.fixture.build_root,
                        env={},
                        check=True,
                        network_disabled=False,
                    )
                altered = self.fixture.command()
                altered[2] = "ambient_esp_idf_sbom"
                with self.assertRaises(RELEASE.ReleaseError):
                    runner(
                        altered,
                        cwd=self.fixture.build_root,
                        env={},
                        check=True,
                        network_disabled=True,
                    )
                with self.assertRaises(RELEASE.ReleaseError):
                    runner(
                        self.fixture.command(),
                        cwd=self.fixture.root,
                        env={},
                        check=True,
                        network_disabled=True,
                    )

    def test_missing_extra_tampered_and_symlink_wheels_fail_closed(self):
        self.assertTrue(
            HAS_LOCKED_RUNNER,
            "[BLD-8 red] LockedWheelSbomRunner production adapter is missing",
        )
        mutations = {}

        missing = LockedRunnerFixture()
        missing.dependency.unlink()
        mutations["missing"] = missing

        extra = LockedRunnerFixture()
        make_runner_wheel(
            extra.wheelhouse / "unlocked_extra-9.0-py3-none-any.whl",
            distribution="unlocked-extra",
            version="9.0",
        )
        mutations["extra"] = extra

        tampered = LockedRunnerFixture()
        tampered.dependency.write_bytes(tampered.dependency.read_bytes() + b"tampered")
        mutations["tampered"] = tampered

        symlinked = LockedRunnerFixture()
        outside = symlinked.root / symlinked.dependency.name
        symlinked.dependency.rename(outside)
        symlinked.dependency.symlink_to(outside)
        mutations["symlink"] = symlinked

        try:
            for label, fixture in mutations.items():
                with self.subTest(case=label):
                    with mock.patch.object(
                        RELEASE,
                        "ESP_IDF_SBOM_WHEEL_SHA256",
                        fixture.top_hash,
                    ):
                        with self.assertRaises(RELEASE.ReleaseError):
                            RELEASE.LockedWheelSbomRunner(
                                repo_root=fixture.repo,
                                build_root=fixture.build_root,
                                wheelhouse=fixture.wheelhouse,
                            )
        finally:
            for fixture in mutations.values():
                fixture.close()

    def test_unsafe_metadata_closure_and_platform_wheels_fail_closed(self):
        self.assertTrue(
            HAS_LOCKED_RUNNER,
            "[BLD-8 red] LockedWheelSbomRunner production adapter is missing",
        )
        fixtures = {}

        unsafe = LockedRunnerFixture()
        unsafe.write_lock(dependency_filename="../escape.whl")
        fixtures["unsafe filename"] = unsafe

        metadata = LockedRunnerFixture()
        make_runner_wheel(
            metadata.dependency,
            distribution="wrong-distribution",
            version="1.0",
        )
        metadata.write_lock()
        fixtures["metadata name mismatch"] = metadata

        version = LockedRunnerFixture()
        version.write_lock(dependency_version="2.0")
        fixtures["requirement version mismatch"] = version

        platform_wheel = LockedRunnerFixture()
        incompatible = (
            platform_wheel.wheelhouse
            / "fixture_dependency-1.0-cp999-cp999-macosx_11_0_arm64.whl"
        )
        platform_wheel.dependency.unlink()
        platform_wheel.dependency = incompatible
        make_runner_wheel(
            incompatible,
            distribution="fixture-dependency",
            version="1.0",
            tag="cp999-cp999-macosx_11_0_arm64",
        )
        platform_wheel.write_lock(dependency_filename=incompatible.name)
        fixtures["incompatible platform tag"] = platform_wheel

        try:
            for label, fixture in fixtures.items():
                with self.subTest(case=label):
                    with mock.patch.object(
                        RELEASE,
                        "ESP_IDF_SBOM_WHEEL_SHA256",
                        fixture.top_hash,
                    ):
                        with self.assertRaises(RELEASE.ReleaseError):
                            RELEASE.LockedWheelSbomRunner(
                                repo_root=fixture.repo,
                                build_root=fixture.build_root,
                                wheelhouse=fixture.wheelhouse,
                            )
        finally:
            for fixture in fixtures.values():
                fixture.close()

    def test_missing_or_ineffective_os_isolation_fails_closed(self):
        self.assertTrue(HAS_LOCKED_RUNNER)
        self.assertTrue(
            hasattr(RELEASE, "_audit_network_isolation_prefix"),
            "production adapter lacks a fixed isolation boundary",
        )
        with self.patched_tool_hash():
            with mock.patch.object(
                RELEASE,
                "_audit_network_isolation_prefix",
                side_effect=RELEASE.ReleaseError("no trusted isolator"),
            ):
                with self.assertRaises(RELEASE.ReleaseError):
                    with self.runner():
                        pass


class ProductionAuditPublicationTests(unittest.TestCase):
    def test_locked_audit_entrypoint_publishes_outputs_only_after_success(self):
        self.assertTrue(
            HAS_LOCKED_AUDIT,
            "[BLD-8 red] audit_release_licenses_from_lock is missing",
        )
        with tempfile.TemporaryDirectory(prefix="pyble-locked-publication-") as raw:
            root = Path(raw)
            build = root / "build"
            repo = root / "repo"
            wheelhouse = root / "wheelhouse"
            build.mkdir()
            repo.mkdir()
            wheelhouse.mkdir()
            evidence = root / "evidence"
            notice = root / "THIRD_PARTY_LICENSES.txt"

            class FakeLockedRunner:
                def __init__(self, **_kwargs):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            def successful_audit(*, evidence_dir, **_kwargs):
                evidence_dir.mkdir()
                (evidence_dir / "audit-receipt.json").write_text(
                    "{}\n",
                    encoding="utf-8",
                )
                return {"third_party_licenses": "reviewed notice\n"}

            with mock.patch.object(
                RELEASE,
                "LockedWheelSbomRunner",
                FakeLockedRunner,
            ), mock.patch.object(
                RELEASE,
                "audit_release_licenses",
                successful_audit,
            ):
                RELEASE.audit_release_licenses_from_lock(
                    build_root=build,
                    repo_root=repo,
                    evidence_dir=evidence,
                    wheelhouse=wheelhouse,
                    notice_output=notice,
                )
            self.assertEqual(
                notice.read_text(encoding="utf-8"),
                "reviewed notice\n",
            )
            self.assertTrue((evidence / "audit-receipt.json").is_file())

            failed_evidence = root / "failed-evidence"
            failed_notice = root / "FAILED_THIRD_PARTY_LICENSES.txt"
            with mock.patch.object(
                RELEASE,
                "LockedWheelSbomRunner",
                FakeLockedRunner,
            ), mock.patch.object(
                RELEASE,
                "audit_release_licenses",
                side_effect=RELEASE.ReleaseError("fixture audit failed"),
            ):
                with self.assertRaises(RELEASE.ReleaseError):
                    RELEASE.audit_release_licenses_from_lock(
                        build_root=build,
                        repo_root=repo,
                        evidence_dir=failed_evidence,
                        wheelhouse=wheelhouse,
                        notice_output=failed_notice,
                    )
            self.assertFalse(failed_evidence.exists())
            self.assertFalse(failed_notice.exists())

    def test_locked_audit_publication_never_replaces_a_concurrent_destination(
        self,
    ):
        self.assertTrue(HAS_LOCKED_AUDIT)
        with tempfile.TemporaryDirectory(
            prefix="pyble-locked-publication-race-"
        ) as raw:
            root = Path(raw)
            build = root / "build"
            repo = root / "repo"
            wheelhouse = root / "wheelhouse"
            build.mkdir()
            repo.mkdir()
            wheelhouse.mkdir()
            evidence = root / "evidence"
            notice = root / "THIRD_PARTY_LICENSES.txt"

            class FakeLockedRunner:
                def __init__(self, **_kwargs):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            def racing_audit(*, evidence_dir, **_kwargs):
                evidence_dir.mkdir()
                (evidence_dir / "audit-receipt.json").write_text(
                    "{}\n",
                    encoding="utf-8",
                )
                evidence.mkdir()
                (evidence / "contender.txt").write_text(
                    "do not replace\n",
                    encoding="utf-8",
                )
                return {"third_party_licenses": "reviewed notice\n"}

            with mock.patch.object(
                RELEASE,
                "LockedWheelSbomRunner",
                FakeLockedRunner,
            ), mock.patch.object(
                RELEASE,
                "audit_release_licenses",
                racing_audit,
            ):
                with self.assertRaises(RELEASE.ReleaseError):
                    RELEASE.audit_release_licenses_from_lock(
                        build_root=build,
                        repo_root=repo,
                        evidence_dir=evidence,
                        wheelhouse=wheelhouse,
                        notice_output=notice,
                    )

            self.assertEqual(
                (evidence / "contender.txt").read_text(encoding="utf-8"),
                "do not replace\n",
            )
            self.assertFalse(notice.exists())


@unittest.skipUnless(
    HAS_AUDIT,
    "SPDX 2.2 tag/value behavior waits for audit_release_licenses",
)
@unittest.skip(
    "schema-v1 fixture superseded by schema-v2 policy integration tests"
)
class Spdx22TagValueAuditTests(unittest.TestCase):
    # Schema-v2 migration map:
    # - exact raw bytes, normalized documents, and receipt filenames:
    #   ObservePolicyV2InputsTests.
    #   test_audit_consumes_v2_observations_and_normalizes_reviewed_raw_docs
    # - malformed tag/value singleton/text handling:
    #   PolicyV2AuditMigrationTests.
    #   test_v2_audit_rejects_malformed_tag_value_singletons_and_text
    # - unresolved/mismatched raw provenance and extra packages:
    #   PolicyV2FailClosedTests.
    #   test_exact_raw_package_properties_and_relationship_multisets and
    #   test_raw_reviewed_and_redistributed_expressions_are_separate
    def setUp(self):
        self.fixture = ReleaseLicenseFixture()

    def tearDown(self):
        self.fixture.close()

    def run_audit(self, runner: FakeTagValueSbomRunner):
        if self.fixture.evidence.exists():
            shutil.rmtree(self.fixture.evidence)
        self.fixture.evidence.mkdir()
        return RELEASE.audit_release_licenses(
            build_root=self.fixture.build_root,
            repo_root=self.fixture.repo,
            evidence_dir=self.fixture.evidence,
            runner=runner,
        )

    def assert_rejected(self, runner: FakeTagValueSbomRunner) -> None:
        with self.assertRaises(RELEASE.ReleaseError):
            self.run_audit(runner)

    def test_real_spdx22_tag_value_is_converted_and_exact_policy_resolves_it(self):
        runner = FakeTagValueSbomRunner(self.fixture)
        result = self.run_audit(runner)
        notice = extract_notice(result)

        self.assertEqual(len(runner.calls), len(PROFILE_ROLES))
        self.assertEqual(len(runner.raw_values), len(PROFILE_ROLES))
        for raw_value in runner.raw_values:
            self.assertIn("SPDXVersion: SPDX-2.2\n", raw_value)
            self.assertIn("Creator: Tool: ESP-IDF SBOM builder\n", raw_value)
            self.assertIn("PackageLicenseDeclared: NOASSERTION\n", raw_value)
            self.assertIn("PackageComment: <text>\n", raw_value)
            self.assertIn(
                "Relationship: SPDXRef-DOCUMENT DESCRIBES ",
                raw_value,
            )
            self.assertIn(" DEPENDS_ON ", raw_value)

        raw_paths = sorted((self.fixture.evidence / "raw").glob("*.spdx.tag"))
        self.assertEqual(len(raw_paths), len(PROFILE_ROLES))
        self.assertEqual(
            Counter(path.read_text(encoding="utf-8") for path in raw_paths),
            Counter(runner.raw_values),
            "raw tag/value bytes must be retained without normalization",
        )
        policy = self.fixture.policy()
        expected_licenses = {
            entry["dependency"]["name"]: entry["spdx_expression"]
            for entry in policy["entries"]
        }
        approved = set(policy["approved_license_refs"])
        spdx_paths = sorted((self.fixture.evidence / "spdx").glob("*.spdx.json"))
        self.assertEqual(len(spdx_paths), len(PROFILE_ROLES))
        for path in spdx_paths:
            with self.subTest(evidence=path.name):
                document = json.loads(path.read_text(encoding="utf-8"))
                validate_spdx_document(
                    self,
                    document,
                    approved_license_refs=approved,
                )
                self.assertEqual(
                    document["creationInfo"].get("comment"),
                    (
                        "Generated by the pinned offline tool.\n"
                        "This deliberately spans two lines."
                    ),
                )
                for package in document["packages"]:
                    self.assertEqual(
                        package["licenseDeclared"],
                        expected_licenses[package["name"]],
                    )
                    self.assertRegex(
                        package.get("comment", ""),
                        (
                            r"^\nfixture-index: \d+\n"
                            r"source: project_description\.json\n$"
                        ),
                    )
                self.assertIn(
                    "DEPENDS_ON",
                    {
                        relationship["relationshipType"]
                        for relationship in document["relationships"]
                    },
                )

        self.assertNotIn("NOASSERTION", notice)
        self.assertNotIn("NONE", notice)
        reviewed_text = "\n".join(
            path.read_text(encoding="utf-8") for path in spdx_paths
        )
        self.assertNotIn("NOASSERTION", reviewed_text)
        self.assertNotIn("NONE", reviewed_text)
        raw_text = "\n".join(path.read_text(encoding="utf-8") for path in raw_paths)
        self.assertIn("NOASSERTION", raw_text)

        receipt = json.loads(
            (self.fixture.evidence / "audit-receipt.json").read_text(encoding="utf-8")
        )
        expected_paths = {
            "%s/%s--%s.%s"
            % (
                directory,
                profile_id,
                role,
                extension,
            )
            for profile_id, role in PROFILE_ROLES
            for directory, extension in (
                ("raw", "spdx.tag"),
                ("spdx", "spdx.json"),
            )
        }
        self.assertEqual(set(receipt["evidence_sha256"]), expected_paths)
        for relative, digest in receipt["evidence_sha256"].items():
            self.assertEqual(
                sha256_path(self.fixture.evidence / relative),
                digest,
            )

    def test_duplicate_singletons_and_malformed_tag_value_fail_closed(self):
        for malformed in (
            "duplicate-document-field",
            "duplicate-package-field",
            "relationship",
            "unterminated-text",
        ):
            with self.subTest(malformed=malformed):
                self.assert_rejected(
                    FakeTagValueSbomRunner(
                        self.fixture,
                        malformed=malformed,
                    )
                )

    def test_raw_noassertion_without_exact_reviewed_provenance_fails_closed(self):
        for provenance_override in ("version", "source", "copyright"):
            with self.subTest(provenance=provenance_override):
                self.assert_rejected(
                    FakeTagValueSbomRunner(
                        self.fixture,
                        provenance_override=provenance_override,
                    )
                )
        self.assert_rejected(
            FakeTagValueSbomRunner(
                self.fixture,
                extra_package="fixture-unmapped-package",
            )
        )


@unittest.skipUnless(
    HAS_AUDIT,
    "deep BLD-8 behavior waits for audit_release_licenses",
)
@unittest.skip(
    "schema-v1 fixture superseded by schema-v2 policy integration tests"
)
class ReleaseLicenseAuditBehaviorTests(unittest.TestCase):
    # Schema-v2 migration map:
    # - complete sorted notices, runner receipts, exact descriptions,
    #   deterministic evidence, review-file hashes, and public promotion:
    #   PolicyV2AuditMigrationTests in
    #   test_release_license_policy_v2_integration.py
    # - descriptions/maps/generated archives/opaque inputs/toolchains:
    #   ObservePolicyV2InputsTests in that module
    # - exact raw graph coverage, expressions, many-to-many input ownership,
    #   supplemental packages, and policy ambiguity:
    #   PolicyV2FailClosedTests in test_release_license_policy_v2.py
    # - symlink/path/source/receipt hardening:
    #   PolicyV2HardeningTests in
    #   test_release_license_policy_v2_hardening.py
    #
    # Keeping this obsolete fixture executable would be actively misleading:
    # every negative test would pass at the schema-version check without
    # reaching the behavior named by the test.
    def setUp(self):
        self.fixture = ReleaseLicenseFixture()

    def tearDown(self):
        self.fixture.close()

    def run_audit(
        self,
        fixture: ReleaseLicenseFixture | None = None,
        runner: FakeOfflineSbomRunner | None = None,
    ) -> tuple[str, object, FakeOfflineSbomRunner]:
        fixture = fixture or self.fixture
        if fixture.evidence.exists():
            shutil.rmtree(fixture.evidence)
        fixture.evidence.mkdir()
        runner = runner or FakeOfflineSbomRunner(fixture)
        result = RELEASE.audit_release_licenses(
            build_root=fixture.build_root,
            repo_root=fixture.repo,
            evidence_dir=fixture.evidence,
            runner=runner,
        )
        notice = extract_notice(result)
        self.assertTrue(notice.endswith("\n"))
        self.assertTrue(
            any(path.is_file() for path in fixture.evidence.rglob("*")),
            "audit retained no review evidence",
        )
        return notice, result, runner

    def assert_rejected(
        self,
        *,
        fixture: ReleaseLicenseFixture | None = None,
        runner: FakeOfflineSbomRunner | None = None,
    ) -> None:
        fixture = fixture or self.fixture
        if fixture.evidence.exists():
            shutil.rmtree(fixture.evidence)
        fixture.evidence.mkdir()
        runner = runner or FakeOfflineSbomRunner(fixture)
        with self.assertRaises(RELEASE.ReleaseError):
            RELEASE.audit_release_licenses(
                build_root=fixture.build_root,
                repo_root=fixture.repo,
                evidence_dir=fixture.evidence,
                runner=runner,
            )

    def make_public_bundle(self, notice: str):
        spec = importlib.util.spec_from_file_location(
            "pyble_release_bundle_fixture_for_bld8_extra",
            RELEASE_BUNDLE_TEST,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(spec.name, None)
        bundle_fixture = module.ReleaseFixture()
        bundle = bundle_fixture.make_bundle(public=True)
        (bundle / "THIRD_PARTY_LICENSES.txt").write_text(
            notice,
            encoding="utf-8",
        )
        bundle_fixture.refresh_declared_hashes()
        return bundle_fixture, bundle

    def test_notice_systematically_contains_every_field_and_complete_text(self):
        notice, _result, _runner = self.run_audit()
        self.assertNotIn(CANDIDATE_MARKER, notice)
        self.assertNotIn("esp-web-tools", notice.lower())
        self.assertNotIn("website_third_party_licenses", notice.lower())
        for frozen_upstream in (
            "flashbdev.py",
            "inisetup.py",
            "asyncio",
            "NeoPixel",
        ):
            self.assertIn(frozen_upstream, notice)
        policy = self.fixture.policy()
        for entry in policy["entries"]:
            dependency = entry["dependency"]
            for field in (
                dependency["name"],
                dependency["version_ref"],
                dependency["source_url"],
                dependency["copyright"],
                entry["spdx_expression"],
            ):
                with self.subTest(entry=entry["id"], field=field):
                    self.assertIn(field, notice)
            notice_record = entry["notice"]
            if notice_record["required"]:
                required_text = (
                    safe_fixture_path(
                        self.fixture.repo,
                        notice_record["path"],
                    )
                    .read_text(encoding="utf-8")
                    .rstrip()
                )
                self.assertIn(required_text, notice)
            for applicability in entry["applicability"]:
                profile_id = applicability["profile_id"]
                role = applicability["role"]
                alternatives = (
                    "%s/%s" % (profile_id, role),
                    "%s:%s" % (profile_id, role),
                    "%s (%s)" % (profile_id, role),
                )
                self.assertTrue(
                    any(value in notice for value in alternatives),
                    "notice lacks profile/role annotation %s/%s" % (profile_id, role),
                )
        sorted_names = sorted(
            entry["dependency"]["name"] for entry in policy["entries"]
        )
        self.assertEqual(
            [notice.index(name) for name in sorted_names],
            sorted(notice.index(name) for name in sorted_names),
            "dependency union is not sorted by stable dependency name",
        )

        unique_texts = {}
        for entry in policy["entries"]:
            for record in entry["license_texts"]:
                text = (
                    safe_fixture_path(
                        self.fixture.repo,
                        record["path"],
                    )
                    .read_text(encoding="utf-8")
                    .rstrip()
                )
                unique_texts.setdefault(record["sha256"], text)
        for digest, complete_text in unique_texts.items():
            with self.subTest(complete_text_sha256=digest):
                self.assertEqual(
                    notice.count(complete_text),
                    1,
                    "identical complete text is not deduplicated by hash",
                )

    def test_tool_runs_offline_from_the_complete_locked_hash_receipt(self):
        _notice, _result, runner = self.run_audit()
        self.assertEqual(len(runner.calls), 6)
        receipt = json.loads(
            (self.fixture.evidence / "audit-receipt.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            receipt.get("execution_identity"),
            runner.execution_identity,
        )
        descriptions = []
        for call in runner.calls:
            command = call["argv"]
            self.assertTrue(call["check"])
            self.assertTrue(call["network_disabled"])
            normalized_command = " ".join(command).lower().replace("-", "_")
            self.assertIn("esp_idf_sbom", normalized_command)
            self.assertIn("create", normalized_command)
            for flag in ("--rem-unused", "--rem-config", "--file-tags"):
                self.assertEqual(command.count(flag), 1)
            for forbidden_flag in (
                "--add-unused-deps",
                "--add-config-deps",
                "--add-unused",
                "--add-config",
            ):
                self.assertNotIn(forbidden_flag, command)
            self.assertIn("--output-file", command)
            matched = [
                Path(value).resolve()
                for value in command
                if value.endswith("project_description.json")
            ]
            self.assertEqual(len(matched), 1)
            descriptions.extend(matched)
            env = call["env"]
            self.assertEqual(
                Path(env["SBOM_EXCLUDED_CVES_FILE"]).resolve(),
                self.fixture.excluded_cves.resolve(),
            )
            for key in ("HOME", "XDG_CACHE_HOME", "PIP_CACHE_DIR"):
                temporary = Path(env[key]).resolve()
                self.assertFalse(
                    temporary.is_relative_to(self.fixture.evidence.resolve())
                )
                self.assertFalse(temporary.is_relative_to(self.fixture.repo.resolve()))
                self.assertFalse(
                    temporary.is_relative_to(self.fixture.build_root.resolve())
                )
        self.assertEqual(
            set(descriptions),
            {path.resolve() for path in self.fixture.project_descriptions()},
        )
        for temporary in runner.temporary_paths:
            self.assertFalse(
                temporary.exists(),
                "isolated home/cache was retained after the audit",
            )
        evidence_names = {
            part.lower()
            for path in self.fixture.evidence.rglob("*")
            for part in path.relative_to(self.fixture.evidence).parts
        }
        self.assertTrue(
            evidence_names.isdisjoint(
                {"home", ".cache", "pip-cache", "xdg-cache", "wheelhouse"}
            )
        )

        wrong = self.fixture.lock_artifact_hashes()
        wrong[SBOM_NAME] = "0" * 64
        self.assert_rejected(
            runner=FakeOfflineSbomRunner(
                self.fixture,
                executed_artifacts=wrong,
            )
        )
        extra = self.fixture.lock_artifact_hashes()
        extra["unlocked-fixture"] = "f" * 64
        self.assert_rejected(
            runner=FakeOfflineSbomRunner(
                self.fixture,
                executed_artifacts=extra,
            )
        )
        self.assert_rejected(
            runner=FakeOfflineSbomRunner(
                self.fixture,
                network_isolated=False,
            )
        )
        collision = self.fixture.lock_artifact_hashes()
        collision["esp_idf_sbom"] = collision[SBOM_NAME]
        self.assert_rejected(
            runner=FakeOfflineSbomRunner(
                self.fixture,
                executed_artifacts=collision,
            )
        )

    def test_lock_hash_artifact_and_graph_mutations_fail_closed(self):
        def wrong_top(lock):
            lock["tool"]["sha256"] = "0" * 64
            for artifact in lock["artifacts"]:
                if canonical_package_name(artifact["name"]) == SBOM_NAME:
                    artifact["sha256"] = "0" * 64

        with self.fixture.mutate_lock(wrong_top):
            self.assert_rejected()

        cached = (
            self.fixture.firmware
            / "release-tool-fixtures"
            / "fixture_expression-2.0-py3-none-any.whl"
        )
        with patched_bytes(cached, cached.read_bytes() + b"tampered"):
            self.assert_rejected()

        for label, pinned_input in (
            ("excluded CVEs", self.fixture.excluded_cves),
            ("license policy", self.fixture.policy_path),
        ):
            with self.subTest(changed_pinned_input=label):
                with patched_bytes(
                    pinned_input,
                    pinned_input.read_bytes() + b"\n",
                ):
                    self.assert_rejected()

        def missing_transitive(lock):
            lock["artifacts"] = [
                item
                for item in lock["artifacts"]
                if canonical_package_name(item["name"]) != "fixture-transitive"
            ]

        with self.fixture.mutate_lock(missing_transitive):
            matching_runner = FakeOfflineSbomRunner(self.fixture)
            self.assert_rejected(runner=matching_runner)

        def unreachable_extra(lock):
            lock["artifacts"].append(
                {
                    "name": "fixture-unreachable",
                    "version": "9.0",
                    "filename": "fixture_unreachable-9.0-py3-none-any.whl",
                    "sha256": "e" * 64,
                    "requires": [],
                }
            )

        with self.fixture.mutate_lock(unreachable_extra):
            matching_runner = FakeOfflineSbomRunner(self.fixture)
            self.assert_rejected(runner=matching_runner)

    def test_each_description_is_required_and_spdx_identity_cannot_swap(self):
        self.run_audit()
        for description in self.fixture.project_descriptions():
            with self.subTest(missing=description):
                with removed_file(description):
                    self.assert_rejected()
        role_inputs = []
        for _profile_id, target, _idf_target in PROFILE_TARGETS:
            target_build = self.fixture.build_root / target
            role_inputs.extend(
                [
                    target_build / "micropython.map",
                    target_build / "compile_commands.json",
                    target_build / "bootloader" / "bootloader.map",
                    target_build / "bootloader" / "compile_commands.json",
                ]
            )
        for role_input in role_inputs:
            with self.subTest(missing_role_input=role_input):
                with removed_file(role_input):
                    self.assert_rejected()
        for mode in ("rotate", "duplicate"):
            with self.subTest(identity_mode=mode):
                self.assert_rejected(
                    runner=FakeOfflineSbomRunner(
                        self.fixture,
                        identity_mode=mode,
                    )
                )

    def test_maps_archive_members_and_compile_sources_reconcile_exactly(self):
        self.run_audit()
        target = self.fixture.build_root / "esp32"
        map_path = target / "micropython.map"
        baseline_map = map_path.read_text(encoding="utf-8")
        known_archive = target / "esp-idf" / "app_core" / "libfixture_app.a"

        unknown_archive = target / "libfixture_unknown.a"
        with new_file(
            unknown_archive,
            make_ar_bytes([("unknown.o", b"unknown object\n")]),
        ):
            with patched_text(
                map_path,
                baseline_map
                + "libfixture_unknown.a(unknown.o)\n"
                + "                              (unknown_symbol)\n",
            ):
                self.assert_rejected()

        with patched_text(
            map_path,
            baseline_map
            + "esp-idf/app_core/libfixture_app.a(missing.o)\n"
            + "                              (missing_symbol)\n",
        ):
            self.assert_rejected()

        commands_path = target / "compile_commands.json"
        commands = json.loads(commands_path.read_text(encoding="utf-8"))
        ambiguous_source = self.fixture.firmware / "components" / "app_core" / "other.c"
        duplicate = copy.deepcopy(commands[0])
        duplicate["file"] = str(ambiguous_source)
        with new_file(
            ambiguous_source,
            b"// SPDX-License-Identifier: MIT\n",
        ):
            with patched_text(
                commands_path,
                json.dumps(commands + [duplicate], indent=2) + "\n",
            ):
                self.assert_rejected()

        unrelated_source = self.fixture.root / "unrelated-source.c"
        rewritten = copy.deepcopy(commands)
        rewritten[0]["file"] = str(unrelated_source)
        rewritten[0]["command"] = rewritten[0]["command"].replace(
            commands[0]["file"],
            str(unrelated_source),
        )
        with new_file(
            unrelated_source,
            b"// SPDX-License-Identifier: MIT\n",
        ):
            with patched_text(
                commands_path,
                json.dumps(rewritten, indent=2) + "\n",
            ):
                self.assert_rejected()

        members = parse_ar_members(known_archive.read_bytes())
        changed_archive = make_ar_bytes(
            [
                (
                    name,
                    value + b"changed" if name == "app_core.o" else value,
                )
                for name, value in members.items()
            ]
        )
        with patched_bytes(known_archive, changed_archive):
            self.assert_rejected()

        outside_archive = self.fixture.root / "outside.a"
        with new_file(
            outside_archive,
            make_ar_bytes([("escape.o", b"escape\n")]),
        ):
            with patched_text(
                map_path,
                baseline_map
                + "../../outside.a(escape.o)\n"
                + "                              (escape_symbol)\n",
            ):
                self.assert_rejected()

        mirror = self.fixture.root / "mirrored-known.a"
        with new_file(mirror, known_archive.read_bytes()):
            with symlink_instead(known_archive, mirror):
                self.assert_rejected()

    def test_policy_ambiguity_paths_refs_dispositions_and_text_hashes_fail(self):
        def duplicate_record(policy):
            policy["entries"].append(copy.deepcopy(policy["entries"][0]))

        with self.fixture.mutate_policy(duplicate_record):
            self.assert_rejected()

        for replacement in (
            "../outside-license.txt",
            str(self.fixture.root / "absolute-license.txt"),
        ):

            def unsafe_path(policy, replacement=replacement):
                policy["entries"][0]["license_texts"][0]["path"] = replacement

            with self.subTest(policy_path=replacement):
                with self.fixture.mutate_policy(unsafe_path):
                    self.assert_rejected()

        def mutable_ref(policy):
            policy["entries"][0]["source"]["ref"] = "main"
            policy["entries"][0]["dependency"]["version_ref"] = "latest"

        with self.fixture.mutate_policy(mutable_ref):
            self.assert_rejected()

        for disposition in ("deny", "review-required"):

            def changed_disposition(policy, disposition=disposition):
                policy["entries"][0]["disposition"] = disposition

            with self.subTest(disposition=disposition):
                with self.fixture.mutate_policy(changed_disposition):
                    self.assert_rejected()

        records = self.fixture.policy_by_id()
        license_path = safe_fixture_path(
            self.fixture.repo,
            records["fixture-app-core"]["license_texts"][0]["path"],
        )
        notice_path = safe_fixture_path(
            self.fixture.repo,
            records["fixture-controller-blob"]["notice"]["path"],
        )
        for label, path in (
            ("license", license_path),
            ("notice", notice_path),
        ):
            with self.subTest(kind=label, mutation="changed"):
                with patched_bytes(path, path.read_bytes() + b"changed\n"):
                    self.assert_rejected()
            with self.subTest(kind=label, mutation="missing"):
                with removed_file(path):
                    self.assert_rejected()

        outside = self.fixture.root / "outside-license-copy.txt"
        with new_file(outside, license_path.read_bytes()):
            with symlink_instead(license_path, outside):
                self.assert_rejected()

        outside_directory = self.fixture.root / "outside-license-directory"
        outside_nested = outside_directory / "MIT.txt"
        linked_directory = self.fixture.licenses / "linked-texts"
        with new_file(outside_nested, license_path.read_bytes()):
            with new_symlink(linked_directory, outside_directory):

                def intermediate_symlink(policy):
                    record = policy["entries"][0]["license_texts"][0]
                    record["path"] = "firmware/licenses/linked-texts/MIT.txt"
                    record["sha256"] = sha256_path(outside_nested)

                with self.fixture.mutate_policy(intermediate_symlink):
                    self.assert_rejected()

        source = (
            self.fixture.firmware
            / "upstream"
            / "micropython"
            / "lib"
            / "micropython-lib"
            / "micropython"
            / "drivers"
            / "led"
            / "neopixel"
            / "neopixel.py"
        )
        with patched_bytes(source, source.read_bytes() + b"# changed\n"):
            self.assert_rejected()

    def test_spdx_is_parsed_and_unknown_states_fail_closed(self):
        notice, _result, _runner = self.run_audit()
        self.assertIn("MIT OR BSD-2-Clause", notice)
        self.assertIn("LicenseRef-PyBLE-Test-Controller", notice)
        for expression in (
            "NOASSERTION",
            "NONE",
            "MIT OR (Apache-2.0 AND Mystery-9.9)",
            "MIT AND (Apache-2.0",
            "MIT OR LicenseRef-Not-Reviewed",
        ):

            def changed_expression(policy, expression=expression):
                policy["entries"][0]["spdx_expression"] = expression

            with self.subTest(expression=expression):
                with self.fixture.mutate_policy(changed_expression):
                    # The fake reads the changed policy, so SBOM and policy
                    # agree. Rejection therefore requires real SPDX parsing.
                    self.assert_rejected()

        def remove_approval(policy):
            policy["approved_license_refs"].remove("LicenseRef-PyBLE-Test-Controller")

        with self.fixture.mutate_policy(remove_approval):
            self.assert_rejected()

        self.assert_rejected(
            runner=FakeOfflineSbomRunner(
                self.fixture,
                license_override="MIT",
            )
        )

    def test_frozen_manifest_generated_inventory_and_neopixel_are_exact(self):
        notice, _result, _runner = self.run_audit()
        self.assertIn("Fixture frozen NeoPixel package", notice)
        for _profile_id, target, _idf_target in PROFILE_TARGETS:
            manifest = self.fixture.firmware / "board_overlays" / target / "manifest.py"
            frozen = self.fixture.build_root / target / "frozen_content.c"
            manifest_before = manifest.read_text(encoding="utf-8")
            manifest_lines = (
                'module("flashbdev.py", base_path="$(PORT_DIR)/modules")\n',
                'module("inisetup.py", base_path="$(PORT_DIR)/modules")\n',
                'include("$(MPY_DIR)/extmod/asyncio")\n',
                'require("neopixel")\n',
                'module("_boot.py", base_path="$(BOARD_DIR)")\n',
                ('module("pyble/pyble_agent.py", ' 'base_path="$(BOARD_DIR)")\n'),
            )
            for manifest_line in manifest_lines:
                self.assertIn(manifest_line, manifest_before)
                with self.subTest(
                    target=target,
                    manifest_missing=manifest_line.strip(),
                ):
                    with patched_text(
                        manifest,
                        manifest_before.replace(manifest_line, "", 1),
                    ):
                        self.assert_rejected()

            frozen_before = frozen.read_text(encoding="utf-8")
            for frozen_name in (
                "flashbdev.py",
                "inisetup.py",
                "asyncio/__init__.py",
                "asyncio/core.py",
                "_boot.py",
                "pyble/pyble_agent.py",
                "neopixel.py",
            ):
                with self.subTest(
                    target=target,
                    generated_missing=frozen_name,
                ):
                    changed = "\n".join(
                        line
                        for line in frozen_before.splitlines()
                        if frozen_name not in line
                    )
                    with patched_text(frozen, changed + "\n"):
                        self.assert_rejected()

            for label, path, changed in (
                (
                    "manifest-only extra",
                    manifest,
                    manifest_before + 'freeze("fixture", "only_manifest.py")\n',
                ),
                (
                    "generated-only extra",
                    frozen,
                    frozen_before + "// - frozen file name: only_generated.py\n",
                ),
            ):
                with self.subTest(target=target, case=label):
                    with patched_text(path, changed):
                        self.assert_rejected()

    def test_blobs_and_runtime_are_exact_role_specific_policy_inputs(self):
        notice, _result, _runner = self.run_audit()
        records = self.fixture.policy_by_id()
        required = (
            "fixture-controller-blob",
            "fixture-phy-blob",
            "fixture-wifi-blob",
            "fixture-coex-blob",
            "fixture-gcc-runtime",
            "fixture-newlib-runtime",
        )
        for identifier in required:
            entry = records[identifier]
            self.assertIn(entry["dependency"]["name"], notice)
            self.assertIn(entry["spdx_expression"], notice)
            for text_record in entry["license_texts"]:
                complete = (
                    safe_fixture_path(
                        self.fixture.repo,
                        text_record["path"],
                    )
                    .read_text(encoding="utf-8")
                    .rstrip()
                )
                self.assertIn(complete, notice)

            def without(policy, identifier=identifier):
                policy["entries"] = [
                    item for item in policy["entries"] if item["id"] != identifier
                ]

            with self.subTest(missing_policy=identifier):
                with self.fixture.mutate_policy(without):
                    self.assert_rejected()

        gcc = records["fixture-gcc-runtime"]
        self.assertEqual(
            gcc["spdx_expression"],
            "GPL-3.0-or-later WITH GCC-exception-3.1",
        )
        self.assertEqual(len(gcc["license_texts"]), 2)
        for identifier in (
            "fixture-controller-blob",
            "fixture-phy-blob",
            "fixture-wifi-blob",
            "fixture-coex-blob",
        ):
            roles = {item["role"] for item in records[identifier]["applicability"]}
            self.assertEqual(roles, {"application"})
        self.assertEqual(
            {item["role"] for item in records["fixture-gcc-runtime"]["applicability"]},
            {"application", "bootloader"},
        )
        # The test intentionally reads, but never guesses, newlib/blob SPDX.

    def test_unmapped_sbom_package_fails_closed(self):
        self.assert_rejected(
            runner=FakeOfflineSbomRunner(
                self.fixture,
                extra_package="fixture-unmapped-package",
            )
        )

    def test_normalized_review_evidence_is_semantically_deterministic(self):
        second = ReleaseLicenseFixture()
        try:
            first_notice, _first_result, first_runner = self.run_audit(
                self.fixture,
                FakeOfflineSbomRunner(
                    self.fixture,
                    reverse_packages=False,
                ),
            )
            second_notice, _second_result, second_runner = self.run_audit(
                second,
                FakeOfflineSbomRunner(
                    second,
                    reverse_packages=True,
                ),
            )
            first_semantics = evidence_semantics(self.fixture.evidence)
            second_semantics = evidence_semantics(second.evidence)
            first_reviewed = {
                path: value
                for path, value in first_semantics.items()
                if path.startswith("spdx/")
            }
            second_reviewed = {
                path: value
                for path, value in second_semantics.items()
                if path.startswith("spdx/")
            }
            self.assertEqual(first_notice, second_notice)
            self.assertEqual(first_reviewed, second_reviewed)

            reviewed_serialized = first_notice + "\n" + json.dumps(
                first_reviewed,
                sort_keys=True,
            )
            for forbidden in (
                str(self.fixture.root),
                str(second.root),
                "2099-12-31T23:59:59Z",
            ):
                self.assertNotIn(forbidden, reviewed_serialized)
            self.assertIn("documentNamespace", reviewed_serialized)
            spdx_documents = nested_spdx_documents(first_reviewed)
            self.assertGreaterEqual(
                len(spdx_documents),
                6,
                "all six normalized SPDX inventories must be retained",
            )
            self.assertEqual(
                {document.get("name") for document in spdx_documents},
                {"PyBLE fixture %s/%s" % identity for identity in PROFILE_ROLES},
            )
            approved = set(self.fixture.policy()["approved_license_refs"])
            for document in spdx_documents:
                validate_spdx_document(
                    self,
                    document,
                    approved_license_refs=approved,
                )
            normalized_namespaces = list(
                deep_values_for_key(
                    first_reviewed,
                    "documentNamespace",
                )
            )
            self.assertTrue(normalized_namespaces)
            self.assertEqual(
                len(set(normalized_namespaces)),
                6,
                "normalized SPDX namespaces must remain identity-unique",
            )
            for namespace in normalized_namespaces:
                self.assertIsInstance(namespace, str)
            first_raw = json.dumps(
                {
                    path: value
                    for path, value in first_semantics.items()
                    if path.startswith("raw/")
                },
                sort_keys=True,
            )
            second_raw = json.dumps(
                {
                    path: value
                    for path, value in second_semantics.items()
                    if path.startswith("raw/")
                },
                sort_keys=True,
            )
            self.assertEqual(len(first_runner.raw_namespaces), 6)
            self.assertEqual(len(second_runner.raw_namespaces), 6)
            for raw_namespace in first_runner.raw_namespaces:
                self.assertIn(raw_namespace, first_raw)
                self.assertNotIn(raw_namespace, reviewed_serialized)
            for raw_namespace in second_runner.raw_namespaces:
                self.assertIn(raw_namespace, second_raw)
                self.assertNotIn(raw_namespace, reviewed_serialized)
            self.assertIn(str(self.fixture.root), first_raw)
            self.assertIn("2099-12-31T23:59:59Z", first_raw)

            for profile_id, role in PROFILE_ROLES:
                evidence = combined_evidence_text(self.fixture.evidence)
                self.assertIn(profile_id, evidence)
                self.assertIn(role, evidence)
            for runner in (first_runner, second_runner):
                for temporary in runner.temporary_paths:
                    self.assertFalse(temporary.exists())
            self.assertNotIn("2099-12-31", first_notice)
            self.assertIsNone(UUID_PATTERN.search(first_notice))
        finally:
            second.close()

    def test_public_validation_is_bound_to_fresh_exact_review_evidence(self):
        notice, _result, _runner = self.run_audit()
        spec = importlib.util.spec_from_file_location(
            "pyble_release_bundle_fixture_for_bld8",
            RELEASE_BUNDLE_TEST,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        bundle_fixture = module.ReleaseFixture()
        try:
            bundle = bundle_fixture.make_bundle(public=True)
            # A plausible marker-free hand-written notice is not audit proof.
            with self.assertRaises(RELEASE.ReleaseError):
                RELEASE.validate_bundle(bundle, public=True)
            with self.assertRaises(RELEASE.ReleaseError):
                RELEASE.validate_bundle(
                    bundle,
                    public=True,
                    license_evidence_dir=self.fixture.evidence,
                    license_build_root=self.fixture.build_root,
                    repo_root=self.fixture.repo,
                )

            notice_path = bundle / "THIRD_PARTY_LICENSES.txt"
            notice_path.write_text(notice, encoding="utf-8")
            bundle_fixture.refresh_declared_hashes()
            self.assertIsNotNone(
                RELEASE.validate_bundle(
                    bundle,
                    public=True,
                    license_evidence_dir=self.fixture.evidence,
                    license_build_root=self.fixture.build_root,
                    repo_root=self.fixture.repo,
                )
            )

            with patched_bytes(
                notice_path,
                notice_path.read_bytes() + b"tampered\n",
            ):
                bundle_fixture.refresh_declared_hashes()
                with self.assertRaises(RELEASE.ReleaseError):
                    RELEASE.validate_bundle(
                        bundle,
                        public=True,
                        license_evidence_dir=self.fixture.evidence,
                        license_build_root=self.fixture.build_root,
                        repo_root=self.fixture.repo,
                    )
            notice_path.write_text(notice, encoding="utf-8")
            bundle_fixture.refresh_declared_hashes()

            stale_inputs = (
                self.fixture.build_root / "esp32" / "project_description.json",
                self.fixture.build_root / "esp32" / "micropython.map",
                self.fixture.build_root / "esp32-s3" / "compile_commands.json",
                self.fixture.build_root / "esp32-c3" / "frozen_content.c",
                self.fixture.excluded_cves,
                self.fixture.policy_path,
                self.fixture.lock_path,
            )
            for source_input in stale_inputs:
                with self.subTest(stale_review_input=source_input):
                    with patched_bytes(
                        source_input,
                        source_input.read_bytes() + b"\n",
                    ):
                        with self.assertRaises(RELEASE.ReleaseError):
                            RELEASE.validate_bundle(
                                bundle,
                                public=True,
                                license_evidence_dir=self.fixture.evidence,
                                license_build_root=self.fixture.build_root,
                                repo_root=self.fixture.repo,
                            )

            evidence_file = next(
                path for path in self.fixture.evidence.rglob("*") if path.is_file()
            )
            with patched_bytes(
                evidence_file,
                evidence_file.read_bytes() + b"\n",
            ):
                with self.assertRaises(RELEASE.ReleaseError):
                    RELEASE.validate_bundle(
                        bundle,
                        public=True,
                        license_evidence_dir=self.fixture.evidence,
                        license_build_root=self.fixture.build_root,
                        repo_root=self.fixture.repo,
                    )

            identity_files = {}
            for profile_id in ("esp32-4mb", "esp32-c3-4mb"):
                identity_files[profile_id] = next(
                    (
                        path
                        for path in self.fixture.evidence.rglob("*")
                        if path.is_file()
                        and profile_id in path.read_text(encoding="utf-8")
                    ),
                    None,
                )
                self.assertIsNotNone(
                    identity_files[profile_id],
                    "review evidence does not bind %s" % profile_id,
                )
            left = identity_files["esp32-4mb"]
            right = identity_files["esp32-c3-4mb"]
            if left == right:
                identity_text = left.read_text(encoding="utf-8")
                swapped = (
                    identity_text.replace(
                        "esp32-4mb",
                        "__PROFILE_SWAP__",
                        1,
                    )
                    .replace("esp32-c3-4mb", "esp32-4mb", 1)
                    .replace("__PROFILE_SWAP__", "esp32-c3-4mb", 1)
                )
                mutation = patched_text(left, swapped)
            else:
                mutation = swapped_file_bytes(left, right)
            with mutation:
                with self.assertRaises(RELEASE.ReleaseError):
                    RELEASE.validate_bundle(
                        bundle,
                        public=True,
                        license_evidence_dir=self.fixture.evidence,
                        license_build_root=self.fixture.build_root,
                        repo_root=self.fixture.repo,
                    )
        finally:
            bundle_fixture.cleanup()

    def test_public_validation_rejects_an_evidence_root_symlink(self):
        notice, _result, _runner = self.run_audit()
        bundle_fixture, bundle = self.make_public_bundle(notice)
        real_evidence = self.fixture.root / "real-review-evidence"
        try:
            self.fixture.evidence.rename(real_evidence)
            self.fixture.evidence.symlink_to(real_evidence, target_is_directory=True)
            with self.assertRaises(RELEASE.ReleaseError):
                RELEASE.validate_bundle(
                    bundle,
                    public=True,
                    license_evidence_dir=self.fixture.evidence,
                    license_build_root=self.fixture.build_root,
                    repo_root=self.fixture.repo,
                )
        finally:
            bundle_fixture.cleanup()

    def test_public_validation_semantically_revalidates_retained_spdx(self):
        notice, _result, _runner = self.run_audit()
        bundle_fixture, bundle = self.make_public_bundle(notice)
        try:
            spdx_path = (
                self.fixture.evidence / "spdx" / "esp32-4mb--application.spdx.json"
            )
            document = json.loads(spdx_path.read_text(encoding="utf-8"))
            document["packages"][0]["licenseDeclared"] = "NOASSERTION"
            document["packages"][0]["licenseConcluded"] = "NOASSERTION"
            write_json(spdx_path, document)

            receipt_path = self.fixture.evidence / "audit-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            relative = spdx_path.relative_to(self.fixture.evidence).as_posix()
            receipt["evidence_sha256"][relative] = sha256_path(spdx_path)
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=False) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(RELEASE.ReleaseError):
                RELEASE.validate_bundle(
                    bundle,
                    public=True,
                    license_evidence_dir=self.fixture.evidence,
                    license_build_root=self.fixture.build_root,
                    repo_root=self.fixture.repo,
                )
        finally:
            bundle_fixture.cleanup()

    def test_public_validation_requires_exact_raw_and_reviewed_evidence_filenames(self):
        notice, _result, _runner = self.run_audit()
        bundle_fixture, bundle = self.make_public_bundle(notice)
        try:
            original = (
                self.fixture.evidence / "spdx" / "esp32-c3-4mb--bootloader.spdx.json"
            )
            renamed = original.with_name("renamed-valid-looking.spdx.json")
            original.rename(renamed)
            receipt_path = self.fixture.evidence / "audit-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            original_key = original.relative_to(self.fixture.evidence).as_posix()
            renamed_key = renamed.relative_to(self.fixture.evidence).as_posix()
            receipt["evidence_sha256"][renamed_key] = receipt["evidence_sha256"].pop(
                original_key
            )
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=False) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(RELEASE.ReleaseError):
                RELEASE.validate_bundle(
                    bundle,
                    public=True,
                    license_evidence_dir=self.fixture.evidence,
                    license_build_root=self.fixture.build_root,
                    repo_root=self.fixture.repo,
                )
        finally:
            bundle_fixture.cleanup()


@unittest.skipUnless(
    RELEASE is not None,
    "real-format audit regressions wait for release_bundle.py",
)
class RealFormatLicenseAuditRegressionTests(unittest.TestCase):
    def test_pinned_literal_manifests_resolve_exact_frozen_destinations(self):
        expected = {
            "flashbdev.py",
            "inisetup.py",
            "asyncio/__init__.py",
            "asyncio/core.py",
            "asyncio/event.py",
            "asyncio/funcs.py",
            "asyncio/lock.py",
            "asyncio/stream.py",
            "uasyncio.py",
            "neopixel.py",
            "_boot.py",
            "pyble/__init__.py",
            "pyble/pyble_ble.py",
            "pyble/pyble_proto.py",
        }
        with tempfile.TemporaryDirectory(prefix="pyble-real-manifest-red-") as raw:
            frozen = Path(raw) / "frozen_content.c"
            frozen.write_text(
                "\n".join(
                    "// - frozen file name: %s" % name for name in sorted(expected)
                )
                + "\n",
                encoding="utf-8",
            )
            actual = RELEASE._audit_manifest_inventory(
                REPO_ROOT / "firmware" / "board_overlays" / "esp32" / "manifest.py",
                frozen,
                repo_root=REPO_ROOT,
                target="esp32",
            )
        self.assertEqual(actual, expected)

    def test_manifest_parser_rejects_unrecognized_or_dynamic_selection(self):
        with tempfile.TemporaryDirectory(prefix="pyble-manifest-dsl-red-") as raw:
            root = Path(raw)
            board = root / "firmware" / "board_overlays" / "fixture"
            board.mkdir(parents=True)
            (board / "safe.py").write_text(
                "# SPDX-License-Identifier: MIT\n",
                encoding="utf-8",
            )
            manifest = board / "manifest.py"
            manifest.write_text(
                'module("safe.py", base_path="$(BOARD_DIR)")\n'
                'custom_freeze("silently-ignored.py")\n',
                encoding="utf-8",
            )
            frozen = root / "frozen_content.c"
            frozen.write_text(
                "// - frozen file name: safe.py\n",
                encoding="utf-8",
            )
            with self.assertRaises(RELEASE.ReleaseError):
                RELEASE._audit_manifest_inventory(
                    manifest,
                    frozen,
                    repo_root=root,
                    target="fixture",
                )

    def test_duplicate_archive_member_basenames_preserve_occurrence_counts(self):
        with tempfile.TemporaryDirectory(prefix="pyble-ar-multiset-red-") as raw:
            root = Path(raw)
            archive = root / "libduplicate.a"
            archive.write_bytes(
                make_ar_bytes(
                    [
                        ("shared.o", b"first object"),
                        ("shared.o", b"second object"),
                    ]
                )
            )
            self.assertEqual(
                RELEASE._audit_ar_members(archive),
                Counter({"shared.o": 2}),
            )

            map_path = root / "link.map"
            map_path.write_text(
                "%s(shared.o)\n%s(shared.o)\n" % (archive, archive),
                encoding="utf-8",
            )
            self.assertEqual(
                RELEASE._audit_map_archives(
                    map_path,
                    repo_root=root,
                    build_root=root,
                ),
                [(archive, "shared.o"), (archive, "shared.o")],
            )
            map_path.write_text(
                "%s(shared.o)\n%s(shared.o)\n%s(shared.o)\n"
                % (archive, archive, archive),
                encoding="utf-8",
            )
            with self.assertRaises(RELEASE.ReleaseError):
                RELEASE._audit_map_archives(
                    map_path,
                    repo_root=root,
                    build_root=root,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
