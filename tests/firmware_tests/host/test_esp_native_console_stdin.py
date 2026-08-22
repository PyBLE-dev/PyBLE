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
import re
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
