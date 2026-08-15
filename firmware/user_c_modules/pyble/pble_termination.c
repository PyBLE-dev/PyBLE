// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

#include "pble_termination.h"

#include <limits.h>
#include <stddef.h>
#include <string.h>

static bool pble_term_matches(const pble_term_state_t *state, uint16_t conn,
                              uint64_t generation) {
    return state != NULL && state->conn == conn &&
           state->generation == generation && generation != 0;
}

static bool pble_term_ticket_matches(
    const pble_term_state_t *state,
    const pble_term_watchdog_ticket_t *ticket) {
    return state != NULL && ticket != NULL &&
           pble_term_matches(state, ticket->conn, ticket->generation) &&
           state->deadline_us == ticket->deadline_us;
}

static pble_term_effects_t pble_term_restart(pble_term_state_t *state) {
    if (state != NULL) {
        state->phase = PBLE_TERM_PHASE_RESTARTING;
        state->watchdog_armed = false;
        state->watchdog_rearm_pending = false;
        state->cleanup_allowed = false;
    }
    return PBLE_TERM_EFFECT_RESTART;
}

void pble_term_init(pble_term_state_t *state) {
    if (state == NULL) {
        return;
    }
    memset(state, 0, sizeof(*state));
    state->phase = PBLE_TERM_PHASE_CLOSED;
}

bool pble_term_open(pble_term_state_t *state, uint16_t conn,
                    uint64_t generation) {
    if (state == NULL || state->phase != PBLE_TERM_PHASE_CLOSED ||
        generation == 0) {
        return false;
    }
    state->phase = PBLE_TERM_PHASE_OPEN;
    state->conn = conn;
    state->generation = generation;
    state->deadline_us = 0;
    state->watchdog_armed = false;
    state->watchdog_rearm_pending = false;
    state->cleanup_stop_required = false;
    state->cleanup_allowed = false;
    return true;
}

bool pble_term_admits(const pble_term_state_t *state, uint16_t conn,
                      uint64_t generation) {
    return state != NULL && state->phase == PBLE_TERM_PHASE_OPEN &&
           pble_term_matches(state, conn, generation);
}

bool pble_term_rotate_open(pble_term_state_t *state, uint16_t conn,
                           uint64_t old_generation,
                           uint64_t new_generation) {
    if (state == NULL || state->phase != PBLE_TERM_PHASE_OPEN ||
        !pble_term_matches(state, conn, old_generation) ||
        new_generation == 0 || new_generation == old_generation) {
        return false;
    }
    state->generation = new_generation;
    state->deadline_us = 0;
    state->watchdog_armed = false;
    state->watchdog_rearm_pending = false;
    state->cleanup_stop_required = false;
    state->cleanup_allowed = false;
    return true;
}

pble_term_effects_t pble_term_begin(pble_term_state_t *state, uint16_t conn,
                                    uint64_t generation, int64_t now_us) {
    if (!pble_term_admits(state, conn, generation)) {
        return PBLE_TERM_EFFECT_NONE;
    }
    state->phase = PBLE_TERM_PHASE_CLOSING;
    state->deadline_us =
        now_us > INT64_MAX - PBLE_TERM_WATCHDOG_US
            ? INT64_MAX
            : now_us + PBLE_TERM_WATCHDOG_US;
    state->watchdog_armed = false;
    state->watchdog_rearm_pending = false;
    state->cleanup_stop_required = true;
    state->cleanup_allowed = false;
    return PBLE_TERM_EFFECT_ARM_WATCHDOG;
}

bool pble_term_watchdog_ticket(const pble_term_state_t *state, uint16_t conn,
                               uint64_t generation,
                               pble_term_watchdog_ticket_t *ticket) {
    if (ticket == NULL || state == NULL ||
        state->phase != PBLE_TERM_PHASE_CLOSING ||
        !pble_term_matches(state, conn, generation)) {
        return false;
    }
    ticket->conn = conn;
    ticket->generation = generation;
    ticket->deadline_us = state->deadline_us;
    return true;
}

int64_t pble_term_remaining_us(
    const pble_term_state_t *state,
    const pble_term_watchdog_ticket_t *ticket, int64_t now_us) {
    if (state == NULL || state->phase != PBLE_TERM_PHASE_CLOSING ||
        !pble_term_ticket_matches(state, ticket) ||
        now_us >= state->deadline_us) {
        return 0;
    }
    return state->deadline_us - now_us;
}

pble_term_effects_t pble_term_watchdog_armed(pble_term_state_t *state,
                                             uint16_t conn,
                                             uint64_t generation, bool ok) {
    if (state == NULL || state->phase != PBLE_TERM_PHASE_CLOSING ||
        !pble_term_matches(state, conn, generation) ||
        state->watchdog_armed) {
        return PBLE_TERM_EFFECT_NONE;
    }
    if (!ok) {
        return pble_term_restart(state);
    }
    state->watchdog_armed = true;
    return PBLE_TERM_EFFECT_CALL_GAP;
}

pble_term_effects_t pble_term_gap_result(pble_term_state_t *state,
                                         uint16_t conn, uint64_t generation,
                                         bool pending) {
    if (state == NULL || state->phase != PBLE_TERM_PHASE_CLOSING ||
        !pble_term_matches(state, conn, generation) ||
        !state->watchdog_armed) {
        return PBLE_TERM_EFFECT_NONE;
    }
    return pending ? PBLE_TERM_EFFECT_NONE : pble_term_restart(state);
}

pble_term_effects_t pble_term_disconnect(pble_term_state_t *state,
                                         uint16_t conn,
                                         uint64_t generation) {
    if (state == NULL || !pble_term_matches(state, conn, generation)) {
        return PBLE_TERM_EFFECT_NONE;
    }
    if (state->phase == PBLE_TERM_PHASE_OPEN) {
        state->phase = PBLE_TERM_PHASE_CLEANING;
        state->cleanup_stop_required = false;
        state->cleanup_allowed = true;
        return PBLE_TERM_EFFECT_INVALIDATE;
    }
    if (state->phase == PBLE_TERM_PHASE_CLOSING) {
        state->phase = PBLE_TERM_PHASE_CLEANING;
        state->cleanup_stop_required = true;
        state->cleanup_allowed = false;
        return PBLE_TERM_EFFECT_STOP_WATCHDOG;
    }
    return PBLE_TERM_EFFECT_NONE;
}

pble_term_effects_t pble_term_reset(pble_term_state_t *state) {
    if (state == NULL) {
        return PBLE_TERM_EFFECT_NONE;
    }
    if (state->phase == PBLE_TERM_PHASE_OPEN) {
        state->phase = PBLE_TERM_PHASE_CLEANING;
        state->cleanup_stop_required = false;
        state->cleanup_allowed = true;
        return PBLE_TERM_EFFECT_INVALIDATE;
    }
    if (state->phase == PBLE_TERM_PHASE_CLOSING) {
        state->phase = PBLE_TERM_PHASE_CLEANING;
        state->cleanup_stop_required = true;
        state->cleanup_allowed = false;
        return PBLE_TERM_EFFECT_STOP_WATCHDOG;
    }
    return PBLE_TERM_EFFECT_NONE;
}

pble_term_effects_t pble_term_watchdog_stopped(pble_term_state_t *state,
                                               uint16_t conn,
                                               uint64_t generation, bool ok) {
    if (state == NULL || state->phase != PBLE_TERM_PHASE_CLEANING ||
        !pble_term_matches(state, conn, generation) ||
        !state->cleanup_stop_required) {
        return PBLE_TERM_EFFECT_NONE;
    }
    if (!ok) {
        return pble_term_restart(state);
    }
    state->watchdog_armed = false;
    state->watchdog_rearm_pending = false;
    state->cleanup_stop_required = false;
    state->cleanup_allowed = true;
    return PBLE_TERM_EFFECT_INVALIDATE;
}

pble_term_effects_t pble_term_cleanup_complete(pble_term_state_t *state,
                                               uint16_t conn,
                                               uint64_t generation) {
    if (state == NULL || state->phase != PBLE_TERM_PHASE_CLEANING ||
        !pble_term_matches(state, conn, generation) ||
        !state->cleanup_allowed || state->cleanup_stop_required) {
        return PBLE_TERM_EFFECT_NONE;
    }
    state->phase = PBLE_TERM_PHASE_CLOSED;
    state->conn = 0;
    state->generation = 0;
    state->deadline_us = 0;
    state->watchdog_armed = false;
    state->watchdog_rearm_pending = false;
    state->cleanup_allowed = false;
    return PBLE_TERM_EFFECT_NONE;
}

pble_term_effects_t pble_term_watchdog_fired(
    pble_term_state_t *state, const pble_term_watchdog_ticket_t *ticket,
    int64_t now_us) {
    if (state == NULL || state->phase != PBLE_TERM_PHASE_CLOSING ||
        !pble_term_ticket_matches(state, ticket) || !state->watchdog_armed ||
        state->watchdog_rearm_pending) {
        return PBLE_TERM_EFFECT_NONE;
    }
    if (now_us >= state->deadline_us) {
        return pble_term_restart(state);
    }
    state->watchdog_rearm_pending = true;
    return PBLE_TERM_EFFECT_REARM_WATCHDOG;
}

pble_term_effects_t pble_term_watchdog_rearmed(
    pble_term_state_t *state, const pble_term_watchdog_ticket_t *ticket,
    bool ok) {
    if (state == NULL || state->phase != PBLE_TERM_PHASE_CLOSING ||
        !pble_term_ticket_matches(state, ticket) ||
        !state->watchdog_rearm_pending) {
        return PBLE_TERM_EFFECT_NONE;
    }
    state->watchdog_rearm_pending = false;
    if (!ok) {
        return pble_term_restart(state);
    }
    state->watchdog_armed = true;
    return PBLE_TERM_EFFECT_NONE;
}
