// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_fs — PBLE/1 filesystem bridge + workspace jail. See pble_fs.h for the
// execution model. Clean-room vs protocol.md §5 (FROZEN) + specs.md §4.4:
//   F-08  read : FILE_LIST (0x10) / FILE_STAT (0x11) / FILE_GET_* (0x12/13/14)
//   F-09  write: windowed FILE_PUT_* (0x15/16/41/17) + DELETE/MKDIR/RENAME
//   F-17  jail : pble_fs_resolve — the single, unbypassable vfs chokepoint (SEC-4)
//
// Reliability invariants (protocol.md §5 / FR-FS-9/14):
//   - Upload is temp-write-then-rename: PUT_BEGIN opens `<dest>.pbltmp` (truncated);
//     PUT_END verifies watermark==total_size + whole-file CRC, then fsync(close)+
//     rename(temp,dest) (atomic on LittleFS). On ANY failure the temp is deleted
//     and the OLD file is kept byte-for-byte — the live target is never partially
//     overwritten.
//   - Exactly one active transfer (PUT or GET). A second *_BEGIN while a PUT is
//     active → EBUSY.
//   - `.py`/data only: .mpy/.pyc are never accepted as transfer artifacts.
//   - Resume on reconnect (F-10): a link drop leaves `<dest>.pbltmp` + its on-flash
//     length on storage (pble_fs_on_disconnect only resets in-RAM state). A later
//     FILE_PUT_BEGIN for the same dest re-derives the verified prefix length from
//     flash (pble_fs_resume_prefix), re-seeds the running whole-file CRC over it,
//     and returns it as resume_offset so the app sends only the remaining bytes.
//     The whole-file CRC at PUT_END is the ONLY correctness gate (a bad/foreign
//     prefix → ECRC, old file kept). The running whole-file CRC is maintained
//     incrementally across PUT_DATA so PUT_END need not re-scan the temp
//     (NFR-PERF-2).
//
// Clean-room: authored fresh against protocol.md + the public MicroPython/ESP-IDF
// API. No proprietary source is referenced.
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"   // vTaskDelay (fs-worker TX pacing)

#include "py/mperrno.h"    // MP_ENOENT/EACCES/ENOSPC/EIO/ENOMEM/EEXIST/...
#include "py/mpstate.h"    // MP_STATE_VM (rooted PUT file object)
#include "py/mpthread.h"   // MP_THREAD_GIL_EXIT / _ENTER
#include "py/obj.h"        // mp_obj_*, mp_type_OSError
#include "py/runtime.h"    // nlr, mp_getiter/mp_iternext, mp_raise_OSError
#include "py/stream.h"     // mp_get_stream, mp_stream_close, mp_stream_p_t
#include "extmod/vfs.h"    // mp_vfs_*, MP_S_IFDIR

#include "pble_ble.h"      // pble_ble_mtu (chunk sizing)
#include "pble_fs.h"
#include "pble_proto.h"
#include "pble_vm_lifecycle.h"

// Error-path logging only (the build runs at ERROR log level): an undeliverable
// stream chunk is a genuine fault worth a console line. Never per-transfer
// chatter, never on the BLE console path.
#include "esp_log.h"
#define PBLE_FS_TAG "pble_fs"

// --- Frozen bounds (protocol.md §5) ------------------------------------------
#define PBLE_FS_ROOT        "/"     // fs_root (mirrors pble_info caps); LittleFS mount
#define PBLE_FS_PATH_MAX    128     // max path bytes on the wire (§5), else ERANGE
#define PBLE_FS_PATH_BUF    160     // resolved/temp/dest buffer (leading '/' + ".pbltmp")
#define PBLE_FS_TMP_SUFFIX  ".pbltmp"   // reserved transfer-scratch suffix (jailed)

// --- Internal design bounds (architect: queue depth = W+2, W=8 2026-07-04) ----
#define PBLE_FS_ITEM_PAYLOAD 248    // ≥ [offset:4] + max chunk (mtu-4 ≤ 243)
#define PBLE_FS_QDEPTH       10     // W + 2 unacknowledged PUT_DATA + control (W=PBLE_FS_PUT_WINDOW)
#define PBLE_FS_SCRATCH      512    // worker-only static TX/read buffer

// Keep the mailbox depth locked to the single-source window (pble_fs.h): a
// half-edit that bumps W without the queue re-opens the queue-full PUT_DATA drop
// that Go-Back-N then has to recover from (FR-FS-4). Compile-time, zero cost.
MP_STATIC_ASSERT(PBLE_FS_QDEPTH == PBLE_FS_PUT_WINDOW + 2);

// LittleFS returns ENOTEMPTY (39) for rmdir/rename over a non-empty dir; not a
// macro in py/mperrno.h, so name the numeric value locally (POSIX-standard).
#define PBLE_FS_ENOTEMPTY   39

// A mailbox request item (copied off the transient dispatch buffer by the host
// handler; consumed by value on the fs-worker).
typedef struct {
    uint8_t  opcode;
    uint8_t  id;
    pble_session_token_t session;
    uint64_t vm_epoch;
    pble_rsp_ticket_t ticket;
    uint16_t len;
    uint8_t  payload[PBLE_FS_ITEM_PAYLOAD];
} pble_fs_req_t;

typedef bool (*pble_fs_validator_t)(const pble_fs_req_t *it);

// --- Module state ------------------------------------------------------------
static QueueHandle_t g_fs_q;                 // bounded host→worker mailbox
static pble_fs_req_t g_enq;                  // host-task staging (single host task)
static uint8_t g_scratch[PBLE_FS_SCRATCH];   // worker-only (single-thread, no lock)
static SemaphoreHandle_t g_fs_gate;          // enqueue/dequeue/quiescence cut
static SemaphoreHandle_t g_fs_work;          // exact queued-work wake count
static bool g_fs_admission_open;
static bool g_fs_worker_busy;
static uint32_t g_fs_outstanding;
static bool g_fs_dequeue_claim;

// Worker-local single-active-transfer PUT state machine (§5 windowed upload).
static bool     g_put_active;
static char     g_put_temp[PBLE_FS_PATH_BUF];   // "<dest>.pbltmp"
static char     g_put_dest[PBLE_FS_PATH_BUF];   // final jailed destination
static uint32_t g_put_total;                     // declared total_size
static uint32_t g_put_crc_target;                // declared whole-file crc32
static uint32_t g_put_watermark;                 // highest contiguous byte written
static uint32_t g_put_crc_running;               // streaming whole-file CRC, PRE-final-xor
static uint8_t  g_put_latched;                   // 0, or a latched write status

// The open temp file object must survive GC across PUT_DATA calls → rooted.
MP_REGISTER_ROOT_POINTER(mp_obj_t pble_fs_put_file);

static bool pble_fs_item_valid(const pble_fs_req_t *it) {
    return it != NULL && pble_ble_session_live(&it->session) &&
           pble_vm_epoch_valid(it->vm_epoch);
}

static bool pble_fs_ticket_valid(const pble_fs_req_t *it) {
    return pble_fs_item_valid(it) &&
           pble_rsp_ticket_valid(&it->ticket);
}

// ============================================================================
// Little-endian helpers + incremental CRC-32 (bit-identical to pble_proto_crc32)
// ============================================================================
static void le32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}
static uint32_t rd32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static uint16_t rd16(const uint8_t *p) {
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

// Reflected poly 0xEDB88320, init/xorout 0xFFFFFFFF (zlib) — the SAME algorithm as
// pble_proto_crc32, but streaming so a whole file need not be buffered. Feed with
// `crc = 0xFFFFFFFF`, then finalize `crc ^ 0xFFFFFFFF`.
static uint32_t crc32_update(uint32_t crc, const uint8_t *d, size_t n) {
    for (size_t i = 0; i < n; i++) {
        crc ^= d[i];
        for (int k = 0; k < 8; k++) {
            crc = (crc & 1u) ? ((crc >> 1) ^ 0xEDB88320u) : (crc >> 1);
        }
    }
    return crc;
}

// ============================================================================
// Error mapping (FR-FS-15)
// ============================================================================
uint8_t pble_fs_errno_to_status(int e) {
    switch (e) {
        case MP_ENOENT:
        case MP_ENOTDIR:        return PBLE_ENOENT;
        case MP_EACCES:
        case MP_EPERM:
        case MP_EROFS:
        case MP_EISDIR:
        case PBLE_FS_ENOTEMPTY: return PBLE_EACCES;   // incl. non-empty-dir delete/rename
        case MP_ENOSPC:         return PBLE_ENOSPC;
        case MP_ENOMEM:         return PBLE_ENOMEM;
        case MP_EINVAL:
        case MP_ERANGE:         return PBLE_ERANGE;
        case MP_EEXIST:         return PBLE_EBADREQ;
        case MP_EIO:            return PBLE_EIO;
        default:                return PBLE_EIO;       // unclassified vfs error
    }
}

// A caught nlr value (an exception instance) → §8 status. An OSError carries its
// errno as the exception value; anything else (or a non-int value) → EINTERNAL.
static uint8_t fs_exc_to_status(mp_obj_t exc) {
    if (mp_obj_is_exception_instance(exc)) {
        mp_int_t e;
        mp_obj_t v = mp_obj_exception_get_value(exc);
        if (mp_obj_get_int_maybe(v, &e)) {
            return pble_fs_errno_to_status((int)e);
        }
    }
    return PBLE_EINTERNAL;
}

// ============================================================================
// pble_fs_resolve — the single jail chokepoint (F-17 / SEC-4)
// ============================================================================
// A reserved agent-module prefix on the TOP-LEVEL component → forbidden. The
// agent (Layer 3 `pyble_*`/`pble_*`) and its boot scaffold are firmware-EMBEDDED
// (ADR-0006), not vfs paths — this is defense-in-depth so the control plane can
// never be shadowed/replaced via PBLE/1 (FR-FS-11 / CON-10 / SEC-4).
static bool fs_reserved_prefix(const char *c) {
    return strncmp(c, "pyble", 5) == 0 ||
           strncmp(c, "pble", 4) == 0 ||
           strcmp(c, "_boot.py") == 0 ||
           strcmp(c, "boot.py") == 0;
}

// True if `name` ends with the reserved ".pbltmp" transfer-scratch suffix.
static bool fs_has_tmp_suffix(const char *name) {
    size_t nl = strlen(name);
    size_t sl = sizeof(PBLE_FS_TMP_SUFFIX) - 1;
    return nl >= sl && strcmp(name + nl - sl, PBLE_FS_TMP_SUFFIX) == 0;
}

uint8_t pble_fs_resolve(const char *in, size_t inlen, char *out, size_t outcap) {
    if (in == NULL || inlen == 0) {
        return PBLE_EBADREQ;
    }
    if (inlen > PBLE_FS_PATH_MAX) {
        return PBLE_ERANGE;
    }
    for (size_t i = 0; i < inlen; i++) {
        if (in[i] == '\0') {
            return PBLE_EBADREQ;   // embedded NUL — reject NUL injection
        }
    }

    // Mutable NUL-terminated copy for tokenization.
    char buf[PBLE_FS_PATH_MAX + 1];
    memcpy(buf, in, inlen);
    buf[inlen] = '\0';

    // Canonicalize: split on '/', drop '.'/empty, pop on '..' (never above root).
    // A '..' that would pop past the root is an escape attempt → EACCES.
    const char *parts[(PBLE_FS_PATH_MAX / 2) + 2];
    int np = 0;
    char *save = NULL;
    for (char *tok = strtok_r(buf, "/", &save); tok != NULL;
         tok = strtok_r(NULL, "/", &save)) {
        if (strcmp(tok, ".") == 0) {
            continue;
        }
        if (strcmp(tok, "..") == 0) {
            if (np == 0) {
                return PBLE_EACCES;    // traversal escape outside fs_root
            }
            np--;
            continue;
        }
        if (fs_has_tmp_suffix(tok)) {
            return PBLE_EACCES;        // reserved transfer-scratch suffix
        }
        parts[np++] = tok;
    }
    if (np > 0 && fs_reserved_prefix(parts[0])) {
        return PBLE_EACCES;            // reserved agent-module prefix
    }

    // Join into an absolute path rooted at fs_root ("/"). np==0 → "/".
    size_t o = 0;
    if (o + 1 >= outcap) {
        return PBLE_ERANGE;
    }
    out[o++] = '/';
    for (int i = 0; i < np; i++) {
        if (i > 0) {
            if (o + 1 >= outcap) {
                return PBLE_ERANGE;
            }
            out[o++] = '/';
        }
        size_t l = strlen(parts[i]);
        if (o + l + 1 > outcap) {
            return PBLE_ERANGE;
        }
        memcpy(out + o, parts[i], l);
        o += l;
    }
    out[o] = '\0';
    return PBLE_OK;
}

// Reject .mpy/.pyc as transfer artifacts (.py/data only — FR-FS-12 / CON-3).
static bool fs_is_forbidden_artifact(const char *path) {
    size_t l = strlen(path);
    return (l >= 4 && strcmp(path + l - 4, ".mpy") == 0) ||
           (l >= 4 && strcmp(path + l - 4, ".pyc") == 0);
}

// ============================================================================
// Small MP-object helpers (all invoked on the worker under the caller's nlr)
// ============================================================================
static mp_obj_t fs_str(const char *s) {
    return mp_obj_new_str(s, strlen(s));
}

// Open a jailed path via the VFS with the given mode ("rb"/"wb"). Raises on error.
static mp_obj_t fs_open(const pble_fs_req_t *it,
                        pble_fs_validator_t validator,
                        const char *path, const char *mode) {
    mp_obj_t args[2] = { fs_str(path), fs_str(mode) };
    mp_map_t kw;
    mp_map_init(&kw, 0);
    if (!validator(it)) {
        return MP_OBJ_NULL;
    }
    mp_obj_t opened = mp_vfs_open(2, args, &kw);
    if (!validator(it)) {
        return MP_OBJ_NULL;
    }
    return opened;
}

static uint32_t fs_chunk(void) {
    unsigned mtu = pble_ble_mtu();
    // caps chunk_size = mtu − PBLE_CHUNK_OVERHEAD: one data chunk == ONE §3.2
    // notify packet (the frozen single-packet stream invariant; mtu − 4 here
    // was the 11.9 kB-download-stall bug — 14 bytes of framing overshoot made
    // every GET_DATA a 2-packet message, voiding the clean-retry contract).
    uint32_t c = (mtu > PBLE_CHUNK_OVERHEAD) ? (mtu - PBLE_CHUNK_OVERHEAD) : 20;
    if (c > PBLE_FS_SCRATCH - 4) {
        c = PBLE_FS_SCRATCH - 4;                     // reserve room for [offset:4]
    }
    if (c == 0) {
        c = 20;
    }
    return c;
}

// mp_vfs_stat under its own nlr → size + is-dir. Returns §8 status.
static uint8_t fs_stat_path(const pble_fs_req_t *it, const char *path,
                            uint32_t *size, bool *isdir) {
    nlr_buf_t nlr;
    uint8_t st;
    if (nlr_push(&nlr) == 0) {
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        mp_obj_t r = mp_vfs_stat(fs_str(path));
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        mp_obj_t *f;
        size_t n;
        mp_obj_get_array(r, &n, &f);
        mp_int_t mode = (n > 0) ? mp_obj_get_int(f[0]) : 0;
        *size = (n > 6) ? (uint32_t)mp_obj_get_int(f[6]) : 0;
        *isdir = (mode & MP_S_IFDIR) ? true : false;
        nlr_pop();
        st = PBLE_OK;
    } else {
        st = fs_exc_to_status(MP_OBJ_FROM_PTR(nlr.ret_val));
    }
    return st;
}

// Whole-file CRC-32 over [0, size). Opens "rb", streams into g_scratch, always
// closes. Returns §8 status; *out set on OK.
static uint8_t fs_crc_file(const pble_fs_req_t *it, const char *path,
                           uint32_t *out) {
    nlr_buf_t nlr;
    uint8_t st;
    volatile mp_obj_t f = MP_OBJ_NULL;
    if (nlr_push(&nlr) == 0) {
        f = fs_open(it, pble_fs_ticket_valid, path, "rb");
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        const mp_stream_p_t *sp = mp_get_stream((mp_obj_t)f);
        uint32_t crc = 0xFFFFFFFFu;
        for (;;) {
            int err;
            if (!pble_fs_ticket_valid(it)) {
                nlr_pop();
                return PBLE_NO_RSP;
            }
            mp_uint_t n = sp->read((mp_obj_t)f, g_scratch, PBLE_FS_SCRATCH, &err);
            if (!pble_fs_ticket_valid(it)) {
                nlr_pop();
                return PBLE_NO_RSP;
            }
            if (n == MP_STREAM_ERROR) {
                mp_raise_OSError(err);
            }
            if (n == 0) {
                break;
            }
            crc = crc32_update(crc, g_scratch, n);
        }
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        mp_stream_close((mp_obj_t)f);
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        f = MP_OBJ_NULL;
        *out = crc ^ 0xFFFFFFFFu;
        nlr_pop();
        st = PBLE_OK;
    } else {
        if (f != MP_OBJ_NULL) {
            nlr_buf_t n2;
            if (nlr_push(&n2) == 0) {
                if (!pble_fs_ticket_valid(it)) {
                    nlr_pop();
                    return PBLE_NO_RSP;
                }
                mp_stream_close((mp_obj_t)f);
                if (!pble_fs_ticket_valid(it)) {
                    nlr_pop();
                    return PBLE_NO_RSP;
                }
                nlr_pop();
            }
        }
        st = fs_exc_to_status(MP_OBJ_FROM_PTR(nlr.ret_val));
    }
    return st;
}

// Running (PRE-final-xor) CRC-32 over `temp[0, len)`, for re-seeding the streaming
// whole-file CRC on a resume (F-10). Opens "rb", streams up to `len` bytes into
// g_scratch, always closes. Returns §8 status; *running set (feed 0xFFFFFFFF form)
// on OK — the caller continues it with crc32_update and finalizes `^ 0xFFFFFFFF`.
static uint8_t fs_crc_prefix(const pble_fs_req_t *it, const char *path,
                             uint32_t len, uint32_t *running) {
    nlr_buf_t nlr;
    uint8_t st;
    volatile mp_obj_t f = MP_OBJ_NULL;
    if (nlr_push(&nlr) == 0) {
        f = fs_open(it, pble_fs_ticket_valid, path, "rb");
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        const mp_stream_p_t *sp = mp_get_stream((mp_obj_t)f);
        uint32_t crc = 0xFFFFFFFFu;
        uint32_t remaining = len;
        while (remaining > 0) {
            uint32_t want = (remaining < PBLE_FS_SCRATCH) ? remaining : PBLE_FS_SCRATCH;
            int err;
            if (!pble_fs_ticket_valid(it)) {
                nlr_pop();
                return PBLE_NO_RSP;
            }
            mp_uint_t n = sp->read((mp_obj_t)f, g_scratch, want, &err);
            if (!pble_fs_ticket_valid(it)) {
                nlr_pop();
                return PBLE_NO_RSP;
            }
            if (n == MP_STREAM_ERROR) {
                mp_raise_OSError(err);
            }
            if (n == 0) {
                break;                // temp shorter than stat → CRC what exists
            }
            crc = crc32_update(crc, g_scratch, n);
            remaining -= (uint32_t)n;
        }
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        mp_stream_close((mp_obj_t)f);
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        f = MP_OBJ_NULL;
        *running = crc;               // NOT finalized — continued by PUT_DATA
        nlr_pop();
        st = PBLE_OK;
    } else {
        if (f != MP_OBJ_NULL) {
            nlr_buf_t n2;
            if (nlr_push(&n2) == 0) {
                if (!pble_fs_ticket_valid(it)) {
                    nlr_pop();
                    return PBLE_NO_RSP;
                }
                mp_stream_close((mp_obj_t)f);
                if (!pble_fs_ticket_valid(it)) {
                    nlr_pop();
                    return PBLE_NO_RSP;
                }
                nlr_pop();
            }
        }
        st = fs_exc_to_status(MP_OBJ_FROM_PTR(nlr.ret_val));
    }
    return st;
}

// ============================================================================
// Worker op: FILE_LIST (0x10)
// ============================================================================
// RSP payload (after status) = [more:u8][count:u16] + count× {etype:u8, esize:u32,
// nlen:u16, name}. Truncated to the worker RSP buffer → more=1. esize comes from a
// per-entry stat (LittleFS ilistdir yields no size); best-effort (0 on failure).
static uint8_t fs_do_list(const pble_fs_req_t *it, size_t *extra) {
    *extra = 0;
    if (it->len < 2) {
        return PBLE_EBADREQ;
    }
    uint16_t plen = rd16(it->payload);
    if ((size_t)plen + 2 > it->len) {
        return PBLE_EBADREQ;
    }
    char path[PBLE_FS_PATH_BUF];
    uint8_t rc = pble_fs_resolve((const char *)it->payload + 2, plen, path, sizeof(path));
    if (rc != PBLE_OK) {
        return rc;
    }

    nlr_buf_t nlr;
    uint8_t st;
    if (nlr_push(&nlr) == 0) {
        mp_obj_t args1[1] = { fs_str(path) };
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        mp_obj_t iter = mp_vfs_ilistdir(1, args1);
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        mp_obj_iter_buf_t ibuf;
        mp_obj_t iterable = mp_getiter(iter, &ibuf);

        size_t o = 1 + 3;          // reserve g_scratch[0]=status, [1]=more, [2..3]=count
        uint16_t count = 0;
        uint8_t more = 0;
        mp_obj_t item;
        for (;;) {
            if (!pble_fs_ticket_valid(it)) {
                nlr_pop();
                return PBLE_NO_RSP;
            }
            item = mp_iternext(iterable);
            if (!pble_fs_ticket_valid(it)) {
                nlr_pop();
                return PBLE_NO_RSP;
            }
            if (item == MP_OBJ_STOP_ITERATION) {
                break;
            }
            mp_obj_t *fld;
            size_t nf;
            mp_obj_get_array(item, &nf, &fld);
            size_t nlen;
            const char *name = mp_obj_str_get_data(fld[0], &nlen);
            mp_int_t type = (nf > 1) ? mp_obj_get_int(fld[1]) : 0;
            uint8_t etype = (type & MP_S_IFDIR) ? 1 : 0;

            size_t need = 1 + 4 + 2 + nlen;
            if (o + need > PBLE_RSP_MAX) {
                more = 1;          // does not fit the worker buffer → truncate
                break;
            }

            uint32_t esize = 0;
            if (etype == 0) {      // best-effort size for files
                char child[PBLE_FS_PATH_BUF];
                size_t pl = strlen(path);
                size_t cl = 0;
                memcpy(child, path, pl);
                cl = pl;
                if (!(pl == 1 && path[0] == '/')) {
                    child[cl++] = '/';
                }
                if (cl + nlen + 1 <= sizeof(child)) {
                    memcpy(child + cl, name, nlen);
                    cl += nlen;
                    child[cl] = '\0';
                    uint32_t sz;
                    bool d;
                    uint8_t child_st = fs_stat_path(it, child, &sz, &d);
                    if (child_st == PBLE_NO_RSP) {
                        nlr_pop();
                        return PBLE_NO_RSP;
                    }
                    if (child_st == PBLE_OK) {
                        esize = sz;
                    }
                }
            }

            g_scratch[o++] = etype;
            le32(g_scratch + o, esize);
            o += 4;
            g_scratch[o] = (uint8_t)(nlen & 0xFF);
            g_scratch[o + 1] = (uint8_t)((nlen >> 8) & 0xFF);
            o += 2;
            memcpy(g_scratch + o, name, nlen);
            o += nlen;
            count++;
        }
        g_scratch[1] = more;
        g_scratch[2] = (uint8_t)(count & 0xFF);
        g_scratch[3] = (uint8_t)((count >> 8) & 0xFF);
        *extra = o - 1;
        nlr_pop();
        st = PBLE_OK;
    } else {
        st = fs_exc_to_status(MP_OBJ_FROM_PTR(nlr.ret_val));
    }
    return st;
}

// ============================================================================
// Worker op: FILE_STAT (0x11) → [size:u32][crc32:u32]; ENOENT on missing.
// ============================================================================
static uint8_t fs_do_stat(const pble_fs_req_t *it, size_t *extra) {
    *extra = 0;
    if (it->len < 2) {
        return PBLE_EBADREQ;
    }
    uint16_t plen = rd16(it->payload);
    if ((size_t)plen + 2 > it->len) {
        return PBLE_EBADREQ;
    }
    char path[PBLE_FS_PATH_BUF];
    uint8_t rc = pble_fs_resolve((const char *)it->payload + 2, plen, path, sizeof(path));
    if (rc != PBLE_OK) {
        return rc;
    }
    uint32_t size;
    bool isdir;
    uint8_t st = fs_stat_path(it, path, &size, &isdir);
    if (st != PBLE_OK) {
        return st;      // ENOENT for a missing path (FR-FS-2)
    }
    uint32_t crc = 0;
    if (!isdir) {
        st = fs_crc_file(it, path, &crc);
        if (st != PBLE_OK) {
            return st;
        }
    }
    le32(g_scratch + 1, size);
    le32(g_scratch + 5, crc);
    *extra = 8;
    return PBLE_OK;
}

// --- fs-worker paced TX (NFR-REL) --------------------------------------------
// A streamed GET blasts dozens of notifications; NimBLE's msys pool drains
// mid-burst and TX reports PBLE_TX_AGAIN. Ignoring that return silently DROPS
// the chunk (the 11.9 kB open-from-board hang); a timed sleep-retry busy-spins
// at a coarse tick (pdMS_TO_TICKS(5) == 0 at 100 Hz) and re-consumes the pool.
// The fix is EVENT-DRIVEN: pble_proto_emit_paced parks the fs-worker on the
// NOTIFY_TX drain event and resends only the not-yet-sent packet, bounded by a
// per-message budget. Runs ONLY on the fs-worker, never the host task.
#define FS_TX_BUDGET_MS 2000u

static int fs_emit_paced(const pble_fs_req_t *it, uint8_t opcode,
                         const uint8_t *payload, size_t len) {
    if (!pble_fs_item_valid(it)) {
        return PBLE_TX_NO_CONN;
    }
    int rc = pble_proto_emit_paced_for_session(opcode, payload, len,
                                               FS_TX_BUDGET_MS, &it->session);
    if (rc != PBLE_TX_OK) {
        // A stream chunk undeliverable within its budget (link gone or
        // pathologically congested) — the transfer aborts; the app's stall
        // watchdog surfaces a typed timeout.
        ESP_LOGE(PBLE_FS_TAG, "emit op=0x%02x len=%u rc=%d", opcode,
                 (unsigned)len, rc);
    }
    return rc;
}

// ============================================================================
// Worker op: FILE_GET_BEGIN (0x12) — emits its OWN RSP + DATA/END events.
// ============================================================================
// [offset:u32][plen:u16][path] → RSP [status](+[total_size:u32]); on OK streams
// FILE_GET_DATA (0x13, EVT) [offset:u32][bytes] chunks then FILE_GET_END (0x14,
// EVT) [crc32:u32] over the WHOLE file (a skipped prefix is CRC'd too). Returns
// PBLE_NO_RSP once it has emitted its RSP; an early failure returns a status for
// the dispatcher to reply.
static uint8_t fs_do_get(const pble_fs_req_t *it) {
    if (it->len < 6) {
        return PBLE_EBADREQ;
    }
    uint32_t offset = rd32(it->payload);
    uint16_t plen = rd16(it->payload + 4);
    if ((size_t)plen + 6 > it->len) {
        return PBLE_EBADREQ;
    }
    char path[PBLE_FS_PATH_BUF];
    uint8_t rc = pble_fs_resolve((const char *)it->payload + 6, plen, path, sizeof(path));
    if (rc != PBLE_OK) {
        return rc;
    }
    if (g_put_active) {
        return PBLE_EBUSY;            // single active transfer
    }

    uint32_t total;
    bool isdir;
    if (!pble_rsp_ticket_valid(&it->ticket) || !pble_fs_ticket_valid(it)) {
        return PBLE_NO_RSP;
    }
    uint8_t st = fs_stat_path(it, path, &total, &isdir);
    if (!pble_rsp_ticket_valid(&it->ticket) || !pble_fs_ticket_valid(it)) {
        return PBLE_NO_RSP;
    }
    if (st != PBLE_OK) {
        return st;                    // ENOENT
    }
    if (isdir) {
        return PBLE_EACCES;           // cannot GET a directory
    }
    if (offset > total) {
        return PBLE_ERANGE;
    }

    // RSP{OK}[total_size:u32] must fully complete before dependent events.
    g_scratch[0] = PBLE_OK;
    le32(g_scratch + 1, total);
    if (!pble_rsp_expect_completion(&it->ticket)) {
        return PBLE_NO_RSP;
    }
    if (!pble_rsp_publish(&it->ticket, PBLE_OP_FILE_GET_BEGIN, it->id,
                          g_scratch, 5)) {
        pble_rsp_cancel_ticket(&it->ticket);
    }
    MP_THREAD_GIL_EXIT();
    bool rsp_delivered = pble_rsp_wait(&it->ticket);
    MP_THREAD_GIL_ENTER();
    if (!rsp_delivered || !pble_fs_item_valid(it)) {
        return PBLE_NO_RSP;
    }

    uint32_t chunk = fs_chunk();
    uint32_t crc = 0xFFFFFFFFu;
    nlr_buf_t nlr;
    volatile mp_obj_t f = MP_OBJ_NULL;
    volatile int tx_dead = 0;   // link gone / backpressure budget exhausted
    if (nlr_push(&nlr) == 0) {
        if (!pble_fs_item_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        f = fs_open(it, pble_fs_item_valid, path, "rb");
        if (!pble_fs_item_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        const mp_stream_p_t *sp = mp_get_stream((mp_obj_t)f);
        uint32_t pos = 0;
        for (;;) {
            if (!pble_fs_item_valid(it)) {
                tx_dead = 1;
                break;
            }
            int err;
            // Read into g_scratch+4 so a [offset:u32] header can sit contiguously
            // in front of the emitted slice.
            if (!pble_fs_item_valid(it)) {
                nlr_pop();
                return PBLE_NO_RSP;
            }
            mp_uint_t n = sp->read((mp_obj_t)f, g_scratch + 4, chunk, &err);
            if (!pble_fs_item_valid(it)) {
                nlr_pop();
                return PBLE_NO_RSP;
            }
            if (n == MP_STREAM_ERROR) {
                mp_raise_OSError(err);
            }
            if (n == 0) {
                break;
            }
            crc = crc32_update(crc, g_scratch + 4, n);   // whole-file CRC (from 0)
            uint32_t blk_end = pos + (uint32_t)n;
            if (blk_end > offset) {                       // emit only bytes ≥ offset
                uint32_t from = (pos > offset) ? pos : offset;
                uint32_t elen = blk_end - from;
                uint8_t *dp = g_scratch + 4 + (from - pos);
                le32(dp - 4, from);
                // Paced + CHECKED: a chunk that cannot be sent aborts the
                // stream — never silently dropped (the app's stall watchdog
                // then surfaces a typed timeout instead of hanging).
                if (!pble_fs_item_valid(it)) {
                    nlr_pop();
                    return PBLE_NO_RSP;
                }
                int emit_rc = fs_emit_paced(it, PBLE_OP_FILE_GET_DATA, dp - 4,
                                            (size_t)(4 + elen));
                if (!pble_fs_item_valid(it)) {
                    nlr_pop();
                    return PBLE_NO_RSP;
                }
                if (emit_rc != PBLE_TX_OK) {
                    tx_dead = 1;
                    break;
                }
            }
            pos = blk_end;
        }
        if (!pble_fs_item_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        mp_stream_close((mp_obj_t)f);
        if (!pble_fs_item_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        f = MP_OBJ_NULL;
        nlr_pop();
    } else {
        if (f != MP_OBJ_NULL) {
            nlr_buf_t n2;
            if (nlr_push(&n2) == 0) {
                if (!pble_fs_item_valid(it)) {
                    nlr_pop();
                    return PBLE_NO_RSP;
                }
                mp_stream_close((mp_obj_t)f);
                if (!pble_fs_item_valid(it)) {
                    nlr_pop();
                    return PBLE_NO_RSP;
                }
                nlr_pop();
            }
        }
        // RSP{OK} already went out; a mid-stream fault cannot retract it. Emit END
        // with the partial CRC so the app detects the mismatch (HIL-verified).
    }
    if (!tx_dead && pble_fs_item_valid(it)) {
        uint32_t fcrc = crc ^ 0xFFFFFFFFu;
        le32(g_scratch, fcrc);
        if (!pble_fs_item_valid(it)) {
            return PBLE_NO_RSP;
        }
        (void)fs_emit_paced(it, PBLE_OP_FILE_GET_END, g_scratch, 4);
        if (!pble_fs_item_valid(it)) {
            return PBLE_NO_RSP;
        }
    }
    // tx_dead: the link is gone or saturated beyond the retry budget — an END
    // cannot usefully be delivered; the app recovers via its data timeout.
    return PBLE_NO_RSP;
}

// ============================================================================
// Worker op: windowed upload PUT_BEGIN/DATA/END (0x15/0x16/0x41/0x17)
// ============================================================================
static void fs_put_ack(const pble_fs_req_t *it) {
    if (!pble_fs_item_valid(it)) {
        return;
    }
    uint8_t b[4];
    le32(b, g_put_watermark);        // ack_offset = next expected = highest contiguous
    // Paced: a dropped ACK stalls the (client-paced) upload for a full client
    // timeout; under backpressure wait for the pool rather than dropping.
    (void)fs_emit_paced(it, PBLE_OP_FILE_PUT_ACK, b, 4);
}

static void fs_put_close(const pble_fs_req_t *it) {
    mp_obj_t f = MP_STATE_VM(pble_fs_put_file);
    if (f != MP_OBJ_NULL) {
        nlr_buf_t nlr;
        if (nlr_push(&nlr) == 0) {
            if (!pble_fs_ticket_valid(it)) {
                nlr_pop();
                return;
            }
            mp_stream_close(f);
            if (!pble_fs_ticket_valid(it)) {
                nlr_pop();
                return;
            }
            nlr_pop();
        }
        MP_STATE_VM(pble_fs_put_file) = MP_OBJ_NULL;
    }
}

static void fs_put_reset(void) {
    g_put_active = false;
    g_put_temp[0] = '\0';
    g_put_dest[0] = '\0';
    g_put_total = g_put_crc_target = g_put_watermark = 0;
    g_put_crc_running = 0xFFFFFFFFu;
    g_put_latched = 0;
}

// F-10 link-drop hook — see pble_fs.h. HOST-TASK SAFE: plain C state only, so the
// NimBLE disconnect callback can call it directly. It intentionally does NOT close
// or delete the temp: `<dest>.pbltmp` and its on-flash length persist as the
// durable watermark a resuming FILE_PUT_BEGIN re-derives. Any file object left
// open by the interrupted transfer is flushed + closed later, on the worker, by
// that next FILE_PUT_BEGIN (fs_put_close there) — never from this host-task hook.
// Idempotent.
void pble_fs_on_disconnect(void) {
    fs_put_reset();
}

// F-10 resume-offset — see pble_fs.h. WORKER-ONLY (mp_vfs_* under nlr). Always
// (re)initializes the worker-local running whole-file CRC + watermark.
static uint32_t pble_fs_resume_prefix(const pble_fs_req_t *it,
                                      const char *dest_vfs_path,
                                      uint32_t total_size) {
    g_put_watermark = 0;
    g_put_crc_running = 0xFFFFFFFFu;      // fresh-upload default

    // Build "<dest>.pbltmp" (same jailed sibling the transfer writes).
    char temp[PBLE_FS_PATH_BUF];
    size_t dl = strlen(dest_vfs_path);
    if (dl + (sizeof(PBLE_FS_TMP_SUFFIX) - 1) + 1 > sizeof(temp)) {
        return 0;
    }
    memcpy(temp, dest_vfs_path, dl);
    memcpy(temp + dl, PBLE_FS_TMP_SUFFIX, sizeof(PBLE_FS_TMP_SUFFIX));  // incl NUL

    uint32_t len;
    bool isdir;
    if (fs_stat_path(it, temp, &len, &isdir) != PBLE_OK) {
        return 0;                        // no temp / unreadable → fresh
    }
    if (isdir || len == 0 || len > total_size) {
        return 0;                        // nothing to resume / over-size guard →
                                         // caller's "wb" open truncates to 0
    }
    uint32_t running;
    if (fs_crc_prefix(it, temp, len, &running) != PBLE_OK) {
        return 0;                        // unreadable prefix → fresh (wb truncates)
    }
    g_put_crc_running = running;          // re-seed the streaming whole-file CRC
    g_put_watermark = len;               // durable prefix re-derived from flash
    return len;
}

// Abort a transfer: close the temp, delete it (KEEP the old target), reset state.
static void fs_put_abort(const pble_fs_req_t *it) {
    fs_put_close(it);
    if (g_put_temp[0] != '\0') {
        nlr_buf_t nlr;
        if (nlr_push(&nlr) == 0) {
            if (!pble_fs_ticket_valid(it)) {
                nlr_pop();
                fs_put_reset();
                return;
            }
            mp_vfs_remove(fs_str(g_put_temp));
            if (!pble_fs_ticket_valid(it)) {
                nlr_pop();
                fs_put_reset();
                return;
            }
            nlr_pop();
        }
    }
    fs_put_reset();
}

static uint8_t fs_do_put_begin(const pble_fs_req_t *it, size_t *extra) {
    *extra = 0;
    // [total_size:u32][crc32:u32][plen:u16][path]
    if (it->len < 10) {
        return PBLE_EBADREQ;
    }
    uint32_t total = rd32(it->payload);
    uint32_t crc = rd32(it->payload + 4);
    uint16_t plen = rd16(it->payload + 8);
    if ((size_t)plen + 10 > it->len) {
        return PBLE_EBADREQ;
    }
    char dest[PBLE_FS_PATH_BUF];
    uint8_t rc = pble_fs_resolve((const char *)it->payload + 10, plen, dest, sizeof(dest));
    if (rc != PBLE_OK) {
        return rc;
    }
    if (fs_is_forbidden_artifact(dest)) {
        return PBLE_EACCES;          // .mpy/.pyc never accepted (FR-FS-12)
    }
    if (g_put_active) {
        return PBLE_EBUSY;           // single active transfer (§5)
    }
    // Flush + close any file object orphaned by a prior link-dropped transfer
    // (pble_fs_on_disconnect resets the flags on the host task but cannot touch
    // MP objects). This is worker-side + VM-safe and syncs the last buffered block
    // to flash so resume_prefix below sees the full verified prefix length (F-10).
    fs_put_close(it);
    if (!pble_fs_ticket_valid(it)) {
        return PBLE_NO_RSP;
    }

    // temp = "<dest>.pbltmp" (same jailed directory; never routed through resolve,
    // which forbids the reserved suffix by design).
    size_t dl = strlen(dest);
    if (dl + (sizeof(PBLE_FS_TMP_SUFFIX) - 1) + 1 > sizeof(g_put_temp)) {
        return PBLE_ERANGE;
    }
    memcpy(g_put_dest, dest, dl + 1);
    memcpy(g_put_temp, dest, dl);
    memcpy(g_put_temp + dl, PBLE_FS_TMP_SUFFIX, sizeof(PBLE_FS_TMP_SUFFIX));  // incl NUL

    // Resume-on-reconnect (F-10): re-derive any verified prefix from flash. This
    // sets g_put_watermark + re-seeds g_put_crc_running (or leaves them fresh).
    // resume>0 → append to the existing prefix; resume==0 → "wb" truncates any
    // stale/over-size temp to 0 (the frozen over-size guard).
    uint32_t resume = pble_fs_resume_prefix(it, g_put_dest, total);
    if (!pble_fs_ticket_valid(it)) {
        return PBLE_NO_RSP;
    }
    const char *mode = (resume > 0) ? "ab" : "wb";

    // Open the temp under nlr.
    nlr_buf_t nlr;
    uint8_t st;
    if (nlr_push(&nlr) == 0) {
        mp_obj_t f = fs_open(it, pble_fs_ticket_valid, g_put_temp, mode);
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        MP_STATE_VM(pble_fs_put_file) = f;
        nlr_pop();
        st = PBLE_OK;
    } else {
        st = fs_exc_to_status(MP_OBJ_FROM_PTR(nlr.ret_val));
    }
    if (st != PBLE_OK) {
        fs_put_reset();              // clears watermark/CRC; temp persists on flash
        return st;
    }

    g_put_active = true;
    g_put_total = total;
    g_put_crc_target = crc;
    g_put_latched = 0;
    // g_put_watermark + g_put_crc_running were set by pble_fs_resume_prefix.

    le32(g_scratch + 1, resume);    // resume_offset = verified prefix length (§5)
    *extra = 4;
    return PBLE_OK;
}

// PUT_DATA: [offset:u32][bytes]. Go-Back-N, no reorder buffer. Always re-ACKs the
// current watermark; emits no RSP.
static void fs_do_put_data(const pble_fs_req_t *it) {
    if (!g_put_active) {
        return;                      // no transfer → nothing to ack
    }
    if (it->len < 4) {
        fs_put_ack(it);              // malformed → re-ack (idempotent)
        return;
    }
    uint32_t offset = rd32(it->payload);
    const uint8_t *bytes = it->payload + 4;
    uint32_t n = it->len - 4;

    if (g_put_latched) {
        fs_put_ack(it);              // latched write error → keep acking; END reports
        return;
    }
    if (offset == g_put_watermark && n > 0) {
        nlr_buf_t nlr;
        if (nlr_push(&nlr) == 0) {
            mp_obj_t f = MP_STATE_VM(pble_fs_put_file);
            const mp_stream_p_t *sp = mp_get_stream(f);
            uint32_t done = 0;
            while (done < n) {
                int err;
                if (!pble_fs_item_valid(it)) {
                    nlr_pop();
                    return;
                }
                mp_uint_t w = sp->write(f, bytes + done, n - done, &err);
                if (!pble_fs_item_valid(it)) {
                    nlr_pop();
                    return;
                }
                if (w == MP_STREAM_ERROR) {
                    g_put_latched = pble_fs_errno_to_status(err);
                    break;
                }
                done += (uint32_t)w;
            }
            if (!g_put_latched) {
                // Advance + extend the streaming whole-file CRC together, only on a
                // full contiguous write, so the running CRC stays in lockstep with
                // the watermark (Go-Back-N never double-counts a dup/gap).
                g_put_crc_running = crc32_update(g_put_crc_running, bytes, n);
                g_put_watermark += n;
            }
            nlr_pop();
        } else {
            g_put_latched = fs_exc_to_status(MP_OBJ_FROM_PTR(nlr.ret_val));
        }
    }
    // offset < watermark (duplicate) and offset > watermark (gap) both re-ACK the
    // watermark so the app retransmits from there (Go-Back-N).
    fs_put_ack(it);
}

// PUT_END: [crc32:u32] → RSP [status]. Verify watermark==total + whole-file CRC,
// then fsync(close)+rename. On ANY failure delete temp + KEEP old file (FR-FS-14).
static uint8_t fs_do_put_end(const pble_fs_req_t *it, size_t *extra) {
    *extra = 0;
    if (!g_put_active) {
        return PBLE_EBADREQ;         // END without an active BEGIN
    }
    if (it->len < 4) {
        fs_put_abort(it);
        return PBLE_EBADREQ;
    }
    uint32_t declared = rd32(it->payload);

    if (g_put_latched) {
        uint8_t st = g_put_latched;  // ENOSPC / EIO latched during DATA
        fs_put_abort(it);
        return st;
    }
    if (g_put_watermark != g_put_total) {
        fs_put_abort(it);
        return PBLE_ERANGE;          // short/over transfer
    }

    fs_put_close(it);                // flush the temp to storage
    if (!pble_fs_ticket_valid(it)) {
        return PBLE_NO_RSP;
    }

    // Finalize the streaming whole-file CRC (maintained across PUT_DATA + re-seeded
    // over any resumed prefix by pble_fs_resume_prefix) — no temp re-scan needed
    // (NFR-PERF-2). The whole-file CRC is the ONLY correctness gate, so a resumed
    // bad/foreign prefix fails here → ECRC, temp deleted, old file kept (FR-FS-14).
    uint32_t crc = g_put_crc_running ^ 0xFFFFFFFFu;
    uint8_t st;
    if (crc != g_put_crc_target || crc != declared) {
        fs_put_abort(it);
        return PBLE_ECRC;            // mismatch → target untouched (FR-FS-14)
    }

    // Atomic replace on LittleFS.
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        mp_vfs_rename(fs_str(g_put_temp), fs_str(g_put_dest));
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        nlr_pop();
        st = PBLE_OK;
    } else {
        st = fs_exc_to_status(MP_OBJ_FROM_PTR(nlr.ret_val));
    }
    if (st != PBLE_OK) {
        fs_put_abort(it);
        return st;
    }
    fs_put_reset();                  // temp is gone (renamed) — clear, do not delete
    return PBLE_OK;
}

// ============================================================================
// Worker op: DELETE (0x18) / MKDIR (0x19) / RENAME (0x1A)
// ============================================================================
static uint8_t fs_do_delete(const pble_fs_req_t *it, size_t *extra) {
    *extra = 0;
    if (it->len < 2) {
        return PBLE_EBADREQ;
    }
    uint16_t plen = rd16(it->payload);
    if ((size_t)plen + 2 > it->len) {
        return PBLE_EBADREQ;
    }
    char path[PBLE_FS_PATH_BUF];
    uint8_t rc = pble_fs_resolve((const char *)it->payload + 2, plen, path, sizeof(path));
    if (rc != PBLE_OK) {
        return rc;
    }
    uint32_t sz;
    bool isdir;
    uint8_t st = fs_stat_path(it, path, &sz, &isdir);
    if (st != PBLE_OK) {
        return st;                   // missing → ENOENT
    }
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        mp_obj_t po = fs_str(path);
        if (isdir) {
            if (!pble_fs_ticket_valid(it)) {
                nlr_pop();
                return PBLE_NO_RSP;
            }
            mp_vfs_rmdir(po);        // non-empty → ENOTEMPTY → EACCES
            if (!pble_fs_ticket_valid(it)) {
                nlr_pop();
                return PBLE_NO_RSP;
            }
        } else {
            if (!pble_fs_ticket_valid(it)) {
                nlr_pop();
                return PBLE_NO_RSP;
            }
            mp_vfs_remove(po);
            if (!pble_fs_ticket_valid(it)) {
                nlr_pop();
                return PBLE_NO_RSP;
            }
        }
        nlr_pop();
        st = PBLE_OK;
    } else {
        st = fs_exc_to_status(MP_OBJ_FROM_PTR(nlr.ret_val));
    }
    return st;
}

static uint8_t fs_do_mkdir(const pble_fs_req_t *it, size_t *extra) {
    *extra = 0;
    if (it->len < 2) {
        return PBLE_EBADREQ;
    }
    uint16_t plen = rd16(it->payload);
    if ((size_t)plen + 2 > it->len) {
        return PBLE_EBADREQ;
    }
    char path[PBLE_FS_PATH_BUF];
    uint8_t rc = pble_fs_resolve((const char *)it->payload + 2, plen, path, sizeof(path));
    if (rc != PBLE_OK) {
        return rc;
    }
    nlr_buf_t nlr;
    uint8_t st;
    if (nlr_push(&nlr) == 0) {
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        mp_vfs_mkdir(fs_str(path));  // missing parent → ENOENT
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        nlr_pop();
        return PBLE_OK;
    } else {
        st = fs_exc_to_status(MP_OBJ_FROM_PTR(nlr.ret_val));
    }
    if (!pble_fs_ticket_valid(it)) {
        return PBLE_NO_RSP;
    }
    if (st != PBLE_EBADREQ) {      // only EEXIST maps to EBADREQ here
        return st;
    }

    // EEXIST can name either a directory (idempotent OK) or a file (EBADREQ).
    // Resolve it with a fresh stat instead of treating any failed pre-stat as
    // proof that the path was absent.
    uint32_t sz;
    bool isdir;
    st = fs_stat_path(it, path, &sz, &isdir);
    if (st != PBLE_OK) {
        return st;
    }
    return isdir ? PBLE_OK : PBLE_EBADREQ;
}

static uint8_t fs_do_rename(const pble_fs_req_t *it, size_t *extra) {
    *extra = 0;
    // [slen:u16][src][dlen:u16][dst] — both jailed.
    if (it->len < 4) {
        return PBLE_EBADREQ;
    }
    uint16_t sl = rd16(it->payload);
    if ((size_t)2 + sl + 2 > it->len) {
        return PBLE_EBADREQ;
    }
    uint16_t dl = rd16(it->payload + 2 + sl);
    if ((size_t)2 + sl + 2 + dl > it->len) {
        return PBLE_EBADREQ;
    }
    char spath[PBLE_FS_PATH_BUF];
    char dpath[PBLE_FS_PATH_BUF];
    uint8_t rc = pble_fs_resolve((const char *)it->payload + 2, sl, spath, sizeof(spath));
    if (rc != PBLE_OK) {
        return rc;
    }
    rc = pble_fs_resolve((const char *)it->payload + 4 + sl, dl, dpath, sizeof(dpath));
    if (rc != PBLE_OK) {
        return rc;
    }
    uint32_t sz;
    bool isdir;
    uint8_t st = fs_stat_path(it, spath, &sz, &isdir);
    if (st != PBLE_OK) {
        return st;                   // src missing → ENOENT
    }
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        mp_vfs_rename(fs_str(spath), fs_str(dpath));  // dst non-empty dir → EACCES
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        nlr_pop();
        st = PBLE_OK;
    } else {
        st = fs_exc_to_status(MP_OBJ_FROM_PTR(nlr.ret_val));
    }
    return st;
}

// ============================================================================
// Worker dispatch + loop
// ============================================================================
static void fs_dispatch(const pble_fs_req_t *it) {
    bool response_bearing = it->opcode != PBLE_OP_FILE_PUT_DATA;
    if (response_bearing &&
        (!pble_rsp_ticket_valid(&it->ticket) || !pble_fs_ticket_valid(it))) {
        return;
    }
    if (!response_bearing && !pble_fs_item_valid(it)) {
        return;
    }
    size_t extra = 0;
    uint8_t st;
    switch (it->opcode) {
        case PBLE_OP_FILE_LIST:      st = fs_do_list(it, &extra); break;
        case PBLE_OP_FILE_STAT:      st = fs_do_stat(it, &extra); break;
        case PBLE_OP_FILE_GET_BEGIN: st = fs_do_get(it); break;        // emits own RSP+events
        case PBLE_OP_FILE_PUT_BEGIN: st = fs_do_put_begin(it, &extra); break;
        case PBLE_OP_FILE_PUT_DATA:  fs_do_put_data(it); return;       // ACK only, no RSP
        case PBLE_OP_FILE_PUT_END:   st = fs_do_put_end(it, &extra); break;
        case PBLE_OP_FILE_DELETE:    st = fs_do_delete(it, &extra); break;
        case PBLE_OP_MKDIR:          st = fs_do_mkdir(it, &extra); break;
        case PBLE_OP_FILE_RENAME:    st = fs_do_rename(it, &extra); break;
        default:                     st = PBLE_EUNSUPPORTED; break;
    }
    if (st == PBLE_NO_RSP) {
        return;                      // handler already emitted its reply
    }
    if (!pble_rsp_ticket_valid(&it->ticket) || !pble_fs_ticket_valid(it)) {
        return;
    }
    g_scratch[0] = st;
    pble_rsp_publish(&it->ticket, it->opcode, it->id, g_scratch, 1 + extra);
}

static bool pble_fs_dequeue_begin(pble_fs_req_t *item) {
    if (item == NULL || g_fs_work == NULL || g_fs_gate == NULL ||
        g_fs_q == NULL) {
        return false;
    }
    if (xSemaphoreTake(g_fs_work, portMAX_DELAY) != pdTRUE) {
        return false;
    }
    if (xSemaphoreTake(g_fs_gate, portMAX_DELAY) != pdTRUE) {
        (void)xSemaphoreGive(g_fs_work);
        return false;
    }
    if (xQueueReceive(g_fs_q, item, 0) != pdTRUE) {
        (void)xSemaphoreGive((SemaphoreHandle_t)g_fs_gate);
        return false;
    }
    g_fs_dequeue_claim = true;
    g_fs_worker_busy = true;
    if (g_fs_outstanding > 0) {
        g_fs_outstanding--;
    }
    g_fs_dequeue_claim = false;
    (void)xSemaphoreGive(g_fs_gate);
    return true;
}

static void pble_fs_dequeue_end(void) {
    if (g_fs_gate == NULL) {
        return;
    }
    if (xSemaphoreTake(g_fs_gate, portMAX_DELAY) == pdTRUE) {
        g_fs_worker_busy = false;
        g_fs_dequeue_claim = false;
        (void)xSemaphoreGive(g_fs_gate);
    }
}

bool pble_fs_quiesce_try(void) {
    if (g_fs_gate == NULL || g_fs_q == NULL ||
        xSemaphoreTake(g_fs_gate, 0) != pdTRUE) {
        return false;
    }
    g_fs_admission_open = false;
    bool idle = !g_fs_worker_busy && !g_fs_dequeue_claim &&
                g_fs_outstanding == 0 &&
                uxQueueMessagesWaiting(g_fs_q) == 0;
    if (!idle) {
        g_fs_admission_open = true;
    }
    (void)xSemaphoreGive(g_fs_gate);
    return idle;
}

void pble_fs_quiesce_abort(void) {
    if (g_fs_gate != NULL && xSemaphoreTake(g_fs_gate, 0) == pdTRUE) {
        g_fs_admission_open = true;
        (void)xSemaphoreGive(g_fs_gate);
    }
}

void pble_fs_vm_reset(void) {
    g_fs_admission_open = false;
    g_fs_worker_busy = false;
    g_fs_outstanding = 0;
    g_fs_dequeue_claim = false;
    if (g_fs_q != NULL) {
        (void)xQueueReset(g_fs_q);
    }
    if (g_fs_work != NULL) {
        while (xSemaphoreTake(g_fs_work, 0) == pdTRUE) {
        }
    }
    fs_put_reset();
    MP_STATE_VM(pble_fs_put_file) = MP_OBJ_NULL;
}

void pble_fs_worker(void) {
    pble_vm_worker_ready(PBLE_VM_WORKER_FS);
    for (;;) {
        pble_fs_req_t item;
        // Release the GIL while blocked so the main-task REPL + runner run freely;
        // re-acquire before touching VM/vfs state.
        MP_THREAD_GIL_EXIT();
        bool dequeued = pble_fs_dequeue_begin(&item);
        MP_THREAD_GIL_ENTER();
        if (dequeued) {
            fs_dispatch(&item);
            pble_fs_dequeue_end();
        }
    }
}

// ============================================================================
// Host-task dispatch surface — validate + enqueue (NEVER call mp_vfs_* here)
// ============================================================================
static uint8_t fs_enqueue(const pble_frame_t *req,
                          const pble_session_token_t *session, bool put_data,
                          const pble_rsp_ticket_t *ticket) {
    if (req == NULL) {
        return put_data ? PBLE_NO_RSP : PBLE_EBADREQ;
    }
    if (g_fs_q == NULL || g_fs_gate == NULL || g_fs_work == NULL) {
        return put_data ? PBLE_NO_RSP : PBLE_EINTERNAL;
    }
    if (req->len > PBLE_FS_ITEM_PAYLOAD) {
        return put_data ? PBLE_NO_RSP : PBLE_ERANGE;
    }
    if (!put_data && (ticket == NULL || !pble_rsp_ticket_valid(ticket))) {
        return PBLE_NO_RSP;
    }
    bool queued = false;
    if (session != NULL && pble_ble_session_live(session) &&
        xSemaphoreTake(g_fs_gate, 0) == pdTRUE) {
        if (g_fs_admission_open) {
            g_enq.opcode = req->opcode;
            g_enq.id = req->id;
            g_enq.session = *session;
            g_enq.vm_epoch = pble_vm_epoch_current();
            if (ticket != NULL) {
                g_enq.ticket = *ticket;
            } else {
                memset(&g_enq.ticket, 0, sizeof(g_enq.ticket));
            }
            g_enq.len = req->len;
            if (req->len > 0 && req->payload != NULL) {
                memcpy(g_enq.payload, req->payload, req->len);
            }
            if (xQueueSend(g_fs_q, &g_enq, 0) == pdTRUE) {
                g_fs_outstanding++;
                queued = true;
            }
        }
        (void)xSemaphoreGive(g_fs_gate);
    }
    if (queued) {
        (void)xSemaphoreGive(g_fs_work);
        return PBLE_NO_RSP;          // worker replies async by id
    }
    // Mailbox full: PUT_DATA drops silently (app retransmits from last ACK). A
    // response-bearing command publishes EBUSY through its existing reservation.
    if (!put_data) {
        uint8_t status = PBLE_EBUSY;
        pble_rsp_publish(ticket, req->opcode, req->id, &status, 1);
    }
    return PBLE_NO_RSP;
}

uint8_t pble_fs_list(const pble_frame_t *req, uint8_t *rsp, size_t *rlen,
                     const pble_session_token_t *session,
                     const pble_rsp_ticket_t *ticket) {
    (void)rsp; if (rlen) { *rlen = 0; } return fs_enqueue(req, session, false, ticket);
}
uint8_t pble_fs_stat(const pble_frame_t *req, uint8_t *rsp, size_t *rlen,
                     const pble_session_token_t *session,
                     const pble_rsp_ticket_t *ticket) {
    (void)rsp; if (rlen) { *rlen = 0; } return fs_enqueue(req, session, false, ticket);
}
uint8_t pble_fs_get_begin(const pble_frame_t *req, uint8_t *rsp, size_t *rlen,
                          const pble_session_token_t *session,
                          const pble_rsp_ticket_t *ticket) {
    (void)rsp; if (rlen) { *rlen = 0; } return fs_enqueue(req, session, false, ticket);
}
uint8_t pble_fs_put_begin(const pble_frame_t *req, uint8_t *rsp, size_t *rlen,
                          const pble_session_token_t *session,
                          const pble_rsp_ticket_t *ticket) {
    (void)rsp; if (rlen) { *rlen = 0; } return fs_enqueue(req, session, false, ticket);
}
uint8_t pble_fs_put_data(const pble_frame_t *req, uint8_t *rsp, size_t *rlen,
                         const pble_session_token_t *session) {
    (void)rsp; if (rlen) { *rlen = 0; } return fs_enqueue(req, session, true, NULL);
}
uint8_t pble_fs_put_end(const pble_frame_t *req, uint8_t *rsp, size_t *rlen,
                        const pble_session_token_t *session,
                        const pble_rsp_ticket_t *ticket) {
    (void)rsp; if (rlen) { *rlen = 0; } return fs_enqueue(req, session, false, ticket);
}
uint8_t pble_fs_delete(const pble_frame_t *req, uint8_t *rsp, size_t *rlen,
                       const pble_session_token_t *session,
                       const pble_rsp_ticket_t *ticket) {
    (void)rsp; if (rlen) { *rlen = 0; } return fs_enqueue(req, session, false, ticket);
}
uint8_t pble_fs_mkdir(const pble_frame_t *req, uint8_t *rsp, size_t *rlen,
                      const pble_session_token_t *session,
                      const pble_rsp_ticket_t *ticket) {
    (void)rsp; if (rlen) { *rlen = 0; } return fs_enqueue(req, session, false, ticket);
}
uint8_t pble_fs_rename(const pble_frame_t *req, uint8_t *rsp, size_t *rlen,
                       const pble_session_token_t *session,
                       const pble_rsp_ticket_t *ticket) {
    (void)rsp; if (rlen) { *rlen = 0; } return fs_enqueue(req, session, false, ticket);
}

void pble_fs_register(void) {
    if (g_fs_q == NULL) {
        g_fs_q = xQueueCreate(PBLE_FS_QDEPTH, sizeof(pble_fs_req_t));
    }
    if (g_fs_gate == NULL) {
        g_fs_gate = xSemaphoreCreateMutex();
    }
    if (g_fs_work == NULL) {
        g_fs_work = xSemaphoreCreateCounting(PBLE_FS_QDEPTH, 0);
    }
    if (g_fs_q == NULL || g_fs_gate == NULL || g_fs_work == NULL) {
        mp_raise_msg(&mp_type_RuntimeError,
                     MP_ERROR_TEXT("filesystem mailbox alloc failed"));
    }
    if (xSemaphoreTake(g_fs_gate, portMAX_DELAY) == pdTRUE) {
        g_fs_admission_open = true;
        (void)xSemaphoreGive(g_fs_gate);
    }
    fs_put_reset();
    pble_proto_register_deferred(PBLE_OP_FILE_LIST, pble_fs_list);
    pble_proto_register_deferred(PBLE_OP_FILE_STAT, pble_fs_stat);
    pble_proto_register_deferred(PBLE_OP_FILE_GET_BEGIN, pble_fs_get_begin);
    pble_proto_register_deferred(PBLE_OP_FILE_PUT_BEGIN, pble_fs_put_begin);
    pble_proto_register_no_response(PBLE_OP_FILE_PUT_DATA, pble_fs_put_data);
    pble_proto_register_deferred(PBLE_OP_FILE_PUT_END, pble_fs_put_end);
    pble_proto_register_deferred(PBLE_OP_FILE_DELETE, pble_fs_delete);
    pble_proto_register_deferred(PBLE_OP_MKDIR, pble_fs_mkdir);
    pble_proto_register_deferred(PBLE_OP_FILE_RENAME, pble_fs_rename);
}

// ============================================================================
// Thin MicroPython surface (boot wiring + HIL introspection)
// ============================================================================
// worker() is the _thread entry: `_thread.start_new_thread(pble_fs.worker, ())`
// from _boot.py after init_agent(). It never returns. register() is idempotent
// (called from init_agent BEFORE the worker launches).
static mp_obj_t mod_pble_fs_worker(void) {
    pble_fs_worker();
    return mp_const_none;            // unreachable
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_pble_fs_worker_obj, mod_pble_fs_worker);

static mp_obj_t mod_pble_fs_register(void) {
    pble_fs_register();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_pble_fs_register_obj, mod_pble_fs_register);

static const mp_rom_map_elem_t pble_fs_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_pble_fs) },
    { MP_ROM_QSTR(MP_QSTR_register), MP_ROM_PTR(&mod_pble_fs_register_obj) },
    { MP_ROM_QSTR(MP_QSTR_worker), MP_ROM_PTR(&mod_pble_fs_worker_obj) },
};
static MP_DEFINE_CONST_DICT(pble_fs_globals, pble_fs_globals_table);

const mp_obj_module_t pble_fs_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&pble_fs_globals,
};

MP_REGISTER_MODULE(MP_QSTR_pble_fs, pble_fs_user_cmodule);
