#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""RED cross-runtime contract for exact PBLE/1 command payload grammar.

The JSON corpus is deliberately shared by the portable dispatcher and the
dependency-free native wire admission unit.  A malformed structured payload
must be rejected before a registered handler can observe it.  Commands whose
last field is explicitly "remaining bytes" are the counterexample: every byte
in that field remains valid payload and must reach the handler unchanged.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HOST = Path(__file__).resolve().parent
NATIVE = ROOT / "firmware" / "user_c_modules" / "pyble"
CORPUS_PATH = HOST / "conformance" / "v061_payload_grammar_vectors.json"

if str(HOST) not in sys.path:
    sys.path.insert(0, str(HOST))
import _support  # noqa: E402

_support._inject_micropython_guards()
import pyble_proto as proto  # noqa: E402


CMD = 0x01
RSP = 0x02
OK = 0x00
EBADREQ = 0x01
NO_RESPONSE = frozenset((0x16, 0x31))


def load_vectors() -> dict:
    with CORPUS_PATH.open("r", encoding="utf-8") as stream:
        vectors = json.load(stream)
    if vectors.get("schema") != 1:
        raise AssertionError("unsupported payload-grammar corpus schema")
    return vectors


VECTORS = load_vectors()
HELLO_PAYLOAD = bytes.fromhex(VECTORS["structured"][0]["valid_payloads_hex"][0])


class FakeLink:
    """Small production-dispatcher link seam with observable violation debit."""

    def __init__(self) -> None:
        self.token = 1
        self.violations = 0

    def session_token(self) -> int:
        return self.token

    def record_protocol_violation(self, session: int) -> bool:
        if session == self.token:
            self.violations += 1
        return True


def fresh_portable_dispatcher():
    link = FakeLink()
    dispatcher = proto.Dispatcher(link)
    effects: list[tuple[int, bytes]] = []

    def handler(frame):
        effects.append((frame.opcode, bytes(frame.payload)))
        if frame.opcode in NO_RESPONSE:
            return None
        return bytes((OK,))

    for row in VECTORS["structured"] + VECTORS["terminal_bytes"]:
        dispatcher.register(row["opcode"], handler)
    return dispatcher, link, effects


def negotiate(dispatcher) -> None:
    response = dispatcher.on_message(
        proto.encode(CMD, proto.OPCODES["HELLO"], 0x7E, HELLO_PAYLOAD)
    )
    if response is None:
        raise AssertionError("test precondition: canonical HELLO produced no response")
    receipt = dispatcher.take_publish_callback()
    if receipt is None:
        raise AssertionError("test precondition: canonical HELLO armed no receipt")
    receipt()


class PortablePayloadGrammarTest(unittest.TestCase):
    def test_canonical_structured_payloads_reach_handler_unchanged(self):
        failures = []
        request_id = 1
        for row in VECTORS["structured"]:
            for payload_hex in row["valid_payloads_hex"]:
                dispatcher, _link, effects = fresh_portable_dispatcher()
                if row["opcode"] != proto.OPCODES["HELLO"]:
                    negotiate(dispatcher)
                    effects.clear()
                payload = bytes.fromhex(payload_hex)
                response = dispatcher.on_message(
                    proto.encode(CMD, row["opcode"], request_id, payload)
                )
                expected_effect = [(row["opcode"], payload)]
                if effects != expected_effect:
                    failures.append(
                        "{}: handler effects {!r}, expected {!r}".format(
                            row["name"], effects, expected_effect
                        )
                    )
                if response is None:
                    failures.append("{}: canonical request produced no RSP".format(row["name"]))
                else:
                    decoded = proto.decode(response)
                    if (decoded.type, decoded.opcode, decoded.id) != (
                        RSP,
                        row["opcode"],
                        request_id,
                    ) or not decoded.payload or decoded.payload[0] != OK:
                        failures.append("{}: canonical request did not return OK".format(row["name"]))
                request_id = request_id % 0xFF + 1
        self.assertEqual([], failures, "\n" + "\n".join(failures))

    def test_trailing_bytes_are_ebadreq_before_any_handler_side_effect(self):
        failures = []
        request_id = 0x40
        for row in VECTORS["structured"]:
            dispatcher, link, effects = fresh_portable_dispatcher()
            if row["opcode"] != proto.OPCODES["HELLO"]:
                negotiate(dispatcher)
                effects.clear()
                link.violations = 0
            payload = bytes.fromhex(row["invalid_payload_hex"])
            response = dispatcher.on_message(
                proto.encode(CMD, row["opcode"], request_id, payload)
            )
            status = None
            if response is not None:
                decoded = proto.decode(response)
                if decoded.type == RSP and decoded.payload:
                    status = decoded.payload[0]
            if status != EBADREQ or effects:
                failures.append(
                    "{}: status={!r}, handler_effects={!r}, violation_debits={}".format(
                        row["name"], status, effects, link.violations
                    )
                )
            request_id += 1
        self.assertEqual(
            [],
            failures,
            "structured payload trailing bytes crossed the portable admission cut:\n"
            + "\n".join(failures),
        )

    def test_terminal_byte_fields_reach_handler_whole_and_unchanged(self):
        failures = []
        request_id = 0x70
        for row in VECTORS["terminal_bytes"]:
            dispatcher, _link, effects = fresh_portable_dispatcher()
            negotiate(dispatcher)
            effects.clear()
            payload = bytes.fromhex(row["payload_hex"])
            response = dispatcher.on_message(
                proto.encode(CMD, row["opcode"], request_id, payload)
            )
            if effects != [(row["opcode"], payload)]:
                failures.append("{}: handler did not receive the complete payload".format(row["name"]))
            if row["opcode"] in NO_RESPONSE:
                if response is not None:
                    failures.append("{}: CMD-only form unexpectedly returned a RSP".format(row["name"]))
            elif response is None or proto.decode(response).payload[:1] != bytes((OK,)):
                failures.append("{}: response-bearing form did not return OK".format(row["name"]))
            request_id += 1
        self.assertEqual([], failures, "\n" + "\n".join(failures))


def c_array(name: str, payload: bytes) -> tuple[str, str, str]:
    if not payload:
        return "", "NULL", "0u"
    body = ", ".join("0x{:02x}u".format(value) for value in payload)
    return (
        "static const uint8_t {}[] = {{{}}};\n".format(name, body),
        name,
        "sizeof({})".format(name),
    )


def native_harness_source() -> str:
    declarations = []
    calls = []
    index = 0

    for row in VECTORS["structured"]:
        for payload_hex in row["valid_payloads_hex"]:
            declaration, pointer, length = c_array(
                "payload_{}".format(index), bytes.fromhex(payload_hex)
            )
            declarations.append(declaration)
            calls.append(
                "failures += check_valid(\"{} canonical\", 0x{:02x}u, {}, {});".format(
                    row["name"], row["opcode"], pointer, length
                )
            )
            index += 1
        declaration, pointer, length = c_array(
            "payload_{}".format(index), bytes.fromhex(row["invalid_payload_hex"])
        )
        declarations.append(declaration)
        calls.append(
            "failures += check_invalid(\"{} trailing\", 0x{:02x}u, {}, {});".format(
                row["name"], row["opcode"], pointer, length
            )
        )
        index += 1

    for row in VECTORS["terminal_bytes"]:
        declaration, pointer, length = c_array(
            "payload_{}".format(index), bytes.fromhex(row["payload_hex"])
        )
        declarations.append(declaration)
        calls.append(
            "failures += check_valid(\"{}\", 0x{:02x}u, {}, {});".format(
                row["name"], row["opcode"], pointer, length
            )
        )
        index += 1

    return textwrap.dedent(
        r"""
        #include <stdint.h>
        #include <stdio.h>
        #include <string.h>

        #include "pble_wire.c"

        #define FRAME_CAP 512u

        __DECLARATIONS__

        static size_t encode_cmd(uint8_t opcode, const uint8_t *payload,
                                 size_t payload_len, uint8_t *out) {
            size_t crc_at = 6u + payload_len;
            out[0] = PBLE_WIRE_VERSION;
            out[1] = PBLE_WIRE_TYPE_CMD;
            out[2] = opcode;
            out[3] = 0x35u;
            out[4] = (uint8_t)(payload_len & 0xffu);
            out[5] = (uint8_t)((payload_len >> 8) & 0xffu);
            if (payload_len != 0u) {
                memcpy(out + 6u, payload, payload_len);
            }
            uint32_t crc = pble_wire_crc32(out, crc_at);
            out[crc_at] = (uint8_t)(crc & 0xffu);
            out[crc_at + 1u] = (uint8_t)((crc >> 8) & 0xffu);
            out[crc_at + 2u] = (uint8_t)((crc >> 16) & 0xffu);
            out[crc_at + 3u] = (uint8_t)((crc >> 24) & 0xffu);
            return crc_at + 4u;
        }

        static int reaches_handler(const pble_wire_decision_t *decision) {
            return decision->action == PBLE_WIRE_DISPATCH ||
                   decision->commit_hello;
        }

        static void decide(uint8_t opcode, const uint8_t *payload,
                           size_t payload_len, pble_wire_decision_t *decision,
                           uint8_t *before, uint8_t *after, size_t *frame_len) {
            pble_wire_session_t session;
            pble_wire_session_reset(&session);
            pble_wire_session_commit_v1(&session);
            *frame_len = encode_cmd(opcode, payload, payload_len, before);
            memcpy(after, before, *frame_len);
            pble_wire_decide(&session, after, *frame_len, decision);
        }

        static int check_valid(const char *name, uint8_t opcode,
                               const uint8_t *payload, size_t payload_len) {
            uint8_t before[FRAME_CAP];
            uint8_t after[FRAME_CAP];
            size_t frame_len = 0u;
            pble_wire_decision_t decision;
            decide(opcode, payload, payload_len, &decision,
                   before, after, &frame_len);
            if (!reaches_handler(&decision) ||
                memcmp(before, after, frame_len) != 0) {
                fprintf(stderr,
                        "%s: canonical/terminal bytes did not reach handler "
                        "unchanged (action=%d status=%u commit=%d)\n",
                        name, (int)decision.action, (unsigned)decision.status,
                        decision.commit_hello ? 1 : 0);
                return 1;
            }
            return 0;
        }

        static int check_invalid(const char *name, uint8_t opcode,
                                 const uint8_t *payload, size_t payload_len) {
            uint8_t before[FRAME_CAP];
            uint8_t after[FRAME_CAP];
            size_t frame_len = 0u;
            pble_wire_decision_t decision;
            decide(opcode, payload, payload_len, &decision,
                   before, after, &frame_len);
            int handler_effects = reaches_handler(&decision) ? 1 : 0;
            if (decision.action != PBLE_WIRE_RSP ||
                decision.status != PBLE_WIRE_EBADREQ || handler_effects != 0) {
                fprintf(stderr,
                        "%s: action=%d status=%u handler_effects=%d\n",
                        name, (int)decision.action, (unsigned)decision.status,
                        handler_effects);
                return 1;
            }
            return 0;
        }

        int main(void) {
            int failures = 0;
            __CALLS__
            return failures == 0 ? 0 : 1;
        }
        """
    ).replace("__DECLARATIONS__", "".join(declarations)).replace(
        "__CALLS__", "\n    ".join(calls)
    )


@unittest.skipUnless(shutil.which("cc"), "a host C compiler is required")
class NativePayloadGrammarTest(unittest.TestCase):
    def test_production_wire_admission_uses_the_shared_exact_grammar(self):
        with tempfile.TemporaryDirectory(prefix="pyble-payload-grammar-") as temp_dir:
            source_path = Path(temp_dir) / "payload_grammar.c"
            binary_path = Path(temp_dir) / "payload_grammar"
            source_path.write_text(native_harness_source(), encoding="utf-8")
            compile_result = subprocess.run(
                [
                    shutil.which("cc"),
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I",
                    os.fspath(NATIVE),
                    os.fspath(source_path),
                    "-o",
                    os.fspath(binary_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                0,
                compile_result.returncode,
                "native payload-grammar harness did not compile:\n"
                + compile_result.stdout
                + compile_result.stderr,
            )
            run_result = subprocess.run(
                [os.fspath(binary_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                0,
                run_result.returncode,
                "production pble_wire payload admission diverged from the shared corpus:\n"
                + run_result.stdout
                + run_result.stderr,
            )


if __name__ == "__main__":
    unittest.main()
