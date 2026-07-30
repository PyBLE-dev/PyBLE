// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_console — the PyBLE console tee + stdin bridge for a run (F-07):
//   - tee the WORKER's stdout/stderr into CONSOLE_DATA (0x30) events, thread-gated
//     so the main-task REPL / UART output is NEVER teed (observe-anywhere);
//   - feed CONSOLE_INPUT (0x31) bytes into a bounded ring the WORKER's
//     input()/sys.stdin drains (FR-CON-1..5, FR-RUN-9, NFR-PERF-3).
//
// Interposition uses the upstream-supported `os.dupterm` extension point
// (MICROPY_PY_OS_DUPTERM on esp32): a native stream this module installs mirrors
// stdout->tee and serves stdin from the ring, both thread-gated to the worker.
// Upstream is never edited (CON-1). The USB/UART path stays as a debug mirror
// only, never a runtime transport (FR-CON-5).
//
// Clean-room: authored fresh against protocol.md + the public MicroPython/ESP-IDF
// API. No proprietary source is referenced.
#ifndef PBLE_CONSOLE_H
#define PBLE_CONSOLE_H

#include <stddef.h>
#include <stdint.h>

#include "py/mpprint.h"   // mp_print_t (worker stderr traceback printer)

#include "pble_proto.h"   // pble_frame_t, pble_handler_t

#ifdef __cplusplus
extern "C" {
#endif

// CONSOLE_DATA stream tag (protocol.md §6 CONSOLE_DATA payload = [stream][bytes]).
enum {
    PBLE_STREAM_STDOUT = 0,
    PBLE_STREAM_STDERR = 1,
};

// The WORKER announces its VM thread state so the tee/stdin gate on run origin.
// Called once from pble_runner_worker() at entry (worker thread, GIL held).
void pble_console_set_worker(void *mp_state_thread);

// SINGLE emit chokepoint: tag + bytes -> CONSOLE_DATA (0x30) via pble_proto_emit.
// No-op unless called on the worker thread (main/REPL output is never teed). Bytes
// are chunked to fit the event budget; bounded (no unbounded heap growth).
void pble_console_out(uint8_t stream_tag, const char *buf, size_t len);

// mp_print_t whose backend is pble_console_out(STDERR, ...). The worker prints an
// uncaught-exception traceback through this so it is tagged stderr (FR-CON-2)
// without routing through the platform printer (which would mis-tag it stdout).
extern const mp_print_t pble_console_stderr_print;

// 0x31 CONSOLE_INPUT handler (NimBLE host task): append payload to the bounded
// stdin ring; fire-and-forget — returns PBLE_NO_RSP so dispatch emits no frame.
uint8_t pble_console_input(const pble_frame_t *req, uint8_t *rsp, size_t *rlen, uint16_t conn);

// Worker stdin drain for input()/sys.stdin: next byte, or -1 when empty.
int  pble_console_stdin_getchar(void);

// Register 0x31 and install the dupterm tee/stdin stream. Idempotent; call once
// at boot from init_agent() (main task, valid VM state).
void pble_console_register(void);

#ifdef __cplusplus
}
#endif

#endif  // PBLE_CONSOLE_H
