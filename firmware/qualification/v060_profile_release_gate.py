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

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable


class QualificationError(RuntimeError):
    """The private result or its release binding is invalid."""


RESULT_SCHEMA_VERSION = 1
SUMMARY_SCHEMA_VERSION = 1
RECEIPT_SCHEMA_VERSION = 1
MAX_RESULT_BYTES = 64 * 1024
C3_PROFILE_ID = "esp32-c3-4mb"
PICO_PROFILE_ID = "rpi-pico2-w"
# Frozen C3 post-OI NVS raw-slice identity (ports/esp32-c3-4mb.md): the only
# passing capture is the fully erased partition at the frozen geometry.
C3_NVS_PARTITION_OFFSET = 0x9000
C3_NVS_PARTITION_SIZE = 0x6000
C3_POST_OI_NVS_SLICE_SHA256 = (
    "1df8949b2e345ab8c00cb81fb6b83686e20a4080f969e5cd8b8d520a07cdaba2"
)
C3_POST_OI_NVS_RESET_SAMPLES = 10
_POST_OI_NVS_BINDING_KEYS = {"receipt_sha256", "receipt_size_bytes", "summary"}
_POST_OI_NVS_SUMMARY_KEYS = {
    "schema_version",
    "profile_id",
    "candidate_release_json_sha256",
    "candidate_firmware_sha256",
    "oi1_raw_sha256",
    "reset_samples",
    "partition_offset",
    "partition_size",
    "nvs_slice_sha256",
    "nvs_slice_size_bytes",
    "acquisition_log_sha256",
    "acquisition_log_size_bytes",
    "integrity",
    "written_namespaces",
}
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
_CANDIDATE_PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
    "waveshare-esp32-s3-lcd-147b",
    C3_PROFILE_ID,
    PICO_PROFILE_ID,
)
_ESP_PROFILE_METADATA = {
    "esp32-4mb": {
        "target": "esp32",
        "chip_family": "ESP32",
        "silicon_revision": {"minimum_full": 0, "maximum_full": 399},
        "flash_size_bytes": 4 * 1024 * 1024,
        "psram": {"required": False, "size_bytes": 0, "type": "not-required"},
        "frequency_hz": 40_000_000,
        "install_offset": 0x1000,
        "component_offsets": (0x1000, 0x8000, 0x10000),
    },
    "esp32-s3-n16r8": {
        "target": "esp32-s3",
        "chip_family": "ESP32-S3",
        "silicon_revision": {"minimum_full": 0, "maximum_full": 99},
        "flash_size_bytes": 16 * 1024 * 1024,
        "psram": {"required": True, "size_bytes": 8 * 1024 * 1024, "type": "octal"},
        "frequency_hz": 80_000_000,
        "install_offset": 0,
        "component_offsets": (0, 0x8000, 0x10000),
    },
    "waveshare-esp32-s3-lcd-147b": {
        "target": "waveshare-esp32-s3-lcd-147b",
        "chip_family": "ESP32-S3",
        "silicon_revision": {"minimum_full": 0, "maximum_full": 99},
        "flash_size_bytes": 16 * 1024 * 1024,
        "psram": {"required": True, "size_bytes": 8 * 1024 * 1024, "type": "octal"},
        "frequency_hz": 80_000_000,
        "install_offset": 0,
        "component_offsets": (0, 0x8000, 0x10000),
    },
    C3_PROFILE_ID: {
        "target": "esp32-c3",
        "chip_family": "ESP32-C3",
        "silicon_revision": {"minimum_full": 3, "maximum_full": 199},
        "flash_size_bytes": 4 * 1024 * 1024,
        "psram": {"required": False, "size_bytes": 0, "type": "not-required"},
        "frequency_hz": 80_000_000,
        "install_offset": 0,
        "component_offsets": (0, 0x8000, 0x10000),
    },
}
_COMPONENTS = (
    ("bootloader", "bootloader.bin"),
    ("partition-table", "partition-table.bin"),
    ("application", "application.bin"),
)
_DOCUMENT_PATHS = {
    "third_party_licenses": "THIRD_PARTY_LICENSES.txt",
    "release_notes": "RELEASE_NOTES.md",
    "recovery": "RECOVERY.md",
    "hil_report": "HIL_REPORT.md",
}
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_FILE_ID_FIELDS = (
    "st_dev",
    "st_ino",
    "st_mode",
    "st_nlink",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
)


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


def post_oi_nvs_evidence_paths(result_path: Path) -> dict[str, Path]:
    """Frozen sibling layout binding one C3 result to its evidence trio.

    Completion and finalization never accept operator-chosen evidence paths;
    the receipt, raw NVS slice, and acquisition log live beside the private
    result under these derived names so every stage reopens the same files.
    """

    result = Path(result_path)
    base = result.stem + "-post-oi-nvs"
    return {
        "post_oi_nvs_receipt_path": result.with_name(base + ".json"),
        "post_oi_nvs_slice_path": result.with_name(base + "-slice.bin"),
        "post_oi_nvs_acquisition_log_path": result.with_name(
            base + "-acquisition.log"
        ),
    }


def _validate_c3_post_oi_nvs_slice_bytes(raw: bytes) -> str:
    """Admit only the exact fully erased C3 NVS partition slice."""

    _require(
        type(raw) is bytes,
        "C3 post-OI NVS slice must be raw bytes",
    )
    _require(
        len(raw) == C3_NVS_PARTITION_SIZE,
        "C3 post-OI NVS slice must be exactly %d bytes" % C3_NVS_PARTITION_SIZE,
    )
    _require(
        raw == b"\xff" * C3_NVS_PARTITION_SIZE,
        "C3 post-OI NVS slice is not the fully erased partition",
    )
    digest = hashlib.sha256(raw).hexdigest()
    _require(
        digest == C3_POST_OI_NVS_SLICE_SHA256,
        "C3 post-OI NVS slice digest changed",
    )
    return digest


def _validate_post_oi_nvs_summary(
    value: Any,
    *,
    candidate_release_json_sha256: str,
    artifact_sha256: str,
) -> dict[str, Any]:
    """Validate one candidate-bound C3 post-OI NVS receipt summary."""

    summary = _exact_dict(
        value,
        _POST_OI_NVS_SUMMARY_KEYS,
        "C3 post-OI NVS summary",
    )
    _require(
        type(summary["schema_version"]) is int
        and summary["schema_version"] == RECEIPT_SCHEMA_VERSION
        and summary["profile_id"] == C3_PROFILE_ID
        and summary["integrity"] == "passed",
        "C3 post-OI NVS summary identity changed",
    )
    _require(
        summary["candidate_release_json_sha256"] == candidate_release_json_sha256,
        "C3 post-OI NVS candidate-release binding changed",
    )
    _require(
        summary["candidate_firmware_sha256"] == artifact_sha256,
        "C3 post-OI NVS candidate-firmware binding changed",
    )
    _require(
        type(summary["oi1_raw_sha256"]) is str
        and _SHA256_RE.fullmatch(summary["oi1_raw_sha256"]) is not None
        and summary["oi1_raw_sha256"] != "0" * 64,
        "C3 post-OI NVS raw-log binding is invalid",
    )
    _require(
        type(summary["reset_samples"]) is int
        and summary["reset_samples"] == C3_POST_OI_NVS_RESET_SAMPLES,
        "C3 post-OI NVS reset-sample count changed",
    )
    _require(
        type(summary["partition_offset"]) is int
        and summary["partition_offset"] == C3_NVS_PARTITION_OFFSET
        and type(summary["partition_size"]) is int
        and summary["partition_size"] == C3_NVS_PARTITION_SIZE,
        "C3 post-OI NVS partition geometry changed",
    )
    _require(
        summary["nvs_slice_sha256"] == C3_POST_OI_NVS_SLICE_SHA256
        and type(summary["nvs_slice_size_bytes"]) is int
        and summary["nvs_slice_size_bytes"] == C3_NVS_PARTITION_SIZE,
        "C3 post-OI NVS slice binding changed",
    )
    _require(
        type(summary["acquisition_log_sha256"]) is str
        and _SHA256_RE.fullmatch(summary["acquisition_log_sha256"]) is not None
        and type(summary["acquisition_log_size_bytes"]) is int
        and summary["acquisition_log_size_bytes"] > 0,
        "C3 post-OI NVS acquisition-log binding is invalid",
    )
    _require(
        summary["written_namespaces"] == [],
        "C3 post-OI NVS capture recorded written namespaces",
    )
    return summary


def _expected_post_oi_nvs_receipt_bytes(summary: dict[str, Any]) -> bytes:
    """A passing slice is fully erased, so the canonical inventory is empty."""

    return canonical_json_bytes({"summary": summary, "inventory": []})


def _reopen_c3_post_oi_nvs_evidence(
    receipt_path: Path | None,
    slice_path: Path | None,
    acquisition_log_path: Path | None,
    *,
    candidate_release_json_sha256: str,
    artifact_sha256: str,
) -> dict[str, Any]:
    """Reopen and re-hash the exclusive C3 evidence trio; trust no summary.

    Every digest and byte length is re-derived from the reopened bytes and
    the raw slice is re-verified against its exact fully erased identity, so
    a hand-written receipt or result can never substitute copied claims.
    """

    _require(
        receipt_path is not None
        and slice_path is not None
        and acquisition_log_path is not None,
        "C3 qualification requires the post-OI NVS receipt, raw slice, "
        "and acquisition log",
    )
    receipt_raw, _receipt_identity = _stable_regular_bytes(
        Path(receipt_path),
        label="C3 post-OI NVS receipt",
        maximum=MAX_RESULT_BYTES,
        exclusive=True,
    )
    slice_raw, _slice_identity = _stable_regular_bytes(
        Path(slice_path),
        label="C3 post-OI NVS raw slice",
        maximum=C3_NVS_PARTITION_SIZE,
        exclusive=True,
    )
    log_raw, _log_identity = _stable_regular_bytes(
        Path(acquisition_log_path),
        label="C3 post-OI NVS acquisition log",
        maximum=MAX_RESULT_BYTES,
        exclusive=True,
    )
    slice_digest = _validate_c3_post_oi_nvs_slice_bytes(slice_raw)
    receipt = _exact_dict(
        _strict_json(receipt_raw),
        {"summary", "inventory"},
        "C3 post-OI NVS receipt",
    )
    _require(
        receipt["inventory"] == [],
        "C3 post-OI NVS inventory must be empty for the fully erased slice",
    )
    summary = _validate_post_oi_nvs_summary(
        receipt["summary"],
        candidate_release_json_sha256=candidate_release_json_sha256,
        artifact_sha256=artifact_sha256,
    )
    _require(
        summary["nvs_slice_sha256"] == slice_digest
        and summary["nvs_slice_size_bytes"] == len(slice_raw),
        "C3 post-OI NVS summary does not match the reopened raw slice",
    )
    _require(
        summary["acquisition_log_sha256"]
        == hashlib.sha256(log_raw).hexdigest()
        and summary["acquisition_log_size_bytes"] == len(log_raw),
        "C3 post-OI NVS summary does not match the reopened acquisition log",
    )
    return {
        "receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
        "receipt_size_bytes": len(receipt_raw),
        "summary": summary,
    }


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
    elif expected_profile_id == C3_PROFILE_ID:
        expected_keys.add("post_oi_nvs")
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
    if not public and expected_profile_id == C3_PROFILE_ID:
        binding = _exact_dict(
            item["post_oi_nvs"],
            _POST_OI_NVS_BINDING_KEYS,
            "C3 post-OI NVS binding",
        )
        receipt_summary = _validate_post_oi_nvs_summary(
            binding["summary"],
            candidate_release_json_sha256=candidate_release_json_sha256,
            artifact_sha256=artifact_sha256,
        )
        expected_receipt = _expected_post_oi_nvs_receipt_bytes(receipt_summary)
        _require(
            binding["receipt_sha256"]
            == hashlib.sha256(expected_receipt).hexdigest()
            and type(binding["receipt_size_bytes"]) is int
            and binding["receipt_size_bytes"] == len(expected_receipt),
            "C3 post-OI NVS receipt binding changed",
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
    summary.pop("post_oi_nvs", None)
    summary[digest_key] = artifact_sha256
    summary["qualification_result_sha256"] = hashlib.sha256(raw).hexdigest()
    return summary


def validate_c3_result_for_observation(
    result_path: Path,
    *,
    artifact_path: Path,
    expected_version: str,
    candidate_release_json_sha256: str,
    observation: Any,
    post_oi_nvs_receipt_path: Path,
    post_oi_nvs_slice_path: Path,
    post_oi_nvs_acquisition_log_path: Path,
) -> dict[str, Any]:
    """Bind one C3 private result to its reopened evidence and observation.

    Completion and finalization use this seam instead of trusting a
    hand-written result: the exclusive mode-0600 receipt, raw-slice, and
    acquisition-log files are reopened and re-hashed, the slice's exact
    fully erased identity is re-verified, and the retained OI raw-log
    digest plus reset-sample count are cross-checked against the completed
    C3 observation.  Returns the same non-private public summary as
    ``validate_result_file``.
    """

    _gate_names, expected_name, digest_key = _validate_expected_inputs(
        C3_PROFILE_ID,
        expected_version,
        candidate_release_json_sha256,
    )
    raw, _identity = _stable_regular_bytes(
        Path(result_path),
        label="qualification result",
        maximum=MAX_RESULT_BYTES,
        exclusive=True,
    )
    artifact_sha256 = _artifact_digest(Path(artifact_path), expected_name)
    value = _validate_common(
        _strict_json(raw),
        expected_profile_id=C3_PROFILE_ID,
        expected_version=expected_version,
        candidate_release_json_sha256=candidate_release_json_sha256,
        artifact_sha256=artifact_sha256,
        public=False,
    )
    binding = value["post_oi_nvs"]
    reopened = _reopen_c3_post_oi_nvs_evidence(
        post_oi_nvs_receipt_path,
        post_oi_nvs_slice_path,
        post_oi_nvs_acquisition_log_path,
        candidate_release_json_sha256=candidate_release_json_sha256,
        artifact_sha256=artifact_sha256,
    )
    _require(
        reopened == binding,
        "C3 post-OI NVS evidence does not match the private result",
    )
    _require(
        type(observation) is dict,
        "C3 qualification observation must be an object",
    )
    observed_raw_sha256 = observation.get("raw_log_sha256")
    observed_resets = observation.get("reset_to_service_advertisement_ms")
    _require(
        type(observed_raw_sha256) is str
        and _SHA256_RE.fullmatch(observed_raw_sha256) is not None,
        "C3 qualification observation raw-log digest is invalid",
    )
    _require(
        type(observed_resets) is list
        and len(observed_resets) == C3_POST_OI_NVS_RESET_SAMPLES,
        "C3 qualification observation reset samples changed",
    )
    _require(
        reopened["summary"]["oi1_raw_sha256"] == observed_raw_sha256
        and reopened["summary"]["reset_samples"] == len(observed_resets),
        "C3 post-OI NVS receipt is not bound to this observation",
    )
    summary = dict(value)
    summary.pop("post_oi_nvs", None)
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


def _strict_json_object(raw: bytes, label: str) -> dict[str, Any]:
    """Decode strict JSON without imposing private-result key ordering."""

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except QualificationError:
        raise
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise QualificationError("%s is not strict UTF-8 JSON" % label) from exc
    _require(type(value) is dict, "%s must be a JSON object" % label)
    return value


def _absolute_lexical_path(path: Path, label: str) -> Path:
    """Return an absolute path without resolving or accepting symlink hops."""

    _require(os.name == "posix", "%s requires reviewed POSIX dirfd support" % label)
    _require(
        hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW"),
        "%s requires no-follow directory opens" % label,
    )
    try:
        raw = os.fspath(path)
        _require(type(raw) is str and bool(raw), "%s path is invalid" % label)
        _require(
            all(component not in (".", "..") for component in raw.split(os.sep)),
            "%s path contains lexical navigation" % label,
        )
        value = Path(os.path.abspath(raw))
    except (OSError, TypeError, ValueError) as exc:
        raise QualificationError("%s path is invalid" % label) from exc
    _require(value.is_absolute(), "%s path must be absolute" % label)
    return value


def _directory_identity(value: os.stat_result) -> tuple[int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mode)


def _verify_directory_chain(
    chain: list[tuple[int, Path, tuple[int, int, int]]],
    label: str,
) -> None:
    """Prove every held directory still names the original non-symlink inode."""

    for descriptor, path, expected in chain:
        try:
            held = os.fstat(descriptor)
            visible = path.lstat()
        except OSError as exc:
            raise QualificationError("%s directory chain changed" % label) from exc
        _require(
            stat.S_ISDIR(held.st_mode)
            and stat.S_ISDIR(visible.st_mode)
            and not stat.S_ISLNK(visible.st_mode)
            and _directory_identity(held) == expected
            and _directory_identity(visible) == expected,
            "%s directory chain changed" % label,
        )


def _verify_output_parent(
    chain: list[tuple[int, Path, tuple[int, int, int]]],
) -> None:
    """Named seam for before/after output-parent race verification."""

    _verify_directory_chain(chain, "qualification result parent")


def _close_directory_chain(
    chain: list[tuple[int, Path, tuple[int, int, int]]],
) -> None:
    for descriptor, _path, _identity in reversed(chain):
        try:
            os.close(descriptor)
        except OSError:
            pass


def _open_directory_chain(
    path: Path,
    *,
    label: str,
    create: bool,
) -> list[tuple[int, Path, tuple[int, int, int]]]:
    """Open each absolute directory component with held no-follow dirfds."""

    directory = _absolute_lexical_path(path, label)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    chain: list[tuple[int, Path, tuple[int, int, int]]] = []
    try:
        descriptor = os.open(os.sep, flags)
        root_stat = os.fstat(descriptor)
        _require(stat.S_ISDIR(root_stat.st_mode), "%s root is unsafe" % label)
        chain.append((descriptor, Path(os.sep), _directory_identity(root_stat)))
        current = Path(os.sep)
        for component in directory.parts[1:]:
            parent_descriptor = chain[-1][0]
            try:
                descriptor = os.open(component, flags, dir_fd=parent_descriptor)
            except FileNotFoundError:
                _require(create, "%s directory is missing" % label)
                try:
                    os.mkdir(component, 0o700, dir_fd=parent_descriptor)
                except FileExistsError:
                    # A concurrent creator is accepted only if the no-follow
                    # open below proves it created a directory, never a link.
                    pass
                descriptor = os.open(component, flags, dir_fd=parent_descriptor)
            current = current / component
            opened = os.fstat(descriptor)
            _require(stat.S_ISDIR(opened.st_mode), "%s ancestor is unsafe" % label)
            chain.append((descriptor, current, _directory_identity(opened)))
        _verify_directory_chain(chain, label)
        return chain
    except QualificationError:
        _close_directory_chain(chain)
        raise
    except OSError as exc:
        _close_directory_chain(chain)
        raise QualificationError("%s directory chain is unsafe" % label) from exc


def _read_open_regular(
    descriptor: int,
    *,
    label: str,
    maximum: int,
) -> tuple[bytes, tuple[int, ...]]:
    """Read an already no-follow-opened regular file twice and bind identity."""

    before = os.fstat(descriptor)
    _require(stat.S_ISREG(before.st_mode), "%s must be a regular file" % label)
    _require(0 < before.st_size <= maximum, "%s size is outside its bound" % label)

    def read_once() -> bytes:
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    raw = read_once()
    os.lseek(descriptor, 0, os.SEEK_SET)
    repeated = read_once()
    after = os.fstat(descriptor)
    _require(
        len(raw) == before.st_size
        and raw == repeated
        and all(
            getattr(before, field) == getattr(after, field)
            for field in _FILE_ID_FIELDS
        ),
        "%s changed while it was read" % label,
    )
    return raw, tuple(getattr(before, field) for field in _FILE_ID_FIELDS)


def _read_regular_at(
    directory_descriptor: int,
    name: str,
    *,
    label: str,
    maximum: int,
) -> tuple[bytes, tuple[int, ...]]:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = -1
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
        return _read_open_regular(descriptor, label=label, maximum=maximum)
    except QualificationError:
        raise
    except OSError as exc:
        raise QualificationError("%s is missing or unsafe" % label) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _artifact_record(
    value: Any,
    *,
    expected_path: str,
    label: str,
    offset: int | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    keys = {"path", "size", "sha256"}
    if offset is not None:
        keys.add("offset")
    if role is not None:
        keys.add("role")
    record = _exact_dict(value, keys, label)
    _require(record["path"] == expected_path, "%s path changed" % label)
    _require(
        type(record["size"]) is int and record["size"] > 0,
        "%s size is invalid" % label,
    )
    _require(
        type(record["sha256"]) is str
        and _SHA256_RE.fullmatch(record["sha256"]) is not None,
        "%s digest is invalid" % label,
    )
    if offset is not None:
        _require(record["offset"] == offset, "%s offset changed" % label)
    if role is not None:
        _require(record["role"] == role, "%s role changed" % label)
    return record


def _validate_candidate_provenance(value: Any) -> None:
    provenance = _exact_dict(
        value,
        {"pyble", "micropython", "esp_idf", "patch_count", "runner", "tools"},
        "candidate provenance",
    )
    pyble = _exact_dict(
        provenance["pyble"], {"commit", "clean"}, "candidate PyBLE provenance"
    )
    _require(
        type(pyble["commit"]) is str
        and re.fullmatch(r"[0-9a-f]{40}", pyble["commit"]) is not None
        and pyble["clean"] is True,
        "candidate PyBLE provenance changed",
    )
    for name in ("micropython", "esp_idf"):
        source = _exact_dict(
            provenance[name], {"ref", "commit"}, "candidate %s provenance" % name
        )
        _require(
            type(source["ref"]) is str
            and bool(source["ref"])
            and type(source["commit"]) is str
            and re.fullmatch(r"[0-9a-f]{40}", source["commit"]) is not None,
            "candidate %s provenance changed" % name,
        )
    _require(
        type(provenance["patch_count"]) is int
        and provenance["patch_count"] >= 0,
        "candidate patch count changed",
    )
    runner = _exact_dict(
        provenance["runner"], {"os", "architecture"}, "candidate runner"
    )
    _require(
        all(type(runner[key]) is str and bool(runner[key].strip()) for key in runner),
        "candidate runner changed",
    )
    tools = provenance["tools"]
    _require(type(tools) is list and bool(tools), "candidate tools are missing")
    names: list[str] = []
    for index, tool in enumerate(tools):
        item = _exact_dict(
            tool, {"name", "version"}, "candidate tool %d" % index
        )
        _require(
            all(type(item[key]) is str and bool(item[key].strip()) for key in item),
            "candidate tool metadata changed",
        )
        names.append(item["name"])
    _require(
        names == sorted(names) and len(names) == len(set(names)),
        "candidate tool order changed",
    )


def _validate_candidate_release(
    release: Any,
    *,
    profile_id: str,
    artifact_size: int,
    artifact_sha256: str,
) -> str:
    """Validate the frozen V4 five-profile metadata used by this gate writer."""

    value = _exact_dict(
        release,
        {"schema_version", "identity", "provenance", "installer", "profiles", "documents"},
        "candidate release",
    )
    _require(value["schema_version"] == 4, "candidate release schema changed")
    identity = _exact_dict(
        value["identity"],
        {"version", "tag", "agent_version", "protocol_version", "built_at"},
        "candidate release identity",
    )
    _require(
        identity["version"] == "0.6.0"
        and identity["tag"] == "firmware-v0.6.0"
        and identity["agent_version"] == "0.6.0"
        and identity["protocol_version"] == "PBLE/1"
        and type(identity["built_at"]) is str
        and _UTC_RE.fullmatch(identity["built_at"]) is not None,
        "candidate is not the exact v0.6.0 release source era",
    )
    _validate_candidate_provenance(value["provenance"])
    _require(
        value["installer"] == {"package": "esp-web-tools", "version": "10.4.0"},
        "candidate installer metadata changed",
    )
    profiles = value["profiles"]
    _require(
        type(profiles) is list
        and [item.get("id") if type(item) is dict else None for item in profiles]
        == list(_CANDIDATE_PROFILE_ORDER),
        "candidate profile order changed",
    )
    for current_profile_id, raw_profile in zip(_CANDIDATE_PROFILE_ORDER, profiles):
        if current_profile_id == PICO_PROFILE_ID:
            item = _exact_dict(
                raw_profile,
                {
                    "id",
                    "target",
                    "provisioning_kind",
                    "board",
                    "hil_status",
                    "install",
                    "resource_image",
                },
                "candidate Pico profile",
            )
            _require(
                item["id"] == PICO_PROFILE_ID
                and item["target"] == PICO_PROFILE_ID
                and item["provisioning_kind"] == "verified-uf2-bootsel"
                and item["board"] == "RPI_PICO2_W"
                and item["hil_status"] == "pending",
                "candidate Pico profile metadata changed",
            )
            install = _exact_dict(
                item["install"],
                {"path", "size", "sha256", "format"},
                "candidate Pico install",
            )
            _require(install["format"] == "uf2", "candidate Pico format changed")
            install = _artifact_record(
                {key: install[key] for key in ("path", "size", "sha256")},
                expected_path="rpi-pico2-w/firmware.uf2",
                label="candidate Pico install",
            )
            resource = _exact_dict(
                item["resource_image"],
                {"path", "size", "sha256", "image_limit_bytes"},
                "candidate Pico resource image",
            )
            _require(
                resource["image_limit_bytes"] == 1_572_864,
                "candidate Pico image limit changed",
            )
            _artifact_record(
                {key: resource[key] for key in ("path", "size", "sha256")},
                expected_path="rpi-pico2-w/firmware.bin",
                label="candidate Pico resource image",
            )
            if profile_id == PICO_PROFILE_ID:
                _require(
                    install["size"] == artifact_size
                    and install["sha256"] == artifact_sha256,
                    "candidate Pico install does not bind firmware.uf2",
                )
            continue

        spec = _ESP_PROFILE_METADATA[current_profile_id]
        item = _exact_dict(
            raw_profile,
            {
                "id",
                "target",
                "provisioning_kind",
                "chip_family",
                "silicon_revision",
                "requirements",
                "flash",
                "hil_status",
                "manifest",
                "install",
                "components",
            },
            "candidate %s profile" % current_profile_id,
        )
        requirements = _exact_dict(
            item["requirements"],
            {"flash_size_bytes", "psram"},
            "candidate %s requirements" % current_profile_id,
        )
        _require(
            item["id"] == current_profile_id
            and item["target"] == spec["target"]
            and item["provisioning_kind"] == "esp-web-serial"
            and item["chip_family"] == spec["chip_family"]
            and item["silicon_revision"] == spec["silicon_revision"]
            and requirements["flash_size_bytes"] == spec["flash_size_bytes"]
            and requirements["psram"] == spec["psram"]
            and item["flash"]
            == {"mode": "dio", "frequency_hz": spec["frequency_hz"]}
            and item["hil_status"] == "pending",
            "candidate %s profile metadata changed" % current_profile_id,
        )
        _artifact_record(
            item["manifest"],
            expected_path="%s/manifest.json" % current_profile_id,
            label="candidate %s manifest" % current_profile_id,
        )
        install = _artifact_record(
            item["install"],
            expected_path="%s/firmware.bin" % current_profile_id,
            label="candidate %s install" % current_profile_id,
            offset=spec["install_offset"],
        )
        components = item["components"]
        _require(
            type(components) is list and len(components) == len(_COMPONENTS),
            "candidate %s component count changed" % current_profile_id,
        )
        for component, (role, filename), component_offset in zip(
            components, _COMPONENTS, spec["component_offsets"]
        ):
            _artifact_record(
                component,
                expected_path="%s/%s" % (current_profile_id, filename),
                label="candidate %s %s" % (current_profile_id, role),
                offset=component_offset,
                role=role,
            )
        if profile_id == current_profile_id:
            _require(
                install["size"] == artifact_size
                and install["sha256"] == artifact_sha256,
                "candidate %s install does not bind firmware.bin"
                % current_profile_id,
            )

    documents = _exact_dict(
        value["documents"], set(_DOCUMENT_PATHS), "candidate documents"
    )
    for key, expected_path in _DOCUMENT_PATHS.items():
        _artifact_record(
            documents[key],
            expected_path=expected_path,
            label="candidate document %s" % key,
        )
    return identity["version"]


def _candidate_snapshot(
    candidate_dir: Path,
    profile_id: str,
) -> tuple[Any, ...]:
    """Bind candidate directory, release bytes, artifact bytes, and metadata."""

    _require(profile_id in _GATES_BY_PROFILE, "qualification profile is unsupported")
    candidate_root = _absolute_lexical_path(candidate_dir, "candidate")
    chain = _open_directory_chain(candidate_root, label="candidate", create=False)
    profile_descriptor = -1
    try:
        release_raw, release_identity = _read_regular_at(
            chain[-1][0],
            "release.json",
            label="candidate release.json",
            maximum=2 * 1024 * 1024,
        )
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        profile_path = candidate_root / profile_id
        profile_descriptor = os.open(profile_id, flags, dir_fd=chain[-1][0])
        profile_stat = os.fstat(profile_descriptor)
        _require(stat.S_ISDIR(profile_stat.st_mode), "candidate profile is unsafe")
        chain.append(
            (profile_descriptor, profile_path, _directory_identity(profile_stat))
        )
        profile_descriptor = -1
        expected_name, _digest_key = _ARTIFACT_BY_PROFILE[profile_id]
        artifact_raw, artifact_identity = _read_regular_at(
            chain[-1][0],
            expected_name,
            label="candidate %s" % expected_name,
            maximum=64 * 1024 * 1024,
        )
        _verify_directory_chain(chain, "candidate")
    except QualificationError:
        raise
    except OSError as exc:
        raise QualificationError("candidate profile is missing or unsafe") from exc
    finally:
        if profile_descriptor >= 0:
            os.close(profile_descriptor)
        chain_identity = tuple(
            (os.fspath(path), identity) for _descriptor, path, identity in chain
        )
        _close_directory_chain(chain)

    artifact_sha256 = hashlib.sha256(artifact_raw).hexdigest()
    release = _strict_json_object(release_raw, "candidate release.json")
    version = _validate_candidate_release(
        release,
        profile_id=profile_id,
        artifact_size=len(artifact_raw),
        artifact_sha256=artifact_sha256,
    )
    artifact_path = candidate_root / profile_id / expected_name
    return (
        version,
        hashlib.sha256(release_raw).hexdigest(),
        artifact_path,
        artifact_sha256,
        candidate_root,
        release_identity,
        artifact_identity,
        chain_identity,
    )


def _candidate_identity(
    candidate_dir: Path,
    profile_id: str,
) -> tuple[str, str, Path, str]:
    """Return the public identity fields from one full candidate snapshot."""

    snapshot = _candidate_snapshot(candidate_dir, profile_id)
    return snapshot[0], snapshot[1], snapshot[2], snapshot[3]


def _remove_created_result(
    parent_descriptor: int,
    name: str,
    created_identity: tuple[int, int] | None,
) -> None:
    """Best-effort rollback through the held parent, never through a path."""

    try:
        if created_identity is not None:
            visible = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
            if (visible.st_dev, visible.st_ino) != created_identity:
                return
        os.unlink(name, dir_fd=parent_descriptor)
        try:
            os.fsync(parent_descriptor)
        except OSError:
            pass
    except OSError:
        pass


def _write_exclusive_result(
    path: Path,
    raw: bytes,
    *,
    post_write_check: Callable[[], None] | None = None,
) -> None:
    """Durably create one no-replace result or remove every partial write."""

    _require(
        type(raw) is bytes and 0 < len(raw) <= MAX_RESULT_BYTES,
        "qualification result bytes are outside their bound",
    )
    output = _absolute_lexical_path(path, "qualification result")
    _require(output.name not in ("", ".", ".."), "qualification result name is unsafe")
    chain = _open_directory_chain(
        output.parent,
        label="qualification result parent",
        create=True,
    )
    parent_descriptor = chain[-1][0]
    descriptor = -1
    reader = -1
    created = False
    preserve = False
    created_identity: tuple[int, int] | None = None
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        _verify_output_parent(chain)
        try:
            descriptor = os.open(
                output.name,
                flags,
                0o600,
                dir_fd=parent_descriptor,
            )
        except FileExistsError as exc:
            raise QualificationError(
                "qualification result output already exists"
            ) from exc
        created = True
        opened = os.fstat(descriptor)
        created_identity = (opened.st_dev, opened.st_ino)
        _require(stat.S_ISREG(opened.st_mode), "qualification result output is unsafe")
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise OSError("short qualification result write")
            offset += written
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        _require(
            stat.S_ISREG(after.st_mode)
            and stat.S_IMODE(after.st_mode) == 0o600
            and after.st_nlink == 1
            and after.st_size == len(raw)
            and (after.st_dev, after.st_ino) == created_identity,
            "qualification result output is unsafe",
        )
        os.close(descriptor)
        descriptor = -1

        _verify_output_parent(chain)
        read_flags = os.O_RDONLY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            read_flags |= os.O_CLOEXEC
        reader = os.open(output.name, read_flags, dir_fd=parent_descriptor)
        written_raw, written_identity = _read_open_regular(
            reader,
            label="qualification result",
            maximum=MAX_RESULT_BYTES,
        )
        _require(
            written_raw == raw
            and (written_identity[0], written_identity[1]) == created_identity
            and stat.S_IMODE(written_identity[2]) == 0o600
            and written_identity[3] == 1,
            "qualification result write verification failed",
        )
        os.close(reader)
        reader = -1
        if post_write_check is not None:
            post_write_check()
        _verify_output_parent(chain)
        reader = os.open(output.name, read_flags, dir_fd=parent_descriptor)
        final_raw, final_identity = _read_open_regular(
            reader,
            label="qualification result",
            maximum=MAX_RESULT_BYTES,
        )
        _require(
            final_raw == raw
            and (final_identity[0], final_identity[1]) == created_identity
            and stat.S_IMODE(final_identity[2]) == 0o600
            and final_identity[3] == 1,
            "qualification result changed during final validation",
        )
        os.close(reader)
        reader = -1
        os.fsync(parent_descriptor)
        _verify_output_parent(chain)
        preserve = True
    except QualificationError:
        raise
    except OSError as exc:
        raise QualificationError("qualification result could not be written") from exc
    finally:
        if reader >= 0:
            try:
                os.close(reader)
            except OSError:
                pass
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if created and not preserve:
            _remove_created_result(
                parent_descriptor,
                output.name,
                created_identity,
            )
        _close_directory_chain(chain)


def create_result_file(
    *,
    candidate_dir: Path,
    profile_id: str,
    passed_gates: list[str],
    output_path: Path,
    post_oi_nvs_receipt_path: Path | None = None,
    post_oi_nvs_slice_path: Path | None = None,
    post_oi_nvs_acquisition_log_path: Path | None = None,
) -> Path:
    """Derive and create one candidate-bound private gate result safely.

    For ``esp32-c3-4mb`` the three post-OI NVS evidence paths are required:
    the writer reopens the exclusive mode-0600 receipt, raw-slice, and
    acquisition-log files, re-derives every digest from the reopened bytes,
    and re-verifies the slice's exact fully erased identity before any
    result byte is written.  A diagnostic capture that fails those checks is
    retained on disk but never mints a passing result.  Pico rejects the
    evidence inputs.
    """

    expected_gates = _GATES_BY_PROFILE.get(profile_id)
    _require(expected_gates is not None, "qualification profile is unsupported")
    _require(
        type(passed_gates) is list
        and all(type(item) is str for item in passed_gates)
        and len(passed_gates) == len(set(passed_gates))
        and set(passed_gates) == set(expected_gates),
        "passed gates must cover the exact profile gate set once",
    )
    candidate_snapshot = _candidate_snapshot(
        Path(candidate_dir),
        profile_id,
    )
    version, release_sha256, artifact_path, artifact_sha256 = candidate_snapshot[:4]
    candidate_root = candidate_snapshot[4]
    output = _absolute_lexical_path(output_path, "qualification result")
    _require(
        not output.is_relative_to(candidate_root),
        "qualification result output must not be inside the candidate",
    )
    if profile_id == C3_PROFILE_ID:
        post_oi_nvs_binding = _reopen_c3_post_oi_nvs_evidence(
            post_oi_nvs_receipt_path,
            post_oi_nvs_slice_path,
            post_oi_nvs_acquisition_log_path,
            candidate_release_json_sha256=release_sha256,
            artifact_sha256=artifact_sha256,
        )
    else:
        _require(
            post_oi_nvs_receipt_path is None
            and post_oi_nvs_slice_path is None
            and post_oi_nvs_acquisition_log_path is None,
            "%s rejects post-OI NVS evidence inputs" % profile_id,
        )
        post_oi_nvs_binding = None
    _expected_name, digest_key = _ARTIFACT_BY_PROFILE[profile_id]
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": "passed",
        "profile_id": profile_id,
        "firmware_version": version,
        "candidate_release_json_sha256": release_sha256,
        digest_key: artifact_sha256,
        "gates": {name: "passed" for name in expected_gates},
    }
    if post_oi_nvs_binding is not None:
        result["post_oi_nvs"] = post_oi_nvs_binding
    raw = canonical_json_bytes(result)
    def validate_before_preserve() -> None:
        validate_result_file(
            output,
            artifact_path=artifact_path,
            expected_profile_id=profile_id,
            expected_version=version,
            candidate_release_json_sha256=release_sha256,
        )
        _require(
            _candidate_snapshot(Path(candidate_dir), profile_id) == candidate_snapshot,
            "candidate changed while qualification result was created",
        )
        if post_oi_nvs_binding is not None:
            _require(
                _reopen_c3_post_oi_nvs_evidence(
                    post_oi_nvs_receipt_path,
                    post_oi_nvs_slice_path,
                    post_oi_nvs_acquisition_log_path,
                    candidate_release_json_sha256=release_sha256,
                    artifact_sha256=artifact_sha256,
                )
                == post_oi_nvs_binding,
                "C3 post-OI NVS evidence changed while the result was created",
            )

    _write_exclusive_result(
        output,
        raw,
        post_write_check=validate_before_preserve,
    )
    return output


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "create-result derives candidate identity and accepts one "
            "--passed-gate per frozen profile gate"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create-result")
    create_parser.add_argument("candidate_dir", type=Path)
    create_parser.add_argument(
        "profile_id",
        choices=(C3_PROFILE_ID, PICO_PROFILE_ID),
    )
    create_parser.add_argument("output_path", type=Path)
    create_parser.add_argument(
        "--passed-gate",
        action="append",
        required=True,
        dest="passed_gates",
    )
    create_parser.add_argument(
        "--post-oi-nvs-receipt",
        type=Path,
        dest="post_oi_nvs_receipt",
        help="C3-only exclusive mode-0600 post-OI NVS inventory receipt",
    )
    create_parser.add_argument(
        "--post-oi-nvs-slice",
        type=Path,
        dest="post_oi_nvs_slice",
        help="C3-only exclusive mode-0600 raw NVS partition slice",
    )
    create_parser.add_argument(
        "--post-oi-nvs-acquisition-log",
        type=Path,
        dest="post_oi_nvs_acquisition_log",
        help="C3-only exclusive mode-0600 NVS acquisition log",
    )
    args = parser.parse_args(argv)
    try:
        created = create_result_file(
            candidate_dir=args.candidate_dir,
            profile_id=args.profile_id,
            passed_gates=args.passed_gates,
            output_path=args.output_path,
            post_oi_nvs_receipt_path=args.post_oi_nvs_receipt,
            post_oi_nvs_slice_path=args.post_oi_nvs_slice,
            post_oi_nvs_acquisition_log_path=args.post_oi_nvs_acquisition_log,
        )
    except QualificationError as exc:
        print("qualification result creation failed: %s" % exc, file=sys.stderr)
        return 1
    print(created)
    return 0


__all__ = (
    "C3_NVS_PARTITION_OFFSET",
    "C3_NVS_PARTITION_SIZE",
    "C3_POST_OI_NVS_SLICE_SHA256",
    "C3_PROFILE_ID",
    "PICO_PROFILE_ID",
    "QualificationError",
    "canonical_json_bytes",
    "create_result_file",
    "post_oi_nvs_evidence_paths",
    "private_result_snapshot",
    "validate_c3_result_for_observation",
    "validate_public_summary",
    "validate_result_file",
)


if __name__ == "__main__":
    raise SystemExit(_main())
