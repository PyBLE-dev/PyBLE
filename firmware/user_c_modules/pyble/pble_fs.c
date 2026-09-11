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
#define PBLE_FS_SAFETY_RESERVE 65536u   // bytes kept free after PUT admission

// --- Internal design bounds (architect: queue depth = W+2, W=8 2026-07-04) ----
#define PBLE_FS_ITEM_PAYLOAD 260    // [slen:2]+src[128]+[dlen:2]+dst[128]
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
    uint64_t transfer_generation;
    bool get_active_at_enqueue;
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
static bool g_fs_registered;
static uint64_t g_fs_registration_epoch;
static portMUX_TYPE g_fs_transfer_mux = portMUX_INITIALIZER_UNLOCKED;
static uint64_t g_fs_transfer_generation = 1;
static bool g_fs_transfer_exhausted;

// GET streams occupy the one fs worker until completion. Namespace mutations
// admitted concurrently snapshot this generation-qualified bit so that their
// later dequeue cannot erase the admission-time EBUSY decision.
static bool g_get_active;
static uint64_t g_get_generation;

// Worker-local single-active-transfer PUT state machine (§5 windowed upload).
static bool     g_put_active;
static char     g_put_temp[PBLE_FS_PATH_BUF];   // "<dest>.pbltmp"
static char     g_put_dest[PBLE_FS_PATH_BUF];   // final jailed destination
static uint32_t g_put_total;                     // declared total_size
static uint32_t g_put_crc_target;                // declared whole-file crc32
static uint32_t g_put_watermark;                 // highest contiguous byte written
static uint32_t g_put_crc_running;               // streaming whole-file CRC, PRE-final-xor
static uint8_t  g_put_latched;                   // 0, or a latched write status
static uint64_t g_put_generation;                // exact FS generation that owns g_put_*

// The open temp file object must survive GC across PUT_DATA calls → rooted.
MP_REGISTER_ROOT_POINTER(mp_obj_t pble_fs_put_file);

static bool fs_put_owned(const pble_fs_req_t *it);
static bool fs_put_active_current(const pble_fs_req_t *it);

static bool pble_fs_transfer_valid(const pble_fs_req_t *it) {
    if (it == NULL) {
        return false;
    }
    bool valid;
    taskENTER_CRITICAL(&g_fs_transfer_mux);
    valid = !g_fs_transfer_exhausted &&
            it->transfer_generation == g_fs_transfer_generation;
    taskEXIT_CRITICAL(&g_fs_transfer_mux);
    return valid;
}

static bool pble_fs_item_valid(const pble_fs_req_t *it) {
    return it != NULL && pble_ble_session_live(&it->session) &&
           pble_vm_epoch_valid(it->vm_epoch) &&
           pble_fs_transfer_valid(it);
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
static bool fs_has_tmp_suffix(const char *name, size_t nl) {
    size_t sl = sizeof(PBLE_FS_TMP_SUFFIX) - 1;
    return nl >= sl &&
           memcmp(name + nl - sl, PBLE_FS_TMP_SUFFIX, sl) == 0;
}

// Accept only Unicode scalar values in their shortest UTF-8 encoding. Paths
// are byte-counted on the wire, so validation must happen before strtok/strlen
// or any VFS call can reinterpret malformed byte sequences.
static bool fs_utf8_valid(const char *input, size_t len) {
    const uint8_t *bytes = (const uint8_t *)input;
    size_t i = 0;
    while (i < len) {
        uint8_t first = bytes[i++];
        if (first <= 0x7fu) {
            if (first == 0u) {
                return false;
            }
            continue;
        }
        if (first >= 0xc2u && first <= 0xdfu) {
            if (i >= len || (bytes[i] & 0xc0u) != 0x80u) {
                return false;
            }
            ++i;
            continue;
        }
        if (first >= 0xe0u && first <= 0xefu) {
            if (i + 1u >= len ||
                (bytes[i] & 0xc0u) != 0x80u ||
                (bytes[i + 1u] & 0xc0u) != 0x80u ||
                (first == 0xe0u && bytes[i] < 0xa0u) ||
                (first == 0xedu && bytes[i] >= 0xa0u)) {
                return false;
            }
            i += 2u;
            continue;
        }
        if (first >= 0xf0u && first <= 0xf4u) {
            if (i + 2u >= len ||
                (bytes[i] & 0xc0u) != 0x80u ||
                (bytes[i + 1u] & 0xc0u) != 0x80u ||
                (bytes[i + 2u] & 0xc0u) != 0x80u ||
                (first == 0xf0u && bytes[i] < 0x90u) ||
                (first == 0xf4u && bytes[i] > 0x8fu)) {
                return false;
            }
            i += 3u;
            continue;
        }
        return false;
    }
    return true;
}

uint8_t pble_fs_resolve(const char *in, size_t inlen, char *out, size_t outcap) {
    if (in == NULL || inlen == 0) {
        return PBLE_EBADREQ;
    }
    if (inlen > PBLE_FS_PATH_MAX) {
        return PBLE_ERANGE;
    }
    if (!fs_utf8_valid(in, inlen)) {
        return PBLE_EBADREQ;
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
        if (fs_has_tmp_suffix(tok, strlen(tok))) {
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

// Close an exact local VFS object regardless of whether the request identity
// that opened it is still current.  Cancellation forbids stale protocol
// effects, but it must not turn already-acquired worker resources into leaks.
// Close is best-effort because cleanup must preserve the original status (or
// silent cancellation) when the VFS itself raises while unwinding.
static void fs_close_local(mp_obj_t file) {
    if (file == MP_OBJ_NULL) {
        return;
    }
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        mp_stream_close(file);
        nlr_pop();
    }
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
        // The open itself may have raced invalidation. Closing this exact local
        // object is the sole VFS cleanup a stale BEGIN may still perform.
        fs_close_local(opened);
        (void)validator(it);
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

static bool fs_mode_is_regular(mp_int_t mode) {
    return (mode & 0xf000) == MP_S_IFREG;
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
        bool isreg = fs_mode_is_regular(mode);
        bool directory = (mode & 0xf000) == MP_S_IFDIR;
        if (!isreg && !directory) {
            nlr_pop();
            return PBLE_EACCES;
        }
        *size = (n > 6) ? (uint32_t)mp_obj_get_int(f[6]) : 0;
        *isdir = directory;
        nlr_pop();
        st = PBLE_OK;
    } else {
        st = fs_exc_to_status(MP_OBJ_FROM_PTR(nlr.ret_val));
    }
    return st;
}

// Whole-file CRC-32 over exactly the stat-advertised extent. Opens "rb",
// streams into g_scratch, rejects premature EOF/overreported reads, and always
// closes. Returns §8 status; *out set on OK.
static uint8_t fs_crc_file(const pble_fs_req_t *it, const char *path,
                           uint32_t expected, uint32_t *out) {
    nlr_buf_t nlr;
    uint8_t st;
    volatile mp_obj_t f = MP_OBJ_NULL;
    if (nlr_push(&nlr) == 0) {
        f = fs_open(it, pble_fs_ticket_valid, path, "rb");
        if (!pble_fs_ticket_valid(it)) {
            fs_close_local((mp_obj_t)f);
            f = MP_OBJ_NULL;
            nlr_pop();
            return PBLE_NO_RSP;
        }
        const mp_stream_p_t *sp = mp_get_stream((mp_obj_t)f);
        uint32_t crc = 0xFFFFFFFFu;
        uint32_t remaining = expected;
        while (remaining > 0) {
            int err;
            if (!pble_fs_ticket_valid(it)) {
                fs_close_local((mp_obj_t)f);
                f = MP_OBJ_NULL;
                nlr_pop();
                return PBLE_NO_RSP;
            }
            mp_uint_t want = (remaining > PBLE_FS_SCRATCH)
                                 ? PBLE_FS_SCRATCH
                                 : (mp_uint_t)remaining;
            mp_uint_t n = sp->read((mp_obj_t)f, g_scratch, want, &err);
            if (!pble_fs_ticket_valid(it)) {
                fs_close_local((mp_obj_t)f);
                f = MP_OBJ_NULL;
                nlr_pop();
                return PBLE_NO_RSP;
            }
            if (n == MP_STREAM_ERROR) {
                mp_raise_OSError(err);
            }
            if (n > PBLE_FS_SCRATCH || n > want) {
                mp_raise_OSError(MP_EIO);
            }
            if (n == 0) {
                mp_raise_OSError(MP_EIO);
            }
            crc = crc32_update(crc, g_scratch, n);
            remaining -= (uint32_t)n;
        }
        if (!pble_fs_ticket_valid(it)) {
            fs_close_local((mp_obj_t)f);
            f = MP_OBJ_NULL;
            nlr_pop();
            return PBLE_NO_RSP;
        }
        mp_stream_close((mp_obj_t)f);
        f = MP_OBJ_NULL;
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        *out = crc ^ 0xFFFFFFFFu;
        nlr_pop();
        st = PBLE_OK;
    } else {
        if (f != MP_OBJ_NULL) {
            fs_close_local((mp_obj_t)f);
            f = MP_OBJ_NULL;
        }
        if (!pble_fs_ticket_valid(it)) {
            return PBLE_NO_RSP;
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
            fs_close_local((mp_obj_t)f);
            f = MP_OBJ_NULL;
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
                fs_close_local((mp_obj_t)f);
                f = MP_OBJ_NULL;
                nlr_pop();
                return PBLE_NO_RSP;
            }
            mp_uint_t n = sp->read((mp_obj_t)f, g_scratch, want, &err);
            if (!pble_fs_ticket_valid(it)) {
                fs_close_local((mp_obj_t)f);
                f = MP_OBJ_NULL;
                nlr_pop();
                return PBLE_NO_RSP;
            }
            if (n == MP_STREAM_ERROR) {
                mp_raise_OSError(err);
            }
            if (n > want) {
                mp_raise_OSError(MP_EIO);
            }
            if (n == 0) {
                // Premature EOF is malformed scratch, never a verified resume
                // prefix. MP_EIO maps to the required PBLE_EIO cleanup path.
                mp_raise_OSError(MP_EIO);
            }
            crc = crc32_update(crc, g_scratch, n);
            remaining -= (uint32_t)n;
        }
        if (!pble_fs_ticket_valid(it)) {
            fs_close_local((mp_obj_t)f);
            f = MP_OBJ_NULL;
            nlr_pop();
            return PBLE_NO_RSP;
        }
        mp_stream_close((mp_obj_t)f);
        f = MP_OBJ_NULL;
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        *running = crc;               // NOT finalized — continued by PUT_DATA
        nlr_pop();
        st = PBLE_OK;
    } else {
        if (f != MP_OBJ_NULL) {
            fs_close_local((mp_obj_t)f);
            f = MP_OBJ_NULL;
        }
        if (!pble_fs_ticket_valid(it)) {
            return PBLE_NO_RSP;
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
            if (fs_has_tmp_suffix(name, nlen)) {
                continue;            // internal scratch consumes no LIST budget
            }
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
        st = fs_crc_file(it, path, size, &crc);
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
    if (g_put_active && fs_put_active_current(it)) {
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

    // From this cut until every stream exit, concurrent namespace mutations
    // must retain that they were admitted during this GET. The worker itself
    // is single-threaded, but host-task enqueue runs concurrently.
    bool get_claimed = false;
    taskENTER_CRITICAL(&g_fs_transfer_mux);
    if (!g_fs_transfer_exhausted &&
        it->transfer_generation == g_fs_transfer_generation &&
        (!g_get_active || g_get_generation != g_fs_transfer_generation)) {
        g_get_active = true;
        g_get_generation = it->transfer_generation;
        get_claimed = true;
    }
    taskEXIT_CRITICAL(&g_fs_transfer_mux);
    if (!get_claimed) {
        return PBLE_NO_RSP;
    }
    if (!pble_fs_ticket_valid(it)) {
        goto get_done;
    }

    // RSP{OK}[total_size:u32] must fully complete before dependent events.
    g_scratch[0] = PBLE_OK;
    le32(g_scratch + 1, total);
    if (!pble_rsp_expect_completion(&it->ticket)) {
        goto get_done;
    }
    if (!pble_rsp_publish(&it->ticket, PBLE_OP_FILE_GET_BEGIN, it->id,
                          g_scratch, 5)) {
        pble_rsp_cancel_ticket(&it->ticket);
    }
    MP_THREAD_GIL_EXIT();
    bool rsp_delivered = pble_rsp_wait(&it->ticket);
    MP_THREAD_GIL_ENTER();
    if (!rsp_delivered || !pble_fs_item_valid(it)) {
        goto get_done;
    }

    uint32_t chunk = fs_chunk();
    uint32_t crc = 0xFFFFFFFFu;
    uint32_t remaining = total;
    nlr_buf_t nlr;
    volatile mp_obj_t f = MP_OBJ_NULL;
    volatile int tx_dead = 0;   // link gone / backpressure budget exhausted
    volatile int stream_complete = 0;
    if (nlr_push(&nlr) == 0) {
        if (!pble_fs_item_valid(it)) {
            nlr_pop();
            goto get_done;
        }
        f = fs_open(it, pble_fs_item_valid, path, "rb");
        if (!pble_fs_item_valid(it)) {
            fs_close_local((mp_obj_t)f);
            f = MP_OBJ_NULL;
            nlr_pop();
            goto get_done;
        }
        const mp_stream_p_t *sp = mp_get_stream((mp_obj_t)f);
        uint32_t pos = 0;
        while (remaining > 0) {
            if (!pble_fs_item_valid(it)) {
                tx_dead = 1;
                break;
            }
            int err;
            mp_uint_t want = (remaining > chunk)
                                 ? (mp_uint_t)chunk
                                 : (mp_uint_t)remaining;
            // Read into g_scratch+4 so a [offset:u32] header can sit contiguously
            // in front of the emitted slice.
            if (!pble_fs_item_valid(it)) {
                fs_close_local((mp_obj_t)f);
                f = MP_OBJ_NULL;
                nlr_pop();
                goto get_done;
            }
            mp_uint_t n = sp->read((mp_obj_t)f, g_scratch + 4, want, &err);
            if (!pble_fs_item_valid(it)) {
                fs_close_local((mp_obj_t)f);
                f = MP_OBJ_NULL;
                nlr_pop();
                goto get_done;
            }
            if (n == MP_STREAM_ERROR) {
                mp_raise_OSError(err);
            }
            if (n > chunk || n > want) {
                mp_raise_OSError(MP_EIO);
            }
            if (n == 0) {
                mp_raise_OSError(MP_EIO);
            }
            crc = crc32_update(crc, g_scratch + 4, n);   // whole-file CRC (from 0)
            remaining -= (uint32_t)n;
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
                    fs_close_local((mp_obj_t)f);
                    f = MP_OBJ_NULL;
                    nlr_pop();
                    goto get_done;
                }
                int emit_rc = fs_emit_paced(it, PBLE_OP_FILE_GET_DATA, dp - 4,
                                            (size_t)(4 + elen));
                if (!pble_fs_item_valid(it)) {
                    fs_close_local((mp_obj_t)f);
                    f = MP_OBJ_NULL;
                    nlr_pop();
                    goto get_done;
                }
                if (emit_rc != PBLE_TX_OK) {
                    tx_dead = 1;
                    break;
                }
            }
            pos = blk_end;
        }
        if (!pble_fs_item_valid(it)) {
            fs_close_local((mp_obj_t)f);
            f = MP_OBJ_NULL;
            nlr_pop();
            goto get_done;
        }
        mp_stream_close((mp_obj_t)f);
        f = MP_OBJ_NULL;
        if (!pble_fs_item_valid(it)) {
            nlr_pop();
            goto get_done;
        }
        stream_complete = (remaining == 0);
        nlr_pop();
    } else {
        stream_complete = 0;
        if (f != MP_OBJ_NULL) {
            fs_close_local((mp_obj_t)f);
            f = MP_OBJ_NULL;
        }
        // RSP{OK} already went out; omit END so the client times out the
        // incomplete transfer instead of accepting a partial CRC.
    }
    if (stream_complete && !tx_dead && pble_fs_item_valid(it)) {
        uint32_t fcrc = crc ^ 0xFFFFFFFFu;
        le32(g_scratch, fcrc);
        if (!pble_fs_item_valid(it)) {
            goto get_done;
        }
        (void)fs_emit_paced(it, PBLE_OP_FILE_GET_END, g_scratch, 4);
        if (!pble_fs_item_valid(it)) {
            goto get_done;
        }
    }
    // tx_dead: the link is gone or saturated beyond the retry budget — an END
    // cannot usefully be delivered; the app recovers via its data timeout.
get_done:
    taskENTER_CRITICAL(&g_fs_transfer_mux);
    if (g_get_active && g_get_generation == it->transfer_generation) {
        g_get_active = false;
        g_get_generation = 0;
    }
    taskEXIT_CRITICAL(&g_fs_transfer_mux);
    return PBLE_NO_RSP;
}

// ============================================================================
// Worker op: windowed upload PUT_BEGIN/DATA/END (0x15/0x16/0x41/0x17)
// ============================================================================
static void fs_put_ack(const pble_fs_req_t *it) {
    if (!fs_put_owned(it)) {
        return;
    }
    uint8_t b[4];
    uint32_t watermark;
    taskENTER_CRITICAL(&g_fs_transfer_mux);
    bool owned = g_put_active &&
                 g_put_generation == it->transfer_generation &&
                 it->transfer_generation == g_fs_transfer_generation;
    watermark = g_put_watermark;
    taskEXIT_CRITICAL(&g_fs_transfer_mux);
    if (!owned) {
        return;
    }
    le32(b, watermark);              // next expected = highest contiguous
    // Paced: a dropped ACK stalls the (client-paced) upload for a full client
    // timeout; under backpressure wait for the pool rather than dropping.
    (void)fs_emit_paced(it, PBLE_OP_FILE_PUT_ACK, b, 4);
}

static bool fs_put_latch_owner(const pble_fs_req_t *it, uint8_t status) {
    if (!pble_fs_item_valid(it)) {
        return false;
    }
    bool latched = false;
    taskENTER_CRITICAL(&g_fs_transfer_mux);
    if (g_put_active &&
        g_put_generation == it->transfer_generation &&
        it->transfer_generation == g_fs_transfer_generation) {
        g_put_latched = status;
        latched = true;
    }
    taskEXIT_CRITICAL(&g_fs_transfer_mux);
    return latched;
}

static uint8_t fs_put_close(const pble_fs_req_t *it) {
    mp_obj_t f = MP_STATE_VM(pble_fs_put_file);
    if (f == MP_OBJ_NULL) {
        return PBLE_OK;
    }
    uint8_t st = PBLE_OK;
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        mp_stream_close(f);
        bool cancelled = !pble_fs_ticket_valid(it);
        nlr_pop();
        MP_STATE_VM(pble_fs_put_file) = MP_OBJ_NULL;
        if (cancelled) {
            return PBLE_NO_RSP;
        }
    } else {
        st = PBLE_EIO;
    }
    MP_STATE_VM(pble_fs_put_file) = MP_OBJ_NULL;
    if (!pble_fs_ticket_valid(it)) {
        return PBLE_NO_RSP;
    }
    return st;
}

static void fs_put_reset_locked(void) {
    g_put_active = false;
    g_put_generation = 0;
    g_put_temp[0] = '\0';
    g_put_dest[0] = '\0';
    g_put_total = g_put_crc_target = g_put_watermark = 0;
    g_put_crc_running = 0xFFFFFFFFu;
    g_put_latched = 0;
}

static void fs_put_reset(void) {
    taskENTER_CRITICAL(&g_fs_transfer_mux);
    fs_put_reset_locked();
    taskEXIT_CRITICAL(&g_fs_transfer_mux);
}

static bool fs_put_owned(const pble_fs_req_t *it) {
    if (!pble_fs_item_valid(it)) {
        return false;
    }
    bool owned;
    taskENTER_CRITICAL(&g_fs_transfer_mux);
    owned = !g_fs_transfer_exhausted && g_put_active &&
            g_put_generation == it->transfer_generation &&
            it->transfer_generation == g_fs_transfer_generation;
    taskEXIT_CRITICAL(&g_fs_transfer_mux);
    return owned;
}

static bool fs_put_active_current(const pble_fs_req_t *it) {
    bool active;
    taskENTER_CRITICAL(&g_fs_transfer_mux);
    active = it != NULL && !g_fs_transfer_exhausted && g_put_active &&
             g_put_generation == g_fs_transfer_generation &&
             it->transfer_generation == g_fs_transfer_generation;
    taskEXIT_CRITICAL(&g_fs_transfer_mux);
    return active;
}

static bool fs_put_reset_owner(const pble_fs_req_t *it) {
    if (!pble_fs_ticket_valid(it)) {
        return false;
    }
    bool reset = false;
    taskENTER_CRITICAL(&g_fs_transfer_mux);
    if (it != NULL && !g_fs_transfer_exhausted && g_put_active &&
        g_put_generation == it->transfer_generation &&
        it->transfer_generation == g_fs_transfer_generation) {
        fs_put_reset_locked();
        reset = true;
    }
    taskEXIT_CRITICAL(&g_fs_transfer_mux);
    return reset;
}

static void fs_put_close_local(const pble_fs_req_t *it, mp_obj_t file) {
    // A BEGIN invalidated after opening must still close the exact object it
    // owns. Observe the ticket without making cleanup conditional on a ticket
    // that is expected to be stale here.
    (void)pble_fs_ticket_valid(it);
    fs_close_local(file);
    (void)pble_fs_ticket_valid(it);
}

// A successor worker may close and discard only a stale active record. The
// host disconnect path advances the generation but never races these fields.
static uint8_t fs_put_reconcile_stale(const pble_fs_req_t *it) {
    uint64_t stale_generation = 0;
    bool stale = false;
    taskENTER_CRITICAL(&g_fs_transfer_mux);
    bool request_current = it != NULL && !g_fs_transfer_exhausted &&
                           it->transfer_generation ==
                               g_fs_transfer_generation;
    if (request_current && g_put_active &&
        g_put_generation != g_fs_transfer_generation) {
        stale_generation = g_put_generation;
        stale = true;
    }
    taskEXIT_CRITICAL(&g_fs_transfer_mux);
    if (!request_current || !pble_fs_ticket_valid(it)) {
        return PBLE_NO_RSP;
    }
    if (!stale) {
        return PBLE_OK;
    }

    uint8_t close_status = fs_put_close(it);
    if (close_status == PBLE_NO_RSP) {
        return PBLE_NO_RSP;
    }

    bool ticket_current = pble_fs_ticket_valid(it);
    bool reclaimed = false;
    taskENTER_CRITICAL(&g_fs_transfer_mux);
    if (ticket_current && !g_fs_transfer_exhausted &&
        it->transfer_generation == g_fs_transfer_generation &&
        g_put_active && g_put_generation == stale_generation) {
        fs_put_reset_locked();
        reclaimed = true;
    }
    taskEXIT_CRITICAL(&g_fs_transfer_mux);
    return reclaimed ? close_status : PBLE_NO_RSP;
}

// F-10 link-drop hook. The host callback invalidates ownership only; it never
// writes worker-owned g_put_* or touches an MP/VFS object. A later worker closes
// the stale object and re-derives the durable prefix from `<dest>.pbltmp`.
void pble_fs_on_disconnect(void) {
    taskENTER_CRITICAL(&g_fs_transfer_mux);
    if (g_fs_transfer_generation == UINT64_MAX) {
        g_fs_transfer_exhausted = true;
    } else {
        g_fs_transfer_generation++;
    }
    taskEXIT_CRITICAL(&g_fs_transfer_mux);
}

// Remove exactly one malformed scratch object. This is deliberately
// non-recursive and verifies absence after a nominally successful backend call.
static uint8_t fs_remove_malformed_scratch(const pble_fs_req_t *it,
                                           const char *temp) {
    uint32_t size;
    bool isdir;
    uint8_t st = fs_stat_path(it, temp, &size, &isdir);
    if (st == PBLE_ENOENT) {
        return PBLE_OK;
    }
    if (st != PBLE_OK) {
        return st == PBLE_NO_RSP ? st : PBLE_EIO;
    }

    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        if (isdir) {
            mp_vfs_rmdir(fs_str(temp));
            if (!pble_fs_ticket_valid(it)) {
                nlr_pop();
                return PBLE_NO_RSP;
            }
        } else {
            mp_vfs_remove(fs_str(temp));
            if (!pble_fs_ticket_valid(it)) {
                nlr_pop();
                return PBLE_NO_RSP;
            }
        }
        nlr_pop();
    } else {
        return pble_fs_ticket_valid(it) ? PBLE_EIO : PBLE_NO_RSP;
    }

    st = fs_stat_path(it, temp, &size, &isdir);
    if (st == PBLE_ENOENT) {
        return PBLE_OK;
    }
    return st == PBLE_NO_RSP ? st : PBLE_EIO;
}

// Dynamic capacity admission for only the bytes remaining after an exact
// verified resume prefix. Geometry and every intermediate use checked u64.
static uint8_t fs_put_space_status(const pble_fs_req_t *it,
                                   uint32_t remaining) {
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        mp_obj_t result = mp_vfs_statvfs(fs_str(PBLE_FS_ROOT));
        if (!pble_fs_ticket_valid(it)) {
            nlr_pop();
            return PBLE_NO_RSP;
        }
        mp_obj_t *fields;
        size_t count;
        mp_obj_get_array(result, &count, &fields);
        if (count <= 4 || !mp_obj_is_int(fields[1]) ||
            !mp_obj_is_int(fields[4])) {
            nlr_pop();
            return PBLE_EIO;
        }
        mp_int_t unit_value;
        mp_int_t available_value;
        if (!mp_obj_get_int_maybe(fields[1], &unit_value) ||
            !mp_obj_get_int_maybe(fields[4], &available_value) ||
            unit_value <= 0 || available_value < 0) {
            nlr_pop();
            return PBLE_EIO;
        }

        uint64_t unit = (uint64_t)unit_value;
        uint64_t available = (uint64_t)available_value;
        if (available != 0 && unit > UINT64_MAX / available) {
            nlr_pop();
            return PBLE_EIO;
        }
        uint64_t free_bytes = unit * available;
        uint64_t rounded = 0;
        if (remaining != 0) {
            uint64_t addend = unit - 1u;
            if ((uint64_t)remaining > UINT64_MAX - addend) {
                nlr_pop();
                return PBLE_EIO;
            }
            uint64_t sum = (uint64_t)remaining + addend;
            rounded = (sum / unit) * unit;
        }
        if (rounded > UINT64_MAX - PBLE_FS_SAFETY_RESERVE) {
            nlr_pop();
            return PBLE_EIO;
        }
        uint64_t required = rounded + PBLE_FS_SAFETY_RESERVE;
        nlr_pop();
        return free_bytes >= required ? PBLE_OK : PBLE_ENOSPC;
    }
    return PBLE_EIO;
}

// F-10 resume-offset — see pble_fs.h. WORKER-ONLY (mp_vfs_* under nlr).
// Returns explicit status and initializes the running CRC/watermark only from
// an exact-length scan whose regular-file type and length survive a re-stat.
static uint8_t pble_fs_resume_prefix(const pble_fs_req_t *it,
                                     const char *dest_vfs_path,
                                     uint32_t total_size,
                                     uint32_t *resume_out,
                                     uint32_t *running_out) {
    *resume_out = 0;
    *running_out = 0xFFFFFFFFu;           // fresh-upload default

    // Build "<dest>.pbltmp" (same jailed sibling the transfer writes).
    char temp[PBLE_FS_PATH_BUF];
    size_t dl = strlen(dest_vfs_path);
    if (dl + (sizeof(PBLE_FS_TMP_SUFFIX) - 1) + 1 > sizeof(temp)) {
        return PBLE_ERANGE;
    }
    memcpy(temp, dest_vfs_path, dl);
    memcpy(temp + dl, PBLE_FS_TMP_SUFFIX, sizeof(PBLE_FS_TMP_SUFFIX));  // incl NUL

    uint32_t len;
    bool isdir;
    uint8_t st = fs_stat_path(it, temp, &len, &isdir);
    if (st == PBLE_ENOENT) {
        return PBLE_OK;
    }
    if (st != PBLE_OK) {
        return st == PBLE_NO_RSP ? st : PBLE_EIO;
    }
    bool isreg = !isdir;  // fs_stat_path admits only exact REG or exact DIR.
    if (!isreg || len > total_size) {
        return fs_remove_malformed_scratch(it, temp);
    }
    if (len == 0) {
        return PBLE_OK;
    }
    uint32_t running;
    st = fs_crc_prefix(it, temp, len, &running);
    if (st != PBLE_OK) {
        if (st == PBLE_NO_RSP) {
            return st;
        }
        return fs_remove_malformed_scratch(it, temp);
    }

    uint32_t checked_len;
    bool checked_isdir = false;
    st = fs_stat_path(it, temp, &checked_len, &checked_isdir);
    bool checked_isreg = st == PBLE_OK && !checked_isdir;
    if (st != PBLE_OK || !checked_isreg || checked_len != len) {
        if (st == PBLE_NO_RSP) {
            return st;
        }
        return fs_remove_malformed_scratch(it, temp);
    }
    *running_out = running;               // continued by later PUT_DATA
    *resume_out = len;
    return PBLE_OK;
}

// Abort one exactly-owned transfer. Cleanup failure overrides the originating
// protocol status with EIO. Cancellation stops further VFS effects and leaves a
// stale record for successor reconciliation instead of clearing newer state.
static uint8_t fs_put_abort(const pble_fs_req_t *it, uint8_t originating) {
    if (!fs_put_owned(it)) {
        return PBLE_NO_RSP;
    }

    char temp[PBLE_FS_PATH_BUF];
    taskENTER_CRITICAL(&g_fs_transfer_mux);
    if (!g_put_active ||
        g_put_generation != it->transfer_generation ||
        it->transfer_generation != g_fs_transfer_generation) {
        taskEXIT_CRITICAL(&g_fs_transfer_mux);
        return PBLE_NO_RSP;
    }
    memcpy(temp, g_put_temp, sizeof(temp));
    temp[sizeof(temp) - 1u] = '\0';
    taskEXIT_CRITICAL(&g_fs_transfer_mux);

    bool cleanup_failed = false;
    uint8_t close_status = fs_put_close(it);
    if (close_status == PBLE_NO_RSP) {
        return PBLE_NO_RSP;
    }
    if (close_status != PBLE_OK) {
        cleanup_failed = true;
    }

    if (temp[0] == '\0') {
        cleanup_failed = true;
    } else {
        if (!pble_fs_ticket_valid(it)) {
            return PBLE_NO_RSP;
        }
        nlr_buf_t nlr;
        if (nlr_push(&nlr) == 0) {
            mp_vfs_remove(fs_str(temp));
            bool cancelled = !pble_fs_ticket_valid(it);
            nlr_pop();
            if (cancelled) {
                return PBLE_NO_RSP;
            }
        } else {
            if (!pble_fs_ticket_valid(it)) {
                return PBLE_NO_RSP;
            }
            cleanup_failed = true;
        }

        uint32_t remaining_size;
        bool remaining_isdir;
        uint8_t absence = fs_stat_path(
            it, temp, &remaining_size, &remaining_isdir);
        if (absence == PBLE_NO_RSP) {
            return PBLE_NO_RSP;
        }
        if (absence != PBLE_ENOENT) {
            cleanup_failed = true;
        }
    }

    if (!fs_put_reset_owner(it)) {
        return PBLE_NO_RSP;
    }
    return cleanup_failed ? PBLE_EIO : originating;
}

static bool fs_put_publish(const pble_fs_req_t *it, mp_obj_t file,
                           const char *temp, const char *dest,
                           uint32_t total, uint32_t crc_target,
                           uint32_t watermark, uint32_t crc_running) {
    if (!pble_fs_ticket_valid(it)) {
        return false;
    }
    bool published = false;
    taskENTER_CRITICAL(&g_fs_transfer_mux);
    if (!g_fs_transfer_exhausted && !g_put_active &&
        it->transfer_generation == g_fs_transfer_generation) {
        g_put_generation = it->transfer_generation;
        g_put_active = true;
        memset(g_put_temp, 0, sizeof(g_put_temp));
        memset(g_put_dest, 0, sizeof(g_put_dest));
        memcpy(g_put_temp, temp, strlen(temp) + 1u);
        memcpy(g_put_dest, dest, strlen(dest) + 1u);
        g_put_total = total;
        g_put_crc_target = crc_target;
        g_put_watermark = watermark;
        g_put_crc_running = crc_running;
        g_put_latched = 0;
        MP_STATE_VM(pble_fs_put_file) = file;
        published = true;
    }
    taskEXIT_CRITICAL(&g_fs_transfer_mux);
    return published;
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

    // A reconnecting session may close/reclaim only an older generation. Do
    // that before deciding whether the single-transfer record is genuinely busy.
    uint8_t reconcile_status = fs_put_reconcile_stale(it);
    if (reconcile_status != PBLE_OK) {
        return reconcile_status;
    }
    if (fs_put_active_current(it)) {
        return PBLE_EBUSY;           // single active transfer (§5)
    }

    // temp = "<dest>.pbltmp" (same jailed directory; never routed through resolve,
    // which forbids the reserved suffix by design).
    char temp[PBLE_FS_PATH_BUF] = {0};
    size_t dl = strlen(dest);
    if (dl + (sizeof(PBLE_FS_TMP_SUFFIX) - 1) + 1 > sizeof(temp)) {
        return PBLE_ERANGE;
    }
    memcpy(temp, dest, dl);
    memcpy(temp + dl, PBLE_FS_TMP_SUFFIX, sizeof(PBLE_FS_TMP_SUFFIX));

    // Resume-on-reconnect (F-10): keep all candidate state local until the
    // generation-qualified publication cut below.
    // resume>0 → append to the existing prefix; resume==0 → "wb" truncates any
    // stale/over-size temp to 0 (the frozen over-size guard).
    uint32_t resume;
    uint32_t running;
    uint8_t resume_status = pble_fs_resume_prefix(
        it, dest, total, &resume, &running);
    if (resume_status != PBLE_OK) {
        return resume_status;
    }
    if (!pble_fs_ticket_valid(it)) {
        return PBLE_NO_RSP;
    }
    uint8_t space_status = fs_put_space_status(it, total - resume);
    if (space_status != PBLE_OK) {
        return space_status;
    }
    const char *mode = (resume > 0) ? "ab" : "wb";

    // Open the temp under nlr.
    nlr_buf_t nlr;
    uint8_t st;
    volatile mp_obj_t opened = MP_OBJ_NULL;
    if (nlr_push(&nlr) == 0) {
        opened = fs_open(it, pble_fs_ticket_valid, temp, mode);
        if (!pble_fs_ticket_valid(it)) {
            fs_close_local((mp_obj_t)opened);
            opened = MP_OBJ_NULL;
            nlr_pop();
            return PBLE_NO_RSP;
        }
        nlr_pop();
        st = PBLE_OK;
    } else {
        fs_close_local((mp_obj_t)opened);
        opened = MP_OBJ_NULL;
        st = fs_exc_to_status(MP_OBJ_FROM_PTR(nlr.ret_val));
    }
    if (st != PBLE_OK) {
        if (!pble_fs_ticket_valid(it)) {
            return PBLE_NO_RSP;
        }
        return st;
    }

    if (!fs_put_publish(it, (mp_obj_t)opened, temp, dest, total, crc,
                        resume, running)) {
        fs_put_close_local(it, (mp_obj_t)opened);
        opened = MP_OBJ_NULL;
        return PBLE_NO_RSP;
    }
    opened = MP_OBJ_NULL;            // the rooted active record now owns it

    le32(g_scratch + 1, resume);    // resume_offset = verified prefix length (§5)
    *extra = 4;
    return PBLE_OK;
}

// PUT_DATA: [offset:u32][bytes]. Go-Back-N, no reorder buffer. Always re-ACKs the
// current watermark; emits no RSP.
static void fs_do_put_data(const pble_fs_req_t *it) {
    if (!fs_put_owned(it)) {
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
        if (g_put_watermark > g_put_total ||
            n > (g_put_total - g_put_watermark)) {
            taskENTER_CRITICAL(&g_fs_transfer_mux);
            bool owned = g_put_active &&
                         g_put_generation == it->transfer_generation &&
                         it->transfer_generation == g_fs_transfer_generation;
            if (owned) {
                g_put_latched = PBLE_ERANGE;
            }
            taskEXIT_CRITICAL(&g_fs_transfer_mux);
            if (!owned) {
                return;
            }
            fs_put_ack(it);
            return;
        }
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
                    (void)fs_put_latch_owner(
                        it, pble_fs_errno_to_status(err));
                    break;
                }
                if (w == 0 || w > n - done) {
                    // A nominally successful stream write must make bounded
                    // forward progress. Otherwise this worker could spin
                    // forever or advance beyond the admitted input chunk.
                    (void)fs_put_latch_owner(it, PBLE_EIO);
                    break;
                }
                done += (uint32_t)w;
            }
            if (!g_put_latched) {
                // Advance + extend the streaming whole-file CRC together, only on a
                // full contiguous write, so the running CRC stays in lockstep with
                // the watermark (Go-Back-N never double-counts a dup/gap).
                uint32_t next_crc = crc32_update(
                    g_put_crc_running, bytes, n);
                taskENTER_CRITICAL(&g_fs_transfer_mux);
                bool commit = g_put_active &&
                              g_put_generation == it->transfer_generation &&
                              it->transfer_generation ==
                                  g_fs_transfer_generation;
                if (commit) {
                    g_put_crc_running = next_crc;
                    g_put_watermark += n;
                }
                taskEXIT_CRITICAL(&g_fs_transfer_mux);
                if (!commit) {
                    nlr_pop();
                    return;
                }
            }
            nlr_pop();
        } else {
            (void)fs_put_latch_owner(
                it, fs_exc_to_status(MP_OBJ_FROM_PTR(nlr.ret_val)));
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
    if (!fs_put_owned(it)) {
        bool record_active;
        taskENTER_CRITICAL(&g_fs_transfer_mux);
        record_active = g_put_active;
        taskEXIT_CRITICAL(&g_fs_transfer_mux);
        // Preserve the frozen END-without-BEGIN response. An old-generation END
        // remains silent and cannot act on any active successor record.
        return !record_active && pble_fs_ticket_valid(it)
                   ? PBLE_EBADREQ
                   : PBLE_NO_RSP;
    }
    if (it->len < 4) {
        return fs_put_abort(it, PBLE_EBADREQ);
    }
    uint32_t declared = rd32(it->payload);

    if (g_put_latched) {
        uint8_t st = g_put_latched;  // ENOSPC / EIO latched during DATA
        return fs_put_abort(it, st);
    }
    if (g_put_watermark != g_put_total) {
        return fs_put_abort(it, PBLE_ERANGE);  // short/over transfer
    }

    uint8_t close_status = fs_put_close(it);  // durability cut before rename
    if (close_status != PBLE_OK) {
        if (close_status == PBLE_NO_RSP) {
            return PBLE_NO_RSP;
        }
        return fs_put_abort(it, PBLE_EIO);
    }

    // Finalize the streaming whole-file CRC (maintained across PUT_DATA + re-seeded
    // over any resumed prefix by pble_fs_resume_prefix) — no temp re-scan needed
    // (NFR-PERF-2). The whole-file CRC is the ONLY correctness gate, so a resumed
    // bad/foreign prefix fails here → ECRC, temp deleted, old file kept (FR-FS-14).
    uint32_t crc = g_put_crc_running ^ 0xFFFFFFFFu;
    uint8_t st;
    if (crc != g_put_crc_target || crc != declared) {
        return fs_put_abort(it, PBLE_ECRC);  // target remains untouched
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
        return fs_put_abort(it, st);
    }
    if (!fs_put_reset_owner(it)) {
        return PBLE_NO_RSP;
    }
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
    if (fs_put_active_current(it) || it->get_active_at_enqueue) {
        return PBLE_EBUSY;
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
    if (fs_put_active_current(it) || it->get_active_at_enqueue) {
        return PBLE_EBUSY;
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
        if (!pble_fs_ticket_valid(it)) {
            return PBLE_NO_RSP;
        }
        st = fs_exc_to_status(MP_OBJ_FROM_PTR(nlr.ret_val));
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
    if (fs_put_active_current(it) || it->get_active_at_enqueue) {
        return PBLE_EBUSY;
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
    if (response_bearing && !pble_fs_ticket_valid(it)) {
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
    if (!pble_fs_ticket_valid(it)) {
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
    taskENTER_CRITICAL(&g_fs_transfer_mux);
    if (g_fs_transfer_generation == UINT64_MAX) {
        g_fs_transfer_exhausted = true;
    } else {
        g_fs_transfer_generation++;
    }
    g_get_active = false;
    g_get_generation = 0;
    fs_put_reset_locked();
    taskEXIT_CRITICAL(&g_fs_transfer_mux);
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
            taskENTER_CRITICAL(&g_fs_transfer_mux);
            g_enq.transfer_generation = g_fs_transfer_generation;
            bool generation_available = !g_fs_transfer_exhausted;
            g_enq.get_active_at_enqueue = generation_available &&
                g_get_active &&
                g_get_generation == g_fs_transfer_generation;
            taskEXIT_CRITICAL(&g_fs_transfer_mux);
            if (ticket != NULL) {
                g_enq.ticket = *ticket;
            } else {
                memset(&g_enq.ticket, 0, sizeof(g_enq.ticket));
            }
            g_enq.len = req->len;
            if (req->len > 0 && req->payload != NULL) {
                memcpy(g_enq.payload, req->payload, req->len);
            }
            if (generation_available &&
                xQueueSend(g_fs_q, &g_enq, 0) == pdTRUE) {
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
    uint64_t epoch = pble_vm_epoch_current();
    if (g_fs_registered && g_fs_registration_epoch == epoch) {
        return;
    }
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
    g_fs_registration_epoch = epoch;
    g_fs_registered = true;
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
