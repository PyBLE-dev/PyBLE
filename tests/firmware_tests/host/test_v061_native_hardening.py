#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""[red] native ESP v0.6.1 execution and persistence hardening.

The runner test compiles the production ``runner_exec`` body against a small
host model of MicroPython's globals API.  It therefore proves fresh dictionaries
and restoration behavior rather than accepting a comment or helper name alone.
The NVS tests are structural because ESP-IDF NVS is not faked as storage truth;
they pin the checked commit cuts and the single authoritative Identify record.
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
NATIVE = ROOT / "firmware" / "user_c_modules" / "pyble"
RUNNER = (NATIVE / "pble_runner.c").read_text(encoding="utf-8")
DEVICE_CONFIG = (NATIVE / "pble_device_config.c").read_text(encoding="utf-8")
BOOT = (NATIVE / "pble_boot.c").read_text(encoding="utf-8")
BLE = (NATIVE / "pble_ble.c").read_text(encoding="utf-8")


def matching_brace(source, opening):
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


def c_function(source, name):
    match = re.search(
        rf"(?m)^[^\n;{{}}]*\b{re.escape(name)}\s*\([^;{{}}]*\)\s*\{{",
        source,
    )
    if match is None:
        raise AssertionError("missing function {}".format(name))
    opening = source.find("{", match.start())
    return source[match.start():matching_brace(source, opening) + 1]


def code_only(source):
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)


def assert_checked_commit(testcase, body, criterion):
    body = code_only(body)
    testcase.assertIn("nvs_commit(", body, criterion + ": persistence must commit")
    testcase.assertNotRegex(
        body,
        r"\(void\)\s*nvs_commit\s*\(",
        criterion + ": nvs_commit result must never be discarded",
    )
    checked = re.search(
        r"(?:if\s*\([^)]*nvs_commit\s*\([^)]*\)[^)]*(?:==|!=)[^)]*ESP_OK|"
        r"(?:esp_err_t|int)\s+([A-Za-z_]\w*)\s*=\s*nvs_commit\s*\([^)]*\))",
        body,
    )
    testcase.assertIsNotNone(checked, criterion + ": nvs_commit must be checked")
    if checked.group(1):
        tail = body[checked.end():]
        testcase.assertRegex(
            tail,
            r"\b{}\b\s*(?:==|!=)\s*ESP_OK".format(re.escape(checked.group(1))),
            criterion + ": captured commit result must control success",
        )


class NativeFreshGlobalsTests(unittest.TestCase):
    def test_runner_explicitly_swaps_both_globals_and_locals(self):
        body = code_only(c_function(RUNNER, "runner_exec"))
        for call in (
            "mp_globals_get(",
            "mp_locals_get(",
            "mp_obj_new_dict(",
            "mp_globals_set(",
            "mp_locals_set(",
        ):
            self.assertIn(call, body, "fresh native RUN is missing {}".format(call))
        self.assertIn("MP_QSTR___name__", body)
        self.assertIn("MP_QSTR___main__", body)
        self.assertGreaterEqual(
            body.count("mp_globals_set("), 2,
            "native RUN must install fresh globals and restore the predecessor",
        )
        self.assertGreaterEqual(
            body.count("mp_locals_set("), 2,
            "native RUN must install fresh locals and restore the predecessor",
        )

    def test_compiled_runner_exec_does_not_leak_names_and_restores_context(self):
        compiler = shutil.which(os.environ.get("CC", "cc"))
        self.assertIsNotNone(compiler, "a host C compiler is required for runner_exec")
        runner_exec = c_function(RUNNER, "runner_exec")
        harness = textwrap.dedent(
            r'''
            #include <stdbool.h>
            #include <stddef.h>
            #include <stdint.h>
            #include <stdlib.h>
            #include <setjmp.h>

            typedef int qstr;
            typedef uintptr_t mp_obj_t;
            typedef struct { int marker; int name_is_main; } mp_obj_dict_t;
            typedef struct { int unused; } mp_lexer_t;
            typedef struct { int unused; } mp_parse_tree_t;
            typedef struct { jmp_buf jump; void *ret_val; } nlr_buf_t;
            typedef int mp_print_t;

            #define PBLE_RUN_MODE_FILE 0
            #define MP_PARSE_FILE_INPUT 0
            #define MP_HANDLE_PENDING_CALLBACKS_AND_EXCEPTIONS 0
            #define MP_QSTR__lt_stdin_gt_ 10
            #define MP_QSTR___name__ 11
            #define MP_QSTR___main__ 12
            #define MP_OBJ_NULL ((mp_obj_t)0)
            #define MP_OBJ_FROM_PTR(p) ((mp_obj_t)(uintptr_t)(p))
            #define MP_OBJ_TO_PTR(o) ((void *)(uintptr_t)(o))
            #define MP_OBJ_NEW_QSTR(q) ((mp_obj_t)(q))

            static mp_obj_dict_t main_dict;
            static mp_obj_dict_t pool[8];
            static size_t pool_used;
            static mp_obj_dict_t *current_globals = &main_dict;
            static mp_obj_dict_t *current_locals = &main_dict;
            static int phase;
            static int leaked;
            static mp_lexer_t lexer;
            static const mp_print_t pble_console_stderr_print = 0;
            static nlr_buf_t *active_nlr;

            #define nlr_push(nlr) (active_nlr = (nlr), setjmp((nlr)->jump))
            #define nlr_pop() do { active_nlr = NULL; } while (0)
            static qstr qstr_from_str(const char *s) { (void)s; return 1; }
            static mp_lexer_t *mp_lexer_new_from_file(qstr q) { (void)q; return &lexer; }
            static mp_lexer_t *mp_lexer_new_from_str_len(qstr q, const char *s,
                                                         size_t n, int free_len) {
                (void)q; (void)s; (void)n; (void)free_len; return &lexer;
            }
            static mp_parse_tree_t mp_parse(mp_lexer_t *lex, int mode) {
                mp_parse_tree_t tree = {0}; (void)lex; (void)mode; return tree;
            }
            static mp_obj_t mp_compile(mp_parse_tree_t *tree, qstr q, bool repl) {
                (void)tree; (void)q; (void)repl; return 1;
            }
            static void mp_call_function_0(mp_obj_t fn) {
                (void)fn;
                if (phase == 1) current_globals->marker = 1;
                if (phase == 2) leaked = current_globals->marker;
                if (phase == 3) {
                    active_nlr->ret_val = (void *)(uintptr_t)99;
                    longjmp(active_nlr->jump, 1);
                }
            }
            static void mp_handle_pending(int mode) { (void)mode; }
            static bool pble_runner_stop_requested(void) { return false; }
            static void mp_obj_print_exception(const mp_print_t *print, mp_obj_t exc) {
                (void)print; (void)exc;
            }
            static mp_obj_dict_t *mp_globals_get(void) { return current_globals; }
            static mp_obj_dict_t *mp_locals_get(void) { return current_locals; }
            static void mp_globals_set(mp_obj_dict_t *dict) { current_globals = dict; }
            static void mp_locals_set(mp_obj_dict_t *dict) { current_locals = dict; }
            static mp_obj_t mp_obj_new_dict(size_t count) {
                (void)count;
                if (pool_used >= sizeof(pool) / sizeof(pool[0])) abort();
                pool[pool_used].marker = 0;
                pool[pool_used].name_is_main = 0;
                return MP_OBJ_FROM_PTR(&pool[pool_used++]);
            }
            static void mp_obj_dict_store(mp_obj_t dict, mp_obj_t key, mp_obj_t value) {
                mp_obj_dict_t *target = (mp_obj_dict_t *)MP_OBJ_TO_PTR(dict);
                if (key == MP_QSTR___name__ && value == MP_QSTR___main__) {
                    target->name_is_main = 1;
                }
            }
            static void mp_store_global(qstr key, mp_obj_t value) {
                mp_obj_dict_store(MP_OBJ_FROM_PTR(current_globals), key, value);
            }
            static void mp_store_name(qstr key, mp_obj_t value) {
                mp_obj_dict_store(MP_OBJ_FROM_PTR(current_locals), key, value);
            }
            '''
        )
        main = textwrap.dedent(
            r'''
            int main(void) {
                phase = 1;
                if (!runner_exec(1, "first", 5)) return 20;
                if (current_globals != &main_dict || current_locals != &main_dict) return 21;
                phase = 2;
                if (!runner_exec(1, "second", 6)) return 22;
                if (current_globals != &main_dict || current_locals != &main_dict) return 23;
                phase = 3;
                if (runner_exec(1, "raises", 6)) return 27;
                if (current_globals != &main_dict || current_locals != &main_dict) return 28;
                if (leaked) return 24;
                if (pool_used != 3) return 25;
                if (!pool[0].name_is_main || !pool[1].name_is_main ||
                    !pool[2].name_is_main) return 26;
                return 0;
            }
            '''
        )
        with tempfile.TemporaryDirectory(prefix="pyble-v061-runner-") as temp:
            source = Path(temp) / "runner_probe.c"
            binary = Path(temp) / "runner_probe"
            source.write_text(harness + "\n" + runner_exec + "\n" + main,
                              encoding="utf-8")
            built = subprocess.run(
                [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                 "-Wno-unused-function",
                 str(source), "-o", str(binary)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(
                built.returncode, 0,
                "runner_exec host probe did not compile:\n{}{}".format(
                    built.stdout, built.stderr),
            )
            executed = subprocess.run(
                [str(binary)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, check=False)
            self.assertEqual(
                executed.returncode, 0,
                "runner_exec leaked/restored incorrectly; probe exit {}".format(
                    executed.returncode),
            )


class NativeReassemblyTests(unittest.TestCase):
    def test_rx_capacity_carries_the_largest_supported_run_source(self):
        match = re.search(r"#\s*define\s+PBLE_MSG_MAX\s+(\d+)\b", BLE)
        self.assertIsNotNone(match, "native reassembly needs a fixed static cap")
        # RUN payload is [mode:u8][source <= 2048], inside the six-byte PBLE
        # header and four-byte CRC. A smaller transport cap makes a valid
        # handler-level maximum unreachable on every ESP profile.
        self.assertGreaterEqual(
            int(match.group(1)), 6 + 1 + 2048 + 4,
            "native RX cannot carry the documented maximum RUN source frame",
        )

    def test_compiled_rx_discards_empty_cut_and_correlates_split_header(self):
        compiler = shutil.which(os.environ.get("CC", "cc"))
        self.assertIsNotNone(compiler, "a host C compiler is required for RX")
        limit_match = re.search(r"#\s*define\s+PBLE_MSG_MAX\s+(\d+)\b", BLE)
        self.assertIsNotNone(limit_match)
        limit = int(limit_match.group(1))
        reset = c_function(BLE, "pble_reset_reassembly")
        discard = c_function(BLE, "pble_discard_reassembly_tail")
        ingest = c_function(BLE, "pble_rx_ingest")
        harness = textwrap.dedent(
            r'''
            #include <stdbool.h>
            #include <stddef.h>
            #include <stdint.h>
            #include <string.h>

            #define PBLE_MSG_MAX __LIMIT__
            #define PBLE_FRAG_FIRST 0x80
            #define PBLE_FRAG_LAST 0x40
            #define PBLE_FRAG_IDX_MASK 0x3f
            #define PBLE_FRAG_IDX_MOD 64
            #define PBLE_RX_REASSEMBLY_DEADLINE_US 5000000LL
            #define PBLE_PROTO_VERSION 1
            #define PBLE_TYPE_CMD 1
            #define PBLE_ERANGE 9

            typedef struct { uint16_t conn; } pble_session_token_t;
            static uint8_t pble_rx_buf[PBLE_MSG_MAX];
            static size_t pble_rx_len;
            static bool pble_rx_active;
            static uint8_t pble_rx_next_index;
            static int64_t pble_rx_started_us;
            static bool pble_rx_discard_tail;
            static bool pble_rx_hdr_valid;
            static uint8_t pble_rx_hdr_ver;
            static uint8_t pble_rx_hdr_type;
            static uint8_t pble_rx_hdr_op;
            static uint8_t pble_rx_hdr_id;
            static int dispatch_calls;
            static int violation_calls;
            static int refuse_calls;
            static uint8_t refused_op;
            static uint8_t refused_id;
            static uint8_t refused_status;

            static int64_t esp_timer_get_time(void) { return 100; }
            static bool pble_ble_record_protocol_violation(
                    const pble_session_token_t *session) {
                (void)session;
                violation_calls++;
                return true;
            }
            static void pble_proto_dispatch(const uint8_t *msg, size_t len,
                                            uint16_t conn) {
                (void)msg; (void)len; (void)conn;
                dispatch_calls++;
            }
            static void pble_proto_refuse(uint8_t op, uint8_t id,
                                          uint8_t status,
                                          const pble_session_token_t *session) {
                (void)session;
                refuse_calls++;
                refused_op = op;
                refused_id = id;
                refused_status = status;
            }
            '''
        ).replace("__LIMIT__", str(limit))
        main = textwrap.dedent(
            r'''
            static int empty_write_cut(const pble_session_token_t *session) {
                uint8_t first[] = {PBLE_FRAG_FIRST, 'A'};
                uint8_t stale_last[] = {PBLE_FRAG_LAST | 1, 'B'};
                pble_reset_reassembly();
                dispatch_calls = violation_calls = 0;
                pble_rx_ingest(first, sizeof(first), session);
                pble_rx_ingest(NULL, 0, session);
                pble_rx_ingest(stale_last, sizeof(stale_last), session);
                return dispatch_calls == 0 && violation_calls == 1;
            }

            static int split_header_oversize(const pble_session_token_t *session) {
                uint8_t message[PBLE_MSG_MAX + 1];
                uint8_t packet[98];
                memset(message, 'X', sizeof(message));
                message[0] = PBLE_PROTO_VERSION;
                message[1] = PBLE_TYPE_CMD;
                message[2] = 0x20;
                message[3] = 0x2a;
                message[4] = 0;
                message[5] = 0;
                pble_reset_reassembly();
                refuse_calls = violation_calls = 0;
                size_t offset = 0;
                uint8_t index = 0;
                while (offset < sizeof(message)) {
                    size_t chunk = index == 0 ? 1 : sizeof(packet) - 1;
                    if (chunk > sizeof(message) - offset) {
                        chunk = sizeof(message) - offset;
                    }
                    packet[0] = (index == 0 ? PBLE_FRAG_FIRST : 0) |
                                (index & PBLE_FRAG_IDX_MASK);
                    memcpy(packet + 1, message + offset, chunk);
                    pble_rx_ingest(packet, chunk + 1, session);
                    offset += chunk;
                    index = (uint8_t)((index + 1) % PBLE_FRAG_IDX_MOD);
                }
                return refuse_calls == 1 && violation_calls == 1 &&
                       refused_op == 0x20 && refused_id == 0x2a &&
                       refused_status == PBLE_ERANGE;
            }

            int main(void) {
                pble_session_token_t session = {7};
                if (!empty_write_cut(&session)) return 20;
                if (!split_header_oversize(&session)) return 21;
                return 0;
            }
            '''
        )
        with tempfile.TemporaryDirectory(prefix="pyble-v061-rx-") as temp:
            source = Path(temp) / "rx_probe.c"
            binary = Path(temp) / "rx_probe"
            source.write_text(
                harness + "\n" + reset + "\n" + discard + "\n" + ingest +
                "\n" + main,
                encoding="utf-8",
            )
            built = subprocess.run(
                [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                 "-Wno-unused-variable", str(source), "-o", str(binary)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(
                built.returncode, 0,
                "native RX host probe did not compile:\n{}{}".format(
                    built.stdout, built.stderr),
            )
            executed = subprocess.run(
                [str(binary)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, check=False)
            self.assertEqual(
                executed.returncode, 0,
                "native RX mishandled empty/split-header input; probe exit {}"
                .format(executed.returncode),
            )


class NativeLabelAndNvsTests(unittest.TestCase):
    def test_missing_nvs_namespace_is_clean_first_boot(self):
        autorun = code_only(c_function(BOOT, "pble_boot_autorun_enabled"))
        self.assertRegex(
            autorun,
            r"open_rc\s*==\s*ESP_ERR_NVS_NOT_FOUND[\s\S]*"
            r"boot_config_fault\s*=\s*BOOT_CONFIG_OK",
            "an erased device without the NVS namespace is clean first boot",
        )
        init = code_only(c_function(DEVICE_CONFIG, "pble_dc_init"))
        self.assertRegex(
            init,
            r"else\s+if\s*\(\s*open_rc\s*!=\s*ESP_ERR_NVS_NOT_FOUND\s*\)"
            r"[\s\S]*dc_config_fault",
            "missing device-config namespace must not set a corruption fault",
        )

    def test_set_and_load_share_the_strict_label_validator(self):
        self.assertIsNotNone(
            re.search(r"\bpble_dc_label_status\s*\(", DEVICE_CONFIG),
            "native strict UTF-8 validator must have one directly testable seam",
        )
        set_label = code_only(c_function(DEVICE_CONFIG, "pble_dc_set_label"))
        init = code_only(c_function(DEVICE_CONFIG, "pble_dc_init"))
        self.assertIn("pble_dc_label_status(", set_label)
        self.assertIn("pble_dc_label_status(", init,
                      "persisted NVS labels require the same validation as BLE input")

    def test_label_commit_is_checked_before_ram_and_advertisement_change(self):
        body = code_only(c_function(DEVICE_CONFIG, "pble_dc_set_label"))
        assert_checked_commit(self, body, "SET_LABEL")
        commit = body.find("nvs_commit(")
        mutations = [position for position in (
            body.find("dc_label["), body.find("memcpy(dc_label")) if position >= 0]
        self.assertTrue(mutations, "SET_LABEL must publish its committed label to RAM")
        self.assertLess(commit, min(mutations), "RAM label changed before NVS commit")
        self.assertGreater(body.find("pble_ble_set_adv_name", commit), commit)

    def test_identify_uses_one_authoritative_versioned_blob(self):
        for pattern, message in (
            (r'#\s*define\s+DC_KEY_IDCFG\s+"id_cfg"',
             "Identify needs one authoritative id_cfg NVS key"),
            (r'#\s*define\s+DC_IDCFG_VERSION\s+1\b',
             "Identify blob schema version must be 1"),
            (r'#\s*define\s+DC_IDCFG_LEN\s+4\b',
             "Identify blob must be exactly four bytes"),
        ):
            self.assertIsNotNone(re.search(pattern, DEVICE_CONFIG), message)
        init = code_only(c_function(DEVICE_CONFIG, "pble_dc_init"))
        setter = code_only(c_function(DEVICE_CONFIG, "pble_dc_set_identify_led"))
        self.assertIn("nvs_get_blob(", init)
        self.assertLess(init.find("nvs_get_blob("), init.find("nvs_get_u8("),
                        "authoritative id_cfg must be examined before legacy fallback")
        self.assertRegex(
            init,
            r"ESP_ERR_NVS_NOT_FOUND[\s\S]*nvs_get_u8\s*\(",
            "legacy keys may be consulted only when id_cfg is absent",
        )
        self.assertIn("nvs_set_blob(", setter)
        self.assertNotRegex(setter, r"nvs_set_u8\s*\([^,]+,\s*DC_KEY_ID")
        self.assertNotRegex(setter, r"nvs_erase_key\s*\([^,]+,\s*DC_KEY_ID")
        assert_checked_commit(self, setter, "SET_IDENTIFY_LED")
        commit = setter.find("nvs_commit(")
        publish = setter.find("dc_id_configured", commit)
        self.assertGreater(publish, commit, "Identify RAM/GPIO changed before commit")

    def test_autorun_commit_is_checked_and_only_exact_one_enables(self):
        enabled = code_only(c_function(BOOT, "pble_boot_autorun_enabled"))
        self.assertRegex(enabled, r"return\s+v\s*==\s*1\s*;")
        self.assertNotRegex(enabled, r"return\s+v\s*!=\s*0\s*;")
        setter = code_only(c_function(BOOT, "pble_boot_set_autorun"))
        assert_checked_commit(self, setter, "SET_AUTORUN")

    def test_autorun_wire_payload_is_exactly_one_boolean_byte(self):
        handler = code_only(c_function(BOOT, "pble_boot_set_autorun_cmd"))
        self.assertRegex(
            handler,
            r"req->len\s*!=\s*1",
            "SET_AUTORUN must reject both short and trailing payload bytes",
        )
        self.assertRegex(
            handler,
            r"req->payload\s*\[\s*0\s*\]\s*>\s*1",
            "SET_AUTORUN accepts only exact wire values 0 and 1",
        )
        self.assertNotRegex(handler, r"req->payload\s*\[\s*0\s*\]\s*!=\s*0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
