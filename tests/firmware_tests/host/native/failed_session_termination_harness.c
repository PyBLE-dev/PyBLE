// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

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
    unsigned critical_depth;
    unsigned enter_calls;
    unsigned exit_calls;
    unsigned arm_calls;
    unsigned rearm_calls;
    unsigned stop_calls;
    unsigned gap_calls;
    unsigned invalidate_calls;
    unsigned advertise_calls;
    unsigned restart_calls;
    int64_t last_arm_delay_us;
    char order[16];
    size_t order_len;
} mock_adapter_t;

enum {
    MOCK_GAP_OK = 0,
    MOCK_GAP_EALREADY = 2,
    MOCK_GAP_ERROR = 5,
};

static void mock_record(mock_adapter_t *mock, char action) {
    assert(mock->order_len < sizeof(mock->order));
    mock->order[mock->order_len++] = action;
}

static void mock_enter(mock_adapter_t *mock) {
    assert(mock->critical_depth == 0);
    mock->critical_depth = 1;
    mock->enter_calls++;
}

static void mock_exit(mock_adapter_t *mock) {
    assert(mock->critical_depth == 1);
    mock->critical_depth = 0;
    mock->exit_calls++;
}

static void mock_restart(mock_adapter_t *mock, const pble_term_state_t *state) {
    assert(mock->critical_depth == 0);
    assert(state->phase == PBLE_TERM_PHASE_RESTARTING);
    mock->restart_calls++;
    mock_record(mock, 'R');
}

static bool mock_adapter_open(mock_adapter_t *mock, pble_term_state_t *state,
                              uint16_t conn, uint64_t generation) {
    mock_enter(mock);
    bool opened = pble_term_open(state, conn, generation);
    mock_exit(mock);
    if (!opened) {
        mock->restart_calls++;
        mock_record(mock, 'R');
    }
    return opened;
}

/* Reference the production adapter order with mocked timer, GAP, and restart I/O. */
static void mock_adapter_begin(mock_adapter_t *mock, pble_term_state_t *state,
                               uint16_t conn, uint64_t generation,
                               int64_t begin_now_us, int64_t arm_now_us,
                               bool arm_ok, int gap_rc) {
    mock_enter(mock);
    pble_term_effects_t effect =
        pble_term_begin(state, conn, generation, begin_now_us);
    if (effect != PBLE_TERM_EFFECT_ARM_WATCHDOG) {
        assert(effect == PBLE_TERM_EFFECT_NONE);
        mock_exit(mock);
        return;
    }

    pble_term_watchdog_ticket_t ticket;
    assert(pble_term_watchdog_ticket(state, conn, generation, &ticket));
    assert(ticket.conn == conn);
    assert(ticket.generation == generation);
    assert(ticket.deadline_us == state->deadline_us);
    int64_t remaining_us =
        pble_term_remaining_us(state, &ticket, arm_now_us);
    if (remaining_us <= 0) {
        effect = pble_term_watchdog_armed(state, conn, generation, false);
    } else {
        assert(mock->critical_depth == 1);
        mock->arm_calls++;
        mock->last_arm_delay_us = remaining_us;
        mock_record(mock, 'A');
        effect = pble_term_watchdog_armed(state, conn, generation, arm_ok);
    }
    mock_exit(mock);
    if (effect == PBLE_TERM_EFFECT_RESTART) {
        mock_restart(mock, state);
        return;
    }
    assert(effect == PBLE_TERM_EFFECT_CALL_GAP);

    assert(mock->critical_depth == 0);
    mock->gap_calls++;
    mock_record(mock, 'G');
    bool pending = gap_rc == MOCK_GAP_OK || gap_rc == MOCK_GAP_EALREADY;
    mock_enter(mock);
    effect = pble_term_gap_result(state, conn, generation, pending);
    mock_exit(mock);
    if (effect == PBLE_TERM_EFFECT_RESTART) {
        mock_restart(mock, state);
    } else {
        assert(effect == PBLE_TERM_EFFECT_NONE);
    }
}

static void mock_adapter_cleanup(mock_adapter_t *mock, pble_term_state_t *state,
                                 uint16_t conn, uint64_t generation,
                                 bool reset, bool stop_ok, bool advertise) {
    mock_enter(mock);
    pble_term_effects_t effect =
        reset ? pble_term_reset(state)
              : pble_term_disconnect(state, conn, generation);
    mock_exit(mock);

    if (effect == PBLE_TERM_EFFECT_STOP_WATCHDOG) {
        mock->stop_calls++;
        mock_record(mock, 'S');
        mock_enter(mock);
        effect = pble_term_watchdog_stopped(state, conn, generation, stop_ok);
        mock_exit(mock);
    }
    if (effect == PBLE_TERM_EFFECT_RESTART) {
        mock_restart(mock, state);
        return;
    }
    if (effect != PBLE_TERM_EFFECT_INVALIDATE) {
        assert(effect == PBLE_TERM_EFFECT_NONE);
        return;
    }

    mock->invalidate_calls++;
    mock_record(mock, 'I');
    mock_enter(mock);
    assert_effects(pble_term_cleanup_complete(state, conn, generation),
                   PBLE_TERM_EFFECT_NONE);
    mock_exit(mock);
    if (advertise) {
        mock->advertise_calls++;
        mock_record(mock, 'V');
    }
}

static void mock_adapter_watchdog(mock_adapter_t *mock,
                                  pble_term_state_t *state,
                                  pble_term_watchdog_ticket_t ticket,
                                  int64_t now_us, bool rearm_ok) {
    mock_enter(mock);
    pble_term_effects_t effect =
        pble_term_watchdog_fired(state, &ticket, now_us);
    mock_exit(mock);
    if (effect == PBLE_TERM_EFFECT_REARM_WATCHDOG) {
        int64_t remaining_us =
            pble_term_remaining_us(state, &ticket, now_us);
        assert(remaining_us > 0);
        mock->rearm_calls++;
        mock->last_arm_delay_us = remaining_us;
        mock_record(mock, 'a');
        mock_enter(mock);
        effect = pble_term_watchdog_rearmed(state, &ticket, rearm_ok);
        mock_exit(mock);
    }
    if (effect == PBLE_TERM_EFFECT_RESTART) {
        mock_restart(mock, state);
    } else {
        assert(effect == PBLE_TERM_EFFECT_NONE);
    }
}

static void mock_adapter_term_failure(mock_adapter_t *mock,
                                      pble_term_state_t *state) {
    pble_term_state_t before_state = *state;
    mock_adapter_t before_mock = *mock;
    /* Intentionally empty: BLE_GAP_EVENT_TERM_FAILURE is a total no-op. */
    assert(memcmp(&before_state, state, sizeof(*state)) == 0);
    assert(memcmp(&before_mock, mock, sizeof(*mock)) == 0);
}

static void test_begin_and_terminal_deadline(void) {
    pble_term_state_t state;
    pble_term_init(&state);
    assert(state.phase == PBLE_TERM_PHASE_CLOSED);
    assert(PBLE_TERM_WATCHDOG_US == INT64_C(2500000));

    assert(!pble_term_open(&state, UINT16_C(7), UINT64_C(0)));
    assert(state.phase == PBLE_TERM_PHASE_CLOSED);
    assert(pble_term_open(&state, UINT16_C(7), UINT64_C(41)));
    assert(!pble_term_open(&state, UINT16_C(8), UINT64_C(42)));
    assert(state.phase == PBLE_TERM_PHASE_OPEN);
    assert(pble_term_admits(&state, UINT16_C(7), UINT64_C(41)));
    assert(!pble_term_admits(&state, UINT16_C(7), UINT64_C(42)));
    assert_effects(
        pble_term_begin(&state, UINT16_C(7), UINT64_C(42), INT64_C(1000000)),
        PBLE_TERM_EFFECT_NONE);
    assert(state.phase == PBLE_TERM_PHASE_OPEN);
    assert(pble_term_admits(&state, UINT16_C(7), UINT64_C(41)));
    assert_effects(
        pble_term_begin(&state, UINT16_C(8), UINT64_C(41), INT64_C(1000000)),
        PBLE_TERM_EFFECT_NONE);
    assert(state.phase == PBLE_TERM_PHASE_OPEN);

    assert_effects(
        pble_term_begin(&state, UINT16_C(7), UINT64_C(41), INT64_C(1000000)),
        PBLE_TERM_EFFECT_ARM_WATCHDOG);
    assert(state.phase == PBLE_TERM_PHASE_CLOSING);
    assert(state.deadline_us == INT64_C(3500000));
    pble_term_watchdog_ticket_t ticket;
    assert(pble_term_watchdog_ticket(&state, UINT16_C(7), UINT64_C(41),
                                     &ticket));
    assert(ticket.conn == UINT16_C(7));
    assert(ticket.generation == UINT64_C(41));
    assert(ticket.deadline_us == INT64_C(3500000));
    assert(!pble_term_admits(&state, UINT16_C(7), UINT64_C(41)));
    assert_effects(
        pble_term_begin(&state, UINT16_C(7), UINT64_C(41), INT64_C(1000010)),
        PBLE_TERM_EFFECT_NONE);
    assert(!pble_term_open(&state, UINT16_C(7), UINT64_C(42)));

    /* A callback cannot act in the CLOSING-before-arm acknowledgement window. */
    assert_effects(
        pble_term_watchdog_fired(&state, &ticket, INT64_MAX),
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

    /* All three immutable ticket fields are revalidated by callback APIs. */
    pble_term_watchdog_ticket_t wrong_conn = ticket;
    wrong_conn.conn++;
    pble_term_watchdog_ticket_t wrong_generation = ticket;
    wrong_generation.generation++;
    pble_term_watchdog_ticket_t wrong_deadline = ticket;
    wrong_deadline.deadline_us++;
    const pble_term_watchdog_ticket_t invalid_tickets[] = {
        wrong_conn,
        wrong_generation,
        wrong_deadline,
    };
    for (size_t i = 0;
         i < sizeof(invalid_tickets) / sizeof(invalid_tickets[0]); i++) {
        assert(pble_term_remaining_us(&state, &invalid_tickets[i],
                                      INT64_C(3499900)) == 0);
        assert_effects(
            pble_term_watchdog_fired(&state, &invalid_tickets[i], INT64_MAX),
            PBLE_TERM_EFFECT_NONE);
        assert_effects(
            pble_term_watchdog_rearmed(&state, &invalid_tickets[i], false),
            PBLE_TERM_EFFECT_NONE);
    }

    /* The early-fire delay is residual and the absolute deadline never moves. */
    assert(pble_term_remaining_us(&state, &ticket,
                                  INT64_C(3499900)) == INT64_C(100));
    assert(pble_term_remaining_us(&state, &ticket,
                                  INT64_C(3500000)) == 0);
    assert_effects(
        pble_term_watchdog_fired(&state, &ticket, INT64_C(3499900)),
        PBLE_TERM_EFFECT_REARM_WATCHDOG);
    assert_effects(
        pble_term_watchdog_rearmed(&state, &ticket, true),
        PBLE_TERM_EFFECT_NONE);
    assert(state.deadline_us == INT64_C(3500000));

    /* Deadline claims terminal restart before any external restart call. */
    assert_effects(
        pble_term_watchdog_fired(&state, &ticket, INT64_C(3500000)),
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
    pble_term_watchdog_ticket_t ticket;
    assert(pble_term_watchdog_ticket(&state, UINT16_C(7), UINT64_C(50),
                                     &ticket));

    assert_effects(pble_term_disconnect(&state, UINT16_C(8), UINT64_C(50)),
                   PBLE_TERM_EFFECT_NONE);
    assert_effects(pble_term_disconnect(&state, UINT16_C(7), UINT64_C(49)),
                   PBLE_TERM_EFFECT_NONE);
    assert(state.phase == PBLE_TERM_PHASE_CLOSING);

    assert_effects(pble_term_disconnect(&state, UINT16_C(7), UINT64_C(50)),
                   PBLE_TERM_EFFECT_STOP_WATCHDOG);
    assert(state.phase == PBLE_TERM_PHASE_CLEANING);
    assert_effects(pble_term_disconnect(&state, UINT16_C(7), UINT64_C(50)),
                   PBLE_TERM_EFFECT_NONE);
    assert_effects(pble_term_cleanup_complete(&state, UINT16_C(7), UINT64_C(50)),
                   PBLE_TERM_EFFECT_NONE);
    assert(state.phase == PBLE_TERM_PHASE_CLEANING);
    assert_effects(
        pble_term_watchdog_fired(&state, &ticket, INT64_MAX),
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

    /* NimBLE reset while CLOSING follows the same required-stop path. */
    open_and_arm(&state, UINT16_C(9), UINT64_C(55), INT64_C(3000000));
    assert_effects(pble_term_reset(&state), PBLE_TERM_EFFECT_STOP_WATCHDOG);
    assert(state.phase == PBLE_TERM_PHASE_CLEANING);
    assert_effects(
        pble_term_watchdog_stopped(&state, UINT16_C(9), UINT64_C(54), true),
        PBLE_TERM_EFFECT_NONE);
    assert_effects(
        pble_term_watchdog_stopped(&state, UINT16_C(9), UINT64_C(55), true),
        PBLE_TERM_EFFECT_INVALIDATE);
    assert_effects(pble_term_cleanup_complete(&state, UINT16_C(9), UINT64_C(55)),
                   PBLE_TERM_EFFECT_NONE);
    assert(state.phase == PBLE_TERM_PHASE_CLOSED);
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
    pble_term_watchdog_ticket_t ticket;
    assert(pble_term_watchdog_ticket(&state, UINT16_C(7), UINT64_C(62),
                                     &ticket));
    assert_effects(
        pble_term_watchdog_fired(&state, &ticket, INT64_C(5499999)),
        PBLE_TERM_EFFECT_REARM_WATCHDOG);
    assert_effects(
        pble_term_watchdog_rearmed(&state, &ticket, false),
        PBLE_TERM_EFFECT_RESTART);
    assert(state.phase == PBLE_TERM_PHASE_RESTARTING);

    /* Old callback remains inert while the reused handle's successor closes. */
    pble_term_init(&state);
    open_and_arm(&state, UINT16_C(7), UINT64_C(63), INT64_C(4000000));
    pble_term_watchdog_ticket_t stale_ticket;
    assert(pble_term_watchdog_ticket(&state, UINT16_C(7), UINT64_C(63),
                                     &stale_ticket));
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
        pble_term_watchdog_fired(&state, &stale_ticket, INT64_MAX),
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
        assert(mock_adapter_open(&mock, &state, UINT16_C(11),
                                 UINT64_C(70) + i));
        mock_adapter_begin(&mock, &state, UINT16_C(11), UINT64_C(70) + i,
                           INT64_C(1000000), INT64_C(1250000), true,
                           results[i]);
        mock_adapter_begin(&mock, &state, UINT16_C(11), UINT64_C(70) + i,
                           INT64_C(1250010), INT64_C(1250020), true,
                           results[i]);
        assert(mock.arm_calls == 1);
        assert(mock.last_arm_delay_us == INT64_C(2250000));
        assert(mock.gap_calls == 1);
        assert(mock.restart_calls == (results[i] == MOCK_GAP_ERROR ? 1u : 0u));
        assert(mock.order[0] == 'A');
        assert(mock.order[1] == 'G');
        assert(mock.critical_depth == 0);
        assert(mock.enter_calls == mock.exit_calls);
    }

    pble_term_state_t state;
    mock_adapter_t mock = {0};
    pble_term_init(&state);
    assert(mock_adapter_open(&mock, &state, UINT16_C(11), UINT64_C(80)));
    mock_adapter_begin(&mock, &state, UINT16_C(11), UINT64_C(80),
                       INT64_C(1000000), INT64_C(1000010), false,
                       MOCK_GAP_OK);
    assert(mock.arm_calls == 1);
    assert(mock.gap_calls == 0);
    assert(mock.restart_calls == 1);

    pble_term_init(&state);
    memset(&mock, 0, sizeof(mock));
    assert(mock_adapter_open(&mock, &state, UINT16_C(11), UINT64_C(81)));
    mock_adapter_begin(&mock, &state, UINT16_C(11), UINT64_C(81),
                       INT64_C(1000000), INT64_C(3500000), true,
                       MOCK_GAP_OK);
    assert(mock.arm_calls == 0);
    assert(mock.gap_calls == 0);
    assert(mock.restart_calls == 1);
    assert(state.phase == PBLE_TERM_PHASE_RESTARTING);

    pble_term_init(&state);
    memset(&mock, 0, sizeof(mock));
    assert(!mock_adapter_open(&mock, &state, UINT16_C(11), UINT64_C(0)));
    assert(mock.restart_calls == 1);
    pble_term_init(&state);
    memset(&mock, 0, sizeof(mock));
    assert(mock_adapter_open(&mock, &state, UINT16_C(11), UINT64_C(82)));
    assert(!mock_adapter_open(&mock, &state, UINT16_C(12), UINT64_C(83)));
    assert(mock.restart_calls == 1);
}

static void test_mock_adapter_cleanup_matrix(void) {
    pble_term_state_t state;
    mock_adapter_t mock = {0};

    /* Normal OPEN disconnect invalidates without touching the watchdog. */
    pble_term_init(&state);
    assert(mock_adapter_open(&mock, &state, UINT16_C(20), UINT64_C(90)));
    mock_adapter_cleanup(&mock, &state, UINT16_C(20), UINT64_C(90), false,
                         true, true);
    assert(mock.stop_calls == 0);
    assert(mock.invalidate_calls == 1);
    assert(mock.advertise_calls == 1);
    assert(mock.order[mock.order_len - 2] == 'I');
    assert(mock.order[mock.order_len - 1] == 'V');
    assert(state.phase == PBLE_TERM_PHASE_CLOSED);

    /* CLOSING disconnect proves stop before invalidation and advertising. */
    pble_term_init(&state);
    memset(&mock, 0, sizeof(mock));
    open_and_arm(&state, UINT16_C(20), UINT64_C(91), INT64_C(1000000));
    mock_adapter_term_failure(&mock, &state);
    mock_adapter_cleanup(&mock, &state, UINT16_C(20), UINT64_C(91), false,
                         true, true);
    assert(mock.stop_calls == 1);
    assert(mock.invalidate_calls == 1);
    assert(mock.advertise_calls == 1);
    assert(mock.order_len == 3);
    assert(memcmp(mock.order, "SIV", 3) == 0);
    assert(state.phase == PBLE_TERM_PHASE_CLOSED);

    /* CLOSING NimBLE reset is the same stop path, without advertising. */
    pble_term_init(&state);
    memset(&mock, 0, sizeof(mock));
    open_and_arm(&state, UINT16_C(20), UINT64_C(92), INT64_C(2000000));
    mock_adapter_cleanup(&mock, &state, UINT16_C(20), UINT64_C(92), true,
                         true, false);
    assert(mock.stop_calls == 1);
    assert(mock.invalidate_calls == 1);
    assert(mock.advertise_calls == 0);
    assert(mock.order_len == 2);
    assert(memcmp(mock.order, "SI", 2) == 0);

    /* A stop result other than success is terminal and cancels nothing. */
    pble_term_init(&state);
    memset(&mock, 0, sizeof(mock));
    open_and_arm(&state, UINT16_C(20), UINT64_C(93), INT64_C(3000000));
    mock_adapter_cleanup(&mock, &state, UINT16_C(20), UINT64_C(93), false,
                         false, true);
    assert(mock.stop_calls == 1);
    assert(mock.invalidate_calls == 0);
    assert(mock.advertise_calls == 0);
    assert(mock.restart_calls == 1);
    assert(mock.order_len == 2);
    assert(memcmp(mock.order, "SR", 2) == 0);
    assert(state.phase == PBLE_TERM_PHASE_RESTARTING);
}

static void test_mock_adapter_callback_and_stale_matrix(void) {
    pble_term_state_t state;
    mock_adapter_t mock = {0};
    pble_term_watchdog_ticket_t ticket;

    pble_term_init(&state);
    open_and_arm(&state, UINT16_C(30), UINT64_C(100), INT64_C(1000000));
    assert(pble_term_watchdog_ticket(&state, UINT16_C(30), UINT64_C(100),
                                     &ticket));
    mock_adapter_watchdog(&mock, &state, ticket, INT64_C(3499900), true);
    assert(mock.rearm_calls == 1);
    assert(mock.last_arm_delay_us == INT64_C(100));
    assert(mock.restart_calls == 0);
    mock_adapter_watchdog(&mock, &state, ticket, INT64_C(3500000), true);
    assert(mock.restart_calls == 1);
    assert(state.phase == PBLE_TERM_PHASE_RESTARTING);

    pble_term_init(&state);
    memset(&mock, 0, sizeof(mock));
    open_and_arm(&state, UINT16_C(30), UINT64_C(101), INT64_C(2000000));
    assert(pble_term_watchdog_ticket(&state, UINT16_C(30), UINT64_C(101),
                                     &ticket));
    mock_adapter_watchdog(&mock, &state, ticket, INT64_C(4499999), false);
    assert(mock.rearm_calls == 1);
    assert(mock.restart_calls == 1);
    assert(state.phase == PBLE_TERM_PHASE_RESTARTING);

    /* An immutable old ticket is inert after exact cleanup and handle reuse. */
    pble_term_init(&state);
    memset(&mock, 0, sizeof(mock));
    open_and_arm(&state, UINT16_C(30), UINT64_C(102), INT64_C(3000000));
    assert(pble_term_watchdog_ticket(&state, UINT16_C(30), UINT64_C(102),
                                     &ticket));
    mock_adapter_cleanup(&mock, &state, UINT16_C(30), UINT64_C(102), false,
                         true, false);
    open_and_arm(&state, UINT16_C(30), UINT64_C(103), INT64_C(4000000));
    unsigned calls_before = mock.rearm_calls + mock.restart_calls;
    int64_t successor_deadline = state.deadline_us;
    mock_adapter_watchdog(&mock, &state, ticket, INT64_MAX, true);
    assert(mock.rearm_calls + mock.restart_calls == calls_before);
    assert(state.phase == PBLE_TERM_PHASE_CLOSING);
    assert(state.deadline_us == successor_deadline);
    mock_adapter_term_failure(&mock, &state);
    assert(mock.critical_depth == 0);
    assert(mock.enter_calls == mock.exit_calls);
}

static void test_open_generation_rotation(void) {
    pble_term_state_t state;
    pble_term_init(&state);
    assert(pble_term_open(&state, UINT16_C(40), UINT64_C(110)));

    /* Only the exact OPEN owner may rotate to a fresh nonzero generation. */
    assert(!pble_term_rotate_open(&state, UINT16_C(41), UINT64_C(110),
                                  UINT64_C(111)));
    assert(!pble_term_rotate_open(&state, UINT16_C(40), UINT64_C(109),
                                  UINT64_C(111)));
    assert(!pble_term_rotate_open(&state, UINT16_C(40), UINT64_C(110),
                                  UINT64_C(0)));
    assert(!pble_term_rotate_open(&state, UINT16_C(40), UINT64_C(110),
                                  UINT64_C(110)));
    assert(pble_term_admits(&state, UINT16_C(40), UINT64_C(110)));

    assert(pble_term_rotate_open(&state, UINT16_C(40), UINT64_C(110),
                                 UINT64_C(111)));
    assert(!pble_term_admits(&state, UINT16_C(40), UINT64_C(110)));
    assert(pble_term_admits(&state, UINT16_C(40), UINT64_C(111)));
    assert(state.deadline_us == 0);
    assert(!state.watchdog_armed);
    assert(!state.watchdog_rearm_pending);
    assert(!state.cleanup_stop_required);
    assert(!state.cleanup_allowed);

    /* Rotation cannot erase a CLOSING claim or its watchdog. */
    assert_effects(
        pble_term_begin(&state, UINT16_C(40), UINT64_C(111), INT64_C(1)),
        PBLE_TERM_EFFECT_ARM_WATCHDOG);
    assert(!pble_term_rotate_open(&state, UINT16_C(40), UINT64_C(111),
                                  UINT64_C(112)));
    assert(state.phase == PBLE_TERM_PHASE_CLOSING);
    assert(state.generation == UINT64_C(111));
}

int main(void) {
    test_begin_and_terminal_deadline();
    test_exact_cleanup_and_timer_stop();
    test_failure_matrix_and_stale_successor();
    test_mock_adapter_one_call_matrix();
    test_mock_adapter_cleanup_matrix();
    test_mock_adapter_callback_and_stale_matrix();
    test_open_generation_rotation();
    puts("failed-session termination reducer: all scenarios passed");
    return 0;
}
