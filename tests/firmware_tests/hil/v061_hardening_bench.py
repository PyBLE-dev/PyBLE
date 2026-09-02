#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Target-neutral physical HIL bench for firmware-v0.6.1 hardening.

The tool exercises only PBLE/1 behavior amended for v0.6.1.  It deliberately
does not claim that host-side checks, a different profile, or a different board
can fill a physical evidence row.  BLE addresses, device IDs, labels, console
payloads, and exception details never enter the bounded machine evidence.

The two pre-service workspace observations are supplied as separately captured
candidate-bound receipts.  Only after those receipts and all seven live
scenarios pass does this runner publish one exclusive private result.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import sys
import time

import _pble_bench as pble_bench
from _pble_central import PbleCentral, RX_UUID, rsp_status, status_name
import _pble_wire as wire
import target_smoke


ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = ROOT / "firmware" / "qualification" / "oi1-gates.json"
QUALIFICATION_DIR = ROOT / "firmware" / "qualification"
if str(QUALIFICATION_DIR) not in sys.path:
    sys.path.insert(0, str(QUALIFICATION_DIR))
import v061_hardening_release_gate as hardening_gate  # noqa: E402

PROFILE_ORDER = tuple(pble_bench.PROFILE_ORDER)
PROFILE_CHIPS = dict(pble_bench.PROFILE_CHIPS)
PROFILE_BOARD_IDENTITIES = {
    "esp32-4mb": {
        "board_manufacturer": "Espressif Systems",
        "board_model": "Electronically identified ESP32 development board",
        "module_marking": "ESP32-D0WD revision v1.0 (esptool)",
    },
    "esp32-s3-n16r8": {
        "board_manufacturer": "Espressif Systems",
        "board_model": "Electronically identified ESP32-S3 development board",
        "module_marking": "ESP32-S3 QFN56 revision v0.1 (esptool)",
    },
    "waveshare-esp32-s3-lcd-147b": {
        "board_manufacturer": "Waveshare",
        "board_model": "ESP32-S3-LCD-1.47B",
        "module_marking": "ESP32-S3R8",
    },
    "esp32-c3-4mb": {
        "board_manufacturer": "Espressif Systems",
        "board_model": "Electronically identified ESP32-C3 development board",
        "module_marking": "ESP32-C3 QFN32 revision v0.4 (esptool)",
    },
    "rpi-pico2-w": {
        "board_manufacturer": "Raspberry Pi Ltd",
        "board_model": "Raspberry Pi Pico 2 W",
        "module_marking": "RP2350 + CYW43439",
    },
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

HELLO_PAYLOAD = (
    b"proto_versions=1\n"
    b"app_name=v061-hardening\n"
    b"app_version=0"
)
UNSUPPORTED_HELLO_PAYLOAD = (
    b"proto_versions=2\n"
    b"app_name=v061-hardening\n"
    b"app_version=0"
)

REASSEMBLY_DEADLINE_S = 5.0
MALFORMED_BUDGET = 8
QUIET_S = 0.35
EVENT_TIMEOUT_S = 12.0
CONNECT_TIMEOUT_S = 25.0
RECONNECT_RETRY_S = 35.0
SEQUENTIAL_RUNS = 50
CAPACITY_RESERVE = 65536
STDIN_OVERFLOW_BYTES = 400
LABEL_24 = "ทดสอบไทย"

ST_IDLE = 0
ST_RUNNING = 1
ST_DONE = 2
ST_ERROR = 3

WORK_DIR = "/v061_hil"
SOURCE_FILE_ONE = WORK_DIR + "/fresh_one.py"
SOURCE_FILE_TWO = WORK_DIR + "/fresh_two.py"
FS_SENTINEL_PATH = WORK_DIR + "/old_target.bin"
FS_RENAME_PATH = WORK_DIR + "/renamed.bin"
FS_BLOCKED_DIR = WORK_DIR + "/blocked_dir"
FS_CAPACITY_PATH = WORK_DIR + "/capacity.bin"

SOURCE_SET_MARKER = b"__PYBLE_V061_SOURCE_SET__"
SOURCE_FRESH_MARKER = b"__PYBLE_V061_fresh-source__=1"
FILE_SET_MARKER = b"__PYBLE_V061_FILE_SET__"
FILE_FRESH_MARKER = b"__PYBLE_V061_fresh-file__=1"
STATVFS_MARKER = b"__PYBLE_V061_STATVFS__="


class BenchFailure(RuntimeError):
    """A deterministic, operator-safe physical-check failure."""


class LiveState:
    def __init__(self, args):
        self.args = args
        self.ids = pble_bench.CommandIds()
        self.central = None
        self.caps = {}


def _require(condition, message):
    if not condition:
        raise BenchFailure(message)


def _status_is(response, expected, operation):
    actual = rsp_status(response)
    if actual != expected:
        raise BenchFailure(
            "%s returned %s, expected %s"
            % (operation, status_name(actual), status_name(expected))
        )
    return response


def _caps_from_hello(response, args):
    _status_is(response, wire.ST_OK, "HELLO")
    try:
        text = response.payload[1:].decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise BenchFailure("HELLO caps are not strict UTF-8") from exc
    caps = target_smoke.parse_caps(text)
    try:
        target_smoke.validate_caps(
            caps,
            PROFILE_CHIPS[args.profile],
            args.expect_agent,
        )
    except ValueError as exc:
        raise BenchFailure("HELLO caps failed the target contract") from exc
    return caps


async def _connect(state):
    deadline = time.monotonic() + RECONNECT_RETRY_S
    while True:
        try:
            state.central = await PbleCentral.connect(
                state.args.address,
                timeout=CONNECT_TIMEOUT_S,
            )
            return state.central
        except Exception as exc:
            if time.monotonic() >= deadline:
                raise BenchFailure("board did not accept a clean BLE connection") from exc
            await asyncio.sleep(0.25)


async def _disconnect(state):
    central = state.central
    state.central = None
    if central is None:
        return
    try:
        await central.disconnect()
    except Exception:
        # The adversarial budget and SOFT_REBOOT cases intentionally make the
        # peer close first.  A proven disconnected client needs no second fact.
        if central.is_connected:
            raise


async def _best_effort_stop(state):
    """Prevent a failed interactive check from leaving user code running."""
    central = state.central
    if central is None or not central.is_connected:
        return
    try:
        response = await central.send_cmd(
            wire.OP_STOP,
            state.ids.next(),
            timeout=2.0,
        )
        if rsp_status(response) == wire.ST_OK:
            await asyncio.sleep(0.05)
    except Exception:
        pass


async def _negotiate(state):
    response = await state.central.send_cmd(
        wire.OP_HELLO,
        state.ids.next(),
        HELLO_PAYLOAD,
    )
    caps = _caps_from_hello(response, state.args)
    try:
        state.central.confirm_caps_mtu(int(caps["mtu"]))
    except ValueError as exc:
        raise BenchFailure("HELLO and backend MTU evidence disagree") from exc
    state.caps = caps
    return caps


async def _reconnect_and_negotiate(state):
    await _disconnect(state)
    await _connect(state)
    return await _negotiate(state)


async def _wait_until(predicate, timeout_s, failure):
    deadline = time.monotonic() + timeout_s
    while True:
        if predicate():
            return
        if time.monotonic() >= deadline:
            raise BenchFailure(failure)
        await asyncio.sleep(0.02)


async def _wait_disconnected(central, timeout_s=EVENT_TIMEOUT_S):
    await _wait_until(
        lambda: not central.is_connected,
        timeout_s,
        "board did not terminate the exact malformed-input session",
    )


async def _wait_event(central, cursor, predicate, timeout_s, failure):
    deadline = time.monotonic() + timeout_s
    while True:
        next_cursor, events = central.events_since(cursor)
        for event in events:
            if predicate(event):
                return next_cursor, event
        cursor = next_cursor
        if time.monotonic() >= deadline:
            raise BenchFailure(failure)
        await asyncio.sleep(0.02)


def _events_after(central, cursor):
    _next, events = central.events_since(cursor)
    return list(events)


def _console_bytes(events, stream=0):
    return b"".join(
        event.payload[1:]
        for event in events
        if event.type == wire.EVT
        and event.opcode == wire.OP_CONSOLE_DATA
        and event.payload
        and event.payload[0] == stream
    )


def _states(events):
    return [
        event.payload[0]
        for event in events
        if event.type == wire.EVT
        and event.opcode == wire.OP_RUN_STATE
        and len(event.payload) == 1
    ]


async def _wait_program_terminal(central, cursor, timeout_s=EVENT_TIMEOUT_S):
    deadline = time.monotonic() + timeout_s
    while True:
        events = _events_after(central, cursor)
        terminal = [state for state in _states(events) if state in (ST_DONE, ST_ERROR)]
        if terminal:
            _require(len(terminal) == 1, "RUN emitted more than one terminal state")
            _require(terminal[0] == ST_DONE, "bounded RUN ended in error")
            return events
        if time.monotonic() >= deadline:
            raise BenchFailure("bounded RUN did not reach a terminal state")
        await asyncio.sleep(0.02)


async def _run_program(state, mode, data, description):
    central = state.central
    cursor = central.event_cursor()
    response = await central.send_cmd(
        wire.OP_RUN,
        state.ids.next(),
        bytes((mode,)) + bytes(data),
    )
    _status_is(response, wire.ST_OK, description + " RUN")
    events = await _wait_program_terminal(central, cursor)
    states = _states(events)
    _require(
        states == [ST_RUNNING, ST_DONE],
        description + " RUN did not emit exactly running then done",
    )
    _require(_console_bytes(events, 1) == b"", description + " emitted stderr")
    return _console_bytes(events, 0)


async def _wait_console_marker(central, cursor, marker, timeout_s=EVENT_TIMEOUT_S):
    deadline = time.monotonic() + timeout_s
    while True:
        events = _events_after(central, cursor)
        if marker in _console_bytes(events, 0):
            return events
        if ST_ERROR in _states(events) or ST_DONE in _states(events):
            raise BenchFailure("interactive RUN terminated before its prompt")
        if time.monotonic() >= deadline:
            raise BenchFailure("interactive RUN did not emit its prompt")
        await asyncio.sleep(0.02)


async def _assert_run_still_active(central, cursor, boundary):
    await asyncio.sleep(QUIET_S)
    states = _states(_events_after(central, cursor))
    _require(
        ST_DONE not in states and ST_ERROR not in states and ST_IDLE not in states,
        "%s bytes crossed into the successor RUN" % boundary,
    )


def _input_source(case, delay_ms=0):
    _require(re.fullmatch(r"[a-z-]{1,32}", case) is not None, "invalid input case")
    prompt = "__PYBLE_V061_STDIN_%s_PROMPT__" % case
    echo = "__PYBLE_V061_STDIN_%s_ECHO__=" % case
    delay = ""
    if delay_ms:
        delay = (
            "import time\n"
            "_v061_deadline=time.ticks_add(time.ticks_ms(),%d)\n"
            "while time.ticks_diff(_v061_deadline,time.ticks_ms())>0: pass\n"
            % int(delay_ms)
        )
    source = (
        "print(%r)\n"
        "%s"
        "_v061_value=input()\n"
        "print(%r+_v061_value)\n"
        % (prompt, delay, echo)
    ).encode("ascii")
    return source, prompt.encode("ascii"), echo.encode("ascii")


async def _start_input_run(state, case, delay_ms=0):
    source, prompt, echo = _input_source(case, delay_ms)
    cursor = state.central.event_cursor()
    response = await state.central.send_cmd(
        wire.OP_RUN,
        state.ids.next(),
        b"\x01" + source,
    )
    _status_is(response, wire.ST_OK, case + " stdin RUN")
    await _wait_console_marker(state.central, cursor, prompt)
    return cursor, echo


async def _finish_input_run(state, cursor, echo_prefix, value):
    await state.central.send_cmd_no_rsp(
        wire.OP_CONSOLE_INPUT,
        state.ids.next(),
        value + b"\n",
    )
    events = await _wait_program_terminal(state.central, cursor)
    stdout = _console_bytes(events, 0)
    _require(
        stdout.count(echo_prefix + value) == 1,
        "stdin successor did not consume exactly its fresh line",
    )
    _require(_console_bytes(events, 1) == b"", "stdin RUN emitted stderr")


def _put_begin_payload(path, data_size, checksum):
    return (
        int(data_size).to_bytes(4, "little")
        + int(checksum).to_bytes(4, "little")
        + pble_bench.path_payload(path)
    )


async def _begin_put(state, path, data_size, checksum, expected=wire.ST_OK):
    response = await state.central.send_cmd(
        wire.OP_FILE_PUT_BEGIN,
        state.ids.next(),
        _put_begin_payload(path, data_size, checksum),
    )
    _status_is(response, expected, "FILE_PUT_BEGIN")
    if expected != wire.ST_OK:
        return None
    _require(len(response.payload) == 5, "FILE_PUT_BEGIN omitted resume_offset")
    return int.from_bytes(response.payload[1:5], "little")


async def _send_put_piece(state, scope, offset, piece, total, valid_offsets):
    await state.central.send_cmd_no_rsp(
        wire.OP_FILE_PUT_DATA,
        state.ids.next(),
        int(offset).to_bytes(4, "little") + bytes(piece),
    )
    wanted = offset + len(piece)
    deadline = time.monotonic() + EVENT_TIMEOUT_S
    while True:
        try:
            watermark = scope.poll(
                sent_limit=wanted,
                total=total,
                valid_offsets=valid_offsets,
            )
        except ValueError as exc:
            raise BenchFailure("FILE_PUT_ACK was outside the transmitted range") from exc
        if watermark >= wanted:
            return watermark
        if time.monotonic() >= deadline:
            raise BenchFailure("FILE_PUT_DATA did not reach its ACK watermark")
        await asyncio.sleep(0.01)


async def _end_put(state, checksum, expected=wire.ST_OK):
    response = await state.central.send_cmd(
        wire.OP_FILE_PUT_END,
        state.ids.next(),
        int(checksum).to_bytes(4, "little"),
    )
    _status_is(response, expected, "FILE_PUT_END")
    return response


async def put_file(state, path, data):
    """Upload and stat-verify one small physical fixture with nonzero CMD IDs."""
    data = bytes(data)
    checksum = wire.crc32(data)
    await pble_bench.remove_if_present(state.central, path, state.ids.next)
    resume = await _begin_put(state, path, len(data), checksum)
    _require(resume == 0, "fresh fixture unexpectedly resumed a scratch prefix")
    scope = state.central.begin_ack_scope(0)
    offset = 0
    chunk = int(state.caps["chunk"])
    valid_offsets = {0}
    while offset < len(data):
        piece = data[offset : offset + chunk]
        valid_offsets.add(offset + len(piece))
        offset = await _send_put_piece(
            state,
            scope,
            offset,
            piece,
            len(data),
            valid_offsets,
        )
    await _end_put(state, checksum)
    response = await state.central.send_cmd(
        wire.OP_FILE_STAT,
        state.ids.next(),
        pble_bench.path_payload(path),
    )
    _status_is(response, wire.ST_OK, "FILE_STAT after fixture PUT")
    _require(len(response.payload) == 9, "FILE_STAT payload has the wrong length")
    _require(
        int.from_bytes(response.payload[1:5], "little") == len(data)
        and int.from_bytes(response.payload[5:9], "little") == checksum,
        "FILE_STAT did not verify the fixture bytes",
    )


def parse_list_payload(payload):
    payload = bytes(payload)
    _require(len(payload) >= 4, "FILE_LIST payload is truncated")
    _require(payload[0] == wire.ST_OK, "FILE_LIST status is not OK")
    _require(payload[1] in (0, 1), "FILE_LIST more flag is invalid")
    count = int.from_bytes(payload[2:4], "little")
    offset = 4
    entries = []
    for _index in range(count):
        _require(offset + 7 <= len(payload), "FILE_LIST entry header is truncated")
        kind = payload[offset]
        size = int.from_bytes(payload[offset + 1 : offset + 5], "little")
        name_size = int.from_bytes(payload[offset + 5 : offset + 7], "little")
        offset += 7
        _require(offset + name_size <= len(payload), "FILE_LIST name is truncated")
        try:
            name = payload[offset : offset + name_size].decode(
                "utf-8", errors="strict"
            )
        except UnicodeDecodeError as exc:
            raise BenchFailure("FILE_LIST name is not strict UTF-8") from exc
        _require(kind in (0, 1), "FILE_LIST entry kind is invalid")
        entries.append((kind, size, name))
        offset += name_size
    _require(offset == len(payload), "FILE_LIST has trailing bytes")
    return payload[1], entries


def _profile_thresholds(profile):
    try:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BenchFailure("the committed OI-1 resource policy is unreadable") from exc
    _require(
        tuple(policy.get("profile_order", ())) == PROFILE_ORDER,
        "the committed resource policy profile order has drifted",
    )
    matches = [entry for entry in policy.get("profiles", ()) if entry.get("profile_id") == profile]
    _require(len(matches) == 1, "the resource policy lacks the selected profile")
    return dict(matches[0].get("thresholds", {}))


def resource_failures(snapshots, thresholds):
    failures = []
    floor_map = {
        "gc_free_bytes": "gc_free_min_bytes",
        "idf_internal_free_bytes": "idf_internal_free_min_bytes",
        "idf_internal_largest_block_bytes": "idf_internal_largest_block_min_bytes",
        "idf_internal_minimum_free_bytes": "idf_internal_minimum_free_min_bytes",
    }
    for index, snapshot in enumerate(snapshots):
        for observed_key, threshold_key in floor_map.items():
            if threshold_key not in thresholds:
                continue
            value = snapshot.get(observed_key)
            floor = thresholds[threshold_key]
            if not isinstance(value, int) or isinstance(value, bool) or value < floor:
                failures.append(
                    "resource floor failed at sample %d for %s" % (index + 1, observed_key)
                )
    gc_values = [snapshot.get("gc_free_bytes") for snapshot in snapshots]
    if (
        len(gc_values) > 1
        and all(isinstance(value, int) and not isinstance(value, bool) for value in gc_values)
        and all(later <= earlier for earlier, later in zip(gc_values, gc_values[1:]))
        and any(later < earlier for earlier, later in zip(gc_values, gc_values[1:]))
    ):
        failures.append("gc_free_bytes has a monotonic downward leak signature")
    return failures


def format_result(status, profile, caps, workspace):
    return (
        "V061 HARDENING %s (profile=%s chip=%s agent=%s scenarios=%d workspace=%s)"
        % (
            status,
            profile,
            caps.get("chip", "?"),
            caps.get("agent", "?"),
            len(SCENARIO_ORDER),
            workspace,
        )
    )


def workspace_prerequisite(args):
    return (
        "passed"
        if getattr(args, "_workspace_receipts_validated", False)
        else "pending"
    )


def preflight_result_inputs(args):
    """Lease the candidate, receipts, and committed runner before BLE work."""
    try:
        preflight = hardening_gate.preflight_result_inputs(
            candidate_dir=Path(args.candidate_dir),
            profile_id=args.profile,
            workspace_erased_receipt=Path(args.workspace_erased_receipt),
            workspace_nonblank_receipt=Path(args.workspace_nonblank_receipt),
            qualification_repo_root=Path(args.qualification_repo_root),
        )
    except hardening_gate.QualificationError as exc:
        raise BenchFailure("candidate-bound input preflight failed") from exc
    args._workspace_receipts_validated = True
    return preflight


async def preflight_board_workspace(state):
    """Refuse any namespace collision before the first board mutation."""
    for path, label in (
        (WORK_DIR, "v0.6.1 scratch root"),
        ("/main.py", "owner main.py"),
    ):
        response = await state.central.send_cmd(
            wire.OP_FILE_STAT,
            state.ids.next(),
            pble_bench.path_payload(path),
        )
        _status_is(response, wire.ST_ENOENT, "%s preflight" % label)
        _require(
            response.payload == bytes((wire.ST_ENOENT,)),
            "%s preflight returned malformed evidence" % label,
        )


async def run_transport_session(state):
    """Prove HELLO-first, unsupported-offer refusal, and reconnect freshness."""
    await _connect(state)
    response = await state.central.send_cmd(
        wire.OP_DEVICE_INFO,
        state.ids.next(),
    )
    _status_is(response, wire.ST_EBADREQ, "pre-HELLO DEVICE_INFO")

    response = await state.central.send_cmd(
        wire.OP_HELLO,
        state.ids.next(),
        UNSUPPORTED_HELLO_PAYLOAD,
    )
    _status_is(response, wire.ST_EUNSUPPORTED, "unsupported HELLO offer")
    await _negotiate(state)

    # A failed repeated HELLO must not revoke the already committed v1
    # negotiation for this exact session.
    response = await state.central.send_cmd(
        wire.OP_HELLO,
        state.ids.next(),
        UNSUPPORTED_HELLO_PAYLOAD,
    )
    _status_is(response, wire.ST_EUNSUPPORTED, "repeated unsupported HELLO offer")
    response = await state.central.send_cmd(
        wire.OP_DEVICE_INFO,
        state.ids.next(),
    )
    _status_is(response, wire.ST_OK, "DEVICE_INFO after failed repeated HELLO")

    await _disconnect(state)
    await _connect(state)
    response = await state.central.send_cmd(
        wire.OP_DEVICE_INFO,
        state.ids.next(),
    )
    _status_is(response, wire.ST_EBADREQ, "reconnected pre-HELLO DEVICE_INFO")
    await _negotiate(state)


async def _write_raw_packet(central, packet):
    await asyncio.wait_for(
        central._client.write_gatt_char(RX_UUID, bytes(packet), response=True),
        timeout=EVENT_TIMEOUT_S,
    )


async def _write_raw_frame(central, frame):
    for packet in wire.fragment(frame, central.mtu):
        await _write_raw_packet(central, packet)


async def _expect_raw_silence(central, frame, description):
    before = central.rx_frames
    await _write_raw_frame(central, frame)
    await asyncio.sleep(QUIET_S)
    _require(central.rx_frames == before, description + " was not reply-silent")


async def run_fragment_hardening(state):
    """Exercise TYPE/ID rejection, ECRC, expiry, and the exact budget."""
    central = state.central

    # A valid inbound RSP has the wrong TYPE and a valid CMD with ID zero has
    # invalid correlation.  Both are silently discarded physical RX writes;
    # _write_raw_packet performs the real backend write_gatt_char operation.
    await _expect_raw_silence(
        central,
        wire.encode(wire.RSP, wire.OP_DEVICE_INFO, 71, b"\x00"),
        "wrong-direction frame",
    )
    await _expect_raw_silence(
        central,
        wire.encode(wire.CMD, wire.OP_DEVICE_INFO, 0, b""),
        "zero-ID frame",
    )

    cursor = central.event_cursor()
    bad_crc = bytearray(wire.encode(wire.CMD, wire.OP_DEVICE_INFO, 72, b""))
    bad_crc[-1] ^= 0x80
    await _write_raw_frame(central, bad_crc)
    _cursor, error = await _wait_event(
        central,
        cursor,
        lambda event: event.type == wire.EVT
        and event.opcode == wire.OP_DEVICE_INFO
        and event.id == 0
        and event.payload == bytes((wire.ST_ECRC,)),
        EVENT_TIMEOUT_S,
        "CRC corruption did not emit the frozen ECRC event",
    )
    _require(error.payload == bytes((wire.ST_ECRC,)), "ECRC payload drifted")

    # Progress at t<5000 ms must not extend the FIRST fragment's absolute
    # REASSEMBLY_DEADLINE_S.  The expired LAST is one discarded run.
    frame = wire.encode(wire.CMD, wire.OP_DEVICE_INFO, 73, b"")
    before = central.rx_frames
    started = time.monotonic()
    await _write_raw_packet(central, bytes((0x80,)) + frame[:3])
    await asyncio.sleep(REASSEMBLY_DEADLINE_S - 0.75)
    _require(
        time.monotonic() - started < REASSEMBLY_DEADLINE_S,
        "host scheduling missed the pre-deadline fragment observation",
    )
    await _write_raw_packet(central, bytes((0x01,)) + frame[3:6])
    remaining = REASSEMBLY_DEADLINE_S + 0.10 - (time.monotonic() - started)
    if remaining > 0:
        await asyncio.sleep(remaining)
    await _write_raw_packet(central, bytes((0x42,)) + frame[6:])
    await asyncio.sleep(QUIET_S)
    _require(central.rx_frames == before, "expired fragment run produced a response")
    response = await central.send_cmd(wire.OP_DEVICE_INFO, state.ids.next())
    _status_is(response, wire.ST_OK, "post-expiry DEVICE_INFO")

    # Use a clean session so the MALFORMED_BUDGET count is exact.  Seven
    # wrong-direction frames stay connected and silent; number eight closes.
    await _reconnect_and_negotiate(state)
    central = state.central
    for index in range(MALFORMED_BUDGET - 1):
        await _expect_raw_silence(
            central,
            wire.encode(wire.RSP, wire.OP_DEVICE_INFO, 80 + index, b"\x00"),
            "pre-limit wrong-direction frame",
        )
        _require(central.is_connected, "session closed before the eighth violation")
    try:
        await _write_raw_frame(
            central,
            wire.encode(wire.RSP, wire.OP_DEVICE_INFO, 87, b"\x00"),
        )
    except Exception:
        if central.is_connected:
            raise
    await _wait_disconnected(central)
    state.central = None

    # Only a new connection clears the budget; its HELLO proves a clean
    # successor rather than treating local disconnect state as recovery.
    await _connect(state)
    await _negotiate(state)


async def run_fresh_globals(state):
    """Prove fresh globals independently for source and file RUN modes."""
    # _run_program submits the physical wire.OP_RUN for both modes below.
    source_one = (
        b"_pyble_v061_source_global=1\n"
        b"print('__PYBLE_V061_SOURCE_SET__')\n"
    )
    source_two = (
        b"print('__PYBLE_V061_fresh-source__=%d'%"
        b"('_pyble_v061_source_global' not in globals()))\n"
    )
    stdout = await _run_program(state, 1, source_one, "fresh-source setup")
    _require(stdout.count(SOURCE_SET_MARKER) == 1, "source setup marker was not exact")
    stdout = await _run_program(state, 1, source_two, "fresh-source check")
    _require(stdout.count(SOURCE_FRESH_MARKER) == 1, "source globals leaked across RUN")

    await pble_bench.ensure_directory(state.central, WORK_DIR, state.ids.next)
    file_one = (
        b"_pyble_v061_file_global=1\n"
        b"print('__PYBLE_V061_FILE_SET__')\n"
    )
    file_two = (
        b"print('__PYBLE_V061_fresh-file__=%d'%"
        b"('_pyble_v061_file_global' not in globals()))\n"
    )
    try:
        await put_file(state, SOURCE_FILE_ONE, file_one)
        await put_file(state, SOURCE_FILE_TWO, file_two)
        stdout = await _run_program(
            state, 0, SOURCE_FILE_ONE.encode("utf-8"), "fresh-file setup"
        )
        _require(stdout.count(FILE_SET_MARKER) == 1, "file setup marker was not exact")
        stdout = await _run_program(
            state, 0, SOURCE_FILE_TWO.encode("utf-8"), "fresh-file check"
        )
        _require(stdout.count(FILE_FRESH_MARKER) == 1, "file globals leaked across RUN")
    finally:
        await pble_bench.remove_if_present(
            state.central, SOURCE_FILE_ONE, state.ids.next
        )
        await pble_bench.remove_if_present(
            state.central, SOURCE_FILE_TWO, state.ids.next
        )


async def run_resource_stability(state):
    """Run exactly SEQUENTIAL_RUNS bounded probes against existing floors."""
    thresholds = _profile_thresholds(state.args.profile)
    _require("gc_free_min_bytes" in thresholds, "resource policy lacks the GC floor")
    snapshots = []
    profile_token = re.sub(r"[^0-9A-Za-z]", "", state.args.profile)
    for index in range(SEQUENTIAL_RUNS):
        nonce = "v061%s%02d" % (profile_token, index)
        if state.args.profile == "rpi-pico2-w":
            snapshot = await pble_bench.run_rp2_heap_probe(
                state.central,
                state.ids.next,
                nonce=nonce,
            )
        else:
            snapshot = await pble_bench.run_heap_probe(
                state.central,
                state.ids.next,
                nonce=nonce,
            )
        snapshots.append(snapshot)
    failures = resource_failures(snapshots, thresholds)
    _require(not failures, failures[0] if failures else "resource stability failed")


async def run_stdin_isolation(state):
    """Prove idle/prompt/STOP/terminal/disconnect/overflow stdin boundaries."""
    # idle: pre-RUN input must be discarded; only input after the prompt wins.
    await state.central.send_cmd_no_rsp(
        wire.OP_CONSOLE_INPUT, state.ids.next(), b"idle-stale\n"
    )
    cursor, echo = await _start_input_run(state, "idle")
    await _assert_run_still_active(state.central, cursor, "idle")
    await _finish_input_run(state, cursor, echo, b"idle-fresh")

    # terminal: a second queued line must be cleared when the first line ends
    # the program, so it cannot satisfy the successor's prompt.
    cursor, echo = await _start_input_run(state, "terminal-one")
    await state.central.send_cmd_no_rsp(
        wire.OP_CONSOLE_INPUT,
        state.ids.next(),
        b"terminal-good\nterminal-stale\n",
    )
    events = await _wait_program_terminal(state.central, cursor)
    _require(
        _console_bytes(events, 0).count(echo + b"terminal-good") == 1,
        "terminal setup did not consume its first line",
    )
    cursor, echo = await _start_input_run(state, "terminal-two")
    await _assert_run_still_active(state.central, cursor, "terminal")
    await _finish_input_run(state, cursor, echo, b"terminal-fresh")

    # overflow + STOP: exceed the 256-byte ring while the VM is busy, then STOP
    # must clear both retained prefix and overflow residue before a successor.
    cursor, _echo = await _start_input_run(state, "overflow", delay_ms=3000)
    first = b"x" * (STDIN_OVERFLOW_BYTES // 2)
    second = b"y" * (STDIN_OVERFLOW_BYTES - len(first))
    await state.central.send_cmd_no_rsp(
        wire.OP_CONSOLE_INPUT, state.ids.next(), first
    )
    await state.central.send_cmd_no_rsp(
        wire.OP_CONSOLE_INPUT, state.ids.next(), second
    )
    stop_cursor = state.central.event_cursor()
    response = await state.central.send_cmd(wire.OP_STOP, state.ids.next())
    _status_is(response, wire.ST_OK, "overflow STOP")
    await _wait_event(
        state.central,
        stop_cursor,
        lambda event: event.type == wire.EVT
        and event.opcode == wire.OP_RUN_STATE
        and event.payload == bytes((ST_IDLE,)),
        EVENT_TIMEOUT_S,
        "accepted STOP did not emit idle",
    )
    cursor, echo = await _start_input_run(state, "stop-successor")
    await _assert_run_still_active(state.central, cursor, "STOP/overflow")
    await _finish_input_run(state, cursor, echo, b"stop-fresh")

    # disconnect: the program deliberately cannot call input() until after the
    # old link is gone.  A newly negotiated client feeds that same live RUN.
    cursor, _echo = await _start_input_run(state, "disconnect", delay_ms=5000)
    await state.central.send_cmd_no_rsp(
        wire.OP_CONSOLE_INPUT, state.ids.next(), b"disconnect-stale\n"
    )
    await _disconnect(state)
    await _connect(state)
    await _negotiate(state)
    successor_cursor = state.central.event_cursor()
    await asyncio.sleep(QUIET_S)
    await state.central.send_cmd_no_rsp(
        wire.OP_CONSOLE_INPUT, state.ids.next(), b"disconnect-fresh\n"
    )
    await _wait_console_marker(
        state.central,
        successor_cursor,
        b"__PYBLE_V061_STDIN_disconnect_ECHO__=disconnect-fresh",
        EVENT_TIMEOUT_S,
    )
    await _wait_event(
        state.central,
        successor_cursor,
        lambda event: event.type == wire.EVT
        and event.opcode == wire.OP_RUN_STATE
        and event.payload == bytes((ST_DONE,)),
        EVENT_TIMEOUT_S,
        "disconnect-cleared RUN did not finish",
    )
    stdout = _console_bytes(_events_after(state.central, successor_cursor), 0)
    _require(b"disconnect-stale" not in stdout, "disconnect retained stale stdin")


async def _device_info(state):
    response = await state.central.send_cmd(
        wire.OP_DEVICE_INFO,
        state.ids.next(),
    )
    _status_is(response, wire.ST_OK, "DEVICE_INFO")
    try:
        caps = target_smoke.parse_caps(
            response.payload[1:].decode("utf-8", errors="strict")
        )
        target_smoke.validate_caps(
            caps,
            PROFILE_CHIPS[state.args.profile],
            state.args.expect_agent,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise BenchFailure("DEVICE_INFO caps failed validation") from exc
    return caps


async def _set_label(state, payload, expected):
    response = await state.central.send_cmd(
        wire.OP_SET_LABEL,
        state.ids.next(),
        payload,
    )
    return _status_is(response, expected, "SET_LABEL")


async def _wait_advertisement(state, expected_name):
    deadline = time.monotonic() + RECONNECT_RETRY_S
    while time.monotonic() < deadline:
        for address, name in await PbleCentral.scan(timeout=2.0):
            if address == state.args.address and name == expected_name:
                return
        await asyncio.sleep(0.10)
    raise BenchFailure("expected persisted advertisement was not observed")


async def _soft_reboot_to_advertisement(state, expected_name):
    central = state.central
    response = await central.send_cmd(wire.OP_SOFT_REBOOT, state.ids.next())
    _status_is(response, wire.ST_OK, "SOFT_REBOOT")
    await _wait_disconnected(central)
    state.central = None
    await _wait_advertisement(state, expected_name)
    await _connect(state)
    return await _negotiate(state)


async def run_label_durability(state):
    """Prove label, autorun, and owner-configured Identify durability."""
    # _set_label and _soft_reboot_to_advertisement issue wire.OP_SET_LABEL and
    # wire.OP_SOFT_REBOOT; keeping them transactional lets restoration share
    # the same exact physical path as the assertion.
    original_caps = await _device_info(state)
    original_label = original_caps["label"]
    original_name = original_label or "PyBLE-%s" % original_caps["device_id"]
    _require(
        original_caps.get("auto_run") in ("0", "1"),
        "DEVICE_INFO auto_run is not a bit",
    )
    _require(
        original_caps.get("has_identify") in ("0", "1"),
        "DEVICE_INFO has_identify is not a bit",
    )
    original_auto_run = int(original_caps["auto_run"])
    original_identify_led = original_caps.get("identify_led")
    has_identify = original_caps["has_identify"] == "1"
    test_bytes = LABEL_24.encode("utf-8")
    _require(len(test_bytes) == 24, "LABEL_24 is not exactly 24 UTF-8 bytes")
    primary_error = None
    try:
        # Identify is an action, never a configuration operation.  Preserve
        # the owner's identify_led and prove the action on both sides of a
        # soft reboot only when the capability says it exists.
        if has_identify:
            response = await state.central.send_cmd(
                wire.OP_IDENTIFY,
                state.ids.next(),
            )
            _status_is(response, wire.ST_OK, "IDENTIFY before soft reboot")

        rejected = (
            (b"x" * 25, wire.ST_ERANGE),
            (b"bad\x00label", wire.ST_EBADREQ),
            (b"bad\nlabel", wire.ST_EBADREQ),
            (b"bad\rlabel", wire.ST_EBADREQ),
            (b"bad\x01label", wire.ST_EBADREQ),
            (b"bad\x7flabel", wire.ST_EBADREQ),
            (b"\xc2\x80", wire.ST_EBADREQ),
            (b"\xff", wire.ST_EBADREQ),
        )
        for payload, status in rejected:
            await _set_label(state, payload, status)
            caps = await _device_info(state)
            _require(caps["label"] == original_label, "rejected label changed DEVICE_INFO")

        # A reboot plus service-filtered scan proves rejected bytes did not
        # reach either persistence or the advertisement, not just live caps.
        caps = await _soft_reboot_to_advertisement(state, original_name)
        _require(
            caps["label"] == original_label,
            "rejected label changed persisted configuration",
        )
        _require(
            caps.get("identify_led") == original_identify_led,
            "soft reboot changed owner identify_led configuration",
        )
        if has_identify:
            response = await state.central.send_cmd(
                wire.OP_IDENTIFY,
                state.ids.next(),
            )
            _status_is(response, wire.ST_OK, "IDENTIFY after soft reboot")

        toggled_auto_run = 1 - original_auto_run
        response = await state.central.send_cmd(
            wire.OP_SET_AUTORUN,
            state.ids.next(),
            bytes((toggled_auto_run,)),
        )
        _status_is(response, wire.ST_OK, "SET_AUTORUN durability toggle")
        caps = await _device_info(state)
        _require(
            caps.get("auto_run") == str(toggled_auto_run),
            "SET_AUTORUN did not update DEVICE_INFO",
        )
        caps = await _soft_reboot_to_advertisement(state, original_name)
        _require(
            caps.get("auto_run") == str(toggled_auto_run),
            "auto_run did not persist across soft reboot",
        )
        _require(
            caps.get("identify_led") == original_identify_led,
            "autorun durability changed owner identify_led configuration",
        )

        await _set_label(state, test_bytes, wire.ST_OK)
        caps = await _device_info(state)
        _require(caps["label"] == LABEL_24, "accepted 24-byte label was not published")
        caps = await _soft_reboot_to_advertisement(state, LABEL_24)
        _require(caps["label"] == LABEL_24, "24-byte label did not persist across reboot")
    except BaseException as exc:
        primary_error = exc
    finally:
        try:
            if state.central is None or not state.central.is_connected:
                await _connect(state)
                await _negotiate(state)
            await _set_label(
                state,
                original_label.encode("utf-8"),
                wire.ST_OK,
            )
            response = await state.central.send_cmd(
                wire.OP_SET_AUTORUN,
                state.ids.next(),
                bytes((original_auto_run,)),
            )
            _status_is(response, wire.ST_OK, "SET_AUTORUN restore")
            restored = await _soft_reboot_to_advertisement(state, original_name)
            _require(
                restored["label"] == original_label,
                "original label was not restored after the durability check",
            )
            _require(
                restored.get("auto_run") == str(original_auto_run),
                "original auto_run was not restored after the durability check",
            )
            _require(
                restored.get("identify_led") == original_identify_led,
                "restoration changed owner identify_led configuration",
            )
        except BaseException as cleanup_error:
            if primary_error is None:
                primary_error = cleanup_error
            else:
                primary_error = BenchFailure(
                    "configuration check failed and deterministic restoration also failed"
                )
    if primary_error is not None:
        raise primary_error


async def _list_directory(state, path):
    response = await state.central.send_cmd(
        wire.OP_FILE_LIST,
        state.ids.next(),
        pble_bench.path_payload(path),
    )
    _status_is(response, wire.ST_OK, "FILE_LIST")
    return parse_list_payload(response.payload)


async def _assert_scratch_hidden(state):
    more, entries = await _list_directory(state, WORK_DIR)
    _require(more == 0, "small fixture directory was unexpectedly truncated")
    _require(
        all(not name.endswith(".pbltmp") for _kind, _size, name in entries),
        ".pbltmp scratch artifact escaped into FILE_LIST",
    )


async def _mutation_status(state, opcode, payload, description):
    response = await state.central.send_cmd(opcode, state.ids.next(), payload)
    _status_is(response, wire.ST_EBUSY, description)


async def _statvfs_geometry(state):
    source = (
        b"import os\n"
        b"_v061_sv=os.statvfs('/')\n"
        b"print('__PYBLE_V061_STATVFS__=%d,%d'%(_v061_sv[1],_v061_sv[4]))\n"
    )
    stdout = await _run_program(state, 1, source, "capacity statvfs")
    matches = re.findall(rb"__PYBLE_V061_STATVFS__=([0-9]+),([0-9]+)", stdout)
    _require(len(matches) == 1, "statvfs probe did not emit exact geometry")
    unit, available = (int(value) for value in matches[0])
    _require(unit > 0 and available >= 0, "statvfs geometry is invalid")
    return unit, available


async def _cleanup_bench_put(state, path):
    if state.central is None or not state.central.is_connected:
        await _connect(state)
        await _negotiate(state)
    # Resolve any active transaction first.  Failure is expected for an
    # incomplete transaction and safely removes its scratch.
    try:
        await _end_put(state, 0, expected=wire.ST_ERANGE)
    except Exception:
        pass
    # A zero-length begin makes any remaining nonempty regular scratch
    # malformed, safely removes it, and gives this bench a deletable artifact.
    try:
        resume = await _begin_put(state, path, 0, 0)
        if resume == 0:
            await _end_put(state, 0)
    except Exception:
        pass
    try:
        await pble_bench.remove_if_present(state.central, path, state.ids.next)
    except Exception:
        pass


async def run_filesystem_hardening(state):
    """Exercise .pbltmp hiding, mutation EBUSY, scratch safety, and capacity."""
    # _assert_scratch_hidden performs wire.OP_FILE_LIST; every valid namespace
    # mutation below must return the exact wire.ST_EBUSY status during PUT.
    old_bytes = b"v061-old-target-sentinel"
    replacement = b"v061-new-target-content-123456"
    await pble_bench.ensure_directory(state.central, WORK_DIR, state.ids.next)
    try:
        await put_file(state, FS_SENTINEL_PATH, old_bytes)

        # An active PUT exposes neither its .pbltmp file nor a mutation window.
        resume = await _begin_put(
            state,
            FS_SENTINEL_PATH,
            len(replacement),
            wire.crc32(replacement),
        )
        _require(resume == 0, "active-PUT fixture unexpectedly resumed")
        scope = state.central.begin_ack_scope(0)
        piece = replacement[:8]
        await _send_put_piece(
            state, scope, 0, piece, len(replacement), {0, len(piece)}
        )
        await _assert_scratch_hidden(state)
        await _mutation_status(
            state,
            wire.OP_FILE_DELETE,
            pble_bench.path_payload(FS_SENTINEL_PATH),
            "active-PUT FILE_DELETE",
        )
        await _mutation_status(
            state,
            wire.OP_FILE_RENAME,
            pble_bench.path_payload(FS_SENTINEL_PATH)
            + pble_bench.path_payload(FS_RENAME_PATH),
            "active-PUT FILE_RENAME",
        )
        await _mutation_status(
            state,
            wire.OP_MKDIR,
            pble_bench.path_payload(FS_BLOCKED_DIR),
            "active-PUT MKDIR",
        )
        await _end_put(state, wire.crc32(replacement), expected=wire.ST_ERANGE)
        await pble_bench.get_file(
            state.central,
            FS_SENTINEL_PATH,
            old_bytes,
            next_id=state.ids.next,
        )
        response = await state.central.send_cmd(
            wire.OP_FILE_STAT,
            state.ids.next(),
            pble_bench.path_payload(FS_RENAME_PATH),
        )
        _status_is(response, wire.ST_ENOENT, "post-PUT renamed destination stat")
        _more, entries = await _list_directory(state, WORK_DIR)
        _require(
            all(name != "blocked_dir" for _kind, _size, name in entries),
            "active-PUT MKDIR mutated the filesystem",
        )

        # Leave a valid 16-byte prefix, reconnect, then declare an 8-byte file.
        # The now-oversized scratch is malformed; recovery must restart at zero
        # while preserving the old destination byte-for-byte.
        resume = await _begin_put(
            state,
            FS_SENTINEL_PATH,
            len(replacement),
            wire.crc32(replacement),
        )
        _require(resume == 0, "malformed-scratch fixture unexpectedly resumed")
        scope = state.central.begin_ack_scope(0)
        piece = replacement[:16]
        await _send_put_piece(
            state, scope, 0, piece, len(replacement), {0, len(piece)}
        )
        await _disconnect(state)
        await _connect(state)
        await _negotiate(state)
        await _assert_scratch_hidden(state)

        short_data = b"12345678"
        resume = await _begin_put(
            state,
            FS_SENTINEL_PATH,
            len(short_data),
            wire.crc32(short_data),
        )
        _require(resume == 0, "oversized malformed scratch was resumed")
        await _end_put(state, wire.crc32(short_data), expected=wire.ST_ERANGE)
        await pble_bench.get_file(
            state.central,
            FS_SENTINEL_PATH,
            old_bytes,
            next_id=state.ids.next,
        )

        # Capacity admission uses the live board's statvfs geometry but writes
        # no large payload.  Exactly free-reserve rounded to a whole unit is
        # accepted; one byte beyond that allocation boundary is ENOSPC.
        unit, available = await _statvfs_geometry(state)
        free = available * unit
        blocks = (free - CAPACITY_RESERVE) // unit
        _require(blocks >= 1, "capacity boundary is not safely feasible")
        exact_total = blocks * unit
        _require(exact_total < (1 << 32), "capacity boundary exceeds PBLE/1 u32")
        await pble_bench.remove_if_present(
            state.central, FS_CAPACITY_PATH, state.ids.next
        )
        resume = await _begin_put(state, FS_CAPACITY_PATH, exact_total, 0)
        _require(resume == 0, "exact capacity boundary unexpectedly resumed")
        await _end_put(state, 0, expected=wire.ST_ERANGE)

        unit, available = await _statvfs_geometry(state)
        free = available * unit
        blocks = (free - CAPACITY_RESERVE) // unit
        _require(blocks >= 0, "capacity rejection boundary is not feasible")
        rejected_total = blocks * unit + 1
        _require(rejected_total < (1 << 32), "capacity rejection exceeds PBLE/1 u32")
        await _begin_put(
            state,
            FS_CAPACITY_PATH,
            rejected_total,
            0,
            expected=wire.ST_ENOSPC,
        )
        await pble_bench.get_file(
            state.central,
            FS_SENTINEL_PATH,
            old_bytes,
            next_id=state.ids.next,
        )
    finally:
        await _cleanup_bench_put(state, FS_SENTINEL_PATH)
        await _cleanup_bench_put(state, FS_CAPACITY_PATH)
        await pble_bench.remove_if_present(
            state.central, FS_RENAME_PATH, state.ids.next
        )
        await pble_bench.remove_if_present(
            state.central, FS_BLOCKED_DIR, state.ids.next
        )
        await pble_bench.remove_if_present(state.central, WORK_DIR, state.ids.next)


def _scenario_log_bytes(scenario_results):
    rows = []
    for name in SCENARIO_ORDER:
        row = scenario_results[name]
        value = {"scenario": name, "status": row["status"]}
        if name == "resource-stability":
            value["sequential_runs"] = row["sequential_runs"]
        rows.append(value)
    try:
        return b"".join(
            (
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
            for value in rows
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BenchFailure("scenario result log is not canonical") from exc


def _write_private_log(path, raw):
    """Create one mode-0600 raw log without following or replacing a name."""
    try:
        hardening_gate._write_exclusive(Path(path), raw)
    except hardening_gate.QualificationError as exc:
        raise BenchFailure("raw log output could not be created safely") from exc


def write_private_result(
    candidate_dir,
    profile_id,
    scenario_results,
    workspace_erased_receipt,
    workspace_nonblank_receipt,
    raw_log,
    result,
    qualification_repo_root,
):
    """Write the bounded raw log, then publish one shared-gate result."""
    _write_private_log(raw_log, _scenario_log_bytes(scenario_results))
    try:
        return hardening_gate.create_result(
            candidate_dir=Path(candidate_dir),
            profile_id=profile_id,
            scenario_results=scenario_results,
            workspace_erased_receipt=Path(workspace_erased_receipt),
            workspace_nonblank_receipt=Path(workspace_nonblank_receipt),
            raw_log=Path(raw_log),
            output_path=Path(result),
            qualification_repo_root=Path(qualification_repo_root),
        )
    except hardening_gate.QualificationError as exc:
        raise BenchFailure("candidate-bound result validation failed") from exc


def write_private_result_from_preflight(
    preflight,
    scenario_results,
    raw_log,
    result,
):
    """Write the raw log and consume the exact pre-BLE evidence lease."""
    _write_private_log(raw_log, _scenario_log_bytes(scenario_results))
    try:
        return hardening_gate.create_result_from_preflight(
            preflight=preflight,
            scenario_results=scenario_results,
            raw_log=Path(raw_log),
            output_path=Path(result),
        )
    except hardening_gate.QualificationError as exc:
        raise BenchFailure("candidate-bound result validation failed") from exc


async def _run_scenario(name, operation):
    await operation()
    print("V061 SCENARIO PASS (%s)" % name)


async def run(args):
    workspace = "pending"
    expected_caps = {
        "chip": PROFILE_CHIPS[args.profile],
        "agent": args.expect_agent,
    }
    state = LiveState(args)
    scenario_results = {}
    try:
        # The host preflight leases args.workspace_erased_receipt and
        # args.workspace_nonblank_receipt before any physical operation.
        preflight = preflight_result_inputs(args)
        workspace = workspace_prerequisite(args)
        await _run_scenario(
            "transport-session", lambda: run_transport_session(state)
        )
        scenario_results["transport-session"] = {"status": "passed"}
        await preflight_board_workspace(state)
        await _run_scenario(
            "fragment-hardening", lambda: run_fragment_hardening(state)
        )
        scenario_results["fragment-hardening"] = {"status": "passed"}
        await _run_scenario("run-isolation", lambda: run_fresh_globals(state))
        scenario_results["run-isolation"] = {"status": "passed"}
        await _run_scenario(
            "resource-stability", lambda: run_resource_stability(state)
        )
        scenario_results["resource-stability"] = {
            "status": "passed",
            "sequential_runs": SEQUENTIAL_RUNS,
        }
        await _run_scenario("stdin-isolation", lambda: run_stdin_isolation(state))
        scenario_results["stdin-isolation"] = {"status": "passed"}
        await _run_scenario(
            "configuration-durability", lambda: run_label_durability(state)
        )
        scenario_results["configuration-durability"] = {"status": "passed"}
        await _run_scenario(
            "filesystem-hardening", lambda: run_filesystem_hardening(state)
        )
        scenario_results["filesystem-hardening"] = {"status": "passed"}
        write_private_result_from_preflight(
            preflight=preflight,
            scenario_results=scenario_results,
            raw_log=args.raw_log,
            result=args.result,
        )
        print(format_result("PASS", args.profile, state.caps, workspace))
        return 0
    except BenchFailure as exc:
        print("V061 FAILURE (%s)" % str(exc))
        print(format_result("FAIL", args.profile, state.caps or expected_caps, workspace))
        return 1
    finally:
        try:
            await _best_effort_stop(state)
            await _disconnect(state)
        except Exception:
            pass


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="physical PBLE/1 firmware-v0.6.1 hardening HIL bench"
    )
    parser.add_argument(
        "--create-workspace-receipt",
        action="store_true",
        help="derive one pre-service receipt without opening BLE",
    )
    parser.add_argument(
        "--profile",
        choices=PROFILE_ORDER,
        help="exact physical release profile under test",
    )
    parser.add_argument(
        "--address",
        help="private BLE address/UUID (never emitted in the result)",
    )
    parser.add_argument(
        "--expect-agent",
        help="exact v0.6.1 agent version",
    )
    parser.add_argument(
        "--candidate-dir",
        type=Path,
        help="exact firmware-v0.6.1 release candidate directory",
    )
    parser.add_argument(
        "--workspace-erased-receipt",
        type=Path,
        help="private erased-media-first-boot receipt",
    )
    parser.add_argument(
        "--workspace-nonblank-receipt",
        type=Path,
        help="private nonblank-media-refusal receipt",
    )
    parser.add_argument(
        "--raw-log",
        type=Path,
        help="new private canonical JSONL output",
    )
    parser.add_argument(
        "--result",
        type=Path,
        help="new private candidate-bound result output",
    )
    parser.add_argument("--board-manufacturer")
    parser.add_argument("--board-model")
    parser.add_argument("--module-marking")
    parser.add_argument(
        "--observation-kind",
        choices=hardening_gate.WORKSPACE_PROVISIONING_ORDER,
    )
    parser.add_argument("--raw-boot-log", type=Path)
    parser.add_argument("--receipt-output", type=Path)
    args = parser.parse_args(argv)

    def require_options(names):
        missing = ["--" + name.replace("_", "-") for name in names if getattr(args, name) is None]
        if missing:
            parser.error("the following arguments are required: %s" % ", ".join(missing))

    args.qualification_repo_root = ROOT
    try:
        if args.create_workspace_receipt:
            require_options(
                (
                    "profile",
                    "candidate_dir",
                    "observation_kind",
                    "raw_boot_log",
                    "receipt_output",
                )
            )
            forbidden = (
                "address",
                "expect_agent",
                "workspace_erased_receipt",
                "workspace_nonblank_receipt",
                "raw_log",
                "result",
                "board_manufacturer",
                "board_model",
                "module_marking",
            )
            if any(getattr(args, name) is not None for name in forbidden):
                parser.error(
                    "workspace-receipt mode accepts only its bounded receipt inputs"
                )
            candidate = hardening_gate._absolute_lexical_path(
                args.candidate_dir, "candidate"
            )
            chain = hardening_gate._open_directory_chain(
                candidate, label="candidate"
            )
            hardening_gate._close_directory_chain(chain)
            raw_boot_log = hardening_gate._absolute_lexical_path(
                args.raw_boot_log, "workspace raw boot log"
            )
            receipt_output = hardening_gate._absolute_lexical_path(
                args.receipt_output, "workspace receipt output"
            )
            if receipt_output.suffix != ".json":
                raise hardening_gate.QualificationError(
                    "workspace receipt output must end in .json"
                )
            if raw_boot_log != hardening_gate._workspace_raw_path(receipt_output):
                raise hardening_gate.QualificationError(
                    "workspace raw boot log name must be derived from its receipt"
                )
            hardening_gate._stable_regular_bytes(
                raw_boot_log,
                label="workspace raw boot log",
                maximum=64 * 1024,
                private=True,
            )
            if os.path.lexists(receipt_output):
                raise hardening_gate.QualificationError(
                    "workspace receipt output already exists"
                )
            for path, label in (
                (raw_boot_log, "workspace raw boot log"),
                (receipt_output, "workspace receipt output"),
            ):
                if hardening_gate._inside(path, candidate):
                    raise hardening_gate.QualificationError(
                        "%s must be outside the candidate" % label
                    )
                if hardening_gate._inside(path, ROOT):
                    raise hardening_gate.QualificationError(
                        "%s must be outside the qualification checkout" % label
                    )
            chain = hardening_gate._open_directory_chain(
                receipt_output.parent, label="workspace receipt output parent"
            )
            hardening_gate._close_directory_chain(chain)
            return args

        require_options(
            (
                "profile",
                "address",
                "candidate_dir",
                "workspace_erased_receipt",
                "workspace_nonblank_receipt",
                "raw_log",
                "result",
                "board_manufacturer",
                "board_model",
                "module_marking",
            )
        )
        if any(
            getattr(args, name) is not None
            for name in ("observation_kind", "raw_boot_log", "receipt_output")
        ):
            parser.error("workspace-receipt inputs are invalid in live mode")
        if not args.address.strip():
            parser.error("--address must be non-empty")
        if args.expect_agent is not None and args.expect_agent.strip() != "0.6.1":
            parser.error("--expect-agent must be exactly 0.6.1")
        args.address = args.address.strip()
        args.expect_agent = "0.6.1"
        expected_identity = PROFILE_BOARD_IDENTITIES[args.profile]
        for field in ("board_manufacturer", "board_model", "module_marking"):
            if getattr(args, field) != expected_identity[field]:
                parser.error(
                    "--%s must match the reviewed %s identity"
                    % (field.replace("_", "-"), args.profile)
                )
        candidate = hardening_gate._absolute_lexical_path(
            args.candidate_dir, "candidate"
        )
        chain = hardening_gate._open_directory_chain(
            candidate, label="candidate"
        )
        hardening_gate._close_directory_chain(chain)
        receipts = (
            args.workspace_erased_receipt,
            args.workspace_nonblank_receipt,
        )
        normalized_receipts = []
        for receipt in receipts:
            normalized = hardening_gate._absolute_lexical_path(
                receipt, "workspace receipt"
            )
            hardening_gate._stable_regular_bytes(
                normalized,
                label="workspace receipt",
                maximum=2 * 1024 * 1024,
                private=True,
            )
            normalized_receipts.append(normalized)
        if normalized_receipts[0] == normalized_receipts[1]:
            raise hardening_gate.QualificationError(
                "workspace receipts must be distinct"
            )

        raw_log = hardening_gate._absolute_lexical_path(
            args.raw_log, "hardening raw log"
        )
        result = hardening_gate._absolute_lexical_path(
            args.result, "hardening result"
        )
        if raw_log.suffix != ".jsonl" or result.suffix != ".json":
            raise hardening_gate.QualificationError(
                "hardening outputs must use .jsonl and .json"
            )
        if raw_log == result:
            raise hardening_gate.QualificationError(
                "hardening raw log and result must differ"
            )
        if os.path.lexists(raw_log) or os.path.lexists(result):
            raise hardening_gate.QualificationError(
                "hardening output already exists"
            )
        if hardening_gate._inside(raw_log, candidate) or hardening_gate._inside(
            result, candidate
        ):
            raise hardening_gate.QualificationError(
                "hardening outputs must be outside the candidate"
            )
        if hardening_gate._inside(raw_log, ROOT) or hardening_gate._inside(
            result, ROOT
        ):
            raise hardening_gate.QualificationError(
                "hardening outputs must be outside the qualification checkout"
            )
        for parent in (raw_log.parent, result.parent):
            chain = hardening_gate._open_directory_chain(
                parent, label="hardening output parent"
            )
            hardening_gate._close_directory_chain(chain)
    except hardening_gate.QualificationError as exc:
        parser.error(str(exc))
    return args


def main(argv=None):
    args = _parse_args(argv)
    if args.create_workspace_receipt:
        try:
            hardening_gate.create_workspace_receipt(
                candidate_dir=Path(args.candidate_dir),
                profile_id=args.profile,
                observation_kind=args.observation_kind,
                raw_boot_log=args.raw_boot_log,
                output_path=args.receipt_output,
                qualification_repo_root=ROOT,
            )
        except hardening_gate.QualificationError:
            print("V061 WORKSPACE RECEIPT ERROR (private details withheld)")
            return 2
        print(
            "V061 WORKSPACE RECEIPT PASS (profile=%s observation=%s)"
            % (args.profile, args.observation_kind)
        )
        return 0
    try:
        return asyncio.run(run(args))
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        caps = {
            "chip": PROFILE_CHIPS[args.profile],
            "agent": args.expect_agent,
        }
        print("V061 ERROR (HIL prerequisite or transport failed; private details withheld)")
        print(
            format_result(
                "FAIL",
                args.profile,
                caps,
                workspace_prerequisite(args),
            )
        )
        return 3


if __name__ == "__main__":
    sys.exit(main())
