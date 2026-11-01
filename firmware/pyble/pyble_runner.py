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
#       - service() runs on the supervisor (main thread): publishing the
#         executing marker is the pickup cut, immediately followed by the final
#         cancellation check. A pre-cut STOP consumes the captured request and
#         emits only RUN_STATE(idle); a post-cut STOP takes the VM-interrupt
#         path. service_interrupted() idempotently closes a KBI that lands in
#         the post-exec terminal transition, so RUNNING can never be stranded.
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

# Stopped-terminal publication phases.  The transition to IDLE and its wire
# event are separate cuts because the deferred STOP KeyboardInterrupt may land
# between them.
_TERMINAL_NONE = 0
_TERMINAL_UNPUBLISHED = 1
_TERMINAL_PUBLISHED = 2

# protocol.md §8 status codes used by this module (frozen).
OK = 0x00
EBADREQ = 0x01
EBUSY = 0x07
ERANGE = 0x09

# protocol.md §6 RUN payload modes (frozen).
MODE_FILE = 0
MODE_SOURCE = 1

# PBLE/1 §6.1 additive, bounded committed execution metadata.
STATUS_QUEUED = 1
STATUS_STOPPING = 2
ORIGIN_FILE = 1
ORIGIN_SOURCE = 2
ORIGIN_AUTORUN = 3
MAX_RUN_ID = 0xffffffff
MAX_REVISION = 9007199254740991


def _status_fields_valid(schema, boot_id, run_id, revision, state, origin,
                         terminal_reason, flags):
    if (schema != 1 or len(boot_id) != 8 or not any(boot_id) or
            not 0 <= run_id <= MAX_RUN_ID or
            not 0 <= revision <= MAX_REVISION or
            state not in (IDLE, RUNNING, DONE, ERROR) or
            origin not in (0, ORIGIN_FILE, ORIGIN_SOURCE, ORIGIN_AUTORUN) or
            terminal_reason not in (0, 1, 2, 3) or flags & ~3):
        raise ValueError("invalid run status")
    if run_id == 0:
        if (revision, state, origin, terminal_reason, flags) != (0, 0, 0, 0, 0):
            raise ValueError("invalid initial run status")
    elif origin == 0 or revision < run_id:
        raise ValueError("invalid admitted run status")
    if state == RUNNING:
        if terminal_reason != 0:
            raise ValueError("running status has a terminal reason")
    elif flags != 0:
        raise ValueError("terminal status has flags")
    elif run_id != 0 and terminal_reason != (3, 0, 1, 2)[state]:
        raise ValueError("terminal status reason mismatch")


def encode_run_status(boot_id, run_id, revision, state, origin,
                      terminal_reason, flags):
    """Encode exactly the §6.1 snapshot, without its response status byte."""
    boot_id = bytes(boot_id)
    _status_fields_valid(1, boot_id, run_id, revision, state, origin,
                         terminal_reason, flags)
    return (b"\x01" + boot_id + run_id.to_bytes(4, "little") +
            revision.to_bytes(8, "little") +
            bytes((state, origin, terminal_reason, flags)))


def decode_run_status(payload):
    """Validate the bounded value also used for atomic metadata replacement."""
    if len(payload) != 25:
        raise ValueError("run status must have 25 bytes")
    fields = (payload[0], bytes(payload[1:9]),
              int.from_bytes(payload[9:13], "little"),
              int.from_bytes(payload[13:21], "little"),
              payload[21], payload[22], payload[23], payload[24])
    _status_fields_valid(*fields)
    return fields

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
        return self.state

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

    def __init__(self, emit_state, exec_fn, emit_terminal=None,
                 end_input=None, boot_id=None):
        if boot_id is None:
            import os
            boot_id = os.urandom(8)
        # A single immutable value is the publication cut. A scheduled BLE
        # callback never assembles a query from separately changing fields.
        self._status = encode_run_status(boot_id, 0, 0, IDLE, 0, 0, 0)
        self._pending_status_id = None
        self._pending_status_origin = None
        self._terminal_status_id = None
        self.rsm = RunStateMachine()
        self._emit_state = emit_state
        self._emit_terminal = (emit_terminal if emit_terminal is not None
                               else self._default_emit_terminal)
        self._exec_fn = exec_fn
        self._pending = None          # captured (mode, data) awaiting pickup
        self._reserved_prior_state = None
        self._stop_requested = False
        self._executing = False       # reserved/pending is deliberately distinct
        self._terminal_phase = _TERMINAL_NONE
        self._terminal_prepared = False
        self._pending_owner = None
        self._active_owner = None
        self._terminal_owner = None
        self._event_owner = None
        self._pending_input_generation = None
        self._active_input_generation = None
        self._terminal_input_generation = None
        self._event_input_generation = None
        self._end_input = end_input

    def run_status(self):
        return self._status

    def _status_transition(self, state, reason, flags, expected_id,
                           clear_queued=False):
        # This publication region has no Python conditional jumps, loops or
        # Python helper calls. The pinned RP2 VM services scheduled callbacks
        # at jump checkpoints; builtin operations on these exact bytes/ints
        # cannot yield halfway through the read/modify/publish transaction.
        # Selecting unchanged fields for an old owner prevents terminal retry
        # from changing a successor run. Pickup preserves accepted STOP intent.
        old = self._status
        matches = int.from_bytes(old[9:13], "little") == expected_id
        wanted_flags = (flags, old[24] & ~STATUS_QUEUED)[clear_queued]
        selected = ((old[21], old[23], old[24]),
                    (state, reason, wanted_flags))[matches]
        changed = selected != (old[21], old[23], old[24])
        revision = int.from_bytes(old[13:21], "little") + changed
        self._status = (old[:13] + revision.to_bytes(8, "little") +
                        bytes((selected[0], old[22], selected[1], selected[2])))
        return changed

    def _finish_status(self, ok, expected_id):
        # Same branch-free publication rule as _status_transition. A STOP that
        # arrived at the caller's final branch checkpoint wins over completion.
        old = self._status
        matches = int.from_bytes(old[9:13], "little") == expected_id
        stopped = bool(old[24] & STATUS_STOPPING) | bool(self._stop_requested)
        state = ((ERROR, DONE)[ok], IDLE)[stopped]
        reason = ((2, 1)[ok], 3)[stopped]
        selected = ((old[21], old[23], old[24]), (state, reason, 0))[matches]
        changed = selected != (old[21], old[23], old[24])
        revision = int.from_bytes(old[13:21], "little") + changed
        self._stop_requested = (self._stop_requested, False)[matches]
        self._status = (old[:13] + revision.to_bytes(8, "little") +
                        bytes((selected[0], old[22], selected[1], selected[2])))
        return selected[0]

    def _admit_status(self, snapshot, run_id):
        # Validation may service a scheduled STOP for an autorun reservation.
        # Read its latched intent inside this branch-free final publication
        # region, after every codec/caller checkpoint. Both flags first become
        # visible in the same committed snapshot and consume one revision.
        self._status = snapshot[:24] + bytes((
            snapshot[24] | (STATUS_STOPPING * bool(self._stop_requested)),))
        self._pending_status_id = run_id

    def commit_reserved_run(self, origin=None):
        """Commit only an accepted RUN response or an admitted autorun."""
        if self._pending is None or self._pending_status_id is not None:
            return False
        _, boot, run_id, revision, _, _, _, _ = decode_run_status(self._status)
        if run_id == MAX_RUN_ID:
            return False
        origin = self._pending_status_origin if origin is None else origin
        snapshot = encode_run_status(
            boot, run_id + 1, revision + 1, RUNNING, origin, 0, STATUS_QUEUED)
        self._admit_status(snapshot, run_id + 1)
        return True

    def _default_emit_terminal(self, state, published):
        """Compatibility adapter for host users without a TX receipt seam."""
        self._emit_state(state)
        published()

    def _terminal_published(self):
        # Deliberately branch-free: BleLink calls this immediately after the
        # final native Notify acceptance, before the VM's next branch/pending-
        # exception check.
        self._terminal_phase = _TERMINAL_PUBLISHED

    def event_owner(self):
        """Immutable session owner of the event currently being emitted."""
        return self._event_owner

    def event_input_generation(self):
        """Console lease belonging to the event currently being emitted."""
        return self._event_input_generation

    def bind_reserved_input(self, generation):
        """Bind successful RUN-response stdin admission to its reservation."""
        if self._pending is None or self._executing:
            return False
        self._pending_input_generation = generation
        return True

    def _emit_owned_state(self, state, owner, input_generation):
        prior_owner = self._event_owner
        prior_input = self._event_input_generation
        self._event_owner = owner
        self._event_input_generation = input_generation
        try:
            return self._emit_state(state)
        finally:
            self._event_owner = prior_owner
            self._event_input_generation = prior_input

    def _emit_owned_terminal(self, state, published):
        prior_owner = self._event_owner
        prior_input = self._event_input_generation
        self._event_owner = self._terminal_owner
        self._event_input_generation = self._terminal_input_generation
        try:
            return self._emit_terminal(state, published)
        finally:
            self._event_owner = prior_owner
            self._event_input_generation = prior_input

    def _end_active_input(self):
        generation = self._active_input_generation
        self._active_input_generation = None
        self._terminal_input_generation = generation
        if self._end_input is not None and generation is not None:
            self._end_input(generation)

    def handle_run(self, payload, owner=None):
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
        # Preserve legacy active-run refusal before considering exhaustion of
        # the next identity. Malformed payloads still win over both checks.
        if self.rsm.state == RUNNING:
            return EBUSY
        if int.from_bytes(self._status[9:13], "little") == MAX_RUN_ID:
            return ERANGE
        prior_state = self.rsm.state
        status = self.rsm.on_run()
        if status != OK:
            return status             # EBUSY: no capture, no RUN_STATE
        self._stop_requested = False  # fresh reservation owns fresh control
        self._pending = (mode, data)  # reserved -> single writer of the capture
        self._reserved_prior_state = prior_state
        self._pending_owner = owner
        self._pending_input_generation = None
        self._pending_status_id = None
        self._pending_status_origin = (ORIGIN_FILE if mode == MODE_FILE
                                       else ORIGIN_SOURCE)
        return OK                     # RSP only; RUN_STATE is supervisor work

    def cancel_reserved_run(self):
        """Roll back a provisional RUN whose response handoff was rejected.

        This is valid only before supervisor pickup.  Restoring the captured
        predecessor matters because a new RUN may be reserved from DONE/ERROR,
        not just IDLE.
        """
        if (self._pending is None or self._executing or
                self._pending_status_id is not None):
            return False
        prior_state = self._reserved_prior_state
        if prior_state is None:
            return False
        self._pending = None
        self._reserved_prior_state = None
        self._pending_owner = None
        self._pending_input_generation = None
        self._pending_status_origin = None
        self._stop_requested = False
        self._terminal_phase = _TERMINAL_NONE
        self._terminal_prepared = False
        self.rsm.state = prior_state
        return True

    def handle_stop(self):
        # Idempotent while idle/terminal. While RUNNING this intent applies to
        # the current reservation or execution; service() consumes it before a
        # pending source can start, or uses it for the executing terminal cut.
        if self.rsm.state == RUNNING:
            self._stop_requested = True
            status = self._status
            if status[21] == RUNNING:
                self._status_transition(
                    RUNNING, 0, status[24] | STATUS_STOPPING,
                    int.from_bytes(status[9:13], "little"))
        return OK

    def is_executing(self):
        """True only while supervisor pickup is inside the execution lifecycle.

        A RUN reservation with a captured `_pending` item is active for EBUSY,
        but is not executing and therefore needs cancellation, not a VM KBI.
        """
        return self._executing

    def _terminalize_stopped(self):
        """Publish the stopped terminal once for the current pickup.

        The RSM transition and wire publication are deliberately restartable:
        a deferred KBI can land immediately before or after `on_stopped()`.
        """
        if self._terminal_phase == _TERMINAL_NONE:
            return False
        if self._terminal_phase == _TERMINAL_PUBLISHED:
            self._terminal_phase = _TERMINAL_NONE
            self._terminal_prepared = False
            self._terminal_owner = None
            self._terminal_input_generation = None
            return False
        if not self._terminal_prepared:
            self._executing = False
            self._stop_requested = False
            # End the predecessor's stdin lease before its RSM state becomes
            # IDLE and therefore admits a successor RUN. A publication retry
            # must not touch a successor reservation or its STOP/input state.
            self._end_active_input()
            self._status_transition(IDLE, 3, 0, self._terminal_status_id)
            self._terminal_prepared = True
        # Test the reservation before its identity: if the old RSM is still
        # RUNNING, no successor can enter before this transition; an already
        # admitted successor carries another snapshot identity and is skipped.
        if self.rsm.state != IDLE:
            if int.from_bytes(self._status[9:13], "little") == self._terminal_status_id:
                self.rsm.on_stopped()
        accepted = self._emit_owned_terminal(IDLE, self._terminal_published)
        if self._terminal_phase == _TERMINAL_PUBLISHED:
            self._terminal_phase = _TERMINAL_NONE
            self._terminal_prepared = False
            self._terminal_owner = None
            self._terminal_input_generation = None
        elif accepted is False:
            # No live session, or the captured session went stale: omit instead
            # of retaining the terminal for a future connection (protocol.md
            # §6).
            self._terminal_phase = _TERMINAL_NONE
            self._terminal_prepared = False
            self._terminal_owner = None
            self._terminal_input_generation = None
        return True

    def service_interrupted(self):
        """Recover a KBI that escaped service's post-exec transition."""
        return self._terminalize_stopped()

    def service(self):
        """Consume a cancelled reservation as idle, else run it to terminal.

        Returns True iff a pending request was serviced.
        """
        if self._pending is None:
            if self._terminal_phase == _TERMINAL_UNPUBLISHED:
                return self._terminalize_stopped()
            return False
        if self._pending_status_id is None:
            # Standalone users of Runner treat a returned OK as admission;
            # Agent commits explicitly at the actual response receipt instead.
            self.commit_reserved_run()
            if self._stop_requested:
                self._status_transition(
                    RUNNING, 0, STATUS_QUEUED | STATUS_STOPPING,
                    self._pending_status_id)
        mode, data = self._pending
        owner = self._pending_owner
        input_generation = self._pending_input_generation
        self._terminal_status_id = self._pending_status_id
        self._pending = None
        self._reserved_prior_state = None
        self._pending_owner = None
        self._pending_input_generation = None
        self._pending_status_id = None
        self._pending_status_origin = None
        self._active_owner = owner
        self._active_input_generation = input_generation
        self._terminal_owner = owner
        self._terminal_input_generation = input_generation
        self._terminal_phase = _TERMINAL_UNPUBLISHED
        self._terminal_prepared = False

        # Linearization cut: a control callback before this store leaves the
        # marker false and sets cancellation intent; one after it observes an
        # executing lifecycle and arms KBI. The final check MUST follow the
        # store, leaving no check-then-publish hole where source can start.
        self._executing = True
        if self._stop_requested:
            self._terminalize_stopped()
            return True

        try:
            self._status_transition(RUNNING, 0, 0, self._terminal_status_id,
                                    clear_queued=True)
            self.rsm.on_started()
            self._emit_owned_state(RUNNING, owner, input_generation)
            self._exec_fn(mode, bytes(data))
            ok = True
        except KeyboardInterrupt:
            # The STOP path (P3): stopped != done/error — force the idle terminal.
            self._stop_requested = True
            ok = False
        except Exception:
            ok = False
        finally:
            self._executing = False
        # Terminal transition: STOP wins over completion (pble_runner.c worker:
        # term = stop_requested ? stopped : finished).
        if self._stop_requested:
            self._terminalize_stopped()
        else:
            # The predecessor owns this terminal value and console lease. End
            # its input before exposing a terminal RSM state that a scheduled
            # BLE callback may immediately replace with a successor RUN.
            self._end_active_input()
            terminal = self._finish_status(ok, self._terminal_status_id)
            if terminal == IDLE:
                self.rsm.on_stopped()
            else:
                self.rsm.on_finished(terminal == DONE)
            self._emit_owned_state(
                terminal, self._terminal_owner,
                self._terminal_input_generation)
            self._terminal_phase = _TERMINAL_NONE
            self._terminal_prepared = False
            self._terminal_owner = None
            self._terminal_input_generation = None
        self._active_owner = None
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
