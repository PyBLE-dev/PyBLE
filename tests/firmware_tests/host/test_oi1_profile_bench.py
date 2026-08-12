# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Host-only contract tests for the frozen OI-1 profile HIL bench.  All BLE,
# reset, clock, and file inputs are fakes; no board or serial adapter is used.

import argparse
import asyncio
import copy
import errno
import hashlib
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
HIL_DIR = HERE.parent / "hil"
sys.path.insert(0, str(HIL_DIR))

import _pble_bench as bench  # noqa: E402
from _pble_central import PbleCentral  # noqa: E402
import _pble_wire as wire  # noqa: E402
import oi1_profile_bench as profile_bench  # noqa: E402


PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
    "waveshare-esp32-s3-lcd-147b",
)
HISTORICAL_V042_PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
)
PROFILE_TARGETS = {
    "esp32-4mb": "esp32",
    "esp32-s3-n16r8": "esp32-s3",
    "waveshare-esp32-s3-lcd-147b": "waveshare-esp32-s3-lcd-147b",
}
PROFILE_CHIPS = {
    "esp32-4mb": "esp32",
    "esp32-s3-n16r8": "esp32-s3",
    "waveshare-esp32-s3-lcd-147b": "esp32-s3",
}
POLICY_TARGETS = {
    "esp32-4mb": "esp32",
    "esp32-s3-n16r8": "esp32-s3",
    "waveshare-esp32-s3-lcd-147b": "waveshare-esp32-s3-lcd-147b",
}
THRESHOLD_KEYS = {
    "application_headroom_min_bytes",
    "application_image_max_bytes",
    "gc_free_min_bytes",
    "get_verified_goodput_min_bytes_per_second",
    "idf_internal_free_min_bytes",
    "idf_internal_largest_block_min_bytes",
    "idf_internal_minimum_free_min_bytes",
    "put_committed_goodput_min_bytes_per_second",
    "reset_to_service_advertisement_max_ms",
}
HEAP_KEYS = {
    "gc_free_bytes",
    "gc_allocated_bytes",
    "idf_internal_free_bytes",
    "idf_internal_largest_block_bytes",
    "idf_internal_minimum_free_bytes",
}
OBSERVATION_KEYS = {
    "observed_att_mtu",
    "observed_window",
    "observed_chunk_bytes",
    "reset_to_service_advertisement_ms",
    "heap_default_free_post_hello_bytes",
    "heap_post_hello",
    "put_unique_committed_bytes",
    "put_duration_ns",
    "put_committed_goodput_bytes_per_second",
    "get_unique_verified_bytes",
    "get_duration_ns",
    "get_verified_goodput_bytes_per_second",
    "put_retransmitted_chunks",
    "put_retransmitted_bytes",
    "get_retransmitted_chunks",
    "get_retransmitted_bytes",
    "roundtrip_integrity_verified",
    "get_offset_sequences_validated",
    "roundtrip_unexpected_disconnects",
    "roundtrip_integrity_failures",
    "heap_post_roundtrip",
    "reliability",
    "heap_post_reliability",
    "transfer_link_facts",
    "physical_power_cycle_advertising",
    "raw_log_sha256",
}


def _partition_entry(part_type, subtype, offset, size, label):
    return struct.pack(
        "<HBBII16sI",
        0x50AA,
        part_type,
        subtype,
        offset,
        size,
        label.encode("ascii").ljust(16, b"\0"),
        0,
    )


def _partition_table(factory_size=0x1F0000, *, duplicate_factory=False):
    entries = [
        _partition_entry(1, 2, 0x9000, 0x6000, "nvs"),
        _partition_entry(0, 0, 0x10000, factory_size, "factory"),
        _partition_entry(1, 0x81, 0x200000, 0x200000, "vfs"),
    ]
    if duplicate_factory:
        entries.append(_partition_entry(0, 0, 0x400000, 0x100000, "factory2"))
    encoded = b"".join(entries)
    md5_record = b"\xeb\xeb" + b"\xff" * 14 + hashlib.md5(encoded).digest()  # nosec
    return (encoded + md5_record).ljust(0xC00, b"\xff")


def _heap(
        gc_free=9001,
        gc_allocated=1000,
        internal_free=17001,
        largest=9001,
        minimum=5001):
    return {
        "gc_free_bytes": gc_free,
        "gc_allocated_bytes": gc_allocated,
        "idf_internal_free_bytes": internal_free,
        "idf_internal_largest_block_bytes": largest,
        "idf_internal_minimum_free_bytes": minimum,
    }


def _transfer_link_facts(profile_id):
    """One strict ADR-0027 fact object for the requested exact profile."""
    if profile_id == "esp32-4mb":
        phy = {
            "required_2m": False,
            "request_attempts": 0,
            "updates": [],
            "settled_tx": 0,
            "settled_rx": 0,
        }
        connection_parameters = {
            "request_return_codes": [0],
            "updates": [{"status": 0, "interval_units": 24}],
            "settled_interval_units": 24,
        }
    elif profile_id in (
        "esp32-s3-n16r8",
        "waveshare-esp32-s3-lcd-147b",
    ):
        phy = {
            "required_2m": True,
            "request_attempts": 2,
            "updates": [
                {"status": 26, "tx": 1, "rx": 1},
                {"status": 0, "tx": 2, "rx": 2},
            ],
            "settled_tx": 2,
            "settled_rx": 2,
        }
        connection_parameters = {
            "request_return_codes": [530, 0],
            "updates": [
                {"status": 554, "interval_units": 40},
                {"status": 0, "interval_units": 12},
            ],
            "settled_interval_units": 12,
        }
    else:
        raise AssertionError("test fixture received an unsupported profile")
    return {
        "dle": {
            "request_attempts": 2,
            "max_tx_octets": 251,
            "max_tx_time_us": 2120,
        },
        "phy": phy,
        "connection_parameters": connection_parameters,
        "tx_mbuf_starve_count": 3,
    }


def _valid_observation(profile_id):
    heap = _heap()
    durations = [1_000_000_000] * 5
    return {
        "observed_att_mtu": 247,
        "observed_window": 8,
        "observed_chunk_bytes": 229,
        "reset_to_service_advertisement_ms": [100] * 10,
        "heap_default_free_post_hello_bytes": [16_384] * 10,
        "heap_post_hello": [copy.deepcopy(heap) for _ in range(10)],
        "put_unique_committed_bytes": [65_536] * 5,
        "put_duration_ns": durations,
        "put_committed_goodput_bytes_per_second": [65_536] * 5,
        "get_unique_verified_bytes": [65_536] * 5,
        "get_duration_ns": durations,
        "get_verified_goodput_bytes_per_second": [65_536] * 5,
        "put_retransmitted_chunks": [0] * 5,
        "put_retransmitted_bytes": [0] * 5,
        "get_retransmitted_chunks": [0] * 5,
        "get_retransmitted_bytes": [0] * 5,
        "roundtrip_integrity_verified": 5,
        "get_offset_sequences_validated": 5,
        "roundtrip_unexpected_disconnects": 0,
        "roundtrip_integrity_failures": 0,
        "heap_post_roundtrip": [copy.deepcopy(heap) for _ in range(5)],
        "reliability": {
            "attempted_files": 20,
            "completed_files": 20,
            "verified_files": 20,
            "bytes_per_file": 16_384,
            "total_payload_bytes": 327_680,
            "unexpected_disconnects": 0,
            "integrity_failures": 0,
            "failed_statuses": 0,
            "retransmitted_chunks": 0,
            "retransmitted_bytes": 0,
            "rewinds": 0,
        },
        "heap_post_reliability": copy.deepcopy(heap),
        "transfer_link_facts": _transfer_link_facts(profile_id),
        "physical_power_cycle_advertising": "passed",
        "raw_log_sha256": "4" * 64,
    }


class FrozenConstantsTest(unittest.TestCase):
    def test_exact_v051_candidate_profiles_and_workload_are_frozen(self):
        self.assertEqual(tuple(bench.PROFILE_ORDER), PROFILE_ORDER)
        self.assertEqual(
            bench.PROFILE_TARGETS,
            PROFILE_TARGETS,
        )
        self.assertEqual(bench.PROFILE_CHIPS, PROFILE_CHIPS)
        self.assertEqual(
            bench.WORKLOAD,
            {
                "reset_samples": 10,
                "reset_hold_ms": 1000,
                "advertising_timeout_ms": 15000,
                "post_hello_heap_samples": 10,
                "roundtrip_samples": 5,
                "roundtrip_payload_bytes": 65536,
                "payload_generator": "sha256-counter-v1",
                "post_roundtrip_heap_samples": 5,
                "reliability_files": 20,
                "reliability_file_bytes": 16384,
                "post_reliability_heap_samples": 1,
                "required_att_mtu": 247,
                "required_put_window": 8,
                "required_chunk_bytes": 229,
            },
        )
        self.assertEqual(
            bench.DERIVATION,
            {
                "application_image": "exact-byte-identical-two-root-v1",
                "application_headroom": "factory-minus-application-v1",
                "heap_floor": "floor-min-1024-v1",
                "boot_ceiling": "fixed-product-slo-3000-v3",
                "goodput_floor": "floor-95pct-min-100-v2",
            },
        )

    def test_committed_v042_policy_remains_immutable_two_profile_evidence(self):
        policy_path = (
            REPO_ROOT / "firmware" / "qualification" / "oi1-gates.json"
        )
        payload = policy_path.read_bytes()
        policy = json.loads(payload.decode("utf-8"))

        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "635c484501bc0b81806f9f582de4b482d30283a72f5f95eb0b892652f7575629",
        )
        self.assertEqual(policy["schema_version"], 1)
        self.assertEqual(
            policy["profile_order"],
            list(HISTORICAL_V042_PROFILE_ORDER),
        )
        self.assertEqual(
            [entry["profile_id"] for entry in policy["profiles"]],
            list(HISTORICAL_V042_PROFILE_ORDER),
        )
        self.assertEqual(
            {
                entry["profile_id"]: entry["target"]
                for entry in policy["profiles"]
            },
            {
                "esp32-4mb": "esp32",
                "esp32-s3-n16r8": "esp32-s3",
            },
        )
        self.assertEqual(
            policy["baseline_evidence"],
            {
                "path": (
                    "docs/validation/firmware/oi1/"
                    "2f38c43838b0f8cfbd10fab8e6561ae523927968.json"
                ),
                "sha256": (
                    "deee0f1630c781ee38a9887a5df5388f2d1ec8879fdb8570"
                    "886555bf5f4f8be5"
                ),
            },
        )

    def test_v051_three_profile_policy_contract_uses_synthetic_evidence(self):
        synthetic_thresholds = {
            profile_id: {
                key: profile_index * 100 + key_index
                for key_index, key in enumerate(sorted(THRESHOLD_KEYS), start=1)
            }
            for profile_index, profile_id in enumerate(PROFILE_ORDER, start=1)
        }
        policy = {
            "schema_version": 2,
            "qualification_scope": "pre-v1",
            "profile_order": list(PROFILE_ORDER),
            "deferred_profiles": ["esp32-c3-4mb"],
            "workload": bench.WORKLOAD,
            "derivation": bench.DERIVATION,
            "baseline_evidence": {
                "path": "synthetic-v0.5.1-evidence.json",
                "sha256": "0" * 64,
            },
            "profiles": [
                {
                    "profile_id": profile_id,
                    "target": POLICY_TARGETS[profile_id],
                    "thresholds": synthetic_thresholds[profile_id],
                }
                for profile_id in PROFILE_ORDER
            ],
        }

        with tempfile.TemporaryDirectory() as temporary:
            policy_path = Path(temporary) / "oi1-gates-v0.5.1-synthetic.json"
            policy_path.write_bytes(bench.canonical_json_bytes(policy))
            for profile_id in PROFILE_ORDER:
                with self.subTest(profile_id=profile_id):
                    self.assertEqual(
                        profile_bench._load_policy_thresholds(
                            policy_path,
                            profile_id,
                        ),
                        synthetic_thresholds[profile_id],
                    )

        for entry in policy["profiles"]:
            with self.subTest(profile_id=entry["profile_id"]):
                thresholds = entry["thresholds"]
                self.assertEqual(set(thresholds), THRESHOLD_KEYS)
                self.assertTrue(
                    all(
                        type(value) is int and value > 0
                        for value in thresholds.values()
                    )
                )

    def test_sha256_counter_payload_is_byte_exact_and_deterministic(self):
        payload = bench.deterministic_payload("esp32-4mb", 0, 65536)
        self.assertEqual(len(payload), 65536)
        self.assertEqual(
            payload[:32].hex(),
            "8cbe43aac4424c5d2375f33c919769cf"
            "86647fc8eb071d7c6e0117fffe08b7ad",
        )
        self.assertEqual(payload, bench.deterministic_payload("esp32-4mb", 0, 65536))
        self.assertNotEqual(
            payload,
            bench.deterministic_payload("esp32-s3-n16r8", 0, 65536),
        )
        waveshare = bench.deterministic_payload(
            "waveshare-esp32-s3-lcd-147b", 0, 65536
        )
        self.assertNotEqual(payload, waveshare)
        self.assertNotEqual(
            waveshare,
            bench.deterministic_payload("esp32-s3-n16r8", 0, 65536),
        )
        with self.assertRaises(ValueError):
            bench.deterministic_payload("esp32-c3-4mb", 0, 65536)


class LinkFactParserRedTests(unittest.TestCase):
    """Freeze the pure, identifier-free ADR-0027 UART parser API and grammar."""

    def parser(self, profile_id):
        parser_type = getattr(profile_bench, "LinkFactParser", None)
        self.assertTrue(
            callable(parser_type),
            "HAND-OFF HIL [green]: add LinkFactParser(profile_id)",
        )
        return parser_type(profile_id)

    @staticmethod
    def line(payload):
        # ESP_LOG's timestamp/tag prefix is transport framing; only the exact
        # payload grammar below may enter retained evidence.
        return "E (1234) pyble: " + payload

    def feed(self, parser, *payloads):
        for payload in payloads:
            self.assertTrue(parser.feed_line(self.line(payload)))

    def test_both_s3_parsers_preserve_order_and_seal_after_session_end(self):
        for profile_id in (
            "esp32-s3-n16r8",
            "waveshare-esp32-s3-lcd-147b",
        ):
            with self.subTest(profile_id=profile_id):
                parser = self.parser(profile_id)
                self.assertFalse(
                    parser.feed_line(
                        "I (2) pyble: connected "
                        "address=AA:BB:CC:DD:EE:FF label=private"
                    )
                )
                self.feed(
                    parser,
                    "link tune req phase=dle attempt=1 context=connect rc=530",
                    "link tune req phase=dle attempt=2 context=timer rc=0",
                    "link tune complete phase=dle "
                    "max_tx_octets=251 max_tx_time_us=2120",
                    "link tune req phase=phy attempt=1 context=timer rc=530",
                    "link tune complete phase=phy status=26 tx=1 rx=1",
                    "link tune req phase=phy attempt=2 context=retry rc=0",
                    "link tune complete phase=phy status=0 tx=2 rx=2",
                    "link tune req phase=conn-param attempt=1 context=timer rc=530",
                    "link tune complete phase=conn-param "
                    "status=554 interval_units=40",
                    "link tune req phase=conn-param attempt=2 context=retry rc=0",
                    "link tune complete phase=conn-param "
                    "status=0 interval_units=12",
                )
                parser.require_settled()
                with self.assertRaisesRegex(
                    bench.BenchError, "session end|starve|seal"
                ):
                    parser.seal()
                self.feed(
                    parser,
                    "link tune session end tx_mbuf_starve_count=3",
                )
                self.assertEqual(
                    parser.seal(),
                    _transfer_link_facts(profile_id),
                )

    def test_classic_parser_requires_explicit_compiled_out_phy_fact(self):
        parser = self.parser("esp32-4mb")
        self.feed(
            parser,
            "link tune req phase=dle attempt=1 context=connect rc=530",
            "link tune req phase=dle attempt=2 context=timer rc=0",
            "link tune complete phase=dle max_tx_octets=251 max_tx_time_us=2120",
            "link tune skip phase=phy context=classic-compiled-out",
            "link tune req phase=conn-param attempt=1 context=timer rc=0",
            "link tune complete phase=conn-param status=0 interval_units=24",
            "link tune session end tx_mbuf_starve_count=3",
        )
        parser.require_settled()
        self.assertEqual(parser.seal(), _transfer_link_facts("esp32-4mb"))

    def test_known_prefix_rejects_malformed_or_wrong_profile_records(self):
        cases = (
            (
                "esp32-s3-n16r8",
                "link tune req phase=dle attempt=1 context=UPPER rc=0",
            ),
            (
                "esp32-s3-n16r8",
                "link tune complete phase=dle max_tx_octets=-1 max_tx_time_us=2120",
            ),
            (
                "esp32-s3-n16r8",
                "link tune req phase=dle attempt=2 context=timer rc=0",
            ),
            (
                "esp32-s3-n16r8",
                "link tune req phase=dle attempt=1 context=timer rc=-1",
            ),
            (
                "esp32-s3-n16r8",
                "link tune skip phase=phy context=classic-compiled-out",
            ),
            (
                "esp32-4mb",
                "link tune req phase=phy attempt=1 context=timer rc=0",
            ),
            (
                "esp32-4mb",
                "link tune session end tx_mbuf_starve_count=0 address=private",
            ),
        )
        for profile_id, payload in cases:
            with self.subTest(profile_id=profile_id, payload=payload):
                with self.assertRaises(bench.BenchError):
                    self.parser(profile_id).feed_line(self.line(payload))

    def test_unsettled_and_exhausted_ladders_fail_closed(self):
        unsettled = self.parser("esp32-s3-n16r8")
        self.feed(
            unsettled,
            "link tune req phase=dle attempt=1 context=connect rc=0",
            "link tune complete phase=dle max_tx_octets=251 max_tx_time_us=2120",
        )
        with self.assertRaisesRegex(bench.BenchError, "unsettled"):
            unsettled.require_settled()

        exhausted = self.parser("esp32-s3-n16r8")
        self.feed(
            exhausted,
            *(
                "link tune req phase=dle attempt=%d context=timer rc=530" % attempt
                for attempt in range(1, 5)
            ),
        )
        with self.assertRaisesRegex(bench.BenchError, "exhausted|unsettled"):
            exhausted.require_settled()

        weak_dle = self.parser("esp32-s3-n16r8")
        self.feed(
            weak_dle,
            "link tune req phase=dle attempt=1 context=connect rc=0",
            "link tune complete phase=dle max_tx_octets=243 max_tx_time_us=2120",
        )
        with self.assertRaisesRegex(bench.BenchError, "DLE|dle|unsettled"):
            weak_dle.require_settled()


class HardwareExecutorTransferLinkSerialRedTest(
        unittest.IsolatedAsyncioTestCase):
    async def test_bytearray_uart_lines_settle_classic_without_retaining_noise(self):
        class Reset:
            def __init__(self):
                self.clear_count = 0
                self.chunks = [
                    b"\xff device-id=arbitrary-uart-must-not-be-retained\r\n"
                    b"E (1) pyble: link tune req phase=dle attempt=1 "
                    b"context=connect rc=530\r\n"
                    b"E (2) pyble: link tune req phase=dle attempt=2 "
                    b"context=timer rc=0\r\n"
                    b"E (3) pyble: link tune complete phase=dle "
                    b"max_tx_octets=251 max_tx_time_us=2120\r\n"
                    b"E (4) pyble: link tune skip phase=phy "
                    b"context=classic-compiled-out\r\n"
                    b"E (5) pyble: link tune req phase=conn-param attempt=1 "
                    b"context=timer rc=0\r\n"
                    b"E (6) pyble: link tune complete phase=conn-param "
                    b"status=0 interval_units=24\r\n",
                    b"E (7) pyble: link tune session end "
                    b"tx_mbuf_starve_count=3\r\n",
                ]

            def clear_input_buffer(self):
                self.clear_count += 1

            def read_available(self):
                return self.chunks.pop(0) if self.chunks else b""

        class RawLog:
            def __init__(self):
                self.events = []

            def write(self, event, **values):
                self.events.append((event, values))

        reset = Reset()
        raw_log = RawLog()
        executor = profile_bench.HardwareExecutor(
            argparse.Namespace(), reset, raw_log
        )

        await executor.begin_transfer_link_capture("esp32-4mb")
        await executor.await_transfer_link_settlement(100)
        facts = await executor.seal_transfer_link_facts(100)

        self.assertEqual(facts, _transfer_link_facts("esp32-4mb"))
        self.assertEqual(reset.clear_count, 1)
        retained = json.dumps(raw_log.events, sort_keys=True)
        self.assertNotIn("arbitrary-uart-must-not-be-retained", retained)
        self.assertNotIn("device-id", retained)

    async def test_delayed_pre_capture_terminal_is_consumed_before_capture(self):
        class Reset:
            def __init__(self):
                self.read_count = 0
                self.clear_count = 0
                self.chunks = [
                    b"",
                    b"private-device-id=discard-before-capture\r\n"
                    b"E (0) pyble: link tune session ",
                    b"end tx_mbuf_starve_count=9\r\n",
                    b"E (1) pyble: link tune req phase=dle attempt=1 "
                    b"context=connect rc=530\r\n"
                    b"E (2) pyble: link tune req phase=dle attempt=2 "
                    b"context=timer rc=0\r\n"
                    b"E (3) pyble: link tune complete phase=dle "
                    b"max_tx_octets=251 max_tx_time_us=2120\r\n"
                    b"E (4) pyble: link tune skip phase=phy "
                    b"context=classic-compiled-out\r\n"
                    b"E (5) pyble: link tune req phase=conn-param attempt=1 "
                    b"context=timer rc=0\r\n"
                    b"E (6) pyble: link tune complete phase=conn-param "
                    b"status=0 interval_units=24\r\n",
                    b"E (7) pyble: link tune session end "
                    b"tx_mbuf_starve_count=3\r\n",
                ]

            def clear_input_buffer(self):
                self.clear_count += 1

            def read_available(self):
                self.read_count += 1
                return self.chunks.pop(0) if self.chunks else b""

        class Connection:
            def __init__(self):
                self.disconnect_count = 0

            async def disconnect(self):
                self.disconnect_count += 1

        class RawLog:
            def __init__(self):
                self.events = []

            def write(self, event, **values):
                self.events.append((event, values))

        reset = Reset()
        raw_log = RawLog()
        executor = profile_bench.HardwareExecutor(
            argparse.Namespace(), reset, raw_log
        )
        pre_capture_connection = Connection()

        await executor.disconnect(pre_capture_connection)
        self.assertEqual(pre_capture_connection.disconnect_count, 1)
        self.assertGreaterEqual(reset.read_count, 3)

        await executor.begin_transfer_link_capture("esp32-4mb")
        await executor.await_transfer_link_settlement(100)
        capture_connection = Connection()
        await executor.disconnect(capture_connection)
        facts = await executor.seal_transfer_link_facts(100)

        self.assertEqual(capture_connection.disconnect_count, 1)
        self.assertEqual(reset.clear_count, 2)
        self.assertEqual(facts, _transfer_link_facts("esp32-4mb"))
        retained = json.dumps(raw_log.events, sort_keys=True)
        self.assertNotIn("private-device-id", retained)
        self.assertNotIn("discard-before-capture", retained)

    async def test_missing_pre_capture_terminal_fails_without_private_text(self):
        class Reset:
            def __init__(self):
                self.clear_count = 0

            def clear_input_buffer(self):
                self.clear_count += 1

            def read_available(self):
                return b"private-device-id=must-not-enter-error\r\n"

        class Connection:
            async def disconnect(self):
                return None

        class RawLog:
            def write(self, event, **values):
                return None

        executor = profile_bench.HardwareExecutor(
            argparse.Namespace(), Reset(), RawLog()
        )
        with mock.patch.object(
            profile_bench,
            "PRE_CAPTURE_SESSION_END_TIMEOUT_MS",
            20,
        ):
            with self.assertRaisesRegex(
                bench.BenchError,
                "pre-capture session end",
            ) as raised:
                await executor.disconnect(Connection())
        self.assertNotIn("private-device-id", str(raised.exception))
        self.assertNotIn("must-not-enter-error", str(raised.exception))

    async def test_duplicate_pre_capture_terminal_fails_closed(self):
        terminal = (
            b"E (1) pyble: link tune session end "
            b"tx_mbuf_starve_count=0\r\n"
        )

        class Reset:
            def clear_input_buffer(self):
                return None

            def read_available(self):
                return terminal + terminal

        class Connection:
            async def disconnect(self):
                return None

        class RawLog:
            def write(self, event, **values):
                return None

        executor = profile_bench.HardwareExecutor(
            argparse.Namespace(), Reset(), RawLog()
        )
        with self.assertRaisesRegex(
            bench.BenchError,
            "duplicate pre-capture session end",
        ):
            await executor.disconnect(Connection())


class BuildAndDerivationTest(unittest.TestCase):
    def test_application_and_factory_partition_arithmetic_use_exact_bytes(self):
        application = b"A" * 12345
        result = bench.oi1_build_from_bytes(application, _partition_table())
        self.assertEqual(
            result,
            {
                "application_image_bytes": 12345,
                "factory_partition_bytes": 0x1F0000,
                "application_headroom_bytes": 0x1F0000 - 12345,
            },
        )

    def test_partition_table_requires_one_md5_verified_factory_that_fits(self):
        with self.assertRaises(bench.BenchError):
            bench.oi1_build_from_bytes(
                b"A" * 16, _partition_table(duplicate_factory=True)
            )
        bad_md5 = bytearray(_partition_table())
        bad_md5[3 * 32 + 16] ^= 0x01
        with self.assertRaises(bench.BenchError):
            bench.oi1_build_from_bytes(b"A" * 16, bytes(bad_md5))
        with self.assertRaises(bench.BenchError):
            bench.oi1_build_from_bytes(b"A" * 101, _partition_table(100))

    def test_frozen_metric_specific_threshold_derivation(self):
        post_hello = [
            _heap(9001 + i, 1000, 17001 + i, 9001 + i, 5001 + i)
            for i in range(10)
        ]
        post_roundtrip = [
            _heap(10001 + i, 1000, 18001 + i, 10001 + i, 6001 + i)
            for i in range(5)
        ]
        observation = {
            "reset_to_service_advertisement_ms": [82, 91, 101, 94, 88, 86, 92, 90, 89, 87],
            "heap_post_hello": post_hello,
            "heap_post_roundtrip": post_roundtrip,
            "heap_post_reliability": _heap(11001, 1000, 19001, 11001, 7001),
            "put_committed_goodput_bytes_per_second": [40001, 39001, 38001, 37001, 32768],
            "get_verified_goodput_bytes_per_second": [30001, 29001, 28001, 27001, 16384],
        }
        self.assertEqual(
            bench.derive_thresholds(
                {
                    "application_image_bytes": 123456,
                    "factory_partition_bytes": 200000,
                    "application_headroom_bytes": 76544,
                },
                observation,
            ),
            {
                "application_image_max_bytes": 123456,
                "application_headroom_min_bytes": 76544,
                "gc_free_min_bytes": 8192,
                "idf_internal_free_min_bytes": 16384,
                "idf_internal_largest_block_min_bytes": 8192,
                "idf_internal_minimum_free_min_bytes": 4096,
                "reset_to_service_advertisement_max_ms": 3000,
                "put_committed_goodput_min_bytes_per_second": 31100,
                "get_verified_goodput_min_bytes_per_second": 15500,
            },
        )

    def test_repeatability_allowances_do_not_change_static_or_heap_gates(self):
        heaps = [_heap(135792, 1, 86212, 81920, 86172) for _ in range(16)]
        observation = {
            "reset_to_service_advertisement_ms": [1182] * 9 + [1498],
            "heap_post_hello": heaps[:10],
            "heap_post_roundtrip": heaps[10:15],
            "heap_post_reliability": heaps[15],
            "put_committed_goodput_bytes_per_second": [7612, 7430, 7354, 7558, 7506],
            "get_verified_goodput_bytes_per_second": [13910, 14174, 14086, 14365, 13907],
        }
        thresholds = bench.derive_thresholds(
            {
                "application_image_bytes": 1699936,
                "factory_partition_bytes": 2031616,
                "application_headroom_bytes": 331680,
            },
            observation,
        )
        self.assertEqual(
            thresholds,
            {
                "application_image_max_bytes": 1699936,
                "application_headroom_min_bytes": 331680,
                "gc_free_min_bytes": 135168,
                "idf_internal_free_min_bytes": 86016,
                "idf_internal_largest_block_min_bytes": 81920,
                "idf_internal_minimum_free_min_bytes": 86016,
                "reset_to_service_advertisement_max_ms": 3000,
                "put_committed_goodput_min_bytes_per_second": 6900,
                "get_verified_goodput_min_bytes_per_second": 13200,
            },
        )

        repeat_observation = dict(observation)
        repeat_observation.update(
            {
                "reset_to_service_advertisement_ms": [1170] * 9 + [2378],
                "put_committed_goodput_bytes_per_second": [7208] * 5,
                "get_verified_goodput_bytes_per_second": [13238] * 5,
            }
        )
        repeat_derived = bench.evaluate_thresholds(
            {
                "application_image_bytes": 1699936,
                "factory_partition_bytes": 2031616,
                "application_headroom_bytes": 331680,
            },
            repeat_observation,
            thresholds,
        )
        self.assertEqual(
            repeat_derived["reset_to_service_advertisement_max_ms"],
            3000,
        )
        self.assertEqual(
            repeat_derived[
                "put_committed_goodput_min_bytes_per_second"
            ],
            6800,
        )

    def test_fixed_reset_product_slo_accepts_boundary_and_rejects_above_it(self):
        heaps = [_heap() for _ in range(16)]
        observation = {
            "reset_to_service_advertisement_ms": [1000] * 9 + [3000],
            "heap_post_hello": heaps[:10],
            "heap_post_roundtrip": heaps[10:15],
            "heap_post_reliability": heaps[15],
            "put_committed_goodput_bytes_per_second": [40000] * 5,
            "get_verified_goodput_bytes_per_second": [40000] * 5,
        }
        thresholds = bench.derive_thresholds(
            {
                "application_image_bytes": 100,
                "factory_partition_bytes": 1000,
                "application_headroom_bytes": 900,
            },
            {**observation, "reset_to_service_advertisement_ms": [1000] * 10},
        )
        accepted = bench.evaluate_thresholds(
            {
                "application_image_bytes": 100,
                "factory_partition_bytes": 1000,
                "application_headroom_bytes": 900,
            },
            observation,
            thresholds,
        )
        self.assertEqual(
            accepted["reset_to_service_advertisement_max_ms"],
            3000,
        )
        above_boundary = dict(observation)
        above_boundary["reset_to_service_advertisement_ms"] = list(
            observation["reset_to_service_advertisement_ms"]
        )
        above_boundary["reset_to_service_advertisement_ms"][-1] = 3001
        with self.assertRaisesRegex(
            bench.BenchError,
            "reset_to_service_advertisement_max_ms=3001 exceeds 3000",
        ):
            bench.evaluate_thresholds(
                {
                    "application_image_bytes": 100,
                    "factory_partition_bytes": 1000,
                    "application_headroom_bytes": 900,
                },
                above_boundary,
                thresholds,
            )


class CapsAndMtuTest(unittest.TestCase):
    def test_caps_are_strict_and_transport_values_are_exact(self):
        caps = bench.parse_caps(
            b"chip=esp32-s3\nmtu=247\nwindow=8\nchunk=229\nfree_mem=12345\n"
        )
        observed = bench.validate_oi1_caps(
            caps, expected_chip="esp32-s3", backend_mtu=247
        )
        self.assertEqual(observed, (247, 8, 229, 12345))
        self.assertEqual(
            bench.validate_oi1_caps(
                caps, expected_chip="esp32-s3", backend_mtu=None
            ),
            observed,
        )
        for changed in (
            {**caps, "mtu": "246"},
            {**caps, "window": "7"},
            {**caps, "chunk": "228"},
            {**caps, "chip": "esp32"},
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(bench.BenchError):
                    bench.validate_oi1_caps(
                        changed, expected_chip="esp32-s3", backend_mtu=247
                    )
        with self.assertRaises(bench.BenchError):
            bench.validate_oi1_caps(
                caps, expected_chip="esp32-s3", backend_mtu=23
            )
        with self.assertRaises(bench.BenchError):
            bench.parse_caps(b"mtu=247\nmtu=247\n")

    def test_unknown_backend_mtu_is_not_manufactured(self):
        class UnknownMtuClient:
            pass

        central = PbleCentral(UnknownMtuClient())
        self.assertIsNone(central.backend_mtu)
        self.assertEqual(central.mtu, 23)
        central.confirm_caps_mtu(247)
        self.assertIsNone(central.backend_mtu)
        self.assertEqual(central.mtu, 247)

        class MismatchClient:
            mtu_size = 23

        mismatch = PbleCentral(MismatchClient())
        self.assertEqual(mismatch.backend_mtu, 23)
        with self.assertRaises(ValueError):
            mismatch.confirm_caps_mtu(247)

        malformed_ack = PbleCentral(UnknownMtuClient())
        cursor = malformed_ack.begin_ack_scope(0)
        malformed_ack._ack_history.append(None)
        with self.assertRaises(ValueError):
            cursor.poll(sent_limit=0, total=10, valid_offsets={0})


class CentralFragmentationTest(unittest.IsolatedAsyncioTestCase):
    async def test_larger_fragmentation_is_enabled_only_after_caps_confirmation(self):
        class Client:
            def __init__(self):
                self.writes = []

            async def write_gatt_char(self, _uuid, payload, response):
                self.writes.append((bytes(payload), response))

        client = Client()
        central = PbleCentral(client)
        await central._write(b"x" * 100)
        self.assertGreater(len(client.writes), 1)
        self.assertTrue(all(len(packet) <= 20 for packet, _ in client.writes))

        client.writes.clear()
        central.confirm_caps_mtu(247)
        await central._write(b"x" * 100)
        self.assertEqual(len(client.writes), 1)
        self.assertEqual(len(client.writes[0][0]), 101)


class HeapAndTransferValidationTest(unittest.TestCase):
    def test_heap_probe_source_and_split_nonce_marker_are_strict(self):
        source = bench.heap_probe_source("abc123")
        for required in (
            "gc.collect()",
            "gc.mem_free()",
            "gc.mem_alloc()",
            "esp32.idf_heap_info(2052)",
            "abc123",
        ):
            self.assertIn(required, source)
        parsed = bench.parse_heap_probe_output(
            [
                b"prefix\n__PYBLE_OI1_HEAP_abc",
                b"123=9001,1000,17001,9001,5001\n",
            ],
            "abc123",
        )
        self.assertEqual(parsed, _heap())
        with self.assertRaises(bench.BenchError):
            bench.parse_heap_probe_output(
                [b"__PYBLE_OI1_HEAP_other=1,2,3,4,5\n"], "abc123"
            )
        with self.assertRaises(bench.BenchError):
            bench.parse_heap_probe_output(
                [
                    b"__PYBLE_OI1_HEAP_abc123=1,2,3,4,5\n"
                    b"__PYBLE_OI1_HEAP_abc123=1,2,3,4,5\n"
                ],
                "abc123",
            )

    def test_get_offsets_are_contiguous_unique_and_crc_verified(self):
        expected = b"abcdefghij"
        verifier = bench.DownloadVerifier(expected)
        verifier.feed(0, b"abcd")
        verifier.feed(4, b"efg")
        verifier.feed(7, b"hij")
        self.assertEqual(verifier.finish(zlib.crc32(expected)), expected)
        self.assertEqual(verifier.unique_bytes, len(expected))
        self.assertEqual(verifier.retransmitted_chunks, 0)
        self.assertEqual(verifier.retransmitted_bytes, 0)

        duplicate = bench.DownloadVerifier(expected)
        duplicate.feed(0, b"abcd")
        with self.assertRaises(bench.BenchError):
            duplicate.feed(0, b"abcd")
        self.assertEqual(duplicate.retransmitted_chunks, 1)
        self.assertEqual(duplicate.retransmitted_bytes, 4)

        gap = bench.DownloadVerifier(expected)
        with self.assertRaises(bench.BenchError):
            gap.feed(4, b"efg")

    def test_put_retransmit_accounting_counts_chunks_bytes_and_rewinds(self):
        accounting = bench.PutAccounting()
        accounting.note_send(0, 229)
        accounting.note_send(229, 229)
        accounting.note_rewind()
        accounting.note_send(0, 229)
        accounting.note_send(229, 100)
        self.assertEqual(accounting.retransmitted_chunks, 2)
        self.assertEqual(accounting.retransmitted_bytes, 329)
        self.assertEqual(accounting.rewinds, 1)

    def test_goodput_is_integer_floor_from_nanoseconds(self):
        self.assertEqual(bench.goodput_bps(65536, 2_000_000_000), 32768)
        with self.assertRaises(bench.BenchError):
            bench.goodput_bps(65536, 0)


class TransferLinkFactsObservationRedTests(unittest.TestCase):
    """`validate_observation(value, *, profile_id=...)` is profile-exact."""

    def validate(self, value, profile_id):
        return bench.validate_observation(value, profile_id=profile_id)

    def test_exact_transfer_link_facts_are_required_for_all_three_profiles(self):
        for profile_id in PROFILE_ORDER:
            with self.subTest(profile_id=profile_id):
                observation = _valid_observation(profile_id)
                self.assertIs(self.validate(observation, profile_id), observation)
                missing = copy.deepcopy(observation)
                missing.pop("transfer_link_facts")
                with self.assertRaisesRegex(
                    bench.BenchError, "transfer_link_facts|wrong keys"
                ):
                    self.validate(missing, profile_id)

    def test_nested_shape_boolean_and_numeric_bounds_fail_closed(self):
        mutations = {
            "extra": lambda facts: facts.__setitem__("identifier", "private"),
            "missing-nested": lambda facts: facts["dle"].pop("max_tx_time_us"),
            "bool-attempt": lambda facts: facts["dle"].__setitem__(
                "request_attempts", True
            ),
            "zero-attempts": lambda facts: facts["dle"].__setitem__(
                "request_attempts", 0
            ),
            "five-attempts": lambda facts: facts["dle"].__setitem__(
                "request_attempts", 5
            ),
            "short-dle": lambda facts: facts["dle"].__setitem__(
                "max_tx_octets", 243
            ),
            "zero-dle-time": lambda facts: facts["dle"].__setitem__(
                "max_tx_time_us", 0
            ),
            "no-conn-request": lambda facts: facts["connection_parameters"].__setitem__(
                "request_return_codes", []
            ),
            "four-conn-requests": lambda facts: facts[
                "connection_parameters"
            ].__setitem__("request_return_codes", [0, 0, 0, 0]),
            "no-conn-update": lambda facts: facts["connection_parameters"].__setitem__(
                "updates", []
            ),
            "bad-final-status": lambda facts: facts["connection_parameters"][
                "updates"
            ][-1].__setitem__("status", 1),
            "settled-mismatch": lambda facts: facts[
                "connection_parameters"
            ].__setitem__("settled_interval_units", 13),
            "interval-below": lambda facts: (
                facts["connection_parameters"]["updates"][-1].__setitem__(
                    "interval_units", 11
                ),
                facts["connection_parameters"].__setitem__(
                    "settled_interval_units", 11
                ),
            ),
            "interval-above": lambda facts: (
                facts["connection_parameters"]["updates"][-1].__setitem__(
                    "interval_units", 25
                ),
                facts["connection_parameters"].__setitem__(
                    "settled_interval_units", 25
                ),
            ),
            "bool-starve": lambda facts: facts.__setitem__(
                "tx_mbuf_starve_count", False
            ),
            "negative-starve": lambda facts: facts.__setitem__(
                "tx_mbuf_starve_count", -1
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                observation = _valid_observation("esp32-s3-n16r8")
                mutate(observation["transfer_link_facts"])
                with self.assertRaises(bench.BenchError):
                    self.validate(observation, "esp32-s3-n16r8")

    def test_profile_exact_phy_representation_rejects_cross_contamination(self):
        for profile_id, wrong_profile in (
            ("esp32-4mb", "esp32-s3-n16r8"),
            ("esp32-s3-n16r8", "esp32-4mb"),
            ("waveshare-esp32-s3-lcd-147b", "esp32-4mb"),
        ):
            with self.subTest(profile_id=profile_id):
                observation = _valid_observation(profile_id)
                observation["transfer_link_facts"]["phy"] = copy.deepcopy(
                    _transfer_link_facts(wrong_profile)["phy"]
                )
                with self.assertRaises(bench.BenchError):
                    self.validate(observation, profile_id)

    def test_both_s3_final_phy_updates_must_confirm_the_settled_pair(self):
        for profile_id in (
            "esp32-s3-n16r8",
            "waveshare-esp32-s3-lcd-147b",
        ):
            with self.subTest(profile_id=profile_id):
                observation = _valid_observation(profile_id)
                observation["transfer_link_facts"]["phy"]["updates"].append(
                    {"status": 26, "tx": 1, "rx": 1}
                )
                with self.assertRaises(bench.BenchError):
                    self.validate(observation, profile_id)


class TransferTimerBoundaryTest(unittest.IsolatedAsyncioTestCase):
    async def test_put_timer_wraps_begin_through_end_but_excludes_stat(self):
        data = bytes(range(256)) + b"tail"
        commands = []
        clock_positions = []

        class AckScope:
            def poll(self, *, sent_limit, total, valid_offsets):
                self.assert_valid = sent_limit in valid_offsets
                return sent_limit

        class Central:
            async def send_cmd(self, opcode, id_, payload, timeout):
                commands.append(opcode)
                if opcode == wire.OP_FILE_PUT_BEGIN:
                    return wire.Frame(wire.RSP, opcode, id_, b"\x00" + (0).to_bytes(4, "little"))
                if opcode == wire.OP_FILE_PUT_END:
                    return wire.Frame(wire.RSP, opcode, id_, b"\x00")
                if opcode == wire.OP_FILE_STAT:
                    return wire.Frame(
                        wire.RSP,
                        opcode,
                        id_,
                        b"\x00"
                        + len(data).to_bytes(4, "little")
                        + zlib.crc32(data).to_bytes(4, "little"),
                    )
                raise AssertionError("unexpected opcode")

            async def send_cmd_no_rsp(self, opcode, id_, payload):
                self.last_data = (opcode, id_, payload)

            def begin_ack_scope(self, initial):
                self.initial = initial
                return AckScope()

        ticks = iter((100, 5_100))

        def clock_ns():
            clock_positions.append(tuple(commands))
            return next(ticks)

        async def no_sleep(_seconds):
            return None

        ids = bench.CommandIds()
        result = await bench.put_file(
            Central(),
            "oi1/timer.bin",
            data,
            window=8,
            chunk=229,
            next_id=ids.next,
            clock_ns=clock_ns,
            sleep=no_sleep,
        )
        self.assertEqual(result.duration_ns, 5_000)
        self.assertEqual(clock_positions[0], ())
        self.assertEqual(clock_positions[1][-1], wire.OP_FILE_PUT_END)
        self.assertEqual(commands[-1], wire.OP_FILE_STAT)

    async def test_get_timer_stops_only_after_valid_end_and_byte_verification(self):
        expected = b"abcdefghij"
        commands = []
        clock_positions = []

        class Central:
            def __init__(self):
                self.events = []

            def event_cursor(self):
                return 0

            async def send_cmd(self, opcode, id_, payload, timeout):
                commands.append(opcode)
                self.events = [
                    wire.Frame(
                        wire.EVT,
                        wire.OP_FILE_GET_DATA,
                        0,
                        (0).to_bytes(4, "little") + expected[:4],
                    ),
                    wire.Frame(
                        wire.EVT,
                        wire.OP_FILE_GET_DATA,
                        0,
                        (4).to_bytes(4, "little") + expected[4:],
                    ),
                    wire.Frame(
                        wire.EVT,
                        wire.OP_FILE_GET_END,
                        0,
                        zlib.crc32(expected).to_bytes(4, "little"),
                    ),
                ]
                return wire.Frame(
                    wire.RSP,
                    opcode,
                    id_,
                    b"\x00" + len(expected).to_bytes(4, "little"),
                )

            def events_since(self, cursor):
                if cursor == 0:
                    return len(self.events), self.events
                return cursor, []

        ticks = iter((1_000, 9_000))

        def clock_ns():
            clock_positions.append((tuple(commands), len(central.events)))
            return next(ticks)

        async def no_sleep(_seconds):
            return None

        central = Central()
        ids = bench.CommandIds()
        result = await bench.get_file(
            central,
            "oi1/timer.bin",
            expected,
            next_id=ids.next,
            clock_ns=clock_ns,
            sleep=no_sleep,
        )
        self.assertEqual(result.duration_ns, 8_000)
        self.assertEqual(clock_positions[0], ((), 0))
        self.assertEqual(clock_positions[1][0], (wire.OP_FILE_GET_BEGIN,))
        self.assertEqual(result.unique_verified_bytes, len(expected))
        self.assertTrue(result.offset_sequence_validated)


class ResetTimingTest(unittest.IsolatedAsyncioTestCase):
    async def test_stale_advertisement_during_quiet_interval_is_rejected(self):
        class Reset:
            def __init__(self):
                self.actions = []

            def assert_reset(self):
                self.actions.append("assert")

            def release_reset(self):
                self.actions.append("release")

        class Watcher:
            def __init__(self, stale):
                self.stale = stale
                self.started = False
                self.stopped = False

            async def start(self):
                self.started = True

            async def stop(self):
                self.stopped = True

            @property
            def first_match_ns(self):
                return 100 if self.stale else None

            async def wait_for_match(self, timeout_ms):
                return 2_900_000

        async def no_sleep(_seconds):
            return None

        clock_values = iter((1_000_000, 2_000_000))
        reset = Reset()
        watcher = Watcher(stale=True)
        with self.assertRaises(bench.BenchError):
            await bench.measure_reset_to_advertisement(
                reset,
                watcher,
                hold_ms=1000,
                timeout_ms=15000,
                sleep=no_sleep,
                monotonic_ns=lambda: next(clock_values),
            )
        self.assertEqual(reset.actions, ["assert"])
        self.assertTrue(watcher.stopped)

    async def test_reset_latency_is_ceil_milliseconds_from_release(self):
        class Reset:
            def __init__(self):
                self.actions = []

            def assert_reset(self):
                self.actions.append("assert")

            def release_reset(self):
                self.actions.append("release")

        class Watcher:
            first_match_ns = None

            async def start(self):
                return None

            async def stop(self):
                return None

            async def wait_for_match(self, timeout_ms):
                self.timeout_ms = timeout_ms
                return 12_000_001

        async def no_sleep(_seconds):
            return None

        reset = Reset()
        watcher = Watcher()
        value = await bench.measure_reset_to_advertisement(
            reset,
            watcher,
            hold_ms=1000,
            timeout_ms=15000,
            sleep=no_sleep,
            monotonic_ns=lambda: 10_000_000,
        )
        self.assertEqual(value, 3)
        self.assertEqual(reset.actions, ["assert", "release"])
        self.assertEqual(watcher.timeout_ms, 15000)


class SerialResetCleanupTest(unittest.TestCase):
    @staticmethod
    def _controller_with_errors(errors=None):
        errors = dict(errors or {})
        events = []

        class Device:
            @property
            def rts(self):
                return False

            @rts.setter
            def rts(self, value):
                events.append(("rts", value))
                if "rts" in errors:
                    raise OSError(errors["rts"], "RTS cleanup failed")

            @property
            def dtr(self):
                return False

            @dtr.setter
            def dtr(self, value):
                events.append(("dtr", value))
                if "dtr" in errors:
                    raise OSError(errors["dtr"], "DTR cleanup failed")

            def close(self):
                events.append(("close", None))
                if "close" in errors:
                    raise OSError(errors["close"], "serial close failed")

        controller = object.__new__(profile_bench.SerialResetController)
        device = Device()
        controller._device = device
        return controller, device, events

    def test_normal_close_is_complete_terminal_and_idempotent(self):
        controller, _device, events = self._controller_with_errors()
        controller.close()
        controller.close()
        self.assertEqual(
            events,
            [("rts", False), ("dtr", False), ("close", None)],
        )
        self.assertIsNone(controller._device)

    def test_close_accepts_device_gone_at_each_cleanup_step(self):
        expected_events = [("rts", False), ("dtr", False), ("close", None)]
        for error_number in (errno.EIO, errno.ENXIO, errno.ENODEV, errno.EBADF):
            for stage in ("rts", "dtr", "close"):
                with self.subTest(error_number=error_number, stage=stage):
                    controller, _device, events = self._controller_with_errors(
                        {stage: error_number}
                    )
                    controller.close(allow_endpoint_gone=True)
                    self.assertEqual(events, expected_events)
                    self.assertIsNone(controller._device)

    def test_close_rejects_device_gone_before_physical_cycle(self):
        controller, _device, events = self._controller_with_errors(
            {"rts": errno.ENXIO}
        )
        with self.assertRaises(OSError) as raised:
            controller.close()
        self.assertEqual(raised.exception.errno, errno.ENXIO)
        self.assertEqual(
            events,
            [("rts", False), ("dtr", False), ("close", None)],
        )
        self.assertIsNone(controller._device)

    def test_close_preserves_first_unexpected_error_after_all_attempts(self):
        controller, _device, events = self._controller_with_errors(
            {"rts": errno.EPERM, "dtr": errno.EACCES, "close": errno.EINVAL}
        )
        with self.assertRaises(OSError) as raised:
            controller.close(allow_endpoint_gone=True)
        self.assertEqual(raised.exception.errno, errno.EPERM)
        self.assertEqual(
            events,
            [("rts", False), ("dtr", False), ("close", None)],
        )
        self.assertIsNone(controller._device)

    def test_gone_error_does_not_hide_later_unexpected_error(self):
        controller, _device, events = self._controller_with_errors(
            {"rts": errno.ENXIO, "dtr": errno.EPERM}
        )
        with self.assertRaises(OSError) as raised:
            controller.close(allow_endpoint_gone=True)
        self.assertEqual(raised.exception.errno, errno.EPERM)
        self.assertEqual(
            events,
            [("rts", False), ("dtr", False), ("close", None)],
        )
        self.assertIsNone(controller._device)

    def test_run_cleanup_closes_raw_log_after_unexpected_serial_error(self):
        events = []

        class Reset:
            def close(self):
                events.append("reset.close")
                raise OSError(errno.EPERM, "unexpected serial failure")

        class RawLog:
            def close(self):
                events.append("raw_log.close")

        with self.assertRaises(OSError) as raised:
            profile_bench._close_run_resources(Reset(), RawLog())
        self.assertEqual(raised.exception.errno, errno.EPERM)
        self.assertEqual(events, ["reset.close", "raw_log.close"])


class RawLogPrivacyTest(unittest.TestCase):
    def test_exclusive_raw_log_is_mode_0600_under_permissive_umask(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "oi1-private.jsonl"
            previous_umask = os.umask(0)
            try:
                raw_log = bench.RedactedRawLog(path)
            finally:
                os.umask(previous_umask)
            try:
                raw_log.write("measurement_start", profile_id="esp32-4mb")
            finally:
                raw_log.close()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_existing_regular_raw_log_is_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "oi1-private.jsonl"
            original = b"retained evidence\n"
            path.write_bytes(original)
            with self.assertRaisesRegex(
                bench.BenchError,
                "raw log already exists",
            ):
                bench.RedactedRawLog(path)
            self.assertEqual(path.read_bytes(), original)

    def test_raw_log_symlink_is_rejected_without_touching_its_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "retained-evidence.jsonl"
            link = root / "oi1-private.jsonl"
            original = b"retained evidence\n"
            target.write_bytes(original)
            link.symlink_to(target)
            with self.assertRaisesRegex(
                bench.BenchError,
                "raw log already exists",
            ):
                bench.RedactedRawLog(link)
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_bytes(), original)


class PhysicalCycleCleanupOrderTest(unittest.IsolatedAsyncioTestCase):
    async def test_serial_handle_closes_before_first_power_prompt(self):
        events = []

        class Reset:
            def close(self):
                events.append("reset.close")

        class RawLog:
            def write(self, event, **values):
                events.append(("log", event, values))

        class Watcher:
            def __init__(self, address):
                self.address = address
                self.first_match_ns = None

            async def start(self):
                events.append("watcher.start")

            async def wait_for_match(self, timeout_ms):
                events.append(("watcher.match", timeout_ms))
                self.first_match_ns = 1
                return self.first_match_ns

            async def stop(self):
                events.append("watcher.stop")

        async def fake_to_thread(_function, prompt):
            events.append(("prompt", prompt))
            return ""

        async def fake_sleep(seconds):
            events.append(("sleep", seconds))

        executor = profile_bench.HardwareExecutor(
            argparse.Namespace(address="test-address"),
            Reset(),
            RawLog(),
        )
        with (
            mock.patch.object(profile_bench, "AdvertisementWatcher", Watcher),
            mock.patch.object(profile_bench.asyncio, "to_thread", fake_to_thread),
            mock.patch.object(profile_bench.asyncio, "sleep", fake_sleep),
        ):
            result = await executor.physical_power_cycle()
        self.assertEqual(result, "passed")
        first_prompt = next(i for i, event in enumerate(events) if event[0] == "prompt")
        self.assertLess(events.index("reset.close"), first_prompt)


class WorkloadOrchestrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_exact_sample_counts_and_observation_shape(self):
        class FakeExecutor:
            def __init__(self):
                self.events = []
                self.reset_calls = []
                self.heap_calls = []
                self.roundtrip_calls = []
                self.disconnect_calls = []
                self.reliability_calls = 0
                self.power_calls = 0

            async def reset_connect_hello(self, sample_index):
                self.events.append(("reset_connect_hello", sample_index))
                self.reset_calls.append(sample_index)
                caps = {
                    "chip": "esp32-s3",
                    "mtu": "247",
                    "window": "8",
                    "chunk": "229",
                    "free_mem": str(40000 + sample_index),
                }
                return sample_index + 1, caps, 247, "connection-%d" % sample_index

            async def heap_snapshot(self, connection):
                self.heap_calls.append(connection)
                return _heap()

            async def disconnect(self, connection):
                self.events.append(("disconnect", connection))
                self.disconnect_calls.append(connection)

            async def begin_transfer_link_capture(self, profile_id):
                self.events.append(("begin_transfer_link_capture", profile_id))

            async def await_transfer_link_settlement(self, timeout_ms):
                self.events.append(("await_transfer_link_settlement", timeout_ms))

            async def seal_transfer_link_facts(self, timeout_ms):
                self.events.append(("seal_transfer_link_facts", timeout_ms))
                return _transfer_link_facts(
                    "waveshare-esp32-s3-lcd-147b"
                )

            async def roundtrip(self, connection, path, payload):
                self.events.append(("roundtrip", connection))
                index = len(self.roundtrip_calls)
                self.roundtrip_calls.append((connection, path, payload))
                return {
                    "put_unique_committed_bytes": len(payload),
                    "put_duration_ns": 2_000_000_000 + index,
                    "put_retransmitted_chunks": index,
                    "put_retransmitted_bytes": index * 229,
                    "get_unique_verified_bytes": len(payload),
                    "get_duration_ns": 3_000_000_000 + index,
                    "get_retransmitted_chunks": 0,
                    "get_retransmitted_bytes": 0,
                    "integrity_verified": True,
                    "offset_sequence_validated": True,
                }

            async def reliability(self, connection, profile_id):
                self.events.append(("reliability", connection))
                self.reliability_calls += 1
                return {
                    "attempted_files": 20,
                    "completed_files": 20,
                    "verified_files": 20,
                    "bytes_per_file": 16384,
                    "total_payload_bytes": 327680,
                    "unexpected_disconnects": 0,
                    "integrity_failures": 0,
                    "failed_statuses": 0,
                    "retransmitted_chunks": 2,
                    "retransmitted_bytes": 458,
                    "rewinds": 1,
                }

            async def physical_power_cycle(self):
                self.events.append(("physical_power_cycle",))
                self.power_calls += 1
                return "passed"

            def raw_log_sha256(self):
                return "a" * 64

        fake = FakeExecutor()
        observation = await profile_bench.collect_observation(
            "waveshare-esp32-s3-lcd-147b", fake
        )
        self.assertEqual(set(observation), OBSERVATION_KEYS)
        self.assertEqual(fake.reset_calls, list(range(10)))
        self.assertEqual(len(fake.roundtrip_calls), 5)
        self.assertEqual(fake.reliability_calls, 1)
        self.assertEqual(fake.power_calls, 1)
        self.assertEqual(len(observation["heap_post_hello"]), 10)
        self.assertEqual(len(observation["heap_post_roundtrip"]), 5)
        self.assertEqual(set(observation["heap_post_reliability"]), HEAP_KEYS)
        self.assertEqual(observation["put_unique_committed_bytes"], [65536] * 5)
        self.assertEqual(observation["get_unique_verified_bytes"], [65536] * 5)
        self.assertEqual(observation["roundtrip_integrity_verified"], 5)
        self.assertEqual(observation["get_offset_sequences_validated"], 5)
        self.assertEqual(
            observation["transfer_link_facts"],
            _transfer_link_facts("waveshare-esp32-s3-lcd-147b"),
        )
        self.assertEqual(observation["raw_log_sha256"], "a" * 64)
        self.assertEqual(
            fake.disconnect_calls,
            ["connection-%d" % i for i in range(10)],
        )
        # The three executor seams deliberately freeze the serial-capture
        # lifecycle: clear before reset 10, settle before timing, then collect
        # the disconnect-owned starvation fact before sealing evidence.
        self.assertLess(
            fake.events.index(
                (
                    "begin_transfer_link_capture",
                    "waveshare-esp32-s3-lcd-147b",
                )
            ),
            fake.events.index(("reset_connect_hello", 9)),
        )
        self.assertLess(
            fake.events.index(("await_transfer_link_settlement", 5000)),
            fake.events.index(("roundtrip", "connection-9")),
        )
        self.assertLess(
            fake.events.index(("disconnect", "connection-9")),
            fake.events.index(("seal_transfer_link_facts", 2000)),
        )
        self.assertLess(
            fake.events.index(("seal_transfer_link_facts", 2000)),
            fake.events.index(("physical_power_cycle",)),
        )


class EvidenceAndCliTest(unittest.TestCase):
    def test_canonical_json_is_sorted_indented_lf_terminated(self):
        encoded = bench.canonical_json_bytes({"z": 1, "a": ["é", {"b": 2}]})
        self.assertEqual(
            encoded,
            (
                '{\n'
                '  "a": [\n'
                '    "é",\n'
                '    {\n'
                '      "b": 2\n'
                "    }\n"
                "  ],\n"
                '  "z": 1\n'
                "}\n"
            ).encode("utf-8"),
        )
        self.assertEqual(json.loads(encoded), {"z": 1, "a": ["é", {"b": 2}]})

    def test_baseline_profile_is_redacted_and_verify_emits_observation(self):
        observation = {"raw_log_sha256": "b" * 64}
        profile = profile_bench.build_baseline_profile(
            profile_id="esp32-4mb",
            board_manufacturer="Espressif",
            board_model="ESP32 DevKit",
            module_marking="ESP32-WROOM-32",
            device_flash_capacity_bytes=4 * 1024 * 1024,
            device_psram_capacity_bytes=0,
            firmware_sha256="c" * 64,
            manifest_sha256="d" * 64,
            environment={
                "desktop_os": "macOS",
                "ble_backend": "CoreBluetooth",
                "ble_adapter": "built-in",
                "python_version": "3.13",
            },
            oi1_build={
                "application_image_bytes": 100,
                "factory_partition_bytes": 200,
                "application_headroom_bytes": 100,
            },
            oi1_observation=observation,
        )
        self.assertNotIn("address", json.dumps(profile))
        self.assertNotIn("reset_port", json.dumps(profile))
        self.assertEqual(profile_bench.output_for_mode("baseline", profile, observation), profile)
        self.assertEqual(
            profile_bench.output_for_mode("verify", profile, observation),
            observation,
        )

    def test_cli_requires_exact_owned_profile_and_explicit_reset_port(self):
        required = [
            "--mode",
            "baseline",
            "--profile",
            "esp32-4mb",
            "--expect-chip",
            "esp32",
            "--address",
            "test-address",
            "--reset-port",
            "/dev/test-reset",
            "--application-bin",
            "application.bin",
            "--partition-table-bin",
            "partition-table.bin",
            "--raw-log",
            "raw.jsonl",
            "--output",
            "observation.json",
        ]
        args = profile_bench._parse_args(required)
        self.assertEqual(args.profile, "esp32-4mb")
        waveshare = list(required)
        waveshare[waveshare.index("esp32-4mb")] = (
            "waveshare-esp32-s3-lcd-147b"
        )
        waveshare[waveshare.index("esp32")] = "esp32-s3"
        waveshare_args = profile_bench._parse_args(waveshare)
        self.assertEqual(
            waveshare_args.profile,
            "waveshare-esp32-s3-lcd-147b",
        )
        self.assertEqual(waveshare_args.expect_chip, "esp32-s3")
        for missing_flag in ("--reset-port", "--raw-log", "--output"):
            with self.subTest(missing=missing_flag):
                index = required.index(missing_flag)
                without = required[:index] + required[index + 2 :]
                with self.assertRaises(SystemExit):
                    profile_bench._parse_args(without)
        c3 = list(required)
        c3[c3.index("esp32-4mb")] = "esp32-c3-4mb"
        c3[c3.index("esp32")] = "esp32-c3"
        with self.assertRaises(SystemExit):
            profile_bench._parse_args(c3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
