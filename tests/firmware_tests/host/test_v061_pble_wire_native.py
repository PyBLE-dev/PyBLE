#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED parity contract for dependency-free native ``pble_wire``.

The production C unit is compiled directly with a small standard-C harness;
there is no Python reimplementation standing in for native behavior.  Exact
HELLO/frame bytes come from the same corpus as the portable Agent and Dart
client. Exact label bytes are consumed by both portable Python and native C.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NATIVE = ROOT / "firmware" / "user_c_modules" / "pyble"
HARNESS = HERE / "native" / "v061_pble_wire_harness.c"
SESSION_CORPUS = HERE / "conformance" / "v061_session_vectors.json"
LABEL_CORPUS = HERE / "conformance" / "v061_label_vectors.json"

sys.path.insert(0, str(HERE))
import _support  # noqa: E402

DC = _support.RedReason("pyble_device_config", owner="v0.6.1-config-engineer")

CMD = 0x01
HELLO = 0x01
CANONICAL_HELLO = (
    b"proto_versions=1\n"
    b"app_name=PyBLE\n"
    b"app_version=0.2.0"
)


def load_json(path):
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def case_payload(case):
    if "payload_ascii" in case:
        return case["payload_ascii"].encode("ascii")
    return bytes.fromhex(case["payload_hex"])


def frame(ver, type_, opcode, id_, payload=b""):
    payload = bytes(payload)
    head = bytes((ver, type_, opcode, id_)) + len(payload).to_bytes(2, "little")
    body = head + payload
    return body + (zlib.crc32(body) & 0xFFFFFFFF).to_bytes(4, "little")


def vector_frame(case):
    if "raw_hex" in case:
        return bytes.fromhex(case["raw_hex"])
    spec = case["frame"]
    value = frame(
        spec["ver"], spec["type"], spec["opcode"], spec["id"],
        bytes.fromhex(spec.get("payload_hex", "")),
    )
    if spec.get("corrupt_crc"):
        value = value[:-1] + bytes((value[-1] ^ 1,))
    return value


class PortableLabelCorpusTest(unittest.TestCase):
    def test_portable_validator_consumes_every_shared_byte_vector(self):
        corpus = load_json(LABEL_CORPUS)
        self.assertEqual(24, corpus["constants"]["label_max_bytes"])
        validator = DC.attr(
            self, "label_status", "v0.6.1 shared strict label validator")
        for case in corpus["cases"]:
            with self.subTest(case=case["name"]):
                self.assertEqual(
                    case["expected_status"],
                    validator(bytes.fromhex(case["payload_hex"])),
                )


class CompiledNativeWireTest(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.sessions = load_json(SESSION_CORPUS)
        self.labels = load_json(LABEL_CORPUS)
        self.temp = tempfile.TemporaryDirectory(prefix="pyble-v061-wire-")
        self.addCleanup(self.temp.cleanup)
        self._binary = None

    def build_harness(self):
        if self._binary is not None:
            return self._binary
        source = NATIVE / "pble_wire.c"
        header = NATIVE / "pble_wire.h"
        self.assertTrue(
            source.is_file() and header.is_file(),
            "D11 requires dependency-free production pble_wire.c/.h shared "
            "by firmware and the compiled host harness",
        )
        compiler = shutil.which(os.environ.get("CC", "cc"))
        self.assertIsNotNone(
            compiler, "a host C compiler is required for pble_wire parity")
        binary = Path(self.temp.name) / "v061_pble_wire_harness"
        built = subprocess.run(
            [
                compiler,
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pedantic",
                "-I",
                str(NATIVE),
                str(HARNESS),
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
            0, built.returncode,
            "pble_wire must compile as standard C without ESP-IDF, FreeRTOS, "
            "MicroPython, or test-only dependencies:\n{}".format(built.stderr),
        )
        self._binary = binary
        return binary

    def run_harness(self, commands):
        binary = self.build_harness()
        result = subprocess.run(
            [str(binary)],
            input="\n".join(commands) + "\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(
            0, result.returncode,
            "compiled pble_wire harness failed:\n{}".format(result.stderr),
        )
        return [line.split() for line in result.stdout.splitlines()]

    def assert_frame_line(self, parts, expected, violation, negotiated,
                          commit=False):
        self.assertEqual("FRAME", parts[0])
        self.assertEqual(expected["action"], parts[1])
        self.assertEqual(8, len(parts))
        values = tuple(int(value) for value in parts[2:])
        opcode, id_, status, got_violation, got_commit, got_negotiated = values
        if "opcode" in expected:
            self.assertEqual(expected["opcode"], opcode)
        if "id" in expected:
            self.assertEqual(expected["id"], id_)
        if "status" in expected:
            self.assertEqual(expected["status"], status)
        self.assertEqual(int(violation), got_violation)
        self.assertEqual(int(commit), got_commit)
        self.assertEqual(int(negotiated), got_negotiated)

    def test_dependency_free_native_label_corpus_matches_portable_contract(self):
        commands = [
            "LABEL {}".format(case["payload_hex"] or "-")
            for case in self.labels["cases"]
        ]
        output = self.run_harness(commands)
        self.assertEqual(len(commands), len(output))
        for case, parts in zip(self.labels["cases"], output):
            with self.subTest(case=case["name"]):
                self.assertEqual(
                    ["LABEL", str(case["expected_status"])], parts)

    def test_native_hello_and_guard_use_the_shared_session_corpus(self):
        self.build_harness()
        for request_id, case in enumerate(
                self.sessions["hello_cases"], start=1):
            with self.subTest(hello=case["name"]):
                request = frame(
                    1, CMD, HELLO, request_id, case_payload(case))
                output = self.run_harness([
                    "RESET",
                    "FRAME 1 {}".format(request.hex()),
                ])
                self.assertEqual(["RESET", "0"], output[0])
                self.assert_frame_line(
                    output[1],
                    {
                        "action": "rsp",
                        "opcode": HELLO,
                        "id": request_id,
                        "status": case["expected_status"],
                    },
                    bool(case["violation_delta"]),
                    case["negotiates_v1"],
                    commit=case["negotiates_v1"],
                )

        for case in self.sessions["inbound_cases"]:
            with self.subTest(frame=case["name"]):
                commands = ["RESET"]
                if case["initial_state"] == "negotiated":
                    hello = frame(1, CMD, HELLO, 250, CANONICAL_HELLO)
                    commands.append("FRAME 1 {}".format(hello.hex()))
                commands.append("FRAME 1 {}".format(vector_frame(case).hex()))
                output = self.run_harness(commands)
                target = output[-1]
                self.assert_frame_line(
                    target,
                    case["guard"],
                    bool(case["violation_delta"]),
                    case["initial_state"] == "negotiated",
                )

    def test_native_repeat_failure_publication_and_reset_semantics(self):
        self.build_harness()
        hello_by_name = {
            case["name"]: case for case in self.sessions["hello_cases"]
        }
        expected_final_state = {
            "compatible_repeat_is_idempotent": True,
            "failed_repeat_preserves_negotiated_state": True,
            "malformed_repeat_preserves_negotiated_state": True,
            "disconnect_and_reconnect_clear_negotiation": False,
            "unpublished_hello_does_not_negotiate": False,
        }
        for sequence in self.sessions["session_sequences"]:
            commands = ["RESET"]
            for step in sequence["steps"]:
                if step["action"] == "reconnect":
                    commands.append("RESET")
                    continue
                if step["action"] == "hello":
                    payload = case_payload(hello_by_name[step["case"]])
                    request = frame(1, CMD, HELLO, step["id"], payload)
                else:
                    request = frame(1, CMD, step["opcode"], step["id"])
                published = 1 if step.get("accept_send", True) else 0
                commands.append(
                    "FRAME {} {}".format(published, request.hex()))

            with self.subTest(sequence=sequence["name"]):
                output = self.run_harness(commands)
                self.assertEqual(
                    int(expected_final_state[sequence["name"]]),
                    int(output[-1][-1]),
                    "repeat failure or reset changed the wrong session state",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
