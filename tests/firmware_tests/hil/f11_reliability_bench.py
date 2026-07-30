# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# F-11 — Multi-file reliability bench (HIL).  [red]/bench, firmware-test-author.
#
# WHAT IT IS: a HOST-SIDE BLE driver (over bleak) that uploads N files back-to-
# back at the negotiated MTU (the app requests 247, §2) to a real PyBLE board and
# ASSERTS the reliability contract, then REPORTS a throughput baseline. It is
# ENTIRELY a test artifact — there is NO firmware [green] for F-11 (architect
# DoR). It is HIL-ONLY: it needs an exact-profile board running the candidate
# firmware plus `pip install bleak`. Its pure caps-selection helper runs in host
# CI so the release bench cannot silently drift from the frozen HELLO contract.
#
# ACCEPTANCE CRITERIA CAPTURED (protocol.md §5 windowed upload FROZEN; §3 framing;
# firmware/specs.md):
#   * NFR-REL-5 — a multi-file transfer completes with every file intact; no file
#     is silently dropped or corrupted across the run.
#   * FR-FS-6/FR-FS-14 — FILE_PUT_END reports OK only on a whole-file CRC match;
#     the bench independently re-verifies each dest via FILE_STAT{size,crc}.
#   * FR-FS-4/5, NFR-PERF-2 — windowed (W) Go-Back-N upload driven by cumulative
#     FILE_PUT_ACK{watermark}; the bench counts retransmits as a reliability
#     signal but the PASS gate is whole-file integrity, not zero retransmits.
#   * NFR-PERF-1 / NFR-FP-TPUT — captures a throughput number at MTU 247.
#     *** OI-1: this number is a BASELINE the bench MEASURES and PRINTS; it is
#     NEVER a hardcoded ceiling. A pass/fail floor is applied ONLY if the
#     architect/build-smith supplies one via --tput-floor-bps / PYBLE_TPUT_FLOOR_BPS
#     (frozen at M3). With no floor, throughput is report-only. ***
#   * SEC-11 — with --relabel the bench sets a device label mid-run and asserts
#     uploads behave IDENTICALLY (identity is display-only, never gates access).
#
# WIRE (all FROZEN, referenced not redefined — protocol.md §5):
#   FILE_PUT_BEGIN 0x15 CMD [total:u32][crc32:u32][plen:u16][path] -> RSP[status](+[resume_offset:u32])
#   FILE_PUT_DATA  0x16 CMD (no RSP) [offset:u32][bytes]
#   FILE_PUT_ACK   0x41 EVT id0 [ack_offset:u32] = highest contiguous byte written
#   FILE_PUT_END   0x17 CMD [crc32:u32] -> RSP[status]
#   FILE_STAT      0x11 CMD [plen:u16][path] -> RSP[status](+[size:u32][crc32:u32])
#   MKDIR          0x19 CMD [plen:u16][path] -> RSP[status]
#
# USAGE (HIL runner):
#   python3 f11_reliability_bench.py --scan
#   python3 f11_reliability_bench.py --address <UUID/MAC> --expect-chip esp32-s3 --files 20 --size 16384
#   python3 f11_reliability_bench.py --address <addr> --expect-chip esp32 --tput-floor-bps 4000
# Exit 0 = reliability PASS (+ throughput report/floor); non-zero = a file failed
# integrity, or a supplied throughput floor was not met.

import argparse
import asyncio
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import _pble_wire as wire                       # noqa: E402
from _pble_central import (  # noqa: E402
    REQUESTED_MTU,
    PbleCentral,
    rsp_status,
    status_name,
)

# §5: paths are [plen:u16][path UTF-8], max 128 B. HELLO's frozen caps text
# supplies the upload window and single-packet chunk. A diagnostic override may
# only reduce those advertised limits.
FRAME_OVERHEAD = 18
HELLO_PAYLOAD = (
    b"proto_versions=1\n"
    b"app_name=hil-f11\n"
    b"app_version=0"
)


def _path_payload(path):
    p = path.encode("utf-8")
    return len(p).to_bytes(2, "little") + p


def _parse_caps(payload):
    """Parse frozen §7 newline key=value caps; reject ambiguous duplicates."""
    try:
        text = bytes(payload).decode("ascii", errors="strict")
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("HELLO caps are not strict ASCII") from exc
    caps = {}
    for line in text.splitlines():
        if not line:
            continue
        if "=" not in line:
            raise ValueError("HELLO caps contain a non key=value line")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in caps:
            raise ValueError("HELLO caps contain an empty or duplicate key")
        caps[key] = value.strip()
    return caps


def _positive_cap(caps, key):
    raw = caps.get(key)
    if raw is None:
        raise ValueError("HELLO caps are missing %s" % key)
    try:
        value = int(raw, 10)
    except (TypeError, ValueError) as exc:
        raise ValueError("HELLO cap %s is not an integer" % key) from exc
    if value <= 0:
        raise ValueError("HELLO cap %s must be positive" % key)
    return value


def _select_transfer_settings(
        caps,
        *,
        mtu,
        expected_chip=None,
        window_override=None,
        chunk_override=None):
    """Return (canonical chip, W, chunk), bounded by the advertised caps."""
    chip = str(caps.get("chip", "")).strip()
    if not chip:
        raise ValueError("HELLO caps are missing chip")
    if expected_chip and chip != expected_chip:
        raise ValueError("wrong board: chip=%s (expected %s)" % (
            chip, expected_chip))

    advertised_window = _positive_cap(caps, "window")
    advertised_chunk = _positive_cap(caps, "chunk")
    max_single_packet_chunk = int(mtu) - FRAME_OVERHEAD
    if max_single_packet_chunk <= 0:
        raise ValueError("negotiated MTU is too small for PBLE/1 FILE_PUT_DATA")
    if advertised_chunk > max_single_packet_chunk:
        raise ValueError(
            "advertised chunk=%d exceeds MTU-derived limit %d" % (
                advertised_chunk, max_single_packet_chunk))

    window = advertised_window
    if window_override not in (None, 0):
        window = int(window_override)
        if window <= 0 or window > advertised_window:
            raise ValueError(
                "window override must be 1..%d" % advertised_window)

    chunk = advertised_chunk
    if chunk_override not in (None, 0):
        chunk = int(chunk_override)
        if chunk <= 0 or chunk > advertised_chunk:
            raise ValueError(
                "chunk override must be 1..%d" % advertised_chunk)
    return chip, window, chunk


def _gen(size, seed):
    r = random.Random(seed)
    return bytes(r.getrandbits(8) for _ in range(size))


class FileResult:
    def __init__(self, path, size):
        self.path = path
        self.size = size
        self.ok = False
        self.reason = ""
        self.retransmits = 0
        self.begin_resume_offset = 0
        self.stat_verified = False


async def _upload_one(c, path, data, window, chunk, next_id,
                      ack_timeout, end_timeout):
    """Windowed Go-Back-N upload of one file. Returns a FileResult."""
    res = FileResult(path, len(data))
    total = len(data)
    crc = wire.crc32(data)

    begin = (total.to_bytes(4, "little") + crc.to_bytes(4, "little")
             + _path_payload(path))
    r = await c.send_cmd(wire.OP_FILE_PUT_BEGIN, next_id(), begin)
    st = rsp_status(r)
    if st != wire.ST_OK:
        res.reason = "FILE_PUT_BEGIN -> %s" % status_name(st)
        return res
    # resume_offset (S6/F-10): starts here if a verified partial prefix exists.
    res.begin_resume_offset = (int.from_bytes(r.payload[1:5], "little")
                               if len(r.payload) >= 5 else 0)

    # Reset the shared ACK watermark to this transfer's start.
    c.last_ack = res.begin_resume_offset
    watermark = res.begin_resume_offset
    next_off = watermark

    loop = asyncio.get_event_loop()
    while watermark < total:
        # Fill the window with in-order chunks.
        while next_off < total and (next_off - watermark) < window * chunk:
            piece = data[next_off:next_off + chunk]
            await c.send_cmd_no_rsp(
                wire.OP_FILE_PUT_DATA,
                0,  # DATA is no-RSP; id irrelevant
                next_off.to_bytes(4, "little") + piece)
            next_off += len(piece)

        # Wait for the cumulative ACK to advance the watermark.
        deadline = loop.time() + ack_timeout
        advanced = False
        while loop.time() < deadline:
            if c.last_ack > watermark:
                watermark = c.last_ack
                next_off = max(next_off, watermark)
                advanced = True
                break
            await asyncio.sleep(0.01)
        if not advanced:
            # Go-Back-N: no progress within the timeout -> resend from watermark.
            if next_off <= watermark:
                res.reason = "stalled at watermark %d/%d (no ACK)" % (watermark, total)
                return res
            res.retransmits += 1
            next_off = watermark

    end = crc.to_bytes(4, "little")
    r = await c.send_cmd(wire.OP_FILE_PUT_END, next_id(), end, timeout=end_timeout)
    st = rsp_status(r)
    if st != wire.ST_OK:
        res.reason = "FILE_PUT_END -> %s (watermark=%d/%d)" % (status_name(st), watermark, total)
        return res

    # Independent whole-file re-verification via FILE_STAT (FR-FS-6/14).
    r = await c.send_cmd(wire.OP_FILE_STAT, next_id(), _path_payload(path))
    st = rsp_status(r)
    if st == wire.ST_OK and len(r.payload) >= 9:
        got_size = int.from_bytes(r.payload[1:5], "little")
        got_crc = int.from_bytes(r.payload[5:9], "little")
        res.stat_verified = (got_size == total and got_crc == crc)
        if not res.stat_verified:
            res.reason = "FILE_STAT mismatch: size %d/%d crc 0x%08x/0x%08x" % (
                got_size, total, got_crc, crc)
            return res
    else:
        res.reason = "FILE_STAT -> %s (cannot re-verify)" % status_name(st)
        return res

    res.ok = True
    return res


async def run_bench(args):
    print("== F-11 multi-file reliability bench (HIL) ==")
    if args.scan:
        boards = await PbleCentral.scan(timeout=args.scan_timeout)
        if not boards:
            print("no PyBLE boards found (filtered to the service UUID)")
            return 2
        for addr, name in boards:
            print("  %s  %s" % (addr, name))
        return 0

    if not args.address:
        print("error: --address <UUID/MAC> required (or --scan)")
        return 2

    c = await PbleCentral.connect(args.address)
    try:
        _id = [0]

        def next_id():
            _id[0] = (_id[0] % 255) + 1
            return _id[0]

        # HELLO is the mandatory first exchange. Release pacing comes from its
        # advertised caps, never an independent bench default.
        try:
            r = await c.send_cmd(
                wire.OP_HELLO,
                next_id(),
                HELLO_PAYLOAD,
                timeout=5.0,
            )
            st = rsp_status(r)
            if st != wire.ST_OK:
                print("error: HELLO -> %s" % status_name(st))
                return 2
            caps = _parse_caps(r.payload[1:])
            # HELLO itself uses the conservative ATT-default fragmentation.
            # Only validated device-side caps may enable larger writes; an
            # unknown Bleak backend MTU remains unknown evidence.
            caps_mtu = _positive_cap(caps, "mtu")
            c.confirm_caps_mtu(caps_mtu)
            mtu = c.mtu
            chip, window, chunk = _select_transfer_settings(
                caps,
                mtu=mtu,
                expected_chip=args.expect_chip,
                window_override=args.window,
                chunk_override=args.chunk_size,
            )
        except (ValueError, UnicodeError) as exc:
            print("error: invalid HELLO caps: %s" % exc)
            return 2

        print("connected: chip=%s mtu=%d chunk=%d window=%d files=%d "
              "size=%dB dir=%s"
              % (chip, mtu, chunk, window, args.files, args.size, args.dir))
        if mtu < REQUESTED_MTU:
            print("  note: negotiated MTU %d < requested %d (platform-capped); "
                  "throughput is reported at the actual MTU"
                  % (mtu, REQUESTED_MTU))

        # Jail-friendly working dir under fs_root (idempotent MKDIR).
        if args.dir:
            r = await c.send_cmd(wire.OP_MKDIR, next_id(), _path_payload(args.dir))
            st = rsp_status(r)
            if st not in (wire.ST_OK,):
                print("  MKDIR %s -> %s (continuing; may already exist)"
                      % (args.dir, status_name(st)))

        results = []
        t0 = time.monotonic()
        for i in range(args.files):
            path = ("%s/bench_%03d.bin" % (args.dir, i)) if args.dir else ("bench_%03d.bin" % i)
            data = _gen(args.size, seed=(args.seed + i))
            res = await _upload_one(c, path, data, window, chunk, next_id,
                                    args.ack_timeout, args.end_timeout)
            results.append(res)
            flag = "OK " if res.ok else "FAIL"
            extra = "" if res.ok else ("  <- %s" % res.reason)
            print("  [%3d/%3d] %s %-28s %dB rtx=%d%s"
                  % (i + 1, args.files, flag, path, res.size, res.retransmits, extra))
            # Optional mid-run relabel: SEC-11 identity-never-gates-access probe.
            if args.relabel and i == args.files // 2:
                lbl = args.relabel.encode("utf-8")[:24]
                r = await c.send_cmd(wire.OP_SET_LABEL, next_id(), lbl)
                print("  SET_LABEL(%r) -> %s (uploads must be unaffected — SEC-11)"
                      % (lbl, status_name(rsp_status(r))))
        elapsed = time.monotonic() - t0

        ok_files = sum(1 for r in results if r.ok)
        total_bytes = sum(r.size for r in results if r.ok)
        total_rtx = sum(r.retransmits for r in results)
        tput = (total_bytes / elapsed) if elapsed > 0 else 0.0

        print("-" * 56)
        print("files OK           : %d / %d" % (ok_files, args.files))
        print("bytes transferred  : %d" % total_bytes)
        print("elapsed            : %.2f s" % elapsed)
        print("throughput         : %.0f B/s (%.1f kbit/s)  [OI-1 baseline @ MTU %d]"
              % (tput, tput * 8 / 1000.0, mtu))
        print("retransmits (total): %d" % total_rtx)

        # --- PASS gate: RELIABILITY (integrity), always enforced --------------
        failed = [r for r in results if not r.ok]
        if failed:
            print("RESULT: FAIL — %d file(s) failed whole-file integrity "
                  "(NFR-REL-5/FR-FS-6/14):" % len(failed))
            for r in failed:
                print("   %s: %s" % (r.path, r.reason))
            return 1

        # --- Optional throughput floor: ONLY if the architect supplied one ----
        if args.tput_floor_bps is not None:
            if tput < args.tput_floor_bps:
                print("RESULT: FAIL — throughput %.0f B/s below the supplied floor "
                      "%.0f B/s (NFR-FP-TPUT)" % (tput, args.tput_floor_bps))
                return 1
            print("RESULT: PASS — reliability intact AND throughput >= supplied "
                  "floor %.0f B/s" % args.tput_floor_bps)
        else:
            print("RESULT: PASS — reliability intact. Throughput is a REPORTED "
                  "OI-1 baseline (no floor supplied; the ceiling is frozen at M3, "
                  "never invented by the bench).")
        return 0
    finally:
        await c.disconnect()


def _parse_args(argv=None):
    ap = argparse.ArgumentParser(description="F-11 multi-file reliability bench (HIL, PBLE/1 over BLE)")
    ap.add_argument("--scan", action="store_true", help="scan for PyBLE boards and exit")
    ap.add_argument("--scan-timeout", type=float, default=8.0)
    ap.add_argument("--address", help="BLE address/UUID of the board under test")
    ap.add_argument(
        "--expect-chip",
        help="abort unless HELLO caps use this canonical PBLE/1 target ID",
    )
    ap.add_argument("--files", type=int, default=10, help="number of files to upload back-to-back")
    ap.add_argument("--size", type=int, default=8192, help="bytes per file")
    ap.add_argument("--dir", default="bench", help="workspace subdir (jailed under fs_root); '' for root")
    ap.add_argument(
        "--window",
        type=int,
        default=0,
        help="diagnostic W override (0 = HELLO cap; must not exceed cap)",
    )
    ap.add_argument(
        "--chunk-size",
        type=int,
        default=0,
        help="diagnostic DATA-byte override (0 = HELLO cap; must not exceed cap)",
    )
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--ack-timeout", type=float, default=3.0, help="per-window ACK wait before Go-Back-N resend")
    ap.add_argument("--end-timeout", type=float, default=20.0, help="FILE_PUT_END whole-file CRC RSP wait")
    ap.add_argument("--tput-floor-bps", type=float, default=None,
                    help="OPTIONAL throughput floor in B/s; applied ONLY if supplied (OI-1: never invented)")
    ap.add_argument("--relabel", default=None, help="set this device label mid-run to prove SEC-11 (identity never gates access)")
    args = ap.parse_args(argv)
    if not args.scan:
        if not args.address:
            ap.error("--address <UUID/MAC> is required unless --scan is used")
        if not args.expect_chip:
            ap.error("--expect-chip is required for every non-scan HIL run")
    if args.tput_floor_bps is None:
        env = os.environ.get("PYBLE_TPUT_FLOOR_BPS")
        if env:
            args.tput_floor_bps = float(env)
    return args


def main(argv=None):
    args = _parse_args(argv)
    try:
        return asyncio.run(run_bench(args))
    except RuntimeError as exc:
        print("HIL prerequisite: %s" % exc)
        return 3


if __name__ == "__main__":
    sys.exit(main())
