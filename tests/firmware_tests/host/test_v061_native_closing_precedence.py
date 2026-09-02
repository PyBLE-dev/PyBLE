#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""RED native contract for global SOFT_REBOOT closing precedence."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / "firmware" / "user_c_modules" / "pyble"
PROTO = NATIVE / "pble_proto.c"
WIRE = NATIVE / "pble_wire.c"


class NativeClosingPrecedenceTest(unittest.TestCase):
    """Exercise production dispatch on an unnegotiated successor session."""

    def test_successor_commands_observe_global_closing_before_wire_session(self):
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler, "a host C compiler is required")

        proto_source = PROTO.read_text(encoding="utf-8", errors="strict")
        marker = "// --- MicroPython module shim"
        self.assertIn(marker, proto_source)
        # Compile the production protocol core verbatim.  The MicroPython-only
        # module registration below this marker is unrelated to dispatch and
        # would otherwise require the complete target object ABI on the host.
        proto_core = proto_source.partition(marker)[0]

        with tempfile.TemporaryDirectory(
            prefix="pyble-v061-native-closing-"
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
            (temp / "freertos" / "FreeRTOS.h").write_text(
                FREERTOS_STUB, encoding="utf-8"
            )
            (temp / "freertos" / "task.h").write_text(
                TASK_STUB, encoding="utf-8"
            )
            (temp / "freertos" / "semphr.h").write_text(
                SEMPHR_STUB, encoding="utf-8"
            )

            harness = temp / "native_closing_harness.c"
            harness.write_text(proto_core + HARNESS, encoding="utf-8")
            executable = temp / "native_closing_harness"
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
                    str(WIRE),
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
                "native closing harness did not compile:\n" + compiled.stderr,
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
                "native dispatch violated closing precedence:\n"
                + completed.stderr,
            )


RUNTIME_STUB = r"""
#ifndef MP_RUNTIME_H
#define MP_RUNTIME_H
typedef struct { int unused; } mp_obj_type_t;
extern const mp_obj_type_t mp_type_RuntimeError;
#define MP_ERROR_TEXT(text) (text)
void mp_raise_msg(const mp_obj_type_t *type, const char *message);
#endif
"""


FREERTOS_STUB = r"""
#ifndef FREERTOS_H
#define FREERTOS_H
#include <stdint.h>
typedef uint32_t TickType_t;
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
int xSemaphoreGive(SemaphoreHandle_t semaphore);
#endif
"""


HARNESS = r"""

#include <stdio.h>
#include <stdlib.h>

const mp_obj_type_t mp_type_RuntimeError = {0};

static unsigned violation_debits;
static unsigned handler_effects;
static unsigned notify_effects;
static uint64_t harness_epoch = 7u;

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

int xSemaphoreGive(SemaphoreHandle_t semaphore) {
    semaphore->count++;
    return pdTRUE;
}

TickType_t xTaskGetTickCount(void) {
    return 1u;
}

bool pble_ble_session_live(const pble_session_token_t *session) {
    return session != NULL && session->vm_epoch == harness_epoch;
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
    notify_effects++;
    return PBLE_TX_OK;
}

uint64_t pble_vm_epoch_current(void) {
    return harness_epoch;
}

bool pble_vm_epoch_valid(uint64_t epoch) {
    return epoch == harness_epoch;
}

bool pble_vm_reboot_command_admitted(bool is_soft_reboot) {
    // Model the committed 250 ms grace: the legacy provisional gate admits
    // SOFT so its handler can report the duplicate, but rejects other work.
    // A global closing-precedence check calls this with false before applying
    // the fresh successor's HELLO-first wire-session gate.
    return is_soft_reboot;
}

static uint8_t side_effect_handler(
    const pble_frame_t *request, uint8_t *response, size_t *response_length,
    const pble_session_token_t *session) {
    (void)request;
    (void)response;
    (void)session;
    handler_effects++;
    *response_length = 0u;
    return PBLE_OK;
}

static void dispatch_empty_command(uint8_t opcode, uint8_t id,
                                   const pble_session_token_t *session) {
    uint8_t frame[16];
    int length = pble_proto_encode(
        PBLE_TYPE_CMD, opcode, id, NULL, 0u, frame, sizeof(frame));
    if (length <= 0) {
        fprintf(stderr, "could not encode opcode 0x%02x\n", opcode);
        abort();
    }
    pble_proto_dispatch_admitted(frame, (size_t)length, session);
}

static int take_status(uint8_t opcode, uint8_t id) {
    pble_rsp_tx_t tx;
    if (!pble_rsp_tx_peek(&tx)) {
        return -1;
    }
    int status = -2;
    if (tx.frame_len >= PBLE_HDR_LEN + 1u + PBLE_CRC_LEN &&
        tx.frame[0] == PBLE_PROTO_VERSION &&
        tx.frame[1] == PBLE_TYPE_RSP && tx.frame[2] == opcode &&
        tx.frame[3] == id && tx.frame[4] == 1u && tx.frame[5] == 0u) {
        status = tx.frame[PBLE_HDR_LEN];
    }
    pble_rsp_tx_result(&tx, tx.stream_generation, tx.offset, tx.index,
                       tx.frame_len, PBLE_TX_OK);
    return status;
}

static void expect_equal(const char *label, unsigned actual, unsigned expected,
                         unsigned *failures) {
    if (actual != expected) {
        fprintf(stderr, "%s: got %u, expected %u\n", label, actual, expected);
        (*failures)++;
    }
}

int main(void) {
    const pble_session_token_t successor = {
        .conn = 0x0044u,
        .generation = 2u,
        .vm_epoch = 7u,
    };
    unsigned failures = 0u;
    unsigned before;

    pble_proto_register(PBLE_OP_DEVICE_INFO, side_effect_handler);
    pble_proto_register_special(PBLE_OP_SOFT_REBOOT, side_effect_handler);
    pble_proto_register_no_response(
        PBLE_OP_CONSOLE_INPUT, side_effect_handler);

    before = violation_debits;
    dispatch_empty_command(PBLE_OP_DEVICE_INFO, 0x31u, &successor);
    expect_equal("response-bearing status",
                 (unsigned)take_status(PBLE_OP_DEVICE_INFO, 0x31u),
                 PBLE_EBUSY, &failures);
    expect_equal("response-bearing violation debit", violation_debits, before,
                 &failures);

    before = violation_debits;
    dispatch_empty_command(PBLE_OP_SOFT_REBOOT, 0x32u, &successor);
    expect_equal("successor duplicate SOFT status",
                 (unsigned)take_status(PBLE_OP_SOFT_REBOOT, 0x32u),
                 PBLE_EBUSY, &failures);
    expect_equal("successor duplicate SOFT violation debit", violation_debits,
                 before, &failures);

    before = violation_debits;
    dispatch_empty_command(PBLE_OP_CONSOLE_INPUT, 0x33u, &successor);
    expect_equal("CONSOLE_INPUT violation debit", violation_debits, before,
                 &failures);
    expect_equal("CONSOLE_INPUT response", pble_rsp_has_pending(), false,
                 &failures);

    expect_equal("handler side effects", handler_effects, 0u, &failures);
    expect_equal("direct notify side effects", notify_effects, 0u, &failures);
    return failures == 0u ? EXIT_SUCCESS : EXIT_FAILURE;
}
"""


if __name__ == "__main__":
    unittest.main()
