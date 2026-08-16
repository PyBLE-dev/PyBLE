#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Host tests for the F-25 rpi-pico2-w console (port spec P3/P8; plan
# PART 3 test 6). Sole [red] author: firmware-test-author. Production module
# owner (HAND-OFF for [green]): agent-engineer -> firmware/pyble/pyble_console.py
# (NEW; C reference twin: firmware/user_c_modules/pyble/pble_console.c).
#
# FROZEN references: protocol.md §6 (CONSOLE_DATA [stream:u8][bytes], stream
# 0=stdout / 1=stderr; CONSOLE_INPUT fire-and-forget); ports/rpi-pico2-w.md
# P3 (STOP = arm 0x03 in the tee + one dupterm notify; tee.readinto returns
# 1 byte or None — NEVER 0 and NEVER raises, because EOF/raise deactivates
# dupterm, extmod/os_dupterm.c) and P8 (one io.IOBase object; run-active gate;
# chunks <= 200 data bytes; 256 B stdin ring drop-on-overflow; token-bucket TX
# budget — a dead link degrades to drop-and-continue, never a wedge).
#
# Env-reality: NO os.dupterm / BTstack behaviour is faked. The notify seam and
# the clock are INJECTED callables; tests exercise pure logic only.
#
# ---------------------------------------------------------------------------
# INTERFACE PINNED BY THIS [red] TEST (agent-engineer implements to it):
#   pyble_console.STDOUT == 0, pyble_console.STDERR == 1      (§6 stream tags)
#   pyble_console.CHUNK == 200          (pble_console.c PBLE_CONSOLE_CHUNK)
#   pyble_console.STDIN_RING == 256     (pble_console.c PBLE_STDIN_RING)
#   pyble_console.STOP_CHAR == 0x03     (P3 interrupt char)
#   pyble_console.Console(emit, notify, clock=None, tx_capacity=None,
#                         tx_refill_per_ms=None, stop_fail=None)
#     - an io.IOBase subclass (P8: ONE object serves tee + stdin + STOP).
#     - emit(stream:int, data:bytes) is called once per emitted chunk,
#       len(data) <= CHUNK; notify() (zero-arg) is the injected
#       os.dupterm_notify seam; clock() -> int milliseconds; stop_fail() is
#       the non-returning reset seam if re-notifying a STOP consumed inside
#       dupterm write cannot be admitted.
#     - tx_capacity / tx_refill_per_ms configure the token bucket (defaults =
#       the HIL-tuned OI-P3 constants). Semantics: tokens start at capacity;
#       tokens = min(capacity, tokens + elapsed_ms * refill) at each attempt;
#       a chunk is emitted only if tokens >= len(chunk-data) (then deducted),
#       else THAT CHUNK is dropped and emission continues — never blocks,
#       never raises into the program (pble_console.c budget-expiry drop).
#     .set_run_active(flag)             # starts INACTIVE; gate for the tee
#     .write(b) -> int                  # dupterm stdout entry == out(STDOUT,b);
#                                       # ALWAYS reports len(b) consumed
#     .out(stream, b)                   # the single emit chokepoint (stderr
#                                       # traceback path uses out(STDERR, ...))
#     .readinto(buf) -> 1 | None        # 1 byte into buf[0], or None if empty;
#                                       # armed STOP_CHAR preempts buffered stdin
#     .feed_input(b) -> None            # CONSOLE_INPUT: bounded ring; on
#                                       # overflow the EXCESS TAIL is dropped
#     .inject_stop() -> bool            # atomically arm 0x03 + call notify once;
#                                       # False rolls the arm back on notify error
# ---------------------------------------------------------------------------

import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

# Guard-inject the MicroPython module surfaces before importing the scaffold
# (tolerant: the `micropython` guard may not exist yet — never fake behaviour).
_support._inject_micropython_guards()
try:
    import importlib as _importlib

    if "micropython" not in sys.modules:
        sys.modules["micropython"] = _importlib.import_module("micropython")
except ImportError:
    pass

CONSOLE = _support.RedReason("pyble_console", owner="agent-engineer")

BIG = 1 << 30  # an effectively-unlimited bucket for non-budget tests


def make_console(testcase, criterion, emit=None, notify=None, clock=None,
                 cap=BIG, refill=BIG, stop_fail=None):
    """Build a Console with recording emit/notify seams and an injected clock.
    Returns (console, chunks, notifies): chunks = [(stream, bytes), ...]."""
    cls = CONSOLE.attr(testcase, "Console", criterion)
    chunks = []
    notifies = []

    def default_emit(stream, data):
        chunks.append((stream, bytes(data)))

    kwargs = {
        "clock": clock if clock is not None else (lambda: 0),
        "tx_capacity": cap,
        "tx_refill_per_ms": refill,
    }
    if stop_fail is not None:
        kwargs["stop_fail"] = stop_fail
    con = cls(
        emit if emit is not None else default_emit,
        notify if notify is not None else (lambda: notifies.append(1)),
        **kwargs
    )
    return con, chunks, notifies


def drain(testcase, con, limit=1000):
    """Drain the console via 1-byte readinto calls, asserting the P3 contract
    (each result is exactly 1 or None — never 0, never an exception)."""
    out = bytearray()
    buf = bytearray(1)
    for _ in range(limit):
        n = con.readinto(buf)
        if n is None:
            return bytes(out)
        testcase.assertEqual(
            n, 1, "readinto MUST return exactly 1 or None — a 0/other return "
                  "deactivates dupterm (extmod/os_dupterm.c)")
        out.append(buf[0])
    testcase.fail("readinto never drained — ring not bounded?")


class ConstantsAndShapeTest(unittest.TestCase):
    """P8: the frozen tuning constants mirror pble_console.c, and the console is
    ONE io.IOBase object (the os.dupterm tee)."""

    def test_stream_tags(self):
        self.assertEqual(CONSOLE.attr(self, "STDOUT", "F-25/§6 STDOUT=0"), 0)
        self.assertEqual(CONSOLE.attr(self, "STDERR", "F-25/§6 STDERR=1"), 1)

    def test_tuning_constants(self):
        self.assertEqual(CONSOLE.attr(self, "CHUNK", "F-25/P8 chunk<=200"), 200)
        self.assertEqual(CONSOLE.attr(self, "STDIN_RING", "F-25/P8 ring=256"), 256)
        self.assertEqual(CONSOLE.attr(self, "STOP_CHAR", "F-25/P3 stop=0x03"), 0x03)

    def test_console_is_an_iobase(self):
        con, _, _ = make_console(self, "F-25/P8 one io.IOBase object")
        self.assertIsInstance(
            con, io.IOBase,
            "os.dupterm on rp2 requires an io.IOBase stream — P8 pins ONE such "
            "object serving tee + stdin + STOP")


class RunGateTest(unittest.TestCase):
    """P8: the tee is gated on the run-active flag — the main-thread equivalent
    of the ESP32 worker-origin gate (REPL/supervisor output NEVER reaches BLE)."""

    CRIT = "F-25/P8 run-gate"

    def test_starts_inactive_and_emits_nothing(self):
        con, chunks, _ = make_console(self, self.CRIT)
        self.assertEqual(con.write(b"hello"), 5,
                         "the tee ALWAYS reports the bytes consumed "
                         "(pble_console.c tee_write returns size)")
        self.assertEqual(chunks, [], "run-inactive output MUST NOT be emitted")

    def test_active_emits_then_inactive_silences(self):
        con, chunks, _ = make_console(self, self.CRIT)
        con.set_run_active(True)
        con.write(b"hello")
        self.assertEqual(chunks, [(0, b"hello")],
                         "run-active stdout MUST emit [stream=0][bytes]")
        con.set_run_active(False)
        con.write(b"bye")
        self.assertEqual(chunks, [(0, b"hello")],
                         "after the run ends the tee MUST fall silent again")

    def test_stderr_path_is_gated_too(self):
        con, chunks, _ = make_console(self, self.CRIT)
        con.out(1, b"traceback")
        self.assertEqual(chunks, [], "out() is the same gated chokepoint")


class ChunkingTest(unittest.TestCase):
    """§6/P8: CONSOLE_DATA payloads are [stream:u8][<=200 data bytes]; a long
    write is split exactly like pble_console_out (full chunks then remainder)."""

    CRIT = "F-25/P8 [stream][<=200] chunking"

    def test_stdout_chunk_split(self):
        con, chunks, _ = make_console(self, self.CRIT)
        con.set_run_active(True)
        data = bytes(range(256)) + bytes(194)  # 450 bytes
        con.write(data)
        self.assertEqual([s for s, _ in chunks], [0, 0, 0])
        self.assertEqual([len(d) for _, d in chunks], [200, 200, 50],
                         "the C twin emits full 200-byte chunks then the tail")
        self.assertEqual(b"".join(d for _, d in chunks), data,
                         "chunking MUST be byte-identical and ordered")

    def test_stderr_chunk_split(self):
        con, chunks, _ = make_console(self, self.CRIT)
        con.set_run_active(True)
        data = b"T" * 450
        con.out(1, data)
        self.assertEqual([s for s, _ in chunks], [1, 1, 1],
                         "tracebacks route via out(STDERR, ...) tagged stream=1")
        self.assertEqual(b"".join(d for _, d in chunks), data)


class TokenBucketTest(unittest.TestCase):
    """P8: emission is budgeted by a token bucket driven by the INJECTED clock;
    an exhausted budget drops chunks (drop-and-continue) — it never blocks."""

    CRIT = "F-25/P8 token-bucket budget"

    def setUp(self):
        self.now = [0]
        self.con, self.chunks, _ = make_console(
            self, self.CRIT, clock=lambda: self.now[0], cap=400, refill=1)
        self.con.set_run_active(True)

    def emitted_bytes(self):
        return b"".join(d for _, d in self.chunks)

    def test_capacity_bounds_a_burst(self):
        self.assertEqual(self.con.write(b"A" * 1000), 1000,
                         "write reports full consumption even when dropping — "
                         "dropping is invisible to the program")
        self.assertEqual([len(d) for _, d in self.chunks], [200, 200],
                         "capacity 400 affords exactly two 200-byte chunks; "
                         "the rest of the burst is DROPPED, not queued")
        self.assertEqual(self.emitted_bytes(), b"A" * 400)

    def test_refill_by_injected_clock_and_whole_chunk_drop(self):
        self.con.write(b"A" * 1000)          # drains the bucket to 0
        self.now[0] = 250                     # +250 ms -> 250 tokens
        self.con.write(b"B" * 300)            # chunks [200, 100]
        self.assertEqual([len(d) for _, d in self.chunks], [200, 200, 200],
                         "250 tokens afford the 200-chunk; the 100-byte tail "
                         "chunk exceeds the 50 remaining tokens and is dropped "
                         "whole (per-chunk budget, pble_console.c)")
        self.assertEqual(self.chunks[-1], (0, b"B" * 200))

    def test_refill_clamps_at_capacity(self):
        self.con.write(b"A" * 1000)           # bucket -> 0
        self.now[0] = 10 ** 7                 # a long idle NEVER over-fills
        self.con.write(b"C" * 1000)
        self.assertEqual([len(d) for _, d in self.chunks],
                         [200, 200, 200, 200],
                         "tokens clamp at tx_capacity: the second burst still "
                         "affords exactly 400 bytes")


class NeverWedgeTest(unittest.TestCase):
    """P8: a dead/raising link degrades to drop-and-continue — the tee NEVER
    raises into user code (a raising dupterm stream is deactivated upstream)."""

    CRIT = "F-25/P8 dead-link-drop-never-wedge"

    def test_write_swallows_emit_failures(self):
        def dead_emit(stream, data):
            raise RuntimeError("link is gone")

        con, _, _ = make_console(self, self.CRIT, emit=dead_emit)
        con.set_run_active(True)
        try:
            self.assertEqual(con.write(b"x" * 300), 300)
            self.assertEqual(con.write(b"y"), 1)
        except Exception as exc:  # noqa: BLE001
            self.fail("write() MUST NOT propagate an emit failure into the "
                      "running program (got {!r})".format(exc))


class PrintFloodStopRecoveryTest(unittest.TestCase):
    """P3: upstream mp_os_dupterm_tx_strn catches every exception escaping a
    Python dupterm write.  A STOP KBI delivered inside the tee must therefore
    be re-armed/re-notified before write returns, or print flood silently
    consumes the acknowledged STOP and leaves the runner permanently busy."""

    CRIT = "F-27/P3 print-flood dupterm-write STOP recovery"

    def test_consumed_stop_kbi_is_retried_before_write_returns(self):
        def pending_stop_lands(stream, data):
            raise KeyboardInterrupt()

        con, _, notifies = make_console(
            self, self.CRIT, emit=pending_stop_lands)
        con.set_run_active(True)
        self.assertTrue(con.inject_stop())

        # Model the scheduled native os.dupterm_notify consuming 0x03 and
        # setting the main-thread pending KBI.  Under print flood its next VM
        # back-edge is still inside this dupterm write.
        buf = bytearray(1)
        self.assertEqual(con.readinto(buf), 1)
        self.assertEqual(buf[0], 0x03)

        try:
            written = con.write(b"flood")
        except KeyboardInterrupt:
            self.fail(
                "the exact delivered STOP KBI escaped into upstream's "
                "catch-all dupterm wrapper")
        self.assertEqual(written, 5)
        self.assertEqual(
            len(notifies), 2,
            "the tee must enqueue native dupterm_notify exactly once more")
        self.assertEqual(con.readinto(buf), 1,
                         "the retry must re-arm the STOP interrupt char")
        self.assertEqual(buf[0], 0x03)

        # A terminal transition invalidates any not-yet-consumed retry.
        con.inject_stop()
        con.set_run_active(False)
        self.assertIsNone(con.readinto(buf),
                          "terminal cleanup must leave no latent STOP byte")

    def test_unmarked_keyboard_interrupt_still_propagates(self):
        def unrelated_kbi(stream, data):
            raise KeyboardInterrupt()

        con, _, _ = make_console(self, self.CRIT, emit=unrelated_kbi)
        con.set_run_active(True)
        with self.assertRaises(
                KeyboardInterrupt,
                msg="only a consumed PyBLE STOP may use dupterm-write retry"):
            con.write(b"x")

    def test_retry_schedule_failure_clears_state_then_resets(self):
        calls = []

        def notify():
            calls.append("notify")
            if len(calls) == 2:
                raise RuntimeError("schedule queue full on retry")

        class ResetNow(BaseException):
            pass

        def stop_fail():
            calls.append("reset")
            raise ResetNow()

        def pending_stop_lands(stream, data):
            raise KeyboardInterrupt()

        con, _, _ = make_console(
            self, self.CRIT, emit=pending_stop_lands, notify=notify,
            stop_fail=stop_fail)
        con.set_run_active(True)
        self.assertTrue(con.inject_stop())
        buf = bytearray(1)
        self.assertEqual(con.readinto(buf), 1)

        with self.assertRaises(
                ResetNow,
                msg="failed post-RSP retry admission must reset, not wedge"):
            con.write(b"flood")
        self.assertEqual(calls, ["notify", "notify", "reset"])
        self.assertIsNone(con.readinto(buf),
                          "reset fail-safe must first clear the retry byte")


class ReadIntoTest(unittest.TestCase):
    """P3: tee.readinto returns 1 byte or None — NEVER 0 and NEVER raises
    (EOF/raise deactivates dupterm, extmod/os_dupterm.c)."""

    CRIT = "F-25/P3 readinto-1-or-None"

    def test_empty_returns_none_not_zero(self):
        con, _, _ = make_console(self, self.CRIT)
        result = con.readinto(bytearray(1))
        self.assertIsNone(result,
                          "an empty console MUST return None (not 0 — 0 is "
                          "EOF and kills the dupterm slot)")

    def test_feed_then_read_one_byte_at_a_time(self):
        con, _, _ = make_console(self, self.CRIT)
        self.assertIsNone(con.feed_input(b"ab"),
                          "CONSOLE_INPUT is fire-and-forget: feed_input "
                          "returns None (no RSP frame, §6)")
        buf = bytearray(8)
        self.assertEqual(con.readinto(buf), 1, "exactly ONE byte per call")
        self.assertEqual(buf[0], ord("a"))
        self.assertEqual(con.readinto(buf), 1)
        self.assertEqual(buf[0], ord("b"))
        self.assertIsNone(con.readinto(buf), "drained -> None")


class RingOverflowTest(unittest.TestCase):
    """P8: the stdin ring is bounded at 256 bytes; overflow drops the EXCESS
    TAIL (pble_console.c: append until full, break) — never grows the heap."""

    CRIT = "F-25/P8 stdin-ring-256-drop-on-overflow"

    def test_overflow_drops_the_new_bytes(self):
        con, _, _ = make_console(self, self.CRIT)
        con.feed_input(b"A" * 256)
        con.feed_input(b"Z")                   # full: dropped
        self.assertEqual(drain(self, con), b"A" * 256,
                         "a full ring MUST drop the overflow, byte-bounded")

    def test_partial_overflow_keeps_the_head_of_the_feed(self):
        con, _, _ = make_console(self, self.CRIT)
        con.feed_input(b"A" * 250)
        con.feed_input(b"0123456789")          # room for 6: keep head, drop tail
        self.assertEqual(drain(self, con), b"A" * 250 + b"012345",
                         "the C twin appends until full then drops the tail")


class InjectStopTest(unittest.TestCase):
    """P3: inject_stop() arms STOP_CHAR (0x03) in the tee and invokes the
    injected notify seam EXACTLY once, so upstream converts it into a
    main-thread KeyboardInterrupt; the armed 0x03 preempts buffered stdin."""

    CRIT = "F-25/P3 inject-stop-0x03-notify-once"

    def test_arms_stop_char_and_notifies_once(self):
        con, _, notifies = make_console(self, self.CRIT)
        self.assertTrue(con.inject_stop(),
                        "successful notify admission MUST report True")
        self.assertEqual(len(notifies), 1,
                         "inject_stop MUST call the notify seam exactly once")
        buf = bytearray(1)
        self.assertEqual(con.readinto(buf), 1)
        self.assertEqual(buf[0], 0x03, "the armed byte IS the interrupt char")
        self.assertIsNone(con.readinto(buf), "0x03 is delivered once, then empty")
        self.assertEqual(len(notifies), 1, "reads MUST NOT re-notify")

    def test_stop_preempts_buffered_stdin(self):
        con, _, notifies = make_console(self, self.CRIT)
        con.feed_input(b"xy")
        self.assertTrue(con.inject_stop())
        self.assertEqual(drain(self, con), b"\x03xy",
                         "the STOP char MUST jump ahead of buffered stdin so "
                         "the KeyboardInterrupt lands promptly (P3 <500 ms)")
        self.assertEqual(len(notifies), 1)

    def test_notify_failure_rolls_back_stop_char_and_reports_false(self):
        def queue_full():
            raise RuntimeError("schedule queue full")

        con, _, _ = make_console(self, self.CRIT, notify=queue_full)
        con.feed_input(b"xy")

        self.assertFalse(
            con.inject_stop(),
            "failed scheduler admission MUST be reported to the agent")
        self.assertEqual(
            drain(self, con), b"xy",
            "failed admission MUST clear the armed 0x03; no latent interrupt "
            "may preempt later stdin")


if __name__ == "__main__":
    unittest.main(verbosity=2)
