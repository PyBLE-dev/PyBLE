# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Shared PBLE/1 hardware-bench operations.  This module is host-side HIL
# tooling; it is not firmware and does not ship to a board.

import asyncio
import binascii
import hashlib
import json
import os
import re
import stat
import struct
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import _pble_wire as wire
from _pble_central import rsp_status, status_name


PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
    "waveshare-esp32-s3-lcd-147b",
    "esp32-c3-4mb",
    "rpi-pico2-w",
)
PROFILE_TARGETS = {
    "esp32-4mb": "esp32",
    "esp32-s3-n16r8": "esp32-s3",
    "waveshare-esp32-s3-lcd-147b": "waveshare-esp32-s3-lcd-147b",
    "esp32-c3-4mb": "esp32-c3",
    "rpi-pico2-w": "rpi-pico2-w",
}
PROFILE_CHIPS = {
    "esp32-4mb": "esp32",
    "esp32-s3-n16r8": "esp32-s3",
    "waveshare-esp32-s3-lcd-147b": "esp32-s3",
    "esp32-c3-4mb": "esp32-c3",
    "rpi-pico2-w": "rpi-pico2-w",
}

V051_PROFILE_ORDER = PROFILE_ORDER[:3]
PROFILE_RESOURCE_KINDS = {
    profile_id: "rp2" if profile_id == "rpi-pico2-w" else "esp-idf"
    for profile_id in PROFILE_ORDER
}
ESP_PROFILE_ORDER = PROFILE_ORDER[:4]
PROFILE_REQUIRES_2M = {
    "esp32-4mb": False,
    "esp32-s3-n16r8": True,
    "waveshare-esp32-s3-lcd-147b": True,
    "esp32-c3-4mb": True,
}
PROFILE_TRANSPORTS = {
    profile_id: {
        "required_att_mtu": 247,
        "required_put_window": 4 if profile_id == "rpi-pico2-w" else 8,
        "required_chunk_bytes": 229,
        "link_facts_kind": (
            "btstack-observed-v1"
            if profile_id == "rpi-pico2-w"
            else "nimble-settled-v1"
        ),
    }
    for profile_id in PROFILE_ORDER
}

WORKLOAD = {
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
    "required_chunk_bytes": 229,
}

V051_WORKLOAD = {**WORKLOAD, "required_put_window": 8}

DERIVATION = {
    "application_image": "exact-byte-identical-two-root-v1",
    "application_headroom": "factory-minus-application-v1",
    "heap_floor": "floor-min-1024-waveshare-block-98304-v2",
    "boot_ceiling": "fixed-profile-product-slo-esp3000-pico7000-v4",
    "goodput_floor": "fixed-product-slo-64k-under-10s-6600-v3",
}

# Frozen historical derivation identity of the v0.5.1 schema-2 policy era.
# Schema-2 policies keep this arithmetic forever; only the active schema-3
# era uses DERIVATION above.
V051_DERIVATION = {
    "application_image": "exact-byte-identical-two-root-v1",
    "application_headroom": "factory-minus-application-v1",
    "heap_floor": "floor-min-1024-v1",
    "boot_ceiling": "fixed-product-slo-3000-v3",
    "goodput_floor": "floor-95pct-min-100-v2",
}

# ADR-0037 fixed product SLOs: ceil_100(65536 B / 10 s) = 6600 B/s for every
# profile; reset-to-service 3000 ms on the ESP profiles and 7000 ms on
# rpi-pico2-w.  These are product decisions, never functions of baseline
# extrema.
FIXED_RESET_SLO_MS_ESP = 3000
FIXED_RESET_SLO_MS_RP2 = 7000
FIXED_GOODPUT_FLOOR_BPS = 6600

# ADR-0039: the single fixed heap-floor exception — the Waveshare
# largest-block floor is the baseline-derived 102400 minus exactly one
# 4096-byte page, admitting that image's characterized single-page
# transient.  Never a function of observed samples.
FIXED_WAVESHARE_LARGEST_BLOCK_MIN_BYTES = 98304
WAVESHARE_PROFILE_ID = "waveshare-esp32-s3-lcd-147b"

RP2_PROFILE_ID = "rpi-pico2-w"

HEAP_KEYS = (
    "gc_free_bytes",
    "gc_allocated_bytes",
    "idf_internal_free_bytes",
    "idf_internal_largest_block_bytes",
    "idf_internal_minimum_free_bytes",
)

RP2_HEAP_KEYS = (
    "gc_free_bytes",
    "gc_allocated_bytes",
)

RP2_IMAGE_LIMIT_BYTES = 1_572_864
RP2_UF2_ARM_FAMILY = 0xE48BFF59
RP2_UF2_EXTENSION_FAMILY = 0xE48BFF57
RP2_UF2_IGNORE_BLOCK_TAG = 0x9957E304

THRESHOLD_KEYS = (
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

RP2_THRESHOLD_KEYS = (
    "firmware_bin_max_bytes",
    "firmware_image_headroom_min_bytes",
    "gc_free_min_bytes",
    "reset_to_service_advertisement_max_ms",
    "put_committed_goodput_min_bytes_per_second",
    "get_verified_goodput_min_bytes_per_second",
)

OBSERVATION_KEYS = (
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
    "transfer_link_facts",
    "physical_power_cycle_advertising",
    "raw_log_sha256",
)

RELIABILITY_KEYS = (
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
)

HELLO_PAYLOAD = (
    b"proto_versions=1\n"
    b"app_name=hil-oi1\n"
    b"app_version=0"
)

FRAME_OVERHEAD = 18
DEFAULT_ACK_TIMEOUT_S = 0.75
DEFAULT_OPERATION_TIMEOUT_S = 120.0
DEFAULT_EVENT_TIMEOUT_S = 15.0
HEAP_MARKER_PREFIX = "__PYBLE_OI1_HEAP_"
OI1_LINK_FACT_MARKER_PREFIX = "__PYBLE_OI1_LINK_FACTS_"
OI1_LINK_FACT_PAIR_TIMEOUT_S = 8.0
OI1_LINK_FACT_ACTIVE_TIMEOUT_S = 5.0
OI1_LINK_FACT_MAX_CHUNK_BYTES = 2048
OI1_LINK_FACT_MAX_CONSOLE_CHUNK_BYTES = 200
OI1_LINK_FACT_MAX_OUTPUT_BYTES = 8192
OI1_LINK_FACT_MAX_UINT32 = (1 << 32) - 1
OI1_LINK_FACT_MAX_EPOCH = (1 << 64) - 1


class BenchError(RuntimeError):
    """A qualification failure with operator-safe text."""


class StatusFailure(BenchError):
    def __init__(self, operation, status):
        self.operation = operation
        self.status = int(status)
        super().__init__("%s -> %s" % (operation, status_name(self.status)))


class IntegrityFailure(BenchError):
    pass


def _require_nonnegative_int(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BenchError("%s must be a non-negative JSON integer" % label)
    return value


def _require_positive_int(value, label):
    value = _require_nonnegative_int(value, label)
    if value == 0:
        raise BenchError("%s must be positive" % label)
    return value


def _require_exact_keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        missing = sorted(set(keys) - set(value) if isinstance(value, dict) else set(keys))
        extra = sorted(set(value) - set(keys) if isinstance(value, dict) else set())
        raise BenchError(
            "%s has wrong keys (missing=%s extra=%s)" % (label, missing, extra)
        )


def required_transport(*, profile_id=None, expected_chip=None):
    """Return the exact v0.6 transport tuple without borrowing a profile row."""
    if profile_id is not None:
        if profile_id not in PROFILE_ORDER:
            raise BenchError("profile is outside the current OI-1 order")
        if (
            expected_chip is not None
            and PROFILE_CHIPS[profile_id] != expected_chip
        ):
            raise BenchError("expected chip disagrees with profile")
        transport = PROFILE_TRANSPORTS[profile_id]
    else:
        matches = [
            PROFILE_TRANSPORTS[candidate]
            for candidate in PROFILE_ORDER
            if PROFILE_CHIPS[candidate] == expected_chip
        ]
        triples = {
            (
                item["required_att_mtu"],
                item["required_put_window"],
                item["required_chunk_bytes"],
            )
            for item in matches
        }
        if len(triples) != 1:
            raise BenchError("expected chip does not select one transport contract")
        mtu, window, chunk = next(iter(triples))
        return mtu, window, chunk
    return (
        transport["required_att_mtu"],
        transport["required_put_window"],
        transport["required_chunk_bytes"],
    )


def canonical_json_bytes(value):
    """Frozen OI-1 canonical form: sorted keys, indent 2, UTF-8, final LF."""
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise BenchError("value is not canonical JSON: %s" % exc) from exc
    return (text + "\n").encode("utf-8")


def atomic_write_canonical_json(path, value):
    """Atomically replace ``path`` with canonical JSON and fsync both levels."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value)
    fd, temporary = tempfile.mkstemp(
        prefix=".%s." % target.name,
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        try:
            directory_fd = os.open(str(target.parent), os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def deterministic_payload(profile_id, sample_index, size):
    """Generate frozen ``sha256-counter-v1`` payload bytes."""
    if profile_id not in PROFILE_ORDER:
        raise ValueError("profile is outside the current OI-1 order")
    if isinstance(sample_index, bool) or not isinstance(sample_index, int):
        raise ValueError("sample index must be an integer")
    if sample_index < 0 or sample_index > 0xFFFFFFFF:
        raise ValueError("sample index is outside u32")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError("payload size must be a non-negative integer")
    prefix = (
        b"PyBLE-OI1-v1\0"
        + profile_id.encode("utf-8")
        + b"\0"
        + sample_index.to_bytes(4, "little")
    )
    output = bytearray()
    block_index = 0
    while len(output) < size:
        output.extend(
            hashlib.sha256(prefix + block_index.to_bytes(4, "little")).digest()
        )
        block_index += 1
    return bytes(output[:size])


def _parse_partition_table(data):
    """Parse enough of an ESP-IDF binary table to prove factory arithmetic.

    This intentionally validates the table's binary/MD5 structure, unique
    labels, non-overlap, and exactly one factory application.  Release
    candidate validation separately enforces the profile's full frozen layout;
    the HIL runner does not duplicate that release-policy allowlist.
    """
    data = bytes(data)
    if len(data) < 64 or len(data) % 32:
        raise BenchError("partition table has invalid size")
    entries = []
    encoded_entries = bytearray()
    saw_md5 = False
    terminated = False
    for position in range(0, len(data), 32):
        chunk = data[position : position + 32]
        if chunk == b"\xff" * 32:
            terminated = True
            continue
        if terminated:
            raise BenchError("partition table contains data after its terminator")
        if chunk[:2] == b"\xeb\xeb":
            if saw_md5:
                raise BenchError("partition table has duplicate MD5 records")
            if chunk[:16] != b"\xeb\xeb" + b"\xff" * 14:
                raise BenchError("partition table has malformed MD5 record")
            expected = hashlib.md5(bytes(encoded_entries)).digest()  # nosec: format
            if chunk[16:] != expected:
                raise BenchError("partition table MD5 is incorrect")
            saw_md5 = True
            terminated = True
            continue
        if saw_md5:
            raise BenchError("partition follows partition-table MD5")
        magic, part_type, subtype, offset, size, raw_label, flags = struct.unpack(
            "<HBBII16sI", chunk
        )
        if magic != 0x50AA:
            raise BenchError("partition table has invalid entry magic")
        if size <= 0:
            raise BenchError("partition table contains an empty partition")
        try:
            label = raw_label.split(b"\0", 1)[0].decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise BenchError("partition table has a non-ASCII label") from exc
        if not label:
            raise BenchError("partition table contains an unnamed partition")
        if any(entry["label"] == label for entry in entries):
            raise BenchError("partition table contains duplicate label %s" % label)
        entries.append(
            {
                "type": part_type,
                "subtype": subtype,
                "offset": offset,
                "size": size,
                "label": label,
                "flags": flags,
            }
        )
        encoded_entries.extend(chunk)
    if not saw_md5:
        raise BenchError("partition table lacks its MD5 record")
    ordered = sorted(entries, key=lambda item: item["offset"])
    for left, right in zip(ordered, ordered[1:]):
        if left["offset"] + left["size"] > right["offset"]:
            raise BenchError(
                "partition table entries %s and %s overlap"
                % (left["label"], right["label"])
            )
    factories = [
        entry
        for entry in entries
        if entry["type"] == 0 and entry["subtype"] == 0
    ]
    if len(factories) != 1:
        raise BenchError("partition table must contain exactly one factory app")
    return entries, factories[0]


def oi1_build_from_bytes(application, partition_table):
    application = bytes(application)
    _, factory = _parse_partition_table(partition_table)
    application_size = len(application)
    factory_size = factory["size"]
    if application_size > factory_size:
        raise BenchError(
            "application image (%d bytes) does not fit factory partition (%d bytes)"
            % (application_size, factory_size)
        )
    return {
        "application_image_bytes": application_size,
        "factory_partition_bytes": factory_size,
        "application_headroom_bytes": factory_size - application_size,
    }


def _read_regular_file(path, label):
    path = Path(path)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise BenchError("cannot stat %s: %s" % (label, exc)) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise BenchError("%s must be a regular non-symlink file" % label)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise BenchError("cannot read %s: %s" % (label, exc)) from exc


def oi1_build_from_paths(application_path, partition_table_path):
    return oi1_build_from_bytes(
        _read_regular_file(application_path, "application image"),
        _read_regular_file(partition_table_path, "partition table"),
    )


def _reconstruct_rp2350_uf2(uf2):
    uf2 = bytes(uf2)
    if not uf2 or len(uf2) % 512:
        raise BenchError("RP2 firmware.uf2 is not a complete UF2 stream")
    arm_blocks = []
    extension_blocks = 0
    for offset in range(0, len(uf2), 512):
        block = uf2[offset : offset + 512]
        (
            magic_start0,
            magic_start1,
            flags,
            address,
            payload_size,
            block_number,
            total_blocks,
            family,
        ) = struct.unpack_from("<IIIIIIII", block, 0)
        magic_end = struct.unpack_from("<I", block, 508)[0]
        if (
            magic_start0 != 0x0A324655
            or magic_start1 != 0x9E5D5157
            or magic_end != 0x0AB16F30
        ):
            raise BenchError("RP2 firmware.uf2 block magic is invalid")
        if payload_size <= 0 or payload_size > 476:
            raise BenchError("RP2 firmware.uf2 payload length is invalid")
        payload = block[32 : 32 + payload_size]
        if flags == 0x00002000 and family == RP2_UF2_ARM_FAMILY:
            if any(block[32 + payload_size : 508]):
                raise BenchError(
                    "RP2 firmware.uf2 contains bytes outside a block payload"
                )
            arm_blocks.append(
                (address, block_number, total_blocks, payload)
            )
        elif (
            flags == 0x0000A000
            and family == RP2_UF2_EXTENSION_FAMILY
            and address == 0x10FFFF00
            and payload_size == 256
            and block_number == 0
            and total_blocks == 2
        ):
            extension_end = 32 + payload_size + 4
            if (
                struct.unpack_from("<I", block, 32 + payload_size)[0]
                != RP2_UF2_IGNORE_BLOCK_TAG
                or any(block[extension_end:508])
            ):
                raise BenchError(
                    "RP2 firmware.uf2 ignore-block extension tag is invalid"
                )
            if offset != 0:
                raise BenchError(
                    "RP2 firmware.uf2 ignore-block extension must be first"
                )
            extension_blocks += 1
        else:
            raise BenchError(
                "RP2 firmware.uf2 contains an unexpected family block"
            )
    if not arm_blocks or extension_blocks != 1:
        raise BenchError("RP2 firmware.uf2 lacks one exact RP2350 image")
    expected_total = arm_blocks[0][2]
    if expected_total != len(arm_blocks):
        raise BenchError("RP2 firmware.uf2 image block count is incomplete")
    for index, (address, block_number, total_blocks, payload) in enumerate(
        arm_blocks
    ):
        if (
            len(payload) != 256
            or block_number != index
            or total_blocks != expected_total
            or address != 0x10000000 + index * 256
        ):
            raise BenchError("RP2 firmware.uf2 image sequence is incomplete")
    return b"".join(
        payload for _address, _number, _total, payload in arm_blocks
    )


def rp2_oi1_build_from_paths(firmware_bin_path, firmware_uf2_path):
    raw_image = _read_regular_file(firmware_bin_path, "RP2 firmware.bin")
    install_image = _read_regular_file(firmware_uf2_path, "RP2 firmware.uf2")
    if not raw_image:
        raise BenchError("RP2 firmware.bin must be nonempty")
    if len(raw_image) > RP2_IMAGE_LIMIT_BYTES:
        raise BenchError("RP2 firmware.bin exceeds the frozen image limit")
    reconstructed = _reconstruct_rp2350_uf2(install_image)
    if (
        len(reconstructed) < len(raw_image)
        or reconstructed[: len(raw_image)] != raw_image
        or any(reconstructed[len(raw_image) :])
    ):
        raise BenchError(
            "RP2 firmware.uf2 does not reconstruct its sibling firmware.bin"
        )
    return {
        "firmware_bin_bytes": len(raw_image),
        "firmware_image_limit_bytes": RP2_IMAGE_LIMIT_BYTES,
        "firmware_image_headroom_bytes": RP2_IMAGE_LIMIT_BYTES
        - len(raw_image),
    }


def floor_quantum(value, quantum):
    _require_nonnegative_int(value, "value")
    _require_positive_int(quantum, "quantum")
    return (value // quantum) * quantum


def ceil_quantum(value, quantum):
    _require_nonnegative_int(value, "value")
    _require_positive_int(quantum, "quantum")
    return ((value + quantum - 1) // quantum) * quantum


def _validated_heap(snapshot, label, keys=HEAP_KEYS):
    _require_exact_keys(snapshot, keys, label)
    return {
        key: _require_nonnegative_int(snapshot[key], "%s.%s" % (label, key))
        for key in keys
    }


def _resource_build_kind(oi1_build):
    if not isinstance(oi1_build, dict):
        raise BenchError("oi1_build must be an object")
    keys = set(oi1_build)
    if keys == {
        "application_image_bytes",
        "factory_partition_bytes",
        "application_headroom_bytes",
    }:
        return "esp-idf"
    if keys == {
        "firmware_bin_bytes",
        "firmware_image_limit_bytes",
        "firmware_image_headroom_bytes",
    }:
        return "rp2"
    raise BenchError("oi1_build has the wrong target-specific keys")


def _qualification_samples(observation, *, heap_keys):
    if not isinstance(observation, dict):
        raise BenchError("oi1_observation must be an object")
    post_hello = observation.get("heap_post_hello")
    post_roundtrip = observation.get("heap_post_roundtrip")
    post_reliability = observation.get("heap_post_reliability")
    if not isinstance(post_hello, list) or len(post_hello) != 10:
        raise BenchError("heap_post_hello must contain 10 snapshots")
    if not isinstance(post_roundtrip, list) or len(post_roundtrip) != 5:
        raise BenchError("heap_post_roundtrip must contain 5 snapshots")
    snapshots = [
        _validated_heap(item, "heap snapshot", heap_keys)
        for item in post_hello + post_roundtrip
    ]
    snapshots.append(
        _validated_heap(post_reliability, "heap_post_reliability", heap_keys)
    )

    reset_samples = observation.get("reset_to_service_advertisement_ms")
    put_goodput = observation.get("put_committed_goodput_bytes_per_second")
    get_goodput = observation.get("get_verified_goodput_bytes_per_second")
    if not isinstance(reset_samples, list) or len(reset_samples) != 10:
        raise BenchError("reset latency must contain 10 samples")
    if not isinstance(put_goodput, list) or len(put_goodput) != 5:
        raise BenchError("PUT goodput must contain 5 samples")
    if not isinstance(get_goodput, list) or len(get_goodput) != 5:
        raise BenchError("GET goodput must contain 5 samples")
    return (
        snapshots,
        [
            _require_nonnegative_int(value, "reset latency")
            for value in reset_samples
        ],
        [_require_positive_int(value, "PUT goodput") for value in put_goodput],
        [_require_positive_int(value, "GET goodput") for value in get_goodput],
    )


def _require_profile_matches_resource_kind(profile_id, resource_kind):
    if profile_id is None:
        return
    if not isinstance(profile_id, str) or not profile_id:
        raise BenchError("profile_id must be a non-empty string")
    if (profile_id == RP2_PROFILE_ID) != (resource_kind == "rp2"):
        raise BenchError(
            "profile %s does not match %s build resources"
            % (profile_id, resource_kind)
        )


def derive_thresholds(oi1_build, observation, profile_id=None):
    resource_kind = _resource_build_kind(oi1_build)
    _require_profile_matches_resource_kind(profile_id, resource_kind)
    if resource_kind == "rp2":
        firmware_size = _require_nonnegative_int(
            oi1_build["firmware_bin_bytes"], "firmware_bin_bytes"
        )
        image_limit = _require_nonnegative_int(
            oi1_build["firmware_image_limit_bytes"],
            "firmware_image_limit_bytes",
        )
        headroom = _require_nonnegative_int(
            oi1_build["firmware_image_headroom_bytes"],
            "firmware_image_headroom_bytes",
        )
        if image_limit != RP2_IMAGE_LIMIT_BYTES:
            raise BenchError("RP2 firmware image limit has drifted")
        if image_limit - firmware_size != headroom:
            raise BenchError("RP2 firmware image headroom arithmetic disagrees")
        snapshots, _resets, _put_goodput, _get_goodput = (
            _qualification_samples(
                observation,
                heap_keys=RP2_HEAP_KEYS,
            )
        )
        return {
            "firmware_bin_max_bytes": firmware_size,
            "firmware_image_headroom_min_bytes": headroom,
            "gc_free_min_bytes": floor_quantum(
                min(item["gc_free_bytes"] for item in snapshots), 1024
            ),
            "reset_to_service_advertisement_max_ms": FIXED_RESET_SLO_MS_RP2,
            "put_committed_goodput_min_bytes_per_second": (
                FIXED_GOODPUT_FLOOR_BPS
            ),
            "get_verified_goodput_min_bytes_per_second": (
                FIXED_GOODPUT_FLOOR_BPS
            ),
        }

    application_size = _require_nonnegative_int(
        oi1_build["application_image_bytes"], "application_image_bytes"
    )
    factory_size = _require_nonnegative_int(
        oi1_build["factory_partition_bytes"], "factory_partition_bytes"
    )
    headroom = _require_nonnegative_int(
        oi1_build["application_headroom_bytes"], "application_headroom_bytes"
    )
    if factory_size - application_size != headroom:
        raise BenchError("application headroom arithmetic does not agree")

    snapshots, _resets, _put_goodput, _get_goodput = _qualification_samples(
        observation,
        heap_keys=HEAP_KEYS,
    )

    largest_block_floor = (
        # ADR-0039: the fixed Waveshare exception, never sample-derived.
        FIXED_WAVESHARE_LARGEST_BLOCK_MIN_BYTES
        if profile_id == WAVESHARE_PROFILE_ID
        else floor_quantum(
            min(
                item["idf_internal_largest_block_bytes"]
                for item in snapshots
            ),
            1024,
        )
    )
    return {
        "application_image_max_bytes": application_size,
        "application_headroom_min_bytes": headroom,
        "gc_free_min_bytes": floor_quantum(
            min(item["gc_free_bytes"] for item in snapshots), 1024
        ),
        "idf_internal_free_min_bytes": floor_quantum(
            min(item["idf_internal_free_bytes"] for item in snapshots), 1024
        ),
        "idf_internal_largest_block_min_bytes": largest_block_floor,
        "idf_internal_minimum_free_min_bytes": floor_quantum(
            min(item["idf_internal_minimum_free_bytes"] for item in snapshots),
            1024,
        ),
        "reset_to_service_advertisement_max_ms": FIXED_RESET_SLO_MS_ESP,
        "put_committed_goodput_min_bytes_per_second": (
            FIXED_GOODPUT_FLOOR_BPS
        ),
        "get_verified_goodput_min_bytes_per_second": (
            FIXED_GOODPUT_FLOOR_BPS
        ),
    }


def evaluate_thresholds(oi1_build, observation, thresholds, profile_id=None):
    resource_kind = _resource_build_kind(oi1_build)
    threshold_keys = (
        RP2_THRESHOLD_KEYS if resource_kind == "rp2" else THRESHOLD_KEYS
    )
    _require_exact_keys(thresholds, threshold_keys, "thresholds")
    for key in threshold_keys:
        _require_positive_int(thresholds[key], "thresholds.%s" % key)
    derived = derive_thresholds(oi1_build, observation, profile_id)
    if resource_kind == "rp2":
        heap_snapshots = (
            observation["heap_post_hello"]
            + observation["heap_post_roundtrip"]
            + [observation["heap_post_reliability"]]
        )
        ceiling_checks = {
            "firmware_bin_max_bytes": oi1_build["firmware_bin_bytes"],
            "reset_to_service_advertisement_max_ms": max(
                observation["reset_to_service_advertisement_ms"]
            ),
        }
        floor_checks = {
            "firmware_image_headroom_min_bytes": oi1_build[
                "firmware_image_headroom_bytes"
            ],
            "gc_free_min_bytes": min(
                item["gc_free_bytes"] for item in heap_snapshots
            ),
            "put_committed_goodput_min_bytes_per_second": min(
                observation["put_committed_goodput_bytes_per_second"]
            ),
            "get_verified_goodput_min_bytes_per_second": min(
                observation["get_verified_goodput_bytes_per_second"]
            ),
        }
        failures = []
        for key, actual in ceiling_checks.items():
            if actual > thresholds[key]:
                failures.append(
                    "%s=%d exceeds %d" % (key, actual, thresholds[key])
                )
        for key, actual in floor_checks.items():
            if actual < thresholds[key]:
                failures.append(
                    "%s=%d is below %d" % (key, actual, thresholds[key])
                )
        if failures:
            raise BenchError("OI-1 threshold failure: " + "; ".join(failures))
        return derived

    failures = []
    ceiling_checks = {
        "application_image_max_bytes": oi1_build["application_image_bytes"],
        "reset_to_service_advertisement_max_ms": max(
            observation["reset_to_service_advertisement_ms"]
        ),
    }
    floor_checks = {
        "application_headroom_min_bytes": oi1_build["application_headroom_bytes"],
        "gc_free_min_bytes": min(
            item["gc_free_bytes"]
            for item in (
                observation["heap_post_hello"]
                + observation["heap_post_roundtrip"]
                + [observation["heap_post_reliability"]]
            )
        ),
        "idf_internal_free_min_bytes": min(
            item["idf_internal_free_bytes"]
            for item in (
                observation["heap_post_hello"]
                + observation["heap_post_roundtrip"]
                + [observation["heap_post_reliability"]]
            )
        ),
        "idf_internal_largest_block_min_bytes": min(
            item["idf_internal_largest_block_bytes"]
            for item in (
                observation["heap_post_hello"]
                + observation["heap_post_roundtrip"]
                + [observation["heap_post_reliability"]]
            )
        ),
        "idf_internal_minimum_free_min_bytes": min(
            item["idf_internal_minimum_free_bytes"]
            for item in (
                observation["heap_post_hello"]
                + observation["heap_post_roundtrip"]
                + [observation["heap_post_reliability"]]
            )
        ),
        "put_committed_goodput_min_bytes_per_second": min(
            observation["put_committed_goodput_bytes_per_second"]
        ),
        "get_verified_goodput_min_bytes_per_second": min(
            observation["get_verified_goodput_bytes_per_second"]
        ),
    }
    for key, actual in ceiling_checks.items():
        if actual > thresholds[key]:
            failures.append("%s=%d exceeds %d" % (key, actual, thresholds[key]))
    for key, actual in floor_checks.items():
        if actual < thresholds[key]:
            failures.append("%s=%d is below %d" % (key, actual, thresholds[key]))
    if failures:
        raise BenchError("OI-1 threshold failure: " + "; ".join(failures))
    return derived


def parse_caps(payload):
    try:
        text = bytes(payload).decode("ascii", errors="strict")
    except (UnicodeDecodeError, TypeError, ValueError) as exc:
        raise BenchError("HELLO caps are not strict ASCII") from exc
    caps = {}
    for line in text.splitlines():
        if not line:
            continue
        if "=" not in line:
            raise BenchError("HELLO caps contain a non key=value line")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in caps:
            raise BenchError("HELLO caps contain an empty or duplicate key")
        caps[key] = value.strip()
    return caps


def _integer_cap(caps, key, *, allow_zero=False):
    raw = caps.get(key)
    if raw is None:
        raise BenchError("HELLO caps are missing %s" % key)
    if not re.fullmatch(r"[0-9]+", raw):
        raise BenchError("HELLO cap %s is not an unsigned integer" % key)
    value = int(raw, 10)
    if value == 0 and not allow_zero:
        raise BenchError("HELLO cap %s must be positive" % key)
    return value


def validate_oi1_caps(caps, *, expected_chip, backend_mtu, profile_id=None):
    chip = caps.get("chip", "")
    if chip != expected_chip:
        raise BenchError(
            "HELLO chip=%s does not match expected %s" % (chip or "<missing>", expected_chip)
        )
    mtu = _integer_cap(caps, "mtu")
    window = _integer_cap(caps, "window")
    chunk = _integer_cap(caps, "chunk")
    free_mem = _integer_cap(caps, "free_mem", allow_zero=True)
    required = required_transport(
        profile_id=profile_id,
        expected_chip=expected_chip,
    )
    if (mtu, window, chunk) != required:
        raise BenchError(
            "HELLO transport caps are mtu=%d window=%d chunk=%d; required %d/%d/%d"
            % ((mtu, window, chunk) + required)
        )
    if isinstance(backend_mtu, bool):
        raise BenchError("backend MTU evidence is not an integer")
    if backend_mtu is not None:
        try:
            backend_mtu = int(backend_mtu)
        except (TypeError, ValueError) as exc:
            raise BenchError("backend MTU evidence is not an integer") from exc
        if backend_mtu != mtu:
            raise BenchError(
                "backend ATT MTU %d disagrees with HELLO mtu=%d"
                % (backend_mtu, mtu)
            )
    return mtu, window, chunk, free_mem


def heap_probe_source(nonce):
    if not isinstance(nonce, str) or not re.fullmatch(r"[0-9A-Za-z_-]{1,64}", nonce):
        raise BenchError("heap-probe nonce is invalid")
    marker = HEAP_MARKER_PREFIX + nonce
    return (
        "import gc,esp32\n"
        "gc.collect()\n"
        "_gf=gc.mem_free();_ga=gc.mem_alloc()\n"
        "_hi=esp32.idf_heap_info(2052)\n"
        "_hf=0;_hl=0;_hm=0\n"
        "for _hr in _hi:\n"
        " _hf+=_hr[1];_hl=max(_hl,_hr[2]);_hm+=_hr[3]\n"
        'print("%s=%%d,%%d,%%d,%%d,%%d"%%(_gf,_ga,_hf,_hl,_hm))\n'
        % marker
    )


def rp2_heap_probe_source(nonce):
    if (
        not isinstance(nonce, str)
        or not re.fullmatch(r"[0-9A-Za-z_-]{1,64}", nonce)
    ):
        raise BenchError("heap-probe nonce is invalid")
    marker = HEAP_MARKER_PREFIX + nonce
    return (
        "import gc\n"
        "gc.collect()\n"
        "_gf=gc.mem_free();_ga=gc.mem_alloc()\n"
        'print("%s=%%d,%%d"%%(_gf,_ga))\n' % marker
    )


def parse_heap_probe_output(chunks, nonce):
    if not isinstance(chunks, (list, tuple)):
        raise BenchError("heap-probe output must be a chunk sequence")
    try:
        output = b"".join(bytes(chunk) for chunk in chunks).decode(
            "ascii", errors="strict"
        )
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise BenchError("heap-probe output is not strict ASCII") from exc
    pattern = re.compile(
        r"^"
        + re.escape(HEAP_MARKER_PREFIX + nonce)
        + r"=([0-9]+),([0-9]+),([0-9]+),([0-9]+),([0-9]+)$"
    )
    matches = []
    for line in output.splitlines():
        match = pattern.fullmatch(line)
        if match:
            matches.append(tuple(int(value, 10) for value in match.groups()))
    if len(matches) != 1:
        raise BenchError(
            "heap probe produced %d matching marker lines; expected one" % len(matches)
        )
    values = matches[0]
    snapshot = dict(zip(HEAP_KEYS, values))
    return _validated_heap(snapshot, "heap probe")


def parse_rp2_heap_probe_output(chunks, nonce):
    if not isinstance(chunks, (list, tuple)):
        raise BenchError("heap-probe output must be a chunk sequence")
    try:
        output = b"".join(bytes(chunk) for chunk in chunks).decode(
            "ascii", errors="strict"
        )
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise BenchError("heap-probe output is not strict ASCII") from exc
    pattern = re.compile(
        r"^"
        + re.escape(HEAP_MARKER_PREFIX + nonce)
        + r"=([0-9]+),([0-9]+)$"
    )
    matches = []
    for line in output.splitlines():
        match = pattern.fullmatch(line)
        if match:
            matches.append(tuple(int(value, 10) for value in match.groups()))
    if len(matches) != 1:
        raise BenchError(
            "RP2 heap probe produced %d matching marker lines; expected one"
            % len(matches)
        )
    snapshot = dict(zip(RP2_HEAP_KEYS, matches[0]))
    return _validated_heap(snapshot, "RP2 heap probe", RP2_HEAP_KEYS)


def _validated_probe_nonce(nonce):
    if (
        not isinstance(nonce, str)
        or not re.fullmatch(r"[0-9A-Za-z_-]{1,64}", nonce)
    ):
        raise BenchError("OI-1 link-fact probe nonce is invalid")
    return nonce


def _validated_oi1_link_fact_projection(projection):
    if type(projection) is not str or projection not in ("pair", "active"):
        raise BenchError("OI-1 link-fact probe projection is invalid")
    return projection


def oi1_link_fact_probe_source(nonce, *, projection):
    """Return the retained-profile RUN source for the hidden native snapshot."""
    marker = OI1_LINK_FACT_MARKER_PREFIX + _validated_probe_nonce(nonce)
    projection = _validated_oi1_link_fact_projection(projection)
    source = (
        "import json\n"
        "import pble_ble\n"
        "_oi1=pble_ble._oi1_link_facts()\n"
    )
    if projection == "active":
        source += '_oi1={"active":_oi1["active"],"last_ended":None}\n'
    return source + 'print("%s="+json.dumps(_oi1))\n' % marker


def _json_object_without_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _reject_json_constant(value):
    raise ValueError("non-finite JSON number: %s" % value)


def _bounded_probe_int(value, label, maximum=OI1_LINK_FACT_MAX_UINT32):
    value = _require_nonnegative_int(value, label)
    if value > maximum:
        raise BenchError("%s exceeds its frozen bound" % label)
    return value


def _validate_oi1_link_fact_facts(value, label):
    _require_exact_keys(
        value,
        ("dle", "phy", "connection_parameters", "tx_mbuf_starve_count"),
        label,
    )
    dle = value["dle"]
    _require_exact_keys(
        dle,
        ("request_attempts", "max_tx_octets", "max_tx_time_us"),
        label + ".dle",
    )
    if _bounded_probe_int(
        dle["request_attempts"], label + ".dle.request_attempts"
    ) > 4:
        raise BenchError(label + ".dle.request_attempts exceeds 4")
    _bounded_probe_int(
        dle["max_tx_octets"], label + ".dle.max_tx_octets", (1 << 16) - 1
    )
    _bounded_probe_int(
        dle["max_tx_time_us"], label + ".dle.max_tx_time_us", (1 << 16) - 1
    )

    phy = value["phy"]
    _require_exact_keys(
        phy,
        ("required_2m", "request_attempts", "updates", "settled_tx", "settled_rx"),
        label + ".phy",
    )
    if phy["required_2m"] is not True:
        raise BenchError(label + ".phy.required_2m must be true")
    if _bounded_probe_int(
        phy["request_attempts"], label + ".phy.request_attempts"
    ) > 4:
        raise BenchError(label + ".phy.request_attempts exceeds 4")
    if not isinstance(phy["updates"], list) or len(phy["updates"]) > 8:
        raise BenchError(label + ".phy.updates must contain at most 8 items")
    for index, update in enumerate(phy["updates"]):
        update_label = "%s.phy.updates[%d]" % (label, index)
        _require_exact_keys(update, ("status", "tx", "rx"), update_label)
        for key in ("status", "tx", "rx"):
            _bounded_probe_int(
                update[key], "%s.%s" % (update_label, key),
                OI1_LINK_FACT_MAX_UINT32 if key == "status" else (1 << 8) - 1,
            )
    _bounded_probe_int(
        phy["settled_tx"], label + ".phy.settled_tx", (1 << 8) - 1
    )
    _bounded_probe_int(
        phy["settled_rx"], label + ".phy.settled_rx", (1 << 8) - 1
    )

    connection = value["connection_parameters"]
    _require_exact_keys(
        connection,
        ("request_return_codes", "updates", "settled_interval_units"),
        label + ".connection_parameters",
    )
    codes = connection["request_return_codes"]
    if not isinstance(codes, list) or len(codes) > 3:
        raise BenchError(
            label + ".connection_parameters.request_return_codes "
            "must contain at most 3 items"
        )
    for index, code in enumerate(codes):
        _bounded_probe_int(
            code,
            "%s.connection_parameters.request_return_codes[%d]"
            % (label, index),
        )
    updates = connection["updates"]
    if not isinstance(updates, list) or len(updates) > 8:
        raise BenchError(
            label + ".connection_parameters.updates must contain at most 8 items"
        )
    for index, update in enumerate(updates):
        update_label = "%s.connection_parameters.updates[%d]" % (
            label,
            index,
        )
        _require_exact_keys(update, ("status", "interval_units"), update_label)
        _bounded_probe_int(update["status"], update_label + ".status")
        _bounded_probe_int(
            update["interval_units"], update_label + ".interval_units",
            (1 << 16) - 1,
        )
    _bounded_probe_int(
        connection["settled_interval_units"],
        label + ".connection_parameters.settled_interval_units",
        (1 << 16) - 1,
    )
    _bounded_probe_int(
        value["tx_mbuf_starve_count"], label + ".tx_mbuf_starve_count"
    )


def _validate_oi1_link_fact_record(value, label):
    _require_exact_keys(
        value,
        ("epoch", "final", "settled", "overflow", "facts"),
        label,
    )
    _bounded_probe_int(value["epoch"], label + ".epoch", OI1_LINK_FACT_MAX_EPOCH)
    if value["epoch"] == 0:
        raise BenchError(label + ".epoch must be positive")
    for key in ("final", "settled", "overflow"):
        if type(value[key]) is not bool:
            raise BenchError("%s.%s must be a boolean" % (label, key))
    _validate_oi1_link_fact_facts(value["facts"], label + ".facts")


def _validate_oi1_link_fact_snapshot(value):
    _require_exact_keys(value, ("active", "last_ended"), "OI-1 link snapshot")
    for key in ("active", "last_ended"):
        record = value[key]
        if record is not None:
            _validate_oi1_link_fact_record(record, "OI-1 link snapshot.%s" % key)
    return value


def parse_oi1_link_fact_probe_output(chunks, nonce, *, projection):
    projection = _validated_oi1_link_fact_projection(projection)
    marker = (OI1_LINK_FACT_MARKER_PREFIX + _validated_probe_nonce(nonce) + "=").encode(
        "ascii"
    )
    if not isinstance(chunks, (list, tuple)):
        raise BenchError("OI-1 link-fact output must be a chunk sequence")
    encoded = bytearray()
    try:
        for chunk in chunks:
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise BenchError("OI-1 link-fact output chunk must contain bytes")
            payload = bytes(chunk)
            if len(payload) > OI1_LINK_FACT_MAX_CHUNK_BYTES:
                raise BenchError("OI-1 link-fact output chunk exceeds its bound")
            if len(encoded) + len(payload) > OI1_LINK_FACT_MAX_OUTPUT_BYTES:
                raise BenchError("OI-1 link-fact output exceeds its total bound")
            encoded.extend(payload)
        output = bytes(encoded).decode("ascii", errors="strict")
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise BenchError("OI-1 link-fact output is not strict ASCII") from exc

    marker_text = marker.decode("ascii")
    matches = [line[len(marker_text):] for line in output.splitlines()
               if line.startswith(marker_text)]
    if len(matches) != 1:
        raise BenchError(
            "OI-1 link-fact probe produced %d matching marker lines; expected one"
            % len(matches)
        )
    try:
        snapshot = json.loads(
            matches[0],
            object_pairs_hook=_json_object_without_duplicates,
            parse_constant=_reject_json_constant,
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise BenchError("OI-1 link-fact marker contains invalid JSON") from exc
    snapshot = _validate_oi1_link_fact_snapshot(snapshot)
    for key in ("active", "last_ended"):
        record = snapshot[key]
        if record is not None and record["overflow"]:
            raise BenchError("OI-1 link snapshot.%s overflowed" % key)
    if snapshot["active"] is not None and snapshot["active"]["final"]:
        raise BenchError("OI-1 link snapshot.active must not be final")
    if snapshot["last_ended"] is not None and not snapshot["last_ended"]["final"]:
        raise BenchError("OI-1 link snapshot.last_ended must be final")
    if projection == "active":
        if snapshot["active"] is None or snapshot["last_ended"] is not None:
            raise BenchError(
                "OI-1 active projection requires active and last-ended null"
            )
    elif snapshot["active"] is None or snapshot["last_ended"] is None:
        raise BenchError("OI-1 pair projection requires active and last-ended records")
    return snapshot


async def run_oi1_link_fact_probe(
        central,
        next_id,
        *,
        projection,
        nonce=None,
        timeout_s,
        sleep=asyncio.sleep):
    """Read one strict retained-profile snapshot through an ordinary RUN."""
    projection = _validated_oi1_link_fact_projection(projection)
    if nonce is None:
        nonce = hashlib.sha256(
            ("%d:%d" % (time.monotonic_ns(), os.getpid())).encode("ascii")
        ).hexdigest()[:16]
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
        raise BenchError("OI-1 link-fact probe timeout is invalid")
    if projection == "pair":
        if timeout_s != OI1_LINK_FACT_PAIR_TIMEOUT_S:
            raise BenchError(
                "OI-1 pair projection requires its exact 8-second timeout cap"
            )
    elif not 0 < timeout_s <= OI1_LINK_FACT_ACTIVE_TIMEOUT_S:
        raise BenchError(
            "OI-1 active projection timeout must be within its 5-second cap"
        )
    source = oi1_link_fact_probe_source(
        nonce, projection=projection
    ).encode("utf-8")
    cursor = central.event_cursor()
    deadline = time.monotonic() + timeout_s

    def require_before_deadline():
        if time.monotonic() >= deadline:
            raise BenchError("OI-1 link-fact probe exhausted its deadline")

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise BenchError("OI-1 link-fact probe exhausted its deadline")
    try:
        response = await asyncio.wait_for(
            central.send_cmd(
                wire.OP_RUN,
                next_id(),
                b"\x01" + source,
                timeout=remaining,
            ),
            timeout=remaining,
        )
    except asyncio.TimeoutError as exc:
        raise BenchError("OI-1 link-fact probe exhausted its deadline") from exc
    require_before_deadline()
    status = rsp_status(response)
    if status != wire.ST_OK:
        raise StatusFailure("RUN OI-1 link-fact probe", status)

    stdout_chunks = []
    running_count = 0
    terminal_count = 0
    while terminal_count == 0:
        require_before_deadline()
        cursor, events = central.events_since(cursor)
        for event in events:
            require_before_deadline()
            if event.opcode == wire.OP_CONSOLE_DATA:
                if not event.payload:
                    raise BenchError(
                        "OI-1 link-fact probe emitted malformed CONSOLE_DATA"
                    )
                stream = event.payload[0]
                if stream == 1:
                    raise BenchError("OI-1 link-fact probe emitted stderr")
                if stream != 0:
                    raise BenchError(
                        "OI-1 link-fact probe emitted unknown console stream"
                    )
                chunk = event.payload[1:]
                if terminal_count:
                    raise BenchError(
                        "OI-1 link-fact probe emitted console data after terminal state"
                    )
                if len(chunk) > OI1_LINK_FACT_MAX_CONSOLE_CHUNK_BYTES:
                    raise BenchError(
                        "OI-1 link-fact output chunk exceeds its bound"
                    )
                stdout_chunks.append(chunk)
                if sum(len(item) for item in stdout_chunks) > OI1_LINK_FACT_MAX_OUTPUT_BYTES:
                    raise BenchError(
                        "OI-1 link-fact output exceeds its total bound"
                    )
            elif event.opcode == wire.OP_RUN_STATE:
                if len(event.payload) != 1:
                    raise BenchError(
                        "OI-1 link-fact probe emitted malformed RUN_STATE"
                    )
                state = event.payload[0]
                if state == 1:
                    running_count += 1
                    if running_count != 1 or terminal_count:
                        raise BenchError(
                            "OI-1 link-fact probe emitted duplicate/out-of-order running state"
                        )
                elif state == 2:
                    if running_count != 1:
                        raise BenchError(
                            "OI-1 link-fact probe ended without one running state"
                        )
                    terminal_count += 1
                    if terminal_count != 1:
                        raise BenchError(
                            "OI-1 link-fact probe emitted duplicate terminal state"
                        )
                elif state == 3:
                    raise BenchError(
                        "OI-1 link-fact probe ended in RUN_STATE(error)"
                    )
                else:
                    raise BenchError(
                        "OI-1 link-fact probe emitted unexpected RUN_STATE"
                    )
        if terminal_count == 0:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BenchError(
                    "OI-1 link-fact probe timed out before RUN_STATE(done)"
                )
            if not events:
                await sleep(min(0.002, remaining))
    snapshot = parse_oi1_link_fact_probe_output(
        stdout_chunks, nonce, projection=projection
    )
    require_before_deadline()
    return snapshot


def goodput_bps(unique_bytes, duration_ns):
    unique_bytes = _require_nonnegative_int(unique_bytes, "unique bytes")
    duration_ns = _require_positive_int(duration_ns, "duration_ns")
    return (unique_bytes * 1_000_000_000) // duration_ns


class DownloadVerifier:
    """Strict contiguous/unique offset, byte, size, and CRC verifier."""

    def __init__(self, expected):
        self.expected = bytes(expected)
        self._buffer = bytearray()
        self.retransmitted_chunks = 0
        self.retransmitted_bytes = 0
        self.offset_sequence_validated = False

    @property
    def unique_bytes(self):
        return len(self._buffer)

    def feed(self, offset, data):
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise IntegrityFailure("GET offset is not a non-negative integer")
        data = bytes(data)
        if not data:
            raise IntegrityFailure("GET_DATA contains no file bytes")
        expected_offset = len(self._buffer)
        if offset < expected_offset:
            self.retransmitted_chunks += 1
            self.retransmitted_bytes += len(data)
            raise IntegrityFailure(
                "GET offset %d duplicates/replays verified offset %d"
                % (offset, expected_offset)
            )
        if offset > expected_offset:
            raise IntegrityFailure(
                "GET offset gap: received %d, expected %d"
                % (offset, expected_offset)
            )
        if offset + len(data) > len(self.expected):
            raise IntegrityFailure("GET_DATA overruns advertised file size")
        wanted = self.expected[offset : offset + len(data)]
        if data != wanted:
            raise IntegrityFailure("GET_DATA bytes differ at offset %d" % offset)
        self._buffer.extend(data)

    def finish(self, end_crc):
        if isinstance(end_crc, bool) or not isinstance(end_crc, int):
            raise IntegrityFailure("GET_END CRC is not an integer")
        if len(self._buffer) != len(self.expected):
            raise IntegrityFailure(
                "GET ended at %d/%d bytes"
                % (len(self._buffer), len(self.expected))
            )
        expected_crc = wire.crc32(self.expected)
        if end_crc != expected_crc:
            raise IntegrityFailure(
                "GET_END CRC 0x%08x differs from 0x%08x"
                % (end_crc, expected_crc)
            )
        self.offset_sequence_validated = True
        return bytes(self._buffer)


class PutAccounting:
    def __init__(self):
        self._sent_offsets = set()
        self.retransmitted_chunks = 0
        self.retransmitted_bytes = 0
        self.rewinds = 0

    def note_send(self, offset, size):
        if offset in self._sent_offsets:
            self.retransmitted_chunks += 1
            self.retransmitted_bytes += int(size)
        else:
            self._sent_offsets.add(offset)

    def note_rewind(self):
        self.rewinds += 1


class CommandIds:
    def __init__(self):
        self._value = 0

    def next(self):
        self._value = (self._value % 255) + 1
        return self._value


@dataclass(frozen=True)
class PutResult:
    unique_committed_bytes: int
    duration_ns: int
    retransmitted_chunks: int
    retransmitted_bytes: int
    rewinds: int


@dataclass(frozen=True)
class GetResult:
    unique_verified_bytes: int
    duration_ns: int
    retransmitted_chunks: int
    retransmitted_bytes: int
    offset_sequence_validated: bool


def _u16(value):
    return int(value).to_bytes(2, "little")


def _u32(value):
    return int(value).to_bytes(4, "little")


def path_payload(path):
    encoded = path.encode("utf-8")
    if not encoded or len(encoded) > 128:
        raise BenchError("PBLE path must contain 1..128 UTF-8 bytes")
    return _u16(len(encoded)) + encoded


async def hello(
        central,
        next_id,
        *,
        expected_chip,
        profile_id=None,
        timeout_s=10.0):
    response = await central.send_cmd(
        wire.OP_HELLO,
        next_id(),
        HELLO_PAYLOAD,
        timeout=timeout_s,
    )
    status = rsp_status(response)
    if status != wire.ST_OK:
        raise StatusFailure("HELLO", status)
    caps = parse_caps(response.payload[1:])
    observed = validate_oi1_caps(
        caps,
        expected_chip=expected_chip,
        backend_mtu=central.backend_mtu,
        profile_id=profile_id,
    )
    try:
        central.confirm_caps_mtu(observed[0])
    except ValueError as exc:
        raise BenchError(str(exc)) from exc
    return caps, observed


async def run_heap_probe(
        central,
        next_id,
        *,
        nonce=None,
        timeout_s=DEFAULT_EVENT_TIMEOUT_S,
        sleep=asyncio.sleep):
    if nonce is None:
        nonce = hashlib.sha256(
            ("%d:%d" % (time.monotonic_ns(), os.getpid())).encode("ascii")
        ).hexdigest()[:16]
    source = heap_probe_source(nonce).encode("utf-8")
    cursor = central.event_cursor()
    response = await central.send_cmd(
        wire.OP_RUN,
        next_id(),
        b"\x01" + source,
        timeout=timeout_s,
    )
    status = rsp_status(response)
    if status != wire.ST_OK:
        raise StatusFailure("RUN heap probe", status)
    stdout_chunks = []
    deadline = time.monotonic() + timeout_s
    terminal = None
    while terminal is None:
        cursor, events = central.events_since(cursor)
        for event in events:
            if event.opcode == wire.OP_CONSOLE_DATA:
                if not event.payload:
                    raise BenchError("heap probe emitted malformed CONSOLE_DATA")
                stream = event.payload[0]
                if stream == 1:
                    raise BenchError(
                        "heap probe emitted stderr: %s"
                        % event.payload[1:].decode("utf-8", errors="replace")
                    )
                if stream == 0:
                    stdout_chunks.append(event.payload[1:])
            elif event.opcode == wire.OP_RUN_STATE:
                if len(event.payload) != 1:
                    raise BenchError("heap probe emitted malformed RUN_STATE")
                state = event.payload[0]
                if state == 2:
                    terminal = "done"
                elif state == 3:
                    raise BenchError("heap probe ended in RUN_STATE(error)")
        if terminal is None:
            if time.monotonic() >= deadline:
                raise BenchError("heap probe timed out before RUN_STATE(done)")
            await sleep(0.002)
    return parse_heap_probe_output(stdout_chunks, nonce)


async def run_rp2_heap_probe(
        central,
        next_id,
        *,
        nonce=None,
        timeout_s=DEFAULT_EVENT_TIMEOUT_S,
        sleep=asyncio.sleep):
    """Collect the RP2 GC-only heap shape without importing an ESP module."""
    if nonce is None:
        nonce = hashlib.sha256(
            ("%d:%d" % (time.monotonic_ns(), os.getpid())).encode("ascii")
        ).hexdigest()[:16]
    source = rp2_heap_probe_source(nonce).encode("utf-8")
    cursor = central.event_cursor()
    response = await central.send_cmd(
        wire.OP_RUN,
        next_id(),
        b"\x01" + source,
        timeout=timeout_s,
    )
    status = rsp_status(response)
    if status != wire.ST_OK:
        raise StatusFailure("RUN RP2 heap probe", status)
    stdout_chunks = []
    deadline = time.monotonic() + timeout_s
    terminal = None
    while terminal is None:
        cursor, events = central.events_since(cursor)
        for event in events:
            if event.opcode == wire.OP_CONSOLE_DATA:
                if not event.payload:
                    raise BenchError(
                        "RP2 heap probe emitted malformed CONSOLE_DATA"
                    )
                stream = event.payload[0]
                if stream == 1:
                    raise BenchError(
                        "RP2 heap probe emitted stderr: %s"
                        % event.payload[1:].decode("utf-8", errors="replace")
                    )
                if stream == 0:
                    stdout_chunks.append(event.payload[1:])
            elif event.opcode == wire.OP_RUN_STATE:
                if len(event.payload) != 1:
                    raise BenchError(
                        "RP2 heap probe emitted malformed RUN_STATE"
                    )
                state = event.payload[0]
                if state == 2:
                    terminal = "done"
                elif state == 3:
                    raise BenchError(
                        "RP2 heap probe ended in RUN_STATE(error)"
                    )
        if terminal is None:
            if time.monotonic() >= deadline:
                raise BenchError(
                    "RP2 heap probe timed out before RUN_STATE(done)"
                )
            await sleep(0.002)
    return parse_rp2_heap_probe_output(stdout_chunks, nonce)


C3_NVS_MARKER_PREFIX = "__PYBLE_OI1_C3_NVS_"


def _validated_c3_nvs_geometry(offset, size, block_bytes):
    for value, label in (
        (offset, "C3 NVS partition offset"),
        (size, "C3 NVS partition size"),
        (block_bytes, "C3 NVS probe block size"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise BenchError("%s must be a positive integer" % label)
    if size % block_bytes != 0:
        raise BenchError("C3 NVS partition size must be whole probe blocks")
    return offset, size, block_bytes


def c3_nvs_probe_source(nonce, *, offset, size, block_bytes):
    """Return the C3 RUN source that streams the raw NVS partition slice.

    The probe is strictly read-only: it opens the ``nvs`` data partition,
    echoes its exact geometry, and prints each flash block base64-encoded.
    It never imports or initializes the NVS API, so no key, namespace, or
    PHY-calibration write can occur during the capture.
    """

    if (
        not isinstance(nonce, str)
        or not re.fullmatch(r"[0-9A-Za-z_-]{1,64}", nonce)
    ):
        raise BenchError("C3 NVS probe nonce is invalid")
    offset, size, block_bytes = _validated_c3_nvs_geometry(
        offset, size, block_bytes
    )
    marker = C3_NVS_MARKER_PREFIX + nonce
    blocks = size // block_bytes
    return (
        "import binascii\n"
        "from esp32 import Partition\n"
        "_p = Partition.find(Partition.TYPE_DATA, label='nvs')[0]\n"
        "_i = _p.info()\n"
        'print("%s-geometry=%%d,%%d" %% (_i[2], _i[3]))\n'
        "_b = bytearray(%d)\n"
        "for _n in range(%d):\n"
        "    _p.readblocks(_n, _b)\n"
        '    print("%s-block-%%d=%%s"\n'
        "          %% (_n, binascii.b2a_base64(_b).decode().strip()))\n"
        % (marker, block_bytes, blocks, marker)
    )


def parse_c3_nvs_probe_output(chunks, nonce, *, offset, size, block_bytes):
    """Rebuild and bound-check the raw C3 NVS slice from probe stdout."""

    if not isinstance(chunks, (list, tuple)):
        raise BenchError("C3 NVS probe output must be a chunk sequence")
    if (
        not isinstance(nonce, str)
        or not re.fullmatch(r"[0-9A-Za-z_-]{1,64}", nonce)
    ):
        raise BenchError("C3 NVS probe nonce is invalid")
    offset, size, block_bytes = _validated_c3_nvs_geometry(
        offset, size, block_bytes
    )
    try:
        output = b"".join(bytes(chunk) for chunk in chunks).decode(
            "ascii", errors="strict"
        )
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise BenchError("C3 NVS probe output is not strict ASCII") from exc
    marker = re.escape(C3_NVS_MARKER_PREFIX + nonce)
    geometry_pattern = re.compile(
        r"^" + marker + r"-geometry=([0-9]+),([0-9]+)$"
    )
    block_pattern = re.compile(
        r"^" + marker + r"-block-([0-9]+)=([0-9A-Za-z+/]+={0,2})$"
    )
    geometries = []
    blocks = []
    for line in output.splitlines():
        geometry_match = geometry_pattern.fullmatch(line)
        if geometry_match:
            geometries.append(
                tuple(int(value, 10) for value in geometry_match.groups())
            )
            continue
        block_match = block_pattern.fullmatch(line)
        if block_match:
            blocks.append(
                (int(block_match.group(1), 10), block_match.group(2))
            )
    if geometries != [(offset, size)]:
        raise BenchError("C3 NVS probe geometry does not match the frozen slice")
    expected_blocks = size // block_bytes
    if [index for index, _encoded in blocks] != list(range(expected_blocks)):
        raise BenchError("C3 NVS probe blocks are missing or out of order")
    raw = bytearray()
    for _index, encoded in blocks:
        try:
            decoded = binascii.a2b_base64(encoded.encode("ascii"))
        except (ValueError, binascii.Error) as exc:
            raise BenchError("C3 NVS probe block is not valid base64") from exc
        if len(decoded) != block_bytes:
            raise BenchError("C3 NVS probe block size changed")
        raw.extend(decoded)
    if len(raw) != size:
        raise BenchError("C3 NVS probe slice size changed")
    return bytes(raw)


async def run_c3_nvs_probe(
        central,
        next_id,
        *,
        offset,
        size,
        block_bytes,
        nonce=None,
        timeout_s=60.0,
        sleep=asyncio.sleep):
    """Read the raw C3 NVS partition slice over one RUN probe session."""

    if nonce is None:
        nonce = hashlib.sha256(
            ("%d:%d" % (time.monotonic_ns(), os.getpid())).encode("ascii")
        ).hexdigest()[:16]
    source = c3_nvs_probe_source(
        nonce,
        offset=offset,
        size=size,
        block_bytes=block_bytes,
    ).encode("utf-8")
    cursor = central.event_cursor()
    response = await central.send_cmd(
        wire.OP_RUN,
        next_id(),
        b"\x01" + source,
        timeout=timeout_s,
    )
    status = rsp_status(response)
    if status != wire.ST_OK:
        raise StatusFailure("RUN C3 NVS probe", status)
    stdout_chunks = []
    deadline = time.monotonic() + timeout_s
    terminal = None
    while terminal is None:
        cursor, events = central.events_since(cursor)
        for event in events:
            if event.opcode == wire.OP_CONSOLE_DATA:
                if not event.payload:
                    raise BenchError(
                        "C3 NVS probe emitted malformed CONSOLE_DATA"
                    )
                stream = event.payload[0]
                if stream == 1:
                    raise BenchError(
                        "C3 NVS probe emitted stderr: %s"
                        % event.payload[1:].decode("utf-8", errors="replace")
                    )
                if stream == 0:
                    stdout_chunks.append(event.payload[1:])
            elif event.opcode == wire.OP_RUN_STATE:
                if len(event.payload) != 1:
                    raise BenchError(
                        "C3 NVS probe emitted malformed RUN_STATE"
                    )
                state = event.payload[0]
                if state == 2:
                    terminal = "done"
                elif state == 3:
                    raise BenchError(
                        "C3 NVS probe ended in RUN_STATE(error)"
                    )
        if terminal is None:
            if time.monotonic() >= deadline:
                raise BenchError(
                    "C3 NVS probe timed out before RUN_STATE(done)"
                )
            await sleep(0.002)
    return parse_c3_nvs_probe_output(
        stdout_chunks,
        nonce,
        offset=offset,
        size=size,
        block_bytes=block_bytes,
    )


async def _require_status(central, opcode, next_id, payload, operation, timeout=10.0):
    response = await central.send_cmd(opcode, next_id(), payload, timeout=timeout)
    status = rsp_status(response)
    if status != wire.ST_OK:
        raise StatusFailure(operation, status)
    return response


async def remove_if_present(central, path, next_id):
    response = await central.send_cmd(
        wire.OP_FILE_DELETE,
        next_id(),
        path_payload(path),
        timeout=10.0,
    )
    status = rsp_status(response)
    if status not in (wire.ST_OK, wire.ST_ENOENT):
        raise StatusFailure("FILE_DELETE", status)


async def ensure_directory(central, path, next_id):
    await _require_status(
        central,
        wire.OP_MKDIR,
        next_id,
        path_payload(path),
        "MKDIR",
    )


async def put_file(
        central,
        path,
        data,
        *,
        window,
        chunk,
        next_id,
        ack_timeout_s=DEFAULT_ACK_TIMEOUT_S,
        operation_timeout_s=DEFAULT_OPERATION_TIMEOUT_S,
        clock_ns=time.monotonic_ns,
        sleep=asyncio.sleep):
    data = bytes(data)
    if window not in {
        transport["required_put_window"]
        for transport in PROFILE_TRANSPORTS.values()
    }:
        raise BenchError("OI-1 PUT window is outside the profile contracts")
    if chunk != WORKLOAD["required_chunk_bytes"]:
        raise BenchError("OI-1 PUT requires chunk=229 with no override")
    total = len(data)
    crc = wire.crc32(data)
    begin_payload = _u32(total) + _u32(crc) + path_payload(path)

    start_ns = clock_ns()
    response = await central.send_cmd(
        wire.OP_FILE_PUT_BEGIN,
        next_id(),
        begin_payload,
        timeout=10.0,
    )
    status = rsp_status(response)
    if status != wire.ST_OK:
        raise StatusFailure("FILE_PUT_BEGIN", status)
    resume = int.from_bytes(response.payload[1:5], "little") if len(response.payload) >= 5 else 0
    if resume != 0:
        raise BenchError(
            "OI-1 requires a fresh PUT path; board returned resume_offset=%d" % resume
        )

    ack_scope = central.begin_ack_scope(0)
    accounting = PutAccounting()
    watermark = 0
    next_offset = 0
    valid_ack_offsets = {0}
    overall_deadline = time.monotonic() + operation_timeout_s
    progress_deadline = time.monotonic() + ack_timeout_s
    while watermark < total:
        while (
            next_offset < total
            and next_offset - watermark < window * chunk
        ):
            piece = data[next_offset : next_offset + chunk]
            accounting.note_send(next_offset, len(piece))
            await central.send_cmd_no_rsp(
                wire.OP_FILE_PUT_DATA,
                0,
                _u32(next_offset) + piece,
            )
            next_offset += len(piece)
            valid_ack_offsets.add(next_offset)

        try:
            observed = ack_scope.poll(
                sent_limit=next_offset,
                total=total,
                valid_offsets=valid_ack_offsets,
            )
        except ValueError as exc:
            raise BenchError(str(exc)) from exc
        now = time.monotonic()
        if observed > watermark:
            watermark = observed
            progress_deadline = now + ack_timeout_s
        elif now >= overall_deadline:
            raise BenchError(
                "PUT timed out at watermark %d/%d" % (watermark, total)
            )
        elif now >= progress_deadline:
            accounting.note_rewind()
            next_offset = watermark
            progress_deadline = now + ack_timeout_s
        await sleep(0.002)

    response = await central.send_cmd(
        wire.OP_FILE_PUT_END,
        next_id(),
        _u32(crc),
        timeout=10.0,
    )
    status = rsp_status(response)
    if status != wire.ST_OK:
        raise StatusFailure("FILE_PUT_END", status)
    end_ns = clock_ns()
    duration_ns = end_ns - start_ns
    _require_positive_int(duration_ns, "PUT duration_ns")

    # Whole-file verification is intentionally outside the frozen PUT timer.
    response = await central.send_cmd(
        wire.OP_FILE_STAT,
        next_id(),
        path_payload(path),
        timeout=10.0,
    )
    status = rsp_status(response)
    if status != wire.ST_OK:
        raise StatusFailure("FILE_STAT after PUT", status)
    if len(response.payload) != 9:
        raise IntegrityFailure("FILE_STAT response has the wrong length")
    got_size = int.from_bytes(response.payload[1:5], "little")
    got_crc = int.from_bytes(response.payload[5:9], "little")
    if got_size != total or got_crc != crc:
        raise IntegrityFailure(
            "FILE_STAT mismatch size=%d/%d crc=0x%08x/0x%08x"
            % (got_size, total, got_crc, crc)
        )
    return PutResult(
        unique_committed_bytes=total,
        duration_ns=duration_ns,
        retransmitted_chunks=accounting.retransmitted_chunks,
        retransmitted_bytes=accounting.retransmitted_bytes,
        rewinds=accounting.rewinds,
    )


async def get_file(
        central,
        path,
        expected,
        *,
        next_id,
        event_timeout_s=DEFAULT_EVENT_TIMEOUT_S,
        clock_ns=time.monotonic_ns,
        sleep=asyncio.sleep):
    expected = bytes(expected)
    verifier = DownloadVerifier(expected)
    cursor = central.event_cursor()
    start_ns = clock_ns()
    response = await central.send_cmd(
        wire.OP_FILE_GET_BEGIN,
        next_id(),
        _u32(0) + path_payload(path),
        timeout=10.0,
    )
    status = rsp_status(response)
    if status != wire.ST_OK:
        raise StatusFailure("FILE_GET_BEGIN", status)
    if len(response.payload) != 5:
        raise IntegrityFailure("FILE_GET_BEGIN response has the wrong length")
    total = int.from_bytes(response.payload[1:5], "little")
    if total != len(expected):
        raise IntegrityFailure(
            "FILE_GET_BEGIN total=%d, expected=%d" % (total, len(expected))
        )

    deadline = time.monotonic() + event_timeout_s
    while True:
        cursor, events = central.events_since(cursor)
        progressed = False
        for event in events:
            if event.opcode == wire.OP_FILE_GET_DATA:
                if len(event.payload) <= 4:
                    raise IntegrityFailure("FILE_GET_DATA payload is truncated")
                offset = int.from_bytes(event.payload[:4], "little")
                verifier.feed(offset, event.payload[4:])
                progressed = True
            elif event.opcode == wire.OP_FILE_GET_END:
                if len(event.payload) != 4:
                    raise IntegrityFailure("FILE_GET_END payload has the wrong length")
                end_crc = int.from_bytes(event.payload, "little")
                verifier.finish(end_crc)
                end_ns = clock_ns()
                duration_ns = end_ns - start_ns
                _require_positive_int(duration_ns, "GET duration_ns")
                return GetResult(
                    unique_verified_bytes=verifier.unique_bytes,
                    duration_ns=duration_ns,
                    retransmitted_chunks=verifier.retransmitted_chunks,
                    retransmitted_bytes=verifier.retransmitted_bytes,
                    offset_sequence_validated=verifier.offset_sequence_validated,
                )
        if progressed:
            deadline = time.monotonic() + event_timeout_s
        if time.monotonic() >= deadline:
            raise BenchError(
                "GET timed out after %d/%d verified bytes"
                % (verifier.unique_bytes, len(expected))
            )
        await sleep(0.002)


async def roundtrip_file(
        central,
        path,
        payload,
        *,
        next_id,
        window=8,
        chunk=229,
        clock_ns=time.monotonic_ns):
    await remove_if_present(central, path, next_id)
    put = await put_file(
        central,
        path,
        payload,
        window=window,
        chunk=chunk,
        next_id=next_id,
        clock_ns=clock_ns,
    )
    get = await get_file(
        central,
        path,
        payload,
        next_id=next_id,
        clock_ns=clock_ns,
    )
    await remove_if_present(central, path, next_id)
    return {
        "put_unique_committed_bytes": put.unique_committed_bytes,
        "put_duration_ns": put.duration_ns,
        "put_retransmitted_chunks": put.retransmitted_chunks,
        "put_retransmitted_bytes": put.retransmitted_bytes,
        "put_rewinds": put.rewinds,
        "get_unique_verified_bytes": get.unique_verified_bytes,
        "get_duration_ns": get.duration_ns,
        "get_retransmitted_chunks": get.retransmitted_chunks,
        "get_retransmitted_bytes": get.retransmitted_bytes,
        "integrity_verified": True,
        "offset_sequence_validated": get.offset_sequence_validated,
    }


async def run_reliability(central, profile_id, *, next_id, clock_ns=time.monotonic_ns):
    attempted = WORKLOAD["reliability_files"]
    size = WORKLOAD["reliability_file_bytes"]
    completed = 0
    verified = 0
    put_rtx_chunks = 0
    put_rtx_bytes = 0
    get_rtx_chunks = 0
    get_rtx_bytes = 0
    rewinds = 0
    _, required_window, required_chunk = required_transport(profile_id=profile_id)
    await ensure_directory(central, "oi1", next_id)
    for index in range(attempted):
        payload = deterministic_payload(
            profile_id,
            WORKLOAD["roundtrip_samples"] + index,
            size,
        )
        path = "oi1/reliability_%02d.bin" % index
        await remove_if_present(central, path, next_id)
        try:
            put = await put_file(
                central,
                path,
                payload,
                window=required_window,
                chunk=required_chunk,
                next_id=next_id,
                clock_ns=clock_ns,
            )
            completed += 1
            get = await get_file(
                central,
                path,
                payload,
                next_id=next_id,
                clock_ns=clock_ns,
            )
            verified += 1
            put_rtx_chunks += put.retransmitted_chunks
            put_rtx_bytes += put.retransmitted_bytes
            get_rtx_chunks += get.retransmitted_chunks
            get_rtx_bytes += get.retransmitted_bytes
            rewinds += put.rewinds
        except StatusFailure:
            raise
        except IntegrityFailure:
            raise
        finally:
            if central.is_connected:
                await remove_if_present(central, path, next_id)
    if completed != attempted or verified != attempted:
        raise BenchError(
            "reliability completed=%d verified=%d attempted=%d"
            % (completed, verified, attempted)
        )
    return {
        "attempted_files": attempted,
        "completed_files": completed,
        "verified_files": verified,
        "bytes_per_file": size,
        "total_payload_bytes": attempted * size,
        "unexpected_disconnects": 0,
        "integrity_failures": 0,
        "failed_statuses": 0,
        "retransmitted_chunks": put_rtx_chunks + get_rtx_chunks,
        "retransmitted_bytes": put_rtx_bytes + get_rtx_bytes,
        "rewinds": rewinds,
    }


async def measure_reset_to_advertisement(
        reset,
        watcher,
        *,
        hold_ms=WORKLOAD["reset_hold_ms"],
        timeout_ms=WORKLOAD["advertising_timeout_ms"],
        sleep=asyncio.sleep,
        monotonic_ns=time.monotonic_ns):
    """Measure controlled reset release to first fresh matching advertisement."""
    if hold_ms != WORKLOAD["reset_hold_ms"]:
        raise BenchError("OI-1 reset hold must be exactly 1000 ms")
    if timeout_ms != WORKLOAD["advertising_timeout_ms"]:
        raise BenchError("OI-1 advertisement timeout must be exactly 15000 ms")
    await watcher.start()
    try:
        reset.assert_reset()
        # An operator-confirmed reset/power-off can take long enough for the
        # already-running scanner to observe the board before it is actually
        # off.  Discard only that pre-confirmation epoch, then apply the full
        # quiet interval to callbacks observed after reset assertion has been
        # confirmed.
        watcher.begin_quiet_interval()
        try:
            await watcher.wait_for_quiet(hold_ms, timeout_ms)
        except asyncio.TimeoutError as exc:
            raise BenchError(
                "no continuous reset quiet interval within %d ms" % timeout_ms
            ) from exc
        reset.release_reset()
        # A serial reset controller returns immediately after releasing EN.
        # The exact Waveshare operator seam returns only after the operator has
        # released RESET and confirmed that physical action, so its proxy
        # release boundary is the first host timestamp after this call.
        release_ns = watcher.begin_post_release_interval(monotonic_ns)
        try:
            match_ns = await watcher.wait_for_match(timeout_ms)
        except asyncio.TimeoutError as exc:
            raise BenchError(
                "no fresh PyBLE advertisement within %d ms" % timeout_ms
            ) from exc
        if match_ns <= release_ns:
            raise BenchError("advertisement timestamp is not after reset release")
        elapsed_ns = match_ns - release_ns
        return (elapsed_ns + 999_999) // 1_000_000
    finally:
        await watcher.stop()


def validate_reliability(value):
    _require_exact_keys(value, RELIABILITY_KEYS, "reliability")
    normalized = {
        key: _require_nonnegative_int(value[key], "reliability.%s" % key)
        for key in RELIABILITY_KEYS
    }
    expected = {
        "attempted_files": 20,
        "completed_files": 20,
        "verified_files": 20,
        "bytes_per_file": 16384,
        "total_payload_bytes": 327680,
        "unexpected_disconnects": 0,
        "integrity_failures": 0,
        "failed_statuses": 0,
    }
    for key, required in expected.items():
        if normalized[key] != required:
            raise BenchError(
                "reliability.%s=%d, required %d"
                % (key, normalized[key], required)
            )
    return normalized


def _validated_link_update(value, keys, label):
    _require_exact_keys(value, keys, label)
    return {
        key: _require_nonnegative_int(value[key], "%s.%s" % (label, key))
        for key in keys
    }


def validate_transfer_link_facts(value, *, profile_id):
    """Validate the strict, identifier-free ADR-0027 transfer-session facts."""
    if profile_id == "rpi-pico2-w":
        _require_exact_keys(
            value,
            (
                "ble_host",
                "observed_att_mtu",
                "observed_window",
                "observed_chunk_bytes",
                "console_tx_budget_ms",
            ),
            "transfer_link_facts",
        )
        if value["ble_host"] != "btstack":
            raise BenchError("RP2 transfer facts must identify BTstack")
        for key, required in (
            ("observed_att_mtu", 247),
            ("observed_window", 4),
            ("observed_chunk_bytes", 229),
        ):
            actual = _require_nonnegative_int(
                value[key], "transfer_link_facts.%s" % key
            )
            if actual != required:
                raise BenchError(
                    "RP2 transfer_link_facts.%s=%d, required %d"
                    % (key, actual, required)
                )
        _require_positive_int(
            value["console_tx_budget_ms"],
            "transfer_link_facts.console_tx_budget_ms",
        )
        return value
    if profile_id not in ESP_PROFILE_ORDER:
        raise BenchError("NimBLE transfer facts require an ESP profile")
    _require_exact_keys(
        value,
        ("dle", "phy", "connection_parameters", "tx_mbuf_starve_count"),
        "transfer_link_facts",
    )

    dle = value["dle"]
    _require_exact_keys(
        dle,
        ("request_attempts", "max_tx_octets", "max_tx_time_us"),
        "transfer_link_facts.dle",
    )
    dle_attempts = _require_nonnegative_int(
        dle["request_attempts"],
        "transfer_link_facts.dle.request_attempts",
    )
    if not 1 <= dle_attempts <= 4:
        raise BenchError("DLE request attempts must be in 1..4")
    if _require_nonnegative_int(
        dle["max_tx_octets"],
        "transfer_link_facts.dle.max_tx_octets",
    ) < 244:
        raise BenchError("settled DLE max_tx_octets must be at least 244")
    _require_positive_int(
        dle["max_tx_time_us"],
        "transfer_link_facts.dle.max_tx_time_us",
    )

    phy = value["phy"]
    _require_exact_keys(
        phy,
        (
            "required_2m",
            "request_attempts",
            "updates",
            "settled_tx",
            "settled_rx",
        ),
        "transfer_link_facts.phy",
    )
    if not isinstance(phy["required_2m"], bool):
        raise BenchError("transfer_link_facts.phy.required_2m must be a boolean")
    phy_attempts = _require_nonnegative_int(
        phy["request_attempts"],
        "transfer_link_facts.phy.request_attempts",
    )
    if not isinstance(phy["updates"], list):
        raise BenchError("transfer_link_facts.phy.updates must be a list")
    phy_updates = [
        _validated_link_update(
            update,
            ("status", "tx", "rx"),
            "transfer_link_facts.phy.updates[%d]" % index,
        )
        for index, update in enumerate(phy["updates"])
    ]
    settled_tx = _require_nonnegative_int(
        phy["settled_tx"], "transfer_link_facts.phy.settled_tx"
    )
    settled_rx = _require_nonnegative_int(
        phy["settled_rx"], "transfer_link_facts.phy.settled_rx"
    )
    if PROFILE_REQUIRES_2M[profile_id]:
        if phy["required_2m"] is not True:
            raise BenchError("2M transfer facts must require 2M PHY")
        if not 1 <= phy_attempts <= 4:
            raise BenchError("2M PHY request attempts must be in 1..4")
        if not phy_updates:
            raise BenchError("2M PHY updates must not be empty")
        if (settled_tx, settled_rx) != (2, 2):
            raise BenchError("PHY must settle at 2M/2M")
        final_phy = phy_updates[-1]
        if (final_phy["status"], final_phy["tx"], final_phy["rx"]) != (
            0,
            settled_tx,
            settled_rx,
        ):
            raise BenchError("final PHY update does not confirm settled 2M/2M")
    else:
        if phy["required_2m"] is not False:
            raise BenchError("classic transfer facts must compile out 2M PHY")
        if phy_attempts != 0 or phy_updates:
            raise BenchError("classic PHY request attempts and updates must be empty")
        if (settled_tx, settled_rx) != (0, 0):
            raise BenchError("classic settled PHY values must both be zero")

    connection = value["connection_parameters"]
    _require_exact_keys(
        connection,
        ("request_return_codes", "updates", "settled_interval_units"),
        "transfer_link_facts.connection_parameters",
    )
    return_codes = connection["request_return_codes"]
    if not isinstance(return_codes, list) or not 1 <= len(return_codes) <= 3:
        raise BenchError("connection-parameter requests must contain 1..3 entries")
    for index, return_code in enumerate(return_codes):
        _require_nonnegative_int(
            return_code,
            "transfer_link_facts.connection_parameters."
            "request_return_codes[%d]" % index,
        )
    updates = connection["updates"]
    if not isinstance(updates, list) or not updates:
        raise BenchError("connection-parameter updates must not be empty")
    normalized_updates = [
        _validated_link_update(
            update,
            ("status", "interval_units"),
            "transfer_link_facts.connection_parameters.updates[%d]" % index,
        )
        for index, update in enumerate(updates)
    ]
    settled_interval = _require_nonnegative_int(
        connection["settled_interval_units"],
        "transfer_link_facts.connection_parameters.settled_interval_units",
    )
    final_update = normalized_updates[-1]
    if final_update["status"] != 0:
        raise BenchError("final connection-parameter update status must be zero")
    if settled_interval != final_update["interval_units"]:
        raise BenchError("settled connection interval must match the final update")
    if not 12 <= settled_interval <= 24:
        raise BenchError("settled connection interval must be in 12..24 units")

    _require_nonnegative_int(
        value["tx_mbuf_starve_count"],
        "transfer_link_facts.tx_mbuf_starve_count",
    )
    return value


def validate_observation(value, *, profile_id):
    _, required_window, _ = required_transport(profile_id=profile_id)
    heap_keys = (
        RP2_HEAP_KEYS if profile_id == "rpi-pico2-w" else HEAP_KEYS
    )
    _require_exact_keys(value, OBSERVATION_KEYS, "oi1_observation")
    for key, required in (
        ("observed_att_mtu", 247),
        ("observed_window", required_window),
        ("observed_chunk_bytes", 229),
        ("roundtrip_integrity_verified", 5),
        ("get_offset_sequences_validated", 5),
        ("roundtrip_unexpected_disconnects", 0),
        ("roundtrip_integrity_failures", 0),
    ):
        actual = _require_nonnegative_int(value[key], key)
        if actual != required:
            raise BenchError("%s=%d, required %d" % (key, actual, required))
    arrays = {
        "reset_to_service_advertisement_ms": 10,
        "heap_default_free_post_hello_bytes": 10,
        "heap_post_hello": 10,
        "put_unique_committed_bytes": 5,
        "put_duration_ns": 5,
        "put_committed_goodput_bytes_per_second": 5,
        "get_unique_verified_bytes": 5,
        "get_duration_ns": 5,
        "get_verified_goodput_bytes_per_second": 5,
        "put_retransmitted_chunks": 5,
        "put_retransmitted_bytes": 5,
        "get_retransmitted_chunks": 5,
        "get_retransmitted_bytes": 5,
        "heap_post_roundtrip": 5,
    }
    for key, length in arrays.items():
        if not isinstance(value[key], list) or len(value[key]) != length:
            raise BenchError("%s must contain %d entries" % (key, length))
    for key in (
        "reset_to_service_advertisement_ms",
        "heap_default_free_post_hello_bytes",
        "put_retransmitted_chunks",
        "put_retransmitted_bytes",
        "get_retransmitted_chunks",
        "get_retransmitted_bytes",
    ):
        for item in value[key]:
            _require_nonnegative_int(item, key)
    for key in (
        "put_unique_committed_bytes",
        "get_unique_verified_bytes",
    ):
        for item in value[key]:
            if _require_nonnegative_int(item, key) != 65536:
                raise BenchError("%s entries must equal 65536" % key)
    for duration_key, goodput_key in (
        ("put_duration_ns", "put_committed_goodput_bytes_per_second"),
        ("get_duration_ns", "get_verified_goodput_bytes_per_second"),
    ):
        for duration, reported in zip(value[duration_key], value[goodput_key]):
            _require_positive_int(duration, duration_key)
            _require_positive_int(reported, goodput_key)
            expected = goodput_bps(65536, duration)
            if reported != expected:
                raise BenchError(
                    "%s=%d does not match duration-derived %d"
                    % (goodput_key, reported, expected)
                )
    for index, snapshot in enumerate(value["heap_post_hello"]):
        _validated_heap(
            snapshot,
            "heap_post_hello[%d]" % index,
            heap_keys,
        )
    for index, snapshot in enumerate(value["heap_post_roundtrip"]):
        _validated_heap(
            snapshot,
            "heap_post_roundtrip[%d]" % index,
            heap_keys,
        )
    _validated_heap(
        value["heap_post_reliability"],
        "heap_post_reliability",
        heap_keys,
    )
    validate_reliability(value["reliability"])
    validate_transfer_link_facts(
        value["transfer_link_facts"], profile_id=profile_id
    )
    if value["physical_power_cycle_advertising"] != "passed":
        raise BenchError("physical power-cycle advertising must be passed")
    if not isinstance(value["raw_log_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", value["raw_log_sha256"]
    ):
        raise BenchError("raw_log_sha256 must be lowercase SHA-256")
    return value


class RedactedRawLog:
    """Access-controlled JSONL log that deliberately excludes transport IDs."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(self.path, flags, 0o600)
            os.fchmod(descriptor, 0o600)
            self._stream = os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
                newline="\n",
            )
            descriptor = None
        except FileExistsError as exc:
            raise BenchError(
                "raw log already exists; choose a new retained path"
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        self._closed = False
        self._sequence = 0

    def write(self, event, **fields):
        if self._closed:
            raise BenchError("raw log is closed")
        if not isinstance(event, str) or not event:
            raise BenchError("raw-log event name is invalid")
        forbidden = {"address", "reset_port", "serial_port", "device_id", "label"}
        if forbidden & set(fields):
            raise BenchError("raw log fields include a non-redacted identifier")
        self._sequence += 1
        record = {"event": event, "sequence": self._sequence}
        record.update(fields)
        self._stream.write(
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        )
        self._stream.flush()

    def sha256(self):
        if not self._closed:
            self._stream.flush()
            os.fsync(self._stream.fileno())
        return sha256_file(self.path)

    def close(self):
        if not self._closed:
            self._stream.flush()
            os.fsync(self._stream.fileno())
            self._stream.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
