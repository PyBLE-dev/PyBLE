// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_device_config — the PyBLE identity store (F-22): bounded NVS label,
// MAC-suffix device_id, advertised-name derivation, and the 0x50 SET_LABEL
// handler. Identity is DISPLAY-ONLY — it NEVER gates access (SEC-11, CON-7).
// Mirrors protocol.md §2/§4/§7 (label max 24 B, OI-6 frozen). Clean-room.
#ifndef PBLE_DEVICE_CONFIG_H
#define PBLE_DEVICE_CONFIG_H

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include "pble_proto.h"   // pble_frame_t, PBLE_LABEL_MAX, status codes

#ifdef __cplusplus
extern "C" {
#endif

// Compute the MAC-suffix device_id + load the persisted label. Idempotent;
// call once at boot before advertising (NVS must already be initialised).
void        pble_dc_init(void);

// The stable device_id: the last two BT-MAC bytes as uppercase hex ("XXXX").
const char *pble_dc_device_id(void);

// Copy the persisted label (or "" if none) into out; returns its length.
size_t      pble_dc_label(char *out, size_t cap);

// Persist a label (FR-IDENT-1): len > PBLE_LABEL_MAX → ERANGE (not stored);
// len == 0 clears to the default. On success re-advertises via pble_ble_set_adv_name.
uint8_t     pble_dc_set_label(const uint8_t *utf8, size_t len);

// The advertised name: the label if set, else "PyBLE-" + device_id (FR-BLE-12).
size_t      pble_dc_adv_name(char *out, size_t cap);

// 0x50 SET_LABEL dispatch handler (registered into pble_proto).
uint8_t     pble_dc_set_label_cmd(const pble_frame_t *req, uint8_t *rsp,
                                  size_t *rsp_len,
                                  const pble_session_token_t *session);

// --- Identify LED (F-23) — the single optional status LED (CON-13, one config,
// never user-code routing) --------------------------------------------------
// True if an identify LED is configured; on true, fills gpio + active_high (for
// the caps has_identify / identify_led fields). SEC-11: display-only, no gating.
bool        pble_dc_identify_led(uint8_t *gpio_out, uint8_t *active_high_out);

// 0x51 core: payload `[gpio][active_level]` persisted to NVS; len 0 clears.
// ERANGE if gpio invalid, EBADREQ if active_level ∉ {0,1} (protocol.md §4).
uint8_t     pble_dc_set_identify_led(const uint8_t *payload, size_t len);
uint8_t     pble_dc_set_identify_led_cmd(const pble_frame_t *req, uint8_t *rsp,
                                         size_t *rsp_len,
                                         const pble_session_token_t *session);

// 0x52 IDENTIFY: EUNSUPPORTED if unset; else start a bounded non-blocking blink
// (5 Hz, optional `[duration_ds]` 1..50, default 20) on an esp_timer and return
// OK immediately — never stalls BLE or user code (FR-IDENT-3, FR-BLE-11).
uint8_t     pble_dc_identify_cmd(const pble_frame_t *req, uint8_t *rsp,
                                 size_t *rsp_len,
                                 const pble_session_token_t *session);

// Register 0x51 / 0x52 into pble_proto. Call once at boot from init_agent().
void        pble_dc_identify_register(void);

// Retained-VM teardown stops the identify timer within the wrapper's shared
// absolute deadline and clears its armed epoch. Inactive/already-fired is OK.
bool        pble_dc_vm_timer_disarm(int64_t deadline_us);

#ifdef __cplusplus
}
#endif

#endif  // PBLE_DEVICE_CONFIG_H
