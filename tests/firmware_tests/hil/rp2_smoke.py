# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# rpi-pico2-w transport + identity SMOKE (HIL H2, port spec P1/P7; F-27/GP2).
# Owned by firmware-test-author; a HOST-SIDE bench over _pble_central (bleak),
# never firmware. Talks only PBLE/1 to the board under test (SEC-8).
#
# H2 pass criteria (ports/rpi-pico2-w.md P1, protocol.md §2/§7):
#   - the advert carries the PyBLE service UUID (the filtered scan is the
#     proof) and the name `PyBLE-XXXX` (or the user label);
#   - MTU 247 is negotiated (caps mtu=247; when the BLE backend exposes a real
#     ATT MTU it must agree — never substituted as evidence);
#   - HELLO RSP is [status:u8]-prefixed, then the frozen §7 caps text with
#     chip=rpi-pico2-w, chunk=mtu-18=229, has_identify=0, identify_led=255,
#     device_id = 4 uppercase hex (from machine.unique_id(), never the MAC);
#   - an INFO characteristic read returns the same DEVICE_INFO caps payload
#     (compared with the live `free_mem` value excluded — the generator is
#     shared, but free heap legitimately moves between two reads).
#
# USAGE (HIL runner; pip install bleak):
#   python3 rp2_smoke.py --scan
#   python3 rp2_smoke.py --address <UUID/MAC>

import argparse
import asyncio
import re
import sys

import _pble_wire as wire
from _pble_central import PbleCentral, rsp_status, status_name

EXPECT_CHIP = "rpi-pico2-w"
EXPECT_MTU = 247
CHUNK_OVERHEAD = 18          # frozen: chunk = mtu - 18 (port spec P1)
DEFAULT_NAME_RE = r"^PyBLE-[0-9A-F]{4}$"
DEVICE_ID_RE = r"^[0-9A-F]{4}$"

# §7 frozen short caps tokens — every one must be present (additive-only wire).
REQUIRED_CAPS = (
    "proto", "agent", "chip", "mpy", "fs_root", "mtu", "window", "chunk",
    "free_mem", "has_sd", "has_identify", "identify_led", "auto_run",
    "device_id", "label",
)


class Checks:
    def __init__(self):
        self.failed = 0

    def check(self, desc, ok, detail=""):
        if ok:
            print("    ok   - %s" % desc)
        else:
            self.failed += 1
            print("    FAIL - %s%s" % (desc, (" (%s)" % detail) if detail else ""))
        return ok


def parse_caps(text):
    caps = {}
    for line in text.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            caps[k.strip()] = v.strip()
    return caps


async def run(args):
    if args.scan:
        for addr, name in await PbleCentral.scan():
            print("%s  %s" % (addr, name))
        return 0

    c = Checks()

    # Adv identity: the scan is filtered to the PyBLE service UUID, so finding
    # the address at all proves the advert carries the service (H2 first leg).
    adv_name = None
    for addr, name in await PbleCentral.scan():
        if addr == args.address:
            adv_name = name
            break
    central = await PbleCentral.connect(args.address)
    try:
        # HELLO is the first exchange (§7). RSP = [status:u8] + caps text.
        rsp = await central.send_cmd(wire.OP_HELLO, 1, b"app=rp2-smoke\nversion=0\n")
        c.check("HELLO RSP status is OK ([status]-prefixed)",
                rsp_status(rsp) == wire.ST_OK, status_name(rsp_status(rsp)))
        caps = parse_caps(rsp.payload[1:].decode(errors="replace"))

        missing = [k for k in REQUIRED_CAPS if k not in caps]
        c.check("caps carry every frozen §7 token", not missing,
                "missing: %s" % ",".join(missing))

        # Frozen §7 serialization: integers are decimal — proto is emitted as
        # the PBLE_PROTO_VERSION decimal ("1"), never the "PBLE/1" wordmark.
        c.check("caps proto=1", caps.get("proto") == "1",
                repr(caps.get("proto")))
        c.check("caps chip=%s" % EXPECT_CHIP, caps.get("chip") == EXPECT_CHIP,
                repr(caps.get("chip")))

        mtu = int(caps.get("mtu", "0") or 0)
        c.check("caps mtu=%d (negotiated, not the 23-byte default)" % EXPECT_MTU,
                mtu == EXPECT_MTU, "mtu=%d" % mtu)
        backend_ok = True
        backend_detail = ""
        if mtu:
            try:
                central.confirm_caps_mtu(mtu)   # backend must agree if it knows
            except ValueError as exc:
                backend_ok = False
                backend_detail = str(exc)
        c.check("backend ATT MTU agrees with the HELLO caps mtu (when exposed)",
                backend_ok, backend_detail)

        chunk = int(caps.get("chunk", "0") or 0)
        c.check("caps chunk = mtu - %d = %d" % (CHUNK_OVERHEAD, EXPECT_MTU - CHUNK_OVERHEAD),
                chunk == mtu - CHUNK_OVERHEAD and chunk == EXPECT_MTU - CHUNK_OVERHEAD,
                "chunk=%d" % chunk)

        c.check("caps has_identify=0 (no u8-representable identify LED, P1)",
                caps.get("has_identify") == "0", repr(caps.get("has_identify")))
        c.check("caps identify_led=255 (none)",
                caps.get("identify_led") == "255", repr(caps.get("identify_led")))
        c.check("caps auto_run is 0/1", caps.get("auto_run") in ("0", "1"),
                repr(caps.get("auto_run")))
        c.check("caps window >= 1", int(caps.get("window", "0") or 0) >= 1,
                repr(caps.get("window")))
        c.check("caps free_mem > 0", int(caps.get("free_mem", "0") or 0) > 0,
                repr(caps.get("free_mem")))

        dev_id = caps.get("device_id", "")
        c.check("device_id is 4 uppercase hex (unique_id-derived, never MAC)",
                re.match(DEVICE_ID_RE, dev_id) is not None, repr(dev_id))

        label = caps.get("label", "")
        if adv_name is None:
            print("    ..   - adv name not captured by this scan (backend cache); skipped")
        elif label:
            c.check("advertised name equals the user label", adv_name == label,
                    "adv=%r label=%r" % (adv_name, label))
        else:
            c.check("advertised name is PyBLE-%s (default, FR-BLE-5 twin)" % dev_id,
                    adv_name == "PyBLE-%s" % dev_id
                    or re.match(DEFAULT_NAME_RE, adv_name or "") is not None,
                    repr(adv_name))

        # INFO read == DEVICE_INFO caps payload (§7 invariant). free_mem is the
        # one live value allowed to move between the two reads.
        di = await central.send_cmd(wire.OP_DEVICE_INFO, 2)
        c.check("DEVICE_INFO RSP status is OK", rsp_status(di) == wire.ST_OK,
                status_name(rsp_status(di)))
        di_caps = parse_caps(di.payload[1:].decode(errors="replace"))
        info_caps = parse_caps((await central.read_info()).decode(errors="replace"))
        di_cmp = dict(di_caps); di_cmp.pop("free_mem", None)
        info_cmp = dict(info_caps); info_cmp.pop("free_mem", None)
        c.check("INFO characteristic read == DEVICE_INFO caps (free_mem excluded)",
                di_cmp == info_cmp and set(di_caps) == set(info_caps),
                "info-only:%s di-only:%s" % (
                    sorted(set(info_caps) - set(di_caps)),
                    sorted(set(di_caps) - set(info_caps))))

        ok = c.failed == 0
        print("RP2 SMOKE %s (chip=%s mtu=%s chunk=%s window=%s device_id=%s agent=%s)"
              % ("PASS" if ok else "FAIL", caps.get("chip"), caps.get("mtu"),
                 caps.get("chunk"), caps.get("window"), dev_id, caps.get("agent")))
        return 0 if ok else 1
    finally:
        await central.disconnect()


def main():
    p = argparse.ArgumentParser(description="rpi-pico2-w PBLE/1 transport+identity smoke (HIL H2)")
    p.add_argument("--scan", action="store_true", help="list PyBLE boards and exit")
    p.add_argument("--address", help="board address/UUID from --scan")
    args = p.parse_args()
    if not args.scan and not args.address:
        p.error("--scan or --address required")
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
