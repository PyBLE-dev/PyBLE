// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_proto — the PBLE/1 protocol engine as a native MicroPython USER_C_MODULE.
//
// The native-C agent base (ADR-0006: native C from day one). Authored CLEAN-ROOM
// against protocol.md §3.1/§3.2/§4/§8/§9 — it mirrors the wire, never redefines
// it, and is BYTE-IDENTICAL to firmware/pyble/pyble_proto.py so both share one
// PBLE/1 conformance corpus. No proprietary source is referenced (clean-room).
//
// Surface: crc32 + encode (F-02) + decode / opcode-dispatch table / §9 VER guard
// (F-16) / emit. The `pble_proto` MicroPython module exposes crc32/encode for the
// host corpus; the agent path is the native pble_proto_* functions.
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "py/runtime.h"
#include "py/obj.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

#include "pble_proto.h"
#include "pble_ble.h"   // general TX + specialized transactional response try
#include "pble_vm_lifecycle.h"

// --- IEEE CRC-32 (protocol.md §3.1 / FR-PROTO-3) ----------------------------
// Reflected, poly 0xEDB88320, init/xorout 0xFFFFFFFF — zlib-compatible, and
// bit-identical to pyble_proto.crc32 (the shared oracle).
uint32_t pble_proto_crc32(const uint8_t *data, size_t len) {
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int k = 0; k < 8; k++) {
            crc = (crc & 1u) ? ((crc >> 1) ^ 0xEDB88320u) : (crc >> 1);
        }
    }
    return crc ^ 0xFFFFFFFFu;
}

#define PBLE_HDR_LEN 6   // VER + TYPE + OPCODE + ID + LEN(2)
#define PBLE_CRC_LEN 4

// Build a §3.1 frame: VER OPCODE etc. + CRC32(LE) over VER..PAYLOAD.
int pble_proto_encode(uint8_t type_, uint8_t opcode, uint8_t id_,
                      const uint8_t *payload, size_t plen, uint8_t *out, size_t cap) {
    if (plen > 0xFFFF) {
        return -1;
    }
    size_t total = PBLE_HDR_LEN + plen + PBLE_CRC_LEN;
    if (total > cap) {
        return -1;
    }
    out[0] = PBLE_PROTO_VERSION;
    out[1] = type_;
    out[2] = opcode;
    out[3] = id_;
    out[4] = (uint8_t)(plen & 0xFF);
    out[5] = (uint8_t)((plen >> 8) & 0xFF);
    if (plen && payload) {
        memcpy(out + PBLE_HDR_LEN, payload, plen);
    }
    uint32_t crc = pble_proto_crc32(out, PBLE_HDR_LEN + plen);
    uint8_t *c = out + PBLE_HDR_LEN + plen;
    c[0] = (uint8_t)(crc & 0xFF);
    c[1] = (uint8_t)((crc >> 8) & 0xFF);
    c[2] = (uint8_t)((crc >> 16) & 0xFF);
    c[3] = (uint8_t)((crc >> 24) & 0xFF);
    return (int)total;
}

// Structural + §9 VER decode (CRC is checked in dispatch, matching pyble_proto).
// 0 ok · -1 malformed (short/LEN mismatch, FR-PROTO-8) · -3 bad VER (FR-PROTO-7).
int pble_proto_decode(const uint8_t *msg, size_t len, pble_frame_t *out) {
    if (len < PBLE_HDR_LEN + PBLE_CRC_LEN) {
        return -1;
    }
    uint16_t plen = (uint16_t)(msg[4] | (msg[5] << 8));
    if (len != (size_t)PBLE_HDR_LEN + plen + PBLE_CRC_LEN) {
        return -1;
    }
    if (msg[0] != PBLE_PROTO_VERSION) {
        return -3;   // §9: only VER 0x01 is served
    }
    out->ver = msg[0];
    out->type = msg[1];
    out->opcode = msg[2];
    out->id = msg[3];
    out->payload = msg + PBLE_HDR_LEN;
    out->len = plen;
    return 0;
}

// --- Static generic-response pool -------------------------------------------
// Slots remain immutable from READY publication until completion/cancellation.
// The short critical section protects metadata and bounded copies only; it is
// never held across Notify, VFS, a semaphore wait, or a handler call.
typedef enum {
    PBLE_RSP_FREE = 0,
    PBLE_RSP_CLAIMED,
    PBLE_RSP_RESERVED,
    PBLE_RSP_READY,
    PBLE_RSP_COMPLETE,
} pble_rsp_state_t;

typedef struct {
    pble_rsp_state_t state;
    uint32_t incarnation;
    pble_rsp_ticket_t ticket;
    uint8_t frame[PBLE_RSP_FRAME_MAX];
    uint16_t frame_len;
    uint16_t offset;
    uint8_t index;
    uint32_t stream_generation;
    TickType_t deadline;
    uint64_t ready_order;
    bool retain_completion;
    bool completion_ok;
} pble_rsp_slot_t;

static pble_rsp_slot_t s_rsp_pool[PBLE_RSP_POOL_DEPTH];
static StaticSemaphore_t s_rsp_done_storage[PBLE_RSP_POOL_DEPTH];
static SemaphoreHandle_t s_rsp_done[PBLE_RSP_POOL_DEPTH];
static portMUX_TYPE s_rsp_mux = portMUX_INITIALIZER_UNLOCKED;
static bool s_rsp_initialized;
static int8_t s_rsp_active_slot = -1;
static uint64_t s_rsp_ready_order;
static bool s_rsp_tx_owned;

static bool pble_rsp_has_pending_locked(void) {
    for (uint8_t i = 0; i < PBLE_RSP_POOL_DEPTH; i++) {
        if (s_rsp_pool[i].state == PBLE_RSP_READY) {
            return true;
        }
    }
    return false;
}

static bool pble_rsp_ticket_matches_locked(const pble_rsp_slot_t *slot,
                                           const pble_rsp_ticket_t *ticket) {
    return ticket != NULL && ticket->slot < PBLE_RSP_POOL_DEPTH &&
           slot == &s_rsp_pool[ticket->slot] &&
           slot->state != PBLE_RSP_FREE &&
           slot->incarnation == ticket->incarnation &&
           slot->ticket.session.conn == ticket->session.conn &&
           slot->ticket.session.generation == ticket->session.generation &&
           slot->ticket.session.vm_epoch == ticket->session.vm_epoch &&
           slot->ticket.vm_epoch == ticket->vm_epoch;
}

static bool pble_rsp_claim_matches_locked(const pble_rsp_slot_t *slot,
                                          const pble_rsp_ticket_t *claim) {
    return slot != NULL && claim != NULL &&
           slot->state == PBLE_RSP_CLAIMED &&
           pble_rsp_ticket_matches_locked(slot, claim);
}

static void pble_rsp_recycle_locked(pble_rsp_slot_t *slot) {
    slot->state = PBLE_RSP_FREE;
    slot->frame_len = 0;
    slot->offset = 0;
    slot->index = 0;
    slot->retain_completion = false;
    slot->completion_ok = false;
    slot->incarnation++;
    if (slot->incarnation == 0) {
        slot->incarnation = 1;
    }
}

void pble_proto_init(void) {
    if (s_rsp_initialized) {
        return;
    }
    memset(s_rsp_pool, 0, sizeof(s_rsp_pool));
    for (uint8_t i = 0; i < PBLE_RSP_POOL_DEPTH; i++) {
        s_rsp_pool[i].incarnation = 1;
        s_rsp_done[i] = xSemaphoreCreateBinaryStatic(&s_rsp_done_storage[i]);
        if (s_rsp_done[i] == NULL) {
            mp_raise_msg(&mp_type_RuntimeError,
                         MP_ERROR_TEXT("response completion alloc failed"));
        }
    }
    s_rsp_initialized = true;
}

bool pble_rsp_reserve(const pble_session_token_t *session,
                      pble_rsp_ticket_t *ticket) {
    if (ticket == NULL || session == NULL ||
        !pble_ble_session_live(session)) {
        return false;
    }
    pble_proto_init();
    uint64_t vm_epoch = pble_vm_epoch_current();
    if (vm_epoch == 0 || vm_epoch != session->vm_epoch ||
        !pble_vm_epoch_valid(vm_epoch)) {
        return false;
    }

    bool reserved = false;
    for (uint8_t i = 0; i < PBLE_RSP_POOL_DEPTH; i++) {
        pble_rsp_slot_t *slot = &s_rsp_pool[i];
        taskENTER_CRITICAL(&s_rsp_mux);
        if (slot->state != PBLE_RSP_FREE) {
            taskEXIT_CRITICAL(&s_rsp_mux);
            continue;
        }
        slot->ticket.slot = i;
        slot->ticket.incarnation = slot->incarnation;
        slot->ticket.session = *session;
        slot->ticket.vm_epoch = vm_epoch;
        slot->retain_completion = false;
        slot->state = PBLE_RSP_CLAIMED;
        pble_rsp_ticket_t claim_ticket = slot->ticket;
        taskEXIT_CRITICAL(&s_rsp_mux);

        // Completion signals are deliberately untagged. Claim the exact slot
        // incarnation first, then drain any delayed old give before RESERVED
        // becomes observable. Cancellation/reset may recycle the claim while
        // the pool lock is released, so revalidate both identity and session.
        (void)xSemaphoreTake(s_rsp_done[i], 0);
        bool claim_live = pble_rsp_session_valid(&claim_ticket);
        taskENTER_CRITICAL(&s_rsp_mux);
        bool claim_matches =
            pble_rsp_claim_matches_locked(slot, &claim_ticket);
        if (!claim_live || !claim_matches) {
            if (claim_matches) {
                pble_rsp_recycle_locked(slot);
            }
            taskEXIT_CRITICAL(&s_rsp_mux);
            continue;
        }
        slot->state = PBLE_RSP_RESERVED;
        *ticket = claim_ticket;
        reserved = true;
        taskEXIT_CRITICAL(&s_rsp_mux);
        break;
    }
    return reserved;
}

bool pble_rsp_session_valid(const pble_rsp_ticket_t *ticket) {
    return ticket != NULL &&
           pble_ble_session_live(&ticket->session) &&
           pble_vm_epoch_valid(ticket->vm_epoch);
}

bool pble_rsp_ticket_valid(const pble_rsp_ticket_t *ticket) {
    bool valid = false;
    if (ticket == NULL || ticket->slot >= PBLE_RSP_POOL_DEPTH) {
        return false;
    }
    taskENTER_CRITICAL(&s_rsp_mux);
    pble_rsp_slot_t *slot = &s_rsp_pool[ticket->slot];
    valid = pble_rsp_ticket_matches_locked(slot, ticket) &&
            slot->state == PBLE_RSP_RESERVED;
    taskEXIT_CRITICAL(&s_rsp_mux);
    return valid && pble_rsp_session_valid(ticket);
}

bool pble_rsp_expect_completion(const pble_rsp_ticket_t *ticket) {
    bool valid = false;
    if (ticket == NULL || ticket->slot >= PBLE_RSP_POOL_DEPTH) {
        return false;
    }
    taskENTER_CRITICAL(&s_rsp_mux);
    pble_rsp_slot_t *slot = &s_rsp_pool[ticket->slot];
    valid = pble_rsp_ticket_matches_locked(slot, ticket) &&
            slot->state == PBLE_RSP_RESERVED;
    if (valid) {
        slot->retain_completion = true;
    }
    taskEXIT_CRITICAL(&s_rsp_mux);
    return valid;
}

bool pble_rsp_publish(const pble_rsp_ticket_t *ticket, uint8_t opcode,
                      uint8_t id_, const uint8_t *payload, size_t len) {
    if (ticket == NULL || ticket->slot >= PBLE_RSP_POOL_DEPTH ||
        len > 1u + PBLE_RSP_MAX) {
        return false;
    }
    uint8_t encoded[PBLE_RSP_FRAME_MAX];
    int encoded_len = pble_proto_encode(PBLE_TYPE_RSP, opcode, id_, payload, len,
                                        encoded, sizeof(encoded));
    if (encoded_len <= 0) {
        return false;
    }

    bool session_live = pble_rsp_session_valid(ticket);
    bool published = false;
    bool wake = false;
    taskENTER_CRITICAL(&s_rsp_mux);
    pble_rsp_slot_t *slot = &s_rsp_pool[ticket->slot];
    if (pble_rsp_ticket_matches_locked(slot, ticket) &&
        slot->state == PBLE_RSP_RESERVED && session_live) {
        memcpy(slot->frame, encoded, (size_t)encoded_len);
        slot->frame_len = (uint16_t)encoded_len;
        slot->offset = 0;
        slot->index = 0;
        slot->stream_generation = 0;
        TickType_t budget = pdMS_TO_TICKS(PBLE_RSP_TX_BUDGET_MS);
        slot->deadline = xTaskGetTickCount() + (budget ? budget : 1);
        slot->ready_order = ++s_rsp_ready_order;
        slot->state = PBLE_RSP_READY;
        // Claim logical TX ownership in the same critical section that makes
        // this response visible. The callout's idle handoff uses this same mux,
        // so a worker cannot publish between an empty-pool observation and an
        // owner clear.
        s_rsp_tx_owned = true;
        published = true;
    }
    taskEXIT_CRITICAL(&s_rsp_mux);
    if (published) {
        pble_ble_rsp_kick();
    }
    if (!published) {
        // A retained publisher has a waiter which must be completed even when
        // admission closes between encoding and publication.  Commit the
        // tagged state first and signal only after leaving the pool mux.
        taskENTER_CRITICAL(&s_rsp_mux);
        slot = &s_rsp_pool[ticket->slot];
        if (pble_rsp_ticket_matches_locked(slot, ticket) &&
            slot->state == PBLE_RSP_RESERVED) {
            if (slot->retain_completion) {
                wake = slot->state != PBLE_RSP_COMPLETE;
                slot->completion_ok = false;
                slot->state = PBLE_RSP_COMPLETE;
            } else {
                pble_rsp_recycle_locked(slot);
            }
        }
        taskEXIT_CRITICAL(&s_rsp_mux);
        if (wake) {
            xSemaphoreGive(s_rsp_done[ticket->slot]);
        }
    }
    return published;
}

void pble_rsp_release(const pble_rsp_ticket_t *ticket) {
    if (ticket == NULL || ticket->slot >= PBLE_RSP_POOL_DEPTH) {
        return;
    }
    taskENTER_CRITICAL(&s_rsp_mux);
    pble_rsp_slot_t *slot = &s_rsp_pool[ticket->slot];
    if (pble_rsp_ticket_matches_locked(slot, ticket)) {
        if (s_rsp_active_slot == (int8_t)ticket->slot) {
            s_rsp_active_slot = -1;
        }
        pble_rsp_recycle_locked(slot);
    }
    taskEXIT_CRITICAL(&s_rsp_mux);
}

bool pble_rsp_wait(const pble_rsp_ticket_t *ticket) {
    if (ticket == NULL || ticket->slot >= PBLE_RSP_POOL_DEPTH) {
        return false;
    }
    for (;;) {
        xSemaphoreTake(s_rsp_done[ticket->slot], portMAX_DELAY);
        bool completed = false;
        bool done = false;
        bool still_waiting = false;
        taskENTER_CRITICAL(&s_rsp_mux);
        pble_rsp_slot_t *slot = &s_rsp_pool[ticket->slot];
        if (pble_rsp_ticket_matches_locked(slot, ticket)) {
            if (slot->state == PBLE_RSP_COMPLETE) {
                completed = slot->completion_ok;
                pble_rsp_recycle_locked(slot);
                done = true;
            } else if (slot->state == PBLE_RSP_RESERVED ||
                       slot->state == PBLE_RSP_READY) {
                still_waiting = true;
            }
        }
        taskEXIT_CRITICAL(&s_rsp_mux);
        if (done) {
            return completed;
        }
        if (still_waiting) {
            continue;
        }
        return false;
    }
}

void pble_rsp_cancel_session(const pble_session_token_t *session) {
    if (session == NULL) {
        return;
    }
    uint32_t wake_mask = 0;
    taskENTER_CRITICAL(&s_rsp_mux);
    for (uint8_t i = 0; i < PBLE_RSP_POOL_DEPTH; i++) {
        pble_rsp_slot_t *slot = &s_rsp_pool[i];
        if (slot->state != PBLE_RSP_FREE &&
            slot->ticket.session.conn == session->conn &&
            slot->ticket.session.generation == session->generation &&
            slot->ticket.session.vm_epoch == session->vm_epoch) {
            if (s_rsp_active_slot == (int8_t)i) {
                s_rsp_active_slot = -1;
            }
            if (slot->retain_completion) {
                bool transition = slot->state != PBLE_RSP_COMPLETE;
                slot->completion_ok = false;
                slot->state = PBLE_RSP_COMPLETE;
                if (transition) {
                    wake_mask |= (1u << i);
                }
            } else {
                pble_rsp_recycle_locked(slot);
            }
        }
    }
    taskEXIT_CRITICAL(&s_rsp_mux);
    for (uint8_t i = 0; i < PBLE_RSP_POOL_DEPTH; i++) {
        if (wake_mask & (1u << i)) {
            xSemaphoreGive(s_rsp_done[i]);
        }
    }
}

void pble_rsp_cancel_ticket(const pble_rsp_ticket_t *ticket) {
    if (ticket == NULL || ticket->slot >= PBLE_RSP_POOL_DEPTH) {
        return;
    }
    bool wake = false;
    taskENTER_CRITICAL(&s_rsp_mux);
    pble_rsp_slot_t *slot = &s_rsp_pool[ticket->slot];
    if (pble_rsp_ticket_matches_locked(slot, ticket)) {
        if (s_rsp_active_slot == (int8_t)ticket->slot) {
            s_rsp_active_slot = -1;
        }
        bool retained = slot->retain_completion;
        wake = retained && slot->state != PBLE_RSP_COMPLETE;
        if (retained) {
            slot->completion_ok = false;
            slot->state = PBLE_RSP_COMPLETE;
        } else {
            pble_rsp_recycle_locked(slot);
        }
    }
    taskEXIT_CRITICAL(&s_rsp_mux);
    if (wake) {
        xSemaphoreGive(s_rsp_done[ticket->slot]);
    }
}

bool pble_rsp_tx_peek(pble_rsp_tx_t *tx) {
    if (tx == NULL) {
        return false;
    }
    bool found = false;
    taskENTER_CRITICAL(&s_rsp_mux);
    if (s_rsp_active_slot < 0 ||
        s_rsp_pool[s_rsp_active_slot].state != PBLE_RSP_READY) {
        int8_t best = -1;
        uint64_t order = UINT64_MAX;
        for (uint8_t i = 0; i < PBLE_RSP_POOL_DEPTH; i++) {
            if (s_rsp_pool[i].state == PBLE_RSP_READY &&
                s_rsp_pool[i].ready_order < order) {
                best = (int8_t)i;
                order = s_rsp_pool[i].ready_order;
            }
        }
        s_rsp_active_slot = best;
    }
    if (s_rsp_active_slot >= 0) {
        pble_rsp_slot_t *slot = &s_rsp_pool[s_rsp_active_slot];
        tx->ticket = slot->ticket;
        tx->frame = slot->frame;
        tx->frame_len = slot->frame_len;
        tx->offset = slot->offset;
        tx->index = slot->index;
        tx->stream_generation = slot->stream_generation;
        tx->deadline = (uint32_t)slot->deadline;
        found = true;
    }
    taskEXIT_CRITICAL(&s_rsp_mux);
    return found;
}

void pble_rsp_tx_result(const pble_rsp_tx_t *tx, uint32_t stream_generation,
                        uint16_t offset, uint8_t index, uint16_t accepted,
                        int tx_result) {
    if (tx == NULL || tx->ticket.slot >= PBLE_RSP_POOL_DEPTH) {
        return;
    }
    bool wake = false;
    taskENTER_CRITICAL(&s_rsp_mux);
    pble_rsp_slot_t *slot = &s_rsp_pool[tx->ticket.slot];
    if (pble_rsp_ticket_matches_locked(slot, &tx->ticket) &&
        slot->state == PBLE_RSP_READY) {
        slot->stream_generation = stream_generation;
        slot->offset = offset;
        slot->index = index;
        if (tx_result == PBLE_TX_OK) {
            slot->offset = (uint16_t)(offset + accepted);
            slot->index = (uint8_t)(index + 1);
            if (slot->offset >= slot->frame_len) {
                s_rsp_active_slot = -1;
                if (slot->retain_completion) {
                    slot->completion_ok = true;
                    slot->state = PBLE_RSP_COMPLETE;
                    wake = true;
                } else {
                    pble_rsp_recycle_locked(slot);
                }
            }
        } else if (tx_result != PBLE_TX_AGAIN) {
            s_rsp_active_slot = -1;
            wake = slot->retain_completion;
            if (wake) {
                slot->completion_ok = false;
                slot->state = PBLE_RSP_COMPLETE;
            } else {
                pble_rsp_recycle_locked(slot);
            }
        }
    }
    taskEXIT_CRITICAL(&s_rsp_mux);
    if (wake) {
        xSemaphoreGive(s_rsp_done[tx->ticket.slot]);
    }
}

bool pble_rsp_has_pending(void) {
    bool pending;
    taskENTER_CRITICAL(&s_rsp_mux);
    pending = pble_rsp_has_pending_locked();
    taskEXIT_CRITICAL(&s_rsp_mux);
    return pending;
}

bool pble_rsp_tx_owned(void) {
    bool owned;
    taskENTER_CRITICAL(&s_rsp_mux);
    owned = s_rsp_tx_owned;
    taskEXIT_CRITICAL(&s_rsp_mux);
    return owned;
}

bool pble_rsp_release_owner_if_idle(void) {
    bool owned;
    taskENTER_CRITICAL(&s_rsp_mux);
    owned = pble_rsp_has_pending_locked();
    s_rsp_tx_owned = owned;
    taskEXIT_CRITICAL(&s_rsp_mux);
    return owned;
}

void pble_proto_vm_reset(void) {
    if (!s_rsp_initialized) {
        return;
    }
    taskENTER_CRITICAL(&s_rsp_mux);
    s_rsp_active_slot = -1;
    s_rsp_tx_owned = false;
    s_rsp_ready_order = 0;
    for (uint8_t i = 0; i < PBLE_RSP_POOL_DEPTH; i++) {
        pble_rsp_recycle_locked(&s_rsp_pool[i]);
    }
    taskEXIT_CRITICAL(&s_rsp_mux);
    for (uint8_t i = 0; i < PBLE_RSP_POOL_DEPTH; i++) {
        while (xSemaphoreTake(s_rsp_done[i], 0) == pdTRUE) {
        }
    }
}

// --- Opcode dispatch table ---------------------------------------------------
typedef enum {
    PBLE_HANDLER_GENERIC = 0,
    PBLE_HANDLER_DEFERRED,
    PBLE_HANDLER_NO_RESPONSE,
    PBLE_HANDLER_SPECIAL,
} pble_handler_kind_t;

static pble_handler_t s_handlers[256];
static pble_deferred_handler_t s_deferred_handlers[256];
static uint8_t s_handler_kinds[256];

void pble_proto_register(uint8_t opcode, pble_handler_t h) {
    s_handlers[opcode] = h;
    s_handler_kinds[opcode] = PBLE_HANDLER_GENERIC;
}

void pble_proto_register_deferred(uint8_t opcode, pble_deferred_handler_t h) {
    s_deferred_handlers[opcode] = h;
    s_handler_kinds[opcode] = PBLE_HANDLER_DEFERRED;
}

void pble_proto_register_no_response(uint8_t opcode, pble_handler_t h) {
    s_handlers[opcode] = h;
    s_handler_kinds[opcode] = PBLE_HANDLER_NO_RESPONSE;
}

void pble_proto_register_special(uint8_t opcode, pble_handler_t h) {
    s_handlers[opcode] = h;
    s_handler_kinds[opcode] = PBLE_HANDLER_SPECIAL;
}

// Scratch response payload (dispatch is single-threaded on the NimBLE host).
static uint8_t s_rsp[1 + PBLE_RSP_MAX];

void pble_proto_refuse(uint8_t opcode, uint8_t id_, uint8_t status,
                       const pble_session_token_t *session) {
    pble_rsp_ticket_t ticket;
    if (!pble_rsp_reserve(session, &ticket)) {
        pble_ble_terminate_session(session);
        return;
    }
    (void)pble_rsp_publish(&ticket, opcode, id_, &status, 1);
}

// All effects after complete-message admission live here.  The outer dispatch
// retains one immutable session token and one lifecycle activity around this
// entire operation, including fire-and-forget and special RUN handlers.
static void pble_proto_dispatch_admitted(
    const uint8_t *msg, size_t len, const pble_session_token_t *session) {
    pble_frame_t f = {0};
    int rc = pble_proto_decode(msg, len, &f);
    bool invoke_handler = false;
    uint8_t opcode = (len > 2) ? msg[2] : 0;
    uint8_t id_ = (len > 3) ? msg[3] : 0;
    uint8_t status = PBLE_EBADREQ;
    size_t extra = 0;
    pble_handler_t h = NULL;
    pble_deferred_handler_t deferred = NULL;
    pble_handler_kind_t kind = PBLE_HANDLER_GENERIC;

    if (rc >= 0) {
        opcode = f.opcode;
        id_ = f.id;
        uint32_t got = (uint32_t)msg[len - 4] |
                       ((uint32_t)msg[len - 3] << 8) |
                       ((uint32_t)msg[len - 2] << 16) |
                       ((uint32_t)msg[len - 1] << 24);
        if (pble_proto_crc32(msg, len - PBLE_CRC_LEN) != got) {
            status = PBLE_ECRC;
        } else {
            kind = (pble_handler_kind_t)s_handler_kinds[f.opcode];
            h = s_handlers[f.opcode];
            deferred = s_deferred_handlers[f.opcode];

            if (!pble_vm_reboot_command_admitted(
                    f.opcode == PBLE_OP_SOFT_REBOOT)) {
                // During an accepted SOFT_REBOOT grace, response-bearing
                // commands receive a bounded EBUSY refusal while fire-and-
                // forget commands remain effect-free and response-free.
                if (kind == PBLE_HANDLER_NO_RESPONSE) {
                    return;
                }
                status = PBLE_EBUSY;
            } else if (kind == PBLE_HANDLER_NO_RESPONSE && h != NULL) {
                (void)h(&f, s_rsp + 1, &extra, session);
                return;
            } else if (kind == PBLE_HANDLER_SPECIAL && h != NULL) {
                pble_handler_t special_handler = h;
                status = special_handler(&f, s_rsp + 1, &extra, session);
                if (status == PBLE_NO_RSP) {
                    return;
                }
            } else if (h == NULL && deferred == NULL) {
                status = PBLE_EUNSUPPORTED;
            } else {
                invoke_handler = true;
            }
        }
    }

    pble_rsp_ticket_t ticket;
    if (!pble_rsp_reserve(session, &ticket)) {
        pble_ble_terminate_session(session);
        return;
    }

    if (invoke_handler) {
        if (kind == PBLE_HANDLER_DEFERRED) {
            status = deferred(&f, s_rsp + 1, &extra, session, &ticket);
        } else {
            status = h(&f, s_rsp + 1, &extra, session);
        }
        if (status == PBLE_NO_RSP) {
            if (kind != PBLE_HANDLER_DEFERRED) {
                pble_rsp_release(&ticket);
            }
            return;
        }
    }
    if (extra > PBLE_RSP_MAX) {
        extra = PBLE_RSP_MAX;
    }
    s_rsp[0] = status;
    (void)pble_rsp_publish(&ticket, opcode, id_, s_rsp, 1 + extra);
}

// Decode → §9/CRC gates → category-aware route → reserved generic RSP.
void pble_proto_dispatch(const uint8_t *msg, size_t len, uint16_t conn) {
    pble_session_token_t session;
    if (!pble_ble_session_snapshot(conn, &session)) {
        return;
    }
    pble_vm_activity_t activity;
    if (!pble_vm_dispatch_enter(session.vm_epoch, &activity)) {
        return;
    }
    pble_proto_dispatch_admitted(msg, len, &session);
    pble_vm_dispatch_leave(&activity);
}

// Emit a frame with a caller-supplied TYPE + ID from any context (see the header).
// Uses a per-call stack buffer (NOT the host-task-only s_out) so concurrent worker
// _threads — the runner worker (RUN_STATE/CONSOLE_DATA) and the fs-worker
// (FILE_GET_DATA/END, FILE_PUT_ACK, async FILE_* RSPs by id) — never collide on a
// shared encode buffer; pble_ble_notify's recursive TX mutex serializes the actual
// fragment+Notify so each whole message goes out atomically.
int pble_proto_emit_id(uint8_t type_, uint8_t opcode, uint8_t id_,
                       const uint8_t *payload, size_t len,
                       const pble_session_token_t *session) {
    // Generic RSPs require a pre-reserved slot. This legacy worker-safe helper
    // remains only for EVT traffic; specialized status RSPs use the exact
    // connection-bound specialized API below.
    if (type_ == PBLE_TYPE_RSP || len > PBLE_RSP_MAX) {
        return -1;
    }
    uint8_t buf[PBLE_HDR_LEN + PBLE_RSP_MAX + PBLE_CRC_LEN];
    int n = pble_proto_encode(type_, opcode, id_, payload, len, buf, sizeof(buf));
    if (n < 0) {
        return -1;
    }
    return pble_ble_notify(buf, (size_t)n, session);
}

// RUN/STOP/SOFT_REBOOT own this narrow status-only response path. Its 11-byte
// frame is one fragment even at ATT MTU 23; the transport independently
// enforces that invariant before its bounded boundary wait and single Notify.
int pble_proto_emit_rsp_status_try(uint8_t opcode, uint8_t id_, uint8_t status,
                                   const pble_session_token_t *expected_conn) {
    uint8_t buf[PBLE_HDR_LEN + 1 + PBLE_CRC_LEN];
    int n = pble_proto_encode(PBLE_TYPE_RSP, opcode, id_, &status, 1,
                              buf, sizeof(buf));
    if (n < 0) {
        return PBLE_TX_OVERSIZE;
    }
    return pble_ble_notify_control_try_for_conn(buf, (size_t)n, expected_conn);
}

// Emit an event (TYPE=EVT, ID=0) — RUN_STATE etc. (FR-PROTO-4).
int pble_proto_emit(uint8_t opcode, const uint8_t *payload, size_t len,
                    const pble_session_token_t *session) {
    return pble_proto_emit_id(PBLE_TYPE_EVT, opcode, 0, payload, len, session);
}

// Paced event emit for STREAMING callers (fs-worker; see pble_ble_notify_paced):
// congestion blocks on the NOTIFY_TX drain event up to [budget_ms] instead of
// dropping the event or busy-spinning.
int pble_proto_emit_paced(uint8_t opcode, const uint8_t *payload, size_t len,
                          uint32_t budget_ms,
                          const pble_session_token_t *session) {
    if (len > PBLE_RSP_MAX) {
        return -1;
    }
    uint8_t buf[PBLE_HDR_LEN + PBLE_RSP_MAX + PBLE_CRC_LEN];
    int n = pble_proto_encode(PBLE_TYPE_EVT, opcode, 0, payload, len,
                              buf, sizeof(buf));
    if (n < 0) {
        return -1;
    }
    return pble_ble_notify_paced(buf, (size_t)n, budget_ms, session);
}

int pble_proto_emit_paced_for_session(
    uint8_t opcode, const uint8_t *payload, size_t len, uint32_t budget_ms,
    const pble_session_token_t *session) {
    if (len > PBLE_RSP_MAX) {
        return -1;
    }
    uint8_t buf[PBLE_HDR_LEN + PBLE_RSP_MAX + PBLE_CRC_LEN];
    int n = pble_proto_encode(PBLE_TYPE_EVT, opcode, 0, payload, len,
                              buf, sizeof(buf));
    if (n < 0) {
        return -1;
    }
    return pble_ble_notify_paced_for_session(buf, (size_t)n, budget_ms,
                                              session);
}

int pble_proto_emit_control_paced(uint8_t opcode, const uint8_t *payload,
                                  size_t len, uint32_t budget_ms,
                                  const pble_session_token_t *session) {
    if (len > PBLE_RSP_MAX) {
        return -1;
    }
    uint8_t buf[PBLE_HDR_LEN + PBLE_RSP_MAX + PBLE_CRC_LEN];
    int n = pble_proto_encode(PBLE_TYPE_EVT, opcode, 0, payload, len, buf, sizeof(buf));
    if (n < 0) {
        return -1;
    }
    return pble_ble_notify_control_paced(buf, (size_t)n, budget_ms, session);
}

// --- MicroPython module shim (host corpus: crc32 + encode) -------------------
static mp_obj_t mod_pble_crc32(mp_obj_t buf_in) {
    mp_buffer_info_t b;
    mp_get_buffer_raise(buf_in, &b, MP_BUFFER_READ);
    return mp_obj_new_int_from_uint(pble_proto_crc32((const uint8_t *)b.buf, b.len));
}
static MP_DEFINE_CONST_FUN_OBJ_1(mod_pble_crc32_obj, mod_pble_crc32);

static mp_obj_t mod_pble_encode(size_t n_args, const mp_obj_t *args) {
    uint8_t type_ = (uint8_t)mp_obj_get_int(args[0]);
    uint8_t opcode = (uint8_t)mp_obj_get_int(args[1]);
    uint8_t id_ = (uint8_t)mp_obj_get_int(args[2]);
    mp_buffer_info_t p;
    p.buf = NULL;
    p.len = 0;
    if (n_args >= 4 && args[3] != mp_const_none) {
        mp_get_buffer_raise(args[3], &p, MP_BUFFER_READ);
    }
    uint8_t buf[PBLE_HDR_LEN + PBLE_RSP_MAX + PBLE_CRC_LEN];
    int n = pble_proto_encode(type_, opcode, id_, (const uint8_t *)p.buf, p.len,
                              buf, sizeof(buf));
    if (n < 0) {
        mp_raise_ValueError(MP_ERROR_TEXT("payload exceeds frame LEN"));
    }
    return mp_obj_new_bytes(buf, (size_t)n);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_pble_encode_obj, 3, 4, mod_pble_encode);

static const mp_rom_map_elem_t pble_proto_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_pble_proto) },
    { MP_ROM_QSTR(MP_QSTR_VER), MP_ROM_INT(PBLE_PROTO_VERSION) },
    { MP_ROM_QSTR(MP_QSTR_CMD), MP_ROM_INT(PBLE_TYPE_CMD) },
    { MP_ROM_QSTR(MP_QSTR_RSP), MP_ROM_INT(PBLE_TYPE_RSP) },
    { MP_ROM_QSTR(MP_QSTR_EVT), MP_ROM_INT(PBLE_TYPE_EVT) },
    { MP_ROM_QSTR(MP_QSTR_crc32), MP_ROM_PTR(&mod_pble_crc32_obj) },
    { MP_ROM_QSTR(MP_QSTR_encode), MP_ROM_PTR(&mod_pble_encode_obj) },
};
static MP_DEFINE_CONST_DICT(pble_proto_globals, pble_proto_globals_table);

const mp_obj_module_t pble_proto_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&pble_proto_globals,
};

MP_REGISTER_MODULE(MP_QSTR_pble_proto, pble_proto_user_cmodule);
