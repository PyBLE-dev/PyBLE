// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_lock — the PyBLE single-active-writer token (F-18 / SEC-3). Centralizes
// the two INDEPENDENT writer classes that mutate board state — a running program
// (W_RUN) and a file transfer (W_XFER) — over the runner's single-program EBUSY
// and the fs single-active-transfer seams (protocol.md §10 FROZEN, specs.md §9).
//
// RULING (protocol.md §10 / s6_pending.json single_active_writer_*): exactly one
// active writer PER CLASS. A second acquire of the SAME class by ANOTHER writer is
// refused EBUSY (0x07); a re-acquire by the SAME writer is idempotent OK. W_RUN and
// W_XFER are INDEPENDENT — a run and an upload may coexist because the workspace
// jail + atomic temp-rename keep the bridge non-corrupting (FR-FS-16). READ ops
// (LIST/STAT/GET) are non-writers and never take the token, so they are not starved.
//
// The token releases on op completion AND on disconnect: a dropped upload frees
// W_XFER so a resuming reconnect can re-open the transfer (this couples F-18 to the
// F-10 resume path). A genuinely-running program PERSISTS across a disconnect — the
// runner's run-state machine keeps gating a concurrent RUN with EBUSY (SEC-3).
//
// Clean-room: authored fresh against protocol.md §10 + the public FreeRTOS API.
#ifndef PBLE_LOCK_H
#define PBLE_LOCK_H

#include <stdint.h>

#include "pble_proto.h"   // PBLE_OK / PBLE_EBUSY / PBLE_EBADREQ status codes

#ifdef __cplusplus
extern "C" {
#endif

// The two independent writer classes (SEC-3). PBLE_W_NONE is the sentinel/free
// value; it is never acquired.
typedef enum {
    PBLE_W_NONE = 0,
    PBLE_W_RUN  = 1,   // a running user program (runner)
    PBLE_W_XFER = 2,   // an active file transfer (fs bridge)
} pble_writer_t;

// Acquire the writer token for class `who` on connection `conn`.
//   free            -> take it, return PBLE_OK
//   held by `conn`  -> idempotent re-acquire, return PBLE_OK
//   held by another -> return PBLE_EBUSY (that class is busy, FR-RUN-4 / §5)
//   invalid `who`   -> PBLE_EBADREQ
// W_RUN and W_XFER are independent: acquiring one never blocks the other.
uint8_t pble_lock_acquire(pble_writer_t who, uint16_t conn);

// Release the writer token for class `who` (op completion). No-op if not held.
void    pble_lock_release(pble_writer_t who);

// Link-drop handler: free W_XFER (a dropped upload must not wedge the resume path,
// coupling to F-10) and reset the fs in-RAM transfer state via pble_fs_on_disconnect
// (owned by storage-engineer; weak-referenced so pble_lock links standalone). W_RUN
// is intentionally NOT freed — a running program persists across a disconnect and
// the runner's run-state keeps gating a concurrent RUN (SEC-3, FR-FS-16).
void    pble_lock_on_disconnect(uint16_t conn);

// Initialise the token (both classes free). Idempotent; call once at boot from
// init_agent().
void    pble_lock_register(void);

#ifdef __cplusplus
}
#endif

#endif  // PBLE_LOCK_H
