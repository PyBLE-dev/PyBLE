// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_console — console tee + stdin bridge for a run (F-07). Native
// USER_C_MODULE (ADR-0006). CONSOLE_DATA (0x30) / CONSOLE_INPUT (0x31) per
// protocol.md §4/§6; FR-CON-1..5, FR-RUN-9, NFR-PERF-3, SEC-11.
//
// DESIGN (lean, thread-gated, upstream-never-edited)
//   - pble_console_out() is the SINGLE emit chokepoint. It is a no-op unless the
//     CURRENT task is the run WORKER, so main-task/REPL/UART output is NEVER teed
//     to BLE — while ANY connected client observes the run (observe-anywhere,
//     FR-CON-4). Output is chunked to the event budget; no unbounded heap growth.
//   - The worker's stdout reaches this chokepoint through a one-line stdout HAL
//     tee in the esp32 board overlay (build-smith / board_overlays, CON-1): it
//     calls pble_console_out(STDOUT, str, len) — the gate keeps REPL output out.
//     stderr is emitted directly by the worker's uncaught-exception traceback via
//     pble_console_stderr_print, so it is correctly tagged (FR-CON-2) without
//     passing through the platform printer (which would mis-tag it stdout).
//   - CONSOLE_INPUT bytes land in a bounded ring (host task); the worker's
//     input()/sys.stdin drain it via pble_console_stdin_getchar() (wired by the
//     same board-overlay stdin HAL hook, worker-gated). Fire-and-forget: the 0x31
//     handler returns PBLE_NO_RSP so dispatch emits no reply frame (FR-CON-3).
//
// Clean-room: authored fresh against protocol.md + the public MicroPython/ESP-IDF
// API. No proprietary source is referenced.
#include <stdint.h>
#include <stdbool.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "py/runtime.h"
#include "py/obj.h"
#include "py/stream.h"     // native stream protocol for the os.dupterm tee
#include "py/mperrno.h"    // MP_EAGAIN / MP_EINVAL
#include "py/mpthread.h"   // mp_thread_get_state — worker-origin gate

#include "pble_console.h"
#include "pble_ble.h"
#include "pble_runner.h"

// --- Frozen wire numbers (mirror protocol.md §4 — never redefined here) -------
// §4 CONSOLE_DATA/CONSOLE_INPUT opcodes are frozen; their §6 payloads freeze at
// S4. These consts move into pble_proto.h once protocol-engineer adds them; kept
// local until then so this module owns only its own files.
#define PBLE_OP_CONSOLE_DATA  0x30   // §4 CONSOLE_DATA (EVT: [stream][bytes])
#define PBLE_OP_CONSOLE_INPUT 0x31   // §4 CONSOLE_INPUT (CMD, no RSP)
// Internal sentinel: a handler returning this suppresses the RSP frame. Mirrors
// the PBLE_NO_RSP that protocol-engineer adds to pble_proto.c dispatch; never on
// the wire. Until that lands, a stray RSP{0xFE} is the only visible effect.
#define PBLE_NO_RSP           0xFE

// --- Tuning (bounded; C3-lean) ----------------------------------------------
// CONSOLE_DATA payload = [stream] + up to CHUNK bytes; fits one 247-MTU Notify
// with PBLE/1 framing, so a run's output streams without per-char fragmentation.
#define PBLE_CONSOLE_CHUNK 200
#define PBLE_CONSOLE_FRAME_OVERHEAD 15
#define PBLE_STDIN_RING    256   // bounded stdin staging (power-of-two)

// Per-chunk TX budget for CONSOLE_DATA. A tight `for i in range(80): print(...)`
// out-runs the link by ~3x, draining NimBLE's msys pool; the previous unpaced
// emit then DISCARDED the chunk, losing 70% of a program's output on HW. Pacing
// converts that loss into backpressure: the printing program is throttled to
// link speed instead. The budget is bounded so a wedged/absent link degrades to
// best-effort (drop this chunk, keep running) and never hangs user code — a
// program must never become unstoppable because a client stopped reading.
#define PBLE_CONSOLE_TX_BUDGET_MS 250u

// --- Module state ------------------------------------------------------------
static void *volatile g_worker;   // worker mp_state_thread_t*, else NULL

// stdin ring: written by the host task (0x31), drained by the worker. A tiny
// critical section (not a lock) keeps STOP and read-only commands unstarved.
static portMUX_TYPE g_ring_mux = portMUX_INITIALIZER_UNLOCKED;
static uint8_t g_ring[PBLE_STDIN_RING];
static uint16_t g_ring_head;   // next write
static uint16_t g_ring_tail;   // next read
static uint16_t g_ring_count;

// Emit staging: [stream][chunk]. Built only on the worker thread (single-writer),
// so no lock is needed here.
static uint8_t g_stage[1 + PBLE_CONSOLE_CHUNK];

// ============================================================================
// Worker-origin gate
// ============================================================================
void pble_console_set_worker(void *mp_state_thread) {
    g_worker = mp_state_thread;
}

static inline bool on_worker(void) {
    void *w = g_worker;
    return w != NULL && (void *)mp_thread_get_state() == w;
}

// ============================================================================
// stdout/stderr tee -> CONSOLE_DATA (0x30) — the single emit chokepoint
// ============================================================================
void pble_console_out(uint8_t stream_tag, const char *buf, size_t len) {
    if (len == 0 || buf == NULL) {
        return;
    }
    // Observe-anywhere but worker-only: REPL/main/UART output is never teed.
    if (!on_worker()) {
        return;
    }
    size_t max_chunk = pble_ble_mtu();
    if (max_chunk <= PBLE_CONSOLE_FRAME_OVERHEAD) {
        return;
    }
    max_chunk -= PBLE_CONSOLE_FRAME_OVERHEAD;
    if (max_chunk > PBLE_CONSOLE_CHUNK) {
        max_chunk = PBLE_CONSOLE_CHUNK;
    }

    g_stage[0] = stream_tag;
    size_t off = 0;
    while (off < len && !pble_runner_stop_requested()) {
        size_t n = len - off;
        if (n > max_chunk) {
            n = max_chunk;
        }
        memcpy(g_stage + 1, buf + off, n);
        // pble_proto_emit_paced encodes [stream][bytes] as an EVT (ID=0) and
        // Notifies, parking on the NOTIFY_TX drain event when NimBLE's msys pool
        // is momentarily empty instead of discarding the chunk. Still bounded —
        // on a dead link the budget expires and we drop, so we never grow the
        // heap and never wedge the program (NFR-PERF-3).
        //
        // The GIL is released across the wait: we are on the run worker, and the
        // whole point is to throttle THIS program while the REPL, the fs-worker
        // and the NimBLE host task keep running (same discipline as pble_fs.c).
        // g_stage stays safe — the on_worker() gate above means the worker is
        // the only task that ever fills or emits it.
        MP_THREAD_GIL_EXIT();
        (void)pble_proto_emit_paced(PBLE_OP_CONSOLE_DATA, g_stage, 1 + n,
                                    PBLE_CONSOLE_TX_BUDGET_MS);
        MP_THREAD_GIL_ENTER();
        off += n;
    }
}

// mp_print_t backend: the worker's traceback printer routes here, tagged stderr.
static void console_stderr_strn(void *data, const char *str, size_t len) {
    (void)data;
    pble_console_out(PBLE_STREAM_STDERR, str, len);
}
const mp_print_t pble_console_stderr_print = { NULL, console_stderr_strn };

// ============================================================================
// stdin ring: CONSOLE_INPUT (0x31) -> ring -> worker getchar
// ============================================================================
// 0x31 host task: append bytes, dropping any overflow (bounded — never grows the
// heap, never blocks the host task). Fire-and-forget: no RSP frame.
uint8_t pble_console_input(const pble_frame_t *req, uint8_t *rsp, size_t *rlen, uint16_t conn) {
    (void)rsp;
    (void)conn;
    if (rlen) {
        *rlen = 0;
    }
    if (req != NULL && req->payload != NULL && req->len > 0) {
        taskENTER_CRITICAL(&g_ring_mux);
        for (uint16_t i = 0; i < req->len; i++) {
            if (g_ring_count >= PBLE_STDIN_RING) {
                break;   // full: drop the overflow tail (bounded)
            }
            g_ring[g_ring_head] = req->payload[i];
            g_ring_head = (uint16_t)((g_ring_head + 1) % PBLE_STDIN_RING);
            g_ring_count++;
        }
        taskEXIT_CRITICAL(&g_ring_mux);
    }
    return PBLE_NO_RSP;   // dispatch suppresses the reply (fire-and-forget)
}

// Worker stdin drain for input()/sys.stdin: next byte, or -1 when empty.
int pble_console_stdin_getchar(void) {
    int c = -1;
    taskENTER_CRITICAL(&g_ring_mux);
    if (g_ring_count > 0) {
        c = g_ring[g_ring_tail];
        g_ring_tail = (uint16_t)((g_ring_tail + 1) % PBLE_STDIN_RING);
        g_ring_count--;
    }
    taskEXIT_CRITICAL(&g_ring_mux);
    return c;
}

// ============================================================================
// Native os.dupterm tee stream (write-only stdout tee)
// ============================================================================
// esp32 os.dupterm requires a NATIVE stream (C stream protocol), not a Python
// class. This write-only stream forwards every stdout byte to pble_console_out
// (which self-gates to the worker), so the worker's print() tees to BLE while the
// primary UART/USB output is untouched. read() never yields, so the dupterm never
// feeds the REPL (worker stdin is a separate path via the CONSOLE_INPUT ring).
typedef struct _pble_tee_obj_t {
    mp_obj_base_t base;
} pble_tee_obj_t;

static mp_uint_t tee_write(mp_obj_t self_in, const void *buf, mp_uint_t size, int *errcode) {
    (void)self_in;
    (void)errcode;
    pble_console_out(PBLE_STREAM_STDOUT, (const char *)buf, size);
    return size;   // consumed (the primary console path already emitted to UART)
}
static mp_uint_t tee_read(mp_obj_t self_in, void *buf, mp_uint_t size, int *errcode) {
    (void)self_in;
    (void)buf;
    (void)size;
    *errcode = MP_EAGAIN;      // never feeds REPL input from this slot
    return MP_STREAM_ERROR;
}
static mp_uint_t tee_ioctl(mp_obj_t self_in, mp_uint_t request, uintptr_t arg, int *errcode) {
    (void)self_in;
    if (request == MP_STREAM_POLL) {
        return arg & MP_STREAM_POLL_WR;   // writable only, never readable
    }
    *errcode = MP_EINVAL;
    return MP_STREAM_ERROR;
}
static const mp_stream_p_t tee_stream_p = {
    .read = tee_read,
    .write = tee_write,
    .ioctl = tee_ioctl,
};
static MP_DEFINE_CONST_OBJ_TYPE(pble_tee_type, MP_QSTR_ConsoleTee, MP_TYPE_FLAG_NONE,
                                protocol, &tee_stream_p);
static const pble_tee_obj_t pble_tee_obj = { { &pble_tee_type } };

// ============================================================================
// Registration + thin MicroPython surface (boot wiring + HIL)
// ============================================================================
void pble_console_register(void) {
    pble_proto_register(PBLE_OP_CONSOLE_INPUT, pble_console_input);
}

static mp_obj_t mod_pble_console_register(void) {
    pble_console_register();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_pble_console_register_obj, mod_pble_console_register);

// HIL helper: drain one stdin byte (or -1). Lets the board-overlay stdin HAL hook
// or a bring-up script pull the ring without a native call.
static mp_obj_t mod_pble_console_stdin_getchar(void) {
    return mp_obj_new_int(pble_console_stdin_getchar());
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_pble_console_stdin_getchar_obj, mod_pble_console_stdin_getchar);

// out(tag, buf) — the stdout tee entry for the os.dupterm stream installed in
// _boot.py. Runs on whichever task printed; pble_console_out() self-gates to the
// worker, so REPL/main output is a no-op here and never reaches BLE (FR-CON-4).
static mp_obj_t mod_pble_console_out(mp_obj_t tag_in, mp_obj_t buf_in) {
    mp_buffer_info_t b;
    mp_get_buffer_raise(buf_in, &b, MP_BUFFER_READ);
    pble_console_out((uint8_t)mp_obj_get_int(tag_in), (const char *)b.buf, b.len);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(mod_pble_console_out_obj, mod_pble_console_out);

// stream() — the native tee stream instance for `os.dupterm(pble_console.stream())`.
static mp_obj_t mod_pble_console_stream(void) {
    return MP_OBJ_FROM_PTR(&pble_tee_obj);
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_pble_console_stream_obj, mod_pble_console_stream);

static const mp_rom_map_elem_t pble_console_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_pble_console) },
    { MP_ROM_QSTR(MP_QSTR_STDOUT), MP_ROM_INT(PBLE_STREAM_STDOUT) },
    { MP_ROM_QSTR(MP_QSTR_STDERR), MP_ROM_INT(PBLE_STREAM_STDERR) },
    { MP_ROM_QSTR(MP_QSTR_register), MP_ROM_PTR(&mod_pble_console_register_obj) },
    { MP_ROM_QSTR(MP_QSTR_stdin_getchar), MP_ROM_PTR(&mod_pble_console_stdin_getchar_obj) },
    { MP_ROM_QSTR(MP_QSTR_out), MP_ROM_PTR(&mod_pble_console_out_obj) },
    { MP_ROM_QSTR(MP_QSTR_stream), MP_ROM_PTR(&mod_pble_console_stream_obj) },
};
static MP_DEFINE_CONST_DICT(pble_console_globals, pble_console_globals_table);

const mp_obj_module_t pble_console_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&pble_console_globals,
};

MP_REGISTER_MODULE(MP_QSTR_pble_console, pble_console_user_cmodule);
