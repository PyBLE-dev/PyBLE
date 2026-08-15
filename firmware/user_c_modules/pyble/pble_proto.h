// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_proto.h — the frozen PBLE/1 protocol-engine contract (ADR-0006 native C).
// Shared types + constants + the decode/dispatch/emit surface the agent modules
// (pble_info, pble_device_config, pble_runner) register into. Mirrors protocol.md
// §3.1/§3.2/§4/§8/§9 — never redefines the wire.
#ifndef PBLE_PROTO_H
#define PBLE_PROTO_H

#include <stddef.h>
#include <stdbool.h>
#include <stdint.h>

#include "pble_termination.h"

#ifdef __cplusplus
extern "C" {
#endif

// --- Frozen constants --------------------------------------------------------
#define PBLE_PROTO_VERSION 0x01   // §9: the single supported wire version (F-16)
#define PBLE_LABEL_MAX     24     // §7/OI-6: max label bytes (UTF-8), else ERANGE

// Frame TYPE (§3.1)
#define PBLE_TYPE_CMD 0x01
#define PBLE_TYPE_RSP 0x02
#define PBLE_TYPE_EVT 0x03

// Opcodes (§4) — numbers FROZEN at G1 (2026-07-01, closes OI-4); payload
// encodings for the identify opcodes remain OI-6, frozen at S4 (F-23).
#define PBLE_OP_HELLO            0x01
#define PBLE_OP_DEVICE_INFO      0x02
// §4 filesystem opcodes (numbers FROZEN at G1; §5 payload wire is DRAFT — the
// fs-worker in pble_fs owns those payload bytes, this table only names+routes them).
#define PBLE_OP_FILE_LIST        0x10   // CMD/RSP: list a directory
#define PBLE_OP_FILE_STAT        0x11   // CMD/RSP: size + crc of one path
#define PBLE_OP_FILE_GET_BEGIN   0x12   // CMD/RSP: start a download
#define PBLE_OP_FILE_GET_DATA    0x13   // EVT: download chunk (offset + bytes)
#define PBLE_OP_FILE_GET_END     0x14   // EVT: download complete (crc)
#define PBLE_OP_FILE_PUT_BEGIN   0x15   // CMD/RSP: start an upload
#define PBLE_OP_FILE_PUT_DATA    0x16   // CMD (no RSP): upload chunk; acked by window
#define PBLE_OP_FILE_PUT_END     0x17   // CMD/RSP: finish upload; board verifies crc
#define PBLE_OP_FILE_DELETE      0x18   // CMD/RSP: delete a file
#define PBLE_OP_MKDIR            0x19   // CMD/RSP: create a directory
#define PBLE_OP_FILE_RENAME      0x1A   // CMD/RSP: rename/move
#define PBLE_OP_RUN              0x20
#define PBLE_OP_STOP             0x21
#define PBLE_OP_SOFT_REBOOT      0x22
#define PBLE_OP_SET_AUTORUN      0x23   // S6 F-12: opt-in /main.py auto-run (additive, §9)
#define PBLE_OP_CONSOLE_DATA     0x30   // EVT: stdout/stderr bytes
#define PBLE_OP_CONSOLE_INPUT    0x31   // CMD, fire-and-forget (no RSP)
#define PBLE_OP_RUN_STATE        0x40   // EVT: idle/running/done/error
#define PBLE_OP_FILE_PUT_ACK     0x41   // EVT: cumulative-offset upload ack (§5)
#define PBLE_OP_SET_LABEL        0x50
#define PBLE_OP_SET_IDENTIFY_LED 0x51
#define PBLE_OP_IDENTIFY         0x52

// Status / error codes (§8, 1-byte `status`).
#define PBLE_OK           0x00
#define PBLE_EBADREQ      0x01
#define PBLE_ENOENT       0x02
#define PBLE_EACCES       0x03
#define PBLE_ENOSPC       0x04
#define PBLE_EIO          0x05
#define PBLE_ENOMEM       0x06
#define PBLE_EBUSY        0x07
#define PBLE_ECRC         0x08
#define PBLE_ERANGE       0x09
#define PBLE_EUNSUPPORTED 0x0A
#define PBLE_EINTERNAL    0xFF

// Internal-only dispatch sentinel (NOT a §8 wire status): a handler returns
// PBLE_NO_RSP to suppress the RSP frame entirely — CONSOLE_INPUT (0x31) is
// fire-and-forget. Never encoded onto the wire.
#define PBLE_NO_RSP       0xFE

// Max bytes a handler may write after the status byte (caps/DEVICE_INFO fit).
#define PBLE_RSP_MAX 480

// ESP reference-agent bounded generic-response delivery (§3.2 / FR-PROTO-6).
#define PBLE_RSP_POOL_DEPTH       2u
#define PBLE_RSP_FRAME_MAX        491u
#define PBLE_RSP_TX_BUDGET_MS     1000u
#define PBLE_RSP_RETRY_SLICE_MS   15u

// Framing overhead between one FILE data chunk and the single §3.2 notify
// packet that carries it: §3.1 header (6) + [offset:u32] (4) + CRC32 (4) +
// FRAG_HDR (1) + ATT notify header (3). caps `chunk_size` = mtu − THIS, so a
// GET_DATA / PUT_DATA message is EXACTLY ONE BLE packet — the frozen invariant
// pble_ble.h's retry contract depends on (a multi-packet stream message is not
// cleanly retriable after a mid-run PBLE_TX_AGAIN).
#define PBLE_CHUNK_OVERHEAD 18

// A decoded §3.1 message (payload points into the caller's buffer).
typedef struct {
    uint8_t ver, type, opcode, id;
    const uint8_t *payload;
    uint16_t len;
} pble_frame_t;

// A reservation is valid only for this exact static-slot incarnation and BLE
// session. Numeric connection handles alone are deliberately insufficient: a
// controller may reuse one after disconnect.
typedef struct {
    uint8_t slot;
    uint32_t incarnation;
    pble_session_token_t session;
    uint64_t vm_epoch;
} pble_rsp_ticket_t;

// Uniform handler ABI: return a §8 status; write up to PBLE_RSP_MAX extra RSP
// bytes (after the status byte) into rsp_payload / *rsp_len.
typedef uint8_t (*pble_handler_t)(const pble_frame_t *req, uint8_t *rsp_payload,
                                  size_t *rsp_len,
                                  const pble_session_token_t *session);

typedef uint8_t (*pble_deferred_handler_t)(const pble_frame_t *req,
                                           uint8_t *rsp_payload,
                                           size_t *rsp_len,
                                           const pble_session_token_t *session,
                                           const pble_rsp_ticket_t *ticket);

// Immutable response view consumed by the NimBLE-host one-fragment callout.
typedef struct {
    pble_rsp_ticket_t ticket;
    const uint8_t *frame;
    uint16_t frame_len;
    uint16_t offset;
    uint8_t index;
    uint32_t stream_generation;
    uint32_t deadline;
} pble_rsp_tx_t;

// --- Codec + dispatch (pble_proto.c) ----------------------------------------
uint32_t pble_proto_crc32(const uint8_t *data, size_t len);
// Build a §3.1 frame + CRC into out; returns total length or <0 on overflow.
int  pble_proto_encode(uint8_t type_, uint8_t opcode, uint8_t id_,
                       const uint8_t *payload, size_t plen, uint8_t *out, size_t cap);
// Structural + VER decode (does NOT check CRC). 0 ok; -1 malformed; -3 bad VER.
int  pble_proto_decode(const uint8_t *msg, size_t len, pble_frame_t *out);
// Bind a handler to an opcode (build the dispatch table at boot).
void pble_proto_register(uint8_t opcode, pble_handler_t h);
void pble_proto_register_deferred(uint8_t opcode, pble_deferred_handler_t h);
void pble_proto_register_no_response(uint8_t opcode, pble_handler_t h);
void pble_proto_register_special(uint8_t opcode, pble_handler_t h);
void pble_proto_init(void);
// Decode → §9 VER guard → CRC gate → route → RSP (via pble_ble_notify).
void pble_proto_dispatch(const uint8_t *msg, size_t len, uint16_t conn);
// Bounded status-only refusal for an RX run that exceeded reassembly capacity.
void pble_proto_refuse(uint8_t opcode, uint8_t id_, uint8_t status,
                       const pble_session_token_t *session);
// Emit an event frame (TYPE=EVT, ID=0) — e.g. RUN_STATE. Returns pble_ble_notify rc.
int pble_proto_emit(uint8_t opcode, const uint8_t *payload, size_t len,
                    const pble_session_token_t *session);

// Paced event emit for STREAMING callers only (fs-worker / MP runner — never
// the NimBLE host task): congestion blocks on the NOTIFY_TX drain event up to
// budget_ms, retrying the SAME packet (see pble_ble_notify_paced).
int  pble_proto_emit_paced(uint8_t opcode, const uint8_t *payload, size_t len,
                           uint32_t budget_ms,
                           const pble_session_token_t *session);
int pble_proto_emit_paced_for_session(
    uint8_t opcode, const uint8_t *payload, size_t len, uint32_t budget_ms,
    const pble_session_token_t *session);
// Paced one-fragment CONTROL event. Unlike bulk paced traffic, this may consume
// the exact msys_1 capacity that bulk submission preserves for control liveness.
int  pble_proto_emit_control_paced(uint8_t opcode, const uint8_t *payload,
                                   size_t len, uint32_t budget_ms,
                                   const pble_session_token_t *session);
// Emit a caller-supplied non-RSP frame from a worker context. Generic RSPs are
// deliberately refused here because they require a pre-reserved pool ticket;
// events remain worker-safe and are serialized by pble_ble.
int  pble_proto_emit_id(uint8_t type_, uint8_t opcode, uint8_t id_,
                        const uint8_t *payload, size_t len,
                        const pble_session_token_t *session);

// Encode one matching status-only RSP in call-local storage and submit it
// through the connection-bound specialized transport seam: one absolute 15 ms
// wait only for the current complete-message TX boundary, then exactly one
// local Notify submission without any capacity wait or retry.
int  pble_proto_emit_rsp_status_try(uint8_t opcode, uint8_t id_, uint8_t status,
                                    const pble_session_token_t *expected_conn);

// Static response-pool/ticket surface shared with the deferred FS worker and
// the BLE-owned host callout. These are internal native-agent APIs, not wire.
bool pble_rsp_reserve(const pble_session_token_t *session,
                      pble_rsp_ticket_t *ticket);
bool pble_rsp_ticket_valid(const pble_rsp_ticket_t *ticket);
bool pble_rsp_session_valid(const pble_rsp_ticket_t *ticket);
bool pble_rsp_publish(const pble_rsp_ticket_t *ticket, uint8_t opcode,
                      uint8_t id_, const uint8_t *payload, size_t len);
void pble_rsp_release(const pble_rsp_ticket_t *ticket);
bool pble_rsp_expect_completion(const pble_rsp_ticket_t *ticket);
bool pble_rsp_wait(const pble_rsp_ticket_t *ticket);
void pble_rsp_cancel_session(const pble_session_token_t *session);
void pble_rsp_cancel_ticket(const pble_rsp_ticket_t *ticket);
bool pble_rsp_tx_peek(pble_rsp_tx_t *tx);
void pble_rsp_tx_result(const pble_rsp_tx_t *tx, uint32_t stream_generation,
                        uint16_t offset, uint8_t index, uint16_t accepted,
                        int tx_result);
bool pble_rsp_has_pending(void);
bool pble_rsp_tx_owned(void);
bool pble_rsp_release_owner_if_idle(void);
void pble_proto_vm_reset(void);

#ifdef __cplusplus
}
#endif

#endif  // PBLE_PROTO_H
