#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""ADR-0024 exact-board Waveshare boot-splash HIL qualification.

The BLE address is input-only. Results contain only the frozen profile,
candidate binding, redacted PBLE capabilities, deterministic lifecycle
evidence, and two explicit operator observations. Nothing in this runner can
manufacture visual or QR evidence: the CLI asks a human to inspect and scan the
physical display twice.
"""

import argparse
import asyncio
import importlib.util
import inspect
import os
import re
import secrets
import sys
import time
from pathlib import Path

import _pble_wire as wire
import _production_app_probe as production_app
import tft_st7789_bench as tft
from _pble_bench import BenchError, CommandIds, canonical_json_bytes
from _pble_central import (
    PbleCentral,
    PbleConnectError,
    PbleLinkLossError,
    rsp_status,
    status_name,
)


def _load_qualification_gate():
    source = (
        Path(__file__).resolve().parents[3]
        / "firmware"
        / "qualification"
        / "waveshare_lcd147b_release_gate.py"
    ).resolve(strict=True)
    spec = importlib.util.spec_from_file_location(
        "_pyble_hil_waveshare_lcd147b_gate",
        source,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the LCD qualification validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


qualification_gate = _load_qualification_gate()


SCHEMA_VERSION = 1
PROFILE_ID = "waveshare-esp32-s3-lcd-147b"
EXPECTED_CHIP = "esp32-s3"
BOARD_MODEL = "ESP32-S3-LCD-1.47B"
EXPECTED_FIRMWARE_VERSION = "0.5.1"

QR_URL = "https://pyble.dev/app"
QR_VERSION = 2
QR_ECC = "M"
QR_MASK = 2
QR_SIZE = 25
QR_ROW_MASKS = (
    0x1FCF87F,
    0x104EE41,
    0x175155D,
    0x1758F5D,
    0x175315D,
    0x1056341,
    0x1FD557F,
    0x0017700,
    0x17C2E7C,
    0x1CA55A2,
    0x097720B,
    0x06A13C1,
    0x0BC7EF7,
    0x181452A,
    0x166F27B,
    0x113A131,
    0x166E1F4,
    0x0019B18,
    0x1FCCD57,
    0x1059B1B,
    0x17597F7,
    0x175C0DF,
    0x175300D,
    0x104E7B9,
    0x1FD207F,
)
QR_MATRIX_SHA256 = (
    "6b00240151e36ff2fdbb1d556d6f3b0dd75f8fcce13683ea21033e8149687875"
)
SPLASH_PATTERN_ID = "waveshare-lcd147b-pyble-boot-splash-v1"

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
FRAMEBUFFER_BYTES = WIDTH * HEIGHT * 2
MAX_REUSE_HEAP_DRIFT_BYTES = 8192
MAX_SPLASH_HEAP_DRIFT_BYTES = 8192
RUN_SOURCE_LIMIT = 2048
REBOOT_DELIVERY_GRACE_S = tft.REBOOT_DELIVERY_GRACE_S
RECONNECT_POLL_S = tft.RECONNECT_POLL_S
DEFAULT_OPERATOR_TIMEOUT_S = tft.DEFAULT_OPERATOR_TIMEOUT_S
MAX_OPERATOR_TIMEOUT_S = tft.MAX_OPERATOR_TIMEOUT_S

MARKER_PREFIX = "__PYBLE_SPLASH_V1_"
ENABLE_MARKER = MARKER_PREFIX + "ENABLE"
DISABLE_MARKER = MARKER_PREFIX + "DISABLE"
PROBE_MARKER = MARKER_PREFIX + "PROBE"
REUSE_MARKER = MARKER_PREFIX + "REUSE"
REBOOT_ARM_MARKER = MARKER_PREFIX + "REBOOT_ARM=armed"
STALE_VM_MARKER = MARKER_PREFIX + "STALE_VM=detected"
VM_SENTINEL = "__PYBLE_SPLASH_VM_EPOCH_V1__"

COMBINED_SCHEMA_VERSION = 1
BOOT_EVIDENCE_MARKER = "__PYBLE_SPLASH_V2_BOOT"
COMBINED_BOOT_PHASES = (
    "setup-disabled",
    "setup-enabled",
    "cycle-1",
    "cycle-2",
    "cycle-3",
)
COMBINED_RECORD_STAGES = (
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

LIFECYCLE_STAGE_NAMES = (
    "disabled-reboot",
    "initial-disabled",
    "enable-reboot",
    "enabled-boot",
    "resource-reuse",
    "redraw-reboot",
    "redraw-boot",
    "final-disabled",
)

_PROCESS_CONTROL_EXCEPTIONS = (
    asyncio.CancelledError,
    KeyboardInterrupt,
    SystemExit,
    GeneratorExit,
)

PROBE_PHASES = {
    "initial-disabled": False,
    "enabled-boot": True,
    "redraw-boot": True,
    "final-disabled": False,
}

HELLO_PAYLOAD = (
    b"proto_versions=1\n"
    b"app_name=hil-splash-adr0024\n"
    b"app_version=0"
)


record_sha256 = tft.record_sha256


def _bounded_source(source, label):
    try:
        encoded = source.encode("ascii", errors="strict")
    except UnicodeEncodeError as exc:
        raise BenchError("%s source is not ASCII" % label) from exc
    if len(encoded) > RUN_SOURCE_LIMIT:
        raise BenchError("%s source exceeds RUN{source} limit" % label)
    return source


def build_enable_source():
    """Persist opt-in and arm a volatile fresh-VM sentinel."""
    return _bounded_source(
        '''import sys
import pyble_waveshare_lcd147b as w
w.enable_boot_splash()
_e=w.boot_splash_enabled()
print("%s=%%d"%%_e)
if not _e:raise RuntimeError("splash enable did not persist")
sys.path.append("%s")
''' % (ENABLE_MARKER, VM_SENTINEL),
        "enable",
    )


def build_disable_source():
    """Persist disablement and prove the retained-frame backlight is low."""
    return _bounded_source(
        '''from machine import Pin
import pyble_waveshare_lcd147b as w
w.disable_boot_splash()
_e=w.boot_splash_enabled();_b=Pin(46).value()
print("%s=%%d,%%d"%%(_e,_b))
if _e or _b:raise RuntimeError("splash disable did not settle")
''' % DISABLE_MARKER,
        "disable",
    )


def build_reboot_arm_source():
    """Arm a volatile fresh-VM sentinel immediately before any reboot."""
    return _bounded_source(
        '''import sys
sys.path.append("%s")
print("%s")
''' % (VM_SENTINEL, REBOOT_ARM_MARKER),
        "reboot arm",
    )


def build_probe_source(phase, expected_enabled):
    """Read only the frozen post-HELLO state for one lifecycle phase."""
    if (
        type(phase) is not str
        or phase not in PROBE_PHASES
        or type(expected_enabled) is not bool
        or PROBE_PHASES[phase] is not expected_enabled
    ):
        raise BenchError("probe phase/enabled contract is invalid")
    stale_guard = ""
    if phase in ("initial-disabled", "enabled-boot", "redraw-boot"):
        stale_guard = '''import sys
if "%s" in sys.path:
 print("%s")
 raise RuntimeError("soft reset did not establish a fresh VM")
''' % (VM_SENTINEL, STALE_VM_MARKER)
    source = '''%simport gc
import pble_ble
import pyble
from machine import Pin
import pyble_waveshare_lcd147b as w
gc.collect();_e=w.boot_splash_enabled();_r=pble_ble.wait_ready(0);_b=Pin(46).value();_m=gc.mem_free()
print("%s=%s,%%d,%%d,%%d,%%s,%%d"%%(_e,_r,_b,pyble.__version__,_m))
if _e!=%s or not _r or _b!=%s:raise RuntimeError("splash probe mismatch")
''' % (
        stale_guard,
        PROBE_MARKER,
        phase,
        "True" if expected_enabled else "False",
        "1" if expected_enabled else "0",
    )
    return _bounded_source(source, "%s probe" % phase)


def build_combined_boot_probe_source(phase, expected_enabled):
    """Prove a fresh VM and the exact immutable boot-decision trace."""
    if (
        type(phase) is not str
        or phase not in COMBINED_BOOT_PHASES
        or type(expected_enabled) is not bool
        or (phase in ("setup-enabled", "cycle-1")) is not expected_enabled
    ):
        raise BenchError("combined boot probe phase/enabled contract is invalid")
    expected_trace = (
        SUCCESS_BOOT_EVIDENCE if expected_enabled else DISABLED_BOOT_EVIDENCE
    )
    trace_name = "success" if expected_enabled else "disabled"
    source = '''import gc,sys
if "%s" in sys.path:
 print("%s")
 raise RuntimeError("soft reset did not establish a fresh VM")
import pble_ble,pyble,pyble_st7789
from machine import Pin
import pyble_waveshare_lcd147b as w
_expected=%r
_trace=w._boot_evidence()
gc.collect();_e=w.boot_splash_enabled();_r=pble_ble.wait_ready(0);_b=Pin(46).value();_m=gc.mem_free()
if _trace!=_expected:raise RuntimeError("boot evidence mismatch")
print("%s=%s,%%d,%%d,%%d,%%s,%%d,%s"%%(_e,_r,_b,pyble.__version__,_m))
if _e!=%s or not _r or _b!=%s:raise RuntimeError("combined boot probe mismatch")
''' % (
        VM_SENTINEL,
        STALE_VM_MARKER,
        expected_trace,
        BOOT_EVIDENCE_MARKER,
        phase,
        trace_name,
        "True" if expected_enabled else "False",
        "1" if expected_enabled else "0",
    )
    return _bounded_source(source, "%s combined boot probe" % phase)


def build_reuse_source():
    """Allocate, show, release, and measure an ordinary generic TFT driver."""
    source = '''import gc,sys
from machine import Pin
import pyble_waveshare_lcd147b as w
from pyble_st7789 import ST7789
gc.collect();_a=gc.mem_free();d=None;_shown=0
try:
 d=ST7789(1,40000000,0,0,Pin(40,Pin.OUT),Pin(45,Pin.OUT),Pin(42,Pin.OUT),Pin(41,Pin.OUT),Pin(39,Pin.OUT),Pin(46,Pin.OUT),172,320,34,0,True,True)
 _d=gc.mem_free();d.fill(0);d.show();_shown=1
finally:
 if d is not None:
  try:d.backlight(False)
  finally:d.deinit()
 d=None;gc.collect()
_z=gc.mem_free();_e=w.boot_splash_enabled();_off=Pin(46).value()==0
print("%s=%%d,%%d,%%d,%%d,%%d,%%d"%%(_a,_d,_z,_e,_shown,_off))
if _a-_d<%d or _a-_z>%d or not (_e and _shown and _off):raise RuntimeError("TFT reuse proof failed")
sys.path.append("%s")
''' % (
        REUSE_MARKER,
        FRAMEBUFFER_BYTES,
        MAX_REUSE_HEAP_DRIFT_BYTES,
        VM_SENTINEL,
    )
    return _bounded_source(source, "TFT reuse")


def _strict_ascii(chunks, label):
    if not isinstance(chunks, (list, tuple)):
        raise BenchError("%s output must be a chunk sequence" % label)
    try:
        return b"".join(bytes(item) for item in chunks).decode(
            "ascii", errors="strict"
        )
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise BenchError("%s output is not strict ASCII" % label) from exc


def _one_marker(chunks, pattern, label):
    output = _strict_ascii(chunks, label)
    matches = []
    for line in output.splitlines():
        if not line.startswith((MARKER_PREFIX, "__PYBLE_SPLASH_V2_")):
            continue
        match = re.fullmatch(pattern, line)
        if match is None:
            raise BenchError("%s contains a malformed runner marker" % label)
        matches.append(match)
    if len(matches) != 1:
        raise BenchError("%s must contain exactly one marker" % label)
    return matches[0]


def parse_probe_evidence(chunks, phase, *, expected_enabled):
    """Validate one connected probe and derive the retained-frame predicate."""
    if (
        type(phase) is not str
        or phase not in PROBE_PHASES
        or type(expected_enabled) is not bool
        or PROBE_PHASES[phase] is not expected_enabled
    ):
        raise BenchError("probe phase/enabled contract is invalid")
    match = _one_marker(
        chunks,
        re.escape(PROBE_MARKER)
        + r"="
        + re.escape(phase)
        + r",([01]),([01]),([01]),([^,\r\n]+),([0-9]+)",
        "%s probe" % phase,
    )
    enabled = match.group(1) == "1"
    wait_ready = match.group(2) == "1"
    backlight_on = match.group(3) == "1"
    version = match.group(4)
    heap = int(match.group(5), 10)
    rendered = enabled and wait_ready and backlight_on
    expected_rendered = expected_enabled
    if (
        enabled is not expected_enabled
        or wait_ready is not True
        or backlight_on is not expected_enabled
        or rendered is not expected_rendered
        or version != EXPECTED_FIRMWARE_VERSION
        or heap <= 0
    ):
        raise BenchError("%s probe evidence changed" % phase)
    return {
        "phase": phase,
        "enabled": enabled,
        "wait_ready": wait_ready,
        "rendered": rendered,
        "backlight_on": backlight_on,
        "firmware_version": version,
        "gc_free_bytes": heap,
    }


def parse_combined_boot_probe_evidence(chunks, phase, *, expected_enabled):
    """Parse only a source-side exact trace comparison and sanitized marker."""
    if (
        type(phase) is not str
        or phase not in COMBINED_BOOT_PHASES
        or type(expected_enabled) is not bool
        or (phase in ("setup-enabled", "cycle-1")) is not expected_enabled
    ):
        raise BenchError("combined boot probe phase/enabled contract is invalid")
    trace_name = "success" if expected_enabled else "disabled"
    match = _one_marker(
        chunks,
        re.escape(BOOT_EVIDENCE_MARKER)
        + r"="
        + re.escape(phase)
        + r",([01]),([01]),([01]),([^,\r\n]+),([0-9]+),(disabled|success)",
        "%s combined boot probe" % phase,
    )
    enabled = match.group(1) == "1"
    wait_ready = match.group(2) == "1"
    backlight_on = match.group(3) == "1"
    version = match.group(4)
    heap = int(match.group(5), 10)
    actual_trace_name = match.group(6)
    if (
        enabled is not expected_enabled
        or wait_ready is not True
        or backlight_on is not expected_enabled
        or version != EXPECTED_FIRMWARE_VERSION
        or heap <= 0
        or actual_trace_name != trace_name
    ):
        raise BenchError("%s exact boot evidence changed" % phase)
    expected_trace = (
        SUCCESS_BOOT_EVIDENCE if expected_enabled else DISABLED_BOOT_EVIDENCE
    )
    return {
        "phase": phase,
        "enabled": enabled,
        "wait_ready": wait_ready,
        "rendered": expected_enabled,
        "backlight_on": backlight_on,
        "firmware_version": version,
        "gc_free_bytes": heap,
        "runtime_imported": True,
        "boot_evidence": [list(item) for item in expected_trace],
    }


def parse_reuse_evidence(chunks):
    match = _one_marker(
        chunks,
        re.escape(REUSE_MARKER)
        + r"=([0-9]+),([0-9]+),([0-9]+),([01]),([01]),([01])",
        "TFT reuse",
    )
    before, during, after = (int(match.group(index), 10) for index in (1, 2, 3))
    enabled = match.group(4) == "1"
    shown = match.group(5) == "1"
    backlight_off = match.group(6) == "1"
    if (
        min(before, during, after) <= 0
        or before - during < FRAMEBUFFER_BYTES
        or before - after > MAX_REUSE_HEAP_DRIFT_BYTES
        or not enabled
        or not shown
        or not backlight_off
    ):
        raise BenchError("TFT reuse did not prove allocation and reclamation")
    return {
        "gc_before_bytes": before,
        "gc_during_bytes": during,
        "gc_after_bytes": after,
        "framebuffer_reclaimed": True,
        "ordinary_driver_reused": True,
        "enabled_after_reuse": True,
        "backlight_off_after_reuse": True,
    }


def validate_operator_observation(value):
    keys = {"phase", "confirmed", "pattern_id", "scanned_url"}
    if not isinstance(value, dict) or set(value) != keys:
        raise BenchError("operator observation has wrong keys")
    if (
        type(value["phase"]) is not str
        or value["phase"] not in ("enabled-boot", "redraw-boot")
        or value["confirmed"] is not True
        or type(value["pattern_id"]) is not str
        or value["pattern_id"] != SPLASH_PATTERN_ID
        or type(value["scanned_url"]) is not str
        or value["scanned_url"] != QR_URL
    ):
        raise BenchError("operator did not confirm the exact splash and QR URL")
    return value


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
    caps = tft.validate_and_redact_caps(response.payload[1:])
    if (
        caps["proto"] != 1
        or caps["agent"] != EXPECTED_FIRMWARE_VERSION
        or caps["chip"] != EXPECTED_CHIP
        or caps["mpy"] != tft.EXPECTED_MPY_VERSION
    ):
        raise BenchError("HELLO runtime identity does not match the candidate")
    if hasattr(central, "confirm_caps_mtu"):
        try:
            central.confirm_caps_mtu(caps["mtu"])
        except ValueError as exc:
            raise BenchError("HELLO MTU validation failed") from exc
    return caps


def _runtime_identity(caps):
    return (caps["proto"], caps["agent"], caps["chip"], caps["mpy"])


def _require_runtime_identity(caps, expected):
    if _runtime_identity(caps) != expected:
        raise BenchError("PBLE runtime identity changed during qualification")


async def _run_source(
        central,
        command_ids,
        caps,
        source,
        *,
        timeout_s,
        poll_interval_s,
        stale_vm_marker=None):
    run = await tft._collect_run(
        central,
        command_ids,
        source,
        hello_caps=caps,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
        probe_responsiveness=False,
        stale_vm_marker=stale_vm_marker,
    )
    chunks = run.pop("stdout_chunks")
    run.pop("info_reads")
    run.pop("device_info_commands")
    run.pop("responsive_refresh_indexes")
    return chunks, run


def _parse_enable(chunks):
    match = _one_marker(
        chunks,
        re.escape(ENABLE_MARKER) + r"=([01])",
        "enable",
    )
    if match.group(1) != "1":
        raise BenchError("boot splash enable did not persist")
    return True


def _parse_disable(chunks):
    match = _one_marker(
        chunks,
        re.escape(DISABLE_MARKER) + r"=([01]),([01])",
        "disable",
    )
    if match.groups() != ("0", "0"):
        raise BenchError("boot splash disable/backlight proof failed")
    return True


def _parse_reboot_arm(chunks):
    _one_marker(
        chunks,
        re.escape(REBOOT_ARM_MARKER),
        "disabled reboot arm",
    )
    return True


async def _probe(
        central,
        command_ids,
        caps,
        phase,
        enabled,
        *,
        timeout_s,
        poll_interval_s):
    chunks, _run = await _run_source(
        central,
        command_ids,
        caps,
        build_probe_source(phase, enabled),
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
        stale_vm_marker=(
            STALE_VM_MARKER
            if phase in ("initial-disabled", "enabled-boot", "redraw-boot")
            else None
        ),
    )
    return parse_probe_evidence(chunks, phase, expected_enabled=enabled)


async def _action(
        central,
        command_ids,
        caps,
        source,
        parser,
        *,
        timeout_s,
        poll_interval_s):
    chunks, _run = await _run_source(
        central,
        command_ids,
        caps,
        source,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
    )
    return parser(chunks)


async def _soft_reboot(central, command_ids, *, timeout_s):
    response = await central.send_cmd(
        wire.OP_SOFT_REBOOT,
        command_ids.next(),
        timeout=timeout_s,
    )
    status = rsp_status(response)
    if status != wire.ST_OK:
        raise BenchError("SOFT_REBOOT -> %s" % status_name(status))
    return True


async def _stop_runner(central, command_ids, *, timeout_s):
    response = await central.send_cmd(
        wire.OP_STOP,
        command_ids.next(),
        timeout=timeout_s,
    )
    status = rsp_status(response)
    if status != wire.ST_OK:
        raise BenchError("STOP -> %s" % status_name(status))
    return True


async def _close_rejected_connection(central, deadline, clock, label, original):
    """Close a rejected transition link without replacing process control."""
    try:
        await tft._close_connection(central, deadline, clock, label)
    except BaseException as cleanup_error:
        if isinstance(original, _PROCESS_CONTROL_EXCEPTIONS):
            raise original
        if isinstance(cleanup_error, _PROCESS_CONTROL_EXCEPTIONS):
            raise cleanup_error from original
        raise original


async def _fresh_phase_connection(
        connect,
        address,
        expected_runtime,
        phase,
        enabled,
        *,
        deadline,
        poll_interval_s,
        sleep,
        clock):
    """Retry only transactional reset-transition failures under one deadline."""
    await tft._sleep_with_deadline(
        sleep,
        REBOOT_DELIVERY_GRACE_S,
        deadline,
        clock,
        "%s delivery grace" % phase,
    )
    attempts = 0
    while True:
        tft._deadline_remaining(deadline, clock, "%s reconnect" % phase)
        attempts += 1
        try:
            central = await tft._connect_with_deadline(
                connect,
                address,
                deadline,
                clock,
                phase,
            )
        except PbleConnectError:
            await tft._sleep_with_deadline(
                sleep,
                RECONNECT_POLL_S,
                deadline,
                clock,
                "%s reconnect delay" % phase,
            )
            continue

        command_ids = CommandIds()
        try:
            caps = await tft._await_with_deadline(
                lambda remaining: _hello(central, command_ids, remaining),
                deadline,
                clock,
                "%s HELLO" % phase,
            )
            _require_runtime_identity(caps, expected_runtime)
            probe = await tft._await_with_deadline(
                lambda remaining: _probe(
                    central,
                    command_ids,
                    caps,
                    phase,
                    enabled,
                    timeout_s=remaining,
                    poll_interval_s=poll_interval_s,
                ),
                deadline,
                clock,
                "%s fresh-VM probe" % phase,
            )
        except BaseException as error:
            retry = isinstance(error, tft.StaleVmEpochError)
            if isinstance(error, PbleLinkLossError):
                retry = not tft._central_connected(central)
            await _close_rejected_connection(
                central,
                deadline,
                clock,
                "%s rejected" % phase,
                error,
            )
            if not retry:
                raise error
            await tft._sleep_with_deadline(
                sleep,
                RECONNECT_POLL_S,
                deadline,
                clock,
                "%s stale transition delay" % phase,
            )
            continue
        tft._deadline_remaining(deadline, clock, "%s fresh-VM proof" % phase)
        return central, command_ids, caps, probe, attempts


async def _reboot_transition(
        connect,
        address,
        central,
        command_ids,
        expected_runtime,
        phase,
        enabled,
        *,
        timeout_s,
        poll_interval_s,
        sleep,
        clock):
    """Acknowledge reboot, close the old link, and prove one fresh VM."""
    deadline = clock() + timeout_s
    acknowledged = await tft._await_with_deadline(
        lambda remaining: _soft_reboot(
            central,
            command_ids,
            timeout_s=remaining,
        ),
        deadline,
        clock,
        "%s SOFT_REBOOT" % phase,
    )
    old_connection_closed = await tft._close_connection(
        central,
        deadline,
        clock,
        "%s old link" % phase,
    )
    fresh = await _fresh_phase_connection(
        connect,
        address,
        expected_runtime,
        phase,
        enabled,
        deadline=deadline,
        poll_interval_s=poll_interval_s,
        sleep=sleep,
        clock=clock,
    )
    return acknowledged, old_connection_closed, fresh


async def _best_effort_disable(
        connect,
        address,
        central,
        command_ids,
        caps,
        *,
        timeout_s,
        poll_interval_s,
        clock):
    """Try once to persist disablement and darken, returning any cleanup error."""
    deadline = clock() + timeout_s
    cleanup_central = central
    cleanup_ids = command_ids
    cleanup_caps = caps
    error = None
    try:
        connected = (
            cleanup_central is not None
            and tft._central_connected(cleanup_central)
        )
    except BaseException as caught:
        connected = False
        error = caught
    if not connected:
        cleanup_central = None
        try:
            cleanup_central = await tft._connect_with_deadline(
                connect,
                address,
                deadline,
                clock,
                "cleanup disable",
            )
            cleanup_ids = CommandIds()
            cleanup_caps = await tft._await_with_deadline(
                lambda remaining: _hello(
                    cleanup_central,
                    cleanup_ids,
                    remaining,
                ),
                deadline,
                clock,
                "cleanup disable HELLO",
            )
        except BaseException as caught:
            return caught
    try:
        await tft._await_with_deadline(
            lambda remaining: _stop_runner(
                cleanup_central,
                cleanup_ids,
                timeout_s=remaining,
            ),
            deadline,
            clock,
            "cleanup STOP",
        )
    except BaseException as caught:
        error = caught
    try:
        await tft._await_with_deadline(
            lambda remaining: _action(
                cleanup_central,
                cleanup_ids,
                cleanup_caps,
                build_disable_source(),
                _parse_disable,
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
            ),
            deadline,
            clock,
            "cleanup disable/darken",
        )
    except BaseException as caught:
        if error is None or isinstance(caught, _PROCESS_CONTROL_EXCEPTIONS):
            error = caught
    try:
        await tft._close_connection(
            cleanup_central,
            deadline,
            clock,
            "cleanup disable",
        )
    except BaseException as caught:
        if error is None or isinstance(caught, _PROCESS_CONTROL_EXCEPTIONS):
            error = caught
    return error


async def _observe(confirm_visual, phase):
    scanned = await confirm_visual(phase, SPLASH_PATTERN_ID, QR_URL)
    observation = {
        "phase": phase,
        "confirmed": type(scanned) is str and scanned == QR_URL,
        "pattern_id": SPLASH_PATTERN_ID,
        "scanned_url": scanned if type(scanned) is str else "",
    }
    return validate_operator_observation(observation)


def _splash_reclamation_proof(initial_disabled, enabled_boot, redraw_boot):
    baseline = initial_disabled["gc_free_bytes"]
    enabled_free = enabled_boot["gc_free_bytes"]
    redraw_free = redraw_boot["gc_free_bytes"]
    enabled_deficit = max(0, baseline - enabled_free)
    redraw_deficit = max(0, baseline - redraw_free)
    if (
        enabled_deficit > MAX_SPLASH_HEAP_DRIFT_BYTES
        or redraw_deficit > MAX_SPLASH_HEAP_DRIFT_BYTES
    ):
        raise BenchError("boot splash framebuffer was not reclaimed")
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


def _build_lifecycle_records(binding, evidence_items):
    if len(evidence_items) != len(LIFECYCLE_STAGE_NAMES):
        raise BenchError("splash lifecycle evidence cardinality changed")
    predecessor = record_sha256(binding)
    records = []
    for ordinal, (stage, evidence) in enumerate(
            zip(LIFECYCLE_STAGE_NAMES, evidence_items), 1):
        record = {
            "ordinal": ordinal,
            "stage": stage,
            "session_id": binding["session_id"],
            "candidate_firmware_sha256": binding["candidate_firmware_sha256"],
            "candidate_firmware_size_bytes": binding[
                "candidate_firmware_size_bytes"
            ],
            "predecessor_sha256": predecessor,
            "evidence": evidence,
        }
        record["record_sha256"] = record_sha256(record)
        predecessor = record["record_sha256"]
        records.append(record)
    return records, predecessor


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
    """Run the exact three-reset, two-scan ADR-0024 qualification."""
    preflight = tft.validate_preflight(preflight)
    candidate_firmware_sha256 = tft._validate_candidate_sha256(
        candidate_firmware_sha256
    )
    candidate_firmware_size_bytes = tft._validate_candidate_size(
        candidate_firmware_size_bytes
    )
    candidate_attestation = tft._validate_candidate_attestation(
        candidate_attestation,
        candidate_firmware_size_bytes,
    )
    if (
        not isinstance(timeout_s, (int, float))
        or isinstance(timeout_s, bool)
        or timeout_s <= REBOOT_DELIVERY_GRACE_S
        or timeout_s > 120
    ):
        raise BenchError("qualification timeout must be in (0.25, 120] seconds")
    if (
        not isinstance(poll_interval_s, (int, float))
        or isinstance(poll_interval_s, bool)
        or poll_interval_s < 0
    ):
        raise BenchError("poll interval must be non-negative")
    if not callable(sleep) or not callable(clock):
        raise BenchError("qualification clock and sleep must be callable")
    if not callable(confirm_visual):
        raise BenchError("qualification requires a real operator callback")
    if session_id is None:
        session_id = secrets.token_hex(16)
    session_id = tft._validate_session_id(session_id)

    candidate_verification = None
    initial_disabled = None
    enabled_boot = None
    resource_reuse = None
    redraw_boot = None
    final_disabled = None
    observations = []
    expected_runtime = None
    disabled_reboot = None
    disabled_old_closed = None
    disabled_attempts = None
    first_reboot = None
    first_old_closed = None
    enabled_attempts = None
    second_reboot = None
    second_old_closed = None
    redraw_attempts = None
    enable_persisted = None
    disable_persisted = None
    cleanup_armed = False
    central = None
    command_ids = None
    caps = None

    try:
        # Segment 1: bind live immutable flash, commit disabled, arm a volatile
        # epoch marker, and reboot. The disabled observation is made only in the
        # fresh VM reached by that acknowledged reset.
        initial_deadline = clock() + timeout_s
        central = await tft._connect_with_deadline(
            connect,
            address,
            initial_deadline,
            clock,
            "candidate/disabled reboot",
        )
        candidate_verification = await tft._await_with_deadline(
            lambda remaining: tft.run_candidate_verification(
                central,
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
        expected_runtime = _runtime_identity(candidate_verification["runtime"])
        command_ids = CommandIds()
        caps = candidate_verification["runtime"]
        cleanup_armed = True
        await tft._await_with_deadline(
            lambda remaining: _action(
                central,
                command_ids,
                caps,
                build_disable_source(),
                _parse_disable,
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
            ),
            initial_deadline,
            clock,
            "initial disable/darken",
        )
        await tft._await_with_deadline(
            lambda remaining: _action(
                central,
                command_ids,
                caps,
                build_reboot_arm_source(),
                _parse_reboot_arm,
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
            ),
            initial_deadline,
            clock,
            "disabled reboot arm",
        )
        disabled_reboot, disabled_old_closed, fresh = await _reboot_transition(
            connect,
            address,
            central,
            command_ids,
            expected_runtime,
            "initial-disabled",
            False,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            sleep=sleep,
            clock=clock,
        )
        central, command_ids, caps, initial_disabled, disabled_attempts = fresh

        # Segment 2: this connection was accepted only after the disabled fresh-
        # VM probe. Persist enablement, arm the same volatile sentinel, and reboot.
        action_deadline = clock() + timeout_s
        enable_persisted = await tft._await_with_deadline(
            lambda remaining: _action(
                central,
                command_ids,
                caps,
                build_enable_source(),
                _parse_enable,
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
            ),
            action_deadline,
            clock,
            "splash enable",
        )
        first_reboot, first_old_closed, fresh = await _reboot_transition(
            connect,
            address,
            central,
            command_ids,
            expected_runtime,
            "enabled-boot",
            True,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            sleep=sleep,
            clock=clock,
        )
        central, command_ids, caps, enabled_boot, enabled_attempts = fresh

        # Segment 3: HELLO and the enabled probe completed while the retained
        # frame was lit. Require the first real observation, then prove ordinary
        # driver takeover/reclamation on this same link before another reboot.
        observations.append(await _observe(confirm_visual, "enabled-boot"))
        reuse_deadline = clock() + timeout_s
        chunks, _run = await tft._await_with_deadline(
            lambda remaining: _run_source(
                central,
                command_ids,
                caps,
                build_reuse_source(),
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
            ),
            reuse_deadline,
            clock,
            "ordinary TFT reuse",
        )
        resource_reuse = parse_reuse_evidence(chunks)
        second_reboot, second_old_closed, fresh = await _reboot_transition(
            connect,
            address,
            central,
            command_ids,
            expected_runtime,
            "redraw-boot",
            True,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            sleep=sleep,
            clock=clock,
        )
        central, command_ids, caps, redraw_boot, redraw_attempts = fresh

        # Segment 4: require the second physical observation, then leave the
        # exact board persistently disabled and dark before accepting evidence.
        observations.append(await _observe(confirm_visual, "redraw-boot"))
        final_deadline = clock() + timeout_s
        disable_persisted = await tft._await_with_deadline(
            lambda remaining: _action(
                central,
                command_ids,
                caps,
                build_disable_source(),
                _parse_disable,
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
            ),
            final_deadline,
            clock,
            "final disable/darken",
        )
        cleanup_armed = False
        final_disabled = await tft._await_with_deadline(
            lambda remaining: _probe(
                central,
                command_ids,
                caps,
                "final-disabled",
                False,
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
            ),
            final_deadline,
            clock,
            "final disabled probe",
        )
        await tft._close_connection(
            central,
            final_deadline,
            clock,
            "redraw/final disable",
        )
        central = None
    except BaseException as original:
        cleanup_error = None
        try:
            if cleanup_armed:
                cleanup_error = await _best_effort_disable(
                    connect,
                    address,
                    central,
                    command_ids,
                    caps,
                    timeout_s=timeout_s,
                    poll_interval_s=poll_interval_s,
                    clock=clock,
                )
            elif central is not None:
                if tft._central_connected(central):
                    await tft._close_connection(
                        central,
                        clock() + timeout_s,
                        clock,
                        "failed splash qualification",
                    )
        except BaseException as caught:
            cleanup_error = caught
        if isinstance(original, _PROCESS_CONTROL_EXCEPTIONS):
            raise
        if isinstance(cleanup_error, _PROCESS_CONTROL_EXCEPTIONS):
            raise cleanup_error from original
        # Ordinary rollback failures never replace the initiating failure.
        raise

    splash_reclamation = _splash_reclamation_proof(
        initial_disabled,
        enabled_boot,
        redraw_boot,
    )

    binding = {
        "session_id": session_id,
        "candidate_firmware_sha256": candidate_firmware_sha256,
        "candidate_firmware_size_bytes": candidate_firmware_size_bytes,
        "candidate_attestation": candidate_attestation,
    }
    lifecycle = {
        "disabled_soft_reboot_acknowledged": disabled_reboot,
        "disabled_old_connection_closed": disabled_old_closed,
        "initial_disabled": initial_disabled,
        "enable_persisted": enable_persisted,
        "first_soft_reboot_acknowledged": first_reboot,
        "first_old_connection_closed": first_old_closed,
        "enabled_boot": enabled_boot,
        "resource_reuse": resource_reuse,
        "splash_framebuffer_reclamation": splash_reclamation,
        "second_soft_reboot_acknowledged": second_reboot,
        "second_old_connection_closed": second_old_closed,
        "redraw_boot": redraw_boot,
        "disable_persisted": disable_persisted,
        "final_disabled": final_disabled,
    }
    reboot_evidence = (
        {
            "soft_reboot_acknowledged": disabled_reboot,
            "old_connection_closed": disabled_old_closed,
            "fresh_reconnect_attempts": disabled_attempts,
        },
        {
            "enable_persisted": enable_persisted,
            "soft_reboot_acknowledged": first_reboot,
            "old_connection_closed": first_old_closed,
            "fresh_reconnect_attempts": enabled_attempts,
        },
        {
            "soft_reboot_acknowledged": second_reboot,
            "old_connection_closed": second_old_closed,
            "fresh_reconnect_attempts": redraw_attempts,
        },
    )
    lifecycle_evidence = (
        reboot_evidence[0],
        initial_disabled,
        reboot_evidence[1],
        {"probe": enabled_boot, "operator_observation": observations[0]},
        resource_reuse,
        reboot_evidence[2],
        {
            "probe": redraw_boot,
            "operator_observation": observations[1],
            "splash_framebuffer_reclamation": splash_reclamation,
        },
        {"disable_persisted": disable_persisted, "probe": final_disabled},
    )
    lifecycle_records, terminal_digest = _build_lifecycle_records(
        binding,
        lifecycle_evidence,
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "stage": "qualification",
        "profile_id": PROFILE_ID,
        "board_model": BOARD_MODEL,
        "firmware_version": EXPECTED_FIRMWARE_VERSION,
        "session_id": session_id,
        "candidate_firmware_sha256": candidate_firmware_sha256,
        "candidate_firmware_size_bytes": candidate_firmware_size_bytes,
        "binding": binding,
        "candidate_verification": candidate_verification,
        "qr": {
            "url": QR_URL,
            "version": QR_VERSION,
            "ecc": QR_ECC,
            "mask": QR_MASK,
            "size": QR_SIZE,
            "matrix_sha256": QR_MATRIX_SHA256,
            "pattern_id": SPLASH_PATTERN_ID,
        },
        "lifecycle": lifecycle,
        "lifecycle_records": lifecycle_records,
        "terminal_record_sha256": terminal_digest,
        "operator_observations": observations,
        "connection_evidence": {
            "fresh_reconnects": 3,
            "hello_while_splash_visible": ["enabled-boot", "redraw-boot"],
        },
    }
    result["record_sha256"] = record_sha256(result)
    return validate_qualification_result(result)


def _exact_dict(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise BenchError("%s has wrong keys" % label)
    return value


def _validate_probe_record(value, phase, enabled):
    _exact_dict(
        value,
        {
            "phase",
            "enabled",
            "wait_ready",
            "rendered",
            "backlight_on",
            "firmware_version",
            "gc_free_bytes",
        },
        "%s probe" % phase,
    )
    expected_rendered = enabled
    if (
        value["phase"] != phase
        or value["enabled"] is not enabled
        or value["wait_ready"] is not True
        or value["rendered"] is not expected_rendered
        or value["backlight_on"] is not enabled
        or value["firmware_version"] != EXPECTED_FIRMWARE_VERSION
        or type(value["gc_free_bytes"]) is not int
        or value["gc_free_bytes"] <= 0
    ):
        raise BenchError("%s probe record changed" % phase)


def _validate_reuse_record(value):
    _exact_dict(
        value,
        {
            "gc_before_bytes",
            "gc_during_bytes",
            "gc_after_bytes",
            "framebuffer_reclaimed",
            "ordinary_driver_reused",
            "enabled_after_reuse",
            "backlight_off_after_reuse",
        },
        "resource reuse",
    )
    before = value["gc_before_bytes"]
    during = value["gc_during_bytes"]
    after = value["gc_after_bytes"]
    if (
        any(type(item) is not int or item <= 0 for item in (before, during, after))
        or before - during < FRAMEBUFFER_BYTES
        or before - after > MAX_REUSE_HEAP_DRIFT_BYTES
        or value["framebuffer_reclaimed"] is not True
        or value["ordinary_driver_reused"] is not True
        or value["enabled_after_reuse"] is not True
        or value["backlight_off_after_reuse"] is not True
    ):
        raise BenchError("resource reuse record changed")


def _validate_splash_reclamation(value, initial_disabled, enabled_boot, redraw_boot):
    keys = {
        "disabled_baseline_gc_free_bytes",
        "enabled_boot_gc_free_bytes",
        "redraw_boot_gc_free_bytes",
        "enabled_boot_free_deficit_bytes",
        "redraw_boot_free_deficit_bytes",
        "max_drift_bytes",
        "framebuffer_bytes",
        "framebuffer_reclaimed",
    }
    _exact_dict(value, keys, "splash framebuffer reclamation")
    for key in keys - {"framebuffer_reclaimed"}:
        if type(value[key]) is not int or value[key] < 0:
            raise BenchError("splash framebuffer reclamation changed")
    if value["framebuffer_reclaimed"] is not True:
        raise BenchError("splash framebuffer reclamation changed")
    expected = _splash_reclamation_proof(
        initial_disabled,
        enabled_boot,
        redraw_boot,
    )
    if value != expected:
        raise BenchError("splash framebuffer reclamation changed")
    return value


def _validate_reboot_evidence(value, label, *, include_enable=False):
    keys = {
        "soft_reboot_acknowledged",
        "old_connection_closed",
        "fresh_reconnect_attempts",
    }
    if include_enable:
        keys.add("enable_persisted")
    _exact_dict(value, keys, label)
    for key in keys - {"fresh_reconnect_attempts"}:
        if value[key] is not True:
            raise BenchError("%s changed" % label)
    if (
        type(value["fresh_reconnect_attempts"]) is not int
        or value["fresh_reconnect_attempts"] <= 0
    ):
        raise BenchError("%s reconnect attempts changed" % label)


def _validate_lifecycle_chain(
        records,
        terminal_digest,
        binding,
        lifecycle,
        observations):
    if not isinstance(records, list) or len(records) != len(LIFECYCLE_STAGE_NAMES):
        raise BenchError("splash lifecycle chain cardinality changed")
    if any(not isinstance(record, dict) for record in records):
        raise BenchError("splash lifecycle chain contains a non-record")
    expected_evidence = (
        {
            "soft_reboot_acknowledged": lifecycle[
                "disabled_soft_reboot_acknowledged"
            ],
            "old_connection_closed": lifecycle["disabled_old_connection_closed"],
            "fresh_reconnect_attempts": records[0]["evidence"].get(
                "fresh_reconnect_attempts"
            ) if isinstance(records[0].get("evidence"), dict) else None,
        },
        lifecycle["initial_disabled"],
        {
            "enable_persisted": lifecycle["enable_persisted"],
            "soft_reboot_acknowledged": lifecycle[
                "first_soft_reboot_acknowledged"
            ],
            "old_connection_closed": lifecycle["first_old_connection_closed"],
            "fresh_reconnect_attempts": records[2]["evidence"].get(
                "fresh_reconnect_attempts"
            ) if isinstance(records[2].get("evidence"), dict) else None,
        },
        {
            "probe": lifecycle["enabled_boot"],
            "operator_observation": observations[0],
        },
        lifecycle["resource_reuse"],
        {
            "soft_reboot_acknowledged": lifecycle[
                "second_soft_reboot_acknowledged"
            ],
            "old_connection_closed": lifecycle["second_old_connection_closed"],
            "fresh_reconnect_attempts": records[5]["evidence"].get(
                "fresh_reconnect_attempts"
            ) if isinstance(records[5].get("evidence"), dict) else None,
        },
        {
            "probe": lifecycle["redraw_boot"],
            "operator_observation": observations[1],
            "splash_framebuffer_reclamation": lifecycle[
                "splash_framebuffer_reclamation"
            ],
        },
        {
            "disable_persisted": lifecycle["disable_persisted"],
            "probe": lifecycle["final_disabled"],
        },
    )
    predecessor = record_sha256(binding)
    exact_keys = {
        "ordinal",
        "stage",
        "session_id",
        "candidate_firmware_sha256",
        "candidate_firmware_size_bytes",
        "predecessor_sha256",
        "evidence",
        "record_sha256",
    }
    for ordinal, (stage, expected, record) in enumerate(
            zip(LIFECYCLE_STAGE_NAMES, expected_evidence, records), 1):
        _exact_dict(record, exact_keys, "%s lifecycle record" % stage)
        if (
            type(record["ordinal"]) is not int
            or record["ordinal"] != ordinal
            or type(record["stage"]) is not str
            or record["stage"] != stage
            or record["session_id"] != binding["session_id"]
            or record["candidate_firmware_sha256"]
            != binding["candidate_firmware_sha256"]
            or type(record["candidate_firmware_size_bytes"]) is not int
            or record["candidate_firmware_size_bytes"]
            != binding["candidate_firmware_size_bytes"]
            or record["predecessor_sha256"] != predecessor
            or record["evidence"] != expected
        ):
            raise BenchError("%s lifecycle record changed" % stage)
        if "reboot" in stage:
            _validate_reboot_evidence(
                record["evidence"],
                "%s evidence" % stage,
                include_enable=(stage == "enable-reboot"),
            )
        digest = record["record_sha256"]
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise BenchError("%s lifecycle digest is invalid" % stage)
        unsigned = dict(record)
        unsigned.pop("record_sha256")
        if digest != record_sha256(unsigned):
            raise BenchError("%s lifecycle digest changed" % stage)
        predecessor = digest
    if (
        not isinstance(terminal_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", terminal_digest) is None
        or terminal_digest != predecessor
    ):
        raise BenchError("splash lifecycle terminal digest changed")


def validate_qualification_result(value):
    """Strictly validate one redacted, candidate-bound final result."""
    top_keys = {
        "schema_version",
        "status",
        "stage",
        "profile_id",
        "board_model",
        "firmware_version",
        "session_id",
        "candidate_firmware_sha256",
        "candidate_firmware_size_bytes",
        "binding",
        "candidate_verification",
        "qr",
        "lifecycle",
        "lifecycle_records",
        "terminal_record_sha256",
        "operator_observations",
        "connection_evidence",
        "record_sha256",
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
        or type(value["firmware_version"]) is not str
        or value["firmware_version"] != EXPECTED_FIRMWARE_VERSION
    ):
        raise BenchError("qualification identity changed")
    session_id = tft._validate_session_id(value["session_id"])
    candidate_sha256 = tft._validate_candidate_sha256(
        value["candidate_firmware_sha256"]
    )
    candidate_size = tft._validate_candidate_size(
        value["candidate_firmware_size_bytes"]
    )
    binding = _exact_dict(
        value["binding"],
        {
            "session_id",
            "candidate_firmware_sha256",
            "candidate_firmware_size_bytes",
            "candidate_attestation",
        },
        "candidate/session binding",
    )
    attestation = tft._validate_candidate_attestation(
        binding["candidate_attestation"],
        candidate_size,
    )
    if (
        binding["session_id"] != session_id
        or binding["candidate_firmware_sha256"] != candidate_sha256
        or type(binding["candidate_firmware_size_bytes"]) is not int
        or binding["candidate_firmware_size_bytes"] != candidate_size
    ):
        raise BenchError("candidate/session binding changed")
    runtime_identity = tft._validate_candidate_stage(
        value["candidate_verification"],
        attestation,
    )
    if runtime_identity[1] != EXPECTED_FIRMWARE_VERSION:
        raise BenchError("candidate runtime version changed")

    expected_qr = {
        "url": QR_URL,
        "version": QR_VERSION,
        "ecc": QR_ECC,
        "mask": QR_MASK,
        "size": QR_SIZE,
        "matrix_sha256": QR_MATRIX_SHA256,
        "pattern_id": SPLASH_PATTERN_ID,
    }
    qr = _exact_dict(value["qr"], set(expected_qr), "QR evidence")
    if (
        any(
            type(qr[key]) is not str
            for key in ("url", "ecc", "matrix_sha256", "pattern_id")
        )
        or any(type(qr[key]) is not int for key in ("version", "mask", "size"))
        or qr != expected_qr
    ):
        raise BenchError("QR evidence changed")

    lifecycle = _exact_dict(
        value["lifecycle"],
        {
            "disabled_soft_reboot_acknowledged",
            "disabled_old_connection_closed",
            "initial_disabled",
            "enable_persisted",
            "first_soft_reboot_acknowledged",
            "first_old_connection_closed",
            "enabled_boot",
            "resource_reuse",
            "splash_framebuffer_reclamation",
            "second_soft_reboot_acknowledged",
            "second_old_connection_closed",
            "redraw_boot",
            "disable_persisted",
            "final_disabled",
        },
        "splash lifecycle",
    )
    _validate_probe_record(lifecycle["initial_disabled"], "initial-disabled", False)
    _validate_probe_record(lifecycle["enabled_boot"], "enabled-boot", True)
    _validate_reuse_record(lifecycle["resource_reuse"])
    _validate_probe_record(lifecycle["redraw_boot"], "redraw-boot", True)
    _validate_probe_record(lifecycle["final_disabled"], "final-disabled", False)
    _validate_splash_reclamation(
        lifecycle["splash_framebuffer_reclamation"],
        lifecycle["initial_disabled"],
        lifecycle["enabled_boot"],
        lifecycle["redraw_boot"],
    )
    for key in (
        "disabled_soft_reboot_acknowledged",
        "disabled_old_connection_closed",
        "enable_persisted",
        "first_soft_reboot_acknowledged",
        "first_old_connection_closed",
        "second_soft_reboot_acknowledged",
        "second_old_connection_closed",
        "disable_persisted",
    ):
        if lifecycle[key] is not True:
            raise BenchError("%s proof changed" % key)

    observations = value["operator_observations"]
    if not isinstance(observations, list) or len(observations) != 2:
        raise BenchError("qualification requires exactly two operator scans")
    expected_phases = ("enabled-boot", "redraw-boot")
    for phase, observation in zip(expected_phases, observations):
        validate_operator_observation(observation)
        if observation["phase"] != phase:
            raise BenchError("operator scan phase order changed")

    _validate_lifecycle_chain(
        value["lifecycle_records"],
        value["terminal_record_sha256"],
        binding,
        lifecycle,
        observations,
    )

    connection = _exact_dict(
        value["connection_evidence"],
        {"fresh_reconnects", "hello_while_splash_visible"},
        "connection evidence",
    )
    if (
        type(connection["fresh_reconnects"]) is not int
        or connection["fresh_reconnects"] != 3
        or not isinstance(connection["hello_while_splash_visible"], list)
        or any(
            type(item) is not str
            for item in connection["hello_while_splash_visible"]
        )
        or connection["hello_while_splash_visible"]
        != ["enabled-boot", "redraw-boot"]
    ):
        raise BenchError("fresh HELLO evidence changed")

    digest = value["record_sha256"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise BenchError("qualification record digest is invalid")
    unsigned = dict(value)
    unsigned.pop("record_sha256")
    if digest != record_sha256(unsigned):
        raise BenchError("qualification record digest changed")

    encoded = canonical_json_bytes(value)
    for forbidden in (
        b"private-input-only",
        b"personal-device-id",
        b"personal-label",
        b"ble_address",
        b"device_id",
        b"raw_info",
        b"stdout_chunks",
        VM_SENTINEL.encode("ascii"),
    ):
        if forbidden in encoded:
            raise BenchError("qualification evidence contains private/raw data")
    return value


def write_result_exclusive(path, result):
    """Validate and create one canonical private result with mode 0600."""
    validate_qualification_result(result)
    payload = canonical_json_bytes(result)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(str(target), flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            target.unlink()
        except OSError:
            pass
        raise
    return payload


def _combined_run_summary(run, label):
    summary = {
        "stdout_bytes": run.get("stdout_bytes"),
        "stdout_marker_bytes": run.get("stdout_marker_bytes"),
        "stderr_bytes": run.get("stderr_bytes"),
        "state_sequence": run.get("state_sequence"),
    }
    if (
        type(summary["stdout_bytes"]) is not int
        or summary["stdout_bytes"] <= 0
        or type(summary["stdout_marker_bytes"]) is not int
        or summary["stdout_marker_bytes"] <= 0
        or type(summary["stderr_bytes"]) is not int
        or summary["stderr_bytes"] != 0
        or summary["state_sequence"] != ["running", "done"]
    ):
        raise BenchError("%s did not retain a sanitized marker RUN summary" % label)
    return summary


def _detach_extended_stage(stage, label):
    if not isinstance(stage, dict) or not isinstance(stage.get("run"), dict):
        raise BenchError("%s stage result is invalid" % label)
    clean = dict(stage)
    clean_run = dict(stage["run"])
    summary = _combined_run_summary(clean_run, "%s run" % label)
    clean_run.pop("stdout_marker_bytes", None)
    clean["run"] = clean_run
    return clean, summary


async def _combined_run_source(
        central,
        command_ids,
        caps,
        source,
        *,
        timeout_s,
        poll_interval_s,
        stale_vm_marker=None):
    run = await tft._collect_run(
        central,
        command_ids,
        source,
        hello_caps=caps,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
        probe_responsiveness=False,
        stale_vm_marker=stale_vm_marker,
        include_marker_bytes=True,
        marker_prefixes=(tft.MARKER_PREFIX, MARKER_PREFIX, "__PYBLE_SPLASH_V2_"),
    )
    chunks = run.pop("stdout_chunks")
    run.pop("info_reads")
    run.pop("device_info_commands")
    run.pop("responsive_refresh_indexes")
    return chunks, _combined_run_summary(run, "combined board action")


async def _combined_action(
        central,
        command_ids,
        caps,
        source,
        parser,
        *,
        timeout_s,
        poll_interval_s):
    chunks, run = await _combined_run_source(
        central,
        command_ids,
        caps,
        source,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
    )
    return parser(chunks), run


async def _combined_boot_probe(
        central,
        command_ids,
        caps,
        phase,
        enabled,
        *,
        timeout_s,
        poll_interval_s):
    chunks, run = await _combined_run_source(
        central,
        command_ids,
        caps,
        build_combined_boot_probe_source(phase, enabled),
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
        stale_vm_marker=STALE_VM_MARKER,
    )
    return {
        "probe": parse_combined_boot_probe_evidence(
            chunks,
            phase,
            expected_enabled=enabled,
        ),
        "run": run,
    }


async def _await_callback(callback, *args):
    value = callback(*args)
    if inspect.isawaitable(value):
        value = await value
    return value


def _combined_splash_observation(central, phase, scanned):
    if phase not in ("setup-enabled", "cycle-1"):
        raise BenchError("combined splash observation phase changed")
    if not tft._central_connected(central):
        raise BenchError("splash central disconnected during observation")
    observation = {
        "phase": phase,
        "confirmed": type(scanned) is str and scanned == QR_URL,
        "pattern_id": SPLASH_PATTERN_ID,
        "scanned_url": scanned if type(scanned) is str else "",
        "before_first_hello": True,
        "connected_central": True,
    }
    if observation["confirmed"] is not True:
        raise BenchError("operator did not scan the exact physical splash QR")
    return observation


async def _fresh_combined_connection(
        connect,
        address,
        expected_runtime,
        phase,
        enabled,
        *,
        deadline,
        poll_interval_s,
        sleep,
        clock,
        confirm_splash,
        operator_timeout_s,
        cleanup_reserve_s):
    await tft._sleep_with_deadline(
        sleep,
        REBOOT_DELIVERY_GRACE_S,
        deadline,
        clock,
        "%s delivery grace" % phase,
    )
    attempts = 0
    operator_remaining_s = operator_timeout_s
    while True:
        tft._deadline_remaining(deadline, clock, "%s reconnect" % phase)
        attempts += 1
        try:
            central = await tft._connect_with_deadline(
                connect,
                address,
                deadline,
                clock,
                phase,
            )
        except PbleConnectError:
            await tft._sleep_with_deadline(
                sleep,
                RECONNECT_POLL_S,
                deadline,
                clock,
                "%s reconnect delay" % phase,
            )
            continue

        command_ids = CommandIds()
        observation = None
        try:
            if enabled:
                if not tft._central_connected(central):
                    raise BenchError(
                        "splash central was not connected before observation"
                    )
                device_remaining_s = tft._deadline_remaining(
                    deadline,
                    clock,
                    "%s physical observation" % phase,
                )
                if device_remaining_s <= cleanup_reserve_s:
                    raise BenchError(
                        "%s operator callback left no cleanup budget" % phase
                    )
                if operator_remaining_s <= 0:
                    raise BenchError("%s operator confirmation timed out" % phase)
                callback_started = clock()
                try:
                    scanned = await tft._await_operator_callback(
                        confirm_splash,
                        phase,
                        SPLASH_PATTERN_ID,
                        QR_URL,
                        timeout_s=operator_remaining_s,
                        label="%s operator confirmation" % phase,
                    )
                finally:
                    callback_elapsed_s = max(0.0, clock() - callback_started)
                    deadline += callback_elapsed_s
                    operator_remaining_s -= callback_elapsed_s
                if operator_remaining_s <= 0:
                    raise BenchError("%s operator confirmation timed out" % phase)
                observation = _combined_splash_observation(
                    central,
                    phase,
                    scanned,
                )
            caps = await tft._await_with_deadline(
                lambda remaining: _hello(central, command_ids, remaining),
                deadline,
                clock,
                "%s HELLO" % phase,
            )
            _require_runtime_identity(caps, expected_runtime)
            post_reboot = await tft._await_with_deadline(
                lambda remaining: _combined_boot_probe(
                    central,
                    command_ids,
                    caps,
                    phase,
                    enabled,
                    timeout_s=remaining,
                    poll_interval_s=poll_interval_s,
                ),
                deadline,
                clock,
                "%s exact boot probe" % phase,
            )
        except BaseException as error:
            retry = isinstance(error, tft.StaleVmEpochError)
            if isinstance(error, PbleLinkLossError):
                retry = not tft._central_connected(central)
            await _close_rejected_connection(
                central,
                deadline,
                clock,
                "%s rejected" % phase,
                error,
            )
            if not retry:
                raise error
            await tft._sleep_with_deadline(
                sleep,
                RECONNECT_POLL_S,
                deadline,
                clock,
                "%s stale transition delay" % phase,
            )
            continue
        tft._deadline_remaining(deadline, clock, "%s fresh-VM proof" % phase)
        return central, command_ids, caps, post_reboot, observation, attempts


async def _combined_reboot_transition(
        connect,
        address,
        central,
        command_ids,
        expected_runtime,
        phase,
        enabled,
        *,
        timeout_s,
        poll_interval_s,
        sleep,
        clock,
        confirm_splash,
        operator_timeout_s):
    deadline = clock() + timeout_s
    acknowledged = await tft._await_with_deadline(
        lambda remaining: _soft_reboot(
            central,
            command_ids,
            timeout_s=remaining,
        ),
        deadline,
        clock,
        "%s SOFT_REBOOT" % phase,
    )
    old_connection_closed = await tft._close_connection(
        central,
        deadline,
        clock,
        "%s old link" % phase,
    )
    fresh = await _fresh_combined_connection(
        connect,
        address,
        expected_runtime,
        phase,
        enabled,
        deadline=deadline,
        poll_interval_s=poll_interval_s,
        sleep=sleep,
        clock=clock,
        confirm_splash=confirm_splash,
        operator_timeout_s=operator_timeout_s,
        cleanup_reserve_s=min(
            tft.OPERATOR_CLEANUP_RESERVE_S,
            timeout_s / 4.0,
        ),
    )
    return acknowledged, old_connection_closed, fresh


def _combined_record(binding, ordinal, stage, predecessor, fields):
    record = {
        "ordinal": ordinal,
        "stage": stage,
        "session_id": binding["session_id"],
        "candidate_firmware_sha256": binding["candidate_firmware_sha256"],
        "candidate_firmware_size_bytes": binding[
            "candidate_firmware_size_bytes"
        ],
        "candidate_attestation": binding["candidate_attestation"],
        "predecessor_sha256": predecessor,
    }
    record.update(fields)
    record["record_sha256"] = record_sha256(record)
    return record


def _action_record(persisted, run, *, darkened=False, armed=False):
    value = {"persisted": persisted is True, "run": run}
    if darkened:
        value["darkened"] = True
    if armed:
        value["armed"] = True
    return value


async def run_combined_qualification(
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
        production_app_probe=None,
        confirm_splash=None,
        confirm_tft=None,
        operator_timeout_s=DEFAULT_OPERATOR_TIMEOUT_S,
        session_id=None):
    """Run one website-bound, five-reset splash/TFT qualification."""
    preflight = tft.validate_preflight(preflight)
    candidate_firmware_sha256 = tft._validate_candidate_sha256(
        candidate_firmware_sha256
    )
    candidate_firmware_size_bytes = tft._validate_candidate_size(
        candidate_firmware_size_bytes
    )
    candidate_attestation = tft._validate_candidate_attestation(
        candidate_attestation,
        candidate_firmware_size_bytes,
    )
    if (
        not isinstance(timeout_s, (int, float))
        or isinstance(timeout_s, bool)
        or timeout_s <= REBOOT_DELIVERY_GRACE_S
        or timeout_s > 120
    ):
        raise BenchError("combined timeout must be in (0.25, 120] seconds")
    if (
        not isinstance(poll_interval_s, (int, float))
        or isinstance(poll_interval_s, bool)
        or poll_interval_s < 0
    ):
        raise BenchError("combined poll interval must be non-negative")
    if not callable(sleep) or not callable(clock):
        raise BenchError("combined clock and sleep must be callable")
    operator_timeout_s = tft._validate_operator_timeout(operator_timeout_s)
    if not callable(production_app_probe):
        raise BenchError("combined qualification requires production app evidence")
    if not callable(confirm_splash) or not callable(confirm_tft):
        raise BenchError("combined qualification requires both operator callbacks")
    if session_id is None:
        session_id = secrets.token_hex(16)
    session_id = tft._validate_session_id(session_id)

    # This mandatory route proof is deliberately completed and validated before
    # the first BLE connection or any board mutation.
    app_evidence = await _await_callback(production_app_probe)
    app_evidence = production_app.validate_production_app_evidence(app_evidence)
    binding = {
        "session_id": session_id,
        "candidate_firmware_sha256": candidate_firmware_sha256,
        "candidate_firmware_size_bytes": candidate_firmware_size_bytes,
        "candidate_attestation": candidate_attestation,
        "production_app_evidence": app_evidence,
    }
    central = None
    command_ids = None
    caps = None
    cleanup_armed = False
    try:
        initial_deadline = clock() + timeout_s
        central = await tft._connect_with_deadline(
            connect,
            address,
            initial_deadline,
            clock,
            "combined candidate",
        )
        command_ids = CommandIds()
        caps = await tft._await_with_deadline(
            lambda remaining: _hello(central, command_ids, remaining),
            initial_deadline,
            clock,
            "combined candidate HELLO",
        )
        candidate_stage = await tft._await_with_deadline(
            lambda remaining: tft.run_candidate_verification(
                central,
                preflight,
                candidate_firmware_sha256,
                candidate_firmware_size_bytes,
                candidate_attestation,
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
                include_marker_summary=True,
                command_ids=command_ids,
                hello_caps=caps,
            ),
            initial_deadline,
            clock,
            "live candidate verification",
        )
        expected_runtime = _runtime_identity(caps)
        candidate_stage, candidate_run = _detach_extended_stage(
            candidate_stage,
            "candidate verification",
        )

        disabled, disabled_run = await tft._await_with_deadline(
            lambda remaining: _combined_action(
                central,
                command_ids,
                caps,
                build_disable_source(),
                _parse_disable,
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
            ),
            initial_deadline,
            clock,
            "initial disable/darken",
        )
        cleanup_armed = True
        setup_disabled_disable = _action_record(
            disabled,
            disabled_run,
            darkened=True,
        )
        armed, armed_run = await tft._await_with_deadline(
            lambda remaining: _combined_action(
                central,
                command_ids,
                caps,
                build_reboot_arm_source(),
                _parse_reboot_arm,
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
            ),
            initial_deadline,
            clock,
            "setup-disabled reboot arm",
        )
        setup_disabled_arm = _action_record(armed, armed_run, armed=True)
        disabled_reset, disabled_closed, fresh = await _combined_reboot_transition(
            connect,
            address,
            central,
            command_ids,
            expected_runtime,
            "setup-disabled",
            False,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            sleep=sleep,
            clock=clock,
            confirm_splash=confirm_splash,
            operator_timeout_s=operator_timeout_s,
        )
        (
            central,
            command_ids,
            caps,
            setup_disabled_post,
            disabled_observation,
            disabled_attempts,
        ) = fresh
        if disabled_observation is not None:
            raise BenchError("disabled setup unexpectedly produced visual evidence")

        enabled_deadline = clock() + timeout_s
        enabled, enabled_run = await tft._await_with_deadline(
            lambda remaining: _combined_action(
                central,
                command_ids,
                caps,
                build_enable_source(),
                _parse_enable,
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
            ),
            enabled_deadline,
            clock,
            "setup enable/arm",
        )
        setup_enable_action = _action_record(enabled, enabled_run)
        setup_enabled_armed, setup_enabled_arm_run = await tft._await_with_deadline(
            lambda remaining: _combined_action(
                central,
                command_ids,
                caps,
                build_reboot_arm_source(),
                _parse_reboot_arm,
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
            ),
            enabled_deadline,
            clock,
            "setup-enabled reboot arm",
        )
        setup_enabled_arm = _action_record(
            setup_enabled_armed,
            setup_enabled_arm_run,
            armed=True,
        )
        enabled_reset, enabled_closed, fresh = await _combined_reboot_transition(
            connect,
            address,
            central,
            command_ids,
            expected_runtime,
            "setup-enabled",
            True,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            sleep=sleep,
            clock=clock,
            confirm_splash=confirm_splash,
            operator_timeout_s=operator_timeout_s,
        )
        (
            central,
            command_ids,
            caps,
            setup_enabled_post,
            setup_enabled_observation,
            enabled_attempts,
        ) = fresh

        exercise_stage = await tft.run_exercise(
            central,
            preflight,
            timeout_s=timeout_s,
            operator_timeout_s=operator_timeout_s,
            poll_interval_s=poll_interval_s,
            confirm_visual_during_run=confirm_tft,
            command_ids=command_ids,
            hello_caps=caps,
        )
        exercise_observation = exercise_stage.pop("operator_observation", None)
        exercise_stage, exercise_run = _detach_extended_stage(
            exercise_stage,
            "TFT exercise",
        )

        cycle1_arm_deadline = clock() + timeout_s
        cycle1_armed, cycle1_arm_run = await tft._await_with_deadline(
            lambda remaining: _combined_action(
                central,
                command_ids,
                caps,
                build_reboot_arm_source(),
                _parse_reboot_arm,
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
            ),
            cycle1_arm_deadline,
            clock,
            "cycle 1 reboot arm",
        )
        cycle1_reset, cycle1_closed, fresh = await _combined_reboot_transition(
            connect,
            address,
            central,
            command_ids,
            expected_runtime,
            "cycle-1",
            True,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            sleep=sleep,
            clock=clock,
            confirm_splash=confirm_splash,
            operator_timeout_s=operator_timeout_s,
        )
        (
            central,
            command_ids,
            caps,
            cycle1_post,
            cycle1_observation,
            cycle1_attempts,
        ) = fresh

        cycle1_deadline = clock() + timeout_s
        final_disabled, final_disabled_run = await tft._await_with_deadline(
            lambda remaining: _combined_action(
                central,
                command_ids,
                caps,
                build_disable_source(),
                _parse_disable,
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
            ),
            cycle1_deadline,
            clock,
            "cycle 1 final disable/darken",
        )
        cycle1_final_disable = _action_record(
            final_disabled,
            final_disabled_run,
            darkened=True,
        )
        cycle2_armed, cycle2_arm_run = await tft._await_with_deadline(
            lambda remaining: _combined_action(
                central,
                command_ids,
                caps,
                build_reboot_arm_source(),
                _parse_reboot_arm,
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
            ),
            cycle1_deadline,
            clock,
            "cycle 2 reboot arm",
        )
        cycle2_reset, cycle2_closed, fresh = await _combined_reboot_transition(
            connect,
            address,
            central,
            command_ids,
            expected_runtime,
            "cycle-2",
            False,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            sleep=sleep,
            clock=clock,
            confirm_splash=confirm_splash,
            operator_timeout_s=operator_timeout_s,
        )
        (
            central,
            command_ids,
            caps,
            cycle2_post,
            cycle2_observation,
            cycle2_attempts,
        ) = fresh
        if cycle2_observation is not None:
            raise BenchError("disabled cycle 2 unexpectedly produced visual evidence")

        cycle2_deadline = clock() + timeout_s
        cycle3_armed, cycle3_arm_run = await tft._await_with_deadline(
            lambda remaining: _combined_action(
                central,
                command_ids,
                caps,
                build_reboot_arm_source(),
                _parse_reboot_arm,
                timeout_s=remaining,
                poll_interval_s=poll_interval_s,
            ),
            cycle2_deadline,
            clock,
            "cycle 3 reboot arm",
        )
        cycle3_reset, cycle3_closed, fresh = await _combined_reboot_transition(
            connect,
            address,
            central,
            command_ids,
            expected_runtime,
            "cycle-3",
            False,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            sleep=sleep,
            clock=clock,
            confirm_splash=confirm_splash,
            operator_timeout_s=operator_timeout_s,
        )
        (
            central,
            command_ids,
            caps,
            cycle3_post,
            cycle3_observation,
            cycle3_attempts,
        ) = fresh
        if cycle3_observation is not None:
            raise BenchError("disabled cycle 3 unexpectedly produced visual evidence")
        final_deadline = clock() + timeout_s
        await tft._close_connection(
            central,
            final_deadline,
            clock,
            "combined final disabled link",
        )
        central = None
        cleanup_armed = False
    except BaseException as original:
        cleanup_error = None
        try:
            if cleanup_armed:
                cleanup_error = await _best_effort_disable(
                    connect,
                    address,
                    central,
                    command_ids,
                    caps,
                    timeout_s=timeout_s,
                    poll_interval_s=poll_interval_s,
                    clock=clock,
                )
            elif central is not None and tft._central_connected(central):
                await tft._close_connection(
                    central,
                    clock() + timeout_s,
                    clock,
                    "failed combined qualification",
                )
        except BaseException as caught:
            cleanup_error = caught
        if isinstance(original, _PROCESS_CONTROL_EXCEPTIONS):
            raise original
        if isinstance(cleanup_error, _PROCESS_CONTROL_EXCEPTIONS):
            raise cleanup_error from original
        raise

    records = []
    predecessor = record_sha256(binding)
    candidate_record = _combined_record(
        binding,
        1,
        "candidate-verification",
        predecessor,
        {"stage_result": candidate_stage, "run_summary": candidate_run},
    )
    records.append(candidate_record)
    predecessor = candidate_record["record_sha256"]
    setup_disabled_record = _combined_record(
        binding,
        2,
        "setup-disabled",
        predecessor,
        {
            "pre_reboot": {
                "disable": setup_disabled_disable,
                "arm": setup_disabled_arm,
            },
            "soft_reboot_acknowledged": disabled_reset,
            "old_connection_closed": disabled_closed,
            "reconnect_attempts": disabled_attempts,
            "post_reboot": setup_disabled_post,
            "operator_observation": None,
        },
    )
    records.append(setup_disabled_record)
    predecessor = setup_disabled_record["record_sha256"]
    setup_enabled_record = _combined_record(
        binding,
        3,
        "setup-enabled",
        predecessor,
        {
            "pre_reboot": {
                "enable": setup_enable_action,
                "arm": setup_enabled_arm,
            },
            "soft_reboot_acknowledged": enabled_reset,
            "old_connection_closed": enabled_closed,
            "reconnect_attempts": enabled_attempts,
            "post_reboot": setup_enabled_post,
            "operator_observation": setup_enabled_observation,
        },
    )
    records.append(setup_enabled_record)
    predecessor = setup_enabled_record["record_sha256"]
    exercise_record = _combined_record(
        binding,
        4,
        "exercise",
        predecessor,
        {
            "stage_result": exercise_stage,
            "run_summary": exercise_run,
            "operator_observation": exercise_observation,
        },
    )
    records.append(exercise_record)
    predecessor = exercise_record["record_sha256"]

    cycle_fields = (
        {
            "cycle": 1,
            "pre_reboot": {
                "arm": _action_record(
                    cycle1_armed,
                    cycle1_arm_run,
                    armed=True,
                )
            },
            "soft_reboot_acknowledged": cycle1_reset,
            "old_connection_closed": cycle1_closed,
            "reconnect_attempts": cycle1_attempts,
            "post_reboot": cycle1_post,
            "operator_observation": cycle1_observation,
            "final_disable": cycle1_final_disable,
        },
        {
            "cycle": 2,
            "pre_reboot": {
                "arm": _action_record(
                    cycle2_armed,
                    cycle2_arm_run,
                    armed=True,
                )
            },
            "soft_reboot_acknowledged": cycle2_reset,
            "old_connection_closed": cycle2_closed,
            "reconnect_attempts": cycle2_attempts,
            "post_reboot": cycle2_post,
            "operator_observation": None,
            "final_disable": None,
        },
        {
            "cycle": 3,
            "pre_reboot": {
                "arm": _action_record(
                    cycle3_armed,
                    cycle3_arm_run,
                    armed=True,
                )
            },
            "soft_reboot_acknowledged": cycle3_reset,
            "old_connection_closed": cycle3_closed,
            "reconnect_attempts": cycle3_attempts,
            "post_reboot": cycle3_post,
            "operator_observation": None,
            "final_disable": None,
        },
    )
    cycles = []
    for index, fields in enumerate(cycle_fields, 1):
        cycle = _combined_record(
            binding,
            index + 4,
            "cycle-%d" % index,
            predecessor,
            fields,
        )
        records.append(cycle)
        cycles.append(cycle)
        predecessor = cycle["record_sha256"]

    resource_reclamation = _splash_reclamation_proof(
        setup_disabled_post["probe"],
        setup_enabled_post["probe"],
        cycle1_post["probe"],
    )
    qualification = {
        "acknowledged_resets": 5,
        "ble_segments": 6,
        "setup_resets": 2,
        "tft_exercises": 1,
        "tft_reboot_cycles": 3,
        "fresh_vm_proofs": 5,
        "operator_splash_observations": 2,
        "terminal_record_sha256": predecessor,
    }
    result = {
        "schema_version": COMBINED_SCHEMA_VERSION,
        "status": "passed",
        "stage": "combined-qualification",
        "profile_id": PROFILE_ID,
        "board_model": BOARD_MODEL,
        "firmware_version": EXPECTED_FIRMWARE_VERSION,
        "session_id": session_id,
        "candidate_firmware_sha256": candidate_firmware_sha256,
        "candidate_firmware_size_bytes": candidate_firmware_size_bytes,
        "candidate_attestation": candidate_attestation,
        "production_app_evidence": app_evidence,
        "binding": binding,
        "records": records,
        "setup": {
            "disabled": setup_disabled_record,
            "enabled": setup_enabled_record,
        },
        "exercise": exercise_record,
        "cycles": cycles,
        "resource_reclamation": resource_reclamation,
        "qualification": qualification,
        "terminal_record_sha256": predecessor,
    }
    result["record_sha256"] = record_sha256(result)
    return validate_combined_qualification_result(result)


def validate_combined_qualification_result(value):
    """Delegate successful evidence admission to the release-shared boundary."""

    try:
        return qualification_gate.validate_combined_qualification_result(
            value,
            EXPECTED_FIRMWARE_VERSION,
        )
    except qualification_gate.QualificationError as exc:
        raise BenchError(str(exc)) from exc


def write_combined_result_exclusive(path, result):
    """Create one validated canonical combined result with private mode 0600."""
    validate_combined_qualification_result(result)
    payload = qualification_gate.canonical_json_bytes(result)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(str(target), flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            target.unlink()
        except OSError:
            pass
        raise
    return payload


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Combined production-app, splash, and TFT HIL qualification"
    )
    parser.add_argument(
        "--address",
        required=True,
        help="BLE UUID/MAC input; never written to qualification evidence",
    )
    parser.add_argument("--preflight", required=True, type=Path)
    parser.add_argument("--firmware-bin", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--operator-timeout",
        type=float,
        default=DEFAULT_OPERATOR_TIMEOUT_S,
    )
    return parser.parse_args(argv)


async def _prompt_visual_confirmation(phase, pattern_id, qr_url):
    sys.stderr.write(
        "Inspect the physical %s frame (%s). Confirm PyBLE, BLE READY, "
        "Firmware v%s, and the complete QR are visibly correct. "
        "Type VISIBLE to continue: "
        % (phase, pattern_id, EXPECTED_FIRMWARE_VERSION)
    )
    sys.stderr.flush()
    visible = await tft._read_stdin_line()
    if visible is None:
        return None
    if visible.strip() != "VISIBLE":
        return None
    sys.stderr.write(
        "Scan the physical QR with an independent device and paste the exact "
        "URL (expected %s): " % qr_url
    )
    sys.stderr.flush()
    scanned = await tft._read_stdin_line()
    if scanned is None:
        return None
    return scanned.strip()


async def _run_cli(args):
    preflight = tft.load_preflight(args.preflight)
    firmware_path = getattr(args, "firmware_bin", None)
    if firmware_path is None:
        firmware_path = getattr(args, "firmware", None)
    candidate = tft.inspect_candidate_firmware(firmware_path)
    result = await run_combined_qualification(
        PbleCentral.connect,
        args.address,
        preflight,
        candidate["sha256"],
        candidate["size_bytes"],
        candidate["attestation"],
        timeout_s=args.timeout,
        operator_timeout_s=args.operator_timeout,
        production_app_probe=production_app.collect_production_app_evidence,
        confirm_splash=_prompt_visual_confirmation,
        confirm_tft=tft._prompt_visual_confirmation,
    )
    write_combined_result_exclusive(args.output, result)
    return None


def main(argv=None):
    args = _parse_args(argv)
    try:
        asyncio.run(_run_cli(args))
    except BenchError as exc:
        print("Splash HIL failed: %s" % exc, file=sys.stderr)
        return 2
    except FileExistsError:
        print("Splash HIL failed: output already exists", file=sys.stderr)
        return 2
    except Exception as exc:  # BLE backend errors may contain private addresses.
        print(
            "Splash HIL failed in local backend (%s)" % type(exc).__name__,
            file=sys.stderr,
        )
        return 2
    print("Combined HIL evidence written successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
