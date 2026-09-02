#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED host contract for PBLE/1 v0.6.1 negotiation/session hardening.

This suite deliberately drives the public portable ``Agent``/``BleLink`` seam
instead of pinning a particular parser or state-machine class.  The same exact
semantic inputs live in ``conformance/v061_session_vectors.json`` so the native
C harness and Dart client tests can consume them without re-authoring bytes.

Expected RED baseline (firmware v0.6.0): HELLO payloads are ignored, every
opcode can dispatch before HELLO, valid RSP/EVT and CMD-id-0 inputs dispatch as
commands, and disconnect does not clear a negotiation state that does not yet
exist.  CRC -> EVT ECRC already passes on the portable implementation and is
kept here to pin validation precedence while the surrounding gates turn red.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

_support._inject_micropython_guards()
try:
    import importlib as _importlib

    if "micropython" not in sys.modules:
        sys.modules["micropython"] = _importlib.import_module("micropython")
except ImportError:
    pass

import pyble_proto  # noqa: E402

AGENT = _support.RedReason("pyble_agent", owner="protocol-engineer")

HERE = os.path.dirname(os.path.abspath(__file__))
VECTORS_PATH = os.path.join(HERE, "conformance", "v061_session_vectors.json")

CMD = 0x01
RSP = 0x02
EVT = 0x03
HELLO = 0x01
DEVICE_INFO = 0x02
CONSOLE_INPUT = 0x31
OK = 0x00
EBADREQ = 0x01
ECRC = 0x08
ERANGE = 0x09
EUNSUPPORTED = 0x0A

CANONICAL_HELLO = (
    b"proto_versions=1\n"
    b"app_name=PyBLE\n"
    b"app_version=0.2.0"
)


def load_vectors():
    with open(VECTORS_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def payload_bytes(case):
    has_ascii = "payload_ascii" in case
    has_hex = "payload_hex" in case
    if has_ascii == has_hex:
        raise AssertionError(
            "{} must carry exactly one of payload_ascii/payload_hex".format(
                case.get("name", "vector")))
    if has_ascii:
        return case["payload_ascii"].encode("ascii")
    return bytes.fromhex(case["payload_hex"])


def oracle_frame(ver, type_, opcode, id_, payload=b""):
    """Build a frame independently of the production encoder, including VER2."""
    payload = bytes(payload)
    head = bytes((ver, type_, opcode, id_)) + len(payload).to_bytes(2, "little")
    body = head + payload
    return body + (zlib.crc32(body) & 0xFFFFFFFF).to_bytes(4, "little")


def vector_frame(case):
    if "raw_hex" in case:
        return bytes.fromhex(case["raw_hex"])
    spec = case["frame"]
    msg = oracle_frame(
        spec["ver"], spec["type"], spec["opcode"], spec["id"],
        bytes.fromhex(spec.get("payload_hex", "")))
    if spec.get("corrupt_crc"):
        msg = msg[:-1] + bytes((msg[-1] ^ 0x01,))
    return msg


class RecordingLink:
    """Records only the portable Agent's already-public link boundary."""

    def __init__(self):
        self.sent = []
        self.accept_send = True
        self.message_cb = None
        self.connect_cb = None
        self.disconnect_cb = None
        self.oversize_cb = None
        self.info_payload = None
        self.adv_name = None
        self.session = 1
        self.terminations = []
        self.violation_count = 0
        self.closed = False

    def on_message(self, cb):
        self.message_cb = cb

    def on_connect(self, cb):
        self.connect_cb = cb

    def on_disconnect(self, cb):
        self.disconnect_cb = cb

    def on_oversize(self, cb):
        self.oversize_cb = cb

    def session_token(self):
        return self.session

    def send_message(self, msg, on_published=None, expected_session=None):
        if expected_session is not None and expected_session != self.session:
            return False
        if not self.accept_send:
            return False
        self.sent.append(bytes(msg))
        if on_published is not None:
            on_published()
        return True

    def terminate_session(self, expected_session=None):
        if expected_session is not None and expected_session != self.session:
            return False
        if not self.closed:
            self.closed = True
            self.terminations.append(self.session)
        return True

    def record_protocol_violation(self, expected_session=None):
        """Fake only the link-owned bounded counter, never frame classification.

        Production ``Agent`` remains responsible for deciding whether one input
        is a violation and calling this seam *before* publishing its reply.  The
        real BleLink counter/termination behavior is independently exercised by
        test_v061_reassembly_hardening.py.
        """
        if expected_session is not None and expected_session != self.session:
            return False
        if self.closed:
            return False
        self.violation_count += 1
        if self.violation_count >= 8:
            self.terminate_session(expected_session)
            return False
        return True

    def reconnect(self):
        self.session += 1
        self.violation_count = 0
        self.closed = False

    def trigger_oversize(self, head):
        """Model BleLink's link-owned debit-before-upcall ordering only.

        Frame classification and response construction remain production Agent
        behavior. The real portable BleLink's oversize detection, tail
        suppression, and identical budget cut are tested separately.
        """
        if self.record_protocol_violation(self.session):
            self.oversize_cb(bytes(head))

    def set_info_payload(self, payload):
        self.info_payload = bytes(payload)

    def set_adv_name(self, name):
        self.adv_name = name

    def mtu(self):
        return 247

    def mac(self):
        return b"\x00" * 6


class ProtocolSessionContractTest(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.vectors = load_vectors()
        self.root = tempfile.mkdtemp(prefix="pyble_v061_session_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.now = [0]

    def new_agent(self):
        cls = AGENT.attr(
            self, "Agent", "v0.6.1 HELLO/session observable contract")
        link = RecordingLink()
        agent = cls(
            link,
            self.root,
            unique_id=b"\x12\x34\x56\x78\x9a\xbc\x9f\x3a",
            reset=lambda: None,
            clock=lambda: self.now[0],
        )
        self.assertIsNotNone(link.message_cb, "Agent must bind on_message")
        self.assertIsNotNone(link.connect_cb, "Agent must bind on_connect")
        self.assertIsNotNone(link.disconnect_cb, "Agent must bind on_disconnect")
        link.connect_cb()
        return agent, link

    def send(self, link, msg):
        link.message_cb(bytes(msg))

    def negotiate(self, link, id_=250):
        link.sent[:] = []
        self.send(link, oracle_frame(1, CMD, HELLO, id_, CANONICAL_HELLO))
        self.assertEqual(1, len(link.sent), "canonical HELLO must produce one RSP")
        rsp = pyble_proto.decode(link.sent[0])
        self.assertEqual((RSP, HELLO, id_, OK),
                         (rsp.type, rsp.opcode, rsp.id, rsp.payload[0]))
        link.sent[:] = []

    def assert_wire(self, link, expected, context):
        kind = expected["wire"]
        if kind == "none":
            self.assertEqual([], link.sent, context + ": expected no wire output")
            return

        self.assertEqual(
            1, len(link.sent), context + ": expected exactly one output frame")
        frame = pyble_proto.decode(link.sent[0])
        expected_type = RSP if kind == "rsp" else EVT
        self.assertEqual(expected_type, frame.type, context + ": TYPE")
        self.assertEqual(expected["opcode"], frame.opcode, context + ": OPCODE")
        self.assertEqual(expected["id"], frame.id, context + ": ID")
        self.assertTrue(frame.payload, context + ": status byte missing")
        self.assertEqual(expected["status"], frame.payload[0], context + ": status")
        if expected["status"] != OK:
            self.assertEqual(
                bytes((expected["status"],)), bytes(frame.payload),
                context + ": refusal must be status-only")

    def test_shared_corpus_pins_bounds_and_current_app_bytes(self):
        constants = self.vectors["constants"]
        self.assertEqual(1, constants["protocol_version"])
        self.assertEqual(192, constants["hello_max_bytes"])
        self.assertEqual(8, constants["hello_max_offers"])
        self.assertEqual(32, constants["hello_key_max_bytes"])
        self.assertEqual(32, constants["hello_value_max_bytes"])
        self.assertEqual(32, constants["hello_app_field_max_bytes"])
        self.assertEqual(5000, constants["rx_reassembly_deadline_ms"])
        self.assertEqual(8, constants["session_violation_limit"])

        cases = {c["name"]: c for c in self.vectors["hello_cases"]}
        self.assertEqual(
            CANONICAL_HELLO, payload_bytes(cases["canonical_current_app"]))
        self.assertEqual(193, len(payload_bytes(cases["payload_193_bytes"])))
        self.assertEqual(
            {"unnegotiated", "negotiated"},
            {c["initial_state"] for c in self.vectors["inbound_cases"]})

    def test_hello_request_semantic_vectors(self):
        for index, case in enumerate(self.vectors["hello_cases"], start=1):
            with self.subTest(case=case["name"]):
                _, link = self.new_agent()
                request_id = index
                self.send(
                    link,
                    oracle_frame(1, CMD, HELLO, request_id, payload_bytes(case)),
                )
                self.assertEqual(1, len(link.sent), "HELLO must get one response")
                rsp = pyble_proto.decode(link.sent[0])
                self.assertEqual((RSP, HELLO, request_id),
                                 (rsp.type, rsp.opcode, rsp.id))
                self.assertTrue(rsp.payload, "HELLO response lacks status")
                self.assertEqual(case["expected_status"], rsp.payload[0])
                if case["expected_status"] == OK:
                    self.assertIn(b"proto=1\n", bytes(rsp.payload[1:]))
                else:
                    self.assertEqual(
                        bytes((case["expected_status"],)), bytes(rsp.payload),
                        "failed HELLO is status-only and cannot expose caps")
                self.assertEqual(
                    case["violation_delta"], link.violation_count,
                    "HELLO semantic classification must update the one "
                    "link-owned session budget exactly once")

    def test_only_successful_hello_opens_the_session(self):
        for index, case in enumerate(self.vectors["hello_cases"], start=30):
            with self.subTest(case=case["name"]):
                _, link = self.new_agent()
                self.send(
                    link,
                    oracle_frame(1, CMD, HELLO, index, payload_bytes(case)),
                )
                link.sent[:] = []
                self.send(link, oracle_frame(1, CMD, DEVICE_INFO, index + 40))
                self.assertEqual(1, len(link.sent))
                rsp = pyble_proto.decode(link.sent[0])
                expected = OK if case["negotiates_v1"] else EBADREQ
                self.assertEqual(
                    expected, rsp.payload[0],
                    "only HELLO RSP OK publication may open command admission")

    def test_inbound_direction_id_crc_and_session_precedence_vectors(self):
        for case in self.vectors["inbound_cases"]:
            with self.subTest(case=case["name"]):
                agent, link = self.new_agent()
                if case["initial_state"] == "negotiated":
                    self.negotiate(link)
                else:
                    link.sent[:] = []

                self.send(link, vector_frame(case))
                self.assert_wire(link, case["expected"], case["name"])
                self.assertEqual(
                    case["violation_delta"], link.violation_count,
                    case["name"] + ": violation delta")

                if case["expected"].get("effect") == "console_input_empty":
                    buf = bytearray(1)
                    self.assertIsNone(
                        agent.console.readinto(buf),
                        "pre-HELLO CONSOLE_INPUT must not reach the stdin ring")

    def test_repeat_disconnect_and_publication_cut_sequences(self):
        hello_by_name = {
            case["name"]: case for case in self.vectors["hello_cases"]
        }
        for sequence in self.vectors["session_sequences"]:
            with self.subTest(sequence=sequence["name"]):
                _, link = self.new_agent()
                for step_index, step in enumerate(sequence["steps"]):
                    link.sent[:] = []
                    action = step["action"]
                    if action == "reconnect":
                        link.disconnect_cb()
                        link.reconnect()
                        link.connect_cb()
                        continue

                    link.accept_send = step.get("accept_send", True)
                    if action == "hello":
                        hello = hello_by_name[step["case"]]
                        msg = oracle_frame(
                            1, CMD, HELLO, step["id"], payload_bytes(hello))
                        opcode = HELLO
                    elif action == "command":
                        opcode = step["opcode"]
                        msg = oracle_frame(1, CMD, opcode, step["id"])
                    else:
                        self.fail("unknown sequence action {!r}".format(action))

                    self.send(link, msg)
                    expected = {"wire": step["wire"]}
                    if step["wire"] != "none":
                        expected.update({
                            "opcode": opcode,
                            "id": step["id"],
                            "status": step["status"],
                        })
                    self.assert_wire(
                        link, expected,
                        "{} step {}".format(sequence["name"], step_index))
                    link.accept_send = True

    def test_eighth_violation_closes_before_reply_and_terminates_once(self):
        case = self.vectors["violation_budget_case"]
        _, link = self.new_agent()
        frame_spec = case["frame"]

        for offset in range(case["responses_before_limit"]):
            request_id = case["first_id"] + offset
            link.sent[:] = []
            self.send(link, oracle_frame(
                frame_spec["ver"], frame_spec["type"], frame_spec["opcode"],
                request_id, bytes.fromhex(frame_spec["payload_hex"])))
            self.assertEqual([], link.terminations)
            self.assert_wire(link, {
                "wire": "rsp",
                "opcode": frame_spec["opcode"],
                "id": request_id,
                "status": case["response_status_before_limit"],
            }, "violation {} before limit".format(offset + 1))

        eighth_id = case["first_id"] + case["responses_before_limit"]
        link.sent[:] = []
        self.send(link, oracle_frame(
            frame_spec["ver"], frame_spec["type"], frame_spec["opcode"],
            eighth_id, bytes.fromhex(frame_spec["payload_hex"])))
        self.assertEqual([], link.sent, "eighth violation must suppress its RSP")
        self.assertEqual(
            case["termination_count_at_limit"], len(link.terminations),
            "eighth violation must terminate the exact session once")

        link.sent[:] = []
        self.send(link, oracle_frame(
            frame_spec["ver"], frame_spec["type"], frame_spec["opcode"],
            eighth_id + 1, bytes.fromhex(frame_spec["payload_hex"])))
        self.assertEqual([], link.sent, "closed session must remain reply-silent")
        self.assertEqual(
            case["termination_count_after_limit"], len(link.terminations),
            "closed-session repeats must not invoke termination twice")

    def test_oversize_reply_requires_a_safely_correlatable_header(self):
        _, link = self.new_agent()
        self.assertIsNotNone(link.oversize_cb, "Agent must bind on_oversize")

        unsafe = (
            b"\x01\x01\x20\x2a",              # no complete six-byte header
            b"\x02\x01\x20\x2a\x00\x00",  # unsupported VER
            b"\x01\x02\x20\x2a\x00\x00",  # inbound RSP
            b"\x01\x03\x20\x2a\x00\x00",  # inbound EVT
            b"\x01\x01\x20\x00\x00\x00",  # request ID zero
        )
        for head in unsafe:
            with self.subTest(head=head.hex()):
                link.sent[:] = []
                link.trigger_oversize(head)
                self.assertEqual(
                    [], link.sent,
                    "unsafe oversize header cannot be echoed as a response")

        link.sent[:] = []
        link.trigger_oversize(b"\x01\x01\x20\x2a\x00\x00")
        self.assert_wire(link, {
            "wire": "rsp", "opcode": 0x20, "id": 0x2A, "status": ERANGE,
        }, "safely correlated oversize")
        self.assertEqual(6, link.violation_count)

    def test_eighth_oversize_suppresses_erange_before_termination(self):
        _, link = self.new_agent()
        safe = b"\x01\x01\x20\x2a\x00\x00"

        for _ in range(7):
            link.sent[:] = []
            link.trigger_oversize(safe)
            self.assert_wire(link, {
                "wire": "rsp", "opcode": 0x20, "id": 0x2A,
                "status": ERANGE,
            }, "oversize before budget limit")
        self.assertEqual([], link.terminations)

        link.sent[:] = []
        link.trigger_oversize(safe)
        self.assertEqual([], link.sent)
        self.assertEqual([1], link.terminations)

        link.trigger_oversize(safe)
        self.assertEqual([], link.sent)
        self.assertEqual([1], link.terminations)


if __name__ == "__main__":
    unittest.main(verbosity=2)
