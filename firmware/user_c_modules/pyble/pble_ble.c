// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_ble — the PyBLE BLE agent as a native MicroPython USER_C_MODULE that OWNS
// NimBLE in C (ADR-0006: native C from day one; lean/fast/optimized firmware).
//
// Layer-1 boundary: this is the ONLY module that touches NimBLE. It brings up the
// peripheral, advertises `PyBLE-XXXX` (or the persisted label) filtered to the
// PBLE/1 Service UUID, registers exactly one primary GATT service with the three
// frozen characteristics —
//   RX   (Write / Write-Without-Response, app -> board)
//   TX   (Notify,                          board -> app)
//   INFO (Read,                            board -> app)
// negotiates MTU up to 247 (staying correct down to the BLE default 23), and moves
// the PBLE/1 byte stream: it reassembles §3.2 fragments off RX and hands the
// complete §3.1 message up to the protocol engine, and fragments already-encoded
// bytes down onto TX as Notifications. It NEVER decodes frames, computes CRC-32,
// authors DEVICE_INFO/caps, or reads NVS — it moves bytes only.
//
// Wire constants below MIRROR protocol.md §2 (GATT) and §3.2 (fragmentation);
// they are never redefined here. Any wire change goes through the
// firmware-architect and lands in protocol.md first.
//
// Clean-room: authored fresh against protocol.md + the public ESP-IDF NimBLE
// API. No proprietary source is referenced.
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>

#include "py/runtime.h"
#include "py/obj.h"
#ifndef PBLE_ENABLE_SPLASH_READINESS
#define PBLE_ENABLE_SPLASH_READINESS 0
#endif
#if PBLE_ENABLE_SPLASH_READINESS
#include "py/mpthread.h"   // bounded wait_ready releases the MicroPython GIL
#endif

#include "esp_log.h"
// FreeRTOS: the TX path is the sole exit for PBLE/1 bytes and is now called from
// several tasks (NimBLE host task for RSPs, the MicroPython worker _thread for
// CONSOLE_DATA/RUN_STATE). A recursive mutex serializes whole-message
// fragmentation so §3.2 fragments from concurrent senders never interleave.
#include "freertos/FreeRTOS.h"
#if PBLE_ENABLE_SPLASH_READINESS
#include "freertos/event_groups.h"
#endif
#include "freertos/semphr.h"
// The ESP-IDF NimBLE MYNEWT_VAL_* config maps CONFIG_BT_NIMBLE_* -> the values
// syscfg.h uses; the bt component force-includes it for its own sources, so we
// pull it in explicitly BEFORE any NimBLE header (else MYNEWT_VAL_* are undefined).
#include "esp_nimble_cfg.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "nimble/nimble_npl.h"   // ble_npl_callout: deferred link-tune (G5-impl)
#include "os/os_mbuf.h"
#include "os/os_mempool.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"

#include "pble_ble.h"

#define PBLE_TAG "pble"

// --- Wire constants — mirrored from protocol.md §2 / §3.2 (FROZEN v1.0) -------
// §2 MTU: app requests 247; usable per-packet payload = MTU-3 (ATT) - 1 (frag).
#define PBLE_ATT_HDR        3
#define PBLE_FRAG_HDR       1
#define PBLE_MTU_DEFAULT    23      // BLE default; transport stays correct here.
#define PBLE_MTU_PREFERRED  247
#define PBLE_MTU_MAX        247
// §3.2 FRAG_HDR bit layout: bit7 = FIRST, bit6 = LAST, bits5..0 = index mod 64.
#define PBLE_FRAG_FIRST     0x80
#define PBLE_FRAG_LAST      0x40
#define PBLE_FRAG_IDX_MASK  0x3F
#define PBLE_FRAG_IDX_MOD   64

// A small notification uses one msys_1 block for its data mbuf and one for the
// ATT command wrapper in pinned NimBLE. Bulk traffic must leave both available
// so a host-task STOP response can be submitted immediately. The terminal
// RUN_STATE(idle) reuses returned blocks after that response drains.
#define PBLE_TX_BULK_RESERVE_BLOCKS 2
#define PBLE_TX_ATT_WRAPPER_BLOCKS  1

#if PBLE_ENABLE_SPLASH_READINESS
// Boot-internal readiness snapshot (ADR-0024 / FR-SPLASH-4), exact image only.
#define PBLE_READY_BIT      BIT0
#endif

// --- Transport sizing (module-local design, not wire) ------------------------
// Bounded static reassembly buffer for a whole §3.1 message (D3: no per-message
// heap churn on the hot path). A message that would overflow is dropped; the app
// retransmits. Sized to comfortably hold caps/HELLO/DEVICE_INFO and directory
// listings while staying small for the ESP32-C3.
#define PBLE_MSG_MAX        2048
#define PBLE_INFO_MAX       512     // INFO/DEVICE_INFO read scratch
#define PBLE_NAME_MAX       32      // "PyBLE-XXXX" or a bounded label (<= 24 B)
// Largest single fragment packet = 1 (FRAG_HDR) + (MTU_MAX - 4) FRAGMENT DATA.
#define PBLE_FRAG_PKT_MAX   (PBLE_FRAG_HDR + (PBLE_MTU_MAX - PBLE_ATT_HDR - PBLE_FRAG_HDR))

// --- Link-tuning ladder — G5-impl download-ceiling tuning --------------------
// Link-layer / GAP-procedure / controller-config only; the PBLE/1 wire (MTU 247,
// opcodes, §3.1 framing, §3.2 fragmentation, chunk derivation) is UNTOUCHED.
// Order DLE -> PHY -> conn-param, split into two phases so no LL control
// procedure collides (NimBLE
// serializes them: a back-to-back pair returns BLE_HS_EALREADY and silently
// never runs on air) and so the conn-param update lands AFTER the link settles
// (iOS ignores a param update issued mid-connection-setup).

// Capability gate (compile-time, self-contained — no new board macro). 2M PHY
// exists only on BLE-5 silicon; compiled OUT on classic ESP32 (BLE 4.2 / BTDM)
// so a 2M request can never pollute a classic connect (the classic controller
// rejects it with rc=513 HCI Unknown Command).
#if defined(CONFIG_IDF_TARGET_ESP32S3) || defined(CONFIG_IDF_TARGET_ESP32C3)
#define PBLE_HAS_2M_PHY 1
#else
#define PBLE_HAS_2M_PHY 0
#endif

#define PBLE_LINK_TUNE_DELAY_MS  200   // settle window before rungs 2+3; a single
                                       // one-shot timer (never an event edge) is
                                       // the sole trigger. By 200 ms MTU exchange
                                       // + CCCD subscribe are done and the DLE LL
                                       // round-trip is long complete.
#define PBLE_CONN_ITVL_MIN       12    // 12 x 1.25 ms = 15 ms — the Apple minimum
                                       // grantable interval.
#define PBLE_CONN_ITVL_MAX       24    // 30 ms. Apple's acceptance rule requires
                                       // itvl_max >= itvl_min + 15 ms; the earlier
                                       // pinned min==max=12 violated it, so iOS
                                       // granting was luck-of-the-collision. HIL
                                       // 2026-07-04: an iPad central grants 15 ms.
#define PBLE_CONN_LATENCY        0     // no slave latency (small, per Apple rule).
#define PBLE_CONN_SUPTO          400   // 400 x 10 ms = 4 s supervision (Apple 2..6 s).
                                       // HIL 2026-07-04: iPad@15ms GET sessions on
                                       // classic died ~4 s in with SUPTO=2 s; the
                                       // longer window tolerates radio blips while
                                       // the reason-byte log below names real drops.
#define PBLE_CONN_CE_LEN         24    // max_ce_len hint, 0.625 ms units = 15 ms:
                                       // let the controller extend the connection
                                       // event instead of closing after one PDU.
#define PBLE_DLE_ATTEMPT_MAX     4     // bounded timer-progressed DLE submissions.
#define PBLE_PHY_ATTEMPT_MAX     4     // bounded timer-progressed 2M submissions.
#define PBLE_CP_ATTEMPT_MAX      3     // bounded re-fires after a CONN_UPDATE
                                       // collision (HCI 0x2A, seen as status=554
                                       // ~50% of the time on macOS).

// --- Peer modules (native cross-module contract; in the build as of S3) -------
// The protocol engine + identity modules are compiled alongside pble_ble now:
// pble_ble hands received bytes to the dispatcher and serves DEVICE_INFO / the
// advertised name from them.
#include "pble_proto.h"
#include "pble_info.h"
#include "pble_device_config.h"
#include "pble_runner.h"     // S4: RUN/STOP/SOFT_REBOOT registration
#include "pble_console.h"    // S4: CONSOLE_INPUT registration
#include "pble_fs.h"         // S5: FILE_* registration
#include "pble_lock.h"       // S6 F-18: single-writer token (SEC-3)
#include "pble_boot.h"       // S6 F-12: SET_AUTORUN registration

// S6 F-18 link-teardown hooks owned by peer modules (declared extern here — we
// only invoke them from the GAP DISCONNECT path; they are NOT ours). On link
// loss the single-writer token(s) MUST be released so a resuming reconnect is
// not locked out (SEC-3, FR-FS-16): the runtime frees its RUN/XFER writer lock
// and the fs bridge finalizes/aborts any in-flight transfer. Compatible
// forward declarations — pble_lock/pble_fs may later publish these in their own
// headers without conflict.
extern void pble_lock_on_disconnect(uint16_t conn);  // runtime-engineer (pble_lock)
extern void pble_fs_on_disconnect(void);             // storage-engineer (pble_fs)

// PBLE/1 UUIDs 7079626c-1ab1-4d50-9e3a-0000000000{01..04}, in NimBLE's
// little-endian on-air byte order (the string reversed). Only the final byte
// distinguishes Service (01) / RX (02) / TX (03) / INFO (04).
static const ble_uuid128_t PBLE_SVC_UUID = BLE_UUID128_INIT(
    0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x3a, 0x9e,
    0x50, 0x4d, 0xb1, 0x1a, 0x6c, 0x62, 0x79, 0x70);
static const ble_uuid128_t PBLE_RX_UUID = BLE_UUID128_INIT(
    0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x3a, 0x9e,
    0x50, 0x4d, 0xb1, 0x1a, 0x6c, 0x62, 0x79, 0x70);
static const ble_uuid128_t PBLE_TX_UUID = BLE_UUID128_INIT(
    0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x3a, 0x9e,
    0x50, 0x4d, 0xb1, 0x1a, 0x6c, 0x62, 0x79, 0x70);
static const ble_uuid128_t PBLE_INFO_UUID = BLE_UUID128_INIT(
    0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0x3a, 0x9e,
    0x50, 0x4d, 0xb1, 0x1a, 0x6c, 0x62, 0x79, 0x70);

static uint8_t  pble_addr_type;
static uint8_t  pble_addr[6];                       // NimBLE little-endian MAC
static char     pble_name[PBLE_NAME_MAX];           // advertised name
static bool     pble_started = false;
static bool     pble_synced = false;

static uint16_t pble_conn_handle = BLE_HS_CONN_HANDLE_NONE;
static uint16_t pble_mtu_val = PBLE_MTU_DEFAULT;    // negotiated ATT MTU
static uint16_t pble_tx_val_handle;                 // cached for Notifications

#if PBLE_ENABLE_SPLASH_READINESS
// Native-static so the object and observed state survive a MicroPython soft
// reset. Allocation is best-effort: BLE remains fully functional if this stays
// NULL, while the boot-only wait_ready API deterministically returns false.
static EventGroupHandle_t pble_ready_events;

static void pble_ready_set(void) {
    if (pble_ready_events != NULL) {
        xEventGroupSetBits(pble_ready_events, PBLE_READY_BIT);
    }
}

static void pble_ready_clear(void) {
    if (pble_ready_events != NULL) {
        xEventGroupClearBits(pble_ready_events, PBLE_READY_BIT);
    }
}

static void pble_ready_refresh(void) {
    if (pble_conn_handle != BLE_HS_CONN_HANDLE_NONE || ble_gap_adv_active()) {
        pble_ready_set();
    } else {
        pble_ready_clear();
    }
}
#else
// Generic images compile every splash-only transition and allocation to zero.
#define pble_ready_set()     ((void)0)
#define pble_ready_clear()   ((void)0)
#define pble_ready_refresh() ((void)0)
#endif

// ADR-0027 deferred link settlement: one NimBLE callout advances exactly one
// submitted phase at a time. Completion events can re-arm it, but the timer is
// the progress guarantee when a controller omits an event.
static struct ble_npl_callout pble_link_tune_co;

// Rung-1 (DLE) confirmation latch. NimBLE serializes LL control procedures: a
// set_data_len issued while the central runs its OWN early procedure (a BLE-5
// central starts feature/PHY exchanges right at connect) returns
// BLE_HS_EALREADY and the request silently never runs on air — the S3-only
// "still 1 chunk per event" failure. So the request is re-issued until
// DATA_LEN_CHG confirms max_tx_octets >= 244, bounded by a hard attempt cap;
// each re-issue happens where an LL slot is free (the deferred callout, or
// right after a completed CONN_UPDATE procedure).
static bool    pble_dle_confirmed = false;
static uint8_t pble_dle_attempts = 0;
static bool    pble_phy_confirmed_2m = false;
static uint8_t pble_phy_attempts = 0;
static bool    pble_cp_confirmed = false;
static uint8_t pble_cp_attempts = 0;
#if !PBLE_HAS_2M_PHY
static bool    pble_phy_classic_skip_logged = false;
#endif

static int pble_request_dle(uint16_t conn, const char *ctx) {
    if (pble_dle_confirmed || pble_dle_attempts >= PBLE_DLE_ATTEMPT_MAX) {
        return 0;
    }
    pble_dle_attempts++;
    int rc = ble_gap_set_data_len(conn, 251, 2120);
    // ERROR level: this build strips everything below ERROR
    // (CONFIG_LOG_DEFAULT_LEVEL=1), and the link-fact lines ARE the no-sniffer
    // bench evidence (§G5-impl G5i.4) — invisible evidence is none.
    ESP_LOGE(PBLE_TAG, "link tune req phase=dle attempt=%u context=%s rc=%d",
             pble_dle_attempts, ctx, rc);
    return rc;
}

// GAP-2 instrumentation (gates the G5i.2 host/controller pool bumps, applied by
// build-smith): per-session count of NULL-mbuf TX starvation (the host msys pool
// drained by in-flight notifications). Logged at DISCONNECT; observability only —
// it never changes the paced-TX pump's behavior.
static volatile uint32_t pble_tx_mbuf_starve = 0;

// TX serialization: guards the whole fragment-and-Notify sequence in
// pble_ble_notify so a multi-fragment message goes out atomically relative to
// any other sender (host task RSP vs. worker-thread CONSOLE_DATA/RUN_STATE).
// Recursive so an unforeseen same-thread nesting can never self-deadlock.
static SemaphoreHandle_t pble_tx_mutex;

// TX-drain signal for the paced notify path: BLE_GAP_EVENT_NOTIFY_TX (a
// notification actually left / controller space freed) gives this binary
// semaphore, and a congested streaming sender blocks on it instead of
// sleep-spinning. Event-driven backpressure — the F-164-class lesson: a timed
// retry at a 100 Hz tick truncates to zero and busy-spins, and every blind
// whole-message retry consumes more of the very mbuf pool it is waiting on.
static SemaphoreHandle_t pble_tx_drain_sem;

// §3.2 reassembly accumulator (single static buffer).
static uint8_t  pble_rx_buf[PBLE_MSG_MAX];
static size_t   pble_rx_len;
static bool     pble_rx_active;
static uint8_t  pble_rx_next_index;

// Header of the message being reassembled, captured from its FIRST fragment so
// an OVER-LONG message can still be REFUSED BY ID instead of vanishing. Without
// this, a RUN{source} carrying an editor buffer above the reassembly bound got
// no reply at all: the app waited out its 5 s RSP timeout with no status to
// explain it (measured cliff: source >= ~2038 B on a 2048 B buffer).
static bool     pble_rx_hdr_valid;
static uint8_t  pble_rx_hdr_type;
static uint8_t  pble_rx_hdr_op;
static uint8_t  pble_rx_hdr_id;

static void pble_advertise(void);

// --- §3.2 byte transport helpers --------------------------------------------

// Usable per-packet PBLE/1 payload (FR-BLE-8): MTU-3 (ATT) - 1 (frag header).
static inline size_t pble_payload_size(uint16_t mtu) {
    if (mtu < PBLE_ATT_HDR + PBLE_FRAG_HDR + 1) {
        return 1;   // never zero: a byte still moves at the smallest MTU.
    }
    return (size_t)(mtu - PBLE_ATT_HDR - PBLE_FRAG_HDR);
}

static void pble_reset_reassembly(void) {
    pble_rx_len = 0;
    pble_rx_active = false;
    pble_rx_next_index = 0;
    pble_rx_hdr_valid = false;
}

// Reassemble one RX packet (§3.2): strip the 1-byte FRAG_HDR, concatenate
// FRAGMENT DATA from FIRST through LAST (index increasing mod 64), then hand the
// complete §3.1 message up to the protocol engine. CRC/structure validation is
// pble_proto's — never done here. Gap/out-of-order fragments reset the buffer
// (the app retransmits); an over-long message is dropped, not truncated.
static void pble_rx_ingest(const uint8_t *pkt, size_t len, uint16_t conn) {
    if (len == 0) {
        return;
    }
    uint8_t hdr = pkt[0];
    bool first = (hdr & PBLE_FRAG_FIRST) != 0;
    bool last = (hdr & PBLE_FRAG_LAST) != 0;
    uint8_t index = hdr & PBLE_FRAG_IDX_MASK;

    if (first) {
        pble_rx_len = 0;
        pble_rx_active = true;
        pble_rx_next_index = index;
        // Latch the §3.1 header (VER TYPE OPCODE ID LEN) while it is still in
        // hand, so an over-long message can be answered by ID (below).
        pble_rx_hdr_valid = (len - 1) >= 4;
        if (pble_rx_hdr_valid) {
            pble_rx_hdr_type = pkt[2];
            pble_rx_hdr_op   = pkt[3];
            pble_rx_hdr_id   = pkt[4];
        }
    } else if (!pble_rx_active || index != pble_rx_next_index) {
        pble_reset_reassembly();
        return;
    }

    size_t data_len = len - 1;
    if (data_len > sizeof(pble_rx_buf) - pble_rx_len) {
        // Over the bounded buffer. NEVER silently drop a CMD: answer the
        // originating id with ERANGE (§8 "bad offset/length") so the client
        // gets a typed refusal instead of an unexplained timeout (§9 requires
        // a refusal, not silence). EVTs/RSPs have no one to answer, so they
        // just drop. The remaining fragments of this message are ignored: they
        // are non-FIRST and land on !pble_rx_active below.
        bool answerable = pble_rx_hdr_valid && pble_rx_hdr_type == PBLE_TYPE_CMD;
        uint8_t op = pble_rx_hdr_op, id = pble_rx_hdr_id;
        pble_reset_reassembly();
        if (answerable) {
            uint8_t status = PBLE_ERANGE;
            pble_proto_emit_id(PBLE_TYPE_RSP, op, id, &status, 1);
        }
        return;
    }
    memcpy(pble_rx_buf + pble_rx_len, pkt + 1, data_len);
    pble_rx_len += data_len;
    pble_rx_next_index = (uint8_t)((index + 1) % PBLE_FRAG_IDX_MOD);

    if (last) {
        size_t msg_len = pble_rx_len;
        pble_reset_reassembly();
        pble_proto_dispatch(pble_rx_buf, msg_len, conn);
    }
}

// Notify one fully-formed §3.2 packet (FRAG_HDR already in pkt[0]) on TX.
// Returns a PBLE_TX_* code so a streaming caller can distinguish a dropped link
// (abort) from transient host/controller backpressure (retry). A NULL mbuf means
// the host mbuf pool is drained by in-flight notifications — that is transient
// backpressure, and nothing was sent for this packet.
static int pble_msys1_num_free(void) {
    struct os_mempool *pool = NULL;
    struct os_mempool_info info;
    while ((pool = os_mempool_info_get_next(pool, &info)) != NULL) {
        if (strcmp(info.omi_name, "msys_1") == 0) {
            return info.omi_num_free;
        }
    }
    // Fail closed for bulk admission if the pinned pool cannot be identified.
    return 0;
}

static int pble_notify_packet(const uint8_t *pkt, size_t len,
                              uint8_t reserve_blocks) {
    struct os_mbuf *om = ble_hs_mbuf_from_flat(pkt, (uint16_t)len);
    if (om == NULL) {
        pble_tx_mbuf_starve++;   // GAP-2: host msys pool drained (pool-starve gate)
        return PBLE_TX_AGAIN;
    }
    // The data chain above is already charged to msys_1. Before a BULK submit,
    // preserve one block for this packet's ATT wrapper plus the two blocks a
    // subsequent small control notification needs. Query msys_1 specifically:
    // aggregate msys_1+msys_2 free space cannot satisfy these allocations.
    if (reserve_blocks > 0 &&
        pble_msys1_num_free() < PBLE_TX_ATT_WRAPPER_BLOCKS + reserve_blocks) {
        os_mbuf_free_chain(om);
        pble_tx_mbuf_starve++;
        return PBLE_TX_AGAIN;
    }
    // ble_gatts_notify_custom consumes the mbuf on both success and failure.
    int rc = ble_gatts_notify_custom(pble_conn_handle, pble_tx_val_handle, om);
    if (rc == 0) {
        return PBLE_TX_OK;
    }
    // A gone link is unrecoverable (abort the stream); anything else is treated
    // as transient flow control (the caller may pace and retry).
    if (rc == BLE_HS_ENOTCONN || rc == BLE_HS_ENOENT) {
        return PBLE_TX_NO_CONN;
    }
    return PBLE_TX_AGAIN;
}

// --- Frozen ble<->proto contract (exported, see pble_ble.h) ------------------

// Fragment + Notify one whole §3.1 message. Caller holds pble_tx_mutex so the
// emitted §3.2 fragment run is atomic w.r.t. other senders. Returns a PBLE_TX_*
// code: OK, NO_CONN (no link / link dropped), or AGAIN (transient backpressure).
static int pble_notify_message(const uint8_t *msg, size_t len) {
    if (pble_conn_handle == BLE_HS_CONN_HANDLE_NONE) {
        return PBLE_TX_NO_CONN;
    }
    size_t psize = pble_payload_size(pble_mtu_val);
    uint8_t pkt[PBLE_FRAG_PKT_MAX];

    if (len == 0) {
        pkt[0] = PBLE_FRAG_FIRST | PBLE_FRAG_LAST;  // one empty FIRST+LAST packet
        return pble_notify_packet(pkt, 1, 0);
    }

    size_t offset = 0;
    uint8_t index = 0;
    while (offset < len) {
        size_t chunk = len - offset;
        if (chunk > psize) {
            chunk = psize;
        }
        uint8_t hdr = (uint8_t)(index % PBLE_FRAG_IDX_MOD);
        if (index == 0) {
            hdr |= PBLE_FRAG_FIRST;
        }
        if (offset + chunk >= len) {
            hdr |= PBLE_FRAG_LAST;
        }
        pkt[0] = hdr;
        memcpy(pkt + 1, msg + offset, chunk);
        int rc = pble_notify_packet(pkt, chunk + 1, 0);
        if (rc != PBLE_TX_OK) {
            return rc;   // propagate NO_CONN (abort) vs AGAIN (retriable) verbatim
        }
        offset += chunk;
        index++;
    }
    return PBLE_TX_OK;
}

// Paced one-fragment TX. A retry serializes exactly one Notify attempt, releases
// the mutex, and only then waits. Complete PBLE messages therefore remain atomic
// while a control sender can acquire the mutex during bulk backpressure.
static int pble_ble_notify_paced_with_reserve(const uint8_t *msg, size_t len,
                                              uint32_t budget_ms,
                                              uint8_t reserve_blocks) {
    if (pble_tx_mutex == NULL || pble_tx_drain_sem == NULL) {
        return PBLE_TX_NO_CONN;
    }
    if (pble_conn_handle == BLE_HS_CONN_HANDLE_NONE) {
        return PBLE_TX_NO_CONN;
    }
    if (len > pble_payload_size(pble_mtu_val)) {
        return PBLE_TX_OVERSIZE;
    }

    uint8_t pkt[PBLE_FRAG_PKT_MAX];
    pkt[0] = PBLE_FRAG_FIRST | PBLE_FRAG_LAST;
    if (len > 0) {
        memcpy(pkt + 1, msg, len);
    }

    TickType_t ticks = pdMS_TO_TICKS(budget_ms);
    if (ticks == 0) {
        ticks = 1;
    }
    TickType_t started = xTaskGetTickCount();
    const TickType_t max_slice = pdMS_TO_TICKS(15) ? pdMS_TO_TICKS(15) : 1;

    for (;;) {
        TickType_t elapsed = xTaskGetTickCount() - started;  // wrap-safe
        if (elapsed >= ticks) {
            return PBLE_TX_AGAIN;
        }
        TickType_t remaining = ticks - elapsed;
        if (xSemaphoreTakeRecursive(pble_tx_mutex, remaining) != pdTRUE) {
            return PBLE_TX_AGAIN;
        }
        int rc = pble_notify_packet(pkt, len + 1, reserve_blocks);
        xSemaphoreGiveRecursive(pble_tx_mutex);
        if (rc != PBLE_TX_AGAIN) {
            return rc;
        }

        elapsed = xTaskGetTickCount() - started;
        if (elapsed >= ticks) {
            return PBLE_TX_AGAIN;
        }
        TickType_t slice = ticks - elapsed;
        if (slice > max_slice) {
            slice = max_slice;
        }
        xSemaphoreTake(pble_tx_drain_sem, slice);
    }
}

int pble_ble_notify_paced(const uint8_t *msg, size_t len, uint32_t budget_ms) {
    return pble_ble_notify_paced_with_reserve(
        msg, len, budget_ms, PBLE_TX_BULK_RESERVE_BLOCKS);
}

int pble_ble_notify_control_paced(const uint8_t *msg, size_t len,
                                  uint32_t budget_ms) {
    return pble_ble_notify_paced_with_reserve(msg, len, budget_ms, 0);
}

// Sole TX path (FR-BLE-3/10): fragment already-encoded PBLE/1 bytes to
// payload_size(mtu) and Notify each §3.2 packet on TX. Byte-identical to the
// receiver's reassembly. Returns PBLE_TX_OK / PBLE_TX_NO_CONN / PBLE_TX_AGAIN.
//
// Concurrency (FR-BLE-11): callable from the NimBLE host task (dispatch RSP),
// the MicroPython runner worker (CONSOLE_DATA/RUN_STATE), or the fs-worker
// (FILE_GET_DATA/END, FILE_PUT_ACK, async FILE_* RSPs). The recursive mutex
// makes each message's fragment run atomic so concurrent senders never interleave
// on TX (the app has a single reassembly buffer). The critical section is bounded
// to ONE message's fragments and never blocks on the peer, so a busy file
// transfer streaming from the fs-worker cannot starve a host-task STOP RSP, and
// the underlying NimBLE Notify holds its own host mutex. No bytes are queued: on
// a full link a packet is not buffered — the transport returns PBLE_TX_AGAIN and
// the streaming caller paces/retries on its own task (never on the host task);
// on an absent/dropped link it returns PBLE_TX_NO_CONN and the caller aborts.
// Either way there is no unbounded buffering (NFR-PERF-2).
int pble_ble_notify(const uint8_t *msg, size_t len) {
    if (pble_tx_mutex == NULL) {
        return PBLE_TX_NO_CONN;          // not brought up yet — no link to send on.
    }
    xSemaphoreTakeRecursive(pble_tx_mutex, portMAX_DELAY);
    int rc = pble_notify_message(msg, len);
    xSemaphoreGiveRecursive(pble_tx_mutex);
    return rc;
}

// FR-BLE-7/8: the negotiated ATT MTU (247 once the central requests it, the BLE
// default until then). Sizes proto/storage buffers and DEVICE_INFO.mtu.
uint16_t pble_ble_mtu(void) {
    return pble_mtu_val;
}

// FR-BLE-12: replace the advertised name (label-else-`PyBLE-XXXX`) and, if not
// connected, re-advertise pre-connect so the change shows in the scan list. The
// name is display-only — never an access/trust/routing signal (SEC-5/7/11).
void pble_ble_set_adv_name(const char *name) {
    if (name == NULL) {
        return;
    }
    strncpy(pble_name, name, sizeof(pble_name) - 1);
    pble_name[sizeof(pble_name) - 1] = '\0';
    if (pble_synced) {
        ble_svc_gap_device_name_set(pble_name);
        if (pble_conn_handle == BLE_HS_CONN_HANDLE_NONE) {
            ble_gap_adv_stop();
            pble_advertise();
        }
    }
}

// --- GATT service ------------------------------------------------------------

// RX access: a Write / Write-Without-Response copies the fragment out of the
// mbuf and feeds §3.2 reassembly.
static int pble_rx_access(uint16_t conn_handle, uint16_t attr_handle,
                          struct ble_gatt_access_ctxt *ctxt, void *arg) {
    (void)attr_handle;
    (void)arg;
    if (ctxt->op != BLE_GATT_ACCESS_OP_WRITE_CHR) {
        return BLE_ATT_ERR_UNLIKELY;
    }
    uint8_t frag[PBLE_FRAG_PKT_MAX];
    uint16_t copied = 0;
    if (OS_MBUF_PKTLEN(ctxt->om) > sizeof(frag)) {
        return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    }
    if (ble_hs_mbuf_to_flat(ctxt->om, frag, sizeof(frag), &copied) != 0) {
        return BLE_ATT_ERR_UNLIKELY;
    }
    pble_rx_ingest(frag, copied, conn_handle);
    return 0;
}

// INFO access: a Read returns the DEVICE_INFO-equivalent payload VERBATIM
// (FR-BLE-4). The bytes are authored by pble_info — this module only serves them.
static int pble_info_access(uint16_t conn_handle, uint16_t attr_handle,
                            struct ble_gatt_access_ctxt *ctxt, void *arg) {
    (void)conn_handle;
    (void)attr_handle;
    (void)arg;
    if (ctxt->op != BLE_GATT_ACCESS_OP_READ_CHR) {
        return BLE_ATT_ERR_UNLIKELY;
    }
    uint8_t info[PBLE_INFO_MAX];
    size_t n = pble_info_device_info(info, sizeof(info));
    if (n > sizeof(info)) {
        n = sizeof(info);
    }
    if (os_mbuf_append(ctxt->om, info, (uint16_t)n) != 0) {
        return BLE_ATT_ERR_INSUFFICIENT_RES;
    }
    return 0;
}

// TX access: the characteristic is Notify-only (the board pushes values via
// ble_gatts_notify_custom). NimBLE's ble_gatts_chr_is_sane still requires a
// non-NULL access_cb on EVERY characteristic, so this stub refuses direct reads.
static int pble_tx_access(uint16_t conn_handle, uint16_t attr_handle,
                          struct ble_gatt_access_ctxt *ctxt, void *arg) {
    (void)conn_handle;
    (void)attr_handle;
    (void)ctxt;
    (void)arg;
    return BLE_ATT_ERR_READ_NOT_PERMITTED;
}

// One primary GATT service with exactly RX (W/WWR), TX (Notify), INFO (Read).
static const struct ble_gatt_svc_def pble_gatt_svcs[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = &PBLE_SVC_UUID.u,
        .characteristics = (struct ble_gatt_chr_def[]){
            {
                .uuid = &PBLE_RX_UUID.u,
                .access_cb = pble_rx_access,
                .flags = BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP,
            },
            {
                .uuid = &PBLE_TX_UUID.u,
                .access_cb = pble_tx_access,     // Notify-only; cb required by NimBLE
                .val_handle = &pble_tx_val_handle,
                .flags = BLE_GATT_CHR_F_NOTIFY,
            },
            {
                .uuid = &PBLE_INFO_UUID.u,
                .access_cb = pble_info_access,
                .flags = BLE_GATT_CHR_F_READ,
            },
            { 0 },
        },
    },
    { 0 },
};

static int pble_gatt_register(void) {
    int rc = ble_gatts_count_cfg(pble_gatt_svcs);
    if (rc != 0) {
        return rc;
    }
    return ble_gatts_add_svcs(pble_gatt_svcs);
}

// --- G5-impl deferred link-tune (Phase B) ------------------------------------

// Rung 2 — request the 2M-capable preference on BLE-5 chips. The helper is
// compiled out on classic ESP32 so that controller can never see the command.
#if PBLE_HAS_2M_PHY
static int pble_request_phy(uint16_t conn, const char *ctx) {
    if (pble_phy_confirmed_2m || pble_phy_attempts >= PBLE_PHY_ATTEMPT_MAX) {
        return 0;
    }
    pble_phy_attempts++;
    int rc = ble_gap_set_prefered_le_phy(conn,
                                         BLE_GAP_LE_PHY_1M_MASK | BLE_GAP_LE_PHY_2M_MASK,
                                         BLE_GAP_LE_PHY_1M_MASK | BLE_GAP_LE_PHY_2M_MASK,
                                         BLE_GAP_LE_PHY_CODED_ANY);
    ESP_LOGE(PBLE_TAG, "link tune req phase=phy attempt=%u context=%s rc=%d",
             pble_phy_attempts, ctx, rc);
    return rc;
}
#endif

// Rung 3 — request the Apple-fast connection-parameter range. update_params is
// a 4.x procedure issued on ALL chips; a non-zero rc is non-fatal (the link keeps
// whatever interval the central granted). Returns the NimBLE rc.
static int pble_request_conn_param(uint16_t conn, const char *ctx) {
    struct ble_gap_upd_params params = {
        .itvl_min = PBLE_CONN_ITVL_MIN,
        .itvl_max = PBLE_CONN_ITVL_MAX, // min+15ms span per the Apple accept rule
        .latency = PBLE_CONN_LATENCY,
        .supervision_timeout = PBLE_CONN_SUPTO,
        .min_ce_len = 0,
        .max_ce_len = PBLE_CONN_CE_LEN, // hint: pack the event, don't close early
    };
    if (pble_cp_confirmed || pble_cp_attempts >= PBLE_CP_ATTEMPT_MAX) {
        return 0;
    }
    pble_cp_attempts++;
    int rc = ble_gap_update_params(conn, &params);
    ESP_LOGE(PBLE_TAG, "link tune req phase=conn-param attempt=%u context=%s rc=%d",
             pble_cp_attempts, ctx, rc);
    return rc;
}

// One-shot callout body: each invocation submits at most one LL/GAP procedure,
// then re-arms itself. That keeps DLE, PHY, and connection parameters in
// separate settle windows and guarantees bounded progress even when an IDF /
// controller pair omits a completion event. Idempotent after link teardown.
static void pble_link_tune(struct ble_npl_event *ev) {
    (void)ev;
    uint16_t conn = pble_conn_handle;
    if (conn == BLE_HS_CONN_HANDLE_NONE) {
        return;                          // link already dropped — do nothing.
    }
    // Rung 1 gate: a re-issued DLE needs the LL slot to itself. Even the final
    // submission re-arms the timer: with no completion event, the next callout
    // observes the exhausted budget and advances to the following phase.
    if (!pble_dle_confirmed && pble_dle_attempts < PBLE_DLE_ATTEMPT_MAX) {
        pble_request_dle(conn, "timer");
        ble_npl_callout_reset(&pble_link_tune_co,
            ble_npl_time_ms_to_ticks32(PBLE_LINK_TUNE_DELAY_MS));
        return;
    }
#if PBLE_HAS_2M_PHY
    if (!pble_phy_confirmed_2m && pble_phy_attempts < PBLE_PHY_ATTEMPT_MAX) {
        const char *ctx = pble_phy_attempts == 0 ? "timer" : "retry";
        pble_request_phy(conn, ctx);
        ble_npl_callout_reset(&pble_link_tune_co,
            ble_npl_time_ms_to_ticks32(PBLE_LINK_TUNE_DELAY_MS));
        return;
    }
#else
    if (!pble_phy_classic_skip_logged) {
        ESP_LOGE(PBLE_TAG, "link tune skip phase=phy context=classic-compiled-out");
        pble_phy_classic_skip_logged = true;
    }
#endif
    // Rung 3 — request 15..30 ms only after the preceding rung has had its own
    // callout. Re-arm after every accepted or rejected submission so a missing
    // CONN_UPDATE event cannot strand this terminal phase.
    if (!pble_cp_confirmed && pble_cp_attempts < PBLE_CP_ATTEMPT_MAX) {
        const char *ctx = pble_cp_attempts == 0 ? "timer" : "retry";
        pble_request_conn_param(conn, ctx);
        ble_npl_callout_reset(&pble_link_tune_co,
            ble_npl_time_ms_to_ticks32(PBLE_LINK_TUNE_DELAY_MS));
        return;
    }
}

// --- GAP / advertising -------------------------------------------------------

static int pble_gap_event(struct ble_gap_event *event, void *arg) {
    (void)arg;
    switch (event->type) {
        case BLE_GAP_EVENT_CONNECT:
            if (event->connect.status == 0) {
                pble_conn_handle = event->connect.conn_handle;
                pble_ready_refresh();
                pble_reset_reassembly();
                pble_tx_mbuf_starve = 0;        // fresh per-session GAP-2 count
                ble_npl_callout_stop(&pble_link_tune_co);
                pble_dle_confirmed = false;
                pble_dle_attempts = 0;
                pble_phy_confirmed_2m = false;
                pble_phy_attempts = 0;
                pble_cp_confirmed = false;
                pble_cp_attempts = 0;
#if !PBLE_HAS_2M_PHY
                pble_phy_classic_skip_logged = false;
#endif
                // Rung 1 — LE Data Length Extension, first attempt, ALL chips
                // (classic 4.2 supports DLE). Without it a 229 B chunk shreds into
                // ~9×27 B LL PDUs and streaming collapses to ~1 chunk per
                // connection event. Confirmed by DATA_LEN_CHG; re-issued from the
                // tune callout / post-CONN_UPDATE until confirmed or capped
                // (the EALREADY collision with a BLE-5 central's own early LL
                // procedures is the S3-only DLE-loss mode). §G5-impl rung 1.
                pble_request_dle(pble_conn_handle, "connect");
                // The callout advances all remaining bounded submissions even
                // when the controller emits no completion event.
                ble_npl_callout_reset(&pble_link_tune_co,
                    ble_npl_time_ms_to_ticks32(PBLE_LINK_TUNE_DELAY_MS));
            } else {
                pble_ready_clear();
                pble_advertise();       // connection failed — keep advertising
            }
            break;
        case BLE_GAP_EVENT_DISCONNECT:
            // Disarm any pending link-tune so no stale rung fires into the next
            // session, then clear every phase latch and submission budget.
            ble_npl_callout_stop(&pble_link_tune_co);
            pble_dle_confirmed = false;
            pble_dle_attempts = 0;
            pble_phy_confirmed_2m = false;
            pble_phy_attempts = 0;
            pble_cp_confirmed = false;
            pble_cp_attempts = 0;
#if !PBLE_HAS_2M_PHY
            pble_phy_classic_skip_logged = false;
#endif
            // Link-fact evidence (ERROR level — this build strips below it): the
            // HCI disconnect REASON names the killer (0x08 supervision timeout,
            // 0x13 remote terminated, 0x16 local host), and the GAP-2 NULL-mbuf
            // starvation count gates the G5i.2 pool bumps. HIL 2026-07-04: iPad
            // GET sessions died undiagnosed because the reason was not logged.
            ESP_LOGE(PBLE_TAG, "disconnect reason=%d (0x%02x)",
                     event->disconnect.reason, (unsigned)event->disconnect.reason);
            ESP_LOGE(PBLE_TAG, "link tune session end tx_mbuf_starve_count=%lu",
                     (unsigned long)pble_tx_mbuf_starve);
            pble_conn_handle = BLE_HS_CONN_HANDLE_NONE;
            pble_ready_clear();
            pble_mtu_val = PBLE_MTU_DEFAULT;
            pble_reset_reassembly();
            // F-18/SEC-3: release the single-writer token(s) and finalize any
            // in-flight file transfer BEFORE re-advertising, so a resuming
            // reconnect is never locked out by a stale writer (FR-FS-16). These
            // are peer-owned; we only trigger them on teardown.
            pble_lock_on_disconnect(event->disconnect.conn.conn_handle);
            pble_fs_on_disconnect();
            pble_advertise();           // link outlives the session (FR-BLE-11)
            break;
        case BLE_GAP_EVENT_ENC_CHANGE:
            // F-18/SEC-1: the central initiated pairing/encryption. Encryption
            // is AVAILABLE + USED but NOT access-gating (no per-char ENC flag),
            // so nothing changes in our byte transport — we just consume the
            // event so NimBLE's SM does not assert on an unhandled callback.
            ESP_LOGI(PBLE_TAG, "enc change; status=%d handle=%u",
                     event->enc_change.status, event->enc_change.conn_handle);
            break;
        case BLE_GAP_EVENT_ADV_COMPLETE:
            if (pble_conn_handle == BLE_HS_CONN_HANDLE_NONE) {
                pble_ready_clear();
                pble_advertise();
            }
            break;
        case BLE_GAP_EVENT_MTU:
            pble_mtu_val = event->mtu.value;   // FR-BLE-7: accept up to 247
            break;
        case BLE_GAP_EVENT_PHY_UPDATE_COMPLETE:
            ESP_LOGE(PBLE_TAG, "link tune complete phase=phy status=%d tx=%u rx=%u",
                     event->phy_updated.status,
                     event->phy_updated.tx_phy, event->phy_updated.rx_phy);
#if PBLE_HAS_2M_PHY
            if (pble_phy_attempts > 0 &&
                event->phy_updated.status == 0 &&
                event->phy_updated.tx_phy == 2 &&
                event->phy_updated.rx_phy == 2) {
                pble_phy_confirmed_2m = true;
            }
            // Completion can move the next timer window forward, but is never
            // required: every submission already left a callout armed.
            if (pble_conn_handle != BLE_HS_CONN_HANDLE_NONE) {
                ble_npl_callout_reset(&pble_link_tune_co,
                    ble_npl_time_ms_to_ticks32(PBLE_LINK_TUNE_DELAY_MS));
            }
#endif
            break;
        case BLE_GAP_EVENT_DATA_LEN_CHG:
            // Rung-1 confirmation (ERROR level, G5i.4): DLE landed when
            // max_tx_octets >= 244; stuck near 27 = refused/lost — the retry
            // latch keeps re-issuing until confirmed or capped.
            if (event->data_len_chg.max_tx_octets >= 244) {
                pble_dle_confirmed = true;
            }
            ESP_LOGE(PBLE_TAG, "link tune complete phase=dle max_tx_octets=%u max_tx_time_us=%u",
                     event->data_len_chg.max_tx_octets,
                     event->data_len_chg.max_tx_time);
            if (pble_conn_handle != BLE_HS_CONN_HANDLE_NONE) {
                ble_npl_callout_reset(&pble_link_tune_co,
                    ble_npl_time_ms_to_ticks32(PBLE_LINK_TUNE_DELAY_MS));
            }
            break;
        case BLE_GAP_EVENT_CONN_UPDATE: {
            // Bench confirmation (ERROR level): expect the 15 ms interval
            // (itvl 12) granted. The event carries only status, so read the
            // descriptor for the interval actually in force (G5i.4).
            struct ble_gap_conn_desc desc;
            uint16_t itvl = 0;
            if (ble_gap_conn_find(event->conn_update.conn_handle, &desc) == 0) {
                itvl = desc.conn_itvl;
            }
            ESP_LOGE(PBLE_TAG, "link tune complete phase=conn-param status=%d interval_units=%u",
                     event->conn_update.status, itvl);
            if (pble_cp_attempts > 0 &&
                event->conn_update.status == 0 &&
                itvl >= PBLE_CONN_ITVL_MIN &&
                itvl <= PBLE_CONN_ITVL_MAX) {
                pble_cp_confirmed = true;
                ble_npl_callout_stop(&pble_link_tune_co);
            } else if (pble_conn_handle != BLE_HS_CONN_HANDLE_NONE &&
                       pble_cp_attempts < PBLE_CP_ATTEMPT_MAX) {
                ble_npl_callout_reset(&pble_link_tune_co,
                    ble_npl_time_ms_to_ticks32(PBLE_LINK_TUNE_DELAY_MS));
            }
            break;
        }
        case BLE_GAP_EVENT_NOTIFY_TX:
            // A notification cleared the host/controller: wake a paced sender
            // waiting out congestion (binary semaphore — saturates at one).
            // Status-aware: NimBLE fires this SYNCHRONOUSLY at submit time (never
            // on controller credit return — G5 synthesis H3), so a give on a
            // FAILED submit would wake the pump into an immediate identical
            // failure — a hot-spin. Only a successful submit means pool/queue
            // space actually moved.
            if (event->notify_tx.status == 0 && pble_tx_drain_sem != NULL) {
                xSemaphoreGive(pble_tx_drain_sem);
            }
            break;
        default:
            break;
    }
    return 0;
}

static void pble_advertise(void) {
    struct ble_hs_adv_fields fields;
    struct ble_hs_adv_fields rsp;
    struct ble_gap_adv_params advp;

    // Adv packet: Flags + Complete 128-bit Service UUID (so scans filter to it).
    memset(&fields, 0, sizeof(fields));
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.uuids128 = (ble_uuid128_t *)&PBLE_SVC_UUID;
    fields.num_uuids128 = 1;
    fields.uuids128_is_complete = 1;
    if (ble_gap_adv_set_fields(&fields) != 0) {
        pble_ready_refresh();
        return;
    }

    // Scan response: the Complete Local Name (label, else PyBLE-XXXX).
    memset(&rsp, 0, sizeof(rsp));
    rsp.name = (uint8_t *)pble_name;
    rsp.name_len = strlen(pble_name);
    rsp.name_is_complete = 1;
    if (ble_gap_adv_rsp_set_fields(&rsp) != 0) {
        pble_ready_refresh();
        return;
    }

    memset(&advp, 0, sizeof(advp));
    advp.conn_mode = BLE_GAP_CONN_MODE_UND;   // connectable
    advp.disc_mode = BLE_GAP_DISC_MODE_GEN;   // general discoverable
    int rc = ble_gap_adv_start(pble_addr_type, NULL, BLE_HS_FOREVER, &advp,
                               pble_gap_event, NULL);
    if (rc == 0 || (rc == BLE_HS_EALREADY && ble_gap_adv_active())) {
        pble_ready_set();
    } else {
        pble_ready_refresh();
    }
}

// Resolve the advertised name: the persisted label (via pble_device_config, once
// it lands) else the default `PyBLE-XXXX` derived from the last two MAC bytes
// (uppercase hex) — stable across reboots, ~unique per board (FR-BLE-5/12).
static void pble_refresh_name(void) {
    char buf[PBLE_NAME_MAX];
    size_t n = pble_dc_adv_name(buf, sizeof(buf));
    if (n > 0 && n < sizeof(buf)) {
        memcpy(pble_name, buf, n);
        pble_name[n] = '\0';
        return;
    }
    snprintf(pble_name, sizeof(pble_name), "PyBLE-%02X%02X",
             pble_addr[1], pble_addr[0]);
}

static void pble_on_sync(void) {
    // Ensure an identity address, cache it, then set the preferred MTU and the
    // advertised name before we start advertising.
    ble_hs_util_ensure_addr(0);
    if (ble_hs_id_infer_auto(0, &pble_addr_type) != 0) {
        return;
    }
    ble_hs_id_copy_addr(pble_addr_type, pble_addr, NULL);
    ble_att_set_preferred_mtu(PBLE_MTU_PREFERRED);
    pble_refresh_name();
    ble_svc_gap_device_name_set(pble_name);
    pble_synced = true;
    pble_advertise();
}

static void pble_on_reset(int reason) {
    pble_synced = false;
    pble_conn_handle = BLE_HS_CONN_HANDLE_NONE;
    pble_ready_clear();
    ESP_LOGW(PBLE_TAG, "nimble reset; reason=%d", reason);
}

// --- SEC-1 link-layer pairing/encryption baseline (F-18) ---------------------
// Configure the NimBLE Security Manager for the SEC-1 "personal board on a
// workbench" posture (protocol.md §10, specs.md §9 SEC-1/2). The link is
// Just-Works (no passkey — the board is screenless), LE Secure Connections, and
// bonding: pairing/encryption is AVAILABLE and USED whenever the central
// initiates it, and bonded keys let a re-pair be silent.
//
// CRITICAL — this is NOT access-gating. The RX/TX/INFO characteristics carry NO
// per-characteristic encryption-permission flag (no BLE_GATT_CHR_F_READ_ENC /
// _WRITE_ENC in pble_gatt_svcs above), so a normal central — the app, or
// bleak/CoreBluetooth on macOS — connects and exchanges PBLE/1 with NO mandatory
// pairing step (SEC-2). Encryption is negotiated only if the central asks for
// it; the byte transport is identical either way. MITM is off (NO_INPUT_OUTPUT
// has no way to confirm a passkey). Called from pble_ble_init before the host
// starts advertising, so the SM config is in place before any connection.
void pble_ble_sm_config(void) {
    ble_hs_cfg.sm_io_cap = BLE_HS_IO_NO_INPUT_OUTPUT;   // screenless: Just-Works
    ble_hs_cfg.sm_sc = 1;          // LE Secure Connections (legacy also built in)
    ble_hs_cfg.sm_bonding = 1;     // persist keys (MAX_BONDS=3): silent re-pair
    ble_hs_cfg.sm_mitm = 0;        // Just-Works — no man-in-the-middle protection
    // Standard key distribution for a bonded encrypted link (ENC + ID/IRK).
    ble_hs_cfg.sm_our_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;
    ble_hs_cfg.sm_their_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;
}

static void pble_host_task(void *param) {
    (void)param;
    nimble_port_run();                  // returns only on nimble_port_stop()
    nimble_port_freertos_deinit();
}

// Bring up NimBLE + the GATT service + advertising. Idempotent; non-blocking
// (the host task + on_sync run asynchronously). See pble_ble.h.
void pble_ble_init(void) {
#if PBLE_ENABLE_SPLASH_READINESS
    // Retry a previous best-effort allocation before the idempotent fast path.
    // If NimBLE already runs, refresh gives a newly recovered event truthful
    // advertising/connection state instead of leaving its initial bit clear.
    if (pble_ready_events == NULL) {
        pble_ready_events = xEventGroupCreate();
    }
#endif
    if (pble_started) {
        pble_ready_refresh();
        return;
    }
    // Create the TX serialization mutex before any task can call the notify
    // path (the worker _thread is launched after init_agent()).
    if (pble_tx_mutex == NULL) {
        pble_tx_mutex = xSemaphoreCreateRecursiveMutex();
        if (pble_tx_mutex == NULL) {
            mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("tx mutex alloc failed"));
        }
    }
    if (pble_tx_drain_sem == NULL) {
        pble_tx_drain_sem = xSemaphoreCreateBinary();
        if (pble_tx_drain_sem == NULL) {
            mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("tx drain sem alloc failed"));
        }
    }
    if (nimble_port_init() != 0) {
        mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("nimble port init failed"));
    }
    // G5-impl: init the one-shot deferred link-tune callout on the default eventq
    // (host-task context). Armed per CONNECT, it fires rungs 2+3 (PHY + conn-param)
    // after the settle window. The eventq exists once nimble_port_init succeeds.
    ble_npl_callout_init(&pble_link_tune_co, nimble_port_get_dflt_eventq(),
                         pble_link_tune, NULL);
    ble_hs_cfg.sync_cb = pble_on_sync;
    ble_hs_cfg.reset_cb = pble_on_reset;
    pble_ble_sm_config();           // F-18 SEC-1: Just-Works pairing, non-gating

    ble_svc_gap_init();
    ble_svc_gatt_init();
    if (pble_gatt_register() != 0) {
        mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("gatt register failed"));
    }

    nimble_port_freertos_init(pble_host_task);
    pble_started = true;
}

// --- MicroPython module shim (frozen _boot.py calls pble_ble.init_agent()) ---

static mp_obj_t pble_ble_init_agent(void) {
    // Identity first (device_id + persisted label), then register the S3 opcode
    // handlers into pble_proto's dispatch, then bring up NimBLE + GATT + adv.
    pble_dc_init();
    pble_lock_register();            // S6 F-18: single active-writer token (SEC-3)
    pble_proto_register(PBLE_OP_HELLO, pble_info_hello);
    pble_proto_register(PBLE_OP_DEVICE_INFO, pble_info_device_info_cmd);
    pble_proto_register(PBLE_OP_SET_LABEL, pble_dc_set_label_cmd);
    pble_dc_identify_register();     // S4 F-23: 0x51 SET_IDENTIFY_LED / 0x52 IDENTIFY
    pble_runner_register();          // S4 F-04/05/06: 0x20 RUN / 0x21 STOP / 0x22 SOFT_REBOOT
    pble_console_register();         // S4 F-07: 0x31 CONSOLE_INPUT
    pble_fs_register();              // S5 F-08/09/17: 0x10..0x1A FILE_*
    pble_boot_register();            // S6 F-12: 0x23 SET_AUTORUN
    pble_ble_init();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(pble_ble_init_agent_obj, pble_ble_init_agent);

#if PBLE_ENABLE_SPLASH_READINESS
static mp_obj_t pble_ble_wait_ready(mp_obj_t timeout_in) {
    if (!mp_obj_is_int(timeout_in)) {
        mp_raise_TypeError(MP_ERROR_TEXT("timeout_ms must be an integer"));
    }
    mp_int_t timeout_ms = mp_obj_get_int(timeout_in);
    if (timeout_ms < 0 || timeout_ms > 1500) {
        mp_raise_ValueError(MP_ERROR_TEXT("timeout_ms must be 0..1500"));
    }
    if (pble_ready_events == NULL) {
        return mp_const_false;
    }

    TickType_t ticks = pdMS_TO_TICKS((uint32_t)timeout_ms);
    if (timeout_ms > 0 && ticks == 0) {
        ticks = 1;
    }

    EventBits_t observed;
    MP_THREAD_GIL_EXIT();
    observed = xEventGroupWaitBits(pble_ready_events, PBLE_READY_BIT,
                                   pdFALSE, pdFALSE, ticks);
    MP_THREAD_GIL_ENTER();
    return mp_obj_new_bool((observed & PBLE_READY_BIT) != 0);
}
static MP_DEFINE_CONST_FUN_OBJ_1(pble_ble_wait_ready_obj, pble_ble_wait_ready);
#endif

static const mp_rom_map_elem_t pble_ble_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_pble_ble) },
    { MP_ROM_QSTR(MP_QSTR_init_agent), MP_ROM_PTR(&pble_ble_init_agent_obj) },
#if PBLE_ENABLE_SPLASH_READINESS
    { MP_ROM_QSTR(MP_QSTR_wait_ready), MP_ROM_PTR(&pble_ble_wait_ready_obj) },
#endif
};
static MP_DEFINE_CONST_DICT(pble_ble_globals, pble_ble_globals_table);

const mp_obj_module_t pble_ble_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&pble_ble_globals,
};

MP_REGISTER_MODULE(MP_QSTR_pble_ble, pble_ble_user_cmodule);
