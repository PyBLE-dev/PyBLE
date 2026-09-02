#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""RED compiled contract for strict UTF-8 at the native FS jail."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / "firmware" / "user_c_modules" / "pyble"
FS_PATH = NATIVE / "pble_fs.c"


def _function_span(source: str, name: str) -> tuple[int, int]:
    import re

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
                return match.start(), index + 1
        index += 1
    raise AssertionError("unbalanced production function `{}`".format(name))


def _function(source: str, name: str) -> str:
    start, end = _function_span(source, name)
    return source[start:end]


class NativeUtf8PathTest(unittest.TestCase):
    def test_malformed_utf8_is_ebadreq_before_any_vfs_effect(self):
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler, "a host C compiler is required")
        fs = FS_PATH.read_text(encoding="utf-8", errors="strict")

        # Keep the production jail helper cluster contiguous so a strict UTF-8
        # helper added beside the existing reserved-name/suffix helpers is also
        # compiled by this regression without creating a host-only twin.
        helper_start, _ = _function_span(fs, "fs_reserved_prefix")
        _, resolver_end = _function_span(fs, "pble_fs_resolve")
        jail_cluster = fs[helper_start:resolver_end]
        native_functions = "\n\n".join(
            (
                jail_cluster,
                _function(fs, "rd16"),
                _function(fs, "fs_do_mkdir"),
            )
        )

        with tempfile.TemporaryDirectory(
            prefix="pyble-v061-native-utf8-path-"
        ) as temporary:
            temp = Path(temporary)
            source = temp / "native_utf8_path.c"
            binary = temp / "native_utf8_path"
            source.write_text(
                HARNESS_PREAMBLE + native_functions + HARNESS_MAIN,
                encoding="utf-8",
            )
            compiled = subprocess.run(
                [
                    compiler,
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-D_POSIX_C_SOURCE=200809L",
                    "-I",
                    str(NATIVE),
                    str(source),
                    "-o",
                    str(binary),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(
                compiled.returncode,
                0,
                "native UTF-8 path harness did not compile:\n"
                + compiled.stderr,
            )

            completed = subprocess.run(
                [str(binary)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                "native path jail accepted malformed UTF-8:\n"
                + completed.stderr,
            )


HARNESS_PREAMBLE = r"""
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "pble_proto.h"

#define PBLE_FS_PATH_MAX 128u
#define PBLE_FS_PATH_BUF 160u
#define PBLE_FS_ITEM_PAYLOAD 248u
#define PBLE_FS_TMP_SUFFIX ".pbltmp"

typedef void *mp_obj_t;
typedef struct { void *ret_val; } nlr_buf_t;
typedef struct {
    uint16_t len;
    uint8_t payload[PBLE_FS_ITEM_PAYLOAD];
} pble_fs_req_t;

#define MP_OBJ_FROM_PTR(pointer) ((mp_obj_t)(pointer))

static bool g_put_active;
static unsigned vfs_effects;

static int nlr_push(nlr_buf_t *nlr) {
    nlr->ret_val = NULL;
    return 0;
}

static void nlr_pop(void) {
}

static bool pble_fs_ticket_valid(const pble_fs_req_t *request) {
    return request != NULL;
}

static bool fs_put_active_current(const pble_fs_req_t *request) {
    (void)request;
    return g_put_active;
}

static mp_obj_t fs_str(const char *path) {
    return (mp_obj_t)path;
}

static void mp_vfs_mkdir(mp_obj_t path) {
    (void)path;
    vfs_effects++;
}

static uint8_t fs_exc_to_status(mp_obj_t exception) {
    (void)exception;
    return PBLE_EIO;
}

static uint8_t fs_stat_path(const pble_fs_req_t *request, const char *path,
                            uint32_t *size, bool *is_directory) {
    (void)request;
    (void)path;
    *size = 0u;
    *is_directory = false;
    return PBLE_ENOENT;
}
"""


HARNESS_MAIN = r"""

typedef struct {
    const char *name;
    const uint8_t *path;
    size_t length;
} malformed_case_t;

static uint8_t mkdir_path(const uint8_t *path, size_t length) {
    pble_fs_req_t request = {0};
    size_t extra = 99u;
    request.len = (uint16_t)(length + 2u);
    request.payload[0] = (uint8_t)(length & 0xffu);
    request.payload[1] = (uint8_t)(length >> 8);
    memcpy(request.payload + 2, path, length);
    return fs_do_mkdir(&request, &extra);
}

int main(void) {
    static const uint8_t overlong[] = {'/', 'a', 0xc0u, 0xafu};
    static const uint8_t continuation[] = {'/', 'a', 0x80u};
    static const uint8_t surrogate[] = {'/', 'a', 0xedu, 0xa0u, 0x80u};
    static const uint8_t above_unicode[] = {
        '/', 'a', 0xf4u, 0x90u, 0x80u, 0x80u,
    };
    static const malformed_case_t cases[] = {
        {"overlong encoding", overlong, sizeof(overlong)},
        {"lone continuation", continuation, sizeof(continuation)},
        {"surrogate U+D800", surrogate, sizeof(surrogate)},
        {"> U+10FFFF", above_unicode, sizeof(above_unicode)},
    };
    unsigned failures = 0u;

    for (size_t i = 0u; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        char resolved[PBLE_FS_PATH_BUF];
        vfs_effects = 0u;
        uint8_t direct = pble_fs_resolve(
            (const char *)cases[i].path, cases[i].length,
            resolved, sizeof(resolved));
        if (direct != PBLE_EBADREQ) {
            fprintf(stderr, "%s resolver status: got %u, expected %u\n",
                    cases[i].name, direct, PBLE_EBADREQ);
            failures++;
        }

        uint8_t command = mkdir_path(cases[i].path, cases[i].length);
        if (command != PBLE_EBADREQ) {
            fprintf(stderr, "%s MKDIR status: got %u, expected %u\n",
                    cases[i].name, command, PBLE_EBADREQ);
            failures++;
        }
        if (vfs_effects != 0u) {
            fprintf(stderr, "%s leaked %u VFS effect(s)\n",
                    cases[i].name, vfs_effects);
            failures++;
        }
    }
    return failures == 0u ? EXIT_SUCCESS : EXIT_FAILURE;
}
"""


if __name__ == "__main__":
    unittest.main()
