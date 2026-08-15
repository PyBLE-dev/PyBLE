// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_lock — the single-active-writer token (F-18 / SEC-3). See pble_lock.h.
//
// DESIGN (lean, non-starving): two INDEPENDENT slots (W_RUN, W_XFER), each a
// {held, owner-conn} pair guarded by a portMUX critical section that brackets ONLY
// the tiny test/transition — so STOP and read-only commands (which never take the
// token) are never starved (SEC-3). The critical section runs on the NimBLE host
// task (the fs/runner handlers and the GAP disconnect callback), so it is a
// spinlock-guarded state test, never a blocking wait.
//
// Clean-room: authored fresh against protocol.md §10 + the public FreeRTOS API.
#include <stdbool.h>
#include <stdint.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "pble_lock.h"

// pble_fs_on_disconnect is owned by storage-engineer (pble_fs.c, F-10 resume).
// Weak reference: until that strong definition ships, the symbol resolves to NULL
// and we skip the call — pble_lock links standalone (fail-safe cross-boundary
// hand-off, never wedge the build). The strong def, once present, binds here.
extern void pble_fs_on_disconnect(void) __attribute__((weak));

// --- Module state ------------------------------------------------------------
typedef struct {
    bool     held;
    uint16_t conn;   // owning connection when held (idempotent re-acquire key)
} lock_slot_t;

static lock_slot_t g_run_slot;    // W_RUN
static lock_slot_t g_xfer_slot;   // W_XFER
static portMUX_TYPE g_lock_mux = portMUX_INITIALIZER_UNLOCKED;

// Select the slot for a writer class, or NULL for an invalid class.
static lock_slot_t *lock_slot_for(pble_writer_t who) {
    switch (who) {
        case PBLE_W_RUN:  return &g_run_slot;
        case PBLE_W_XFER: return &g_xfer_slot;
        default:          return NULL;   // PBLE_W_NONE or out of range
    }
}

uint8_t pble_lock_acquire(pble_writer_t who, uint16_t conn) {
    lock_slot_t *s = lock_slot_for(who);
    if (s == NULL) {
        return PBLE_EBADREQ;
    }
    uint8_t st;
    taskENTER_CRITICAL(&g_lock_mux);
    if (!s->held) {
        s->held = true;
        s->conn = conn;
        st = PBLE_OK;             // free -> taken
    } else if (s->conn == conn) {
        st = PBLE_OK;             // same writer -> idempotent
    } else {
        st = PBLE_EBUSY;          // that class held by another writer (SEC-3)
    }
    taskEXIT_CRITICAL(&g_lock_mux);
    return st;
}

void pble_lock_release(pble_writer_t who) {
    lock_slot_t *s = lock_slot_for(who);
    if (s == NULL) {
        return;
    }
    taskENTER_CRITICAL(&g_lock_mux);
    s->held = false;
    s->conn = 0;
    taskEXIT_CRITICAL(&g_lock_mux);
}

void pble_lock_on_disconnect(uint16_t conn) {
    // Free the transfer writer so a resuming reconnect can re-open the upload
    // (couples F-18 to the F-10 resume path). Under the v1 single-central model
    // this is unconditional; W_RUN is deliberately left held (a running program
    // persists across a disconnect, SEC-3 / FR-FS-16).
    pble_lock_release(PBLE_W_XFER);
    // Reset the fs in-RAM transfer state (the jailed temp + watermark persist on
    // flash for resume). Owned by storage-engineer; weak-referenced (see above).
    if (pble_fs_on_disconnect) {
        pble_fs_on_disconnect();
    }
    (void)conn;
}

void pble_lock_register(void) {
    taskENTER_CRITICAL(&g_lock_mux);
    g_run_slot.held = false;
    g_run_slot.conn = 0;
    g_xfer_slot.held = false;
    g_xfer_slot.conn = 0;
    taskEXIT_CRITICAL(&g_lock_mux);
}
