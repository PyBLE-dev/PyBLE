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

static void open_and_arm(pble_term_state_t *state, uint16_t conn,
                         uint64_t generation, int64_t now_us) {
    assert(pble_term_open(state, conn, generation));
    assert_effects(pble_term_begin(state, conn, generation, now_us),
                   PBLE_TERM_EFFECT_ARM_WATCHDOG);
    assert_effects(pble_term_watchdog_armed(state, conn, generation, true),
                   PBLE_TERM_EFFECT_CALL_GAP);
    assert_effects(pble_term_gap_result(state, conn, generation, true),
                   PBLE_TERM_EFFECT_NONE);
}

typedef struct {
    unsigned arm_calls;
    unsigned gap_calls;
    unsigned restart_calls;
} mock_adapter_t;

enum {
    MOCK_GAP_OK = 0,
    MOCK_GAP_EALREADY = 2,
    MOCK_GAP_ERROR = 5,
};

/* Exercise the effect-driven adapter with mocked timer, GAP, and restart I/O. */
static void mock_adapter_begin(mock_adapter_t *mock, pble_term_state_t *state,
                               uint16_t conn, uint64_t generation,
                               int64_t now_us, bool arm_ok, int gap_rc) {
    pble_term_effects_t effect =
        pble_term_begin(state, conn, generation, now_us);
    if (effect != PBLE_TERM_EFFECT_ARM_WATCHDOG) {
        assert(effect == PBLE_TERM_EFFECT_NONE);
        return;
    }

    mock->arm_calls++;
    effect = pble_term_watchdog_armed(state, conn, generation, arm_ok);
    if (effect == PBLE_TERM_EFFECT_RESTART) {
        mock->restart_calls++;
        return;
    }
    assert(effect == PBLE_TERM_EFFECT_CALL_GAP);

    mock->gap_calls++;
    bool pending = gap_rc == MOCK_GAP_OK || gap_rc == MOCK_GAP_EALREADY;
    effect = pble_term_gap_result(state, conn, generation, pending);
    if (effect == PBLE_TERM_EFFECT_RESTART) {
        mock->restart_calls++;
    } else {
        assert(effect == PBLE_TERM_EFFECT_NONE);
    }
}

static void test_begin_and_terminal_deadline(void) {
    pble_term_state_t state;
    pble_term_init(&state);
    assert(state.phase == PBLE_TERM_PHASE_CLOSED);
    assert(PBLE_TERM_WATCHDOG_US == INT64_C(2500000));

    assert(pble_term_open(&state, UINT16_C(7), UINT64_C(41)));
    assert(pble_term_admits(&state, UINT16_C(7), UINT64_C(41)));
    assert(!pble_term_admits(&state, UINT16_C(7), UINT64_C(42)));
    assert_effects(
        pble_term_begin(&state, UINT16_C(8), UINT64_C(41), INT64_C(1000000)),
        PBLE_TERM_EFFECT_NONE);
    assert(state.phase == PBLE_TERM_PHASE_OPEN);

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

    /* A callback cannot act in the CLOSING-before-arm acknowledgement window. */
    assert_effects(
        pble_term_watchdog_fired(&state, UINT16_C(7), UINT64_C(41),
                                 INT64_MAX),
        PBLE_TERM_EFFECT_NONE);
    assert_effects(
        pble_term_watchdog_armed(&state, UINT16_C(7), UINT64_C(42), true),
        PBLE_TERM_EFFECT_NONE);
    assert_effects(
        pble_term_watchdog_armed(&state, UINT16_C(7), UINT64_C(41), true),
        PBLE_TERM_EFFECT_CALL_GAP);
    assert_effects(
        pble_term_watchdog_armed(&state, UINT16_C(7), UINT64_C(41), true),
        PBLE_TERM_EFFECT_NONE);
    assert_effects(
        pble_term_gap_result(&state, UINT16_C(7), UINT64_C(41), true),
        PBLE_TERM_EFFECT_NONE);

    /* The early-fire delay is residual and the absolute deadline never moves. */
    assert(pble_term_remaining_us(&state, UINT16_C(7), UINT64_C(41),
                                  INT64_C(3499900)) == INT64_C(100));
    assert_effects(
        pble_term_watchdog_fired(&state, UINT16_C(7), UINT64_C(41),
                                 INT64_C(3499900)),
        PBLE_TERM_EFFECT_REARM_WATCHDOG);
    assert_effects(
        pble_term_watchdog_rearmed(&state, UINT16_C(7), UINT64_C(41), true),
        PBLE_TERM_EFFECT_NONE);
    assert(state.deadline_us == INT64_C(3500000));

    /* Deadline claims terminal restart before any external restart call. */
    assert_effects(
        pble_term_watchdog_fired(&state, UINT16_C(7), UINT64_C(41),
                                 INT64_C(3500000)),
        PBLE_TERM_EFFECT_RESTART);
    assert(state.phase == PBLE_TERM_PHASE_RESTARTING);
    assert_effects(pble_term_disconnect(&state, UINT16_C(7), UINT64_C(41)),
                   PBLE_TERM_EFFECT_NONE);
    assert_effects(pble_term_reset(&state), PBLE_TERM_EFFECT_NONE);
    assert(!pble_term_open(&state, UINT16_C(7), UINT64_C(42)));
}

static void test_exact_cleanup_and_timer_stop(void) {
    pble_term_state_t state;
    pble_term_init(&state);
    open_and_arm(&state, UINT16_C(7), UINT64_C(50), INT64_C(1000000));

    assert_effects(pble_term_disconnect(&state, UINT16_C(8), UINT64_C(50)),
                   PBLE_TERM_EFFECT_NONE);
    assert_effects(pble_term_disconnect(&state, UINT16_C(7), UINT64_C(49)),
                   PBLE_TERM_EFFECT_NONE);
    assert(state.phase == PBLE_TERM_PHASE_CLOSING);

    assert_effects(pble_term_disconnect(&state, UINT16_C(7), UINT64_C(50)),
                   PBLE_TERM_EFFECT_STOP_WATCHDOG);
    assert(state.phase == PBLE_TERM_PHASE_CLEANING);
    assert_effects(
        pble_term_watchdog_fired(&state, UINT16_C(7), UINT64_C(50), INT64_MAX),
        PBLE_TERM_EFFECT_NONE);
    assert(!pble_term_open(&state, UINT16_C(7), UINT64_C(51)));

    /* An unproven stop (including ESP_ERR_INVALID_STATE) is fail-closed. */
    assert_effects(
        pble_term_watchdog_stopped(&state, UINT16_C(7), UINT64_C(50), false),
        PBLE_TERM_EFFECT_RESTART);
    assert(state.phase == PBLE_TERM_PHASE_RESTARTING);
    assert_effects(pble_term_cleanup_complete(&state, UINT16_C(7), UINT64_C(50)),
                   PBLE_TERM_EFFECT_NONE);

    pble_term_init(&state);  /* Simulated whole-board cold boot. */
    open_and_arm(&state, UINT16_C(7), UINT64_C(52), INT64_C(2000000));
    assert_effects(pble_term_disconnect(&state, UINT16_C(7), UINT64_C(52)),
                   PBLE_TERM_EFFECT_STOP_WATCHDOG);
    assert_effects(
        pble_term_watchdog_stopped(&state, UINT16_C(7), UINT64_C(52), true),
        PBLE_TERM_EFFECT_INVALIDATE);
    assert_effects(pble_term_cleanup_complete(&state, UINT16_C(7), UINT64_C(52)),
                   PBLE_TERM_EFFECT_NONE);
    assert(state.phase == PBLE_TERM_PHASE_CLOSED);
    assert(pble_term_open(&state, UINT16_C(7), UINT64_C(53)));

    /* Normal OPEN teardown has no termination watchdog to stop. */
    assert_effects(pble_term_disconnect(&state, UINT16_C(7), UINT64_C(53)),
                   PBLE_TERM_EFFECT_INVALIDATE);
    assert(state.phase == PBLE_TERM_PHASE_CLEANING);
    assert_effects(pble_term_cleanup_complete(&state, UINT16_C(7), UINT64_C(53)),
                   PBLE_TERM_EFFECT_NONE);
    assert(state.phase == PBLE_TERM_PHASE_CLOSED);

    assert(pble_term_open(&state, UINT16_C(9), UINT64_C(54)));
    assert_effects(pble_term_reset(&state), PBLE_TERM_EFFECT_INVALIDATE);
    assert_effects(pble_term_cleanup_complete(&state, UINT16_C(9), UINT64_C(54)),
                   PBLE_TERM_EFFECT_NONE);
}

static void test_failure_matrix_and_stale_successor(void) {
    pble_term_state_t state;
    pble_term_init(&state);
    assert(pble_term_open(&state, UINT16_C(7), UINT64_C(60)));
    assert_effects(
        pble_term_begin(&state, UINT16_C(7), UINT64_C(60), INT64_C(1000000)),
        PBLE_TERM_EFFECT_ARM_WATCHDOG);
    assert_effects(
        pble_term_watchdog_armed(&state, UINT16_C(7), UINT64_C(60), false),
        PBLE_TERM_EFFECT_RESTART);
    assert(state.phase == PBLE_TERM_PHASE_RESTARTING);
    assert_effects(
        pble_term_gap_result(&state, UINT16_C(7), UINT64_C(60), true),
        PBLE_TERM_EFFECT_NONE);

    pble_term_init(&state);
    open_and_arm(&state, UINT16_C(7), UINT64_C(61), INT64_C(2000000));
    assert_effects(
        pble_term_gap_result(&state, UINT16_C(7), UINT64_C(61), false),
        PBLE_TERM_EFFECT_RESTART);
    assert(state.phase == PBLE_TERM_PHASE_RESTARTING);

    pble_term_init(&state);
    open_and_arm(&state, UINT16_C(7), UINT64_C(62), INT64_C(3000000));
    assert_effects(
        pble_term_watchdog_fired(&state, UINT16_C(7), UINT64_C(62),
                                 INT64_C(5499999)),
        PBLE_TERM_EFFECT_REARM_WATCHDOG);
    assert_effects(
        pble_term_watchdog_rearmed(&state, UINT16_C(7), UINT64_C(62), false),
        PBLE_TERM_EFFECT_RESTART);
    assert(state.phase == PBLE_TERM_PHASE_RESTARTING);

    /* Old callback remains inert while the reused handle's successor closes. */
    pble_term_init(&state);
    open_and_arm(&state, UINT16_C(7), UINT64_C(63), INT64_C(4000000));
    assert_effects(pble_term_disconnect(&state, UINT16_C(7), UINT64_C(63)),
                   PBLE_TERM_EFFECT_STOP_WATCHDOG);
    assert_effects(
        pble_term_watchdog_stopped(&state, UINT16_C(7), UINT64_C(63), true),
        PBLE_TERM_EFFECT_INVALIDATE);
    assert_effects(pble_term_cleanup_complete(&state, UINT16_C(7), UINT64_C(63)),
                   PBLE_TERM_EFFECT_NONE);
    open_and_arm(&state, UINT16_C(7), UINT64_C(64), INT64_C(5000000));
    int64_t successor_deadline = state.deadline_us;
    assert_effects(
        pble_term_watchdog_fired(&state, UINT16_C(7), UINT64_C(63), INT64_MAX),
        PBLE_TERM_EFFECT_NONE);
    assert(state.phase == PBLE_TERM_PHASE_CLOSING);
    assert(state.deadline_us == successor_deadline);
}

static void test_mock_adapter_one_call_matrix(void) {
    const int results[] = {MOCK_GAP_OK, MOCK_GAP_EALREADY, MOCK_GAP_ERROR};
    for (size_t i = 0; i < sizeof(results) / sizeof(results[0]); i++) {
        pble_term_state_t state;
        mock_adapter_t mock = {0};
        pble_term_init(&state);
        assert(pble_term_open(&state, UINT16_C(11), UINT64_C(70) + i));
        mock_adapter_begin(&mock, &state, UINT16_C(11), UINT64_C(70) + i,
                           INT64_C(1000000), true, results[i]);
        mock_adapter_begin(&mock, &state, UINT16_C(11), UINT64_C(70) + i,
                           INT64_C(1000010), true, results[i]);
        assert(mock.arm_calls == 1);
        assert(mock.gap_calls == 1);
        assert(mock.restart_calls == (results[i] == MOCK_GAP_ERROR ? 1u : 0u));
    }

    pble_term_state_t state;
    mock_adapter_t mock = {0};
    pble_term_init(&state);
    assert(pble_term_open(&state, UINT16_C(11), UINT64_C(80)));
    mock_adapter_begin(&mock, &state, UINT16_C(11), UINT64_C(80),
                       INT64_C(1000000), false, MOCK_GAP_OK);
    assert(mock.arm_calls == 1);
    assert(mock.gap_calls == 0);
    assert(mock.restart_calls == 1);
}

int main(void) {
    test_begin_and_terminal_deadline();
    test_exact_cleanup_and_timer_stop();
    test_failure_matrix_and_stale_successor();
    test_mock_adapter_one_call_matrix();
    puts("failed-session termination reducer: all scenarios passed");
    return 0;
}
