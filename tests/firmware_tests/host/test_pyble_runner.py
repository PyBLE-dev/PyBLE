#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Host tests for F-04 `pyble_runner` (RUN file + RUN_STATE + single-program
# EBUSY). M1/G1, Sprint S3. Sole [red] author: firmware-test-author. Production
# module owner (HAND-OFF for [green]): runtime-engineer ->
# firmware/pyble/pyble_runner.py (native twin pble_runner.c).
#
# =====================================================================
# DoR STATUS — BLOCKED (do NOT commit [red] before the freeze):
#   protocol.md §6 (Run / Stop / Console) is DRAFT (freeze ledger, 2026-07-01).
#   Per the architect DoR, F-04 is ready:false until §6 freezes (RUN{mode,path}
#   shape, RSP-then-RUN_STATE(running) sequence, running->done/error, EBUSY) and
#   is mirrored into specs.md FR-RUN. Until then this suite asserts ONLY the
#   FROZEN SEMANTICS via a PURE run-state-machine seam (the F-04 refactor
#   extracts one for reuse by RUN source + STOP) — it NEVER hardcodes a DRAFT
#   RUN payload byte, and it NEVER spawns a task. The actual separate-task
#   spawn, link-stays-responsive, and HIL run-file are HIL-only (see
#   gates/g1_s3_check.sh).
# =====================================================================
#
# FROZEN references: protocol.md §4 (0x20 RUN, 0x40 RUN_STATE), §8 (EBUSY 0x07);
# specs.md FR-RUN-1/3/4/7/9, NFR-SAFE-1/2, NFR-REL-1; architect contract
# (state 0 idle / 1 running / 2 done / 3 error; runner task SEPARATE from the
# NimBLE host task; RUN_STATE emitted thread-safely on each transition).
#
# ---------------------------------------------------------------------------
# INTERFACE PINNED BY THIS [red] TEST (runtime-engineer implements to it):
#   pyble_runner.IDLE / RUNNING / DONE / ERROR : int == 0 / 1 / 2 / 3
#   pyble_runner.EBUSY : int == 0x07
#   pyble_runner.RunStateMachine():         # the PURE seam (F-04 refactor)
#       .state -> int                        # current state, starts IDLE
#       .on_run() -> int                     # OK(0x00) if spawnable; EBUSY if RUNNING
#       .on_started() -> None                # -> RUNNING (a run actually began)
#       .on_finished(ok: bool) -> None       # -> DONE (ok) / ERROR (not ok)
#       .events -> list[int]                 # RUN_STATE values emitted, in order
# The REAL runner (task spawn, file exec, CONSOLE_DATA traceback) drives this
# seam but is HIL-verified, not exercised here.
# ---------------------------------------------------------------------------

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

RUNNER = _support.RedReason("pyble_runner", owner="runtime-engineer")

OK, EBUSY = 0x00, 0x07


def sm(testcase, criterion):
    cls = RUNNER.attr(testcase, "RunStateMachine", criterion)
    return cls()


class StateConstantsTest(unittest.TestCase):
    """Architect contract: state enum 0 idle / 1 running / 2 done / 3 error."""

    def test_state_constants(self):
        self.assertEqual(RUNNER.attr(self, "IDLE", "F-04 state IDLE=0"), 0)
        self.assertEqual(RUNNER.attr(self, "RUNNING", "F-04 state RUNNING=1"), 1)
        self.assertEqual(RUNNER.attr(self, "DONE", "F-04 state DONE=2"), 2)
        self.assertEqual(RUNNER.attr(self, "ERROR", "F-04 state ERROR=3"), 3)


class RunLifecycleTest(unittest.TestCase):
    """FR-RUN-1/7: RUN starts a run then the board reports RUN_STATE(running);
    FR-RUN-9: normal completion -> RUN_STATE(done); uncaught -> RUN_STATE(error)."""

    def test_starts_idle(self):
        m = sm(self, "F-04/FR-RUN-7 starts idle")
        self.assertEqual(m.state, RUNNER.attr(self, "IDLE", "F-04 IDLE"))

    def test_run_then_running_then_done(self):
        idle = RUNNER.attr(self, "IDLE", "F-04 IDLE")
        running = RUNNER.attr(self, "RUNNING", "F-04 RUNNING")
        done = RUNNER.attr(self, "DONE", "F-04 DONE")
        m = sm(self, "F-04/FR-RUN-1 run->running->done")
        self.assertEqual(m.on_run(), OK, "a RUN from idle MUST be accepted (OK)")
        m.on_started()
        self.assertEqual(m.state, running, "after a run begins the state MUST be RUNNING")
        m.on_finished(True)
        self.assertEqual(m.state, done, "normal completion MUST be DONE")
        # FR-RUN-7: a RUN_STATE event on EVERY transition.
        self.assertEqual(list(m.events), [running, done],
                         "RUN_STATE MUST be emitted on each transition (running, done)")

    def test_uncaught_exception_goes_to_error(self):
        running = RUNNER.attr(self, "RUNNING", "F-04 RUNNING")
        error = RUNNER.attr(self, "ERROR", "F-04 ERROR")
        m = sm(self, "F-04/FR-RUN-9 uncaught -> error")
        m.on_run()
        m.on_started()
        m.on_finished(False)
        self.assertEqual(m.state, error, "an uncaught exception MUST end in ERROR")
        self.assertEqual(list(m.events), [running, error],
                         "RUN_STATE(running) then RUN_STATE(error) MUST be emitted")


class SingleProgramEbusyTest(unittest.TestCase):
    """FR-RUN-4: only one user program runs at a time; a RUN issued while one is
    running MUST be answered EBUSY (no second spawn)."""

    def test_second_run_while_running_is_ebusy(self):
        m = sm(self, "F-04/FR-RUN-4 second RUN -> EBUSY")
        self.assertEqual(m.on_run(), OK)
        m.on_started()
        self.assertEqual(m.on_run(), EBUSY,
                         "a RUN while one is RUNNING MUST return EBUSY (0x07)")

    def test_ebusy_does_not_emit_a_new_run_state(self):
        running = RUNNER.attr(self, "RUNNING", "F-04 RUNNING")
        m = sm(self, "F-04/FR-RUN-4 EBUSY does not re-transition")
        m.on_run()
        m.on_started()
        m.on_run()  # rejected EBUSY
        self.assertEqual(list(m.events), [running],
                         "an EBUSY-rejected RUN MUST NOT emit a second RUN_STATE(running)")

    def test_run_allowed_again_after_completion(self):
        m = sm(self, "F-04/FR-RUN-4 run allowed after completion")
        m.on_run()
        m.on_started()
        m.on_finished(True)
        self.assertEqual(m.on_run(), OK,
                         "after DONE the runner MUST accept a new RUN")


if __name__ == "__main__":
    unittest.main(verbosity=2)
