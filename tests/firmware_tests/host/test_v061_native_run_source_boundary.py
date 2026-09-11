#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""Compiled native integration guard for the maximum RUN-source boundary."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / "firmware" / "user_c_modules" / "pyble"
BLE_PATH = NATIVE / "pble_ble.c"
PROTO_PATH = NATIVE / "pble_proto.c"
RUNNER_PATH = NATIVE / "pble_runner.c"
WIRE_PATH = NATIVE / "pble_wire.c"


def _function(source: str, name: str) -> str:
    match = re.search(
        r"(?m)^[^\n;{}]*\b" + re.escape(name) + r"\s*\([^;{}]*\)\s*\{",
        source,
    )
    if match is None:
        raise AssertionError("production function `{}` is missing".format(name))
    opening = source.find("{", match.start(), match.end())
    depth = 0
    state = "code"
    index = opening
    while index < len(source):
        char = source[index]
        nxt = source[index + 1] if index + 1 < len(source) else ""
        if state == "line":
            if char == "\n":
                state = "code"
        elif state == "block":
            if char == "*" and nxt == "/":
                state = "code"
                index += 1
        elif state == "string":
            if char == "\\":
                index += 1
            elif char == '"':
                state = "code"
        elif state == "char":
            if char == "\\":
                index += 1
            elif char == "'":
                state = "code"
        elif char == "/" and nxt == "/":
            state = "line"
            index += 1
        elif char == "/" and nxt == "*":
            state = "block"
            index += 1
        elif char == '"':
            state = "string"
        elif char == "'":
            state = "char"
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[match.start() : index + 1]
        index += 1
    raise AssertionError("unbalanced production function `{}`".format(name))


def _integer_define(source: str, name: str) -> int:
    match = re.search(
        r"(?m)^\s*#\s*define\s+{}\s+(\d+)\b".format(re.escape(name)),
        source,
    )
    if match is None:
        raise AssertionError("production define `{}` is missing".format(name))
    return int(match.group(1))


class NativeRunSourceBoundaryTest(unittest.TestCase):
    def test_full_native_path_reaches_runner_at_2048_and_2049_bytes(self):
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler, "a host C compiler is required")

        ble = BLE_PATH.read_text(encoding="utf-8", errors="strict")
        proto = PROTO_PATH.read_text(encoding="utf-8", errors="strict")
        runner = RUNNER_PATH.read_text(encoding="utf-8", errors="strict")
        message_max = _integer_define(ble, "PBLE_MSG_MAX")
        runner_max = _integer_define(runner, "PBLE_RUN_BUF_MAX")
        self.assertEqual(runner_max, 2048)

        marker = "// --- MicroPython module shim"
        self.assertIn(marker, proto)
        # This is the exact production protocol core. Only its MicroPython
        # module-registration tail is omitted because it is unrelated to RX.
        protocol_core = proto.partition(marker)[0]
        production_functions = "\n\n".join(
            (
                _function(ble, "pble_reset_reassembly"),
                _function(ble, "pble_discard_reassembly_tail"),
                _function(ble, "pble_rx_ingest"),
                _function(runner, "pble_rsm_init"),
                _function(runner, "pble_rsm_on_run"),
                _function(runner, "pble_runner_run"),
            )
        )

        with tempfile.TemporaryDirectory(
            prefix="pyble-v061-native-run-boundary-"
        ) as temporary:
            temp = Path(temporary)
            (temp / "py").mkdir()
            (temp / "freertos").mkdir()
            (temp / "py" / "runtime.h").write_text(
                RUNTIME_STUB, encoding="utf-8"
            )
            (temp / "py" / "obj.h").write_text(
                "#ifndef MP_OBJ_H\n#define MP_OBJ_H\n#endif\n",
                encoding="utf-8",
            )
            (temp / "py" / "mpstate.h").write_text(
                MPSTATE_STUB, encoding="utf-8"
            )
            (temp / "freertos" / "FreeRTOS.h").write_text(
                FREERTOS_STUB, encoding="utf-8"
            )
            (temp / "freertos" / "task.h").write_text(
                TASK_STUB, encoding="utf-8"
            )
            (temp / "freertos" / "semphr.h").write_text(
                SEMPHR_STUB, encoding="utf-8"
            )

            harness = temp / "native_run_boundary.c"
            harness.write_text(
                protocol_core
                + HARNESS_PREAMBLE.replace("__MESSAGE_MAX__", str(message_max))
                .replace("__RUNNER_MAX__", str(runner_max))
                + production_functions
                + HARNESS_MAIN,
                encoding="utf-8",
            )
            executable = temp / "native_run_boundary"
            linker_gc = (
                "-Wl,-dead_strip"
                if sys.platform == "darwin"
                else "-Wl,--gc-sections"
            )
            compiled = subprocess.run(
                [
                    compiler,
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-ffunction-sections",
                    "-fdata-sections",
                    "-I",
                    str(temp),
                    "-I",
                    str(NATIVE),
                    str(harness),
                    str(WIRE_PATH),
                    linker_gc,
                    "-o",
                    str(executable),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(
                compiled.returncode,
                0,
                "native RUN-boundary harness did not compile:\n"
                + compiled.stderr,
            )

            completed = subprocess.run(
                [str(executable)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                "native RUN-boundary integration failed:\n" + completed.stderr,
            )


RUNTIME_STUB = r"""
#ifndef MP_RUNTIME_H
#define MP_RUNTIME_H
#include <stddef.h>
typedef void *mp_obj_t;
typedef struct { int unused; } mp_obj_type_t;
extern const mp_obj_type_t mp_type_RuntimeError;
#define MP_OBJ_NULL ((mp_obj_t)0)
#define MP_ERROR_TEXT(text) (text)
void mp_raise_msg(const mp_obj_type_t *type, const char *message);
#endif
"""


MPSTATE_STUB = r"""
#ifndef MP_STATE_H
#define MP_STATE_H
#include "runtime.h"
typedef struct {
    mp_obj_t mp_pending_exception;
} mp_state_thread_t;
#endif
"""


FREERTOS_STUB = r"""
#ifndef FREERTOS_H
#define FREERTOS_H
#include <assert.h>
#include <stdint.h>
typedef uint32_t TickType_t;
typedef int BaseType_t;
typedef struct { unsigned count; } StaticSemaphore_t;
typedef StaticSemaphore_t *SemaphoreHandle_t;
typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portMAX_DELAY UINT32_MAX
#define pdTRUE 1
#define pdFALSE 0
#define pdMS_TO_TICKS(milliseconds) ((TickType_t)(milliseconds))
#define taskENTER_CRITICAL(mux) ((void)(mux))
#define taskEXIT_CRITICAL(mux) ((void)(mux))
#define configASSERT(condition) assert(condition)
#endif
"""


TASK_STUB = r"""
#ifndef FREERTOS_TASK_H
#define FREERTOS_TASK_H
#include "FreeRTOS.h"
TickType_t xTaskGetTickCount(void);
#endif
"""


SEMPHR_STUB = r"""
#ifndef FREERTOS_SEMPHR_H
#define FREERTOS_SEMPHR_H
#include "FreeRTOS.h"
SemaphoreHandle_t xSemaphoreCreateBinaryStatic(StaticSemaphore_t *storage);
int xSemaphoreTake(SemaphoreHandle_t semaphore, TickType_t timeout);
BaseType_t xSemaphoreGive(SemaphoreHandle_t semaphore);
#endif
"""


HARNESS_PREAMBLE = r"""

#include <stdio.h>
#include <stdlib.h>
#include "py/mpstate.h"
#include "pble_runner.h"

#define PBLE_MSG_MAX __MESSAGE_MAX__
#define PBLE_RX_REASSEMBLY_DEADLINE_US 5000000LL
#define PBLE_FRAG_FIRST 0x80u
#define PBLE_FRAG_LAST 0x40u
#define PBLE_FRAG_IDX_MASK 0x3fu
#define PBLE_FRAG_IDX_MOD 64u
#define PBLE_RUN_PATH_MAX 128u
#define PBLE_RUN_BUF_MAX __RUNNER_MAX__

static uint8_t pble_rx_buf[PBLE_MSG_MAX];
static size_t pble_rx_len;
static bool pble_rx_active;
static uint8_t pble_rx_next_index;
static int64_t pble_rx_started_us;
static bool pble_rx_discard_tail;

static pble_rsm_t g_rsm;
static portMUX_TYPE g_mux = portMUX_INITIALIZER_UNLOCKED;
static StaticSemaphore_t run_sem_storage;
static SemaphoreHandle_t g_run_sem = &run_sem_storage;
static mp_state_thread_t *volatile g_worker_state;
static volatile bool g_stop_requested;
static uint8_t g_run_mode;
static size_t g_run_len;
static char g_run_buf[PBLE_RUN_BUF_MAX];

static pble_session_token_t live_session = {
    .conn = 0x0042u,
    .generation = 3u,
    .vm_epoch = 9u,
};
static unsigned protocol_dispatches;
static unsigned runner_calls;
static uint16_t runner_lengths[2];
static unsigned violation_debits;
static unsigned specialized_responses;
static uint8_t specialized_status;
static unsigned stdin_begins;

int64_t esp_timer_get_time(void);
void pble_console_stdin_begin(void);
"""


HARNESS_MAIN = r"""

const mp_obj_type_t mp_type_RuntimeError = {0};

void mp_raise_msg(const mp_obj_type_t *type, const char *message) {
    (void)type;
    fprintf(stderr, "unexpected MicroPython raise: %s\n", message);
    abort();
}

SemaphoreHandle_t xSemaphoreCreateBinaryStatic(StaticSemaphore_t *storage) {
    storage->count = 0u;
    return storage;
}

int xSemaphoreTake(SemaphoreHandle_t semaphore, TickType_t timeout) {
    (void)timeout;
    if (semaphore->count == 0u) {
        return pdFALSE;
    }
    semaphore->count--;
    return pdTRUE;
}

BaseType_t xSemaphoreGive(SemaphoreHandle_t semaphore) {
    semaphore->count++;
    return pdTRUE;
}

TickType_t xTaskGetTickCount(void) {
    return 1u;
}

int64_t esp_timer_get_time(void) {
    return 100;
}

bool pble_ble_session_snapshot(uint16_t expected_conn,
                               pble_session_token_t *session) {
    if (session == NULL || expected_conn != live_session.conn) {
        return false;
    }
    *session = live_session;
    protocol_dispatches++;
    return true;
}

bool pble_ble_session_live(const pble_session_token_t *session) {
    return session != NULL && session->conn == live_session.conn &&
           session->generation == live_session.generation &&
           session->vm_epoch == live_session.vm_epoch;
}

bool pble_ble_record_protocol_violation(
    const pble_session_token_t *session) {
    (void)session;
    violation_debits++;
    return true;
}

void pble_ble_terminate_session(const pble_session_token_t *session) {
    (void)session;
}

void pble_ble_rsp_kick(void) {
}

int pble_ble_notify(const uint8_t *message, size_t length,
                    const pble_session_token_t *session) {
    (void)message;
    (void)length;
    (void)session;
    return PBLE_TX_OK;
}

int pble_ble_notify_control_try_for_conn(
    const uint8_t *message, size_t length,
    const pble_session_token_t *session) {
    if (!pble_ble_session_live(session) || length != 11u ||
        message[0] != PBLE_PROTO_VERSION || message[1] != PBLE_TYPE_RSP ||
        message[2] != PBLE_OP_RUN || message[4] != 1u || message[5] != 0u) {
        return PBLE_TX_NO_CONN;
    }
    specialized_responses++;
    specialized_status = message[6];
    return PBLE_TX_OK;
}

uint64_t pble_vm_epoch_current(void) {
    return live_session.vm_epoch;
}

bool pble_vm_epoch_valid(uint64_t epoch) {
    return epoch == live_session.vm_epoch;
}

bool pble_vm_dispatch_enter(uint64_t epoch, pble_vm_activity_t *activity) {
    activity->epoch = epoch;
    activity->active = epoch == live_session.vm_epoch;
    return activity->active;
}

void pble_vm_dispatch_leave(pble_vm_activity_t *activity) {
    activity->active = false;
}

bool pble_vm_reboot_command_admitted(bool is_soft_reboot) {
    (void)is_soft_reboot;
    return true;
}

void pble_console_stdin_begin(void) {
    stdin_begins++;
}

static uint8_t observed_runner(
    const pble_frame_t *request, uint8_t *response, size_t *response_length,
    const pble_session_token_t *session) {
    if (runner_calls < 2u) {
        runner_lengths[runner_calls] = request->len;
    }
    runner_calls++;
    return pble_runner_run(request, response, response_length, session);
}

static int take_generic_status(uint8_t id) {
    pble_rsp_tx_t tx;
    if (!pble_rsp_tx_peek(&tx)) {
        return -1;
    }
    int status = -2;
    if (tx.frame_len == 11u && tx.frame[0] == PBLE_PROTO_VERSION &&
        tx.frame[1] == PBLE_TYPE_RSP && tx.frame[2] == PBLE_OP_RUN &&
        tx.frame[3] == id && tx.frame[4] == 1u && tx.frame[5] == 0u) {
        status = tx.frame[6];
    }
    pble_rsp_tx_result(&tx, tx.stream_generation, tx.offset, tx.index,
                       tx.frame_len, PBLE_TX_OK);
    return status;
}

static bool send_source(size_t source_length, uint8_t id) {
    uint8_t payload[1u + 2049u];
    uint8_t frame[PBLE_MSG_MAX];
    uint8_t fragment[32];
    payload[0] = PBLE_RUN_MODE_SOURCE;
    memset(payload + 1, 'x', source_length);
    int encoded = pble_proto_encode(PBLE_TYPE_CMD, PBLE_OP_RUN, id, payload,
                                    source_length + 1u, frame, sizeof(frame));
    if (encoded <= 0) {
        return false;
    }

    size_t offset = 0u;
    uint8_t index = 0u;
    while (offset < (size_t)encoded) {
        size_t chunk = (size_t)encoded - offset;
        if (chunk > sizeof(fragment) - 1u) {
            chunk = sizeof(fragment) - 1u;
        }
        uint8_t header = index & PBLE_FRAG_IDX_MASK;
        if (offset == 0u) {
            header |= PBLE_FRAG_FIRST;
        }
        if (offset + chunk == (size_t)encoded) {
            header |= PBLE_FRAG_LAST;
        }
        fragment[0] = header;
        memcpy(fragment + 1, frame + offset, chunk);
        pble_rx_ingest(fragment, chunk + 1u, &live_session);
        offset += chunk;
        index = (uint8_t)((index + 1u) % PBLE_FRAG_IDX_MOD);
    }
    return true;
}

static void expect_equal(const char *label, unsigned actual, unsigned expected,
                         unsigned *failures) {
    if (actual != expected) {
        fprintf(stderr, "%s: got %u, expected %u\n", label, actual, expected);
        (*failures)++;
    }
}

int main(void) {
    unsigned failures = 0u;
    pble_rsm_init(&g_rsm);
    pble_proto_register_special(PBLE_OP_RUN, observed_runner);

    // Establish the exact successor as already HELLO-negotiated. This test
    // begins at RX fragmentation, not at the unrelated HELLO exchange.
    s_wire_session_token = live_session;
    s_wire_session_bound = true;
    pble_wire_session_reset(&s_wire_session);
    pble_wire_session_commit_v1(&s_wire_session);

    if (!send_source(2048u, 0x61u)) {
        fprintf(stderr, "2048-byte RUN frame did not encode\n");
        return EXIT_FAILURE;
    }
    expect_equal("2048 dispatches", protocol_dispatches, 1u, &failures);
    expect_equal("2048 runner calls", runner_calls, 1u, &failures);
    expect_equal("2048 runner payload length", runner_lengths[0], 2049u,
                 &failures);
    expect_equal("2048 specialized responses", specialized_responses, 1u,
                 &failures);
    expect_equal("2048 status", specialized_status, PBLE_OK, &failures);
    expect_equal("2048 captured source length", (unsigned)g_run_len, 2048u,
                 &failures);
    expect_equal("2048 stdin begins", stdin_begins, 1u, &failures);
    expect_equal("2048 transport violations", violation_debits, 0u, &failures);
    expect_equal("2048 generic responses", pble_rsp_has_pending(), false,
                 &failures);

    if (!send_source(2049u, 0x62u)) {
        fprintf(stderr, "2049-byte RUN frame did not encode\n");
        return EXIT_FAILURE;
    }
    expect_equal("2049 dispatches", protocol_dispatches, 2u, &failures);
    expect_equal("2049 runner calls", runner_calls, 2u, &failures);
    expect_equal("2049 runner payload length", runner_lengths[1], 2050u,
                 &failures);
    expect_equal("2049 generic status",
                 (unsigned)take_generic_status(0x62u), PBLE_ERANGE, &failures);
    expect_equal("2049 specialized response count", specialized_responses, 1u,
                 &failures);
    expect_equal("2049 did not replace accepted source",
                 (unsigned)g_run_len, 2048u, &failures);
    expect_equal("2049 stdin begins", stdin_begins, 1u, &failures);
    expect_equal("2049 transport violations", violation_debits, 0u, &failures);
    return failures == 0u ? EXIT_SUCCESS : EXIT_FAILURE;
}
"""


if __name__ == "__main__":
    unittest.main()
