#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Target-neutral PBLE/1 transport, identity, and INFO smoke bench."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import re
import sys

import _pble_wire as wire
from _pble_central import PbleCentral, rsp_status, status_name


LOCK_PATH = Path(__file__).resolve().parents[3] / "firmware" / "versions.lock"
EXPECT_MTU = 247
CHUNK_OVERHEAD = 18
DEVICE_ID_RE = re.compile(r"^[0-9A-F]{4}$")
REQUIRED_CAPS = {
    "proto", "agent", "chip", "mpy", "fs_root", "mtu", "window",
    "chunk", "free_mem", "has_sd", "has_identify", "identify_led",
    "auto_run", "device_id", "label",
}


def expected_agent_from_lock(path=LOCK_PATH):
    """Read [pyble].agent_version without adding a HIL TOML dependency."""
    in_pyble = False
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("["):
            in_pyble = line == "[pyble]"
        elif in_pyble:
            match = re.fullmatch(r'agent_version\s*=\s*"([^"]+)"', line)
            if match:
                return match.group(1)
    raise RuntimeError("versions.lock has no [pyble].agent_version")


def parse_caps(text):
    caps = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            caps[key.strip()] = value.strip()
    return caps


def _decimal(caps, key):
    value = caps.get(key, "")
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError("caps %s must be an unsigned decimal" % key)
    return int(value)


def validate_caps(caps, expect_chip, expect_agent):
    """Validate frozen §7 fields without reflecting identity values."""
    missing = sorted(REQUIRED_CAPS.difference(caps))
    if missing:
        raise ValueError("caps missing required keys: %s" % ",".join(missing))
    if caps["proto"] != "1":
        raise ValueError("caps proto must be 1")
    if caps["chip"] != expect_chip:
        raise ValueError("caps chip does not match --expect-chip")
    if caps["agent"] != expect_agent:
        raise ValueError("caps agent does not match --expect-agent")
    if not caps["mpy"] or caps["fs_root"] != "/":
        raise ValueError("caps MicroPython version/fs_root is invalid")

    mtu = _decimal(caps, "mtu")
    chunk = _decimal(caps, "chunk")
    if mtu != EXPECT_MTU:
        raise ValueError("caps mtu must be the negotiated 247-byte MTU")
    if chunk != mtu - CHUNK_OVERHEAD:
        raise ValueError("caps chunk must equal mtu - 18")
    if _decimal(caps, "window") < 1 or _decimal(caps, "free_mem") < 1:
        raise ValueError("caps window/free_mem must be positive")
    for key in ("has_sd", "has_identify", "auto_run"):
        if caps[key] not in ("0", "1"):
            raise ValueError("caps %s must be 0 or 1" % key)
    identify_led = _decimal(caps, "identify_led")
    if identify_led > 255:
        raise ValueError("caps identify_led must fit u8")
    if caps["has_identify"] == "0" and identify_led != 255:
        raise ValueError("caps without Identify must use identify_led=255")
    if DEVICE_ID_RE.fullmatch(caps["device_id"]) is None:
        raise ValueError("caps device_id format is invalid")
    if len(caps["label"].encode("utf-8")) > 24:
        raise ValueError("caps label exceeds the frozen 24-byte bound")
    return caps


def info_matches_device_info(device_info, info):
    """The live free heap may move; every other key and value must match."""
    if set(device_info) != set(info):
        return False
    left = dict(device_info)
    right = dict(info)
    left.pop("free_mem", None)
    right.pop("free_mem", None)
    return left == right


def format_result(status, caps):
    """Return public-safe evidence: never address, device_id, or label."""
    return (
        "TARGET SMOKE %s (chip=%s agent=%s mtu=%s chunk=%s window=%s)"
        % (
            status, caps.get("chip", "?"), caps.get("agent", "?"),
            caps.get("mtu", "?"), caps.get("chunk", "?"),
            caps.get("window", "?"),
        )
    )


async def run(args):
    if args.scan:
        # Scan output is operator-private discovery data and is never included
        # in the PASS/FAIL evidence line returned by format_result().
        for address, name in await PbleCentral.scan(timeout=args.scan_timeout):
            print("%s  %s" % (address, name))
        return 0

    advertisement_name = None
    for address, name in await PbleCentral.scan(timeout=args.scan_timeout):
        if address == args.address:
            advertisement_name = name
            break
    if advertisement_name is None:
        print("TARGET SMOKE FAIL (service-filtered advertisement not observed)")
        return 1

    central = await PbleCentral.connect(args.address)
    try:
        hello = await central.send_cmd(
            wire.OP_HELLO, 1, b"app=target-smoke\nversion=0\n"
        )
        if rsp_status(hello) != wire.ST_OK:
            raise ValueError("HELLO status is %s" % status_name(rsp_status(hello)))
        hello_caps = parse_caps(hello.payload[1:].decode(errors="replace"))
        validate_caps(hello_caps, args.expect_chip, args.expect_agent)
        central.confirm_caps_mtu(int(hello_caps["mtu"]))

        # Advertisement values are compared but never echoed into evidence.
        expected_name = hello_caps["label"] or "PyBLE-%s" % hello_caps["device_id"]
        if advertisement_name != expected_name:
            raise ValueError("advertisement name does not match caps identity")

        response = await central.send_cmd(wire.OP_DEVICE_INFO, 2)
        if rsp_status(response) != wire.ST_OK:
            raise ValueError(
                "DEVICE_INFO status is %s" % status_name(rsp_status(response))
            )
        device_info = parse_caps(response.payload[1:].decode(errors="replace"))
        info = parse_caps((await central.read_info()).decode(errors="replace"))
        validate_caps(device_info, args.expect_chip, args.expect_agent)
        validate_caps(info, args.expect_chip, args.expect_agent)
        if not info_matches_device_info(device_info, info):
            raise ValueError("INFO does not match DEVICE_INFO")
        if not info_matches_device_info(hello_caps, device_info):
            raise ValueError("HELLO caps do not match DEVICE_INFO")

        print(format_result("PASS", hello_caps))
        return 0
    except ValueError as exc:
        print("TARGET SMOKE FAIL (%s)" % exc)
        return 1
    finally:
        await central.disconnect()


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="target-neutral PBLE/1 transport and identity smoke (HIL)"
    )
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--scan-timeout", type=float, default=8.0)
    parser.add_argument("--address", help="private BLE address/UUID from --scan")
    parser.add_argument(
        "--expect-chip", help="exact port-defined PBLE/1 chip identifier"
    )
    parser.add_argument(
        "--expect-agent", default=expected_agent_from_lock(),
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
        print("TARGET SMOKE ERROR (HIL prerequisite or transport failed; private details withheld)")
        return 3


if __name__ == "__main__":
    sys.exit(main())
