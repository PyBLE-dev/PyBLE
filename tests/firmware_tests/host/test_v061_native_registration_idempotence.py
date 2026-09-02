#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""Compile the native same-VM registration paths against retained state.

The v0.6.1 lifecycle contract permits repeating ``pble_ble.init_agent()`` in
one VM.  Its registration calls must therefore preserve live runtime state.
This harness extracts the unchanged production C function bodies; the fake
RTOS/protocol seams only make the already-created objects deterministic.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / "firmware" / "user_c_modules" / "pyble"


def _matching_brace(source: str, opening: int) -> int:
    depth = 0
    state = "code"
    index = opening
    while index < len(source):
        char = source[index]
        nxt = source[index + 1] if index + 1 < len(source) else ""
        if state == "line-comment":
            if char == "\n":
                state = "code"
        elif state == "block-comment":
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
            state = "line-comment"
            index += 1
        elif char == "/" and nxt == "*":
            state = "block-comment"
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
                return index
        index += 1
    raise AssertionError("unbalanced C function body")


def _function(source: str, name: str) -> str:
    match = re.search(
        r"(?m)^[ \t]*(?:static[ \t]+)?[A-Za-z_]"
        r"[A-Za-z0-9_ \t*]*\b"
        + re.escape(name)
        + r"[ \t]*\([^;{}]*\)[ \t]*\{",
        source,
    )
    if match is None:
        raise AssertionError("native function `{}` is missing".format(name))
    opening = source.find("{", match.start(), match.end())
    closing = _matching_brace(source, opening)
    return source[match.start(): closing + 1]


class NativeRegistrationIdempotenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        compiler = shutil.which(os.environ.get("CC", "cc"))
        if compiler is None:
            raise unittest.SkipTest("a host C compiler is required")

        fs_source = (NATIVE / "pble_fs.c").read_text(encoding="utf-8")
        lock_source = (NATIVE / "pble_lock.c").read_text(encoding="utf-8")
        production = "\n\n".join(
            [
                _function(fs_source, "fs_put_reset_locked"),
                _function(fs_source, "fs_put_reset"),
                _function(fs_source, "pble_fs_register"),
                _function(lock_source, "lock_slot_for"),
                _function(lock_source, "pble_lock_acquire"),
                _function(lock_source, "pble_lock_register"),
            ]
        )

        cls._temporary = tempfile.TemporaryDirectory(
            prefix="pyble-v061-native-register-"
        )
        temp = Path(cls._temporary.name)
        harness = temp / "native_registration_idempotence.c"
        harness.write_text(
            PRELUDE + "\n\n" + production + "\n\n" + SCENARIOS,
            encoding="utf-8",
        )
        cls.binary = temp / "native_registration_idempotence"
        built = subprocess.run(
            [
                compiler,
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(harness),
                "-o",
                str(cls.binary),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if built.returncode != 0:
            raise AssertionError(
                "native registration harness did not compile:\n{}{}".format(
                    built.stdout, built.stderr
                )
            )

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "_temporary"):
            cls._temporary.cleanup()

    def run_scenario(self, scenario: str) -> None:
        completed = subprocess.run(
            [str(self.binary), scenario],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            "native registration scenario {!r} failed:\n{}{}".format(
                scenario, completed.stdout, completed.stderr
            ),
        )

    def test_repeated_fs_registration_preserves_active_rooted_put(self) -> None:
        self.run_scenario("filesystem")

    def test_repeated_lock_registration_preserves_writer_owners(self) -> None:
        self.run_scenario("writer-locks")


PRELUDE = r"""
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PBLE_OK      0x00u
#define PBLE_EBADREQ 0x01u
#define PBLE_EBUSY   0x07u

#define PBLE_OP_FILE_LIST      0x10u
#define PBLE_OP_FILE_STAT      0x11u
#define PBLE_OP_FILE_GET_BEGIN 0x12u
#define PBLE_OP_FILE_PUT_BEGIN 0x15u
#define PBLE_OP_FILE_PUT_DATA  0x16u
#define PBLE_OP_FILE_PUT_END   0x17u
#define PBLE_OP_FILE_DELETE    0x18u
#define PBLE_OP_MKDIR          0x19u
#define PBLE_OP_FILE_RENAME    0x1au
#define PBLE_FS_QDEPTH         10u
#define PBLE_FS_PATH_BUF       160u

#define pdTRUE 1
#define portMAX_DELAY UINT32_MAX
typedef int BaseType_t;
typedef void *QueueHandle_t;
typedef void *SemaphoreHandle_t;
typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
#define taskENTER_CRITICAL(mux) ((void)(mux))
#define taskEXIT_CRITICAL(mux) ((void)(mux))

static int g_queue_object;
static int g_gate_object;
static int g_work_object;
static QueueHandle_t xQueueCreate(unsigned depth, size_t size) {
    (void)depth;
    (void)size;
    return &g_queue_object;
}
static SemaphoreHandle_t xSemaphoreCreateMutex(void) {
    return &g_gate_object;
}
static SemaphoreHandle_t xSemaphoreCreateCounting(unsigned maximum,
                                                   unsigned initial) {
    (void)maximum;
    (void)initial;
    return &g_work_object;
}
static BaseType_t xSemaphoreTake(SemaphoreHandle_t semaphore,
                                 uint32_t timeout) {
    (void)semaphore;
    (void)timeout;
    return pdTRUE;
}
static BaseType_t xSemaphoreGive(SemaphoreHandle_t semaphore) {
    (void)semaphore;
    return pdTRUE;
}

typedef uintptr_t mp_obj_t;
#define MP_OBJ_NULL ((mp_obj_t)0)
static mp_obj_t g_root_pble_fs_put_file;
#define MP_STATE_VM(name) g_root_##name
#define MP_ERROR_TEXT(text) (text)
static int mp_type_RuntimeError;
static void mp_raise_msg(const int *type, const char *message) {
    (void)type;
    fprintf(stderr, "unexpected MicroPython raise: %s\n", message);
    abort();
}

typedef struct { uint8_t unused; } pble_frame_t;
typedef struct { uint8_t unused; } pble_session_token_t;
typedef struct { uint8_t unused; } pble_rsp_ticket_t;
typedef struct { uint8_t unused; } pble_fs_req_t;
typedef uint8_t (*pble_deferred_handler_t)(
    const pble_frame_t *, uint8_t *, size_t *,
    const pble_session_token_t *, const pble_rsp_ticket_t *);
typedef uint8_t (*pble_handler_t)(
    const pble_frame_t *, uint8_t *, size_t *,
    const pble_session_token_t *);

#define DEFINE_DEFERRED(name)                                                \
    static uint8_t name(const pble_frame_t *frame, uint8_t *response,        \
                        size_t *length, const pble_session_token_t *session,  \
                        const pble_rsp_ticket_t *ticket) {                    \
        (void)frame; (void)response; (void)length; (void)session;             \
        (void)ticket; return PBLE_OK;                                         \
    }
#define DEFINE_HANDLER(name)                                                 \
    static uint8_t name(const pble_frame_t *frame, uint8_t *response,        \
                        size_t *length, const pble_session_token_t *session) { \
        (void)frame; (void)response; (void)length; (void)session;             \
        return PBLE_OK;                                                       \
    }
DEFINE_DEFERRED(pble_fs_list)
DEFINE_DEFERRED(pble_fs_stat)
DEFINE_DEFERRED(pble_fs_get_begin)
DEFINE_DEFERRED(pble_fs_put_begin)
DEFINE_HANDLER(pble_fs_put_data)
DEFINE_DEFERRED(pble_fs_put_end)
DEFINE_DEFERRED(pble_fs_delete)
DEFINE_DEFERRED(pble_fs_mkdir)
DEFINE_DEFERRED(pble_fs_rename)

static void pble_proto_register_deferred(uint8_t opcode,
                                         pble_deferred_handler_t handler) {
    (void)opcode;
    (void)handler;
}
static void pble_proto_register_no_response(uint8_t opcode,
                                            pble_handler_t handler) {
    (void)opcode;
    (void)handler;
}

static QueueHandle_t g_fs_q;
static SemaphoreHandle_t g_fs_gate;
static SemaphoreHandle_t g_fs_work;
static bool g_fs_admission_open;
static portMUX_TYPE g_fs_transfer_mux = portMUX_INITIALIZER_UNLOCKED;
static bool g_put_active;
static char g_put_temp[PBLE_FS_PATH_BUF];
static char g_put_dest[PBLE_FS_PATH_BUF];
static uint32_t g_put_total;
static uint32_t g_put_crc_target;
static uint32_t g_put_watermark;
static uint32_t g_put_crc_running;
static uint8_t g_put_latched;
static uint64_t g_put_generation;

typedef enum {
    PBLE_W_NONE = 0,
    PBLE_W_RUN = 1,
    PBLE_W_XFER = 2,
} pble_writer_t;
typedef struct {
    bool held;
    uint16_t conn;
} lock_slot_t;
static lock_slot_t g_run_slot;
static lock_slot_t g_xfer_slot;
static portMUX_TYPE g_lock_mux = portMUX_INITIALIZER_UNLOCKED;
"""


SCENARIOS = r"""
static int scenario_filesystem(void) {
    pble_fs_register();

    g_put_active = true;
    g_put_generation = UINT64_C(17);
    strcpy(g_put_temp, "/demo.py.pbltmp");
    strcpy(g_put_dest, "/demo.py");
    g_put_total = 100u;
    g_put_crc_target = 0x12345678u;
    g_put_watermark = 40u;
    g_put_crc_running = 0x87654321u;
    g_put_latched = PBLE_EBUSY;
    g_root_pble_fs_put_file = (mp_obj_t)(uintptr_t)0x1234u;

    pble_fs_register();

    if (!g_put_active || g_put_generation != UINT64_C(17) ||
        strcmp(g_put_temp, "/demo.py.pbltmp") != 0 ||
        strcmp(g_put_dest, "/demo.py") != 0 || g_put_total != 100u ||
        g_put_crc_target != 0x12345678u || g_put_watermark != 40u ||
        g_put_crc_running != 0x87654321u || g_put_latched != PBLE_EBUSY ||
        g_root_pble_fs_put_file != (mp_obj_t)(uintptr_t)0x1234u) {
        fprintf(stderr,
                "repeated pble_fs_register discarded active PUT state "
                "without closing/preserving its rooted file\n");
        return 1;
    }
    return 0;
}

static int scenario_writer_locks(void) {
    pble_lock_register();
    if (pble_lock_acquire(PBLE_W_RUN, 41u) != PBLE_OK ||
        pble_lock_acquire(PBLE_W_XFER, 41u) != PBLE_OK) {
        fprintf(stderr, "could not establish writer ownership\n");
        return 2;
    }

    pble_lock_register();

    if (!g_run_slot.held || g_run_slot.conn != 41u ||
        !g_xfer_slot.held || g_xfer_slot.conn != 41u ||
        pble_lock_acquire(PBLE_W_RUN, 99u) != PBLE_EBUSY ||
        pble_lock_acquire(PBLE_W_XFER, 99u) != PBLE_EBUSY) {
        fprintf(stderr,
                "repeated pble_lock_register released live writer owners\n");
        return 1;
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "expected one scenario\n");
        return 2;
    }
    if (strcmp(argv[1], "filesystem") == 0) {
        return scenario_filesystem();
    }
    if (strcmp(argv[1], "writer-locks") == 0) {
        return scenario_writer_locks();
    }
    fprintf(stderr, "unknown scenario: %s\n", argv[1]);
    return 2;
}
"""


if __name__ == "__main__":
    unittest.main()
