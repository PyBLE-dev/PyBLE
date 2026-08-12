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
//     wakes the worker, and returns a §8 status. STOP writes a KeyboardInterrupt
//     into the WORKER's OWN VM state (NOT mp_sched_keyboard_interrupt(), which
//     targets the MAIN/REPL thread) so it lands inside the worker's tight loop.
//     SOFT_REBOOT stops the worker then marshals a VM soft-reset to the MAIN task.
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

#include "py/runtime.h"      // nlr, mp_call_function_0, mp_handle_pending, mp_sched_exception
#include "py/obj.h"          // mp_obj_new_exception, mp_type_SystemExit, mp_obj_print_exception
#include "py/mpstate.h"      // MP_STATE_VM / MP_STATE_THREAD, mp_state_thread_t
#include "py/mpthread.h"     // mp_thread_get_state, GIL macros
#include "py/lexer.h"        // mp_lexer_new_from_file / _from_str_len
#include "py/parse.h"        // mp_parse, MP_PARSE_FILE_INPUT
#include "py/compile.h"      // mp_compile

#include "pble_runner.h"
#include "pble_console.h"    // tee stdout/stderr, worker-origin gate

// Port hook: wake the MAIN task out of a blocked readline so a marshalled
// soft-reset (SystemExit) is serviced promptly. Present on all esp32 variants.
extern void mp_hal_wake_main_task(void);

// --- Frozen wire numbers (mirror protocol.md §4/§8 — never redefined here) ----
// STOP/SOFT_REBOOT opcodes are frozen in §4; their §6 semantics freeze at S4.
// These consts move into pble_proto.h once protocol-engineer adds them.
#define PBLE_OP_STOP        0x21   // §4 STOP
#define PBLE_OP_SOFT_REBOOT 0x22   // §4 SOFT_REBOOT
// (PBLE_OP_RUN 0x20 / PBLE_OP_RUN_STATE 0x40 and the §8 status codes come from
//  pble_proto.h.)

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
    // Both call sites are on the runner worker with the GIL held; release it
    // across the bounded wait so the REPL + fs-worker keep running (the same
    // discipline as pble_fs.c's worker mailbox wait).
    MP_THREAD_GIL_EXIT();
    (void)pble_proto_emit_paced(PBLE_OP_RUN_STATE, &b, 1,
                                PBLE_RUNSTATE_TX_BUDGET_MS);
    MP_THREAD_GIL_ENTER();
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
        // Uncaught exception -> traceback to CONSOLE_DATA(stderr) (FR-RUN-9).
        mp_obj_print_exception(&pble_console_stderr_print, MP_OBJ_FROM_PTR(nlr.ret_val));
        ok = false;
    }
    // Never let a pending exception leak into the next run.
    MP_STATE_THREAD(mp_pending_exception) = MP_OBJ_NULL;
    return ok;
}

// ============================================================================
// Worker loop — MicroPython _thread entry (valid VM thread state)
// ============================================================================
void pble_runner_worker(void) {
    g_worker_state = mp_thread_get_state();
    pble_console_set_worker((void *)g_worker_state);

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

        // Fresh run: clear stop intent + any stale pending exception.
        g_stop_requested = false;
        MP_STATE_THREAD(mp_pending_exception) = MP_OBJ_NULL;

        runner_emit_state(pble_rsm_on_started(&g_rsm));   // RUN_STATE(running)

        bool ok = runner_exec(mode, local, len);

        // Terminal transition: STOP -> idle; otherwise done/error. try/finally is
        // implicit — runner_exec always returns, so we always emit a terminal.
        int term;
        taskENTER_CRITICAL(&g_mux);
        term = g_stop_requested ? pble_rsm_on_stopped(&g_rsm)
                                : pble_rsm_on_finished(&g_rsm, ok);
        taskEXIT_CRITICAL(&g_mux);
        runner_emit_state(term);   // RUN_STATE(idle | done | error)
    }
}

// ============================================================================
// Dispatch surface (NimBLE host task) — RUN / STOP / SOFT_REBOOT
// ============================================================================
uint8_t pble_runner_run(const pble_frame_t *req, uint8_t *rsp, size_t *rlen, uint16_t conn) {
    (void)rsp;
    (void)conn;
    if (rlen) {
        *rlen = 0;   // RSP{status} carries no extra bytes
    }

    // §6-DRAFT: RUN payload = [mode:u8][data]. Validate BEFORE reserving so a bad
    // request can never wedge the reservation. This is the only place the RUN
    // payload is parsed, so freezing §6 touches just this block.
    if (req == NULL || req->payload == NULL || req->len < 1) {
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

    // Reserve the run (or refuse) under the single-writer critical section. STOP
    // and read-only commands are never starved: the section only brackets the
    // tiny state test/transition.
    uint8_t status;
    taskENTER_CRITICAL(&g_mux);
    status = pble_rsm_on_run(&g_rsm);
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
    xSemaphoreGive(g_run_sem);   // RUN_STATE(running) follows from the worker
    return PBLE_OK;
}

// Inject a KeyboardInterrupt into the WORKER's own VM state. Single volatile-word
// store; safe from the (non-MP) NimBLE host task because it targets the captured
// worker thread state, not the current thread. The worker raises at its next VM
// pending-exception check (GIL_VM_DIVISOR=32), landing inside `while True: pass`.
static void inject_worker_kbd_interrupt(void) {
    mp_state_thread_t *ws = g_worker_state;
    if (ws != NULL) {
        MP_STATE_VM(mp_kbd_exception).traceback_data = NULL;
        ws->mp_pending_exception = MP_OBJ_FROM_PTR(&MP_STATE_VM(mp_kbd_exception));
    }
}

uint8_t pble_runner_stop(const pble_frame_t *req, uint8_t *rsp, size_t *rlen, uint16_t conn) {
    (void)req;
    (void)rsp;
    (void)conn;
    if (rlen) {
        *rlen = 0;
    }
    // Idempotent: STOP while idle is a no-op OK (the flag is cleared at next run
    // start). If running, the worker unwinds to RUN_STATE(idle) (FR-RUN-5/6/10).
    g_stop_requested = true;
    inject_worker_kbd_interrupt();
    return PBLE_OK;   // returns immediately from the host task (FR-BLE-11)
}

static void soft_reboot_timer_cb(void *arg) {
    (void)arg;
    bool reset;
    taskENTER_CRITICAL(&g_mux);
    reset = g_soft_reboot_pending;
    g_soft_reboot_pending = false;
    taskEXIT_CRITICAL(&g_mux);
    if (!reset) {
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
}

uint8_t pble_runner_soft_reboot(const pble_frame_t *req, uint8_t *rsp, size_t *rlen, uint16_t conn) {
    (void)rsp;
    (void)conn;
    if (rlen) {
        *rlen = 0;
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
    g_soft_reboot_pending = true;
    taskEXIT_CRITICAL(&g_mux);

    // Submit the one-packet RSP{OK} before arming teardown, then return the
    // internal no-RSP sentinel so dispatch cannot duplicate it. Local Notify
    // acceptance is not delivery, hence the bounded one-shot below.
    uint8_t status = PBLE_OK;
    if (pble_proto_emit_id(PBLE_TYPE_RSP, req->opcode, req->id, &status, 1) != 0) {
        taskENTER_CRITICAL(&g_mux);
        g_soft_reboot_pending = false;
        taskEXIT_CRITICAL(&g_mux);
        return PBLE_EBUSY;
    }

    // A valid, inactive, pre-created one-shot is an invariant while pending was
    // false. If IDF nevertheless refuses it, suppress the dispatcher's second
    // response (OK is already submitted), clear the reservation, and leave the
    // VM intact rather than perform an ambiguous immediate reset.
    if (esp_timer_start_once(g_soft_reboot_timer, PBLE_SOFT_REBOOT_GRACE_US) != ESP_OK) {
        taskENTER_CRITICAL(&g_mux);
        g_soft_reboot_pending = false;
        taskEXIT_CRITICAL(&g_mux);
        return PBLE_NO_RSP;
    }

    // Stop the worker while the response drains. The one-shot later marshals a
    // VM soft-reset to the MAIN task; init_agent() is idempotent, so the BLE
    // link is kept where possible (FR-RUN-8).
    g_stop_requested = true;
    inject_worker_kbd_interrupt();
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

void pble_runner_register(void) {
    if (g_run_sem == NULL) {
        g_run_sem = xSemaphoreCreateBinary();
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
    pble_rsm_init(&g_rsm);
    // Pre-create the SOFT_REBOOT SystemExit while on a valid VM thread (register
    // runs from init_agent at boot). Rooted via the root pointer above.
    if (MP_STATE_VM(pble_runner_sysexit) == MP_OBJ_NULL) {
        MP_STATE_VM(pble_runner_sysexit) = mp_obj_new_exception(&mp_type_SystemExit);
    }
    pble_proto_register(PBLE_OP_RUN, pble_runner_run);
    pble_proto_register(PBLE_OP_STOP, pble_runner_stop);
    pble_proto_register(PBLE_OP_SOFT_REBOOT, pble_runner_soft_reboot);
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
