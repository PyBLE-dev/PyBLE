#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""Execute v0.6.1 native filesystem reducers against a fake VFS.

This test compiles the named function bodies directly from production
``pble_fs.c``.  The surrounding MicroPython/VFS and PBLE session surfaces are
small deterministic seams: assertions therefore exercise the C control flow
that ships, rather than a Python model of that control flow.
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
FS_SOURCE = NATIVE / "pble_fs.c"


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


PRODUCTION_FUNCTIONS = (
    "le32",
    "rd32",
    "rd16",
    "crc32_update",
    "pble_fs_errno_to_status",
    "fs_exc_to_status",
    "fs_reserved_prefix",
    "fs_has_tmp_suffix",
    "fs_utf8_valid",
    "pble_fs_resolve",
    "fs_is_forbidden_artifact",
    "fs_str",
    "fs_close_local",
    "fs_open",
    "fs_chunk",
    "fs_mode_is_regular",
    "fs_stat_path",
    "fs_crc_file",
    "fs_crc_prefix",
    "fs_do_list",
    "fs_do_get",
    "pble_fs_transfer_valid",
    "pble_fs_item_valid",
    "pble_fs_ticket_valid",
    "fs_put_close",
    "fs_put_reset_locked",
    "fs_put_owned",
    "fs_put_active_current",
    "fs_put_reset_owner",
    "fs_put_close_local",
    "fs_put_reconcile_stale",
    "pble_fs_on_disconnect",
    "fs_remove_malformed_scratch",
    "fs_put_space_status",
    "pble_fs_resume_prefix",
    "fs_put_abort",
    "fs_put_publish",
    "fs_do_put_begin",
    "fs_do_put_end",
    "fs_do_delete",
    "fs_do_mkdir",
    "fs_do_rename",
)


class NativeFsBehaviorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        compiler = shutil.which(os.environ.get("CC", "cc"))
        if compiler is None:
            raise unittest.SkipTest("a host C compiler is required")

        source = FS_SOURCE.read_text(encoding="utf-8", errors="strict")
        production = "\n\n".join(
            _function(source, name) for name in PRODUCTION_FUNCTIONS
        )
        cls._temporary = tempfile.TemporaryDirectory(
            prefix="pyble-v061-native-fs-behavior-"
        )
        temp = Path(cls._temporary.name)
        harness = temp / "native_fs_behavior.c"
        harness.write_text(
            PRELUDE + "\n\n" + production + "\n\n" + SCENARIOS,
            encoding="utf-8",
        )
        cls._executable = temp / "native_fs_behavior"
        compiled = subprocess.run(
            [
                compiler,
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(harness),
                "-o",
                str(cls._executable),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if compiled.returncode != 0:
            raise AssertionError(
                "native filesystem behavior harness did not compile:\n"
                + compiled.stdout
                + compiled.stderr
            )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def run_scenario(self, scenario: str) -> None:
        completed = subprocess.run(
            [str(self._executable), scenario],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            "native filesystem scenario {!r} failed:\n{}{}".format(
                scenario, completed.stdout, completed.stderr
            ),
        )

    def test_scratch_entries_are_hidden_before_budget_and_stat(self) -> None:
        self.run_scenario("listing")

    def test_capacity_uses_exact_reserve_and_checked_geometry(self) -> None:
        self.run_scenario("capacity")

    def test_malformed_resume_reads_preserve_the_old_destination(self) -> None:
        self.run_scenario("malformed-resume")

    def test_active_transfers_block_mutation_only_after_jail_resolution(self) -> None:
        self.run_scenario("mutation-gate")

    def test_stale_identity_cannot_publish_or_commit(self) -> None:
        self.run_scenario("identity")

    def test_crc_file_closes_after_post_open_invalidation(self) -> None:
        self.run_scenario("crc-file-open-close")

    def test_crc_file_closes_after_post_read_invalidation(self) -> None:
        self.run_scenario("crc-file-read-close")

    def test_crc_prefix_closes_after_post_open_invalidation(self) -> None:
        self.run_scenario("crc-prefix-open-close")

    def test_crc_prefix_closes_after_post_read_invalidation(self) -> None:
        self.run_scenario("crc-prefix-read-close")

    def test_get_closes_after_post_open_invalidation(self) -> None:
        self.run_scenario("get-open-close")

    def test_get_closes_after_post_read_invalidation(self) -> None:
        self.run_scenario("get-read-close")

    def test_put_begin_closes_local_handle_across_invalidation(self) -> None:
        self.run_scenario("put-begin-open-close")


PRELUDE = r"""
#define _POSIX_C_SOURCE 200809L
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#include <limits.h>

#define PBLE_OK           0x00u
#define PBLE_EBADREQ      0x01u
#define PBLE_ENOENT       0x02u
#define PBLE_EACCES       0x03u
#define PBLE_ENOSPC       0x04u
#define PBLE_EIO          0x05u
#define PBLE_ENOMEM       0x06u
#define PBLE_EBUSY        0x07u
#define PBLE_ECRC         0x08u
#define PBLE_ERANGE       0x09u
#define PBLE_EINTERNAL    0xffu
#define PBLE_NO_RSP       0xfeu
#define PBLE_RSP_MAX      480u
#define PBLE_OP_FILE_GET_BEGIN 0x12u
#define PBLE_OP_FILE_GET_DATA  0x13u
#define PBLE_OP_FILE_GET_END   0x14u
#define PBLE_TX_OK 0

#define PBLE_FS_ROOT           "/"
#define PBLE_FS_PATH_MAX       128u
#define PBLE_FS_PATH_BUF       160u
#define PBLE_FS_TMP_SUFFIX     ".pbltmp"
#define PBLE_FS_SAFETY_RESERVE 65536u
#define PBLE_FS_ITEM_PAYLOAD   260u
#define PBLE_FS_SCRATCH        512u
#define PBLE_FS_ENOTEMPTY      39
#define PBLE_CHUNK_OVERHEAD    18u

#define MP_ENOENT 2
#define MP_EIO 5
#define MP_ENOMEM 12
#define MP_EACCES 13
#define MP_EEXIST 17
#define MP_ENOTDIR 20
#define MP_EISDIR 21
#define MP_EINVAL 22
#define MP_ENOSPC 28
#define MP_EROFS 30
#define MP_ERANGE 34
#define MP_EPERM 1
#define MP_S_IFDIR 0x4000
#define MP_S_IFREG 0x8000
#define MP_STREAM_ERROR ((mp_uint_t)-1)
#define MP_THREAD_GIL_EXIT() do { } while (0)
#define MP_THREAD_GIL_ENTER() do { } while (0)

typedef long long mp_int_t;
typedef unsigned long long mp_uint_t;
typedef struct fake_obj fake_obj_t;
typedef fake_obj_t *mp_obj_t;
typedef struct { int unused; } mp_map_t;
typedef struct { int unused; } mp_obj_iter_buf_t;
typedef struct {
    mp_uint_t (*read)(mp_obj_t, void *, mp_uint_t, int *);
    mp_uint_t (*write)(mp_obj_t, const void *, mp_uint_t, int *);
} mp_stream_p_t;

typedef struct {
    uint16_t conn;
    uint32_t incarnation;
} pble_session_token_t;

typedef struct {
    uint8_t slot;
    uint32_t incarnation;
    pble_session_token_t session;
    uint64_t vm_epoch;
} pble_rsp_ticket_t;

typedef struct {
    uint8_t opcode;
    uint8_t id;
    pble_session_token_t session;
    uint64_t vm_epoch;
    uint64_t transfer_generation;
    bool get_active_at_enqueue;
    pble_rsp_ticket_t ticket;
    uint16_t len;
    uint8_t payload[PBLE_FS_ITEM_PAYLOAD];
} pble_fs_req_t;

typedef bool (*pble_fs_validator_t)(const pble_fs_req_t *it);

typedef struct nlr_buf {
    jmp_buf jump;
    void *ret_val;
    struct nlr_buf *previous;
} nlr_buf_t;

static nlr_buf_t *g_nlr_top;
#define nlr_push(buffer)                                                   \
    (((buffer)->previous = g_nlr_top), (g_nlr_top = (buffer)),             \
     setjmp((buffer)->jump))
#define nlr_pop() do {                                                     \
    g_nlr_top = g_nlr_top->previous;                                       \
} while (0)

enum fake_kind {
    FAKE_INT,
    FAKE_STRING,
    FAKE_ARRAY,
    FAKE_ITERATOR,
    FAKE_FILE,
    FAKE_EXCEPTION,
};

struct fake_obj {
    enum fake_kind kind;
    mp_int_t integer;
    const char *string;
    size_t length;
    mp_obj_t elements[10];
    size_t count;
    size_t cursor;
};

#define MP_OBJ_NULL ((mp_obj_t)0)
#define MP_OBJ_STOP_ITERATION ((mp_obj_t)(uintptr_t)1u)
#define MP_OBJ_FROM_PTR(pointer) ((mp_obj_t)(pointer))

static fake_obj_t g_objects[512];
static size_t g_object_count;
static fake_obj_t g_exception;
static fake_obj_t g_exception_value;
static fake_obj_t g_file_object;
static mp_obj_t g_listing_items[8];
static size_t g_listing_count;

static bool g_session_enabled = true;
static bool g_vm_enabled = true;
static bool g_ticket_enabled = true;
static pble_session_token_t g_live_session = {7u, 11u};
static uint64_t g_live_vm_epoch = 13u;

enum invalidation_domain {
    INVALIDATE_NONE,
    INVALIDATE_SESSION,
    INVALIDATE_VM,
    INVALIDATE_TRANSFER,
};
static enum invalidation_domain g_invalidation_domain;
static bool g_invalidate_after_open;
static bool g_invalidate_after_read;
static bool g_open_cut_via_ticket;
static bool g_open_cut_armed;
static unsigned g_item_checks_after_open;
static unsigned g_ticket_checks_after_open;

static bool g_scratch_exists;
static bool g_scratch_is_directory;
static uint32_t g_scratch_stat_size;
static uint8_t g_scratch_bytes[32];
static size_t g_scratch_actual_size;
static int g_read_behavior;
static bool g_remove_failure;
static char g_old_destination[32];

static mp_int_t g_statvfs_unit = 4096;
static mp_int_t g_statvfs_available = 16;
static size_t g_statvfs_count = 5u;
static bool g_statvfs_unit_is_int = true;
static bool g_statvfs_available_is_int = true;

static unsigned g_stat_calls;
static unsigned g_visible_stat_calls;
static unsigned g_hidden_stat_calls;
static unsigned g_open_calls;
static unsigned g_close_calls;
static unsigned g_remove_calls;
static unsigned g_rmdir_calls;
static unsigned g_mkdir_calls;
static unsigned g_rename_calls;

static uint8_t g_scratch[PBLE_FS_SCRATCH];
typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
#define taskENTER_CRITICAL(mux) do { (void)(mux); } while (0)
#define taskEXIT_CRITICAL(mux) do { (void)(mux); } while (0)
static portMUX_TYPE g_fs_transfer_mux = portMUX_INITIALIZER_UNLOCKED;
static uint64_t g_fs_transfer_generation = 1u;
static bool g_fs_transfer_exhausted;
static bool g_get_active;
static uint64_t g_get_generation;
static bool g_put_active;
static char g_put_temp[PBLE_FS_PATH_BUF];
static char g_put_dest[PBLE_FS_PATH_BUF];
static uint32_t g_put_total;
static uint32_t g_put_crc_target;
static uint32_t g_put_watermark;
static uint32_t g_put_crc_running;
static uint8_t g_put_latched;
static uint64_t g_put_generation;
static mp_obj_t g_root_pble_fs_put_file;
#define MP_STATE_VM(member) g_root_##member

static bool pble_fs_transfer_valid(const pble_fs_req_t *it);
static bool pble_fs_item_valid(const pble_fs_req_t *it);
static bool pble_fs_ticket_valid(const pble_fs_req_t *it);
static uint8_t fs_stat_path(const pble_fs_req_t *it, const char *path,
                            uint32_t *size, bool *isdir);
static bool fs_put_owned(const pble_fs_req_t *it);
static bool fs_put_active_current(const pble_fs_req_t *it);

static void invalidate_identity(void) {
    switch (g_invalidation_domain) {
        case INVALIDATE_SESSION:
            g_session_enabled = false;
            break;
        case INVALIDATE_VM:
            g_vm_enabled = false;
            break;
        case INVALIDATE_TRANSFER:
            g_fs_transfer_generation++;
            break;
        default:
            break;
    }
}

static void fake_die(const char *message) {
    fprintf(stderr, "fake runtime error: %s\n", message);
    exit(90);
}

static fake_obj_t *fake_object(enum fake_kind kind) {
    if (g_object_count >= sizeof(g_objects) / sizeof(g_objects[0])) {
        fake_die("object pool exhausted");
    }
    fake_obj_t *object = &g_objects[g_object_count++];
    memset(object, 0, sizeof(*object));
    object->kind = kind;
    return object;
}

static mp_obj_t fake_int(mp_int_t value) {
    fake_obj_t *object = fake_object(FAKE_INT);
    object->integer = value;
    return object;
}

static mp_obj_t fake_string(const char *value, size_t length) {
    fake_obj_t *object = fake_object(FAKE_STRING);
    object->string = value;
    object->length = length;
    return object;
}

static mp_obj_t fake_array(mp_obj_t *items, size_t count) {
    if (count > 10u) {
        fake_die("array too large");
    }
    fake_obj_t *object = fake_object(FAKE_ARRAY);
    memcpy(object->elements, items, count * sizeof(items[0]));
    object->count = count;
    return object;
}

static _Noreturn void mp_raise_OSError(int error) {
    if (g_nlr_top == NULL) {
        fake_die("OSError outside nlr");
    }
    g_exception.kind = FAKE_EXCEPTION;
    g_exception_value.kind = FAKE_INT;
    g_exception_value.integer = error;
    nlr_buf_t *target = g_nlr_top;
    target->ret_val = &g_exception;
    g_nlr_top = target->previous;
    longjmp(target->jump, 1);
}

static bool mp_obj_is_exception_instance(mp_obj_t object) {
    return object != MP_OBJ_NULL && object->kind == FAKE_EXCEPTION;
}

static mp_obj_t mp_obj_exception_get_value(mp_obj_t object) {
    (void)object;
    return &g_exception_value;
}

static bool mp_obj_get_int_maybe(mp_obj_t object, mp_int_t *value) {
    if (object == MP_OBJ_NULL || object->kind != FAKE_INT) {
        return false;
    }
    *value = object->integer;
    return true;
}

static bool mp_obj_is_int(mp_obj_t object) {
    return object != MP_OBJ_NULL && object->kind == FAKE_INT;
}

static mp_int_t mp_obj_get_int(mp_obj_t object) {
    mp_int_t value;
    if (!mp_obj_get_int_maybe(object, &value)) {
        fake_die("integer requested from non-integer");
    }
    return value;
}

static mp_obj_t mp_obj_new_str(const char *value, size_t length) {
    return fake_string(value, length);
}

static void mp_map_init(mp_map_t *map, size_t count) {
    (void)map;
    (void)count;
}

static const char *mp_obj_str_get_data(mp_obj_t object, size_t *length) {
    if (object == MP_OBJ_NULL || object->kind != FAKE_STRING) {
        fake_die("string requested from non-string");
    }
    *length = object->length;
    return object->string;
}

static void mp_obj_get_array(mp_obj_t object, size_t *count,
                             mp_obj_t **fields) {
    if (object == MP_OBJ_NULL || object->kind != FAKE_ARRAY) {
        fake_die("array requested from non-array");
    }
    *count = object->count;
    *fields = object->elements;
}

static mp_obj_t mp_getiter(mp_obj_t iterable, mp_obj_iter_buf_t *buffer) {
    (void)buffer;
    return iterable;
}

static mp_obj_t mp_iternext(mp_obj_t iterable) {
    if (iterable == MP_OBJ_NULL || iterable->kind != FAKE_ITERATOR) {
        fake_die("iteration requested from non-iterator");
    }
    if (iterable->cursor >= iterable->count) {
        return MP_OBJ_STOP_ITERATION;
    }
    return iterable->elements[iterable->cursor++];
}

static bool pble_ble_session_live(const pble_session_token_t *session) {
    if (g_invalidate_after_open && !g_open_cut_via_ticket &&
        g_open_cut_armed) {
        g_item_checks_after_open++;
        if (g_item_checks_after_open == 2u) {
            invalidate_identity();
        }
    }
    return g_session_enabled && session != NULL &&
           session->conn == g_live_session.conn &&
           session->incarnation == g_live_session.incarnation;
}

static bool pble_vm_epoch_valid(uint64_t epoch) {
    return g_vm_enabled && epoch == g_live_vm_epoch;
}

static bool pble_rsp_ticket_valid(const pble_rsp_ticket_t *ticket) {
    if (g_invalidate_after_open && g_open_cut_via_ticket &&
        g_open_cut_armed) {
        g_ticket_checks_after_open++;
        if (g_ticket_checks_after_open == 2u) {
            invalidate_identity();
        }
    }
    return g_ticket_enabled && ticket != NULL &&
           ticket->incarnation == 17u &&
           pble_ble_session_live(&ticket->session) &&
           pble_vm_epoch_valid(ticket->vm_epoch);
}

static mp_obj_t fake_stat(mp_int_t mode, uint32_t size) {
    mp_obj_t fields[7] = {
        fake_int(mode), fake_int(0), fake_int(0), fake_int(0),
        fake_int(0), fake_int(0), fake_int((mp_int_t)size),
    };
    return fake_array(fields, 7u);
}

static const char *fake_path(mp_obj_t object) {
    size_t length;
    const char *path = mp_obj_str_get_data(object, &length);
    (void)length;
    return path;
}

static mp_obj_t mp_vfs_stat(mp_obj_t path_object) {
    const char *path = fake_path(path_object);
    g_stat_calls++;
    if (strstr(path, ".pbltmp") != NULL) {
        g_hidden_stat_calls++;
    }
    if (strcmp(path, "/main.py") == 0) {
        g_visible_stat_calls++;
        return fake_stat(MP_S_IFREG, 7u);
    }
    if (strcmp(path, "/docs") == 0) {
        g_visible_stat_calls++;
        return fake_stat(MP_S_IFDIR, 0u);
    }
    if (strcmp(path, "/old.py") == 0) {
        return fake_stat(MP_S_IFREG, (uint32_t)strlen(g_old_destination));
    }
    if (strcmp(path, "/old.py.pbltmp") == 0 && g_scratch_exists) {
        return fake_stat(
            g_scratch_is_directory ? MP_S_IFDIR : MP_S_IFREG,
            g_scratch_stat_size
        );
    }
    mp_raise_OSError(MP_ENOENT);
}

static mp_obj_t mp_vfs_ilistdir(size_t count, mp_obj_t *arguments) {
    (void)count;
    (void)arguments;
    fake_obj_t *iterator = fake_object(FAKE_ITERATOR);
    if (g_listing_count > 10u) {
        fake_die("too many listing entries");
    }
    memcpy(
        iterator->elements,
        g_listing_items,
        g_listing_count * sizeof(g_listing_items[0])
    );
    iterator->count = g_listing_count;
    return iterator;
}

static mp_obj_t mp_vfs_statvfs(mp_obj_t path_object) {
    (void)path_object;
    mp_obj_t fields[5] = {
        fake_int(0),
        g_statvfs_unit_is_int
            ? fake_int(g_statvfs_unit)
            : fake_string("invalid", 7u),
        fake_int(0),
        fake_int(0),
        g_statvfs_available_is_int
            ? fake_int(g_statvfs_available)
            : fake_string("invalid", 7u),
    };
    return fake_array(fields, g_statvfs_count);
}

static mp_uint_t fake_stream_read(mp_obj_t file, void *buffer,
                                  mp_uint_t requested, int *error) {
    (void)error;
    if (file != &g_file_object) {
        fake_die("read from unknown file");
    }
    if (g_read_behavior == 2) {
        g_read_behavior = 3;
        return requested + 1u;
    }
    size_t remaining = g_scratch_actual_size > file->cursor
                           ? g_scratch_actual_size - file->cursor
                           : 0u;
    size_t amount = remaining < requested ? remaining : (size_t)requested;
    memcpy(buffer, g_scratch_bytes + file->cursor, amount);
    file->cursor += amount;
    if (g_invalidate_after_read) {
        g_invalidate_after_read = false;
        invalidate_identity();
    }
    return (mp_uint_t)amount;
}

static mp_uint_t fake_stream_write(mp_obj_t file, const void *buffer,
                                   mp_uint_t requested, int *error) {
    (void)file;
    (void)buffer;
    (void)error;
    return requested;
}

static const mp_stream_p_t g_stream = {
    .read = fake_stream_read,
    .write = fake_stream_write,
};

static mp_obj_t mp_vfs_open(size_t count, mp_obj_t *arguments, mp_map_t *kw) {
    (void)kw;
    const char *path = fake_path(arguments[0]);
    if (count != 2u ||
        (strcmp(path, "/old.py.pbltmp") != 0 &&
         strcmp(path, "/old.py") != 0)) {
        fake_die("unexpected open");
    }
    g_open_calls++;
    memset(&g_file_object, 0, sizeof(g_file_object));
    g_file_object.kind = FAKE_FILE;
    if (g_invalidate_after_open) {
        g_open_cut_armed = true;
        g_item_checks_after_open = 0u;
        g_ticket_checks_after_open = 0u;
    }
    return &g_file_object;
}

static const mp_stream_p_t *mp_get_stream(mp_obj_t file) {
    if (file != &g_file_object || file->kind != FAKE_FILE) {
        fake_die("stream requested from non-file");
    }
    return &g_stream;
}

static void mp_stream_close(mp_obj_t file) {
    if (file != &g_file_object) {
        fake_die("close of unknown file");
    }
    g_close_calls++;
}

static void mp_vfs_remove(mp_obj_t path_object) {
    const char *path = fake_path(path_object);
    g_remove_calls++;
    if (strcmp(path, "/old.py.pbltmp") == 0) {
        if (g_remove_failure) {
            mp_raise_OSError(MP_EIO);
        }
        g_scratch_exists = false;
        return;
    }
    if (strcmp(path, "/old.py") == 0) {
        g_old_destination[0] = '\0';
        return;
    }
}

static void mp_vfs_rmdir(mp_obj_t path_object) {
    const char *path = fake_path(path_object);
    g_rmdir_calls++;
    if (strcmp(path, "/old.py.pbltmp") == 0) {
        if (g_remove_failure) {
            mp_raise_OSError(MP_EIO);
        }
        g_scratch_exists = false;
    }
}

static void mp_vfs_mkdir(mp_obj_t path_object) {
    (void)path_object;
    g_mkdir_calls++;
}

static void mp_vfs_rename(mp_obj_t source_object, mp_obj_t dest_object) {
    const char *source = fake_path(source_object);
    const char *dest = fake_path(dest_object);
    g_rename_calls++;
    if (strcmp(source, "/old.py.pbltmp") == 0 &&
        strcmp(dest, "/old.py") == 0) {
        memcpy(g_old_destination, g_scratch_bytes, g_scratch_actual_size);
        g_old_destination[g_scratch_actual_size] = '\0';
        g_scratch_exists = false;
    }
}

static uint16_t pble_ble_mtu(void) {
    return 247u;
}

static bool pble_rsp_expect_completion(const pble_rsp_ticket_t *ticket) {
    return pble_rsp_ticket_valid(ticket);
}

static bool pble_rsp_publish(const pble_rsp_ticket_t *ticket, uint8_t opcode,
                             uint8_t id, const uint8_t *payload, size_t len) {
    (void)opcode;
    (void)id;
    (void)payload;
    (void)len;
    return pble_rsp_ticket_valid(ticket);
}

static void pble_rsp_cancel_ticket(const pble_rsp_ticket_t *ticket) {
    (void)ticket;
}

static bool pble_rsp_wait(const pble_rsp_ticket_t *ticket) {
    (void)ticket;
    return true;
}

static int fs_emit_paced(const pble_fs_req_t *it, uint8_t opcode,
                         const uint8_t *payload, size_t len) {
    (void)it;
    (void)opcode;
    (void)payload;
    (void)len;
    return PBLE_TX_OK;
}
"""


SCENARIOS = r"""
#define CHECK(condition, message) do {                                      \
    if (!(condition)) {                                                     \
        fprintf(stderr, "%s\n", (message));                               \
        return 1;                                                           \
    }                                                                       \
} while (0)

static void reset_world(void) {
    memset(g_objects, 0, sizeof(g_objects));
    g_object_count = 0u;
    g_nlr_top = NULL;
    g_listing_count = 0u;
    g_session_enabled = true;
    g_vm_enabled = true;
    g_ticket_enabled = true;
    g_invalidation_domain = INVALIDATE_NONE;
    g_invalidate_after_open = false;
    g_invalidate_after_read = false;
    g_open_cut_via_ticket = false;
    g_open_cut_armed = false;
    g_item_checks_after_open = 0u;
    g_ticket_checks_after_open = 0u;
    g_live_session.conn = 7u;
    g_live_session.incarnation = 11u;
    g_live_vm_epoch = 13u;
    g_scratch_exists = false;
    g_scratch_is_directory = false;
    g_scratch_stat_size = 0u;
    memset(g_scratch_bytes, 0, sizeof(g_scratch_bytes));
    g_scratch_actual_size = 0u;
    g_read_behavior = 0;
    g_remove_failure = false;
    strcpy(g_old_destination, "OLD");
    g_statvfs_unit = 4096;
    g_statvfs_available = 16;
    g_statvfs_count = 5u;
    g_statvfs_unit_is_int = true;
    g_statvfs_available_is_int = true;
    g_stat_calls = 0u;
    g_visible_stat_calls = 0u;
    g_hidden_stat_calls = 0u;
    g_open_calls = 0u;
    g_close_calls = 0u;
    g_remove_calls = 0u;
    g_rmdir_calls = 0u;
    g_mkdir_calls = 0u;
    g_rename_calls = 0u;
    memset(g_scratch, 0, sizeof(g_scratch));
    g_fs_transfer_mux = portMUX_INITIALIZER_UNLOCKED;
    g_fs_transfer_generation = 19u;
    g_fs_transfer_exhausted = false;
    g_get_active = false;
    g_get_generation = 0u;
    g_put_active = false;
    memset(g_put_temp, 0, sizeof(g_put_temp));
    memset(g_put_dest, 0, sizeof(g_put_dest));
    g_put_total = 0u;
    g_put_crc_target = 0u;
    g_put_watermark = 0u;
    g_put_crc_running = 0xffffffffu;
    g_put_latched = 0u;
    g_put_generation = 0u;
    g_root_pble_fs_put_file = MP_OBJ_NULL;
}

static pble_fs_req_t current_request(void) {
    pble_fs_req_t request;
    memset(&request, 0, sizeof(request));
    request.id = 3u;
    request.session = g_live_session;
    request.vm_epoch = g_live_vm_epoch;
    request.transfer_generation = g_fs_transfer_generation;
    request.ticket.slot = 1u;
    request.ticket.incarnation = 17u;
    request.ticket.session = g_live_session;
    request.ticket.vm_epoch = g_live_vm_epoch;
    return request;
}

static void set_path_request(pble_fs_req_t *request, const char *path) {
    size_t length = strlen(path);
    request->payload[0] = (uint8_t)(length & 0xffu);
    request->payload[1] = (uint8_t)(length >> 8);
    memcpy(request->payload + 2u, path, length);
    request->len = (uint16_t)(length + 2u);
}

static void set_rename_request(pble_fs_req_t *request,
                               const char *source, const char *dest) {
    size_t source_length = strlen(source);
    size_t dest_length = strlen(dest);
    request->payload[0] = (uint8_t)(source_length & 0xffu);
    request->payload[1] = (uint8_t)(source_length >> 8);
    memcpy(request->payload + 2u, source, source_length);
    size_t dest_header = 2u + source_length;
    request->payload[dest_header] = (uint8_t)(dest_length & 0xffu);
    request->payload[dest_header + 1u] = (uint8_t)(dest_length >> 8);
    memcpy(request->payload + dest_header + 2u, dest, dest_length);
    request->len = (uint16_t)(dest_header + 2u + dest_length);
}

static mp_obj_t listing_entry(const char *name, size_t length, mp_int_t type) {
    mp_obj_t fields[2] = {
        fake_string(name, length),
        fake_int(type),
    };
    return fake_array(fields, 2u);
}

static int scenario_listing(void) {
    reset_world();
    static char oversized_hidden[501];
    memset(oversized_hidden, 'x', sizeof(oversized_hidden));
    memcpy(
        oversized_hidden + sizeof(oversized_hidden) - 8u,
        ".pbltmp",
        8u
    );
    oversized_hidden[sizeof(oversized_hidden) - 1u] = '\0';
    static const char hidden_directory[] = "cache.pbltmp";
    static const char visible_file[] = "main.py";
    static const char visible_directory[] = "docs";

    g_listing_items[0] = listing_entry(
        oversized_hidden, strlen(oversized_hidden), MP_S_IFREG);
    g_listing_items[1] = listing_entry(
        hidden_directory, strlen(hidden_directory), MP_S_IFDIR);
    g_listing_items[2] = listing_entry(
        visible_file, strlen(visible_file), MP_S_IFREG);
    g_listing_items[3] = listing_entry(
        visible_directory, strlen(visible_directory), MP_S_IFDIR);
    g_listing_count = 4u;

    pble_fs_req_t request = current_request();
    set_path_request(&request, "/");
    size_t extra = 0u;
    uint8_t status = fs_do_list(&request, &extra);
    CHECK(status == PBLE_OK, "LIST did not succeed");
    CHECK(g_scratch[1] == 0u,
          "oversized hidden scratch entry consumed the response budget");
    CHECK(g_scratch[2] == 2u && g_scratch[3] == 0u,
          "LIST did not expose exactly the two visible entries");
    CHECK(g_hidden_stat_calls == 0u,
          "hidden scratch entry reached the per-entry stat seam");
    CHECK(g_visible_stat_calls == 1u,
          "the one visible file did not receive exactly one stat");
    CHECK(extra > 3u, "LIST emitted no visible entry payload");
    return 0;
}

static int expect_space(uint32_t remaining, uint8_t expected,
                        const char *message) {
    pble_fs_req_t request = current_request();
    uint8_t actual = fs_put_space_status(&request, remaining);
    if (actual != expected) {
        fprintf(stderr, "%s: expected %u, got %u\n",
                message, (unsigned)expected, (unsigned)actual);
        return 1;
    }
    return 0;
}

static int scenario_capacity(void) {
    reset_world();
    CHECK(expect_space(0u, PBLE_OK, "exact reserve") == 0,
          "exact reserve boundary failed");
    g_statvfs_available = 15;
    CHECK(expect_space(0u, PBLE_ENOSPC, "one block below reserve") == 0,
          "below-reserve boundary failed");
    g_statvfs_available = 17;
    CHECK(expect_space(1u, PBLE_OK, "one-byte rounded admission") == 0,
          "rounded exact boundary failed");
    g_statvfs_available = 16;
    CHECK(expect_space(1u, PBLE_ENOSPC, "rounded admission shortfall") == 0,
          "rounded shortfall failed");

    g_statvfs_count = 4u;
    CHECK(expect_space(0u, PBLE_EIO, "short statvfs tuple") == 0,
          "short statvfs tuple was trusted");
    g_statvfs_count = 5u;
    g_statvfs_unit_is_int = false;
    CHECK(expect_space(0u, PBLE_EIO, "non-integer unit") == 0,
          "non-integer unit was trusted");
    g_statvfs_unit_is_int = true;
    g_statvfs_available_is_int = false;
    CHECK(expect_space(0u, PBLE_EIO, "non-integer availability") == 0,
          "non-integer availability was trusted");
    g_statvfs_available_is_int = true;
    g_statvfs_unit = 0;
    CHECK(expect_space(0u, PBLE_EIO, "zero unit") == 0,
          "zero allocation unit was trusted");
    g_statvfs_unit = 4096;
    g_statvfs_available = -1;
    CHECK(expect_space(0u, PBLE_EIO, "negative availability") == 0,
          "negative availability was trusted");
    g_statvfs_unit = LLONG_MAX;
    g_statvfs_available = 3;
    CHECK(expect_space(0u, PBLE_EIO, "geometry multiplication overflow") == 0,
          "overflowing geometry was trusted");
    return 0;
}

static int run_bad_resume(int behavior, bool cleanup_failure,
                          uint8_t expected_status) {
    reset_world();
    g_scratch_exists = true;
    g_scratch_stat_size = 4u;
    memcpy(g_scratch_bytes, "AB", 2u);
    g_scratch_actual_size = 2u;
    g_read_behavior = behavior;
    g_remove_failure = cleanup_failure;
    pble_fs_req_t request = current_request();
    uint32_t resume = 99u;
    uint32_t running = 0u;
    uint8_t status = pble_fs_resume_prefix(
        &request, "/old.py", 4u, &resume, &running);
    CHECK(status == expected_status, "malformed resume returned wrong status");
    CHECK(strcmp(g_old_destination, "OLD") == 0,
          "malformed scratch changed the old destination");
    CHECK(g_rename_calls == 0u,
          "malformed scratch reached the publication rename");
    CHECK(g_open_calls == 1u && g_close_calls == 1u,
          "malformed scratch scan did not close its exact file");
    return 0;
}

static int scenario_malformed_resume(void) {
    CHECK(run_bad_resume(1, false, PBLE_OK) == 0,
          "short-read cleanup scenario failed");
    CHECK(!g_scratch_exists && g_remove_calls == 1u,
          "short-read scratch was not removed exactly once");

    CHECK(run_bad_resume(2, false, PBLE_OK) == 0,
          "overreported-read cleanup scenario failed");
    CHECK(!g_scratch_exists && g_remove_calls == 1u,
          "overreported-read scratch was not removed exactly once");

    CHECK(run_bad_resume(1, true, PBLE_EIO) == 0,
          "cleanup-failure scenario failed");
    CHECK(g_scratch_exists && g_remove_calls == 1u,
          "failed cleanup did not preserve the scratch evidence");
    CHECK(strcmp(g_old_destination, "OLD") == 0,
          "cleanup failure changed the old destination");
    return 0;
}

static void arm_active_put(void) {
    g_put_active = true;
    g_put_generation = g_fs_transfer_generation;
    strcpy(g_put_temp, "/old.py.pbltmp");
    strcpy(g_put_dest, "/old.py");
}

static int scenario_mutation_gate(void) {
    reset_world();
    arm_active_put();
    pble_fs_req_t request = current_request();
    size_t extra = 123u;

    set_path_request(&request, "../escape");
    CHECK(fs_do_delete(&request, &extra) == PBLE_EACCES,
          "DELETE applied busy precedence before jail rejection");
    CHECK(g_stat_calls == 0u && g_remove_calls == 0u,
          "rejected DELETE reached VFS");
    set_path_request(&request, "/user.py");
    CHECK(fs_do_delete(&request, &extra) == PBLE_EBUSY,
          "valid DELETE was not blocked by active PUT");
    CHECK(g_stat_calls == 0u && g_remove_calls == 0u,
          "busy DELETE reached VFS");

    set_path_request(&request, "../escape");
    CHECK(fs_do_mkdir(&request, &extra) == PBLE_EACCES,
          "MKDIR applied busy precedence before jail rejection");
    CHECK(g_mkdir_calls == 0u, "rejected MKDIR reached VFS");
    set_path_request(&request, "/new-dir");
    CHECK(fs_do_mkdir(&request, &extra) == PBLE_EBUSY,
          "valid MKDIR was not blocked by active PUT");
    CHECK(g_mkdir_calls == 0u, "busy MKDIR reached VFS");

    set_rename_request(&request, "/source.py", "../escape");
    CHECK(fs_do_rename(&request, &extra) == PBLE_EACCES,
          "RENAME applied busy precedence before destination jail rejection");
    CHECK(g_stat_calls == 0u && g_rename_calls == 0u,
          "rejected RENAME reached VFS");
    set_rename_request(&request, "/source.py", "/dest.py");
    CHECK(fs_do_rename(&request, &extra) == PBLE_EBUSY,
          "valid RENAME was not blocked by active PUT");
    CHECK(g_stat_calls == 0u && g_rename_calls == 0u,
          "busy RENAME reached VFS");

    g_put_active = false;
    request.get_active_at_enqueue = true;
    set_path_request(&request, "/missing.py");
    CHECK(fs_do_delete(&request, &extra) == PBLE_EBUSY,
          "valid DELETE admitted during GET was not blocked");
    CHECK(g_stat_calls == 0u && g_remove_calls == 0u,
          "GET-busy DELETE reached VFS");
    set_path_request(&request, "/new-dir");
    CHECK(fs_do_mkdir(&request, &extra) == PBLE_EBUSY,
          "valid MKDIR admitted during GET was not blocked");
    CHECK(g_mkdir_calls == 0u, "GET-busy MKDIR reached VFS");
    set_rename_request(&request, "/source.py", "/dest.py");
    CHECK(fs_do_rename(&request, &extra) == PBLE_EBUSY,
          "valid RENAME admitted during GET was not blocked");
    CHECK(g_stat_calls == 0u && g_rename_calls == 0u,
          "GET-busy RENAME reached VFS");

    set_path_request(&request, "../escape");
    CHECK(fs_do_delete(&request, &extra) == PBLE_EACCES,
          "GET-busy DELETE applied EBUSY before jail rejection");
    set_rename_request(&request, "/source.py", "../escape");
    CHECK(fs_do_rename(&request, &extra) == PBLE_EACCES,
          "GET-busy RENAME applied EBUSY before destination jail rejection");
    return 0;
}

static bool try_publish(pble_fs_req_t *request) {
    return fs_put_publish(
        request,
        &g_file_object,
        "/old.py.pbltmp",
        "/old.py",
        0u,
        0u,
        0u,
        0xffffffffu
    );
}

static uint8_t try_end(pble_fs_req_t *request) {
    request->len = 4u;
    memset(request->payload, 0, 4u);
    size_t extra = 99u;
    return fs_do_put_end(request, &extra);
}

static int scenario_identity(void) {
    reset_world();
    pble_fs_req_t request = current_request();
    pble_fs_req_t stale = request;
    stale.session.incarnation--;
    CHECK(!try_publish(&stale) && !g_put_active,
          "stale connection published PUT ownership");

    stale = request;
    stale.vm_epoch--;
    CHECK(!try_publish(&stale) && !g_put_active,
          "stale VM epoch published PUT ownership");

    stale = request;
    stale.transfer_generation--;
    CHECK(!try_publish(&stale) && !g_put_active,
          "stale transfer generation published PUT ownership");

    CHECK(try_publish(&request) && g_put_active,
          "current identity could not publish PUT ownership");
    uint64_t published_generation = g_put_generation;
    pble_fs_on_disconnect();
    CHECK(g_fs_transfer_generation == published_generation + 1u,
          "disconnect did not invalidate the filesystem generation");
    CHECK(try_end(&request) == PBLE_NO_RSP,
          "disconnected owner produced a terminal response");
    CHECK(g_rename_calls == 0u && strcmp(g_old_destination, "OLD") == 0,
          "disconnected owner committed its stale scratch");

    reset_world();
    arm_active_put();
    request = current_request();
    request.session.incarnation--;
    CHECK(try_end(&request) == PBLE_NO_RSP,
          "stale connection committed an active transfer");
    CHECK(g_rename_calls == 0u && strcmp(g_old_destination, "OLD") == 0,
          "stale connection reached publication rename");

    reset_world();
    arm_active_put();
    request = current_request();
    request.vm_epoch--;
    CHECK(try_end(&request) == PBLE_NO_RSP,
          "stale VM epoch committed an active transfer");
    CHECK(g_rename_calls == 0u && strcmp(g_old_destination, "OLD") == 0,
          "stale VM epoch reached publication rename");

    reset_world();
    arm_active_put();
    request = current_request();
    request.transfer_generation--;
    CHECK(try_end(&request) == PBLE_NO_RSP,
          "stale generation committed an active transfer");
    CHECK(g_rename_calls == 0u && strcmp(g_old_destination, "OLD") == 0,
          "stale generation reached publication rename");
    return 0;
}

static void prepare_file_bytes(const char *bytes) {
    size_t length = strlen(bytes);
    if (length > sizeof(g_scratch_bytes)) {
        fake_die("test file exceeds fake storage");
    }
    memcpy(g_scratch_bytes, bytes, length);
    g_scratch_actual_size = length;
}

static void arm_post_open_cut(enum invalidation_domain domain,
                              bool via_ticket) {
    g_invalidation_domain = domain;
    g_invalidate_after_open = true;
    g_open_cut_via_ticket = via_ticket;
}

static void arm_post_read_cut(enum invalidation_domain domain) {
    g_invalidation_domain = domain;
    g_invalidate_after_read = true;
}

static int check_local_close(uint8_t status, const char *context) {
    if (status != PBLE_NO_RSP) {
        fprintf(stderr, "%s returned %u instead of silent cancellation\n",
                context, (unsigned)status);
        return 1;
    }
    if (g_open_calls != 1u || g_close_calls != 1u) {
        fprintf(stderr,
                "%s opened %u local object(s) but closed %u (expected 1/1)\n",
                context, g_open_calls, g_close_calls);
        return 1;
    }
    return 0;
}

static int scenario_crc_file_close(bool after_open) {
    reset_world();
    prepare_file_bytes("OLD");
    if (after_open) {
        arm_post_open_cut(INVALIDATE_SESSION, true);
    } else {
        arm_post_read_cut(INVALIDATE_VM);
    }
    pble_fs_req_t request = current_request();
    uint32_t crc = 0u;
    uint8_t status = fs_crc_file(&request, "/old.py", 3u, &crc);
    return check_local_close(
        status, after_open ? "fs_crc_file post-open"
                           : "fs_crc_file post-read");
}

static int scenario_crc_prefix_close(bool after_open) {
    reset_world();
    prepare_file_bytes("OLD");
    if (after_open) {
        arm_post_open_cut(INVALIDATE_TRANSFER, true);
    } else {
        arm_post_read_cut(INVALIDATE_SESSION);
    }
    pble_fs_req_t request = current_request();
    uint32_t running = 0u;
    uint8_t status = fs_crc_prefix(
        &request, "/old.py.pbltmp", 3u, &running);
    return check_local_close(
        status, after_open ? "fs_crc_prefix post-open"
                           : "fs_crc_prefix post-read");
}

static void set_get_request(pble_fs_req_t *request, const char *path) {
    size_t length = strlen(path);
    memset(request->payload, 0, 4u);
    request->payload[4] = (uint8_t)(length & 0xffu);
    request->payload[5] = (uint8_t)(length >> 8);
    memcpy(request->payload + 6u, path, length);
    request->len = (uint16_t)(6u + length);
}

static int scenario_get_close(bool after_open) {
    reset_world();
    prepare_file_bytes("OLD");
    if (after_open) {
        arm_post_open_cut(INVALIDATE_VM, false);
    } else {
        arm_post_read_cut(INVALIDATE_TRANSFER);
    }
    pble_fs_req_t request = current_request();
    set_get_request(&request, "/old.py");
    uint8_t status = fs_do_get(&request);
    int result = check_local_close(
        status, after_open ? "fs_do_get post-open"
                           : "fs_do_get post-read");
    if (result != 0) {
        return result;
    }
    CHECK(!g_get_active && g_get_generation == 0u,
          "cancelled GET retained active-download ownership");
    return 0;
}

static void set_put_begin_request(pble_fs_req_t *request, const char *path) {
    size_t length = strlen(path);
    memset(request->payload, 0, 8u);  // total=0, whole-file CRC=0
    request->payload[8] = (uint8_t)(length & 0xffu);
    request->payload[9] = (uint8_t)(length >> 8);
    memcpy(request->payload + 10u, path, length);
    request->len = (uint16_t)(10u + length);
}

static int scenario_put_begin_close(void) {
    reset_world();
    arm_post_open_cut(INVALIDATE_SESSION, true);
    pble_fs_req_t request = current_request();
    set_put_begin_request(&request, "/old.py");
    size_t extra = 99u;
    uint8_t status = fs_do_put_begin(&request, &extra);
    CHECK(!g_put_active && g_root_pble_fs_put_file == MP_OBJ_NULL,
          "cancelled PUT_BEGIN published an active/rooted file");
    CHECK(strcmp(g_old_destination, "OLD") == 0,
          "cancelled PUT_BEGIN changed the old destination");
    return check_local_close(status, "fs_do_put_begin post-open");
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "expected one scenario\n");
        return 2;
    }
    if (strcmp(argv[1], "listing") == 0) {
        return scenario_listing();
    }
    if (strcmp(argv[1], "capacity") == 0) {
        return scenario_capacity();
    }
    if (strcmp(argv[1], "malformed-resume") == 0) {
        return scenario_malformed_resume();
    }
    if (strcmp(argv[1], "mutation-gate") == 0) {
        return scenario_mutation_gate();
    }
    if (strcmp(argv[1], "identity") == 0) {
        return scenario_identity();
    }
    if (strcmp(argv[1], "crc-file-open-close") == 0) {
        return scenario_crc_file_close(true);
    }
    if (strcmp(argv[1], "crc-file-read-close") == 0) {
        return scenario_crc_file_close(false);
    }
    if (strcmp(argv[1], "crc-prefix-open-close") == 0) {
        return scenario_crc_prefix_close(true);
    }
    if (strcmp(argv[1], "crc-prefix-read-close") == 0) {
        return scenario_crc_prefix_close(false);
    }
    if (strcmp(argv[1], "get-open-close") == 0) {
        return scenario_get_close(true);
    }
    if (strcmp(argv[1], "get-read-close") == 0) {
        return scenario_get_close(false);
    }
    if (strcmp(argv[1], "put-begin-open-close") == 0) {
        return scenario_put_begin_close();
    }
    fprintf(stderr, "unknown scenario: %s\n", argv[1]);
    return 2;
}
"""


if __name__ == "__main__":
    unittest.main()
