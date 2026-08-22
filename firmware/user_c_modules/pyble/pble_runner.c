// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_runner — execution control plane as a native MicroPython USER_C_MODULE
// (ADR-0006: native C from day one). VM-thread model:
//   F-04 RUN file (0x20) + RUN_STATE (0x40) + single-active-program EBUSY;
//   F-05 RUN source ([mode][data]);
//   F-06 STOP (0x21) via per-worker KeyboardInterrupt + SOFT_REBOOT (0x22);
//   F-07 stdout/stderr tee + stdin via pble_console.
//
// DESIGN (frozen VM-thread contract; VM-safe & lean)
//   - User Python runs on a MicroPython _thread WORKER (pble_runner_worker),
//     launched ONCE from _boot.py after init_agent() via
//     `_thread.start_new_thread(pble_runner.worker, ())`. The worker has valid VM
//     thread state; a user `while True: pass` blocks ONLY the worker task — the
//     NimBLE host task and the main-task REPL stay live (FR-RUN-3, FR-BLE-11,
//     NFR-SAFE-2, NFR-REL-1).
//   - The 0x20/0x21/0x22 handlers run on the NimBLE host task and NEVER execute
//     user Python inline. RUN reserves (or refuses EBUSY), captures [mode][data],
//     and wakes the worker only after the bounded specialized RSP{OK} submission
//     succeeds. STOP writes a KeyboardInterrupt into the WORKER's OWN
//     VM state (NOT mp_sched_keyboard_interrupt(), which targets the MAIN/REPL
//     thread) so it lands inside the worker's tight loop. SOFT_REBOOT stops the
//     worker then marshals a VM soft-reset to the MAIN task.
//   - RUN_STATE (0x40) is emitted on EVERY transition via pble_proto_emit (EVT,
//     ID=0) -> pble_ble_notify; the app never polls (FR-RUN-7, FR-MODE-3).
//
// Clean-room: authored fresh against protocol.md + the public MicroPython/ESP-IDF
// API. No proprietary source is referenced.
#include <stdint.h>
#include <stdbool.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

#include "esp_timer.h"
#include "esp_system.h"

#include "py/runtime.h"      // nlr, mp_call_function_0, mp_handle_pending, mp_sched_exception
#include "py/obj.h"          // mp_obj_new_exception, mp_type_SystemExit, mp_obj_print_exception
#include "py/mpstate.h"      // MP_STATE_VM / MP_STATE_THREAD, mp_state_thread_t
#include "py/mpthread.h"     // mp_thread_get_state, GIL macros
#include "py/lexer.h"        // mp_lexer_new_from_file / _from_str_len
#include "py/parse.h"        // mp_parse, MP_PARSE_FILE_INPUT
#include "py/compile.h"      // mp_compile

#include "pble_runner.h"
#include "pble_ble.h"        // PBLE_TX_OK for transactional RUN admission
#include "pble_console.h"    // tee stdout/stderr, worker-origin gate
#include "pble_fs.h"         // non-blocking SOFT_REBOOT quiescence gate
#include "pble_vm_lifecycle.h"

// Port hook: wake the MAIN task out of a blocked readline so a marshalled
// soft-reset (SystemExit) is serviced promptly. Present on all esp32 variants.
extern void mp_hal_wake_main_task(void);

// --- Payload bounds (bounded; C3-lean) --------------------------------------
// §6-DRAFT: the RUN payload wire ([mode][data]) freezes at S4; isolated here so
// the freeze touches one block. Path bound covers workspace-relative paths;
// source bound caps a single RUN{source} snippet.
#define PBLE_RUN_PATH_MAX   128
#define PBLE_RUN_BUF_MAX    2048

// A successful NimBLE Notify submission can still be queued below ATT. Keep
// the VM alive for several negotiated connection intervals after RSP{OK} so
// the central can actually receive it before MicroPython tears its heap down.
#define PBLE_SOFT_REBOOT_GRACE_US 250000ULL

// --- Module state ------------------------------------------------------------
static pble_rsm_t g_rsm;                 // the run-state machine (single owner)
static portMUX_TYPE g_mux = portMUX_INITIALIZER_UNLOCKED;  // guards g_rsm
static SemaphoreHandle_t g_run_sem;      // host-task -> worker hand-off
static SemaphoreHandle_t g_control_resolution_sem;
static volatile bool g_control_unresolved;

// Captured at worker entry so STOP can target the WORKER's own pending-exception
// slot (a single volatile-word store — the same mechanism as mp_sched_exception,
// but per-thread rather than to the MAIN thread).
static mp_state_thread_t *volatile g_worker_state;
static volatile bool g_stop_requested;

// The active request, published under the run reservation (single writer).
static uint8_t g_run_mode;
static size_t  g_run_len;
static char    g_run_buf[PBLE_RUN_BUF_MAX];

// Created once from pble_runner_register(). The IDF timer task is independent
// of the NimBLE host task, so the host never sleeps while honoring the delivery
// grace. The pending flag is guarded by g_mux across the two tasks.
static esp_timer_handle_t g_soft_reboot_timer;
static volatile bool g_soft_reboot_pending;
static uint64_t g_soft_reboot_epoch;

// Pre-created SystemExit for SOFT_REBOOT's main-task VM reset (rooted below).
MP_REGISTER_ROOT_POINTER(mp_obj_t pble_runner_sysexit);

// ============================================================================
// Pure run-state machine (the reusable seam)
// ============================================================================
void pble_rsm_init(pble_rsm_t *m) {
    m->state = PBLE_RUN_IDLE;
}

// OK if a run may proceed; EBUSY if one is already active. On OK it atomically
// reserves RUNNING so a concurrent RUN (a second dispatch on the host task) is
// refused before the worker emits RUN_STATE(running) — one active writer
// (SEC-3 / FR-RUN-4), no spurious transition on the EBUSY path.
uint8_t pble_rsm_on_run(pble_rsm_t *m) {
    if (m->state == PBLE_RUN_RUNNING) {
        return PBLE_EBUSY;
    }
    m->state = PBLE_RUN_RUNNING;
    return PBLE_OK;
}

int pble_rsm_on_started(pble_rsm_t *m) {
    m->state = PBLE_RUN_RUNNING;
    return m->state;
}

int pble_rsm_on_finished(pble_rsm_t *m, bool ok) {
    m->state = ok ? PBLE_RUN_DONE : PBLE_RUN_ERROR;
    return m->state;
}

// STOP terminal: a stopped run returns to IDLE (protocol.md §6 STOP -> idle).
int pble_rsm_on_stopped(pble_rsm_t *m) {
    m->state = PBLE_RUN_IDLE;
    return m->state;
}

// ============================================================================
// RUN_STATE emission (the only place the 0x40 payload is built)
// ============================================================================
// §6-DRAFT: RUN_STATE (0x40) carries the 1-byte lifecycle value; the §4 state
// enum is frozen, the single-byte encoding is provisional and isolated here.
// Emitted from the worker task; pble_ble_notify holds the NimBLE host mutex.
//
// PACED (not best-effort): RUN_STATE is a CONTROL event the client's UI is a
// state machine over — a dropped terminal `done` leaves the app believing a
// program is still running FOREVER (Run stays disabled, Stop stays armed). The
// unpaced emit dropped it on 8/8 print-heavy runs on HW, because a program that
// has just flooded CONSOLE_DATA leaves the msys pool drained at exactly the
// moment the terminal state is emitted. Park on the NOTIFY_TX drain event
// instead, like the fs-worker's streaming path (pble_fs.c fs_emit_paced).
#define PBLE_RUNSTATE_TX_BUDGET_MS 1000u

static void runner_emit_state(int st) {
    uint8_t b = (uint8_t)st;
    pble_session_token_t event_session;
    if (!pble_ble_session_snapshot_current(&event_session)) {
        return;
    }
    // Both call sites are on the runner worker with the GIL held; release it
    // across the bounded wait so the REPL + fs-worker keep running (the same
    // discipline as pble_fs.c's worker mailbox wait).
    MP_THREAD_GIL_EXIT();
    (void)pble_proto_emit_control_paced(PBLE_OP_RUN_STATE, &b, 1,
                                        PBLE_RUNSTATE_TX_BUDGET_MS,
                                        &event_session);
    MP_THREAD_GIL_ENTER();
}

// Mark a control response unresolved before leaving the runner domain for the
// bounded TX-boundary attempt. Drain a prior unused binary give first; a worker
// that was already released always loops and rechecks the predicate under g_mux.
static void runner_control_attempt_begin(void) {
    configASSERT(g_control_resolution_sem != NULL);
    while (xSemaphoreTake(g_control_resolution_sem, 0) == pdTRUE) {
    }
    taskENTER_CRITICAL(&g_mux);
    configASSERT(!g_control_unresolved);
    g_control_unresolved = true;
    taskEXIT_CRITICAL(&g_mux);
}

// Inject a KeyboardInterrupt into the WORKER's own VM state while the caller
// holds g_mux. The worker raises at its next VM pending-exception check
// (GIL_VM_DIVISOR=32), landing inside `while True: pass`.
static void inject_worker_kbd_interrupt(void) {
    mp_state_thread_t *ws = g_worker_state;
    if (ws != NULL) {
        MP_STATE_VM(mp_kbd_exception).traceback_data = NULL;
        ws->mp_pending_exception = MP_OBJ_FROM_PTR(&MP_STATE_VM(mp_kbd_exception));
    }
}

// Resolve both TX outcomes in one runner-domain cut. Only local response
// acceptance publishes stop intent; either outcome wakes a pickup waiter after
// the predicate is final and the runner lock has been released.
static void runner_control_attempt_resolve(bool accepted) {
    taskENTER_CRITICAL(&g_mux);
    configASSERT(g_control_unresolved);
    if (accepted) {
        g_stop_requested = true;
        inject_worker_kbd_interrupt();
    }
    g_control_unresolved = false;
    taskEXIT_CRITICAL(&g_mux);

    BaseType_t gave = xSemaphoreGive(g_control_resolution_sem);
    configASSERT(gave == pdTRUE);
    (void)gave;
}

bool pble_runner_stop_requested(void) {
    for (;;) {
        bool unresolved;
        bool requested;
        taskENTER_CRITICAL(&g_mux);
        unresolved = g_control_unresolved;
        requested = g_stop_requested;
        taskEXIT_CRITICAL(&g_mux);
        if (!unresolved) {
            return requested;
        }
        if (g_control_resolution_sem == NULL) {
            return true;
        }
        MP_THREAD_GIL_EXIT();
        (void)xSemaphoreTake(g_control_resolution_sem, portMAX_DELAY);
        MP_THREAD_GIL_ENTER();
    }
}

// ============================================================================
// Worker-side execution (own nlr boundary -> correct stdout/stderr tagging)
// ============================================================================
// Runs the captured code under our OWN nlr so an uncaught traceback is emitted
// as stderr via pble_console (NOT the platform printer, which would mis-tag it
// stdout). Returns true on clean completion, false on any uncaught exception
// (including STOP's KeyboardInterrupt and a missing/inaccessible file).
static bool runner_exec(uint8_t mode, const char *data, size_t len) {
    nlr_buf_t nlr;
    bool ok;
    if (nlr_push(&nlr) == 0) {
        qstr src_name;
        mp_lexer_t *lex;
        if (mode == PBLE_RUN_MODE_FILE) {
            src_name = qstr_from_str(data);          // NUL-terminated path
            lex = mp_lexer_new_from_file(src_name);  // raises OSError if absent
        } else {
            src_name = MP_QSTR__lt_stdin_gt_;
            lex = mp_lexer_new_from_str_len(src_name, data, len, 0);
        }
        mp_parse_tree_t parse_tree = mp_parse(lex, MP_PARSE_FILE_INPUT);
        mp_obj_t module_fun = mp_compile(&parse_tree, src_name, false);
        mp_call_function_0(module_fun);
        // Deliver a STOP that raced code completion (pending KBI) so it lands.
        mp_handle_pending(MP_HANDLE_PENDING_CALLBACKS_AND_EXCEPTIONS);
        nlr_pop();
        ok = true;
    } else {
        // STOP's injected KeyboardInterrupt is expected lifecycle control, not
        // a user failure. Suppress its traceback so it cannot compete with the
        // ordered STOP response and terminal idle event. Real exceptions keep
        // the frozen stderr traceback behavior (FR-RUN-9).
        if (!pble_runner_stop_requested()) {
            mp_obj_print_exception(&pble_console_stderr_print, MP_OBJ_FROM_PTR(nlr.ret_val));
        }
        ok = false;
    }
    return ok;
}

// Linearize natural completion against an in-flight STOP/SOFT_REBOOT response.
// A control whose begin cut came first owns the terminal decision; wait for its
// resolution without the GIL or runner lock, then classify and commit in one
// runner-domain cut so the resolver cannot slip between snapshot and mutation.
static int runner_terminal_transition(bool ok) {
    configASSERT(g_control_resolution_sem != NULL);

    for (;;) {
        bool unresolved;
        int term = PBLE_RUN_ERROR;

        taskENTER_CRITICAL(&g_mux);
        unresolved = g_control_unresolved;
        if (!unresolved) {
            bool stopped = g_stop_requested;
            term = stopped ? pble_rsm_on_stopped(&g_rsm)
                           : pble_rsm_on_finished(&g_rsm, ok);
            if (g_worker_state != NULL) {
                g_worker_state->mp_pending_exception = MP_OBJ_NULL;
            }
        }
        taskEXIT_CRITICAL(&g_mux);

        if (!unresolved) {
            return term;
        }
        MP_THREAD_GIL_EXIT();
        (void)xSemaphoreTake(g_control_resolution_sem, portMAX_DELAY);
        MP_THREAD_GIL_ENTER();
    }
}

// ============================================================================
// Worker loop — MicroPython _thread entry (valid VM thread state)
// ============================================================================
void pble_runner_worker(void) {
    uint64_t worker_epoch = pble_vm_epoch_current();
    g_worker_state = mp_thread_get_state();
    pble_console_set_worker((void *)g_worker_state);

    // Announce entry while holding the GIL, then release it so the main task's
    // final vm_ready() call can observe both workers and open admission. An
    // auto-run may already own the semaphore, but it cannot be consumed until
    // final boot wiring has crossed this barrier.
    pble_vm_worker_ready(PBLE_VM_WORKER_RUNNER);
    MP_THREAD_GIL_EXIT();
    bool epoch_ready = pble_vm_wait_ready_epoch(worker_epoch);
    MP_THREAD_GIL_ENTER();
    if (!epoch_ready) {
        return;
    }

    for (;;) {
        // Block until a RUN is reserved. Release the GIL while idle so the
        // main-task REPL runs freely; re-acquire before touching VM state.
        MP_THREAD_GIL_EXIT();
        xSemaphoreTake(g_run_sem, portMAX_DELAY);
        MP_THREAD_GIL_ENTER();

        // Snapshot the request (published under the reservation before the give;
        // the give/take pair is the happens-before barrier). Copy off g_run_buf
        // into a static buffer — not the worker's limited MP stack.
        static char local[PBLE_RUN_BUF_MAX + 1];
        uint8_t mode = g_run_mode;
        size_t len = g_run_len;
        if (len > PBLE_RUN_BUF_MAX) {
            len = PBLE_RUN_BUF_MAX;
        }
        memcpy(local, g_run_buf, len);
        local[len] = '\0';

        // Resolve any STOP/SOFT_REBOOT whose response attempt began before
        // pickup. An accepted control owns this reservation before any RUN event
        // or user-code effect; a failed attempt releases pickup unchanged.
        bool stopped_before_start = pble_runner_stop_requested();
        bool ok = false;
        if (!stopped_before_start) {
            runner_emit_state(pble_rsm_on_started(&g_rsm));
            // STOP may have been accepted while the paced RUN_STATE event was
            // in flight. Recheck through the same resolution gate before exec.
            if (!pble_runner_stop_requested()) {
                ok = runner_exec(mode, local, len);
            }
        }

        // Terminal transition: STOP -> idle; otherwise done/error. try/finally is
        // implicit — runner_exec always returns, so we always emit a terminal.
        int term = runner_terminal_transition(ok);
        if (!stopped_before_start) {
            runner_emit_state(term);   // RUN_STATE(idle | done | error)
        }
    }
}

// ============================================================================
// Dispatch surface (NimBLE host task) — RUN / STOP / SOFT_REBOOT
// ============================================================================
uint8_t pble_runner_run(const pble_frame_t *req, uint8_t *rsp, size_t *rlen,
                        const pble_session_token_t *conn) {
    (void)rsp;
    if (rlen) {
        *rlen = 0;   // RSP{status} carries no extra bytes
    }

    // §6-DRAFT: RUN payload = [mode:u8][data]. Validate BEFORE reserving so a bad
    // request can never wedge the reservation. This is the only place the RUN
    // payload is parsed, so freezing §6 touches just this block.
    if (req == NULL || conn == NULL || req->payload == NULL || req->len < 1) {
        return PBLE_EBADREQ;   // need at least the mode byte
    }
    uint8_t mode = req->payload[0];
    if (mode != PBLE_RUN_MODE_FILE && mode != PBLE_RUN_MODE_SOURCE) {
        return PBLE_EBADREQ;
    }
    size_t dlen = (size_t)req->len - 1;
    if (mode == PBLE_RUN_MODE_FILE) {
        if (dlen == 0 || dlen > PBLE_RUN_PATH_MAX) {
            return PBLE_ERANGE;
        }
    } else if (dlen > PBLE_RUN_BUF_MAX) {
        return PBLE_ERANGE;
    }
    if (g_run_sem == NULL) {
        return PBLE_EINTERNAL;
    }

    // Reserve provisionally (or refuse) under the single-writer critical
    // section. Remember the exact runnable state so every local TX failure can
    // roll back without manufacturing IDLE from DONE or ERROR.
    uint8_t status;
    int prior_state;
    taskENTER_CRITICAL(&g_mux);
    prior_state = g_rsm.state;
    status = pble_rsm_on_run(&g_rsm);
    if (status == PBLE_OK) {
        // Consume only STOP intent that predates this reservation. A later
        // accepted control writes both fields under this same mux and survives
        // until worker pickup.
        g_stop_requested = false;
        if (g_worker_state != NULL) {
            g_worker_state->mp_pending_exception = MP_OBJ_NULL;
        }
    }
    taskEXIT_CRITICAL(&g_mux);
    if (status != PBLE_OK) {
        return status;   // EBUSY: no capture, no wake, no RUN_STATE (FR-RUN-4)
    }

    // Reserved -> single writer of the request buffer.
    g_run_mode = mode;
    g_run_len = dlen;
    if (dlen) {
        memcpy(g_run_buf, req->payload + 1, dlen);
    }

    // The exact RSP{OK} is the admission cut. This call may wait under one
    // absolute 15 ms deadline only for the current complete-message TX boundary,
    // then rechecks the originating connection and attempts one local Notify.
    // Suppress generic dispatch fallback on both success and failure: a failed
    // local submission is a side-effect-free timeout, not a second response.
    int tx_rc = pble_proto_emit_rsp_status_try(req->opcode, req->id,
                                                PBLE_OK, conn);
    if (tx_rc != PBLE_TX_OK) {
        taskENTER_CRITICAL(&g_mux);
        g_rsm.state = prior_state;
        taskEXIT_CRITICAL(&g_mux);
        return PBLE_NO_RSP;
    }

    BaseType_t gave = xSemaphoreGive(g_run_sem);
    configASSERT(gave == pdTRUE);  // single reservation => binary sem was empty
    (void)gave;
    return PBLE_NO_RSP;
}

uint8_t pble_runner_stop(const pble_frame_t *req, uint8_t *rsp, size_t *rlen,
                         const pble_session_token_t *conn) {
    (void)rsp;
    if (rlen) {
        *rlen = 0;
    }
    if (req == NULL || conn == NULL) {
        return PBLE_NO_RSP;
    }

    // Bridge pickup across the TX attempt without nesting runner and TX locks.
    runner_control_attempt_begin();
    int tx_rc = pble_proto_emit_rsp_status_try(req->opcode, req->id,
                                                PBLE_OK, conn);
    if (tx_rc != PBLE_TX_OK) {
        runner_control_attempt_resolve(false);
        return PBLE_NO_RSP;
    }
    runner_control_attempt_resolve(true);
    return PBLE_NO_RSP;   // exact RSP already submitted; never duplicate it
}

static void soft_reboot_timer_cb(void *arg) {
    (void)arg;
    bool reset;
    uint64_t epoch;
    taskENTER_CRITICAL(&g_mux);
    reset = g_soft_reboot_pending;
    epoch = g_soft_reboot_epoch;
    taskEXIT_CRITICAL(&g_mux);
    if (!reset) {
        return;
    }

    pble_vm_activity_t activity = {0};
    if (!pble_vm_callback_enter(epoch, &activity)) {
        return;
    }

    // The SystemExit object is pre-created and rooted while the current VM is
    // valid. Schedule it only after the delivery grace; the main task remains
    // the sole mp_deinit/mp_init site.
    mp_obj_t se = MP_STATE_VM(pble_runner_sysexit);
    if (se != MP_OBJ_NULL) {
        mp_sched_exception(se);
        mp_hal_wake_main_task();
    }
    pble_vm_callback_leave(&activity);
}

static void runner_reboot_provisional_abort(uint64_t vm_epoch) {
    pble_vm_reboot_abort(vm_epoch);
    pble_fs_quiesce_abort();
}

uint8_t pble_runner_soft_reboot(const pble_frame_t *req, uint8_t *rsp,
                                size_t *rlen,
                                const pble_session_token_t *conn) {
    (void)rsp;
    if (rlen) {
        *rlen = 0;
    }
    if (req == NULL || conn == NULL) {
        return PBLE_NO_RSP;
    }
    if (MP_STATE_VM(pble_runner_sysexit) == MP_OBJ_NULL ||
        g_soft_reboot_timer == NULL) {
        return PBLE_EINTERNAL;
    }

    taskENTER_CRITICAL(&g_mux);
    if (g_soft_reboot_pending) {
        taskEXIT_CRITICAL(&g_mux);
        return PBLE_EBUSY;
    }
    taskEXIT_CRITICAL(&g_mux);

    // The FS gate is the first provisional cut. It closes enqueue only if the
    // worker and queue are atomically idle; otherwise it reopens itself and the
    // generic reserved response reports EBUSY with no reboot effect.
    if (!pble_fs_quiesce_try()) {
        return PBLE_EBUSY;
    }

    if (!pble_vm_reboot_close(conn->vm_epoch)) {
        runner_reboot_provisional_abort(conn->vm_epoch);
        return PBLE_NO_RSP;
    }

    taskENTER_CRITICAL(&g_mux);
    g_soft_reboot_pending = true;
    g_soft_reboot_epoch = conn->vm_epoch;
    taskEXIT_CRITICAL(&g_mux);

    // Only a provisionally quiesced reboot participates in the pickup gate.
    // Keep the TX domain outside g_mux, then resolve success/failure exactly
    // once after all failure rollback needed before worker wake.
    runner_control_attempt_begin();
    int tx_rc = pble_proto_emit_rsp_status_try(req->opcode, req->id,
                                               PBLE_OK, conn);
    if (tx_rc != PBLE_TX_OK) {
        taskENTER_CRITICAL(&g_mux);
        g_soft_reboot_pending = false;
        g_soft_reboot_epoch = 0;
        taskEXIT_CRITICAL(&g_mux);
        pble_vm_reboot_abort(conn->vm_epoch);
        pble_fs_quiesce_abort();
        runner_control_attempt_resolve(false);
        return PBLE_NO_RSP;
    }
    runner_control_attempt_resolve(true);

    // A valid, inactive, pre-created one-shot is an invariant while pending was
    // false. Once RSP{OK} was locally accepted, gates never reopen: if IDF
    // nevertheless refuses the arm, restart immediately rather than strand an
    // acknowledged reboot in an ambiguous live VM.
    if (esp_timer_start_once(g_soft_reboot_timer, PBLE_SOFT_REBOOT_GRACE_US) != ESP_OK) {
        esp_restart();
        return PBLE_NO_RSP;
    }

    // The accepted resolver already stopped the worker. The one-shot later
    // marshals a VM soft-reset to the MAIN task; init_agent() is idempotent, so
    // the BLE link is kept where possible (FR-RUN-8).
    return PBLE_NO_RSP;
}

// Auto-run entry (F-12): hand a file path to the WORKER exactly as pble_runner_run
// would for RUN{mode=file}, but from a non-dispatch caller (pble_boot on the MP main
// task). Reuses the single-writer reservation + hand-off so a concurrent RUN is still
// refused EBUSY (SEC-3 / FR-RUN-4) and user code lands on the worker, never inline.
uint8_t pble_runner_run_file(const char *path) {
    if (path == NULL) {
        return PBLE_EBADREQ;
    }
    size_t plen = strlen(path);
    if (plen == 0 || plen > PBLE_RUN_PATH_MAX) {
        return PBLE_ERANGE;
    }

    // Reserve the run (or refuse) under the same single-writer critical section as
    // the RUN handler — no spurious RUN_STATE on the EBUSY path.
    uint8_t status;
    taskENTER_CRITICAL(&g_mux);
    status = pble_rsm_on_run(&g_rsm);
    if (status == PBLE_OK) {
        g_stop_requested = false;
        if (g_worker_state != NULL) {
            g_worker_state->mp_pending_exception = MP_OBJ_NULL;
        }
    }
    taskEXIT_CRITICAL(&g_mux);
    if (status != PBLE_OK) {
        return status;
    }

    // Reserved -> single writer of the request buffer.
    g_run_mode = PBLE_RUN_MODE_FILE;
    g_run_len = plen;
    memcpy(g_run_buf, path, plen);
    xSemaphoreGive(g_run_sem);   // RUN_STATE(running) follows from the worker
    return PBLE_OK;
}

int pble_runner_state(void) {
    int s;
    taskENTER_CRITICAL(&g_mux);
    s = g_rsm.state;
    taskEXIT_CRITICAL(&g_mux);
    return s;
}

bool pble_runner_vm_timer_disarm(int64_t deadline_us) {
    if (esp_timer_get_time() >= deadline_us) {
        return false;
    }
    esp_err_t rc = ESP_ERR_INVALID_STATE;
    if (g_soft_reboot_timer != NULL) {
        rc = esp_timer_stop(g_soft_reboot_timer);
    }
    if (rc != ESP_OK && rc != ESP_ERR_INVALID_STATE) {
        return false;
    }
    taskENTER_CRITICAL(&g_mux);
    g_soft_reboot_pending = false;
    g_soft_reboot_epoch = 0;
    taskEXIT_CRITICAL(&g_mux);
    return esp_timer_get_time() < deadline_us;
}

void pble_runner_vm_detach(void) {
    taskENTER_CRITICAL(&g_mux);
    g_worker_state = NULL;
    taskEXIT_CRITICAL(&g_mux);
}

void pble_runner_vm_reset(void) {
    taskENTER_CRITICAL(&g_mux);
    pble_rsm_init(&g_rsm);
    g_stop_requested = false;
    g_control_unresolved = false;
    g_soft_reboot_pending = false;
    g_soft_reboot_epoch = 0;
    g_worker_state = NULL;
    g_run_mode = 0;
    g_run_len = 0;
    taskEXIT_CRITICAL(&g_mux);
    // Epoch begin runs with admission closed after old VM workers were deleted;
    // keep the interrupt-disabled section above bounded to scalar state.
    memset(g_run_buf, 0, sizeof(g_run_buf));
    if (g_run_sem != NULL) {
        while (xSemaphoreTake(g_run_sem, 0) == pdTRUE) {
        }
    }
    if (g_control_resolution_sem != NULL) {
        while (xSemaphoreTake(g_control_resolution_sem, 0) == pdTRUE) {
        }
    }
}

void pble_runner_register(void) {
    if (g_run_sem == NULL) {
        g_run_sem = xSemaphoreCreateBinary();
    }
    if (g_control_resolution_sem == NULL) {
        g_control_resolution_sem = xSemaphoreCreateBinary();
    }
    if (g_run_sem == NULL || g_control_resolution_sem == NULL) {
        mp_raise_msg(&mp_type_RuntimeError,
                     MP_ERROR_TEXT("runner semaphore alloc failed"));
    }
    if (g_soft_reboot_timer == NULL) {
        const esp_timer_create_args_t timer_args = {
            .callback = soft_reboot_timer_cb,
            .arg = NULL,
            .dispatch_method = ESP_TIMER_TASK,
            .name = "pble-soft-reboot",
        };
        if (esp_timer_create(&timer_args, &g_soft_reboot_timer) != ESP_OK) {
            mp_raise_msg(&mp_type_RuntimeError,
                         MP_ERROR_TEXT("soft reboot timer alloc failed"));
        }
    }
    // Pre-create the SOFT_REBOOT SystemExit while on a valid VM thread (register
    // runs from init_agent at boot). Rooted via the root pointer above.
    if (MP_STATE_VM(pble_runner_sysexit) == MP_OBJ_NULL) {
        MP_STATE_VM(pble_runner_sysexit) = mp_obj_new_exception(&mp_type_SystemExit);
    }
    pble_proto_register_special(PBLE_OP_RUN, pble_runner_run);
    pble_proto_register_special(PBLE_OP_STOP, pble_runner_stop);
    pble_proto_register_special(PBLE_OP_SOFT_REBOOT, pble_runner_soft_reboot);
}

// ============================================================================
// Thin MicroPython surface (boot wiring + HIL introspection)
// ============================================================================
// worker() is the _thread entry: `_thread.start_new_thread(pble_runner.worker,())`
// from _boot.py after init_agent(). It never returns. register() is idempotent
// (called from init_agent BEFORE the worker launches). state() aids HIL bring-up.
static mp_obj_t mod_pble_runner_worker(void) {
    pble_runner_worker();
    return mp_const_none;   // unreachable
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_pble_runner_worker_obj, mod_pble_runner_worker);

static mp_obj_t mod_pble_runner_register(void) {
    pble_runner_register();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_pble_runner_register_obj, mod_pble_runner_register);

static mp_obj_t mod_pble_runner_state(void) {
    return mp_obj_new_int(pble_runner_state());
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_pble_runner_state_obj, mod_pble_runner_state);

static const mp_rom_map_elem_t pble_runner_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_pble_runner) },
    { MP_ROM_QSTR(MP_QSTR_IDLE), MP_ROM_INT(PBLE_RUN_IDLE) },
    { MP_ROM_QSTR(MP_QSTR_RUNNING), MP_ROM_INT(PBLE_RUN_RUNNING) },
    { MP_ROM_QSTR(MP_QSTR_DONE), MP_ROM_INT(PBLE_RUN_DONE) },
    { MP_ROM_QSTR(MP_QSTR_ERROR), MP_ROM_INT(PBLE_RUN_ERROR) },
    { MP_ROM_QSTR(MP_QSTR_register), MP_ROM_PTR(&mod_pble_runner_register_obj) },
    { MP_ROM_QSTR(MP_QSTR_worker), MP_ROM_PTR(&mod_pble_runner_worker_obj) },
    { MP_ROM_QSTR(MP_QSTR_state), MP_ROM_PTR(&mod_pble_runner_state_obj) },
};
static MP_DEFINE_CONST_DICT(pble_runner_globals, pble_runner_globals_table);

const mp_obj_module_t pble_runner_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&pble_runner_globals,
};

MP_REGISTER_MODULE(MP_QSTR_pble_runner, pble_runner_user_cmodule);
