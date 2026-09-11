#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""FR-CON-3 structural gate for the real ESP native dupterm stream.

The TFT transport fake deliberately cannot prove this boundary: a fake may
manufacture console and terminal events after seeing CONSOLE_INPUT.  These
tests inspect the C stream that MicroPython's input()/sys.stdin actually reads.
"""

from __future__ import annotations

from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[3]
CONSOLE = (
    ROOT / "firmware" / "user_c_modules" / "pyble" / "pble_console.c"
).read_text(encoding="utf-8")
DUPTERM = (
    ROOT / "firmware" / "upstream" / "micropython" / "extmod" / "os_dupterm.c"
).read_text(encoding="utf-8")


def matching_brace(source: str, opening: int) -> int:
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
                return index
        index += 1
    raise AssertionError("unterminated C block")


def c_function(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^[^\n;{{}}]*\b{re.escape(name)}\s*\([^;{{}}]*\)\s*\{{",
        source,
    )
    if match is None:
        raise AssertionError("missing function %s" % name)
    opening = source.find("{", match.start())
    return source[match.start() : matching_brace(source, opening) + 1]


def code_only(source: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)


class EspNativeConsoleStdinTests(unittest.TestCase):
    def test_dupterm_reads_one_real_native_stream_byte(self):
        upstream = code_only(c_function(DUPTERM, "mp_os_dupterm_rx_chr"))
        self.assertRegex(upstream, r"stream_p->read\([^;]+buf\s*,\s*1\s*,")

        read = code_only(c_function(CONSOLE, "tee_read"))
        self.assertIn("on_worker()", read)
        self.assertIn("pble_console_stdin_getchar()", read)
        self.assertRegex(read, r"\(\(uint8_t\s*\*\)buf\)\[0\]\s*=")
        self.assertRegex(read, r"return\s+1\s*;")

    def test_empty_or_main_repl_read_is_eagain_not_eof(self):
        read = code_only(c_function(CONSOLE, "tee_read"))
        self.assertRegex(read, r"!on_worker\(\)")
        self.assertIn("MP_EAGAIN", read)
        self.assertIn("MP_STREAM_ERROR", read)
        self.assertNotRegex(read, r"return\s+0\s*;")

    def test_poll_readiness_uses_the_same_worker_owned_ring(self):
        ready = code_only(c_function(CONSOLE, "stdin_ring_readable"))
        self.assertIn("g_ring_count", ready)
        self.assertIn("taskENTER_CRITICAL(&g_ring_mux)", ready)
        self.assertIn("taskEXIT_CRITICAL(&g_ring_mux)", ready)

        ioctl = code_only(c_function(CONSOLE, "tee_ioctl"))
        self.assertIn("on_worker()", ioctl)
        self.assertIn("stdin_ring_readable()", ioctl)
        self.assertIn("MP_STREAM_POLL_RD", ioctl)
        self.assertIn("MP_STREAM_POLL_WR", ioctl)


class EspNativeConsoleStdinBehaviorTests(unittest.TestCase):
    """Compile the production ring reducer and exercise every v0.6.1 cut."""

    def test_compiled_ring_isolates_idle_runs_disconnect_and_vm_reset(self):
        compiler = shutil.which(os.environ.get("CC", "cc"))
        self.assertIsNotNone(compiler, "a host C compiler is required")
        functions = "\n".join(
            c_function(CONSOLE, name)
            for name in (
                "on_worker",
                "stdin_ring_clear_locked",
                "pble_console_stdin_begin",
                "pble_console_stdin_end",
                "pble_console_stdin_clear",
                "pble_console_input",
                "pble_console_stdin_getchar",
                "stdin_ring_readable",
                "pble_console_vm_detach",
                "pble_console_vm_reset",
            )
        )
        harness = textwrap.dedent(
            r'''
            #include <stdbool.h>
            #include <stddef.h>
            #include <stdint.h>
            #include <stdio.h>
            #include <string.h>

            #define PBLE_STDIN_RING 256
            #define PBLE_CONSOLE_CHUNK 200
            #define PBLE_NO_RSP 0xfe
            #define taskENTER_CRITICAL(mux) ((void)(mux))
            #define taskEXIT_CRITICAL(mux) ((void)(mux))

            typedef int portMUX_TYPE;
            typedef struct {
                const uint8_t *payload;
                uint16_t len;
            } pble_frame_t;
            typedef struct { uint16_t conn; } pble_session_token_t;

            static void *volatile g_worker;
            static void *current_thread;
            static portMUX_TYPE g_ring_mux;
            static uint8_t g_ring[PBLE_STDIN_RING];
            static uint16_t g_ring_head;
            static uint16_t g_ring_tail;
            static uint16_t g_ring_count;
            static bool g_stdin_active;
            static int64_t g_console_next_notify_us;
            static uint8_t g_stage[1 + PBLE_CONSOLE_CHUNK];

            static void *mp_thread_get_state(void) { return current_thread; }
            static void console_reset_notify_interval(void) {
                g_console_next_notify_us = 0;
            }
            '''
        )
        main = textwrap.dedent(
            r'''
            #define CHECK(condition, code) do { if (!(condition)) return (code); } while (0)

            static uint8_t feed(const uint8_t *data, uint16_t len) {
                pble_frame_t frame = {data, len};
                size_t response_len = 99;
                uint8_t status = pble_console_input(
                    &frame, NULL, &response_len, NULL);
                CHECK(response_len == 0, 90);
                return status;
            }

            int main(void) {
                static uint8_t bytes[300];
                for (size_t i = 0; i < sizeof(bytes); ++i) {
                    bytes[i] = (uint8_t)i;
                }
                g_worker = (void *)1;
                current_thread = (void *)1;

                CHECK(feed(bytes, 4) == PBLE_NO_RSP, 20);
                CHECK(g_ring_count == 0 && pble_console_stdin_getchar() == -1, 21);

                pble_console_stdin_begin();
                CHECK(g_stdin_active && !stdin_ring_readable(), 22);
                CHECK(feed(bytes, sizeof(bytes)) == PBLE_NO_RSP, 23);
                CHECK(g_ring_count == PBLE_STDIN_RING && stdin_ring_readable(), 24);
                for (size_t i = 0; i < PBLE_STDIN_RING; ++i) {
                    CHECK(pble_console_stdin_getchar() == (int)(uint8_t)i, 25);
                }
                CHECK(pble_console_stdin_getchar() == -1, 26);

                CHECK(feed(bytes, 3) == PBLE_NO_RSP, 27);
                current_thread = (void *)2;
                CHECK(pble_console_stdin_getchar() == -1 && g_ring_count == 3, 28);
                current_thread = (void *)1;
                CHECK(pble_console_stdin_getchar() == 0 && g_ring_count == 2, 29);

                pble_console_stdin_clear();
                CHECK(g_stdin_active && g_ring_count == 0, 30);
                CHECK(feed(bytes + 7, 1) == PBLE_NO_RSP, 31);
                CHECK(pble_console_stdin_getchar() == 7, 32);

                CHECK(feed(bytes, 4) == PBLE_NO_RSP, 33);
                pble_console_stdin_end();
                CHECK(!g_stdin_active && g_ring_count == 0, 34);
                CHECK(feed(bytes, 4) == PBLE_NO_RSP && g_ring_count == 0, 35);
                pble_console_stdin_begin();
                CHECK(pble_console_stdin_getchar() == -1, 36);

                CHECK(feed(bytes, 4) == PBLE_NO_RSP, 37);
                g_console_next_notify_us = 123;
                memset(g_stage, 0xa5, sizeof(g_stage));
                pble_console_vm_reset();
                CHECK(!g_stdin_active && g_ring_count == 0 && g_worker == NULL, 38);
                CHECK(g_console_next_notify_us == 0, 39);
                for (size_t i = 0; i < sizeof(g_ring); ++i) CHECK(g_ring[i] == 0, 40);
                for (size_t i = 0; i < sizeof(g_stage); ++i) CHECK(g_stage[i] == 0, 41);
                return 0;
            }
            '''
        )
        with tempfile.TemporaryDirectory(prefix="pyble-v061-stdin-") as temp:
            source = Path(temp) / "stdin_probe.c"
            binary = Path(temp) / "stdin_probe"
            source.write_text(harness + functions + main, encoding="utf-8")
            built = subprocess.run(
                [
                    compiler,
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-Wno-unused-function",
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
                built.returncode,
                0,
                "native stdin probe did not compile:\n{}{}".format(
                    built.stdout, built.stderr
                ),
            )
            executed = subprocess.run(
                [str(binary)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(
                executed.returncode,
                0,
                "native stdin lifecycle probe exited {}:\n{}{}".format(
                    executed.returncode, executed.stdout, executed.stderr
                ),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
