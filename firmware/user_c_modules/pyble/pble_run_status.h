// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
#ifndef PBLE_RUN_STATUS_H
#define PBLE_RUN_STATUS_H
#include <stdbool.h>
#include <stdint.h>

#define PBLE_RUN_STATUS_BYTES 25u
#define PBLE_RUN_STATUS_QUEUED 1u
#define PBLE_RUN_STATUS_STOPPING 2u

// Allocation-free committed metadata. The owning runner serializes all access;
// no user source, path, console bytes or persistent identifier is retained here.
typedef struct {
    uint8_t boot_id[8];
    uint32_t run_id;
    uint64_t revision;
    uint8_t state;
    uint8_t origin;
    uint8_t terminal_reason;
    uint8_t flags;
} pble_run_status_t;

bool pble_run_status_init(pble_run_status_t *status, const uint8_t boot_id[8]);
bool pble_run_status_admit(pble_run_status_t *status, uint8_t origin);
void pble_run_status_pickup(pble_run_status_t *status);
void pble_run_status_stop(pble_run_status_t *status);
void pble_run_status_finish(pble_run_status_t *status, bool ok, bool stopped);
void pble_run_status_encode(const pble_run_status_t *status,
                            uint8_t out[PBLE_RUN_STATUS_BYTES]);
#endif
