#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""ADR-0023 exact-board ST7789 hardware-in-the-loop runner.

The three explicit stages intentionally use a new BLE connection each time:
``exercise`` renders and cleans up, ``soft-reboot`` obtains the PBLE/1 reboot
acknowledgement, and ``post-reboot`` proves that a fresh connection can import
the frozen runtime.  Results never contain the BLE address, device ID, label,
or raw INFO bytes.
"""

import argparse
import asyncio
import hashlib
import inspect
import json
import math
import os
import re
import secrets
import stat
import sys
import time
from pathlib import Path

import _pble_wire as wire
from _pble_bench import (
    BenchError,
    CommandIds,
    canonical_json_bytes,
    parse_caps,
)
from _pble_central import (
    PbleCentral,
    PbleConnectError,
    PbleLinkLossError,
    rsp_status,
    status_name,
)


SCHEMA_VERSION = 1
PROFILE_ID = "waveshare-esp32-s3-lcd-147b"
EXPECTED_CHIP = "esp32-s3"
BOARD_MODEL = "ESP32-S3-LCD-1.47B"
FLASH_CAPACITY_BYTES = 16 * 1024 * 1024
PSRAM_CAPACITY_BYTES = 8 * 1024 * 1024
EXPECTED_AGENT_VERSION = "0.5.1"
EXPECTED_MPY_VERSION = "1.28.0"
BOOT_PARTITION_IMMUTABLE_END = 0x9000
APPLICATION_OFFSET = 0x10000
FACTORY_APPLICATION_END = 0x210000
WIDTH = 172
HEIGHT = 320
X_OFFSET = 34
Y_OFFSET = 0
PINS = {
    "sck": 40,
    "mosi": 45,
    "cs": 42,
    "dc": 41,
    "reset": 39,
    "backlight": 46,
}
REFRESH_COUNT = 6
MIN_RESPONSIVE_PROBES = 3
RESPONSIVENESS_WINDOW_MS = 300
MIN_RUNTIME_VISIBLE_PSRAM_BYTES = 7 * 1024 * 1024
RUN_SOURCE_LIMIT = 2048
QUALIFICATION_REBOOT_CYCLES = 3
REBOOT_DELIVERY_GRACE_S = 0.25
RECONNECT_POLL_S = 0.1
VISUAL_CONFIRMATION_HOLD_MS = 5000
VISUAL_PATTERN_ID = "st7789-172x320-border-rgb-corners-text-progress-v1"

MARKER_PREFIX = "__PYBLE_TFT_V1_"
MEMORY_MARKER = MARKER_PREFIX + "MEM"
BACKLIGHT_MARKER = MARKER_PREFIX + "BL"
PATTERN_MARKER = MARKER_PREFIX + "PATTERN"
REFRESH_MARKER = MARKER_PREFIX + "REFRESH"
CLEANUP_MARKER = MARKER_PREFIX + "CLEANUP"
VISUAL_RELEASE_MARKER = MARKER_PREFIX + "VISUAL_RELEASE"
VISUAL_RELEASE_INPUT = b"__PYBLE_TFT_VISUAL_CONFIRMED_V1__"
OPERATOR_CLEANUP_RESERVE_S = 2.0
DEFAULT_OPERATOR_TIMEOUT_S = 900.0
MAX_OPERATOR_TIMEOUT_S = 900.0
CANDIDATE_MARKER = MARKER_PREFIX + "CANDIDATE"
PRE_REBOOT_MARKER = MARKER_PREFIX + "PRE_REBOOT=armed"
POST_REBOOT_MARKER = MARKER_PREFIX + "POST_REBOOT=imported"
STALE_VM_MARKER = MARKER_PREFIX + "STALE_VM=detected"
VM_SENTINEL = "__PYBLE_TFT_VM_EPOCH_V1__"

HELLO_PAYLOAD = (
    b"proto_versions=1\n"
    b"app_name=hil-tft-adr0023\n"
    b"app_version=0"
)

PREFLIGHT_KEYS = {
    "schema_version",
    "profile_id",
    "chip",
    "board_model",
    "flash_capacity_bytes",
    "psram_capacity_bytes",
    "discovery_method",
}

STATE_NAMES = {
    0: "idle",
    1: "running",
    2: "done",
    3: "error",
}

_PROCESS_CONTROL_EXCEPTIONS = (
    asyncio.CancelledError,
    KeyboardInterrupt,
    SystemExit,
    GeneratorExit,
)


class StaleVmEpochError(BenchError):
    """The post-reboot connection still reached the pre-reboot interpreter."""


def _validate_operator_timeout(value):
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value <= 0
        or value > MAX_OPERATOR_TIMEOUT_S
        or not math.isfinite(value)
    ):
        raise BenchError(
            "operator timeout must be finite and in (0, 900] seconds"
        )
    return float(value)


async def _invoke_operator_callback(callback, args):
    try:
        value = callback(*args)
        if inspect.isawaitable(value):
            value = await value
    except BaseException as caught:
        return False, caught
    return True, value


async def _cancel_and_drain_operator_task(task):
    current = asyncio.current_task()
    cancelling = getattr(current, "cancelling", None)
    cancellation_count = cancelling() if callable(cancelling) else 0
    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        if callable(cancelling) and cancelling() > cancellation_count:
            raise
    except BaseException:
        pass


async def _await_operator_callback(callback, *args, timeout_s, label):
    """Await one callback without treating timeout cancellation as process control."""
    timeout_s = _validate_operator_timeout(timeout_s)
    task = asyncio.create_task(_invoke_operator_callback(callback, args))
    try:
        done, _pending = await asyncio.wait({task}, timeout=timeout_s)
    except BaseException:
        await _cancel_and_drain_operator_task(task)
        raise
    if task not in done:
        await _cancel_and_drain_operator_task(task)
        raise BenchError("%s timed out" % label)
    succeeded, result = task.result()
    if succeeded:
        return result
    raise result


def _require_nonnegative_int(value, label):
    if type(value) is not int or value < 0:
        raise BenchError("%s must be a non-negative integer" % label)
    return value


def validate_preflight(value):
    """Require one sanitized, exact-board read-only discovery record."""
    if not isinstance(value, dict) or set(value) != PREFLIGHT_KEYS:
        missing = sorted(PREFLIGHT_KEYS - set(value) if isinstance(value, dict) else PREFLIGHT_KEYS)
        extra = sorted(set(value) - PREFLIGHT_KEYS if isinstance(value, dict) else set())
        raise BenchError(
            "preflight has wrong keys (missing=%s extra=%s)" % (missing, extra)
        )
    expected = {
        "schema_version": SCHEMA_VERSION,
        "profile_id": PROFILE_ID,
        "chip": EXPECTED_CHIP,
        "board_model": BOARD_MODEL,
        "flash_capacity_bytes": FLASH_CAPACITY_BYTES,
        "psram_capacity_bytes": PSRAM_CAPACITY_BYTES,
        "discovery_method": "esptool-read-only",
    }
    for key, required in expected.items():
        actual = value[key]
        if type(actual) is not type(required) or actual != required:
            raise BenchError(
                "preflight %s=%r does not match exact-board value %r"
                % (key, actual, required)
            )
    return dict(value)


def load_preflight(path):
    """Load a regular, non-symlink JSON record and enforce the exact schema."""
    source = Path(path)
    try:
        metadata = source.lstat()
    except OSError as exc:
        raise BenchError("cannot stat preflight record") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise BenchError("preflight record must be a regular non-symlink file")
    try:
        raw = source.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchError("preflight record is not strict UTF-8 JSON") from exc
    return validate_preflight(value)


def inspect_candidate_firmware(path):
    """Measure one merged image and its runtime-immutable flash spans."""
    source = Path(path)
    if source.name != "firmware.bin":
        raise BenchError("candidate firmware must be named firmware.bin")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(source), flags)
    except OSError as exc:
        raise BenchError("cannot open candidate firmware.bin") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise BenchError("candidate firmware.bin must be a nonempty regular file")
        size_bytes = _validate_candidate_size(metadata.st_size)
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            payload = stream.read(size_bytes + 1)
            stream.seek(0)
            repeated_payload = stream.read(size_bytes + 1)
            after = os.fstat(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    identity_fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    if len(payload) != size_bytes or repeated_payload != payload or any(
        getattr(after, key) != getattr(metadata, key) for key in identity_fields
    ):
        raise BenchError("candidate firmware.bin changed while it was inspected")
    mutable = payload[BOOT_PARTITION_IMMUTABLE_END:APPLICATION_OFFSET]
    if mutable != b"\xff" * (APPLICATION_OFFSET - BOOT_PARTITION_IMMUTABLE_END):
        raise BenchError("candidate NVS/PHY-init image bytes must be erased")
    spans = _expected_candidate_spans(size_bytes)
    immutable = b"".join(
        payload[item["offset"]:item["offset"] + item["size_bytes"]]
        for item in spans
    )
    attestation = {
        "sha256": hashlib.sha256(immutable).hexdigest(),
        "size_bytes": len(immutable),
        "spans": spans,
    }
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": size_bytes,
        "attestation": attestation,
    }


def hash_candidate_firmware(path):
    return inspect_candidate_firmware(path)["sha256"]


def record_sha256(value):
    """Digest one canonical, redacted qualification record."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _validate_candidate_sha256(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise BenchError("candidate firmware SHA-256 is not canonical lowercase hex")
    return value


def _validate_candidate_size(value):
    if (
        type(value) is not int
        or value <= APPLICATION_OFFSET
        or value > FACTORY_APPLICATION_END
    ):
        raise BenchError("candidate firmware byte length is outside the factory image")
    return value


def _expected_candidate_spans(candidate_size_bytes):
    candidate_size_bytes = _validate_candidate_size(candidate_size_bytes)
    return [
        {"offset": 0, "size_bytes": BOOT_PARTITION_IMMUTABLE_END},
        {
            "offset": APPLICATION_OFFSET,
            "size_bytes": candidate_size_bytes - APPLICATION_OFFSET,
        },
    ]


def _validate_candidate_attestation(value, candidate_size_bytes=None):
    if not isinstance(value, dict) or set(value) != {
        "sha256",
        "size_bytes",
        "spans",
    }:
        raise BenchError("candidate attestation has wrong keys")
    digest = _validate_candidate_sha256(value["sha256"])
    if not isinstance(value["spans"], list):
        raise BenchError("candidate immutable spans must be a list")
    spans = []
    for item in value["spans"]:
        if not isinstance(item, dict) or set(item) != {"offset", "size_bytes"}:
            raise BenchError("candidate immutable span has wrong keys")
        offset = _require_nonnegative_int(item["offset"], "immutable span offset")
        size_bytes = _positive_int(item["size_bytes"], "immutable span size")
        spans.append({"offset": offset, "size_bytes": size_bytes})
    if candidate_size_bytes is None:
        if len(spans) != 2 or spans[1]["offset"] != APPLICATION_OFFSET:
            raise BenchError("candidate immutable span map is not exact")
        candidate_size_bytes = APPLICATION_OFFSET + spans[1]["size_bytes"]
    expected = _expected_candidate_spans(candidate_size_bytes)
    if spans != expected:
        raise BenchError("candidate immutable span map is not exact")
    expected_size = sum(item["size_bytes"] for item in expected)
    if type(value["size_bytes"]) is not int or value["size_bytes"] != expected_size:
        raise BenchError("candidate immutable byte count is not exact")
    return {
        "sha256": digest,
        "size_bytes": expected_size,
        "spans": expected,
    }


def _validate_session_id(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{32}", value) is None:
        raise BenchError("qualification session ID is not 128-bit lowercase hex")
    return value


def _unsigned_cap(caps, key, *, allow_zero=False):
    raw = caps.get(key)
    if raw is None or not re.fullmatch(r"[0-9]+", raw):
        raise BenchError("caps %s is not an unsigned integer" % key)
    value = int(raw, 10)
    if value == 0 and not allow_zero:
        raise BenchError("caps %s must be positive" % key)
    return value


def validate_and_redact_caps(payload):
    """Validate exact target metadata and retain only non-personal fields."""
    caps = parse_caps(payload)
    if caps.get("chip") != EXPECTED_CHIP:
        raise BenchError(
            "wrong PBLE target: chip=%s expected %s"
            % (caps.get("chip", "<missing>"), EXPECTED_CHIP)
        )
    for key in ("proto", "agent", "mpy"):
        if not caps.get(key):
            raise BenchError("caps are missing %s" % key)
    return {
        "proto": _unsigned_cap(caps, "proto"),
        "agent": caps["agent"],
        "chip": caps["chip"],
        "mpy": caps["mpy"],
        "mtu": _unsigned_cap(caps, "mtu"),
        "window": _unsigned_cap(caps, "window"),
        "chunk": _unsigned_cap(caps, "chunk"),
        "free_mem_bytes": _unsigned_cap(caps, "free_mem", allow_zero=True),
    }


def validate_runtime_memory(value):
    """Check runtime-observable memory without overstating physical PSRAM.

    ``esp.flash_size`` reports the physical flash size exactly.  MicroPython
    does not expose a physical-PSRAM-size API, so the exact 8 MiB value remains
    bound to the read-only preflight while this check requires a large visible
    PSRAM heap either in ESP-IDF or in the MicroPython GC heap.
    """
    keys = {
        "flash_size_bytes",
        "psram_idf_heap_region_bytes",
        "gc_free_bytes",
        "gc_allocated_bytes",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise BenchError("runtime memory evidence has wrong keys")
    checked = {
        key: _require_nonnegative_int(value[key], "runtime memory %s" % key)
        for key in keys
    }
    if checked["flash_size_bytes"] != FLASH_CAPACITY_BYTES:
        raise BenchError(
            "runtime flash size is %d, expected %d"
            % (checked["flash_size_bytes"], FLASH_CAPACITY_BYTES)
        )
    gc_total = checked["gc_free_bytes"] + checked["gc_allocated_bytes"]
    runtime_visible = max(
        checked["psram_idf_heap_region_bytes"],
        gc_total,
    )
    if runtime_visible < MIN_RUNTIME_VISIBLE_PSRAM_BYTES:
        raise BenchError(
            "runtime exposes only %d bytes in its largest PSRAM-backed view"
            % runtime_visible
        )
    return checked


def build_candidate_probe_source(candidate_attestation):
    candidate_attestation = _validate_candidate_attestation(candidate_attestation)
    spans = "(" + ",".join(
        "(%d,%d)" % (item["offset"], item["size_bytes"])
        for item in candidate_attestation["spans"]
    ) + ")"
    source = '''import binascii,esp,hashlib
_expected="%s";_spans=%s
_hash=hashlib.sha256();_buffer=bytearray(4096)
for _base,_length in _spans:
 for _offset in range(0,_length,4096):
  _view=memoryview(_buffer)[:min(4096,_length-_offset)]
  esp.flash_read(_base+_offset,_view);_hash.update(_view)
_actual=binascii.hexlify(_hash.digest()).decode()
print("%s="+_actual)
if _actual!=_expected:raise RuntimeError("candidate mismatch")
''' % (candidate_attestation["sha256"], spans, CANDIDATE_MARKER)
    if len(source.encode("utf-8")) > RUN_SOURCE_LIMIT:
        raise BenchError("candidate probe source exceeds RUN{source} limit")
    return source


def build_exercise_source(interactive_confirmation=False):
    """Return the exact deterministic display workload, within RUN{source}."""
    if type(interactive_confirmation) is not bool:
        raise BenchError("interactive confirmation flag must be Boolean")
    if interactive_confirmation:
        first_frame_gate = '''
   _release=input()
   if _release!="%s":raise RuntimeError("visual release mismatch")
   print("%s=1")''' % (
            VISUAL_RELEASE_INPUT.decode("ascii"),
            VISUAL_RELEASE_MARKER,
        )
        final_visible_hold = ""
    else:
        first_frame_gate = ""
        final_visible_hold = " sleep_ms(%d)" % VISUAL_CONFIRMATION_HOLD_MS
    source = """import gc,esp,esp32
from machine import Pin
from time import sleep_ms
from pyble_st7789 import ST7789,rgb565
gc.collect();_p=0
for _r in esp32.idf_heap_info(1024):_p+=_r[0]
print(\"%s=%%d,%%d,%%d,%%d\"%%(esp.flash_size(),_p,gc.mem_free(),gc.mem_alloc()))
d=None
try:
 d=ST7789(1,40000000,0,0,Pin(40,Pin.OUT),Pin(45,Pin.OUT),Pin(42,Pin.OUT),Pin(41,Pin.OUT),Pin(39,Pin.OUT),Pin(46,Pin.OUT),172,320,34,0,True,True)
 d.backlight(False);print(\"%s=0\")
 _bg=rgb565(8,18,40);_w=rgb565(255,255,255);_c=rgb565(0,220,255)
 d.fill(_bg);d.rect(0,0,172,320,_w)
 d.fill_rect(1,1,56,40,rgb565(255,0,0));d.fill_rect(58,1,56,40,rgb565(0,255,0));d.fill_rect(115,1,56,40,rgb565(0,0,255))
 d.pixel(0,0,_w);d.pixel(171,0,_w);d.pixel(0,319,_w);d.pixel(171,319,_w)
 d.text(\"PyBLE\",64,154,_w);print(\"%s=ready\")
 for _i in range(%d):
  d.fill_rect(1,296,170,23,_bg);d.fill_rect(1,296,(_i+1)*28,23,_c)
  print(\"%s=%%d,before\"%%_i);sleep_ms(%d);d.show();print(\"%s=%%d,after\"%%_i)
  if _i==0:
   d.backlight(True);print(\"%s=1\")%s
  sleep_ms(80)
%s
finally:
 if d is not None:
  try:d.backlight(False);print(\"%s=0\")
  finally:d.deinit()
 print(\"%s=1\")
""" % (
        MEMORY_MARKER,
        BACKLIGHT_MARKER,
        PATTERN_MARKER,
        REFRESH_COUNT,
        REFRESH_MARKER,
        RESPONSIVENESS_WINDOW_MS,
        REFRESH_MARKER,
        BACKLIGHT_MARKER,
        first_frame_gate,
        final_visible_hold,
        BACKLIGHT_MARKER,
        CLEANUP_MARKER,
    )
    if len(source.encode("utf-8")) > RUN_SOURCE_LIMIT:
        raise BenchError("TFT exercise source exceeds RUN{source} limit")
    return source


def build_pre_reboot_source():
    source = '''import sys
sys.path.append("%s")
print("%s")
''' % (VM_SENTINEL, PRE_REBOOT_MARKER)
    if len(source.encode("utf-8")) > RUN_SOURCE_LIMIT:
        raise BenchError("pre-reboot source exceeds RUN{source} limit")
    return source


def build_post_reboot_source():
    source = '''import sys
if "%s" in sys.path:
 print("%s")
 raise RuntimeError("VM epoch did not reset")
import pyble_st7789
print("%s")
''' % (VM_SENTINEL, STALE_VM_MARKER, POST_REBOOT_MARKER)
    if len(source.encode("utf-8")) > RUN_SOURCE_LIMIT:
        raise BenchError("post-reboot source exceeds RUN{source} limit")
    return source


def parse_console_evidence(chunks):
    """Parse only runner-owned markers from captured stdout chunks."""
    if not isinstance(chunks, (list, tuple)):
        raise BenchError("stdout evidence must be a chunk sequence")
    try:
        output = b"".join(bytes(chunk) for chunk in chunks).decode(
            "ascii", errors="strict"
        )
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise BenchError("TFT stdout is not strict ASCII") from exc

    memory_values = []
    backlights = []
    visual_sequence = []
    pattern_count = 0
    refresh_events = []
    cleanup_count = 0
    visual_release_count = 0
    for line in output.splitlines():
        if not line.startswith(MARKER_PREFIX):
            continue
        memory_match = re.fullmatch(
            re.escape(MEMORY_MARKER) + r"=([0-9]+),([0-9]+),([0-9]+),([0-9]+)",
            line,
        )
        if memory_match:
            values = tuple(int(item, 10) for item in memory_match.groups())
            memory_values.append(
                {
                    "flash_size_bytes": values[0],
                    "psram_idf_heap_region_bytes": values[1],
                    "gc_free_bytes": values[2],
                    "gc_allocated_bytes": values[3],
                }
            )
            continue
        backlight_match = re.fullmatch(
            re.escape(BACKLIGHT_MARKER) + r"=([01])", line
        )
        if backlight_match:
            backlight = backlight_match.group(1) == "1"
            backlights.append(backlight)
            visual_sequence.append("backlight-on" if backlight else "backlight-off")
            continue
        if line == PATTERN_MARKER + "=ready":
            pattern_count += 1
            continue
        refresh_match = re.fullmatch(
            re.escape(REFRESH_MARKER) + r"=([0-9]+),(before|after)", line
        )
        if refresh_match:
            refresh_events.append((int(refresh_match.group(1), 10), refresh_match.group(2)))
            continue
        if line == CLEANUP_MARKER + "=1":
            cleanup_count += 1
            continue
        if line == VISUAL_RELEASE_MARKER + "=1":
            visual_release_count += 1
            visual_sequence.append("stdin-release")
            continue
        raise BenchError("TFT stdout contains a malformed runner marker")

    if len(memory_values) != 1:
        raise BenchError("TFT run must emit exactly one memory marker")
    if backlights != [False, True, False]:
        raise BenchError("backlight evidence is not the required off/on/off sequence")
    if pattern_count != 1:
        raise BenchError("TFT run must emit exactly one pattern-ready marker")
    if cleanup_count != 1:
        raise BenchError("TFT run did not prove cleanup exactly once")
    if visual_release_count > 1:
        raise BenchError("TFT run duplicated its visual release marker")
    allowed_visual_sequences = (
        ["backlight-off", "backlight-on", "backlight-off"],
        [
            "backlight-off",
            "backlight-on",
            "stdin-release",
            "backlight-off",
        ],
    )
    if visual_sequence not in allowed_visual_sequences:
        raise BenchError("TFT visual release/backlight evidence is out of order")
    if len(refresh_events) % 2:
        raise BenchError("TFT refresh markers are incomplete")
    refresh_count = len(refresh_events) // 2
    expected_events = []
    for index in range(refresh_count):
        expected_events.extend(((index, "before"), (index, "after")))
    if refresh_events != expected_events:
        raise BenchError("TFT refresh markers are out of order or incomplete")

    return {
        "memory": validate_runtime_memory(memory_values[0]),
        "backlight_sequence": backlights,
        "pattern_ready": True,
        "refreshes_completed": refresh_count,
        "cleanup_completed": True,
        "visual_release_completed": visual_release_count == 1,
    }


async def _hello(central, command_ids, timeout_s):
    response = await central.send_cmd(
        wire.OP_HELLO,
        command_ids.next(),
        HELLO_PAYLOAD,
        timeout=timeout_s,
    )
    status = rsp_status(response)
    if status != wire.ST_OK:
        raise BenchError("HELLO -> %s" % status_name(status))
    caps = validate_and_redact_caps(response.payload[1:])
    if hasattr(central, "confirm_caps_mtu"):
        try:
            central.confirm_caps_mtu(caps["mtu"])
        except ValueError as exc:
            raise BenchError("HELLO MTU validation failed") from exc
    return caps


async def _responsiveness_probe(central, command_ids, hello_caps, timeout_s):
    try:
        info_payload = await asyncio.wait_for(central.read_info(), timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        raise BenchError("INFO read timed out while TFT run was active") from exc
    info_caps = validate_and_redact_caps(info_payload)
    response = await central.send_cmd(
        wire.OP_DEVICE_INFO,
        command_ids.next(),
        timeout=timeout_s,
    )
    status = rsp_status(response)
    if status != wire.ST_OK:
        raise BenchError("DEVICE_INFO while refreshing -> %s" % status_name(status))
    command_caps = validate_and_redact_caps(response.payload[1:])
    stable_keys = ("proto", "agent", "chip", "mpy")
    for key in stable_keys:
        if info_caps[key] != hello_caps[key] or command_caps[key] != hello_caps[key]:
            raise BenchError("INFO identity metadata changed while refreshing")
    return True


async def _collect_run(
        central,
        command_ids,
        source,
        *,
        hello_caps,
        timeout_s,
        poll_interval_s,
        probe_responsiveness,
        stale_vm_marker=None,
        confirm_visual_during_run=None,
        operator_timeout_s=DEFAULT_OPERATOR_TIMEOUT_S,
        include_marker_bytes=False,
        marker_prefixes=(MARKER_PREFIX,),
        release_visual_after_confirmation=False):
    cursor = central.event_cursor()
    response = await central.send_cmd(
        wire.OP_RUN,
        command_ids.next(),
        b"\x01" + source.encode("utf-8"),
        timeout=timeout_s,
    )
    status = rsp_status(response)
    if status != wire.ST_OK:
        raise BenchError("RUN TFT workload -> %s" % status_name(status))

    stdout_chunks = []
    stdout_bytes = 0
    stderr_chunks = []
    stderr_bytes = 0
    states = []
    terminal = None
    info_reads = 0
    device_info_commands = 0
    console_line_buffer = bytearray()
    stdout_marker_bytes = 0
    refresh_before = []
    refresh_after = set()
    probed_refreshes = []
    pattern_ready_seen = False
    visual_confirmation_completed = False
    visual_callback_completed = False
    visual_release_sent = False
    visual_stop_sent = False
    deferred_visual_error = None
    deferred_drain_error = None
    ignored_pre_stop_terminals = 0
    deadline = time.monotonic() + timeout_s
    cleanup_reserve_s = min(OPERATOR_CLEANUP_RESERVE_S, timeout_s / 4.0)

    async def release_visible_run():
        if not release_visual_after_confirmation:
            raise BenchError("TFT visual release handshake is not armed")
        sender = getattr(central, "send_cmd_no_rsp", None)
        if not callable(sender):
            raise BenchError("PBLE central cannot send the visual release")
        if not _central_connected(central):
            raise PbleLinkLossError("TFT link dropped before visual release")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BenchError("TFT visual release exceeded its RUN deadline")
        try:
            await asyncio.wait_for(
                sender(
                    wire.OP_CONSOLE_INPUT,
                    command_ids.next(),
                    VISUAL_RELEASE_INPUT + b"\n",
                ),
                timeout=remaining,
            )
        except asyncio.TimeoutError as exc:
            raise BenchError("TFT visual release exceeded its RUN deadline") from exc
        if not _central_connected(central):
            raise PbleLinkLossError("TFT link dropped during visual release")

    async def stop_visible_run():
        if not _central_connected(central):
            raise PbleLinkLossError("TFT link dropped before visual STOP")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BenchError("TFT visual STOP exceeded its RUN deadline")
        try:
            response = await asyncio.wait_for(
                central.send_cmd(
                    wire.OP_STOP,
                    command_ids.next(),
                    timeout=remaining,
                ),
                timeout=remaining,
            )
        except asyncio.TimeoutError as exc:
            raise BenchError("TFT visual STOP exceeded its RUN deadline") from exc
        status = rsp_status(response)
        if status != wire.ST_OK:
            raise BenchError("STOP visual RUN -> %s" % status_name(status))

    def preferred_failure(original, cleanup):
        if isinstance(original, _PROCESS_CONTROL_EXCEPTIONS):
            return original
        if isinstance(cleanup, _PROCESS_CONTROL_EXCEPTIONS):
            return cleanup
        return original

    def defer_or_raise_drain_failure(error):
        nonlocal deferred_drain_error
        if deferred_visual_error is not None:
            if deferred_drain_error is None:
                deferred_drain_error = error
            else:
                deferred_drain_error = preferred_failure(
                    deferred_drain_error,
                    error,
                )
            return
        raise error

    while terminal is None:
        cursor, events = central.events_since(cursor)
        for item in events:
            if item.opcode == wire.OP_CONSOLE_DATA:
                if not item.payload or item.payload[0] not in (0, 1):
                    defer_or_raise_drain_failure(
                        BenchError("TFT run emitted malformed CONSOLE_DATA")
                    )
                    continue
                data = item.payload[1:]
                if item.payload[0] == 0:
                    stdout_chunks.append(data)
                    stdout_bytes += len(data)
                    console_line_buffer.extend(data)
                    while b"\n" in console_line_buffer:
                        raw_line, _, remainder = console_line_buffer.partition(b"\n")
                        console_line_buffer = bytearray(remainder)
                        if raw_line.endswith(b"\r"):
                            raw_line = raw_line[:-1]
                        try:
                            line = raw_line.decode("ascii", errors="strict")
                        except UnicodeDecodeError as exc:
                            error = BenchError("TFT stdout is not strict ASCII")
                            if deferred_visual_error is not None:
                                defer_or_raise_drain_failure(error)
                                continue
                            raise error from exc
                        if line.startswith(marker_prefixes):
                            stdout_marker_bytes += len(raw_line)
                        if line == PATTERN_MARKER + "=ready":
                            pattern_ready_seen = True
                        before_match = re.fullmatch(
                            re.escape(REFRESH_MARKER) + r"=([0-9]+),before",
                            line,
                        )
                        after_match = re.fullmatch(
                            re.escape(REFRESH_MARKER) + r"=([0-9]+),after",
                            line,
                        )
                        if before_match:
                            refresh_before.append(int(before_match.group(1), 10))
                        elif after_match:
                            refresh_after.add(int(after_match.group(1), 10))
                        if (
                            confirm_visual_during_run is not None
                            and not visual_callback_completed
                            and pattern_ready_seen
                            and line == BACKLIGHT_MARKER + "=1"
                        ):
                            if not states or states[-1] != 1 or terminal is not None:
                                raise BenchError(
                                    "TFT visual confirmation was not requested during RUN"
                                )
                            if not _central_connected(central):
                                raise BenchError(
                                    "TFT link dropped before visual confirmation"
                                )
                            callback_error = None
                            confirmed = None
                            callback_started = None
                            callback_elapsed = 0.0
                            try:
                                if (
                                    deadline - time.monotonic()
                                    <= cleanup_reserve_s
                                ):
                                    raise BenchError(
                                        "TFT operator callback left no cleanup budget"
                                    )
                                callback_started = time.monotonic()
                                confirmed = await _await_operator_callback(
                                    confirm_visual_during_run,
                                    VISUAL_PATTERN_ID,
                                    timeout_s=operator_timeout_s,
                                    label="TFT operator confirmation",
                                )
                            except BaseException as caught:
                                callback_error = caught
                            finally:
                                if callback_started is not None:
                                    callback_elapsed = max(
                                        0.0,
                                        time.monotonic() - callback_started,
                                    )
                                    deadline += callback_elapsed
                            if (
                                callback_error is None
                                and callback_elapsed >= operator_timeout_s
                            ):
                                callback_error = BenchError(
                                    "TFT operator confirmation timed out"
                                )
                            if callback_error is None and confirmed is not True:
                                callback_error = BenchError(
                                    "operator did not confirm the live TFT pattern"
                                )
                            _queued_cursor, queued_events = central.events_since(
                                cursor
                            )
                            queued_stdout = bytearray(console_line_buffer)
                            terminal_queued = False
                            terminal_queued_count = 0
                            queued_failure = None
                            for queued in queued_events:
                                if queued.opcode == wire.OP_RUN_STATE:
                                    if (
                                        len(queued.payload) != 1
                                        or queued.payload[0] not in STATE_NAMES
                                    ):
                                        if queued_failure is None:
                                            queued_failure = BenchError(
                                                "TFT run emitted malformed RUN_STATE"
                                            )
                                        continue
                                    if queued.payload[0] in (0, 2, 3):
                                        terminal_queued = True
                                        terminal_queued_count += 1
                                elif (
                                    queued.opcode == wire.OP_CONSOLE_DATA
                                    and queued.payload
                                    and queued.payload[0] == 0
                                ):
                                    queued_stdout.extend(queued.payload[1:])
                                elif queued.opcode == wire.OP_CONSOLE_DATA:
                                    if (
                                        not queued.payload
                                        or queued.payload[0] not in (0, 1)
                                    ) and queued_failure is None:
                                        queued_failure = BenchError(
                                            "TFT run emitted malformed CONSOLE_DATA"
                                        )
                            dark_marker = (
                                BACKLIGHT_MARKER + "=0"
                            ).encode("ascii")
                            if (
                                queued_failure is None
                                and (
                                    terminal_queued
                                    or dark_marker in queued_stdout
                                )
                            ):
                                stale_failure = callback_error or BenchError(
                                    "TFT pattern ended before operator confirmation"
                                )
                                if not _central_connected(central):
                                    raise stale_failure
                                try:
                                    await stop_visible_run()
                                except BaseException as stop_error:
                                    raise preferred_failure(
                                        stale_failure,
                                        stop_error,
                                    ) from stale_failure
                                visual_stop_sent = True
                                visual_callback_completed = True
                                deferred_visual_error = stale_failure
                                ignored_pre_stop_terminals += terminal_queued_count
                                continue
                            if queued_failure is not None:
                                callback_error = (
                                    preferred_failure(
                                        callback_error,
                                        queued_failure,
                                    )
                                    if callback_error is not None
                                    else queued_failure
                                )
                            if callback_error is not None:
                                if not _central_connected(central):
                                    raise callback_error
                                try:
                                    await stop_visible_run()
                                except BaseException as stop_error:
                                    raise preferred_failure(
                                        callback_error,
                                        stop_error,
                                    ) from callback_error
                                visual_stop_sent = True
                                visual_callback_completed = True
                                deferred_visual_error = callback_error
                                continue
                            if not _central_connected(central):
                                link_error = PbleLinkLossError(
                                    "TFT link dropped during visual confirmation"
                                )
                                if isinstance(
                                    callback_error,
                                    _PROCESS_CONTROL_EXCEPTIONS,
                                ):
                                    raise callback_error
                                if callback_error is not None:
                                    raise callback_error from link_error
                                raise link_error
                            try:
                                await release_visible_run()
                            except BaseException as release_error:
                                failure = (
                                    preferred_failure(
                                        callback_error,
                                        release_error,
                                    )
                                    if callback_error is not None
                                    else release_error
                                )
                                if not _central_connected(central):
                                    raise failure
                                try:
                                    await stop_visible_run()
                                except BaseException as stop_error:
                                    raise preferred_failure(
                                        failure,
                                        stop_error,
                                    ) from failure
                                visual_stop_sent = True
                                visual_callback_completed = True
                                deferred_visual_error = failure
                                continue
                            visual_release_sent = True
                            visual_callback_completed = True
                            if callback_error is not None:
                                deferred_visual_error = callback_error
                            else:
                                visual_confirmation_completed = True
                else:
                    stderr_chunks.append(data)
                    stderr_bytes += len(data)
            elif item.opcode == wire.OP_RUN_STATE:
                if len(item.payload) != 1 or item.payload[0] not in STATE_NAMES:
                    defer_or_raise_drain_failure(
                        BenchError("TFT run emitted malformed RUN_STATE")
                    )
                    continue
                state = item.payload[0]
                if state in (0, 2, 3) and ignored_pre_stop_terminals:
                    ignored_pre_stop_terminals -= 1
                    continue
                states.append(state)
                if state in (0, 2, 3):
                    terminal = state

        running = bool(states) and states[-1] == 1 and terminal is None
        pending_refresh = next(
            (
                index
                for index in refresh_before
                if index not in refresh_after and index not in probed_refreshes
            ),
            None,
        )
        if probe_responsiveness and running and pending_refresh is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BenchError("TFT run timed out")
            await _responsiveness_probe(
                central,
                command_ids,
                hello_caps,
                min(remaining, timeout_s),
            )
            info_reads += 1
            device_info_commands += 1
            probed_refreshes.append(pending_refresh)

        if terminal is None:
            if time.monotonic() >= deadline:
                if deferred_visual_error is not None:
                    raise deferred_visual_error
                raise BenchError("TFT run timed out before a terminal RUN_STATE")
            await asyncio.sleep(poll_interval_s)

    expected_states = [1, 0] if visual_stop_sent else [1, 2]
    drain_error = deferred_drain_error
    if states != expected_states:
        if stale_vm_marker is not None and states == [1, 3]:
            try:
                stale_output = b"".join(stdout_chunks).decode("ascii", errors="strict")
            except UnicodeDecodeError:
                stale_output = ""
            if stale_output.splitlines().count(stale_vm_marker) == 1:
                raise StaleVmEpochError(
                    "post-reboot connection reached the stale VM epoch"
                )
        names = [STATE_NAMES[value] for value in states]
        drain_error = BenchError(
            "TFT run state sequence is %s, expected %s"
            % (names, [STATE_NAMES[value] for value in expected_states])
        )
    if stderr_bytes:
        stderr_error = BenchError("TFT run emitted %d stderr bytes" % stderr_bytes)
        drain_error = (
            preferred_failure(drain_error, stderr_error)
            if drain_error is not None
            else stderr_error
        )
    if probe_responsiveness and info_reads < MIN_RESPONSIVE_PROBES:
        responsiveness_error = BenchError(
            "PBLE responsiveness was not proven across repeated refreshes"
        )
        drain_error = (
            preferred_failure(drain_error, responsiveness_error)
            if drain_error is not None
            else responsiveness_error
        )
    if deferred_visual_error is not None:
        try:
            drained_stdout = b"".join(stdout_chunks).decode(
                "ascii",
                errors="strict",
            )
        except UnicodeDecodeError:
            drained_stdout = ""
        backlight_on_marker = BACKLIGHT_MARKER + "=1"
        backlight_off_marker = BACKLIGHT_MARKER + "=0"
        cleanup_marker = CLEANUP_MARKER + "=1"
        if (
            drained_stdout.find(backlight_on_marker) < 0
            or drained_stdout.rfind(backlight_off_marker)
            < drained_stdout.find(backlight_on_marker)
            or drained_stdout.rfind(cleanup_marker)
            < drained_stdout.find(backlight_on_marker)
        ):
            cleanup_error = BenchError(
                "failed TFT confirmation did not drain dark/cleanup evidence"
            )
            drain_error = (
                preferred_failure(drain_error, cleanup_error)
                if drain_error is not None
                else cleanup_error
            )
        if drain_error is not None:
            raise preferred_failure(
                deferred_visual_error,
                drain_error,
            ) from drain_error
        raise deferred_visual_error
    if drain_error is not None:
        raise drain_error
    if (
        confirm_visual_during_run is not None
        and not visual_confirmation_completed
    ):
        raise BenchError("TFT visual confirmation was not completed during RUN")
    result = {
        "stdout_chunks": stdout_chunks,
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
        "state_sequence": [STATE_NAMES[value] for value in states],
        "info_reads": info_reads,
        "device_info_commands": device_info_commands,
        "responsive_refresh_indexes": probed_refreshes,
    }
    if include_marker_bytes:
        result["stdout_marker_bytes"] = stdout_marker_bytes
    if confirm_visual_during_run is not None:
        result["operator_confirmed_during_run"] = True
        result["visual_release_sent"] = visual_release_sent
    return result


def _base_result(stage, preflight, caps):
    validate_preflight(preflight)
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "stage": stage,
        "profile_id": PROFILE_ID,
        "board_model": BOARD_MODEL,
        "preflight": {
            "chip": preflight["chip"],
            "flash_capacity_bytes": preflight["flash_capacity_bytes"],
            "psram_capacity_bytes": preflight["psram_capacity_bytes"],
            "discovery_method": preflight["discovery_method"],
        },
        "runtime": caps,
    }
    return result


async def run_candidate_verification(
        central,
        preflight,
        candidate_firmware_sha256,
        candidate_firmware_size_bytes,
        candidate_attestation,
        *,
        timeout_s=20.0,
        poll_interval_s=0.01,
        include_marker_summary=False,
        command_ids=None,
        hello_caps=None):
    preflight = validate_preflight(preflight)
    candidate_firmware_sha256 = _validate_candidate_sha256(
        candidate_firmware_sha256
    )
    candidate_firmware_size_bytes = _validate_candidate_size(
        candidate_firmware_size_bytes
    )
    candidate_attestation = _validate_candidate_attestation(
        candidate_attestation,
        candidate_firmware_size_bytes,
    )
    if (command_ids is None) != (hello_caps is None):
        raise BenchError(
            "connected candidate verification requires command IDs and HELLO caps"
        )
    if command_ids is None:
        command_ids = CommandIds()
        caps = await _hello(central, command_ids, timeout_s)
    else:
        if not callable(getattr(command_ids, "next", None)):
            raise BenchError("connected candidate verification command IDs are invalid")
        if not isinstance(hello_caps, dict):
            raise BenchError("connected candidate verification HELLO caps are invalid")
        caps = dict(hello_caps)
    run = await _collect_run(
        central,
        command_ids,
        build_candidate_probe_source(candidate_attestation),
        hello_caps=caps,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
        probe_responsiveness=False,
        include_marker_bytes=include_marker_summary,
    )
    try:
        stdout = b"".join(run.pop("stdout_chunks")).decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        raise BenchError("candidate readback output is not strict ASCII") from exc
    matches = []
    for line in stdout.splitlines():
        match = re.fullmatch(re.escape(CANDIDATE_MARKER) + r"=([0-9a-f]{64})", line)
        if match:
            matches.append(match.group(1))
        elif line.startswith(MARKER_PREFIX):
            raise BenchError("candidate readback emitted a malformed runner marker")
    if matches != [candidate_attestation["sha256"]]:
        raise BenchError("live flash does not match the exact candidate firmware")
    run.pop("info_reads")
    run.pop("device_info_commands")
    run.pop("responsive_refresh_indexes")
    result = _base_result("candidate-verification", preflight, caps)
    result.update(
        {
            "live_immutable_sha256": candidate_attestation["sha256"],
            "immutable_bytes_verified": candidate_attestation["size_bytes"],
            "immutable_spans": candidate_attestation["spans"],
            "run": run,
            "next_stage": "exercise",
        }
    )
    return result


async def run_exercise(
        central,
        preflight,
        *,
        timeout_s=20.0,
        operator_timeout_s=DEFAULT_OPERATOR_TIMEOUT_S,
        poll_interval_s=0.01,
        confirm_visual_during_run=None,
        command_ids=None,
        hello_caps=None):
    preflight = validate_preflight(preflight)
    operator_timeout_s = _validate_operator_timeout(operator_timeout_s)
    if (command_ids is None) != (hello_caps is None):
        raise BenchError("connected exercise requires both command IDs and HELLO caps")
    if command_ids is None:
        command_ids = CommandIds()
        caps = await _hello(central, command_ids, timeout_s)
    else:
        if not callable(getattr(command_ids, "next", None)):
            raise BenchError("connected exercise command IDs are invalid")
        if not isinstance(hello_caps, dict):
            raise BenchError("connected exercise HELLO caps are invalid")
        caps = dict(hello_caps)
    if confirm_visual_during_run is not None and not callable(
            confirm_visual_during_run):
        raise BenchError("TFT visual confirmation callback is invalid")
    run = await _collect_run(
        central,
        command_ids,
        build_exercise_source(confirm_visual_during_run is not None),
        hello_caps=caps,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
        probe_responsiveness=True,
        confirm_visual_during_run=confirm_visual_during_run,
        operator_timeout_s=operator_timeout_s,
        include_marker_bytes=confirm_visual_during_run is not None,
        release_visual_after_confirmation=(
            confirm_visual_during_run is not None
        ),
    )
    confirmed_during_run = run.pop("operator_confirmed_during_run", False)
    visual_release_sent = run.pop("visual_release_sent", False)
    evidence = parse_console_evidence(run.pop("stdout_chunks"))
    visual_release_completed = evidence.pop("visual_release_completed")
    if confirm_visual_during_run is not None:
        if not visual_release_sent or not visual_release_completed:
            raise BenchError("TFT visual release handshake did not complete")
    elif visual_release_sent or visual_release_completed:
        raise BenchError("standalone TFT run emitted an unexpected visual release")
    if evidence["refreshes_completed"] != REFRESH_COUNT:
        raise BenchError(
            "TFT completed %d refreshes, expected %d"
            % (evidence["refreshes_completed"], REFRESH_COUNT)
        )
    result = _base_result("exercise", preflight, caps)
    result.update(
        {
            "memory": {
                **evidence["memory"],
                "hello_free_mem_bytes": caps["free_mem_bytes"],
            },
            "display": {
                "geometry": [WIDTH, HEIGHT, X_OFFSET, Y_OFFSET],
                "refreshes_completed": evidence["refreshes_completed"],
                "pattern_ready": evidence["pattern_ready"],
                "backlight_sequence": evidence["backlight_sequence"],
                "cleanup_completed": evidence["cleanup_completed"],
            },
            "pble_responsiveness": {
                "info_reads": run.pop("info_reads"),
                "device_info_commands": run.pop("device_info_commands"),
                "refresh_indexes": run.pop("responsive_refresh_indexes"),
                "while_run_active": True,
            },
            "run": run,
            "next_stage": "soft-reboot",
        }
    )
    if confirm_visual_during_run is not None:
        if confirmed_during_run is not True:
            raise BenchError("TFT visual confirmation evidence is absent")
        result["operator_observation"] = {
            "confirmed": True,
            "pattern_id": VISUAL_PATTERN_ID,
            "while_run_active": True,
            "stdin_release_sent": True,
        }
    return result


async def run_soft_reboot(central, preflight, *, timeout_s=10.0):
    preflight = validate_preflight(preflight)
    command_ids = CommandIds()
    caps = await _hello(central, command_ids, timeout_s)
    pre_reboot_run = await _collect_run(
        central,
        command_ids,
        build_pre_reboot_source(),
        hello_caps=caps,
        timeout_s=timeout_s,
        poll_interval_s=0.01,
        probe_responsiveness=False,
    )
    try:
        stdout = b"".join(pre_reboot_run.pop("stdout_chunks")).decode(
            "ascii", errors="strict"
        )
    except UnicodeDecodeError as exc:
        raise BenchError("pre-reboot sentinel output is not strict ASCII") from exc
    if stdout.splitlines().count(PRE_REBOOT_MARKER) != 1:
        raise BenchError("pre-reboot sentinel marker is missing or duplicated")
    pre_reboot_run.pop("info_reads")
    pre_reboot_run.pop("device_info_commands")
    pre_reboot_run.pop("responsive_refresh_indexes")
    response = await central.send_cmd(
        wire.OP_SOFT_REBOOT,
        command_ids.next(),
        timeout=timeout_s,
    )
    status = rsp_status(response)
    if status != wire.ST_OK:
        raise BenchError("SOFT_REBOOT -> %s" % status_name(status))
    result = _base_result("soft-reboot", preflight, caps)
    result.update(
        {
            "volatile_sentinel_armed": True,
            "pre_reboot_run": pre_reboot_run,
            "soft_reboot_acknowledged": True,
            "transport_disconnect_required": True,
            "next_stage": "post-reboot",
        }
    )
    return result


async def run_post_reboot(
        central,
        preflight,
        *,
        timeout_s=10.0,
        poll_interval_s=0.01):
    preflight = validate_preflight(preflight)
    command_ids = CommandIds()
    caps = await _hello(central, command_ids, timeout_s)
    run = await _collect_run(
        central,
        command_ids,
        build_post_reboot_source(),
        hello_caps=caps,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
        probe_responsiveness=False,
        stale_vm_marker=STALE_VM_MARKER,
    )
    try:
        stdout = b"".join(run.pop("stdout_chunks")).decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        raise BenchError("post-reboot import output is not strict ASCII") from exc
    if stdout.splitlines().count(POST_REBOOT_MARKER) != 1:
        raise BenchError("post-reboot pyble_st7789 import marker is missing or duplicated")
    run.pop("info_reads")
    run.pop("device_info_commands")
    run.pop("responsive_refresh_indexes")
    result = _base_result("post-reboot", preflight, caps)
    result.update(
        {
            "runtime_imported": True,
            "volatile_sentinel_absent": True,
            "run": run,
            "next_stage": None,
        }
    )
    return result


def _deadline_remaining(deadline, clock, label):
    remaining = deadline - clock()
    if remaining <= 0:
        raise BenchError("%s exceeded its qualification deadline" % label)
    return remaining


async def _await_with_deadline(factory, deadline, clock, label):
    remaining = _deadline_remaining(deadline, clock, label)
    try:
        result = await asyncio.wait_for(factory(remaining), timeout=remaining)
    except asyncio.TimeoutError as exc:
        raise BenchError("%s exceeded its qualification deadline" % label) from exc
    _deadline_remaining(deadline, clock, label)
    return result


def _central_connected(central):
    try:
        value = central.is_connected
    except Exception as exc:
        raise BenchError("cannot prove BLE connection closure") from exc
    if not isinstance(value, bool):
        raise BenchError("BLE connection state is not Boolean")
    return value


async def _close_connection(central, deadline, clock, label):
    if central is None:
        raise BenchError("%s has no connection to close" % label)
    try:
        await _await_with_deadline(
            lambda _remaining: central.disconnect(),
            deadline,
            clock,
            "%s disconnect" % label,
        )
    except Exception as exc:
        if _central_connected(central):
            raise BenchError("%s connection remained open" % label) from exc
        _deadline_remaining(deadline, clock, "%s disconnect" % label)
        return True
    if _central_connected(central):
        raise BenchError("%s disconnect returned with the link still open" % label)
    return True


async def _connect_with_deadline(connect, address, deadline, clock, label):
    return await _await_with_deadline(
        lambda remaining: connect(address, timeout=remaining),
        deadline,
        clock,
        "%s connection" % label,
    )


async def _sleep_with_deadline(sleep, seconds, deadline, clock, label):
    remaining = _deadline_remaining(deadline, clock, label)
    duration = min(seconds, remaining)
    await _await_with_deadline(
        lambda _remaining: sleep(duration),
        deadline,
        clock,
        label,
    )


async def _await_fresh_post_reboot(
        connect,
        address,
        preflight,
        *,
        timeout_s,
        poll_interval_s,
        sleep,
        clock=time.monotonic):
    deadline = clock() + timeout_s
    await _sleep_with_deadline(
        sleep,
        REBOOT_DELIVERY_GRACE_S,
        deadline,
        clock,
        "reboot delivery grace",
    )
    attempts = 0
    while True:
        _deadline_remaining(deadline, clock, "fresh-VM reconnect")
        attempts += 1
        central = None
        try:
            central = await _connect_with_deadline(
                connect,
                address,
                deadline,
                clock,
                "fresh-VM",
            )
        except PbleConnectError:
            await _sleep_with_deadline(
                sleep,
                RECONNECT_POLL_S,
                deadline,
                clock,
                "fresh-VM reconnect delay",
            )
            continue

        retry_transition = False
        try:
            result = await _await_with_deadline(
                lambda remaining: run_post_reboot(
                    central,
                    preflight,
                    timeout_s=remaining,
                    poll_interval_s=poll_interval_s,
                ),
                deadline,
                clock,
                "fresh-VM probe",
            )
        except StaleVmEpochError:
            retry_transition = True
            result = None
        except PbleLinkLossError:
            if _central_connected(central):
                raise
            retry_transition = True
            result = None
        finally:
            await _close_connection(central, deadline, clock, "post-reboot")

        if not retry_transition:
            _deadline_remaining(deadline, clock, "fresh-VM proof")
            return result, attempts
        await _sleep_with_deadline(
            sleep,
            RECONNECT_POLL_S,
            deadline,
            clock,
            "reset-transition retry delay",
        )


async def run_qualification(
        connect,
        address,
        preflight,
        candidate_firmware_sha256,
        candidate_firmware_size_bytes,
        candidate_attestation,
        *,
        timeout_s=20.0,
        poll_interval_s=0.01,
        sleep=asyncio.sleep,
        clock=time.monotonic,
        confirm_visual=None,
        session_id=None):
    """Run one exact-candidate exercise and three chained reboot cycles."""
    preflight = validate_preflight(preflight)
    candidate_firmware_sha256 = _validate_candidate_sha256(
        candidate_firmware_sha256
    )
    candidate_firmware_size_bytes = _validate_candidate_size(
        candidate_firmware_size_bytes
    )
    candidate_attestation = _validate_candidate_attestation(
        candidate_attestation,
        candidate_firmware_size_bytes,
    )
    if not isinstance(timeout_s, (int, float)) or timeout_s <= REBOOT_DELIVERY_GRACE_S:
        raise BenchError("qualification timeout must exceed the reboot delivery grace")
    if session_id is None:
        session_id = secrets.token_hex(16)
    session_id = _validate_session_id(session_id)
    if not callable(confirm_visual):
        raise BenchError("qualification requires an operator confirmation callback")

    initial_deadline = clock() + timeout_s
    initial = await _connect_with_deadline(
        connect,
        address,
        initial_deadline,
        clock,
        "candidate/exercise",
    )
    try:
        candidate_verification = await _await_with_deadline(
            lambda remaining: run_candidate_verification(
                initial,
                preflight,
                candidate_firmware_sha256,
                candidate_firmware_size_bytes,
                candidate_attestation,
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
            ),
            initial_deadline,
            clock,
            "live candidate verification",
        )
        exercise_result = await _await_with_deadline(
            lambda remaining: run_exercise(
                initial,
                preflight,
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
            ),
            initial_deadline,
            clock,
            "TFT exercise",
        )
    finally:
        await _close_connection(
            initial,
            initial_deadline,
            clock,
            "candidate/exercise",
        )

    confirmed = await confirm_visual(VISUAL_PATTERN_ID)
    if confirmed is not True:
        raise BenchError("operator did not confirm the frozen TFT pattern")
    operator_observation = {
        "confirmed": True,
        "pattern_id": VISUAL_PATTERN_ID,
    }
    exercise_record = {
        "session_id": session_id,
        "candidate_firmware_sha256": candidate_firmware_sha256,
        "candidate_firmware_size_bytes": candidate_firmware_size_bytes,
        "candidate_attestation": candidate_attestation,
        "candidate_verification": candidate_verification,
        "operator_observation": operator_observation,
        "stage_result": exercise_result,
    }
    exercise_record["record_sha256"] = record_sha256(exercise_record)
    predecessor_sha256 = exercise_record["record_sha256"]

    cycles = []
    for cycle_number in range(1, QUALIFICATION_REBOOT_CYCLES + 1):
        soft_deadline = clock() + timeout_s
        soft_central = await _connect_with_deadline(
            connect,
            address,
            soft_deadline,
            clock,
            "soft-reboot",
        )
        try:
            soft_reboot_result = await _await_with_deadline(
                lambda remaining: run_soft_reboot(
                    soft_central,
                    preflight,
                    timeout_s=remaining,
                ),
                soft_deadline,
                clock,
                "soft-reboot stage",
            )
        finally:
            old_connection_closed = await _close_connection(
                soft_central,
                soft_deadline,
                clock,
                "acknowledged old",
            )
        post_reboot_result, reconnect_attempts = await _await_fresh_post_reboot(
            connect,
            address,
            preflight,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            sleep=sleep,
            clock=clock,
        )
        cycle_record = {
            "session_id": session_id,
            "candidate_firmware_sha256": candidate_firmware_sha256,
            "candidate_firmware_size_bytes": candidate_firmware_size_bytes,
            "candidate_attestation": candidate_attestation,
            "cycle": cycle_number,
            "predecessor_sha256": predecessor_sha256,
            "reconnect_attempts": reconnect_attempts,
            "old_connection_closed": old_connection_closed,
            "soft_reboot": soft_reboot_result,
            "post_reboot": post_reboot_result,
        }
        cycle_record["record_sha256"] = record_sha256(cycle_record)
        predecessor_sha256 = cycle_record["record_sha256"]
        cycles.append(cycle_record)

    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "stage": "qualification",
        "profile_id": PROFILE_ID,
        "board_model": BOARD_MODEL,
        "session_id": session_id,
        "candidate_firmware_sha256": candidate_firmware_sha256,
        "candidate_firmware_size_bytes": candidate_firmware_size_bytes,
        "candidate_attestation": candidate_attestation,
        "exercise": exercise_record,
        "cycles": cycles,
        "qualification": {
            "reboot_cycles": QUALIFICATION_REBOOT_CYCLES,
            "fresh_vm_cycles": QUALIFICATION_REBOOT_CYCLES,
            "terminal_record_sha256": predecessor_sha256,
        },
    }
    return validate_qualification_result(result)


BASE_STAGE_KEYS = {
    "schema_version",
    "status",
    "stage",
    "profile_id",
    "board_model",
    "preflight",
    "runtime",
}


def _exact_dict(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise BenchError("%s has wrong keys" % label)
    return value


def _positive_int(value, label, *, allow_zero=False):
    if type(value) is not int:
        raise BenchError("%s is not an integer" % label)
    if value < 0 or (value == 0 and not allow_zero):
        raise BenchError("%s is outside its allowed range" % label)
    return value


def _validate_redacted_stage(
        value,
        stage,
        extra_keys,
        label,
        expected_runtime_identity=None):
    _exact_dict(value, BASE_STAGE_KEYS | set(extra_keys), label)
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
        raise BenchError("%s schema version changed" % label)
    if (
        type(value["status"]) is not str
        or type(value["stage"]) is not str
        or value["status"] != "passed"
        or value["stage"] != stage
    ):
        raise BenchError("%s did not retain its passed stage" % label)
    if (
        type(value["profile_id"]) is not str
        or type(value["board_model"]) is not str
        or value["profile_id"] != PROFILE_ID
        or value["board_model"] != BOARD_MODEL
    ):
        raise BenchError("%s exact-board identity changed" % label)
    _exact_dict(
        value["preflight"],
        {
            "chip",
            "flash_capacity_bytes",
            "psram_capacity_bytes",
            "discovery_method",
        },
        "%s preflight" % label,
    )
    expected_preflight = {
        "chip": EXPECTED_CHIP,
        "flash_capacity_bytes": FLASH_CAPACITY_BYTES,
        "psram_capacity_bytes": PSRAM_CAPACITY_BYTES,
        "discovery_method": "esptool-read-only",
    }
    if any(
        type(value["preflight"][key]) is not type(expected)
        or value["preflight"][key] != expected
        for key, expected in expected_preflight.items()
    ):
        raise BenchError("%s preflight identity changed" % label)
    runtime = _exact_dict(
        value["runtime"],
        {"proto", "agent", "chip", "mpy", "mtu", "window", "chunk", "free_mem_bytes"},
        "%s runtime" % label,
    )
    if (
        type(runtime["chip"]) is not str
        or runtime["chip"] != EXPECTED_CHIP
        or type(runtime["proto"]) is not int
        or runtime["proto"] != 1
    ):
        raise BenchError("%s runtime identity changed" % label)
    expected_versions = {
        "agent": EXPECTED_AGENT_VERSION,
        "mpy": EXPECTED_MPY_VERSION,
    }
    semantic_version = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    for key, expected in expected_versions.items():
        if (
            type(runtime[key]) is not str
            or re.fullmatch(semantic_version, runtime[key]) is None
            or runtime[key] != expected
        ):
            raise BenchError("%s runtime %s is invalid" % (label, key))
    for key in ("mtu", "window", "chunk"):
        _positive_int(runtime[key], "%s runtime %s" % (label, key))
    _positive_int(
        runtime["free_mem_bytes"],
        "%s runtime free memory" % label,
        allow_zero=True,
    )
    identity = (
        runtime["proto"],
        runtime["agent"],
        runtime["chip"],
        runtime["mpy"],
    )
    if expected_runtime_identity is not None and identity != expected_runtime_identity:
        raise BenchError("%s runtime identity drifted" % label)
    return identity


def _validate_run_summary(value, label):
    _exact_dict(value, {"stdout_bytes", "stderr_bytes", "state_sequence"}, label)
    _positive_int(value["stdout_bytes"], "%s stdout bytes" % label)
    if (
        type(value["stderr_bytes"]) is not int
        or value["stderr_bytes"] != 0
        or not isinstance(value["state_sequence"], list)
        or any(type(item) is not str for item in value["state_sequence"])
        or value["state_sequence"] != ["running", "done"]
    ):
        raise BenchError("%s is not a clean running/done result" % label)


def _validate_candidate_stage(value, candidate_attestation):
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
    )
    live_attestation = _validate_candidate_attestation(
        {
            "sha256": value["live_immutable_sha256"],
            "size_bytes": value["immutable_bytes_verified"],
            "spans": value["immutable_spans"],
        }
    )
    if live_attestation != candidate_attestation:
        raise BenchError("live candidate attestation changed")
    if type(value["next_stage"]) is not str or value["next_stage"] != "exercise":
        raise BenchError("candidate verification next stage changed")
    _validate_run_summary(value["run"], "candidate verification run")
    return runtime_identity


def _validate_exercise_stage(value, expected_runtime_identity):
    _validate_redacted_stage(
        value,
        "exercise",
        {"memory", "display", "pble_responsiveness", "run", "next_stage"},
        "exercise",
        expected_runtime_identity,
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
    validate_runtime_memory(
        {
            "flash_size_bytes": memory["flash_size_bytes"],
            "psram_idf_heap_region_bytes": memory["psram_idf_heap_region_bytes"],
            "gc_free_bytes": memory["gc_free_bytes"],
            "gc_allocated_bytes": memory["gc_allocated_bytes"],
        }
    )
    _positive_int(
        memory["hello_free_mem_bytes"],
        "exercise HELLO free memory",
        allow_zero=True,
    )
    if memory["hello_free_mem_bytes"] != value["runtime"]["free_mem_bytes"]:
        raise BenchError("exercise HELLO free memory drifted from runtime caps")
    _exact_dict(
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
    display = value["display"]
    if (
        not isinstance(display["geometry"], list)
        or any(type(item) is not int for item in display["geometry"])
        or display["geometry"] != [WIDTH, HEIGHT, X_OFFSET, Y_OFFSET]
        or type(display["refreshes_completed"]) is not int
        or display["refreshes_completed"] != REFRESH_COUNT
        or display["pattern_ready"] is not True
        or not isinstance(display["backlight_sequence"], list)
        or any(type(item) is not bool for item in display["backlight_sequence"])
        or display["backlight_sequence"] != [False, True, False]
        or display["cleanup_completed"] is not True
    ):
        raise BenchError("exercise display evidence changed")
    _exact_dict(
        value["pble_responsiveness"],
        {"info_reads", "device_info_commands", "refresh_indexes", "while_run_active"},
        "exercise responsiveness",
    )
    responsiveness = value["pble_responsiveness"]
    info_reads = _positive_int(responsiveness["info_reads"], "exercise INFO reads")
    device_commands = _positive_int(
        responsiveness["device_info_commands"],
        "exercise DEVICE_INFO commands",
    )
    indexes = responsiveness["refresh_indexes"]
    if (
        responsiveness["while_run_active"] is not True
        or not isinstance(indexes, list)
        or any(type(item) is not int for item in indexes)
        or len(indexes) < MIN_RESPONSIVE_PROBES
        or indexes != sorted(set(indexes))
        or any(item < 0 or item >= REFRESH_COUNT for item in indexes)
        or info_reads != device_commands
        or info_reads != len(indexes)
    ):
        raise BenchError("exercise responsiveness is not active-run evidence")
    _validate_run_summary(value["run"], "exercise run")
    if type(value["next_stage"]) is not str or value["next_stage"] != "soft-reboot":
        raise BenchError("exercise next stage changed")


def _validate_soft_stage(value, expected_runtime_identity):
    _validate_redacted_stage(
        value,
        "soft-reboot",
        {
            "volatile_sentinel_armed",
            "pre_reboot_run",
            "soft_reboot_acknowledged",
            "transport_disconnect_required",
            "next_stage",
        },
        "soft reboot",
        expected_runtime_identity,
    )
    if (
        value["volatile_sentinel_armed"] is not True
        or value["soft_reboot_acknowledged"] is not True
        or value["transport_disconnect_required"] is not True
        or value["next_stage"] != "post-reboot"
    ):
        raise BenchError("soft-reboot proof changed")
    _validate_run_summary(value["pre_reboot_run"], "pre-reboot run")


def _validate_post_stage(value, expected_runtime_identity):
    _validate_redacted_stage(
        value,
        "post-reboot",
        {"runtime_imported", "volatile_sentinel_absent", "run", "next_stage"},
        "post reboot",
        expected_runtime_identity,
    )
    if (
        value["runtime_imported"] is not True
        or value["volatile_sentinel_absent"] is not True
        or value["next_stage"] is not None
    ):
        raise BenchError("post-reboot proof changed")
    _validate_run_summary(value["run"], "post-reboot run")


def validate_qualification_result(value):
    """Strictly validate a complete redacted qualification hash chain."""
    top_keys = {
        "schema_version",
        "status",
        "stage",
        "profile_id",
        "board_model",
        "session_id",
        "candidate_firmware_sha256",
        "candidate_firmware_size_bytes",
        "candidate_attestation",
        "exercise",
        "cycles",
        "qualification",
    }
    _exact_dict(value, top_keys, "qualification result")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != SCHEMA_VERSION
        or type(value["status"]) is not str
        or value["status"] != "passed"
        or type(value["stage"]) is not str
        or value["stage"] != "qualification"
        or type(value["profile_id"]) is not str
        or value["profile_id"] != PROFILE_ID
        or type(value["board_model"]) is not str
        or value["board_model"] != BOARD_MODEL
    ):
        raise BenchError("qualification top-level identity changed")
    session_id = _validate_session_id(value["session_id"])
    candidate_sha256 = _validate_candidate_sha256(
        value["candidate_firmware_sha256"]
    )
    candidate_size_bytes = _validate_candidate_size(
        value["candidate_firmware_size_bytes"]
    )
    candidate_attestation = _validate_candidate_attestation(
        value["candidate_attestation"],
        candidate_size_bytes,
    )

    exercise = _exact_dict(
        value["exercise"],
        {
            "session_id",
            "candidate_firmware_sha256",
            "candidate_firmware_size_bytes",
            "candidate_attestation",
            "candidate_verification",
            "operator_observation",
            "stage_result",
            "record_sha256",
        },
        "exercise record",
    )
    exercise_attestation = _validate_candidate_attestation(
        exercise["candidate_attestation"],
        candidate_size_bytes,
    )
    if (
        exercise["session_id"] != session_id
        or exercise["candidate_firmware_sha256"] != candidate_sha256
        or type(exercise["candidate_firmware_size_bytes"]) is not int
        or exercise["candidate_firmware_size_bytes"] != candidate_size_bytes
        or exercise_attestation != candidate_attestation
    ):
        raise BenchError("exercise record identity changed")
    runtime_identity = _validate_candidate_stage(
        exercise["candidate_verification"],
        candidate_attestation,
    )
    observation = _exact_dict(
        exercise["operator_observation"],
        {"confirmed", "pattern_id"},
        "operator observation",
    )
    if (
        observation["confirmed"] is not True
        or type(observation["pattern_id"]) is not str
        or observation["pattern_id"] != VISUAL_PATTERN_ID
    ):
        raise BenchError("operator observation is absent or changed")
    _validate_exercise_stage(exercise["stage_result"], runtime_identity)
    exercise_without_digest = dict(exercise)
    exercise_digest = exercise_without_digest.pop("record_sha256")
    if exercise_digest != record_sha256(exercise_without_digest):
        raise BenchError("exercise record digest changed")

    cycles = value["cycles"]
    if not isinstance(cycles, list) or len(cycles) != QUALIFICATION_REBOOT_CYCLES:
        raise BenchError("qualification must contain exactly three cycles")
    predecessor = exercise_digest
    cycle_keys = {
        "session_id",
        "candidate_firmware_sha256",
        "candidate_firmware_size_bytes",
        "candidate_attestation",
        "cycle",
        "predecessor_sha256",
        "reconnect_attempts",
        "old_connection_closed",
        "soft_reboot",
        "post_reboot",
        "record_sha256",
    }
    for index, cycle in enumerate(cycles, 1):
        _exact_dict(cycle, cycle_keys, "qualification cycle %d" % index)
        cycle_attestation = _validate_candidate_attestation(
            cycle["candidate_attestation"],
            candidate_size_bytes,
        )
        if (
            cycle["session_id"] != session_id
            or cycle["candidate_firmware_sha256"] != candidate_sha256
            or type(cycle["candidate_firmware_size_bytes"]) is not int
            or cycle["candidate_firmware_size_bytes"] != candidate_size_bytes
            or cycle_attestation != candidate_attestation
            or type(cycle["cycle"]) is not int
            or cycle["cycle"] != index
            or cycle["predecessor_sha256"] != predecessor
            or cycle["old_connection_closed"] is not True
        ):
            raise BenchError("qualification cycle %d identity changed" % index)
        _positive_int(cycle["reconnect_attempts"], "cycle reconnect attempts")
        _validate_soft_stage(cycle["soft_reboot"], runtime_identity)
        _validate_post_stage(cycle["post_reboot"], runtime_identity)
        cycle_without_digest = dict(cycle)
        cycle_digest = cycle_without_digest.pop("record_sha256")
        if cycle_digest != record_sha256(cycle_without_digest):
            raise BenchError("qualification cycle %d digest changed" % index)
        predecessor = cycle_digest

    qualification = _exact_dict(
        value["qualification"],
        {"reboot_cycles", "fresh_vm_cycles", "terminal_record_sha256"},
        "qualification summary",
    )
    _positive_int(qualification["reboot_cycles"], "qualification reboot cycles")
    _positive_int(qualification["fresh_vm_cycles"], "qualification fresh VM cycles")
    if (
        qualification["reboot_cycles"] != QUALIFICATION_REBOOT_CYCLES
        or qualification["fresh_vm_cycles"] != QUALIFICATION_REBOOT_CYCLES
        or qualification["terminal_record_sha256"] != predecessor
    ):
        raise BenchError("qualification summary changed")
    if VM_SENTINEL.encode("ascii") in canonical_json_bytes(value):
        raise BenchError("qualification evidence leaked the volatile sentinel")
    return value


def write_result_exclusive(path, result):
    """Write one redacted canonical result without replacing existing data."""
    if isinstance(result, dict) and (
        result.get("stage") == "qualification"
        or "cycles" in result
        or "qualification" in result
    ):
        validate_qualification_result(result)
    payload = canonical_json_bytes(result)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(str(target), flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            target.unlink()
        except OSError:
            pass
        raise
    return payload


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="ADR-0023 exact ESP32-S3-LCD-1.47B TFT HIL runner"
    )
    parser.add_argument(
        "--stage",
        required=True,
        choices=("exercise", "soft-reboot", "post-reboot", "qualification"),
    )
    parser.add_argument(
        "--address",
        required=True,
        help="BLE UUID/MAC input; deliberately omitted from result evidence",
    )
    parser.add_argument("--preflight", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--firmware-bin", type=Path)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)
    if args.stage == "qualification" and args.firmware_bin is None:
        parser.error("--firmware-bin is required for qualification")
    if args.stage != "qualification" and args.firmware_bin is not None:
        parser.error("--firmware-bin is accepted only for qualification")
    return args


async def _read_stdin_line():
    """Read one operator line without an uncancellable executor thread."""
    loop = asyncio.get_running_loop()
    try:
        descriptor = sys.stdin.fileno()
    except (AttributeError, OSError, ValueError):
        return None
    future = loop.create_future()

    def line_ready():
        if future.done():
            return
        try:
            line = sys.stdin.readline()
        except (EOFError, OSError, ValueError):
            future.set_result(None)
            return
        future.set_result(line if line else None)

    try:
        loop.add_reader(descriptor, line_ready)
    except (AttributeError, NotImplementedError, OSError, ValueError):
        return None
    try:
        return await future
    finally:
        loop.remove_reader(descriptor)


async def _prompt_visual_confirmation(pattern_id):
    message = (
        "Confirm the Waveshare TFT visibly showed the complete %s pattern "
        "with the border, RGB bars, four corners, PyBLE text, and progress "
        "bar. Type VISIBLE to continue: " % pattern_id
    )
    sys.stderr.write(message)
    sys.stderr.flush()
    answer = await _read_stdin_line()
    if answer is None:
        return False
    return answer.strip() == "VISIBLE"


async def _run_cli(args):
    if not isinstance(args.timeout, (int, float)) or args.timeout <= 0 or args.timeout > 120:
        raise BenchError("timeout must be in (0, 120] seconds")
    preflight = load_preflight(args.preflight)
    if args.stage == "qualification":
        candidate = inspect_candidate_firmware(args.firmware_bin)
        return await run_qualification(
            PbleCentral.connect,
            args.address,
            preflight,
            candidate["sha256"],
            candidate["size_bytes"],
            candidate["attestation"],
            timeout_s=args.timeout,
            confirm_visual=_prompt_visual_confirmation,
        )
    central = await PbleCentral.connect(args.address, timeout=args.timeout)
    try:
        if args.stage == "exercise":
            return await run_exercise(central, preflight, timeout_s=args.timeout)
        if args.stage == "soft-reboot":
            return await run_soft_reboot(central, preflight, timeout_s=args.timeout)
        return await run_post_reboot(central, preflight, timeout_s=args.timeout)
    finally:
        await central.disconnect()


def main(argv=None):
    args = _parse_args(argv)
    try:
        result = asyncio.run(_run_cli(args))
        payload = write_result_exclusive(args.output, result)
    except BenchError as exc:
        print("TFT HIL failed: %s" % exc, file=sys.stderr)
        return 2
    except FileExistsError:
        print("TFT HIL failed: output already exists", file=sys.stderr)
        return 2
    except Exception as exc:  # HIL backend errors can include private addresses.
        print(
            "TFT HIL failed in local BLE backend (%s)" % type(exc).__name__,
            file=sys.stderr,
        )
        return 2
    sys.stdout.buffer.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
