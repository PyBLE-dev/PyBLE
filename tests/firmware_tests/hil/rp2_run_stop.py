# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# rpi-pico2-w RUN/STOP bench (HIL H6, port spec P2/P3; F-27/GP2). Owned by
# firmware-test-author; a HOST-SIDE bench over _pble_central (bleak), never
# firmware.
#
# H6 pass criteria (ports/rpi-pico2-w.md P2/P3, protocol.md §6):
#   - RSP{OK} precedes RUN_STATE(running) on EVERY run (handler answers inline
#     in scheduled context; the supervisor emits running after pickup);
#   - STOP lands < 500 ms into `while True: pass` AND `while True: print("x")`
#     — the dupterm 0x03 + os.dupterm_notify KeyboardInterrupt path;
#   - the terminal state after STOP is `idle` (stopped != done/error);
#   - STOP while idle -> RSP{OK} with NO RUN_STATE emitted (idempotent);
#   - RUN of /main.py (file mode 0) follows the same lifecycle to `done`.
#
# Frame-arrival ORDER is proven by tapping the central's reassembler: every
# completed frame (RSP and EVT alike) is appended to one timestamped log in
# the order the notify path completed it — no cross-task race can reorder it.
#
# USAGE (HIL runner; pip install bleak):
#   python3 rp2_run_stop.py --scan
#   python3 rp2_run_stop.py --address <UUID/MAC>

import argparse
import asyncio
import sys
import time
import zlib

import _pble_wire as wire
from _pble_central import PbleCentral, rsp_status, status_name

STOP_DEADLINE_S = 0.5     # H6: STOP must land inside this bound
STATE_WAIT_S = 5.0        # bench-side ceiling for an expected RUN_STATE
DONE_WAIT_S = 10.0        # ceiling for a finite script to reach done
QUIET_WATCH_S = 1.0       # window in which no further RUN_STATE may arrive
MAIN_PATH = "/main.py"
MAIN_SOURCE = b"print('pyble-main-ran')\n"

ST_IDLE, ST_RUNNING, ST_DONE, ST_ERROR = 0, 1, 2, 3
STATE_NAME = {ST_IDLE: "idle", ST_RUNNING: "running", ST_DONE: "done", ST_ERROR: "error"}


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


def install_tap(central):
    """Record every completed frame (RSP + EVT) in arrival order, timestamped.

    The central's _on_notify feeds packets through its Reassembler instance;
    shadowing that instance's `feed` observes each completed frame exactly at
    the point the notify path decodes it, so the log order IS the wire order.
    """
    log = []
    real_feed = central._re.feed

    def tapped(packet):
        frame = real_feed(packet)
        if frame is not None:
            log.append((time.monotonic(), frame))
        return frame

    central._re.feed = tapped
    return log


def find_rsp(log, start, opcode, id_):
    for i in range(start, len(log)):
        _, f = log[i]
        if f.type == wire.RSP and f.opcode == opcode and f.id == id_:
            return i
    return None


def find_run_state(log, start, state):
    for i in range(start, len(log)):
        _, f = log[i]
        if (f.type == wire.EVT and f.opcode == wire.OP_RUN_STATE
                and f.payload and f.payload[0] == state):
            return i
    return None


async def wait_run_state(log, start, state, timeout):
    deadline = time.monotonic() + timeout
    while True:
        i = find_run_state(log, start, state)
        if i is not None:
            return i
        if time.monotonic() > deadline:
            return None
        await asyncio.sleep(0.02)


async def run_and_stop(c, central, log, id_, source, hold_s, desc):
    """RUN a source snippet, STOP it, and assert the H6 lifecycle contract."""
    cursor = len(log)
    rsp = await central.send_cmd(wire.OP_RUN, id_, bytes((1,)) + source)
    c.check("%s: RUN RSP status is OK" % desc, rsp_status(rsp) == wire.ST_OK,
            status_name(rsp_status(rsp)))

    run_i = await wait_run_state(log, cursor, ST_RUNNING, STATE_WAIT_S)
    if not c.check("%s: RUN_STATE(running) arrives" % desc, run_i is not None):
        return
    rsp_i = find_rsp(log, cursor, wire.OP_RUN, id_)
    c.check("%s: RSP precedes RUN_STATE(running) on the wire" % desc,
            rsp_i is not None and rsp_i < run_i,
            "rsp_index=%s running_index=%s" % (rsp_i, run_i))

    await asyncio.sleep(hold_s)

    cursor = len(log)
    t_stop = time.monotonic()
    rsp = await central.send_cmd(wire.OP_STOP, id_ + 1, timeout=STATE_WAIT_S)
    c.check("%s: STOP RSP status is OK" % desc, rsp_status(rsp) == wire.ST_OK,
            status_name(rsp_status(rsp)))
    idle_i = await wait_run_state(log, cursor, ST_IDLE, STATE_WAIT_S)
    if not c.check("%s: RUN_STATE(idle) arrives after STOP" % desc, idle_i is not None):
        return
    latency = log[idle_i][0] - t_stop
    c.check("%s: STOP lands < %.0f ms (dupterm 0x03 path)" % (desc, STOP_DEADLINE_S * 1e3),
            latency < STOP_DEADLINE_S, "%.0f ms" % (latency * 1e3))

    # Terminal state is idle and STAYS idle: no done/error may follow a STOP.
    await asyncio.sleep(QUIET_WATCH_S)
    late_done = find_run_state(log, idle_i + 1, ST_DONE)
    late_err = find_run_state(log, idle_i + 1, ST_ERROR)
    c.check("%s: stopped run terminates as idle, never done/error" % desc,
            late_done is None and late_err is None)


async def put_small_file(central, path, data, first_id):
    """Minimal single-chunk windowed PUT for a bench fixture file."""
    rsp = await central.send_cmd(
        wire.OP_FILE_PUT_BEGIN, first_id,
        len(data).to_bytes(4, "little") + (zlib.crc32(data) & 0xFFFFFFFF).to_bytes(4, "little")
        + len(path.encode()).to_bytes(2, "little") + path.encode())
    if rsp_status(rsp) != wire.ST_OK:
        raise SystemExit("PUT_BEGIN %s: %s" % (path, status_name(rsp_status(rsp))))
    central.last_ack = 0
    await central.send_cmd_no_rsp(wire.OP_FILE_PUT_DATA, 0, (0).to_bytes(4, "little") + data)
    deadline = time.monotonic() + DONE_WAIT_S
    while central.last_ack < len(data):
        if time.monotonic() > deadline:
            raise SystemExit("PUT %s stalled: ack=%d want=%d"
                             % (path, central.last_ack, len(data)))
        await asyncio.sleep(0.01)
    rsp = await central.send_cmd(wire.OP_FILE_PUT_END, first_id + 1,
                                 (zlib.crc32(data) & 0xFFFFFFFF).to_bytes(4, "little"))
    if rsp_status(rsp) != wire.ST_OK:
        raise SystemExit("PUT_END %s: %s" % (path, status_name(rsp_status(rsp))))


async def run(args):
    if args.scan:
        for addr, name in await PbleCentral.scan():
            print("%s  %s" % (addr, name))
        return 0

    c = Checks()
    central = await PbleCentral.connect(args.address)
    log = install_tap(central)
    try:
        # HELLO first (§7); adopt the negotiated MTU for fragmentation.
        rsp = await central.send_cmd(wire.OP_HELLO, 1, b"app=rp2-run-stop\nversion=0\n")
        if rsp_status(rsp) != wire.ST_OK:
            raise SystemExit("HELLO refused: %s" % status_name(rsp_status(rsp)))
        caps = {}
        for line in rsp.payload[1:].decode(errors="replace").splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                caps[k.strip()] = v.strip()
        if caps.get("mtu"):
            central.confirm_caps_mtu(int(caps["mtu"]))
        print("board: chip=%s mtu=%s" % (caps.get("chip", "?"), caps.get("mtu", "?")))

        # A) tight loop, no I/O — the pure VM back-edge interrupt case.
        await run_and_stop(c, central, log, 10, b"while True: pass", 2.0,
                           "busy-loop")

        # B) print flood — STOP must land while the console tee is streaming.
        cursor = len(log)
        await run_and_stop(c, central, log, 20, b"while True: print('x')", 2.0,
                           "print-loop")
        console = sum(1 for _, f in log[cursor:]
                      if f.type == wire.EVT and f.opcode == wire.OP_CONSOLE_DATA)
        print("    ..   - print-loop streamed %d CONSOLE_DATA chunks (informational)"
              % console)

        # C) STOP while idle: RSP{OK}, and NO RUN_STATE of any kind.
        cursor = len(log)
        rsp = await central.send_cmd(wire.OP_STOP, 30)
        c.check("idle STOP: RSP status is OK (idempotent)",
                rsp_status(rsp) == wire.ST_OK, status_name(rsp_status(rsp)))
        await asyncio.sleep(QUIET_WATCH_S)
        stray = [f for _, f in log[cursor:]
                 if f.type == wire.EVT and f.opcode == wire.OP_RUN_STATE]
        c.check("idle STOP: no RUN_STATE emitted", not stray,
                "got %d RUN_STATE event(s)" % len(stray))

        # D) file-mode RUN of /main.py: same lifecycle, finite script -> done.
        await put_small_file(central, MAIN_PATH, MAIN_SOURCE, 40)
        cursor = len(log)
        rsp = await central.send_cmd(wire.OP_RUN, 42, bytes((0,)) + MAIN_PATH.encode())
        c.check("file-mode: RUN %s RSP status is OK" % MAIN_PATH,
                rsp_status(rsp) == wire.ST_OK, status_name(rsp_status(rsp)))
        run_i = await wait_run_state(log, cursor, ST_RUNNING, STATE_WAIT_S)
        if c.check("file-mode: RUN_STATE(running) arrives", run_i is not None):
            rsp_i = find_rsp(log, cursor, wire.OP_RUN, 42)
            c.check("file-mode: RSP precedes RUN_STATE(running) on the wire",
                    rsp_i is not None and rsp_i < run_i,
                    "rsp_index=%s running_index=%s" % (rsp_i, run_i))
            done_i = await wait_run_state(log, run_i + 1, ST_DONE, DONE_WAIT_S)
            c.check("file-mode: finite %s terminates as done" % MAIN_PATH,
                    done_i is not None)
        # Cleanup the bench fixture so autorun cannot pick it up later.
        await central.send_cmd(wire.OP_FILE_DELETE, 43,
                               len(MAIN_PATH.encode()).to_bytes(2, "little")
                               + MAIN_PATH.encode())

        ok = c.failed == 0
        print("RP2 RUN/STOP %s (chip=%s, %d checks failed)"
              % ("PASS" if ok else "FAIL", caps.get("chip", "?"), c.failed))
        return 0 if ok else 1
    finally:
        await central.disconnect()


def main():
    p = argparse.ArgumentParser(description="rpi-pico2-w RUN/STOP lifecycle bench (HIL H6)")
    p.add_argument("--scan", action="store_true", help="list PyBLE boards and exit")
    p.add_argument("--address", help="board address/UUID from --scan")
    args = p.parse_args()
    if not args.scan and not args.address:
        p.error("--scan or --address required")
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
