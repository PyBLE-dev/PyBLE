// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

#ifndef PBLE_TERMINATION_H
#define PBLE_TERMINATION_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PBLE_TERM_WATCHDOG_US INT64_C(2500000)

// Every command and TX attempt carries all three fields.  The pure termination
// reducer owns conn+generation; pble_ble protects the VM epoch beside it under
// the same session critical section.
typedef struct {
    uint16_t conn;
    uint64_t generation;
    uint64_t vm_epoch;
} pble_session_token_t;

typedef enum {
    PBLE_TERM_PHASE_CLOSED = 0,
    PBLE_TERM_PHASE_OPEN,
    PBLE_TERM_PHASE_CLOSING,
    PBLE_TERM_PHASE_CLEANING,
    PBLE_TERM_PHASE_RESTARTING,
} pble_term_phase_t;

typedef enum {
    PBLE_TERM_EFFECT_NONE = 0,
    PBLE_TERM_EFFECT_ARM_WATCHDOG,
    PBLE_TERM_EFFECT_CALL_GAP,
    PBLE_TERM_EFFECT_STOP_WATCHDOG,
    PBLE_TERM_EFFECT_INVALIDATE,
    PBLE_TERM_EFFECT_REARM_WATCHDOG,
    PBLE_TERM_EFFECT_RESTART,
} pble_term_effects_t;

typedef struct {
    uint16_t conn;
    uint64_t generation;
    int64_t deadline_us;
} pble_term_watchdog_ticket_t;

typedef struct {
    pble_term_phase_t phase;
    uint16_t conn;
    uint64_t generation;
    int64_t deadline_us;
    bool watchdog_armed;
    bool watchdog_rearm_pending;
    bool cleanup_stop_required;
    bool cleanup_allowed;
} pble_term_state_t;

void pble_term_init(pble_term_state_t *state);
bool pble_term_open(pble_term_state_t *state, uint16_t conn,
                    uint64_t generation);
bool pble_term_admits(const pble_term_state_t *state, uint16_t conn,
                      uint64_t generation);
bool pble_term_rotate_open(pble_term_state_t *state, uint16_t conn,
                           uint64_t old_generation,
                           uint64_t new_generation);
pble_term_effects_t pble_term_begin(pble_term_state_t *state, uint16_t conn,
                                    uint64_t generation, int64_t now_us);
bool pble_term_watchdog_ticket(const pble_term_state_t *state, uint16_t conn,
                               uint64_t generation,
                               pble_term_watchdog_ticket_t *ticket);
int64_t pble_term_remaining_us(
    const pble_term_state_t *state,
    const pble_term_watchdog_ticket_t *ticket, int64_t now_us);
pble_term_effects_t pble_term_watchdog_armed(pble_term_state_t *state,
                                             uint16_t conn,
                                             uint64_t generation, bool ok);
pble_term_effects_t pble_term_gap_result(pble_term_state_t *state,
                                         uint16_t conn, uint64_t generation,
                                         bool pending);
pble_term_effects_t pble_term_disconnect(pble_term_state_t *state,
                                         uint16_t conn,
                                         uint64_t generation);
pble_term_effects_t pble_term_reset(pble_term_state_t *state);
pble_term_effects_t pble_term_watchdog_stopped(pble_term_state_t *state,
                                               uint16_t conn,
                                               uint64_t generation, bool ok);
pble_term_effects_t pble_term_cleanup_complete(pble_term_state_t *state,
                                               uint16_t conn,
                                               uint64_t generation);
pble_term_effects_t pble_term_watchdog_fired(
    pble_term_state_t *state, const pble_term_watchdog_ticket_t *ticket,
    int64_t now_us);
pble_term_effects_t pble_term_watchdog_rearmed(
    pble_term_state_t *state, const pble_term_watchdog_ticket_t *ticket,
    bool ok);

#ifdef __cplusplus
}
#endif

#endif  // PBLE_TERMINATION_H
