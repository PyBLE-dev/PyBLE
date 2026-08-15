#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Host tests for the F-25 rpi-pico2-w runner (port spec P2/P3; plan
# PART 3 test 5). Sole [red] author: firmware-test-author. Production module
# owner (HAND-OFF for [green]): agent-engineer -> firmware/pyble/pyble_runner.py
# (C reference twin: firmware/user_c_modules/pyble/pble_runner.c).
#
# FROZEN references: protocol.md §4 (0x20 RUN / 0x21 STOP / 0x40 RUN_STATE),
# §6 (RUN [mode:u8][data], RSP-then-RUN_STATE(running), STOP -> idle), §8
# (EBADREQ 0x01, EBUSY 0x07, ERANGE 0x09); ports/rpi-pico2-w.md P2 (validate ->
# reserve -> RSP only; supervisor executes), P3 (stopped != done/error), P6
# (path <= 128, source <= 2048).
#
# ---------------------------------------------------------------------------
# INTERFACE PINNED BY THIS [red] TEST (agent-engineer implements to it):
#   pyble_runner.MODE_FILE   : int == 0      # §6 RUN mode 0 = file path
#   pyble_runner.MODE_SOURCE : int == 1      # §6 RUN mode 1 = inline source
#   pyble_runner.RUN_PATH_MAX   : int == 128   # P6 (pble_runner.c PBLE_RUN_PATH_MAX)
#   pyble_runner.RUN_SOURCE_MAX : int == 2048  # P6 (pble_runner.c PBLE_RUN_BUF_MAX)
#   RunStateMachine.on_stopped() -> int      # -> IDLE; appends IDLE to .events
#                                            # (pble_rsm_on_stopped twin — the
#                                            #  transition missing from the S3 twin)
#   pyble_runner.Runner(emit_state, exec_fn) # the rp2 single-thread runner seam
#       .handle_run(payload: bytes) -> int   # §8 status. Validates the §6
#            # [mode:u8][data] payload BEFORE rsm.on_run() (a bad request can
#            # never wedge the reservation), reserves on OK, captures the
#            # request for the supervisor, and NEVER emits or executes inline.
#       .handle_stop() -> int                # always OK (0x00); arms stop intent
#       .service() -> bool                   # supervisor pickup: if a run is
#            # pending, clear any stale stop intent (fresh run — pble_runner.c
#            # worker loop: g_stop_requested = false), emit RUN_STATE(running)
#            # via emit_state, call exec_fn(mode:int, data:bytes) and emit the
#            # terminal state:
#            # normal return -> DONE; KeyboardInterrupt -> IDLE; any other
#            # uncaught exception -> ERROR; stop requested during the run ->
#            # IDLE (term = stop_requested ? stopped : finished). Returns True
#            # iff a run was serviced.
#       .rsm : RunStateMachine               # the pure seam (kept per plan C9)
#   emit_state(state_int) is called for every RUN_STATE transition, in order.
# ---------------------------------------------------------------------------

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

RUNNER = _support.RedReason("pyble_runner", owner="agent-engineer")

OK, EBADREQ, EBUSY, ERANGE = 0x00, 0x01, 0x07, 0x09
IDLE, RUNNING, DONE, ERROR = 0, 1, 2, 3

GOOD_SOURCE = bytes((1,)) + b"x = 1"   # [mode=source][tiny snippet]


def make_runner(testcase, criterion, exec_fn=None):
    """Build a Runner with a recording emit_state and a recording exec_fn.
    Returns (runner, emitted_states, exec_calls)."""
    cls = RUNNER.attr(testcase, "Runner", criterion)
    emitted = []
    calls = []

    def default_exec(mode, data):
        calls.append((mode, bytes(data)))

    runner = cls(emitted.append, exec_fn if exec_fn is not None else default_exec)
    return runner, emitted, calls


class ModeAndBoundConstantsTest(unittest.TestCase):
    """P6/§6: the RUN payload modes and the per-handler bounds are module
    constants mirroring pble_runner.c (never re-derived per call site)."""

    def test_mode_constants(self):
        self.assertEqual(RUNNER.attr(self, "MODE_FILE", "F-25/§6 MODE_FILE=0"), 0)
        self.assertEqual(RUNNER.attr(self, "MODE_SOURCE", "F-25/§6 MODE_SOURCE=1"), 1)

    def test_bound_constants(self):
        self.assertEqual(RUNNER.attr(self, "RUN_PATH_MAX", "F-25/P6 path<=128"), 128)
        self.assertEqual(RUNNER.attr(self, "RUN_SOURCE_MAX", "F-25/P6 source<=2048"), 2048)


class RsmOnStoppedTest(unittest.TestCase):
    """P3/§6: STOP terminal — a stopped run returns to IDLE (never done/error).
    pble_rsm_on_stopped twin; the transition is missing from the S3 scaffold."""

    def _machine(self, criterion):
        cls = RUNNER.attr(self, "RunStateMachine", criterion)
        m = cls()
        if not hasattr(m, "on_stopped"):
            self.fail(
                "[{crit}] unmet: RunStateMachine.on_stopped missing — the "
                "pble_rsm_on_stopped twin (pble_runner.c) is pinned by this "
                "[red] test. HAND-OFF: agent-engineer.".format(crit=criterion)
            )
        return m

    def test_on_stopped_returns_to_idle(self):
        m = self._machine("F-25/P3 stopped->IDLE")
        m.on_run()
        m.on_started()
        m.on_stopped()
        self.assertEqual(m.state, IDLE, "a stopped run MUST return to IDLE")

    def test_on_stopped_emits_idle_not_done_or_error(self):
        m = self._machine("F-25/P3 stopped emits RUN_STATE(idle)")
        m.on_run()
        m.on_started()
        m.on_stopped()
        self.assertEqual(list(m.events), [RUNNING, IDLE],
                         "STOP MUST emit RUN_STATE(idle) — never done/error (§6)")

    def test_run_allowed_again_after_stop(self):
        m = self._machine("F-25/P3 run allowed after stop")
        m.on_run()
        m.on_started()
        m.on_stopped()
        self.assertEqual(m.on_run(), OK, "after a STOP the runner MUST accept a new RUN")


class ValidateBeforeReserveTest(unittest.TestCase):
    """P2 (pble_runner.c pble_runner_run twin): the §6 [mode][data] payload is
    validated BEFORE the reservation, so a bad request never wedges the runner
    and never emits a RUN_STATE."""

    CRIT = "F-25/P2 validate-before-reserve"

    def test_empty_payload_is_ebadreq(self):
        r, emitted, _ = make_runner(self, self.CRIT)
        self.assertEqual(r.handle_run(b""), EBADREQ, "no mode byte -> EBADREQ")
        self.assertEqual(r.rsm.state, IDLE, "a rejected RUN MUST NOT reserve")
        self.assertEqual(emitted, [], "a rejected RUN MUST NOT emit RUN_STATE")

    def test_bad_mode_is_ebadreq(self):
        r, emitted, _ = make_runner(self, self.CRIT)
        self.assertEqual(r.handle_run(bytes((2,)) + b"x"), EBADREQ,
                         "mode not in {0,1} -> EBADREQ (§6)")
        self.assertEqual(r.rsm.state, IDLE)
        self.assertEqual(emitted, [])

    def test_file_mode_empty_path_is_erange(self):
        r, _, _ = make_runner(self, self.CRIT)
        self.assertEqual(r.handle_run(bytes((0,))), ERANGE,
                         "file mode with a 0-length path -> ERANGE")
        self.assertEqual(r.rsm.state, IDLE)

    def test_file_mode_overlong_path_is_erange(self):
        r, _, _ = make_runner(self, self.CRIT)
        self.assertEqual(r.handle_run(bytes((0,)) + b"a" * 129), ERANGE,
                         "path > 128 bytes -> ERANGE (P6)")
        self.assertEqual(r.rsm.state, IDLE)

    def test_file_mode_boundary_path_is_ok(self):
        r, _, _ = make_runner(self, self.CRIT)
        self.assertEqual(r.handle_run(bytes((0,)) + b"a" * 128), OK,
                         "path == 128 bytes is within bounds")

    def test_source_mode_overlong_is_erange(self):
        r, _, _ = make_runner(self, self.CRIT)
        self.assertEqual(r.handle_run(bytes((1,)) + b"a" * 2049), ERANGE,
                         "source > 2048 bytes -> ERANGE (P6)")
        self.assertEqual(r.rsm.state, IDLE)

    def test_source_mode_boundary_is_ok(self):
        r, _, _ = make_runner(self, self.CRIT)
        self.assertEqual(r.handle_run(bytes((1,)) + b"a" * 2048), OK,
                         "source == 2048 bytes is within bounds")

    def test_rejection_never_wedges_the_reservation(self):
        r, _, _ = make_runner(self, self.CRIT)
        self.assertEqual(r.handle_run(bytes((0,)) + b"a" * 200), ERANGE)
        self.assertEqual(r.handle_run(GOOD_SOURCE), OK,
                         "a rejected RUN MUST leave the runner able to accept "
                         "the next RUN (validation precedes the reserve)")


class EbusyReserveNoEmitTest(unittest.TestCase):
    """FR-RUN-4 / P2: RUN reserves atomically at the handler; a second RUN while
    reserved is EBUSY with no capture, no execution, and no RUN_STATE."""

    CRIT = "F-25/P2 EBUSY-reserve-no-emit"

    def test_second_run_is_ebusy_before_any_emission(self):
        r, emitted, calls = make_runner(self, self.CRIT)
        self.assertEqual(r.handle_run(GOOD_SOURCE), OK)
        self.assertEqual(r.handle_run(GOOD_SOURCE), EBUSY,
                         "a RUN while one is reserved MUST return EBUSY (0x07)")
        self.assertEqual(emitted, [],
                         "neither the reserve nor the EBUSY refusal may emit "
                         "RUN_STATE — emission is supervisor work")
        self.assertEqual(calls, [], "the handler NEVER executes user code inline")

    def test_ebusy_never_adds_an_extra_transition(self):
        r, emitted, _ = make_runner(self, self.CRIT)
        r.handle_run(GOOD_SOURCE)
        r.handle_run(GOOD_SOURCE)  # EBUSY
        self.assertTrue(r.service(), "the reserved run MUST be serviced")
        self.assertEqual(emitted, [RUNNING, DONE],
                         "exactly one running->done pair — the EBUSY-rejected "
                         "RUN MUST NOT add transitions")


class RspPrecedesRunStateTest(unittest.TestCase):
    """P2/§6: the RSP status is decided and returned by handle_run; RUN_STATE
    (running) is emitted only at supervisor pickup — RSP < RUN_STATE(running)
    is structural (handler vs supervisor)."""

    CRIT = "F-25/P2 RSP-precedes-RUN_STATE"

    def test_no_emission_at_handler_time(self):
        r, emitted, calls = make_runner(self, self.CRIT)
        self.assertEqual(r.handle_run(GOOD_SOURCE), OK)
        self.assertEqual(emitted, [],
                         "after handle_run returns (the RSP moment) no "
                         "RUN_STATE may have been emitted yet")
        self.assertEqual(calls, [], "no inline execution at handler time")

    def test_service_emits_running_then_terminal(self):
        r, emitted, calls = make_runner(self, self.CRIT)
        r.handle_run(bytes((1,)) + b"print(1)")
        self.assertTrue(r.service())
        self.assertEqual(emitted, [RUNNING, DONE],
                         "supervisor pickup MUST emit RUN_STATE(running) then "
                         "the terminal state")
        self.assertEqual(calls, [(1, b"print(1)")],
                         "exec_fn(mode, data) receives the captured request verbatim")

    def test_service_with_nothing_pending_is_a_noop(self):
        r, emitted, _ = make_runner(self, self.CRIT)
        self.assertFalse(r.service(), "no pending run -> service() returns False")
        self.assertEqual(emitted, [], "an idle service MUST NOT emit")


class TerminalStateTest(unittest.TestCase):
    """§6/P3: a terminal RUN_STATE is ALWAYS emitted — done on normal return,
    error on an uncaught exception, idle on KeyboardInterrupt/STOP."""

    def test_uncaught_exception_emits_error(self):
        def boom(mode, data):
            raise ValueError("boom")

        r, emitted, _ = make_runner(self, "F-25/§6 uncaught->error", boom)
        r.handle_run(GOOD_SOURCE)
        r.service()
        self.assertEqual(emitted, [RUNNING, ERROR],
                         "an uncaught exception MUST still emit a terminal "
                         "RUN_STATE(error)")
        self.assertEqual(r.rsm.state, ERROR)

    def test_keyboard_interrupt_emits_idle(self):
        def kbi(mode, data):
            raise KeyboardInterrupt()

        r, emitted, _ = make_runner(self, "F-25/P3 stopped->idle", kbi)
        r.handle_run(GOOD_SOURCE)
        r.service()
        self.assertEqual(emitted, [RUNNING, IDLE],
                         "a KeyboardInterrupt (the STOP path, P3) MUST end in "
                         "RUN_STATE(idle) — never done/error")
        self.assertEqual(r.rsm.state, IDLE)

    def test_stop_accepted_before_terminal_cut_ends_idle(self):
        # The STOP acceptance cut precedes this execution callback's return, so
        # the later terminal cut must select stopped rather than finished.
        cell = {}

        def stop_then_return(mode, data):
            cell["r"].handle_stop()

        r, emitted, _ = make_runner(
            self, "F-25/P3 stop-raced-completion->idle", stop_then_return)
        cell["r"] = r
        r.handle_run(GOOD_SOURCE)
        r.service()
        self.assertEqual(emitted, [RUNNING, IDLE],
                         "a STOP accepted before normal completion's terminal "
                         "cut MUST land idle (stopped wins over done)")

    def test_run_allowed_again_after_terminal(self):
        r, _, _ = make_runner(self, "F-25/§6 run-after-terminal")
        r.handle_run(GOOD_SOURCE)
        r.service()
        self.assertEqual(r.handle_run(GOOD_SOURCE), OK,
                         "after a terminal state the runner MUST accept a new RUN")


class StaleStopClearedTest(unittest.TestCase):
    """P3/§6: STOP is idempotent (always OK, no emission while idle) and a stale
    stop intent from an idle STOP MUST NOT bleed into the next run."""

    CRIT = "F-25/P3 stale-stop-cleared"

    def test_idle_stop_is_ok_and_silent(self):
        r, emitted, _ = make_runner(self, self.CRIT)
        self.assertEqual(r.handle_stop(), OK,
                         "STOP while idle MUST be RSP{OK} (idempotent, §6)")
        self.assertEqual(emitted, [], "STOP while idle MUST NOT emit RUN_STATE")

    def test_stale_stop_does_not_turn_the_next_run_idle(self):
        r, emitted, _ = make_runner(self, self.CRIT)
        r.handle_stop()                      # idle STOP arms nothing durable
        r.handle_run(GOOD_SOURCE)
        r.service()
        self.assertEqual(emitted, [RUNNING, DONE],
                         "stop intent MUST be cleared at fresh-run pickup "
                         "(pble_runner.c: g_stop_requested = false) — the next "
                         "run terminates done, not idle")


if __name__ == "__main__":
    unittest.main(verbosity=2)
