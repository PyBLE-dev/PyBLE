# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# pyble_runner — RUN / STOP lifecycle for the rpi-pico2-w portable agent
# (ports/rpi-pico2-w.md P2/P3/P6; C reference twin pble_runner.c).
#
# Layout mirrors the native twin:
#   * RunStateMachine — the PURE single-program lifecycle seam (pble_rsm_*),
#     kept intact for the existing S3 host suite; on_stopped() is the STOP
#     terminal (protocol.md §6: a stopped run returns to IDLE, never done/error).
#   * Runner — the rp2 single-thread handler/supervisor split (P2):
#       - handle_run() runs in BLE scheduled context: it validates the §6
#         [mode:u8][data] payload BEFORE reserving (a bad request can never
#         wedge the reservation), reserves via the RSM, captures the request
#         for the supervisor, and returns the §8 RSP status ONLY — it never
#         emits RUN_STATE and never executes user code inline.
#       - service() runs on the supervisor (main thread): it picks up the
#         captured request, clears any stale stop intent (pble_runner.c worker:
#         g_stop_requested = false at fresh-run start), emits RUN_STATE(running),
#         calls exec_fn(mode, data), and ALWAYS emits a terminal RUN_STATE
#         (stop wins over completion: term = stop_requested ? stopped : finished).
#   * make_exec_fn() — the supervisor executor (P2/P3): compile + exec in a
#     FRESH globals dict per run; an uncaught exception routes its traceback
#     through the console stderr path (pble_console_stderr_print twin) and then
#     re-raises so the Runner lands RUN_STATE(error); KeyboardInterrupt (the
#     STOP path, P3) propagates untouched so the Runner lands RUN_STATE(idle).

# protocol.md §4 RUN_STATE lifecycle values (frozen).
IDLE = 0
RUNNING = 1
DONE = 2
ERROR = 3

# protocol.md §8 status codes used by this module (frozen).
OK = 0x00
EBADREQ = 0x01
EBUSY = 0x07
ERANGE = 0x09

# protocol.md §6 RUN payload modes (frozen).
MODE_FILE = 0
MODE_SOURCE = 1

# ports/rpi-pico2-w.md P6 per-handler bounds (pble_runner.c PBLE_RUN_PATH_MAX /
# PBLE_RUN_BUF_MAX twins) — module constants, never re-derived per call site.
RUN_PATH_MAX = 128
RUN_SOURCE_MAX = 2048


class RunStateMachine:
    """Pure twin of the native single-program lifecycle seam (pble_rsm_*)."""

    def __init__(self):
        self.state = IDLE
        self.events = []

    def on_run(self):
        if self.state == RUNNING:
            return EBUSY
        # Reserve the single runner immediately. RUN_STATE is emitted only when
        # the run actually starts, matching pble_rsm_on_run/on_started.
        self.state = RUNNING
        return OK

    def on_started(self):
        self.state = RUNNING
        self.events.append(RUNNING)

    def on_finished(self, ok):
        self.state = DONE if ok else ERROR
        self.events.append(self.state)

    def on_stopped(self):
        # STOP terminal: a stopped run returns to IDLE (§6 STOP -> idle;
        # pble_rsm_on_stopped twin) — never done, never error.
        self.state = IDLE
        self.events.append(IDLE)
        return self.state


class Runner:
    """rp2 handler/supervisor runner seam (P2). `emit_state(state)` is called
    for every RUN_STATE transition; `exec_fn(mode, data)` executes user code
    in supervisor context (see make_exec_fn)."""

    def __init__(self, emit_state, exec_fn):
        self.rsm = RunStateMachine()
        self._emit_state = emit_state
        self._exec_fn = exec_fn
        self._pending = None          # captured (mode, data) awaiting pickup
        self._stop_requested = False

    def handle_run(self, payload):
        # Validate BEFORE reserving (pble_runner_run twin) — the only place the
        # §6 RUN payload is parsed.
        payload = bytes(payload)
        if len(payload) < 1:
            return EBADREQ            # need at least the mode byte
        mode = payload[0]
        if mode != MODE_FILE and mode != MODE_SOURCE:
            return EBADREQ
        data = payload[1:]
        if mode == MODE_FILE:
            if len(data) == 0 or len(data) > RUN_PATH_MAX:
                return ERANGE
        elif len(data) > RUN_SOURCE_MAX:
            return ERANGE
        status = self.rsm.on_run()
        if status != OK:
            return status             # EBUSY: no capture, no RUN_STATE
        self._pending = (mode, data)  # reserved -> single writer of the capture
        return OK                     # RSP only; RUN_STATE is supervisor work

    def handle_stop(self):
        # Idempotent: STOP while idle is a no-op OK (the intent is cleared at
        # the next fresh-run pickup). The agent additionally arms the console
        # 0x03 channel when a run is active (P3) — that wiring lives outside
        # this seam.
        self._stop_requested = True
        return OK

    def service(self):
        """Supervisor pickup: run the captured request, emitting RUN_STATE
        (running) then ALWAYS a terminal state. Returns True iff serviced."""
        if self._pending is None:
            return False
        mode, data = self._pending
        self._pending = None
        # Fresh run: a stale stop intent never bleeds into this run.
        self._stop_requested = False
        self.rsm.on_started()
        self._emit_state(RUNNING)
        try:
            self._exec_fn(mode, bytes(data))
            ok = True
        except KeyboardInterrupt:
            # The STOP path (P3): stopped != done/error — force the idle terminal.
            self._stop_requested = True
            ok = False
        except Exception:
            ok = False
        # Terminal transition: STOP wins over completion (pble_runner.c worker:
        # term = stop_requested ? stopped : finished).
        if self._stop_requested:
            self.rsm.on_stopped()
        else:
            self.rsm.on_finished(ok)
        self._stop_requested = False
        self._emit_state(self.rsm.state)
        return True


class _StderrWriter:
    """Minimal write() adaptor so both MicroPython's sys.print_exception and
    CPython's traceback module can print into the console stderr sink."""

    def __init__(self, sink):
        self._sink = sink

    def write(self, s):
        if isinstance(s, str):
            s = s.encode("utf-8")
        self._sink(s)
        return len(s)


def _print_exception(exc, sink):
    """Best-effort traceback -> stderr sink; NEVER raises (the terminal
    RUN_STATE must still be emitted on a broken sink)."""
    if sink is None:
        return
    try:
        writer = _StderrWriter(sink)
        try:
            from sys import print_exception as _pe    # MicroPython
        except ImportError:
            _pe = None
        if _pe is not None:
            _pe(exc, writer)
        else:                                         # CPython host suite
            import traceback
            traceback.print_exception(type(exc), exc, exc.__traceback__,
                                      file=writer)
    except Exception:
        pass


def make_exec_fn(write_stderr=None):
    """Build the supervisor executor (P2): compile/exec the captured request in
    a FRESH globals dict per run. `write_stderr(bytes)` is the console stderr
    chokepoint (e.g. lambda b: console.out(STDERR, b))."""

    def _exec(mode, data):
        try:
            if mode == MODE_FILE:
                name = data.decode("utf-8")
                f = open(name)                        # raises OSError if absent
                try:
                    source = f.read()
                finally:
                    f.close()
            else:
                name = "<run>"
                source = data.decode("utf-8")
            code = compile(source, name, "exec")
            fresh_globals = {"__name__": "__main__"}
            exec(code, fresh_globals)
        except KeyboardInterrupt:
            raise                                     # STOP -> idle, no traceback
        except Exception as exc:
            # Uncaught -> traceback via the console stderr path (FR-RUN-9 twin),
            # then re-raise so the Runner lands RUN_STATE(error).
            _print_exception(exc, write_stderr)
            raise
    return _exec
