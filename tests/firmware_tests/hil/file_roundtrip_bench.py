# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# File ROUND-TRIP bench (HIL) — upload a file, then DOWNLOAD it back and
# byte-compare. Owned by firmware-test-author; a HOST-SIDE bench over
# _pble_central (bleak), never firmware.
#
# WHY IT EXISTS: the field-reported failure "an 11.9 kB upload succeeds but
# opening the same file from the board hangs" — the GET stream dropped chunks
# under TX backpressure (pble_fs.c ignored PBLE_TX_AGAIN). This bench exercises
# the download burst end-to-end at the negotiated MTU and PASSES only when the
# assembled bytes equal the uploaded bytes exactly (FR-FS/FR-PBLE-9 integrity).
# It reports up/down throughput; per OI-1 those numbers are MEASURED baselines,
# never hardcoded ceilings.
#
# The GET wait is DEADLINE-BOUNDED so the bench itself can never hang: on a
# stall it reports received/expected bytes — the diagnostic that localizes a
# dropped-chunk failure.
#
# USAGE (HIL runner; pip install bleak):
#   python3 file_roundtrip_bench.py --scan
#   python3 file_roundtrip_bench.py --address <UUID/MAC> [--size 12190]
#   python3 file_roundtrip_bench.py --address <UUID/MAC> --expect-chip esp32-s3

import argparse
import asyncio
import os
import sys
import time
import zlib

import _pble_wire as wire
from _pble_central import PbleCentral, rsp_status, status_name
from _pble_bench import DownloadVerifier

DEST = "/bench_roundtrip.bin"
GET_STALL_S = 10.0  # bench-side inactivity ceiling per chunk (diagnostic bound)
PUT_REWIND_S = 0.75  # no-ACK-progress interval that triggers a Go-Back-N rewind
DEFAULT_WINDOW = 4   # fallback W when caps omit `window=` (matches "up to W" client)


def _u16(v):
    return int(v).to_bytes(2, "little")


def _u32(v):
    return int(v).to_bytes(4, "little")


def _path_field(path):
    b = path.encode()
    return _u16(len(b)) + b


async def _hello(c, id_):
    rsp = await c.send_cmd(wire.OP_HELLO, id_, b"app=bench\nversion=0\n")
    if rsp_status(rsp) != wire.ST_OK:
        raise SystemExit("HELLO refused: %s" % status_name(rsp_status(rsp)))
    caps = {}
    for line in rsp.payload[1:].decode(errors="replace").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            caps[k.strip()] = v.strip()
    return caps


async def _put(c, data, chunk, window):
    """Windowed FILE_PUT sender honoring the ADVERTISED caps window (FR-FS-4).

    Keeps up to `window` unacknowledged chunks in flight past the cumulative
    watermark `c.last_ack` (AC-1), advances the base as `FILE_PUT_ACK{ack_offset}`
    retires one-or-more chunks (AC-2), and on an ACK stall rewinds the send
    cursor to `last_ack` and retransmits every chunk at/after the watermark —
    Go-Back-N recovery for the queue-full PUT_DATA drop the firmware receiver
    relies on (AC-3). `c.last_ack` is monotonic, so progress never regresses on a
    resend (AC-5). Resume is honored: the window starts at `resume_offset` (AC-4).
    The whole loop is deadline-bounded (GET_STALL_S) so the bench can never hang,
    reporting ack/want on a true stall (the dropped-chunk diagnostic)."""
    t0 = time.monotonic()
    rsp = await c.send_cmd(
        wire.OP_FILE_PUT_BEGIN, 2,
        _u32(len(data)) + _u32(zlib.crc32(data)) + _path_field(DEST))
    if rsp_status(rsp) != wire.ST_OK:
        raise SystemExit("PUT_BEGIN: %s" % status_name(rsp_status(rsp)))
    total = len(data)
    # resume_offset from PUT_BEGIN: the window starts here, loop otherwise same.
    next_off = int.from_bytes(rsp.payload[1:5], "little") if len(rsp.payload) >= 5 else 0
    c.last_ack = next_off
    win_bytes = max(1, window) * chunk    # <= `window` full chunks past last_ack
    seen_ack = c.last_ack                 # highest watermark observed so far
    last_progress = time.monotonic()      # last time the watermark advanced
    last_rewind = 0.0                     # throttle: one rewind per stall interval
    while c.last_ack < total:
        # Fill the window: never let outstanding bytes exceed `win_bytes`, i.e.
        # never more than `window` unacknowledged chunks in flight (AC-1).
        while next_off < total and (next_off - c.last_ack) < win_bytes:
            piece = data[next_off:next_off + chunk]
            await c.send_cmd_no_rsp(wire.OP_FILE_PUT_DATA, 0, _u32(next_off) + piece)
            next_off += len(piece)
        now = time.monotonic()
        if c.last_ack > seen_ack:
            # A cumulative ACK retired >=1 chunk: advance base, reset the clock.
            seen_ack = c.last_ack
            last_progress = now
        elif now - last_progress > GET_STALL_S:
            raise SystemExit("PUT stalled: ack=%d want=%d" % (c.last_ack, total))
        elif now - last_progress > PUT_REWIND_S and now - last_rewind > PUT_REWIND_S:
            # No ACK progress within the window: a chunk was dropped and the
            # board keeps re-ACKing the old watermark. Go-Back-N: rewind the
            # cursor to last_ack and resend from there (AC-3).
            next_off = c.last_ack
            last_rewind = now
        await asyncio.sleep(0.002)
    rsp = await c.send_cmd(wire.OP_FILE_PUT_END, 3, _u32(zlib.crc32(data)))
    if rsp_status(rsp) != wire.ST_OK:
        raise SystemExit("PUT_END: %s" % status_name(rsp_status(rsp)))
    return time.monotonic() - t0


async def _get(c, expected):
    """GET_BEGIN then drain GET_DATA events until GET_END. Deadline-bounded."""
    expected = bytes(expected)
    expect_len = len(expected)
    verifier = DownloadVerifier(expected)
    c.events.clear()
    t0 = time.monotonic()
    rsp = await c.send_cmd(wire.OP_FILE_GET_BEGIN, 4, _u32(0) + _path_field(DEST))
    if rsp_status(rsp) != wire.ST_OK:
        raise SystemExit("GET_BEGIN: %s" % status_name(rsp_status(rsp)))
    total = int.from_bytes(rsp.payload[1:5], "little")
    if total != expect_len:
        raise SystemExit("GET_BEGIN total=%d, expected %d" % (total, expect_len))

    end_crc = None
    consumed = 0
    last_data = time.monotonic()
    while end_crc is None:
        while consumed < len(c.events):
            f = c.events[consumed]
            consumed += 1
            if f.opcode == wire.OP_FILE_GET_DATA:
                if len(f.payload) <= 4:
                    raise SystemExit("GET_DATA payload is truncated")
                offset = int.from_bytes(f.payload[:4], "little")
                try:
                    verifier.feed(offset, f.payload[4:])
                except Exception as exc:
                    raise SystemExit("GET integrity: %s" % exc)
                last_data = time.monotonic()
            elif f.opcode == wire.OP_FILE_GET_END:
                if len(f.payload) != 4:
                    raise SystemExit("GET_END payload has the wrong length")
                end_crc = int.from_bytes(f.payload, "little")
        if end_crc is None:
            if time.monotonic() - last_data > GET_STALL_S:
                raise SystemExit(
                    "GET STALLED: received %d of %d bytes, no END — the "
                    "dropped-chunk failure" % (verifier.unique_bytes, total))
            await asyncio.sleep(0.002)
    try:
        got = verifier.finish(end_crc)
    except Exception as exc:
        raise SystemExit("GET integrity: %s" % exc)
    return got, end_crc, time.monotonic() - t0


async def run(args):
    if args.scan:
        for addr, name in await PbleCentral.scan():
            print("%s  %s" % (addr, name))
        return 0

    c = await PbleCentral.connect(args.address)
    try:
        caps = await _hello(c, 1)
        chip = caps.get("chip", "?")
        caps_mtu = int(caps.get("mtu", "0") or 0)
        if caps_mtu:
            # Never promote the write-fragmentation MTU until HELLO reports it;
            # if Bleak exposes a real backend MTU, the central also requires
            # agreement here.
            c.confirm_caps_mtu(caps_mtu)
        chunk = int(caps.get("chunk", "0") or 0) or max(20, c.mtu - 4)
        # W is advertised in HELLO caps (`window=`); the sender adapts to it —
        # "up to W" client semantics, fallback DEFAULT_WINDOW if caps omit it.
        window = int(caps.get("window", "") or DEFAULT_WINDOW)
        print("board: chip=%s mtu=%d chunk=%d window=%d" % (chip, c.mtu, chunk, window))
        if args.expect_chip and chip != args.expect_chip:
            raise SystemExit("wrong board: chip=%s (expected %s)" % (chip, args.expect_chip))

        data = os.urandom(args.size)
        up_s = await _put(c, data, chunk, window)
        print("PUT  %6d B in %5.2f s  (%6.0f B/s)" % (len(data), up_s, len(data) / up_s))

        got, end_crc, dn_s = await _get(c, data)
        print("GET  %6d B in %5.2f s  (%6.0f B/s)" % (len(got), dn_s, len(got) / dn_s))

        ok = got == data and end_crc == zlib.crc32(data)
        print("END crc=0x%08x  match=%s  bytes-equal=%s"
              % (end_crc, end_crc == zlib.crc32(data), got == data))
        # Cleanup: remove the bench artifact from the board.
        await c.send_cmd(wire.OP_FILE_DELETE, 5, _path_field(DEST))
        # Record the negotiated ATT MTU on the final line: it is the link fact the
        # OI-1 throughput numbers are read against (chunk = mtu - PBLE_CHUNK_OVERHEAD),
        # so the owner's measurement log captures the MTU the run actually saw.
        print("ROUNDTRIP %s (%s, %d bytes, mtu=%d)"
              % ("PASS" if ok else "FAIL", chip, args.size, c.mtu))
        return 0 if ok else 1
    finally:
        await c.disconnect()


def main():
    p = argparse.ArgumentParser(description="PBLE/1 file round-trip HIL bench")
    p.add_argument("--scan", action="store_true", help="list PyBLE boards and exit")
    p.add_argument("--address", help="board address/UUID from --scan")
    p.add_argument("--size", type=int, default=12190,
                   help="payload size in bytes (default: the reported 11.9 kB)")
    p.add_argument("--expect-chip", help="abort unless HELLO caps chip matches")
    args = p.parse_args()
    if not args.scan and not args.address:
        p.error("--scan or --address required")
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
