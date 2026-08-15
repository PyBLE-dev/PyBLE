// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_runner — the PyBLE execution control plane: run user code (file OR source)
// on a MicroPython _thread WORKER that is SEPARATE from both the NimBLE host task
// and the main-task REPL, emit RUN_STATE (0x40) on every transition, enforce
// single-active-program EBUSY, and service STOP / SOFT_REBOOT from the host task
// without ever blocking the link (protocol.md §4/§6/§8; FR-RUN-1..10, FR-BLE-11,
// FR-MODE-3, NFR-SAFE-1/2, NFR-REL-1, SEC-3).
//
// EXECUTION MODEL (frozen by the runtime owner — VM-thread, NOT appliance):
//   - User Python runs on a MicroPython _thread WORKER (MICROPY_PY_THREAD=1),
//     launched ONCE at boot via `_thread.start_new_thread(pble_runner.worker,())`.
//     The worker has valid VM thread state; a user `while True: pass` blocks ONLY
//     the worker — the NimBLE host task and the main-task REPL stay live.
//   - The 0x20/0x21/0x22 handlers run on the NimBLE host task (pble_proto_dispatch)
//     and NEVER execute user Python inline. RUN reserves + copies, admits only
//     after one connection-bound zero-wait RSP{OK} submission, then hands off;
//     STOP stores a KeyboardInterrupt into the WORKER's own VM state; SOFT_REBOOT
//     stops the worker then marshals a VM soft-reset to the MAIN task (the only
//     VM-safe site for mp_deinit/mp_init).
//   - RUN_STATE (0x40) is emitted on EVERY transition via pble_proto_emit (EVT,
//     ID=0) -> pble_ble_notify; the app never polls (FR-RUN-7, FR-MODE-3).
//
// Clean-room: authored fresh against protocol.md + the public MicroPython/ESP-IDF
// API. No proprietary source is referenced.
#ifndef PBLE_RUNNER_H
#define PBLE_RUNNER_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#include "pble_proto.h"   // pble_frame_t, pble_handler_t, pble_proto_register/emit

// --- Run lifecycle states (architect contract; = RUN_STATE 0x40 values) ------
// protocol.md §4 (0x40 RUN_STATE): idle / running / done / error.
enum {
    PBLE_RUN_IDLE    = 0,
    PBLE_RUN_RUNNING = 1,
    PBLE_RUN_DONE    = 2,
    PBLE_RUN_ERROR   = 3,
};

// --- RUN payload discriminator (protocol.md §6 RUN{mode,data}) ---------------
// §6-DRAFT: the RUN payload wire ([mode][data]) freezes at S4. Isolated here so
// the freeze touches one place (see the §6-DRAFT note in pble_runner.c).
enum {
    PBLE_RUN_MODE_FILE   = 0,   // data = UTF-8 workspace path
    PBLE_RUN_MODE_SOURCE = 1,   // data = UTF-8 source snippet
};

// --- Pure run-state machine (the reusable seam) ------------------------------
// The single-owner transition core. Standalone value type with no I/O of its own
// (emission is the caller's job) so an EBUSY-rejected RUN cannot emit a spurious
// RUN_STATE. RUN-file, RUN-source, STOP and SOFT_REBOOT all reuse this seam.
typedef struct {
    int state;   // one of PBLE_RUN_*
} pble_rsm_t;

void    pble_rsm_init(pble_rsm_t *m);                  // -> IDLE
uint8_t pble_rsm_on_run(pble_rsm_t *m);                // OK if spawnable, else EBUSY
                                                       //   (atomically reserves RUNNING)
int     pble_rsm_on_started(pble_rsm_t *m);            // -> RUNNING; returns new state
int     pble_rsm_on_finished(pble_rsm_t *m, bool ok);  // -> DONE/ERROR; returns new state
int     pble_rsm_on_stopped(pble_rsm_t *m);            // -> IDLE (STOP terminal); returns new state

// --- Dispatch surface (registered into pble_proto; run on the NimBLE host task)
// 0x20 RUN — validate/reserve/copy, submit the matching RSP{OK} once without
// waiting, then hand off only on local acceptance. RUN_STATE(running) follows
// from the worker. Admission failure rolls back and suppresses response fallback.
uint8_t pble_runner_run(const pble_frame_t *req, uint8_t *rsp, size_t *rlen,
                        const pble_session_token_t *conn);
// 0x21 STOP — idempotent; RSP{OK} always. If running, inject KeyboardInterrupt
// into the WORKER's own VM state (FR-RUN-5/6/10). Link stays live (FR-BLE-11).
uint8_t pble_runner_stop(const pble_frame_t *req, uint8_t *rsp, size_t *rlen,
                         const pble_session_token_t *conn);
// 0x22 SOFT_REBOOT — RSP{OK}; stop the worker then marshal a VM soft-reset to the
// MAIN task; terminal -> RUN_STATE(idle) (FR-RUN-8).
uint8_t pble_runner_soft_reboot(const pble_frame_t *req, uint8_t *rsp,
                                size_t *rlen,
                                const pble_session_token_t *conn);

// Auto-run hand-off (F-12): run a workspace file on the WORKER from a NON-dispatch
// caller — pble_boot's opt-in /main.py auto-run. Reserves the single run (or refuses
// EBUSY if one is active, ERANGE on a bad path length), captures the path, and wakes
// the worker; RUN_STATE(running) then follows from the worker exactly as a RUN{file}
// dispatch would. Call from a valid MP thread (the pble_boot MP wrapper, after the
// worker is up). NEVER executes user code inline — a broken/looping /main.py lands on
// the worker, never the caller (NFR-SAFE-2, FR-BOOT-4/6).
uint8_t pble_runner_run_file(const char *path);

// Current lifecycle state (0 idle / 1 running / 2 done / 3 error).
int  pble_runner_state(void);

// True only while STOP/soft-reboot is unwinding the active worker. Console
// output uses this read-only signal to abandon the remainder of a flood.
bool pble_runner_stop_requested(void);

// Register 0x20/0x21/0x22 into pble_proto and provision the hand-off primitives.
// Idempotent; call once at boot from init_agent() BEFORE the worker is launched.
void pble_runner_register(void);

// Retained-VM lifecycle hooks. Timer disarm consumes only the residual of the
// wrapper's absolute deadline; reset drains stale hand-offs and retained state;
// detach prevents old worker pointers surviving upstream thread deletion.
bool pble_runner_vm_timer_disarm(int64_t deadline_us);
void pble_runner_vm_reset(void);
void pble_runner_vm_detach(void);

// MicroPython _thread WORKER entry — launched ONCE from _boot.py via
// `_thread.start_new_thread(pble_runner.worker, ())` AFTER init_agent(). Captures
// its own mp_state_thread_t for STOP targeting, then blocks serving runs. Runs
// user code with valid VM state on a task SEPARATE from the NimBLE host and the
// main-task REPL. Does not return.
void pble_runner_worker(void);

#endif // PBLE_RUNNER_H
