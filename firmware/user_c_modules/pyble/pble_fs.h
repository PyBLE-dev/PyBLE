// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_fs — the PBLE/1 filesystem bridge + workspace jail (F-08/F-09/F-17), a
// native MicroPython USER_C_MODULE (ADR-0006: native C from day one). Clean-room
// vs protocol.md §5 (FROZEN, G1 · 2026-07-01) + specs.md §4.4 (FR-FS-1..16).
//
// EXECUTION MODEL (mirrors the S4 runner worker): MicroPython's VFS at fs_root is
// reachable ONLY via mp_vfs_* / the MP object+nlr machinery, which REQUIRE a valid
// MicroPython VM thread state + the GIL. But pble_proto_dispatch + every CMD
// handler run on the NON-MP NimBLE host task. Therefore the FILE_* host handlers
// NEVER call mp_vfs_* inline — they validate + copy the request into a bounded
// FreeRTOS mailbox and return PBLE_NO_RSP; a dedicated MP fs-worker _thread (valid
// VM state, launched from _boot.py) dequeues, resolves the jail, performs the vfs
// op under an nlr boundary, maps the caught OSError → §8 status, and replies
// asynchronously by request id via pble_proto_emit_id. The host task NEVER blocks
// on the fs-worker (FR-BLE-11).
#ifndef PBLE_FS_H
#define PBLE_FS_H

#include <stddef.h>
#include <stdint.h>

#include "pble_proto.h"

#ifdef __cplusplus
extern "C" {
#endif

// THE single source of truth for the reference-agent PUT sliding-window W
// (FR-FS-4 / NFR-PERF-2, frozen 2026-07-04: W 4->8, no wire change — W is not a
// §5 wire field, it lives only in HELLO caps `window=`, §7). The receiver mailbox
// depth is derived as W + 2 (see PBLE_FS_QDEPTH in pble_fs.c) so a full window of
// unacknowledged PUT_DATA (plus control) is buffered without a queue-full drop.
// The pble_info caps `window=` literal MUST match this value.
#define PBLE_FS_PUT_WINDOW  8u

// Register the FILE_* opcodes (0x10..0x1A) into pble_proto and create the mailbox
// queue. Called from init_agent() BEFORE the fs-worker launches. Idempotent.
void pble_fs_register(void);

// The MP fs-worker _thread entry (launched from _boot.py via
// `_thread.start_new_thread(pble_fs.worker, ())`). Loops forever: dequeue →
// pble_fs_resolve → mp_vfs_* under nlr → errno→status → async RSP/EVT by id.
// Never returns.
void pble_fs_worker(void);

// THE single path-jail chokepoint (F-17 / SEC-4). Canonicalizes `in` (inlen bytes,
// may be non-NUL-terminated) against fs_root and enforces the frozen forbidden set:
//   - NULL / empty            → PBLE_EBADREQ
//   - embedded NUL            → PBLE_EBADREQ
//   - overlong (> 128 bytes)  → PBLE_ERANGE  (or no room in `out`)
//   - `..` traversal / absolute escape that resolves outside fs_root → PBLE_EACCES
//   - the reserved `.pbltmp` transfer-scratch suffix on any component → PBLE_EACCES
//   - a reserved agent-module prefix on the top-level component       → PBLE_EACCES
// On OK it writes a NUL-terminated absolute vfs path into `out` and returns
// PBLE_OK. EVERY vfs op routes through this first — there is no second path into
// the vfs from the bridge (the jail is unbypassable, SEC-4).
uint8_t pble_fs_resolve(const char *in, size_t inlen, char *out, size_t outcap);

// Map a MicroPython OSError errno → the §8 1-byte status (FR-FS-15).
uint8_t pble_fs_errno_to_status(int mp_errno);

// Upload resume-on-reconnect (F-10 / FR-FS-7 / protocol.md §5 "Resume on
// reconnect", FROZEN). WORKER-ONLY: touches mp_vfs_* (stat + read), so it MUST
// run on the MP fs-worker under a valid VM thread state + the GIL — it is called
// from FILE_PUT_BEGIN handling on the worker, never from the host task.
//
// For a resolved jailed `dest_vfs_path` whose sibling `<dest>.pbltmp` already
// holds a partial prefix the board itself wrote:
//   - no temp / unreadable / zero-length / a dir  → returns 0 (fresh upload);
//   - `temp_len > total_size`                      → returns 0 (the caller's "wb"
//     open then truncates the stale temp to 0 — the frozen over-size guard);
//   - otherwise → re-CRCs `temp[0,len)` to RE-SEED the running whole-file CRC and
//     sets the watermark to `len`, returning `len` as the resume_offset.
// In every case it (re)initializes the worker-local running whole-file CRC +
// watermark, so FILE_PUT_BEGIN can rely on them afterwards. The whole-file CRC at
// FILE_PUT_END stays the ONLY correctness gate — a bad/foreign prefix simply
// fails CRC (ECRC) and the old file is kept byte-for-byte (FR-FS-14).
uint32_t pble_fs_resume_prefix(const char *dest_vfs_path, uint32_t total_size);

// Link-drop hook (F-10 / protocol.md §5). Clears the in-RAM single-active-transfer
// state (flags/counters/paths) WITHOUT deleting `<dest>.pbltmp` — the temp + its
// on-flash length (the durable watermark a resuming reconnect re-derives) persist.
// HOST-TASK SAFE: touches ONLY plain C module state, never mp_vfs_* / MP objects,
// so it is safe to call directly from the NimBLE disconnect callback. Idempotent.
// Any file object left open by the interrupted transfer is flushed + closed later,
// on the worker, by the next FILE_PUT_BEGIN (never from this host-task hook).
void pble_fs_on_disconnect(void);

// Host-task dispatch handlers (registered into pble_proto). Each validates the
// frame length, copies the payload into the mailbox, and enqueues non-blocking:
// enqueue OK → PBLE_NO_RSP (the worker replies async by id); enqueue FULL → EBUSY,
// EXCEPT pble_fs_put_data which returns PBLE_NO_RSP on drop (the app retransmits
// from the last ACK).
uint8_t pble_fs_list(const pble_frame_t *req, uint8_t *rsp, size_t *rlen, uint16_t conn);
uint8_t pble_fs_stat(const pble_frame_t *req, uint8_t *rsp, size_t *rlen, uint16_t conn);
uint8_t pble_fs_get_begin(const pble_frame_t *req, uint8_t *rsp, size_t *rlen, uint16_t conn);
uint8_t pble_fs_put_begin(const pble_frame_t *req, uint8_t *rsp, size_t *rlen, uint16_t conn);
uint8_t pble_fs_put_data(const pble_frame_t *req, uint8_t *rsp, size_t *rlen, uint16_t conn);
uint8_t pble_fs_put_end(const pble_frame_t *req, uint8_t *rsp, size_t *rlen, uint16_t conn);
uint8_t pble_fs_delete(const pble_frame_t *req, uint8_t *rsp, size_t *rlen, uint16_t conn);
uint8_t pble_fs_mkdir(const pble_frame_t *req, uint8_t *rsp, size_t *rlen, uint16_t conn);
uint8_t pble_fs_rename(const pble_frame_t *req, uint8_t *rsp, size_t *rlen, uint16_t conn);

#ifdef __cplusplus
}
#endif

#endif  // PBLE_FS_H
