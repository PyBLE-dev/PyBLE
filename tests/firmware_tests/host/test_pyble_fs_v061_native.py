#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Native-C parity guard for the v0.6.1 filesystem hardening increment.
#
# The portable suite provides executable semantic coverage over a real host
# filesystem.  pble_fs.c is coupled to the MicroPython VM, MP streams, NLR,
# FreeRTOS, and the response-ticket lifecycle, so pretending to execute it with
# a large fake runtime would test the fake.  These focused structural checks
# instead ensure the native path contains the same gates, in the safe order,
# while existing ESP build/HIL gates provide compilation and physical proof.

import os
import re
import shutil
import subprocess
import tempfile
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SOURCE_PATH = os.path.join(
    REPO_ROOT, "firmware", "user_c_modules", "pyble", "pble_fs.c")
HEADER_PATH = os.path.join(
    REPO_ROOT, "firmware", "user_c_modules", "pyble", "pble_fs.h")


def _matching_brace(source, opening):
    """Return the matching `}` while ignoring comments and C literals."""
    depth = 0
    index = opening
    state = "code"
    while index < len(source):
        char = source[index]
        nxt = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if char == "/" and nxt == "*":
                state = "block-comment"
                index += 2
                continue
            if char == "/" and nxt == "/":
                state = "line-comment"
                index += 2
                continue
            if char == '"':
                state = "string"
            elif char == "'":
                state = "char"
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index
        elif state == "block-comment":
            if char == "*" and nxt == "/":
                state = "code"
                index += 2
                continue
        elif state == "line-comment":
            if char == "\n":
                state = "code"
        elif state in ("string", "char"):
            if char == "\\":
                index += 2
                continue
            if (state == "string" and char == '"') or (
                    state == "char" and char == "'"):
                state = "code"
        index += 1
    raise AssertionError("unbalanced C function body at byte {}".format(opening))


def _function_span(source, name):
    # The leading return-type match is line-anchored so calls cannot masquerade
    # as definitions.  pble_fs.c uses ordinary C definitions without attributes.
    pattern = re.compile(
        r"(?m)^[ \t]*(?:static[ \t]+)?[A-Za-z_][A-Za-z0-9_ \t*]*"
        + re.escape(name)
        + r"[ \t]*\([^;{}]*\)[ \t]*\{")
    match = pattern.search(source)
    if match is None:
        raise AssertionError("native function `{}` is missing".format(name))
    opening = source.find("{", match.start(), match.end())
    closing = _matching_brace(source, opening)
    return match.start(), closing + 1, source[opening + 1:closing]


def _function_body(source, name):
    return _function_span(source, name)[2]


def _defined_functions(source):
    names = set(re.findall(
        r"(?m)^[ \t]*(?:[A-Za-z_][A-Za-z0-9_]*[ \t*]+)+?"
        r"([A-Za-z_][A-Za-z0-9_]*)[ \t]*\([^;{}]*\)[ \t]*\{",
        source))
    return dict((name, _function_body(source, name)) for name in names)


class NativeFsV061ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SOURCE_PATH, "r", encoding="utf-8") as source_file:
            cls.source = source_file.read()
        with open(HEADER_PATH, "r", encoding="utf-8") as header_file:
            cls.header = header_file.read()

    def test_list_filters_scratch_before_budget_stat_and_serialisation(self):
        body = _function_body(self.source, "fs_do_list")
        name_at = body.find("mp_obj_str_get_data")
        suffix_at = body.find("fs_has_tmp_suffix")
        budget_at = body.find("PBLE_RSP_MAX")
        stat_at = body.find("fs_stat_path")
        serialise_at = body.find("memcpy(g_scratch")

        self.assertGreaterEqual(
            suffix_at, 0,
            "native FILE_LIST must invoke its existing .pbltmp suffix helper")
        self.assertTrue(
            name_at < suffix_at < budget_at,
            "scratch filtering must occur after decoding the entry name but "
            "before response-budget/more processing")
        self.assertTrue(
            suffix_at < stat_at and suffix_at < serialise_at,
            "a hidden entry must consume neither VFS stat work nor response bytes")
        self.assertIn(
            "continue", body[suffix_at:budget_at],
            "the scratch predicate must skip the directory entry, not merely inspect it")

    def test_mailbox_payload_holds_two_maximum_rename_paths(self):
        capacity = re.search(
            r"#\s*define\s+PBLE_FS_ITEM_PAYLOAD\s+(\d+)\b", self.source)
        self.assertIsNotNone(capacity)
        self.assertGreaterEqual(
            int(capacity.group(1)), 2 + 128 + 2 + 128,
            "the native mailbox cannot reject a protocol-valid 128/128 "
            "FILE_RENAME before either path reaches the jail validator",
        )

    def test_each_mutator_gates_every_active_transfer_after_path_resolution(self):
        cases = (
            ("fs_do_delete", 1, "fs_stat_path"),
            ("fs_do_mkdir", 1, "mp_vfs_mkdir"),
            ("fs_do_rename", 2, "fs_stat_path"),
        )
        for function, resolve_count, first_effect in cases:
            with self.subTest(function=function):
                body = _function_body(self.source, function)
                resolve_positions = [
                    match.start()
                    for match in re.finditer(r"\bpble_fs_resolve\s*\(", body)
                ]
                self.assertEqual(
                    len(resolve_positions), resolve_count,
                    "the existing jail chokepoint count must remain explicit")
                busy_at = body.find("fs_put_active_current(it)")
                effect_at = body.find(first_effect)
                self.assertGreaterEqual(
                    busy_at, 0,
                    "{} must consult generation-qualified active PUT ownership"
                    .format(function))
                self.assertTrue(
                    resolve_positions[-1] < busy_at < effect_at,
                    "{} must apply jail precedence, then EBUSY, before the first "
                    "namespace probe/effect".format(function))
                gate = body[busy_at:effect_at]
                self.assertIn("PBLE_EBUSY", gate)
                self.assertIn("return", gate)

                get_busy_at = body.find("get_active_at_enqueue")
                self.assertTrue(
                    resolve_positions[-1] < get_busy_at < effect_at,
                    "{} must consume the admission-time active-GET snapshot "
                    "after jail resolution and before VFS".format(function),
                )

    def test_native_mailbox_snapshots_accepted_get_activity(self):
        item = re.search(
            r"typedef\s+struct\s*\{(?P<body>[^{}]*)\}\s*pble_fs_req_t\s*;",
            self.source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(item)
        self.assertRegex(
            item.group("body"),
            r"\bbool\s+get_active_at_enqueue\s*;",
            "each queued command must retain whether a GET owned its "
            "admission instant",
        )

        enqueue = _function_body(self.source, "fs_enqueue")
        self.assertIn("get_active_at_enqueue", enqueue)
        self.assertIn("g_get_active", enqueue)
        snapshot_at = enqueue.find("get_active_at_enqueue")
        queue_at = enqueue.find("xQueueSend")
        self.assertTrue(0 <= snapshot_at < queue_at)

        get_body = _function_body(self.source, "fs_do_get")
        self.assertIn("g_get_active", get_body)
        self.assertRegex(
            get_body,
            r"g_get_active\s*=\s*true",
            "GET must become active before its successful response commits",
        )
        self.assertRegex(
            get_body,
            r"g_get_active\s*=\s*false",
            "every completed or aborted stream must release active GET",
        )

    def test_put_data_checks_crossing_with_non_overflowing_math_before_write(self):
        body = _function_body(self.source, "fs_do_put_data")
        write_at = body.find("sp->write")
        latch_at = body.find("g_put_latched = PBLE_ERANGE")
        self.assertGreaterEqual(
            latch_at, 0,
            "a chunk crossing total_size must latch PBLE_ERANGE")
        self.assertLess(latch_at, write_at,
                        "range rejection must occur before the first MP stream write")
        prewrite = body[:write_at]
        self.assertRegex(
            prewrite,
            r"(?:offset|g_put_watermark)\s*>\s*g_put_total",
            "check the contiguous offset before subtracting it from the declared total")
        self.assertRegex(
            prewrite,
            r"n\s*>\s*\(?\s*g_put_total\s*-\s*"
            r"(?:offset|g_put_watermark)\s*\)?",
            "use subtraction-form bounds checking; offset+n may wrap uint32_t")
        self.assertIn("fs_put_ack", body[latch_at:write_at])
        self.assertIn("return", body[latch_at:write_at])

    def test_put_data_rejects_zero_or_impossible_stream_progress(self):
        body = _function_body(self.source, "fs_do_put_data")
        write_at = body.find("sp->write")
        progress_at = body.find("done +=", write_at)
        self.assertGreaterEqual(write_at, 0)
        self.assertGreater(progress_at, write_at)
        guard = body[write_at:progress_at]
        self.assertRegex(
            guard,
            r"\bw\s*==\s*0",
            "a zero-byte successful write must not spin the filesystem worker",
        )
        self.assertRegex(
            guard,
            r"\bw\s*>\s*\(?\s*n\s*-\s*done\s*\)?",
            "an impossible over-report must not advance beyond the input chunk",
        )
        self.assertIn("PBLE_EIO", guard)
        self.assertIn("break", guard)

    def test_every_native_read_rejects_backend_overreport_before_buffer_use(self):
        cases = (
            ("fs_crc_file", "PBLE_FS_SCRATCH"),
            ("fs_crc_prefix", "want"),
            ("fs_do_get", "chunk"),
        )
        for function, requested in cases:
            with self.subTest(function=function):
                body = _function_body(self.source, function)
                read_at = body.find("sp->read")
                crc_at = body.find("crc32_update", read_at)
                self.assertTrue(0 <= read_at < crc_at)
                guard = body[read_at:crc_at]
                self.assertRegex(
                    guard,
                    r"\bn\s*>\s*\(?\s*{}\s*\)?".format(
                        re.escape(requested)),
                    "{} trusts a stream count larger than its {}-byte "
                    "destination and may read beyond g_scratch".format(
                        function, requested),
                )
                self.assertRegex(guard, r"\b(?:MP|PBLE)_EIO\b")

    def test_stat_crc_consumes_exactly_the_advertised_extent(self):
        start, _end, crc_body = _function_span(self.source, "fs_crc_file")
        signature = self.source[start:self.source.find("{", start)]
        self.assertRegex(
            signature,
            r"fs_crc_file\s*\([^)]*uint32_t\s+(?:expected|extent|size)",
            "FILE_STAT must pass its stat-advertised size into the CRC scan",
        )
        self.assertRegex(
            crc_body,
            r"uint32_t\s+remaining\s*=\s*(?:expected|extent|size)\s*;",
        )
        self.assertRegex(crc_body, r"while\s*\(\s*remaining\s*>\s*0\s*\)")
        self.assertRegex(
            crc_body,
            r"sp->read\s*\([^;]*,\s*want\s*,",
            "the last CRC read must be bounded by the promised remainder",
        )
        eof = re.search(
            r"if\s*\(\s*n\s*==\s*0\s*\)\s*\{(?P<body>[^{}]*)\}",
            crc_body,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(eof)
        self.assertNotIn("break", eof.group("body"))
        self.assertRegex(eof.group("body"), r"(?:MP|PBLE)_EIO")
        stat_body = _function_body(self.source, "fs_do_stat")
        self.assertRegex(
            stat_body,
            r"fs_crc_file\s*\(\s*it\s*,\s*path\s*,\s*size\s*,\s*&crc\s*\)",
        )

    def test_get_short_read_cannot_emit_a_completion_event(self):
        body = _function_body(self.source, "fs_do_get")
        self.assertRegex(body, r"uint32_t\s+remaining\s*=\s*total\s*;")
        self.assertRegex(body, r"while\s*\(\s*remaining\s*>\s*0\s*\)")
        read_at = body.find("sp->read")
        self.assertGreaterEqual(read_at, 0)
        self.assertRegex(
            body[read_at:body.find("crc32_update", read_at)],
            r"\bn\s*>\s*want\b",
            "GET must compare a backend count with the exact final read size",
        )
        self.assertRegex(
            body[read_at:body.find("crc32_update", read_at)],
            r"\bn\s*==\s*0\b[\s\S]*(?:MP|PBLE)_EIO",
            "zero before the promised total must take the read-failure path",
        )
        self.assertIn(
            "stream_complete",
            body,
            "GET_END needs an explicit exact-extent completion predicate",
        )
        end_at = body.find("PBLE_OP_FILE_GET_END")
        self.assertGreater(end_at, 0)
        completion_gate = body[max(0, end_at - 500):end_at]
        self.assertIn(
            "stream_complete", completion_gate,
            "a catch path or early EOF must not publish FILE_GET_END",
        )

    def test_put_end_requires_a_successful_close_before_rename(self):
        functions = _defined_functions(self.source)
        close = functions["fs_put_close"]
        end = functions["fs_do_put_end"]
        signature_start, _end, _body = _function_span(
            self.source, "fs_put_close")
        signature = self.source[
            signature_start:self.source.find("{", signature_start)]
        self.assertRegex(signature, r"\buint8_t\s+fs_put_close\s*\(")
        self.assertIn("PBLE_EIO", close)
        close_at = end.find("fs_put_close(")
        rename_at = end.find("mp_vfs_rename(")
        self.assertTrue(0 <= close_at < rename_at)
        gate = end[close_at:rename_at]
        self.assertIn("PBLE_OK", gate)
        self.assertIn("return", gate)
        self.assertIn("fs_put_abort", gate)

    def test_put_abort_returns_checked_cleanup_and_verifies_absence(self):
        start, _end, abort = _function_span(self.source, "fs_put_abort")
        signature = self.source[start:self.source.find("{", start)]
        self.assertRegex(signature, r"\buint8_t\s+fs_put_abort\s*\(")
        self.assertIn("fs_put_close", abort)
        self.assertIn("mp_vfs_remove", abort)
        self.assertGreaterEqual(
            abort.find("fs_stat_path", abort.find("mp_vfs_remove")), 0,
            "a nominally successful abort remove must be followed by stat",
        )
        self.assertIn("PBLE_EIO", abort)

        end = _function_body(self.source, "fs_do_put_end")
        self.assertRegex(
            end,
            r"(?:return|=)[^;\n]*fs_put_abort\s*\(",
            "PUT_END must consume abort status instead of discarding it",
        )

    def test_resume_requires_exact_regular_file_mode(self):
        start, end, _body = _function_span(self.source, "fs_mode_is_regular")
        helper = self.source[start:end]
        compiler = shutil.which(os.environ.get("CC", "cc"))
        self.assertIsNotNone(compiler, "a host C compiler is required")
        probe = (
            "#include <stdbool.h>\n"
            "typedef long mp_int_t;\n"
            "#define MP_S_IFREG 0x8000\n"
            + helper
            + "\nint main(void) {\n"
            "  if (!fs_mode_is_regular(0x8000)) return 20;\n"
            "  if (!fs_mode_is_regular(0x81a4)) return 21;\n"
            "  if (fs_mode_is_regular(0x4000)) return 22;\n"
            "  if (fs_mode_is_regular(0xa000)) return 23;\n"
            "  if (fs_mode_is_regular(0x2000)) return 24;\n"
            "  if (fs_mode_is_regular(0x0000)) return 25;\n"
            "  return 0;\n}\n"
        )
        with tempfile.TemporaryDirectory(prefix="pyble-v061-mode-") as temp:
            source = os.path.join(temp, "mode_probe.c")
            binary = os.path.join(temp, "mode_probe")
            with open(source, "w", encoding="utf-8") as stream:
                stream.write(probe)
            built = subprocess.run(
                [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                 source, "-o", binary],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, check=False,
            )
            self.assertEqual(
                built.returncode, 0,
                "native mode probe did not compile:\n{}{}".format(
                    built.stdout, built.stderr),
            )
            executed = subprocess.run(
                [binary], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, check=False,
            )
            self.assertEqual(
                executed.returncode, 0,
                "native regular-file predicate accepted a non-regular mode; "
                "probe exit {}".format(executed.returncode),
            )

        stat = _function_body(self.source, "fs_stat_path")
        resume = _function_body(self.source, "pble_fs_resume_prefix")
        self.assertIn("fs_mode_is_regular", stat)
        self.assertRegex(resume, r"!\s*[A-Za-z_]*isreg")

    def test_put_begin_calls_checked_statvfs_admission_before_open(self):
        functions = _defined_functions(self.source)
        providers = [
            name for name, body in functions.items()
            if "mp_vfs_statvfs" in body
        ]
        self.assertEqual(
            len(providers), 1,
            "native filesystem must have one auditable mp_vfs_statvfs admission helper")
        provider_name = providers[0]
        provider = functions[provider_name]
        begin = functions["fs_do_put_begin"]

        if provider_name == "fs_do_put_begin":
            admission_at = begin.find("mp_vfs_statvfs")
        else:
            admission_at = begin.find(provider_name + "(")
            self.assertGreaterEqual(
                admission_at, 0,
                "FILE_PUT_BEGIN must call the statvfs admission helper")
        resume_at = begin.find("pble_fs_resume_prefix")
        open_at = begin.find("fs_open")
        self.assertTrue(
            resume_at < admission_at < open_at,
            "validate/normalise scratch, determine resume, then admit remaining "
            "allocation before opening or growing scratch")

        reserve_names = set(re.findall(
            r"\b[A-Za-z_][A-Za-z0-9_]*reserve[A-Za-z0-9_]*\b",
            self.source, flags=re.IGNORECASE))
        reserve_names = set(
            name for name in reserve_names
            if name.lower() != "reserve" and "_" in name)
        used_reserves = [name for name in reserve_names if name in provider]
        self.assertTrue(
            used_reserves,
            "the statvfs helper must apply a named safety-reserve constant")
        definitions = self.source + "\n" + self.header
        definition_lines = [
            line for line in definitions.splitlines()
            if any(name in line for name in used_reserves)
        ]
        compact = "".join(definition_lines).replace(" ", "").lower()
        self.assertTrue(
            "65536" in compact or "64u*1024u" in compact
            or "64*1024" in compact,
            "native admission reserve must be exactly 65,536 bytes")
        self.assertIn("uint64_t", provider,
                      "free-space and rounded-needed arithmetic must not wrap u32")
        self.assertIn("PBLE_ENOSPC", provider)
        self.assertIn("PBLE_EIO", provider)
        self.assertRegex(provider, r"\[\s*1\s*\]",
                         "statvfs f_frsize is tuple field 1")
        self.assertRegex(provider, r"\[\s*4\s*\]",
                         "statvfs f_bavail is tuple field 4")

    def test_resume_helper_returns_explicit_status_and_cleans_malformed_state(self):
        start, _end, body = _function_span(self.source, "pble_fs_resume_prefix")
        signature = self.source[start:self.source.find("{", start)]
        self.assertRegex(
            signature,
            r"\buint8_t\s+pble_fs_resume_prefix\s*\(",
            "resume helper must return an explicit PBLE status, not overload "
            "resume_offset zero as both fresh and failed")
        functions = _defined_functions(self.source)
        cleanup = body
        if "mp_vfs_remove" not in cleanup or "mp_vfs_rmdir" not in cleanup:
            cleanup_helpers = [
                (name, candidate)
                for name, candidate in functions.items()
                if "mp_vfs_remove" in candidate and "mp_vfs_rmdir" in candidate
                and name + "(" in body
            ]
            self.assertEqual(
                len(cleanup_helpers), 1,
                "resume must directly clean malformed scratch or call one "
                "auditable non-recursive cleanup helper")
            cleanup = cleanup_helpers[0][1]
        self.assertIn("mp_vfs_remove", cleanup,
                      "malformed regular scratch must be removed explicitly")
        self.assertIn("mp_vfs_rmdir", cleanup,
                      "an empty malformed scratch directory must be removed safely")
        self.assertTrue(
            "PBLE_EIO" in body or "PBLE_EIO" in cleanup,
            "uncleanable/type-invalid scratch must fail closed")
        self.assertGreaterEqual(
            len(re.findall(r"\bfs_stat_path\s*\(", body)), 2,
            "resume must re-stat after scanning to reject a changed type/length")

        begin = functions["fs_do_put_begin"]
        resume_at = begin.find("pble_fs_resume_prefix")
        first_open_at = begin.find("fs_open")
        status_window = begin[resume_at:first_open_at]
        self.assertIn("PBLE_OK", status_window)
        self.assertIn(
            "return", status_window,
            "FILE_PUT_BEGIN must stop before opening scratch when resume "
            "validation/normalisation returns a failure status")

        crc_body = _function_body(self.source, "fs_crc_prefix")
        eof = re.search(
            r"if\s*\(\s*n\s*==\s*0\s*\)\s*\{([^{}]*)\}", crc_body,
            flags=re.DOTALL)
        self.assertIsNotNone(eof,
                             "prefix scanner must handle premature EOF explicitly")
        self.assertNotIn(
            "break", eof.group(1),
            "premature EOF before the stat length cannot produce a successful CRC")
        self.assertTrue(
            "PBLE_EIO" in eof.group(1) or "return" in eof.group(1),
            "premature EOF must surface as malformed/error to the resume helper")


if __name__ == "__main__":
    unittest.main(verbosity=2)
