// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "pble_termination.h"

static void assert_effects(pble_term_effects_t actual,
                           pble_term_effects_t expected) {
    assert(actual == expected);
}

int main(void) {
    pble_term_state_t state;
    pble_term_init(&state);
    assert(state.phase == PBLE_TERM_PHASE_CLOSED);
    assert(PBLE_TERM_WATCHDOG_US == INT64_C(2500000));

    /* OPEN -> CLOSING closes admission before watchdog/GAP actions. */
    assert(pble_term_open(&state, UINT16_C(7), UINT64_C(41)));
    assert(pble_term_admits(&state, UINT16_C(7), UINT64_C(41)));
    assert_effects(
        pble_term_begin(&state, UINT16_C(7), UINT64_C(41), INT64_C(1000000)),
        PBLE_TERM_EFFECT_ARM_WATCHDOG);
    assert(state.phase == PBLE_TERM_PHASE_CLOSING);
    assert(state.deadline_us == INT64_C(3500000));
    assert(!pble_term_admits(&state, UINT16_C(7), UINT64_C(41)));
    assert_effects(
        pble_term_begin(&state, UINT16_C(7), UINT64_C(41), INT64_C(1000010)),
        PBLE_TERM_EFFECT_NONE);
    assert(!pble_term_open(&state, UINT16_C(7), UINT64_C(42)));

    /* GAP is called exactly once and only after watchdog arm succeeds. */
    assert_effects(
        pble_term_watchdog_armed(&state, UINT16_C(7), UINT64_C(41), true),
        PBLE_TERM_EFFECT_CALL_GAP);
    assert_effects(
        pble_term_watchdog_armed(&state, UINT16_C(7), UINT64_C(41), true),
        PBLE_TERM_EFFECT_NONE);
    assert_effects(
        pble_term_gap_result(&state, UINT16_C(7), UINT64_C(41), true),
        PBLE_TERM_EFFECT_NONE);

    /* The absolute deadline is inclusive and never extended by progress. */
    assert_effects(
        pble_term_watchdog_fired(&state, UINT16_C(7), UINT64_C(41),
                                 INT64_C(3499999)),
        PBLE_TERM_EFFECT_REARM_WATCHDOG);
    assert(state.deadline_us == INT64_C(3500000));
    assert_effects(
        pble_term_watchdog_fired(&state, UINT16_C(7), UINT64_C(41),
                                 INT64_C(3500000)),
        PBLE_TERM_EFFECT_RESTART);

    /* After the adapter cancels its timer, exact disconnect invalidates once. */
    assert_effects(
        pble_term_disconnect(&state, UINT16_C(8), UINT64_C(41)),
        PBLE_TERM_EFFECT_NONE);
    assert_effects(
        pble_term_disconnect(&state, UINT16_C(7), UINT64_C(41)),
        PBLE_TERM_EFFECT_INVALIDATE);
    assert(state.phase == PBLE_TERM_PHASE_CLOSED);
    assert(pble_term_open(&state, UINT16_C(7), UINT64_C(42)));
    assert(pble_term_admits(&state, UINT16_C(7), UINT64_C(42)));
    assert_effects(pble_term_reset(&state), PBLE_TERM_EFFECT_INVALIDATE);
    assert_effects(
        pble_term_disconnect(&state, UINT16_C(7), UINT64_C(41)),
        PBLE_TERM_EFFECT_NONE);

    /* Arm failure and every non-pending GAP result restart immediately. */
    assert(pble_term_open(&state, UINT16_C(7), UINT64_C(45)));
    assert_effects(
        pble_term_begin(&state, UINT16_C(7), UINT64_C(45), INT64_C(9000000)),
        PBLE_TERM_EFFECT_ARM_WATCHDOG);
    assert_effects(
        pble_term_watchdog_armed(&state, UINT16_C(7), UINT64_C(45), false),
        PBLE_TERM_EFFECT_RESTART);
    assert_effects(pble_term_reset(&state), PBLE_TERM_EFFECT_INVALIDATE);

    assert(pble_term_open(&state, UINT16_C(7), UINT64_C(46)));
    assert_effects(
        pble_term_begin(&state, UINT16_C(7), UINT64_C(46), INT64_C(12000000)),
        PBLE_TERM_EFFECT_ARM_WATCHDOG);
    assert_effects(
        pble_term_watchdog_armed(&state, UINT16_C(7), UINT64_C(46), true),
        PBLE_TERM_EFFECT_CALL_GAP);
    assert_effects(
        pble_term_gap_result(&state, UINT16_C(7), UINT64_C(46), false),
        PBLE_TERM_EFFECT_RESTART);
    assert_effects(
        pble_term_reset(&state),
        PBLE_TERM_EFFECT_INVALIDATE);

    /* A stopped-but-queued old callback cannot affect a reused handle. */
    assert(pble_term_open(&state, UINT16_C(7), UINT64_C(47)));
    assert_effects(
        pble_term_watchdog_fired(&state, UINT16_C(7), UINT64_C(46),
                                 INT64_MAX),
        PBLE_TERM_EFFECT_NONE);
    assert(pble_term_admits(&state, UINT16_C(7), UINT64_C(47)));

    puts("failed-session termination reducer: all scenarios passed");
    return 0;
}
