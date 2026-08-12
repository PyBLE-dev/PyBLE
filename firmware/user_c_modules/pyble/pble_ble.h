// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_ble.h — the frozen ble<->{proto,info,device_config} native contract.
//
// pble_ble owns NimBLE (Layer 1) and the PBLE/1 byte transport. Peer modules
// call these to move bytes; they never touch NimBLE directly. Implemented in
// pble_ble.c. Signatures mirror the frozen native cross-module contract.
#ifndef PBLE_BLE_H
#define PBLE_BLE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Bring up NimBLE + the one GATT service (RX/TX/INFO) + advertising. Idempotent
// and non-blocking; called once from the frozen _boot.py via init_agent().
void pble_ble_init(void);

// F-18 (SEC-1): configure the NimBLE Security Manager for the Just-Works
// pairing/encryption baseline — available and USED when the central initiates,
// but NOT access-gating (the RX/TX/INFO characteristics carry no per-char
// encryption-permission flag, so a normal central connects and speaks PBLE/1
// with no mandatory pairing step, SEC-1/2). Called by pble_ble_init before the
// host starts; exposed for the unit/HIL harness to assert the SM posture.
void pble_ble_sm_config(void);

// pble_ble_notify() return codes. Negative == the message did not fully go out;
// existing callers may keep testing `rc < 0`. The two negatives are
// DISTINGUISHABLE so a streaming sender (e.g. the file-GET fs-worker) can tell an
// aborted link from transient host/controller backpressure:
//   PBLE_TX_OK      ( 0)  every §3.2 fragment was handed to NimBLE.
//   PBLE_TX_NO_CONN (-1)  no active connection (or the link dropped mid-send) —
//                         the caller should ABORT the stream; retrying is futile.
//   PBLE_TX_AGAIN   (-2)  transient: the host mbuf pool / controller queue is
//                         full (in-flight notifications not yet flushed). For a
//                         single-packet message NOTHING was sent, so the caller
//                         may pace — on ITS OWN task with a bounded delay, NEVER
//                         on the NimBLE host task — and RETRY. Backpressure policy
//                         lives with the caller; the transport neither queues nor
//                         blocks (FR-BLE-11), so it never buffers unbounded bytes.
//   PBLE_TX_OVERSIZE (-3) paced traffic was not one transport fragment. Paced
//                         callers must split at complete PBLE-message boundaries
//                         before calling; the transport never permits fragments
//                         from another message to interleave during a retry wait.
#define PBLE_TX_OK       0
#define PBLE_TX_NO_CONN  (-1)
#define PBLE_TX_AGAIN    (-2)
#define PBLE_TX_OVERSIZE (-3)

// Sole TX path: fragment already-encoded PBLE/1 bytes (§3.2) and Notify each
// packet on TX. Returns PBLE_TX_OK / PBLE_TX_NO_CONN / PBLE_TX_AGAIN (above).
// (FR-BLE-3/10) — the bytes are never decoded here.
//
// NOTE on retry after PBLE_TX_AGAIN: only a SINGLE-packet message is cleanly
// retriable, because a mid-run AGAIN on a multi-fragment message means earlier
// fragments already reached the app. The file-GET DATA chunks are sized to one
// BLE packet (caps chunk_size) precisely so each stream event is a single packet
// and PBLE_TX_AGAIN is always a clean "nothing sent, safe to retry".
int pble_ble_notify(const uint8_t *msg, size_t len);

// Paced TX for BULK streaming callers (fs-worker / console — NEVER the NimBLE
// host task). The encoded message MUST fit one §3.2 fragment. Each retry makes
// one Notify attempt while serialized, releases the TX mutex, then waits on the
// drain event outside the mutex. The bulk path preserves enough exact msys_1
// capacity for one immediate small control Notify. Returns PBLE_TX_OVERSIZE when
// the one-fragment precondition is violated.
int pble_ble_notify_paced(const uint8_t *msg, size_t len, uint32_t budget_ms);

// Paced one-fragment CONTROL event. It follows the same bounded retry discipline
// but consumes the capacity deliberately reserved from bulk traffic.
int pble_ble_notify_control_paced(const uint8_t *msg, size_t len,
                                  uint32_t budget_ms);

// Replace the advertised name (label-else-`PyBLE-XXXX`) and re-advertise
// pre-connect so the change shows in the scan list (FR-BLE-12). Display-only.
void pble_ble_set_adv_name(const char *name);

// The negotiated ATT MTU (247 once the central requests it, the BLE default
// until then) — sizes proto/storage buffers and DEVICE_INFO.mtu (FR-BLE-7/8).
uint16_t pble_ble_mtu(void);

#ifdef __cplusplus
}
#endif

#endif  // PBLE_BLE_H
