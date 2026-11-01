// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
#include "pble_run_status.h"
#include <string.h>

bool pble_run_status_init(pble_run_status_t *status, const uint8_t boot_id[8]) {
    uint8_t nonzero = 0;
    for (unsigned i = 0; i < 8; ++i) {
        nonzero |= boot_id[i];
    }
    if (nonzero == 0) {
        return false;
    }
    memset(status, 0, sizeof(*status));
    memcpy(status->boot_id, boot_id, 8);
    return true;
}

bool pble_run_status_admit(pble_run_status_t *status, uint8_t origin) {
    if (status->state == 1 || status->run_id == UINT32_MAX ||
        origin < 1 || origin > 3) {
        return false;
    }
    ++status->run_id;
    ++status->revision;
    status->state = 1;
    status->origin = origin;
    status->terminal_reason = 0;
    status->flags = PBLE_RUN_STATUS_QUEUED;
    return true;
}

void pble_run_status_pickup(pble_run_status_t *status) {
    if (status->state == 1 && (status->flags & PBLE_RUN_STATUS_QUEUED)) {
        status->flags &= (uint8_t)~PBLE_RUN_STATUS_QUEUED;
        ++status->revision;
    }
}

void pble_run_status_stop(pble_run_status_t *status) {
    if (status->state == 1 && !(status->flags & PBLE_RUN_STATUS_STOPPING)) {
        status->flags |= PBLE_RUN_STATUS_STOPPING;
        ++status->revision;
    }
}

void pble_run_status_finish(pble_run_status_t *status, bool ok, bool stopped) {
    if (status->state != 1) {
        return;
    }
    status->state = stopped ? 0 : (ok ? 2 : 3);
    status->terminal_reason = stopped ? 3 : (ok ? 1 : 2);
    status->flags = 0;
    ++status->revision;
}

void pble_run_status_encode(const pble_run_status_t *status,
                            uint8_t out[PBLE_RUN_STATUS_BYTES]) {
    out[0] = 1;
    memcpy(out + 1, status->boot_id, 8);
    for (unsigned i = 0; i < 4; ++i) {
        out[9 + i] = (uint8_t)(status->run_id >> (8 * i));
    }
    for (unsigned i = 0; i < 8; ++i) {
        out[13 + i] = (uint8_t)(status->revision >> (8 * i));
    }
    out[21] = status->state;
    out[22] = status->origin;
    out[23] = status->terminal_reason;
    out[24] = status->flags;
}
