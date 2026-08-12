#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Pure validation boundary for the private Waveshare LCD qualification.

The real-board runner owns transport and operator interaction.  This module is
standard-library-only and owns the immutable result contract consumed at
release finalization.  It deliberately returns a small public summary: the
private result, session identifier, and detailed observations never enter a
release bundle.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any


def _stable_source_bytes(path: Path) -> tuple[bytes, tuple[int, ...]]:
    """Read one source file without following names or accepting drift."""

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(os.fspath(path), flags)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > 1024 * 1024
        ):
            raise RuntimeError("qualification validator source is unsafe")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            raw = stream.read(1024 * 1024 + 1)
            stream.seek(0)
            repeated = stream.read(1024 * 1024 + 1)
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
    if (
        len(raw) != before.st_size
        or raw != repeated
        or any(getattr(before, key) != getattr(after, key) for key in fields)
    ):
        raise RuntimeError("qualification validator source changed while read")
    return raw, tuple(getattr(before, key) for key in fields)


_IMPORTED_SOURCE_PATH = Path(__file__).resolve(strict=True)
_IMPORTED_SOURCE_BYTES, _IMPORTED_SOURCE_IDENTITY = _stable_source_bytes(
    _IMPORTED_SOURCE_PATH
)
_IMPORTED_SOURCE_SHA256 = hashlib.sha256(_IMPORTED_SOURCE_BYTES).hexdigest()


class QualificationError(RuntimeError):
    """The private result or its release binding is invalid."""


PROFILE_ID = "waveshare-esp32-s3-lcd-147b"
BOARD_MODEL = "ESP32-S3-LCD-1.47B"
EXPECTED_CHIP = "esp32-s3"
EXPECTED_MPY_VERSION = "1.28.0"
RESULT_SCHEMA_VERSION = 1
SUMMARY_SCHEMA_VERSION = 1
FLASH_CAPACITY_BYTES = 16 * 1024 * 1024
PSRAM_CAPACITY_BYTES = 8 * 1024 * 1024
APPLICATION_OFFSET = 0x10000
BOOT_PARTITION_IMMUTABLE_END = 0x9000
FACTORY_APPLICATION_END = 0x210000
WIDTH = 172
HEIGHT = 320
X_OFFSET = 34
Y_OFFSET = 0
REFRESH_COUNT = 6
MIN_RESPONSIVE_PROBES = 3
MIN_RUNTIME_VISIBLE_PSRAM_BYTES = 7 * 1024 * 1024
FRAMEBUFFER_BYTES = WIDTH * HEIGHT * 2
MAX_SPLASH_HEAP_DRIFT_BYTES = 8192
SPLASH_PATTERN_ID = "waveshare-lcd147b-pyble-boot-splash-v1"
TFT_VISUAL_PATTERN_ID = "st7789-172x320-border-rgb-corners-text-progress-v1"
MAX_RESULT_BYTES = 4 * 1024 * 1024
EXPECTED_QR_SIZE_BYTES = 2424
EXPECTED_QR_SHA256 = (
    "4ab6c814a8526c4d69a3b330dc563298edf5bf7eadbea4babd262fa75568e305"
)
EXPECTED_REDIRECT = "/app?pyble_hil=1"
RECORD_STAGES = (
    "candidate-verification",
    "setup-disabled",
    "setup-enabled",
    "exercise",
    "cycle-1",
    "cycle-2",
    "cycle-3",
)
DISABLED_BOOT_EVIDENCE = (
    ("guard-enter",),
    ("enabled", False),
    ("return", False),
)
SUCCESS_BOOT_EVIDENCE = (
    ("guard-enter",),
    ("enabled", True),
    ("wait-ready", 1500, True),
    ("display-start",),
    ("frame-show",),
    ("resources-released",),
    ("wait-ready", 0, True),
    ("backlight-high",),
    ("return", True),
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SESSION_RE = re.compile(r"^[0-9a-f]{32}$")
_BLE_MAC_RE = re.compile(
    rb"(?i)(?<![0-9a-f])[0-9a-f]{2}([:-])"
    rb"(?:[0-9a-f]{2}\1){4}[0-9a-f]{2}(?![0-9a-f])"
)
_IDENTITY_ASSIGNMENT_RE = re.compile(rb"(?i)\b(?:address|label)\s*[:=]")
_SEMVER_IDENTIFIER = r"(?:0|[1-9][0-9]*|[A-Za-z-][0-9A-Za-z-]*)"
_SEMVER_BUILD_IDENTIFIER = r"[0-9A-Za-z-]+"
_SEMVER = (
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    r"(?:-" + _SEMVER_IDENTIFIER + r"(?:\." + _SEMVER_IDENTIFIER + r")*)?"
    r"(?:\+" + _SEMVER_BUILD_IDENTIFIER + r"(?:\." + _SEMVER_BUILD_IDENTIFIER + r")*)?"
)
_SEMVER_RE = re.compile(r"^" + _SEMVER + r"$")
_RELEASE_PATH_RE = re.compile(r"^/firmware/v" + _SEMVER + r"/release\.json$")
_TOP_KEYS = {
    "schema_version",
    "status",
    "stage",
    "profile_id",
    "board_model",
    "firmware_version",
    "session_id",
    "candidate_firmware_sha256",
    "candidate_firmware_size_bytes",
    "candidate_attestation",
    "production_app_evidence",
    "binding",
    "records",
    "setup",
    "exercise",
    "cycles",
    "resource_reclamation",
    "qualification",
    "terminal_record_sha256",
    "record_sha256",
}
_BINDING_KEYS = {
    "session_id",
    "candidate_firmware_sha256",
    "candidate_firmware_size_bytes",
    "candidate_attestation",
    "production_app_evidence",
}
_RECORD_COMMON_KEYS = {
    "ordinal",
    "stage",
    "session_id",
    "candidate_firmware_sha256",
    "candidate_firmware_size_bytes",
    "candidate_attestation",
    "predecessor_sha256",
    "record_sha256",
}
_STAGE_KEYS = {
    "candidate-verification": {"stage_result", "run_summary"},
    "setup-disabled": {
        "pre_reboot",
        "soft_reboot_acknowledged",
        "old_connection_closed",
        "reconnect_attempts",
        "post_reboot",
        "operator_observation",
    },
    "setup-enabled": {
        "pre_reboot",
        "soft_reboot_acknowledged",
        "old_connection_closed",
        "reconnect_attempts",
        "post_reboot",
        "operator_observation",
    },
    "exercise": {"stage_result", "run_summary", "operator_observation"},
    "cycle-1": {
        "cycle",
        "pre_reboot",
        "soft_reboot_acknowledged",
        "old_connection_closed",
        "reconnect_attempts",
        "post_reboot",
        "operator_observation",
        "final_disable",
    },
    "cycle-2": {
        "cycle",
        "pre_reboot",
        "soft_reboot_acknowledged",
        "old_connection_closed",
        "reconnect_attempts",
        "post_reboot",
        "operator_observation",
        "final_disable",
    },
    "cycle-3": {
        "cycle",
        "pre_reboot",
        "soft_reboot_acknowledged",
        "old_connection_closed",
        "reconnect_attempts",
        "post_reboot",
        "operator_observation",
        "final_disable",
    },
}
_RUN_KEYS = {
    "stdout_bytes",
    "stdout_marker_bytes",
    "stderr_bytes",
    "state_sequence",
}
_SUMMARY_KEYS = {
    "schema_version",
    "status",
    "profile_id",
    "board_model",
    "firmware_version",
    "candidate_release_json_sha256",
    "candidate_firmware_sha256",
    "candidate_firmware_size_bytes",
    "candidate_attestation_sha256",
    "candidate_attestation_size_bytes",
    "production_app_evidence_sha256",
    "production_app_active_release_path",
    "terminal_record_sha256",
    "qualification_result_sha256",
}
_PRIVATE_TOKENS = (
    b'"address"',
    b'"ble_address"',
    b'"device_id"',
    b'"label"',
    b'"raw_info"',
    b'"raw_output"',
    b'"stdout_chunks"',
    b'"source"',
    b"__PYBLE_SPLASH_VM_EPOCH_V1__",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationError(message)


def _exact_dict(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == keys, "%s shape changed" % label)
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    """Return the runner's frozen canonical JSON representation."""

    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
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


def _strict_result_value(raw: bytes) -> dict[str, Any]:
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
    _require(raw == canonical_json_bytes(value), "qualification result is not canonical")
    _require(type(value) is dict, "qualification result must be a JSON object")
    return value


def _stable_private_result_with_identity(
    path: Path,
) -> tuple[bytes, tuple[int, ...]]:
    source = Path(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(os.fspath(source), flags)
    except OSError as exc:
        raise QualificationError("qualification result is missing or unsafe") from exc
    try:
        before = os.fstat(descriptor)
        _require(
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and stat.S_IMODE(before.st_mode) == 0o600,
            "qualification result must be one exclusive mode-0600 regular file",
        )
        _require(
            0 < before.st_size <= MAX_RESULT_BYTES,
            "qualification result size is outside its bound",
        )
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            raw = stream.read(MAX_RESULT_BYTES + 1)
            stream.seek(0)
            repeated = stream.read(MAX_RESULT_BYTES + 1)
            after = os.fstat(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    identity = (
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
        and repeated == raw
        and all(getattr(before, key) == getattr(after, key) for key in identity),
        "qualification result changed while it was read",
    )
    return raw, tuple(getattr(before, key) for key in identity)


def _stable_private_result(path: Path) -> bytes:
    return _stable_private_result_with_identity(path)[0]


def private_result_snapshot(path: Path) -> tuple[Any, ...]:
    """Return the immutable identity used for whole-finalization rechecks."""

    raw, identity = _stable_private_result_with_identity(Path(path))
    return identity + (hashlib.sha256(raw).hexdigest(),)


def _stable_firmware(path: Path) -> bytes:
    source = Path(path)
    _require(source.name == "firmware.bin", "candidate image must be named firmware.bin")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(os.fspath(source), flags)
    except OSError as exc:
        raise QualificationError("candidate firmware.bin is missing or unsafe") from exc
    try:
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode), "candidate firmware.bin is not regular")
        _require(
            APPLICATION_OFFSET < before.st_size <= FACTORY_APPLICATION_END,
            "candidate firmware.bin size is outside the factory image",
        )
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            raw = stream.read(FACTORY_APPLICATION_END + 1)
            stream.seek(0)
            repeated = stream.read(FACTORY_APPLICATION_END + 1)
            after = os.fstat(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    identity = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    _require(
        len(raw) == before.st_size
        and repeated == raw
        and all(getattr(before, key) == getattr(after, key) for key in identity),
        "candidate firmware.bin changed while it was read",
    )
    _require(
        raw[BOOT_PARTITION_IMMUTABLE_END:APPLICATION_OFFSET]
        == b"\xff" * (APPLICATION_OFFSET - BOOT_PARTITION_IMMUTABLE_END),
        "candidate NVS/PHY-init image bytes are not erased",
    )
    return raw


def _validate_gate_source(repo_root: Path) -> None:
    """Bind this validator to the exact source in the audited repository."""

    try:
        root = Path(repo_root).resolve(strict=True)
        source = (
            root
            / "firmware"
            / "qualification"
            / "waveshare_lcd147b_release_gate.py"
        )
        source.lstat()
        loaded = Path(__file__).resolve(strict=True)
        audited_bytes, _audited_identity = _stable_source_bytes(source)
        loaded_bytes, loaded_identity = _stable_source_bytes(loaded)
    except OSError as exc:
        raise QualificationError(
            "audited LCD qualification validator source is unavailable"
        ) from exc
    except RuntimeError as exc:
        raise QualificationError(
            "audited LCD qualification validator source is unstable"
        ) from exc
    _require(
        root.is_dir()
        and loaded == _IMPORTED_SOURCE_PATH
        and loaded_identity == _IMPORTED_SOURCE_IDENTITY
        and hashlib.sha256(loaded_bytes).hexdigest() == _IMPORTED_SOURCE_SHA256
        and hashlib.sha256(audited_bytes).hexdigest() == _IMPORTED_SOURCE_SHA256,
        "loaded LCD qualification validator differs from imported/audited source",
    )


def validate_loaded_source(repo_root: Path) -> None:
    """Recheck the executing validator against its import-time audited bytes."""

    _validate_gate_source(Path(repo_root))


def _candidate_measurement(raw: bytes) -> dict[str, Any]:
    spans = [
        {"offset": 0, "size_bytes": BOOT_PARTITION_IMMUTABLE_END},
        {"offset": APPLICATION_OFFSET, "size_bytes": len(raw) - APPLICATION_OFFSET},
    ]
    immutable = b"".join(
        raw[item["offset"] : item["offset"] + item["size_bytes"]]
        for item in spans
    )
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "attestation": {
            "sha256": hashlib.sha256(immutable).hexdigest(),
            "size_bytes": len(immutable),
            "spans": spans,
        },
    }


def _validate_attestation(value: Any, candidate_size: int) -> dict[str, Any]:
    item = _exact_dict(value, {"sha256", "size_bytes", "spans"}, "attestation")
    _require(
        type(item["sha256"]) is str and _SHA256_RE.fullmatch(item["sha256"]) is not None,
        "attestation digest is invalid",
    )
    expected_spans = [
        {"offset": 0, "size_bytes": BOOT_PARTITION_IMMUTABLE_END},
        {"offset": APPLICATION_OFFSET, "size_bytes": candidate_size - APPLICATION_OFFSET},
    ]
    _require(item["spans"] == expected_spans, "attestation span map changed")
    expected_size = sum(span["size_bytes"] for span in expected_spans)
    _require(
        type(item["size_bytes"]) is int and item["size_bytes"] == expected_size,
        "attestation byte count changed",
    )
    return item


def _validate_artifact(value: Any, label: str, maximum: int) -> None:
    item = _exact_dict(value, {"status", "size_bytes", "sha256"}, label)
    _require(type(item["status"]) is int and item["status"] == 200, "%s status changed" % label)
    _require(
        type(item["size_bytes"]) is int and 0 < item["size_bytes"] <= maximum,
        "%s size changed" % label,
    )
    _require(
        type(item["sha256"]) is str and _SHA256_RE.fullmatch(item["sha256"]) is not None,
        "%s digest changed" % label,
    )


def _validate_production_app(value: Any) -> dict[str, Any]:
    keys = {
        "schema_version",
        "app",
        "qr",
        "flash",
        "normalized_redirect",
        "link_facts",
        "active_release_path",
    }
    item = _exact_dict(value, keys, "production app evidence")
    _require(item["schema_version"] == 1, "production app schema changed")
    _validate_artifact(item["app"], "app evidence", 512 * 1024)
    _validate_artifact(item["qr"], "QR evidence", 256 * 1024)
    _validate_artifact(item["flash"], "flash evidence", 512 * 1024)
    _require(
        item["qr"]["size_bytes"] == EXPECTED_QR_SIZE_BYTES
        and item["qr"]["sha256"] == EXPECTED_QR_SHA256,
        "production QR evidence is not the reviewed asset",
    )
    _require(
        item["normalized_redirect"]
        == {"status": 308, "location": EXPECTED_REDIRECT},
        "production app redirect evidence changed",
    )
    facts = _exact_dict(
        item["link_facts"],
        {
            "main_content",
            "testflight_href",
            "testflight_visible_fallback",
            "flash_href",
            "support_href",
            "qr_src",
        },
        "production app link facts",
    )
    _require(all(value is True for value in facts.values()), "production app link fact changed")
    _require(
        type(item["active_release_path"]) is str
        and _RELEASE_PATH_RE.fullmatch(item["active_release_path"]) is not None,
        "production active release path changed",
    )
    return item


def _nonnegative_int(value: Any, label: str) -> int:
    _require(type(value) is int and value >= 0, "%s is not non-negative" % label)
    return value


def _positive_int(value: Any, label: str, *, allow_zero: bool = False) -> int:
    _require(
        type(value) is int and (value > 0 or (allow_zero and value == 0)),
        "%s is outside its allowed range" % label,
    )
    return value


def _validate_runtime_memory(value: Any) -> None:
    memory = _exact_dict(
        value,
        {
            "flash_size_bytes",
            "psram_idf_heap_region_bytes",
            "gc_free_bytes",
            "gc_allocated_bytes",
        },
        "runtime memory",
    )
    checked = {
        key: _nonnegative_int(item, "runtime memory %s" % key)
        for key, item in memory.items()
    }
    _require(
        checked["flash_size_bytes"] == FLASH_CAPACITY_BYTES,
        "runtime flash capacity changed",
    )
    visible = max(
        checked["psram_idf_heap_region_bytes"],
        checked["gc_free_bytes"] + checked["gc_allocated_bytes"],
    )
    _require(
        visible >= MIN_RUNTIME_VISIBLE_PSRAM_BYTES,
        "runtime PSRAM-backed memory proof changed",
    )


def _validate_redacted_stage(
    value: Any,
    stage: str,
    extra_keys: set[str],
    label: str,
    expected_version: str,
    expected_runtime_identity: tuple[Any, ...] | None = None,
) -> tuple[Any, ...]:
    base_keys = {
        "schema_version",
        "status",
        "stage",
        "profile_id",
        "board_model",
        "preflight",
        "runtime",
    }
    item = _exact_dict(value, base_keys | extra_keys, label)
    _require(
        type(item["schema_version"]) is int
        and item["schema_version"] == RESULT_SCHEMA_VERSION
        and item["status"] == "passed"
        and item["stage"] == stage
        and item["profile_id"] == PROFILE_ID
        and item["board_model"] == BOARD_MODEL,
        "%s passed identity changed" % label,
    )
    preflight = _exact_dict(
        item["preflight"],
        {
            "chip",
            "flash_capacity_bytes",
            "psram_capacity_bytes",
            "discovery_method",
        },
        "%s preflight" % label,
    )
    _require(
        preflight
        == {
            "chip": EXPECTED_CHIP,
            "flash_capacity_bytes": FLASH_CAPACITY_BYTES,
            "psram_capacity_bytes": PSRAM_CAPACITY_BYTES,
            "discovery_method": "esptool-read-only",
        },
        "%s preflight identity changed" % label,
    )
    runtime = _exact_dict(
        item["runtime"],
        {"proto", "agent", "chip", "mpy", "mtu", "window", "chunk", "free_mem_bytes"},
        "%s runtime" % label,
    )
    _require(
        type(runtime["proto"]) is int
        and runtime["proto"] == 1
        and type(runtime["agent"]) is str
        and runtime["agent"] == expected_version
        and type(runtime["chip"]) is str
        and runtime["chip"] == EXPECTED_CHIP
        and type(runtime["mpy"]) is str
        and runtime["mpy"] == EXPECTED_MPY_VERSION,
        "%s runtime identity changed" % label,
    )
    for key in ("mtu", "window", "chunk"):
        _positive_int(runtime[key], "%s runtime %s" % (label, key))
    _positive_int(runtime["free_mem_bytes"], "%s runtime free memory" % label, allow_zero=True)
    identity = (
        runtime["proto"],
        runtime["agent"],
        runtime["chip"],
        runtime["mpy"],
    )
    _require(
        expected_runtime_identity is None or identity == expected_runtime_identity,
        "%s runtime identity drifted" % label,
    )
    return identity


def _validate_stage_run(value: Any, label: str) -> None:
    run = _exact_dict(value, {"stdout_bytes", "stderr_bytes", "state_sequence"}, label)
    _positive_int(run["stdout_bytes"], "%s stdout bytes" % label)
    _require(
        type(run["stderr_bytes"]) is int
        and run["stderr_bytes"] == 0
        and run["state_sequence"] == ["running", "done"],
        "%s state changed" % label,
    )


def _validate_candidate_stage(
    value: Any,
    candidate_attestation: dict[str, Any],
    candidate_size: int,
    expected_version: str,
) -> tuple[Any, ...]:
    runtime_identity = _validate_redacted_stage(
        value,
        "candidate-verification",
        {
            "live_immutable_sha256",
            "immutable_bytes_verified",
            "immutable_spans",
            "run",
            "next_stage",
        },
        "candidate verification",
        expected_version,
    )
    live = _validate_attestation(
        {
            "sha256": value["live_immutable_sha256"],
            "size_bytes": value["immutable_bytes_verified"],
            "spans": value["immutable_spans"],
        },
        candidate_size,
    )
    _require(live == candidate_attestation, "live candidate attestation changed")
    _require(value["next_stage"] == "exercise", "candidate next stage changed")
    _validate_stage_run(value["run"], "candidate verification run")
    return runtime_identity


def _validate_exercise_stage(
    value: Any,
    runtime_identity: tuple[Any, ...],
    expected_version: str,
) -> None:
    _validate_redacted_stage(
        value,
        "exercise",
        {"memory", "display", "pble_responsiveness", "run", "next_stage"},
        "exercise",
        expected_version,
        runtime_identity,
    )
    memory = _exact_dict(
        value["memory"],
        {
            "flash_size_bytes",
            "psram_idf_heap_region_bytes",
            "gc_free_bytes",
            "gc_allocated_bytes",
            "hello_free_mem_bytes",
        },
        "exercise memory",
    )
    _validate_runtime_memory(
        {
            key: memory[key]
            for key in (
                "flash_size_bytes",
                "psram_idf_heap_region_bytes",
                "gc_free_bytes",
                "gc_allocated_bytes",
            )
        }
    )
    _positive_int(memory["hello_free_mem_bytes"], "exercise HELLO memory", allow_zero=True)
    _require(
        memory["hello_free_mem_bytes"] == value["runtime"]["free_mem_bytes"],
        "exercise HELLO memory changed",
    )
    display = _exact_dict(
        value["display"],
        {
            "geometry",
            "refreshes_completed",
            "pattern_ready",
            "backlight_sequence",
            "cleanup_completed",
        },
        "exercise display",
    )
    _require(
        display["geometry"] == [WIDTH, HEIGHT, X_OFFSET, Y_OFFSET]
        and type(display["refreshes_completed"]) is int
        and display["refreshes_completed"] == REFRESH_COUNT
        and display["pattern_ready"] is True
        and display["backlight_sequence"] == [False, True, False]
        and display["cleanup_completed"] is True,
        "exercise display evidence changed",
    )
    responsive = _exact_dict(
        value["pble_responsiveness"],
        {"info_reads", "device_info_commands", "refresh_indexes", "while_run_active"},
        "exercise responsiveness",
    )
    info_reads = _positive_int(responsive["info_reads"], "exercise INFO reads")
    device_commands = _positive_int(
        responsive["device_info_commands"], "exercise DEVICE_INFO commands"
    )
    indexes = responsive["refresh_indexes"]
    _require(
        responsive["while_run_active"] is True
        and type(indexes) is list
        and all(type(item) is int for item in indexes)
        and len(indexes) >= MIN_RESPONSIVE_PROBES
        and indexes == sorted(set(indexes))
        and all(0 <= item < REFRESH_COUNT for item in indexes)
        and info_reads == device_commands == len(indexes),
        "exercise responsiveness changed",
    )
    _validate_stage_run(value["run"], "exercise run")
    _require(value["next_stage"] == "soft-reboot", "exercise next stage changed")


def _validate_combined_action(value: Any, kind: str, label: str) -> None:
    keys = {"persisted", "run"}
    if kind == "disable":
        keys.add("darkened")
    elif kind == "arm":
        keys.add("armed")
    else:
        _require(kind == "enable", "combined action kind changed")
    action = _exact_dict(value, keys, label)
    _require(action["persisted"] is True, "%s was not persisted" % label)
    if kind == "disable":
        _require(action["darkened"] is True, "%s did not darken" % label)
    if kind == "arm":
        _require(action["armed"] is True, "%s did not arm" % label)
    _exact_dict(action["run"], _RUN_KEYS, "%s run" % label)
    _validate_run(action["run"])


def _validate_combined_observation(value: Any, phase: str) -> None:
    observation = _exact_dict(
        value,
        {
            "phase",
            "confirmed",
            "pattern_id",
            "scanned_url",
            "before_first_hello",
            "connected_central",
        },
        "%s splash observation" % phase,
    )
    _require(
        observation
        == {
            "phase": phase,
            "confirmed": True,
            "pattern_id": SPLASH_PATTERN_ID,
            "scanned_url": "https://pyble.dev/app",
            "before_first_hello": True,
            "connected_central": True,
        },
        "%s splash observation changed" % phase,
    )


def _validate_combined_post_reboot(
    value: Any,
    phase: str,
    enabled: bool,
    expected_version: str,
) -> dict[str, Any]:
    post = _exact_dict(value, {"probe", "run"}, "%s post reboot" % phase)
    probe = _exact_dict(
        post["probe"],
        {
            "phase",
            "enabled",
            "wait_ready",
            "rendered",
            "backlight_on",
            "firmware_version",
            "gc_free_bytes",
            "runtime_imported",
            "boot_evidence",
        },
        "%s boot probe" % phase,
    )
    trace = SUCCESS_BOOT_EVIDENCE if enabled else DISABLED_BOOT_EVIDENCE
    _require(
        probe["phase"] == phase
        and probe["enabled"] is enabled
        and probe["wait_ready"] is True
        and probe["rendered"] is enabled
        and probe["backlight_on"] is enabled
        and probe["firmware_version"] == expected_version
        and type(probe["gc_free_bytes"]) is int
        and probe["gc_free_bytes"] > 0
        and probe["runtime_imported"] is True
        and probe["boot_evidence"] == [list(item) for item in trace],
        "%s exact boot probe changed" % phase,
    )
    _exact_dict(post["run"], _RUN_KEYS, "%s post-reboot run" % phase)
    _validate_run(post["run"])
    return probe


def _validate_combined_transition(
    record: dict[str, Any],
    phase: str,
    enabled: bool,
    expected_version: str,
) -> dict[str, Any]:
    _require(
        record["soft_reboot_acknowledged"] is True
        and record["old_connection_closed"] is True
        and type(record["reconnect_attempts"]) is int
        and record["reconnect_attempts"] > 0,
        "%s transition changed" % phase,
    )
    return _validate_combined_post_reboot(
        record["post_reboot"], phase, enabled, expected_version
    )


def _splash_reclamation_proof(
    initial_disabled: dict[str, Any],
    enabled_boot: dict[str, Any],
    redraw_boot: dict[str, Any],
) -> dict[str, Any]:
    baseline = initial_disabled["gc_free_bytes"]
    enabled_free = enabled_boot["gc_free_bytes"]
    redraw_free = redraw_boot["gc_free_bytes"]
    enabled_deficit = max(0, baseline - enabled_free)
    redraw_deficit = max(0, baseline - redraw_free)
    _require(
        enabled_deficit <= MAX_SPLASH_HEAP_DRIFT_BYTES
        and redraw_deficit <= MAX_SPLASH_HEAP_DRIFT_BYTES,
        "splash framebuffer was not reclaimed",
    )
    return {
        "disabled_baseline_gc_free_bytes": baseline,
        "enabled_boot_gc_free_bytes": enabled_free,
        "redraw_boot_gc_free_bytes": redraw_free,
        "enabled_boot_free_deficit_bytes": enabled_deficit,
        "redraw_boot_free_deficit_bytes": redraw_deficit,
        "max_drift_bytes": MAX_SPLASH_HEAP_DRIFT_BYTES,
        "framebuffer_bytes": FRAMEBUFFER_BYTES,
        "framebuffer_reclaimed": True,
    }


def _validate_splash_reclamation(
    value: Any,
    initial_disabled: dict[str, Any],
    enabled_boot: dict[str, Any],
    redraw_boot: dict[str, Any],
) -> None:
    expected = _splash_reclamation_proof(
        initial_disabled, enabled_boot, redraw_boot
    )
    _exact_dict(value, set(expected), "splash framebuffer reclamation")
    _require(value == expected, "splash framebuffer reclamation changed")


def _run_summaries(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def visit(item: Any) -> None:
        if type(item) is dict:
            if set(item) == _RUN_KEYS:
                found.append(item)
            else:
                for nested in item.values():
                    visit(nested)
        elif type(item) is list:
            for nested in item:
                visit(nested)

    visit(value)
    return found


def _validate_run(value: dict[str, Any]) -> None:
    _require(
        type(value["stdout_bytes"]) is int
        and value["stdout_bytes"] > 0
        and type(value["stdout_marker_bytes"]) is int
        and value["stdout_marker_bytes"] > 0
        and type(value["stderr_bytes"]) is int
        and value["stderr_bytes"] == 0
        and value["state_sequence"] == ["running", "done"],
        "sanitized RUN evidence changed",
    )


def validate_combined_qualification_result(
    value: Any,
    expected_version: str = "0.5.0",
    *,
    expected_measurement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the exact successful combined HIL evidence contract.

    The hardware runner calls this boundary before it writes evidence.  Release
    finalization calls the same boundary with an independently measured
    ``firmware.bin`` so neither side can drift to a weaker interpretation.
    """

    _require(
        type(expected_version) is str
        and _SEMVER_RE.fullmatch(expected_version) is not None,
        "expected firmware version is invalid",
    )
    result = _exact_dict(value, _TOP_KEYS, "combined qualification")
    _require(
        result["schema_version"] == RESULT_SCHEMA_VERSION
        and result["status"] == "passed"
        and result["stage"] == "combined-qualification"
        and result["profile_id"] == PROFILE_ID
        and result["board_model"] == BOARD_MODEL
        and result["firmware_version"] == expected_version,
        "combined qualification identity changed",
    )
    session = result["session_id"]
    _require(
        type(session) is str and _SESSION_RE.fullmatch(session) is not None,
        "session identity changed",
    )
    candidate_sha256 = result["candidate_firmware_sha256"]
    candidate_size = result["candidate_firmware_size_bytes"]
    _require(
        type(candidate_sha256) is str
        and _SHA256_RE.fullmatch(candidate_sha256) is not None,
        "candidate firmware digest changed",
    )
    _require(
        type(candidate_size) is int
        and APPLICATION_OFFSET < candidate_size <= FACTORY_APPLICATION_END,
        "candidate firmware byte length changed",
    )
    attestation = _validate_attestation(
        result["candidate_attestation"], candidate_size
    )
    if expected_measurement is not None:
        _require(
            expected_measurement
            == {
                "sha256": candidate_sha256,
                "size_bytes": candidate_size,
                "attestation": attestation,
            },
            "combined result identifies different firmware.bin bytes",
        )
    app = _validate_production_app(result["production_app_evidence"])
    binding = _exact_dict(result["binding"], _BINDING_KEYS, "combined binding")
    _require(
        binding
        == {
            "session_id": session,
            "candidate_firmware_sha256": candidate_sha256,
            "candidate_firmware_size_bytes": candidate_size,
            "candidate_attestation": attestation,
            "production_app_evidence": app,
        },
        "combined binding changed",
    )

    records = result["records"]
    _require(type(records) is list and len(records) == len(RECORD_STAGES), "record cardinality changed")
    predecessor = _digest(binding)
    for ordinal, (record, stage_name) in enumerate(zip(records, RECORD_STAGES), 1):
        record = _exact_dict(
            record,
            _RECORD_COMMON_KEYS | _STAGE_KEYS[stage_name],
            "%s record" % stage_name,
        )
        _require(
            type(record["ordinal"]) is int
            and record["ordinal"] == ordinal
            and record["stage"] == stage_name
            and record["session_id"] == session
            and record["candidate_firmware_sha256"] == candidate_sha256
            and type(record["candidate_firmware_size_bytes"]) is int
            and record["candidate_firmware_size_bytes"] == candidate_size
            and record["candidate_attestation"] == attestation
            and record["predecessor_sha256"] == predecessor,
            "%s record binding changed" % stage_name,
        )
        unsigned = dict(record)
        record_digest = unsigned.pop("record_sha256")
        _require(
            type(record_digest) is str
            and _SHA256_RE.fullmatch(record_digest) is not None
            and record_digest == _digest(unsigned),
            "%s record digest changed" % stage_name,
        )
        summaries = _run_summaries(record)
        _require(bool(summaries), "%s record lacks RUN evidence" % stage_name)
        for summary in summaries:
            _validate_run(summary)
        predecessor = record_digest

    candidate_record = records[0]
    runtime_identity = _validate_candidate_stage(
        candidate_record["stage_result"],
        attestation,
        candidate_size,
        expected_version,
    )
    _exact_dict(
        candidate_record["run_summary"],
        _RUN_KEYS,
        "candidate record run",
    )
    _validate_run(candidate_record["run_summary"])

    setup_disabled = records[1]
    _exact_dict(
        setup_disabled["pre_reboot"],
        {"disable", "arm"},
        "setup-disabled pre-reboot",
    )
    _validate_combined_action(
        setup_disabled["pre_reboot"]["disable"],
        "disable",
        "setup-disabled disable",
    )
    _validate_combined_action(
        setup_disabled["pre_reboot"]["arm"],
        "arm",
        "setup-disabled arm",
    )
    _require(
        setup_disabled["operator_observation"] is None,
        "disabled setup contains visual evidence",
    )
    initial_disabled = _validate_combined_transition(
        setup_disabled,
        "setup-disabled",
        False,
        expected_version,
    )

    setup_enabled = records[2]
    _exact_dict(
        setup_enabled["pre_reboot"],
        {"enable", "arm"},
        "setup-enabled pre-reboot",
    )
    _validate_combined_action(
        setup_enabled["pre_reboot"]["enable"],
        "enable",
        "setup-enabled enable",
    )
    _validate_combined_action(
        setup_enabled["pre_reboot"]["arm"],
        "arm",
        "setup-enabled arm",
    )
    enabled_boot = _validate_combined_transition(
        setup_enabled,
        "setup-enabled",
        True,
        expected_version,
    )
    _validate_combined_observation(
        setup_enabled["operator_observation"],
        "setup-enabled",
    )

    exercise = records[3]
    _validate_exercise_stage(
        exercise["stage_result"],
        runtime_identity,
        expected_version,
    )
    _exact_dict(exercise["run_summary"], _RUN_KEYS, "exercise record run")
    _validate_run(exercise["run_summary"])
    operator = _exact_dict(
        exercise["operator_observation"],
        {"confirmed", "pattern_id", "while_run_active", "stdin_release_sent"},
        "TFT operator observation",
    )
    _require(
        operator
        == {
            "confirmed": True,
            "pattern_id": TFT_VISUAL_PATTERN_ID,
            "while_run_active": True,
            "stdin_release_sent": True,
        },
        "TFT live operator observation changed",
    )

    cycle_probes: list[dict[str, Any]] = []
    for index, cycle in enumerate(records[4:], 1):
        _require(
            type(cycle["cycle"]) is int and cycle["cycle"] == index,
            "cycle-%d numbering changed" % index,
        )
        _exact_dict(
            cycle["pre_reboot"],
            {"arm"},
            "cycle-%d pre-reboot" % index,
        )
        _validate_combined_action(
            cycle["pre_reboot"]["arm"],
            "arm",
            "cycle-%d arm" % index,
        )
        cycle_probes.append(
            _validate_combined_transition(
                cycle,
                "cycle-%d" % index,
                index == 1,
                expected_version,
            )
        )
        if index == 1:
            _validate_combined_observation(
                cycle["operator_observation"],
                "cycle-1",
            )
            _validate_combined_action(
                cycle["final_disable"],
                "disable",
                "cycle-1 final disable",
            )
        else:
            _require(
                cycle["operator_observation"] is None
                and cycle["final_disable"] is None,
                "disabled cycle contains visual/disable duplication",
            )

    _exact_dict(result["setup"], {"disabled", "enabled"}, "setup record views")
    _require(
        result["setup"] == {"disabled": setup_disabled, "enabled": setup_enabled}
        and result["exercise"] == exercise
        and result["cycles"] == records[4:],
        "combined record views diverged from their chain",
    )
    _validate_splash_reclamation(
        result["resource_reclamation"],
        initial_disabled,
        enabled_boot,
        cycle_probes[0],
    )
    qualification = _exact_dict(
        result["qualification"],
        {
            "acknowledged_resets",
            "ble_segments",
            "setup_resets",
            "tft_exercises",
            "tft_reboot_cycles",
            "fresh_vm_proofs",
            "operator_splash_observations",
            "terminal_record_sha256",
        },
        "qualification summary",
    )
    expected_counts = {
        "acknowledged_resets": 5,
        "ble_segments": 6,
        "setup_resets": 2,
        "tft_exercises": 1,
        "tft_reboot_cycles": 3,
        "fresh_vm_proofs": 5,
        "operator_splash_observations": 2,
        "terminal_record_sha256": predecessor,
    }
    _require(qualification == expected_counts, "qualification counts or terminal changed")
    _require(result["terminal_record_sha256"] == predecessor, "terminal record changed")
    unsigned_result = dict(result)
    result_digest = unsigned_result.pop("record_sha256")
    _require(
        type(result_digest) is str
        and _SHA256_RE.fullmatch(result_digest) is not None
        and result_digest == _digest(unsigned_result),
        "combined qualification digest changed",
    )
    encoded = canonical_json_bytes(result)
    _require(
        not any(token in encoded for token in _PRIVATE_TOKENS),
        "qualification result contains private/raw evidence",
    )
    return result


def validate_result_file(
    result_path: Path,
    *,
    firmware_path: Path,
    expected_version: str,
    candidate_release_json_sha256: str,
    repo_root: Path,
) -> dict[str, Any]:
    """Validate one exclusive result and derive its non-private release summary."""

    validate_loaded_source(Path(repo_root))
    _require(
        type(candidate_release_json_sha256) is str
        and _SHA256_RE.fullmatch(candidate_release_json_sha256) is not None,
        "candidate release.json digest is invalid",
    )
    raw = _stable_private_result(Path(result_path))
    value = _strict_result_value(raw)
    firmware = _stable_firmware(Path(firmware_path))
    measurement = _candidate_measurement(firmware)
    result = validate_combined_qualification_result(
        value,
        expected_version,
        expected_measurement=measurement,
    )
    app = result["production_app_evidence"]
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "status": "passed",
        "profile_id": PROFILE_ID,
        "board_model": BOARD_MODEL,
        "firmware_version": expected_version,
        "candidate_release_json_sha256": candidate_release_json_sha256,
        "candidate_firmware_sha256": measurement["sha256"],
        "candidate_firmware_size_bytes": measurement["size_bytes"],
        "candidate_attestation_sha256": measurement["attestation"]["sha256"],
        "candidate_attestation_size_bytes": measurement["attestation"]["size_bytes"],
        "production_app_evidence_sha256": _digest(app),
        "production_app_active_release_path": app["active_release_path"],
        "terminal_record_sha256": result["terminal_record_sha256"],
        "qualification_result_sha256": hashlib.sha256(raw).hexdigest(),
    }
    return validate_public_summary(
        summary,
        firmware_path=firmware_path,
        expected_version=expected_version,
        candidate_release_json_sha256=candidate_release_json_sha256,
    )


def validate_public_report_privacy(
    report_bytes: bytes,
    *,
    result_path: Path,
) -> None:
    """Reject any public HIL text containing admitted private-result material."""

    _require(
        type(report_bytes) is bytes and 0 < len(report_bytes) <= MAX_RESULT_BYTES,
        "public HIL report size is outside its privacy bound",
    )
    try:
        report_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise QualificationError("public HIL report is not strict UTF-8") from exc
    private_raw = _stable_private_result(Path(result_path))
    private = _strict_result_value(private_raw)
    normalized_report = report_bytes.lower()
    session = private.get("session_id")
    _require(
        type(session) is str and _SESSION_RE.fullmatch(session) is not None,
        "private qualification session identity changed",
    )
    _require(
        session.encode("ascii") not in normalized_report
        and private_raw not in report_bytes,
        "public HIL report contains private qualification evidence",
    )
    bare_reserved = (
        b"session_id",
        b"raw_output",
        b"raw_info",
        b"stdout_chunks",
        b"ble_address",
        b"device_id",
        b"operator_observation",
        b"resource_reclamation",
        b"boot_evidence",
        b"pre_reboot",
        b"post_reboot",
        b"reconnect_attempts",
        b"stdin_release_sent",
        b"scanned_url",
        b"connected_central",
        b"before_first_hello",
        b"runtime_imported",
        b"framebuffer_reclaimed",
        b"live_immutable_sha256",
        b"pble_responsiveness",
        b"refresh_indexes",
    )
    quoted_reserved = (
        b"address",
        b"binding",
        b"label",
        b"production_app_evidence",
    )
    _require(
        not any(token in normalized_report for token in bare_reserved)
        and _BLE_MAC_RE.search(normalized_report) is None
        and _IDENTITY_ASSIGNMENT_RE.search(normalized_report) is None
        and not any(
            b'"' + token + b'"' in normalized_report
            or b'\\"' + token + b'\\"' in normalized_report
            for token in quoted_reserved
        ),
        "public HIL report contains reserved private evidence fields",
    )


def validate_public_summary(
    value: Any,
    *,
    firmware_path: Path,
    expected_version: str,
    candidate_release_json_sha256: str,
) -> dict[str, Any]:
    """Validate the non-private summary retained by a public release."""

    summary = _exact_dict(value, _SUMMARY_KEYS, "public LCD qualification summary")
    _require(
        summary["schema_version"] == SUMMARY_SCHEMA_VERSION
        and summary["status"] == "passed"
        and summary["profile_id"] == PROFILE_ID
        and summary["board_model"] == BOARD_MODEL
        and summary["firmware_version"] == expected_version,
        "public LCD qualification identity changed",
    )
    _require(
        type(expected_version) is str and _SEMVER_RE.fullmatch(expected_version) is not None,
        "public expected firmware version is invalid",
    )
    _require(
        type(candidate_release_json_sha256) is str
        and _SHA256_RE.fullmatch(candidate_release_json_sha256) is not None
        and summary["candidate_release_json_sha256"] == candidate_release_json_sha256,
        "public LCD qualification candidate-release binding changed",
    )
    measurement = _candidate_measurement(_stable_firmware(Path(firmware_path)))
    _require(
        summary["candidate_firmware_sha256"] == measurement["sha256"]
        and type(summary["candidate_firmware_size_bytes"]) is int
        and summary["candidate_firmware_size_bytes"] == measurement["size_bytes"]
        and summary["candidate_attestation_sha256"]
        == measurement["attestation"]["sha256"]
        and type(summary["candidate_attestation_size_bytes"]) is int
        and summary["candidate_attestation_size_bytes"]
        == measurement["attestation"]["size_bytes"],
        "public LCD qualification candidate bytes changed",
    )
    for key in (
        "production_app_evidence_sha256",
        "terminal_record_sha256",
        "qualification_result_sha256",
    ):
        _require(
            type(summary[key]) is str and _SHA256_RE.fullmatch(summary[key]) is not None,
            "public LCD qualification %s changed" % key,
        )
    _require(
        type(summary["production_app_active_release_path"]) is str
        and _RELEASE_PATH_RE.fullmatch(summary["production_app_active_release_path"])
        is not None,
        "public production-app release path changed",
    )
    return dict(summary)


__all__ = (
    "BOARD_MODEL",
    "PROFILE_ID",
    "QualificationError",
    "canonical_json_bytes",
    "private_result_snapshot",
    "validate_combined_qualification_result",
    "validate_loaded_source",
    "validate_public_report_privacy",
    "validate_public_summary",
    "validate_result_file",
)
