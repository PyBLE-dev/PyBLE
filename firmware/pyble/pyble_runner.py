# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Pure host seam for the native pble_runner run-state machine.
#
# Worker creation, user-code execution, STOP delivery, and RUN_STATE transport
# remain native in pble_runner.c. This file mirrors only pble_rsm_* transitions
# for deterministic host verification and is not frozen into release images.

IDLE = 0
RUNNING = 1
DONE = 2
ERROR = 3

OK = 0x00
EBUSY = 0x07


class RunStateMachine:
    """Pure twin of the native single-program lifecycle seam."""

    def __init__(self):
        self.state = IDLE
        self.events = []

    def on_run(self):
        if self.state == RUNNING:
            return EBUSY
        # Reserve the single runner immediately. RUN_STATE is emitted only when
        # the worker actually starts, matching pble_rsm_on_run/on_started.
        self.state = RUNNING
        return OK

    def on_started(self):
        self.state = RUNNING
        self.events.append(RUNNING)

    def on_finished(self, ok):
        self.state = DONE if ok else ERROR
        self.events.append(self.state)
