# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# pyble_console — the rpi-pico2-w agent console: ONE io.IOBase object serving
# three roles (ports/rpi-pico2-w.md P3/P8; C reference twin pble_console.c):
#
#   1. os.dupterm stdout tee: write() -> out(STDOUT, ...) — gated on the
#      run-active flag (the main-thread equivalent of the ESP32 worker-origin
#      gate: REPL/supervisor output NEVER reaches BLE), chunked to CONSOLE_DATA
#      [stream:u8][bytes <= CHUNK] payloads (§6), and budgeted by a token
#      bucket (BTstack heap-queues congested notifies — the budget bounds the
#      queue; a dead link degrades to drop-and-continue, NEVER a wedge; the
#      PBLE_CONSOLE_TX_BUDGET_MS twin). write() always reports full
#      consumption — dropping is invisible to the running program.
#   2. stdin: feed_input() (CONSOLE_INPUT 0x31, fire-and-forget: returns None,
#      no RSP frame) into a 256-byte ring, drop-on-overflow (append until
#      full, drop the excess tail — bounded, never grows the heap);
#      readinto() hands MicroPython exactly 1 byte or None — NEVER 0 and
#      NEVER raises, because EOF/raise deactivates the dupterm slot
#      (extmod/os_dupterm.c).
#   3. STOP channel (P3): inject_stop() transactionally arms the 0x03 interrupt
#      char (which preempts buffered stdin) and calls the injected deferred
#      os.dupterm_notify seam exactly once. Admission success returns True so
#      upstream converts it into a main-thread KeyboardInterrupt at the next VM
#      back-edge; a scheduling exception rolls the arm back and returns False so
#      the agent can take its post-RSP hardware-reset fail-safe. Upstream catches
#      any exception escaping a Python dupterm write, so write() recognizes an
#      exact delivered STOP KBI and re-arms it through the injected two-stage
#      retry: checkpoint 1 runs a locked trampoline, checkpoint 2 runs native
#      dupterm_notify, then write returns before the KBI's next exception check.
#
# The emit / notify / clock seams are INJECTED so the host suite exercises the
# pure logic; on device the agent wires emit -> CONSOLE_DATA EVT notify,
# notify -> os.dupterm_notify(None), clock -> time.ticks_ms.

try:
    from io import IOBase as _IOBase          # MicroPython + CPython
except ImportError:                            # minimal-build fallback
    _IOBase = object

try:
    from time import ticks_ms as _ticks_ms, ticks_diff as _ticks_diff
except ImportError:                            # CPython host suite
    from time import monotonic as _monotonic

    def _ticks_ms():
        return int(_monotonic() * 1000)

    def _ticks_diff(a, b):
        return a - b

# protocol.md §6 CONSOLE_DATA stream tags (frozen).
STDOUT = 0
STDERR = 1

# pble_console.c twins: PBLE_CONSOLE_CHUNK / PBLE_STDIN_RING; P3 interrupt char.
CHUNK = 200
STDIN_RING = 256
STOP_CHAR = 0x03

# Frozen Pico token-bucket contract (port spec P8/OI-P3): capacity in bytes,
# refill in bytes per elapsed millisecond, and the exact empty-to-full refill
# horizon in milliseconds.  TX_BUDGET_MS is evidence metadata; it does not
# block, sleep, or change the token arithmetic below.
TX_CAPACITY = 2048
TX_REFILL_PER_MS = 20
TX_BUDGET_MS = (TX_CAPACITY + TX_REFILL_PER_MS - 1) // TX_REFILL_PER_MS


class Console(_IOBase):
    """The single tee/stdin/STOP object handed to os.dupterm (P8)."""

    def __init__(self, emit, notify, clock=None, tx_capacity=None,
                 tx_refill_per_ms=None, stop_fail=None):
        self._emit = emit
        self._notify = notify
        self._stop_fail = stop_fail
        self._stop_retry = None
        self._clock = clock if clock is not None else _ticks_ms
        self._cap = TX_CAPACITY if tx_capacity is None else tx_capacity
        self._refill = TX_REFILL_PER_MS if tx_refill_per_ms is None else tx_refill_per_ms
        self._tokens = self._cap              # bucket starts at capacity
        self._last_ms = self._clock()
        self._run_active = False              # gate starts INACTIVE
        self._stop_armed = False
        self._stop_inflight = False
        self._ring = bytearray()              # logical stdin ring (bounded)
        self._head = 0

    # -- run gate --------------------------------------------------------------
    def set_run_active(self, flag):
        self._run_active = bool(flag)
        if not self._run_active:
            # A terminal transition invalidates queued dupterm notifications
            # for the old run. They may still execute, but readinto() then has
            # no byte to turn into a late KeyboardInterrupt.
            self._stop_armed = False
            self._stop_inflight = False

    def set_stop_retry(self, retry):
        """Install the device-only two-checkpoint dupterm retry seam (P3)."""
        self._stop_retry = retry

    def stop_retry_failed(self):
        """Clear all STOP state before the non-returning reset fail-safe."""
        self._stop_armed = False
        self._stop_inflight = False
        if self._stop_fail is not None:
            self._stop_fail()

    # -- stdout/stderr tee -> CONSOLE_DATA (the single emit chokepoint) --------
    def write(self, b):
        # dupterm stdout entry: ALWAYS report the bytes consumed (tee_write
        # twin) — gating/dropping is invisible to the running program.
        n = len(b)
        try:
            self.out(STDOUT, b)
        except KeyboardInterrupt as stop_exc:
            if not self._stop_inflight:
                raise

            # extmod/os_dupterm.c:mp_os_dupterm_tx_strn catches every exception
            # escaping a Python stream write and deactivates the dupterm slot.
            # Consume only the KBI proven to come from our delivered 0x03. The
            # injected retry queues a trampoline for bytecode checkpoint 1;
            # that locked callback queues native dupterm_notify for checkpoint
            # 2. There is no third checkpoint before RETURN_VALUE, so upstream
            # removes its NLR catch before the retried KBI is examined.
            self._stop_inflight = False
            self._stop_armed = True
            if self._stop_retry is None:
                self.stop_retry_failed()
                raise stop_exc                 # defensive host-only fallback
            try:
                self._stop_retry()
            except Exception:
                self.stop_retry_failed()
                raise stop_exc                 # defensive host-only fallback
        return n

    def out(self, stream, b):
        if not self._run_active:
            return
        if isinstance(b, str):
            b = b.encode("utf-8")
        total = len(b)
        off = 0
        while off < total:
            n = total - off
            if n > CHUNK:
                n = CHUNK
            # Per-chunk budget: an unaffordable chunk is dropped WHOLE and
            # emission continues (budget-expiry drop twin) — never blocks.
            if self._take_tokens(n):
                try:
                    self._emit(stream, bytes(b[off:off + n]))
                except Exception:
                    # Dead/raising link: drop-and-continue, never raise into
                    # the running program (a raising dupterm stream is
                    # deactivated upstream).
                    pass
            off += n

    def _take_tokens(self, n):
        now = self._clock()
        elapsed = _ticks_diff(now, self._last_ms)
        if elapsed < 0:
            elapsed = 0
        self._last_ms = now
        tokens = self._tokens + elapsed * self._refill
        if tokens > self._cap:
            tokens = self._cap                # a long idle NEVER over-fills
        if tokens >= n:
            self._tokens = tokens - n
            return True
        self._tokens = tokens
        return False

    # -- stdin ring + STOP channel --------------------------------------------
    def feed_input(self, b):
        # CONSOLE_INPUT is fire-and-forget: no RSP frame (§6) -> returns None.
        if b:
            if isinstance(b, str):
                b = b.encode("utf-8")
            if self._head:
                # Compact so the bound below counts only undrained bytes.
                self._ring = self._ring[self._head:]
                self._head = 0
            room = STDIN_RING - len(self._ring)
            if room > 0:
                self._ring.extend(b[:room])   # append until full, drop the tail
        return None

    def readinto(self, buf):
        # P3 contract: exactly 1 byte or None — never 0, never raises.
        try:
            if self._stop_armed:
                buf[0] = STOP_CHAR            # 0x03 preempts buffered stdin
                self._stop_armed = False      # delivered once
                self._stop_inflight = True    # identifies write-swallowed KBI
                return 1
            if self._head < len(self._ring):
                buf[0] = self._ring[self._head]
                self._head += 1
                if self._head == len(self._ring):
                    self._ring = bytearray()
                    self._head = 0
                return 1
        except Exception:
            pass
        return None

    def inject_stop(self):
        # P3: arm + notify is one logical transaction. A full scheduler queue
        # must not leave 0x03 latent for an unrelated later dupterm notification.
        self._stop_armed = True
        try:
            self._notify()
        except Exception:
            self._stop_armed = False
            self._stop_inflight = False
            return False                      # agent takes non-returning reset
        return True
