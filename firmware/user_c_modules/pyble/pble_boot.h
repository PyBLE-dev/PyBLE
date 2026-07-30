// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_boot — cold-boot safety + opt-in /main.py auto-run (F-12), a native
// MicroPython USER_C_MODULE (ADR-0006). Clean-room vs protocol.md §4 (0x23
// SET_AUTORUN, FROZEN G1 · OI-5 CLOSED) + §7 (the auto_run cap) + specs.md §4.7
// (FR-BOOT-1..6, FR-MODE-1/4, NFR-SAFE-3).
//
// COLD-BOOT POSTURE (SEC-6 / FR-BOOT-1/2): the board advertises-and-waits on every
// power-up and NEVER runs /main.py by default — auto-run is strictly OPT-IN, persisted
// in NVS, and surfaced as the auto_run capability so an unowned board is inert. When
// opted in, /main.py is handed to the runner WORKER (never executed inline), so even a
// broken or infinite-loop /main.py leaves the link + STOP + control plane serviceable
// (FR-BOOT-4/6, NFR-SAFE-2/3). The auto-run FLAG (behaviour + persisted state) is owned
// here; the auto_run CAP wire name/encoding is protocol.md's and its serialization is
// identity's (pble_info reads pble_boot_autorun_enabled()).
#ifndef PBLE_BOOT_H
#define PBLE_BOOT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "pble_proto.h"   // pble_frame_t, status codes

#ifdef __cplusplus
extern "C" {
#endif

// The persisted opt-in auto-run flag (NVS "pyble"/"autorun", default 0 = off).
// Read by pble_info to serialize the auto_run capability (FR-BOOT-3). Cheap enough
// to call at boot; no caching required.
bool    pble_boot_autorun_enabled(void);

// Persist the auto-run flag. PBLE_OK on success; PBLE_EIO if NVS write fails.
uint8_t pble_boot_set_autorun(bool enable);

// 0x23 SET_AUTORUN dispatch handler (registered into pble_proto). Payload
// [enable:u8] (0=off, non-zero=on) -> persist -> RSP{status}. Short payload -> EBADREQ.
uint8_t pble_boot_set_autorun_cmd(const pble_frame_t *req, uint8_t *rsp,
                                  size_t *rsp_len, uint16_t conn);

// If auto-run is enabled AND /main.py exists at fs_root, hand it to the runner as
// RUN{mode=file, path="/main.py"} on the WORKER — NON-BLOCKING, fail-safe, self-guarded,
// and a NO-OP when disabled or when /main.py is absent (so a bare board stays at
// RUN_STATE idle, no spurious error). MUST be called from a valid MP thread AFTER the
// runner worker is up (the pble_boot MP wrapper, invoked from _boot.py). It never runs
// user code inline (FR-BOOT-3/4/6, FR-MODE-1, NFR-SAFE-2/3).
void    pble_boot_maybe_autorun(void);

// Register 0x23 SET_AUTORUN into pble_proto. Idempotent; call once at boot from
// init_agent().
void    pble_boot_register(void);

#ifdef __cplusplus
}
#endif

#endif  // PBLE_BOOT_H
