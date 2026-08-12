#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Pure release boundary for v0.6.0 C3 and Pico qualification results.

Physical runners own device access, operator interaction, and detailed bench
evidence.  This standard-library-only module admits a deliberately small,
canonical result which binds the exact candidate and says only that every
frozen profile gate passed.  It returns the equally small public summary; no
device identity, operator input, INFO response, or console bytes can enter a
release through this boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any


class QualificationError(RuntimeError):
    """The private result or its release binding is invalid."""


RESULT_SCHEMA_VERSION = 1
SUMMARY_SCHEMA_VERSION = 1
MAX_RESULT_BYTES = 64 * 1024
C3_PROFILE_ID = "esp32-c3-4mb"
PICO_PROFILE_ID = "rpi-pico2-w"
_GATES_BY_PROFILE = {
    C3_PROFILE_ID: tuple("C3-G%d" % index for index in range(7)),
    PICO_PROFILE_ID: ("GP0", "GP1", "GP2"),
}
_ARTIFACT_BY_PROFILE = {
    C3_PROFILE_ID: ("firmware.bin", "candidate_firmware_sha256"),
    PICO_PROFILE_ID: ("firmware.uf2", "candidate_uf2_sha256"),
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SEMVER_IDENTIFIER = r"(?:0|[1-9][0-9]*|[A-Za-z-][0-9A-Za-z-]*)"
_SEMVER_BUILD_IDENTIFIER = r"[0-9A-Za-z-]+"
_SEMVER_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    r"(?:-" + _SEMVER_IDENTIFIER + r"(?:\." + _SEMVER_IDENTIFIER + r")*)?"
    r"(?:\+" + _SEMVER_BUILD_IDENTIFIER + r"(?:\." + _SEMVER_BUILD_IDENTIFIER + r")*)?$"
)
_BASE_KEYS = {
    "schema_version",
    "status",
    "profile_id",
    "firmware_version",
    "candidate_release_json_sha256",
    "gates",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationError(message)


def _exact_dict(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == keys, "%s shape changed" % label)
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return the frozen private-result representation."""

    try:
        text = json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise QualificationError("qualification result is not canonical JSON") from exc
    return (text + "\n").encode("utf-8")


def _reject_constant(value: str) -> None:
    raise QualificationError("qualification result contains non-JSON %s" % value)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationError("qualification result duplicates a JSON key")
        result[key] = value
    return result


def _strict_json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except QualificationError:
        raise
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise QualificationError(
            "qualification result is not strict UTF-8 JSON"
        ) from exc
    _require(type(value) is dict, "qualification result must be a JSON object")
    _require(raw == canonical_json_bytes(value), "qualification result is not canonical")
    return value


def _stable_regular_bytes(
    path: Path,
    *,
    label: str,
    maximum: int,
    exclusive: bool,
) -> tuple[bytes, tuple[int, ...]]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(os.fspath(Path(path)), flags)
    except OSError as exc:
        raise QualificationError("%s is missing or unsafe" % label) from exc
    try:
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode), "%s must be a regular file" % label)
        if exclusive:
            _require(
                before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600,
                "%s must be one exclusive mode-0600 regular file" % label,
            )
        _require(0 < before.st_size <= maximum, "%s size is outside its bound" % label)
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            raw = stream.read(maximum + 1)
            stream.seek(0)
            repeated = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    _require(
        len(raw) == before.st_size
        and raw == repeated
        and all(getattr(before, key) == getattr(after, key) for key in fields),
        "%s changed while it was read" % label,
    )
    return raw, tuple(getattr(before, key) for key in fields)


def private_result_snapshot(path: Path) -> tuple[Any, ...]:
    """Bind one private input's file identity and exact bytes."""

    raw, identity = _stable_regular_bytes(
        Path(path),
        label="qualification result",
        maximum=MAX_RESULT_BYTES,
        exclusive=True,
    )
    return identity + (hashlib.sha256(raw).hexdigest(),)


def _artifact_digest(path: Path, expected_name: str) -> str:
    artifact = Path(path)
    _require(
        artifact.name == expected_name,
        "candidate artifact must be named %s" % expected_name,
    )
    raw, _identity = _stable_regular_bytes(
        artifact,
        label="candidate %s" % expected_name,
        maximum=64 * 1024 * 1024,
        exclusive=False,
    )
    return hashlib.sha256(raw).hexdigest()


def _validate_expected_inputs(
    expected_profile_id: str,
    expected_version: str,
    candidate_release_json_sha256: str,
) -> tuple[tuple[str, ...], str, str]:
    _require(
        expected_profile_id in _GATES_BY_PROFILE,
        "expected qualification profile is unsupported",
    )
    _require(
        type(expected_version) is str
        and _SEMVER_RE.fullmatch(expected_version) is not None,
        "expected firmware version is invalid",
    )
    _require(
        type(candidate_release_json_sha256) is str
        and _SHA256_RE.fullmatch(candidate_release_json_sha256) is not None,
        "candidate release digest is invalid",
    )
    expected_name, digest_key = _ARTIFACT_BY_PROFILE[expected_profile_id]
    return _GATES_BY_PROFILE[expected_profile_id], expected_name, digest_key


def _validate_common(
    value: Any,
    *,
    expected_profile_id: str,
    expected_version: str,
    candidate_release_json_sha256: str,
    artifact_sha256: str,
    public: bool,
) -> dict[str, Any]:
    gate_names, _expected_name, digest_key = _validate_expected_inputs(
        expected_profile_id,
        expected_version,
        candidate_release_json_sha256,
    )
    expected_keys = set(_BASE_KEYS) | {digest_key}
    if public:
        expected_keys.add("qualification_result_sha256")
    item = _exact_dict(
        value,
        expected_keys,
        "public qualification summary" if public else "private qualification result",
    )
    _require(
        type(item["schema_version"]) is int
        and item["schema_version"]
        == (SUMMARY_SCHEMA_VERSION if public else RESULT_SCHEMA_VERSION)
        and item["status"] == "passed"
        and item["profile_id"] == expected_profile_id
        and item["firmware_version"] == expected_version,
        "qualification identity changed",
    )
    _require(
        item["candidate_release_json_sha256"] == candidate_release_json_sha256,
        "qualification candidate-release binding changed",
    )
    _require(
        type(item[digest_key]) is str
        and _SHA256_RE.fullmatch(item[digest_key]) is not None
        and item[digest_key] == artifact_sha256,
        "qualification candidate artifact binding changed",
    )
    gates = _exact_dict(
        item["gates"],
        set(gate_names),
        "%s qualification gates" % expected_profile_id,
    )
    _require(
        all(gates[name] == "passed" for name in gate_names),
        "qualification profile gates are incomplete",
    )
    if public:
        # Private bytes never enter the bundle, so replay cannot recompute this
        # digest.  Exact recomputation happens while the private mode-0600 file
        # is open at finalization; public replay retains only the canonical,
        # non-placeholder receipt plus candidate/artifact/gate bindings.
        _require(
            type(item["qualification_result_sha256"]) is str
            and _SHA256_RE.fullmatch(item["qualification_result_sha256"]) is not None
            and item["qualification_result_sha256"] != "0" * 64,
            "qualification result digest changed",
        )
    return item


def validate_result_file(
    result_path: Path,
    *,
    artifact_path: Path,
    expected_profile_id: str,
    expected_version: str,
    candidate_release_json_sha256: str,
) -> dict[str, Any]:
    """Validate one private result and derive its non-private public summary."""

    gate_names, expected_name, digest_key = _validate_expected_inputs(
        expected_profile_id,
        expected_version,
        candidate_release_json_sha256,
    )
    del gate_names
    raw, _identity = _stable_regular_bytes(
        Path(result_path),
        label="qualification result",
        maximum=MAX_RESULT_BYTES,
        exclusive=True,
    )
    artifact_sha256 = _artifact_digest(Path(artifact_path), expected_name)
    value = _validate_common(
        _strict_json(raw),
        expected_profile_id=expected_profile_id,
        expected_version=expected_version,
        candidate_release_json_sha256=candidate_release_json_sha256,
        artifact_sha256=artifact_sha256,
        public=False,
    )
    summary = dict(value)
    summary[digest_key] = artifact_sha256
    summary["qualification_result_sha256"] = hashlib.sha256(raw).hexdigest()
    return summary


def validate_public_summary(
    value: Any,
    *,
    artifact_path: Path,
    expected_profile_id: str,
    expected_version: str,
    candidate_release_json_sha256: str,
) -> dict[str, Any]:
    """Revalidate the exact derived summary stored in a public V5 report."""

    _gate_names, expected_name, _digest_key = _validate_expected_inputs(
        expected_profile_id,
        expected_version,
        candidate_release_json_sha256,
    )
    artifact_sha256 = _artifact_digest(Path(artifact_path), expected_name)
    return _validate_common(
        value,
        expected_profile_id=expected_profile_id,
        expected_version=expected_version,
        candidate_release_json_sha256=candidate_release_json_sha256,
        artifact_sha256=artifact_sha256,
        public=True,
    )


__all__ = (
    "C3_PROFILE_ID",
    "PICO_PROFILE_ID",
    "QualificationError",
    "canonical_json_bytes",
    "private_result_snapshot",
    "validate_public_summary",
    "validate_result_file",
)
