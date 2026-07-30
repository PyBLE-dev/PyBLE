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
#include <string.h>
#include "py/runtime.h"
#include "py/obj.h"

#include "pble_proto.h"
#include "pble_ble.h"   // pble_ble_notify — the sole TX path

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

// --- Opcode dispatch table ---------------------------------------------------
static pble_handler_t s_handlers[256];

void pble_proto_register(uint8_t opcode, pble_handler_t h) {
    s_handlers[opcode] = h;
}

// Scratch buffers (dispatch runs single-threaded on the NimBLE host task).
static uint8_t s_rsp[1 + PBLE_RSP_MAX];                 // [status][handler extra]
static uint8_t s_out[PBLE_HDR_LEN + 1 + PBLE_RSP_MAX + PBLE_CRC_LEN];

static void pble_send(uint8_t type_, uint8_t opcode, uint8_t id_,
                      const uint8_t *payload, size_t plen) {
    int n = pble_proto_encode(type_, opcode, id_, payload, plen, s_out, sizeof(s_out));
    if (n > 0) {
        pble_ble_notify(s_out, (size_t)n);
    }
}

// decode → §9 VER guard → CRC gate → route → RSP. Mirrors pyble_proto.on_message:
// malformed/bad-VER → RSP EBADREQ (echo opcode/id best-effort); CRC fail → EVT
// ERROR(ECRC) id=0 ref opcode; unknown opcode → RSP EUNSUPPORTED; handler → RSP
// [status][extra] echoing the request opcode + id.
void pble_proto_dispatch(const uint8_t *msg, size_t len, uint16_t conn) {
    pble_frame_t f;
    int rc = pble_proto_decode(msg, len, &f);
    if (rc < 0) {   // -1 malformed OR -3 bad VER (§9 refusal, F-16)
        uint8_t op = (len > 2) ? msg[2] : 0;
        uint8_t id = (len > 3) ? msg[3] : 0;
        uint8_t st = PBLE_EBADREQ;
        pble_send(PBLE_TYPE_RSP, op, id, &st, 1);
        return;
    }
    // CRC gate (FR-PROTO-3): a mismatch drops the frame → EVT ERROR(ECRC), id 0.
    uint32_t got = (uint32_t)msg[len - 4] | ((uint32_t)msg[len - 3] << 8) |
                   ((uint32_t)msg[len - 2] << 16) | ((uint32_t)msg[len - 1] << 24);
    if (pble_proto_crc32(msg, len - PBLE_CRC_LEN) != got) {
        uint8_t st = PBLE_ECRC;
        pble_send(PBLE_TYPE_EVT, f.opcode, 0, &st, 1);
        return;
    }
    pble_handler_t h = s_handlers[f.opcode];
    size_t extra = 0;
    uint8_t status;
    if (h == NULL) {
        status = PBLE_EUNSUPPORTED;     // FR-PROTO-9
    } else {
        status = h(&f, s_rsp + 1, &extra, conn);
        // Fire-and-forget CMDs (CONSOLE_INPUT 0x31) return PBLE_NO_RSP: no RSP
        // frame is emitted. The sentinel is internal-only, never on the wire.
        if (status == PBLE_NO_RSP) {
            return;
        }
        if (extra > PBLE_RSP_MAX) {
            extra = PBLE_RSP_MAX;
        }
    }
    s_rsp[0] = status;
    pble_send(PBLE_TYPE_RSP, f.opcode, f.id, s_rsp, 1 + extra);
}

// Emit a frame with a caller-supplied TYPE + ID from any context (see the header).
// Uses a per-call stack buffer (NOT the host-task-only s_out) so concurrent worker
// _threads — the runner worker (RUN_STATE/CONSOLE_DATA) and the fs-worker
// (FILE_GET_DATA/END, FILE_PUT_ACK, async FILE_* RSPs by id) — never collide on a
// shared encode buffer; pble_ble_notify's recursive TX mutex serializes the actual
// fragment+Notify so each whole message goes out atomically.
int pble_proto_emit_id(uint8_t type_, uint8_t opcode, uint8_t id_,
                       const uint8_t *payload, size_t len) {
    if (len > PBLE_RSP_MAX) {
        return -1;
    }
    uint8_t buf[PBLE_HDR_LEN + PBLE_RSP_MAX + PBLE_CRC_LEN];
    int n = pble_proto_encode(type_, opcode, id_, payload, len, buf, sizeof(buf));
    if (n < 0) {
        return -1;
    }
    return pble_ble_notify(buf, (size_t)n);
}

// Emit an event (TYPE=EVT, ID=0) — RUN_STATE etc. (FR-PROTO-4).
int pble_proto_emit(uint8_t opcode, const uint8_t *payload, size_t len) {
    return pble_proto_emit_id(PBLE_TYPE_EVT, opcode, 0, payload, len);
}

// Paced event emit for STREAMING callers (fs-worker; see pble_ble_notify_paced):
// congestion blocks on the NOTIFY_TX drain event up to [budget_ms] instead of
// dropping the event or busy-spinning.
int pble_proto_emit_paced(uint8_t opcode, const uint8_t *payload, size_t len,
                          uint32_t budget_ms) {
    if (len > PBLE_RSP_MAX) {
        return -1;
    }
    uint8_t buf[PBLE_HDR_LEN + PBLE_RSP_MAX + PBLE_CRC_LEN];
    int n = pble_proto_encode(PBLE_TYPE_EVT, opcode, 0, payload, len, buf, sizeof(buf));
    if (n < 0) {
        return -1;
    }
    return pble_ble_notify_paced(buf, (size_t)n, budget_ms);
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
