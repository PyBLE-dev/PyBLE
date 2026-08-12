#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Target-neutral PBLE/1 RUN/STOP lifecycle and console-flood HIL bench."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
import zlib

import _pble_wire as wire
from _pble_central import PbleCentral, rsp_status, status_name
import target_smoke


STOP_DEADLINE_S = 0.5
STATE_WAIT_S = 5.0
DONE_WAIT_S = 10.0
QUIET_WATCH_S = 1.0
BUSY_LOOP_SOURCE = b"while True: pass"
PRINT_FLOOD_SOURCE = b"while True: print('x')"
FIXTURE_PATH = "/target_hil_run.py"
FIXTURE_SOURCE = b"print('pyble-target-file-run')\n"
ST_IDLE, ST_RUNNING, ST_DONE, ST_ERROR = 0, 1, 2, 3


class Checks:
    def __init__(self):
        self.failed = 0

    def check(self, description, condition, detail=""):
        if condition:
            print("    ok   - %s" % description)
        else:
            self.failed += 1
            print(
                "    FAIL - %s%s"
                % (description, (" (%s)" % detail) if detail else "")
            )
        return condition


def install_tap(central):
    """Record every fully reassembled RSP/EVT in wire-arrival order."""
    log = []
    real_feed = central._re.feed

    def tapped(packet):
        frame = real_feed(packet)
        if frame is not None:
            log.append((time.monotonic(), frame))
        return frame

    central._re.feed = tapped
    return log


def _matching_indices(log, predicate):
    return [index for index, (_when, frame) in enumerate(log) if predicate(frame)]


def validate_stop_trace(log, stop_id, submitted_at):
    """Require one OK STOP RSP, then one idle, strictly inside 500 ms."""
    responses = _matching_indices(
        log,
        lambda frame: frame.type == wire.RSP
        and frame.opcode == wire.OP_STOP
        and frame.id == stop_id,
    )
    idle = _matching_indices(
        log,
        lambda frame: frame.type == wire.EVT
        and frame.opcode == wire.OP_RUN_STATE
        and frame.payload == bytes((ST_IDLE,)),
    )
    if len(responses) != 1 or len(idle) != 1:
        raise ValueError("STOP must yield exactly one matching RSP and one idle")
    response_index, idle_index = responses[0], idle[0]
    if rsp_status(log[response_index][1]) != wire.ST_OK:
        raise ValueError("STOP response is not OK")
    if response_index >= idle_index:
        raise ValueError("STOP RSP must precede RUN_STATE(idle)")
    terminal = [
        frame.payload[0]
        for _when, frame in log
        if frame.type == wire.EVT
        and frame.opcode == wire.OP_RUN_STATE
        and len(frame.payload) == 1
        and frame.payload[0] in (ST_DONE, ST_ERROR)
    ]
    if terminal:
        raise ValueError("stopped run must not later report done/error")
    latency = log[idle_index][0] - submitted_at
    if latency < 0 or latency >= STOP_DEADLINE_S:
        raise ValueError(
            "STOP terminal idle missed the strict 500 ms deadline (%d ms)"
            % int(latency * 1000)
        )
    return latency


def build_follow_up_source(nonce):
    """Build one bounded, injection-safe marker program for same-link proof."""
    if not isinstance(nonce, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", nonce) is None:
        raise ValueError("follow-up nonce must be 1..64 safe ASCII characters")
    return ("print('__PYBLE_FOLLOW_UP_%s__')" % nonce).encode("ascii")


async def _wait_for(log, start, predicate, timeout):
    deadline = time.monotonic() + timeout
    while True:
        matches = _matching_indices(log[start:], predicate)
        if matches:
            return start + matches[0]
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(0.02)


async def run_nonce_follow_up(checks, central, log, request_id, nonce, description):
    """Prove the same link still runs, streams, and terminates after STOP."""
    marker = ("__PYBLE_FOLLOW_UP_%s__" % nonce).encode("ascii")
    cursor = len(log)
    response = await central.send_cmd(
        wire.OP_RUN, request_id, bytes((1,)) + build_follow_up_source(nonce)
    )
    checks.check(
        "%s: same-link follow-up RUN RSP is OK" % description,
        rsp_status(response) == wire.ST_OK,
        status_name(rsp_status(response)),
    )
    done_index = await _wait_for(
        log,
        cursor,
        lambda frame: frame.type == wire.EVT
        and frame.opcode == wire.OP_RUN_STATE
        and frame.payload == bytes((ST_DONE,)),
        DONE_WAIT_S,
    )
    if not checks.check(
        "%s: same-link follow-up reaches done" % description,
        done_index is not None,
    ):
        return
    frames = [frame for _when, frame in log[cursor:done_index + 1]]
    console = b"".join(
        frame.payload[1:]
        for frame in frames
        if frame.type == wire.EVT
        and frame.opcode == wire.OP_CONSOLE_DATA
        and frame.payload
        and frame.payload[0] == 0
    )
    running = [
        index for index, frame in enumerate(frames)
        if frame.type == wire.EVT
        and frame.opcode == wire.OP_RUN_STATE
        and frame.payload == bytes((ST_RUNNING,))
    ]
    done = [
        index for index, frame in enumerate(frames)
        if frame.type == wire.EVT
        and frame.opcode == wire.OP_RUN_STATE
        and frame.payload == bytes((ST_DONE,))
    ]
    responses = [
        index for index, frame in enumerate(frames)
        if frame.type == wire.RSP and frame.opcode == wire.OP_RUN
        and frame.id == request_id and rsp_status(frame) == wire.ST_OK
    ]
    checks.check(
        "%s: follow-up RSP/running/done order is exact" % description,
        len(responses) == len(running) == len(done) == 1
        and responses[0] < running[0] < done[0],
    )
    checks.check(
        "%s: follow-up nonce returns through CONSOLE_DATA" % description,
        console.count(marker) == 1,
    )


async def run_and_stop(checks, central, log, request_id, source, description):
    """Run one runaway source, validate STOP, then prove same-link recovery."""
    cursor = len(log)
    response = await central.send_cmd(
        wire.OP_RUN, request_id, bytes((1,)) + source
    )
    checks.check(
        "%s: RUN RSP is OK" % description,
        rsp_status(response) == wire.ST_OK,
        status_name(rsp_status(response)),
    )
    running_index = await _wait_for(
        log,
        cursor,
        lambda frame: frame.type == wire.EVT
        and frame.opcode == wire.OP_RUN_STATE
        and frame.payload == bytes((ST_RUNNING,)),
        STATE_WAIT_S,
    )
    if not checks.check(
        "%s: RUN_STATE(running) arrives" % description,
        running_index is not None,
    ):
        return
    responses = _matching_indices(
        log[cursor:],
        lambda frame: frame.type == wire.RSP
        and frame.opcode == wire.OP_RUN
        and frame.id == request_id,
    )
    checks.check(
        "%s: RUN RSP precedes running" % description,
        len(responses) == 1 and cursor + responses[0] < running_index,
    )

    await asyncio.sleep(2.0)
    stop_cursor = len(log)
    submitted_at = time.monotonic()
    stop_id = request_id + 1
    await central.send_cmd(wire.OP_STOP, stop_id, timeout=STATE_WAIT_S)
    await _wait_for(
        log,
        stop_cursor,
        lambda frame: frame.type == wire.EVT
        and frame.opcode == wire.OP_RUN_STATE
        and frame.payload == bytes((ST_IDLE,)),
        STATE_WAIT_S,
    )
    await asyncio.sleep(QUIET_WATCH_S)
    try:
        latency = validate_stop_trace(log[stop_cursor:], stop_id, submitted_at)
    except ValueError as exc:
        checks.check("%s: authoritative STOP trace" % description, False, str(exc))
        return
    checks.check(
        "%s: one OK STOP RSP precedes one idle in <500 ms" % description,
        True,
        "%.0f ms" % (latency * 1000),
    )

    nonce = os.urandom(6).hex()
    await run_nonce_follow_up(
        checks, central, log, request_id + 2, nonce, description
    )


async def put_small_file(central, path, data, first_id):
    encoded_path = path.encode("utf-8")
    checksum = zlib.crc32(data) & 0xFFFFFFFF
    response = await central.send_cmd(
        wire.OP_FILE_PUT_BEGIN,
        first_id,
        len(data).to_bytes(4, "little")
        + checksum.to_bytes(4, "little")
        + len(encoded_path).to_bytes(2, "little")
        + encoded_path,
    )
    if rsp_status(response) != wire.ST_OK:
        raise ValueError(
            "fixture PUT_BEGIN failed: %s"
            % status_name(rsp_status(response))
        )
    central.last_ack = 0
    await central.send_cmd_no_rsp(
        wire.OP_FILE_PUT_DATA, 0, (0).to_bytes(4, "little") + data
    )
    deadline = time.monotonic() + DONE_WAIT_S
    while central.last_ack < len(data):
        if time.monotonic() >= deadline:
            raise ValueError("fixture upload stalled")
        await asyncio.sleep(0.01)
    response = await central.send_cmd(
        wire.OP_FILE_PUT_END, first_id + 1, checksum.to_bytes(4, "little")
    )
    if rsp_status(response) != wire.ST_OK:
        raise ValueError("fixture PUT_END failed")


def format_result(status, caps):
    return "TARGET RUN/STOP %s (chip=%s agent=%s)" % (
        status, caps.get("chip", "?"), caps.get("agent", "?"),
    )


async def run(args):
    if args.scan:
        for address, name in await PbleCentral.scan(timeout=args.scan_timeout):
            print("%s  %s" % (address, name))
        return 0

    checks = Checks()
    central = await PbleCentral.connect(args.address)
    log = install_tap(central)
    caps = {}
    try:
        hello = await central.send_cmd(
            wire.OP_HELLO, 1, b"app=target-run-stop\nversion=0\n"
        )
        if rsp_status(hello) != wire.ST_OK:
            raise ValueError("HELLO was refused")
        caps = target_smoke.parse_caps(
            hello.payload[1:].decode(errors="replace")
        )
        target_smoke.validate_caps(caps, args.expect_chip, args.expect_agent)
        central.confirm_caps_mtu(int(caps["mtu"]))

        await run_and_stop(
            checks, central, log, 10, BUSY_LOOP_SOURCE, "busy-loop"
        )
        await run_and_stop(
            checks, central, log, 20, PRINT_FLOOD_SOURCE, "print-flood"
        )

        cursor = len(log)
        response = await central.send_cmd(wire.OP_STOP, 30)
        checks.check(
            "idle STOP is idempotent",
            rsp_status(response) == wire.ST_OK,
            status_name(rsp_status(response)),
        )
        await asyncio.sleep(QUIET_WATCH_S)
        stray = [
            frame for _when, frame in log[cursor:]
            if frame.type == wire.EVT and frame.opcode == wire.OP_RUN_STATE
        ]
        checks.check("idle STOP emits no RUN_STATE", not stray)

        await put_small_file(central, FIXTURE_PATH, FIXTURE_SOURCE, 40)
        cursor = len(log)
        response = await central.send_cmd(
            wire.OP_RUN, 42, bytes((0,)) + FIXTURE_PATH.encode("utf-8")
        )
        checks.check(
            "file-mode RUN RSP is OK",
            rsp_status(response) == wire.ST_OK,
            status_name(rsp_status(response)),
        )
        done = await _wait_for(
            log,
            cursor,
            lambda frame: frame.type == wire.EVT
            and frame.opcode == wire.OP_RUN_STATE
            and frame.payload == bytes((ST_DONE,)),
            DONE_WAIT_S,
        )
        checks.check("file-mode bounded run reaches done", done is not None)
        encoded_path = FIXTURE_PATH.encode("utf-8")
        await central.send_cmd(
            wire.OP_FILE_DELETE,
            43,
            len(encoded_path).to_bytes(2, "little") + encoded_path,
        )

        status = "PASS" if checks.failed == 0 else "FAIL"
        print(format_result(status, caps))
        return 0 if checks.failed == 0 else 1
    except ValueError as exc:
        print("TARGET RUN/STOP FAIL (%s)" % exc)
        return 1
    finally:
        await central.disconnect()


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="target-neutral PBLE/1 RUN/STOP lifecycle bench (HIL)"
    )
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--scan-timeout", type=float, default=8.0)
    parser.add_argument("--address", help="private BLE address/UUID from --scan")
    parser.add_argument("--expect-chip", help="exact port-defined PBLE/1 chip ID")
    parser.add_argument(
        "--expect-agent", default=target_smoke.expected_agent_from_lock(),
        help="expected agent SemVer (default: versions.lock)",
    )
    args = parser.parse_args(argv)
    if not args.scan:
        if not args.address:
            parser.error("--address is required unless --scan is used")
        if not args.expect_chip or not args.expect_chip.strip():
            parser.error("--expect-chip is required for every non-scan HIL run")
        args.expect_chip = args.expect_chip.strip()
        if not args.expect_agent or not args.expect_agent.strip():
            parser.error("--expect-agent must be non-empty")
        args.expect_agent = args.expect_agent.strip()
    return args


def main(argv=None):
    args = _parse_args(argv)
    try:
        return asyncio.run(run(args))
    except RuntimeError:
        print("TARGET RUN/STOP ERROR (HIL prerequisite or transport failed; private details withheld)")
        return 3


if __name__ == "__main__":
    sys.exit(main())
