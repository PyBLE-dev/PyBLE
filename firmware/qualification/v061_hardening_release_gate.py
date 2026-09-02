#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Candidate-bound private evidence authority for v0.6.1 hardening HIL.

This module deliberately accepts only bounded, canonical, privacy-safe
machine evidence.  It is shared by the physical bench and release admission
so that neither path can silently reinterpret an operator log.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Callable


class QualificationError(RuntimeError):
    """The supplied evidence cannot be admitted."""


PROFILE_TARGETS = {
    "esp32-4mb": "esp32",
    "esp32-s3-n16r8": "esp32-s3",
    "waveshare-esp32-s3-lcd-147b": "waveshare-esp32-s3-lcd-147b",
    "esp32-c3-4mb": "esp32-c3",
    "rpi-pico2-w": "rpi-pico2-w",
}
SCENARIO_ORDER = (
    "transport-session",
    "fragment-hardening",
    "run-isolation",
    "resource-stability",
    "stdin-isolation",
    "configuration-durability",
    "filesystem-hardening",
)
WORKSPACE_PROVISIONING_ORDER = (
    "erased-media-first-boot",
    "nonblank-media-refusal",
)
RESULT_KEYS = (
    "schema_version",
    "measurement_contract",
    "profile_id",
    "target",
    "firmware_version",
    "source_commit",
    "candidate_release_json_sha256",
    "install_sha256",
    "qualification_source_commit",
    "qualification_executable_sha256",
    "scenario_order",
    "scenarios",
    "workspace_provisioning",
    "raw_log_sha256",
    "status",
)
PUBLIC_SUMMARY_KEYS = (
    "measurement_contract",
    "scenario_order",
    "scenarios",
    "sequential_runs",
    "workspace_provisioning",
    "private_result_sha256",
)
WORKSPACE_RECEIPT_KEYS = (
    "schema_version",
    "measurement_contract",
    "observation_kind",
    "profile_id",
    "target",
    "firmware_version",
    "source_commit",
    "candidate_release_json_sha256",
    "install_sha256",
    "qualification_source_commit",
    "qualification_executable_sha256",
    "raw_log_sha256",
    "status",
)

_RESULT_CONTRACT = "v061-hardening-seven-scenario-v1"
_RECEIPT_CONTRACT = "v061-workspace-provisioning-receipt-v1"
_VERSION = "0.6.1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_MAX_JSON_BYTES = 2 * 1024 * 1024
_MAX_LOG_BYTES = 64 * 1024
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_QUALIFICATION_SOURCE_PATHS = (
    "firmware/qualification/v061_hardening_release_gate.py",
    "tests/firmware_tests/hil/v061_hardening_bench.py",
    "tests/firmware_tests/hil/_pble_bench.py",
    "tests/firmware_tests/hil/_pble_central.py",
    "tests/firmware_tests/hil/_pble_wire.py",
    "tests/firmware_tests/hil/target_smoke.py",
    "firmware/qualification/oi1-gates.json",
    "firmware/versions.lock",
)
_QUALIFICATION_EXECUTABLE_RELATIVE = (
    "tests/firmware_tests/hil/v061_hardening_bench.py"
)
_FILE_ID_FIELDS = (
    "st_dev",
    "st_ino",
    "st_mode",
    "st_nlink",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
)


class _ResultInputPreflight:
    """Opaque lease over the exact long-lived inputs to one physical run."""

    __slots__ = (
        "candidate_dir",
        "profile_id",
        "candidate",
        "qualification_root",
        "qualification",
        "validation",
        "erased_path",
        "erased_summary",
        "erased_snapshot",
        "nonblank_path",
        "nonblank_summary",
        "nonblank_snapshot",
    )

    def __init__(
        self,
        *,
        candidate_dir,
        profile_id,
        candidate,
        qualification_root,
        qualification,
        validation,
        erased_path,
        erased_summary,
        erased_snapshot,
        nonblank_path,
        nonblank_summary,
        nonblank_snapshot,
    ) -> None:
        self.candidate_dir = candidate_dir
        self.profile_id = profile_id
        self.candidate = candidate
        self.qualification_root = qualification_root
        self.qualification = qualification
        self.validation = validation
        self.erased_path = erased_path
        self.erased_summary = erased_summary
        self.erased_snapshot = erased_snapshot
        self.nonblank_path = nonblank_path
        self.nonblank_summary = nonblank_summary
        self.nonblank_snapshot = nonblank_snapshot


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationError(message)


def canonical_json_bytes(value: Any) -> bytes:
    """Return the frozen private-evidence JSON representation."""

    try:
        text = json.dumps(
            value,
            indent=2,
            sort_keys=False,
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise QualificationError("evidence is not canonical JSON") from exc
    return (text + "\n").encode("utf-8")


def _reject_constant(value: str) -> None:
    raise QualificationError("evidence contains non-JSON %s" % value)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationError("evidence duplicates a JSON key")
        result[key] = value
    return result


def _decode_json(raw: bytes, label: str, *, canonical: bool) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except QualificationError:
        raise
    except (UnicodeDecodeError, TypeError, ValueError) as exc:
        raise QualificationError("%s is not strict UTF-8 JSON" % label) from exc
    _require(type(value) is dict, "%s must be a JSON object" % label)
    if canonical:
        _require(raw == canonical_json_bytes(value), "%s is not canonical" % label)
    return value


def _canonical_json_line(value: dict[str, Any]) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise QualificationError("raw evidence is not canonical JSON Lines") from exc


def _absolute_lexical_path(path: Path, label: str) -> Path:
    _require(os.name == "posix", "%s requires POSIX no-follow support" % label)
    _require(
        hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW"),
        "%s requires POSIX no-follow support" % label,
    )
    try:
        raw = os.fspath(path)
        _require(type(raw) is str and bool(raw), "%s path is invalid" % label)
        _require(
            all(part not in (".", "..") for part in raw.split(os.sep)),
            "%s path contains lexical navigation" % label,
        )
        value = Path(os.path.abspath(raw))
        # Darwin exposes /var as a fixed system alias for /private/var.  Test
        # and operator temporary directories commonly retain the /var
        # spelling, so normalize that one OS-owned alias without resolving any
        # caller-controlled component farther down the path.
        if value.parts[:2] == (os.sep, "var"):
            try:
                if os.readlink("/var") == "private/var":
                    value = Path("/private/var").joinpath(*value.parts[2:])
            except OSError:
                pass
    except (OSError, TypeError, ValueError) as exc:
        raise QualificationError("%s path is invalid" % label) from exc
    return value


def _directory_identity(value: os.stat_result) -> tuple[int, int, int]:
    return value.st_dev, value.st_ino, value.st_mode


def _close_directory_chain(
    chain: list[tuple[int, Path, tuple[int, int, int]]],
) -> None:
    for descriptor, _path, _identity in reversed(chain):
        try:
            os.close(descriptor)
        except OSError:
            pass


def _verify_directory_chain(
    chain: list[tuple[int, Path, tuple[int, int, int]]], label: str
) -> None:
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


def _open_directory_chain(
    path: Path, *, label: str
) -> list[tuple[int, Path, tuple[int, int, int]]]:
    directory = _absolute_lexical_path(path, label)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    chain: list[tuple[int, Path, tuple[int, int, int]]] = []
    try:
        descriptor = os.open(os.sep, flags)
        root_stat = os.fstat(descriptor)
        chain.append((descriptor, Path(os.sep), _directory_identity(root_stat)))
        current = Path(os.sep)
        for component in directory.parts[1:]:
            descriptor = os.open(component, flags, dir_fd=chain[-1][0])
            opened = os.fstat(descriptor)
            current = current / component
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
    private: bool,
) -> tuple[bytes, tuple[int, ...]]:
    before = os.fstat(descriptor)
    _require(stat.S_ISREG(before.st_mode), "%s must be a regular file" % label)
    if private:
        _require(
            before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600,
            "%s must be one private mode-0600 regular file" % label,
        )
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
    identity = tuple(getattr(before, field) for field in _FILE_ID_FIELDS)
    _require(
        len(raw) == before.st_size
        and raw == repeated
        and identity == tuple(getattr(after, field) for field in _FILE_ID_FIELDS),
        "%s changed while it was read" % label,
    )
    return raw, identity


def _stable_regular_bytes(
    path: Path,
    *,
    label: str,
    maximum: int,
    private: bool,
) -> tuple[bytes, tuple[int, ...]]:
    value = _absolute_lexical_path(path, label)
    chain = _open_directory_chain(value.parent, label=label + " parent")
    descriptor = -1
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(value.name, flags, dir_fd=chain[-1][0])
        raw, identity = _read_open_regular(
            descriptor, label=label, maximum=maximum, private=private
        )
        _verify_directory_chain(chain, label + " parent")
        return raw, identity
    except QualificationError:
        raise
    except OSError as exc:
        raise QualificationError("%s is missing or unsafe" % label) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        _close_directory_chain(chain)


def _file_snapshot(path: Path, *, label: str, maximum: int, private: bool):
    raw, identity = _stable_regular_bytes(
        path, label=label, maximum=maximum, private=private
    )
    return raw, identity, hashlib.sha256(raw).hexdigest()


def _expected_workspace_values(observation_kind: str) -> list[dict[str, Any]]:
    if observation_kind == WORKSPACE_PROVISIONING_ORDER[0]:
        return [
            {"event": "media-precondition", "state": "erased"},
            {"count": 1, "event": "lfs2-format"},
            {"count": 1, "event": "lfs2-remount"},
            {"event": "service-advertisement", "status": "observed"},
        ]
    if observation_kind == WORKSPACE_PROVISIONING_ORDER[1]:
        return [
            {"event": "media-precondition", "state": "nonblank-incompatible"},
            {"count": 0, "event": "media-write"},
            {"count": 1, "event": "recovery-message"},
            {"event": "service-advertisement", "status": "absent"},
        ]
    raise QualificationError("workspace observation kind is unsupported")


def _validate_exact_json_lines(
    raw: bytes, expected: list[dict[str, Any]], label: str
) -> None:
    wanted = b"".join(_canonical_json_line(value) for value in expected)
    _require(raw == wanted, "%s does not match its exact canonical grammar" % label)


def _expected_scenario_log() -> list[dict[str, Any]]:
    return [
        (
            {"scenario": name, "sequential_runs": 50, "status": "passed"}
            if name == "resource-stability"
            else {"scenario": name, "status": "passed"}
        )
        for name in SCENARIO_ORDER
    ]


def _validate_sha(value: Any, label: str) -> None:
    _require(
        type(value) is str and _SHA256_RE.fullmatch(value) is not None,
        "%s digest is invalid" % label,
    )


def _validate_commit(value: Any, label: str) -> None:
    _require(
        type(value) is str and _COMMIT_RE.fullmatch(value) is not None,
        "%s commit is invalid" % label,
    )


def _validate_expected_identity(
    value: dict[str, Any],
    *,
    expected_profile_id: str,
    expected_target: str,
    expected_version: str,
    expected_source_commit: str,
    candidate_release_json_sha256: str,
    expected_install_sha256: str,
    expected_qualification_source_commit: str,
    expected_qualification_executable_sha256: str,
) -> None:
    _require(expected_profile_id in PROFILE_TARGETS, "expected profile is unsupported")
    _require(expected_target == PROFILE_TARGETS[expected_profile_id], "expected target changed")
    _require(expected_version == _VERSION, "hardening evidence requires version 0.6.1")
    _validate_commit(expected_source_commit, "expected source")
    _validate_sha(candidate_release_json_sha256, "candidate release.json")
    _validate_sha(expected_install_sha256, "expected install")
    _validate_commit(expected_qualification_source_commit, "qualification source")
    _validate_sha(
        expected_qualification_executable_sha256, "qualification executable"
    )
    expected = {
        "profile_id": expected_profile_id,
        "target": expected_target,
        "firmware_version": expected_version,
        "source_commit": expected_source_commit,
        "candidate_release_json_sha256": candidate_release_json_sha256,
        "install_sha256": expected_install_sha256,
        "qualification_source_commit": expected_qualification_source_commit,
        "qualification_executable_sha256": expected_qualification_executable_sha256,
    }
    for key, wanted in expected.items():
        _require(type(value.get(key)) is str and value.get(key) == wanted, "%s mismatch" % key)


def validate_workspace_receipt_payload(
    value,
    observation_kind,
    expected_profile_id,
    expected_target,
    expected_version,
    expected_source_commit,
    candidate_release_json_sha256,
    expected_install_sha256,
    expected_qualification_source_commit,
    expected_qualification_executable_sha256,
):
    """Validate and summarize one exact private workspace receipt."""

    _require(
        type(value) is dict and tuple(value) == WORKSPACE_RECEIPT_KEYS,
        "workspace receipt shape or key order changed",
    )
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1, "workspace receipt schema changed")
    _require(value["measurement_contract"] == _RECEIPT_CONTRACT, "workspace receipt contract changed")
    _require(observation_kind in WORKSPACE_PROVISIONING_ORDER, "workspace observation kind is unsupported")
    _require(value["observation_kind"] == observation_kind, "workspace observation kind mismatch")
    _validate_expected_identity(
        value,
        expected_profile_id=expected_profile_id,
        expected_target=expected_target,
        expected_version=expected_version,
        expected_source_commit=expected_source_commit,
        candidate_release_json_sha256=candidate_release_json_sha256,
        expected_install_sha256=expected_install_sha256,
        expected_qualification_source_commit=expected_qualification_source_commit,
        expected_qualification_executable_sha256=expected_qualification_executable_sha256,
    )
    _validate_sha(value["raw_log_sha256"], "workspace raw log")
    _require(value["status"] == "passed", "workspace receipt did not pass")
    raw = canonical_json_bytes(value)
    return {
        "status": "passed",
        "receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_log_sha256": value["raw_log_sha256"],
    }


def _workspace_raw_path(receipt_path: Path) -> Path:
    _require(receipt_path.suffix == ".json", "workspace receipt must end in .json")
    return receipt_path.with_name(receipt_path.stem + "-raw.jsonl")


def _workspace_receipt_file_snapshot(
    path: Path,
    observation_kind: str,
    validation: dict[str, str],
):
    receipt_path = _absolute_lexical_path(path, "workspace receipt")
    receipt_raw, receipt_identity, receipt_digest = _file_snapshot(
        receipt_path,
        label="workspace receipt",
        maximum=_MAX_JSON_BYTES,
        private=True,
    )
    value = _decode_json(receipt_raw, "workspace receipt", canonical=True)
    summary = validate_workspace_receipt_payload(
        value, observation_kind=observation_kind, **validation
    )
    _require(summary["receipt_sha256"] == receipt_digest, "workspace receipt digest mismatch")
    raw_path = _workspace_raw_path(receipt_path)
    boot_raw, boot_identity, boot_digest = _file_snapshot(
        raw_path,
        label="workspace raw boot log",
        maximum=_MAX_LOG_BYTES,
        private=True,
    )
    _validate_exact_json_lines(
        boot_raw,
        _expected_workspace_values(observation_kind),
        "workspace raw boot log",
    )
    _require(boot_digest == value["raw_log_sha256"], "workspace receipt does not bind its raw log")
    return summary, (
        (receipt_path, (receipt_raw, receipt_identity, receipt_digest)),
        (raw_path, (boot_raw, boot_identity, boot_digest)),
    )


def validate_workspace_receipt_file(
    path,
    observation_kind,
    expected_profile_id,
    expected_target,
    expected_version,
    expected_source_commit,
    candidate_release_json_sha256,
    expected_install_sha256,
    expected_qualification_source_commit,
    expected_qualification_executable_sha256,
):
    validation = {
        "expected_profile_id": expected_profile_id,
        "expected_target": expected_target,
        "expected_version": expected_version,
        "expected_source_commit": expected_source_commit,
        "candidate_release_json_sha256": candidate_release_json_sha256,
        "expected_install_sha256": expected_install_sha256,
        "expected_qualification_source_commit": expected_qualification_source_commit,
        "expected_qualification_executable_sha256": expected_qualification_executable_sha256,
    }
    summary, _snapshot = _workspace_receipt_file_snapshot(
        Path(path), observation_kind, validation
    )
    return summary


def _validate_scenarios(value: Any) -> None:
    _require(type(value) is dict and tuple(value) == SCENARIO_ORDER, "scenario order or inventory changed")
    for name in SCENARIO_ORDER:
        row = value[name]
        keys = ("status", "sequential_runs") if name == "resource-stability" else ("status",)
        _require(type(row) is dict and tuple(row) == keys, "%s result shape changed" % name)
        _require(row["status"] == "passed", "%s did not pass" % name)
        if name == "resource-stability":
            _require(type(row["sequential_runs"]) is int and row["sequential_runs"] == 50, "resource stability must contain exactly 50 runs")


def _validate_workspace_summary(value: Any) -> None:
    _require(type(value) is dict and tuple(value) == WORKSPACE_PROVISIONING_ORDER, "workspace evidence order or inventory changed")
    for name in WORKSPACE_PROVISIONING_ORDER:
        row = value[name]
        _require(
            type(row) is dict
            and tuple(row) == ("status", "receipt_sha256", "raw_log_sha256"),
            "%s workspace summary shape changed" % name,
        )
        _require(row["status"] == "passed", "%s workspace evidence did not pass" % name)
        _validate_sha(row["receipt_sha256"], "%s receipt" % name)
        _validate_sha(row["raw_log_sha256"], "%s raw log" % name)
    first = value[WORKSPACE_PROVISIONING_ORDER[0]]
    second = value[WORKSPACE_PROVISIONING_ORDER[1]]
    _require(first["receipt_sha256"] != second["receipt_sha256"], "workspace receipts must be distinct")
    _require(first["raw_log_sha256"] != second["raw_log_sha256"], "workspace raw logs must be distinct")


def validate_result_payload(
    value,
    expected_profile_id,
    expected_target,
    expected_version,
    expected_source_commit,
    candidate_release_json_sha256,
    expected_install_sha256,
    expected_qualification_source_commit,
    expected_qualification_executable_sha256,
):
    """Validate a private result and derive its privacy-safe public summary."""

    _require(type(value) is dict and tuple(value) == RESULT_KEYS, "hardening result shape or key order changed")
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1, "hardening result schema changed")
    _require(value["measurement_contract"] == _RESULT_CONTRACT, "hardening result contract changed")
    _validate_expected_identity(
        value,
        expected_profile_id=expected_profile_id,
        expected_target=expected_target,
        expected_version=expected_version,
        expected_source_commit=expected_source_commit,
        candidate_release_json_sha256=candidate_release_json_sha256,
        expected_install_sha256=expected_install_sha256,
        expected_qualification_source_commit=expected_qualification_source_commit,
        expected_qualification_executable_sha256=expected_qualification_executable_sha256,
    )
    _require(type(value["scenario_order"]) is list and tuple(value["scenario_order"]) == SCENARIO_ORDER, "scenario_order changed")
    _validate_scenarios(value["scenarios"])
    _validate_workspace_summary(value["workspace_provisioning"])
    _validate_sha(value["raw_log_sha256"], "hardening raw log")
    _require(value["status"] == "passed", "hardening evidence did not pass")
    result_raw = canonical_json_bytes(value)
    return {
        "measurement_contract": _RESULT_CONTRACT,
        "scenario_order": list(SCENARIO_ORDER),
        "scenarios": {name: "passed" for name in SCENARIO_ORDER},
        "sequential_runs": 50,
        "workspace_provisioning": {
            name: "passed" for name in WORKSPACE_PROVISIONING_ORDER
        },
        "private_result_sha256": hashlib.sha256(result_raw).hexdigest(),
    }


def validate_result_file(
    path,
    artifact_path,
    expected_profile_id,
    expected_target,
    expected_version,
    expected_source_commit,
    candidate_release_json_sha256,
    expected_qualification_source_commit,
    expected_qualification_executable_sha256,
):
    result_raw, _identity, _digest = _file_snapshot(
        Path(path), label="hardening result", maximum=_MAX_JSON_BYTES, private=True
    )
    artifact_raw, _artifact_identity, install_sha256 = _file_snapshot(
        Path(artifact_path),
        label="candidate install artifact",
        maximum=_MAX_ARTIFACT_BYTES,
        private=False,
    )
    _require(bool(artifact_raw), "candidate install artifact is empty")
    value = _decode_json(result_raw, "hardening result", canonical=True)
    return validate_result_payload(
        value,
        expected_profile_id=expected_profile_id,
        expected_target=expected_target,
        expected_version=expected_version,
        expected_source_commit=expected_source_commit,
        candidate_release_json_sha256=candidate_release_json_sha256,
        expected_install_sha256=install_sha256,
        expected_qualification_source_commit=expected_qualification_source_commit,
        expected_qualification_executable_sha256=expected_qualification_executable_sha256,
    )


def _candidate_snapshot(candidate_dir: Path, profile_id: str):
    _require(profile_id in PROFILE_TARGETS, "candidate profile is unsupported")
    candidate = _absolute_lexical_path(candidate_dir, "candidate")
    chain = _open_directory_chain(candidate, label="candidate")
    candidate_identity = tuple((os.fspath(path), identity) for _fd, path, identity in chain)
    _close_directory_chain(chain)
    release_raw, release_identity, release_sha256 = _file_snapshot(
        candidate / "release.json",
        label="candidate release.json",
        maximum=_MAX_JSON_BYTES,
        private=False,
    )
    release = _decode_json(release_raw, "candidate release.json", canonical=False)
    identity = release.get("identity")
    _require(type(identity) is dict, "candidate identity is missing")
    _require(identity.get("version") == _VERSION and identity.get("agent_version") == _VERSION, "candidate version is not 0.6.1")
    _require(identity.get("tag") == "firmware-v0.6.1", "candidate tag is not firmware-v0.6.1")
    _require(identity.get("protocol_version") == "PBLE/1", "candidate protocol changed")
    provenance = release.get("provenance")
    _require(type(provenance) is dict and type(provenance.get("pyble")) is dict, "candidate provenance is missing")
    source_commit = provenance["pyble"].get("commit")
    _validate_commit(source_commit, "candidate source")
    matches = [row for row in release.get("profiles", ()) if type(row) is dict and row.get("id") == profile_id]
    _require(len(matches) == 1, "candidate profile inventory is invalid")
    profile = matches[0]
    _require(profile.get("target") == PROFILE_TARGETS[profile_id], "candidate profile target changed")
    install = profile.get("install")
    _require(type(install) is dict, "candidate install record is missing")
    expected_name = "firmware.uf2" if profile_id == "rpi-pico2-w" else "firmware.bin"
    expected_relative = "%s/%s" % (profile_id, expected_name)
    _require(install.get("path") == expected_relative, "candidate install path changed")
    artifact = candidate / profile_id / expected_name
    artifact_raw, artifact_identity, install_sha256 = _file_snapshot(
        artifact,
        label="candidate install artifact",
        maximum=_MAX_ARTIFACT_BYTES,
        private=False,
    )
    _require(type(install.get("size")) is int and not isinstance(install.get("size"), bool) and install["size"] == len(artifact_raw), "candidate install size mismatch")
    _require(install.get("sha256") == install_sha256, "candidate install digest mismatch")
    return {
        "candidate": candidate,
        "candidate_identity": candidate_identity,
        "release_identity": release_identity,
        "release_sha256": release_sha256,
        "artifact": artifact,
        "artifact_identity": artifact_identity,
        "install_sha256": install_sha256,
        "source_commit": source_commit,
    }


def _git_command_bytes(root: Path, arguments: list[str], label: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise QualificationError("%s is unavailable" % label) from exc
    return completed.stdout


def _git_commit(root: Path) -> str:
    try:
        commit = _git_command_bytes(
            root,
            ["rev-parse", "--verify", "HEAD"],
            "qualification checkout commit",
        ).decode("ascii", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise QualificationError("qualification checkout commit is invalid") from exc
    _validate_commit(commit, "qualification source")
    return commit


def _committed_qualification_file(root: Path, commit: str, relative: str):
    tree_raw = _git_command_bytes(
        root,
        ["ls-tree", "-z", commit, "--", relative],
        "committed qualification source",
    )
    records = [record for record in tree_raw.split(b"\0") if record]
    _require(len(records) == 1, "qualification source inventory changed")
    try:
        metadata, encoded_path = records[0].split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii", errors="strict").split(" ")
        observed_path = encoded_path.decode("utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError) as exc:
        raise QualificationError("committed qualification source is invalid") from exc
    _require(
        observed_path == relative
        and kind == "blob"
        and mode in ("100644", "100755")
        and _COMMIT_RE.fullmatch(object_id) is not None,
        "qualification source inventory changed",
    )
    raw = _git_command_bytes(
        root,
        ["cat-file", "blob", object_id],
        "committed qualification source bytes",
    )
    _require(
        0 < len(raw) <= _MAX_JSON_BYTES,
        "committed qualification source size is outside its bound",
    )
    return mode, object_id, raw


def _qualification_snapshot(qualification_repo_root: Path):
    root = _absolute_lexical_path(qualification_repo_root, "qualification checkout")
    chain = _open_directory_chain(root, label="qualification checkout")
    root_identity = tuple((os.fspath(path), identity) for _fd, path, identity in chain)
    _close_directory_chain(chain)
    try:
        top = _git_command_bytes(
            root,
            ["rev-parse", "--show-toplevel"],
            "qualification checkout root",
        ).decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise QualificationError("qualification checkout root is invalid") from exc
    _require(
        _absolute_lexical_path(Path(top), "qualification Git root") == root,
        "qualification checkout must be the Git root",
    )
    commit = _git_commit(root)
    sources = []
    for relative in _QUALIFICATION_SOURCE_PATHS:
        mode, object_id, committed_raw = _committed_qualification_file(
            root, commit, relative
        )
        path = root / Path(relative)
        raw, identity, digest = _file_snapshot(
            path,
            label="qualification source %s" % relative,
            maximum=_MAX_JSON_BYTES,
            private=False,
        )
        executable = bool(identity[2] & 0o111)
        _require(
            raw == committed_raw
            and executable == (mode == "100755"),
            "qualification source differs from HEAD: %s" % relative,
        )
        sources.append((relative, path, identity, digest, mode, object_id))
    _require(
        _git_commit(root) == commit,
        "qualification checkout changed while it was inspected",
    )
    executable_record = [
        record
        for record in sources
        if record[0] == _QUALIFICATION_EXECUTABLE_RELATIVE
    ]
    _require(len(executable_record) == 1, "qualification executable is missing")
    _relative, executable, executable_identity, executable_digest, _mode, _oid = (
        executable_record[0]
    )
    return {
        "root": root,
        "root_identity": root_identity,
        "commit": commit,
        "sources": tuple(sources),
        "executable": executable,
        "executable_identity": executable_identity,
        "executable_sha256": executable_digest,
    }


def _inside(path: Path, directory: Path) -> bool:
    try:
        return os.path.commonpath((os.fspath(path), os.fspath(directory))) == os.fspath(directory)
    except ValueError:
        return False


def _remove_created(parent_fd: int, name: str, identity: tuple[int, int] | None) -> None:
    try:
        visible = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if identity is not None and (visible.st_dev, visible.st_ino) != identity:
            return
        os.unlink(name, dir_fd=parent_fd)
        try:
            os.fsync(parent_fd)
        except OSError:
            pass
    except OSError:
        pass


def _write_exclusive(
    path: Path, raw: bytes, *, post_write_check: Callable[[], None] | None = None
) -> None:
    output = _absolute_lexical_path(path, "evidence output")
    _require(output.name not in ("", ".", ".."), "evidence output name is unsafe")
    chain = _open_directory_chain(output.parent, label="evidence output parent")
    parent_fd = chain[-1][0]
    descriptor = -1
    reader = -1
    created = False
    preserve = False
    created_identity: tuple[int, int] | None = None
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        _verify_directory_chain(chain, "evidence output parent")
        try:
            descriptor = os.open(output.name, flags, 0o600, dir_fd=parent_fd)
        except FileExistsError as exc:
            raise QualificationError("evidence output already exists") from exc
        created = True
        opened = os.fstat(descriptor)
        created_identity = opened.st_dev, opened.st_ino
        _require(stat.S_ISREG(opened.st_mode), "evidence output is unsafe")
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise OSError("short evidence write")
            offset += written
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        _require(
            stat.S_ISREG(after.st_mode)
            and stat.S_IMODE(after.st_mode) == 0o600
            and after.st_nlink == 1
            and after.st_size == len(raw)
            and (after.st_dev, after.st_ino) == created_identity,
            "evidence output is unsafe",
        )
        os.close(descriptor)
        descriptor = -1
        _verify_directory_chain(chain, "evidence output parent")
        read_flags = os.O_RDONLY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            read_flags |= os.O_CLOEXEC
        reader = os.open(output.name, read_flags, dir_fd=parent_fd)
        written, written_identity = _read_open_regular(
            reader,
            label="evidence output",
            maximum=_MAX_JSON_BYTES,
            private=True,
        )
        _require(written == raw and (written_identity[0], written_identity[1]) == created_identity, "evidence write verification failed")
        os.close(reader)
        reader = -1
        if post_write_check is not None:
            post_write_check()
        _verify_directory_chain(chain, "evidence output parent")
        reader = os.open(output.name, read_flags, dir_fd=parent_fd)
        final_raw, final_identity = _read_open_regular(
            reader,
            label="evidence output",
            maximum=_MAX_JSON_BYTES,
            private=True,
        )
        _require(
            final_raw == raw
            and (final_identity[0], final_identity[1]) == created_identity,
            "evidence output changed before publication completed",
        )
        os.close(reader)
        reader = -1
        _verify_directory_chain(chain, "evidence output parent")
        preserve = True
        try:
            os.fsync(parent_fd)
        except OSError:
            pass
    except QualificationError:
        raise
    except OSError as exc:
        raise QualificationError("evidence output could not be created safely") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if reader >= 0:
            os.close(reader)
        if created and not preserve:
            _remove_created(parent_fd, output.name, created_identity)
        _close_directory_chain(chain)


def _same_file_snapshot(path: Path, prior, *, label: str, maximum: int, private: bool) -> None:
    current = _file_snapshot(path, label=label, maximum=maximum, private=private)
    _require(current == prior, "%s changed before publication completed" % label)


def _same_candidate(candidate_dir: Path, profile_id: str, prior) -> None:
    current = _candidate_snapshot(candidate_dir, profile_id)
    for key in (
        "candidate",
        "candidate_identity",
        "release_identity",
        "release_sha256",
        "artifact",
        "artifact_identity",
        "install_sha256",
        "source_commit",
    ):
        _require(current[key] == prior[key], "candidate changed before publication completed")


def _same_qualification(root: Path, prior) -> None:
    current = _qualification_snapshot(root)
    for key in (
        "root",
        "root_identity",
        "commit",
        "sources",
        "executable",
        "executable_identity",
        "executable_sha256",
    ):
        _require(current[key] == prior[key], "qualification checkout changed before publication completed")


def _validation_from(candidate, qualification):
    profile_id = candidate["profile_id"] if "profile_id" in candidate else None
    _require(profile_id in PROFILE_TARGETS, "candidate profile is unsupported")
    return {
        "expected_profile_id": profile_id,
        "expected_target": PROFILE_TARGETS[profile_id],
        "expected_version": _VERSION,
        "expected_source_commit": candidate["source_commit"],
        "candidate_release_json_sha256": candidate["release_sha256"],
        "expected_install_sha256": candidate["install_sha256"],
        "expected_qualification_source_commit": qualification["commit"],
        "expected_qualification_executable_sha256": qualification["executable_sha256"],
    }


def create_workspace_receipt(
    candidate_dir,
    profile_id,
    observation_kind,
    raw_boot_log,
    output_path,
    qualification_repo_root,
):
    """Create one exclusive candidate-bound workspace observation receipt."""

    _require(observation_kind in WORKSPACE_PROVISIONING_ORDER, "workspace observation kind is unsupported")
    output = _absolute_lexical_path(Path(output_path), "workspace receipt output")
    raw_path = _absolute_lexical_path(Path(raw_boot_log), "workspace raw boot log")
    _require(output.suffix == ".json", "workspace receipt output must end in .json")
    _require(raw_path == _workspace_raw_path(output), "workspace raw boot log name must be derived from its receipt")
    candidate = _candidate_snapshot(Path(candidate_dir), profile_id)
    candidate["profile_id"] = profile_id
    qualification = _qualification_snapshot(Path(qualification_repo_root))
    _require(not _inside(output, candidate["candidate"]), "workspace receipt output must be outside the candidate")
    _require(not _inside(raw_path, candidate["candidate"]), "workspace raw log must be outside the candidate")
    _require(
        not _inside(output, qualification["root"]),
        "workspace receipt output must be outside the qualification checkout",
    )
    _require(
        not _inside(raw_path, qualification["root"]),
        "workspace raw log must be outside the qualification checkout",
    )
    raw_snapshot = _file_snapshot(
        raw_path,
        label="workspace raw boot log",
        maximum=_MAX_LOG_BYTES,
        private=True,
    )
    _validate_exact_json_lines(
        raw_snapshot[0],
        _expected_workspace_values(observation_kind),
        "workspace raw boot log",
    )
    validation = _validation_from(candidate, qualification)
    value = {
        "schema_version": 1,
        "measurement_contract": _RECEIPT_CONTRACT,
        "observation_kind": observation_kind,
        "profile_id": profile_id,
        "target": PROFILE_TARGETS[profile_id],
        "firmware_version": _VERSION,
        "source_commit": candidate["source_commit"],
        "candidate_release_json_sha256": candidate["release_sha256"],
        "install_sha256": candidate["install_sha256"],
        "qualification_source_commit": qualification["commit"],
        "qualification_executable_sha256": qualification["executable_sha256"],
        "raw_log_sha256": raw_snapshot[2],
        "status": "passed",
    }
    validate_workspace_receipt_payload(
        value, observation_kind=observation_kind, **validation
    )
    encoded = canonical_json_bytes(value)

    def unchanged() -> None:
        _same_candidate(Path(candidate_dir), profile_id, candidate)
        _same_qualification(Path(qualification_repo_root), qualification)
        _same_file_snapshot(
            raw_path,
            raw_snapshot,
            label="workspace raw boot log",
            maximum=_MAX_LOG_BYTES,
            private=True,
        )

    _write_exclusive(output, encoded, post_write_check=unchanged)
    return Path(output_path)


def _require_private_evidence_outside(
    path: Path, *, label: str, candidate: dict[str, Any], qualification: dict[str, Any]
) -> None:
    _require(
        not _inside(path, candidate["candidate"]),
        "%s must be outside the candidate" % label,
    )
    _require(
        not _inside(path, qualification["root"]),
        "%s must be outside the qualification checkout" % label,
    )


def preflight_result_inputs(
    candidate_dir,
    profile_id,
    workspace_erased_receipt,
    workspace_nonblank_receipt,
    qualification_repo_root,
):
    """Validate and lease every long-lived input before physical BLE work."""

    candidate_path = Path(candidate_dir)
    qualification_root = Path(qualification_repo_root)
    candidate = _candidate_snapshot(candidate_path, profile_id)
    candidate["profile_id"] = profile_id
    qualification = _qualification_snapshot(qualification_root)
    validation = _validation_from(candidate, qualification)
    erased_path = _absolute_lexical_path(
        Path(workspace_erased_receipt), "erased workspace receipt"
    )
    nonblank_path = _absolute_lexical_path(
        Path(workspace_nonblank_receipt), "nonblank workspace receipt"
    )
    _require(erased_path != nonblank_path, "workspace receipts must be separate files")
    for receipt_path in (erased_path, nonblank_path):
        _require_private_evidence_outside(
            receipt_path,
            label="workspace receipt",
            candidate=candidate,
            qualification=qualification,
        )
        _require_private_evidence_outside(
            _workspace_raw_path(receipt_path),
            label="workspace raw log",
            candidate=candidate,
            qualification=qualification,
        )
    erased_summary, erased_snapshot = _workspace_receipt_file_snapshot(
        erased_path, WORKSPACE_PROVISIONING_ORDER[0], validation
    )
    nonblank_summary, nonblank_snapshot = _workspace_receipt_file_snapshot(
        nonblank_path, WORKSPACE_PROVISIONING_ORDER[1], validation
    )
    return _ResultInputPreflight(
        candidate_dir=candidate_path,
        profile_id=profile_id,
        candidate=candidate,
        qualification_root=qualification_root,
        qualification=qualification,
        validation=validation,
        erased_path=erased_path,
        erased_summary=erased_summary,
        erased_snapshot=erased_snapshot,
        nonblank_path=nonblank_path,
        nonblank_summary=nonblank_summary,
        nonblank_snapshot=nonblank_snapshot,
    )


def revalidate_result_inputs(preflight):
    """Reopen the exact leased inputs; a caller cannot substitute a new set."""

    _require(
        type(preflight) is _ResultInputPreflight,
        "hardening result preflight token is invalid",
    )
    _same_candidate(
        preflight.candidate_dir,
        preflight.profile_id,
        preflight.candidate,
    )
    _same_qualification(
        preflight.qualification_root,
        preflight.qualification,
    )
    for receipt_path, prior, kind, wanted_summary in (
        (
            preflight.erased_path,
            preflight.erased_snapshot,
            WORKSPACE_PROVISIONING_ORDER[0],
            preflight.erased_summary,
        ),
        (
            preflight.nonblank_path,
            preflight.nonblank_snapshot,
            WORKSPACE_PROVISIONING_ORDER[1],
            preflight.nonblank_summary,
        ),
    ):
        for evidence_path, evidence_snapshot in prior:
            _same_file_snapshot(
                evidence_path,
                evidence_snapshot,
                label="workspace evidence",
                maximum=(
                    _MAX_JSON_BYTES
                    if evidence_path.suffix == ".json"
                    else _MAX_LOG_BYTES
                ),
                private=True,
            )
        summary, current = _workspace_receipt_file_snapshot(
            receipt_path, kind, preflight.validation
        )
        _require(
            summary == wanted_summary and current == prior,
            "workspace evidence changed before publication completed",
        )
    return preflight


def create_result_from_preflight(
    preflight,
    scenario_results,
    raw_log,
    output_path,
):
    """Publish one result from the exact pre-BLE input lease."""

    revalidate_result_inputs(preflight)
    output = _absolute_lexical_path(Path(output_path), "hardening result output")
    raw_path = _absolute_lexical_path(Path(raw_log), "hardening raw log")
    _require(output.suffix == ".json", "hardening result output must end in .json")
    _require(raw_path.suffix == ".jsonl", "hardening raw log must end in .jsonl")
    _require(output != raw_path, "hardening result and raw log must differ")
    for path, label in ((output, "hardening result"), (raw_path, "hardening raw log")):
        _require_private_evidence_outside(
            path,
            label=label,
            candidate=preflight.candidate,
            qualification=preflight.qualification,
        )
    raw_snapshot = _file_snapshot(
        raw_path,
        label="hardening raw log",
        maximum=_MAX_LOG_BYTES,
        private=True,
    )
    _validate_exact_json_lines(
        raw_snapshot[0], _expected_scenario_log(), "hardening raw log"
    )
    value = {
        "schema_version": 1,
        "measurement_contract": _RESULT_CONTRACT,
        "profile_id": preflight.profile_id,
        "target": PROFILE_TARGETS[preflight.profile_id],
        "firmware_version": _VERSION,
        "source_commit": preflight.candidate["source_commit"],
        "candidate_release_json_sha256": preflight.candidate["release_sha256"],
        "install_sha256": preflight.candidate["install_sha256"],
        "qualification_source_commit": preflight.qualification["commit"],
        "qualification_executable_sha256": preflight.qualification[
            "executable_sha256"
        ],
        "scenario_order": list(SCENARIO_ORDER),
        "scenarios": scenario_results,
        "workspace_provisioning": {
            WORKSPACE_PROVISIONING_ORDER[0]: preflight.erased_summary,
            WORKSPACE_PROVISIONING_ORDER[1]: preflight.nonblank_summary,
        },
        "raw_log_sha256": raw_snapshot[2],
        "status": "passed",
    }
    validate_result_payload(value, **preflight.validation)
    encoded = canonical_json_bytes(value)

    def unchanged() -> None:
        revalidate_result_inputs(preflight)
        _same_file_snapshot(
            raw_path,
            raw_snapshot,
            label="hardening raw log",
            maximum=_MAX_LOG_BYTES,
            private=True,
        )

    _write_exclusive(output, encoded, post_write_check=unchanged)
    return Path(output_path)


def create_result(
    candidate_dir,
    profile_id,
    scenario_results,
    workspace_erased_receipt,
    workspace_nonblank_receipt,
    raw_log,
    output_path,
    qualification_repo_root,
):
    """Create the exclusive private seven-scenario hardening result."""

    preflight = preflight_result_inputs(
        candidate_dir=candidate_dir,
        profile_id=profile_id,
        workspace_erased_receipt=workspace_erased_receipt,
        workspace_nonblank_receipt=workspace_nonblank_receipt,
        qualification_repo_root=qualification_repo_root,
    )
    return create_result_from_preflight(
        preflight=preflight,
        scenario_results=scenario_results,
        raw_log=raw_log,
        output_path=output_path,
    )


__all__ = (
    "QualificationError",
    "PROFILE_TARGETS",
    "SCENARIO_ORDER",
    "WORKSPACE_PROVISIONING_ORDER",
    "RESULT_KEYS",
    "PUBLIC_SUMMARY_KEYS",
    "WORKSPACE_RECEIPT_KEYS",
    "canonical_json_bytes",
    "validate_workspace_receipt_payload",
    "validate_workspace_receipt_file",
    "validate_result_payload",
    "validate_result_file",
    "create_workspace_receipt",
    "preflight_result_inputs",
    "revalidate_result_inputs",
    "create_result_from_preflight",
    "create_result",
)
