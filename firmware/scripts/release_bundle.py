#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Build and verify PyBLE's immutable browser-flashing release bundle.

The implementation is deliberately standard-library-only.  It does not trust
filenames for offsets or image roles: authoritative ESP-IDF flasher metadata,
ESP image headers, the partition table, and a deterministic reconstruction of
the merged image must all agree before any output is emitted.

Public third-party notices need a reviewed ESP-IDF SBOM/policy pass in addition
to the conservative linked-input inventory implemented here.  Candidate
notices are marked accordingly, and public validation rejects that marker.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import copy
import ctypes
from email.parser import BytesParser
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import shutil
import stat as stat_module
import struct
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from typing import Any
from urllib.parse import urlsplit
import zipfile


def _load_waveshare_lcd147b_gate() -> Any:
    source = (
        Path(__file__).resolve().parents[1]
        / "qualification"
        / "waveshare_lcd147b_release_gate.py"
    ).resolve(strict=True)
    spec = importlib.util.spec_from_file_location(
        "_pyble_release_waveshare_lcd147b_gate",
        source,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the LCD qualification validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_WAVESHARE_LCD147B_GATE = _load_waveshare_lcd147b_gate()


class ReleaseError(RuntimeError):
    """A fail-closed release-contract violation."""


HISTORICAL_V042_RELEASE_PROFILE_ORDER = ("esp32-4mb", "esp32-s3-n16r8")
V05_RELEASE_PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
    "waveshare-esp32-s3-lcd-147b",
)
V060_RELEASE_PROFILE_ORDER = (
    *V05_RELEASE_PROFILE_ORDER,
    "esp32-c3-4mb",
    "rpi-pico2-w",
)
# The unqualified source-selected candidate is v0.6.0.  Source-era helpers
# below retain the immutable v0.4.2 and v0.5.x orders explicitly.
RELEASE_PROFILE_ORDER = V060_RELEASE_PROFILE_ORDER
QUALIFICATION_POLICY_RELATIVE = "firmware/qualification/oi1-gates.json"
QUALIFICATION_BASELINE_RE = re.compile(
    r"^docs/validation/firmware/oi1/"
    r"([0-9a-f]{40})\.json$"
)
QUALIFICATION_V042_BASELINE_RE = re.compile(
    r"^docs/validation/firmware/oi1/"
    r"([0-9a-f]{40})\.json$"
)
QUALIFICATION_WORKLOAD = {
    "reset_samples": 10,
    "reset_hold_ms": 1000,
    "advertising_timeout_ms": 15000,
    "post_hello_heap_samples": 10,
    "roundtrip_samples": 5,
    "roundtrip_payload_bytes": 65536,
    "payload_generator": "sha256-counter-v1",
    "post_roundtrip_heap_samples": 5,
    "reliability_files": 20,
    "reliability_file_bytes": 16384,
    "post_reliability_heap_samples": 1,
    "required_att_mtu": 247,
    "required_put_window": 8,
    "required_chunk_bytes": 229,
}
QUALIFICATION_DERIVATION_V1 = {
    "application_image": "exact-byte-identical-two-root-v1",
    "application_headroom": "factory-minus-application-v1",
    "heap_floor": "floor-min-1024-v1",
    "boot_ceiling": "ceil-max-10-v1",
    "goodput_floor": "floor-min-100-v1",
}
QUALIFICATION_DERIVATION_V2 = {
    "application_image": "exact-byte-identical-two-root-v1",
    "application_headroom": "factory-minus-application-v1",
    "heap_floor": "floor-min-1024-v1",
    "boot_ceiling": "ceil-max-plus-300-10-v2",
    "goodput_floor": "floor-95pct-min-100-v2",
}
QUALIFICATION_DERIVATION_V3 = {
    "application_image": "exact-byte-identical-two-root-v1",
    "application_headroom": "factory-minus-application-v1",
    "heap_floor": "floor-min-1024-v1",
    "boot_ceiling": "fixed-product-slo-3000-v3",
    "goodput_floor": "floor-95pct-min-100-v2",
}
QUALIFICATION_DERIVATION = QUALIFICATION_DERIVATION_V3
QUALIFICATION_THRESHOLD_KEYS = (
    "application_image_max_bytes",
    "application_headroom_min_bytes",
    "gc_free_min_bytes",
    "idf_internal_free_min_bytes",
    "idf_internal_largest_block_min_bytes",
    "idf_internal_minimum_free_min_bytes",
    "reset_to_service_advertisement_max_ms",
    "put_committed_goodput_min_bytes_per_second",
    "get_verified_goodput_min_bytes_per_second",
)
RP2_QUALIFICATION_THRESHOLD_KEYS = (
    "firmware_bin_max_bytes",
    "firmware_image_headroom_min_bytes",
    "gc_free_min_bytes",
    "reset_to_service_advertisement_max_ms",
    "put_committed_goodput_min_bytes_per_second",
    "get_verified_goodput_min_bytes_per_second",
)
RP2_IMAGE_LIMIT_BYTES = 1_572_864
ROLE_ORDER = ("bootloader", "partition-table", "application")
DOCUMENT_KEYS = (
    "third_party_licenses",
    "release_notes",
    "recovery",
    "hil_report",
)
DOCUMENT_PATHS = {
    "third_party_licenses": "THIRD_PARTY_LICENSES.txt",
    "release_notes": "RELEASE_NOTES.md",
    "recovery": "RECOVERY.md",
    "hil_report": "HIL_REPORT.md",
}
PROMOTION_ENVELOPE = frozenset(
    {
        "HIL_REPORT.md",
        "release.json",
        "SHA256SUMS",
    }
)
PROFILE_SPECS = {
    "esp32-4mb": {
        "target": "esp32",
        "port": "esp32",
        "provisioning": "esp-web-tools",
        "primary_artifact": "firmware.bin",
        "provenance": "pyble-build-provenance.json",
        "idf_target": "esp32",
        "chip_family": "ESP32",
        "chip_id": 0,
        "flash_size": "4MB",
        "flash_size_bytes": 4 * 1024 * 1024,
        "flash_freq": "40m",
        "frequency_hz": 40_000_000,
        "header_size_freq": 0x20,
        "base_offset": 0x1000,
        "component_offsets": (0x1000, 0x8000, 0x10000),
        "silicon_revision": {"minimum_full": 0, "maximum_full": 399},
        "psram": {"required": False, "size_bytes": 0, "type": "not-required"},
    },
    "esp32-s3-n16r8": {
        "target": "esp32-s3",
        "port": "esp32",
        "provisioning": "esp-web-tools",
        "primary_artifact": "firmware.bin",
        "provenance": "pyble-build-provenance.json",
        "idf_target": "esp32s3",
        "chip_family": "ESP32-S3",
        "chip_id": 9,
        "flash_size": "16MB",
        "flash_size_bytes": 16 * 1024 * 1024,
        "flash_freq": "80m",
        "frequency_hz": 80_000_000,
        "header_size_freq": 0x4F,
        "base_offset": 0,
        "component_offsets": (0, 0x8000, 0x10000),
        "silicon_revision": {"minimum_full": 0, "maximum_full": 99},
        "psram": {
            "required": True,
            "size_bytes": 8 * 1024 * 1024,
            "type": "octal",
        },
    },
    "waveshare-esp32-s3-lcd-147b": {
        "target": "waveshare-esp32-s3-lcd-147b",
        "port": "esp32",
        "provisioning": "esp-web-tools",
        "primary_artifact": "firmware.bin",
        "provenance": "pyble-build-provenance.json",
        "idf_target": "esp32s3",
        "chip_family": "ESP32-S3",
        "chip_id": 9,
        "flash_size": "16MB",
        "flash_size_bytes": 16 * 1024 * 1024,
        "flash_freq": "80m",
        "frequency_hz": 80_000_000,
        "header_size_freq": 0x4F,
        "base_offset": 0,
        "component_offsets": (0, 0x8000, 0x10000),
        "silicon_revision": {"minimum_full": 0, "maximum_full": 99},
        "psram": {
            "required": True,
            "size_bytes": 8 * 1024 * 1024,
            "type": "octal",
        },
    },
    "esp32-c3-4mb": {
        "target": "esp32-c3",
        "port": "esp32",
        "provisioning": "esp-web-tools",
        "primary_artifact": "firmware.bin",
        "provenance": "pyble-build-provenance.json",
        "idf_target": "esp32c3",
        "chip_family": "ESP32-C3",
        "chip_id": 5,
        "flash_size": "4MB",
        "flash_size_bytes": 4 * 1024 * 1024,
        "flash_freq": "80m",
        "frequency_hz": 80_000_000,
        "header_size_freq": 0x2F,
        "base_offset": 0,
        "component_offsets": (0, 0x8000, 0x10000),
        "silicon_revision": {"minimum_full": 3, "maximum_full": 199},
        "psram": {"required": False, "size_bytes": 0, "type": "not-required"},
    },
    "rpi-pico2-w": {
        "target": "rpi-pico2-w",
        "port": "rp2",
        # ``board`` is the public upstream hardware identity.  The build is
        # intentionally produced from PyBLE's private overlay, whose name is
        # recorded separately so public metadata never leaks a build-system
        # implementation detail into the supported-board contract.
        "board": "RPI_PICO2_W",
        "build_board": "PYBLE_RPI_PICO2_W",
        "provisioning": "uf2-bootsel",
        "primary_artifact": "firmware.uf2",
        "resource_artifact": "firmware.bin",
        "provenance": "pyble-build-provenance.json",
        "image_limit_bytes": RP2_IMAGE_LIMIT_BYTES,
        "flash_size_bytes": 4 * 1024 * 1024,
        "psram": {"required": False, "size_bytes": 0, "type": "not-required"},
    },
}
TARGET_TO_PROFILE = {
    value["target"]: profile_id
    for profile_id, value in PROFILE_SPECS.items()
    if value["port"] == "esp32"
}
RP2_TARGET_TO_PROFILE = {
    value["target"]: profile_id
    for profile_id, value in PROFILE_SPECS.items()
    if value["port"] == "rp2"
}
PARTITION_LAYOUTS = {
    "esp32": (
        {
            "type": 1,
            "subtype": 2,
            "offset": 0x9000,
            "size": 0x6000,
            "name": "nvs",
            "flags": 0,
        },
        {
            "type": 1,
            "subtype": 1,
            "offset": 0xF000,
            "size": 0x1000,
            "name": "phy_init",
            "flags": 0,
        },
        {
            "type": 0,
            "subtype": 0,
            "offset": 0x10000,
            "size": 0x1F0000,
            "name": "factory",
            "flags": 0,
        },
        {
            "type": 1,
            "subtype": 0x81,
            "offset": 0x200000,
            "size": 0x200000,
            "name": "vfs",
            "flags": 0,
        },
    ),
    "esp32-s3": (
        {
            "type": 1,
            "subtype": 2,
            "offset": 0x9000,
            "size": 0x6000,
            "name": "nvs",
            "flags": 0,
        },
        {
            "type": 1,
            "subtype": 1,
            "offset": 0xF000,
            "size": 0x1000,
            "name": "phy_init",
            "flags": 0,
        },
        {
            "type": 0,
            "subtype": 0,
            "offset": 0x10000,
            "size": 0x200000,
            "name": "factory",
            "flags": 0,
        },
        {
            "type": 1,
            "subtype": 0x81,
            "offset": 0x210000,
            "size": 0xDF0000,
            "name": "vfs",
            "flags": 0,
        },
    ),
    "esp32-c3": (
        {
            "type": 1,
            "subtype": 2,
            "offset": 0x9000,
            "size": 0x6000,
            "name": "nvs",
            "flags": 0,
        },
        {
            "type": 1,
            "subtype": 1,
            "offset": 0xF000,
            "size": 0x1000,
            "name": "phy_init",
            "flags": 0,
        },
        {
            "type": 0,
            "subtype": 0,
            "offset": 0x10000,
            "size": 0x1F0000,
            "name": "factory",
            "flags": 0,
        },
        {
            "type": 1,
            "subtype": 0x81,
            "offset": 0x200000,
            "size": 0x200000,
            "name": "vfs",
            "flags": 0,
        },
    ),
}
PARTITION_LAYOUTS["waveshare-esp32-s3-lcd-147b"] = copy.deepcopy(
    PARTITION_LAYOUTS["esp32-s3"]
)

_SEMVER_NUMERIC = r"(?:0|[1-9][0-9]*)"
_SEMVER_PRERELEASE = r"(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
_SEMVER_BUILD = r"[0-9A-Za-z-]+"
SEMVER_RE = re.compile(
    r"^%s\.%s\.%s(?:-%s(?:\.%s)*)?(?:\+%s(?:\.%s)*)?$"
    % (
        _SEMVER_NUMERIC,
        _SEMVER_NUMERIC,
        _SEMVER_NUMERIC,
        _SEMVER_PRERELEASE,
        _SEMVER_PRERELEASE,
        _SEMVER_BUILD,
        _SEMVER_BUILD,
    )
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
HIL_MARKER_RE = re.compile(
    r"<!--\s*PYBLE_HIL_RECORDS_V([2345])\s*(\{.*?\})\s*-->",
    re.DOTALL,
)
HIL_ANY_MARKER_RE = re.compile(r"<!--\s*PYBLE_HIL_RECORDS_V[0-9]+\b")
HIL_REPORT_SHELL_PREFIX = (
    "# PyBLE firmware HIL report\n\n"
    "This access-controlled candidate is pending real-board browser install "
    "and interrupted-flash recovery on every exact profile. Fill every "
    "record without changing firmware or manifest bytes.\n\n"
)
HIL_REPORT_SHELL_SUFFIX = "\n"
PLACEHOLDER_RE = re.compile(
    r"^(?:unknown|placeholder|todo|tbd|n/?a|none)$", re.IGNORECASE
)

ESP_IDF_SBOM_VERSION = "1.2.0"
ESP_IDF_SBOM_WHEEL_SHA256 = (
    "a1444a7f23740c44cacbce4845efb5cbcb08927878b6a3852c33a52d8b2b5da9"
)
ESP_IDF_SBOM_TAG_COMMIT = "d46a159ac239b9f843c59e0b4bfcfaff1859b862"
NOTICE_CANDIDATE_MARKER = "PUBLIC-NOTICE-STATUS: CANDIDATE-ONLY"

RELEASE_BUILD_INPUTS = (
    "firmware.bin",
    "micropython.bin",
    "micropython.elf",
    "bootloader/bootloader.bin",
    "partition_table/partition-table.bin",
    "flasher_args.json",
    "sdkconfig",
    "project_description.json",
    "pyble-build-provenance.json",
)

COMPATIBLE_SPDX = {
    "Apache-2.0",
    "Apache-2.0 OR MIT",
    "BSD-1-Clause",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "CC0-1.0",
    "ISC",
    "MIT",
    "Unlicense",
    "Unlicense OR CC0-1.0",
    "Zlib",
}

_AUDIT_MAIN_METADATA_HEADERS = (
    "compressed.data.h",
    "moduledefs.h",
    "mpversion.h",
    "pins.h",
    "qstrdefs.generated.h",
    "root_pointers.h",
)
_AUDIT_PYBLE_C_SOURCES = (
    "pble_proto.c",
    "pble_ble.c",
    "pble_info.c",
    "pble_device_config.c",
    "pble_runner.c",
    "pble_console.c",
    "pble_fs.c",
    "pble_lock.c",
    "pble_boot.c",
)
_AUDIT_BERKELEY_DB_C_SOURCES = (
    "btree/bt_close.c",
    "btree/bt_conv.c",
    "btree/bt_debug.c",
    "btree/bt_delete.c",
    "btree/bt_get.c",
    "btree/bt_open.c",
    "btree/bt_overflow.c",
    "btree/bt_page.c",
    "btree/bt_put.c",
    "btree/bt_search.c",
    "btree/bt_seq.c",
    "btree/bt_split.c",
    "btree/bt_utils.c",
    "mpool/mpool.c",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseError(message)


def _read_json(path: Path, label: str) -> Any:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReleaseError("%s is missing or unreadable: %s" % (label, path)) from exc
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ReleaseError("%s is not valid JSON: %s" % (label, path)) from exc


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
            return digest.hexdigest()
    except OSError as exc:
        raise ReleaseError("cannot hash release file: %s" % path) from exc


def _atomic_publish_no_replace(
    source: Path,
    destination: Path,
    label: str,
) -> None:
    """Atomically rename ``source`` while refusing every existing destination."""

    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        operation = getattr(libc, "renamex_np", None)
        _require(
            operation is not None,
            "%s cannot prove atomic no-replace publication on Darwin" % label,
        )
        operation.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        operation.restype = ctypes.c_int
        arguments = (source_bytes, destination_bytes, 0x00000004)
    elif sys.platform.startswith("linux"):
        operation = getattr(libc, "renameat2", None)
        _require(
            operation is not None,
            "%s cannot prove atomic no-replace publication on Linux" % label,
        )
        operation.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        operation.restype = ctypes.c_int
        arguments = (-100, source_bytes, -100, destination_bytes, 0x00000001)
    else:
        raise ReleaseError(
            "%s has no reviewed atomic no-replace implementation on %s"
            % (label, sys.platform)
        )

    ctypes.set_errno(0)
    if operation(*arguments) == 0:
        return
    error_number = ctypes.get_errno() or errno.EIO
    if error_number in (
        errno.EEXIST,
        errno.ENOTEMPTY,
        errno.ENOTDIR,
        errno.EISDIR,
    ):
        raise ReleaseError("%s destination already exists" % label)
    raise ReleaseError(
        "%s atomic no-replace publication failed: %s"
        % (label, os.strerror(error_number))
    )


def _artifact(path: Path, relative: str, **extra: Any) -> dict[str, Any]:
    _require(path.is_file(), "artifact is missing: %s" % path)
    record = {
        "path": relative,
        "size": path.stat().st_size,
        "sha256": _sha256_path(path),
    }
    record.update(extra)
    return record


def _read_lock(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "firmware" / "versions.lock"
    try:
        with path.open("rb") as handle:
            lock = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseError("cannot parse firmware/versions.lock") from exc
    for section in ("micropython", "esp_idf", "pyble"):
        _require(
            isinstance(lock.get(section), dict), "versions.lock lacks [%s]" % section
        )
    for section in ("micropython", "esp_idf"):
        for key in ("repo", "ref", "commit"):
            _require(
                isinstance(lock[section].get(key), str) and bool(lock[section][key]),
                "versions.lock [%s].%s is missing" % (section, key),
            )
        _require(
            bool(COMMIT_RE.fullmatch(lock[section]["commit"])),
            "versions.lock [%s].commit must be a full lowercase commit" % section,
        )
    version = lock["pyble"].get("agent_version")
    _require(
        isinstance(version, str) and bool(SEMVER_RE.fullmatch(version)),
        "versions.lock agent_version must be canonical SemVer",
    )
    _require(
        lock["pyble"].get("protocol_version") == "PBLE/1",
        "versions.lock protocol_version must be PBLE/1",
    )
    return lock


def _require_frozen_release_lock(repo_root: Path) -> None:
    path = repo_root / "firmware" / "versions.lock"
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReleaseError("cannot read firmware/versions.lock pin state") from exc
    marker = re.search(r"(?i)\b(?:draft|proposed)\b", source)
    _require(
        marker is None,
        "firmware/versions.lock pin state is %s, not frozen"
        % (marker.group(0).lower() if marker else "invalid"),
    )


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    _require(isinstance(value, dict), "%s must be an object" % label)
    actual = set(value)
    _require(
        actual == expected,
        "%s fields differ (missing=%s, extra=%s)"
        % (label, sorted(expected - actual), sorted(actual - expected)),
    )
    return value


def _git_output(checkout: Path, label: str, *args: str) -> str:
    environment = {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": os.fspath(checkout),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
        "TMPDIR": "/tmp",
    }
    try:
        completed = subprocess.run(
            ["git", "-C", str(checkout), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
    except OSError as exc:
        raise ReleaseError("cannot inspect %s checkout" % label) from exc
    _require(
        completed.returncode == 0,
        "cannot inspect %s checkout: %s" % (label, completed.stderr.strip()),
    )
    return completed.stdout.strip()


def _micropython_generated_path_is_allowed(relative: str) -> bool:
    exact = {"ports/esp32/partitions.csv"}
    prefixes = (
        "ports/esp32/boards/PYBLE_ESP32/",
        "ports/esp32/boards/PYBLE_ESP32_S3/",
        "ports/esp32/boards/PYBLE_WAVESHARE_ESP32_S3_LCD_147B/",
        "ports/esp32/boards/PYBLE_ESP32_C3/",
        "ports/esp32/build-PYBLE_ESP32/",
        "ports/esp32/build-PYBLE_ESP32_S3/",
        "ports/esp32/build-PYBLE_WAVESHARE_ESP32_S3_LCD_147B/",
        "ports/esp32/build-PYBLE_ESP32_C3/",
        "mpy-cross/build/",
    )
    return relative in exact or relative.startswith(prefixes)


def _require_checkout_clean(
    checkout: Path,
    label: str,
    *,
    allow_micropython_generated: bool = False,
) -> None:
    tracked = _git_output(
        checkout,
        label,
        "status",
        "--porcelain",
        "--untracked-files=no",
        "--ignore-submodules=untracked",
    )
    _require(not tracked, "%s checkout has dirty tracked source" % label)
    raw_untracked = _git_output(
        checkout,
        label,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    )
    untracked = [value for value in raw_untracked.split("\0") if value]
    if allow_micropython_generated:
        untracked = [
            value
            for value in untracked
            if not _micropython_generated_path_is_allowed(value)
        ]
    _require(
        not untracked,
        "%s checkout has unowned untracked source: %s" % (label, ", ".join(untracked)),
    )


def _validate_build_provenance(value: Any, target: str) -> dict[str, Any]:
    record = _exact_keys(
        value,
        {
            "schema_version",
            "target",
            "source_date_epoch",
            "pyble",
            "micropython",
            "esp_idf",
        },
        "%s build provenance" % target,
    )
    _require(
        type(record["schema_version"]) is int
        and record["schema_version"] == 1,
        "%s build provenance schema_version must be 1" % target,
    )
    _require(
        record["target"] == target,
        "%s build provenance target mismatch" % target,
    )
    epoch = record["source_date_epoch"]
    _require(
        type(epoch) is int and epoch > 0,
        "%s build provenance source epoch must be a positive integer" % target,
    )
    pyble = _exact_keys(
        record["pyble"], {"commit", "clean"}, "%s build provenance.pyble" % target
    )
    _require(
        pyble["clean"] is True,
        "%s build provenance must record a clean PyBLE source" % target,
    )
    commits = (("pyble", pyble),)
    commits += tuple(
        (
            name,
            _exact_keys(
                record[name],
                {"commit"},
                "%s build provenance.%s" % (target, name),
            ),
        )
        for name in ("micropython", "esp_idf")
    )
    for name, item in commits:
        _require(
            isinstance(item["commit"], str)
            and COMMIT_RE.fullmatch(item["commit"]) is not None,
            "%s build provenance %s commit must be full lowercase 40-hex"
            % (target, name),
        )
    return record


def _build_source_identity(provenance: dict[str, Any]) -> tuple[Any, ...]:
    """Return the historical ESP build identity used by retained callers."""

    return (
        provenance["source_date_epoch"],
        provenance["pyble"]["commit"],
        provenance["micropython"]["commit"],
        provenance["esp_idf"]["commit"],
    )


def _require_one_build_source_identity(
    validated: list[dict[str, Any]],
) -> tuple[Any, ...]:
    _require(bool(validated), "no build provenance records were supplied")
    provenances = [item["provenance"] for item in validated]
    identity = (
        provenances[0]["source_date_epoch"],
        provenances[0]["pyble"]["commit"],
        provenances[0]["micropython"]["commit"],
    )
    for provenance in provenances[1:]:
        _require(
            (
                provenance["source_date_epoch"],
                provenance["pyble"]["commit"],
                provenance["micropython"]["commit"],
            )
            == identity,
            "build provenance source identity/epoch differs across targets or roots",
        )
    esp_idf_commits = {
        provenance["esp_idf"]["commit"]
        for provenance in provenances
        if "esp_idf" in provenance
    }
    _require(
        len(esp_idf_commits) <= 1,
        "build provenance ESP-IDF commit differs across targets or roots",
    )
    arm_toolchains = {
        (
            provenance["arm_gnu_toolchain"]["release"],
            provenance["arm_gnu_toolchain"]["gcc"],
        )
        for provenance in provenances
        if "arm_gnu_toolchain" in provenance
    }
    _require(
        len(arm_toolchains) <= 1,
        "build provenance ARM GNU identity differs across targets or roots",
    )
    return identity


def _validate_retained_source_checkout(
    target: str,
    build: Path,
    description: dict[str, Any],
    provenance: dict[str, Any],
    lock: dict[str, Any],
) -> dict[str, str]:
    build = Path(build).absolute()
    build_root = build.parent
    logical_checkout = build_root / ".sources" / target / "micropython"
    logical_project = logical_checkout / "ports" / "esp32"
    declared_project = description.get("project_path")
    _require(
        isinstance(declared_project, str)
        and declared_project == str(logical_project),
        "%s project_description project_path is not the exact retained target source"
        % target,
    )

    try:
        resolved_build_root = build_root.resolve(strict=True)
        resolved_checkout = logical_checkout.resolve(strict=True)
        resolved_project = logical_project.resolve(strict=True)
    except OSError as exc:
        raise ReleaseError(
            "%s retained MicroPython source checkout is missing or unreadable" % target
        ) from exc
    expected_resolved_checkout = (
        resolved_build_root / ".sources" / target / "micropython"
    )
    expected_resolved_project = expected_resolved_checkout / "ports" / "esp32"
    _require(
        resolved_checkout == expected_resolved_checkout
        and resolved_project == expected_resolved_project,
        "%s retained MicroPython source path contains a symlink or escapes its target"
        % target,
    )
    _require(
        logical_checkout.is_dir() and logical_project.is_dir(),
        "%s retained MicroPython source checkout or ESP32 project is missing" % target,
    )
    checkout_root = _git_output(
        logical_checkout,
        "%s retained MicroPython" % target,
        "rev-parse",
        "--show-toplevel",
    )
    _require(
        Path(checkout_root).resolve() == resolved_checkout,
        "%s retained MicroPython source is not the checkout root" % target,
    )

    commit = _git_output(
        logical_checkout,
        "%s retained MicroPython" % target,
        "rev-parse",
        "HEAD",
    )
    _require(
        commit == provenance["micropython"]["commit"],
        "%s retained MicroPython checkout commit disagrees with build provenance"
        % target,
    )
    _require(
        commit == lock["micropython"]["commit"],
        "%s retained MicroPython checkout commit disagrees with versions.lock"
        % target,
    )
    origin_urls = _git_output(
        logical_checkout,
        "%s retained MicroPython" % target,
        "remote",
        "get-url",
        "--all",
        "origin",
    ).splitlines()
    expected_origin = lock["micropython"]["repo"]
    _require(
        origin_urls == [expected_origin],
        "%s retained MicroPython checkout must have exactly one canonical origin URL"
        % target,
    )
    _require_checkout_clean(
        logical_checkout,
        "%s retained MicroPython" % target,
        allow_micropython_generated=True,
    )

    project_description = build / "project_description.json"
    _require(
        project_description.is_file(),
        "%s retained source lacks project_description.json" % target,
    )
    return {
        "target": target,
        "project_path": (
            ".sources/%s/micropython/ports/esp32" % target
        ),
        "project_description_sha256": _sha256_path(project_description),
        "commit": commit,
        "origin": expected_origin,
    }


def _audit_retained_source_checkouts(
    repo_root: Path,
    build_root: Path,
) -> list[dict[str, str]]:
    """Validate and normalize all retained target source identities."""

    root = Path(repo_root)
    builds = Path(build_root)
    lock = _read_lock(root)
    records = []
    for target in sorted(TARGET_TO_PROFILE):
        build = builds / target
        description = _read_json(
            build / "project_description.json",
            "%s retained-source project description" % target,
        )
        provenance = _validate_build_provenance(
            _read_json(
                build / "pyble-build-provenance.json",
                "%s retained-source build provenance" % target,
            ),
            target,
        )
        records.append(
            _validate_retained_source_checkout(
                target,
                build,
                description,
                provenance,
                lock,
            )
        )
    return records


def _audit_retained_source_digest(
    records: list[dict[str, str]],
) -> str:
    """Hash canonical, host-independent retained-source evidence."""

    return _sha256_bytes(
        json.dumps(
            records,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    )


def _validate_build_against_repo(
    target: str,
    build: Path,
    description: dict[str, Any],
    provenance: dict[str, Any],
    repo_root: Path,
) -> dict[str, str]:
    root = Path(repo_root)
    pyble_commit = _git_output(root, "PyBLE", "rev-parse", "HEAD")
    _require(
        pyble_commit == provenance["pyble"]["commit"],
        "%s build provenance PyBLE commit is not checkout HEAD" % target,
    )
    epoch_text = _git_output(
        root,
        "PyBLE",
        "show",
        "-s",
        "--format=%ct",
        pyble_commit,
    )
    _require(
        epoch_text.isdigit() and int(epoch_text) == provenance["source_date_epoch"],
        "%s build provenance source epoch disagrees with its PyBLE commit" % target,
    )
    _require_checkout_clean(root, "PyBLE")

    lock = _read_lock(root)
    retained_source = _validate_retained_source_checkout(
        target,
        build,
        description,
        provenance,
        lock,
    )
    checkouts = {
        "micropython": root / "firmware" / "upstream" / "micropython",
        "esp_idf": root / "firmware" / ".esp-idf",
    }
    for name, checkout in checkouts.items():
        label = "MicroPython" if name == "micropython" else "ESP-IDF"
        commit = _git_output(checkout, label, "rev-parse", "HEAD")
        _require(
            commit == provenance[name]["commit"],
            "%s build provenance %s commit is not checkout HEAD" % (target, label),
        )
        _require(
            commit == lock[name]["commit"],
            "%s checkout commit disagrees with versions.lock" % label,
        )
        _require_checkout_clean(
            checkout,
            label,
            allow_micropython_generated=(name == "micropython"),
        )

    declared_build = description.get("build_dir")
    _require(
        isinstance(declared_build, str) and Path(declared_build).is_absolute(),
        "%s project_description build_dir is invalid" % target,
    )
    _require(
        Path(declared_build).resolve() == build.resolve(),
        "%s project_description build_dir is not the selected build" % target,
    )
    declared_idf = description.get("idf_path")
    _require(
        isinstance(declared_idf, str) and Path(declared_idf).is_absolute(),
        "%s project_description idf_path is invalid" % target,
    )
    _require(
        Path(declared_idf).resolve() == checkouts["esp_idf"].resolve(),
        "%s project_description idf_path is not the pinned ESP-IDF checkout" % target,
    )
    return retained_source


def _safe_relative_path(value: Any, label: str) -> str:
    _require(isinstance(value, str) and bool(value), "%s path must be nonempty" % label)
    _require("\\" not in value, "%s path contains a backslash" % label)
    _require(
        "?" not in value and "#" not in value, "%s path contains query/fragment" % label
    )
    _require("://" not in value, "%s path contains a URL scheme" % label)
    _require(not value.startswith("/"), "%s path must be relative" % label)
    pure = PurePosixPath(value)
    _require(
        all(part not in ("", ".", "..") for part in pure.parts),
        "%s path contains a dot or empty segment" % label,
    )
    _require(str(pure) == value, "%s path is not canonical POSIX form" % label)
    return value


def _path_below(root: Path, relative: str, label: str) -> Path:
    safe = _safe_relative_path(relative, label)
    root_resolved = root.resolve()
    candidate = (root / safe).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ReleaseError("%s escapes its version directory" % label) from exc
    return candidate


def _parse_esp_image(
    data: bytes,
    spec: dict[str, Any],
    role: str,
    label: str,
) -> bytes | None:
    _require(len(data) >= 33, "%s ESP image is truncated" % label)
    _require(data[0] == 0xE9, "%s has wrong ESP image magic" % label)
    segment_count = data[1]
    _require(1 <= segment_count <= 16, "%s has invalid segment count" % label)
    _require(data[2] == 2, "%s is not DIO flash mode" % label)
    _require(
        data[3] == spec["header_size_freq"],
        "%s flash size/frequency header disagrees with profile" % label,
    )
    chip_id = struct.unpack_from("<H", data, 12)[0]
    _require(chip_id == spec["chip_id"], "%s targets the wrong ESP chip" % label)
    minimum_full, maximum_full = struct.unpack_from("<HH", data, 15)
    expected_revision = spec["silicon_revision"]
    _require(
        minimum_full == expected_revision["minimum_full"]
        and maximum_full == expected_revision["maximum_full"],
        "%s silicon-revision window disagrees with profile" % label,
    )

    position = 24
    checksum = 0xEF
    first_segment_start = None
    first_segment_length = None
    for segment_index in range(segment_count):
        _require(position + 8 <= len(data), "%s segment header is truncated" % label)
        _load_address, length = struct.unpack_from("<II", data, position)
        position += 8
        _require(length > 0, "%s segment %d is empty" % (label, segment_index))
        _require(position + length <= len(data), "%s segment data is truncated" % label)
        if first_segment_start is None:
            first_segment_start = position
            first_segment_length = length
        segment = data[position : position + length]
        for octet in segment:
            checksum ^= octet
        position += length

    checksum_position = position + ((15 - (position % 16)) % 16)
    _require(checksum_position < len(data), "%s image checksum is missing" % label)
    _require(
        data[checksum_position] == checksum,
        "%s image checksum does not match its segments" % label,
    )
    _require(
        first_segment_start == 32, "%s first segment has unexpected layout" % label
    )
    _require(
        isinstance(first_segment_length, int) and first_segment_length >= 4,
        "%s first segment cannot contain its image descriptor" % label,
    )
    app_magic = struct.unpack_from("<I", data, first_segment_start)[0]
    if role == "application":
        _require(
            app_magic == 0xABCD5432,
            "%s lacks the ESP application descriptor" % label,
        )
        _require(
            first_segment_length >= 256,
            "%s ESP application descriptor is truncated" % label,
        )
        digest_start = first_segment_start + 0x90
        return data[digest_start : digest_start + 32]
    elif role == "bootloader":
        _require(
            app_magic != 0xABCD5432,
            "%s is an application image, not a bootloader" % label,
        )
        return None
    else:
        raise ReleaseError("unknown ESP image role: %s" % role)


def _parse_partition_table(
    data: bytes,
    spec: dict[str, Any],
    application_length: int,
    label: str,
) -> list[dict[str, Any]]:
    _require(len(data) >= 64 and len(data) % 32 == 0, "%s has invalid size" % label)
    entries: list[dict[str, Any]] = []
    encoded_entries = bytearray()
    saw_md5 = False
    after_md5 = False

    for position in range(0, len(data), 32):
        chunk = data[position : position + 32]
        if chunk == b"\xff" * 32:
            after_md5 = True
            continue
        _require(not after_md5, "%s has data after its terminator" % label)
        if chunk[:2] == b"\xeb\xeb":
            _require(not saw_md5, "%s has duplicate MD5 records" % label)
            _require(
                chunk[:16] == b"\xeb\xeb" + b"\xff" * 14,
                "%s has malformed MD5 record" % label,
            )
            expected = hashlib.md5(bytes(encoded_entries)).digest()  # nosec: format.
            _require(chunk[16:] == expected, "%s partition MD5 is incorrect" % label)
            saw_md5 = True
            after_md5 = True
            continue

        _require(not saw_md5, "%s has a partition after its MD5 record" % label)
        magic, part_type, subtype, offset, size, raw_name, flags = struct.unpack(
            "<HBBII16sI", chunk
        )
        _require(magic == 0x50AA, "%s has invalid partition magic" % label)
        _require(size > 0, "%s contains an empty partition" % label)
        _require(
            offset + size <= spec["flash_size_bytes"],
            "%s partition extends beyond declared flash capacity" % label,
        )
        try:
            name = raw_name.split(b"\0", 1)[0].decode("ascii")
        except UnicodeDecodeError as exc:
            raise ReleaseError(
                "%s contains a non-ASCII partition label" % label
            ) from exc
        _require(bool(name), "%s contains an unnamed partition" % label)
        _require(
            all(existing["name"] != name for existing in entries),
            "%s contains duplicate partition label %s" % (label, name),
        )
        entries.append(
            {
                "type": part_type,
                "subtype": subtype,
                "offset": offset,
                "size": size,
                "name": name,
                "flags": flags,
            }
        )
        encoded_entries.extend(chunk)

    _require(saw_md5, "%s lacks its partition-table MD5" % label)
    _require(entries, "%s has no partition entries" % label)
    by_offset = sorted(entries, key=lambda item: item["offset"])
    for previous, current in zip(by_offset, by_offset[1:]):
        _require(
            previous["offset"] + previous["size"] <= current["offset"],
            "%s partitions %s and %s overlap"
            % (label, previous["name"], current["name"]),
        )
    _require(
        entries == list(PARTITION_LAYOUTS[spec["target"]]),
        "%s does not match the exact frozen partition layout" % label,
    )

    factory = [
        entry for entry in entries if entry["type"] == 0 and entry["subtype"] == 0
    ]
    _require(len(factory) == 1, "%s must contain exactly one factory app" % label)
    _require(
        factory[0]["offset"] == spec["component_offsets"][2],
        "%s factory application offset disagrees with profile" % label,
    )
    _require(
        application_length <= factory[0]["size"],
        "%s application does not fit its factory partition" % label,
    )
    vfs = [entry for entry in entries if entry["name"] == "vfs"]
    _require(len(vfs) == 1, "%s must contain exactly one vfs partition" % label)
    _require(
        vfs[0]["offset"] + vfs[0]["size"] == spec["flash_size_bytes"],
        "%s vfs partition does not end at declared flash capacity" % label,
    )
    return entries


def _merge_components(
    base_offset: int, components: list[tuple[int, bytes]], label: str
) -> bytes:
    ordered = sorted(components, key=lambda item: item[0])
    _require(
        ordered and ordered[0][0] == base_offset, "%s has wrong merge base" % label
    )
    for (left_offset, left), (right_offset, _right) in zip(ordered, ordered[1:]):
        _require(
            left_offset + len(left) <= right_offset,
            "%s source components overlap" % label,
        )
    end = max(offset + len(value) for offset, value in ordered)
    merged = bytearray(b"\xff" * (end - base_offset))
    for offset, value in ordered:
        start = offset - base_offset
        _require(start >= 0, "%s component precedes merged base" % label)
        merged[start : start + len(value)] = value
    return bytes(merged)


def _validate_components(
    spec: dict[str, Any],
    merged: bytes,
    bootloader: bytes,
    partition_table: bytes,
    application: bytes,
    label: str,
) -> bytes:
    _parse_esp_image(bootloader, spec, "bootloader", "%s bootloader" % label)
    application_elf_sha256 = _parse_esp_image(
        application,
        spec,
        "application",
        "%s application" % label,
    )
    _require(
        isinstance(application_elf_sha256, bytes)
        and len(application_elf_sha256) == 32,
        "%s application lacks its ELF SHA-256" % label,
    )
    _parse_partition_table(
        partition_table, spec, len(application), "%s partition table" % label
    )
    reconstructed = _merge_components(
        spec["base_offset"],
        list(
            zip(
                spec["component_offsets"],
                (bootloader, partition_table, application),
            )
        ),
        label,
    )
    _require(
        merged == reconstructed,
        "%s merged firmware is not the exact FF-padded component merge" % label,
    )
    return application_elf_sha256


def _validate_flasher_args(value: Any, spec: dict[str, Any], label: str) -> None:
    _require(isinstance(value, dict), "%s must be an object" % label)
    required = {
        "write_flash_args",
        "flash_settings",
        "flash_files",
        "bootloader",
        "app",
        "partition-table",
        "extra_esptool_args",
    }
    _require(required <= set(value), "%s lacks required ESP-IDF fields" % label)
    expected_write_args = [
        "--flash_mode",
        "dio",
        "--flash_size",
        spec["flash_size"],
        "--flash_freq",
        spec["flash_freq"],
    ]
    _require(
        value["write_flash_args"] == expected_write_args,
        "%s write_flash_args disagree with profile" % label,
    )
    _require(
        value["flash_settings"]
        == {
            "flash_mode": "dio",
            "flash_size": spec["flash_size"],
            "flash_freq": spec["flash_freq"],
        },
        "%s flash settings disagree with profile" % label,
    )
    boot_offset, partition_offset, app_offset = spec["component_offsets"]
    expected_files = {
        hex(boot_offset): "bootloader/bootloader.bin",
        hex(app_offset): "micropython.bin",
        hex(partition_offset): "partition_table/partition-table.bin",
    }
    _require(
        value["flash_files"] == expected_files,
        "%s flash file map disagrees with frozen component paths/offsets" % label,
    )
    for key, offset, path in (
        ("bootloader", boot_offset, "bootloader/bootloader.bin"),
        ("partition-table", partition_offset, "partition_table/partition-table.bin"),
        ("app", app_offset, "micropython.bin"),
    ):
        section = value.get(key)
        _require(isinstance(section, dict), "%s %s entry is invalid" % (label, key))
        _require(
            section.get("offset") == hex(offset), "%s %s offset changed" % (label, key)
        )
        _require(section.get("file") == path, "%s %s path changed" % (label, key))
        _require(
            section.get("encrypted") in (False, "false"),
            "%s encrypted images are not qualified" % label,
        )
    extras = value.get("extra_esptool_args")
    _require(isinstance(extras, dict), "%s extra_esptool_args is invalid" % label)
    _require(
        extras.get("chip") == spec["idf_target"],
        "%s ESP chip target disagrees with profile" % label,
    )


def validate_build(
    target: str,
    build_dir: Path,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Validate one target's exact ESP-IDF release inputs."""

    _require(target in TARGET_TO_PROFILE, "unknown release target: %s" % target)
    profile_id = TARGET_TO_PROFILE[target]
    spec = PROFILE_SPECS[profile_id]
    build = Path(build_dir)
    _require(build.is_dir(), "build directory is missing: %s" % build)
    paths = {
        "install": build / "firmware.bin",
        "application": build / "micropython.bin",
        "elf": build / "micropython.elf",
        "bootloader": build / "bootloader" / "bootloader.bin",
        "partition-table": build / "partition_table" / "partition-table.bin",
        "flasher_args": build / "flasher_args.json",
        "sdkconfig": build / "sdkconfig",
        "project_description": build / "project_description.json",
        "provenance": build / "pyble-build-provenance.json",
    }
    for role, path in paths.items():
        _require(path.is_file(), "%s build lacks %s: %s" % (target, role, path))

    sdkconfig = paths["sdkconfig"].read_text(encoding="utf-8", errors="strict")
    _require(
        re.search(r"(?m)^CONFIG_APP_REPRODUCIBLE_BUILD=y$", sdkconfig) is not None,
        "%s build did not enable ESP-IDF reproducibility" % target,
    )
    if spec["idf_target"] in ("esp32s3", "esp32c3"):
        _require(
            re.search(r"(?m)^CONFIG_XTAL_FREQ_AUTO=y$", sdkconfig) is None,
            "%s build resolved automatic crystal selection" % target,
        )
        _require(
            re.search(r"(?m)^CONFIG_XTAL_FREQ_40=y$", sdkconfig) is not None
            and re.search(r"(?m)^CONFIG_XTAL_FREQ=40$", sdkconfig) is not None,
            "%s build must resolve an exact 40 MHz crystal" % target,
        )
    args = _read_json(paths["flasher_args"], "%s flasher_args.json" % target)
    _validate_flasher_args(args, spec, "%s flasher_args.json" % target)
    provenance = _validate_build_provenance(
        _read_json(paths["provenance"], "%s build provenance" % target),
        target,
    )

    description = _read_json(
        paths["project_description"], "%s project_description.json" % target
    )
    _require(
        isinstance(description, dict)
        and description.get("target") == spec["idf_target"],
        "%s project_description target disagrees with profile" % target,
    )
    retained_source = None
    if repo_root is not None:
        retained_source = _validate_build_against_repo(
            target,
            build,
            description,
            provenance,
            Path(repo_root),
        )

    try:
        merged = paths["install"].read_bytes()
        bootloader = paths["bootloader"].read_bytes()
        partition_table = paths["partition-table"].read_bytes()
        application = paths["application"].read_bytes()
        elf = paths["elf"].read_bytes()
    except OSError as exc:
        raise ReleaseError("%s release input cannot be read" % target) from exc
    _require(
        len(elf) >= 4 and elf[:4] == b"\x7fELF",
        "%s micropython.elf has wrong ELF magic" % target,
    )
    embedded_elf_sha256 = _validate_components(
        spec,
        merged,
        bootloader,
        partition_table,
        application,
        profile_id,
    )
    _require(
        embedded_elf_sha256 == hashlib.sha256(elf).digest(),
        "%s application descriptor ELF SHA-256 does not match micropython.elf"
        % target,
    )
    forbidden_elf_prefixes = {
        str((build.parent / ".sources" / target / "micropython").resolve()): (
            "%s retained MicroPython" % target
        ),
        str(build.parent.resolve()): "%s selected build root" % target,
        str(build.resolve()): "%s build" % target,
    }
    if repo_root is not None:
        forbidden_elf_prefixes[str(Path(repo_root).resolve())] = "PyBLE"
    for forbidden_prefix, prefix_label in forbidden_elf_prefixes.items():
        _require(
            os.fsencode(forbidden_prefix) not in elf,
            "%s ELF retains unmapped %s path prefix" % (target, prefix_label),
        )
    return {
        "profile_id": profile_id,
        "target": target,
        "spec": copy.deepcopy(spec),
        "paths": paths,
        "flasher_args": args,
        "project_description": description,
        "provenance": provenance,
        **(
            {"retained_source": retained_source}
            if retained_source is not None
            else {}
        ),
    }


def _validate_rp2_build_provenance(
    value: Any,
    target: str,
    *,
    firmware_bin_bytes: int,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Validate the RP2-specific build attestation without inventing IDF facts."""

    spec = PROFILE_SPECS[RP2_TARGET_TO_PROFILE[target]]
    record = _exact_keys(
        value,
        {
            "schema_version",
            "target",
            "port",
            "board",
            "source_date_epoch",
            "pyble",
            "micropython",
            "arm_gnu_toolchain",
            "picotool",
            "firmware_bin_bytes",
        },
        "%s build provenance" % target,
    )
    _require(
        type(record["schema_version"]) is int
        and record["schema_version"] == 1,
        "%s build provenance schema_version must be 1" % target,
    )
    _require(record["target"] == target, "%s build provenance target mismatch" % target)
    _require(
        record["port"] == spec["port"],
        "%s build provenance port mismatch" % target,
    )
    _require(
        record["board"] == spec["build_board"],
        "%s build provenance board mismatch" % target,
    )
    epoch = record["source_date_epoch"]
    _require(
        type(epoch) is int and epoch > 0,
        "%s build provenance source epoch must be a positive integer" % target,
    )
    pyble = _exact_keys(
        record["pyble"],
        {"commit", "clean"},
        "%s build provenance.pyble" % target,
    )
    micropython = _exact_keys(
        record["micropython"],
        {"commit"},
        "%s build provenance.micropython" % target,
    )
    _require(
        pyble["clean"] is True,
        "%s build provenance must record a clean PyBLE source" % target,
    )
    for name, item in (("pyble", pyble), ("micropython", micropython)):
        _require(
            isinstance(item["commit"], str)
            and COMMIT_RE.fullmatch(item["commit"]) is not None,
            "%s build provenance %s commit must be full lowercase 40-hex"
            % (target, name),
        )
    arm = _exact_keys(
        record["arm_gnu_toolchain"],
        {"release", "gcc"},
        "%s build provenance.arm_gnu_toolchain" % target,
    )
    for key in ("release", "gcc"):
        _require(
            isinstance(arm[key], str)
            and bool(arm[key].strip())
            and PLACEHOLDER_RE.fullmatch(arm[key].strip()) is None,
            "%s ARM GNU %s identity is missing" % (target, key),
        )
    _require(
        isinstance(record["picotool"], str)
        and re.match(r"^picotool v[0-9]+(?:\.[0-9]+){2}\b", record["picotool"])
        is not None,
        "%s picotool version is missing or invalid" % target,
    )
    _require(
        type(record["firmware_bin_bytes"]) is int
        and record["firmware_bin_bytes"] == firmware_bin_bytes,
        "%s provenance firmware_bin_bytes disagrees with firmware.bin" % target,
    )

    if repo_root is not None:
        root = Path(repo_root)
        lock = _read_lock(root)
        _require(
            micropython["commit"] == lock["micropython"]["commit"],
            "%s MicroPython provenance disagrees with versions.lock" % target,
        )
        arm_lock = lock.get("arm_gnu_toolchain")
        _require(
            isinstance(arm_lock, dict)
            and arm["release"] == arm_lock.get("release")
            and isinstance(arm_lock.get("gcc_version"), str)
            and arm_lock["gcc_version"] in arm["gcc"],
            "%s ARM GNU provenance disagrees with versions.lock" % target,
        )
        head = _git_output(root, "PyBLE", "rev-parse", "HEAD")
        _require(
            pyble["commit"] == head,
            "%s build provenance PyBLE commit is not checkout HEAD" % target,
        )
        source_epoch = _git_output(root, "PyBLE", "show", "-s", "--format=%ct", head)
        _require(
            source_epoch.isdigit() and int(source_epoch) == epoch,
            "%s build provenance source epoch disagrees with its PyBLE commit"
            % target,
        )
        _require_checkout_clean(root, "PyBLE")

    return record


def _reconstruct_rp2350_uf2(uf2: bytes, target: str) -> bytes:
    """Return the raw RP2350 Arm image after exact UF2 structural validation."""

    _require(
        bool(uf2) and len(uf2) % 512 == 0,
        "%s firmware.uf2 is not a complete UF2 stream" % target,
    )
    arm_blocks: list[tuple[int, int, int, bytes]] = []
    extension_blocks = 0
    rp2_ignore_block_tag = 0x9957E304
    for offset in range(0, len(uf2), 512):
        block = uf2[offset : offset + 512]
        magic_start0, magic_start1, flags, address, payload_size, block_number, total_blocks, family = struct.unpack_from(
            "<IIIIIIII", block, 0
        )
        magic_end = struct.unpack_from("<I", block, 508)[0]
        _require(
            magic_start0 == 0x0A324655
            and magic_start1 == 0x9E5D5157
            and magic_end == 0x0AB16F30,
            "%s firmware.uf2 block magic is invalid" % target,
        )
        _require(
            0 < payload_size <= 476,
            "%s firmware.uf2 payload length is invalid" % target,
        )
        payload = block[32 : 32 + payload_size]
        if flags == 0x00002000 and family == 0xE48BFF59:
            _require(
                all(value == 0 for value in block[32 + payload_size : 508]),
                "%s firmware.uf2 contains nonzero bytes outside a block payload"
                % target,
            )
            arm_blocks.append((address, block_number, total_blocks, payload))
        elif (
            flags == 0x0000A000
            and family == 0xE48BFF57
            and address == 0x10FFFF00
            and payload_size == 256
            and block_number == 0
            and total_blocks == 2
        ):
            extension_end = 32 + payload_size + 4
            _require(
                struct.unpack_from("<I", block, 32 + payload_size)[0]
                == rp2_ignore_block_tag
                and all(value == 0 for value in block[extension_end:508]),
                "%s firmware.uf2 RP2 ignore-block extension tag is invalid"
                % target,
            )
            _require(
                offset == 0,
                "%s firmware.uf2 RP2 ignore-block extension must be first"
                % target,
            )
            extension_blocks += 1
        else:
            raise ReleaseError(
                "%s firmware.uf2 contains an unexpected family or flag block"
                % target
            )

    _require(
        bool(arm_blocks) and extension_blocks == 1,
        "%s firmware.uf2 lacks one exact RP2350 Arm image" % target,
    )
    expected_total = arm_blocks[0][2]
    _require(
        expected_total == len(arm_blocks),
        "%s firmware.uf2 RP2350 Arm block count is incomplete" % target,
    )
    for index, (address, block_number, total_blocks, payload) in enumerate(
        arm_blocks
    ):
        _require(
            len(payload) == 256
            and block_number == index
            and total_blocks == expected_total
            and address == 0x10000000 + index * 256,
            "%s firmware.uf2 RP2350 Arm block sequence is incomplete" % target,
        )
    return b"".join(payload for _address, _number, _total, payload in arm_blocks)


def validate_rp2_build(
    target: str,
    build_dir: Path,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Validate one RP2 build without routing it through ESP-IDF semantics."""

    _require(target in RP2_TARGET_TO_PROFILE, "unknown RP2 release target: %s" % target)
    profile_id = RP2_TARGET_TO_PROFILE[target]
    spec = PROFILE_SPECS[profile_id]
    build = Path(build_dir)
    try:
        build_mode = build.lstat().st_mode
    except OSError as exc:
        raise ReleaseError("build directory is missing: %s" % build) from exc
    _require(
        stat_module.S_ISDIR(build_mode) and not stat_module.S_ISLNK(build_mode),
        "%s build directory must be a regular non-symlink directory" % target,
    )
    paths = {
        "install": build / spec["primary_artifact"],
        "elf": build / "firmware.elf",
        "resource-image": build / spec["resource_artifact"],
        "provenance": build / spec["provenance"],
    }
    snapshots: dict[str, bytes] = {}
    for role, path in paths.items():
        snapshots[role] = _read_regular_file_bytes(
            path,
            "%s build %s" % (target, role),
        )

    raw_image = snapshots["resource-image"]
    _require(bool(raw_image), "%s firmware.bin must be nonempty" % target)
    _require(
        len(raw_image) <= spec["image_limit_bytes"],
        "%s firmware.bin exceeds the %d-byte image limit"
        % (target, spec["image_limit_bytes"]),
    )
    elf = snapshots["elf"]
    _require(
        len(elf) >= 4 and elf[:4] == b"\x7fELF",
        "%s firmware.elf has wrong ELF magic" % target,
    )
    reconstructed = _reconstruct_rp2350_uf2(snapshots["install"], target)
    _require(
        len(reconstructed) >= len(raw_image)
        and reconstructed[: len(raw_image)] == raw_image
        and all(value == 0 for value in reconstructed[len(raw_image) :]),
        "%s firmware.uf2 does not reconstruct its sibling firmware.bin" % target,
    )
    try:
        provenance_value = json.loads(
            snapshots["provenance"].decode("utf-8", errors="strict")
        )
    except (UnicodeError, TypeError, ValueError) as exc:
        raise ReleaseError("%s build provenance is not valid JSON" % target) from exc
    provenance = _validate_rp2_build_provenance(
        provenance_value,
        target,
        firmware_bin_bytes=len(raw_image),
        repo_root=repo_root,
    )
    return {
        "profile_id": profile_id,
        "target": target,
        "spec": copy.deepcopy(spec),
        "paths": paths,
        "provenance": provenance,
        "firmware_bin_bytes": len(raw_image),
        "firmware_image_headroom_bytes": spec["image_limit_bytes"]
        - len(raw_image),
    }


def compare_build_roots(
    left: Path,
    right: Path,
    *,
    repo_root: Path | None = None,
    firmware_version: str | None = None,
) -> None:
    """Require two clean build roots to contain byte-identical release inputs."""

    left_root = Path(left)
    right_root = Path(right)
    esp_relative_inputs = (
        "micropython.elf",
        "firmware.bin",
        "micropython.bin",
        "bootloader/bootloader.bin",
        "partition_table/partition-table.bin",
        "flasher_args.json",
        "pyble-build-provenance.json",
    )
    rp2_relative_inputs = (
        "firmware.uf2",
        "firmware.elf",
        "firmware.bin",
        "pyble-build-provenance.json",
    )
    if firmware_version is not None:
        include_rp2 = (
            "rpi-pico2-w"
            in _release_profile_order_for_version(firmware_version)
        )
    else:
        left_has_rp2 = (left_root / "rpi-pico2-w").exists()
        right_has_rp2 = (right_root / "rpi-pico2-w").exists()
        _require(
            left_has_rp2 == right_has_rp2,
            "reproducibility roots disagree on the RP2 target inventory",
        )
        # Version-less comparison remains usable for immutable v0.4.2/v0.5.x
        # replay; a source-era caller must pass firmware_version explicitly.
        include_rp2 = left_has_rp2
    validated: list[dict[str, Any]] = []
    for target in TARGET_TO_PROFILE:
        validated.append(
            validate_build(
                target,
                left_root / target,
                repo_root=repo_root,
            )
        )
        validated.append(
            validate_build(
                target,
                right_root / target,
                repo_root=repo_root,
            )
        )
    if include_rp2:
        for root in (left_root, right_root):
            validated.append(
                validate_rp2_build(
                    "rpi-pico2-w",
                    root / "rpi-pico2-w",
                    repo_root=repo_root,
                )
            )
    _require_one_build_source_identity(validated)
    for target in TARGET_TO_PROFILE:
        for relative in esp_relative_inputs:
            left_path = left_root / target / relative
            right_path = right_root / target / relative
            _require(
                left_path.read_bytes() == right_path.read_bytes(),
                "reproducibility mismatch: %s/%s" % (target, relative),
            )
    if include_rp2:
        for relative in rp2_relative_inputs:
            left_path = left_root / "rpi-pico2-w" / relative
            right_path = right_root / "rpi-pico2-w" / relative
            _require(
                left_path.read_bytes() == right_path.read_bytes(),
                "reproducibility mismatch: rpi-pico2-w/%s" % relative,
            )


def _require_distinct_build_roots(left: Path, right: Path) -> None:
    left_resolved = Path(left).resolve()
    right_resolved = Path(right).resolve()
    _require(
        left_resolved != right_resolved,
        "reproducibility build root must be distinct from the primary build root",
    )
    _require(
        not left_resolved.is_relative_to(right_resolved)
        and not right_resolved.is_relative_to(left_resolved),
        "reproducibility build roots must not be nested",
    )


def _spdx_from_text(text: str) -> set[str]:
    return {
        match.strip()
        for match in re.findall(r"SPDX-License-Identifier:\s*([^\r\n*]+)", text)
        if match.strip()
    }


def _copyrights_from_text(text: str) -> list[str]:
    found = []
    for line in text.splitlines():
        if "copyright" not in line.lower():
            continue
        cleaned = re.sub(r"^\s*(?:[/#*;-]+\s*)+", "", line).strip()
        if cleaned and cleaned not in found:
            found.append(cleaned)
    return found


def _license_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    names = ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING", "NOTICE", "NOTICE.txt")
    return [directory / name for name in names if (directory / name).is_file()]


def _infer_spdx(license_text: str) -> str | None:
    lowered = license_text.lower()
    if "apache license" in lowered and "version 2.0" in lowered:
        return "Apache-2.0"
    if (
        "mit license" in lowered
        or "permission is hereby granted, free of charge" in lowered
    ):
        return "MIT"
    if "redistribution and use in source and binary forms" in lowered:
        return "BSD-3-Clause"
    if "isc license" in lowered:
        return "ISC"
    if "zlib license" in lowered:
        return "Zlib"
    return None


def _notice_entry(
    *,
    name: str,
    version_ref: str,
    source_url: str,
    spdx: list[str],
    copyrights: list[str],
    required_notice: str,
    license_texts: list[str],
) -> str:
    _require(spdx, "%s has no recognized SPDX identifier" % name)
    for identifier in spdx:
        _require(
            identifier in COMPATIBLE_SPDX,
            "%s uses unrecognized or incompatible SPDX expression %s"
            % (name, identifier),
        )
    _require(copyrights, "%s has no recoverable copyright notice" % name)
    _require(license_texts, "%s has no complete local license text" % name)
    return (
        "=" * 78
        + "\n"
        + "Name: %s\n" % name
        + "Version/ref: %s\n" % version_ref
        + "Source URL: %s\n" % source_url
        + "SPDX identifier: %s\n" % ", ".join(spdx)
        + "Copyright:\n  "
        + "\n  ".join(copyrights)
        + "\n"
        + "Required notice: %s\n" % required_notice
        + "Complete license text:\n"
        + "\n\n".join(text.rstrip() for text in license_texts)
        + "\n"
    )


def generate_third_party_licenses(build_root: Path, repo_root: Path) -> str:
    """Generate a conservative notice inventory from exact linked build inputs.

    This host-runnable inventory is intentionally not represented as the final
    public ESP-IDF SBOM review.  The marker at the top is release-blocking under
    ``validate_bundle(..., public=True)`` until the pinned esp-idf-sbom output
    and reviewed policy map replace it.
    """

    root = Path(repo_root)
    builds = Path(build_root)
    lock = _read_lock(root)
    firmware = root / "firmware"
    mpy_root = firmware / "upstream" / "micropython"
    idf_root = firmware / ".esp-idf"
    mpy_license = mpy_root / "LICENSE"
    idf_license = idf_root / "LICENSE"
    _require(mpy_license.is_file(), "MicroPython LICENSE is missing")
    _require(idf_license.is_file(), "ESP-IDF LICENSE is missing")
    mpy_license_text = mpy_license.read_text(encoding="utf-8", errors="strict")
    idf_license_text = idf_license.read_text(encoding="utf-8", errors="strict")

    entries = [
        _notice_entry(
            name="MicroPython",
            version_ref="%s @ %s"
            % (lock["micropython"]["ref"], lock["micropython"]["commit"]),
            source_url=lock["micropython"]["repo"],
            spdx=["MIT"],
            copyrights=_copyrights_from_text(mpy_license_text),
            required_notice="Retain the copyright and permission notice.",
            license_texts=[mpy_license_text],
        ),
        _notice_entry(
            name="ESP-IDF",
            version_ref="%s @ %s" % (lock["esp_idf"]["ref"], lock["esp_idf"]["commit"]),
            source_url=lock["esp_idf"]["repo"],
            spdx=["Apache-2.0"],
            copyrights=_copyrights_from_text(idf_license_text)
            or ["Copyright Espressif Systems"],
            required_notice="Retain applicable attribution and NOTICE text.",
            license_texts=[idf_license_text],
        ),
    ]

    neopixel = (
        mpy_root
        / "lib"
        / "micropython-lib"
        / "micropython"
        / "drivers"
        / "led"
        / "neopixel"
        / "neopixel.py"
    )
    neopixel_license = mpy_root / "lib" / "micropython-lib" / "LICENSE"
    _require(neopixel.is_file(), "resolved NeoPixel source is missing")
    _require(neopixel_license.is_file(), "micropython-lib LICENSE is missing")
    neopixel_source = neopixel.read_text(encoding="utf-8", errors="strict")
    neopixel_license_text = neopixel_license.read_text(
        encoding="utf-8", errors="strict"
    )
    neopixel_spdx = sorted(_spdx_from_text(neopixel_source)) or ["MIT"]
    entries.append(
        _notice_entry(
            name="micropython-lib NeoPixel",
            version_ref="pinned by MicroPython %s @ %s"
            % (lock["micropython"]["ref"], lock["micropython"]["commit"]),
            source_url="https://github.com/micropython/micropython-lib",
            spdx=neopixel_spdx,
            copyrights=_copyrights_from_text(neopixel_source)
            or _copyrights_from_text(neopixel_license_text),
            required_notice="Retain the copyright and permission notice.",
            license_texts=[neopixel_license_text],
        )
    )

    components: dict[str, dict[str, Any]] = {}
    for target in TARGET_TO_PROFILE:
        target_build = builds / target
        descriptions = [target_build / "project_description.json"]
        boot_description = target_build / "bootloader" / "project_description.json"
        if boot_description.is_file():
            descriptions.append(boot_description)
        for description_path in descriptions:
            description = _read_json(
                description_path,
                "%s linked-component description" % target,
            )
            names = description.get("build_components")
            info = description.get("build_component_info")
            _require(
                isinstance(names, list) and isinstance(info, dict),
                "%s lacks linked component metadata" % description_path,
            )
            for name in names:
                _require(
                    isinstance(name, str) and isinstance(info.get(name), dict),
                    "%s component inventory is inconsistent" % description_path,
                )
                record = info[name]
                directory = Path(record.get("dir", ""))
                _require(
                    directory.is_dir(),
                    "linked component %s source directory is missing: %s"
                    % (name, directory),
                )
                existing = components.get(name)
                if existing is not None:
                    _require(
                        Path(existing["dir"]).resolve() == directory.resolve(),
                        "component %s resolves to different source directories" % name,
                    )
                    existing.setdefault("sources", []).extend(record.get("sources", []))
                else:
                    components[name] = {
                        "dir": str(directory),
                        "sources": list(record.get("sources", [])),
                    }

    for component_name in sorted(components):
        record = components[component_name]
        directory = Path(record["dir"])
        source_paths = sorted({Path(path) for path in record.get("sources", [])})
        source_texts: list[str] = []
        for source_path in source_paths:
            _require(
                source_path.is_file(),
                "linked source for component %s is missing: %s"
                % (component_name, source_path),
            )
            source_texts.append(
                source_path.read_text(encoding="utf-8", errors="ignore")
            )
        combined_sources = "\n".join(source_texts)
        spdx = sorted(_spdx_from_text(combined_sources))

        license_paths = _license_files(directory)
        if not license_paths:
            try:
                directory.resolve().relative_to(idf_root.resolve())
                license_paths = [idf_license]
            except ValueError:
                try:
                    directory.resolve().relative_to(mpy_root.resolve())
                    license_paths = [mpy_license]
                except ValueError as exc:
                    raise ReleaseError(
                        "linked component %s has no exact local license input"
                        % component_name
                    ) from exc
        license_texts = [
            path.read_text(encoding="utf-8", errors="strict") for path in license_paths
        ]
        if not spdx:
            inferred = sorted(
                {
                    identifier
                    for identifier in (_infer_spdx(text) for text in license_texts)
                    if identifier
                }
            )
            spdx = inferred
        for identifier in spdx:
            _require(
                identifier in COMPATIBLE_SPDX,
                "component %s uses unrecognized or incompatible SPDX expression %s"
                % (component_name, identifier),
            )

        copyrights = _copyrights_from_text(combined_sources)
        for text in license_texts:
            for notice in _copyrights_from_text(text):
                if notice not in copyrights:
                    copyrights.append(notice)
        if not copyrights:
            if directory.resolve().is_relative_to(idf_root.resolve()):
                copyrights = ["Copyright Espressif Systems"]
            elif directory.resolve().is_relative_to(mpy_root.resolve()):
                copyrights = ["Copyright MicroPython contributors"]

        source_url = "%s/tree/%s/components/%s" % (
            lock["esp_idf"]["repo"].rstrip("/"),
            lock["esp_idf"]["commit"],
            component_name,
        )
        entries.append(
            _notice_entry(
                name="ESP-IDF component %s" % component_name,
                version_ref="%s @ %s"
                % (lock["esp_idf"]["ref"], lock["esp_idf"]["commit"]),
                source_url=source_url,
                spdx=spdx,
                copyrights=copyrights,
                required_notice="Retain all applicable component notices.",
                license_texts=license_texts,
            )
        )

    header = (
        "PyBLE mechanically generated linked-input notice inventory\n"
        + NOTICE_CANDIDATE_MARKER
        + "\n"
        + "Public qualification additionally requires esp-idf-sbom "
        + ESP_IDF_SBOM_VERSION
        + " (wheel sha256 "
        + ESP_IDF_SBOM_WHEEL_SHA256
        + ", tag commit "
        + ESP_IDF_SBOM_TAG_COMMIT
        + "), app and bootloader inventories for every target, an isolated "
        "network-off run, pinned empty excluded-CVE input, and a reviewed "
        "archive/license/NOTICE policy map.\n\n"
    )
    return header + "\n".join(entries)


LICENSE_AUDIT_PROFILES = (
    ("esp32-4mb", "esp32", "esp32"),
    ("esp32-s3-n16r8", "esp32-s3", "esp32s3"),
    (
        "waveshare-esp32-s3-lcd-147b",
        "waveshare-esp32-s3-lcd-147b",
        "esp32s3",
    ),
    ("esp32-c3-4mb", "esp32-c3", "esp32c3"),
)
LICENSE_AUDIT_ROLES = ("application", "bootloader")
FROZEN_TARGET_SETTINGS = {
    "esp32": {
        "board": "PYBLE_ESP32",
        "architecture": "xtensawin",
    },
    "esp32-s3": {
        "board": "PYBLE_ESP32_S3",
        "architecture": "xtensawin",
    },
    "waveshare-esp32-s3-lcd-147b": {
        "board": "PYBLE_WAVESHARE_ESP32_S3_LCD_147B",
        "architecture": "xtensawin",
    },
    "esp32-c3": {
        "board": "PYBLE_ESP32_C3",
        "architecture": "rv32imc",
    },
}
_AUDIT_FIRST_PARTY_FROZEN_SOURCES = {
    "pyble_waveshare_lcd147b.py": {
        "target": "waveshare-esp32-s3-lcd-147b",
        "introduced_version": "0.5.0",
        "canonical_path": (
            "firmware/board_overlays/waveshare-esp32-s3-lcd-147b/"
            "pyble_waveshare_lcd147b.py"
        ),
        "spdx_expression": "MIT",
    },
    "pyble_st7789.py": {
        "target": "waveshare-esp32-s3-lcd-147b",
        "introduced_version": "0.5.0",
        "canonical_path": "firmware/python_modules/pyble_st7789.py",
        "spdx_expression": "MIT",
    },
}
LICENSE_AUDIT_KNOWN_SPDX = COMPATIBLE_SPDX | {
    "BSD-2-Clause-Views",
    "BSD-2-Clause",
    "GCC-exception-3.1",
    "GPL-2.0-only",
    "GPL-2.0-or-later",
    "GPL-3.0-only",
    "GPL-3.0-or-later",
    "LLVM-exception",
}
LICENSE_AUDIT_KNOWN_EXCEPTIONS = {
    "GCC-exception-3.1",
    "LLVM-exception",
}
LICENSE_AUDIT_TOKEN_RE = re.compile(
    r"\s*(\(|\)|AND\b|OR\b|WITH\b|"
    r"(?:DocumentRef-[A-Za-z0-9.-]+:)?LicenseRef-[A-Za-z0-9.-]+|"
    r"[A-Za-z0-9][A-Za-z0-9.+-]*)"
)
LICENSE_AUDIT_TIMESTAMP = "1970-01-01T00:00:00Z"
LICENSE_AUDIT_RAW_EXTENSIONS = {
    "json": "spdx.json",
    "tag-value": "spdx.tag",
}


def _audit_canonical_package_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _audit_requirement_name(value: str) -> str:
    match = re.match(r"^\s*([A-Za-z0-9_.-]+)", value)
    _require(match is not None, "invalid release-tool requirement: %r" % value)
    return _audit_canonical_package_name(match.group(1))


def _audit_locked_requirement(value: str) -> tuple[str, str]:
    match = re.fullmatch(
        r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9][A-Za-z0-9_.+!-]*)",
        value,
    )
    _require(
        match is not None,
        "locked release-tool requirement must be exact name==version: %r" % value,
    )
    return _audit_canonical_package_name(match.group(1)), match.group(2)


class _AuditSpdxExpressionParser:
    """Parse the SPDX boolean subset used by reviewed release policy."""

    def __init__(self, value: str):
        _require(
            isinstance(value, str) and value not in ("", "NOASSERTION", "NONE"),
            "SPDX expression is missing or unresolved",
        )
        self._tokens: list[str] = []
        position = 0
        while position < len(value):
            match = LICENSE_AUDIT_TOKEN_RE.match(value, position)
            _require(match is not None, "malformed SPDX expression: %s" % value)
            self._tokens.append(match.group(1))
            position = match.end()
        self._index = 0
        self.identifiers: set[str] = set()

    def parse(self) -> set[str]:
        _require(self._tokens, "SPDX expression is empty")
        self._parse_or()
        _require(
            self._index == len(self._tokens),
            "SPDX expression contains trailing tokens",
        )
        return self.identifiers

    def _peek(self) -> str | None:
        if self._index >= len(self._tokens):
            return None
        return self._tokens[self._index]

    def _take(self, expected: str | None = None) -> str:
        value = self._peek()
        _require(
            value is not None and (expected is None or value == expected),
            "malformed SPDX expression",
        )
        self._index += 1
        return value

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
        simple_license = self._parse_primary()
        if self._peek() == "WITH":
            self._take("WITH")
            _require(
                simple_license,
                "SPDX WITH must follow one simple license identifier",
            )
            exception = self._take()
            _require(
                exception in LICENSE_AUDIT_KNOWN_EXCEPTIONS,
                "invalid SPDX exception",
            )
            self.identifiers.add(exception)

    def _parse_primary(self) -> bool:
        if self._peek() == "(":
            self._take("(")
            self._parse_or()
            self._take(")")
            return False
        identifier = self._take()
        _require(
            identifier not in (")", "AND", "OR", "WITH")
            and identifier not in LICENSE_AUDIT_KNOWN_EXCEPTIONS,
            "expected SPDX identifier",
        )
        self.identifiers.add(identifier)
        return True


def _audit_parse_spdx(
    expression: str,
    approved_license_refs: set[str],
) -> set[str]:
    identifiers = _AuditSpdxExpressionParser(expression).parse()
    for identifier in identifiers:
        if "LicenseRef-" in identifier:
            _require(
                identifier in approved_license_refs,
                "unapproved SPDX LicenseRef: %s" % identifier,
            )
        else:
            _require(
                identifier in LICENSE_AUDIT_KNOWN_SPDX,
                "unknown or incompatible SPDX identifier: %s" % identifier,
            )
    return identifiers


def _audit_spdx_tokens(expression: str) -> list[str]:
    """Return the exact SPDX token sequence after validating lexical coverage."""

    _require(
        isinstance(expression, str) and expression not in ("", "NOASSERTION", "NONE"),
        "SPDX expression is missing or unresolved",
    )
    tokens: list[str] = []
    position = 0
    while position < len(expression):
        match = LICENSE_AUDIT_TOKEN_RE.match(expression, position)
        _require(match is not None, "malformed SPDX expression: %s" % expression)
        tokens.append(match.group(1))
        position = match.end()
    _require(tokens, "SPDX expression is empty")
    return tokens


def _audit_spdx_unwrap(tokens: list[str]) -> list[str]:
    """Remove only parentheses that enclose the complete expression."""

    result = list(tokens)
    while len(result) >= 2 and result[0] == "(" and result[-1] == ")":
        depth = 0
        closes_at_end = True
        for index, token in enumerate(result):
            if token == "(":
                depth += 1
            elif token == ")":
                depth -= 1
                _require(depth >= 0, "malformed SPDX expression")
                if depth == 0 and index != len(result) - 1:
                    closes_at_end = False
                    break
        if not closes_at_end or depth != 0:
            break
        result = result[1:-1]
    return result


def _audit_spdx_choice_arms(expression: str) -> list[list[str]]:
    """Split one expression into its exact top-level OR choice arms."""

    tokens = _audit_spdx_unwrap(_audit_spdx_tokens(expression))
    arms: list[list[str]] = []
    start = 0
    depth = 0
    for index, token in enumerate(tokens):
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
            _require(depth >= 0, "malformed SPDX expression")
        elif token == "OR" and depth == 0:
            _require(index > start, "malformed SPDX expression")
            arms.append(_audit_spdx_unwrap(tokens[start:index]))
            start = index + 1
    _require(depth == 0 and start < len(tokens), "malformed SPDX expression")
    arms.append(_audit_spdx_unwrap(tokens[start:]))
    return arms


def _audit_spdx_selected_choice(
    source_expression: str,
    selected_expression: str,
    approved_license_refs: set[str],
) -> tuple[set[str], set[str]]:
    """Validate that selected terms are one complete source choice arm."""

    source_identifiers = _audit_parse_spdx(source_expression, approved_license_refs)
    selected_identifiers = _audit_parse_spdx(
        selected_expression,
        approved_license_refs,
    )
    selected_tokens = _audit_spdx_unwrap(_audit_spdx_tokens(selected_expression))
    _require(
        selected_tokens in _audit_spdx_choice_arms(source_expression),
        "selected SPDX expression is not one exact source-expression choice",
    )
    return source_identifiers, selected_identifiers


_AUDIT_TAG_VALUE_DOCUMENT_TAGS = {
    "SPDXVersion",
    "DataLicense",
    "SPDXID",
    "DocumentName",
    "DocumentNamespace",
    "Creator",
    "Created",
    "CreatorComment",
}
_AUDIT_TAG_VALUE_PACKAGE_TAGS = {
    "PackageName",
    "PackageSummary",
    "PackageVersion",
    "PackageSupplier",
    "PackageOriginator",
    "PackageDownloadLocation",
    "FilesAnalyzed",
    "PackageVerificationCode",
    "PackageLicenseInfoFromFiles",
    "PackageLicenseConcluded",
    "PackageLicenseDeclared",
    "PackageCopyrightText",
    "PackageComment",
    "PackageChecksum",
    "ExternalRef",
}
_AUDIT_TAG_VALUE_FILE_TAGS = {
    "FileName",
    "SPDXID",
    "LicenseInfoInFile",
    "FileCopyrightText",
    "FileChecksum",
    "LicenseConcluded",
    "FileContributor",
}
_AUDIT_TAG_VALUE_REPEATABLE_TAGS = {
    "Creator",
    "Relationship",
    "PackageLicenseInfoFromFiles",
    "PackageChecksum",
    "ExternalRef",
    "LicenseInfoInFile",
    "FileChecksum",
    "FileContributor",
}
_AUDIT_SPDX_ELEMENT_RE = re.compile(
    r"^(?:DocumentRef-[A-Za-z0-9.-]+:)?SPDXRef-[A-Za-z0-9.-]+$"
)


def _audit_tag_value_text(
    lines: list[str],
    index: int,
    value: str,
) -> tuple[str, int]:
    if not value.startswith("<text>"):
        _require(
            "<text>" not in value and "</text>" not in value,
            "SPDX tag/value contains a malformed text value",
        )
        _require(value != "", "SPDX tag/value contains an empty value")
        return value, index

    first = value[len("<text>") :]
    if "</text>" in first:
        _require(
            first.count("</text>") == 1 and first.endswith("</text>"),
            "SPDX tag/value text has trailing or duplicate closing markup",
        )
        content = first[: -len("</text>")]
        _require("<text>" not in content, "SPDX tag/value text is nested")
        return content, index

    parts = [first]
    while index + 1 < len(lines):
        index += 1
        line = lines[index]
        if "</text>" not in line:
            _require("<text>" not in line, "SPDX tag/value text is nested")
            parts.append(line)
            continue
        _require(
            line.count("</text>") == 1 and line.endswith("</text>"),
            "SPDX tag/value text has trailing or duplicate closing markup",
        )
        content = line[: -len("</text>")]
        _require("<text>" not in content, "SPDX tag/value text is nested")
        parts.append(content)
        return "\n".join(parts), index
    raise ReleaseError("SPDX tag/value text is unterminated")


def _audit_tag_value_add(
    record: dict[str, list[str]],
    tag: str,
    value: str,
) -> None:
    values = record.setdefault(tag, [])
    _require(
        tag in _AUDIT_TAG_VALUE_REPEATABLE_TAGS or not values,
        "SPDX tag/value duplicates singleton field %s" % tag,
    )
    _require(value not in values, "SPDX tag/value duplicates %s value" % tag)
    values.append(value)


def _audit_tag_value_one(
    record: dict[str, list[str]],
    tag: str,
) -> str | None:
    values = record.get(tag, [])
    _require(len(values) <= 1, "SPDX tag/value duplicates singleton field %s" % tag)
    return values[0] if values else None


def _audit_tag_value_relationship(value: str) -> dict[str, str]:
    parts = value.split()
    _require(
        len(parts) == 3,
        "SPDX tag/value relationship must contain exactly three fields",
    )
    source, relationship, related = parts
    _require(
        _AUDIT_SPDX_ELEMENT_RE.fullmatch(source) is not None
        and _AUDIT_SPDX_ELEMENT_RE.fullmatch(related) is not None
        and re.fullmatch(r"[A-Z][A-Z0-9_]*", relationship) is not None,
        "SPDX tag/value relationship is malformed",
    )
    return {
        "spdxElementId": source,
        "relationshipType": relationship,
        "relatedSpdxElement": related,
    }


def _audit_tag_value_checksum(value: str) -> dict[str, str]:
    match = re.fullmatch(r"([A-Z0-9-]+): ([0-9A-Fa-f]+)", value)
    _require(match is not None, "SPDX tag/value checksum is malformed")
    return {
        "algorithm": match.group(1),
        "checksumValue": match.group(2).lower(),
    }


def _audit_tag_value_external_ref(value: str) -> dict[str, str]:
    parts = value.split(maxsplit=2)
    _require(len(parts) == 3, "SPDX tag/value ExternalRef is malformed")
    return {
        "referenceCategory": parts[0],
        "referenceType": parts[1],
        "referenceLocator": parts[2],
    }


def _audit_parse_spdx_tag_value(raw: str) -> dict[str, Any]:
    _require(isinstance(raw, str) and raw, "SPDX tag/value output is empty")
    _require("\x00" not in raw, "SPDX tag/value output contains NUL")
    _require(not raw.startswith("\ufeff"), "SPDX tag/value output contains a BOM")
    lines = raw.splitlines()
    document: dict[str, list[str]] = {}
    package_records: list[dict[str, list[str]]] = []
    file_records: list[dict[str, list[str]]] = []
    relationships: list[dict[str, str]] = []
    relationship_values: set[tuple[str, str, str]] = set()
    context = "document"
    current: dict[str, list[str]] = document

    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        _require(":" in line, "SPDX tag/value contains a malformed record")
        raw_tag, raw_value = line.split(":", 1)
        tag = raw_tag.strip()
        _require(
            tag
            in (
                _AUDIT_TAG_VALUE_DOCUMENT_TAGS
                | _AUDIT_TAG_VALUE_PACKAGE_TAGS
                | _AUDIT_TAG_VALUE_FILE_TAGS
                | {"Relationship"}
            ),
            "SPDX tag/value contains unsupported field %s" % tag,
        )
        value, index = _audit_tag_value_text(lines, index, raw_value.lstrip())

        if tag == "Relationship":
            relationship = _audit_tag_value_relationship(value)
            identity = (
                relationship["spdxElementId"],
                relationship["relationshipType"],
                relationship["relatedSpdxElement"],
            )
            _require(
                identity not in relationship_values,
                "SPDX tag/value duplicates a relationship",
            )
            relationship_values.add(identity)
            relationships.append(relationship)
            index += 1
            continue

        if tag == "PackageName":
            context = "package"
            current = {}
            package_records.append(current)
        elif tag == "FileName":
            context = "file"
            current = {}
            file_records.append(current)
        elif tag == "SPDXID":
            _require(
                context in ("document", "package", "file"),
                "SPDXID has no document, package, or file context",
            )
        elif tag in _AUDIT_TAG_VALUE_DOCUMENT_TAGS:
            _require(
                context == "document",
                "SPDX document field appears after package/file records",
            )
        elif tag in _AUDIT_TAG_VALUE_PACKAGE_TAGS:
            _require(context == "package", "SPDX package field lacks PackageName")
        elif tag in _AUDIT_TAG_VALUE_FILE_TAGS:
            _require(context == "file", "SPDX file field lacks FileName")
        _audit_tag_value_add(current, tag, value)
        index += 1

    _require(document, "SPDX tag/value contains no document fields")
    _require(package_records, "SPDX tag/value contains no packages")
    result: dict[str, Any] = {
        "spdxVersion": _audit_tag_value_one(document, "SPDXVersion"),
        "dataLicense": _audit_tag_value_one(document, "DataLicense"),
        "SPDXID": _audit_tag_value_one(document, "SPDXID"),
        "name": _audit_tag_value_one(document, "DocumentName"),
        "documentNamespace": _audit_tag_value_one(document, "DocumentNamespace"),
        "creationInfo": {
            "creators": list(document.get("Creator", [])),
            "created": _audit_tag_value_one(document, "Created"),
        },
        "packages": [],
        "relationships": relationships,
    }
    creator_comment = _audit_tag_value_one(document, "CreatorComment")
    if creator_comment is not None:
        result["creationInfo"]["comment"] = creator_comment

    package_mapping = {
        "PackageName": "name",
        "SPDXID": "SPDXID",
        "PackageSummary": "summary",
        "PackageVersion": "versionInfo",
        "PackageSupplier": "supplier",
        "PackageOriginator": "originator",
        "PackageDownloadLocation": "downloadLocation",
        "PackageLicenseConcluded": "licenseConcluded",
        "PackageLicenseDeclared": "licenseDeclared",
        "PackageCopyrightText": "copyrightText",
        "PackageComment": "comment",
    }
    for record in package_records:
        package: dict[str, Any] = {}
        for tag, key in package_mapping.items():
            value = _audit_tag_value_one(record, tag)
            if value is not None:
                package[key] = value
        analyzed = _audit_tag_value_one(record, "FilesAnalyzed")
        if analyzed is not None:
            _require(
                analyzed in ("true", "false"),
                "SPDX tag/value FilesAnalyzed is not boolean",
            )
            package["filesAnalyzed"] = analyzed == "true"
        verification = _audit_tag_value_one(record, "PackageVerificationCode")
        if verification is not None:
            package["packageVerificationCode"] = {
                "packageVerificationCodeValue": verification
            }
        if record.get("PackageLicenseInfoFromFiles"):
            package["licenseInfoFromFiles"] = list(
                record["PackageLicenseInfoFromFiles"]
            )
        if record.get("PackageChecksum"):
            package["checksums"] = [
                _audit_tag_value_checksum(value) for value in record["PackageChecksum"]
            ]
        if record.get("ExternalRef"):
            package["externalRefs"] = [
                _audit_tag_value_external_ref(value) for value in record["ExternalRef"]
            ]
        result["packages"].append(package)

    if file_records:
        result["files"] = []
    file_mapping = {
        "FileName": "fileName",
        "SPDXID": "SPDXID",
        "LicenseConcluded": "licenseConcluded",
        "FileCopyrightText": "copyrightText",
    }
    for record in file_records:
        file_record: dict[str, Any] = {}
        for tag, key in file_mapping.items():
            value = _audit_tag_value_one(record, tag)
            if value is not None:
                file_record[key] = value
        if record.get("LicenseInfoInFile"):
            file_record["licenseInfoInFiles"] = list(record["LicenseInfoInFile"])
        if record.get("FileChecksum"):
            file_record["checksums"] = [
                _audit_tag_value_checksum(value) for value in record["FileChecksum"]
            ]
        if record.get("FileContributor"):
            file_record["fileContributors"] = list(record["FileContributor"])
        result["files"].append(file_record)
    return result


def _audit_read_spdx_output(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise ReleaseError(
            "%s is missing or not strict UTF-8: %s" % (label, path)
        ) from exc
    _require(raw.strip() != "", "%s is empty" % label)
    first = raw.lstrip()[:1]
    if first in ("{", "["):
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ReleaseError(
                "%s is malformed or mixes JSON and tag/value" % label
            ) from exc
        _require(isinstance(value, dict), "%s JSON must be an object" % label)
        return value, "json"
    _require(
        not any(
            line.lstrip().startswith(("{", "[", "}", "]"))
            for line in raw.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ),
        "%s mixes JSON and tag/value" % label,
    )
    return _audit_parse_spdx_tag_value(raw), "tag-value"


def _audit_no_symlink_components(root: Path, path: Path, label: str) -> None:
    root_absolute = root.absolute()
    root_resolved = root.resolve()
    try:
        relative = path.absolute().relative_to(root_absolute)
    except ValueError as exc:
        raise ReleaseError("%s escapes its approved root" % label) from exc
    current = root_absolute
    for part in relative.parts:
        current = current / part
        _require(not current.is_symlink(), "%s traverses a symlink" % label)
    try:
        path.resolve().relative_to(root_resolved)
    except ValueError as exc:
        raise ReleaseError("%s escapes its approved root" % label) from exc


def _audit_repo_file(repo_root: Path, relative: str, label: str) -> Path:
    safe = _safe_relative_path(relative, label)
    candidate = repo_root / safe
    _audit_no_symlink_components(repo_root, candidate, label)
    _require(candidate.is_file(), "%s is missing: %s" % (label, relative))
    return candidate


def _audit_path_in_roots(
    raw_path: str | Path,
    *,
    relative_to: Path,
    roots: tuple[Path, ...],
    label: str,
) -> Path:
    text = str(raw_path)
    value = Path(text)
    if not value.is_absolute():
        _require(
            "\\" not in text and ".." not in value.parts,
            "%s contains an unsafe relative path" % label,
        )
        value = relative_to / value
    absolute = value.absolute()
    for root in roots:
        resolved_root = root.resolve()
        try:
            absolute.resolve().relative_to(resolved_root)
        except ValueError:
            continue
        _audit_no_symlink_components(root, absolute, label)
        return absolute
    raise ReleaseError("%s is outside the repository/build roots" % label)


def _audit_sha256_tree(path: Path) -> str:
    _require(path.is_dir(), "reviewed source tree is missing: %s" % path)
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        _require(not item.is_symlink(), "reviewed source tree contains a symlink")
        if not item.is_file():
            continue
        relative = item.relative_to(path).as_posix().encode("utf-8")
        value = item.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest()


def _audit_python_cache_artifact(relative: Path) -> bool:
    return "__pycache__" in relative.parts or relative.suffix.lower() in {
        ".pyc",
        ".pyo",
    }


def _audit_sha256_source_tree(
    path: Path,
    *,
    reject_python_cache: bool = False,
) -> str:
    """Hash source bytes canonically without host-generated Python caches."""

    _require(path.is_dir(), "reviewed source tree is missing: %s" % path)
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        _require(not item.is_symlink(), "reviewed source tree contains a symlink")
        if not item.is_file():
            continue
        relative_path = item.relative_to(path)
        if _audit_python_cache_artifact(relative_path):
            _require(
                not reject_python_cache,
                "reviewed source tree contains Python cache artifact: %s"
                % relative_path.as_posix(),
            )
            continue
        relative = relative_path.as_posix().encode("utf-8")
        value = item.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest()


def _audit_artifact_requirements(artifact: dict[str, Any]) -> list[str]:
    value = artifact.get("requires")
    _require(isinstance(value, list), "locked artifact requires must be an array")
    _require(
        all(isinstance(item, str) for item in value),
        "locked artifact requires contains a non-string requirement",
    )
    return value


def _audit_load_tool_lock(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "firmware" / "release-tools.lock"
    try:
        with path.open("rb") as handle:
            lock = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseError("cannot parse firmware/release-tools.lock") from exc

    lock = _exact_keys(
        lock,
        {"schema_version", "tool", "inputs", "artifacts"},
        "release-tools.lock",
    )
    _require(
        type(lock["schema_version"]) is int
        and lock["schema_version"] == 1,
        "release-tools.lock schema version changed",
    )
    tool = _exact_keys(
        lock["tool"],
        {"name", "version", "tag", "commit", "filename", "sha256"},
        "release-tools.lock [tool]",
    )
    expected_tool = {
        "name": "esp-idf-sbom",
        "version": ESP_IDF_SBOM_VERSION,
        "tag": "v1.2.0",
        "commit": ESP_IDF_SBOM_TAG_COMMIT,
        "filename": "esp_idf_sbom-1.2.0-py3-none-any.whl",
        "sha256": ESP_IDF_SBOM_WHEEL_SHA256,
    }
    for key, expected in expected_tool.items():
        _require(
            tool.get(key) == expected,
            "release-tools.lock [tool].%s changed" % key,
        )

    artifacts = lock["artifacts"]
    _require(
        isinstance(artifacts, list) and artifacts,
        "release-tools.lock has no artifacts",
    )
    by_name: dict[str, list[dict[str, Any]]] = {}
    identities: set[tuple[str, str, str, str]] = set()
    filenames: set[str] = set()
    for artifact_raw in artifacts:
        _require(isinstance(artifact_raw, dict), "locked artifact is not an object")
        allowed_keys = {"name", "version", "filename", "sha256", "requires"}
        if "path" in artifact_raw:
            allowed_keys.add("path")
        artifact = _exact_keys(
            artifact_raw,
            allowed_keys,
            "locked artifact",
        )
        for key in ("name", "version", "filename", "sha256"):
            _require(
                isinstance(artifact.get(key), str) and artifact[key],
                "locked artifact lacks %s" % key,
            )
        _require(
            SHA256_RE.fullmatch(artifact["sha256"]) is not None,
            "locked artifact SHA-256 is invalid",
        )
        filename = _safe_relative_path(
            artifact["filename"],
            "locked artifact filename",
        )
        _require(
            PurePosixPath(filename).name == filename and filename.endswith(".whl"),
            "locked artifact filename must be a wheel basename",
        )
        _require(
            filename not in filenames,
            "duplicate locked artifact filename",
        )
        filenames.add(filename)
        canonical = _audit_canonical_package_name(artifact["name"])
        identity = (
            canonical,
            artifact["version"],
            artifact["filename"],
            artifact["sha256"],
        )
        _require(identity not in identities, "duplicate locked artifact")
        identities.add(identity)
        by_name.setdefault(canonical, []).append(artifact)
        _audit_artifact_requirements(artifact)
        if "path" in artifact:
            cached = _audit_repo_file(
                repo_root,
                artifact["path"],
                "locked release-tool artifact",
            )
            _require(
                _sha256_path(cached) == artifact["sha256"],
                "locked release-tool artifact digest changed",
            )

    top = by_name.get("esp-idf-sbom", [])
    _require(
        len(
            [
                artifact
                for artifact in top
                if artifact["version"] == ESP_IDF_SBOM_VERSION
                and artifact["filename"] == expected_tool["filename"]
                and artifact["sha256"] == ESP_IDF_SBOM_WHEEL_SHA256
            ]
        )
        == 1,
        "locked esp-idf-sbom top artifact is missing or ambiguous",
    )

    reachable = {"esp-idf-sbom"}
    pending = ["esp-idf-sbom"]
    while pending:
        current = pending.pop()
        for artifact in by_name[current]:
            for requirement in _audit_artifact_requirements(artifact):
                dependency, required_version = _audit_locked_requirement(requirement)
                _require(
                    dependency in by_name,
                    "locked requirement has no hashed artifact: %s" % requirement,
                )
                _require(
                    len(by_name[dependency]) == 1
                    and by_name[dependency][0]["version"] == required_version,
                    "locked requirement version disagrees with its artifact: %s"
                    % requirement,
                )
                if dependency not in reachable:
                    reachable.add(dependency)
                    pending.append(dependency)
    _require(
        reachable == set(by_name),
        "release-tools.lock contains an unreachable or incomplete closure",
    )
    _require(
        all(len(values) == 1 for values in by_name.values()),
        "executed-artifact receipts require one selected artifact per package",
    )

    inputs = _exact_keys(
        lock["inputs"],
        {
            "excluded_cves_path",
            "excluded_cves_sha256",
            "license_policy_path",
            "license_policy_sha256",
        },
        "release-tools.lock [inputs]",
    )
    for prefix in ("excluded_cves", "license_policy"):
        relative = inputs.get("%s_path" % prefix)
        expected_hash = inputs.get("%s_sha256" % prefix)
        _require(
            isinstance(relative, str)
            and isinstance(expected_hash, str)
            and SHA256_RE.fullmatch(expected_hash) is not None,
            "release-tools.lock input %s is invalid" % prefix,
        )
        source = _audit_repo_file(
            repo_root,
            relative,
            "release audit %s input" % prefix,
        )
        _require(
            _sha256_path(source) == expected_hash,
            "release audit %s input digest changed" % prefix,
        )

    lock["_artifact_hashes"] = {
        name: values[0]["sha256"] for name, values in by_name.items()
    }
    lock["_path"] = path
    return lock


AUDIT_SANDBOX_PROFILE = """\
(version 1)
(allow default)
(deny network*)
"""
AUDIT_RUNNER_BOOTSTRAP = """\
import json
import runpy
import sys
sys.path[:0] = json.loads(sys.argv[1])
arguments = sys.argv[2:]
sys.argv = ["esp_idf_sbom", *arguments]
runpy.run_module("esp_idf_sbom", run_name="__main__", alter_sys=False)
"""
AUDIT_RUNNER_ALLOWED_ENV = {
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "PIP_CACHE_DIR",
    "PIP_CONFIG_FILE",
    "PIP_NO_INDEX",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONHASHSEED",
    "PYTHONNOUSERSITE",
    "SBOM_EXCLUDED_CVES_FILE",
    "TMPDIR",
    "TZ",
    "XDG_CACHE_HOME",
}


def _audit_version_key(value: str) -> tuple[tuple[int, int | str], ...]:
    _require(
        isinstance(value, str) and bool(value),
        "wheel dependency version is missing",
    )
    tokens = re.findall(r"[0-9]+|[A-Za-z]+", value)
    _require(tokens, "wheel dependency version is invalid: %s" % value)
    return tuple(
        (0, int(token)) if token.isdigit() else (1, token.lower()) for token in tokens
    )


def _audit_version_satisfies(version: str, constraints: str) -> bool:
    if not constraints:
        return True
    selected = _audit_version_key(version)
    for raw_constraint in constraints.split(","):
        constraint = raw_constraint.strip()
        match = re.fullmatch(r"(===|==|!=|~=|>=|<=|>|<)\s*(\S+)", constraint)
        _require(
            match is not None,
            "unsupported wheel dependency constraint: %s" % constraint,
        )
        operator, required_text = match.groups()
        required = _audit_version_key(required_text)
        if operator in ("==", "==="):
            accepted = version == required_text
        elif operator == "!=":
            accepted = version != required_text
        elif operator == ">=":
            accepted = selected >= required
        elif operator == "<=":
            accepted = selected <= required
        elif operator == ">":
            accepted = selected > required
        elif operator == "<":
            accepted = selected < required
        else:
            numeric = [int(item) for item in re.findall(r"[0-9]+", required_text)]
            _require(
                len(numeric) >= 2,
                "compatible-release constraint is too broad: %s" % constraint,
            )
            upper = (
                (numeric[0] + 1,)
                if len(numeric) == 2
                else tuple(numeric[:-2] + [numeric[-2] + 1])
            )
            selected_numeric = tuple(
                int(item) for item in re.findall(r"[0-9]+", version)
            )
            accepted = selected >= required and selected_numeric < upper
        if not accepted:
            return False
    return True


def _audit_parse_metadata_requirement(
    value: str,
) -> tuple[str, set[str], str, str]:
    requirement, separator, marker = value.partition(";")
    match = re.fullmatch(
        r"\s*([A-Za-z0-9][A-Za-z0-9_.-]*)"
        r"(?:\[([A-Za-z0-9_.-]+(?:\s*,\s*[A-Za-z0-9_.-]+)*)\])?"
        r"\s*(.*?)\s*",
        requirement,
    )
    _require(match is not None, "wheel METADATA requirement is invalid: %s" % value)
    name, extras_raw, constraints = match.groups()
    constraints = constraints.strip()
    if constraints.startswith("(") and constraints.endswith(")"):
        constraints = constraints[1:-1].strip()
    extras = {
        item.strip().lower() for item in (extras_raw or "").split(",") if item.strip()
    }
    return (
        _audit_canonical_package_name(name),
        extras,
        constraints,
        marker.strip() if separator else "",
    )


def _audit_marker_comparison(
    variable: str,
    operator: str,
    expected: str,
    selected_extras: set[str],
) -> bool:
    if variable == "extra":
        actual: str | tuple[tuple[int, int | str], ...] = ""
        comparisons = [
            (item == expected if operator == "==" else item != expected)
            for item in selected_extras
        ]
        return any(comparisons) if comparisons else operator == "!="
    if variable == "python_version":
        actual = _audit_version_key(
            "%s.%s" % (sys.version_info.major, sys.version_info.minor)
        )
        wanted: str | tuple[tuple[int, int | str], ...] = _audit_version_key(expected)
    elif variable == "platform_system":
        actual = platform.system()
        wanted = expected
    else:
        raise ReleaseError("unsupported wheel environment marker: %s" % variable)
    if operator == "==":
        return actual == wanted
    if operator == "!=":
        return actual != wanted
    _require(
        variable == "python_version",
        "unsupported wheel marker comparison: %s %s" % (variable, operator),
    )
    if operator == "<":
        return actual < wanted
    if operator == "<=":
        return actual <= wanted
    if operator == ">":
        return actual > wanted
    if operator == ">=":
        return actual >= wanted
    raise ReleaseError("unsupported wheel marker operator: %s" % operator)


def _audit_marker_applies(marker: str, selected_extras: set[str]) -> bool:
    if not marker:
        return True
    groups = re.split(r"\s+or\s+", marker, flags=re.IGNORECASE)
    for group in groups:
        accepted = True
        for raw_clause in re.split(r"\s+and\s+", group, flags=re.IGNORECASE):
            clause = raw_clause.strip()
            while clause.startswith("(") and clause.endswith(")"):
                clause = clause[1:-1].strip()
            match = re.fullmatch(
                r"(extra|python_version|platform_system)\s*"
                r"(==|!=|<=|>=|<|>)\s*(['\"])(.*?)\3",
                clause,
            )
            _require(
                match is not None,
                "unsupported wheel environment marker: %s" % marker,
            )
            if not _audit_marker_comparison(
                match.group(1),
                match.group(2),
                match.group(4),
                selected_extras,
            ):
                accepted = False
                break
        if accepted:
            return True
    return False


def _audit_wheel_tag_supported(filename: str, wheel_tags: set[str]) -> None:
    stem = filename.removesuffix(".whl")
    parts = stem.rsplit("-", 3)
    _require(len(parts) == 4, "locked wheel filename has no compatibility tag")
    filename_tag = "-".join(parts[-3:])
    filename_python, filename_abi, filename_platform = parts[-3:]
    expanded_filename_tags = {
        "%s-%s-%s" % (python_tag, abi_tag, platform_tag)
        for python_tag in filename_python.split(".")
        for abi_tag in filename_abi.split(".")
        for platform_tag in filename_platform.split(".")
    }
    _require(
        filename_tag in wheel_tags or expanded_filename_tags <= wheel_tags,
        "locked wheel filename and WHEEL tags disagree",
    )
    current_cp = "cp%s%s" % (sys.version_info.major, sys.version_info.minor)
    machine = platform.machine().lower().replace("-", "_")
    supported = False
    for raw_tag in wheel_tags:
        tag_parts = raw_tag.split("-")
        _require(len(tag_parts) == 3, "wheel compatibility tag is malformed")
        python_tag, abi_tag, platform_tag = tag_parts
        python_tags = set(python_tag.split("."))
        if (
            platform_tag == "any"
            and abi_tag == "none"
            and (
                "py3" in python_tags
                or "py2" in python_tags
                and "py3" in python_tags
                or current_cp in python_tags
            )
        ):
            supported = True
            continue
        if current_cp not in python_tags or abi_tag not in (
            current_cp,
            "abi3",
            "none",
        ):
            continue
        if sys.platform == "darwin":
            supported = platform_tag.startswith("macosx_") and (
                platform_tag.endswith("_" + machine)
                or platform_tag.endswith("_universal2")
            )
        elif sys.platform.startswith("linux"):
            supported = platform_tag.startswith(
                ("manylinux", "musllinux", "linux")
            ) and platform_tag.endswith("_" + machine)
    _require(supported, "locked wheel is incompatible with this release host")


def _audit_extract_verified_wheel(
    *,
    artifact: dict[str, Any],
    payload: bytes,
    destination: Path,
) -> dict[str, Any]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ReleaseError("locked release-tool artifact is not a valid wheel") from exc
    with archive:
        infos = archive.infolist()
        _require(infos, "locked release-tool wheel is empty")
        names: set[str] = set()
        total_size = 0
        for info in infos:
            name = info.filename
            pure = PurePosixPath(name)
            _require(
                name not in names
                and "\\" not in name
                and not pure.is_absolute()
                and all(part not in ("", ".", "..") for part in pure.parts),
                "locked wheel contains an unsafe or duplicate path",
            )
            names.add(name)
            total_size += info.file_size
            _require(
                total_size <= 512 * 1024 * 1024,
                "locked wheel expands beyond the audit safety limit",
            )
            mode = info.external_attr >> 16
            _require(
                not stat_module.S_ISLNK(mode),
                "locked wheel contains a symlink",
            )
            _require(
                not bool(info.flag_bits & 0x1),
                "locked wheel contains an encrypted member",
            )

        metadata_names = [
            name
            for name in names
            if name.endswith(".dist-info/METADATA")
            and len(PurePosixPath(name).parts) == 2
        ]
        wheel_names = [
            name
            for name in names
            if name.endswith(".dist-info/WHEEL") and len(PurePosixPath(name).parts) == 2
        ]
        _require(
            len(metadata_names) == 1 and len(wheel_names) == 1,
            "locked wheel must contain one METADATA and one WHEEL record",
        )
        metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
        _require(
            _audit_canonical_package_name(str(metadata.get("Name", "")))
            == _audit_canonical_package_name(artifact["name"])
            and str(metadata.get("Version", "")) == artifact["version"],
            "locked wheel Name/Version disagrees with the lock",
        )
        wheel_text = archive.read(wheel_names[0]).decode("utf-8", errors="strict")
        wheel_tags = {
            line.split(":", 1)[1].strip()
            for line in wheel_text.splitlines()
            if line.startswith("Tag:")
        }
        _require(wheel_tags, "locked wheel contains no compatibility tags")
        _audit_wheel_tag_supported(artifact["filename"], wheel_tags)

        destination.mkdir(mode=0o700)
        for info in infos:
            if info.is_dir():
                (destination / PurePosixPath(info.filename)).mkdir(
                    mode=0o700,
                    parents=True,
                    exist_ok=True,
                )
                continue
            output = destination / PurePosixPath(info.filename)
            output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            output.write_bytes(archive.read(info))
    return {
        "requirements": list(metadata.get_all("Requires-Dist", [])),
        "tree_sha256": _audit_sha256_tree(destination),
    }


def _audit_validate_wheel_dependency_graph(
    lock: dict[str, Any],
    metadata_by_name: dict[str, dict[str, Any]],
) -> None:
    artifacts = {
        _audit_canonical_package_name(artifact["name"]): artifact
        for artifact in lock["artifacts"]
    }
    selected_extras = {name: set() for name in artifacts}
    queue = ["esp-idf-sbom"]
    visited_extras: dict[str, frozenset[str]] = {}
    metadata_edges: dict[str, set[str]] = {}
    while queue:
        name = queue.pop(0)
        snapshot = frozenset(selected_extras[name])
        if visited_extras.get(name) == snapshot:
            continue
        visited_extras[name] = snapshot
        active: set[str] = set()
        for raw_requirement in metadata_by_name[name]["requirements"]:
            dependency, extras, constraints, marker = _audit_parse_metadata_requirement(
                raw_requirement
            )
            if not _audit_marker_applies(marker, selected_extras[name]):
                continue
            _require(
                dependency in artifacts,
                "wheel METADATA dependency is absent from the locked closure: %s"
                % dependency,
            )
            _require(
                _audit_version_satisfies(
                    artifacts[dependency]["version"],
                    constraints,
                ),
                "locked wheel version does not satisfy METADATA: %s" % dependency,
            )
            active.add(dependency)
            before = set(selected_extras[dependency])
            selected_extras[dependency].update(extras)
            if selected_extras[dependency] != before:
                queue.append(dependency)
            if dependency not in visited_extras:
                queue.append(dependency)
        metadata_edges[name] = active

    _require(
        set(visited_extras) == set(artifacts),
        "wheel METADATA closure is incomplete or contains unreachable artifacts",
    )
    for name, artifact in artifacts.items():
        locked_edges = {
            _audit_locked_requirement(requirement)[0]
            for requirement in _audit_artifact_requirements(artifact)
        }
        _require(
            metadata_edges.get(name, set()) == locked_edges,
            "wheel METADATA dependency graph disagrees with release-tools.lock",
        )


def _audit_prepare_locked_wheels(
    *,
    lock: dict[str, Any],
    wheelhouse: Path,
    destination: Path,
) -> tuple[list[str], list[dict[str, str]], dict[str, str]]:
    _require(not wheelhouse.is_symlink(), "release-tool wheelhouse is a symlink")
    _require(wheelhouse.is_dir(), "release-tool wheelhouse is missing")
    expected_filenames = {artifact["filename"] for artifact in lock["artifacts"]}
    actual_wheels = {
        path.name for path in wheelhouse.iterdir() if path.name.endswith(".whl")
    }
    _require(
        actual_wheels == expected_filenames,
        "release-tool wheelhouse must contain exactly the locked wheels",
    )
    destination.mkdir(mode=0o700)
    module_paths: list[str] = []
    identities: list[dict[str, str]] = []
    tree_hashes: dict[str, str] = {}
    metadata_by_name: dict[str, dict[str, Any]] = {}
    for artifact in sorted(
        lock["artifacts"],
        key=lambda item: _audit_canonical_package_name(item["name"]),
    ):
        candidate = wheelhouse / artifact["filename"]
        _audit_no_symlink_components(
            wheelhouse,
            candidate,
            "locked release-tool wheel",
        )
        try:
            file_stat = candidate.stat(follow_symlinks=False)
            payload = candidate.read_bytes()
        except OSError as exc:
            raise ReleaseError("cannot read locked release-tool wheel") from exc
        _require(
            stat_module.S_ISREG(file_stat.st_mode),
            "locked release-tool wheel is not a regular file",
        )
        _require(
            _sha256_bytes(payload) == artifact["sha256"],
            "locked release-tool wheel digest changed",
        )
        name = _audit_canonical_package_name(artifact["name"])
        extracted = destination / name
        metadata_by_name[name] = _audit_extract_verified_wheel(
            artifact=artifact,
            payload=payload,
            destination=extracted,
        )
        module_paths.append(str(extracted.resolve()))
        tree_hashes[name] = metadata_by_name[name]["tree_sha256"]
        identities.append(
            {
                "name": artifact["name"],
                "version": artifact["version"],
                "filename": artifact["filename"],
                "sha256": artifact["sha256"],
            }
        )
    _audit_validate_wheel_dependency_graph(lock, metadata_by_name)
    return module_paths, identities, tree_hashes


def _audit_network_isolation_prefix() -> tuple[list[str], dict[str, str]]:
    _require(
        sys.platform == "darwin",
        "no reviewed OS network isolator is available on this release host",
    )
    executable = Path("/usr/bin/sandbox-exec")
    _require(
        executable.exists()
        and not executable.is_symlink()
        and stat_module.S_ISREG(executable.stat().st_mode)
        and executable.stat().st_uid == 0
        and not bool(executable.stat().st_mode & 0o022),
        "trusted Darwin sandbox-exec is unavailable",
    )
    prefix = [str(executable), "-p", AUDIT_SANDBOX_PROFILE]
    probe = subprocess.run(
        [
            *prefix,
            str(Path(sys.executable).resolve()),
            "-I",
            "-S",
            "-c",
            (
                "import errno,socket,sys;"
                "s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);"
                "result=s.connect_ex(('1.1.1.1',53));s.close();"
                "sys.exit(0 if result==errno.EPERM else 91)"
            ),
        ],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={
            "HOME": os.devnull,
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        },
    )
    _require(
        probe.returncode == 0,
        "Darwin sandbox network-denial probe failed closed",
    )
    return prefix, {
        "kind": "darwin-sandbox-exec",
        "policy_sha256": _sha256_bytes(AUDIT_SANDBOX_PROFILE.encode("utf-8")),
        "executable_sha256": _sha256_path(executable),
    }


class _LockedAuditCompleted:
    def __init__(
        self,
        *,
        returncode: int,
        stdout: str,
        stderr: str,
        executed_artifacts: dict[str, str],
        network_isolated: bool,
        execution_identity: dict[str, Any],
    ):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.executed_artifacts = executed_artifacts
        self.network_isolated = network_isolated
        self.execution_identity = execution_identity


class LockedWheelSbomRunner:
    """Run esp-idf-sbom only from the reviewed wheel closure, offline."""

    def __init__(
        self,
        *,
        repo_root: Path,
        build_root: Path,
        wheelhouse: Path,
    ):
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._closed = False
        self._repo_root = Path(repo_root)
        self._build_root = Path(build_root)
        self._wheelhouse = Path(wheelhouse)
        _require(self._repo_root.is_dir(), "repository root is missing")
        _require(self._build_root.is_dir(), "license audit build root is missing")
        lock = _audit_load_tool_lock(self._repo_root)
        self._temporary = tempfile.TemporaryDirectory(prefix="pyble-locked-sbom-")
        try:
            private_root = Path(self._temporary.name)
            (
                self._module_paths,
                artifact_identities,
                self._tree_hashes,
            ) = _audit_prepare_locked_wheels(
                lock=lock,
                wheelhouse=self._wheelhouse,
                destination=private_root / "site",
            )
            self._isolation_prefix, isolation_identity = (
                _audit_network_isolation_prefix()
            )
            executable = Path(sys.executable).resolve()
            self._artifact_hashes = dict(sorted(lock["_artifact_hashes"].items()))
            self._execution_identity = {
                "runner": "pyble-locked-wheel-v1",
                "python": {
                    "implementation": sys.implementation.name,
                    "version": platform.python_version(),
                    "executable_sha256": _sha256_path(executable),
                },
                "isolation": isolation_identity,
                "artifacts": artifact_identities,
            }
            _audit_validate_execution_identity(
                self._execution_identity,
                artifact_hashes=self._artifact_hashes,
            )
            self._private_root = private_root
            self._python = str(executable)
        except Exception:
            self.close()
            raise

    def __enter__(self) -> "LockedWheelSbomRunner":
        _require(not self._closed, "locked SBOM runner is closed")
        return self

    def __exit__(self, *_args: Any) -> bool:
        self.close()
        return False

    def close(self) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None
        self._closed = True

    def _verify_private_closure(self) -> None:
        for name, expected in self._tree_hashes.items():
            _require(
                _audit_sha256_tree(self._private_root / "site" / name) == expected,
                "private locked-wheel environment changed during execution",
            )

    def __call__(
        self,
        argv: Any,
        *,
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
        check: bool = True,
        network_disabled: bool = False,
        **_unused: Any,
    ) -> _LockedAuditCompleted:
        _require(not self._closed, "locked SBOM runner is closed")
        _require(check is True, "locked SBOM runner requires checked execution")
        _require(
            network_disabled is True,
            "locked SBOM runner refuses a network-enabled invocation",
        )
        _require(
            isinstance(argv, (list, tuple))
            and all(isinstance(item, (str, Path)) for item in argv),
            "locked SBOM runner command is invalid",
        )
        command = [str(item) for item in argv]
        _require(
            len(command) == 10
            and command[:4] == [sys.executable, "-m", "esp_idf_sbom", "create"]
            and command[5] == "--output-file"
            and command[7:] == ["--rem-unused", "--rem-config", "--file-tags"],
            "locked SBOM runner rejected an unexpected command",
        )
        working = _audit_path_in_roots(
            Path(cwd) if cwd is not None else Path(),
            relative_to=self._build_root,
            roots=(self._build_root,),
            label="locked SBOM working directory",
        )
        _require(working.is_dir(), "locked SBOM working directory is missing")
        description = _audit_path_in_roots(
            command[4],
            relative_to=working,
            roots=(self._build_root,),
            label="locked SBOM project description",
        )
        _require(
            description.is_file() and description.name == "project_description.json",
            "locked SBOM project description is invalid",
        )
        output = Path(command[6])
        _require(
            output.is_absolute()
            and output.parent.is_dir()
            and not output.is_symlink()
            and not output.parent.is_symlink(),
            "locked SBOM output path is unsafe",
        )
        received_env = env if isinstance(env, dict) else {}
        clean_env = {
            key: value
            for key, value in received_env.items()
            if key in AUDIT_RUNNER_ALLOWED_ENV and isinstance(value, str)
        }
        clean_env.update(
            {
                "PIP_CONFIG_FILE": os.devnull,
                "PIP_NO_INDEX": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "PYTHONNOUSERSITE": "1",
                "TMPDIR": str(self._private_root),
            }
        )
        self._verify_private_closure()
        completed = subprocess.run(
            [
                *self._isolation_prefix,
                self._python,
                "-I",
                "-B",
                "-S",
                "-c",
                AUDIT_RUNNER_BOOTSTRAP,
                json.dumps(self._module_paths, separators=(",", ":")),
                *command[3:],
            ],
            cwd=working,
            env=clean_env,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._verify_private_closure()
        if completed.returncode != 0:
            raise ReleaseError(
                "locked esp-idf-sbom failed (%d): %s"
                % (completed.returncode, completed.stderr.strip()[-1000:])
            )
        return _LockedAuditCompleted(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            executed_artifacts=dict(self._artifact_hashes),
            network_isolated=True,
            execution_identity=copy.deepcopy(self._execution_identity),
        )


def _audit_immutable_ref(value: Any, label: str) -> str:
    _require(isinstance(value, str) and bool(value), "%s is missing" % label)
    commit = value.rsplit("@", 1)[-1]
    _require(
        COMMIT_RE.fullmatch(commit) is not None,
        "%s is not bound to a full immutable commit" % label,
    )
    return value


_AUDIT_POLICY_V2_KEYS = {
    "schema_version",
    "approved_license_refs",
    "review_files",
    "shipment_review",
    "raw_documents",
    "reviewed_packages",
    "resolved_inputs",
    "resolutions",
    "supplemental_packages",
    "toolchains",
}
_AUDIT_POLICY_V2_INPUT_KINDS = {
    "generated-component-archive",
    "generated-supplemental-archive",
    "opaque-archive",
    "toolchain-archive",
    "frozen-source-tree",
}
_AUDIT_POLICY_V2_SUPPLEMENTAL_INPUT_KINDS = {
    "generated-supplemental-archive",
    "frozen-source-tree",
}


def _audit_v2_hash(value: Any, label: str) -> str:
    _require(
        isinstance(value, str) and SHA256_RE.fullmatch(value) is not None,
        "%s must be a lowercase SHA-256" % label,
    )
    return value


def _audit_v2_nonempty(value: Any, label: str) -> str:
    _require(isinstance(value, str) and bool(value), "%s is missing" % label)
    return value


def _audit_v2_identity(
    profile_id: Any,
    role: Any,
    label: str,
) -> tuple[str, str]:
    valid_profiles = {
        profile for profile, _target, _idf_target in LICENSE_AUDIT_PROFILES
    }
    _require(
        isinstance(profile_id, str)
        and profile_id in valid_profiles
        and isinstance(role, str)
        and role in LICENSE_AUDIT_ROLES,
        "%s has an invalid profile/role identity" % label,
    )
    return profile_id, role


def _audit_v2_canonical(value: Any, label: str) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    except (TypeError, ValueError) as exc:
        raise ReleaseError("%s is not deterministic JSON data" % label) from exc


def _audit_v2_shipment_review(
    repo_root: Path,
    raw_record: Any,
    *,
    raw_occurrences: set[tuple[str, str, str]],
) -> tuple[dict[str, str], list[dict[str, str]], dict[tuple[str, str, str], str]]:
    """Validate the independent, canonical raw-package shipment ledger."""

    record = _exact_keys(
        raw_record,
        {"path", "sha256"},
        "shipment review policy",
    )
    relative = _safe_relative_path(
        record["path"],
        "shipment review policy path",
    )
    digest = _audit_v2_hash(
        record["sha256"],
        "shipment review policy digest",
    )
    path = _audit_repo_file(
        repo_root,
        relative,
        "shipment review ledger",
    )
    try:
        source = path.read_bytes()
        text = source.decode("utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise ReleaseError(
            "shipment review ledger is missing or not strict UTF-8"
        ) from exc
    _require(
        _sha256_bytes(source) == digest,
        "shipment review ledger changed",
    )
    try:
        document = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ReleaseError("shipment review ledger is not valid JSON") from exc
    _require(
        source
        == (
            _audit_v2_canonical(document, "shipment review ledger") + "\n"
        ).encode("utf-8"),
        "shipment review ledger is not canonical JSON",
    )
    document = _exact_keys(
        document,
        {"schema_version", "occurrences"},
        "shipment review ledger",
    )
    _require(
        type(document["schema_version"]) is int
        and document["schema_version"] == 1,
        "shipment review ledger schema_version must be 1",
    )
    occurrences = document["occurrences"]
    _require(
        isinstance(occurrences, list) and bool(occurrences),
        "shipment review ledger occurrences must be nonempty",
    )
    normalized: list[dict[str, str]] = []
    classifications: dict[tuple[str, str, str], str] = {}
    for raw in occurrences:
        occurrence = _exact_keys(
            raw,
            {"profile_id", "role", "spdx_id", "disposition"},
            "shipment review occurrence",
        )
        profile_id, role = _audit_v2_identity(
            occurrence["profile_id"],
            occurrence["role"],
            "shipment review occurrence",
        )
        spdx_id = _audit_v2_nonempty(
            occurrence["spdx_id"],
            "shipment review occurrence SPDXID",
        )
        disposition = occurrence["disposition"]
        _require(
            disposition in {"allow", "allow-aggregate", "not-shipped"},
            "shipment review occurrence disposition is invalid",
        )
        identity = (profile_id, role, spdx_id)
        _require(
            identity not in classifications,
            "shipment review occurrence is duplicated",
        )
        classifications[identity] = disposition
        normalized.append(
            {
                "profile_id": profile_id,
                "role": role,
                "spdx_id": spdx_id,
                "disposition": disposition,
            }
        )
    expected_order = sorted(
        normalized,
        key=lambda item: (
            item["profile_id"],
            item["role"],
            item["spdx_id"],
        ),
    )
    _require(
        normalized == expected_order,
        "shipment review occurrences are not canonically ordered",
    )
    _require(
        set(classifications) == raw_occurrences,
        "shipment review ledger does not exactly cover raw package occurrences",
    )
    return (
        {"path": relative, "sha256": digest},
        normalized,
        classifications,
    )


def _audit_v2_manifest_evidence(
    repo_root: Path,
    raw_evidence: Any,
) -> list[dict[str, Any]]:
    """Validate canonical literal-manifest evidence derived by the collector."""

    firmware_version = _read_lock(Path(repo_root))["pyble"]["agent_version"]
    includes_first_party_field = bool(
        _audit_first_party_frozen_sources_for_version(firmware_version)
    )
    _require(
        isinstance(raw_evidence, list) and bool(raw_evidence),
        "literal manifest evidence must be nonempty",
    )
    expected_targets = {
        target for _profile_id, target, _idf_target in LICENSE_AUDIT_PROFILES
    }
    normalized: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for raw_record in raw_evidence:
        expected_fields = {
            "target",
            "architecture",
            "frozen_content_sha256",
            "qstrdefs_sha256",
            "mpy_cross",
            "generator_tools",
            "frozen_mpy",
            "linked_frozen_object",
            "generated_board_manifest",
            "manifests",
            "selections",
        }
        if includes_first_party_field:
            expected_fields.add("first_party_frozen_sources")
        record = _exact_keys(
            raw_record,
            expected_fields,
            "literal manifest evidence record",
        )
        target = record["target"]
        _require(
            isinstance(target, str)
            and target in expected_targets
            and target not in seen_targets,
            "literal manifest evidence target is invalid or duplicated",
        )
        seen_targets.add(target)
        frozen_digest = _audit_v2_hash(
            record["frozen_content_sha256"],
            "%s frozen_content.c digest" % target,
        )
        architecture = record["architecture"]
        _require(
            architecture == FROZEN_TARGET_SETTINGS[target]["architecture"],
            "%s frozen architecture changed" % target,
        )
        qstr_digest = _audit_v2_hash(
            record["qstrdefs_sha256"],
            "%s frozen qstr header digest" % target,
        )
        mpy_cross = _exact_keys(
            record["mpy_cross"],
            {"path", "sha256"},
            "%s mpy-cross evidence" % target,
        )
        mpy_cross_path = _safe_relative_path(
            mpy_cross["path"],
            "%s mpy-cross path" % target,
        )
        _require(
            mpy_cross_path
            == "firmware/upstream/micropython/mpy-cross/build/mpy-cross",
            "%s mpy-cross path changed" % target,
        )
        mpy_cross_digest = _audit_v2_hash(
            mpy_cross["sha256"],
            "%s mpy-cross digest" % target,
        )
        checked_mpy_cross = _audit_repo_file(
            repo_root,
            mpy_cross_path,
            "%s mpy-cross" % target,
        )
        _require(
            _sha256_path(checked_mpy_cross) == mpy_cross_digest,
            "%s mpy-cross changed" % target,
        )

        expected_generator_paths = {
            "firmware/upstream/micropython/mpy-cross/mpy_cross/__init__.py",
            "firmware/upstream/micropython/py/makeqstrdata.py",
            "firmware/upstream/micropython/tools/makemanifest.py",
            "firmware/upstream/micropython/tools/manifestfile.py",
            "firmware/upstream/micropython/tools/mpy-tool.py",
        }
        generators_raw = record["generator_tools"]
        _require(
            isinstance(generators_raw, list) and bool(generators_raw),
            "%s frozen generator inventory must be nonempty" % target,
        )
        generators: list[dict[str, str]] = []
        generator_paths: set[str] = set()
        for raw_generator in generators_raw:
            generator = _exact_keys(
                raw_generator,
                {"path", "sha256"},
                "%s frozen generator" % target,
            )
            relative = _safe_relative_path(
                generator["path"],
                "%s frozen generator path" % target,
            )
            digest = _audit_v2_hash(
                generator["sha256"],
                "%s frozen generator digest" % target,
            )
            _require(
                relative not in generator_paths,
                "%s frozen generator path is duplicated" % target,
            )
            source = _audit_repo_file(
                repo_root,
                relative,
                "%s frozen generator" % target,
            )
            _require(
                _sha256_path(source) == digest,
                "%s frozen generator changed" % target,
            )
            generator_paths.add(relative)
            generators.append({"path": relative, "sha256": digest})
        _require(
            generator_paths == expected_generator_paths
            and generators == sorted(generators, key=lambda item: item["path"]),
            "%s frozen generator inventory changed or is unordered" % target,
        )
        generated_board_manifest = _safe_relative_path(
            record["generated_board_manifest"],
            "%s generated board manifest path" % target,
        )
        expected_board_manifest = (
            "firmware/upstream/micropython/ports/esp32/boards/%s/manifest.py"
            % FROZEN_TARGET_SETTINGS[target]["board"]
        )
        _require(
            generated_board_manifest == expected_board_manifest,
            "%s generated board manifest path changed" % target,
        )
        _audit_repo_file(
            repo_root,
            generated_board_manifest,
            "%s generated board manifest" % target,
        )

        manifests_raw = record["manifests"]
        _require(
            isinstance(manifests_raw, list) and bool(manifests_raw),
            "%s literal manifest inventory must be nonempty" % target,
        )
        manifests: list[dict[str, str]] = []
        manifest_paths: set[str] = set()
        for raw_manifest in manifests_raw:
            manifest = _exact_keys(
                raw_manifest,
                {"path", "sha256"},
                "%s literal manifest" % target,
            )
            relative = _safe_relative_path(
                manifest["path"],
                "%s literal manifest path" % target,
            )
            digest = _audit_v2_hash(
                manifest["sha256"],
                "%s literal manifest digest" % target,
            )
            _require(
                relative not in manifest_paths,
                "%s literal manifest path is duplicated" % target,
            )
            path = _audit_repo_file(
                repo_root,
                relative,
                "%s literal manifest" % target,
            )
            _require(
                _sha256_path(path) == digest,
                "%s literal manifest changed" % target,
            )
            manifest_paths.add(relative)
            manifests.append({"path": relative, "sha256": digest})
        _require(
            manifests == sorted(manifests, key=lambda item: item["path"]),
            "%s literal manifests are not canonically ordered" % target,
        )

        selections_raw = record["selections"]
        _require(
            isinstance(selections_raw, list) and bool(selections_raw),
            "%s frozen source selections must be nonempty" % target,
        )
        selections: list[dict[str, str]] = []
        destinations: set[str] = set()
        for raw_selection in selections_raw:
            selection = _exact_keys(
                raw_selection,
                {
                    "destination",
                    "source_path",
                    "sha256",
                    "optimization",
                    "metadata_version",
                },
                "%s frozen source selection" % target,
            )
            destination = _safe_relative_path(
                selection["destination"],
                "%s frozen destination" % target,
            )
            _require(
                destination.endswith(".py") and destination not in destinations,
                "%s frozen destination is invalid or duplicated" % target,
            )
            source_relative = _safe_relative_path(
                selection["source_path"],
                "%s frozen source path" % target,
            )
            digest = _audit_v2_hash(
                selection["sha256"],
                "%s frozen source digest" % target,
            )
            source = _audit_repo_file(
                repo_root,
                source_relative,
                "%s frozen source" % target,
            )
            _require(
                _sha256_path(source) == digest,
                "%s frozen source changed" % target,
            )
            optimization = selection["optimization"]
            _require(
                optimization is None
                or (
                    isinstance(optimization, int)
                    and not isinstance(optimization, bool)
                    and 0 <= optimization <= 3
                ),
                "%s frozen source optimization is invalid" % target,
            )
            metadata_version = selection["metadata_version"]
            _require(
                metadata_version is None
                or (
                    isinstance(metadata_version, str)
                    and re.fullmatch(
                        r"[0-9A-Za-z][0-9A-Za-z._+-]{0,127}",
                        metadata_version,
                    )
                    is not None
                ),
                "%s frozen source metadata version is invalid" % target,
            )
            destinations.add(destination)
            selections.append(
                {
                    "destination": destination,
                    "source_path": source_relative,
                    "sha256": digest,
                    "optimization": optimization,
                    "metadata_version": metadata_version,
                }
            )
        _require(
            selections
            == sorted(selections, key=lambda item: item["destination"]),
            "%s frozen source selections are not canonically ordered" % target,
        )
        first_party_frozen_sources = (
            _audit_first_party_frozen_source_evidence(
                repo_root=repo_root,
                target=target,
                board_dir=(
                    Path(repo_root)
                    / "firmware"
                    / "upstream"
                    / "micropython"
                    / "ports"
                    / "esp32"
                    / "boards"
                    / FROZEN_TARGET_SETTINGS[target]["board"]
                ),
                selections={
                    selection["destination"]: (
                        Path(repo_root) / selection["source_path"]
                    )
                    for selection in selections
                },
                firmware_version=firmware_version,
            )
        )
        if includes_first_party_field:
            _require(
                record["first_party_frozen_sources"]
                == first_party_frozen_sources,
                "%s first-party frozen source evidence changed" % target,
            )

        frozen_mpy_raw = record["frozen_mpy"]
        _require(
            isinstance(frozen_mpy_raw, list) and bool(frozen_mpy_raw),
            "%s frozen MPY inventory must be nonempty" % target,
        )
        frozen_mpy: list[dict[str, str]] = []
        mpy_destinations: set[str] = set()
        for raw_mpy in frozen_mpy_raw:
            mpy = _exact_keys(
                raw_mpy,
                {"destination", "sha256"},
                "%s frozen MPY record" % target,
            )
            destination = _safe_relative_path(
                mpy["destination"],
                "%s frozen MPY destination" % target,
            )
            digest = _audit_v2_hash(
                mpy["sha256"],
                "%s frozen MPY digest" % target,
            )
            _require(
                destination.endswith(".mpy")
                and destination not in mpy_destinations,
                "%s frozen MPY destination is invalid or duplicated" % target,
            )
            mpy_destinations.add(destination)
            frozen_mpy.append(
                {"destination": destination, "sha256": digest}
            )
        _require(
            mpy_destinations
            == {
                selection["destination"][:-3] + ".mpy"
                for selection in selections
            }
            and frozen_mpy
            == sorted(frozen_mpy, key=lambda item: item["destination"]),
            "%s frozen MPY inventory differs from selected sources" % target,
        )
        linked_raw = _exact_keys(
            record["linked_frozen_object"],
            {"component", "archive_path", "member", "sha256"},
            "%s linked frozen object" % target,
        )
        linked_component = linked_raw["component"]
        _require(
            isinstance(linked_component, str)
            and re.fullmatch(r"[0-9A-Za-z_.+-]+", linked_component)
            is not None,
            "%s linked frozen component is invalid" % target,
        )
        linked_archive = _safe_relative_path(
            linked_raw["archive_path"],
            "%s linked frozen archive" % target,
        )
        _require(
            linked_archive.startswith(target + "/")
            and linked_archive.endswith(".a"),
            "%s linked frozen archive identity is invalid" % target,
        )
        linked_member = linked_raw["member"]
        _require(
            isinstance(linked_member, str)
            and bool(linked_member)
            and Path(linked_member).name == linked_member
            and linked_member.endswith((".o", ".obj")),
            "%s linked frozen member identity is invalid" % target,
        )
        linked_digest = _audit_v2_hash(
            linked_raw["sha256"],
            "%s linked frozen object digest" % target,
        )
        normalized_record = {
            "target": target,
            "architecture": architecture,
            "frozen_content_sha256": frozen_digest,
            "qstrdefs_sha256": qstr_digest,
            "mpy_cross": {
                "path": mpy_cross_path,
                "sha256": mpy_cross_digest,
            },
            "generator_tools": generators,
            "frozen_mpy": frozen_mpy,
            "linked_frozen_object": {
                "component": linked_component,
                "archive_path": linked_archive,
                "member": linked_member,
                "sha256": linked_digest,
            },
            "generated_board_manifest": generated_board_manifest,
            "manifests": manifests,
            "selections": selections,
        }
        if includes_first_party_field:
            normalized_record["first_party_frozen_sources"] = (
                first_party_frozen_sources
            )
        normalized.append(normalized_record)
    _require(
        seen_targets == expected_targets,
        "literal manifest evidence does not cover the exact release targets",
    )
    _require(
        normalized == sorted(normalized, key=lambda item: item["target"]),
        "literal manifest evidence targets are not canonically ordered",
    )
    return normalized


def _audit_v2_regular_path(
    raw_path: Any,
    *,
    directory: bool,
    label: str,
) -> Path:
    _require(
        isinstance(raw_path, str) and Path(raw_path).is_absolute(),
        "%s must be an absolute path" % label,
    )
    path = Path(raw_path)
    _require(
        path.absolute() == path.resolve(),
        "%s must use its canonical path without symlink ancestors" % label,
    )
    for ancestor in (path, *path.parents):
        try:
            ancestor_mode = ancestor.lstat().st_mode
        except OSError as exc:
            raise ReleaseError("%s has a missing ancestor" % label) from exc
        _require(
            not stat_module.S_ISLNK(ancestor_mode),
            "%s traverses a symlink" % label,
        )
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise ReleaseError("%s is missing" % label) from exc
    _require(not stat_module.S_ISLNK(mode), "%s must not be a symlink" % label)
    if directory:
        _require(stat_module.S_ISDIR(mode), "%s must be a directory" % label)
    else:
        _require(stat_module.S_ISREG(mode), "%s must be a regular file" % label)
    return path


def _audit_v2_review_files(
    repo_root: Path,
    records: Any,
    label: str,
    *,
    expected_identifiers: set[str],
    approved_license_refs: set[str],
) -> list[dict[str, str]]:
    _require(
        isinstance(records, list) and bool(records),
        "%s has no complete license text" % label,
    )
    normalized: list[dict[str, str]] = []
    identifiers: set[str] = set()
    paths: set[tuple[str, str]] = set()
    for index, raw in enumerate(records):
        record = _exact_keys(
            raw,
            {"spdx_id", "path", "sha256"},
            "%s license text %d" % (label, index),
        )
        spdx_id = _audit_v2_nonempty(
            record["spdx_id"],
            "%s license text %d SPDX identifier" % (label, index),
        )
        _require(
            spdx_id in LICENSE_AUDIT_KNOWN_EXCEPTIONS
            or _audit_parse_spdx(spdx_id, approved_license_refs) == {spdx_id},
            "%s license text %d must name one SPDX identifier"
            % (label, index),
        )
        digest = _audit_v2_hash(
            record["sha256"],
            "%s license text %d digest" % (label, index),
        )
        path = _audit_repo_file(
            repo_root,
            record["path"],
            "%s complete license text" % label,
        )
        _require(
            _sha256_path(path) == digest,
            "%s complete license text changed" % label,
        )
        identity = (record["path"], digest)
        _require(
            spdx_id not in identifiers and identity not in paths,
            "%s duplicates a complete license text" % label,
        )
        identifiers.add(spdx_id)
        paths.add(identity)
        normalized.append(
            {
                "spdx_id": spdx_id,
                "path": record["path"],
                "sha256": digest,
            }
        )
    _require(
        identifiers == expected_identifiers,
        "%s complete license texts do not exactly cover its SPDX expression"
        % label,
    )
    return normalized


def _audit_v2_supporting_review_files(
    repo_root: Path,
    records: Any,
) -> list[dict[str, Any]]:
    _require(
        isinstance(records, list) and bool(records),
        "review_files must be a nonempty array",
    )
    identifiers: set[str] = set()
    paths: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(records):
        record = _exact_keys(
            raw,
            {"id", "purpose", "path", "sha256", "source_identities"},
            "review file %d" % index,
        )
        identifier = _audit_v2_nonempty(
            record["id"],
            "review file %d id" % index,
        )
        purpose = _audit_v2_nonempty(
            record["purpose"],
            "review file %s purpose" % identifier,
        )
        _require(
            identifier not in identifiers,
            "review file id is duplicated",
        )
        digest = _audit_v2_hash(
            record["sha256"],
            "review file %s digest" % identifier,
        )
        path = _audit_repo_file(
            repo_root,
            record["path"],
            "review file %s" % identifier,
        )
        _require(
            record["path"] not in paths and _sha256_path(path) == digest,
            "review file %s is duplicated or changed" % identifier,
        )
        source_identities = record["source_identities"]
        _require(
            isinstance(source_identities, list)
            and bool(source_identities)
            and all(
                isinstance(value, str)
                and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value)
                is not None
                for value in source_identities
            )
            and len(source_identities) == len(set(source_identities)),
            "review file %s source identities are invalid" % identifier,
        )
        identifiers.add(identifier)
        paths.add(record["path"])
        normalized.append(
            {
                "id": identifier,
                "purpose": purpose,
                "path": record["path"],
                "sha256": digest,
                "source_identities": list(source_identities),
            }
        )
    return normalized


def _audit_v2_notice(
    repo_root: Path,
    raw: Any,
    label: str,
) -> dict[str, Any]:
    _require(isinstance(raw, dict), "%s NOTICE policy is invalid" % label)
    required = raw.get("required")
    _require(isinstance(required, bool), "%s NOTICE required flag is invalid" % label)
    if not required:
        _exact_keys(raw, {"required"}, "%s NOTICE" % label)
        return {"required": False}
    record = _exact_keys(
        raw,
        {"required", "path", "sha256"},
        "%s NOTICE" % label,
    )
    digest = _audit_v2_hash(record["sha256"], "%s NOTICE digest" % label)
    path = _audit_repo_file(repo_root, record["path"], "%s NOTICE" % label)
    _require(_sha256_path(path) == digest, "%s NOTICE changed" % label)
    return {
        "required": True,
        "path": record["path"],
        "sha256": digest,
    }


def _audit_v2_dependency(
    raw: Any,
    label: str,
) -> dict[str, str]:
    record = _exact_keys(
        raw,
        {"name", "version_ref", "source_url", "copyright"},
        "%s dependency" % label,
    )
    for field in ("name", "copyright"):
        _audit_v2_nonempty(record[field], "%s dependency.%s" % (label, field))
    _audit_immutable_ref(
        record["version_ref"],
        "%s dependency version_ref" % label,
    )
    _require(
        isinstance(record["source_url"], str)
        and record["source_url"].startswith("https://"),
        "%s dependency source URL is not HTTPS" % label,
    )
    commits = re.findall(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", record["version_ref"])
    _require(
        len(commits) == 1 and commits[0] in record["source_url"],
        "%s dependency source URL is not bound to its full immutable ref" % label,
    )
    return copy.deepcopy(record)


def _audit_v2_source(
    repo_root: Path,
    raw: Any,
    label: str,
    *,
    allow_tree: bool,
) -> dict[str, Any]:
    _require(isinstance(raw, dict), "%s source metadata is invalid" % label)
    expected = {"ref", "url"}
    if allow_tree and ("tree_path" in raw or "tree_sha256" in raw):
        expected |= {"tree_path", "tree_sha256"}
    record = _exact_keys(raw, expected, "%s source" % label)
    _audit_immutable_ref(record["ref"], "%s source ref" % label)
    _require(
        isinstance(record["url"], str) and record["url"].startswith("https://"),
        "%s source URL is not immutable HTTPS metadata" % label,
    )
    if "tree_path" in record:
        relative = _safe_relative_path(
            record["tree_path"],
            "%s source tree" % label,
        )
        digest = _audit_v2_hash(
            record["tree_sha256"],
            "%s source tree digest" % label,
        )
        path = repo_root / relative
        _audit_no_symlink_components(repo_root, path, "%s source tree" % label)
        _require(
            _audit_sha256_source_tree(path, reject_python_cache=True) == digest,
            "%s source tree changed" % label,
        )
    return copy.deepcopy(record)


def _audit_v2_generated_binding(
    raw: Any,
    label: str,
) -> dict[str, Any]:
    _require(isinstance(raw, dict), "%s generated binding is invalid" % label)
    expected = {
        "component",
        "project_description_sha256",
        "compile_commands_sha256",
        "linker_map_sha256",
        "sources",
        "members",
    }
    is_main = raw.get("component") == "main"
    if is_main:
        expected.update(
            {
                "linker_command_sha256",
                "metadata_inputs",
                "direct_objects",
            }
        )
    if "nested_archive" in raw:
        expected.add("nested_archive")
    binding = _exact_keys(raw, expected, "%s generated binding" % label)
    _audit_v2_nonempty(binding["component"], "%s component" % label)
    if "nested_archive" in binding:
        nested = _exact_keys(
            binding["nested_archive"],
            {
                "target",
                "archive_build_path",
                "object_build_directory",
            },
            "%s nested archive" % label,
        )
        _audit_v2_nonempty(nested["target"], "%s nested target" % label)
        for field in ("archive_build_path", "object_build_directory"):
            _safe_relative_path(
                nested[field],
                "%s nested %s" % (label, field),
            )
    for field in (
        "project_description_sha256",
        "compile_commands_sha256",
        "linker_map_sha256",
    ):
        _audit_v2_hash(binding[field], "%s %s" % (label, field))
    if is_main:
        _audit_v2_hash(
            binding["linker_command_sha256"],
            "%s linker command digest" % label,
        )
    sources = binding["sources"]
    _require(
        isinstance(sources, list) and bool(sources),
        "%s generated binding has no compiled sources" % label,
    )
    source_paths: set[str] = set()
    for index, raw_source in enumerate(sources):
        source = _exact_keys(
            raw_source,
            {"path", "sha256"},
            "%s source %d" % (label, index),
        )
        source_path = _safe_relative_path(
            source["path"],
            "%s source path" % label,
        )
        _audit_v2_hash(source["sha256"], "%s source digest" % label)
        _require(
            source_path not in source_paths,
            "%s generated binding duplicates a source" % label,
        )
        source_paths.add(source_path)
    members = binding["members"]
    _require(
        isinstance(members, list)
        and bool(members)
        and all(isinstance(member, str) and member for member in members),
        "%s generated archive member multiset is invalid" % label,
    )
    if is_main:
        metadata_inputs = binding["metadata_inputs"]
        _require(
            isinstance(metadata_inputs, list),
            "%s generated metadata inputs are invalid" % label,
        )
        metadata_paths: set[str] = set()
        for index, raw_metadata in enumerate(metadata_inputs):
            metadata = _exact_keys(
                raw_metadata,
                {"path", "sha256"},
                "%s metadata input %d" % (label, index),
            )
            metadata_path = _safe_relative_path(
                metadata["path"],
                "%s metadata input path" % label,
            )
            _audit_v2_hash(
                metadata["sha256"],
                "%s metadata input digest" % label,
            )
            _require(
                metadata_path not in metadata_paths,
                "%s generated binding duplicates a metadata input" % label,
            )
            metadata_paths.add(metadata_path)
        _require(
            metadata_inputs
            == sorted(metadata_inputs, key=lambda item: item["path"]),
            "%s metadata inputs are not canonical" % label,
        )

        direct_objects = binding["direct_objects"]
        _require(
            isinstance(direct_objects, list) and bool(direct_objects),
            "%s generated direct-object inventory is empty" % label,
        )
        direct_output_paths: set[str] = set()
        for index, raw_direct in enumerate(direct_objects):
            direct = _exact_keys(
                raw_direct,
                {"output", "source"},
                "%s direct object %d" % (label, index),
            )
            for field in ("output", "source"):
                record = _exact_keys(
                    direct[field],
                    {"path", "sha256"},
                    "%s direct object %d %s" % (label, index, field),
                )
                logical_path = _safe_relative_path(
                    record["path"],
                    "%s direct object %s path" % (label, field),
                )
                _audit_v2_hash(
                    record["sha256"],
                    "%s direct object %s digest" % (label, field),
                )
                if field == "output":
                    _require(
                        logical_path.startswith("build/"),
                        "%s direct object output is not a build path" % label,
                    )
                    _require(
                        logical_path not in direct_output_paths,
                        "%s generated binding duplicates a direct output" % label,
                    )
                    direct_output_paths.add(logical_path)
        _require(
            direct_objects
            == sorted(
                direct_objects,
                key=lambda item: item["output"]["path"],
            ),
            "%s direct objects are not canonical" % label,
        )
    return copy.deepcopy(binding)


def _audit_v2_generated_matcher(
    raw: Any,
    label: str,
) -> dict[str, Any]:
    """Validate the stable, build-independent selector committed in policy."""

    _require(isinstance(raw, dict), "%s generated matcher is invalid" % label)
    expected = {"component"}
    if "nested_archive" in raw:
        expected.add("nested_archive")
    matcher = _exact_keys(raw, expected, "%s generated matcher" % label)
    _audit_v2_nonempty(matcher["component"], "%s component" % label)
    if "nested_archive" in matcher:
        nested = _exact_keys(
            matcher["nested_archive"],
            {
                "target",
                "archive_build_path",
                "object_build_directory",
            },
            "%s nested archive matcher" % label,
        )
        _audit_v2_nonempty(nested["target"], "%s nested target" % label)
        for field in ("archive_build_path", "object_build_directory"):
            _safe_relative_path(
                nested[field],
                "%s nested %s" % (label, field),
            )
    return copy.deepcopy(matcher)


def _audit_v2_observed_documents(
    observed_documents: Any,
) -> tuple[
    dict[tuple[str, str], dict[str, Any]],
    dict[tuple[str, str, str], dict[str, Any]],
]:
    _require(
        isinstance(observed_documents, dict),
        "observed SPDX documents must be a mapping",
    )
    documents: dict[tuple[str, str], dict[str, Any]] = {}
    raw_packages: dict[tuple[str, str, str], dict[str, Any]] = {}
    for raw_identity, raw_document in observed_documents.items():
        if (
            isinstance(raw_identity, tuple)
            and len(raw_identity) == 2
            and all(isinstance(item, str) for item in raw_identity)
        ):
            profile_id, role = raw_identity
        elif isinstance(raw_identity, str) and raw_identity.count("/") == 1:
            profile_id, role = raw_identity.split("/", 1)
        else:
            raise ReleaseError("observed SPDX document identity is invalid")
        identity = _audit_v2_identity(
            profile_id,
            role,
            "observed SPDX document",
        )
        _require(
            identity not in documents,
            "observed SPDX document identity is duplicated",
        )
        _require(
            isinstance(raw_document, dict),
            "observed SPDX document is not an object",
        )
        packages = raw_document.get("packages")
        relationships = raw_document.get("relationships")
        _require(
            isinstance(packages, list) and bool(packages),
            "observed SPDX document contains no packages",
        )
        _require(
            isinstance(relationships, list) and bool(relationships),
            "observed SPDX document contains no relationships",
        )
        package_ids: set[str] = set()
        for package in packages:
            _require(isinstance(package, dict), "observed SPDX package is invalid")
            required = {
                "name",
                "SPDXID",
                "downloadLocation",
                "filesAnalyzed",
                "licenseConcluded",
                "licenseDeclared",
                "copyrightText",
            }
            _require(
                required <= set(package),
                "observed SPDX package property set is incomplete",
            )
            if "versionInfo" in package:
                _require(
                    isinstance(package["versionInfo"], str)
                    and bool(package["versionInfo"]),
                    "observed SPDX package versionInfo is explicitly empty",
                )
            spdx_id = package["SPDXID"]
            _require(
                isinstance(spdx_id, str)
                and _AUDIT_SPDX_ELEMENT_RE.fullmatch(spdx_id) is not None
                and spdx_id != "SPDXRef-DOCUMENT"
                and spdx_id not in package_ids,
                "observed SPDX package ID is invalid or duplicated",
            )
            _audit_v2_canonical(package, "observed SPDX package")
            package_ids.add(spdx_id)
            raw_packages[(identity[0], identity[1], spdx_id)] = copy.deepcopy(package)
        known_elements = {"SPDXRef-DOCUMENT"} | package_ids
        for relationship in relationships:
            relation = _exact_keys(
                relationship,
                {
                    "spdxElementId",
                    "relationshipType",
                    "relatedSpdxElement",
                },
                "observed SPDX relationship",
            )
            _require(
                all(
                    isinstance(relation[field], str) and relation[field]
                    for field in relation
                )
                and relation["spdxElementId"] in known_elements
                and relation["relatedSpdxElement"] in known_elements,
                "observed SPDX relationship names an unknown element",
            )
        documents[identity] = {
            "packages": copy.deepcopy(packages),
            "relationships": copy.deepcopy(relationships),
        }
    expected_identities = {
        (profile_id, role)
        for profile_id, _target, _idf_target in LICENSE_AUDIT_PROFILES
        for role in LICENSE_AUDIT_ROLES
    }
    _require(
        set(documents) == expected_identities,
        "observed SPDX documents do not cover the exact six profile/roles",
    )
    return documents, raw_packages


def _audit_v2_observed_inputs(
    observed_inputs: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    _require(
        isinstance(observed_inputs, list) and bool(observed_inputs),
        "observed redistributed inputs must be a nonempty array",
    )
    records: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    frozen_destination_owners: set[tuple[str, str, str]] = set()
    common = {
        "id",
        "profile_id",
        "role",
        "kind",
        "observed_path",
        "sha256",
    }
    kind_fields = {
        "generated-component-archive": {"generated_binding"},
        "generated-supplemental-archive": {"generated_binding"},
        "opaque-archive": {"reviewed_source_path"},
        "toolchain-archive": {
            "toolchain_id",
            "relative_path",
            "compiler_paths",
        },
        "frozen-source-tree": {"frozen_destinations"},
    }
    for raw in observed_inputs:
        _require(isinstance(raw, dict), "observed redistributed input is invalid")
        kind = raw.get("kind")
        _require(
            kind in _AUDIT_POLICY_V2_INPUT_KINDS,
            "observed redistributed input kind is unsupported",
        )
        record = _exact_keys(
            raw,
            common | kind_fields[kind],
            "observed redistributed input",
        )
        identifier = _audit_v2_nonempty(
            record["id"],
            "observed redistributed input id",
        )
        _require(
            identifier not in records,
            "observed redistributed input id is duplicated",
        )
        _audit_v2_identity(
            record["profile_id"],
            record["role"],
            "observed redistributed input %s" % identifier,
        )
        directory = kind == "frozen-source-tree"
        path = _audit_v2_regular_path(
            record["observed_path"],
            directory=directory,
            label="observed redistributed input %s" % identifier,
        )
        actual_digest = _audit_sha256_tree(path) if directory else _sha256_path(path)
        declared_digest = _audit_v2_hash(
            record["sha256"],
            "observed redistributed input %s digest" % identifier,
        )
        _require(
            actual_digest == declared_digest,
            "observed redistributed input %s changed" % identifier,
        )
        if kind.startswith("generated-"):
            _audit_v2_generated_binding(
                record["generated_binding"],
                "observed redistributed input %s" % identifier,
            )
        elif kind == "opaque-archive":
            _safe_relative_path(
                record["reviewed_source_path"],
                "observed opaque source",
            )
        elif kind == "toolchain-archive":
            _audit_v2_nonempty(
                record["toolchain_id"],
                "observed toolchain id",
            )
            _safe_relative_path(
                record["relative_path"],
                "observed toolchain archive",
            )
            compiler_paths = record["compiler_paths"]
            _require(
                isinstance(compiler_paths, list)
                and bool(compiler_paths)
                and all(
                    isinstance(compiler_path, str)
                    and Path(compiler_path).is_absolute()
                    for compiler_path in compiler_paths
                )
                and compiler_paths == sorted(compiler_paths)
                and len(compiler_paths) == len(set(compiler_paths)),
                "observed toolchain compiler paths are invalid",
            )
        else:
            destinations = record["frozen_destinations"]
            _require(
                isinstance(destinations, list)
                and bool(destinations)
                and all(
                    isinstance(destination, str)
                    and _safe_relative_path(
                        destination,
                        "frozen destination",
                    )
                    == destination
                    for destination in destinations
                )
                and len(destinations) == len(set(destinations)),
                "observed frozen destination inventory is invalid",
            )
            destination_owners = {
                (record["profile_id"], record["role"], destination)
                for destination in destinations
            }
            _require(
                frozen_destination_owners.isdisjoint(destination_owners),
                "observed frozen destination has more than one owner",
            )
            frozen_destination_owners.update(destination_owners)
        records[identifier] = copy.deepcopy(record)
        hashes[identifier] = actual_digest
    return records, dict(sorted(hashes.items()))


def _audit_v2_distribution_members(
    source: bytes | Path,
    *,
    root_name: str,
    required_paths: set[str],
    label: str,
) -> dict[str, dict[str, Any]]:
    try:
        if isinstance(source, Path):
            archive = tarfile.open(name=source, mode="r:xz")
        else:
            archive = tarfile.open(fileobj=io.BytesIO(source), mode="r:xz")
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise ReleaseError("%s is not a valid tar.xz archive" % label) from exc
    members: dict[str, tarfile.TarInfo] = {}
    regular: dict[str, tarfile.TarInfo] = {}
    links: dict[str, str] = {}
    total_size = 0
    with archive:
        infos = archive.getmembers()
        _require(
            0 < len(infos) <= 250_000,
            "%s has an unsafe member count" % label,
        )
        for info in infos:
            name = info.name
            pure = PurePosixPath(name)
            _require(
                "\\" not in name
                and not pure.is_absolute()
                and all(part not in ("", ".", "..") for part in pure.parts)
                and pure.as_posix() == name,
                "%s contains an unsafe path" % label,
            )
            if info.isdir() and len(pure.parts) == 1:
                _require(
                    pure.parts[0] == root_name,
                    "%s contains a directory outside its declared root" % label,
                )
                continue
            _require(
                len(pure.parts) >= 2 and pure.parts[0] == root_name,
                "%s contains a path outside its declared root" % label,
            )
            relative = PurePosixPath(*pure.parts[1:]).as_posix()
            if info.isdir():
                continue
            _require(
                relative not in members,
                "%s contains a duplicate path" % label,
            )
            members[relative] = info
            if info.isfile():
                _require(
                    0 <= info.size <= 1024 * 1024 * 1024,
                    "%s contains an oversized member" % label,
                )
                total_size += info.size
                _require(
                    total_size <= 4 * 1024 * 1024 * 1024,
                    "%s expands beyond the audit safety limit" % label,
                )
                regular[relative] = info
                continue
            _require(
                info.issym() or info.islnk(),
                "%s contains a special file" % label,
            )
            link = PurePosixPath(info.linkname)
            if info.issym():
                target = PurePosixPath(relative).parent / link
            else:
                target = link
                if target.parts and target.parts[0] == root_name:
                    target = PurePosixPath(*target.parts[1:])
            normalized_parts: list[str] = []
            for part in target.parts:
                if part in ("", "."):
                    continue
                if part == "..":
                    _require(
                        bool(normalized_parts),
                        "%s link escapes its declared root" % label,
                    )
                    normalized_parts.pop()
                else:
                    normalized_parts.append(part)
            _require(
                not target.is_absolute() and bool(normalized_parts),
                "%s contains an unsafe link target" % label,
            )
            links[relative] = PurePosixPath(*normalized_parts).as_posix()

        for relative, target in links.items():
            seen = {relative}
            while target in links:
                _require(
                    target not in seen,
                    "%s contains a link cycle" % label,
                )
                seen.add(target)
                target = links[target]
            _require(
                target in regular,
                "%s link target is missing or not regular" % label,
            )

        _require(bool(regular), "%s contains no regular files" % label)
        results: dict[str, dict[str, Any]] = {}
        for relative in sorted(required_paths):
            _require(
                relative in members,
                "%s omits a required member" % label,
            )
            target = relative
            while target in links:
                target = links[target]
            info = regular.get(target)
            _require(
                info is not None,
                "%s required member is not regular" % label,
            )
            extracted = archive.extractfile(info)
            _require(extracted is not None, "%s member is unreadable" % label)
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = extracted.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                _require(
                    size <= info.size,
                    "%s member exceeds its declared size" % label,
                )
                digest.update(chunk)
            _require(size == info.size, "%s member is truncated" % label)
            results[relative] = {
                "size": size,
                "sha256": digest.hexdigest(),
            }
    return results


def _audit_v2_compiler_frontends(
    raw: Any,
    label: str,
) -> list[dict[str, str]]:
    _require(
        isinstance(raw, list) and bool(raw),
        "%s compiler_frontends must be a nonempty array" % label,
    )
    records: list[dict[str, str]] = []
    for index, value in enumerate(raw):
        frontend = _exact_keys(
            value,
            {"relative_path", "sha256"},
            "%s compiler frontend %d" % (label, index),
        )
        relative = _safe_relative_path(
            frontend["relative_path"],
            "%s compiler frontend %d" % (label, index),
        )
        digest = _audit_v2_hash(
            frontend["sha256"],
            "%s compiler frontend %d digest" % (label, index),
        )
        records.append(
            {
                "relative_path": relative,
                "sha256": digest,
            }
        )
    relative_paths = [record["relative_path"] for record in records]
    _require(
        relative_paths == sorted(relative_paths)
        and len(relative_paths) == len(set(relative_paths)),
        "%s compiler_frontends must be unique and sorted by relative_path"
        % label,
    )
    frontend_names = {Path(relative).name for relative in relative_paths}
    gcc_prefixes = {
        name[: -len("-gcc")]
        for name in frontend_names
        if name.endswith("-gcc")
    }
    gxx_prefixes = {
        name[: -len("-g++")]
        for name in frontend_names
        if name.endswith("-g++")
    }
    _require(
        len(records) == 2
        and len(gcc_prefixes) == 1
        and gcc_prefixes == gxx_prefixes,
        "%s compiler_frontends must contain exactly one matched gcc/g++ pair"
        % label,
    )
    return records


def _audit_v2_derive_toolchain_cache_context(
    policy: dict[str, Any],
    *,
    repo_root: Path,
    compiler_paths: set[Path],
) -> dict[str, dict[str, str]]:
    """Derive private tool/cache paths from reviewed policy and compiler paths."""

    _require(isinstance(policy, dict), "toolchain cache policy is invalid")
    policy_records = policy.get("toolchains")
    _require(isinstance(policy_records, list), "toolchains must be an array")
    _require(
        isinstance(compiler_paths, set) and bool(compiler_paths),
        "observed toolchain compiler set is invalid",
    )
    observed_compilers: set[Path] = set()
    for raw_path in compiler_paths:
        compiler = _audit_v2_regular_path(
            str(raw_path),
            directory=False,
            label="observed toolchain compiler",
        )
        _require(
            compiler not in observed_compilers,
            "observed toolchain compiler is duplicated",
        )
        observed_compilers.add(compiler)

    contexts: dict[str, dict[str, str]] = {}
    consumed_compilers: set[Path] = set()
    for raw in policy_records:
        record = _exact_keys(
            raw,
            {
                "id",
                "name",
                "version",
                "platform",
                "install_root_relative",
                "compiler_frontends",
                "distribution",
                "metadata",
                "admitted_archive_paths",
            },
            "toolchain policy",
        )
        identifier = _audit_v2_nonempty(record["id"], "toolchain id")
        _require(identifier not in contexts, "toolchain id is duplicated")
        name = _audit_v2_nonempty(record["name"], "toolchain %s name" % identifier)
        version = _audit_v2_nonempty(
            record["version"],
            "toolchain %s version" % identifier,
        )
        platform_name = _audit_v2_nonempty(
            record["platform"],
            "toolchain %s platform" % identifier,
        )

        compiler_frontends = _audit_v2_compiler_frontends(
            record["compiler_frontends"],
            "toolchain %s" % identifier,
        )

        distribution = _exact_keys(
            record["distribution"],
            {
                "url",
                "filename",
                "size",
                "sha256",
                "archive_format",
                "archive_root",
            },
            "toolchain %s distribution" % identifier,
        )
        distribution_url = distribution["url"]
        _require(
            isinstance(distribution_url, str),
            "toolchain %s distribution URL is invalid" % identifier,
        )
        parsed_url = urlsplit(distribution_url)
        _require(
            parsed_url.scheme == "https"
            and bool(parsed_url.netloc)
            and not parsed_url.query
            and not parsed_url.fragment,
            "toolchain %s distribution URL is not canonical HTTPS" % identifier,
        )
        filename = _safe_relative_path(
            distribution["filename"],
            "toolchain %s distribution filename" % identifier,
        )
        _require(
            "/" not in filename
            and parsed_url.path.rsplit("/", 1)[-1] == filename,
            "toolchain %s distribution filename disagrees with its URL"
            % identifier,
        )
        archive_root = _safe_relative_path(
            distribution["archive_root"],
            "toolchain %s distribution archive root" % identifier,
        )
        _require(
            "/" not in archive_root
            and distribution["archive_format"] == "tar.xz",
            "toolchain %s distribution identity changed" % identifier,
        )
        distribution_digest = _audit_v2_hash(
            distribution["sha256"],
            "toolchain %s distribution digest" % identifier,
        )
        _require(
            isinstance(distribution["size"], int)
            and not isinstance(distribution["size"], bool)
            and distribution["size"] > 0,
            "toolchain %s distribution size is invalid" % identifier,
        )

        install_relative = _safe_relative_path(
            record["install_root_relative"],
            "toolchain %s installed root" % identifier,
        )
        _require(
            PurePosixPath(install_relative).parts
            == ("tools", name, version, archive_root),
            "toolchain %s installed root disagrees with its reviewed identity"
            % identifier,
        )
        frontend_paths: list[Path] = []
        tools_homes: set[Path] = set()
        for frontend in compiler_frontends:
            frontend_relative = frontend["relative_path"]
            frontend_suffix = Path(install_relative) / frontend_relative
            suffix_parts = frontend_suffix.parts
            matches = {
                compiler
                for compiler in observed_compilers
                if len(compiler.parts) > len(suffix_parts)
                and compiler.parts[-len(suffix_parts) :] == suffix_parts
            }
            _require(
                len(matches) == 1,
                "toolchain %s compiler frontend does not select one trusted "
                "installation" % identifier,
            )
            frontend_path = next(iter(matches))
            _require(
                frontend_path not in consumed_compilers
                and _sha256_path(frontend_path) == frontend["sha256"],
                "toolchain %s compiler frontend identity changed" % identifier,
            )
            consumed_compilers.add(frontend_path)
            frontend_paths.append(frontend_path)
            tools_home_candidate = frontend_path
            for _part in suffix_parts:
                tools_home_candidate = tools_home_candidate.parent
            tools_homes.add(tools_home_candidate)
        _require(
            len(tools_homes) == 1,
            "toolchain %s compiler frontends do not share one trusted tools "
            "home" % identifier,
        )
        tools_home = next(iter(tools_homes))
        tools_home = _audit_v2_regular_path(
            str(tools_home),
            directory=True,
            label="toolchain %s tools home" % identifier,
        )
        tools_dir = _audit_v2_regular_path(
            str(tools_home / "tools"),
            directory=True,
            label="toolchain %s installed tools directory" % identifier,
        )
        installed_root = _audit_v2_regular_path(
            str(tools_home / install_relative),
            directory=True,
            label="toolchain %s installed root" % identifier,
        )
        _require(
            tools_dir == tools_home / "tools"
            and frontend_paths
            == [
                installed_root / frontend["relative_path"]
                for frontend in compiler_frontends
            ],
            "toolchain %s compiler frontends escaped their reviewed "
            "installation" % identifier,
        )

        metadata_record = _exact_keys(
            record["metadata"],
            {"path", "sha256"},
            "toolchain %s metadata" % identifier,
        )
        metadata_digest = _audit_v2_hash(
            metadata_record["sha256"],
            "toolchain %s metadata digest" % identifier,
        )
        metadata_path = _audit_repo_file(
            repo_root,
            metadata_record["path"],
            "toolchain %s ESP-IDF metadata" % identifier,
        )
        _require(
            _sha256_path(metadata_path) == metadata_digest,
            "toolchain %s ESP-IDF metadata changed" % identifier,
        )
        metadata = _read_json(
            metadata_path,
            "toolchain %s ESP-IDF metadata" % identifier,
        )
        tools = metadata.get("tools") if isinstance(metadata, dict) else None
        _require(
            isinstance(tools, list),
            "toolchain %s ESP-IDF metadata has no tool inventory" % identifier,
        )
        tool_matches = [
            item
            for item in tools
            if isinstance(item, dict) and item.get("name") == name
        ]
        _require(
            len(tool_matches) == 1,
            "toolchain %s ESP-IDF metadata identity is ambiguous" % identifier,
        )
        tool_metadata = tool_matches[0]
        versions = tool_metadata.get("versions")
        _require(
            isinstance(versions, list),
            "toolchain %s ESP-IDF metadata has no versions" % identifier,
        )
        version_matches = [
            item
            for item in versions
            if isinstance(item, dict) and item.get("name") == version
        ]
        _require(
            len(version_matches) == 1,
            "toolchain %s ESP-IDF metadata version is ambiguous" % identifier,
        )
        platform_distribution = version_matches[0].get(platform_name)
        platform_distribution = _exact_keys(
            platform_distribution,
            {"url", "size", "sha256"},
            "toolchain %s ESP-IDF platform distribution" % identifier,
        )
        _require(
            platform_distribution
            == {
                "url": distribution_url,
                "size": distribution["size"],
                "sha256": distribution_digest,
            },
            "toolchain %s policy disagrees with ESP-IDF distribution metadata"
            % identifier,
        )
        frontend_export_directories = {
            PurePosixPath(frontend["relative_path"]).parts[0]
            for frontend in compiler_frontends
        }
        _require(
            len(frontend_export_directories) == 1,
            "toolchain %s compiler frontend export directories changed"
            % identifier,
        )
        expected_export = [archive_root, next(iter(frontend_export_directories))]
        _require(
            tool_metadata.get("export_paths") == [expected_export],
            "toolchain %s ESP-IDF export path changed" % identifier,
        )

        dist_dir = _audit_v2_regular_path(
            str(tools_home / "dist"),
            directory=True,
            label="toolchain %s distribution cache directory" % identifier,
        )
        cache_path = _audit_v2_regular_path(
            str(dist_dir / filename),
            directory=False,
            label="toolchain %s cached distribution" % identifier,
        )
        _require(
            cache_path.stat().st_size == distribution["size"]
            and _sha256_path(cache_path) == distribution_digest,
            "toolchain %s cached distribution changed" % identifier,
        )
        distribution_frontends = _audit_v2_distribution_members(
            cache_path,
            root_name=archive_root,
            required_paths={
                frontend["relative_path"] for frontend in compiler_frontends
            },
            label="toolchain %s cached distribution" % identifier,
        )
        for frontend, frontend_path in zip(
            compiler_frontends,
            frontend_paths,
        ):
            distribution_frontend = distribution_frontends.get(
                frontend["relative_path"]
            )
            _require(
                distribution_frontend is not None
                and frontend_path.stat().st_size
                == distribution_frontend["size"]
                and _sha256_path(frontend_path)
                == distribution_frontend["sha256"],
                "toolchain %s compiler frontend differs from its distribution"
                % identifier,
            )
        contexts[identifier] = {
            "root": str(installed_root),
            "trusted_anchor": str(tools_home),
            "root_relative": install_relative,
            "distribution_cache_path": str(cache_path),
            "distribution_cache_relative": "dist/%s" % filename,
        }

    _require(
        consumed_compilers == observed_compilers,
        "observed compiler set does not exactly match reviewed toolchains",
    )
    return contexts


def _audit_v2_toolchains(
    *,
    policy_records: Any,
    repo_root: Path,
    observed_inputs: dict[str, dict[str, Any]],
    toolchain_roots: Any,
) -> dict[str, dict[str, Any]]:
    _require(isinstance(policy_records, list), "toolchains must be an array")
    toolchain_observations = [
        record
        for record in observed_inputs.values()
        if record["kind"] == "toolchain-archive"
    ]
    declared_id_values: list[str] = []
    for record in policy_records:
        _require(
            isinstance(record, dict)
            and isinstance(record.get("id"), str)
            and bool(record["id"]),
            "toolchain policy id is invalid",
        )
        declared_id_values.append(record["id"])
    _require(
        len(declared_id_values) == len(set(declared_id_values)),
        "toolchain policy id is duplicated",
    )
    declared_ids = set(declared_id_values)
    _require(
        isinstance(toolchain_roots, dict)
        and all(isinstance(identifier, str) for identifier in toolchain_roots)
        and set(toolchain_roots) == declared_ids,
        "verified toolchain roots do not match policy",
    )
    validated: dict[str, dict[str, Any]] = {}
    for raw in policy_records:
        record = _exact_keys(
            raw,
            {
                "id",
                "name",
                "version",
                "platform",
                "install_root_relative",
                "compiler_frontends",
                "distribution",
                "metadata",
                "admitted_archive_paths",
            },
            "toolchain policy",
        )
        identifier = _audit_v2_nonempty(record["id"], "toolchain id")
        _require(identifier not in validated, "toolchain id is duplicated")
        for field in ("name", "version", "platform", "install_root_relative"):
            _audit_v2_nonempty(record[field], "toolchain %s %s" % (identifier, field))
        raw_context = toolchain_roots[identifier]
        _require(
            isinstance(raw_context, dict),
            "toolchain %s root lacks collector-verified context" % identifier,
        )
        context = _exact_keys(
            raw_context,
            {
                "root",
                "trusted_anchor",
                "root_relative",
                "distribution_cache_path",
                "distribution_cache_relative",
            },
            "toolchain %s verified root context" % identifier,
        )
        root = Path(context["root"])
        trusted_anchor = Path(context["trusted_anchor"])
        root_relative = _safe_relative_path(
            context["root_relative"],
            "toolchain %s trusted root relative path" % identifier,
        )
        _require(
            root.is_absolute()
            and trusted_anchor.is_absolute()
            and root == trusted_anchor / root_relative
            and root.absolute() == root.resolve()
            and trusted_anchor.absolute() == trusted_anchor.resolve(),
            "toolchain %s root is not collector-bound to its trusted anchor"
            % identifier,
        )
        for ancestor in (trusted_anchor, *trusted_anchor.parents):
            try:
                ancestor_mode = ancestor.lstat().st_mode
            except OSError as exc:
                raise ReleaseError(
                    "toolchain %s trusted anchor is missing" % identifier
                ) from exc
            _require(
                not stat_module.S_ISLNK(ancestor_mode),
                "toolchain %s trusted anchor traverses a symlink" % identifier,
            )
        _audit_no_symlink_components(
            trusted_anchor,
            root,
            "toolchain %s root" % identifier,
        )
        try:
            root_mode = root.lstat().st_mode
        except OSError as exc:
            raise ReleaseError("toolchain %s root is missing" % identifier) from exc
        _require(
            stat_module.S_ISDIR(root_mode)
            and not stat_module.S_ISLNK(root_mode)
            and root_relative == record["install_root_relative"],
            "toolchain %s root identity is not the reviewed version" % identifier,
        )

        compiler_frontends = _audit_v2_compiler_frontends(
            record["compiler_frontends"],
            "toolchain %s" % identifier,
        )
        frontend_paths: list[Path] = []
        for frontend in compiler_frontends:
            frontend_path = root / frontend["relative_path"]
            _audit_no_symlink_components(
                root,
                frontend_path,
                "toolchain %s compiler frontend" % identifier,
            )
            try:
                frontend_mode = frontend_path.lstat().st_mode
            except OSError as exc:
                raise ReleaseError(
                    "toolchain %s compiler frontend is missing" % identifier
                ) from exc
            _require(
                stat_module.S_ISREG(frontend_mode)
                and not stat_module.S_ISLNK(frontend_mode)
                and _sha256_path(frontend_path) == frontend["sha256"],
                "toolchain %s compiler frontend identity changed" % identifier,
            )
            frontend_paths.append(frontend_path)

        admitted = record["admitted_archive_paths"]
        _require(
            isinstance(admitted, list)
            and bool(admitted)
            and all(isinstance(path, str) for path in admitted),
            "toolchain %s admitted archive paths are invalid" % identifier,
        )
        admitted_paths = [
            _safe_relative_path(
                path,
                "toolchain %s admitted archive" % identifier,
            )
            for path in admitted
        ]
        _require(
            len(admitted_paths) == len(set(admitted_paths)),
            "toolchain %s admitted archive path is duplicated" % identifier,
        )

        metadata = _exact_keys(
            record["metadata"],
            {"path", "sha256"},
            "toolchain %s metadata" % identifier,
        )
        metadata_digest = _audit_v2_hash(
            metadata["sha256"],
            "toolchain %s metadata digest" % identifier,
        )
        metadata_path = _audit_repo_file(
            repo_root,
            metadata["path"],
            "toolchain %s ESP-IDF metadata" % identifier,
        )
        _require(
            _sha256_path(metadata_path) == metadata_digest,
            "toolchain %s ESP-IDF metadata changed" % identifier,
        )

        distribution = _exact_keys(
            record["distribution"],
            {
                "url",
                "filename",
                "size",
                "sha256",
                "archive_format",
                "archive_root",
            },
            "toolchain %s distribution" % identifier,
        )
        _require(
            isinstance(distribution["url"], str)
            and distribution["url"].startswith("https://"),
            "toolchain %s distribution URL is not HTTPS" % identifier,
        )
        distribution_filename = _safe_relative_path(
            distribution["filename"],
            "toolchain %s distribution filename" % identifier,
        )
        distribution_root = _safe_relative_path(
            distribution["archive_root"],
            "toolchain %s distribution archive root" % identifier,
        )
        _require(
            "/" not in distribution_filename
            and "/" not in distribution_root
            and urlsplit(distribution["url"]).path.rsplit("/", 1)[-1]
            == distribution_filename
            and distribution["archive_format"] == "tar.xz",
            "toolchain %s distribution identity changed" % identifier,
        )
        distribution_path = _audit_v2_regular_path(
            context["distribution_cache_path"],
            directory=False,
            label="toolchain %s cached distribution" % identifier,
        )
        distribution_relative = _safe_relative_path(
            context["distribution_cache_relative"],
            "toolchain %s cached distribution" % identifier,
        )
        _require(
            distribution_relative == "dist/%s" % distribution_filename
            and distribution_path == trusted_anchor / distribution_relative,
            "toolchain %s cached distribution is not collector-bound"
            % identifier,
        )
        distribution_digest = _audit_v2_hash(
            distribution["sha256"],
            "toolchain %s distribution digest" % identifier,
        )
        _require(
            isinstance(distribution["size"], int)
            and not isinstance(distribution["size"], bool)
            and distribution["size"] > 0
            and distribution_path.stat().st_size == distribution["size"]
            and _sha256_path(distribution_path) == distribution_digest,
            "toolchain %s cached distribution changed" % identifier,
        )
        distribution_members = _audit_v2_distribution_members(
            distribution_path,
            root_name=distribution_root,
            required_paths={
                *(frontend["relative_path"] for frontend in compiler_frontends),
                *admitted_paths,
            },
            label="toolchain %s cached distribution" % identifier,
        )
        for frontend, frontend_path in zip(
            compiler_frontends,
            frontend_paths,
        ):
            frontend_distribution = distribution_members.get(
                frontend["relative_path"]
            )
            _require(
                frontend_distribution is not None
                and frontend_path.stat().st_size
                == frontend_distribution["size"]
                and _sha256_path(frontend_path)
                == frontend_distribution["sha256"],
                "toolchain %s compiler frontend differs from its distribution"
                % identifier,
            )

        for relative in admitted_paths:
            installed = root / relative
            _audit_no_symlink_components(
                root,
                installed,
                "toolchain %s admitted archive" % identifier,
            )
            try:
                mode = installed.lstat().st_mode
            except OSError as exc:
                raise ReleaseError(
                    "toolchain %s admitted archive is missing" % identifier
                ) from exc
            distribution_member = distribution_members.get(relative)
            _require(
                stat_module.S_ISREG(mode)
                and not stat_module.S_ISLNK(mode)
                and distribution_member is not None
                and installed.stat().st_size == distribution_member["size"]
                and _sha256_path(installed) == distribution_member["sha256"],
                "toolchain %s archive differs from its distribution" % identifier,
            )

        matching_observations = [
            observation
            for observation in toolchain_observations
            if observation["toolchain_id"] == identifier
        ]
        _require(
            bool(matching_observations),
            "toolchain %s has no observed input" % identifier,
        )
        observed_relatives = {
            observation["relative_path"] for observation in matching_observations
        }
        _require(
            observed_relatives == set(admitted_paths),
            "toolchain %s observed archive set changed" % identifier,
        )
        expected_frontend_paths = set(frontend_paths)
        observed_frontend_paths: set[Path] = set()
        for observation in matching_observations:
            relative = observation["relative_path"]
            observed_path = Path(observation["observed_path"])
            observation_frontends = [
                _audit_v2_regular_path(
                    compiler_path,
                    directory=False,
                    label="toolchain %s observed compiler frontend"
                    % identifier,
                )
                for compiler_path in observation["compiler_paths"]
            ]
            _require(
                observed_path.resolve() == (root / relative).resolve()
                and bool(observation_frontends)
                and set(observation_frontends) <= expected_frontend_paths,
                "toolchain %s observation comes from an unreviewed root" % identifier,
            )
            observed_frontend_paths.update(observation_frontends)
        _require(
            observed_frontend_paths == expected_frontend_paths,
            "toolchain %s observed compiler frontend set changed" % identifier,
        )
        validated[identifier] = {
            "id": identifier,
            "name": record["name"],
            "version": record["version"],
            "platform": record["platform"],
            "install_root_relative": record["install_root_relative"],
            "compiler_frontends": copy.deepcopy(compiler_frontends),
            "metadata_path": metadata["path"],
            "metadata_sha256": metadata_digest,
            "distribution_url": distribution["url"],
            "distribution_filename": distribution_filename,
            "distribution_archive_root": distribution_root,
            "distribution_size": distribution["size"],
            "distribution_sha256": distribution_digest,
            "admitted_archive_paths": admitted_paths,
        }
    observed_toolchain_ids = {
        observation["toolchain_id"] for observation in toolchain_observations
    }
    _require(
        observed_toolchain_ids == set(validated),
        "observed toolchain input lacks exact reviewed policy",
    )
    return validated


def _audit_v2_zero_input_proof(
    raw: Any,
    *,
    package_refs: list[dict[str, str]],
    reviewed_package_id: str,
    observed_inputs: dict[str, dict[str, Any]],
    policy_inputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    proof = _exact_keys(
        raw,
        {"profile_roles"},
        "not-shipped zero-input proof",
    )
    records = proof["profile_roles"]
    _require(
        isinstance(records, list) and bool(records),
        "not-shipped zero-input proof has no profile/role records",
    )
    expected_identities = {
        (ref["profile_id"], ref["role"]) for ref in package_refs
    }
    normalized: list[dict[str, Any]] = []
    observed_identities: set[tuple[str, str]] = set()
    for raw_record in records:
        record = _exact_keys(
            raw_record,
            {
                "profile_id",
                "role",
                "matched_input_ids",
            },
            "not-shipped zero-input proof record",
        )
        identity = _audit_v2_identity(
            record["profile_id"],
            record["role"],
            "not-shipped zero-input proof",
        )
        _require(
            identity not in observed_identities,
            "not-shipped zero-input proof duplicates a profile/role",
        )
        observed_identities.add(identity)
        matched = record["matched_input_ids"]
        _require(
            isinstance(matched, list)
            and all(isinstance(item, str) and item for item in matched)
            and len(matched) == len(set(matched)),
            "not-shipped zero-input matched input IDs are invalid",
        )
        expected_matched = sorted(
            identifier
            for identifier, policy_input in policy_inputs.items()
            if policy_input["reviewed_package_id"] == reviewed_package_id
            and (
                policy_input["profile_id"],
                policy_input["role"],
            )
            == identity
        )
        _require(
            matched == expected_matched == [],
            "not-shipped zero-input proof names a redistributed input",
        )
        bindings = {
            (
                item["generated_binding"]["project_description_sha256"],
                item["generated_binding"]["compile_commands_sha256"],
                item["generated_binding"]["linker_map_sha256"],
            )
            for item in observed_inputs.values()
            if (item["profile_id"], item["role"]) == identity
            and item["kind"].startswith("generated-")
        }
        _require(
            len(bindings) == 1,
            "not-shipped zero-input proof is not bound to the observed build",
        )
        (
            project_description_sha256,
            compile_commands_sha256,
            linker_map_sha256,
        ) = next(iter(bindings))
        normalized.append(
            {
                "profile_id": identity[0],
                "role": identity[1],
                "project_description_sha256": project_description_sha256,
                "compile_commands_sha256": compile_commands_sha256,
                "linker_map_sha256": linker_map_sha256,
                "matched_input_ids": [],
            }
        )
    _require(
        observed_identities == expected_identities,
        "not-shipped zero-input proof does not cover its raw package identities",
    )
    return {
        "profile_roles": sorted(
            normalized,
            key=lambda item: (item["profile_id"], item["role"]),
        )
    }


def _audit_v2_aggregate_proof(
    raw: Any,
    *,
    package_refs: list[dict[str, str]],
    reviewed_package_id: str,
    documents: dict[tuple[str, str], dict[str, Any]],
    resolution_by_reviewed: dict[str, dict[str, Any]],
    policy_inputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Validate raw-relationship paths from aggregate packages to input owners."""

    proof = _exact_keys(raw, {"profile_roles"}, "aggregate relationship proof")
    records = proof["profile_roles"]
    _require(
        isinstance(records, list) and bool(records),
        "aggregate relationship proof has no profile/role records",
    )
    expected_refs = {
        (ref["profile_id"], ref["role"], ref["spdx_id"]) for ref in package_refs
    }
    observed_refs: set[tuple[str, str, str]] = set()
    normalized: list[dict[str, Any]] = []
    for raw_record in records:
        record = _exact_keys(
            raw_record,
            {
                "profile_id",
                "role",
                "relationship_path",
                "input_owning_reviewed_package_id",
            },
            "aggregate relationship proof record",
        )
        identity = _audit_v2_identity(
            record["profile_id"],
            record["role"],
            "aggregate relationship proof",
        )
        path = record["relationship_path"]
        _require(
            isinstance(path, list) and bool(path),
            "aggregate relationship proof path is empty",
        )
        relationships = Counter(
            _audit_v2_canonical(
                relationship,
                "observed SPDX relationship",
            )
            for relationship in documents[identity]["relationships"]
        )
        normalized_path: list[dict[str, str]] = []
        first = _exact_keys(
            path[0],
            {
                "spdxElementId",
                "relationshipType",
                "relatedSpdxElement",
            },
            "aggregate relationship path edge",
        )
        candidate_starts = {
            first["spdxElementId"],
            first["relatedSpdxElement"],
        } & {
            spdx_id
            for profile_id, role, spdx_id in expected_refs
            if (profile_id, role) == identity
        }
        _require(
            len(candidate_starts) == 1,
            "aggregate relationship proof does not start at its raw package",
        )
        start = next(iter(candidate_starts))
        current = start
        visited = {current}
        for raw_edge in path:
            edge = _exact_keys(
                raw_edge,
                {
                    "spdxElementId",
                    "relationshipType",
                    "relatedSpdxElement",
                },
                "aggregate relationship path edge",
            )
            _require(
                relationships[
                    _audit_v2_canonical(
                        edge,
                        "aggregate relationship path edge",
                    )
                ]
                > 0,
                "aggregate relationship proof invents a raw relationship",
            )
            source = edge["spdxElementId"]
            related = edge["relatedSpdxElement"]
            _require(
                edge["relationshipType"] == "DEPENDS_ON"
                and "SPDXRef-DOCUMENT" not in (source, related)
                and current in (source, related)
                and source != related,
                "aggregate relationship proof path is disconnected",
            )
            current = related if current == source else source
            _require(
                current not in visited,
                "aggregate relationship proof path is cyclic",
            )
            visited.add(current)
            normalized_path.append(copy.deepcopy(edge))

        target_reviewed_id = _audit_v2_nonempty(
            record["input_owning_reviewed_package_id"],
            "aggregate relationship proof target",
        )
        _require(
            target_reviewed_id != reviewed_package_id,
            "aggregate relationship proof targets itself",
        )
        target = resolution_by_reviewed.get(target_reviewed_id)
        _require(
            target is not None
            and target["disposition"] == "allow"
            and bool(target["input_refs"])
            and any(
                (
                    policy_inputs[input_ref]["profile_id"],
                    policy_inputs[input_ref]["role"],
                )
                == identity
                for input_ref in target["input_refs"]
            )
            and any(
                (
                    ref["profile_id"],
                    ref["role"],
                    ref["spdx_id"],
                )
                == (identity[0], identity[1], current)
                for ref in target["package_refs"]
            ),
            "aggregate relationship proof does not terminate at an input owner",
        )
        proof_ref = (identity[0], identity[1], start)
        _require(
            proof_ref not in observed_refs,
            "aggregate relationship proof duplicates a raw package",
        )
        observed_refs.add(proof_ref)
        normalized.append(
            {
                "profile_id": identity[0],
                "role": identity[1],
                "relationship_path": normalized_path,
                "input_owning_reviewed_package_id": target_reviewed_id,
            }
        )
    _require(
        observed_refs == expected_refs,
        "aggregate relationship proof does not cover its exact raw packages",
    )
    return {
        "profile_roles": sorted(
            normalized,
            key=lambda item: (
                item["profile_id"],
                item["role"],
                _audit_v2_canonical(
                    item["relationship_path"],
                    "aggregate relationship proof path",
                ),
            ),
        )
    }


def _audit_validate_policy_v2(
    policy: Any,
    *,
    repo_root: Path,
    observed_documents: Any,
    observed_inputs: Any,
    manifest_evidence: Any,
    toolchain_roots: Any = None,
) -> dict[str, Any]:
    """Validate schema-v2 raw/reviewed/resolved license evidence.

    This seam consumes already parsed raw SPDX and already reconciled build
    observations. It is deliberately deterministic and returns the hashes and
    normalized review records needed by the audit receipt and public notice.
    """

    root = Path(repo_root)
    _require(root.is_dir(), "license policy repository root is missing")
    policy = _exact_keys(policy, _AUDIT_POLICY_V2_KEYS, "license policy v2")
    _require(
        type(policy["schema_version"]) is int
        and policy["schema_version"] == 2,
        "release license policy schema_version must be 2",
    )
    approved_raw = policy["approved_license_refs"]
    _require(
        isinstance(approved_raw, list)
        and all(isinstance(item, str) and item for item in approved_raw)
        and len(approved_raw) == len(set(approved_raw)),
        "approved_license_refs must be a unique array of strings",
    )
    approved = set(approved_raw)
    validated_review_files = _audit_v2_supporting_review_files(
        root,
        policy["review_files"],
    )

    documents, raw_packages = _audit_v2_observed_documents(observed_documents)
    policy_documents = policy["raw_documents"]
    _require(
        isinstance(policy_documents, list),
        "license policy raw_documents must be an array",
    )
    policy_document_identities: set[tuple[str, str]] = set()
    for raw_document in policy_documents:
        record = _exact_keys(
            raw_document,
            {"profile_id", "role", "packages", "relationships"},
            "license policy raw document",
        )
        identity = _audit_v2_identity(
            record["profile_id"],
            record["role"],
            "license policy raw document",
        )
        _require(
            identity not in policy_document_identities,
            "license policy raw document identity is duplicated",
        )
        policy_document_identities.add(identity)
        _require(
            isinstance(record["packages"], list)
            and isinstance(record["relationships"], list),
            "license policy raw evidence is invalid",
        )
        expected_packages: dict[str, str] = {}
        for package in record["packages"]:
            _require(
                isinstance(package, dict) and isinstance(package.get("SPDXID"), str),
                "license policy raw package is invalid",
            )
            spdx_id = package["SPDXID"]
            _require(
                spdx_id not in expected_packages,
                "license policy raw package ID is duplicated",
            )
            expected_packages[spdx_id] = _audit_v2_canonical(
                package,
                "license policy raw package",
            )
        actual_packages = {
            package["SPDXID"]: _audit_v2_canonical(
                package,
                "observed SPDX package",
            )
            for package in documents[identity]["packages"]
        }
        _require(
            expected_packages == actual_packages,
            "raw SPDX package property sets disagree with reviewed policy",
        )
        expected_relationships = Counter(
            _audit_v2_canonical(
                relationship,
                "license policy raw relationship",
            )
            for relationship in record["relationships"]
        )
        actual_relationships = Counter(
            _audit_v2_canonical(
                relationship,
                "observed SPDX relationship",
            )
            for relationship in documents[identity]["relationships"]
        )
        _require(
            expected_relationships == actual_relationships,
            "raw SPDX relationship multiset disagrees with reviewed policy",
        )
    _require(
        policy_document_identities == set(documents),
        "license policy does not cover the exact raw SPDX documents",
    )
    (
        validated_shipment_review,
        shipment_classifications,
        shipment_by_occurrence,
    ) = _audit_v2_shipment_review(
        root,
        policy["shipment_review"],
        raw_occurrences=set(raw_packages),
    )
    validated_manifest_evidence = _audit_v2_manifest_evidence(
        root,
        manifest_evidence,
    )

    reviewed_raw = policy["reviewed_packages"]
    _require(
        isinstance(reviewed_raw, list) and bool(reviewed_raw),
        "license policy reviewed_packages must be nonempty",
    )
    reviewed: dict[str, dict[str, Any]] = {}
    for raw_record in reviewed_raw:
        expected_reviewed_fields = {
            "id",
            "dependency",
            "source",
            "reviewed_raw_package_expression",
            "license_texts",
            "notice",
        }
        if isinstance(raw_record, dict) and "reviewed_input_expressions" in raw_record:
            expected_reviewed_fields.add("reviewed_input_expressions")
        record = _exact_keys(
            raw_record,
            expected_reviewed_fields,
            "reviewed package",
        )
        identifier = _audit_v2_nonempty(record["id"], "reviewed package id")
        _require(identifier not in reviewed, "reviewed package id is duplicated")
        dependency = _audit_v2_dependency(record["dependency"], identifier)
        source = _audit_v2_source(
            root,
            record["source"],
            identifier,
            allow_tree=False,
        )
        _require(
            source["ref"] == dependency["version_ref"]
            and source["url"] == dependency["source_url"],
            "%s reviewed dependency/source metadata disagrees" % identifier,
        )
        expression = record["reviewed_raw_package_expression"]
        raw_expression_identifiers = _audit_parse_spdx(expression, approved)
        if "reviewed_input_expressions" in record:
            input_expressions = record["reviewed_input_expressions"]
            _require(
                isinstance(input_expressions, list)
                and bool(input_expressions)
                and all(
                    isinstance(input_expression, str) and bool(input_expression)
                    for input_expression in input_expressions
                )
                and len(input_expressions) == len(set(input_expressions)),
                "%s reviewed input expressions are invalid" % identifier,
            )
        else:
            input_expressions = [expression]
        input_expression_identifiers = {
            input_expression: _audit_parse_spdx(input_expression, approved)
            for input_expression in input_expressions
        }
        all_expression_identifiers = set(raw_expression_identifiers)
        for identifiers in input_expression_identifiers.values():
            all_expression_identifiers.update(identifiers)
        reviewed[identifier] = {
            "id": identifier,
            "dependency": dependency,
            "source": source,
            "reviewed_raw_package_expression": expression,
            "reviewed_input_expressions": list(input_expressions),
            "license_texts": _audit_v2_review_files(
                root,
                record["license_texts"],
                identifier,
                expected_identifiers=all_expression_identifiers,
                approved_license_refs=approved,
            ),
            "raw_license_identifiers": raw_expression_identifiers,
            "input_expression_identifiers": input_expression_identifiers,
            "license_identifiers": all_expression_identifiers,
            "notice": _audit_v2_notice(
                root,
                record["notice"],
                identifier,
            ),
        }

    observed_by_id, observed_hashes = _audit_v2_observed_inputs(observed_inputs)
    policy_inputs_raw = policy["resolved_inputs"]
    _require(
        isinstance(policy_inputs_raw, list) and bool(policy_inputs_raw),
        "license policy resolved_inputs must be nonempty",
    )
    policy_inputs: dict[str, dict[str, Any]] = {}
    generated_bindings: dict[str, dict[str, Any]] = {}
    common_input_fields = {
        "id",
        "profile_id",
        "role",
        "kind",
        "reviewed_package_id",
    }
    for raw_input in policy_inputs_raw:
        _require(isinstance(raw_input, dict), "resolved input policy is invalid")
        kind = raw_input.get("kind")
        _require(
            kind in _AUDIT_POLICY_V2_INPUT_KINDS,
            "resolved input policy kind is unsupported",
        )
        if kind.startswith("generated-"):
            expected_fields = common_input_fields | {"generated_matcher"}
        elif kind == "opaque-archive":
            expected_fields = common_input_fields | {
                "reviewed_source_path",
                "sha256",
            }
        elif kind == "toolchain-archive":
            expected_fields = common_input_fields | {
                "toolchain_id",
                "relative_path",
                "sha256",
            }
        else:
            expected_fields = common_input_fields | {
                "path",
                "sha256",
                "frozen_destinations",
            }
        record = _exact_keys(
            raw_input,
            expected_fields,
            "resolved input policy",
        )
        identifier = _audit_v2_nonempty(record["id"], "resolved input id")
        _require(identifier not in policy_inputs, "resolved input id is duplicated")
        _audit_v2_nonempty(
            record["reviewed_package_id"],
            "resolved input %s reviewed package" % identifier,
        )
        _audit_v2_identity(
            record["profile_id"],
            record["role"],
            "resolved input %s" % identifier,
        )
        observed = observed_by_id.get(identifier)
        _require(
            observed is not None
            and observed["profile_id"] == record["profile_id"]
            and observed["role"] == record["role"]
            and observed["kind"] == kind,
            "resolved input %s does not match an exact observation" % identifier,
        )
        if kind.startswith("generated-"):
            matcher = _audit_v2_generated_matcher(
                record["generated_matcher"],
                "resolved input %s" % identifier,
            )
            binding = _audit_v2_generated_binding(
                observed["generated_binding"],
                "observed resolved input %s" % identifier,
            )
            _require(
                (
                    "nested_archive" not in matcher
                    or kind == "generated-supplemental-archive"
                )
                and binding["component"] == matcher["component"]
                and binding.get("nested_archive") == matcher.get("nested_archive"),
                "generated input %s stable matcher disagrees with observation"
                % identifier,
            )
            generated_bindings[identifier] = binding
        elif kind == "opaque-archive":
            relative = _safe_relative_path(
                record["reviewed_source_path"],
                "opaque input %s source" % identifier,
            )
            digest = _audit_v2_hash(
                record["sha256"],
                "opaque input %s digest" % identifier,
            )
            source_path = _audit_repo_file(
                root,
                relative,
                "opaque input %s reviewed source" % identifier,
            )
            _require(
                observed["reviewed_source_path"] == relative
                and _sha256_path(source_path) == digest
                and observed["sha256"] == digest,
                "opaque input %s changed or lacks reviewed provenance" % identifier,
            )
        elif kind == "toolchain-archive":
            relative = _safe_relative_path(
                record["relative_path"],
                "toolchain input %s" % identifier,
            )
            digest = _audit_v2_hash(
                record["sha256"],
                "toolchain input %s digest" % identifier,
            )
            _require(
                record["toolchain_id"] == observed["toolchain_id"]
                and relative == observed["relative_path"]
                and digest == observed["sha256"],
                "toolchain input %s changed" % identifier,
            )
        else:
            relative = _safe_relative_path(
                record["path"],
                "frozen input %s source tree" % identifier,
            )
            digest = _audit_v2_hash(
                record["sha256"],
                "frozen input %s digest" % identifier,
            )
            path = root / relative
            _audit_no_symlink_components(
                root,
                path,
                "frozen input %s source tree" % identifier,
            )
            _require(
                _audit_sha256_tree(path) == digest
                and observed["sha256"] == digest
                and Path(observed["observed_path"]).resolve() == path.resolve()
                and record["frozen_destinations"] == observed["frozen_destinations"],
                "frozen input %s changed" % identifier,
            )
        policy_inputs[identifier] = copy.deepcopy(record)
    _require(
        set(policy_inputs) == set(observed_by_id),
        "resolved input policy does not exactly cover observations",
    )

    validated_toolchains = _audit_v2_toolchains(
        policy_records=policy["toolchains"],
        repo_root=root,
        observed_inputs=observed_by_id,
        toolchain_roots={} if toolchain_roots is None else toolchain_roots,
    )

    raw_consumers: Counter[tuple[str, str, str]] = Counter()
    input_consumers: Counter[str] = Counter()
    normalized_packages: dict[tuple[str, str, str], dict[str, Any]] = {}
    resolutions_raw = policy["resolutions"]
    _require(
        isinstance(resolutions_raw, list) and bool(resolutions_raw),
        "license policy resolutions must be nonempty",
    )
    resolution_ids: set[str] = set()
    reviewed_consumers: Counter[str] = Counter()
    validated_resolutions: list[dict[str, Any]] = []
    resolution_by_reviewed: dict[str, dict[str, Any]] = {}
    resolution_notice_identifiers: dict[str, set[str]] = {}
    for raw_resolution in resolutions_raw:
        _require(isinstance(raw_resolution, dict), "license resolution is invalid")
        base_fields = {
            "id",
            "reviewed_package_id",
            "package_refs",
            "input_refs",
            "resolved_input_expression",
            "disposition",
            "attribution",
        }
        disposition = raw_resolution.get("disposition")
        expected_fields = set(base_fields)
        if disposition == "not-shipped":
            expected_fields.add("zero_input_proof")
        elif disposition == "allow-aggregate":
            expected_fields.add("aggregate_proof")
        resolution = _exact_keys(
            raw_resolution,
            expected_fields,
            "license resolution",
        )
        identifier = _audit_v2_nonempty(resolution["id"], "license resolution id")
        _require(
            identifier not in resolution_ids,
            "license resolution id is duplicated",
        )
        resolution_ids.add(identifier)
        reviewed_id = resolution["reviewed_package_id"]
        _require(
            isinstance(reviewed_id, str) and reviewed_id in reviewed,
            "license resolution names an unknown reviewed package",
        )
        reviewed_consumers[reviewed_id] += 1
        reviewed_record = reviewed[reviewed_id]
        expression = resolution["resolved_input_expression"]
        resolved_identifiers = _audit_parse_spdx(expression, approved)
        _require(
            expression in reviewed_record["input_expression_identifiers"],
            "license resolution expression is not an exact reviewed input expression",
        )
        attribution = _audit_v2_nonempty(
            resolution["attribution"],
            "license resolution attribution",
        )
        package_refs = resolution["package_refs"]
        input_refs = resolution["input_refs"]
        _require(
            isinstance(package_refs, list) and bool(package_refs),
            "license resolution has no raw package references",
        )
        _require(
            isinstance(input_refs, list)
            and all(
                isinstance(input_ref, str) and input_ref for input_ref in input_refs
            ),
            "license resolution input references are invalid",
        )
        if disposition == "allow":
            _require(
                bool(input_refs),
                "allowed license resolution has no redistributed inputs",
            )
            zero_input_proof = None
            aggregate_proof = None
        elif disposition == "allow-aggregate":
            _require(
                not input_refs and isinstance(resolution["aggregate_proof"], dict),
                "aggregate resolution lacks an exact relationship proof",
            )
            _require(
                expression
                == reviewed_record["reviewed_raw_package_expression"],
                "aggregate resolution must retain its reviewed raw expression",
            )
            zero_input_proof = None
            aggregate_proof = resolution["aggregate_proof"]
        elif disposition == "not-shipped":
            _require(
                not input_refs and isinstance(resolution["zero_input_proof"], dict),
                "not-shipped resolution lacks an exact zero-input proof",
            )
            _require(
                expression
                == reviewed_record["reviewed_raw_package_expression"],
                "not-shipped resolution must retain its reviewed raw expression",
            )
            zero_input_proof = resolution["zero_input_proof"]
            aggregate_proof = None
        else:
            raise ReleaseError("license resolution disposition is not approved")

        normalized_refs: list[dict[str, str]] = []
        for raw_ref in package_refs:
            ref = _exact_keys(
                raw_ref,
                {"profile_id", "role", "spdx_id"},
                "license resolution package reference",
            )
            profile_id, role = _audit_v2_identity(
                ref["profile_id"],
                ref["role"],
                "license resolution package reference",
            )
            spdx_id = _audit_v2_nonempty(
                ref["spdx_id"],
                "license resolution package SPDXID",
            )
            key = (profile_id, role, spdx_id)
            package = raw_packages.get(key)
            _require(
                package is not None,
                "license resolution names an unobserved raw package",
            )
            _require(
                shipment_by_occurrence[key] == disposition,
                "license resolution disposition disagrees with shipment review",
            )
            raw_consumers[key] += 1
            concluded = package.get("licenseConcluded")
            declared = package.get("licenseDeclared")
            reviewed_expression = reviewed_record["reviewed_raw_package_expression"]
            if concluded not in ("NOASSERTION", "NONE"):
                _audit_parse_spdx(concluded, approved)
                _require(
                    concluded == reviewed_expression,
                    "concrete raw concluded expression disagrees with review",
                )
            if declared not in ("NOASSERTION", "NONE"):
                _audit_parse_spdx(declared, approved)
                _require(
                    declared == reviewed_expression,
                    "concrete raw declared expression disagrees with review",
                )
            normalized = copy.deepcopy(package)
            normalized.update(
                {
                    "name": reviewed_record["dependency"]["name"],
                    "versionInfo": reviewed_record["dependency"]["version_ref"],
                    "downloadLocation": reviewed_record["dependency"]["source_url"],
                    "copyrightText": reviewed_record["dependency"]["copyright"],
                    "licenseConcluded": reviewed_expression,
                    "licenseDeclared": reviewed_expression,
                }
            )
            existing_attribution = normalized.get("attributionTexts", [])
            _require(
                isinstance(existing_attribution, list)
                and all(
                    isinstance(item, str) and item
                    for item in existing_attribution
                ),
                "raw package attribution texts are invalid",
            )
            normalized["attributionTexts"] = list(
                dict.fromkeys([*existing_attribution, attribution])
            )
            normalized_packages[key] = normalized
            normalized_refs.append(
                {
                    "profile_id": profile_id,
                    "role": role,
                    "spdx_id": spdx_id,
                }
            )
        _require(
            len(normalized_refs)
            == len(
                {
                    (ref["profile_id"], ref["role"], ref["spdx_id"])
                    for ref in normalized_refs
                }
            ),
            "license resolution duplicates a raw package reference",
        )
        if disposition == "not-shipped":
            zero_input_proof = _audit_v2_zero_input_proof(
                zero_input_proof,
                package_refs=normalized_refs,
                reviewed_package_id=reviewed_id,
                observed_inputs=observed_by_id,
                policy_inputs=policy_inputs,
            )
        for input_ref in input_refs:
            _require(
                input_ref in policy_inputs,
                "license resolution names an unknown input",
            )
            _require(
                policy_inputs[input_ref]["kind"]
                not in _AUDIT_POLICY_V2_SUPPLEMENTAL_INPUT_KINDS,
                "raw package resolution consumes a supplemental-only input",
            )
            _require(
                policy_inputs[input_ref]["reviewed_package_id"] == reviewed_id,
                "license resolution consumes an input reviewed for another package",
            )
            _require(
                (
                    policy_inputs[input_ref]["profile_id"],
                    policy_inputs[input_ref]["role"],
                )
                in {
                    (ref["profile_id"], ref["role"])
                    for ref in normalized_refs
                },
                "license resolution input is outside its raw package identities",
            )
            input_consumers[input_ref] += 1
        _require(
            len(input_refs) == len(set(input_refs)),
            "license resolution duplicates an input reference",
        )
        if disposition == "allow":
            _require(
                {
                    (
                        policy_inputs[input_ref]["profile_id"],
                        policy_inputs[input_ref]["role"],
                    )
                    for input_ref in input_refs
                }
                == {
                    (ref["profile_id"], ref["role"])
                    for ref in normalized_refs
                },
                "allowed license resolution lacks exact profile/role input coverage",
            )
        validated = {
            "id": identifier,
            "reviewed_package_id": reviewed_id,
            "package_refs": sorted(
                normalized_refs,
                key=lambda item: (
                    item["profile_id"],
                    item["role"],
                    item["spdx_id"],
                ),
            ),
            "input_refs": sorted(input_refs),
            "resolved_input_expression": expression,
            "disposition": disposition,
            "attribution": attribution,
        }
        if disposition == "not-shipped":
            validated["zero_input_proof"] = zero_input_proof
        elif disposition == "allow-aggregate":
            validated["aggregate_proof"] = copy.deepcopy(aggregate_proof)
        validated_resolutions.append(validated)
        resolution_by_reviewed[reviewed_id] = validated
        resolution_notice_identifiers[identifier] = resolved_identifiers

    for resolution in validated_resolutions:
        if resolution["disposition"] != "allow-aggregate":
            continue
        resolution["aggregate_proof"] = _audit_v2_aggregate_proof(
            resolution["aggregate_proof"],
            package_refs=resolution["package_refs"],
            reviewed_package_id=resolution["reviewed_package_id"],
            documents=documents,
            resolution_by_reviewed=resolution_by_reviewed,
            policy_inputs=policy_inputs,
        )

    _require(
        set(reviewed_consumers) == set(reviewed)
        and all(count == 1 for count in reviewed_consumers.values()),
        "each reviewed raw package must have exactly one resolution",
    )

    supplemental_raw = policy["supplemental_packages"]
    _require(
        isinstance(supplemental_raw, list) and bool(supplemental_raw),
        "supplemental_packages must be nonempty",
    )
    supplemental_ids: set[str] = set()
    validated_supplementals: list[dict[str, Any]] = []
    for raw_supplemental in supplemental_raw:
        supplemental = _exact_keys(
            raw_supplemental,
            {
                "id",
                "dependency",
                "source",
                "source_spdx_expression",
                "selected_spdx_expression",
                "input_refs",
                "relationship",
                "license_texts",
                "notice",
                "disposition",
            },
            "supplemental package",
        )
        identifier = _audit_v2_nonempty(
            supplemental["id"],
            "supplemental package id",
        )
        _require(
            identifier not in supplemental_ids and identifier not in reviewed,
            "supplemental package id is duplicated",
        )
        supplemental_ids.add(identifier)
        _require(
            supplemental["disposition"] == "allow",
            "supplemental package is not approved",
        )
        dependency = _audit_v2_dependency(
            supplemental["dependency"],
            identifier,
        )
        source = _audit_v2_source(
            root,
            supplemental["source"],
            identifier,
            allow_tree=True,
        )
        _require(
            source["ref"] == dependency["version_ref"]
            and source["url"] == dependency["source_url"],
            "%s supplemental dependency/source metadata disagrees" % identifier,
        )
        source_expression = supplemental["source_spdx_expression"]
        selected_expression = supplemental["selected_spdx_expression"]
        source_expression_identifiers, selected_expression_identifiers = (
            _audit_spdx_selected_choice(
                source_expression,
                selected_expression,
                approved,
            )
        )
        relationship = _exact_keys(
            supplemental["relationship"],
            {
                "relationship_type",
                "related_reviewed_package_id",
            },
            "%s supplemental relationship" % identifier,
        )
        _audit_v2_nonempty(
            relationship["relationship_type"],
            "%s supplemental relationship type" % identifier,
        )
        _require(
            relationship["relationship_type"] == "DEPENDS_ON",
            "%s supplemental relationship must be DEPENDS_ON" % identifier,
        )
        related = relationship["related_reviewed_package_id"]
        _require(
            isinstance(related, str)
            and related in reviewed
            and related in resolution_by_reviewed,
            "%s supplemental relationship names an unknown reviewed package"
            % identifier,
        )
        input_refs = supplemental["input_refs"]
        _require(
            isinstance(input_refs, list)
            and bool(input_refs)
            and all(
                isinstance(input_ref, str) and input_ref for input_ref in input_refs
            )
            and len(input_refs) == len(set(input_refs)),
            "%s supplemental input references are invalid" % identifier,
        )
        supplemental_identities: set[tuple[str, str]] = set()
        for input_ref in input_refs:
            policy_input = policy_inputs.get(input_ref)
            _require(
                policy_input is not None
                and policy_input["kind"] in _AUDIT_POLICY_V2_SUPPLEMENTAL_INPUT_KINDS,
                "%s supplemental package names a non-supplemental input" % identifier,
            )
            _require(
                policy_input["reviewed_package_id"] == identifier,
                "%s supplemental package consumes an input reviewed elsewhere"
                % identifier,
            )
            source_tree = source.get("tree_path")
            _require(
                isinstance(source_tree, str) and bool(source_tree),
                "%s supplemental input lacks an immutable reviewed source tree"
                % identifier,
            )
            if policy_input["kind"] == "generated-supplemental-archive":
                tree_prefix = _safe_relative_path(
                    source_tree,
                    "%s supplemental source tree" % identifier,
                ).rstrip("/") + "/"
                _require(
                    all(
                        item["path"].startswith(tree_prefix)
                        for item in generated_bindings[input_ref]["sources"]
                    ),
                    "%s generated source escapes its immutable reviewed tree"
                    % identifier,
                )
            else:
                _require(
                    policy_input["path"] == source_tree,
                    "%s frozen input differs from its immutable reviewed tree"
                    % identifier,
                )
            input_consumers[input_ref] += 1
            supplemental_identities.add(
                (policy_input["profile_id"], policy_input["role"])
            )
        owner_resolution = resolution_by_reviewed[related]
        owner_identities = {
            (ref["profile_id"], ref["role"]) for ref in owner_resolution["package_refs"]
        }
        owner_generated_identities = {
            (
                policy_inputs[input_ref]["profile_id"],
                policy_inputs[input_ref]["role"],
            )
            for input_ref in owner_resolution["input_refs"]
            if policy_inputs[input_ref]["kind"] == "generated-component-archive"
        }
        _require(
            supplemental_identities <= owner_identities
            and supplemental_identities <= owner_generated_identities,
            "%s supplemental relationship does not identify its owning package"
            % identifier,
        )
        validated_supplementals.append(
            {
                "id": identifier,
                "dependency": dependency,
                "source": source,
                "source_spdx_expression": source_expression,
                "selected_spdx_expression": selected_expression,
                "input_refs": sorted(input_refs),
                "relationship": copy.deepcopy(relationship),
                "license_texts": _audit_v2_review_files(
                    root,
                    supplemental["license_texts"],
                    identifier,
                    expected_identifiers=source_expression_identifiers,
                    approved_license_refs=approved,
                ),
                "selected_license_identifiers": selected_expression_identifiers,
                "notice": _audit_v2_notice(
                    root,
                    supplemental["notice"],
                    identifier,
                ),
                "disposition": "allow",
            }
        )

    _require(
        set(raw_consumers) == set(raw_packages)
        and all(count == 1 for count in raw_consumers.values()),
        "every raw package must be consumed by exactly one resolution",
    )
    _require(
        set(input_consumers) == set(policy_inputs)
        and all(count == 1 for count in input_consumers.values()),
        "every redistributed input must be consumed exactly once",
    )

    reviewed_documents: dict[str, dict[str, Any]] = {}
    for identity, document in sorted(documents.items()):
        profile_id, role = identity
        reviewed_documents["%s/%s" % identity] = {
            "profile_id": profile_id,
            "role": role,
            "packages": sorted(
                (
                    normalized_packages[(profile_id, role, package["SPDXID"])]
                    for package in document["packages"]
                ),
                key=lambda package: package["SPDXID"],
            ),
            "relationships": sorted(
                copy.deepcopy(document["relationships"]),
                key=lambda relationship: _audit_v2_canonical(
                    relationship,
                    "reviewed SPDX relationship",
                ),
            ),
        }

    notice_records: list[dict[str, Any]] = []
    for resolution in sorted(validated_resolutions, key=lambda item: item["id"]):
        if resolution["disposition"] not in ("allow", "allow-aggregate"):
            continue
        record = reviewed[resolution["reviewed_package_id"]]
        selected_identifiers = resolution_notice_identifiers[resolution["id"]]
        notice_records.append(
            {
                "id": record["id"],
                "dependency": copy.deepcopy(record["dependency"]),
                "source": copy.deepcopy(record["source"]),
                "spdx_expression": resolution["resolved_input_expression"],
                "license_texts": [
                    copy.deepcopy(item)
                    for item in record["license_texts"]
                    if item["spdx_id"] in selected_identifiers
                ],
                "notice": copy.deepcopy(record["notice"]),
                "input_refs": list(resolution["input_refs"]),
            }
        )
    for supplemental in sorted(
        validated_supplementals,
        key=lambda item: item["id"],
    ):
        notice_records.append(
            {
                "id": supplemental["id"],
                "dependency": copy.deepcopy(supplemental["dependency"]),
                "source": copy.deepcopy(supplemental["source"]),
                "spdx_expression": supplemental["selected_spdx_expression"],
                "license_texts": [
                    copy.deepcopy(item)
                    for item in supplemental["license_texts"]
                    if item["spdx_id"]
                    in supplemental["selected_license_identifiers"]
                ],
                "notice": copy.deepcopy(supplemental["notice"]),
                "input_refs": list(supplemental["input_refs"]),
            }
        )
    notice_records.sort(key=lambda item: item["id"])

    semantic_sha256 = {
        key: _sha256_bytes(
            _audit_v2_canonical(policy[key], "license policy %s" % key).encode(
                "utf-8"
            )
        )
        for key in (
            "raw_documents",
            "review_files",
            "shipment_review",
            "reviewed_packages",
            "resolved_inputs",
            "resolutions",
            "supplemental_packages",
            "toolchains",
        )
    }
    semantic_sha256["resolutions"] = _sha256_bytes(
        _audit_v2_canonical(
            sorted(validated_resolutions, key=lambda item: item["id"]),
            "validated license resolutions",
        ).encode("utf-8")
    )
    semantic_sha256["generated_bindings"] = _sha256_bytes(
        _audit_v2_canonical(
            dict(sorted(generated_bindings.items())),
            "observed generated input bindings",
        ).encode("utf-8")
    )
    semantic_sha256["shipment_classifications"] = _sha256_bytes(
        _audit_v2_canonical(
            shipment_classifications,
            "validated shipment classifications",
        ).encode("utf-8")
    )
    semantic_sha256["frozen_manifest_evidence"] = _sha256_bytes(
        _audit_v2_canonical(
            validated_manifest_evidence,
            "validated literal manifest evidence",
        ).encode("utf-8")
    )
    public_supplementals = []
    for supplemental in sorted(validated_supplementals, key=lambda item: item["id"]):
        record = copy.deepcopy(supplemental)
        record.pop("selected_license_identifiers")
        public_supplementals.append(record)
    return {
        "schema_version": 2,
        "reviewed_documents": reviewed_documents,
        "observed_input_sha256": observed_hashes,
        "generated_bindings": dict(sorted(generated_bindings.items())),
        "review_files": validated_review_files,
        "shipment_review": validated_shipment_review,
        "shipment_classifications": shipment_classifications,
        "manifest_evidence": validated_manifest_evidence,
        "notice_records": notice_records,
        "resolutions": sorted(validated_resolutions, key=lambda item: item["id"]),
        "supplemental_packages": public_supplementals,
        "toolchains": dict(sorted(validated_toolchains.items())),
        "semantic_sha256": semantic_sha256,
    }


def _audit_load_policy(
    repo_root: Path,
    lock: dict[str, Any],
) -> dict[str, Any]:
    inputs = lock["inputs"]
    policy_path = _audit_repo_file(
        repo_root,
        inputs["license_policy_path"],
        "release license policy",
    )
    policy = _read_json(policy_path, "release license policy")
    _require(isinstance(policy, dict), "release license policy must be an object")
    _require(
        type(policy.get("schema_version")) is int
        and policy.get("schema_version") == 2,
        "release license policy schema_version must be 2",
    )
    _exact_keys(policy, _AUDIT_POLICY_V2_KEYS, "release license policy")
    return policy


def _audit_ar_member_payloads(path: Path) -> dict[str, list[bytes]]:
    """Return ordered member payloads from a validated System V/GNU/BSD ar."""

    try:
        value = path.read_bytes()
    except OSError as exc:
        raise ReleaseError("cannot read linked archive: %s" % path) from exc
    _require(value.startswith(b"!<arch>\n"), "linked archive is not a valid ar file")
    position = 8
    long_names = b""
    members: dict[str, list[bytes]] = {}
    while position < len(value):
        _require(position + 60 <= len(value), "linked archive header is truncated")
        header = value[position : position + 60]
        position += 60
        _require(header[58:60] == b"`\n", "linked archive header is malformed")
        try:
            size = int(header[48:58].decode("ascii").strip())
        except (UnicodeDecodeError, ValueError) as exc:
            raise ReleaseError("linked archive member size is malformed") from exc
        _require(
            size >= 0 and position + size <= len(value),
            "linked archive member is truncated",
        )
        payload = value[position : position + size]
        position += size
        if size % 2:
            _require(
                value[position : position + 1] == b"\n",
                "linked archive padding is malformed",
            )
            position += 1

        try:
            raw_name = header[:16].decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise ReleaseError("linked archive member name is not ASCII") from exc
        if raw_name == "//":
            long_names = payload
            continue
        if raw_name in ("/", "/SYM64/"):
            continue
        if raw_name.startswith("#1/"):
            try:
                name_length = int(raw_name[3:])
                name = payload[:name_length].decode("utf-8")
            except (ValueError, UnicodeDecodeError) as exc:
                raise ReleaseError("BSD ar member name is malformed") from exc
            _require(
                0 < name_length <= len(payload),
                "BSD ar member name length is invalid",
            )
            payload = payload[name_length:]
        elif raw_name.startswith("/") and raw_name[1:].isdigit():
            offset = int(raw_name[1:])
            _require(offset < len(long_names), "GNU ar long-name offset is invalid")
            terminators = [
                index
                for index in (
                    long_names.find(b"/\n", offset),
                    long_names.find(b"\0", offset),
                )
                if index >= 0
            ]
            end = min(terminators) if terminators else len(long_names)
            try:
                name = long_names[offset:end].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ReleaseError("GNU ar long member name is invalid") from exc
        else:
            name = raw_name[:-1] if raw_name.endswith("/") else raw_name
        _require(bool(name), "linked archive member name is empty")
        members.setdefault(name, []).append(payload)
    _require(position == len(value), "linked archive has trailing bytes")
    _require(members, "linked archive contains no object members")
    return members


def _audit_ar_members(path: Path) -> Counter[str]:
    """Return counted member names from System V/GNU/BSD ar."""

    return Counter(
        {
            name: len(payloads)
            for name, payloads in _audit_ar_member_payloads(path).items()
        }
    )


def _audit_map_archives(
    map_path: Path,
    *,
    repo_root: Path,
    build_root: Path,
    admitted_roots: tuple[Path, ...] = (),
) -> list[tuple[Path, str]]:
    try:
        lines = map_path.read_text(encoding="utf-8", errors="strict").splitlines()
    except OSError as exc:
        raise ReleaseError("linked map file is missing: %s" % map_path) from exc
    result: list[tuple[Path, str]] = []
    members_by_archive: dict[Path, Counter[str]] = {}
    linked_occurrences: Counter[tuple[Path, str]] = Counter()
    for line in lines:
        match = re.fullmatch(r"(\S+\.a)\(([^()]+)\)", line)
        if match is None:
            continue
        archive = _audit_path_in_roots(
            match.group(1),
            relative_to=map_path.parent,
            roots=(repo_root, build_root, *admitted_roots),
            label="linked map archive",
        )
        _require(archive.is_file(), "linked map archive is missing")
        member = match.group(2)
        archive_key = archive.resolve()
        if archive_key not in members_by_archive:
            members_by_archive[archive_key] = _audit_ar_members(archive)
        occurrence = (archive_key, member)
        linked_occurrences[occurrence] += 1
        _require(
            linked_occurrences[occurrence] <= members_by_archive[archive_key][member],
            "linked map overstates archive member occurrences",
        )
        result.append((archive, member))
    _require(result, "linked map contains no archive-member inventory")
    return result


def _audit_regular_compile_file(path: Path, label: str) -> Path:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise ReleaseError("%s is missing" % label) from exc
    _require(
        stat_module.S_ISREG(mode) and not stat_module.S_ISLNK(mode),
        "%s is not a regular symlink-free file" % label,
    )
    return path


def _audit_expected_compile_file(
    path: Path,
    *,
    root: Path,
    label: str,
) -> Path:
    """Validate one contract-pinned lexical path before canonical equality."""

    _audit_no_symlink_components(root, path, label)
    _audit_regular_compile_file(path, label)
    return path.resolve()


def _audit_command_operand_path(
    raw_path: str,
    *,
    relative_to: Path,
    roots: tuple[Path, ...],
    label: str,
) -> Path:
    """Resolve a compiler operand while permitting a controlled ``..``."""

    _require(
        isinstance(raw_path, str)
        and bool(raw_path)
        and "\x00" not in raw_path,
        "%s is invalid" % label,
    )
    value = Path(raw_path)
    candidate = value if value.is_absolute() else relative_to / value
    # Path.absolute() preserves lexical ``..`` components.  Collapsing them
    # before checking symlinks would model a different traversal from the
    # compiler (for example, ``link/../file`` when ``link`` is a symlink).
    lexical = candidate.absolute()
    for root in roots:
        lexical_root = root.absolute()
        try:
            lexical.relative_to(lexical_root)
        except ValueError:
            continue
        _audit_no_symlink_components(lexical_root, lexical, label)
        try:
            return lexical.resolve(strict=True)
        except OSError as exc:
            raise ReleaseError("%s is missing" % label) from exc
    raise ReleaseError("%s is outside the repository/build roots" % label)


def _audit_exact_compile_source_sets(
    *,
    repo_root: Path,
    build_root: Path,
    target: str,
    compiled_sources: set[Path],
) -> tuple[set[Path], set[Path]]:
    pyble_root = repo_root / "firmware" / "user_c_modules" / "pyble"
    retained_root = (
        build_root
        / ".sources"
        / target
        / "micropython"
        / "lib"
        / "berkeley-db-1.xx"
    )
    def allowlisted(
        root: Path,
        names: tuple[str, ...],
        *,
        approved_root: Path,
        label: str,
    ) -> set[Path]:
        result: set[Path] = set()
        for name in names:
            candidate = root / name
            resolved = candidate.resolve()
            if resolved in compiled_sources:
                resolved = _audit_expected_compile_file(
                    candidate,
                    root=approved_root,
                    label=label,
                )
            result.add(resolved)
        return result

    pyble_sources = allowlisted(
        pyble_root,
        _AUDIT_PYBLE_C_SOURCES,
        approved_root=repo_root,
        label="pinned PyBLE compile source",
    )
    berkeley_sources = allowlisted(
        retained_root,
        _AUDIT_BERKELEY_DB_C_SOURCES,
        approved_root=build_root,
        label="pinned Berkeley DB compile source",
    )
    return pyble_sources, berkeley_sources


def _audit_compile_sources(
    path: Path,
    *,
    description: dict[str, Any],
    repo_root: Path,
    build_root: Path,
    target: str,
    role: str,
    role_build: Path,
) -> dict[str, Any]:
    _require(
        role in LICENSE_AUDIT_ROLES
        and path.parent.resolve() == role_build.resolve(),
        "compile inventory role root is invalid",
    )
    commands = _read_json(path, "compile_commands.json")
    _require(
        isinstance(commands, list) and commands,
        "compile_commands.json contains no commands",
    )
    sources: set[Path] = set()
    outputs: dict[Path, Path] = {}
    source_lexical_by_output: dict[Path, Path] = {}
    for index, command in enumerate(commands):
        label = "compile command %d" % index
        _require(isinstance(command, dict), "compile command is not an object")
        directory_raw = command.get("directory")
        source_raw = command.get("file")
        output_raw = command.get("output")
        _require(
            isinstance(directory_raw, str)
            and isinstance(source_raw, str)
            and isinstance(output_raw, str),
            "compile command lacks directory/file/output",
        )
        directory = _audit_path_in_roots(
            directory_raw,
            relative_to=path.parent,
            roots=(repo_root, build_root),
            label="compile working directory",
        )
        _require(directory.is_dir(), "%s working directory is missing" % label)
        source_lexical = _audit_path_in_roots(
            source_raw,
            relative_to=directory,
            roots=(repo_root, build_root),
            label="compiled source",
        )
        source = source_lexical.resolve()
        _audit_regular_compile_file(source, "%s source" % label)
        output = _audit_path_in_roots(
            output_raw,
            relative_to=role_build,
            roots=(build_root,),
            label="compile output",
        ).resolve()
        _audit_regular_compile_file(output, "%s output" % label)
        _require(
            output.suffix in (".o", ".obj"),
            "%s output is not an object file" % label,
        )

        tokens = _audit_v2_command_tokens(command, label)
        _require(
            tokens.count("-c") == 1
            and tokens.index("-c") + 1 < len(tokens)
            and tokens.count("-o") == 1
            and tokens.index("-o") + 1 < len(tokens)
            and all(token == "-c" or not token.startswith("-c") for token in tokens)
            and all(token == "-o" or not token.startswith("-o") for token in tokens),
            "%s source/output operands are ambiguous" % label,
        )
        command_source = _audit_command_operand_path(
            tokens[tokens.index("-c") + 1],
            relative_to=directory,
            roots=(repo_root, build_root),
            label="%s -c source" % label,
        )
        command_output = _audit_command_operand_path(
            tokens[tokens.index("-o") + 1],
            relative_to=directory,
            roots=(build_root,),
            label="%s -o output" % label,
        )
        _require(
            command_source == source and command_output == output,
            "%s JSON and compiler source/output paths disagree" % label,
        )
        _require(output not in outputs, "compile output resolves ambiguously")
        outputs[output] = source
        source_lexical_by_output[output] = Path(
            os.path.abspath(source_lexical)
        )
        sources.add(source)

    component_info = description.get("build_component_info")
    _require(
        isinstance(component_info, dict) and component_info,
        "project_description lacks build_component_info",
    )
    described_sources: set[Path] = set()
    described_by_component: dict[str, set[Path]] = {}
    described_source_roots: set[Path] = set()
    described_roots_by_component: dict[str, set[Path]] = {}
    config_only_roots: set[Path] = set()
    metadata_by_component: dict[str, set[Path]] = {}
    allowed_headers: set[Path] = set()
    if role == "application" and "main" in component_info:
        allowed_headers = {
            _audit_expected_compile_file(
                role_build / "genhdr" / name,
                root=role_build,
                label="pinned generated main header",
            )
            for name in _AUDIT_MAIN_METADATA_HEADERS
        }
    for component_name, component in component_info.items():
        _require(
            isinstance(component_name, str)
            and bool(component_name)
            and isinstance(component, dict),
            "component info is not an object",
        )
        component_directory_raw = component.get("dir")
        _require(
            isinstance(component_directory_raw, str)
            and bool(component_directory_raw),
            "component source root is missing",
        )
        component_directory = _audit_path_in_roots(
            component_directory_raw,
            relative_to=path.parent,
            roots=(repo_root, build_root),
            label="component source root",
        )
        _require(
            component_directory.is_dir(),
            "component source root is missing",
        )
        component_directory = component_directory.resolve()
        if component.get("type") == "CONFIG_ONLY":
            config_only_roots.add(component_directory)
        component_sources = component.get("sources")
        _require(
            isinstance(component_sources, list),
            "component sources must be an array",
        )
        component_files: set[Path] = set()
        component_roots: set[Path] = set()
        for source_raw in component_sources:
            _require(isinstance(source_raw, str), "component source path is invalid")
            source = _audit_path_in_roots(
                source_raw,
                relative_to=path.parent,
                roots=(repo_root, build_root),
                label="described component source",
            )
            source = source.resolve()
            if source.is_file():
                _audit_regular_compile_file(source, "described component source")
                described_sources.add(source)
                component_files.add(source)
            elif source.is_dir():
                _require(
                    source.is_relative_to(component_directory),
                    "described source directory escapes its component root",
                )
                described_source_roots.add(source)
                component_roots.add(source)
            else:
                raise ReleaseError("described component source is missing")
        described_by_component[component_name] = component_files
        described_roots_by_component[component_name] = component_roots
        metadata = component_files - sources
        _require(
            all(
                role == "application"
                and component_name == "main"
                and source in allowed_headers
                for source in metadata
            ),
            "project description contains an uncompiled source outside the "
            "exact generated main-header set",
        )
        metadata_by_component[component_name] = metadata

    if role == "application" and "main" in component_info:
        _require(
            metadata_by_component["main"] == allowed_headers,
            "application main metadata is not the exact generated-header set",
        )

    pyble_sources: set[Path] = set()
    berkeley_sources: set[Path] = set()
    if role == "application" and "main" in component_info:
        pyble_sources, berkeley_sources = _audit_exact_compile_source_sets(
            repo_root=repo_root,
            build_root=build_root,
            target=target,
            compiled_sources=sources,
        )
    idf_target = description.get("target")
    _require(
        isinstance(idf_target, str) and bool(idf_target),
        "project description target is invalid",
    )
    project_anchor: Path | None = None
    if "main" in component_info:
        project_anchor_path = role_build / ("project_elf_src_%s.c" % idf_target)
        project_anchor = _audit_expected_compile_file(
            project_anchor_path,
            root=role_build,
            label="pinned project ELF source anchor",
        )
        _require(
            project_anchor_path.stat().st_size == 0 and project_anchor in sources,
            "generated project ELF source anchor is not exactly zero bytes",
        )

    _require(
        all(
            source in described_sources
            or any(source.is_relative_to(root) for root in described_source_roots)
            or any(source.is_relative_to(root) for root in config_only_roots)
            or (
                role == "application"
                and "main" in component_info
                and (source in pyble_sources or source in berkeley_sources)
            )
            or source == project_anchor
            for source in sources
        ),
        "project description and compile source inventories disagree",
    )
    return {
        "sources": sources,
        "outputs": outputs,
        "source_lexical_by_output": source_lexical_by_output,
        "described_sources": described_sources,
        "described_by_component": described_by_component,
        "described_roots_by_component": described_roots_by_component,
        "metadata_by_component": metadata_by_component,
        "pyble_sources": pyble_sources,
        "berkeley_sources": berkeley_sources,
        "project_anchor": project_anchor,
    }


def _audit_map_direct_outputs(
    map_path: Path,
    *,
    role_build: Path,
    compile_outputs: dict[Path, Path],
) -> set[Path]:
    """Return the exact direct object ``LOAD`` set from one linker map."""

    try:
        lines = map_path.read_text(
            encoding="utf-8",
            errors="strict",
        ).splitlines()
    except (OSError, UnicodeError) as exc:
        raise ReleaseError("linked map file is missing or invalid") from exc
    direct_outputs: set[Path] = set()
    for line in lines:
        match = re.fullmatch(r"LOAD (\S+\.(?:o|obj))", line)
        if match is None:
            _require(
                re.fullmatch(r"\s*LOAD\s+.*\.(?:o|obj)(?:\s.*)?", line)
                is None,
                "linked map direct-object LOAD is not exact",
            )
            continue
        relative = _safe_relative_path(
            match.group(1),
            "linked map direct object",
        )
        output = _audit_path_in_roots(
            relative,
            relative_to=role_build,
            roots=(role_build,),
            label="linked map direct object",
        ).resolve()
        _audit_regular_compile_file(output, "linked map direct object")
        _require(
            output in compile_outputs and output not in direct_outputs,
            "linked map direct object is uncompiled or duplicated",
        )
        direct_outputs.add(output)
    return direct_outputs


def _audit_link_command_direct_outputs(
    *,
    role_build: Path,
    description: dict[str, Any],
    compile_outputs: dict[Path, Path],
) -> tuple[str, Path, set[Path]]:
    """Safely parse one CMake link command and return its direct objects."""

    app_elf_raw = description.get("app_elf")
    _require(
        isinstance(app_elf_raw, str)
        and bool(app_elf_raw)
        and "\x00" not in app_elf_raw
        and "\\" not in app_elf_raw,
        "project description app_elf is invalid",
    )
    app_elf_path = Path(app_elf_raw)
    app_elf = app_elf_path.name
    _require(
        bool(app_elf)
        and app_elf.endswith(".elf")
        and (
            (
                app_elf_path.is_absolute()
                and app_elf_path.parent.resolve() == role_build.resolve()
            )
            or (
                not app_elf_path.is_absolute()
                and PurePosixPath(app_elf_raw).parts == (app_elf,)
            )
        ),
        "project description app_elf is invalid",
    )
    link_path = (
        role_build / "CMakeFiles" / ("%s.dir" % app_elf) / "link.txt"
    )
    _audit_no_symlink_components(
        role_build,
        link_path,
        "linker command",
    )
    _audit_regular_compile_file(link_path, "linker command")
    try:
        text = link_path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise ReleaseError("linker command is missing or invalid") from exc
    stripped = text.strip()
    _require(
        bool(stripped)
        and "\x00" not in stripped
        and "\n" not in stripped
        and "\r" not in stripped,
        "linker command is empty or contains multiple commands",
    )
    try:
        tokens = shlex.split(stripped, posix=True)
    except ValueError as exc:
        raise ReleaseError("linker command is malformed") from exc
    _require(
        bool(tokens)
        and all(
            token
            and not _audit_command_token_uses_response_file(token)
            and not any(character in token for character in ";&|<>`$#")
            for token in tokens
        ),
        "linker command uses a response file or shell operator",
    )
    direct_outputs: set[Path] = set()
    for token in tokens:
        if not token.endswith((".o", ".obj")):
            continue
        output = _audit_command_operand_path(
            token,
            relative_to=role_build,
            roots=(role_build,),
            label="linker command direct object",
        )
        _audit_regular_compile_file(output, "linker command direct object")
        _require(
            output in compile_outputs and output not in direct_outputs,
            "linker command direct object is uncompiled or duplicated",
        )
        direct_outputs.add(output)
    return app_elf, link_path, direct_outputs


def _audit_component_output_inventory(
    *,
    component: dict[str, Any],
    role_build: Path,
    build_root: Path,
    compile_outputs: dict[Path, Path],
    label: str,
) -> tuple[Path, Path, dict[Path, Path]]:
    """Resolve an ordinary ESP-IDF archive from its literal output topology."""

    archive_raw = component.get("file")
    component_lib = component.get("lib")
    _require(
        isinstance(archive_raw, str)
        and bool(archive_raw)
        and isinstance(component_lib, str)
        and bool(component_lib)
        and re.fullmatch(r"[A-Za-z0-9_.+-]+", component_lib) is not None
        and component_lib not in (".", ".."),
        "%s component archive/lib topology is invalid" % label,
    )
    archive = _audit_path_in_roots(
        archive_raw,
        relative_to=role_build,
        roots=(build_root,),
        label="%s archive" % label,
    )
    _audit_regular_compile_file(archive, "%s archive" % label)
    object_directory = (
        archive.parent / "CMakeFiles" / ("%s.dir" % component_lib)
    )
    _audit_no_symlink_components(
        build_root,
        object_directory,
        "%s object directory" % label,
    )
    _require(
        object_directory.is_dir(),
        "%s object directory is missing" % label,
    )
    object_directory = object_directory.resolve()
    selected_outputs = {
        output: source
        for output, source in compile_outputs.items()
        if output.is_relative_to(object_directory)
    }
    _require(
        bool(selected_outputs),
        "%s object inventory is empty" % label,
    )
    return archive, object_directory, selected_outputs


def _audit_direct_object_records(
    *,
    direct_outputs: set[Path],
    compile_inventory: dict[str, Any],
    app_elf: str,
    role: str,
    role_build: Path,
    repo_root: Path,
    build_root: Path,
) -> list[dict[str, dict[str, str]]]:
    """Validate the three admitted direct-object topologies."""

    records: list[dict[str, dict[str, str]]] = []
    saw_project_anchor = False
    for output in sorted(direct_outputs):
        source = compile_inventory["outputs"][output]
        lexical_source = compile_inventory["source_lexical_by_output"][output]
        if source == compile_inventory["project_anchor"]:
            expected = (
                role_build
                / "CMakeFiles"
                / ("%s.dir" % app_elf)
                / ("%s.obj" % source.name)
            )
            saw_project_anchor = True
        elif (
            role == "application"
            and source in compile_inventory["pyble_sources"]
        ):
            expected = (
                role_build
                / "CMakeFiles"
                / "micropython.elf.dir"
                / ("%s.obj" % lexical_source.as_posix().lstrip("/"))
            )
        elif (
            role == "application"
            and source in compile_inventory["berkeley_sources"]
        ):
            expected = (
                role_build
                / "esp-idf"
                / "main"
                / "CMakeFiles"
                / "micropy_extmod_btree.dir"
                / ("%s.obj" % lexical_source.as_posix().lstrip("/"))
            )
        else:
            raise ReleaseError(
                "linked direct object has an unadmitted compile source"
            )
        expected_resolved = _audit_expected_compile_file(
            expected,
            root=role_build,
            label="pinned direct object output",
        )
        _require(
            output == expected_resolved,
            "linked direct object has an unadmitted output topology",
        )
        records.append(
            {
                "output": _audit_v2_source_record(
                    output,
                    repo_root=repo_root,
                    build_root=build_root,
                ),
                "source": _audit_v2_source_record(
                    source,
                    repo_root=repo_root,
                    build_root=build_root,
                ),
            }
        )
    _require(
        saw_project_anchor,
        "generated main binding lacks its direct project anchor",
    )
    return sorted(records, key=lambda item: item["output"]["path"])


def _audit_linked_frozen_object(
    *,
    repo_root: Path,
    build_root: Path,
    target: str,
    frozen_path: Path,
) -> dict[str, str]:
    """Replay the frozen-C compile and bind its bytes to the linked member."""

    root = Path(repo_root).absolute()
    builds = Path(build_root).absolute()
    target_build = builds / target
    frozen = Path(frozen_path).absolute()
    _require(
        frozen.resolve() == (target_build / "frozen_content.c").resolve(),
        "%s frozen C path does not belong to its target build" % target,
    )
    compile_path = target_build / "compile_commands.json"
    description_path = target_build / "project_description.json"
    map_path = target_build / "micropython.map"
    commands = _read_json(
        compile_path,
        "%s application compile commands" % target,
    )
    _require(
        isinstance(commands, list) and bool(commands),
        "%s application compile commands are empty" % target,
    )
    matches: list[tuple[dict[str, Any], Path, list[str]]] = []
    for command in commands:
        _require(
            isinstance(command, dict),
            "%s compile command is invalid" % target,
        )
        directory_raw = command.get("directory")
        source_raw = command.get("file")
        if not isinstance(directory_raw, str) or not isinstance(source_raw, str):
            continue
        directory = _audit_path_in_roots(
            directory_raw,
            relative_to=target_build,
            roots=(root, builds),
            label="%s frozen compile working directory" % target,
        )
        source = _audit_path_in_roots(
            source_raw,
            relative_to=directory,
            roots=(root, builds),
            label="%s frozen compile source" % target,
        )
        if source.resolve() != frozen.resolve():
            continue
        matches.append(
            (
                command,
                directory,
                _audit_v2_command_tokens(
                    command,
                    "%s frozen compile command" % target,
                ),
            )
        )
    _require(
        len(matches) == 1,
        "%s frozen_content.c must have one exact compile command" % target,
    )
    command, directory, tokens = matches[0]
    _require(
        tokens.count("-c") == 1
        and tokens.index("-c") + 1 < len(tokens)
        and tokens.count("-o") == 1
        and tokens.index("-o") + 1 < len(tokens)
        and all(
            token == "-o" or not token.startswith("-o")
            for token in tokens
        ),
        "%s frozen compile arguments are ambiguous" % target,
    )
    source_token = tokens[tokens.index("-c") + 1]
    source_from_command = _audit_path_in_roots(
        source_token,
        relative_to=directory,
        roots=(root, builds),
        label="%s frozen compile source argument" % target,
    )
    _require(
        source_from_command.resolve() == frozen.resolve(),
        "%s frozen compile source argument changed" % target,
    )
    output_index = tokens.index("-o") + 1
    output_token = tokens[output_index]
    _require(
        bool(output_token) and not output_token.startswith("-"),
        "%s frozen compile output argument is invalid" % target,
    )
    member_name = Path(output_token).name
    _require(
        bool(member_name)
        and "/" not in member_name
        and "\\" not in member_name,
        "%s frozen object member name is invalid" % target,
    )

    executable = _audit_v2_command_executable(
        command,
        "%s frozen compile command" % target,
    )
    executable = _audit_path_in_roots(
        executable,
        relative_to=directory,
        roots=(root, builds, executable.parent),
        label="%s frozen compiler" % target,
    )
    _audit_v2_regular_path(
        os.fspath(executable),
        directory=False,
        label="%s frozen compiler" % target,
    )
    _require(
        executable.stat().st_mode & 0o111,
        "%s frozen compiler is not executable" % target,
    )

    description = _read_json(
        description_path,
        "%s application project description" % target,
    )
    component_info = (
        description.get("build_component_info")
        if isinstance(description, dict)
        else None
    )
    _require(
        isinstance(component_info, dict) and bool(component_info),
        "%s project description lacks component information" % target,
    )
    owning_components: list[tuple[str, dict[str, Any]]] = []
    for component_name, raw_component in component_info.items():
        if not isinstance(component_name, str) or not isinstance(raw_component, dict):
            continue
        component_sources = raw_component.get("sources")
        if not isinstance(component_sources, list):
            continue
        resolved_sources = []
        for raw_source in component_sources:
            if not isinstance(raw_source, str):
                continue
            source = _audit_path_in_roots(
                raw_source,
                relative_to=target_build,
                roots=(root, builds),
                label="%s component source" % target,
            )
            resolved_sources.append(source.resolve())
        if frozen.resolve() in resolved_sources:
            owning_components.append((component_name, raw_component))
    _require(
        len(owning_components) == 1,
        "%s frozen_content.c must belong to one component" % target,
    )
    component_name, component = owning_components[0]
    archive_raw = component.get("file")
    _require(
        isinstance(archive_raw, str) and bool(archive_raw),
        "%s frozen component archive is missing" % target,
    )
    archive = _audit_path_in_roots(
        archive_raw,
        relative_to=target_build,
        roots=(root, builds),
        label="%s frozen component archive" % target,
    )
    _require(
        archive.is_file(),
        "%s frozen component archive is missing" % target,
    )
    payloads = _audit_ar_member_payloads(archive)
    member_payloads = payloads.get(member_name, [])
    _require(
        len(member_payloads) == 1,
        "%s linked frozen object member is missing or ambiguous" % target,
    )
    try:
        map_lines = map_path.read_text(
            encoding="utf-8",
            errors="strict",
        ).splitlines()
    except OSError as exc:
        raise ReleaseError(
            "%s linked map file is missing" % target
        ) from exc
    linked_occurrences = []
    for line in map_lines:
        match = re.fullmatch(r"(\S+\.a)\(([^()]+)\)", line)
        if match is None or match.group(2) != member_name:
            continue
        candidate_raw = Path(match.group(1))
        candidate = (
            candidate_raw
            if candidate_raw.is_absolute()
            else map_path.parent / candidate_raw
        )
        if candidate.resolve() != archive.resolve():
            continue
        linked_archive = _audit_path_in_roots(
            match.group(1),
            relative_to=map_path.parent,
            roots=(root, builds),
            label="%s linked frozen archive" % target,
        )
        linked_occurrences.append((linked_archive.resolve(), member_name))
    _require(
        len(linked_occurrences) == 1,
        "%s frozen object is not one exact linked archive member" % target,
    )

    with tempfile.TemporaryDirectory(
        prefix="pyble-frozen-object-proof-%s-" % target
    ) as temporary_raw:
        temporary = Path(temporary_raw).resolve()
        rebuilt = temporary / member_name
        replay = list(tokens)
        replay[output_index] = os.fspath(rebuilt)
        environment = _audit_controlled_subprocess_environment(temporary)
        try:
            completed = subprocess.run(
                replay,
                cwd=directory,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=180,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReleaseError(
                "%s frozen object reconstruction failed" % target
            ) from exc
        _require(
            completed.returncode == 0,
            "%s frozen object reconstruction failed" % target,
        )
        _audit_v2_regular_path(
            os.fspath(rebuilt),
            directory=False,
            label="%s reconstructed frozen object" % target,
        )
        rebuilt_bytes = rebuilt.read_bytes()
    _require(
        rebuilt_bytes == member_payloads[0],
        "%s linked frozen object differs from frozen_content.c" % target,
    )
    try:
        archive_relative = archive.resolve().relative_to(builds.resolve()).as_posix()
    except ValueError as exc:
        raise ReleaseError(
            "%s frozen archive is outside the build root" % target
        ) from exc
    _require(
        archive_relative.startswith(target + "/"),
        "%s frozen archive belongs to another target" % target,
    )
    return {
        "component": component_name,
        "archive_path": archive_relative,
        "member": member_name,
        "sha256": _sha256_bytes(member_payloads[0]),
    }


def _audit_frozen_names(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except OSError as exc:
        raise ReleaseError("generated frozen_content.c is missing") from exc
    names = re.findall(r"(?m)frozen file name:\s*([A-Za-z0-9_./+-]+\.py)\s*$", text)
    if not names:
        names = re.findall(r'"([A-Za-z0-9_./+-]+\.py)\\0"', text)
    _require(names, "generated frozen_content.c has no Python inventory")
    _require(
        len(names) == len(set(names)),
        "generated frozen_content.c contains duplicate Python destinations",
    )
    return set(names)


def _audit_manifest_literal(node: ast.AST, label: str) -> Any:
    try:
        return ast.literal_eval(node)
    except (TypeError, ValueError) as exc:
        raise ReleaseError("%s must be a literal value" % label) from exc


def _audit_manifest_call_arguments(
    call: ast.Call,
    *,
    operation: str,
    positional: tuple[str, ...],
    allowed_keywords: set[str],
) -> dict[str, Any]:
    _require(
        len(call.args) <= len(positional),
        "manifest %s has too many positional arguments" % operation,
    )
    values: dict[str, Any] = {}
    for name, node in zip(positional, call.args):
        _require(
            not isinstance(node, ast.Starred),
            "manifest %s uses argument expansion" % operation,
        )
        values[name] = _audit_manifest_literal(
            node,
            "manifest %s argument %s" % (operation, name),
        )
    for keyword in call.keywords:
        _require(
            keyword.arg is not None,
            "manifest %s uses keyword expansion" % operation,
        )
        name = keyword.arg
        _require(
            name in allowed_keywords,
            "manifest %s has an unknown keyword %s" % (operation, name),
        )
        _require(
            name not in values,
            "manifest %s duplicates argument %s" % (operation, name),
        )
        values[name] = _audit_manifest_literal(
            keyword.value,
            "manifest %s argument %s" % (operation, name),
        )
    return values


def _audit_manifest_path(
    value: Any,
    *,
    relative_to: Path,
    macros: dict[str, Path],
    repo_root: Path,
    label: str,
) -> Path:
    _require(isinstance(value, str) and bool(value), "%s is not a string" % label)
    _require(
        "\x00" not in value and "\\" not in value,
        "%s contains an unsafe path" % label,
    )
    expanded = value
    for name, path in macros.items():
        expanded = expanded.replace("$(%s)" % name, os.fspath(path))
    _require(
        "$(" not in expanded,
        "%s contains an unresolved manifest variable" % label,
    )
    candidate = Path(expanded)
    _require(
        not (candidate.is_absolute() and expanded == value),
        "%s uses an unreviewed absolute path" % label,
    )
    if not candidate.is_absolute():
        candidate = relative_to / candidate
    candidate = candidate.absolute()
    _audit_no_symlink_components(repo_root, candidate, label)
    return candidate


def _audit_resolve_manifest_context(
    manifest_path: Path,
    *,
    repo_root: Path,
    board_dir: Path,
) -> tuple[dict[str, Path], set[Path], dict[str, dict[str, Any]]]:
    micropython = repo_root / "firmware" / "upstream" / "micropython"
    macros = {
        "MPY_DIR": micropython,
        "PORT_DIR": micropython / "ports" / "esp32",
        "BOARD_DIR": board_dir,
    }
    required_manifests = {
        "neopixel": (
            micropython
            / "lib"
            / "micropython-lib"
            / "micropython"
            / "drivers"
            / "led"
            / "neopixel"
            / "manifest.py"
        )
    }
    selections: dict[str, Path] = {}
    selection_details: dict[str, dict[str, Any]] = {}
    traversed: set[Path] = set()
    active: set[Path] = set()

    def add_selection(
        destination: Any,
        source: Path,
        label: str,
        *,
        opt: Any,
        metadata: dict[str, str],
    ) -> None:
        relative = _safe_relative_path(destination, "%s destination" % label)
        _require(relative.endswith(".py"), "%s destination must be .py" % label)
        _audit_no_symlink_components(repo_root, source, "%s source" % label)
        try:
            mode = source.lstat().st_mode
        except OSError as exc:
            raise ReleaseError("%s source is missing: %s" % (label, source)) from exc
        _require(
            stat_module.S_ISREG(mode) and not stat_module.S_ISLNK(mode),
            "%s source must be a regular non-symlink file" % label,
        )
        _require(
            relative not in selections,
            "frozen manifest duplicates destination %s" % relative,
        )
        selections[relative] = source
        selection_details[relative] = {
            "optimization": opt,
            "metadata_version": metadata.get("version"),
        }

    def resolve(
        current_manifest: Path,
        metadata: dict[str, str],
    ) -> None:
        current_manifest = current_manifest.absolute()
        _audit_no_symlink_components(
            repo_root,
            current_manifest,
            "frozen manifest",
        )
        try:
            mode = current_manifest.lstat().st_mode
            source_text = current_manifest.read_text(
                encoding="utf-8",
                errors="strict",
            )
        except (OSError, UnicodeError) as exc:
            raise ReleaseError(
                "frozen manifest is missing or not strict UTF-8: %s" % current_manifest
            ) from exc
        _require(
            stat_module.S_ISREG(mode) and not stat_module.S_ISLNK(mode),
            "frozen manifest must be a regular non-symlink file",
        )
        _require(
            current_manifest not in active,
            "frozen manifest include cycle is forbidden",
        )
        _require(
            current_manifest not in traversed,
            "frozen manifest is included more than once",
        )
        active.add(current_manifest)
        traversed.add(current_manifest)
        try:
            try:
                syntax = ast.parse(
                    source_text,
                    filename=os.fspath(current_manifest),
                    mode="exec",
                )
            except SyntaxError as exc:
                raise ReleaseError(
                    "frozen manifest is not valid literal Python syntax: %s"
                    % current_manifest
                ) from exc

            for statement in syntax.body:
                _require(
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Call)
                    and isinstance(statement.value.func, ast.Name),
                    "frozen manifest contains dynamic or unrecognized syntax",
                )
                call = statement.value
                operation = call.func.id
                _require(
                    operation
                    in {
                        "include",
                        "require",
                        "package",
                        "module",
                        "metadata",
                    },
                    "frozen manifest contains unknown operation %s" % operation,
                )

                if operation == "metadata":
                    values = _audit_manifest_call_arguments(
                        call,
                        operation=operation,
                        positional=(),
                        allowed_keywords={"description", "version"},
                    )
                    _require(
                        values
                        and all(
                            isinstance(value, str) and bool(value)
                            for value in values.values()
                        ),
                        "manifest metadata must contain nonempty literal strings",
                    )
                    _require(
                        "version" not in values
                        or re.fullmatch(
                            r"[0-9A-Za-z][0-9A-Za-z._+-]{0,127}",
                            values["version"],
                        )
                        is not None,
                        "manifest metadata version is not a safe version token",
                    )
                    _require(
                        not metadata,
                        "manifest metadata must be declared once before selections",
                    )
                    metadata.update(values)
                    continue

                if operation == "include":
                    values = _audit_manifest_call_arguments(
                        call,
                        operation=operation,
                        positional=("manifest_path",),
                        allowed_keywords={"manifest_path"},
                    )
                    _require(
                        set(values) == {"manifest_path"},
                        "manifest include requires one literal path",
                    )
                    included = _audit_manifest_path(
                        values["manifest_path"],
                        relative_to=current_manifest.parent,
                        macros=macros,
                        repo_root=repo_root,
                        label="included manifest",
                    )
                    if included.is_dir():
                        included = included / "manifest.py"
                    resolve(included, metadata)
                    continue

                if operation == "require":
                    values = _audit_manifest_call_arguments(
                        call,
                        operation=operation,
                        positional=("name",),
                        allowed_keywords={"name"},
                    )
                    name = values.get("name")
                    _require(
                        isinstance(name, str) and name in required_manifests,
                        "manifest require names an unrecognized pinned package",
                    )
                    resolve(required_manifests[name], {})
                    continue

                if operation == "module":
                    values = _audit_manifest_call_arguments(
                        call,
                        operation=operation,
                        positional=("module_path", "base_path", "opt"),
                        allowed_keywords={"module_path", "base_path", "opt"},
                    )
                    module_path = values.get("module_path")
                    _require(
                        isinstance(module_path, str),
                        "manifest module requires one literal module path",
                    )
                    destination = _safe_relative_path(
                        module_path,
                        "manifest module",
                    )
                    base_value = values.get("base_path", ".")
                    base = _audit_manifest_path(
                        base_value,
                        relative_to=current_manifest.parent,
                        macros=macros,
                        repo_root=repo_root,
                        label="manifest module base",
                    )
                    opt = values.get("opt")
                    _require(
                        opt is None
                        or (
                            isinstance(opt, int)
                            and not isinstance(opt, bool)
                            and 0 <= opt <= 3
                        ),
                        "manifest module opt must be a literal integer from 0 to 3",
                    )
                    source = base / destination
                    if (
                        base_value == "$(BOARD_DIR)"
                        and destination.startswith("pyble/")
                        and not source.exists()
                    ):
                        source = repo_root / "firmware" / destination
                    elif (
                        base_value == "$(BOARD_DIR)/pyble"
                        and destination == "_version.py"
                        and not source.exists()
                    ):
                        # The reviewed source is a dev-only template. ESP
                        # builds overwrite the copied board-tree module from
                        # versions.lock before freezing it; payload proof
                        # below validates those exact generated bytes.
                        source = repo_root / "firmware" / "pyble" / destination
                    elif (
                        base_value == "$(BOARD_DIR)"
                        and destination in _AUDIT_FIRST_PARTY_FROZEN_SOURCES
                        and not source.exists()
                    ):
                        source = (
                            repo_root
                            / _AUDIT_FIRST_PARTY_FROZEN_SOURCES[destination][
                                "canonical_path"
                            ]
                        )
                    add_selection(
                        destination,
                        source,
                        "manifest module",
                        opt=opt,
                        metadata=metadata,
                    )
                    continue

                values = _audit_manifest_call_arguments(
                    call,
                    operation=operation,
                    positional=("package_path", "files", "base_path", "opt"),
                    allowed_keywords={"package_path", "files", "base_path", "opt"},
                )
                package_path = values.get("package_path")
                files = values.get("files")
                _require(
                    isinstance(package_path, str),
                    "manifest package requires one literal package path",
                )
                package_destination = _safe_relative_path(
                    package_path,
                    "manifest package",
                )
                _require(
                    isinstance(files, (list, tuple))
                    and bool(files)
                    and all(isinstance(item, str) for item in files),
                    "manifest package requires an explicit literal file list",
                )
                base = _audit_manifest_path(
                    values.get("base_path", "."),
                    relative_to=current_manifest.parent,
                    macros=macros,
                    repo_root=repo_root,
                    label="manifest package base",
                )
                opt = values.get("opt")
                _require(
                    opt is None
                    or (
                        isinstance(opt, int)
                        and not isinstance(opt, bool)
                        and 0 <= opt <= 3
                    ),
                    "manifest package opt must be a literal integer from 0 to 3",
                )
                for item in files:
                    package_file = _safe_relative_path(
                        item,
                        "manifest package file",
                    )
                    destination = "%s/%s" % (
                        package_destination,
                        package_file,
                    )
                    add_selection(
                        destination,
                        base / package_destination / package_file,
                        "manifest package",
                        opt=opt,
                        metadata=metadata,
                    )
        finally:
            active.remove(current_manifest)

    resolve(manifest_path, {})
    return selections, traversed, selection_details


def _audit_resolve_manifest(
    manifest_path: Path,
    *,
    repo_root: Path,
    board_dir: Path,
) -> dict[str, Path]:
    selections, _traversed, _selection_details = _audit_resolve_manifest_context(
        manifest_path,
        repo_root=repo_root,
        board_dir=board_dir,
    )
    return selections


def _audit_candidate_source_date_epoch(
    repo_root: Path,
    build_root: Path,
    *,
    targets: tuple[str, ...] | None = None,
) -> int:
    """Return the one source-commit epoch proven by candidate build records."""

    selected_targets = (
        tuple(sorted(TARGET_TO_PROFILE)) if targets is None else targets
    )
    _require(bool(selected_targets), "candidate source epoch has no build targets")
    validated = []
    for target in selected_targets:
        _require(
            target in TARGET_TO_PROFILE,
            "candidate source epoch names an unknown build target",
        )
        provenance = _validate_build_provenance(
            _read_json(
                Path(build_root) / target / "pyble-build-provenance.json",
                "%s candidate build provenance" % target,
            ),
            target,
        )
        validated.append({"provenance": provenance})
    identity = _require_one_build_source_identity(validated)
    source_date_epoch = identity[0]
    source_commit = identity[1]

    root = Path(repo_root)
    if (root / ".git").exists():
        head = _git_output(root, "PyBLE", "rev-parse", "HEAD")
        _require(
            head == source_commit,
            "candidate source epoch commit is not the PyBLE checkout HEAD",
        )
        timestamp = _git_output(
            root,
            "PyBLE",
            "show",
            "-s",
            "--format=%ct",
            source_commit,
        )
        _require(
            timestamp.isdigit() and int(timestamp) == source_date_epoch,
            "candidate SOURCE_DATE_EPOCH disagrees with its source commit",
        )
    return source_date_epoch


def _audit_controlled_subprocess_environment(
    temporary: Path,
    *,
    source_date_epoch: int | None = None,
) -> dict[str, str]:
    """Return the complete fail-closed environment for release proof tools."""

    home = temporary / "home"
    cache = temporary / "python-cache"
    scratch = temporary / "tmp"
    for directory in (home, cache, scratch):
        directory.mkdir(parents=True, exist_ok=True)
    environment = {
        "HOME": os.fspath(home),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPYCACHEPREFIX": os.fspath(cache),
        "TMPDIR": os.fspath(scratch),
        "TZ": "UTC",
    }
    if source_date_epoch is not None:
        _require(
            type(source_date_epoch) is int and source_date_epoch > 0,
            "candidate SOURCE_DATE_EPOCH must be a positive integer",
        )
        environment["SOURCE_DATE_EPOCH"] = str(source_date_epoch)
    return environment


def _audit_rebuild_mpy_cross(
    repo_root: Path,
    *,
    source_date_epoch: int,
) -> str:
    """Build mpy-cross from pinned source and return its byte-proven digest."""

    root = Path(repo_root).resolve()
    source = root / "firmware" / "upstream" / "micropython" / "mpy-cross"
    admitted = source / "build" / "mpy-cross"
    _audit_v2_regular_path(
        os.fspath(source),
        directory=True,
        label="mpy-cross source root",
    )
    _audit_v2_regular_path(
        os.fspath(admitted),
        directory=False,
        label="admitted mpy-cross",
    )
    _require(
        admitted.stat().st_mode & 0o111,
        "admitted mpy-cross is not executable",
    )

    search_path = "/usr/bin:/bin"
    make_raw = shutil.which("make", path=search_path)
    cc_raw = shutil.which("clang", path=search_path) or shutil.which(
        "cc",
        path=search_path,
    )
    _require(
        isinstance(make_raw, str) and isinstance(cc_raw, str),
        "trusted mpy-cross build tools are unavailable",
    )
    make = Path(make_raw).resolve()
    compiler = Path(cc_raw).resolve()
    for path, label in (
        (make, "mpy-cross make"),
        (compiler, "mpy-cross host compiler"),
    ):
        _audit_v2_regular_path(os.fspath(path), directory=False, label=label)
        _require(path.stat().st_mode & 0o111, "%s is not executable" % label)

    with tempfile.TemporaryDirectory(
        prefix="pyble-mpy-cross-proof-"
    ) as temporary_raw:
        temporary = Path(temporary_raw).resolve()
        output_root = temporary / "build"
        environment = _audit_controlled_subprocess_environment(
            temporary,
            source_date_epoch=source_date_epoch,
        )
        try:
            completed = subprocess.run(
                [
                    os.fspath(make),
                    "-C",
                    os.fspath(source),
                    "BUILD=%s" % output_root,
                    "CC=%s" % compiler,
                    "PYTHON=%s" % Path(sys.executable).resolve(),
                    "-j1",
                ],
                cwd=temporary,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=180,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReleaseError("clean mpy-cross rebuild failed") from exc
        rebuilt = output_root / "mpy-cross"
        _require(
            completed.returncode == 0,
            "clean mpy-cross rebuild failed",
        )
        _audit_v2_regular_path(
            os.fspath(rebuilt),
            directory=False,
            label="rebuilt mpy-cross",
        )
        _require(
            rebuilt.stat().st_mode & 0o111
            and rebuilt.read_bytes() == admitted.read_bytes(),
            "admitted mpy-cross differs from its clean source build",
        )
        digest = _sha256_path(rebuilt)
    _require(
        _sha256_path(admitted) == digest,
        "admitted mpy-cross changed after its clean source build",
    )
    return digest


def _firmware_release_core(
    value: str,
    label: str,
) -> tuple[int, int, int]:
    """Return the SemVer release core used by source-introduction gates."""

    _require(
        isinstance(value, str) and SEMVER_RE.fullmatch(value) is not None,
        "%s must be canonical SemVer" % label,
    )
    core = value.split("+", 1)[0].split("-", 1)[0]
    major, minor, patch = core.split(".")
    return int(major), int(minor), int(patch)


def _release_profile_order_for_version(
    firmware_version: str,
) -> tuple[str, ...]:
    """Return the immutable public profile order for one source era."""

    core = _firmware_release_core(firmware_version, "firmware source version")
    if core < (0, 5, 0):
        return HISTORICAL_V042_RELEASE_PROFILE_ORDER
    if core < (0, 6, 0):
        return V05_RELEASE_PROFILE_ORDER
    return V060_RELEASE_PROFILE_ORDER


def _release_metadata_schema_version_for_version(firmware_version: str) -> int:
    """Select the immutable release-metadata schema for one source era."""

    core = _firmware_release_core(firmware_version, "firmware source version")
    if core < (0, 5, 0):
        return 2
    return 3 if core < (0, 6, 0) else 4


def _hil_schema_version_for_version(firmware_version: str) -> int:
    """Select the exact HIL record schema for one source era."""

    core = _firmware_release_core(firmware_version, "firmware source version")
    if core < (0, 5, 0):
        return 2
    return 4 if core < (0, 6, 0) else 5


def _qualification_policy_schema_version_for_version(
    firmware_version: str,
) -> int:
    """Select the immutable OI-1 policy schema for one source era."""

    core = _firmware_release_core(firmware_version, "firmware source version")
    if core < (0, 5, 0):
        return 1
    return 2 if core < (0, 6, 0) else 3


def _require_source_era_evidence_count(
    evidence: list[Path],
    firmware_version: str,
    label: str,
) -> list[Path]:
    """Require one evidence input per profile in the selected source era."""

    _require(isinstance(evidence, list), "%s must be an array" % label)
    expected = len(_release_profile_order_for_version(firmware_version))
    _require(
        len(evidence) == expected,
        "%s must contain exactly %d source-era inputs" % (label, expected),
    )
    return evidence


def _release_license_inventory_for_version(
    firmware_version: str,
) -> list[dict[str, Any]]:
    """Return the explicit per-port redistributed-input review inventory."""

    inventory: list[dict[str, Any]] = []
    for profile_id in _release_profile_order_for_version(firmware_version):
        spec = PROFILE_SPECS[profile_id]
        is_rp2 = spec["port"] == "rp2"
        inventory.append(
            {
                "profile_id": profile_id,
                "target": spec["target"],
                "resource_kind": "rp2" if is_rp2 else "esp-idf",
                "roles": (
                    [
                        "linked-inputs",
                        "frozen-modules",
                        "pico-sdk",
                        "btstack",
                        "cyw43",
                        "arm-gnu-runtime",
                    ]
                    if is_rp2
                    else ["application", "bootloader"]
                ),
            }
        )
    return inventory


def _require_release_license_inventory(
    value: Any,
    firmware_version: str,
) -> dict[str, Any]:
    """Validate an exact, provenance-bound heterogeneous review receipt.

    This helper deliberately validates evidence; it never derives or fills a
    missing review result.  The production audit must emit this receipt from
    the exact reviewed build before a heterogeneous release can be admitted.
    """

    receipt = _exact_keys(
        value,
        {"profile_order", "inventories"},
        "release license inventory receipt",
    )
    expected = _release_license_inventory_for_version(firmware_version)
    _require(
        receipt["profile_order"]
        == [item["profile_id"] for item in expected],
        "release license inventory profile order is stale or incomplete",
    )
    inventories = receipt["inventories"]
    _require(
        isinstance(inventories, list) and len(inventories) == len(expected),
        "release license inventory coverage is incomplete",
    )
    for actual, contract in zip(inventories, expected):
        item = _exact_keys(
            actual,
            {
                "profile_id",
                "resource_kind",
                "roles",
                "provenance_sha256",
            },
            "release license inventory %s" % contract["profile_id"],
        )
        _require(
            item["profile_id"] == contract["profile_id"]
            and item["resource_kind"] == contract["resource_kind"]
            and item["roles"] == contract["roles"],
            "release license inventory differs for %s" % contract["profile_id"],
        )
        _require(
            isinstance(item["provenance_sha256"], str)
            and SHA256_RE.fullmatch(item["provenance_sha256"]) is not None,
            "release license inventory provenance is unbound for %s"
            % contract["profile_id"],
        )
    return receipt


def _waveshare_lcd147b_capable_version(firmware_version: str) -> bool:
    """Return whether this source era ships the qualified LCD companion."""

    return _firmware_release_core(
        firmware_version,
        "firmware source version",
    ) >= (0, 5, 0)


def _audit_first_party_frozen_sources_for_version(
    firmware_version: str,
) -> dict[str, dict[str, str]]:
    """Select only first-party frozen sources shipped by this source era."""

    selected = {}
    version_core = _firmware_release_core(
        firmware_version,
        "firmware source version",
    )
    for destination, contract in _AUDIT_FIRST_PARTY_FROZEN_SOURCES.items():
        introduced = contract["introduced_version"]
        if version_core >= _firmware_release_core(
            introduced,
            "first-party frozen source introduction version",
        ):
            selected[destination] = contract
    return selected


def _audit_generated_version_module_bytes(repo_root: Path) -> bytes:
    """Exact ESP build.sh output for the lock-derived frozen identity."""

    lock = _read_lock(Path(repo_root))
    return (
        "# SPDX-License-Identifier: MIT\n"
        "# GENERATED by firmware/scripts/build.sh from "
        "firmware/versions.lock [pyble] — do not edit.\n"
        'AGENT_VERSION = "%s"\n'
        'PROTOCOL_VERSION = "%s"\n'
        % (
            lock["pyble"]["agent_version"],
            lock["pyble"]["protocol_version"],
        )
    ).encode("utf-8")


def _audit_first_party_frozen_source_evidence(
    *,
    repo_root: Path,
    target: str,
    board_dir: Path,
    selections: dict[str, Path],
    firmware_version: str | None = None,
) -> list[dict[str, str]]:
    """Bind canonical PyBLE Python sources to their generated board copies."""

    root = Path(repo_root).absolute()
    source_version = (
        firmware_version
        if firmware_version is not None
        else _read_lock(root)["pyble"]["agent_version"]
    )
    active_contracts = _audit_first_party_frozen_sources_for_version(
        source_version
    )
    records: list[dict[str, str]] = []
    for destination, contract in sorted(
        _AUDIT_FIRST_PARTY_FROZEN_SOURCES.items()
    ):
        generated = Path(board_dir).absolute() / destination
        if destination not in active_contracts:
            _require(
                destination not in selections,
                "%s must not select unavailable first-party frozen source %s"
                % (target, destination),
            )
            _require(
                not generated.exists() and not generated.is_symlink(),
                "%s contains an unavailable generated first-party source %s"
                % (target, destination),
            )
            continue

        canonical_relative = contract["canonical_path"]
        canonical = _audit_repo_file(
            root,
            canonical_relative,
            "first-party frozen source %s" % destination,
        )
        expected_target = contract["target"]
        if target != expected_target:
            _require(
                destination not in selections,
                "%s must not select first-party frozen source %s"
                % (target, destination),
            )
            _require(
                not generated.exists() and not generated.is_symlink(),
                "%s contains a stray generated first-party source %s"
                % (target, destination),
            )
            continue

        _require(
            destination in selections
            and selections[destination].resolve() == canonical.resolve(),
            "%s must select canonical first-party source %s"
            % (target, destination),
        )
        try:
            canonical_text = canonical.read_text(
                encoding="utf-8",
                errors="strict",
            )
        except (OSError, UnicodeError) as exc:
            raise ReleaseError(
                "first-party frozen source %s is not strict UTF-8"
                % destination
            ) from exc
        expected_spdx = contract["spdx_expression"]
        _require(
            _spdx_from_text(canonical_text) == {expected_spdx},
            "first-party frozen source %s must declare exactly SPDX %s"
            % (destination, expected_spdx),
        )
        try:
            generated_relative = generated.relative_to(root).as_posix()
        except ValueError as exc:
            raise ReleaseError(
                "%s generated first-party source %s escapes the repository"
                % (target, destination)
            ) from exc
        generated_source = _audit_repo_file(
            root,
            generated_relative,
            "%s generated first-party source %s" % (target, destination),
        )
        canonical_bytes = canonical.read_bytes()
        _require(
            generated_source.read_bytes() == canonical_bytes,
            "%s generated first-party source %s differs from canonical source"
            % (target, destination),
        )
        records.append(
            {
                "destination": destination,
                "canonical_path": canonical_relative,
                "generated_path": generated_relative,
                "sha256": _sha256_bytes(canonical_bytes),
                "spdx_expression": expected_spdx,
            }
        )
    return records


def _audit_frozen_payload_proof(
    *,
    repo_root: Path,
    target: str,
    manifest_path: Path,
    frozen_path: Path,
    selections: dict[str, Path],
    trusted_mpy_cross_sha256: str | None = None,
) -> dict[str, Any]:
    """Rebuild frozen MPY content from clean state and compare every byte."""

    settings = FROZEN_TARGET_SETTINGS.get(target)
    _require(settings is not None, "frozen payload target is unsupported")
    root = Path(repo_root).absolute()
    firmware_version = _read_lock(root)["pyble"]["agent_version"]
    includes_first_party_field = bool(
        _audit_first_party_frozen_sources_for_version(firmware_version)
    )
    resolved_root = root.resolve()
    micropython = root / "firmware" / "upstream" / "micropython"
    port_dir = micropython / "ports" / "esp32"
    board_dir = port_dir / "boards" / settings["board"]
    try:
        copied_manifest_relative = (
            (board_dir / "manifest.py")
            .absolute()
            .relative_to(root.absolute())
            .as_posix()
        )
    except ValueError as exc:
        raise ReleaseError(
            "%s generated board manifest escapes the repository" % target
        ) from exc
    copied_manifest = _audit_repo_file(
        root,
        copied_manifest_relative,
        "%s generated board manifest" % target,
    )
    reviewed_manifest = _audit_repo_file(
        root,
        Path(manifest_path)
        .resolve()
        .relative_to(resolved_root)
        .as_posix(),
        "%s reviewed board manifest" % target,
    )
    _require(
        copied_manifest.read_bytes() == reviewed_manifest.read_bytes(),
        "%s generated board manifest differs from its reviewed overlay" % target,
    )

    first_party_frozen_sources = _audit_first_party_frozen_source_evidence(
        repo_root=root,
        target=target,
        board_dir=board_dir,
        selections=selections,
        firmware_version=firmware_version,
    )

    overlay_root = (
        root / "firmware" / "board_overlays" / target
    ).resolve()
    pyble_root = (root / "firmware" / "pyble").resolve()
    for destination, reviewed_source in selections.items():
        resolved_source = reviewed_source.resolve()
        if (
            destination == "_version.py"
            and resolved_source == (pyble_root / "_version.py").resolve()
        ):
            copied_source = _audit_repo_file(
                root,
                (board_dir / "pyble" / destination)
                .absolute()
                .relative_to(root.absolute())
                .as_posix(),
                "%s generated lock-derived source %s" % (target, destination),
            )
            _require(
                copied_source.read_bytes()
                == _audit_generated_version_module_bytes(root),
                "%s generated lock-derived source %s is stale"
                % (target, destination),
            )
            continue
        if resolved_source.is_relative_to(overlay_root):
            copied_source = board_dir / destination
        elif resolved_source.is_relative_to(pyble_root):
            copied_source = board_dir / destination
        else:
            continue
        try:
            copied_relative = (
                copied_source.absolute()
                .relative_to(root.absolute())
                .as_posix()
            )
        except ValueError as exc:
            raise ReleaseError(
                "%s generated board source %s escapes the repository"
                % (target, destination)
            ) from exc
        copied_source = _audit_repo_file(
            root,
            copied_relative,
            "%s generated board source %s" % (target, destination),
        )
        reviewed_source = _audit_repo_file(
            root,
            resolved_source.relative_to(resolved_root).as_posix(),
            "%s reviewed frozen source %s" % (target, destination),
        )
        _require(
            copied_source.read_bytes() == reviewed_source.read_bytes(),
            "%s generated board source %s is stale" % (target, destination),
        )

    tool_relatives = (
        "firmware/upstream/micropython/mpy-cross/mpy_cross/__init__.py",
        "firmware/upstream/micropython/py/makeqstrdata.py",
        "firmware/upstream/micropython/tools/makemanifest.py",
        "firmware/upstream/micropython/tools/manifestfile.py",
        "firmware/upstream/micropython/tools/mpy-tool.py",
    )
    generator_tools = []
    for relative in tool_relatives:
        path = _audit_repo_file(
            root,
            relative,
            "%s frozen generator" % target,
        )
        generator_tools.append(
            {"path": relative, "sha256": _sha256_path(path)}
        )
    generator_tools.sort(key=lambda item: item["path"])
    mpy_cross_relative = (
        "firmware/upstream/micropython/mpy-cross/build/mpy-cross"
    )
    mpy_cross = _audit_repo_file(
        root,
        mpy_cross_relative,
        "%s mpy-cross" % target,
    )
    _require(
        mpy_cross.stat().st_mode & 0o111,
        "%s mpy-cross is not executable" % target,
    )
    mpy_cross_record = {
        "path": mpy_cross_relative,
        "sha256": _sha256_path(mpy_cross),
    }
    if trusted_mpy_cross_sha256 is None:
        target_build_root = Path(frozen_path).absolute().parent.parent
        trusted_mpy_cross_sha256 = _audit_rebuild_mpy_cross(
            root,
            source_date_epoch=_audit_candidate_source_date_epoch(
                root,
                target_build_root,
                targets=(target,),
            ),
        )
    _require(
        mpy_cross_record["sha256"] == trusted_mpy_cross_sha256,
        "%s mpy-cross differs from its clean source build" % target,
    )

    target_build = Path(frozen_path).absolute().parent
    _audit_no_symlink_components(
        target_build.parent,
        target_build,
        "%s target build root" % target,
    )
    try:
        target_build_mode = target_build.lstat().st_mode
    except OSError as exc:
        raise ReleaseError("%s target build root is missing" % target) from exc
    _require(
        stat_module.S_ISDIR(target_build_mode)
        and not stat_module.S_ISLNK(target_build_mode),
        "%s target build root must be a regular directory" % target,
    )

    def checked_build_path(
        path: Path,
        *,
        directory: bool,
        label: str,
    ) -> Path:
        lexical = path.absolute()
        _audit_no_symlink_components(target_build, lexical, label)
        _audit_v2_regular_path(
            str(lexical.resolve()),
            directory=directory,
            label=label,
        )
        return lexical

    qstr_path = checked_build_path(
        target_build / "genhdr" / "qstrdefs.preprocessed.h",
        directory=False,
        label="%s frozen qstr header" % target,
    )
    built_frozen = checked_build_path(
        Path(frozen_path),
        directory=False,
        label="%s frozen_content.c" % target,
    )
    retained_root = checked_build_path(
        target_build / "frozen_mpy",
        directory=True,
        label="%s retained frozen MPY root" % target,
    )
    expected_mpy_paths = {
        destination[:-3] + ".mpy" for destination in selections
    }
    retained_paths: dict[str, Path] = {}
    for candidate in retained_root.rglob("*"):
        _require(
            not candidate.is_symlink(),
            "%s retained frozen MPY inventory contains a symlink" % target,
        )
        if candidate.is_dir():
            continue
        _require(
            candidate.is_file(),
            "%s retained frozen MPY inventory contains a special file" % target,
        )
        relative = candidate.relative_to(retained_root).as_posix()
        _require(
            relative.endswith(".mpy") and relative not in retained_paths,
            "%s retained frozen MPY inventory is invalid" % target,
        )
        retained_paths[relative] = candidate
    _require(
        set(retained_paths) == expected_mpy_paths,
        "%s retained frozen MPY set differs from literal manifest" % target,
    )

    makemanifest = root / "firmware/upstream/micropython/tools/makemanifest.py"
    with tempfile.TemporaryDirectory(
        prefix="pyble-frozen-proof-%s-" % target
    ) as temporary_raw:
        temporary = Path(temporary_raw)
        generated_qstr = temporary / "genhdr" / "qstrdefs.preprocessed.h"
        generated_qstr.parent.mkdir(parents=True)
        shutil.copyfile(qstr_path, generated_qstr)
        generated_frozen = temporary / "frozen_content.c"
        command = [
            sys.executable,
            os.fspath(makemanifest),
            "-o",
            os.fspath(generated_frozen),
            "-v",
            "BOARD_DIR=%s" % board_dir,
            "-v",
            "MPY_DIR=%s" % micropython,
            "-v",
            "MPY_LIB_DIR=%s"
            % (
                micropython
                / "lib"
                / "micropython-lib"
            ),
            "-v",
            "PORT_DIR=%s" % port_dir,
            "-b",
            os.fspath(temporary),
            "-f-march=%s" % settings["architecture"],
            "--mpy-tool-flags=",
            os.fspath(copied_manifest),
        ]
        environment = _audit_controlled_subprocess_environment(temporary)
        try:
            completed = subprocess.run(
                command,
                cwd=temporary,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReleaseError(
                "%s clean frozen payload reconstruction failed" % target
            ) from exc
        _require(
            completed.returncode == 0 and generated_frozen.is_file(),
            "%s clean frozen payload reconstruction failed" % target,
        )
        generated_root = temporary / "frozen_mpy"
        generated_paths = {
            path.relative_to(generated_root).as_posix(): path
            for path in generated_root.rglob("*")
            if path.is_file()
        }
        _require(
            set(generated_paths) == expected_mpy_paths,
            "%s reconstructed frozen MPY set differs from literal manifest"
            % target,
        )
        for relative in sorted(expected_mpy_paths):
            _require(
                generated_paths[relative].read_bytes()
                == retained_paths[relative].read_bytes(),
                "%s retained frozen MPY %s differs from clean reconstruction"
                % (target, relative),
            )
        mpy_marker = (
            b"//\n// Content for MICROPY_MODULE_FROZEN_MPY\n//\n"
        )
        generated_bytes = generated_frozen.read_bytes()
        _require(
            generated_bytes.count(mpy_marker) == 1,
            "%s reconstructed frozen C has an invalid MPY marker" % target,
        )
        frozen_prefix = generated_bytes.split(mpy_marker, 1)[0] + mpy_marker
        ordered_mpy = [
            retained_paths[destination[:-3] + ".mpy"]
            for destination in selections
        ]
        mpy_tool = (
            root
            / "firmware"
            / "upstream"
            / "micropython"
            / "tools"
            / "mpy-tool.py"
        )
        try:
            frozen_completed = subprocess.run(
                [
                    sys.executable,
                    os.fspath(mpy_tool),
                    "-f",
                    "-q",
                    os.fspath(qstr_path),
                    *(os.fspath(path) for path in ordered_mpy),
                ],
                cwd=temporary,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReleaseError(
                "%s retained-MPY frozen C reconstruction failed" % target
            ) from exc
        _require(
            frozen_completed.returncode == 0
            and frozen_prefix + frozen_completed.stdout
            == built_frozen.read_bytes(),
            "%s frozen_content.c differs from clean reconstruction" % target,
        )

    proof = {
        "architecture": settings["architecture"],
        "qstrdefs_sha256": _sha256_path(qstr_path),
        "mpy_cross": mpy_cross_record,
        "generator_tools": generator_tools,
        "frozen_mpy": [
            {
                "destination": relative,
                "sha256": _sha256_path(retained_paths[relative]),
            }
            for relative in sorted(retained_paths)
        ],
        "generated_board_manifest": copied_manifest_relative,
    }
    if includes_first_party_field:
        proof["first_party_frozen_sources"] = first_party_frozen_sources
    return proof


def _audit_manifest_evidence_record(
    manifest_path: Path,
    frozen_path: Path,
    *,
    repo_root: Path,
    target: str,
    trusted_mpy_cross_sha256: str | None = None,
) -> tuple[dict[str, Path], dict[str, Any]]:
    """Return literal selections plus canonical, host-independent evidence."""

    root = Path(repo_root).absolute()
    resolved_root = root.resolve()
    manifest = Path(manifest_path).absolute()
    frozen_source = Path(frozen_path).absolute()
    frozen = _audit_frozen_names(frozen_source)
    selections, traversed, selection_details = _audit_resolve_manifest_context(
        manifest,
        repo_root=root,
        board_dir=manifest.parent,
    )
    _require(
        set(selections) == frozen,
        "%s frozen manifest and generated inventory disagree" % target,
    )

    def logical_file(path: Path, label: str) -> tuple[str, str]:
        checked = path.resolve()
        _require(
            checked.is_relative_to(resolved_root),
            "%s is outside the repository" % label,
        )
        relative = checked.relative_to(resolved_root).as_posix()
        source = _audit_repo_file(root, relative, label)
        return relative, _sha256_path(source)

    manifests = []
    for traversed_manifest in sorted(
        traversed,
        key=lambda path: os.fspath(path.resolve()),
    ):
        relative, digest = logical_file(
            traversed_manifest,
            "%s frozen manifest" % target,
        )
        manifests.append({"path": relative, "sha256": digest})
    selected_sources = []
    for destination, source_path in sorted(selections.items()):
        relative, digest = logical_file(
            source_path,
            "%s frozen source" % target,
        )
        selected_sources.append(
            {
                "destination": destination,
                "source_path": relative,
                "sha256": digest,
                "optimization": selection_details[destination]["optimization"],
                "metadata_version": selection_details[destination][
                    "metadata_version"
                ],
            }
        )
    frozen_proof = _audit_frozen_payload_proof(
        repo_root=root,
        target=target,
        manifest_path=manifest,
        frozen_path=frozen_source,
        selections=selections,
        trusted_mpy_cross_sha256=trusted_mpy_cross_sha256,
    )
    return selections, {
        "target": target,
        "frozen_content_sha256": _sha256_path(frozen_source),
        "manifests": manifests,
        "selections": selected_sources,
        **frozen_proof,
    }


def _audit_manifest_inventory(
    manifest_path: Path,
    frozen_path: Path,
    *,
    repo_root: Path,
    target: str,
) -> set[str]:
    manifest = Path(manifest_path)
    selections, _traversed, _details = _audit_resolve_manifest_context(
        manifest,
        repo_root=Path(repo_root),
        board_dir=manifest.parent,
    )
    frozen = _audit_frozen_names(Path(frozen_path))
    _require(
        set(selections) == frozen,
        "%s frozen manifest and generated inventory disagree" % target,
    )
    return set(selections)


def _audit_all_manifest_evidence(
    *,
    repo_root: Path,
    build_root: Path,
    trusted_mpy_cross_sha256: str | None = None,
) -> list[dict[str, Any]]:
    if trusted_mpy_cross_sha256 is None:
        trusted_mpy_cross_sha256 = _audit_rebuild_mpy_cross(
            repo_root,
            source_date_epoch=_audit_candidate_source_date_epoch(
                repo_root,
                build_root,
            ),
        )
    records = []
    for _profile_id, target, _idf_target in LICENSE_AUDIT_PROFILES:
        _selections, evidence = _audit_manifest_evidence_record(
            Path(repo_root)
            / "firmware"
            / "board_overlays"
            / target
            / "manifest.py",
            Path(build_root) / target / "frozen_content.c",
            repo_root=Path(repo_root),
            target=target,
            trusted_mpy_cross_sha256=trusted_mpy_cross_sha256,
        )
        evidence["linked_frozen_object"] = _audit_linked_frozen_object(
            repo_root=Path(repo_root),
            build_root=Path(build_root),
            target=target,
            frozen_path=Path(build_root) / target / "frozen_content.c",
        )
        records.append(evidence)
    return sorted(records, key=lambda item: item["target"])


def _audit_v2_role_paths(
    build_root: Path,
    target: str,
    role: str,
) -> tuple[Path, Path, Path, Path]:
    target_build = build_root / target
    if role == "application":
        return (
            target_build,
            target_build / "project_description.json",
            target_build / "compile_commands.json",
            target_build / "micropython.map",
        )
    role_build = target_build / "bootloader"
    return (
        role_build,
        role_build / "project_description.json",
        role_build / "compile_commands.json",
        role_build / "bootloader.map",
    )


def _audit_command_token_uses_response_file(token: str) -> bool:
    return token.startswith("@") or ",@" in token


def _audit_v2_command_tokens(command: Any, label: str) -> list[str]:
    _require(isinstance(command, dict), "%s compile command is invalid" % label)
    arguments = command.get("arguments")
    command_text = command.get("command")
    _require(
        (arguments is None) != (command_text is None),
        "%s compile command must use exactly one argument representation" % label,
    )
    if arguments is not None:
        _require(
            isinstance(arguments, list)
            and bool(arguments)
            and all(isinstance(item, str) and item for item in arguments),
            "%s compile arguments are invalid" % label,
        )
        tokens = arguments
    else:
        _require(
            isinstance(command_text, str) and bool(command_text),
            "%s compile command text is missing" % label,
        )
        _require(
            "\x00" not in command_text
            and "\n" not in command_text
            and "\r" not in command_text,
            "%s compile command text uses shell control" % label,
        )
        try:
            tokens = shlex.split(command_text, posix=True)
        except ValueError as exc:
            raise ReleaseError("%s compile command text is malformed" % label) from exc
        _require(
            all(
                not any(character in token for character in ";&|<>`$#")
                for token in tokens
            ),
            "%s compile command text uses shell control" % label,
        )
    _require(
        bool(tokens)
        and all(
            "\x00" not in token
            and not _audit_command_token_uses_response_file(token)
            for token in tokens
        ),
        "%s compile command is empty or uses an unsafe response file" % label,
    )
    return list(tokens)


def _audit_v2_command_executable(command: Any, label: str) -> Path:
    tokens = _audit_v2_command_tokens(command, label)
    executable = Path(tokens[0])
    _require(
        executable.is_absolute(),
        "%s compiler executable must be absolute" % label,
    )
    return executable


def _audit_v2_compilers(path: Path, label: str) -> set[Path]:
    commands = _read_json(path, "%s compile commands" % label)
    _require(
        isinstance(commands, list) and bool(commands),
        "%s compile_commands.json is empty" % label,
    )
    return {
        _audit_v2_command_executable(command, label).absolute()
        for command in commands
    }


def _audit_v2_root_for_relative(path: Path, relative: str, label: str) -> Path:
    relative_path = Path(_safe_relative_path(relative, label))
    parts = relative_path.parts
    _require(
        len(path.parts) > len(parts)
        and tuple(path.parts[-len(parts) :]) == parts,
        "%s does not end in its reviewed relative path" % label,
    )
    return Path(*path.parts[: -len(parts)])


def _audit_v2_derive_toolchain_roots(
    policy: dict[str, Any],
    *,
    compiler_paths: set[Path],
) -> dict[str, Path]:
    records = policy.get("toolchains")
    _require(isinstance(records, list), "toolchains must be an array")
    roots: dict[str, Path] = {}
    consumed: set[Path] = set()
    for raw in records:
        _require(isinstance(raw, dict), "toolchain policy is invalid")
        identifier = _audit_v2_nonempty(raw.get("id"), "toolchain id")
        _require(identifier not in roots, "toolchain policy id is duplicated")
        frontends = _audit_v2_compiler_frontends(
            raw.get("compiler_frontends"),
            "toolchain %s" % identifier,
        )
        frontend_roots: set[Path] = set()
        for frontend in frontends:
            relative = frontend["relative_path"]
            matches: list[tuple[Path, Path]] = []
            for executable in compiler_paths:
                try:
                    root = _audit_v2_root_for_relative(
                        executable,
                        relative,
                        "toolchain %s compiler frontend" % identifier,
                    )
                except ReleaseError:
                    continue
                matches.append((executable, root))
            _require(
                len(matches) == 1,
                "toolchain %s compiler frontend does not derive one root"
                % identifier,
            )
            executable, root = matches[0]
            _require(
                executable not in consumed,
                "toolchain %s compiler frontend is reused" % identifier,
            )
            _audit_no_symlink_components(
                root,
                executable,
                "toolchain %s compiler frontend" % identifier,
            )
            try:
                mode = executable.lstat().st_mode
            except OSError as exc:
                raise ReleaseError(
                    "toolchain %s compiler frontend is missing" % identifier
                ) from exc
            _require(
                stat_module.S_ISREG(mode)
                and not stat_module.S_ISLNK(mode)
                and _sha256_path(executable) == frontend["sha256"],
                "toolchain %s compiler frontend is unsafe" % identifier,
            )
            consumed.add(executable)
            frontend_roots.add(root)
        _require(
            len(frontend_roots) == 1,
            "toolchain %s compiler frontends do not share one root"
            % identifier,
        )
        roots[identifier] = next(iter(frontend_roots))

    _require(
        consumed == compiler_paths,
        "compile commands use an undeclared toolchain frontend",
    )
    return roots


def _audit_v2_source_record(
    path: Path,
    *,
    repo_root: Path,
    build_root: Path,
) -> dict[str, str]:
    resolved = path.resolve()
    try:
        logical = "build/" + resolved.relative_to(
            build_root.resolve()
        ).as_posix()
    except ValueError:
        try:
            logical = resolved.relative_to(repo_root.resolve()).as_posix()
        except ValueError as exc:
            raise ReleaseError(
                "compiled source is outside the repository/build roots: %s" % path
            ) from exc
    return {
        "path": logical,
        "sha256": _sha256_path(path),
    }


def _audit_observe_policy_v2_context_once(
    policy: dict[str, Any],
    *,
    repo_root: Path,
    build_root: Path,
) -> dict[str, Any]:
    """Reconcile exact schema-v2 policy inputs with the linked build."""

    root = Path(repo_root)
    builds = Path(build_root)
    _require(root.is_dir(), "license policy repository root is missing")
    _require(builds.is_dir(), "license audit build root is missing")
    _require(
        isinstance(policy, dict)
        and type(policy.get("schema_version")) is int
        and policy.get("schema_version") == 2,
        "release license policy schema_version must be 2",
    )
    declared_inputs = policy.get("resolved_inputs")
    _require(
        isinstance(declared_inputs, list) and bool(declared_inputs),
        "license policy resolved_inputs must be nonempty",
    )
    retained_source_records = _audit_retained_source_checkouts(
        root,
        builds,
    )
    declared_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = {}
    declared_ids: set[str] = set()
    for raw in declared_inputs:
        _require(isinstance(raw, dict), "resolved input policy is invalid")
        identifier = _audit_v2_nonempty(raw.get("id"), "resolved input id")
        _require(identifier not in declared_ids, "resolved input id is duplicated")
        declared_ids.add(identifier)
        profile_id, role = _audit_v2_identity(
            raw.get("profile_id"),
            raw.get("role"),
            "resolved input %s" % identifier,
        )
        declared_by_identity.setdefault((profile_id, role), []).append(raw)

    role_metadata: dict[tuple[str, str], dict[str, Any]] = {}
    compiler_paths: set[Path] = set()
    manifest_selections: dict[str, dict[str, Path]] = {}
    manifest_evidence: list[dict[str, Any]] = []
    trusted_mpy_cross_sha256 = _audit_rebuild_mpy_cross(
        root,
        source_date_epoch=_audit_candidate_source_date_epoch(root, builds),
    )
    for profile_id, target, idf_target in LICENSE_AUDIT_PROFILES:
        manifest = root / "firmware" / "board_overlays" / target / "manifest.py"
        frozen = builds / target / "frozen_content.c"
        selections, evidence_record = _audit_manifest_evidence_record(
            manifest,
            frozen,
            repo_root=root,
            target=target,
            trusted_mpy_cross_sha256=trusted_mpy_cross_sha256,
        )
        evidence_record["linked_frozen_object"] = _audit_linked_frozen_object(
            repo_root=root,
            build_root=builds,
            target=target,
            frozen_path=frozen,
        )
        manifest_selections[target] = selections
        manifest_evidence.append(evidence_record)
        for role in LICENSE_AUDIT_ROLES:
            role_build, description_path, compile_path, map_path = (
                _audit_v2_role_paths(builds, target, role)
            )
            for label, path in (
                ("project description", description_path),
                ("compile commands", compile_path),
                ("link map", map_path),
            ):
                checked = _audit_path_in_roots(
                    path,
                    relative_to=role_build,
                    roots=(builds,),
                    label="%s/%s %s" % (profile_id, role, label),
                )
                _require(
                    checked.is_file(),
                    "%s/%s %s is missing" % (profile_id, role, label),
                )
            description = _read_json(
                description_path,
                "%s/%s project description" % (profile_id, role),
            )
            _require(
                isinstance(description, dict)
                and description.get("target") == idf_target,
                "%s/%s project description target changed" % (profile_id, role),
            )
            compilers = _audit_v2_compilers(
                compile_path,
                "%s/%s" % (profile_id, role),
            )
            compiler_paths.update(compilers)
            role_metadata[(profile_id, role)] = {
                "target": target,
                "role_build": role_build,
                "description_path": description_path,
                "compile_path": compile_path,
                "map_path": map_path,
                "description": description,
                "compilers": compilers,
            }

    toolchain_contexts = _audit_v2_derive_toolchain_cache_context(
        policy,
        repo_root=root,
        compiler_paths=compiler_paths,
    )
    toolchain_roots = {
        identifier: Path(context["root"])
        for identifier, context in toolchain_contexts.items()
    }
    admitted_roots = tuple(toolchain_roots.values())
    observations: list[dict[str, Any]] = []
    observed_ids: set[str] = set()
    frozen_destination_owners: set[tuple[str, str, str]] = set()
    for identity, metadata in sorted(role_metadata.items()):
        profile_id, role = identity
        target = metadata["target"]
        description = metadata["description"]
        compile_inventory = _audit_compile_sources(
            metadata["compile_path"],
            description=description,
            repo_root=root,
            build_root=builds,
            target=target,
            role=role,
            role_build=metadata["role_build"],
        )
        compile_outputs = compile_inventory["outputs"]
        direct_outputs = _audit_map_direct_outputs(
            metadata["map_path"],
            role_build=metadata["role_build"],
            compile_outputs=compile_outputs,
        )
        linked = _audit_map_archives(
            metadata["map_path"],
            repo_root=root,
            build_root=builds,
            admitted_roots=admitted_roots,
        )
        linked_by_path: dict[Path, Counter[str]] = {}
        representative_paths: dict[Path, Path] = {}
        for archive, member in linked:
            resolved = archive.resolve()
            linked_by_path.setdefault(resolved, Counter())[member] += 1
            representative_paths.setdefault(resolved, archive)
        consumed_archives: set[Path] = set()
        consumed_outputs: set[Path] = set()
        component_info = description.get("build_component_info")
        _require(
            isinstance(component_info, dict) and bool(component_info),
            "%s/%s project description lacks components" % identity,
        )
        ordinary_inventories: dict[
            str,
            tuple[Path, Path, dict[Path, Path]],
        ] = {}
        expected_linked_outputs = set(direct_outputs)
        linked_component_archives: set[Path] = set()
        for component_name, component in component_info.items():
            if (
                not isinstance(component_name, str)
                or not isinstance(component, dict)
                or not isinstance(component.get("file"), str)
                or not component["file"]
            ):
                continue
            component_archive = _audit_path_in_roots(
                component["file"],
                relative_to=metadata["role_build"],
                roots=(builds,),
                label="%s/%s component archive" % identity,
            )
            archive_resolved = component_archive.resolve()
            if archive_resolved not in linked_by_path:
                continue
            _require(
                archive_resolved not in linked_component_archives,
                "%s/%s linked component archive is ambiguous" % identity,
            )
            inventory = _audit_component_output_inventory(
                component=component,
                role_build=metadata["role_build"],
                build_root=builds,
                compile_outputs=compile_outputs,
                label="%s/%s component %s"
                % (profile_id, role, component_name),
            )
            owned_files = compile_inventory["described_by_component"].get(
                component_name,
                set(),
            )
            owned_roots = compile_inventory[
                "described_roots_by_component"
            ].get(component_name, set())
            _require(
                all(
                    source in owned_files
                    or any(source.is_relative_to(root) for root in owned_roots)
                    or (
                        role == "application"
                        and component_name == "main"
                        and source in compile_inventory["pyble_sources"]
                    )
                    for source in inventory[2].values()
                ),
                "%s/%s linked component source ownership changed" % identity,
            )
            selected_output_paths = set(inventory[2])
            _require(
                selected_output_paths.isdisjoint(expected_linked_outputs),
                "%s/%s compile output belongs to multiple linked topologies"
                % identity,
            )
            ordinary_inventories[component_name] = inventory
            expected_linked_outputs.update(selected_output_paths)
            linked_component_archives.add(archive_resolved)
        for raw_input in declared_by_identity.get(identity, []):
            identifier = raw_input["id"]
            kind = raw_input.get("kind")
            common = {
                "id": identifier,
                "profile_id": profile_id,
                "role": role,
                "kind": kind,
            }
            if kind in {
                "generated-component-archive",
                "generated-supplemental-archive",
            }:
                matcher = _audit_v2_generated_matcher(
                    raw_input.get("generated_matcher"),
                    "generated input %s" % identifier,
                )
                component_name = matcher["component"]
                component = component_info.get(component_name)
                _require(
                    isinstance(component, dict),
                    "generated input %s names an unknown component" % identifier,
                )
                nested = matcher.get("nested_archive")
                _require(
                    nested is None or kind == "generated-supplemental-archive",
                    "generated input %s nested matcher is not supplemental"
                    % identifier,
                )
                source_paths: set[Path] = set()
                if nested is None:
                    _require(
                        component_name in ordinary_inventories,
                        "generated input %s is not one linked component topology"
                        % identifier,
                    )
                    archive, _object_directory, selected_outputs = (
                        ordinary_inventories[component_name]
                    )
                    source_paths = set(selected_outputs.values())
                    _require(
                        len(source_paths) == len(selected_outputs),
                        "generated input %s archive source inventory is ambiguous"
                        % identifier,
                    )
                else:
                    _require(
                        component.get("type") == "CONFIG_ONLY"
                        and component.get("file") == ""
                        and component.get("sources") == [],
                        "generated input %s nested owner is not empty CONFIG_ONLY"
                        % identifier,
                    )
                    target_name = nested["target"]
                    archive = _audit_path_in_roots(
                        nested["archive_build_path"],
                        relative_to=metadata["role_build"],
                        roots=(builds,),
                        label="generated input %s nested archive" % identifier,
                    )
                    object_directory = _audit_path_in_roots(
                        nested["object_build_directory"],
                        relative_to=metadata["role_build"],
                        roots=(builds,),
                        label="generated input %s nested object directory"
                        % identifier,
                    )
                    _require(
                        archive.name == "lib%s.a" % target_name
                        and object_directory.name == "%s.dir" % target_name
                        and object_directory.is_dir(),
                        "generated input %s nested target topology changed"
                        % identifier,
                    )
                    _audit_regular_compile_file(
                        archive,
                        "generated input %s nested archive" % identifier,
                    )
                    object_directory = object_directory.resolve()
                    selected_outputs = {
                        output: source
                        for output, source in compile_outputs.items()
                        if output.is_relative_to(object_directory)
                    }
                    _require(
                        bool(selected_outputs),
                        "generated input %s nested object inventory is empty or escaped"
                        % identifier,
                    )
                    owner_dir_raw = component.get("dir")
                    _require(
                        isinstance(owner_dir_raw, str) and bool(owner_dir_raw),
                        "generated input %s nested owner source root is missing"
                        % identifier,
                    )
                    owner_dir = _audit_path_in_roots(
                        owner_dir_raw,
                        relative_to=metadata["role_build"],
                        roots=(root, builds),
                        label="generated input %s nested owner source root"
                        % identifier,
                    ).resolve()
                    source_paths = set(selected_outputs.values())
                    _require(
                        all(source.is_relative_to(owner_dir) for source in source_paths),
                        "generated input %s nested source escapes its owner tree"
                        % identifier,
                    )
                    _require(
                        set(selected_outputs).isdisjoint(expected_linked_outputs),
                        "generated input %s nested output is multiply linked"
                        % identifier,
                    )
                    expected_linked_outputs.update(selected_outputs)
                archive_resolved = archive.resolve()
                _require(
                    archive_resolved in linked_by_path
                    and archive_resolved not in consumed_archives,
                    "generated input %s is not one unique linked archive"
                    % identifier,
                )
                archive_members = _audit_ar_members(archive)
                _require(
                    Counter(output.name for output in selected_outputs)
                    == archive_members,
                    "generated input %s compile/archive members disagree"
                    % identifier,
                )
                source_records = [
                    _audit_v2_source_record(
                        source,
                        repo_root=root,
                        build_root=builds,
                    )
                    for source in sorted(source_paths)
                ]
                _require(
                    set(selected_outputs).isdisjoint(consumed_outputs),
                    "generated input %s reuses a compile output" % identifier,
                )
                consumed_archives.add(archive_resolved)
                consumed_outputs.update(selected_outputs)
                generated_binding = {
                    "component": component_name,
                    "project_description_sha256": _sha256_path(
                        metadata["description_path"]
                    ),
                    "compile_commands_sha256": _sha256_path(
                        metadata["compile_path"]
                    ),
                    "linker_map_sha256": _sha256_path(metadata["map_path"]),
                    "sources": sorted(
                        source_records,
                        key=lambda item: item["path"],
                    ),
                    "members": sorted(archive_members.elements()),
                }
                if component_name == "main":
                    _require(
                        nested is None,
                        "generated main binding cannot use a nested archive",
                    )
                    app_elf, link_path, link_direct_outputs = (
                        _audit_link_command_direct_outputs(
                            role_build=metadata["role_build"],
                            description=description,
                            compile_outputs=compile_outputs,
                        )
                    )
                    _require(
                        link_direct_outputs == direct_outputs,
                        "linker map and linker command direct objects disagree",
                    )
                    metadata_paths = compile_inventory[
                        "metadata_by_component"
                    ].get("main", set())
                    _require(
                        (
                            role == "application"
                            and metadata_paths
                            == {
                                (
                                    metadata["role_build"]
                                    / "genhdr"
                                    / name
                                ).resolve()
                                for name in _AUDIT_MAIN_METADATA_HEADERS
                            }
                        )
                        or (role == "bootloader" and not metadata_paths),
                        "generated main metadata inventory is invalid",
                    )
                    direct_records = _audit_direct_object_records(
                        direct_outputs=direct_outputs,
                        compile_inventory=compile_inventory,
                        app_elf=app_elf,
                        role=role,
                        role_build=metadata["role_build"],
                        repo_root=root,
                        build_root=builds,
                    )
                    _require(
                        direct_outputs.isdisjoint(consumed_outputs),
                        "generated main direct output is multiply consumed",
                    )
                    consumed_outputs.update(direct_outputs)
                    generated_binding.update(
                        {
                            "linker_command_sha256": _sha256_path(link_path),
                            "metadata_inputs": sorted(
                                (
                                    _audit_v2_source_record(
                                        path,
                                        repo_root=root,
                                        build_root=builds,
                                    )
                                    for path in metadata_paths
                                ),
                                key=lambda item: item["path"],
                            ),
                            "direct_objects": direct_records,
                        }
                    )
                if nested is not None:
                    generated_binding["nested_archive"] = copy.deepcopy(nested)
                observation = {
                    **common,
                    "observed_path": str(archive_resolved),
                    "sha256": _sha256_path(archive),
                    "generated_binding": generated_binding,
                }
            elif kind == "opaque-archive":
                reviewed_relative = raw_input.get("reviewed_source_path")
                digest = raw_input.get("sha256")
                _audit_v2_hash(digest, "opaque input %s digest" % identifier)
                reviewed = _audit_repo_file(
                    root,
                    reviewed_relative,
                    "opaque input %s reviewed source" % identifier,
                )
                _require(
                    _sha256_path(reviewed) == digest,
                    "opaque input %s reviewed source changed" % identifier,
                )
                matches = [
                    path
                    for path in linked_by_path
                    if path not in consumed_archives
                    and _sha256_path(representative_paths[path]) == digest
                ]
                _require(
                    len(matches) == 1,
                    "opaque input %s is not one exact linked archive" % identifier,
                )
                archive_resolved = matches[0]
                consumed_archives.add(archive_resolved)
                observation = {
                    **common,
                    "observed_path": str(archive_resolved),
                    "sha256": digest,
                    "reviewed_source_path": reviewed_relative,
                }
            elif kind == "toolchain-archive":
                toolchain_id = raw_input.get("toolchain_id")
                relative = raw_input.get("relative_path")
                root_path = toolchain_roots.get(toolchain_id)
                _require(
                    root_path is not None and isinstance(relative, str),
                    "toolchain input %s lacks a derived root" % identifier,
                )
                archive = root_path / _safe_relative_path(
                    relative,
                    "toolchain input %s archive" % identifier,
                )
                _audit_no_symlink_components(
                    root_path,
                    archive,
                    "toolchain input %s archive" % identifier,
                )
                archive_resolved = archive.resolve()
                _require(
                    archive_resolved in linked_by_path
                    and archive_resolved not in consumed_archives,
                    "toolchain input %s is not one exact linked archive" % identifier,
                )
                toolchain_record = next(
                    item
                    for item in policy["toolchains"]
                    if item["id"] == toolchain_id
                )
                compiler_frontends = _audit_v2_compiler_frontends(
                    toolchain_record.get("compiler_frontends"),
                    "toolchain %s" % toolchain_id,
                )
                reviewed_frontend_paths = {
                    (root_path / frontend["relative_path"]).resolve()
                    for frontend in compiler_frontends
                }
                observed_role_frontends = sorted(
                    compiler.resolve()
                    for compiler in metadata["compilers"]
                    if compiler.resolve() in reviewed_frontend_paths
                )
                _require(
                    bool(observed_role_frontends),
                    "toolchain input %s has no compile-command frontend"
                    % identifier,
                )
                consumed_archives.add(archive_resolved)
                observation = {
                    **common,
                    "observed_path": str(archive.resolve()),
                    "sha256": _sha256_path(archive),
                    "toolchain_id": toolchain_id,
                    "relative_path": relative,
                    "compiler_paths": [
                        str(compiler) for compiler in observed_role_frontends
                    ],
                }
            elif kind == "frozen-source-tree":
                _require(
                    role == "application",
                    "frozen input %s is not an application input" % identifier,
                )
                source_relative = raw_input.get("path")
                source_root = root / _safe_relative_path(
                    source_relative,
                    "frozen input %s source tree" % identifier,
                )
                _audit_no_symlink_components(
                    root,
                    source_root,
                    "frozen input %s source tree" % identifier,
                )
                destinations = raw_input.get("frozen_destinations")
                _require(
                    isinstance(destinations, list)
                    and bool(destinations)
                    and all(
                        isinstance(destination, str)
                        and _safe_relative_path(
                            destination,
                            "frozen input %s destination" % identifier,
                        )
                        == destination
                        for destination in destinations
                    )
                    and len(destinations) == len(set(destinations)),
                    "frozen input %s destinations are invalid" % identifier,
                )
                destination_owners = {
                    (profile_id, role, destination)
                    for destination in destinations
                }
                _require(
                    frozen_destination_owners.isdisjoint(destination_owners),
                    "frozen input %s reuses an owned destination" % identifier,
                )
                selections = manifest_selections[target]
                _require(
                    all(
                        destination in selections
                        and selections[destination]
                        .resolve()
                        .is_relative_to(source_root.resolve())
                        for destination in destinations
                    ),
                    "frozen input %s is not selected by the literal manifest"
                    % identifier,
                )
                frozen_destination_owners.update(destination_owners)
                observation = {
                    **common,
                    "observed_path": str(source_root.resolve()),
                    "sha256": _audit_sha256_tree(source_root),
                    "frozen_destinations": list(destinations),
                }
            else:
                raise ReleaseError(
                    "resolved input %s has an unsupported kind" % identifier
                )
            _require(
                identifier not in observed_ids,
                "observed redistributed input id is duplicated",
            )
            observed_ids.add(identifier)
            observations.append(observation)
        _require(
            consumed_archives == set(linked_by_path),
            "%s/%s linked archive set is not exactly covered by policy" % identity,
        )
        _require(
            consumed_outputs == expected_linked_outputs,
            "%s/%s linked compile outputs are not exactly covered by generated inputs"
            % identity,
        )

    _require(
        observed_ids == declared_ids,
        "resolved input observations do not exactly cover policy",
    )
    return {
        "observed_inputs": sorted(observations, key=lambda item: item["id"]),
        "toolchain_roots": copy.deepcopy(toolchain_contexts),
        "role_metadata": role_metadata,
        "manifest_selections": manifest_selections,
        "manifest_evidence": sorted(
            manifest_evidence,
            key=lambda item: item["target"],
        ),
        "retained_source_records": retained_source_records,
    }


def _audit_observe_policy_v2_context(
    policy: dict[str, Any],
    *,
    repo_root: Path,
    build_root: Path,
) -> dict[str, Any]:
    """Public observer seam retained for focused tests and callers."""

    return _audit_observe_policy_v2_context_once(
        policy,
        repo_root=repo_root,
        build_root=build_root,
    )


def _audit_observe_policy_v2_inputs(
    policy: dict[str, Any],
    *,
    repo_root: Path,
    build_root: Path,
) -> list[dict[str, Any]]:
    """Return exact redistributed-input observations for schema-v2 review."""

    return _audit_observe_policy_v2_context(
        policy,
        repo_root=repo_root,
        build_root=build_root,
    )["observed_inputs"]


def _audit_policy_by_archive_digest(
    entries: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        if entry["match"]["kind"] == "archive":
            result.setdefault(entry["match"]["sha256"], []).append(entry)
    return result


def _audit_inventory_role(
    *,
    profile_id: str,
    target: str,
    idf_target: str,
    role: str,
    repo_root: Path,
    build_root: Path,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    target_build = build_root / target
    if role == "application":
        role_build = target_build
        description_path = target_build / "project_description.json"
        map_path = target_build / "micropython.map"
        compile_path = target_build / "compile_commands.json"
    else:
        role_build = target_build / "bootloader"
        description_path = role_build / "project_description.json"
        map_path = role_build / "bootloader.map"
        compile_path = role_build / "compile_commands.json"
    for label, path in (
        ("project description", description_path),
        ("linked map", map_path),
        ("compile commands", compile_path),
    ):
        _audit_path_in_roots(
            path,
            relative_to=role_build,
            roots=(build_root,),
            label="%s %s" % (profile_id, label),
        )
        _require(path.is_file(), "%s %s is missing" % (profile_id, label))

    description = _read_json(description_path, "%s/%s description" % (profile_id, role))
    _require(isinstance(description, dict), "project description is not an object")
    _require(
        description.get("target") == idf_target,
        "%s/%s description target changed" % (profile_id, role),
    )
    compile_inventory = _audit_compile_sources(
        compile_path,
        description=description,
        repo_root=repo_root,
        build_root=build_root,
        target=target,
        role=role,
        role_build=role_build,
    )
    sources = set(compile_inventory["sources"])
    for metadata_paths in compile_inventory["metadata_by_component"].values():
        sources.update(metadata_paths)
    linked = _audit_map_archives(
        map_path,
        repo_root=repo_root,
        build_root=build_root,
    )

    by_digest = _audit_policy_by_archive_digest(entries)
    matched_ids: set[str] = set()
    archive_hashes: dict[str, str] = {}
    archive_paths: dict[str, Path] = {}
    for archive, _member in linked:
        digest = _sha256_path(archive)
        matches = by_digest.get(digest, [])
        _require(
            len(matches) == 1,
            "linked archive is unmapped or ambiguous in license policy",
        )
        entry = matches[0]
        _require(
            {"profile_id": profile_id, "role": role} in entry["applicability"],
            "linked archive policy omits its profile/role",
        )
        matched_ids.add(entry["id"])
        if archive.resolve().is_relative_to(build_root.resolve()):
            logical = archive.resolve().relative_to(build_root.resolve()).as_posix()
        else:
            logical = (
                "repo/" + archive.resolve().relative_to(repo_root.resolve()).as_posix()
            )
        archive_hashes[logical] = digest
        archive_paths[logical] = archive

    applicable_ids = {
        entry["id"]
        for entry in entries
        if {"profile_id": profile_id, "role": role} in entry["applicability"]
    }
    return {
        "description_path": description_path,
        "description": description,
        "map_path": map_path,
        "compile_path": compile_path,
        "source_paths": tuple(sorted(sources)),
        "archive_hashes": archive_hashes,
        "archive_paths": archive_paths,
        "matched_archive_ids": matched_ids,
        "applicable_ids": applicable_ids,
    }


def _audit_validate_spdx_document(
    document: Any,
    *,
    profile_id: str,
    role: str,
    entries: list[dict[str, Any]],
    approved_license_refs: set[str],
    source_format: str = "json",
    expected_document_name: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    _require(isinstance(document, dict), "SBOM output must be a JSON object")
    _require(
        source_format in ("json", "tag-value"),
        "SBOM source format is unsupported",
    )
    document = copy.deepcopy(document)
    expected_version = "SPDX-2.2" if source_format == "tag-value" else "SPDX-2.3"
    _require(
        document.get("spdxVersion") == expected_version,
        "SBOM SPDX version does not match its source format",
    )
    _require(document.get("dataLicense") == "CC0-1.0", "SPDX data license changed")
    _require(document.get("SPDXID") == "SPDXRef-DOCUMENT", "SPDX document ID changed")
    name = document.get("name")
    if source_format == "tag-value":
        _require(
            isinstance(name, str)
            and bool(name)
            and (
                (
                    isinstance(expected_document_name, str)
                    and name == expected_document_name
                )
                or (profile_id in name and role in name)
            ),
            "SPDX document identity does not match its requested build",
        )
    else:
        _require(
            isinstance(name, str) and profile_id in name and role in name,
            "SPDX document identity does not match its requested profile/role",
        )
    namespace = document.get("documentNamespace")
    if source_format == "tag-value":
        _require(
            isinstance(namespace, str)
            and (
                namespace.startswith("http://spdx.org/spdxdocs/")
                or namespace.startswith("https://")
                or namespace.startswith("urn:")
            ),
            "SPDX document namespace is invalid",
        )
    else:
        _require(
            isinstance(namespace, str)
            and (namespace.startswith("https://") or namespace.startswith("urn:")),
            "SPDX document namespace is invalid",
        )
    creation = document.get("creationInfo")
    _require(isinstance(creation, dict), "SPDX creationInfo is missing")
    creators = creation.get("creators")
    _require(
        isinstance(creators, list)
        and creators
        and all(isinstance(creator, str) and creator for creator in creators)
        and len(creators) == len(set(creators)),
        "SPDX creators are missing, duplicated, or invalid",
    )
    expected_creator = (
        "Tool: ESP-IDF SBOM builder"
        if source_format == "tag-value"
        else "Tool: esp-idf-sbom-1.2.0"
    )
    _require(
        expected_creator in creators,
        "SPDX creator does not identify the pinned tool",
    )
    _require(
        re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
            str(creation.get("created", "")),
        )
        is not None,
        "SPDX creation timestamp is invalid",
    )

    packages = document.get("packages")
    _require(isinstance(packages, list) and packages, "SPDX contains no packages")
    applicable = [
        entry
        for entry in entries
        if {"profile_id": profile_id, "role": role} in entry["applicability"]
    ]
    expected: dict[str, dict[str, Any]] = {}
    for entry in applicable:
        package_name = entry["dependency"]["name"]
        _require(
            package_name not in expected,
            "reviewed policy has an ambiguous package identity",
        )
        expected[package_name] = entry
    _require(len(expected) == len(packages), "SPDX and policy package sets differ")
    package_ids: set[str] = set()
    seen_names: set[str] = set()
    referenced_refs: set[str] = set()
    refs_by_entry: dict[str, set[str]] = {}
    id_remap: dict[str, str] = {}
    for package in packages:
        _require(isinstance(package, dict), "SPDX package is not an object")
        package_id = package.get("SPDXID")
        _require(
            isinstance(package_id, str)
            and _AUDIT_SPDX_ELEMENT_RE.fullmatch(package_id) is not None
            and not package_id.startswith("DocumentRef-")
            and package_id not in package_ids,
            "SPDX package ID is invalid or duplicated",
        )
        package_ids.add(package_id)
        package_name = package.get("name")
        _require(
            isinstance(package_name, str)
            and package_name in expected
            and package_name not in seen_names,
            "SPDX contains an unmapped or duplicate package",
        )
        seen_names.add(package_name)
        entry = expected[package_name]
        dependency = entry["dependency"]
        _require(
            package.get("filesAnalyzed") is False, "SPDX filesAnalyzed must be false"
        )
        _require(
            package.get("versionInfo") == dependency["version_ref"]
            and package.get("downloadLocation") == dependency["source_url"]
            and package.get("copyrightText") == dependency["copyright"],
            "SPDX package provenance disagrees with reviewed policy",
        )
        declared = package.get("licenseDeclared")
        concluded = package.get("licenseConcluded")
        policy_expression = entry["spdx_expression"]
        if (
            source_format == "tag-value"
            and declared
            in (
                "NOASSERTION",
                "NONE",
            )
            and concluded in ("NOASSERTION", "NONE")
        ):
            package["licenseDeclared"] = policy_expression
            package["licenseConcluded"] = policy_expression
            package["attributionTexts"] = [
                "License resolved by reviewed hash-bound PyBLE policy entry %s."
                % entry["id"]
            ]
            declared = policy_expression
            concluded = policy_expression
        _require(
            declared == policy_expression and concluded == declared,
            "SPDX package license disagrees with reviewed policy",
        )
        identifiers = _audit_parse_spdx(declared, approved_license_refs)
        entry_refs = {
            identifier for identifier in identifiers if "LicenseRef-" in identifier
        }
        referenced_refs.update(entry_refs)
        refs_by_entry[entry["id"]] = entry_refs
        if source_format == "json":
            _require(
                re.fullmatch(r"SPDXRef-Package-[A-Za-z0-9.-]+", package_id) is not None,
                "normalized SPDX package ID is invalid",
            )
            canonical_id = package_id
        elif package_id.startswith("SPDXRef-Package-"):
            canonical_id = package_id
        else:
            suffix = re.sub(r"[^A-Za-z0-9.-]", "-", entry["id"]).strip(".-")
            _require(suffix != "", "policy entry cannot form a stable SPDX package ID")
            canonical_id = "SPDXRef-Package-" + suffix
        _require(
            canonical_id not in id_remap.values(),
            "SPDX package IDs collide after normalization",
        )
        id_remap[package_id] = canonical_id
        package["SPDXID"] = canonical_id
    _require(seen_names == set(expected), "SPDX omits a reviewed package")

    files = document.get("files", [])
    _require(
        isinstance(files, list) and not files,
        "linked-only SPDX audit unexpectedly contains file records",
    )
    relationships = document.get("relationships")
    _require(
        isinstance(relationships, list) and relationships,
        "SPDX relationships are missing",
    )
    known_elements = {"SPDXRef-DOCUMENT"} | package_ids
    relationship_keys: set[tuple[str, str, str]] = set()
    described: set[str] = set()
    dependency_graph: dict[str, set[str]] = {
        package_id: set() for package_id in package_ids
    }
    normalized_relationships: list[dict[str, Any]] = []
    for relation in relationships:
        _require(isinstance(relation, dict), "SPDX relationship is not an object")
        source = relation.get("spdxElementId")
        relationship_type = relation.get("relationshipType")
        related = relation.get("relatedSpdxElement")
        _require(
            isinstance(source, str)
            and isinstance(relationship_type, str)
            and isinstance(related, str)
            and source in known_elements
            and related in known_elements,
            "SPDX relationship names an unknown element",
        )
        identity = (source, relationship_type, related)
        _require(identity not in relationship_keys, "SPDX relationship is duplicated")
        relationship_keys.add(identity)
        if source == "SPDXRef-DOCUMENT" and relationship_type == "DESCRIBES":
            _require(
                related in package_ids,
                "SPDX document DESCRIBES a non-package element",
            )
            described.add(related)
        if relationship_type == "DEPENDS_ON" and source in package_ids:
            _require(
                related in package_ids,
                "SPDX package dependency names a non-package element",
            )
            dependency_graph[source].add(related)
        normalized = copy.deepcopy(relation)
        normalized["spdxElementId"] = id_remap.get(source, source)
        normalized["relatedSpdxElement"] = id_remap.get(related, related)
        normalized_relationships.append(normalized)
    _require(described, "SPDX document describes no package")
    reachable = set(described)
    pending = list(described)
    while pending:
        source = pending.pop()
        for dependency in dependency_graph[source]:
            if dependency not in reachable:
                reachable.add(dependency)
                pending.append(dependency)
    _require(
        reachable == package_ids,
        "SPDX package relationship graph is incomplete",
    )
    for canonical_id in sorted(id_remap.values()):
        relationship = {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": canonical_id,
        }
        identity = (
            relationship["spdxElementId"],
            relationship["relationshipType"],
            relationship["relatedSpdxElement"],
        )
        if identity not in {
            (
                item["spdxElementId"],
                item["relationshipType"],
                item["relatedSpdxElement"],
            )
            for item in normalized_relationships
        }:
            normalized_relationships.append(relationship)
    document["relationships"] = normalized_relationships

    licensing_infos = document.get("hasExtractedLicensingInfos", [])
    _require(
        isinstance(licensing_infos, list),
        "SPDX extracted licensing information is invalid",
    )
    if source_format == "tag-value" and referenced_refs:
        _require(
            repo_root is not None,
            "policy-resolved LicenseRef requires the reviewed repository root",
        )
        extracted_by_id: dict[str, dict[str, str]] = {}
        extracted_hashes: dict[str, str] = {}
        for entry in applicable:
            for identifier in refs_by_entry.get(entry["id"], set()):
                license_texts = entry["license_texts"]
                _require(
                    len(license_texts) == 1,
                    "policy LicenseRef must identify one exact complete text",
                )
                record = license_texts[0]
                path = _audit_repo_file(
                    repo_root,
                    record["path"],
                    "%s extracted LicenseRef text" % entry["id"],
                )
                try:
                    extracted_text = path.read_text(encoding="utf-8", errors="strict")
                except (OSError, UnicodeError) as exc:
                    raise ReleaseError(
                        "%s extracted LicenseRef text is unreadable" % entry["id"]
                    ) from exc
                digest = _sha256_bytes(extracted_text.encode("utf-8"))
                _require(
                    digest == record["sha256"],
                    "%s extracted LicenseRef text changed" % entry["id"],
                )
                if identifier in extracted_hashes:
                    _require(
                        extracted_hashes[identifier] == digest,
                        "approved LicenseRef resolves to ambiguous complete texts",
                    )
                extracted_hashes[identifier] = digest
                extracted_by_id[identifier] = {
                    "licenseId": identifier,
                    "name": identifier,
                    "extractedText": extracted_text,
                }
        _require(
            set(extracted_by_id) == referenced_refs,
            "policy did not resolve every approved LicenseRef",
        )
        licensing_infos = [
            extracted_by_id[identifier] for identifier in sorted(extracted_by_id)
        ]
        document["hasExtractedLicensingInfos"] = licensing_infos
    extracted_ids: set[str] = set()
    for info in licensing_infos:
        _require(
            isinstance(info, dict)
            and isinstance(info.get("licenseId"), str)
            and isinstance(info.get("extractedText"), str)
            and bool(info["extractedText"])
            and info["licenseId"] not in extracted_ids,
            "SPDX extracted licensing information is incomplete or duplicated",
        )
        extracted_ids.add(info["licenseId"])
    _require(
        referenced_refs <= extracted_ids,
        "SPDX omits extracted text for an approved LicenseRef",
    )
    if source_format == "tag-value":
        document["spdxVersion"] = "SPDX-2.3"
        document["name"] = "PyBLE license review %s/%s" % (profile_id, role)
        document["creationInfo"]["creators"] = [
            creator for creator in creators if creator != expected_creator
        ] + ["Tool: esp-idf-sbom-1.2.0"]
    return document


def _audit_normalize_value(
    value: Any,
    *,
    replacements: tuple[tuple[str, str], ...],
) -> Any:
    if isinstance(value, dict):
        return {
            key: _audit_normalize_value(child, replacements=replacements)
            for key, child in value.items()
        }
    if isinstance(value, list):
        normalized = [
            _audit_normalize_value(child, replacements=replacements) for child in value
        ]
        if all(isinstance(child, dict) for child in normalized):
            normalized.sort(
                key=lambda child: json.dumps(
                    child,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        return normalized
    if isinstance(value, str):
        result = value
        for original, replacement in replacements:
            result = result.replace(original, replacement)
        return result
    return value


def _audit_normalize_spdx(
    document: dict[str, Any],
    *,
    profile_id: str,
    role: str,
    repo_root: Path,
    build_root: Path,
) -> dict[str, Any]:
    replacements = (
        (str(repo_root.absolute().parent), "${REVIEW_ROOT}"),
        (str(repo_root.resolve().parent), "${REVIEW_ROOT}"),
        (str(repo_root.absolute()), "${REPO_ROOT}"),
        (str(repo_root.resolve()), "${REPO_ROOT}"),
        (str(build_root.absolute()), "${BUILD_ROOT}"),
        (str(build_root.resolve()), "${BUILD_ROOT}"),
    )
    normalized = _audit_normalize_value(document, replacements=replacements)
    normalized["documentNamespace"] = "https://spdx.pyble.dev/review/%s/%s" % (
        profile_id,
        role,
    )
    normalized["creationInfo"]["created"] = LICENSE_AUDIT_TIMESTAMP
    return normalized


def _audit_notice(
    entries: list[dict[str, Any]],
    *,
    repo_root: Path,
    frozen_names: set[str],
) -> str:
    lines = [
        "PyBLE mechanically generated complete firmware dependency notices",
        "",
        "Frozen Python inputs: flashbdev.py, inisetup.py, asyncio, NeoPixel.",
        "Generated inventory: %s." % ", ".join(sorted(frozen_names)),
        "",
    ]
    unique_license_texts: dict[str, tuple[str, str]] = {}
    for entry in sorted(entries, key=lambda item: item["dependency"]["name"]):
        dependency = entry["dependency"]
        lines.extend(
            [
                "=" * 78,
                "Name: %s" % dependency["name"],
                "Version/ref: %s" % dependency["version_ref"],
                "Source URL: %s" % dependency["source_url"],
                "SPDX identifier: %s" % entry["spdx_expression"],
                "Copyright: %s" % dependency["copyright"],
                "Applies to: %s"
                % ", ".join(
                    "%s/%s" % (item["profile_id"], item["role"])
                    for item in sorted(
                        entry["applicability"],
                        key=lambda item: (item["profile_id"], item["role"]),
                    )
                ),
            ]
        )
        notice = entry["notice"]
        if notice["required"]:
            notice_text = _audit_repo_file(
                repo_root,
                notice["path"],
                "%s required NOTICE" % entry["id"],
            ).read_text(encoding="utf-8", errors="strict")
            lines.extend(["Required notice text:", notice_text.rstrip()])
        else:
            lines.append("Required notice text: none.")
        lines.append(
            "Complete license text SHA-256: %s"
            % ", ".join(record["sha256"] for record in entry["license_texts"])
        )
        lines.append("")
        for record in entry["license_texts"]:
            text = _audit_repo_file(
                repo_root,
                record["path"],
                "%s complete license text" % entry["id"],
            ).read_text(encoding="utf-8", errors="strict")
            unique_license_texts.setdefault(
                record["sha256"],
                (record["path"], text.rstrip()),
            )

    lines.extend(["=" * 78, "Complete reviewed license texts", ""])
    for digest in sorted(unique_license_texts):
        path, text = unique_license_texts[digest]
        lines.extend(
            [
                "-" * 78,
                "Reviewed file: %s" % path,
                "SHA-256: %s" % digest,
                "",
                text,
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _audit_stable_input_hash(
    path: Path,
    *,
    repo_root: Path,
    build_root: Path,
) -> str:
    """Hash exact bytes after deterministic absolute-root tokenization."""

    try:
        mode = path.lstat().st_mode
        value = path.read_bytes()
    except OSError as exc:
        raise ReleaseError("audited input is missing or unreadable: %s" % path) from exc
    _require(
        stat_module.S_ISREG(mode) and not stat_module.S_ISLNK(mode),
        "audited input must be a regular non-symlink file: %s" % path,
    )
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return _sha256_bytes(value)
    replacements = (
        (str(repo_root.absolute().parent), "${REVIEW_ROOT}"),
        (str(repo_root.resolve().parent), "${REVIEW_ROOT}"),
        (str(repo_root.absolute()), "${REPO_ROOT}"),
        (str(repo_root.resolve()), "${REPO_ROOT}"),
        (str(build_root.absolute()), "${BUILD_ROOT}"),
        (str(build_root.resolve()), "${BUILD_ROOT}"),
    )
    for original, replacement in replacements:
        text = text.replace(original, replacement)
    return _sha256_bytes(text.encode("utf-8"))


def _audit_logical_path(path: Path, repo_root: Path, build_root: Path) -> str:
    resolved = path.resolve()
    for prefix, root in (("build", build_root), ("repo", repo_root)):
        try:
            relative = resolved.relative_to(root.resolve())
        except ValueError:
            continue
        return "%s/%s" % (prefix, relative.as_posix())
    raise ReleaseError("audited input is outside the repository/build roots: %s" % path)


def _audit_input_hashes(
    *,
    repo_root: Path,
    build_root: Path,
    lock: dict[str, Any],
    entries: list[dict[str, Any]],
    inventories: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, str]:
    values = {
        "firmware/release-tools.lock": _audit_stable_input_hash(
            lock["_path"],
            repo_root=repo_root,
            build_root=build_root,
        ),
        lock["inputs"]["excluded_cves_path"]: _audit_stable_input_hash(
            _audit_repo_file(
                repo_root,
                lock["inputs"]["excluded_cves_path"],
                "excluded CVE input",
            ),
            repo_root=repo_root,
            build_root=build_root,
        ),
        lock["inputs"]["license_policy_path"]: _audit_stable_input_hash(
            _audit_repo_file(
                repo_root,
                lock["inputs"]["license_policy_path"],
                "license policy input",
            ),
            repo_root=repo_root,
            build_root=build_root,
        ),
    }
    for entry in entries:
        identifier = entry["id"]
        for index, record in enumerate(entry["license_texts"]):
            path = _audit_repo_file(
                repo_root,
                record["path"],
                "%s complete license text" % identifier,
            )
            values["policy/%s/license/%d/%s" % (identifier, index, record["path"])] = (
                _audit_stable_input_hash(
                    path,
                    repo_root=repo_root,
                    build_root=build_root,
                )
            )
        notice = entry["notice"]
        if notice["required"]:
            path = _audit_repo_file(
                repo_root,
                notice["path"],
                "%s required NOTICE" % identifier,
            )
            values["policy/%s/notice/%s" % (identifier, notice["path"])] = (
                _audit_stable_input_hash(
                    path,
                    repo_root=repo_root,
                    build_root=build_root,
                )
            )
    for profile_id, target, _idf_target in LICENSE_AUDIT_PROFILES:
        manifest = repo_root / "firmware" / "board_overlays" / target / "manifest.py"
        frozen = build_root / target / "frozen_content.c"
        values["repo/firmware/board_overlays/%s/manifest.py" % target] = (
            _audit_stable_input_hash(
                manifest,
                repo_root=repo_root,
                build_root=build_root,
            )
        )
        values["build/%s/frozen_content.c" % target] = _audit_stable_input_hash(
            frozen,
            repo_root=repo_root,
            build_root=build_root,
        )
        target_build = build_root / target
        for relative in RELEASE_BUILD_INPUTS:
            release_input = target_build / relative
            values["build/%s/release/%s" % (target, relative)] = (
                _audit_stable_input_hash(
                    release_input,
                    repo_root=repo_root,
                    build_root=build_root,
                )
            )
        for role in LICENSE_AUDIT_ROLES:
            inventory = inventories[(profile_id, role)]
            prefix = "build/%s/%s" % (target, role)
            values["%s/project_description.json" % prefix] = _audit_stable_input_hash(
                inventory["description_path"],
                repo_root=repo_root,
                build_root=build_root,
            )
            values["%s/link.map" % prefix] = _audit_stable_input_hash(
                inventory["map_path"],
                repo_root=repo_root,
                build_root=build_root,
            )
            values["%s/compile_commands.json" % prefix] = _audit_stable_input_hash(
                inventory["compile_path"],
                repo_root=repo_root,
                build_root=build_root,
            )
            for source_path in inventory["source_paths"]:
                logical = _audit_logical_path(source_path, repo_root, build_root)
                values["%s/source/%s" % (prefix, logical)] = _audit_stable_input_hash(
                    source_path,
                    repo_root=repo_root,
                    build_root=build_root,
                )
            for relative, archive_path in inventory["archive_paths"].items():
                values["%s/archive/%s" % (prefix, relative)] = _audit_stable_input_hash(
                    archive_path,
                    repo_root=repo_root,
                    build_root=build_root,
                )
    return dict(sorted(values.items()))


def _audit_exact_executed_artifacts(
    value: Any,
    expected: dict[str, str],
) -> dict[str, str]:
    _require(isinstance(value, dict), "executed SBOM artifact receipt is invalid")
    _require(
        len(value) == len(expected),
        "executed SBOM artifact receipt has unexpected entries",
    )
    normalized: dict[str, str] = {}
    for raw_name, raw_digest in value.items():
        _require(
            isinstance(raw_name, str)
            and isinstance(raw_digest, str)
            and SHA256_RE.fullmatch(raw_digest) is not None,
            "executed SBOM artifact receipt contains invalid values",
        )
        name = _audit_canonical_package_name(raw_name)
        _require(
            name not in normalized,
            "executed SBOM artifact receipt has a canonical-name collision",
        )
        normalized[name] = raw_digest
    _require(
        normalized == expected,
        "executed SBOM artifacts do not exactly match the lock",
    )
    return dict(sorted(normalized.items()))


def _audit_validate_execution_identity(
    value: Any,
    *,
    artifact_hashes: dict[str, str],
) -> dict[str, Any]:
    identity = _exact_keys(
        value,
        {"runner", "python", "isolation", "artifacts"},
        "SBOM execution identity",
    )
    _require(
        isinstance(identity["runner"], str) and bool(identity["runner"]),
        "SBOM execution runner identity is missing",
    )
    python_identity = identity["python"]
    _require(
        isinstance(python_identity, dict)
        and {"implementation", "version"} <= set(python_identity)
        and set(python_identity)
        <= {"implementation", "version", "executable", "executable_sha256"},
        "SBOM Python execution identity is invalid",
    )
    _require(
        all(
            isinstance(python_identity[key], str) and bool(python_identity[key])
            for key in ("implementation", "version")
        ),
        "SBOM Python execution identity is incomplete",
    )
    if "executable_sha256" in python_identity:
        _require(
            isinstance(python_identity["executable_sha256"], str)
            and SHA256_RE.fullmatch(python_identity["executable_sha256"]) is not None,
            "SBOM Python executable digest is invalid",
        )

    isolation = identity["isolation"]
    _require(
        isinstance(isolation, dict)
        and {"kind", "policy_sha256"} <= set(isolation)
        and set(isolation)
        <= {"kind", "policy_sha256", "executable", "executable_sha256"},
        "SBOM network-isolation identity is invalid",
    )
    _require(
        isinstance(isolation["kind"], str)
        and bool(isolation["kind"])
        and isinstance(isolation["policy_sha256"], str)
        and SHA256_RE.fullmatch(isolation["policy_sha256"]) is not None,
        "SBOM network-isolation identity is incomplete",
    )
    if "executable_sha256" in isolation:
        _require(
            isinstance(isolation["executable_sha256"], str)
            and SHA256_RE.fullmatch(isolation["executable_sha256"]) is not None,
            "SBOM isolation executable digest is invalid",
        )

    artifacts = identity["artifacts"]
    _require(
        isinstance(artifacts, list) and len(artifacts) == len(artifact_hashes),
        "SBOM execution identity has an incomplete artifact closure",
    )
    received: dict[str, str] = {}
    for record in artifacts:
        record = _exact_keys(
            record,
            {"name", "version", "filename", "sha256"},
            "SBOM execution artifact identity",
        )
        _require(
            all(
                isinstance(record[key], str) and bool(record[key])
                for key in ("name", "version", "filename", "sha256")
            )
            and SHA256_RE.fullmatch(record["sha256"]) is not None,
            "SBOM execution artifact identity is invalid",
        )
        name = _audit_canonical_package_name(record["name"])
        _require(
            name not in received,
            "SBOM execution identity has a canonical-name collision",
        )
        received[name] = record["sha256"]
    _require(
        received == artifact_hashes,
        "SBOM execution identity differs from the locked closure",
    )
    return copy.deepcopy(identity)


def _audit_write_evidence(
    evidence_dir: Path,
    *,
    documents: dict[tuple[str, str], dict[str, Any]],
    raw_documents: dict[tuple[str, str], tuple[str, bytes]],
    notice: str,
    input_hashes: dict[str, str],
    artifact_hashes: dict[str, str],
    execution_identity: dict[str, Any],
) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _require(evidence_dir.is_dir(), "license evidence path is not a directory")
    _require(
        not any(evidence_dir.iterdir()),
        "license evidence directory must be empty",
    )
    _require(
        set(raw_documents) == set(documents),
        "raw and normalized SPDX evidence identities differ",
    )
    raw_dir = evidence_dir / "raw"
    raw_dir.mkdir()
    for (profile_id, role), (source_format, value) in sorted(raw_documents.items()):
        extension = LICENSE_AUDIT_RAW_EXTENSIONS.get(source_format)
        _require(
            extension is not None and isinstance(value, bytes) and bool(value),
            "raw SPDX evidence is missing or has an unsupported format",
        )
        (raw_dir / ("%s--%s.%s" % (profile_id, role, extension))).write_bytes(value)
    spdx_dir = evidence_dir / "spdx"
    spdx_dir.mkdir()
    for (profile_id, role), document in sorted(documents.items()):
        _write_json(spdx_dir / ("%s--%s.spdx.json" % (profile_id, role)), document)
    evidence_hashes = {
        path.relative_to(evidence_dir).as_posix(): _sha256_path(path)
        for path in sorted(evidence_dir.rglob("*"))
        if path.is_file()
    }
    _require(
        len(evidence_hashes)
        == 2 * len(LICENSE_AUDIT_PROFILES) * len(LICENSE_AUDIT_ROLES),
        "license audit must retain the exact raw and normalized profile/role documents",
    )
    receipt = {
        "schema_version": 1,
        "notice_sha256": _sha256_bytes(notice.encode("utf-8")),
        "input_sha256": input_hashes,
        "executed_artifacts": dict(sorted(artifact_hashes.items())),
        "execution_identity": execution_identity,
        "identities": [
            {"profile_id": profile_id, "role": role}
            for profile_id, role in sorted(documents)
        ],
        "evidence_sha256": evidence_hashes,
    }
    _write_json(evidence_dir / "audit-receipt.json", receipt)


def _audit_v2_toolchain_context_from_observations(
    policy: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    repo_root: Path,
) -> dict[str, dict[str, str]]:
    toolchain_observations = [
        item for item in observations if item["kind"] == "toolchain-archive"
    ]
    contexts = _audit_v2_derive_toolchain_cache_context(
        policy,
        repo_root=repo_root,
        compiler_paths={
            Path(compiler_path)
            for item in toolchain_observations
            for compiler_path in item["compiler_paths"]
        },
    )
    for item in toolchain_observations:
        identifier = item["toolchain_id"]
        context = contexts.get(identifier)
        _require(
            context is not None,
            "observed toolchain archive names an unknown toolchain",
        )
        root = Path(context["root"])
        toolchain_record = next(
            record
            for record in policy["toolchains"]
            if record["id"] == identifier
        )
        reviewed_frontends = _audit_v2_compiler_frontends(
            toolchain_record.get("compiler_frontends"),
            "toolchain %s" % identifier,
        )
        expected_frontend_paths = {
            root / frontend["relative_path"]
            for frontend in reviewed_frontends
        }
        _require(
            bool(item["compiler_paths"])
            and {
                Path(compiler_path)
                for compiler_path in item["compiler_paths"]
            }
            <= expected_frontend_paths
            and Path(item["observed_path"])
            == root / item["relative_path"],
            "toolchain %s observation disagrees with trusted cache context"
            % identifier,
        )
    return contexts


def _audit_v2_validate_raw_envelope(
    document: Any,
    *,
    profile_id: str,
    role: str,
    source_format: str,
    expected_document_name: str | None,
) -> dict[str, Any]:
    _require(isinstance(document, dict), "SBOM output must be an object")
    expected_version = "SPDX-2.2" if source_format == "tag-value" else "SPDX-2.3"
    _require(
        document.get("spdxVersion") == expected_version
        and document.get("dataLicense") == "CC0-1.0"
        and document.get("SPDXID") == "SPDXRef-DOCUMENT",
        "raw SPDX document envelope changed",
    )
    name = document.get("name")
    _require(
        isinstance(name, str)
        and bool(name)
        and (
            name == expected_document_name
            or (profile_id in name and role in name)
        ),
        "raw SPDX document identity changed",
    )
    namespace = document.get("documentNamespace")
    _require(
        isinstance(namespace, str)
        and (
            namespace.startswith("http://spdx.org/spdxdocs/")
            or namespace.startswith("https://")
            or namespace.startswith("urn:")
        ),
        "raw SPDX document namespace is invalid",
    )
    creation = document.get("creationInfo")
    _require(isinstance(creation, dict), "raw SPDX creationInfo is missing")
    creators = creation.get("creators")
    _require(
        isinstance(creators, list)
        and "Tool: ESP-IDF SBOM builder" in creators
        and re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
            str(creation.get("created", "")),
        )
        is not None,
        "raw SPDX execution identity changed",
    )
    _require(
        isinstance(document.get("packages"), list)
        and bool(document["packages"])
        and isinstance(document.get("relationships"), list)
        and bool(document["relationships"]),
        "raw SPDX package graph is empty",
    )
    _require(
        document.get("files", []) == [],
        "linked-only raw SPDX unexpectedly contains file records",
    )
    return copy.deepcopy(document)


def _audit_v2_extracted_license_refs(
    policy: dict[str, Any],
    *,
    repo_root: Path,
) -> list[dict[str, str]]:
    approved = set(policy["approved_license_refs"])
    records: dict[str, dict[str, str]] = {}
    for collection in ("reviewed_packages", "supplemental_packages"):
        for package in policy[collection]:
            for record in package["license_texts"]:
                identifier = record["spdx_id"]
                if identifier not in approved:
                    continue
                path = _audit_repo_file(
                    repo_root,
                    record["path"],
                    "%s extracted LicenseRef" % identifier,
                )
                text = path.read_text(encoding="utf-8", errors="strict")
                _require(
                    _sha256_bytes(text.encode("utf-8")) == record["sha256"],
                    "%s extracted LicenseRef text changed" % identifier,
                )
                candidate = {
                    "licenseId": identifier,
                    "name": identifier,
                    "extractedText": text,
                }
                if identifier in records:
                    _require(
                        records[identifier] == candidate,
                        "%s resolves to ambiguous complete texts" % identifier,
                    )
                records[identifier] = candidate
    _require(
        set(records) == approved,
        "approved LicenseRefs lack exact extracted texts",
    )
    return [records[identifier] for identifier in sorted(records)]


def _audit_v2_reviewed_documents(
    *,
    parsed_documents: dict[tuple[str, str], dict[str, Any]],
    validated: dict[str, Any],
    policy: dict[str, Any],
    repo_root: Path,
    build_root: Path,
) -> dict[tuple[str, str], dict[str, Any]]:
    extracted_refs = _audit_v2_extracted_license_refs(
        policy,
        repo_root=repo_root,
    )
    reviewed_documents: dict[tuple[str, str], dict[str, Any]] = {}
    for identity, raw_document in sorted(parsed_documents.items()):
        profile_id, role = identity
        reviewed = copy.deepcopy(raw_document)
        normalized_graph = validated["reviewed_documents"][
            "%s/%s" % identity
        ]
        reviewed["spdxVersion"] = "SPDX-2.3"
        reviewed["name"] = "PyBLE license review %s/%s" % identity
        reviewed["packages"] = normalized_graph["packages"]
        reviewed["relationships"] = normalized_graph["relationships"]
        reviewed["hasExtractedLicensingInfos"] = copy.deepcopy(extracted_refs)
        reviewed["creationInfo"]["creators"] = [
            creator
            for creator in reviewed["creationInfo"]["creators"]
            if creator != "Tool: ESP-IDF SBOM builder"
        ] + ["Tool: esp-idf-sbom-1.2.0"]
        reviewed_documents[identity] = _audit_normalize_spdx(
            reviewed,
            profile_id=profile_id,
            role=role,
            repo_root=repo_root,
            build_root=build_root,
        )
    return reviewed_documents


def _audit_v2_release_notice_records(
    validated: dict[str, Any],
    *,
    policy: dict[str, Any],
    release_profile_ids: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Scope the reviewed notice graph without narrowing its audit evidence."""

    _require(
        tuple(release_profile_ids)
        in (
            tuple(HISTORICAL_V042_RELEASE_PROFILE_ORDER),
            tuple(V05_RELEASE_PROFILE_ORDER),
            tuple(V060_RELEASE_PROFILE_ORDER),
        ),
        "license notice profile scope differs from a supported release era",
    )
    released = set(release_profile_ids)
    audit_profiles = {
        profile_id for profile_id, _target, _idf_target in LICENSE_AUDIT_PROFILES
    }
    _require(
        len(released) == len(release_profile_ids)
        and bool(released)
        and released <= audit_profiles,
        "license notice profile scope is invalid",
    )

    raw_inputs = policy.get("resolved_inputs")
    _require(
        isinstance(raw_inputs, list) and bool(raw_inputs),
        "license notice scope lacks resolved input provenance",
    )
    input_profiles: dict[str, str] = {}
    for raw_input in raw_inputs:
        _require(
            isinstance(raw_input, dict),
            "license notice resolved input is invalid",
        )
        identifier = raw_input.get("id")
        profile_id = raw_input.get("profile_id")
        _require(
            isinstance(identifier, str)
            and bool(identifier)
            and identifier not in input_profiles
            and isinstance(profile_id, str)
            and profile_id in audit_profiles,
            "license notice resolved input profile is invalid",
        )
        input_profiles[identifier] = profile_id

    raw_notice_records = validated.get("notice_records")
    _require(
        isinstance(raw_notice_records, list),
        "validated license notice records are invalid",
    )
    records_by_id: dict[str, dict[str, Any]] = {}
    for raw_record in raw_notice_records:
        _require(
            isinstance(raw_record, dict),
            "validated license notice record is invalid",
        )
        identifier = raw_record.get("id")
        _require(
            isinstance(identifier, str)
            and bool(identifier)
            and identifier not in records_by_id,
            "validated license notice record id is invalid",
        )
        records_by_id[identifier] = raw_record

    selected: list[dict[str, Any]] = []
    resolutions = validated.get("resolutions")
    _require(
        isinstance(resolutions, list),
        "validated license resolutions are invalid",
    )
    for resolution in resolutions:
        _require(
            isinstance(resolution, dict),
            "validated license resolution is invalid",
        )
        disposition = resolution.get("disposition")
        if disposition not in ("allow", "allow-aggregate"):
            continue
        reviewed_id = resolution.get("reviewed_package_id")
        _require(
            isinstance(reviewed_id, str) and reviewed_id in records_by_id,
            "validated license resolution lacks its notice record",
        )
        record = records_by_id.pop(reviewed_id)
        package_refs = resolution.get("package_refs")
        _require(
            isinstance(package_refs, list) and bool(package_refs),
            "validated license resolution has no package applicability",
        )
        applicable = any(
            isinstance(package_ref, dict)
            and package_ref.get("profile_id") in released
            for package_ref in package_refs
        )
        if not applicable:
            continue

        input_refs = record.get("input_refs")
        _require(
            isinstance(input_refs, list)
            and all(
                isinstance(identifier, str) and identifier in input_profiles
                for identifier in input_refs
            ),
            "validated license notice input references are invalid",
        )
        scoped = copy.deepcopy(record)
        scoped["input_refs"] = [
            identifier
            for identifier in input_refs
            if input_profiles[identifier] in released
        ]
        if disposition == "allow":
            _require(
                bool(scoped["input_refs"]),
                "released license resolution lost its redistributed inputs",
            )
        else:
            _require(
                not scoped["input_refs"],
                "aggregate license resolution unexpectedly owns direct inputs",
            )
        selected.append(scoped)

    supplementals = validated.get("supplemental_packages")
    _require(
        isinstance(supplementals, list),
        "validated supplemental license records are invalid",
    )
    for supplemental in supplementals:
        _require(
            isinstance(supplemental, dict),
            "validated supplemental license record is invalid",
        )
        identifier = supplemental.get("id")
        _require(
            isinstance(identifier, str) and identifier in records_by_id,
            "validated supplemental package lacks its notice record",
        )
        record = records_by_id.pop(identifier)
        input_refs = record.get("input_refs")
        _require(
            isinstance(input_refs, list)
            and bool(input_refs)
            and all(
                isinstance(input_ref, str) and input_ref in input_profiles
                for input_ref in input_refs
            ),
            "validated supplemental notice input references are invalid",
        )
        scoped_refs = [
            input_ref
            for input_ref in input_refs
            if input_profiles[input_ref] in released
        ]
        if not scoped_refs:
            continue
        scoped = copy.deepcopy(record)
        scoped["input_refs"] = scoped_refs
        selected.append(scoped)

    _require(
        not records_by_id,
        "validated license notice graph contains unscoped records",
    )
    selected.sort(key=lambda record: record["id"])
    return selected


def _audit_v2_release_frozen_names(
    *,
    repo_root: Path,
    build_root: Path,
    release_profile_ids: tuple[str, ...],
) -> set[str]:
    _require(
        tuple(release_profile_ids)
        in (
            tuple(HISTORICAL_V042_RELEASE_PROFILE_ORDER),
            tuple(V05_RELEASE_PROFILE_ORDER),
            tuple(V060_RELEASE_PROFILE_ORDER),
        ),
        "frozen notice profile scope differs from a supported release era",
    )
    targets = {
        profile_id: target
        for profile_id, target, _idf_target in LICENSE_AUDIT_PROFILES
    }
    _require(
        set(release_profile_ids) <= set(targets),
        "frozen notice profile scope names an unaudited profile",
    )
    frozen_names: set[str] = set()
    for profile_id in release_profile_ids:
        target = targets[profile_id]
        frozen_names.update(
            _audit_manifest_inventory(
                repo_root / "firmware/board_overlays" / target / "manifest.py",
                build_root / target / "frozen_content.c",
                repo_root=repo_root,
                target=target,
            )
        )
    return frozen_names


def _audit_notice_v2(
    records: list[dict[str, Any]],
    *,
    repo_root: Path,
    frozen_names: set[str],
) -> str:
    lines = [
        "PyBLE mechanically generated complete firmware dependency notices",
        "",
        "Generated frozen inventory: %s." % ", ".join(sorted(frozen_names)),
        "",
    ]
    unique_texts: dict[tuple[str, str], tuple[str, str]] = {}
    for record in sorted(records, key=lambda item: item["dependency"]["name"]):
        dependency = record["dependency"]
        lines.extend(
            [
                "=" * 78,
                "Name: %s" % dependency["name"],
                "Version/ref: %s" % dependency["version_ref"],
                "Source URL: %s" % dependency["source_url"],
                "SPDX identifier: %s" % record["spdx_expression"],
                "Copyright: %s" % dependency["copyright"],
                "Resolved inputs: %s"
                % (
                    ", ".join(record["input_refs"])
                    if record["input_refs"]
                    else "aggregate source identity"
                ),
            ]
        )
        notice = record["notice"]
        if notice["required"]:
            value = _audit_repo_file(
                repo_root,
                notice["path"],
                "%s required NOTICE" % record["id"],
            ).read_text(encoding="utf-8", errors="strict")
            lines.extend(["Required notice text:", value.rstrip()])
        else:
            lines.append("Required notice text: none.")
        lines.append(
            "Complete license text SHA-256: %s"
            % ", ".join(item["sha256"] for item in record["license_texts"])
        )
        lines.append("")
        for item in record["license_texts"]:
            text = _audit_repo_file(
                repo_root,
                item["path"],
                "%s complete license text" % record["id"],
            ).read_text(encoding="utf-8", errors="strict")
            unique_texts.setdefault(
                (item["spdx_id"], item["sha256"]),
                (item["path"], text.rstrip()),
            )
    lines.extend(["=" * 78, "Complete reviewed license texts", ""])
    for (identifier, digest), (path, text) in sorted(unique_texts.items()):
        lines.extend(
            [
                "-" * 78,
                "SPDX identifier: %s" % identifier,
                "Reviewed file: %s" % path,
                "SHA-256: %s" % digest,
                "",
                text,
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _audit_release_licenses_v2(
    *,
    build_root: Path,
    repo_root: Path,
    evidence_dir: Path,
    runner: Any,
    lock: dict[str, Any],
    policy: dict[str, Any],
    excluded: Path,
) -> dict[str, Any]:
    observed_context = _audit_observe_policy_v2_context(
        policy,
        repo_root=repo_root,
        build_root=build_root,
    )
    observations = observed_context["observed_inputs"]
    toolchain_context = observed_context["toolchain_roots"]
    initial_manifest_evidence = observed_context["manifest_evidence"]
    initial_retained_sources = observed_context[
        "retained_source_records"
    ]
    initial_observed_hashes = {
        item["id"]: item["sha256"] for item in observations
    }
    initial_fixed_hashes = {
        "release-tools.lock": _sha256_path(repo_root / "firmware/release-tools.lock"),
        "license-policy.json": _sha256_path(
            repo_root / lock["inputs"]["license_policy_path"]
        ),
        "excluded-cves": _sha256_path(excluded),
    }
    raw_documents: dict[tuple[str, str], tuple[str, bytes]] = {}
    parsed_documents: dict[tuple[str, str], dict[str, Any]] = {}
    observed_documents: dict[tuple[str, str], dict[str, Any]] = {}
    execution_identity: dict[str, Any] | None = None
    with tempfile.TemporaryDirectory(prefix="pyble-license-audit-") as temporary_raw:
        temporary = Path(temporary_raw)
        raw_outputs = temporary / "raw"
        raw_outputs.mkdir()
        environment = {
            key: os.environ[key]
            for key in ("LANG", "LC_ALL", "LC_CTYPE", "PATH", "TZ")
            if key in os.environ
        }
        environment.update(
            {
                "HOME": str(temporary / "home"),
                "XDG_CACHE_HOME": str(temporary / "xdg-cache"),
                "PIP_CACHE_DIR": str(temporary / "pip-cache"),
                "PIP_CONFIG_FILE": os.devnull,
                "PIP_NO_INDEX": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "PYTHONNOUSERSITE": "1",
                "SBOM_EXCLUDED_CVES_FILE": str(excluded.resolve()),
                "TMPDIR": str(temporary),
            }
        )
        for profile_id, target, _idf_target in LICENSE_AUDIT_PROFILES:
            for role in LICENSE_AUDIT_ROLES:
                _role_build, description_path, _compile_path, _map_path = (
                    _audit_v2_role_paths(build_root, target, role)
                )
                description = _read_json(
                    description_path,
                    "%s/%s project description" % (profile_id, role),
                )
                output = raw_outputs / ("%s--%s.spdx.tag" % (profile_id, role))
                command = [
                    sys.executable,
                    "-m",
                    "esp_idf_sbom",
                    "create",
                    str(description_path.resolve()),
                    "--output-file",
                    str(output),
                    "--rem-unused",
                    "--rem-config",
                    "--file-tags",
                ]
                try:
                    completed = runner(
                        command,
                        cwd=description_path.parent,
                        env=environment,
                        check=True,
                        network_disabled=True,
                    )
                except Exception as exc:
                    raise ReleaseError(
                        "offline esp-idf-sbom execution failed for %s/%s"
                        % (profile_id, role)
                    ) from exc
                _require(
                    getattr(completed, "returncode", 0) == 0
                    and getattr(completed, "network_isolated", None) is True,
                    "offline SBOM execution was not successful and isolated",
                )
                _audit_exact_executed_artifacts(
                    getattr(completed, "executed_artifacts", None),
                    lock["_artifact_hashes"],
                )
                current_identity = _audit_validate_execution_identity(
                    getattr(completed, "execution_identity", None),
                    artifact_hashes=lock["_artifact_hashes"],
                )
                if execution_identity is None:
                    execution_identity = current_identity
                else:
                    _require(
                        execution_identity == current_identity,
                        "SBOM execution identity changed during the profile/role audit",
                    )
                raw_value = output.read_bytes()
                document, source_format = _audit_read_spdx_output(
                    output,
                    "esp-idf-sbom output",
                )
                document = _audit_v2_validate_raw_envelope(
                    document,
                    profile_id=profile_id,
                    role=role,
                    source_format=source_format,
                    expected_document_name=description.get("project_name"),
                )
                identity = (profile_id, role)
                raw_documents[identity] = (source_format, raw_value)
                parsed_documents[identity] = document
                observed_documents[identity] = {
                    "packages": copy.deepcopy(document["packages"]),
                    "relationships": copy.deepcopy(document["relationships"]),
                }

    _require(
        execution_identity is not None
        and len(observed_documents)
        == len(LICENSE_AUDIT_PROFILES) * len(LICENSE_AUDIT_ROLES),
        "license audit did not retain every profile/role execution result",
    )
    final_observed_context = _audit_observe_policy_v2_context_once(
        policy,
        repo_root=repo_root,
        build_root=build_root,
    )
    _require(
        final_observed_context == observed_context,
        "license audit generated context changed during the profile/role audit",
    )
    validated = _audit_validate_policy_v2(
        policy,
        repo_root=repo_root,
        observed_documents=observed_documents,
        observed_inputs=observations,
        manifest_evidence=initial_manifest_evidence,
        toolchain_roots=toolchain_context,
    )
    reviewed_documents = _audit_v2_reviewed_documents(
        parsed_documents=parsed_documents,
        validated=validated,
        policy=policy,
        repo_root=repo_root,
        build_root=build_root,
    )

    firmware_version = _read_lock(repo_root)["pyble"]["agent_version"]
    release_profile_order = _release_profile_order_for_version(firmware_version)
    frozen_union = _audit_v2_release_frozen_names(
        repo_root=repo_root,
        build_root=build_root,
        release_profile_ids=release_profile_order,
    )
    notice_records = _audit_v2_release_notice_records(
        validated,
        policy=policy,
        release_profile_ids=release_profile_order,
    )
    notice = _audit_notice_v2(
        notice_records,
        repo_root=repo_root,
        frozen_names=frozen_union,
    )
    final_fixed_hashes = {
        "release-tools.lock": _sha256_path(repo_root / "firmware/release-tools.lock"),
        "license-policy.json": _sha256_path(
            repo_root / lock["inputs"]["license_policy_path"]
        ),
        "excluded-cves": _sha256_path(excluded),
    }
    final_observed_hashes = {
        item["id"]: (
            _audit_sha256_tree(Path(item["observed_path"]))
            if item["kind"] == "frozen-source-tree"
            else _sha256_path(Path(item["observed_path"]))
        )
        for item in observations
    }
    final_manifest_evidence = _audit_all_manifest_evidence(
        repo_root=repo_root,
        build_root=build_root,
        trusted_mpy_cross_sha256=initial_manifest_evidence[0][
            "mpy_cross"
        ]["sha256"],
    )
    final_retained_sources = _audit_retained_source_checkouts(
        repo_root,
        build_root,
    )
    _require(
        final_fixed_hashes == initial_fixed_hashes
        and final_observed_hashes == initial_observed_hashes,
        "license audit inputs changed during the profile/role audit",
    )
    _require(
        final_manifest_evidence == initial_manifest_evidence,
        "license audit inputs changed during the profile/role audit",
    )
    _require(
        final_retained_sources == initial_retained_sources,
        "retained target source identity changed during the profile/role audit",
    )
    input_hashes = {
        **initial_fixed_hashes,
        **{
            "resolved-input/%s" % identifier: digest
            for identifier, digest in sorted(initial_observed_hashes.items())
        },
        **{
            "semantic/%s" % identifier: digest
            for identifier, digest in sorted(
                validated["semantic_sha256"].items()
            )
        },
        "semantic/retained_source_checkouts": (
            _audit_retained_source_digest(initial_retained_sources)
        ),
    }
    _audit_write_evidence(
        evidence_dir,
        documents=reviewed_documents,
        raw_documents=raw_documents,
        notice=notice,
        input_hashes=input_hashes,
        artifact_hashes=lock["_artifact_hashes"],
        execution_identity=execution_identity,
    )
    return {
        "third_party_licenses": notice,
        "input_sha256": input_hashes,
    }


def audit_release_licenses(
    *,
    build_root: Path,
    repo_root: Path,
    evidence_dir: Path,
    runner: Any,
) -> dict[str, Any]:
    """Audit every linked profile/role inventory and retain review evidence."""

    root = Path(repo_root)
    builds = Path(build_root)
    evidence = Path(evidence_dir)
    _require(root.is_dir(), "repository root is missing")
    _require(builds.is_dir(), "license audit build root is missing")
    _require(callable(runner), "license audit runner is not callable")
    _require(
        not evidence.resolve().is_relative_to(root.resolve())
        and not evidence.resolve().is_relative_to(builds.resolve()),
        "license evidence must be outside source and build roots",
    )

    lock = _audit_load_tool_lock(root)
    excluded = _audit_repo_file(
        root,
        lock["inputs"]["excluded_cves_path"],
        "excluded CVE input",
    )
    semantic_exclusions = "\n".join(
        line.split("#", 1)[0].strip()
        for line in excluded.read_text(encoding="utf-8").splitlines()
        if line.split("#", 1)[0].strip()
    )
    _require(
        semantic_exclusions in ("", "{}", "[]", "null", "~"),
        "excluded CVE input must remain semantically empty",
    )
    policy = _audit_load_policy(root, lock)
    return _audit_release_licenses_v2(
        build_root=builds,
        repo_root=root,
        evidence_dir=evidence,
        runner=runner,
        lock=lock,
        policy=policy,
        excluded=excluded,
    )

    neopixel_tree = (
        root
        / "firmware"
        / "upstream"
        / "micropython"
        / "lib"
        / "micropython-lib"
        / "micropython"
        / "drivers"
        / "led"
        / "neopixel"
    )
    source_tree_matches = [
        entry for entry in entries if entry["match"]["kind"] == "source-tree"
    ]
    for entry in source_tree_matches:
        if "path" not in entry["match"] and "neopixel" in json.dumps(entry).lower():
            _require(
                _audit_sha256_tree(neopixel_tree) == entry["match"]["sha256"],
                "reviewed NeoPixel source-tree digest changed",
            )

    inventories: dict[tuple[str, str], dict[str, Any]] = {}
    frozen_union: set[str] = set()
    for profile_id, target, idf_target in LICENSE_AUDIT_PROFILES:
        manifest_path = root / "firmware" / "board_overlays" / target / "manifest.py"
        frozen_path = builds / target / "frozen_content.c"
        frozen_union.update(
            _audit_manifest_inventory(
                manifest_path,
                frozen_path,
                repo_root=root,
                target=target,
            )
        )
        for role in LICENSE_AUDIT_ROLES:
            inventories[(profile_id, role)] = _audit_inventory_role(
                profile_id=profile_id,
                target=target,
                idf_target=idf_target,
                role=role,
                repo_root=root,
                build_root=builds,
                entries=entries,
            )

    initial_input_hashes = _audit_input_hashes(
        repo_root=root,
        build_root=builds,
        lock=lock,
        entries=entries,
        inventories=inventories,
    )
    documents: dict[tuple[str, str], dict[str, Any]] = {}
    raw_documents: dict[tuple[str, str], tuple[str, bytes]] = {}
    execution_identity: dict[str, Any] | None = None
    with tempfile.TemporaryDirectory(prefix="pyble-license-audit-") as temporary_raw:
        temporary = Path(temporary_raw)
        home = temporary / "home"
        xdg = temporary / "xdg-cache"
        pip_cache = temporary / "pip-cache"
        raw_outputs = temporary / "raw"
        raw_outputs.mkdir()
        environment = {
            key: os.environ[key]
            for key in ("LANG", "LC_ALL", "LC_CTYPE", "PATH", "TZ")
            if key in os.environ
        }
        environment.update(
            {
                "HOME": str(home),
                "XDG_CACHE_HOME": str(xdg),
                "PIP_CACHE_DIR": str(pip_cache),
                "PIP_CONFIG_FILE": os.devnull,
                "PIP_NO_INDEX": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "PYTHONNOUSERSITE": "1",
                "SBOM_EXCLUDED_CVES_FILE": str(excluded.resolve()),
                "TMPDIR": str(temporary),
            }
        )
        for profile_id, target, _idf_target in LICENSE_AUDIT_PROFILES:
            for role in LICENSE_AUDIT_ROLES:
                inventory = inventories[(profile_id, role)]
                output = raw_outputs / ("%s--%s.spdx.json" % (profile_id, role))
                command = [
                    sys.executable,
                    "-m",
                    "esp_idf_sbom",
                    "create",
                    str(inventory["description_path"].resolve()),
                    "--output-file",
                    str(output),
                    "--rem-unused",
                    "--rem-config",
                    "--file-tags",
                ]
                try:
                    completed = runner(
                        command,
                        cwd=inventory["description_path"].parent,
                        env=environment,
                        check=True,
                        network_disabled=True,
                    )
                except Exception as exc:
                    raise ReleaseError(
                        "offline esp-idf-sbom execution failed for %s/%s"
                        % (profile_id, role)
                    ) from exc
                _require(
                    getattr(completed, "returncode", 0) == 0,
                    "offline esp-idf-sbom returned failure",
                )
                _audit_exact_executed_artifacts(
                    getattr(completed, "executed_artifacts", None),
                    lock["_artifact_hashes"],
                )
                isolated = getattr(completed, "network_isolated", None)
                _require(
                    isolated is True,
                    "SBOM runner did not prove network isolation",
                )
                current_identity = _audit_validate_execution_identity(
                    getattr(completed, "execution_identity", None),
                    artifact_hashes=lock["_artifact_hashes"],
                )
                if execution_identity is None:
                    execution_identity = current_identity
                else:
                    _require(
                        current_identity == execution_identity,
                        "SBOM execution identity changed during the profile/role audit",
                    )
                try:
                    output_mode = output.lstat().st_mode
                    raw_value = output.read_bytes()
                except OSError as exc:
                    raise ReleaseError(
                        "esp-idf-sbom output is missing or unreadable"
                    ) from exc
                _require(
                    stat_module.S_ISREG(output_mode)
                    and not stat_module.S_ISLNK(output_mode)
                    and bool(raw_value),
                    "esp-idf-sbom output must be a non-empty regular file",
                )
                raw_document, source_format = _audit_read_spdx_output(
                    output,
                    "esp-idf-sbom output",
                )
                try:
                    validated_raw_value = output.read_bytes()
                except OSError as exc:
                    raise ReleaseError(
                        "esp-idf-sbom output disappeared during validation"
                    ) from exc
                _require(
                    validated_raw_value == raw_value,
                    "esp-idf-sbom output changed while it was being validated",
                )
                validated = _audit_validate_spdx_document(
                    raw_document,
                    profile_id=profile_id,
                    role=role,
                    entries=entries,
                    approved_license_refs=approved,
                    source_format=source_format,
                    expected_document_name=inventory["description"].get("project_name"),
                    repo_root=root,
                )
                raw_documents[(profile_id, role)] = (source_format, raw_value)
                documents[(profile_id, role)] = _audit_normalize_spdx(
                    validated,
                    profile_id=profile_id,
                    role=role,
                    repo_root=root,
                    build_root=builds,
                )

    _require(
        len(documents) == len(LICENSE_AUDIT_PROFILES) * len(LICENSE_AUDIT_ROLES),
        "license audit did not produce every profile/role SPDX inventory",
    )
    _require(
        execution_identity is not None,
        "license audit retained no execution identity",
    )
    notice = _audit_notice(entries, repo_root=root, frozen_names=frozen_union)
    final_input_hashes = _audit_input_hashes(
        repo_root=root,
        build_root=builds,
        lock=lock,
        entries=entries,
        inventories=inventories,
    )
    _require(
        final_input_hashes == initial_input_hashes,
        "license audit inputs changed during the profile/role audit",
    )
    _audit_write_evidence(
        evidence,
        documents=documents,
        raw_documents=raw_documents,
        notice=notice,
        input_hashes=initial_input_hashes,
        artifact_hashes=lock["_artifact_hashes"],
        execution_identity=execution_identity,
    )
    return {
        "third_party_licenses": notice,
        "input_sha256": initial_input_hashes,
    }


def audit_release_licenses_from_lock(
    *,
    build_root: Path,
    repo_root: Path,
    evidence_dir: Path,
    wheelhouse: Path,
    notice_output: Path,
) -> dict[str, Any]:
    """Run the production offline audit and atomically publish its outputs."""

    builds = Path(build_root).absolute()
    root = Path(repo_root).absolute()
    wheels = Path(wheelhouse).absolute()
    evidence = Path(evidence_dir).absolute()
    notice_path = Path(notice_output).absolute()
    _require(builds.is_dir(), "license audit build root is missing")
    _require(root.is_dir(), "repository root is missing")
    _require(wheels.is_dir(), "release-tool wheelhouse is missing")
    _require(
        evidence.parent.is_dir() and not evidence.parent.is_symlink(),
        "license evidence parent is missing or unsafe",
    )
    _require(
        not evidence.exists() and not evidence.is_symlink(),
        "production license evidence path must be new",
    )
    _require(
        notice_path.parent.is_dir()
        and not notice_path.parent.is_symlink()
        and not notice_path.is_symlink()
        and (not notice_path.exists() or notice_path.is_file()),
        "license notice output path is unsafe",
    )

    with tempfile.TemporaryDirectory(
        prefix=".pyble-license-publication-",
        dir=evidence.parent,
    ) as staging_raw:
        staging_root = Path(staging_raw)
        staging_evidence = staging_root / "evidence"
        temporary_notice: Path | None = None
        try:
            with LockedWheelSbomRunner(
                repo_root=root,
                build_root=builds,
                wheelhouse=wheels,
            ) as runner:
                result = audit_release_licenses(
                    build_root=builds,
                    repo_root=root,
                    evidence_dir=staging_evidence,
                    runner=runner,
                )
            notice = result.get("third_party_licenses")
            _require(
                isinstance(notice, str)
                and bool(notice)
                and notice.endswith("\n")
                and NOTICE_CANDIDATE_MARKER not in notice,
                "production license audit returned an invalid notice",
            )
            descriptor, temporary_raw = tempfile.mkstemp(
                prefix=".%s." % notice_path.name,
                suffix=".tmp",
                dir=notice_path.parent,
            )
            temporary_notice = Path(temporary_raw)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(notice)
                handle.flush()
                os.fsync(handle.fileno())
            _require(
                staging_evidence.is_dir(),
                "production license audit retained no evidence",
            )
            _atomic_publish_no_replace(
                staging_evidence,
                evidence,
                "license evidence",
            )
            try:
                os.replace(temporary_notice, notice_path)
                temporary_notice = None
            except OSError:
                os.replace(evidence, staging_evidence)
                raise
        except OSError as exc:
            raise ReleaseError(
                "cannot atomically publish license audit outputs"
            ) from exc
        finally:
            if temporary_notice is not None:
                try:
                    temporary_notice.unlink()
                except FileNotFoundError:
                    pass
    return {
        "third_party_licenses": notice_path.read_text(encoding="utf-8"),
        "evidence_dir": evidence,
        "notice_output": notice_path,
    }


def _audit_verify_packaged_build(
    *,
    bundle: Path,
    release: dict[str, Any],
    build_root: Path,
) -> None:
    version = release.get("identity", {}).get("version")
    _require(isinstance(version, str), "packaged release version is missing")
    release_profile_order = _release_profile_order_for_version(version)
    profile_records = {
        profile["id"]: profile for profile in release.get("profiles", [])
    }
    _require(
        set(profile_records) == set(release_profile_order),
        "packaged release profile inventory is incomplete",
    )
    build_provenance: list[dict[str, Any]] = []
    for profile_id in release_profile_order:
        target = PROFILE_SPECS[profile_id]["target"]
        target_build = build_root / target
        pairs = (
            (
                bundle / profile_id / "firmware.bin",
                target_build / "firmware.bin",
                "merged firmware",
            ),
            (
                bundle / profile_id / "application.bin",
                target_build / "micropython.bin",
                "application",
            ),
            (
                bundle / profile_id / "bootloader.bin",
                target_build / "bootloader" / "bootloader.bin",
                "bootloader",
            ),
            (
                bundle / profile_id / "partition-table.bin",
                target_build / "partition_table" / "partition-table.bin",
                "partition table",
            ),
        )
        for packaged, audited, label in pairs:
            _require(
                _sha256_path(packaged) == _sha256_path(audited)
                and packaged.stat().st_size == audited.stat().st_size,
                "%s %s differs from the audited packaged build" % (profile_id, label),
            )
        build_provenance.append(
            {
                "provenance": _validate_build_provenance(
                    _read_json(
                        target_build / "pyble-build-provenance.json",
                        "%s audited build provenance" % target,
                    ),
                    target,
                )
            }
        )

    _require_one_build_source_identity(build_provenance)
    packaged_provenance = release["provenance"]
    for item in build_provenance:
        provenance = item["provenance"]
        _require(
            provenance["pyble"]["commit"] == packaged_provenance["pyble"]["commit"]
            and provenance["micropython"]["commit"]
            == packaged_provenance["micropython"]["commit"]
            and provenance["esp_idf"]["commit"]
            == packaged_provenance["esp_idf"]["commit"],
            "packaged release provenance differs from the audited build",
        )


def _audit_verify_release_evidence(
    *,
    notice: str,
    evidence_dir: Path | None,
    build_root: Path | None,
    repo_root: Path | None,
    bundle: Path | None = None,
    release: dict[str, Any] | None = None,
) -> None:
    _require(
        evidence_dir is not None and build_root is not None and repo_root is not None,
        "audited release validation requires fresh license evidence, build root, "
        "and repository root",
    )
    evidence = Path(evidence_dir)
    builds = Path(build_root)
    root = Path(repo_root)
    release_profile_order = (
        _release_profile_order_for_version(release["identity"]["version"])
        if release is not None
        else _release_profile_order_for_version(
            _read_lock(root)["pyble"]["agent_version"]
        )
    )
    if tuple(release_profile_order) == V060_RELEASE_PROFILE_ORDER:
        raise ReleaseError(
            "v0.6.0 license admission requires a persisted heterogeneous "
            "release-inventory receipt; the current ESP-only audit receipt "
            "cannot qualify RP2"
        )
    _require(
        not evidence.is_symlink(),
        "license review evidence root must not be a symlink",
    )
    _require(evidence.is_dir(), "license review evidence directory is missing")
    _require(
        root.is_dir() and builds.is_dir(), "license review input roots are missing"
    )
    _require(
        not evidence.resolve().is_relative_to(root.resolve())
        and not evidence.resolve().is_relative_to(builds.resolve()),
        "license evidence must be outside source and build roots",
    )
    for path in evidence.rglob("*"):
        _require(not path.is_symlink(), "license review evidence contains a symlink")

    receipt_path = evidence / "audit-receipt.json"
    receipt = _read_json(receipt_path, "license audit receipt")
    canonical_receipt = json.dumps(receipt, indent=2, sort_keys=False) + "\n"
    _require(
        receipt_path.read_text(encoding="utf-8", errors="strict") == canonical_receipt,
        "license audit receipt bytes were changed after generation",
    )
    receipt = _exact_keys(
        receipt,
        {
            "schema_version",
            "notice_sha256",
            "input_sha256",
            "executed_artifacts",
            "execution_identity",
            "identities",
            "evidence_sha256",
        },
        "license audit receipt",
    )
    _require(
        type(receipt["schema_version"]) is int
        and receipt["schema_version"] == 1,
        "license audit receipt version changed",
    )
    _require(
        receipt["notice_sha256"] == _sha256_bytes(notice.encode("utf-8")),
        "release notice is not the exact audited notice",
    )

    evidence_hashes = receipt["evidence_sha256"]
    _require(
        isinstance(evidence_hashes, dict)
        and all(isinstance(relative, str) for relative in evidence_hashes),
        "license evidence hash inventory is invalid",
    )
    expected_reviewed_paths = {
        "spdx/%s--%s.spdx.json" % (profile_id, role)
        for profile_id, _target, _idf_target in LICENSE_AUDIT_PROFILES
        for role in LICENSE_AUDIT_ROLES
    }
    actual_evidence_paths = set(evidence_hashes)
    expected_raw_paths: set[str] = set()
    for profile_id, _target, _idf_target in LICENSE_AUDIT_PROFILES:
        for role in LICENSE_AUDIT_ROLES:
            candidates = {
                "raw/%s--%s.%s" % (profile_id, role, extension)
                for extension in LICENSE_AUDIT_RAW_EXTENSIONS.values()
            }
            selected = actual_evidence_paths & candidates
            _require(
                len(selected) == 1,
                "license evidence must contain one exact raw SPDX document "
                "for each profile/role",
            )
            expected_raw_paths.update(selected)
    _require(
        actual_evidence_paths == expected_reviewed_paths | expected_raw_paths,
        "license evidence must contain the exact raw and normalized "
        "profile/role SPDX documents",
    )
    actual_relative = sorted(
        path.relative_to(evidence).as_posix()
        for path in evidence.rglob("*")
        if path.is_file() and path != receipt_path
    )
    _require(
        sorted(evidence_hashes) == actual_relative,
        "license evidence coverage is stale or incomplete",
    )
    for relative, digest in evidence_hashes.items():
        _require(
            isinstance(digest, str) and SHA256_RE.fullmatch(digest) is not None,
            "license evidence digest is invalid",
        )
        source = _audit_repo_file(
            evidence,
            relative,
            "license evidence",
        )
        _require(
            _sha256_path(source) == digest,
            "license evidence was changed after audit",
        )

    expected_identities = [
        {"profile_id": profile_id, "role": role}
        for profile_id, _target, _idf_target in LICENSE_AUDIT_PROFILES
        for role in LICENSE_AUDIT_ROLES
    ]
    _require(
        receipt["identities"]
        == sorted(
            expected_identities,
            key=lambda item: (item["profile_id"], item["role"]),
        ),
        "license evidence profile/role identities are incomplete",
    )

    lock = _audit_load_tool_lock(root)
    policy = _audit_load_policy(root, lock)
    _require(
        receipt["executed_artifacts"] == dict(sorted(lock["_artifact_hashes"].items())),
        "license evidence was generated by a different tool closure",
    )
    _audit_validate_execution_identity(
        receipt["execution_identity"],
        artifact_hashes=lock["_artifact_hashes"],
    )

    excluded = _audit_repo_file(
        root,
        lock["inputs"]["excluded_cves_path"],
        "excluded CVE input",
    )
    semantic_exclusions = "\n".join(
        line.split("#", 1)[0].strip()
        for line in excluded.read_text(encoding="utf-8").splitlines()
        if line.split("#", 1)[0].strip()
    )
    _require(
        semantic_exclusions in ("", "{}", "[]", "null", "~"),
        "excluded CVE input must remain semantically empty",
    )

    observed_context = _audit_observe_policy_v2_context(
        policy,
        repo_root=root,
        build_root=builds,
    )
    observations = observed_context["observed_inputs"]
    parsed_documents: dict[tuple[str, str], dict[str, Any]] = {}
    observed_documents: dict[tuple[str, str], dict[str, Any]] = {}
    for profile_id, _target, _idf_target in LICENSE_AUDIT_PROFILES:
        for role in LICENSE_AUDIT_ROLES:
            raw_candidates = [
                (
                    source_format,
                    "raw/%s--%s.%s"
                    % (
                        profile_id,
                        role,
                        extension,
                    ),
                )
                for source_format, extension in LICENSE_AUDIT_RAW_EXTENSIONS.items()
            ]
            selected = [
                (source_format, relative)
                for source_format, relative in raw_candidates
                if relative in evidence_hashes
            ]
            _require(
                len(selected) == 1,
                "license evidence raw SPDX identity is ambiguous",
            )
            expected_format, raw_relative = selected[0]
            raw_document, source_format = _audit_read_spdx_output(
                evidence / raw_relative,
                "raw license SPDX evidence",
            )
            _require(
                source_format == expected_format,
                "raw license SPDX evidence format disagrees with its filename",
            )
            _role_build, description_path, _compile_path, _map_path = (
                _audit_v2_role_paths(builds, _target, role)
            )
            description = _read_json(
                description_path,
                "%s/%s project description" % (profile_id, role),
            )
            raw_document = _audit_v2_validate_raw_envelope(
                raw_document,
                profile_id=profile_id,
                role=role,
                source_format=source_format,
                expected_document_name=description.get("project_name"),
            )
            identity = (profile_id, role)
            parsed_documents[identity] = raw_document
            observed_documents[identity] = {
                "packages": copy.deepcopy(raw_document["packages"]),
                "relationships": copy.deepcopy(raw_document["relationships"]),
            }

    validated = _audit_validate_policy_v2(
        policy,
        repo_root=root,
        observed_documents=observed_documents,
        observed_inputs=observations,
        manifest_evidence=observed_context["manifest_evidence"],
        toolchain_roots=observed_context["toolchain_roots"],
    )
    expected_reviewed = _audit_v2_reviewed_documents(
        parsed_documents=parsed_documents,
        validated=validated,
        policy=policy,
        repo_root=root,
        build_root=builds,
    )
    for identity, expected_document in sorted(expected_reviewed.items()):
        profile_id, role = identity
        relative = "spdx/%s--%s.spdx.json" % (profile_id, role)
        path = evidence / relative
        actual_document = _read_json(
            path,
            "normalized license SPDX evidence",
        )
        expected_bytes = (
            json.dumps(expected_document, indent=2, sort_keys=False) + "\n"
        )
        _require(
            actual_document == expected_document
            and path.read_text(encoding="utf-8", errors="strict")
            == expected_bytes,
            "normalized license SPDX evidence differs from exact v2 review",
        )

    frozen_union = _audit_v2_release_frozen_names(
        repo_root=root,
        build_root=builds,
        release_profile_ids=release_profile_order,
    )
    notice_records = _audit_v2_release_notice_records(
        validated,
        policy=policy,
        release_profile_ids=release_profile_order,
    )
    expected_notice = _audit_notice_v2(
        notice_records,
        repo_root=root,
        frozen_names=frozen_union,
    )
    _require(
        notice == expected_notice,
        "release notice differs from the exact schema-v2 reviewed notice",
    )

    current_inputs = {
        "release-tools.lock": _sha256_path(root / "firmware/release-tools.lock"),
        "license-policy.json": _sha256_path(
            root / lock["inputs"]["license_policy_path"]
        ),
        "excluded-cves": _sha256_path(excluded),
        **{
            "resolved-input/%s" % item["id"]: item["sha256"]
            for item in observations
        },
        **{
            "semantic/%s" % identifier: digest
            for identifier, digest in sorted(
                validated["semantic_sha256"].items()
            )
        },
        "semantic/retained_source_checkouts": (
            _audit_retained_source_digest(
                observed_context["retained_source_records"]
            )
        ),
    }
    current_inputs = dict(sorted(current_inputs.items()))
    _require(
        isinstance(receipt["input_sha256"], dict)
        and all(
            isinstance(name, str)
            and isinstance(digest, str)
            and SHA256_RE.fullmatch(digest) is not None
            for name, digest in receipt["input_sha256"].items()
        ),
        "license review input receipt is invalid",
    )
    _require(
        receipt["input_sha256"] == current_inputs,
        "license review evidence is stale for the current release inputs",
    )
    if bundle is not None or release is not None:
        _require(
            bundle is not None and release is not None,
            "packaged-build evidence comparison is incomplete",
        )
        _audit_verify_packaged_build(
            bundle=Path(bundle),
            release=release,
            build_root=builds,
        )


def _manifest(version: str, profile_id: str) -> dict[str, Any]:
    spec = PROFILE_SPECS[profile_id]
    return {
        "name": "PyBLE",
        "version": version,
        "new_install_prompt_erase": False,
        "new_install_improv_wait_time": 0,
        "builds": [
            {
                "chipFamily": spec["chip_family"],
                "parts": [
                    {
                        "path": "firmware.bin",
                        "offset": spec["base_offset"],
                    }
                ],
            }
        ],
    }


def _stage_profile_artifacts(
    *,
    profile_dir: Path,
    source_paths: dict[str, Path],
    version: str,
    profile_id: str,
    include_bootloader: bool,
    private: bool,
) -> None:
    profile_dir.mkdir(mode=0o700 if private else 0o777)
    manifest_path = profile_dir / "manifest.json"
    _write_json(manifest_path, _manifest(version, profile_id))
    copies = [
        (source_paths["install"], profile_dir / "firmware.bin"),
        (
            source_paths["partition-table"],
            profile_dir / "partition-table.bin",
        ),
        (source_paths["application"], profile_dir / "application.bin"),
    ]
    if include_bootloader:
        copies.insert(
            1,
            (source_paths["bootloader"], profile_dir / "bootloader.bin"),
        )
    for source, destination in copies:
        shutil.copyfile(source, destination)
    if private:
        manifest_path.chmod(0o600)
        for _source, destination in copies:
            destination.chmod(0o600)


def _stage_rp2_profile_artifacts(
    *,
    profile_dir: Path,
    source_paths: dict[str, Path],
    private: bool,
) -> None:
    """Stage only the verified UF2 installer and its raw resource image."""

    profile_dir.mkdir(mode=0o700 if private else 0o777)
    copies = (
        (source_paths["install"], profile_dir / "firmware.uf2"),
        (source_paths["resource-image"], profile_dir / "firmware.bin"),
    )
    for source, destination in copies:
        shutil.copyfile(source, destination)
        if private:
            destination.chmod(0o600)


def _release_schema(firmware_version: str | None = None) -> dict[str, Any]:
    source_version = firmware_version or "0.6.0"
    profile_order = _release_profile_order_for_version(source_version)
    schema_version = _release_metadata_schema_version_for_version(source_version)
    sha = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    commit = {"type": "string", "pattern": "^[0-9a-f]{40}$"}
    relative_path = {
        "type": "string",
        "minLength": 1,
        "pattern": r"^(?!/)(?!.*(?:^|/)\.\.?(?:/|$))(?!.*[\\?#])(?!.*://).+$",
    }
    artifact_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["path", "size", "sha256"],
        "properties": {
            "path": relative_path,
            "size": {"type": "integer", "minimum": 1},
            "sha256": sha,
        },
    }
    offset_artifact = copy.deepcopy(artifact_schema)
    offset_artifact["required"].append("offset")
    offset_artifact["properties"]["offset"] = {"type": "integer", "minimum": 0}
    component = copy.deepcopy(offset_artifact)
    component["required"].insert(0, "role")
    component["properties"]["role"] = {
        "enum": ["bootloader", "partition-table", "application"]
    }
    profile_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "chip_family",
            "requirements",
            "flash",
            "silicon_revision",
            "hil_status",
            "manifest",
            "install",
            "components",
        ],
        "properties": {
            "id": {"enum": list(profile_order)},
            "chip_family": {"enum": ["ESP32", "ESP32-S3"]},
            "silicon_revision": {
                "type": "object",
                "additionalProperties": False,
                "required": ["minimum_full", "maximum_full"],
                "properties": {
                    "minimum_full": {"type": "integer", "minimum": 0},
                    "maximum_full": {"type": "integer", "minimum": 0},
                },
            },
            "requirements": {
                "type": "object",
                "additionalProperties": False,
                "required": ["flash_size_bytes", "psram"],
                "properties": {
                    "flash_size_bytes": {"type": "integer", "minimum": 1},
                    "psram": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["required", "size_bytes", "type"],
                        "properties": {
                            "required": {"type": "boolean"},
                            "size_bytes": {"type": "integer", "minimum": 0},
                            "type": {"enum": ["not-required", "octal"]},
                        },
                    },
                },
            },
            "flash": {
                "type": "object",
                "additionalProperties": False,
                "required": ["mode", "frequency_hz"],
                "properties": {
                    "mode": {"const": "dio"},
                    "frequency_hz": {"type": "integer", "minimum": 1},
                },
            },
            "hil_status": {"enum": ["pending", "passed"]},
            "manifest": artifact_schema,
            "install": offset_artifact,
            "components": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": component,
            },
        },
    }
    if schema_version == 4:
        esp_profile_schemas = []
        for profile_id in V060_RELEASE_PROFILE_ORDER[:-1]:
            spec = PROFILE_SPECS[profile_id]
            esp_schema = copy.deepcopy(profile_schema)
            esp_schema["required"] = [
                "id",
                "target",
                "provisioning_kind",
                "chip_family",
                "requirements",
                "flash",
                "silicon_revision",
                "hil_status",
                "manifest",
                "install",
                "components",
            ]
            esp_schema["properties"]["id"] = {"const": profile_id}
            esp_schema["properties"]["target"] = {"const": spec["target"]}
            esp_schema["properties"]["provisioning_kind"] = {
                "const": "esp-web-serial"
            }
            esp_schema["properties"]["chip_family"] = {
                "const": spec["chip_family"]
            }
            esp_profile_schemas.append(esp_schema)

        uf2_install = copy.deepcopy(artifact_schema)
        uf2_install["required"].append("format")
        uf2_install["properties"]["format"] = {"const": "uf2"}
        resource_image = copy.deepcopy(artifact_schema)
        resource_image["required"].append("image_limit_bytes")
        resource_image["properties"]["image_limit_bytes"] = {
            "const": RP2_IMAGE_LIMIT_BYTES
        }
        rp2_profile_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "id",
                "target",
                "provisioning_kind",
                "board",
                "hil_status",
                "install",
                "resource_image",
            ],
            "properties": {
                "id": {"const": "rpi-pico2-w"},
                "target": {"const": "rpi-pico2-w"},
                "provisioning_kind": {"const": "verified-uf2-bootsel"},
                "board": {"const": "RPI_PICO2_W"},
                "hil_status": {"enum": ["pending", "passed"]},
                "install": uf2_install,
                "resource_image": resource_image,
            },
        }
        profile_collection_schema = {
            "type": "array",
            "minItems": len(profile_order),
            "maxItems": len(profile_order),
            "prefixItems": [*esp_profile_schemas, rp2_profile_schema],
            "items": False,
        }
    else:
        profile_collection_schema = {
            "type": "array",
            "minItems": len(profile_order),
            "maxItems": len(profile_order),
            "items": profile_schema,
        }
    tool = {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "version"],
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "version": {"type": "string", "minLength": 1},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://pyble.dev/firmware/release.schema.json",
        "title": "PyBLE firmware release metadata v%d" % schema_version,
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "identity",
            "provenance",
            "installer",
            "profiles",
            "documents",
        ],
        "properties": {
            "schema_version": {"const": schema_version},
            "identity": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "version",
                    "tag",
                    "agent_version",
                    "protocol_version",
                    "built_at",
                ],
                "properties": {
                    "version": {"type": "string", "pattern": SEMVER_RE.pattern},
                    "tag": {"type": "string", "pattern": r"^firmware-v.+$"},
                    "agent_version": {"type": "string", "minLength": 1},
                    "protocol_version": {"const": "PBLE/1"},
                    "built_at": {"type": "string", "pattern": UTC_RE.pattern},
                },
            },
            "provenance": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "pyble",
                    "micropython",
                    "esp_idf",
                    "patch_count",
                    "runner",
                    "tools",
                ],
                "properties": {
                    "pyble": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["commit", "clean"],
                        "properties": {
                            "commit": commit,
                            "clean": {"const": True},
                        },
                    },
                    "micropython": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["ref", "commit"],
                        "properties": {
                            "ref": {"type": "string", "minLength": 1},
                            "commit": commit,
                        },
                    },
                    "esp_idf": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["ref", "commit"],
                        "properties": {
                            "ref": {"type": "string", "minLength": 1},
                            "commit": commit,
                        },
                    },
                    "patch_count": {"type": "integer", "minimum": 0},
                    "runner": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["os", "architecture"],
                        "properties": {
                            "os": {"type": "string", "minLength": 1},
                            "architecture": {"type": "string", "minLength": 1},
                        },
                    },
                    "tools": {"type": "array", "minItems": 1, "items": tool},
                },
            },
            "installer": {
                "type": "object",
                "additionalProperties": False,
                "required": ["package", "version"],
                "properties": {
                    "package": {"const": "esp-web-tools"},
                    "version": {"const": "10.4.0"},
                },
            },
            "profiles": profile_collection_schema,
            "documents": {
                "type": "object",
                "additionalProperties": False,
                "required": list(DOCUMENT_KEYS),
                "properties": {key: artifact_schema for key in DOCUMENT_KEYS},
            },
        },
    }


def _validate_schema_document(schema: Any) -> None:
    _require(isinstance(schema, dict), "release.schema.json must be an object")
    _require(
        schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema",
        "release.schema.json must use JSON Schema draft 2020-12",
    )
    _require(schema.get("type") == "object", "release schema root must be an object")

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                _require(
                    node.get("additionalProperties") is False,
                    "every release-schema object must reject unknown keys",
                )
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(schema)


def _validate_no_placeholders(value: Any, label: str) -> None:
    if isinstance(value, str):
        _require(
            PLACEHOLDER_RE.fullmatch(value.strip()) is None,
            "%s contains a placeholder value" % label,
        )
    elif isinstance(value, dict):
        for key, child in value.items():
            _validate_no_placeholders(child, "%s.%s" % (label, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_no_placeholders(child, "%s[%d]" % (label, index))


def _validate_provenance(
    provenance: Any, lock: dict[str, Any] | None = None
) -> dict[str, Any]:
    value = _exact_keys(
        provenance,
        {"pyble", "micropython", "esp_idf", "patch_count", "runner", "tools"},
        "provenance",
    )
    pyble = _exact_keys(value["pyble"], {"commit", "clean"}, "provenance.pyble")
    _require(
        isinstance(pyble["commit"], str) and bool(COMMIT_RE.fullmatch(pyble["commit"])),
        "provenance PyBLE commit must be full lowercase 40-hex",
    )
    _require(pyble["clean"] is True, "release provenance must be clean")
    for name in ("micropython", "esp_idf"):
        item = _exact_keys(value[name], {"ref", "commit"}, "provenance.%s" % name)
        _require(
            isinstance(item["ref"], str) and bool(item["ref"]),
            "provenance %s ref is missing" % name,
        )
        _require(
            isinstance(item["commit"], str)
            and bool(COMMIT_RE.fullmatch(item["commit"])),
            "provenance %s commit must be full lowercase 40-hex" % name,
        )
        if lock is not None:
            _require(
                item["ref"] == lock[name]["ref"]
                and item["commit"] == lock[name]["commit"],
                "provenance %s pin disagrees with versions.lock" % name,
            )
    _require(
        isinstance(value["patch_count"], int)
        and not isinstance(value["patch_count"], bool)
        and value["patch_count"] >= 0,
        "patch_count must be a nonnegative integer",
    )
    runner = _exact_keys(value["runner"], {"os", "architecture"}, "provenance.runner")
    for key in ("os", "architecture"):
        _require(
            isinstance(runner[key], str) and bool(runner[key].strip()),
            "runner %s is missing" % key,
        )
    tools = value["tools"]
    _require(isinstance(tools, list) and bool(tools), "provenance tools are missing")
    names = []
    for index, tool in enumerate(tools):
        item = _exact_keys(tool, {"name", "version"}, "provenance.tools[%d]" % index)
        for key in ("name", "version"):
            _require(
                isinstance(item[key], str) and bool(item[key].strip()),
                "tool %s is empty" % key,
            )
        _require(
            PLACEHOLDER_RE.fullmatch(item["version"].strip()) is None,
            "tool %s has placeholder version" % item["name"],
        )
        names.append(item["name"])
    _require(
        names == sorted(names), "provenance tools must be lexicographically sorted"
    )
    _require(len(names) == len(set(names)), "provenance tool names must be unique")
    _validate_no_placeholders(value, "provenance")
    return value


def _validate_artifact_record(
    value: Any,
    label: str,
    *,
    offset: bool = False,
    component: bool = False,
) -> dict[str, Any]:
    expected = {"path", "size", "sha256"}
    if offset:
        expected.add("offset")
    if component:
        expected.add("role")
    record = _exact_keys(value, expected, label)
    _safe_relative_path(record["path"], label)
    _require(
        isinstance(record["size"], int)
        and not isinstance(record["size"], bool)
        and record["size"] > 0,
        "%s size must be a positive integer" % label,
    )
    _require(
        isinstance(record["sha256"], str)
        and bool(SHA256_RE.fullmatch(record["sha256"])),
        "%s sha256 must be lowercase 64-hex" % label,
    )
    if offset:
        _require(
            isinstance(record["offset"], int)
            and not isinstance(record["offset"], bool)
            and record["offset"] >= 0,
            "%s offset must be a nonnegative integer" % label,
        )
    if component:
        _require(record["role"] in ROLE_ORDER, "%s has unknown component role" % label)
    return record


def _verify_artifact(bundle: Path, record: dict[str, Any], label: str) -> Path:
    path = _path_below(bundle, record["path"], label)
    _require(path.is_file(), "%s file is missing" % label)
    _require(path.stat().st_size == record["size"], "%s size mismatch" % label)
    _require(_sha256_path(path) == record["sha256"], "%s SHA-256 mismatch" % label)
    return path


def _validate_manifest(
    value: Any,
    version: str,
    profile_id: str,
) -> None:
    manifest = _exact_keys(
        value,
        {
            "name",
            "version",
            "new_install_prompt_erase",
            "new_install_improv_wait_time",
            "builds",
        },
        "%s manifest" % profile_id,
    )
    _require(manifest["name"] == "PyBLE", "%s manifest name changed" % profile_id)
    _require(
        manifest["version"] == version, "%s manifest version mismatch" % profile_id
    )
    _require(
        manifest["new_install_prompt_erase"] is False,
        "%s manifest must retain destructive-new-install behavior" % profile_id,
    )
    _require(
        manifest["new_install_improv_wait_time"] == 0,
        "%s manifest Improv wait must be zero" % profile_id,
    )
    builds = manifest["builds"]
    _require(
        isinstance(builds, list) and len(builds) == 1,
        "%s manifest needs one build" % profile_id,
    )
    build = _exact_keys(
        builds[0], {"chipFamily", "parts"}, "%s manifest build" % profile_id
    )
    spec = PROFILE_SPECS[profile_id]
    _require(
        build["chipFamily"] == spec["chip_family"],
        "%s manifest chip family mismatch" % profile_id,
    )
    parts = build["parts"]
    _require(
        isinstance(parts, list) and len(parts) == 1,
        "%s manifest needs one part" % profile_id,
    )
    part = _exact_keys(parts[0], {"path", "offset"}, "%s manifest part" % profile_id)
    _require(
        _safe_relative_path(part["path"], "%s manifest part" % profile_id)
        == "firmware.bin",
        "%s manifest must reference its local merged firmware.bin" % profile_id,
    )
    _require(
        isinstance(part["offset"], int)
        and not isinstance(part["offset"], bool)
        and part["offset"] == spec["base_offset"],
        "%s manifest base offset mismatch" % profile_id,
    )


def _expected_bundle_files(
    profile_order: tuple[str, ...] = RELEASE_PROFILE_ORDER,
) -> list[str]:
    root_files = [
        "release.json",
        "release.schema.json",
        "SHA256SUMS",
        "THIRD_PARTY_LICENSES.txt",
        "RELEASE_NOTES.md",
        "RECOVERY.md",
        "HIL_REPORT.md",
    ]
    profile_files = []
    for profile_id in profile_order:
        spec = PROFILE_SPECS[profile_id]
        filenames = (
            ("firmware.uf2", "firmware.bin")
            if spec["port"] == "rp2"
            else (
                "manifest.json",
                "firmware.bin",
                "bootloader.bin",
                "partition-table.bin",
                "application.bin",
            )
        )
        profile_files.extend(
            "%s/%s" % (profile_id, filename) for filename in filenames
        )
    return sorted(root_files + profile_files)


def _validate_sha256sums(bundle: Path) -> None:
    path = bundle / "SHA256SUMS"
    _require(path.is_file(), "SHA256SUMS is missing")
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    actual_paths: list[str] = []
    for line_number, line in enumerate(lines, 1):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        _require(match is not None, "SHA256SUMS line %d is malformed" % line_number)
        digest, relative = match.groups()
        _safe_relative_path(relative, "SHA256SUMS line %d" % line_number)
        _require(relative != "SHA256SUMS", "SHA256SUMS must not cover itself")
        file_path = _path_below(bundle, relative, "SHA256SUMS entry")
        _require(file_path.is_file(), "SHA256SUMS names a missing file: %s" % relative)
        _require(
            _sha256_path(file_path) == digest,
            "SHA256SUMS digest mismatch: %s" % relative,
        )
        actual_paths.append(relative)
    expected = sorted(
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    )
    _require(actual_paths == expected, "SHA256SUMS coverage/order is not exact")


def _qualification_integer(
    value: Any,
    label: str,
    *,
    positive: bool = False,
) -> int:
    _require(
        type(value) is int and (value > 0 if positive else value >= 0),
        "%s must be a %s integer"
        % (label, "positive" if positive else "nonnegative"),
    )
    return value


def _qualification_baseline_match(
    path: Any,
    firmware_version: str | None,
) -> re.Match[str] | None:
    """Match the baseline location frozen by one retained source era."""

    if not isinstance(path, str):
        return None
    if firmware_version is None:
        patterns = (
            QUALIFICATION_BASELINE_RE,
            QUALIFICATION_V042_BASELINE_RE,
        )
    else:
        _firmware_release_core(firmware_version, "firmware source version")
        patterns = (
            (QUALIFICATION_V042_BASELINE_RE,)
            if firmware_version == "0.4.2"
            else (QUALIFICATION_BASELINE_RE,)
        )
    for pattern in patterns:
        matched = pattern.fullmatch(path)
        if matched is not None:
            return matched
    return None


def _qualification_derivation_for_version(
    firmware_version: str,
) -> dict[str, str]:
    source_core = _firmware_release_core(
        firmware_version,
        "firmware source version",
    )
    if source_core >= (0, 5, 0):
        return QUALIFICATION_DERIVATION_V3
    return QUALIFICATION_DERIVATION_V1


def _validate_qualification_policy(
    value: Any,
    *,
    repo_root: Path | None = None,
    firmware_version: str | None = None,
) -> dict[str, Any]:
    _require(isinstance(value, dict), "OI-1 qualification policy must be an object")
    raw_schema_version = value.get("schema_version")
    if firmware_version is not None:
        profile_order = _release_profile_order_for_version(firmware_version)
        policy_schema_version = (
            _qualification_policy_schema_version_for_version(firmware_version)
        )
    else:
        policy_schema_version = raw_schema_version
        _require(
            type(policy_schema_version) is int
            and policy_schema_version in (1, 2, 3),
            "OI-1 qualification policy schema_version is unsupported",
        )
        if policy_schema_version == 1:
            profile_order = HISTORICAL_V042_RELEASE_PROFILE_ORDER
        elif policy_schema_version == 2:
            profile_order = V05_RELEASE_PROFILE_ORDER
        else:
            profile_order = V060_RELEASE_PROFILE_ORDER

    policy_keys = {
        "schema_version",
        "qualification_scope",
        "profile_order",
        "workload",
        "derivation",
        "baseline_evidence",
        "profiles",
    }
    if policy_schema_version in (1, 2):
        policy_keys.add("deferred_profiles")
    policy = _exact_keys(
        value,
        policy_keys,
        "OI-1 qualification policy",
    )
    _require(
        type(policy["schema_version"]) is int
        and policy["schema_version"] == policy_schema_version,
        "OI-1 qualification policy schema_version does not match the source era",
    )
    expected_scope = (
        "v0.6.0-five-profile" if policy_schema_version == 3 else "pre-v1"
    )
    _require(
        policy["qualification_scope"] == expected_scope,
        "OI-1 qualification scope does not match the source era",
    )
    _require(
        policy["profile_order"] == list(profile_order),
        "OI-1 policy profile order must match the exact source-era release order",
    )
    if policy_schema_version in (1, 2):
        _require(
            policy["deferred_profiles"] == ["esp32-c3-4mb"],
            "OI-1 policy must defer exactly esp32-c3-4mb",
        )

    expected_workload = dict(QUALIFICATION_WORKLOAD)
    if policy_schema_version == 3:
        expected_workload.pop("required_put_window")
    workload = _exact_keys(
        policy["workload"],
        set(expected_workload),
        "OI-1 qualification workload",
    )
    for key, expected in expected_workload.items():
        actual = workload[key]
        if type(expected) is int:
            _require(
                type(actual) is int and actual == expected,
                "OI-1 workload %s has the wrong integer unit/value" % key,
            )
        else:
            _require(
                type(actual) is str and actual == expected,
                "OI-1 workload %s changed" % key,
            )

    derivation = _exact_keys(
        policy["derivation"],
        set(QUALIFICATION_DERIVATION),
        "OI-1 qualification derivation",
    )
    allowed_derivations = (
        (_qualification_derivation_for_version(firmware_version),)
        if firmware_version is not None
        else (
            QUALIFICATION_DERIVATION_V1,
            QUALIFICATION_DERIVATION_V2,
            QUALIFICATION_DERIVATION_V3,
        )
    )
    _require(
        all(type(value) is str for value in derivation.values())
        and any(derivation == expected for expected in allowed_derivations),
        "OI-1 qualification derivation does not match the firmware source era",
    )

    baseline = _exact_keys(
        policy["baseline_evidence"],
        {"path", "sha256"},
        "OI-1 baseline evidence",
    )
    baseline_path = baseline["path"]
    baseline_match = _qualification_baseline_match(
        baseline_path,
        firmware_version,
    )
    _require(
        baseline_match is not None,
        "OI-1 baseline evidence path is not source-commit scoped",
    )
    _require(
        isinstance(baseline["sha256"], str)
        and SHA256_RE.fullmatch(baseline["sha256"]) is not None,
        "OI-1 baseline evidence SHA-256 must be lowercase 64-hex",
    )

    profiles = policy["profiles"]
    _require(
        isinstance(profiles, list)
        and len(profiles) == len(profile_order),
        "OI-1 policy threshold profile count must match the release order",
    )
    _require(
        all(isinstance(item, dict) for item in profiles),
        "OI-1 policy profile entries must be objects",
    )
    _require(
        [item.get("profile_id") for item in profiles]
        == list(profile_order),
        "OI-1 policy threshold profile order/parity is invalid",
    )
    for profile_id, item in zip(profile_order, profiles):
        is_rp2 = PROFILE_SPECS[profile_id]["port"] == "rp2"
        entry_keys = (
            {"profile_id", "target", "resource_kind", "transport", "thresholds"}
            if policy_schema_version == 3
            else {"profile_id", "target", "thresholds"}
        )
        entry = _exact_keys(
            item,
            entry_keys,
            "OI-1 policy profile %s" % profile_id,
        )
        _require(
            entry["profile_id"] == profile_id
            and entry["target"] == PROFILE_SPECS[profile_id]["target"],
            "OI-1 policy profile identity mismatch for %s" % profile_id,
        )
        if policy_schema_version == 3:
            expected_resource_kind = "rp2" if is_rp2 else "esp-idf"
            _require(
                entry["resource_kind"] == expected_resource_kind,
                "OI-1 resource kind mismatch for %s" % profile_id,
            )
            transport = _exact_keys(
                entry["transport"],
                {
                    "required_att_mtu",
                    "required_put_window",
                    "required_chunk_bytes",
                    "link_facts_kind",
                },
                "OI-1 transport for %s" % profile_id,
            )
            _require(
                transport
                == {
                    "required_att_mtu": 247,
                    "required_put_window": 4 if is_rp2 else 8,
                    "required_chunk_bytes": 229,
                    "link_facts_kind": (
                        "btstack-observed-v1" if is_rp2 else "nimble-settled-v1"
                    ),
                },
                "OI-1 transport contract mismatch for %s" % profile_id,
            )
        threshold_keys = (
            RP2_QUALIFICATION_THRESHOLD_KEYS
            if policy_schema_version == 3 and is_rp2
            else QUALIFICATION_THRESHOLD_KEYS
        )
        thresholds = _exact_keys(
            entry["thresholds"],
            set(threshold_keys),
            "OI-1 thresholds for %s" % profile_id,
        )
        for key in threshold_keys:
            _qualification_integer(
                thresholds[key],
                "OI-1 %s threshold %s" % (profile_id, key),
                positive=True,
            )

    if repo_root is not None:
        evidence_path = _audit_repo_file(
            Path(repo_root),
            baseline_path,
            "OI-1 baseline evidence",
        )
        try:
            evidence_bytes = evidence_path.read_bytes()
            evidence_text = evidence_bytes.decode("utf-8", errors="strict")
            evidence_json = json.loads(evidence_text)
        except (OSError, UnicodeError, TypeError, ValueError) as exc:
            raise ReleaseError(
                "OI-1 baseline evidence is missing or invalid"
            ) from exc
        _require(
            isinstance(evidence_json, dict),
            "OI-1 baseline evidence must be a JSON object",
        )
        _require(
            _sha256_bytes(evidence_bytes) == baseline["sha256"],
            "OI-1 baseline evidence digest changed",
        )
        _require(
            evidence_bytes
            == (
                json.dumps(
                    evidence_json,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n"
            ).encode("utf-8"),
            "OI-1 baseline evidence is not canonical JSON",
        )
        _require(
            baseline_match is not None,
            "OI-1 baseline evidence path changed during validation",
        )
        _validate_qualification_baseline(
            evidence_json,
            baseline_match.group(1),
            policy,
            firmware_version=firmware_version,
        )
    return policy


def _load_qualification_policy(
    repo_root: Path,
) -> tuple[dict[str, Any], str]:
    root = Path(repo_root)
    firmware_version = _read_lock(root)["pyble"]["agent_version"]
    path = _audit_repo_file(
        root,
        QUALIFICATION_POLICY_RELATIVE,
        "OI-1 qualification policy",
    )
    try:
        source = path.read_bytes()
        document = json.loads(source.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise ReleaseError(
            "OI-1 qualification policy is missing or invalid"
        ) from exc
    return (
        _validate_qualification_policy(
            document,
            repo_root=root,
            firmware_version=firmware_version,
        ),
        _sha256_bytes(source),
    )


def _qualification_build_measurement(
    bundle: Path,
    profile_id: str,
) -> dict[str, int]:
    spec = PROFILE_SPECS[profile_id]
    directory = Path(bundle) / profile_id
    if spec["port"] == "rp2":
        try:
            firmware_bin_bytes = (directory / "firmware.bin").stat().st_size
        except OSError as exc:
            raise ReleaseError(
                "OI-1 RP2 resource image is missing for %s" % profile_id
            ) from exc
        headroom = spec["image_limit_bytes"] - firmware_bin_bytes
        _require(
            firmware_bin_bytes > 0 and headroom >= 0,
            "OI-1 RP2 resource image exceeds its bound for %s" % profile_id,
        )
        return {
            "firmware_bin_bytes": firmware_bin_bytes,
            "firmware_image_limit_bytes": spec["image_limit_bytes"],
            "firmware_image_headroom_bytes": headroom,
        }
    try:
        application = (directory / "application.bin").read_bytes()
        partition_table = (directory / "partition-table.bin").read_bytes()
    except OSError as exc:
        raise ReleaseError(
            "OI-1 build inputs are missing for %s" % profile_id
        ) from exc
    entries = _parse_partition_table(
        partition_table,
        spec,
        len(application),
        "%s OI-1 partition table" % profile_id,
    )
    factories = [
        entry
        for entry in entries
        if entry["type"] == 0 and entry["subtype"] == 0
    ]
    _require(
        len(factories) == 1,
        "%s OI-1 build must contain one factory partition" % profile_id,
    )
    factory_bytes = factories[0]["size"]
    application_bytes = len(application)
    headroom = factory_bytes - application_bytes
    _require(
        headroom >= 0,
        "%s OI-1 application headroom is negative" % profile_id,
    )
    return {
        "application_image_bytes": application_bytes,
        "factory_partition_bytes": factory_bytes,
        "application_headroom_bytes": headroom,
    }


def _validate_qualification_build(
    value: Any,
    expected: dict[str, int],
    thresholds: dict[str, int],
    profile_id: str,
) -> dict[str, int]:
    if PROFILE_SPECS[profile_id]["port"] == "rp2":
        build = _exact_keys(
            value,
            {
                "firmware_bin_bytes",
                "firmware_image_limit_bytes",
                "firmware_image_headroom_bytes",
            },
            "OI-1 build for %s" % profile_id,
        )
        for key in build:
            _qualification_integer(
                build[key],
                "OI-1 %s build %s" % (profile_id, key),
            )
        _require(
            build == expected
            and build["firmware_image_limit_bytes"] == RP2_IMAGE_LIMIT_BYTES
            and build["firmware_image_headroom_bytes"]
            == build["firmware_image_limit_bytes"] - build["firmware_bin_bytes"],
            "OI-1 RP2 build measurements disagree for %s" % profile_id,
        )
        _require(
            build["firmware_bin_bytes"] <= thresholds["firmware_bin_max_bytes"]
            and build["firmware_image_headroom_bytes"]
            >= thresholds["firmware_image_headroom_min_bytes"],
            "OI-1 RP2 image threshold failed for %s" % profile_id,
        )
        return build
    build = _exact_keys(
        value,
        {
            "application_image_bytes",
            "factory_partition_bytes",
            "application_headroom_bytes",
        },
        "OI-1 build for %s" % profile_id,
    )
    for key in build:
        _qualification_integer(
            build[key],
            "OI-1 %s build %s" % (profile_id, key),
        )
    _require(
        build == expected,
        "OI-1 build measurements disagree with bundled bytes for %s" % profile_id,
    )
    _require(
        build["application_headroom_bytes"]
        == build["factory_partition_bytes"] - build["application_image_bytes"],
        "OI-1 application headroom arithmetic failed for %s" % profile_id,
    )
    _require(
        build["application_image_bytes"]
        <= thresholds["application_image_max_bytes"],
        "OI-1 application image ceiling exceeded for %s" % profile_id,
    )
    _require(
        build["application_headroom_bytes"]
        >= thresholds["application_headroom_min_bytes"],
        "OI-1 application headroom floor crossed for %s" % profile_id,
    )
    return build


def _qualification_integer_array(
    value: Any,
    count: int,
    label: str,
    *,
    positive: bool = False,
    exact: int | None = None,
) -> list[int]:
    _require(
        isinstance(value, list) and len(value) == count,
        "%s must contain exactly %d samples" % (label, count),
    )
    result = []
    for index, item in enumerate(value):
        integer = _qualification_integer(
            item,
            "%s[%d]" % (label, index),
            positive=positive,
        )
        if exact is not None:
            _require(
                integer == exact,
                "%s[%d] has the wrong workload quantity" % (label, index),
            )
        result.append(integer)
    return result


def _validate_heap_snapshot(
    value: Any,
    label: str,
    *,
    rp2: bool = False,
) -> dict[str, int]:
    snapshot = _exact_keys(
        value,
        (
            {"gc_free_bytes", "gc_allocated_bytes"}
            if rp2
            else {
                "gc_free_bytes",
                "gc_allocated_bytes",
                "idf_internal_free_bytes",
                "idf_internal_largest_block_bytes",
                "idf_internal_minimum_free_bytes",
            }
        ),
        label,
    )
    for key in snapshot:
        _qualification_integer(snapshot[key], "%s.%s" % (label, key))
    return snapshot


def _validate_transfer_link_facts(
    value: Any,
    profile_id: str,
) -> dict[str, Any]:
    """Validate the exact, redacted ADR-0027 settlement record."""

    if PROFILE_SPECS[profile_id]["port"] == "rp2":
        facts = _exact_keys(
            value,
            {
                "ble_host",
                "observed_att_mtu",
                "observed_window",
                "observed_chunk_bytes",
                "console_tx_budget_ms",
            },
            "OI-1 RP2 transfer facts for %s" % profile_id,
        )
        _require(
            facts["ble_host"] == "btstack"
            and type(facts["observed_att_mtu"]) is int
            and facts["observed_att_mtu"] == 247
            and type(facts["observed_window"]) is int
            and facts["observed_window"] == 4
            and type(facts["observed_chunk_bytes"]) is int
            and facts["observed_chunk_bytes"] == 229
            and type(facts["console_tx_budget_ms"]) is int
            and facts["console_tx_budget_ms"] > 0,
            "OI-1 RP2 BTstack transport facts are invalid for %s" % profile_id,
        )
        return facts

    facts = _exact_keys(
        value,
        {"dle", "phy", "connection_parameters", "tx_mbuf_starve_count"},
        "OI-1 transfer link facts for %s" % profile_id,
    )

    dle = _exact_keys(
        facts["dle"],
        {"request_attempts", "max_tx_octets", "max_tx_time_us"},
        "OI-1 DLE facts for %s" % profile_id,
    )
    dle_attempts = _qualification_integer(
        dle["request_attempts"],
        "OI-1 DLE request attempts for %s" % profile_id,
        positive=True,
    )
    _require(
        dle_attempts <= 4,
        "OI-1 DLE request attempts exceed the bound for %s" % profile_id,
    )
    max_tx_octets = _qualification_integer(
        dle["max_tx_octets"],
        "OI-1 DLE max_tx_octets for %s" % profile_id,
        positive=True,
    )
    _require(
        max_tx_octets >= 244,
        "OI-1 DLE did not settle for %s" % profile_id,
    )
    _qualification_integer(
        dle["max_tx_time_us"],
        "OI-1 DLE max_tx_time_us for %s" % profile_id,
        positive=True,
    )

    phy = _exact_keys(
        facts["phy"],
        {
            "required_2m",
            "request_attempts",
            "updates",
            "settled_tx",
            "settled_rx",
        },
        "OI-1 PHY facts for %s" % profile_id,
    )
    required_2m = profile_id in (
        "esp32-s3-n16r8",
        "waveshare-esp32-s3-lcd-147b",
    )
    _require(
        profile_id in RELEASE_PROFILE_ORDER
        and type(phy["required_2m"]) is bool
        and phy["required_2m"] is required_2m,
        "OI-1 PHY requirement does not match profile %s" % profile_id,
    )
    phy_attempts = _qualification_integer(
        phy["request_attempts"],
        "OI-1 PHY request attempts for %s" % profile_id,
    )
    phy_updates = phy["updates"]
    _require(
        isinstance(phy_updates, list),
        "OI-1 PHY updates must be an array for %s" % profile_id,
    )
    for index, raw_update in enumerate(phy_updates):
        update = _exact_keys(
            raw_update,
            {"status", "tx", "rx"},
            "OI-1 PHY update %d for %s" % (index, profile_id),
        )
        for key in update:
            _qualification_integer(
                update[key],
                "OI-1 PHY update %d %s for %s"
                % (index, key, profile_id),
            )
    settled_tx = _qualification_integer(
        phy["settled_tx"],
        "OI-1 settled PHY TX for %s" % profile_id,
    )
    settled_rx = _qualification_integer(
        phy["settled_rx"],
        "OI-1 settled PHY RX for %s" % profile_id,
    )
    if required_2m:
        _require(
            1 <= phy_attempts <= 4 and bool(phy_updates),
            "OI-1 2M PHY attempts/updates are incomplete for %s" % profile_id,
        )
        final_phy = phy_updates[-1]
        _require(
            final_phy["status"] == 0
            and final_phy["tx"] == 2
            and final_phy["rx"] == 2
            and settled_tx == 2
            and settled_rx == 2,
            "OI-1 2M PHY did not settle for %s" % profile_id,
        )
    else:
        _require(
            phy_attempts == 0
            and phy_updates == []
            and settled_tx == 0
            and settled_rx == 0,
            "OI-1 classic PHY must retain the compiled-out shape",
        )

    conn = _exact_keys(
        facts["connection_parameters"],
        {"request_return_codes", "updates", "settled_interval_units"},
        "OI-1 connection-parameter facts for %s" % profile_id,
    )
    return_codes = conn["request_return_codes"]
    _require(
        isinstance(return_codes, list) and 1 <= len(return_codes) <= 3,
        "OI-1 connection-parameter requests must contain 1..3 entries for %s"
        % profile_id,
    )
    for index, item in enumerate(return_codes):
        _qualification_integer(
            item,
            "OI-1 connection-parameter return code %d for %s"
            % (index, profile_id),
        )
    updates = conn["updates"]
    _require(
        isinstance(updates, list) and bool(updates),
        "OI-1 connection-parameter updates are missing for %s" % profile_id,
    )
    for index, raw_update in enumerate(updates):
        update = _exact_keys(
            raw_update,
            {"status", "interval_units"},
            "OI-1 connection-parameter update %d for %s"
            % (index, profile_id),
        )
        for key in update:
            _qualification_integer(
                update[key],
                "OI-1 connection-parameter update %d %s for %s"
                % (index, key, profile_id),
            )
    settled_interval = _qualification_integer(
        conn["settled_interval_units"],
        "OI-1 settled connection interval for %s" % profile_id,
        positive=True,
    )
    final_update = updates[-1]
    _require(
        final_update["status"] == 0
        and 12 <= final_update["interval_units"] <= 24
        and settled_interval == final_update["interval_units"],
        "OI-1 connection parameters did not settle for %s" % profile_id,
    )
    _qualification_integer(
        facts["tx_mbuf_starve_count"],
        "OI-1 TX-mbuf starvation count for %s" % profile_id,
    )
    return facts


def _validate_qualification_observation(
    value: Any,
    thresholds: dict[str, int] | None,
    profile_id: str,
    *,
    firmware_version: str,
) -> dict[str, Any]:
    is_rp2 = PROFILE_SPECS[profile_id]["port"] == "rp2"
    observation_keys = {
        "observed_att_mtu",
        "observed_window",
        "observed_chunk_bytes",
        "reset_to_service_advertisement_ms",
        "heap_default_free_post_hello_bytes",
        "heap_post_hello",
        "put_unique_committed_bytes",
        "put_duration_ns",
        "put_committed_goodput_bytes_per_second",
        "get_unique_verified_bytes",
        "get_duration_ns",
        "get_verified_goodput_bytes_per_second",
        "put_retransmitted_chunks",
        "put_retransmitted_bytes",
        "get_retransmitted_chunks",
        "get_retransmitted_bytes",
        "roundtrip_integrity_verified",
        "get_offset_sequences_validated",
        "roundtrip_unexpected_disconnects",
        "roundtrip_integrity_failures",
        "heap_post_roundtrip",
        "reliability",
        "heap_post_reliability",
        "physical_power_cycle_advertising",
        "raw_log_sha256",
    }
    requires_link_facts = (
        _firmware_release_core(firmware_version, "firmware source version")
        >= (0, 5, 0)
    )
    if requires_link_facts:
        observation_keys.add("transfer_link_facts")
    observation = _exact_keys(
        value,
        observation_keys,
        "OI-1 observation for %s" % profile_id,
    )
    if requires_link_facts:
        _validate_transfer_link_facts(
            observation["transfer_link_facts"],
            profile_id,
        )
    transport = {
        "observed_att_mtu": QUALIFICATION_WORKLOAD["required_att_mtu"],
        "observed_window": (
            4 if is_rp2 else QUALIFICATION_WORKLOAD["required_put_window"]
        ),
        "observed_chunk_bytes": QUALIFICATION_WORKLOAD["required_chunk_bytes"],
    }
    for key, expected in transport.items():
        _require(
            type(observation[key]) is int and observation[key] == expected,
            "OI-1 %s is not the required observed transport value" % key,
        )

    resets = _qualification_integer_array(
        observation["reset_to_service_advertisement_ms"],
        QUALIFICATION_WORKLOAD["reset_samples"],
        "OI-1 reset-to-advertisement samples",
    )
    if thresholds is not None:
        _require(
            max(resets)
            <= thresholds["reset_to_service_advertisement_max_ms"],
            "OI-1 reset-to-advertisement ceiling exceeded for %s"
            % profile_id,
        )
    _qualification_integer_array(
        observation["heap_default_free_post_hello_bytes"],
        QUALIFICATION_WORKLOAD["post_hello_heap_samples"],
        "OI-1 default-heap diagnostics",
    )

    heap_groups: list[dict[str, int]] = []
    for key, count in (
        ("heap_post_hello", QUALIFICATION_WORKLOAD["post_hello_heap_samples"]),
        (
            "heap_post_roundtrip",
            QUALIFICATION_WORKLOAD["post_roundtrip_heap_samples"],
        ),
    ):
        samples = observation[key]
        _require(
            isinstance(samples, list) and len(samples) == count,
            "OI-1 %s must contain exactly %d snapshots" % (key, count),
        )
        heap_groups.extend(
            _validate_heap_snapshot(
                snapshot,
                "OI-1 %s[%d]" % (key, index),
                rp2=is_rp2,
            )
            for index, snapshot in enumerate(samples)
        )
    heap_groups.append(
        _validate_heap_snapshot(
            observation["heap_post_reliability"],
            "OI-1 heap_post_reliability",
            rp2=is_rp2,
        )
    )
    heap_thresholds = {
        "gc_free_bytes": "gc_free_min_bytes",
    }
    if not is_rp2:
        heap_thresholds.update(
            {
                "idf_internal_free_bytes": "idf_internal_free_min_bytes",
                "idf_internal_largest_block_bytes": (
                    "idf_internal_largest_block_min_bytes"
                ),
                "idf_internal_minimum_free_bytes": (
                    "idf_internal_minimum_free_min_bytes"
                ),
            }
        )
    _require(
        len(heap_groups)
        == (
            QUALIFICATION_WORKLOAD["post_hello_heap_samples"]
            + QUALIFICATION_WORKLOAD["post_roundtrip_heap_samples"]
            + QUALIFICATION_WORKLOAD["post_reliability_heap_samples"]
        ),
        "OI-1 heap observation count changed",
    )
    if thresholds is not None:
        for metric, threshold_key in heap_thresholds.items():
            _require(
                min(snapshot[metric] for snapshot in heap_groups)
                >= thresholds[threshold_key],
                "OI-1 %s floor crossed for %s" % (metric, profile_id),
            )

    count = QUALIFICATION_WORKLOAD["roundtrip_samples"]
    payload_bytes = QUALIFICATION_WORKLOAD["roundtrip_payload_bytes"]
    for prefix, unique_key, duration_key, goodput_key, threshold_key in (
        (
            "PUT",
            "put_unique_committed_bytes",
            "put_duration_ns",
            "put_committed_goodput_bytes_per_second",
            "put_committed_goodput_min_bytes_per_second",
        ),
        (
            "GET",
            "get_unique_verified_bytes",
            "get_duration_ns",
            "get_verified_goodput_bytes_per_second",
            "get_verified_goodput_min_bytes_per_second",
        ),
    ):
        _qualification_integer_array(
            observation[unique_key],
            count,
            "OI-1 %s unique bytes" % prefix,
            exact=payload_bytes,
        )
        durations = _qualification_integer_array(
            observation[duration_key],
            count,
            "OI-1 %s duration ns" % prefix,
            positive=True,
        )
        goodputs = _qualification_integer_array(
            observation[goodput_key],
            count,
            "OI-1 %s goodput" % prefix,
        )
        recomputed = [
            (payload_bytes * 1_000_000_000) // duration
            for duration in durations
        ]
        _require(
            goodputs == recomputed,
            "OI-1 %s goodput arithmetic mismatch for %s"
            % (prefix, profile_id),
        )
        if thresholds is not None:
            _require(
                min(goodputs) >= thresholds[threshold_key],
                "OI-1 %s goodput floor crossed for %s"
                % (prefix, profile_id),
            )

    for key in (
        "put_retransmitted_chunks",
        "put_retransmitted_bytes",
        "get_retransmitted_chunks",
        "get_retransmitted_bytes",
    ):
        _qualification_integer_array(
            observation[key],
            count,
            "OI-1 %s" % key,
        )
    exact_scalars = {
        "roundtrip_integrity_verified": count,
        "get_offset_sequences_validated": count,
        "roundtrip_unexpected_disconnects": 0,
        "roundtrip_integrity_failures": 0,
    }
    for key, expected in exact_scalars.items():
        _require(
            type(observation[key]) is int and observation[key] == expected,
            "OI-1 %s does not match the frozen workload" % key,
        )

    reliability = _exact_keys(
        observation["reliability"],
        {
            "attempted_files",
            "completed_files",
            "verified_files",
            "bytes_per_file",
            "total_payload_bytes",
            "unexpected_disconnects",
            "integrity_failures",
            "failed_statuses",
            "retransmitted_chunks",
            "retransmitted_bytes",
            "rewinds",
        },
        "OI-1 reliability observation",
    )
    for key in reliability:
        _qualification_integer(
            reliability[key],
            "OI-1 reliability %s" % key,
        )
    reliability_exact = {
        "attempted_files": QUALIFICATION_WORKLOAD["reliability_files"],
        "completed_files": QUALIFICATION_WORKLOAD["reliability_files"],
        "verified_files": QUALIFICATION_WORKLOAD["reliability_files"],
        "bytes_per_file": QUALIFICATION_WORKLOAD["reliability_file_bytes"],
        "total_payload_bytes": (
            QUALIFICATION_WORKLOAD["reliability_files"]
            * QUALIFICATION_WORKLOAD["reliability_file_bytes"]
        ),
        "unexpected_disconnects": 0,
        "integrity_failures": 0,
        "failed_statuses": 0,
    }
    _require(
        all(
            reliability[key] == expected
            for key, expected in reliability_exact.items()
        ),
        "OI-1 reliability workload failed for %s" % profile_id,
    )
    _require(
        observation["physical_power_cycle_advertising"] == "passed",
        "OI-1 physical power-cycle advertising check failed for %s" % profile_id,
    )
    _require(
        isinstance(observation["raw_log_sha256"], str)
        and SHA256_RE.fullmatch(observation["raw_log_sha256"]) is not None,
        "OI-1 raw log digest must be lowercase 64-hex",
    )
    return observation


def _validate_baseline_build(
    value: Any,
    profile_id: str,
) -> dict[str, int]:
    if PROFILE_SPECS[profile_id]["port"] == "rp2":
        build = _exact_keys(
            value,
            {
                "firmware_bin_bytes",
                "firmware_image_limit_bytes",
                "firmware_image_headroom_bytes",
            },
            "OI-1 baseline build for %s" % profile_id,
        )
        for key in build:
            _qualification_integer(
                build[key],
                "OI-1 baseline %s build %s" % (profile_id, key),
            )
        _require(
            build["firmware_image_limit_bytes"] == RP2_IMAGE_LIMIT_BYTES
            and build["firmware_image_headroom_bytes"]
            == build["firmware_image_limit_bytes"] - build["firmware_bin_bytes"],
            "OI-1 baseline RP2 headroom arithmetic failed for %s" % profile_id,
        )
        return build
    build = _exact_keys(
        value,
        {
            "application_image_bytes",
            "factory_partition_bytes",
            "application_headroom_bytes",
        },
        "OI-1 baseline build for %s" % profile_id,
    )
    for key in build:
        _qualification_integer(
            build[key],
            "OI-1 baseline %s build %s" % (profile_id, key),
        )
    _require(
        build["application_headroom_bytes"]
        == build["factory_partition_bytes"] - build["application_image_bytes"],
        "OI-1 baseline application headroom arithmetic failed for %s"
        % profile_id,
    )
    return build


def _derived_qualification_thresholds(
    build: dict[str, int],
    observation: dict[str, Any],
    *,
    firmware_version: str = "0.4.2",
) -> dict[str, int]:
    heap_samples = (
        observation["heap_post_hello"]
        + observation["heap_post_roundtrip"]
        + [observation["heap_post_reliability"]]
    )

    def floor_min(metric: str, quantum: int) -> int:
        return (
            min(sample[metric] for sample in heap_samples) // quantum
        ) * quantum

    derivation = _qualification_derivation_for_version(firmware_version)
    reset_max = max(observation["reset_to_service_advertisement_ms"])
    put_min = min(
        observation["put_committed_goodput_bytes_per_second"]
    )
    get_min = min(
        observation["get_verified_goodput_bytes_per_second"]
    )
    if derivation == QUALIFICATION_DERIVATION_V2:
        reset_max += 300
    if derivation in (
        QUALIFICATION_DERIVATION_V2,
        QUALIFICATION_DERIVATION_V3,
    ):
        put_min = (put_min * 95) // 100
        get_min = (get_min * 95) // 100
    reset_threshold = (
        3000
        if derivation == QUALIFICATION_DERIVATION_V3
        else ((reset_max + 9) // 10) * 10
    )

    image_thresholds = (
        {
            "firmware_bin_max_bytes": build["firmware_bin_bytes"],
            "firmware_image_headroom_min_bytes": build[
                "firmware_image_headroom_bytes"
            ],
        }
        if "firmware_bin_bytes" in build
        else {
            "application_image_max_bytes": build["application_image_bytes"],
            "application_headroom_min_bytes": build[
                "application_headroom_bytes"
            ],
        }
    )
    derived = {
        **image_thresholds,
        "gc_free_min_bytes": floor_min("gc_free_bytes", 1024),
        "reset_to_service_advertisement_max_ms": reset_threshold,
        "put_committed_goodput_min_bytes_per_second": (
            put_min // 100
        )
        * 100,
        "get_verified_goodput_min_bytes_per_second": (
            get_min // 100
        )
        * 100,
    }
    if "firmware_bin_bytes" not in build:
        derived.update(
            {
                "idf_internal_free_min_bytes": floor_min(
                    "idf_internal_free_bytes", 1024
                ),
                "idf_internal_largest_block_min_bytes": floor_min(
                    "idf_internal_largest_block_bytes", 1024
                ),
                "idf_internal_minimum_free_min_bytes": floor_min(
                    "idf_internal_minimum_free_bytes", 1024
                ),
            }
        )
    for key, value in derived.items():
        _qualification_integer(
            value,
            "derived OI-1 threshold %s" % key,
            positive=True,
        )
    return derived


def _validate_qualification_baseline(
    value: Any,
    path_source_commit: str,
    policy: dict[str, Any],
    *,
    firmware_version: str | None = None,
) -> dict[str, Any]:
    profile_order = (
        _release_profile_order_for_version(firmware_version)
        if firmware_version is not None
        else tuple(policy["profile_order"])
    )
    schema_version = 2 if tuple(profile_order) == V060_RELEASE_PROFILE_ORDER else 1
    baseline = _exact_keys(
        value,
        {
            "schema_version",
            "measurement_contract",
            "source_commit",
            "firmware_version",
            "created_at",
            "profile_order",
            "profiles",
        },
        "OI-1 baseline evidence",
    )
    _require(
        type(baseline["schema_version"]) is int
        and baseline["schema_version"] == schema_version,
        "OI-1 baseline schema_version does not match the source era",
    )
    _require(
        baseline["measurement_contract"]
        == (
            "oi1-five-profile-v1"
            if schema_version == 2
            else "oi1-pre-v1-v1"
        ),
        "OI-1 baseline measurement contract changed",
    )
    _require(
        isinstance(baseline["source_commit"], str)
        and COMMIT_RE.fullmatch(baseline["source_commit"]) is not None
        and baseline["source_commit"] == path_source_commit,
        "OI-1 baseline source commit disagrees with its filename",
    )
    _require(
        isinstance(baseline["firmware_version"], str)
        and SEMVER_RE.fullmatch(baseline["firmware_version"]) is not None,
        "OI-1 baseline firmware version must be canonical SemVer",
    )
    if firmware_version is not None:
        source_core = _firmware_release_core(
            firmware_version,
            "firmware source version",
        )
        baseline_core = _firmware_release_core(
            baseline["firmware_version"],
            "OI-1 baseline firmware version",
        )
        _require(
            baseline_core <= source_core,
            "OI-1 baseline firmware version is newer than the source release",
        )
        if source_core >= (0, 5, 0):
            _require(
                baseline_core >= (0, 5, 0),
                "OI-1 baseline predates the v0.5.0 source-era floor",
            )
    _require(
        isinstance(baseline["created_at"], str)
        and UTC_RE.fullmatch(baseline["created_at"]) is not None,
        "OI-1 baseline created_at must be UTC RFC3339",
    )
    _require(
        baseline["profile_order"] == list(profile_order),
        "OI-1 baseline profile order must match the source-era release order",
    )
    profiles = baseline["profiles"]
    _require(
        isinstance(profiles, list)
        and len(profiles) == len(profile_order)
        and all(isinstance(item, dict) for item in profiles),
        "OI-1 baseline profile count must match the release order",
    )
    _require(
        [item.get("profile_id") for item in profiles]
        == list(profile_order),
        "OI-1 baseline profile order/parity is invalid",
    )
    policy_by_id = {
        entry["profile_id"]: entry for entry in policy["profiles"]
    }
    for profile_id, raw_profile in zip(profile_order, profiles):
        spec = PROFILE_SPECS[profile_id]
        is_rp2 = spec["port"] == "rp2"
        profile_keys = {
            "profile_id",
            "target",
            "board_manufacturer",
            "board_model",
            "module_marking",
            "device_flash_capacity_bytes",
            "device_psram_capacity_bytes",
            "environment",
            "oi1_build",
            "oi1_observation",
        }
        if schema_version == 2:
            profile_keys.add("resource_kind")
            profile_keys.update(
                {"install_sha256", "resource_image_sha256"}
                if is_rp2
                else {"install_sha256", "manifest_sha256"}
            )
        else:
            profile_keys.update({"firmware_sha256", "manifest_sha256"})
        profile = _exact_keys(
            raw_profile,
            profile_keys,
            "OI-1 baseline profile %s" % profile_id,
        )
        _require(
            profile["profile_id"] == profile_id
            and profile["target"] == spec["target"],
            "OI-1 baseline profile identity mismatch for %s" % profile_id,
        )
        if schema_version == 2:
            _require(
                profile["resource_kind"] == ("rp2" if is_rp2 else "esp-idf"),
                "OI-1 baseline resource kind mismatch for %s" % profile_id,
            )
        for field in (
            "board_manufacturer",
            "board_model",
            "module_marking",
        ):
            _require(
                isinstance(profile[field], str)
                and bool(profile[field].strip()),
                "OI-1 baseline %s is empty for %s" % (field, profile_id),
            )
        _require(
            type(profile["device_flash_capacity_bytes"]) is int
            and profile["device_flash_capacity_bytes"]
            == spec["flash_size_bytes"]
            and type(profile["device_psram_capacity_bytes"]) is int
            and profile["device_psram_capacity_bytes"]
            == spec["psram"]["size_bytes"],
            "OI-1 baseline physical topology mismatch for %s" % profile_id,
        )
        digest_fields = (
            (
                ("install_sha256", "resource_image_sha256")
                if is_rp2
                else ("install_sha256", "manifest_sha256")
            )
            if schema_version == 2
            else ("firmware_sha256", "manifest_sha256")
        )
        for field in digest_fields:
            _require(
                isinstance(profile[field], str)
                and SHA256_RE.fullmatch(profile[field]) is not None,
                "OI-1 baseline %s is not lowercase 64-hex" % field,
            )
        environment = _exact_keys(
            profile["environment"],
            {
                "desktop_os",
                "ble_backend",
                "ble_adapter",
                "python_version",
            },
            "OI-1 baseline environment for %s" % profile_id,
        )
        for key, item in environment.items():
            _require(
                isinstance(item, str) and bool(item.strip()),
                "OI-1 baseline environment %s is empty for %s"
                % (key, profile_id),
            )
        build = _validate_baseline_build(
            profile["oi1_build"],
            profile_id,
        )
        observation = _validate_qualification_observation(
            profile["oi1_observation"],
            None,
            profile_id,
            firmware_version=baseline["firmware_version"],
        )
        _require(
            policy_by_id[profile_id]["thresholds"]
            == _derived_qualification_thresholds(
                build,
                observation,
                firmware_version=(
                    firmware_version or baseline["firmware_version"]
                ),
            ),
            "OI-1 policy thresholds were not derived from baseline %s"
            % profile_id,
        )
    return baseline


def _parse_hil_report(text: str) -> dict[str, Any]:
    match_objects = list(HIL_MARKER_RE.finditer(text))
    matches = HIL_MARKER_RE.findall(text)
    all_markers = HIL_ANY_MARKER_RE.findall(text)
    _require(
        len(matches) == 1 and len(all_markers) == 1,
        "HIL_REPORT.md must contain exactly one supported PYBLE_HIL_RECORDS marker",
    )
    marker_version, encoded_payload = matches[0]
    marker_match = match_objects[0]
    if marker_version in ("3", "4", "5"):
        _require(
            text[: marker_match.start()] == HIL_REPORT_SHELL_PREFIX
            and text[marker_match.end() :] == HIL_REPORT_SHELL_SUFFIX,
            "current HIL_REPORT.md surrounding shell changed",
        )
    try:
        payload = json.loads(encoded_payload)
    except ValueError as exc:
        raise ReleaseError("HIL_REPORT.md embedded records are invalid JSON") from exc
    schema_version = payload.get("schema_version") if isinstance(payload, dict) else None
    expected_keys = {
        "schema_version",
        "candidate_release_json_sha256",
        "qualification_policy_sha256",
        "qualification_policy",
        "records",
    }
    if marker_version in ("3", "4"):
        expected_keys.add("waveshare_lcd147b_qualification")
    elif marker_version == "5":
        expected_keys.update(
            {
                "waveshare_lcd147b_qualification",
                "esp32_c3_qualification",
                "rpi_pico2_w_qualification",
            }
        )
    payload = _exact_keys(
        payload,
        expected_keys,
        "HIL records",
    )
    _require(
        type(schema_version) is int and schema_version == int(marker_version),
        "HIL record schema version disagrees with its marker",
    )
    candidate_digest = payload["candidate_release_json_sha256"]
    _require(
        isinstance(candidate_digest, str),
        "HIL candidate release digest must be a string",
    )
    _require(
        isinstance(payload["qualification_policy_sha256"], str)
        and SHA256_RE.fullmatch(payload["qualification_policy_sha256"]) is not None,
        "HIL qualification policy digest must be lowercase 64-hex",
    )
    _validate_qualification_policy(payload["qualification_policy"])
    _require(isinstance(payload.get("records"), list), "HIL records array is missing")
    return payload


def _validate_hil_source_era(
    payload: dict[str, Any],
    firmware_version: str,
) -> dict[str, Any]:
    """Require the exact HIL envelope selected by the firmware source era."""

    base_keys = {
        "schema_version",
        "candidate_release_json_sha256",
        "qualification_policy_sha256",
        "qualification_policy",
        "records",
    }
    expected_keys = set(base_keys)
    schema_version = _hil_schema_version_for_version(firmware_version)
    if schema_version == 4:
        expected_keys.add("waveshare_lcd147b_qualification")
    elif schema_version == 5:
        expected_keys.update(
            {
                "waveshare_lcd147b_qualification",
                "esp32_c3_qualification",
                "rpi_pico2_w_qualification",
            }
        )
    _exact_keys(payload, expected_keys, "source-era HIL records")
    _require(
        type(payload["schema_version"]) is int
        and payload["schema_version"]
        == _hil_schema_version_for_version(firmware_version),
        "HIL schema does not match the firmware source era",
    )
    return payload


def _bind_waveshare_lcd147b_hil_summary(
    payload: dict[str, Any],
    summary: dict[str, Any],
    *,
    firmware_version: str,
) -> dict[str, Any]:
    """Perform the sole V4 null-to-derived-summary transition."""

    _validate_hil_source_era(payload, firmware_version)
    _require(
        _waveshare_lcd147b_capable_version(firmware_version)
        and payload["waveshare_lcd147b_qualification"] is None,
        "LCD qualification summary can only replace the V4 candidate null",
    )
    completed = copy.deepcopy(payload)
    completed["waveshare_lcd147b_qualification"] = copy.deepcopy(summary)
    return completed


def _render_hil_report_payload(text: str, payload: dict[str, Any]) -> bytes:
    _parse_hil_report(text)
    matches = list(HIL_MARKER_RE.finditer(text))
    _require(len(matches) == 1, "HIL report marker cannot be rewritten exactly")
    schema_version = payload.get("schema_version")
    _require(schema_version in (2, 4, 5), "HIL report schema cannot be rendered")
    marker = (
        "<!-- PYBLE_HIL_RECORDS_V%d\n" % schema_version
        + json.dumps(payload, indent=2, sort_keys=False)
        + "\n-->"
    )
    rendered = (HIL_REPORT_SHELL_PREFIX + marker + HIL_REPORT_SHELL_SUFFIX).encode(
        "utf-8"
    )
    _parse_hil_report(rendered.decode("utf-8"))
    return rendered


def _validate_hil(
    bundle: Path,
    report_path: Path,
    profiles: list[dict[str, Any]],
    identity: dict[str, Any],
    public: bool,
    *,
    repo_root: Path,
    allow_unfinalized_gate_summaries: bool = False,
) -> dict[str, Any]:
    payload = _parse_hil_report(
        report_path.read_text(encoding="utf-8", errors="strict")
    )
    _validate_hil_source_era(payload, identity["version"])
    policy = _validate_qualification_policy(
        payload["qualification_policy"],
        firmware_version=identity["version"],
    )
    source_policy, source_digest = _load_qualification_policy(Path(repo_root))
    _require(
        policy == source_policy,
        "HIL qualification policy differs from the committed policy",
    )
    _require(
        payload["qualification_policy_sha256"] == source_digest,
        "HIL qualification policy digest differs from committed bytes",
    )
    candidate_digest = payload["candidate_release_json_sha256"]
    if public:
        _require(
            SHA256_RE.fullmatch(candidate_digest) is not None,
            "public HIL candidate release digest must be lowercase 64-hex",
        )
    else:
        _require(
            candidate_digest == "",
            "candidate HIL release digest must remain empty before HIL",
        )
    records = payload["records"]
    profile_order = _release_profile_order_for_version(identity["version"])
    _require(
        len(records) == len(profile_order),
        "HIL report record count must match the source-era release order",
    )
    _require(
        all(isinstance(record, dict) for record in records),
        "HIL records must be objects",
    )
    _require(
        [record.get("profile_id") for record in records]
        == list(profile_order),
        "HIL report profile order/parity is invalid",
    )
    profile_by_id = {profile["id"]: profile for profile in profiles}
    policy_by_id = {
        entry["profile_id"]: entry for entry in policy["profiles"]
    }
    required = {
        "profile_id",
        "status",
        "board_manufacturer",
        "board_model",
        "module_marking",
        "device_flash_capacity_bytes",
        "device_psram_capacity_bytes",
        "firmware_version",
        "tag",
        "source_commit",
        "manifest_sha256",
        "firmware_sha256",
        "tested_at",
        "operator",
        "maintainer_signoff",
        "desktop_os",
        "chromium_version",
        "ble_backend",
        "ble_adapter",
        "python_version",
        "checks",
        "oi1_policy",
        "oi1_build",
        "oi1_observation",
        "redacted_console_log",
    }
    check_names = {
        "browser_erase_install",
        "family_offsets_reset",
        "advertising_info_hello",
        "app_workflow",
        "neopixel_reboot",
        "footprint_reliability",
        "interrupted_flash_recovery",
    }
    for record in records:
        profile_id = record["profile_id"]
        profile = profile_by_id[profile_id]
        if payload["schema_version"] == 5:
            spec = PROFILE_SPECS[profile_id]
            is_rp2 = spec["port"] == "rp2"
            v5_required = {
                "profile_id",
                "target",
                "resource_kind",
                "provisioning_kind",
                "status",
                "board_manufacturer",
                "board_model",
                "module_marking",
                "device_flash_capacity_bytes",
                "device_psram_capacity_bytes",
                "firmware_version",
                "tag",
                "source_commit",
                "install_sha256",
                "tested_at",
                "operator",
                "maintainer_signoff",
                "desktop_os",
                "chromium_version",
                "ble_backend",
                "ble_adapter",
                "python_version",
                "checks",
                "app_hil",
                "profile_gate_summary",
                "oi1_policy",
                "oi1_build",
                "oi1_observation",
                "redacted_console_log",
            }
            if not is_rp2:
                v5_required.add("manifest_sha256")
            _exact_keys(record, v5_required, "HIL %s" % profile_id)
            _require(
                record["target"] == spec["target"]
                and record["resource_kind"] == ("rp2" if is_rp2 else "esp-idf")
                and record["provisioning_kind"]
                == ("verified-uf2-bootsel" if is_rp2 else "esp-web-serial"),
                "HIL target/provisioning identity mismatch for %s" % profile_id,
            )
            _require(
                record["status"] == profile["hil_status"]
                and record["firmware_version"] == identity["version"]
                and record["tag"] == identity["tag"]
                and record["source_commit"] == identity["_source_commit"],
                "HIL release identity mismatch for %s" % profile_id,
            )
            _require(
                record["install_sha256"] == profile["install"]["sha256"],
                "HIL install hash mismatch for %s" % profile_id,
            )
            if not is_rp2:
                _require(
                    record["manifest_sha256"] == profile["manifest"]["sha256"],
                    "HIL manifest hash mismatch for %s" % profile_id,
                )
            policy_entry = policy_by_id[profile_id]
            _require(
                record["oi1_policy"] == policy_entry,
                "HIL OI-1 policy binding mismatch for %s" % profile_id,
            )
            _validate_qualification_build(
                record["oi1_build"],
                _qualification_build_measurement(Path(bundle), profile_id),
                policy_entry["thresholds"],
                profile_id,
            )
            v5_checks = {
                "provisioning_install",
                "provisioning_recovery",
                "advertising_info_hello",
                "pble_workflow",
                "safe_boot_reconnect",
                "filesystem_resume_reliability",
                "footprint_reliability",
            }
            checks = _exact_keys(
                record["checks"], v5_checks, "HIL %s checks" % profile_id
            )
            app_hil = _exact_keys(
                record["app_hil"], {"ipad", "android"}, "HIL %s app_hil" % profile_id
            )
            text_fields = (
                "board_manufacturer",
                "board_model",
                "module_marking",
                "tested_at",
                "operator",
                "maintainer_signoff",
                "desktop_os",
                "chromium_version",
                "ble_backend",
                "ble_adapter",
                "python_version",
                "redacted_console_log",
            )
            if public:
                _require(
                    record["status"] == "passed"
                    and record["device_flash_capacity_bytes"]
                    == spec["flash_size_bytes"]
                    and record["device_psram_capacity_bytes"]
                    == spec["psram"]["size_bytes"]
                    and all(value == "passed" for value in checks.values()),
                    "public HIL result is incomplete for %s" % profile_id,
                )
                for field in text_fields:
                    _require(
                        isinstance(record[field], str)
                        and bool(record[field].strip())
                        and PLACEHOLDER_RE.fullmatch(record[field].strip()) is None,
                        "public HIL %s field %s is missing" % (profile_id, field),
                    )
                _require(
                    UTC_RE.fullmatch(record["tested_at"]) is not None,
                    "public HIL tested_at is not UTC RFC3339",
                )
                for platform_name in ("ipad", "android"):
                    platform_result = _exact_keys(
                        app_hil[platform_name],
                        {"app_version", "app_build", "os_major", "status"},
                        "HIL %s %s app result" % (profile_id, platform_name),
                    )
                    _require(
                        platform_result["status"] == "passed"
                        and all(
                            isinstance(platform_result[key], str)
                            and bool(platform_result[key].strip())
                            for key in ("app_version", "app_build", "os_major")
                        ),
                        "HIL %s %s app result is incomplete"
                        % (profile_id, platform_name),
                    )
                _validate_qualification_observation(
                    record["oi1_observation"],
                    policy_entry["thresholds"],
                    profile_id,
                    firmware_version=identity["version"],
                )
                expected_gates = (
                    tuple("C3-G%d" % index for index in range(7))
                    if profile_id == "esp32-c3-4mb"
                    else (
                        ("GP0", "GP1", "GP2")
                        if profile_id == "rpi-pico2-w"
                        else ()
                    )
                )
                if expected_gates and not allow_unfinalized_gate_summaries:
                    gate_summary = _exact_keys(
                        record["profile_gate_summary"],
                        set(expected_gates),
                        "HIL %s profile gates" % profile_id,
                    )
                    _require(
                        all(gate_summary[key] == "passed" for key in expected_gates),
                        "HIL profile gates are incomplete for %s" % profile_id,
                    )
                else:
                    _require(
                        record["profile_gate_summary"] is None,
                        "HIL profile gate summary is not in its expected phase",
                    )
            else:
                _require(
                    record["status"] == "pending"
                    and record["device_flash_capacity_bytes"] == 0
                    and record["device_psram_capacity_bytes"] == 0
                    and all(record[field] == "" for field in text_fields)
                    and all(value == "pending" for value in checks.values())
                    and app_hil == {"ipad": None, "android": None}
                    and record["profile_gate_summary"] is None
                    and record["oi1_observation"] is None,
                    "candidate HIL fields must remain pending for %s" % profile_id,
                )
            continue
        _exact_keys(record, required, "HIL %s" % profile_id)
        _require(record["status"] == profile["hil_status"], "HIL status disagreement")
        _require(
            record["firmware_version"] == identity["version"]
            and record["tag"] == identity["tag"]
            and record["source_commit"] == identity["_source_commit"],
            "HIL release identity mismatch for %s" % profile_id,
        )
        _require(
            record["manifest_sha256"] == profile["manifest"]["sha256"],
            "HIL manifest hash mismatch for %s" % profile_id,
        )
        _require(
            record["firmware_sha256"] == profile["install"]["sha256"],
            "HIL firmware hash mismatch for %s" % profile_id,
        )
        policy_entry = policy_by_id[profile_id]
        _require(
            record["oi1_policy"] == policy_entry,
            "HIL OI-1 policy binding mismatch for %s" % profile_id,
        )
        thresholds = policy_entry["thresholds"]
        _validate_qualification_build(
            record["oi1_build"],
            _qualification_build_measurement(Path(bundle), profile_id),
            thresholds,
            profile_id,
        )
        checks = _exact_keys(
            record["checks"], check_names, "HIL %s checks" % profile_id
        )
        if public:
            _require(record["status"] == "passed", "public HIL record is not passed")
            spec = PROFILE_SPECS[profile_id]
            _require(
                type(record["device_flash_capacity_bytes"]) is int
                and record["device_flash_capacity_bytes"]
                == spec["flash_size_bytes"]
                and type(record["device_psram_capacity_bytes"]) is int
                and record["device_psram_capacity_bytes"]
                == spec["psram"]["size_bytes"],
                "public HIL observed memory does not match %s" % profile_id,
            )
            for field in (
                "board_manufacturer",
                "board_model",
                "module_marking",
                "tested_at",
                "operator",
                "maintainer_signoff",
                "desktop_os",
                "chromium_version",
                "ble_backend",
                "ble_adapter",
                "python_version",
                "redacted_console_log",
            ):
                _require(
                    isinstance(record[field], str) and bool(record[field].strip()),
                    "public HIL %s field %s is missing" % (profile_id, field),
                )
                _require(
                    PLACEHOLDER_RE.fullmatch(record[field].strip()) is None,
                    "public HIL %s field %s is a placeholder"
                    % (profile_id, field),
                )
            _require(
                UTC_RE.fullmatch(record["tested_at"]) is not None,
                "public HIL tested_at is not UTC RFC3339",
            )
            _require(
                all(value == "passed" for value in checks.values()),
                "public HIL checks are incomplete for %s" % profile_id,
            )
            _validate_qualification_observation(
                record["oi1_observation"],
                thresholds,
                profile_id,
                firmware_version=identity["version"],
            )
        else:
            _require(
                record["status"] == "pending",
                "candidate HIL status must remain pending",
            )
            _require(
                type(record["device_flash_capacity_bytes"]) is int
                and record["device_flash_capacity_bytes"] == 0
                and type(record["device_psram_capacity_bytes"]) is int
                and record["device_psram_capacity_bytes"] == 0,
                "candidate HIL physical capacities must remain zero",
            )
            for field in (
                "board_manufacturer",
                "board_model",
                "module_marking",
                "tested_at",
                "operator",
                "maintainer_signoff",
                "desktop_os",
                "chromium_version",
                "ble_backend",
                "ble_adapter",
                "python_version",
                "redacted_console_log",
            ):
                _require(
                    record[field] == "",
                    "candidate HIL field %s must remain empty" % field,
                )
            _require(
                all(value == "pending" for value in checks.values()),
                "candidate HIL checks must remain pending for %s" % profile_id,
            )
            _require(
                record["oi1_observation"] is None,
                "candidate HIL OI-1 observation must remain null",
            )
    if payload["schema_version"] == 5:
        summaries = (
            payload["waveshare_lcd147b_qualification"],
            payload["esp32_c3_qualification"],
            payload["rpi_pico2_w_qualification"],
        )
        if not public or allow_unfinalized_gate_summaries:
            _require(
                all(summary is None for summary in summaries),
                "V5 qualification summaries must remain null before finalization",
            )
        else:
            _require(
                all(isinstance(summary, dict) for summary in summaries),
                "public V5 qualification summaries are incomplete",
            )
        return payload
    if _waveshare_lcd147b_capable_version(identity["version"]):
        summary = payload["waveshare_lcd147b_qualification"]
        if public:
            try:
                _WAVESHARE_LCD147B_GATE.validate_public_summary(
                    summary,
                    firmware_path=(
                        Path(bundle)
                        / "waveshare-esp32-s3-lcd-147b"
                        / "firmware.bin"
                    ),
                    expected_version=identity["version"],
                    candidate_release_json_sha256=candidate_digest,
                )
            except _WAVESHARE_LCD147B_GATE.QualificationError as exc:
                raise ReleaseError(
                    "public LCD qualification summary is invalid: %s" % exc
                ) from exc
        else:
            _require(
                summary is None,
                "candidate LCD qualification summary must remain null",
            )
    return payload


def validate_bundle(
    bundle_dir: Path,
    public: bool = False,
    *,
    previously_activated_public: bool = False,
    license_evidence_dir: Path | None = None,
    license_build_root: Path | None = None,
    repo_root: Path | None = None,
    qualification_repo_root: Path | None = None,
) -> dict[str, Any]:
    """Validate a candidate, public release, or exact activated-public replay."""

    bundle = Path(bundle_dir)
    _require(
        not (public and previously_activated_public),
        "fresh and previously activated public validation are mutually exclusive",
    )
    public_bundle = public or previously_activated_public
    license_inputs = (
        license_evidence_dir,
        license_build_root,
        repo_root,
    )
    supplied_license_inputs = sum(value is not None for value in license_inputs)
    _require(
        supplied_license_inputs in (0, len(license_inputs)),
        "license evidence directory, build root, and repository root must be "
        "supplied together",
    )
    _require(
        not public or supplied_license_inputs == len(license_inputs),
        "public release validation requires fresh license evidence, build root, "
        "and repository root",
    )
    _require(
        not previously_activated_public or supplied_license_inputs == 0,
        "previously activated public validation does not accept fresh license inputs",
    )
    audited_candidate = (
        not public_bundle and supplied_license_inputs == len(license_inputs)
    )
    if repo_root is not None and qualification_repo_root is not None:
        _require(
            Path(repo_root).resolve() == Path(qualification_repo_root).resolve(),
            "license and qualification repository roots differ",
        )
    effective_qualification_root = (
        Path(repo_root)
        if repo_root is not None
        else (
            Path(qualification_repo_root)
            if qualification_repo_root is not None
            else None
        )
    )
    _require(
        effective_qualification_root is not None,
        "candidate validation requires a qualification repository root",
    )
    try:
        bundle_mode = bundle.lstat().st_mode
    except OSError as exc:
        raise ReleaseError("release bundle directory is missing: %s" % bundle) from exc
    _require(
        not stat_module.S_ISLNK(bundle_mode),
        "release bundle root must not be a symlink",
    )
    _require(
        stat_module.S_ISDIR(bundle_mode),
        "release bundle path is not a directory: %s" % bundle,
    )
    actual_files: list[str] = []
    actual_directories: list[str] = []
    for path in bundle.rglob("*"):
        relative = path.relative_to(bundle).as_posix()
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise ReleaseError(
                "release bundle node cannot be inspected: %s" % relative
            ) from exc
        _require(
            not stat_module.S_ISLNK(mode),
            "release bundle contains a symlink: %s" % relative,
        )
        if stat_module.S_ISREG(mode):
            actual_files.append(relative)
        elif stat_module.S_ISDIR(mode):
            actual_directories.append(relative)
        else:
            raise ReleaseError(
                "release bundle contains an unlisted special file: %s" % relative
            )
    actual_files.sort()
    actual_directories.sort()

    release = _read_json(bundle / "release.json", "release.json")
    release = _exact_keys(
        release,
        {
            "schema_version",
            "identity",
            "provenance",
            "installer",
            "profiles",
            "documents",
        },
        "release.json",
    )
    raw_identity = release["identity"]
    _require(isinstance(raw_identity, dict), "release identity must be an object")
    source_version = raw_identity.get("version")
    _require(
        isinstance(source_version, str)
        and bool(SEMVER_RE.fullmatch(source_version)),
        "release version must be canonical SemVer without v",
    )
    profile_order = _release_profile_order_for_version(source_version)
    metadata_schema_version = (
        _release_metadata_schema_version_for_version(source_version)
    )
    _require(
        actual_files == _expected_bundle_files(profile_order),
        "release bundle layout is not exact",
    )
    _require(
        actual_directories == sorted(profile_order),
        "release bundle directory layout is not exact",
    )

    schema = _read_json(bundle / "release.schema.json", "release.schema.json")
    _validate_schema_document(schema)
    _require(
        schema == _release_schema(source_version),
        "release schema does not exactly match the canonical generator",
    )
    _require(
        type(release["schema_version"]) is int
        and release["schema_version"] == metadata_schema_version,
        "release schema_version does not match the source era",
    )
    identity = _exact_keys(
        release["identity"],
        {"version", "tag", "agent_version", "protocol_version", "built_at"},
        "release identity",
    )
    version = identity["version"]
    _require(
        isinstance(version, str) and bool(SEMVER_RE.fullmatch(version)),
        "release version must be canonical SemVer without v",
    )
    _require(
        identity["tag"] == "firmware-v%s" % version, "release tag/version mismatch"
    )
    _require(identity["agent_version"] == version, "agent/release version mismatch")
    _require(
        identity["protocol_version"] == "PBLE/1", "release protocol must be PBLE/1"
    )
    _require(
        isinstance(identity["built_at"], str)
        and bool(UTC_RE.fullmatch(identity["built_at"])),
        "built_at must be UTC RFC3339 with trailing Z",
    )
    provenance = _validate_provenance(release["provenance"])
    identity_with_source = dict(identity)
    identity_with_source["_source_commit"] = provenance["pyble"]["commit"]

    installer = _exact_keys(
        release["installer"], {"package", "version"}, "release installer"
    )
    _require(
        installer == {"package": "esp-web-tools", "version": "10.4.0"},
        "installer dependency must be exact esp-web-tools 10.4.0",
    )
    _validate_no_placeholders(release, "release.json")

    profiles = release["profiles"]
    _require(
        isinstance(profiles, list) and len(profiles) == len(profile_order),
        "release profile count does not match the source era",
    )
    _require(
        [profile.get("id") for profile in profiles]
        == list(profile_order),
        "release profile order/parity changed",
    )
    for profile_id, profile in zip(profile_order, profiles):
        spec = PROFILE_SPECS[profile_id]
        if spec["port"] == "rp2":
            item = _exact_keys(
                profile,
                {
                    "id",
                    "target",
                    "provisioning_kind",
                    "board",
                    "hil_status",
                    "install",
                    "resource_image",
                },
                "profile %s" % profile_id,
            )
            _require(
                item["id"] == profile_id
                and item["target"] == spec["target"]
                and item["provisioning_kind"] == "verified-uf2-bootsel"
                and item["board"] == spec["board"],
                "%s RP2 profile identity/provisioning mismatch" % profile_id,
            )
            _require(
                item["hil_status"] in ("pending", "passed"),
                "%s HIL status invalid" % profile_id,
            )
            if public_bundle:
                _require(
                    item["hil_status"] == "passed",
                    "%s is not HIL-passed" % profile_id,
                )
            install_raw = _exact_keys(
                item["install"],
                {"path", "size", "sha256", "format"},
                "%s install metadata" % profile_id,
            )
            _require(
                install_raw["format"] == "uf2",
                "%s install format must be UF2" % profile_id,
            )
            install_record = _validate_artifact_record(
                {key: install_raw[key] for key in ("path", "size", "sha256")},
                "%s install metadata" % profile_id,
            )
            _require(
                install_record["path"] == "%s/firmware.uf2" % profile_id,
                "%s install metadata path mismatch" % profile_id,
            )
            install_path = _verify_artifact(
                bundle,
                install_record,
                "%s install" % profile_id,
            )
            resource_raw = _exact_keys(
                item["resource_image"],
                {"path", "size", "sha256", "image_limit_bytes"},
                "%s resource image metadata" % profile_id,
            )
            _require(
                type(resource_raw["image_limit_bytes"]) is int
                and resource_raw["image_limit_bytes"] == RP2_IMAGE_LIMIT_BYTES,
                "%s resource image limit mismatch" % profile_id,
            )
            resource_record = _validate_artifact_record(
                {key: resource_raw[key] for key in ("path", "size", "sha256")},
                "%s resource image metadata" % profile_id,
            )
            _require(
                resource_record["path"] == "%s/firmware.bin" % profile_id
                and resource_record["size"] <= RP2_IMAGE_LIMIT_BYTES,
                "%s resource image metadata mismatch" % profile_id,
            )
            resource_path = _verify_artifact(
                bundle,
                resource_record,
                "%s resource image" % profile_id,
            )
            reconstructed = _reconstruct_rp2350_uf2(
                install_path.read_bytes(),
                profile_id,
            )
            raw_image = resource_path.read_bytes()
            _require(
                len(reconstructed) >= len(raw_image)
                and reconstructed[: len(raw_image)] == raw_image
                and all(value == 0 for value in reconstructed[len(raw_image) :]),
                "%s released UF2 does not reconstruct its resource image"
                % profile_id,
            )
            continue

        esp_profile_keys = {
            "id",
            "chip_family",
            "silicon_revision",
            "requirements",
            "flash",
            "hil_status",
            "manifest",
            "install",
            "components",
        }
        if metadata_schema_version == 4:
            esp_profile_keys.update({"target", "provisioning_kind"})
        item = _exact_keys(
            profile,
            esp_profile_keys,
            "profile %s" % profile_id,
        )
        _require(item["id"] == profile_id, "profile ID mismatch")
        if metadata_schema_version == 4:
            _require(
                item["target"] == spec["target"]
                and item["provisioning_kind"] == "esp-web-serial",
                "%s ESP target/provisioning mismatch" % profile_id,
            )
        _require(
            item["chip_family"] == spec["chip_family"], "profile chip family mismatch"
        )
        revision = _exact_keys(
            item["silicon_revision"],
            {"minimum_full", "maximum_full"},
            "%s silicon revision" % profile_id,
        )
        _require(
            revision == spec["silicon_revision"],
            "%s silicon-revision window mismatch" % profile_id,
        )
        requirements = _exact_keys(
            item["requirements"],
            {"flash_size_bytes", "psram"},
            "%s requirements" % profile_id,
        )
        _require(
            requirements["flash_size_bytes"] == spec["flash_size_bytes"],
            "%s flash capacity mismatch" % profile_id,
        )
        _require(
            requirements["psram"] == spec["psram"],
            "%s PSRAM requirements mismatch" % profile_id,
        )
        flash = _exact_keys(
            item["flash"], {"mode", "frequency_hz"}, "%s flash" % profile_id
        )
        _require(
            flash == {"mode": "dio", "frequency_hz": spec["frequency_hz"]},
            "%s flash settings mismatch" % profile_id,
        )
        _require(
            item["hil_status"] in ("pending", "passed"),
            "%s HIL status invalid" % profile_id,
        )
        if public_bundle:
            _require(
                item["hil_status"] == "passed", "%s is not HIL-passed" % profile_id
            )

        manifest_record = _validate_artifact_record(
            item["manifest"], "%s manifest metadata" % profile_id
        )
        _require(
            manifest_record["path"] == "%s/manifest.json" % profile_id,
            "%s manifest metadata path mismatch" % profile_id,
        )
        manifest_path = _verify_artifact(
            bundle, manifest_record, "%s manifest" % profile_id
        )
        manifest = _read_json(manifest_path, "%s manifest" % profile_id)
        _validate_manifest(manifest, version, profile_id)

        install_record = _validate_artifact_record(
            item["install"], "%s install metadata" % profile_id, offset=True
        )
        _require(
            install_record["path"] == "%s/firmware.bin" % profile_id
            and install_record["offset"] == spec["base_offset"],
            "%s install metadata mismatch" % profile_id,
        )
        install_path = _verify_artifact(
            bundle, install_record, "%s install" % profile_id
        )
        part = manifest["builds"][0]["parts"][0]
        _require(
            part["path"] == Path(install_record["path"]).name
            and part["offset"] == install_record["offset"],
            "%s manifest/install metadata disagreement" % profile_id,
        )

        components = item["components"]
        _require(
            isinstance(components, list) and len(components) == 3,
            "%s needs exactly three components" % profile_id,
        )
        _require(
            [component.get("role") for component in components] == list(ROLE_ORDER),
            "%s component roles/order changed" % profile_id,
        )
        component_paths = []
        expected_names = ("bootloader.bin", "partition-table.bin", "application.bin")
        for role, filename, expected_offset, component_record in zip(
            ROLE_ORDER, expected_names, spec["component_offsets"], components
        ):
            record = _validate_artifact_record(
                component_record,
                "%s %s metadata" % (profile_id, role),
                offset=True,
                component=True,
            )
            _require(
                record["role"] == role
                and record["path"] == "%s/%s" % (profile_id, filename)
                and record["offset"] == expected_offset,
                "%s %s component metadata mismatch" % (profile_id, role),
            )
            component_paths.append(
                _verify_artifact(bundle, record, "%s %s" % (profile_id, role))
            )
        _validate_components(
            spec,
            install_path.read_bytes(),
            component_paths[0].read_bytes(),
            component_paths[1].read_bytes(),
            component_paths[2].read_bytes(),
            profile_id,
        )

    documents = _exact_keys(
        release["documents"], set(DOCUMENT_KEYS), "release documents"
    )
    document_paths = {}
    for key in DOCUMENT_KEYS:
        record = _validate_artifact_record(documents[key], "document %s" % key)
        _require(
            record["path"] == DOCUMENT_PATHS[key], "document %s path mismatch" % key
        )
        document_paths[key] = _verify_artifact(bundle, record, "document %s" % key)

    _validate_sha256sums(bundle)
    _validate_hil(
        bundle,
        document_paths["hil_report"],
        profiles,
        identity_with_source,
        public_bundle,
        repo_root=effective_qualification_root,
    )
    if public_bundle or audited_candidate:
        notices = document_paths["third_party_licenses"].read_text(
            encoding="utf-8", errors="strict"
        )
        _require(
            NOTICE_CANDIDATE_MARKER not in notices,
            "candidate-only linked-input notices cannot qualify an audited release; "
            "run the pinned esp-idf-sbom/policy audit",
        )
    if public or audited_candidate:
        _audit_verify_release_evidence(
            notice=notices,
            evidence_dir=license_evidence_dir,
            build_root=license_build_root,
            repo_root=repo_root,
            bundle=bundle,
            release=release,
        )
    return release


def _candidate_hil_report(
    version: str,
    provenance: dict[str, Any],
    profile_records: list[dict[str, Any]],
    qualification_policy: dict[str, Any],
    qualification_policy_sha256: str,
    bundle: Path,
) -> str:
    hil_schema_version = _hil_schema_version_for_version(version)
    policy_by_id = {
        entry["profile_id"]: entry
        for entry in qualification_policy["profiles"]
    }
    records = []
    for profile in profile_records:
        profile_id = profile["id"]
        spec = PROFILE_SPECS[profile_id]
        if hil_schema_version == 5:
            is_rp2 = spec["port"] == "rp2"
            record = {
                "profile_id": profile_id,
                "target": spec["target"],
                "resource_kind": "rp2" if is_rp2 else "esp-idf",
                "provisioning_kind": (
                    "verified-uf2-bootsel" if is_rp2 else "esp-web-serial"
                ),
                "status": "pending",
                "board_manufacturer": "",
                "board_model": "",
                "module_marking": "",
                "device_flash_capacity_bytes": 0,
                "device_psram_capacity_bytes": 0,
                "firmware_version": version,
                "tag": "firmware-v%s" % version,
                "source_commit": provenance["pyble"]["commit"],
                "install_sha256": profile["install"]["sha256"],
                "tested_at": "",
                "operator": "",
                "maintainer_signoff": "",
                "desktop_os": "",
                "chromium_version": "",
                "ble_backend": "",
                "ble_adapter": "",
                "python_version": "",
                "checks": {
                    "provisioning_install": "pending",
                    "provisioning_recovery": "pending",
                    "advertising_info_hello": "pending",
                    "pble_workflow": "pending",
                    "safe_boot_reconnect": "pending",
                    "filesystem_resume_reliability": "pending",
                    "footprint_reliability": "pending",
                },
                "app_hil": {"ipad": None, "android": None},
                "profile_gate_summary": None,
                "oi1_policy": copy.deepcopy(policy_by_id[profile_id]),
                "oi1_build": _qualification_build_measurement(
                    Path(bundle), profile_id
                ),
                "oi1_observation": None,
                "redacted_console_log": "",
            }
            if not is_rp2:
                record["manifest_sha256"] = profile["manifest"]["sha256"]
            records.append(record)
            continue
        records.append(
            {
                "profile_id": profile_id,
                "status": "pending",
                "board_manufacturer": "",
                "board_model": "",
                "module_marking": "",
                "device_flash_capacity_bytes": 0,
                "device_psram_capacity_bytes": 0,
                "firmware_version": version,
                "tag": "firmware-v%s" % version,
                "source_commit": provenance["pyble"]["commit"],
                "manifest_sha256": profile["manifest"]["sha256"],
                "firmware_sha256": profile["install"]["sha256"],
                "tested_at": "",
                "operator": "",
                "maintainer_signoff": "",
                "desktop_os": "",
                "chromium_version": "",
                "ble_backend": "",
                "ble_adapter": "",
                "python_version": "",
                "checks": {
                    "browser_erase_install": "pending",
                    "family_offsets_reset": "pending",
                    "advertising_info_hello": "pending",
                    "app_workflow": "pending",
                    "neopixel_reboot": "pending",
                    "footprint_reliability": "pending",
                    "interrupted_flash_recovery": "pending",
                },
                "oi1_policy": copy.deepcopy(policy_by_id[profile_id]),
                "oi1_build": _qualification_build_measurement(
                    Path(bundle),
                    profile_id,
                ),
                "oi1_observation": None,
                "redacted_console_log": "",
            }
        )
    payload = {
        "schema_version": hil_schema_version,
        "candidate_release_json_sha256": "",
        "qualification_policy_sha256": qualification_policy_sha256,
        "qualification_policy": copy.deepcopy(qualification_policy),
        "records": records,
    }
    if hil_schema_version == 4:
        payload["waveshare_lcd147b_qualification"] = None
    elif hil_schema_version == 5:
        payload.update(
            {
                "waveshare_lcd147b_qualification": None,
                "esp32_c3_qualification": None,
                "rpi_pico2_w_qualification": None,
            }
        )
    return (
        HIL_REPORT_SHELL_PREFIX
        + "<!-- PYBLE_HIL_RECORDS_V%d\n" % payload["schema_version"]
        + json.dumps(payload, indent=2)
        + "\n-->"
        + HIL_REPORT_SHELL_SUFFIX
    )


def _release_notes(
    version: str,
    built_at: str,
    provenance: dict[str, Any],
) -> str:
    return (
        "# PyBLE firmware %s — %s\n\n"
        "Supported browser profiles:\n\n"
        "- `esp32-4mb`: classic ESP32 with exactly 4 MiB flash.\n"
        "- `esp32-s3-n16r8`: ESP32-S3 N16R8-class only — exactly 16 MiB "
        "flash plus 8 MiB Octal PSRAM; lean common runtime, with no bundled "
        "board-specific display drivers.\n"
        "- `waveshare-esp32-s3-lcd-147b`: exact Waveshare "
        "ESP32-S3-LCD-1.47B B-version only; includes its ST7789 runtime and "
        "fresh-install PyBLE splash with persistent disable.\n\n"
        "Agent `%s`; protocol `PBLE/1`; MicroPython `%s` @ `%s`; ESP-IDF "
        "`%s` @ `%s`; PyBLE source `%s`; tag `firmware-v%s`.\n\n"
        "Installation is destructive and erases the existing firmware and "
        "workspace. Back up board files first. Wired provisioning requires a "
        "supported desktop Chromium browser; iPadOS cannot perform this step. "
        "Runtime use remains BLE-first. Upgrade only with the same exact "
        "qualified profile. See `RECOVERY.md` before installing.\n\n"
        "Known limitations: the initial profile set covers only the exact "
        "memory configurations above. Stop on wrong-memory symptoms instead "
        "of trying another image. Support: https://pyble.dev/support/.\n"
        % (
            version,
            built_at[:10],
            version,
            provenance["micropython"]["ref"],
            provenance["micropython"]["commit"],
            provenance["esp_idf"]["ref"],
            provenance["esp_idf"]["commit"],
            provenance["pyble"]["commit"],
            version,
        )
    )


def _recovery_guide(version: str) -> str:
    return (
        "# PyBLE firmware %s recovery\n\n"
        "Installing PyBLE erases the board's existing firmware and user "
        "workspace. Back up files before installation. Use a data-capable USB "
        "cable, stable power, close every serial monitor/application holding "
        "the port, and select the correct serial device.\n\n"
        "If automatic reset fails, hold BOOT, tap RESET, then release BOOT. "
        "Button names vary by board. After permission denial, disconnect, "
        "timeout, interrupted erase/write, verification failure, or a board "
        "that no longer boots: close the serial user, reconnect USB, enter the "
        "ROM bootloader manually, and retry the same verified profile. Never "
        "guess another image.\n\n"
        "Advanced merged-image recovery commands using these exact bytes:\n\n"
        "```sh\n"
        "python -m esptool --chip esp32 write_flash 0x1000 esp32-4mb/firmware.bin\n"
        "python -m esptool --chip esp32s3 write_flash 0x0 esp32-s3-n16r8/firmware.bin\n"
        "python -m esptool --chip esp32s3 write_flash 0x0 "
        "waveshare-esp32-s3-lcd-147b/firmware.bin\n"
        "```\n\n"
        "Component diagnostics use the bundled bootloader at `0x1000` for "
        "classic ESP32 and `0x0` for S3, partition table at `0x8000`, and "
        "application at `0x10000`. Power-cycle after flashing, expect a "
        "`PyBLE-XXXX` BLE advertisement, then connect from the app.\n\n"
        "Repeated resets, flash-size errors, PSRAM startup errors, or no "
        "advertisement can indicate a wrong memory profile. Stop; do not try "
        "random images. Report only release `%s`, profile ID, board model/module "
        "marking, browser/OS versions, failed stage, and redacted error text at "
        "https://pyble.dev/support/. Do not share secrets or personal device "
        "labels.\n" % (version, version)
    )


def _validate_create_provenance(
    repo_root: Path,
    provenance: dict[str, Any],
    lock: dict[str, Any],
) -> dict[str, Any]:
    value = _validate_provenance(provenance, lock)
    patch_count = len(list((repo_root / "firmware" / "patches").rglob("*.patch")))
    _require(
        value["patch_count"] == patch_count,
        "provenance patch_count disagrees with firmware/patches",
    )
    git_dir = repo_root / ".git"
    if git_dir.exists():

        def git(*args: str) -> str:
            completed = subprocess.run(
                ["git", "-C", str(repo_root), *args],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            _require(
                completed.returncode == 0,
                "cannot verify release Git provenance: %s" % completed.stderr.strip(),
            )
            return completed.stdout.strip()

        head = git("rev-parse", "HEAD")
        _require(head == value["pyble"]["commit"], "provenance commit is not HEAD")
        status = git(
            "status",
            "--porcelain",
            "--untracked-files=normal",
            "--ignore-submodules=untracked",
        )
        _require(status == "", "release source tree is not clean")
        tag = "firmware-v%s" % lock["pyble"]["agent_version"]
        tag_type = git("cat-file", "-t", "refs/tags/%s" % tag)
        _require(tag_type == "tag", "release tag must be annotated: %s" % tag)
        tag_commit = git("rev-list", "-n", "1", tag)
        _require(tag_commit == head, "release tag does not identify HEAD")
    return value


def _write_sha256sums(bundle: Path) -> None:
    lines = []
    for path in sorted(item for item in bundle.rglob("*") if item.is_file()):
        relative = path.relative_to(bundle).as_posix()
        if relative == "SHA256SUMS":
            continue
        lines.append("%s  %s" % (_sha256_path(path), relative))
    (bundle / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _release_tree_snapshot(
    root: Path,
    label: str,
) -> dict[str, tuple[str, int, str] | tuple[str]]:
    """Capture every node without following links for mutation/envelope checks."""

    tree = Path(root)
    try:
        root_mode = tree.lstat().st_mode
    except OSError as exc:
        raise ReleaseError("%s root is missing or unreadable" % label) from exc
    _require(
        stat_module.S_ISDIR(root_mode) and not stat_module.S_ISLNK(root_mode),
        "%s root must be a regular directory" % label,
    )
    snapshot: dict[str, tuple[str, int, str] | tuple[str]] = {}
    try:
        paths = sorted(
            tree.rglob("*"), key=lambda path: path.relative_to(tree).as_posix()
        )
        for path in paths:
            relative = path.relative_to(tree).as_posix()
            mode = path.lstat().st_mode
            _require(
                not stat_module.S_ISLNK(mode),
                "%s contains a symlink: %s" % (label, relative),
            )
            if stat_module.S_ISDIR(mode):
                snapshot[relative] = ("directory",)
            elif stat_module.S_ISREG(mode):
                snapshot[relative] = (
                    "file",
                    path.stat(follow_symlinks=False).st_size,
                    _sha256_path(path),
                )
            else:
                raise ReleaseError("%s contains a special file: %s" % (label, relative))
    except OSError as exc:
        raise ReleaseError("%s changed while it was snapshotted" % label) from exc
    return snapshot


def _read_regular_file_bytes(path: Path, label: str) -> bytes:
    source = Path(path)
    try:
        mode = source.lstat().st_mode
        value = source.read_bytes()
        final_mode = source.lstat().st_mode
    except OSError as exc:
        raise ReleaseError("%s is missing or unreadable" % label) from exc
    _require(
        stat_module.S_ISREG(mode)
        and not stat_module.S_ISLNK(mode)
        and final_mode == mode,
        "%s must be a stable regular non-symlink file" % label,
    )
    return value


def _stage_regular_file_bytes(
    destination: Path,
    payload: bytes,
    label: str,
    *,
    mode: int,
) -> Path:
    target = Path(destination)
    parent = target.parent
    try:
        parent_mode = parent.lstat().st_mode
    except OSError as exc:
        raise ReleaseError("%s parent directory is unavailable" % label) from exc
    _require(
        stat_module.S_ISDIR(parent_mode)
        and not stat_module.S_ISLNK(parent_mode),
        "%s parent must be a regular non-symlink directory" % label,
    )
    descriptor: int | None = None
    temporary: Path | None = None
    staged = False
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".%s." % target.name,
            dir=os.fspath(parent),
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _require(
            _read_regular_file_bytes(temporary, label + " staging")
            == payload,
            "%s staging bytes changed" % label,
        )
        staged = True
        return temporary
    except (OSError, UnicodeError) as exc:
        raise ReleaseError("%s could not be staged safely" % label) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None and not staged:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass


def _sha256sum_records(bundle: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    try:
        lines = (
            (Path(bundle) / "SHA256SUMS")
            .read_text(
                encoding="utf-8",
                errors="strict",
            )
            .splitlines()
        )
    except (OSError, UnicodeError) as exc:
        raise ReleaseError("cannot inspect SHA256SUMS promotion envelope") from exc
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        _require(match is not None, "SHA256SUMS promotion record is malformed")
        digest, relative = match.groups()
        _require(relative not in records, "SHA256SUMS promotion path is duplicated")
        records[relative] = digest
    return records


def _baseline_creation_snapshot(
    repo_root: Path,
    validated: dict[str, dict[str, Any]],
) -> dict[str, tuple[int, str] | str]:
    snapshot: dict[str, tuple[int, str] | str] = {}

    def add_file(key: str, path: Path) -> None:
        try:
            mode = path.lstat().st_mode
            size = path.stat(follow_symlinks=False).st_size
        except OSError as exc:
            raise ReleaseError(
                "baseline snapshot input is missing: %s" % path
            ) from exc
        _require(
            stat_module.S_ISREG(mode) and not stat_module.S_ISLNK(mode),
            "baseline snapshot input must be a regular non-symlink file: %s"
            % path,
        )
        snapshot[key] = (size, _sha256_path(path))

    add_file("repo/firmware/versions.lock", repo_root / "firmware" / "versions.lock")
    patches = repo_root / "firmware" / "patches"
    if patches.is_dir():
        snapshot["repo/firmware/patches"] = _audit_sha256_tree(patches)
    for target in sorted(validated):
        for name, path in sorted(validated[target]["paths"].items()):
            add_file("build/%s/%s" % (target, name), path)
    snapshot["git/head"] = _git_output(
        repo_root,
        "PyBLE",
        "rev-parse",
        "HEAD",
    )
    snapshot["git/status"] = _git_output(
        repo_root,
        "PyBLE",
        "status",
        "--porcelain",
        "--untracked-files=normal",
        "--ignore-submodules=untracked",
    )
    return dict(sorted(snapshot.items()))


def _validate_staged_baseline_inputs(
    staging: Path,
    version: str,
    source_snapshot: dict[str, tuple[int, str] | str],
) -> None:
    expected: dict[str, tuple[str, int, str] | tuple[str]] = {}
    profile_order = _release_profile_order_for_version(version)
    for profile_id in profile_order:
        target = PROFILE_SPECS[profile_id]["target"]
        expected[profile_id] = ("directory",)
        if PROFILE_SPECS[profile_id]["port"] == "rp2":
            for output_name, source_name in (
                ("firmware.uf2", "install"),
                ("firmware.bin", "resource-image"),
            ):
                source_record = source_snapshot.get(
                    "build/%s/%s" % (target, source_name)
                )
                _require(
                    isinstance(source_record, tuple)
                    and len(source_record) == 2
                    and isinstance(source_record[0], int)
                    and isinstance(source_record[1], str),
                    "baseline RP2 source snapshot is incomplete",
                )
                expected["%s/%s" % (profile_id, output_name)] = (
                    "file",
                    source_record[0],
                    source_record[1],
                )
            continue
        manifest_bytes = (
            json.dumps(
                _manifest(version, profile_id),
                indent=2,
                sort_keys=False,
            )
            + "\n"
        ).encode("utf-8")
        expected["%s/manifest.json" % profile_id] = (
            "file",
            len(manifest_bytes),
            _sha256_bytes(manifest_bytes),
        )
        for output_name, source_name in (
            ("firmware.bin", "install"),
            ("application.bin", "application"),
            ("partition-table.bin", "partition-table"),
        ):
            source_record = source_snapshot.get(
                "build/%s/%s" % (target, source_name)
            )
            _require(
                isinstance(source_record, tuple)
                and len(source_record) == 2
                and isinstance(source_record[0], int)
                and isinstance(source_record[1], str),
                "baseline source snapshot is incomplete",
            )
            expected["%s/%s" % (profile_id, output_name)] = (
                "file",
                source_record[0],
                source_record[1],
            )

    actual = _release_tree_snapshot(staging, "baseline input staging")
    _require(
        actual == expected,
        "staged baseline inputs differ from validated source bytes",
    )
    for path in (staging, *staging.rglob("*")):
        _require(
            stat_module.S_IMODE(path.lstat().st_mode) & 0o077 == 0,
            "staged baseline inputs are not access-controlled",
        )


def _release_creation_snapshot(
    repo_root: Path,
    validated: dict[str, dict[str, Any]],
) -> dict[str, tuple[int, str] | str]:
    snapshot: dict[str, tuple[int, str] | str] = {}

    def add_file(key: str, path: Path) -> None:
        try:
            mode = path.lstat().st_mode
            size = path.stat(follow_symlinks=False).st_size
        except OSError as exc:
            raise ReleaseError("release snapshot input is missing: %s" % path) from exc
        _require(
            stat_module.S_ISREG(mode) and not stat_module.S_ISLNK(mode),
            "release snapshot input must be a regular non-symlink file: %s" % path,
        )
        snapshot[key] = (size, _sha256_path(path))

    add_file("repo/firmware/versions.lock", repo_root / "firmware" / "versions.lock")
    qualification_policy, _qualification_digest = _load_qualification_policy(
        repo_root
    )
    add_file(
        "repo/%s" % QUALIFICATION_POLICY_RELATIVE,
        repo_root / QUALIFICATION_POLICY_RELATIVE,
    )
    qualification_baseline = qualification_policy["baseline_evidence"]["path"]
    add_file(
        "repo/%s" % qualification_baseline,
        repo_root / qualification_baseline,
    )
    patches = repo_root / "firmware" / "patches"
    if patches.is_dir():
        snapshot["repo/firmware/patches"] = _audit_sha256_tree(patches)
    for target in sorted(validated):
        for name, path in sorted(validated[target]["paths"].items()):
            add_file("build/%s/%s" % (target, name), path)

    if (repo_root / ".git").exists():
        snapshot["git/head"] = _git_output(
            repo_root,
            "PyBLE",
            "rev-parse",
            "HEAD",
        )
        snapshot["git/status"] = _git_output(
            repo_root,
            "PyBLE",
            "status",
            "--porcelain",
            "--untracked-files=normal",
            "--ignore-submodules=untracked",
        )
    return dict(sorted(snapshot.items()))


def create_baseline_inputs(
    *,
    build_root: Path,
    reproducibility_build_root: Path,
    output_dir: Path,
    repo_root: Path,
) -> Path:
    """Atomically stage exact pre-policy OI-1 measurement inputs."""

    root = Path(repo_root)
    builds_root = Path(build_root)
    reproducibility_root = Path(reproducibility_build_root)
    _require_distinct_build_roots(builds_root, reproducibility_root)
    output = Path(output_dir)
    try:
        output.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ReleaseError(
            "cannot inspect immutable baseline output: %s" % output
        ) from exc
    else:
        raise ReleaseError(
            "immutable baseline output already exists: %s" % output
        )

    lock = _read_lock(root)
    version = lock["pyble"]["agent_version"]
    profile_order = _release_profile_order_for_version(version)
    compare_build_roots(
        builds_root,
        reproducibility_root,
        repo_root=root,
        firmware_version=version,
    )
    validated: dict[str, dict[str, Any]] = {}
    for profile_id in profile_order:
        spec = PROFILE_SPECS[profile_id]
        target = spec["target"]
        validated[target] = (
            validate_rp2_build(target, builds_root / target, repo_root=root)
            if spec["port"] == "rp2"
            else validate_build(target, builds_root / target, repo_root=root)
        )
    _require_one_build_source_identity(list(validated.values()))
    creation_snapshot = _baseline_creation_snapshot(root, validated)

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".%s." % output.name, dir=str(output.parent))
    )
    try:
        for profile_id in profile_order:
            target = PROFILE_SPECS[profile_id]["target"]
            if PROFILE_SPECS[profile_id]["port"] == "rp2":
                _stage_rp2_profile_artifacts(
                    profile_dir=staging / profile_id,
                    source_paths=validated[target]["paths"],
                    private=True,
                )
            else:
                _stage_profile_artifacts(
                    profile_dir=staging / profile_id,
                    source_paths=validated[target]["paths"],
                    version=version,
                    profile_id=profile_id,
                    include_bootloader=False,
                    private=True,
                )

        compare_build_roots(
            builds_root,
            reproducibility_root,
            repo_root=root,
            firmware_version=version,
        )
        revalidated: dict[str, dict[str, Any]] = {}
        for profile_id in profile_order:
            spec = PROFILE_SPECS[profile_id]
            target = spec["target"]
            revalidated[target] = (
                validate_rp2_build(target, builds_root / target, repo_root=root)
                if spec["port"] == "rp2"
                else validate_build(target, builds_root / target, repo_root=root)
            )
        _require_one_build_source_identity(list(revalidated.values()))
        _require(
            _baseline_creation_snapshot(root, revalidated)
            == creation_snapshot,
            "baseline source/build inputs changed during staging",
        )
        _validate_staged_baseline_inputs(
            staging,
            version,
            creation_snapshot,
        )
        _atomic_publish_no_replace(staging, output, "baseline inputs")
        return output
    except ReleaseError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except (OSError, UnicodeError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise ReleaseError("baseline input staging failed safely") from exc


def assemble_oi1_baseline(
    *,
    baseline_inputs_dir: Path,
    profile_fragment_paths: list[Path],
    repo_root: Path,
    created_at: str,
) -> tuple[Path, Path]:
    """Assemble canonical OI-1 evidence and its mechanically derived policy."""

    root = Path(repo_root)
    inputs = Path(baseline_inputs_dir)
    fragments = [Path(path) for path in profile_fragment_paths]
    _require(
        isinstance(created_at, str) and UTC_RE.fullmatch(created_at) is not None,
        "OI-1 baseline created_at must be UTC RFC3339",
    )
    try:
        root_mode = root.lstat().st_mode
    except OSError as exc:
        raise ReleaseError("OI-1 proof checkout is unavailable") from exc
    _require(
        stat_module.S_ISDIR(root_mode) and not stat_module.S_ISLNK(root_mode),
        "OI-1 proof checkout must be a regular directory",
    )
    _require_checkout_clean(root, "PyBLE")
    source_commit = _git_output(root, "PyBLE", "rev-parse", "HEAD")
    _require(
        COMMIT_RE.fullmatch(source_commit) is not None,
        "OI-1 proof checkout HEAD must be full lowercase 40-hex",
    )
    firmware_version = _read_lock(root)["pyble"]["agent_version"]
    profile_order = _release_profile_order_for_version(firmware_version)
    _require_source_era_evidence_count(
        fragments,
        firmware_version,
        "OI-1 baseline fragments",
    )
    input_snapshot = _release_tree_snapshot(inputs, "OI-1 baseline inputs")
    expected_inputs = set(profile_order)
    for profile_id in profile_order:
        filenames = (
            ("firmware.uf2", "firmware.bin")
            if PROFILE_SPECS[profile_id]["port"] == "rp2"
            else (
                "manifest.json",
                "firmware.bin",
                "application.bin",
                "partition-table.bin",
            )
        )
        expected_inputs.update(
            "%s/%s" % (profile_id, filename) for filename in filenames
        )
    _require(
        set(input_snapshot) == expected_inputs,
        "OI-1 baseline input tree layout is not exact",
    )

    fragment_by_id: dict[str, dict[str, Any]] = {}
    for index, fragment_path in enumerate(fragments):
        fragment = _read_json(
            fragment_path,
            "OI-1 baseline fragment %d" % index,
        )
        _require(
            isinstance(fragment, dict),
            "OI-1 baseline fragment %d must be an object" % index,
        )
        profile_id = fragment.get("profile_id")
        _require(
            profile_id in profile_order,
            "OI-1 baseline fragment has an unknown profile",
        )
        _require(
            profile_id not in fragment_by_id,
            "OI-1 baseline fragments duplicate profile %s" % profile_id,
        )
        fragment_by_id[profile_id] = fragment
    _require(
        set(fragment_by_id) == set(profile_order),
        "OI-1 baseline fragments do not cover the exact profile set",
    )

    policy_profiles: list[dict[str, Any]] = []
    baseline_profiles: list[dict[str, Any]] = []
    policy_schema_version = _qualification_policy_schema_version_for_version(
        firmware_version
    )
    baseline_schema_version = 2 if policy_schema_version == 3 else 1
    for profile_id in profile_order:
        profile = fragment_by_id[profile_id]
        profile_dir = inputs / profile_id
        spec = PROFILE_SPECS[profile_id]
        is_rp2 = spec["port"] == "rp2"
        if is_rp2:
            install_bytes = _read_regular_file_bytes(
                profile_dir / "firmware.uf2",
                "OI-1 %s staged UF2" % profile_id,
            )
            resource_bytes = _read_regular_file_bytes(
                profile_dir / "firmware.bin",
                "OI-1 %s staged resource image" % profile_id,
            )
            _require(
                profile.get("target") == spec["target"]
                and profile.get("resource_kind") == "rp2",
                "OI-1 baseline RP2 identity mismatch for %s" % profile_id,
            )
            _require(
                profile.get("install_sha256") == _sha256_bytes(install_bytes)
                and profile.get("resource_image_sha256")
                == _sha256_bytes(resource_bytes),
                "OI-1 baseline RP2 hashes do not match staged bytes for %s"
                % profile_id,
            )
        else:
            if policy_schema_version == 3:
                _require(
                    profile.get("target") == spec["target"]
                    and profile.get("resource_kind") == "esp-idf",
                    "OI-1 baseline ESP identity mismatch for %s" % profile_id,
                )
        expected_manifest_bytes = (
            b""
            if is_rp2
            else (
                json.dumps(
                    _manifest(firmware_version, profile_id),
                    indent=2,
                    sort_keys=False,
                )
                + "\n"
            ).encode("utf-8")
        )
        if not is_rp2:
            manifest_bytes = _read_regular_file_bytes(
                profile_dir / "manifest.json",
                "OI-1 %s staged manifest" % profile_id,
            )
            firmware_bytes = _read_regular_file_bytes(
                profile_dir / "firmware.bin",
                "OI-1 %s staged firmware" % profile_id,
            )
            _require(
                manifest_bytes == expected_manifest_bytes,
                "OI-1 staged manifest differs from the production generator for %s"
                % profile_id,
            )
            expected_install_field = (
                "install_sha256" if policy_schema_version == 3 else "firmware_sha256"
            )
            _require(
                profile.get("manifest_sha256") == _sha256_bytes(manifest_bytes),
                "OI-1 baseline manifest hash does not match staged bytes for %s"
                % profile_id,
            )
            _require(
                profile.get(expected_install_field) == _sha256_bytes(firmware_bytes),
                "OI-1 baseline firmware hash does not match staged bytes for %s"
                % profile_id,
            )
        build = _validate_baseline_build(
            profile.get("oi1_build"),
            profile_id,
        )
        _require(
            build == _qualification_build_measurement(inputs, profile_id),
            "OI-1 baseline build measurements do not match staged bytes for %s"
            % profile_id,
        )
        observation = _validate_qualification_observation(
            profile.get("oi1_observation"),
            None,
            profile_id,
            firmware_version=firmware_version,
        )
        policy_profiles.append(
            ({
                "profile_id": profile_id,
                "target": spec["target"],
                "resource_kind": "rp2" if is_rp2 else "esp-idf",
                "transport": {
                    "required_att_mtu": 247,
                    "required_put_window": 4 if is_rp2 else 8,
                    "required_chunk_bytes": 229,
                    "link_facts_kind": (
                        "btstack-observed-v1" if is_rp2 else "nimble-settled-v1"
                    ),
                },
                "thresholds": _derived_qualification_thresholds(
                    build,
                    observation,
                    firmware_version=firmware_version,
                ),
            } if policy_schema_version == 3 else {
                "profile_id": profile_id,
                "target": spec["target"],
                "thresholds": _derived_qualification_thresholds(
                    build,
                    observation,
                    firmware_version=firmware_version,
                ),
            })
        )
        baseline_profiles.append(copy.deepcopy(profile))

    baseline = {
        "schema_version": baseline_schema_version,
        "measurement_contract": (
            "oi1-five-profile-v1"
            if baseline_schema_version == 2
            else "oi1-pre-v1-v1"
        ),
        "source_commit": source_commit,
        "firmware_version": firmware_version,
        "created_at": created_at,
        "profile_order": list(profile_order),
        "profiles": baseline_profiles,
    }
    baseline_relative = (
        "docs/validation/firmware/oi1/%s.json" % source_commit
    )
    baseline_path = root / baseline_relative
    baseline_bytes = _canonical_json_bytes(baseline)
    policy = {
        "schema_version": policy_schema_version,
        "qualification_scope": (
            "v0.6.0-five-profile" if policy_schema_version == 3 else "pre-v1"
        ),
        "profile_order": list(profile_order),
        "workload": {
            key: copy.deepcopy(value)
            for key, value in QUALIFICATION_WORKLOAD.items()
            if policy_schema_version != 3 or key != "required_put_window"
        },
        "derivation": copy.deepcopy(
            _qualification_derivation_for_version(firmware_version)
        ),
        "baseline_evidence": {
            "path": baseline_relative,
            "sha256": _sha256_bytes(baseline_bytes),
        },
        "profiles": policy_profiles,
    }
    if policy_schema_version in (1, 2):
        policy["deferred_profiles"] = ["esp32-c3-4mb"]
    policy_bytes = _canonical_json_bytes(policy)
    _validate_qualification_baseline(
        baseline,
        source_commit,
        policy,
        firmware_version=firmware_version,
    )
    _validate_qualification_policy(
        policy,
        firmware_version=firmware_version,
    )

    policy_path = root / QUALIFICATION_POLICY_RELATIVE
    try:
        policy_mode = policy_path.lstat().st_mode
    except FileNotFoundError:
        policy_original: bytes | None = None
    except OSError as exc:
        raise ReleaseError("OI-1 policy destination is unavailable") from exc
    else:
        _require(
            stat_module.S_ISREG(policy_mode)
            and not stat_module.S_ISLNK(policy_mode),
            "OI-1 policy destination must be a regular non-symlink file",
        )
        policy_original = _read_regular_file_bytes(policy_path, "OI-1 policy")

    try:
        baseline_path.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ReleaseError("OI-1 baseline destination is unavailable") from exc
    else:
        raise ReleaseError("OI-1 baseline evidence already exists")

    baseline_staging: Path | None = None
    policy_staging: Path | None = None
    try:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_staging = _stage_regular_file_bytes(
            baseline_path,
            baseline_bytes,
            "OI-1 baseline evidence",
            mode=0o644,
        )
        policy_staging = _stage_regular_file_bytes(
            policy_path,
            policy_bytes,
            "OI-1 qualification policy",
            mode=0o644,
        )
        _atomic_publish_no_replace(
            baseline_staging,
            baseline_path,
            "OI-1 baseline evidence",
        )
        baseline_staging = None
        _validate_qualification_policy(policy, repo_root=root)
        if policy_original is None:
            _atomic_publish_no_replace(
                policy_staging,
                policy_path,
                "OI-1 qualification policy",
            )
        else:
            os.replace(policy_staging, policy_path)
        policy_staging = None
        return baseline_path, policy_path
    finally:
        for staging in (baseline_staging, policy_staging):
            if staging is not None:
                try:
                    staging.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    pass


def create_bundle(
    *,
    build_root: Path,
    reproducibility_build_root: Path,
    output_dir: Path,
    repo_root: Path,
    installer_version: str,
    built_at: str,
    provenance: dict[str, Any],
    audited_notice: Path | None = None,
    license_evidence_dir: Path | None = None,
    license_build_root: Path | None = None,
    public: bool = False,
) -> Path:
    """Create an access-controlled candidate bundle atomically.

    Public finalization is intentionally refused here: HIL must run against the
    immutable candidate first.  The production CLI binds the exact reviewed
    SBOM notice and fresh profile/role audit evidence before HIL, so promotion never
    swaps license bytes after hardware qualification.  ``validate_bundle(...,
    public=True)`` remains the final release gate.
    """

    _require(
        not public, "public output cannot be created before completed candidate HIL"
    )
    _require(
        installer_version == "10.4.0",
        "installer version must be exact esp-web-tools 10.4.0",
    )
    _require(
        isinstance(built_at, str) and bool(UTC_RE.fullmatch(built_at)),
        "built_at must be UTC RFC3339 with trailing Z",
    )
    root = Path(repo_root)
    builds_root = Path(build_root)
    reproducibility_root = Path(reproducibility_build_root)
    validation_root = root if (root / ".git").exists() else None
    _require_distinct_build_roots(builds_root, reproducibility_root)
    _require_frozen_release_lock(root)
    lock = _read_lock(root)
    version = lock["pyble"]["agent_version"]
    profile_order = _release_profile_order_for_version(version)
    compare_build_roots(
        builds_root,
        reproducibility_root,
        repo_root=validation_root,
        firmware_version=version,
    )
    output = Path(output_dir)
    try:
        output.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ReleaseError(
            "cannot inspect immutable release output: %s" % output
        ) from exc
    else:
        raise ReleaseError("immutable release output already exists: %s" % output)
    checked_provenance = _validate_create_provenance(root, provenance, lock)
    validated: dict[str, dict[str, Any]] = {}
    for profile_id in profile_order:
        spec = PROFILE_SPECS[profile_id]
        target = spec["target"]
        validated[target] = (
            validate_rp2_build(
                target,
                builds_root / target,
                repo_root=validation_root,
            )
            if spec["port"] == "rp2"
            else validate_build(
                target,
                builds_root / target,
                repo_root=validation_root,
            )
        )
    _require_one_build_source_identity(list(validated.values()))
    for target, item in validated.items():
        build_provenance = item["provenance"]
        same_source = (
            build_provenance["pyble"]["commit"]
            == checked_provenance["pyble"]["commit"]
            and build_provenance["micropython"]["commit"]
            == checked_provenance["micropython"]["commit"]
        )
        if "esp_idf" in build_provenance:
            same_source = (
                same_source
                and build_provenance["esp_idf"]["commit"]
                == checked_provenance["esp_idf"]["commit"]
            )
        _require(
            same_source,
            "%s build provenance does not match the release source identity" % target,
        )
    creation_snapshot = _release_creation_snapshot(root, validated)
    qualification_policy, qualification_policy_sha256 = (
        _load_qualification_policy(root)
    )
    reviewed_inputs = (
        audited_notice,
        license_evidence_dir,
        license_build_root,
    )
    if any(value is not None for value in reviewed_inputs):
        _require(
            all(value is not None for value in reviewed_inputs),
            "audited candidate creation requires notice, evidence, and build root",
        )
        reviewed_builds = Path(license_build_root)
        _require(
            reviewed_builds.resolve() == builds_root.resolve(),
            "audited candidate build root differs from the packaged build root",
        )
        notice_path = Path(audited_notice)
        try:
            notice_mode = notice_path.lstat().st_mode
            notice_bytes = notice_path.read_bytes()
        except OSError as exc:
            raise ReleaseError("audited notice is missing or unreadable") from exc
        _require(
            stat_module.S_ISREG(notice_mode) and not stat_module.S_ISLNK(notice_mode),
            "audited notice must be a regular non-symlink file",
        )
        try:
            notices = notice_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ReleaseError("audited notice is not UTF-8") from exc
        _require(
            notices.endswith("\n") and NOTICE_CANDIDATE_MARKER not in notices,
            "audited candidate notice is incomplete or candidate-only",
        )
        _audit_verify_release_evidence(
            notice=notices,
            evidence_dir=Path(license_evidence_dir),
            build_root=reviewed_builds,
            repo_root=root,
        )
    else:
        notices = generate_third_party_licenses(builds_root, root)

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".%s." % output.name, dir=str(output.parent))
    )
    try:
        for profile_id in profile_order:
            target = PROFILE_SPECS[profile_id]["target"]
            if PROFILE_SPECS[profile_id]["port"] == "rp2":
                _stage_rp2_profile_artifacts(
                    profile_dir=staging / profile_id,
                    source_paths=validated[target]["paths"],
                    private=False,
                )
            else:
                _stage_profile_artifacts(
                    profile_dir=staging / profile_id,
                    source_paths=validated[target]["paths"],
                    version=version,
                    profile_id=profile_id,
                    include_bootloader=True,
                    private=False,
                )

        _write_json(
            staging / "release.schema.json",
            _release_schema(version),
        )
        (staging / "THIRD_PARTY_LICENSES.txt").write_text(notices, encoding="utf-8")
        (staging / "RELEASE_NOTES.md").write_text(
            _release_notes(version, built_at, checked_provenance),
            encoding="utf-8",
        )
        (staging / "RECOVERY.md").write_text(_recovery_guide(version), encoding="utf-8")

        profiles = []
        for profile_id in profile_order:
            spec = PROFILE_SPECS[profile_id]
            profile_dir = staging / profile_id
            if spec["port"] == "rp2":
                profiles.append(
                    {
                        "id": profile_id,
                        "target": spec["target"],
                        "provisioning_kind": "verified-uf2-bootsel",
                        "board": spec["board"],
                        "hil_status": "pending",
                        "install": {
                            **_artifact(
                                profile_dir / "firmware.uf2",
                                "%s/firmware.uf2" % profile_id,
                            ),
                            "format": "uf2",
                        },
                        "resource_image": {
                            **_artifact(
                                profile_dir / "firmware.bin",
                                "%s/firmware.bin" % profile_id,
                            ),
                            "image_limit_bytes": spec["image_limit_bytes"],
                        },
                    }
                )
                continue
            profile_record = {
                    "id": profile_id,
                    "chip_family": spec["chip_family"],
                    "silicon_revision": copy.deepcopy(spec["silicon_revision"]),
                    "requirements": {
                        "flash_size_bytes": spec["flash_size_bytes"],
                        "psram": copy.deepcopy(spec["psram"]),
                    },
                    "flash": {
                        "mode": "dio",
                        "frequency_hz": spec["frequency_hz"],
                    },
                    "hil_status": "pending",
                    "manifest": _artifact(
                        profile_dir / "manifest.json",
                        "%s/manifest.json" % profile_id,
                    ),
                    "install": _artifact(
                        profile_dir / "firmware.bin",
                        "%s/firmware.bin" % profile_id,
                        offset=spec["base_offset"],
                    ),
                    "components": [
                        _artifact(
                            profile_dir / filename,
                            "%s/%s" % (profile_id, filename),
                            role=role,
                            offset=offset,
                        )
                        for role, filename, offset in zip(
                            ROLE_ORDER,
                            (
                                "bootloader.bin",
                                "partition-table.bin",
                                "application.bin",
                            ),
                            spec["component_offsets"],
                        )
                    ],
                }
            if _release_metadata_schema_version_for_version(version) == 4:
                profile_record.update(
                    {
                        "target": spec["target"],
                        "provisioning_kind": "esp-web-serial",
                    }
                )
            profiles.append(profile_record)

        (staging / "HIL_REPORT.md").write_text(
            _candidate_hil_report(
                version,
                checked_provenance,
                profiles,
                qualification_policy,
                qualification_policy_sha256,
                staging,
            ),
            encoding="utf-8",
        )
        metadata = {
            "schema_version": _release_metadata_schema_version_for_version(
                version
            ),
            "identity": {
                "version": version,
                "tag": "firmware-v%s" % version,
                "agent_version": version,
                "protocol_version": "PBLE/1",
                "built_at": built_at,
            },
            "provenance": checked_provenance,
            "installer": {
                "package": "esp-web-tools",
                "version": installer_version,
            },
            "profiles": profiles,
            "documents": {
                key: _artifact(staging / relative, relative)
                for key, relative in DOCUMENT_PATHS.items()
            },
        }
        _write_json(staging / "release.json", metadata)
        _write_sha256sums(staging)
        validate_bundle(
            staging,
            public=False,
            qualification_repo_root=root,
        )
        if all(value is not None for value in reviewed_inputs):
            _audit_verify_release_evidence(
                notice=notices,
                evidence_dir=Path(license_evidence_dir),
                build_root=Path(license_build_root),
                repo_root=root,
                bundle=staging,
                release=metadata,
            )
        _require(
            _release_creation_snapshot(root, validated) == creation_snapshot,
            "release source/build inputs changed during candidate creation",
        )
        compare_build_roots(
            builds_root,
            reproducibility_root,
            repo_root=validation_root,
            firmware_version=version,
        )
        _require(
            _release_creation_snapshot(root, validated) == creation_snapshot,
            "release source/build inputs changed during reproducibility comparison",
        )
        _atomic_publish_no_replace(staging, output, "candidate release")
        return output
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _lcd_qualification_snapshot(path: Path) -> tuple[Any, ...]:
    try:
        return _WAVESHARE_LCD147B_GATE.private_result_snapshot(path)
    except _WAVESHARE_LCD147B_GATE.QualificationError as exc:
        raise ReleaseError("private LCD qualification result is invalid: %s" % exc) from exc


def _validate_lcd_report_privacy(report_bytes: bytes, result_path: Path) -> None:
    try:
        _WAVESHARE_LCD147B_GATE.validate_public_report_privacy(
            report_bytes,
            result_path=result_path,
        )
    except _WAVESHARE_LCD147B_GATE.QualificationError as exc:
        raise ReleaseError("public HIL report leaks private LCD evidence: %s" % exc) from exc


def _validate_lcd_gate_source(repo_root: Path) -> None:
    try:
        _WAVESHARE_LCD147B_GATE.validate_loaded_source(repo_root)
    except _WAVESHARE_LCD147B_GATE.QualificationError as exc:
        raise ReleaseError("LCD qualification validator source changed: %s" % exc) from exc


def _validate_hil_promotion_envelope(
    candidate_payload: dict[str, Any],
    completed_payload: dict[str, Any],
) -> None:
    for key in (
        "schema_version",
        "qualification_policy_sha256",
        "qualification_policy",
    ):
        _require(
            completed_payload[key] == candidate_payload[key],
            "completed HIL changed candidate-frozen field %s" % key,
        )
    if candidate_payload["schema_version"] == 4:
        _require(
            candidate_payload["waveshare_lcd147b_qualification"] is None
            and completed_payload["waveshare_lcd147b_qualification"] is None,
            "completed V4 HIL must retain the candidate LCD qualification null",
        )
    candidate_records = candidate_payload["records"]
    completed_records = completed_payload["records"]
    _require(
        len(candidate_records) == len(completed_records),
        "completed HIL changed candidate record parity",
    )
    immutable_record_fields = (
        "profile_id",
        "firmware_version",
        "tag",
        "source_commit",
        "manifest_sha256",
        "firmware_sha256",
        "oi1_policy",
        "oi1_build",
    )
    for candidate_record, completed_record in zip(
        candidate_records,
        completed_records,
    ):
        for key in immutable_record_fields:
            _require(
                completed_record[key] == candidate_record[key],
                "completed HIL changed candidate-frozen %s for %s"
                % (key, candidate_record["profile_id"]),
            )


def _completed_hil_report(payload: dict[str, Any]) -> bytes:
    schema_version = payload.get("schema_version")
    _require(
        schema_version in (2, 4, 5),
        "completed HIL payload has an unsupported schema",
    )
    return (
        "# PyBLE firmware HIL report\n\n"
        "This completed report was mechanically assembled from the immutable "
        "candidate and bounded per-profile evidence.\n\n"
        "<!-- PYBLE_HIL_RECORDS_V%d\n" % schema_version
    ).encode("utf-8") + _canonical_json_bytes(payload).rstrip(b"\n") + b"\n-->\n"


def assemble_completed_hil_report(
    *,
    candidate_dir: Path,
    profile_evidence_paths: list[Path],
    output_path: Path,
    qualification_repo_root: Path,
) -> Path:
    """Create a candidate-bound completed HIL V2 report without Markdown edits."""

    candidate = Path(candidate_dir)
    evidence_paths = [Path(path) for path in profile_evidence_paths]
    output = Path(output_path)
    qualification_root = Path(qualification_repo_root)
    operator_checks = (
        "browser_erase_install",
        "family_offsets_reset",
        "advertising_info_hello",
        "app_workflow",
        "neopixel_reboot",
        "interrupted_flash_recovery",
    )
    all_checks = (
        *operator_checks[:-1],
        "footprint_reliability",
        operator_checks[-1],
    )
    mutable_fields = (
        "board_manufacturer",
        "board_model",
        "module_marking",
        "device_flash_capacity_bytes",
        "device_psram_capacity_bytes",
        "tested_at",
        "operator",
        "maintainer_signoff",
        "desktop_os",
        "chromium_version",
        "ble_backend",
        "ble_adapter",
        "python_version",
        "redacted_console_log",
    )
    completion_fields = {
        "profile_id",
        "checks",
        "oi1_observation",
        *mutable_fields,
    }
    try:
        output.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ReleaseError("completed HIL output cannot be inspected") from exc
    else:
        raise ReleaseError("completed HIL output already exists")
    try:
        candidate_root = candidate.resolve(strict=True)
        output_parent = output.parent.resolve(strict=True)
    except OSError as exc:
        raise ReleaseError(
            "candidate or completed HIL output parent is unavailable"
        ) from exc
    _require(
        not output_parent.is_relative_to(candidate_root),
        "completed HIL output must not be inside the candidate",
    )

    release = validate_bundle(
        candidate,
        public=False,
        qualification_repo_root=qualification_root,
    )
    firmware_version = release["identity"]["version"]
    profile_order = _release_profile_order_for_version(firmware_version)
    _require_source_era_evidence_count(
        evidence_paths,
        firmware_version,
        "completed HIL evidence",
    )
    _require(
        all(
            profile["hil_status"] == "pending"
            for profile in release["profiles"]
        ),
        "completed HIL assembly requires a fully pending candidate",
    )
    candidate_release_digest = _sha256_path(candidate / "release.json")
    try:
        pending_report_text = (candidate / "HIL_REPORT.md").read_text(
            encoding="utf-8", errors="strict"
        )
    except (OSError, UnicodeError) as exc:
        raise ReleaseError("candidate HIL report is not UTF-8") from exc
    pending_payload = _parse_hil_report(pending_report_text)

    evidence_by_id: dict[str, dict[str, Any]] = {}
    for index, evidence_path in enumerate(evidence_paths):
        evidence = _read_json(
            evidence_path,
            "HIL completion evidence %d" % index,
        )
        completion = _exact_keys(
            evidence,
            completion_fields,
            "HIL completion evidence %d" % index,
        )
        profile_id = completion["profile_id"]
        _require(
            profile_id in profile_order,
            "HIL completion evidence has an unknown profile",
        )
        _require(
            profile_id not in evidence_by_id,
            "HIL completion evidence duplicates profile %s" % profile_id,
        )
        evidence_by_id[profile_id] = completion
    _require(
        set(evidence_by_id) == set(profile_order),
        "HIL completion evidence does not cover the exact profile set",
    )

    completed_payload = copy.deepcopy(pending_payload)
    completed_payload["candidate_release_json_sha256"] = (
        candidate_release_digest
    )
    policy_by_id = {
        item["profile_id"]: item
        for item in completed_payload["qualification_policy"]["profiles"]
    }
    for record in completed_payload["records"]:
        profile_id = record["profile_id"]
        completion = evidence_by_id[profile_id]
        checks = _exact_keys(
            completion["checks"],
            set(operator_checks),
            "HIL completion checks for %s" % profile_id,
        )
        _require(
            all(checks[name] == "passed" for name in operator_checks),
            "HIL operator checks are incomplete for %s" % profile_id,
        )
        _validate_qualification_observation(
            completion["oi1_observation"],
            policy_by_id[profile_id]["thresholds"],
            profile_id,
            firmware_version=firmware_version,
        )

        record["status"] = "passed"
        for field in mutable_fields:
            record[field] = completion[field]
        record["checks"] = {name: "passed" for name in all_checks}
        record["oi1_observation"] = copy.deepcopy(
            completion["oi1_observation"]
        )

    _validate_hil_promotion_envelope(pending_payload, completed_payload)
    report_bytes = _completed_hil_report(completed_payload)

    staging: Path | None = None
    try:
        staging = _stage_regular_file_bytes(
            output,
            report_bytes,
            "completed HIL report",
            mode=0o600,
        )
        passed_profiles = copy.deepcopy(release["profiles"])
        for profile in passed_profiles:
            profile["hil_status"] = "passed"
        identity = copy.deepcopy(release["identity"])
        identity["_source_commit"] = release["provenance"]["pyble"][
            "commit"
        ]
        _validate_hil(
            candidate,
            staging,
            passed_profiles,
            identity,
            True,
            repo_root=qualification_root,
        )
        _atomic_publish_no_replace(
            staging,
            output,
            "completed HIL report",
        )
        staging = None
        return output
    finally:
        if staging is not None:
            try:
                staging.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass


def finalize_public_bundle(
    *,
    candidate_dir: Path,
    completed_hil_report: Path,
    output_dir: Path,
    candidate_release_json_sha256: str,
    license_evidence_dir: Path,
    license_build_root: Path,
    repo_root: Path,
    waveshare_lcd147b_qualification_result: Path | None = None,
    esp32_c3_qualification_result: Path | None = None,
    rpi_pico2_w_qualification_result: Path | None = None,
) -> Path:
    """Promote one audited, HIL-qualified candidate without mutating it."""

    candidate = Path(candidate_dir)
    completed_report = Path(completed_hil_report)
    output = Path(output_dir)
    evidence = Path(license_evidence_dir)
    builds = Path(license_build_root)
    root = Path(repo_root)
    qualification_result = (
        Path(waveshare_lcd147b_qualification_result)
        if waveshare_lcd147b_qualification_result is not None
        else None
    )
    c3_qualification_result = (
        Path(esp32_c3_qualification_result)
        if esp32_c3_qualification_result is not None
        else None
    )
    pico_qualification_result = (
        Path(rpi_pico2_w_qualification_result)
        if rpi_pico2_w_qualification_result is not None
        else None
    )

    _require(
        isinstance(candidate_release_json_sha256, str)
        and SHA256_RE.fullmatch(candidate_release_json_sha256) is not None,
        "candidate release.json digest must be lowercase 64-hex",
    )
    try:
        output.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ReleaseError("cannot inspect public release output: %s" % output) from exc
    else:
        raise ReleaseError(
            "immutable public release output already exists: %s" % output
        )

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        parent_mode = output.parent.lstat().st_mode
    except OSError as exc:
        raise ReleaseError("public release output parent is unavailable") from exc
    _require(
        stat_module.S_ISDIR(parent_mode) and not stat_module.S_ISLNK(parent_mode),
        "public release output parent must be a regular directory",
    )
    try:
        candidate_root = candidate.resolve(strict=True)
        output_parent = output.parent.resolve(strict=True)
    except OSError as exc:
        raise ReleaseError("cannot resolve candidate/public release paths") from exc
    _require(
        not output_parent.is_relative_to(candidate_root),
        "public release output must not be inside the candidate",
    )

    candidate_snapshot = _release_tree_snapshot(candidate, "candidate release")
    candidate_release_path = candidate / "release.json"
    _require(
        _sha256_path(candidate_release_path) == candidate_release_json_sha256,
        "candidate release.json digest does not match the HIL-selected candidate",
    )
    completed_report_bytes = _read_regular_file_bytes(
        completed_report,
        "completed HIL report",
    )
    try:
        completed_report_text = completed_report_bytes.decode(
            "utf-8",
            errors="strict",
        )
    except UnicodeDecodeError as exc:
        raise ReleaseError("completed HIL report is not UTF-8") from exc
    completed_hil = _parse_hil_report(completed_report_text)
    _require(
        completed_hil["candidate_release_json_sha256"] == candidate_release_json_sha256,
        "completed HIL report identifies a different candidate release.json",
    )

    candidate_release = validate_bundle(
        candidate,
        public=False,
        license_evidence_dir=evidence,
        license_build_root=builds,
        repo_root=root,
    )
    _require(
        _release_tree_snapshot(candidate, "candidate release") == candidate_snapshot,
        "candidate release changed during audited validation",
    )
    _require(
        all(
            profile["hil_status"] == "pending"
            for profile in candidate_release["profiles"]
        ),
        "only a fully pending candidate can be finalized",
    )
    candidate_hil = _parse_hil_report(
        (candidate / "HIL_REPORT.md").read_text(
            encoding="utf-8",
            errors="strict",
        )
    )
    firmware_version = candidate_release["identity"]["version"]
    profile_order = _release_profile_order_for_version(firmware_version)
    _validate_hil_source_era(completed_hil, firmware_version)
    _validate_hil_promotion_envelope(candidate_hil, completed_hil)

    v060 = tuple(profile_order) == V060_RELEASE_PROFILE_ORDER
    if v060:
        _require(
            c3_qualification_result is not None
            and pico_qualification_result is not None,
            "v0.6.0 finalization requires both C3 and Pico private "
            "qualification results",
        )
        raise ReleaseError(
            "v0.6.0 finalization remains closed until strict C3 and Pico "
            "private-result validators are implemented"
        )
    _require(
        c3_qualification_result is None and pico_qualification_result is None,
        "pre-v0.6.0 finalization rejects C3/Pico qualification results",
    )

    lcd_capable = _waveshare_lcd147b_capable_version(firmware_version)
    _require(
        lcd_capable == (qualification_result is not None),
        (
            "v0.5.0-or-newer finalization requires the private Waveshare LCD "
            "qualification result"
            if lcd_capable
            else "pre-v0.5.0 finalization rejects unexpected Waveshare LCD evidence"
        ),
    )
    qualification_snapshot: tuple[Any, ...] | None = None
    qualification_summary: dict[str, Any] | None = None
    promoted_report_bytes = completed_report_bytes
    if qualification_result is not None:
        qualification_snapshot = _lcd_qualification_snapshot(qualification_result)
        try:
            qualification_summary = _WAVESHARE_LCD147B_GATE.validate_result_file(
                qualification_result,
                firmware_path=(
                    candidate / "waveshare-esp32-s3-lcd-147b" / "firmware.bin"
                ),
                expected_version=firmware_version,
                candidate_release_json_sha256=candidate_release_json_sha256,
                repo_root=root,
            )
        except _WAVESHARE_LCD147B_GATE.QualificationError as exc:
            raise ReleaseError(
                "private LCD qualification result is invalid: %s" % exc
            ) from exc
        _validate_lcd_report_privacy(
            completed_report_bytes,
            qualification_result,
        )
        promoted_hil = _bind_waveshare_lcd147b_hil_summary(
            completed_hil,
            qualification_summary,
            firmware_version=firmware_version,
        )
        promoted_report_bytes = _render_hil_report_payload(
            completed_report_text,
            promoted_hil,
        )
        _validate_lcd_report_privacy(
            promoted_report_bytes,
            qualification_result,
        )

    staging: Path | None = None
    try:
        staging = Path(
            tempfile.mkdtemp(
                prefix=".%s." % output.name,
                dir=str(output.parent),
            )
        )
        for profile_id in profile_order:
            (staging / profile_id).mkdir()
        for relative in _expected_bundle_files(profile_order):
            source = candidate / relative
            destination = staging / relative
            shutil.copyfile(source, destination)

        _require(
            _release_tree_snapshot(staging, "public release staging")
            == candidate_snapshot,
            "candidate copy differs before administrative promotion",
        )
        _require(
            _release_tree_snapshot(candidate, "candidate release")
            == candidate_snapshot,
            "candidate release changed while it was copied",
        )
        _require(
            _read_regular_file_bytes(completed_report, "completed HIL report")
            == completed_report_bytes,
            "completed HIL report changed during finalization",
        )

        (staging / "HIL_REPORT.md").write_bytes(promoted_report_bytes)
        promoted_release = copy.deepcopy(candidate_release)
        for profile in promoted_release["profiles"]:
            _require(
                profile["hil_status"] == "pending",
                "candidate profile status changed before promotion",
            )
            profile["hil_status"] = "passed"
        promoted_release["documents"]["hil_report"] = _artifact(
            staging / "HIL_REPORT.md",
            "HIL_REPORT.md",
        )
        _write_json(staging / "release.json", promoted_release)
        _write_sha256sums(staging)

        _require(
            _read_json(staging / "release.json", "promoted release.json")
            == promoted_release,
            "public release metadata differs from the administrative promotion",
        )
        staged_snapshot = _release_tree_snapshot(
            staging,
            "public release staging",
        )
        _require(
            set(staged_snapshot) == set(candidate_snapshot),
            "public promotion changed the release-tree layout",
        )
        changed_paths = {
            relative
            for relative in candidate_snapshot
            if candidate_snapshot[relative] != staged_snapshot[relative]
        }
        _require(
            changed_paths == PROMOTION_ENVELOPE,
            "public promotion changed files outside the frozen envelope",
        )
        candidate_sums = _sha256sum_records(candidate)
        public_sums = _sha256sum_records(staging)
        _require(
            set(candidate_sums) == set(public_sums),
            "public promotion changed SHA256SUMS coverage",
        )
        _require(
            {
                relative
                for relative in candidate_sums
                if candidate_sums[relative] != public_sums[relative]
            }
            == {"HIL_REPORT.md", "release.json"},
            "public promotion changed unexpected SHA256SUMS entries",
        )

        validated_public = validate_bundle(
            staging,
            public=True,
            license_evidence_dir=evidence,
            license_build_root=builds,
            repo_root=root,
        )
        _require(
            validated_public == promoted_release,
            "late public validation returned different release metadata",
        )
        _audit_verify_release_evidence(
            notice=(staging / "THIRD_PARTY_LICENSES.txt").read_text(
                encoding="utf-8", errors="strict"
            ),
            evidence_dir=evidence,
            build_root=builds,
            repo_root=root,
            bundle=staging,
            release=validated_public,
        )
        _require(
            _release_tree_snapshot(candidate, "candidate release")
            == candidate_snapshot,
            "candidate release changed during public validation",
        )
        _require(
            _release_tree_snapshot(staging, "public release staging")
            == staged_snapshot,
            "public release staging changed during final validation",
        )
        _require(
            _read_regular_file_bytes(completed_report, "completed HIL report")
            == completed_report_bytes,
            "completed HIL report changed during public validation",
        )
        if qualification_result is not None:
            _validate_lcd_gate_source(root)
            _validate_lcd_report_privacy(
                (staging / "HIL_REPORT.md").read_bytes(),
                qualification_result,
            )
            _require(
                _lcd_qualification_snapshot(qualification_result)
                == qualification_snapshot,
                "private LCD qualification result changed during finalization",
            )
        _atomic_publish_no_replace(staging, output, "public release")
        staging = None
        return output
    except ReleaseError:
        raise
    except (OSError, UnicodeError) as exc:
        raise ReleaseError("public release finalization failed safely") from exc
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def _capture_basic_provenance(repo_root: Path) -> dict[str, Any]:
    root = Path(repo_root)
    lock = _read_lock(root)
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _require(completed.returncode == 0, "cannot capture PyBLE Git commit")
    commit = completed.stdout.strip()
    return {
        "pyble": {"commit": commit, "clean": True},
        "micropython": {
            "ref": lock["micropython"]["ref"],
            "commit": lock["micropython"]["commit"],
        },
        "esp_idf": {
            "ref": lock["esp_idf"]["ref"],
            "commit": lock["esp_idf"]["commit"],
        },
        "patch_count": len(list((root / "firmware" / "patches").rglob("*.patch"))),
        "runner": {
            "os": platform.platform(),
            "architecture": platform.machine(),
        },
        "tools": [
            {"name": "python", "version": platform.python_version()},
        ],
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_build_parser = subparsers.add_parser("validate-build")
    validate_build_parser.add_argument("target", choices=tuple(TARGET_TO_PROFILE))
    validate_build_parser.add_argument("build_dir", type=Path)

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("left", type=Path)
    compare_parser.add_argument("right", type=Path)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("bundle", type=Path)
    validate_mode = validate_parser.add_mutually_exclusive_group()
    validate_mode.add_argument("--public", action="store_true")
    validate_mode.add_argument("--audited-candidate", action="store_true")
    validate_mode.add_argument(
        "--previously-activated-public",
        action="store_true",
    )
    validate_parser.add_argument("--license-evidence-dir", type=Path)
    validate_parser.add_argument("--license-build-root", type=Path)
    validate_parser.add_argument("--repo-root", type=Path)
    validate_parser.add_argument("--qualification-repo-root", type=Path)

    candidate_licenses_parser = subparsers.add_parser("candidate-licenses")
    candidate_licenses_parser.add_argument("build_root", type=Path)
    candidate_licenses_parser.add_argument("repo_root", type=Path)

    audit_licenses_parser = subparsers.add_parser("audit-licenses")
    audit_licenses_parser.add_argument("--build-root", required=True, type=Path)
    audit_licenses_parser.add_argument("--repo-root", required=True, type=Path)
    audit_licenses_parser.add_argument("--evidence-dir", required=True, type=Path)
    audit_licenses_parser.add_argument("--wheelhouse", required=True, type=Path)
    audit_licenses_parser.add_argument(
        "--notice-output",
        required=True,
        type=Path,
    )

    baseline_parser = subparsers.add_parser("create-baseline-inputs")
    baseline_parser.add_argument("build_root", type=Path)
    baseline_parser.add_argument("output_dir", type=Path)
    baseline_parser.add_argument(
        "--reproducibility-build-root",
        required=True,
        type=Path,
    )
    baseline_parser.add_argument("--repo-root", required=True, type=Path)

    baseline_assembly_parser = subparsers.add_parser(
        "assemble-oi1-baseline"
    )
    baseline_assembly_parser.add_argument(
        "baseline_inputs_dir",
        type=Path,
    )
    baseline_assembly_parser.add_argument(
        "profile_fragment_paths",
        nargs="+",
        type=Path,
    )
    baseline_assembly_parser.add_argument(
        "--repo-root",
        required=True,
        type=Path,
    )
    baseline_assembly_parser.add_argument("--created-at", required=True)

    create_parser = subparsers.add_parser("create-candidate")
    create_parser.add_argument("build_root", type=Path)
    create_parser.add_argument("output_dir", type=Path)
    create_parser.add_argument(
        "--reproducibility-build-root",
        required=True,
        type=Path,
    )
    create_parser.add_argument("--repo-root", required=True, type=Path)
    create_parser.add_argument("--audited-notice", required=True, type=Path)
    create_parser.add_argument(
        "--license-evidence-dir",
        required=True,
        type=Path,
    )
    create_parser.add_argument(
        "--license-build-root",
        required=True,
        type=Path,
    )
    create_parser.add_argument("--built-at", required=True)
    create_parser.add_argument("--provenance-json", type=Path)

    finalize_parser = subparsers.add_parser("finalize-public")
    finalize_parser.add_argument("candidate_dir", type=Path)
    finalize_parser.add_argument("completed_hil_report", type=Path)
    finalize_parser.add_argument("output_dir", type=Path)
    finalize_parser.add_argument(
        "--candidate-release-json-sha256",
        required=True,
    )
    finalize_parser.add_argument(
        "--license-evidence-dir",
        required=True,
        type=Path,
    )
    finalize_parser.add_argument(
        "--license-build-root",
        required=True,
        type=Path,
    )
    finalize_parser.add_argument("--repo-root", required=True, type=Path)
    finalize_parser.add_argument(
        "--waveshare-lcd147b-qualification-result",
        type=Path,
    )
    finalize_parser.add_argument(
        "--esp32-c3-qualification-result",
        type=Path,
    )
    finalize_parser.add_argument(
        "--rpi-pico2-w-qualification-result",
        type=Path,
    )

    hil_assembly_parser = subparsers.add_parser("assemble-hil-report")
    hil_assembly_parser.add_argument("candidate_dir", type=Path)
    hil_assembly_parser.add_argument(
        "profile_evidence_paths",
        nargs="+",
        type=Path,
    )
    hil_assembly_parser.add_argument("output_path", type=Path)
    hil_assembly_parser.add_argument(
        "--qualification-repo-root",
        required=True,
        type=Path,
    )

    args = parser.parse_args(argv)
    if args.command == "validate-build":
        validate_build(args.target, args.build_dir)
    elif args.command == "compare":
        compare_build_roots(args.left, args.right)
    elif args.command == "validate":
        evidence_arguments = (
            args.license_evidence_dir,
            args.license_build_root,
            args.repo_root,
        )
        validation_mode = (
            "--public"
            if args.public
            else (
                "--audited-candidate"
                if args.audited_candidate
                else (
                    "--previously-activated-public"
                    if args.previously_activated_public
                    else None
                )
            )
        )
        if validation_mode in ("--public", "--audited-candidate") and any(
            value is None for value in evidence_arguments
        ):
            option_names = (
                "--license-evidence-dir",
                "--license-build-root",
                "--repo-root",
            )
            missing = [
                option
                for option, value in zip(option_names, evidence_arguments)
                if value is None
            ]
            parser.error("%s requires %s" % (validation_mode, ", ".join(missing)))
        if validation_mode not in ("--public", "--audited-candidate") and any(
            value is not None for value in evidence_arguments
        ):
            parser.error(
                "license evidence options require --public or --audited-candidate"
            )
        if (
            validation_mode in (None, "--previously-activated-public")
            and args.qualification_repo_root is None
        ):
            parser.error(
                "%s requires --qualification-repo-root"
                % (validation_mode or "plain candidate validation")
            )
        validate_bundle(
            args.bundle,
            public=args.public,
            previously_activated_public=args.previously_activated_public,
            license_evidence_dir=args.license_evidence_dir,
            license_build_root=args.license_build_root,
            repo_root=args.repo_root,
            qualification_repo_root=args.qualification_repo_root,
        )
    elif args.command == "candidate-licenses":
        sys.stdout.write(generate_third_party_licenses(args.build_root, args.repo_root))
    elif args.command == "audit-licenses":
        result = audit_release_licenses_from_lock(
            build_root=args.build_root,
            repo_root=args.repo_root,
            evidence_dir=args.evidence_dir,
            wheelhouse=args.wheelhouse,
            notice_output=args.notice_output,
        )
        print(result["notice_output"])
        print(result["evidence_dir"])
    elif args.command == "create-baseline-inputs":
        output = create_baseline_inputs(
            build_root=args.build_root,
            reproducibility_build_root=args.reproducibility_build_root,
            output_dir=args.output_dir,
            repo_root=args.repo_root,
        )
        print(output)
    elif args.command == "assemble-oi1-baseline":
        baseline_path, policy_path = assemble_oi1_baseline(
            baseline_inputs_dir=args.baseline_inputs_dir,
            profile_fragment_paths=args.profile_fragment_paths,
            repo_root=args.repo_root,
            created_at=args.created_at,
        )
        print(baseline_path)
        print(policy_path)
    elif args.command == "create-candidate":
        provenance = (
            _read_json(args.provenance_json, "provenance JSON")
            if args.provenance_json
            else _capture_basic_provenance(args.repo_root)
        )
        output = create_bundle(
            build_root=args.build_root,
            reproducibility_build_root=args.reproducibility_build_root,
            output_dir=args.output_dir,
            repo_root=args.repo_root,
            installer_version="10.4.0",
            built_at=args.built_at,
            provenance=provenance,
            audited_notice=args.audited_notice,
            license_evidence_dir=args.license_evidence_dir,
            license_build_root=args.license_build_root,
            public=False,
        )
        print(output)
    elif args.command == "finalize-public":
        output = finalize_public_bundle(
            candidate_dir=args.candidate_dir,
            completed_hil_report=args.completed_hil_report,
            output_dir=args.output_dir,
            candidate_release_json_sha256=args.candidate_release_json_sha256,
            license_evidence_dir=args.license_evidence_dir,
            license_build_root=args.license_build_root,
            repo_root=args.repo_root,
            waveshare_lcd147b_qualification_result=(
                args.waveshare_lcd147b_qualification_result
            ),
            esp32_c3_qualification_result=args.esp32_c3_qualification_result,
            rpi_pico2_w_qualification_result=(
                args.rpi_pico2_w_qualification_result
            ),
        )
        print(output)
    elif args.command == "assemble-hil-report":
        output = assemble_completed_hil_report(
            candidate_dir=args.candidate_dir,
            profile_evidence_paths=args.profile_evidence_paths,
            output_path=args.output_path,
            qualification_repo_root=args.qualification_repo_root,
        )
        print(output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_main())
    except ReleaseError as exc:
        print("release_bundle: %s" % exc, file=sys.stderr)
        raise SystemExit(1) from exc
