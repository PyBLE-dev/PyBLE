# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Host-only contract tests for the frozen OI-1 profile HIL bench.  All BLE,
# reset, clock, and file inputs are fakes; no board or serial adapter is used.

import argparse
import asyncio
import contextlib
import copy
import errno
import hashlib
import inspect
import io
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
CURRENT_PROFILE_ORDER = PROFILE_ORDER + (
    "esp32-c3-4mb",
    "rpi-pico2-w",
)
HISTORICAL_V042_PROFILE_ORDER = (
    "esp32-4mb",
    "esp32-s3-n16r8",
)
PROFILE_TARGETS = {
    "esp32-4mb": "esp32",
    "esp32-s3-n16r8": "esp32-s3",
    "waveshare-esp32-s3-lcd-147b": "waveshare-esp32-s3-lcd-147b",
    "esp32-c3-4mb": "esp32-c3",
    "rpi-pico2-w": "rpi-pico2-w",
}
PROFILE_CHIPS = {
    "esp32-4mb": "esp32",
    "esp32-s3-n16r8": "esp32-s3",
    "waveshare-esp32-s3-lcd-147b": "esp32-s3",
    "esp32-c3-4mb": "esp32-c3",
    "rpi-pico2-w": "rpi-pico2-w",
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
        "esp32-c3-4mb",
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


def _waveshare_link_fact_record(
        epoch, *, final, settled=True, overflow=False):
    return {
        "epoch": epoch,
        "final": final,
        "settled": settled,
        "overflow": overflow,
        "facts": _transfer_link_facts(
            "waveshare-esp32-s3-lcd-147b"
        ),
    }


def _waveshare_link_fact_snapshot(*, active_epoch=42, ended_epoch=41):
    return {
        "active": _waveshare_link_fact_record(
            active_epoch,
            final=False,
        ),
        "last_ended": _waveshare_link_fact_record(
            ended_epoch,
            final=True,
        ),
    }


def _waveshare_active_link_fact_snapshot(*, active_epoch=42):
    return {
        "active": _waveshare_link_fact_record(
            active_epoch,
            final=False,
        ),
        "last_ended": None,
    }


def _max_waveshare_link_fact_record(epoch, *, final):
    uint32_max = (1 << 32) - 1
    facts = {
        "dle": {
            "request_attempts": 4,
            "max_tx_octets": (1 << 16) - 1,
            "max_tx_time_us": (1 << 16) - 1,
        },
        "phy": {
            "required_2m": True,
            "request_attempts": 4,
            "updates": [
                {"status": uint32_max, "tx": 255, "rx": 255}
                for _ in range(7)
            ]
            + [{"status": 0, "tx": 2, "rx": 2}],
            "settled_tx": 2,
            "settled_rx": 2,
        },
        "connection_parameters": {
            "request_return_codes": [uint32_max, uint32_max, 0],
            "updates": [
                {"status": uint32_max, "interval_units": (1 << 16) - 1}
                for _ in range(7)
            ]
            + [{"status": 0, "interval_units": 12}],
            "settled_interval_units": 12,
        },
        "tx_mbuf_starve_count": uint32_max,
    }
    return {
        "epoch": epoch,
        "final": final,
        "settled": True,
        "overflow": False,
        "facts": facts,
    }


def _max_waveshare_link_fact_snapshot(projection):
    epoch_max = (1 << 64) - 1
    if projection == "active":
        return {
            "active": _max_waveshare_link_fact_record(
                epoch_max,
                final=False,
            ),
            "last_ended": None,
        }
    if projection == "pair":
        return {
            "active": _max_waveshare_link_fact_record(
                epoch_max,
                final=False,
            ),
            "last_ended": _max_waveshare_link_fact_record(
                epoch_max - 1,
                final=True,
            ),
        }
    raise AssertionError("test fixture received an unsupported projection")


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
    def test_exact_v060_candidate_profiles_and_common_workload_are_frozen(self):
        self.assertEqual(tuple(bench.PROFILE_ORDER), CURRENT_PROFILE_ORDER)
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
            "workload": bench.V051_WORKLOAD,
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
        c3 = bench.deterministic_payload("esp32-c3-4mb", 0, 65536)
        pico = bench.deterministic_payload("rpi-pico2-w", 0, 65536)
        self.assertNotEqual(c3, payload)
        self.assertNotEqual(pico, c3)
        with self.assertRaises(ValueError):
            bench.deterministic_payload("future-profile", 0, 65536)


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

    def test_all_2m_parsers_preserve_order_and_seal_after_session_end(self):
        for profile_id in (
            "esp32-s3-n16r8",
            "waveshare-esp32-s3-lcd-147b",
            "esp32-c3-4mb",
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

        pico_caps = bench.parse_caps(
            b"chip=rpi-pico2-w\nmtu=247\nwindow=4\nchunk=229\nfree_mem=12345\n"
        )
        self.assertEqual(
            bench.validate_oi1_caps(
                pico_caps,
                expected_chip="rpi-pico2-w",
                backend_mtu=247,
                profile_id="rpi-pico2-w",
            ),
            (247, 4, 229, 12345),
        )
        with self.assertRaises(bench.BenchError):
            bench.validate_oi1_caps(
                {**pico_caps, "window": "8"},
                expected_chip="rpi-pico2-w",
                backend_mtu=247,
                profile_id="rpi-pico2-w",
            )

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


class WaveshareBleLinkFactProbeRedTest(unittest.TestCase):
    def test_probe_projection_and_timeout_contract_is_mandatory(self):
        self.assertEqual(
            getattr(bench, "OI1_LINK_FACT_PAIR_TIMEOUT_S", None),
            8.0,
        )
        self.assertEqual(
            getattr(bench, "OI1_LINK_FACT_ACTIVE_TIMEOUT_S", None),
            5.0,
        )
        for function_name in (
            "oi1_link_fact_probe_source",
            "parse_oi1_link_fact_probe_output",
            "run_oi1_link_fact_probe",
        ):
            with self.subTest(function_name=function_name):
                function = getattr(bench, function_name)
                parameters = inspect.signature(function).parameters
                self.assertIn("projection", parameters)
                self.assertIs(
                    parameters["projection"].default,
                    inspect.Parameter.empty,
                )

    def test_exact_getter_projection_source_and_split_strict_markers(self):
        source_fn = getattr(bench, "oi1_link_fact_probe_source", None)
        parser_fn = getattr(
            bench,
            "parse_oi1_link_fact_probe_output",
            None,
        )
        self.assertIsNotNone(source_fn, "HAND-OFF [green]: add probe source")
        self.assertIsNotNone(parser_fn, "HAND-OFF [green]: add strict parser")

        pair_source = source_fn("abc123", projection="pair")
        active_source = source_fn("abc123", projection="active")
        for source in (pair_source, active_source):
            self.assertIn("import pble_ble", source)
            self.assertEqual(source.count("_oi1_link_facts()"), 1)
            self.assertIn("__PYBLE_OI1_LINK_FACTS_abc123", source)

        native_pair = _waveshare_link_fact_snapshot()
        fake_pble_ble = mock.Mock()
        fake_pble_ble._oi1_link_facts.side_effect = lambda: copy.deepcopy(
            native_pair
        )
        observed_source_values = {}
        for projection, source in (
            ("pair", pair_source),
            ("active", active_source),
        ):
            stdout = io.StringIO()
            with (
                mock.patch.dict(sys.modules, {"pble_ble": fake_pble_ble}),
                contextlib.redirect_stdout(stdout),
            ):
                exec(source, {})  # nosec - generated, fixed qualification source
            marker = "__PYBLE_OI1_LINK_FACTS_abc123="
            line = stdout.getvalue()
            self.assertTrue(line.startswith(marker))
            observed_source_values[projection] = json.loads(
                line[len(marker):]
            )
        self.assertEqual(fake_pble_ble._oi1_link_facts.call_count, 2)
        self.assertEqual(observed_source_values["pair"], native_pair)
        self.assertEqual(
            observed_source_values["active"],
            {
                "active": native_pair["active"],
                "last_ended": None,
            },
        )
        with self.assertRaisesRegex(bench.BenchError, "projection"):
            source_fn("abc123", projection="full")

        pair = _waveshare_link_fact_snapshot()
        pair_encoded = json.dumps(pair, sort_keys=True).encode("ascii")
        parsed_pair = parser_fn(
            [
                b"discarded console noise\n__PYBLE_OI1_LINK_FACTS_abc",
                b"123=" + pair_encoded + b"\n",
            ],
            "abc123",
            projection="pair",
        )
        self.assertEqual(parsed_pair, pair)

        active = _waveshare_active_link_fact_snapshot()
        active_encoded = json.dumps(active, sort_keys=True).encode("ascii")
        parsed_active = parser_fn(
            [
                b"__PYBLE_OI1_LINK_FACTS_abc123=" + active_encoded,
                b"\n",
            ],
            "abc123",
            projection="active",
        )
        self.assertEqual(parsed_active, active)

    def test_projection_parser_rejects_cross_scope_records(self):
        parser_fn = bench.parse_oi1_link_fact_probe_output

        def marker(value):
            return (
                b"__PYBLE_OI1_LINK_FACTS_scope="
                + json.dumps(value, sort_keys=True).encode("ascii")
                + b"\n"
            )

        with self.assertRaisesRegex(bench.BenchError, "last.ended|active"):
            parser_fn(
                [marker(_waveshare_link_fact_snapshot())],
                "scope",
                projection="active",
            )
        with self.assertRaisesRegex(bench.BenchError, "last.ended|pair"):
            parser_fn(
                [marker(_waveshare_active_link_fact_snapshot())],
                "scope",
                projection="pair",
            )
        for projection in ("", "full", True, None):
            with self.subTest(projection=projection):
                with self.assertRaisesRegex(bench.BenchError, "projection"):
                    parser_fn(
                        [marker(_waveshare_link_fact_snapshot())],
                        "scope",
                        projection=projection,
                    )

    def test_malformed_stale_and_overflowed_snapshots_fail_closed(self):
        parser_fn = getattr(
            bench,
            "parse_oi1_link_fact_probe_output",
            None,
        )
        pair_fn = getattr(
            profile_bench,
            "validate_waveshare_link_fact_pair",
            None,
        )
        self.assertIsNotNone(parser_fn, "HAND-OFF [green]: add strict parser")
        self.assertIsNotNone(pair_fn, "HAND-OFF [green]: add epoch validator")

        snapshot = _waveshare_link_fact_snapshot()

        def marker(value):
            return (
                b"__PYBLE_OI1_LINK_FACTS_nonce="
                + json.dumps(value, sort_keys=True).encode("ascii")
                + b"\n"
            )

        malformed = copy.deepcopy(snapshot)
        malformed["address"] = "forbidden"
        overflowed = copy.deepcopy(snapshot)
        overflowed["last_ended"]["overflow"] = True
        for payload in (
            marker(malformed),
            marker(overflowed),
            marker(snapshot) + marker(snapshot),
            b"__PYBLE_OI1_LINK_FACTS_nonce=\xff\n",
        ):
            with self.subTest(payload=payload[:80]):
                with self.assertRaises(bench.BenchError):
                    parser_fn([payload], "nonce", projection="pair")

        pair_fn(snapshot, expected_ended_epoch=41)
        stale = _waveshare_link_fact_snapshot(ended_epoch=40)
        with self.assertRaisesRegex(bench.BenchError, "epoch|stale"):
            pair_fn(stale, expected_ended_epoch=41)
        non_successor = _waveshare_link_fact_snapshot(
            active_epoch=43,
            ended_epoch=41,
        )
        with self.assertRaisesRegex(bench.BenchError, "epoch|successor"):
            pair_fn(non_successor, expected_ended_epoch=41)


class WaveshareBleExecutorRedTest(unittest.IsolatedAsyncioTestCase):
    async def test_first_nine_disconnects_use_bounded_ble_diagnostic_sequence(self):
        executor_type = getattr(
            profile_bench,
            "WaveshareHardwareExecutor",
            None,
        )
        self.assertIsNotNone(
            executor_type,
            "HAND-OFF [green]: add the no-serial Waveshare executor",
        )
        events = []

        class Connection:
            def __init__(self, name):
                self.name = name
                self.backend_mtu = 247

            async def disconnect(self):
                events.append(("disconnect", self.name))

        class Log:
            def write(self, event, **_values):
                events.append(("log", event))

        async def connect(address, timeout):
            events.append(("connect", address, timeout))
            return diagnostic

        async def diagnostic_hello(
                central, _next_id, *, expected_chip, profile_id, timeout_s):
            self.assertIs(central, diagnostic)
            events.append(("hello", expected_chip, profile_id, timeout_s))
            return {}, (247, 8, 229, 0)

        async def probe(central, _next_id, *, projection, timeout_s):
            self.assertIs(central, diagnostic)
            events.append(("probe", projection, timeout_s))
            return _waveshare_link_fact_snapshot()

        args = argparse.Namespace(
            address="private-test-address",
            expect_chip="esp32-s3",
            profile="waveshare-esp32-s3-lcd-147b",
        )
        measured = Connection("measured")
        diagnostic = Connection("diagnostic")
        executor = executor_type(args, object(), Log())
        with (
            mock.patch.object(
                profile_bench.PbleCentral,
                "connect",
                new=connect,
            ),
            mock.patch.object(profile_bench, "hello", new=diagnostic_hello),
            mock.patch.object(
                profile_bench,
                "run_oi1_link_fact_probe",
                new=probe,
                create=True,
            ),
        ):
            await executor.disconnect(measured)

        evidence_events = [event for event in events if event[0] != "log"]
        self.assertEqual(
            evidence_events,
            [
                ("disconnect", "measured"),
                ("connect", "private-test-address", 20.0),
                (
                    "hello",
                    "esp32-s3",
                    "waveshare-esp32-s3-lcd-147b",
                    5.0,
                ),
                ("probe", "pair", 8.0),
                ("disconnect", "diagnostic"),
            ],
        )


class WaveshareBleDeadlineAndCleanupRedTest(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _args():
        return argparse.Namespace(
            address="private-test-address",
            expect_chip="esp32-s3",
            profile="waveshare-esp32-s3-lcd-147b",
        )

    @staticmethod
    def _log():
        class Log:
            def write(self, _event, **_values):
                return None

        return Log()

    @staticmethod
    def _immediate_central(
            snapshot, nonce, *, chunk_bytes=150, separate_newline=False):
        marker = (
            ("__PYBLE_OI1_LINK_FACTS_%s=" % nonce).encode("ascii")
            + json.dumps(snapshot, sort_keys=True).encode("ascii")
        )
        chunks = [
            marker[offset : offset + chunk_bytes]
            for offset in range(0, len(marker), chunk_bytes)
        ]
        if separate_newline:
            chunks.append(b"\n")
        else:
            chunks[-1] += b"\n"

        class ImmediateCentral:
            def __init__(self):
                self.command_timeout = None

            def event_cursor(self):
                return 0

            async def send_cmd(self, opcode, id_, _payload, timeout):
                self.command_timeout = timeout
                return wire.Frame(wire.RSP, opcode, id_, b"\x00")

            def events_since(self, _cursor):
                events = [wire.Frame(wire.EVT, wire.OP_RUN_STATE, 0, b"\x01")]
                events.extend(
                    wire.Frame(
                        wire.EVT,
                        wire.OP_CONSOLE_DATA,
                        0,
                        b"\x00" + chunk,
                    )
                    for chunk in chunks
                )
                events.append(
                    wire.Frame(wire.EVT, wire.OP_RUN_STATE, 0, b"\x02")
                )
                return len(events), events

        return ImmediateCentral(), len(chunks)

    async def test_probe_accepts_exact_projection_caps_and_rejects_wrong_caps(self):
        pair = _waveshare_link_fact_snapshot()
        pair_central, _ = self._immediate_central(pair, "pair-cap")
        observed_pair = await bench.run_oi1_link_fact_probe(
            pair_central,
            lambda: 1,
            nonce="pair-cap",
            projection="pair",
            timeout_s=8.0,
        )
        self.assertEqual(observed_pair, pair)
        self.assertGreater(pair_central.command_timeout, 0)
        self.assertLessEqual(pair_central.command_timeout, 8.0)

        active = _waveshare_active_link_fact_snapshot()
        active_central, _ = self._immediate_central(active, "active-cap")
        observed_active = await bench.run_oi1_link_fact_probe(
            active_central,
            lambda: 1,
            nonce="active-cap",
            projection="active",
            timeout_s=5.0,
        )
        self.assertEqual(observed_active, active)
        self.assertGreater(active_central.command_timeout, 0)
        self.assertLessEqual(active_central.command_timeout, 5.0)

        invalid_cases = (
            ("pair", 5.0),
            ("pair", 8.001),
            ("active", 5.001),
            ("active", 0.0),
            ("full", 8.0),
        )
        for projection, timeout_s in invalid_cases:
            with self.subTest(projection=projection, timeout_s=timeout_s):
                with self.assertRaisesRegex(
                    bench.BenchError,
                    "projection|timeout|cap",
                ):
                    await bench.run_oi1_link_fact_probe(
                        object(),
                        lambda: 1,
                        nonce="invalid-cap",
                        projection=projection,
                        timeout_s=timeout_s,
                    )

    async def test_maximum_projection_shapes_accept_separate_newline_event(self):
        cases = (
            ("pair", 8.0, 14),
            ("active", 5.0, 8),
        )
        for projection, timeout_s, expected_console_submissions in cases:
            with self.subTest(projection=projection):
                snapshot = _max_waveshare_link_fact_snapshot(projection)
                central, console_submissions = self._immediate_central(
                    snapshot,
                    "0123456789abcdef",
                    chunk_bytes=200,
                    separate_newline=True,
                )
                self.assertEqual(
                    console_submissions,
                    expected_console_submissions,
                )
                observed = await bench.run_oi1_link_fact_probe(
                    central,
                    lambda: 1,
                    nonce="0123456789abcdef",
                    projection=projection,
                    timeout_s=timeout_s,
                )
                self.assertEqual(observed, snapshot)

    async def test_probe_total_deadline_includes_command_writes(self):
        class HungWriteCentral:
            def event_cursor(self):
                return 0

            async def send_cmd(self, *_args, **_kwargs):
                await asyncio.Event().wait()

        with self.assertRaisesRegex(bench.BenchError, "deadline|timed out"):
            await asyncio.wait_for(
                bench.run_oi1_link_fact_probe(
                    HungWriteCentral(),
                    lambda: 1,
                    nonce="deadline",
                    projection="active",
                    timeout_s=0.01,
                ),
                timeout=0.20,
            )

    async def test_probe_rejects_queued_terminal_after_absolute_deadline(self):
        clock = type("Clock", (), {"now": 100.0})()
        snapshot = _waveshare_active_link_fact_snapshot()
        marker = (
            b"__PYBLE_OI1_LINK_FACTS_late="
            + json.dumps(snapshot, sort_keys=True).encode("ascii")
            + b"\n"
        )

        class LateCentral:
            def event_cursor(self):
                return 0

            async def send_cmd(self, opcode, id_, _payload, timeout):
                self.assert_positive_timeout = timeout
                return wire.Frame(wire.RSP, opcode, id_, b"\x00")

            def events_since(self, _cursor):
                clock.now = 100.011
                events = [wire.Frame(wire.EVT, wire.OP_RUN_STATE, 0, b"\x01")]
                events.extend(
                    wire.Frame(
                        wire.EVT,
                        wire.OP_CONSOLE_DATA,
                        0,
                        b"\x00" + marker[offset : offset + 150],
                    )
                    for offset in range(0, len(marker), 150)
                )
                events.append(
                    wire.Frame(wire.EVT, wire.OP_RUN_STATE, 0, b"\x02")
                )
                return len(events), events

        with (
            mock.patch.object(bench.time, "monotonic", new=lambda: clock.now),
            self.assertRaisesRegex(bench.BenchError, "deadline|timed out"),
        ):
            await bench.run_oi1_link_fact_probe(
                LateCentral(),
                lambda: 1,
                nonce="late",
                projection="active",
                timeout_s=0.01,
            )

    async def test_active_probe_drip_progress_does_not_extend_absolute_cap(self):
        clock = type("Clock", (), {"now": 100.0})()
        snapshot = _max_waveshare_link_fact_snapshot("active")
        marker = (
            b"__PYBLE_OI1_LINK_FACTS_0123456789abcdef="
            + json.dumps(snapshot, sort_keys=True).encode("ascii")
        )
        console_chunks = [
            marker[offset : offset + 200]
            for offset in range(0, len(marker), 200)
        ] + [b"\n"]
        scripted = [wire.Frame(wire.EVT, wire.OP_RUN_STATE, 0, b"\x01")]
        scripted.extend(
            wire.Frame(
                wire.EVT,
                wire.OP_CONSOLE_DATA,
                0,
                b"\x00" + chunk,
            )
            for chunk in console_chunks
        )
        scripted.append(
            wire.Frame(wire.EVT, wire.OP_RUN_STATE, 0, b"\x02")
        )

        class DripCentral:
            def __init__(self):
                self.published = []

            def event_cursor(self):
                return 0

            async def send_cmd(self, opcode, id_, _payload, timeout):
                self.command_timeout = timeout
                return wire.Frame(wire.RSP, opcode, id_, b"\x00")

            def events_since(self, cursor):
                clock.now += 0.6
                if len(self.published) < len(scripted):
                    self.published.append(scripted[len(self.published)])
                return len(self.published), self.published[cursor:]

        with (
            mock.patch.object(bench.time, "monotonic", new=lambda: clock.now),
            self.assertRaisesRegex(bench.BenchError, "deadline|timed out"),
        ):
            await bench.run_oi1_link_fact_probe(
                DripCentral(),
                lambda: 1,
                nonce="0123456789abcdef",
                projection="active",
                timeout_s=5.0,
            )

    async def test_diagnostic_hello_total_deadline_includes_command_writes(self):
        executor_type = profile_bench.WaveshareHardwareExecutor
        executor = executor_type(self._args(), object(), self._log())
        calls = []
        hello_timeouts = []

        class Diagnostic:
            def __init__(self):
                self.disconnect_count = 0

            async def disconnect(self):
                self.disconnect_count += 1

        diagnostic = Diagnostic()

        async def connect(_address, timeout):
            self.assertEqual(timeout, 20.0)
            return diagnostic

        async def hung_hello(*_args, **kwargs):
            hello_timeouts.append(kwargs["timeout_s"])
            await asyncio.Event().wait()

        real_wait_for = asyncio.wait_for

        async def bounded_wait_for(awaitable, timeout):
            calls.append(timeout)
            return await real_wait_for(awaitable, timeout=0.01)

        with (
            mock.patch.object(profile_bench.PbleCentral, "connect", new=connect),
            mock.patch.object(profile_bench, "hello", new=hung_hello),
            mock.patch.object(
                profile_bench.asyncio,
                "wait_for",
                new=bounded_wait_for,
            ),
            self.assertRaisesRegex(profile_bench.BenchError, "HELLO.*deadline"),
        ):
            await executor._diagnostic_snapshot()
        self.assertEqual(calls, [5.0])
        self.assertEqual(hello_timeouts, [5.0])
        self.assertEqual(diagnostic.disconnect_count, 1)

    async def test_settlement_rejects_snapshot_returned_after_outer_deadline(self):
        executor_type = profile_bench.WaveshareHardwareExecutor
        executor = executor_type(self._args(), object(), self._log())
        executor._measured_connection = object()

        class Loop:
            now = 100.0

            def time(self):
                return self.now

        loop = Loop()

        async def late_probe(
                _connection, _next_id, *, projection, timeout_s):
            self.assertEqual(projection, "active")
            self.assertEqual(timeout_s, 5.0)
            loop.now = 105.001
            return _waveshare_active_link_fact_snapshot()

        with (
            mock.patch.object(
                profile_bench.asyncio,
                "get_running_loop",
                return_value=loop,
            ),
            mock.patch.object(
                profile_bench,
                "run_oi1_link_fact_probe",
                new=late_probe,
            ),
            self.assertRaisesRegex(profile_bench.BenchError, "not observed"),
        ):
            await executor.await_transfer_link_settlement(5000)
        self.assertIsNone(executor._transfer_epoch)

    async def test_settlement_does_not_retry_after_probe_failure(self):
        executor = profile_bench.WaveshareHardwareExecutor(
            self._args(), object(), self._log()
        )
        executor._measured_connection = object()
        calls = []

        async def failed_probe(*_args, **kwargs):
            calls.append(kwargs)
            raise profile_bench.BenchError("probe failed closed")

        with (
            mock.patch.object(
                profile_bench,
                "run_oi1_link_fact_probe",
                new=failed_probe,
            ),
            self.assertRaisesRegex(profile_bench.BenchError, "failed closed"),
        ):
            await executor.await_transfer_link_settlement(5000)
        self.assertEqual(
            calls,
            [{"projection": "active", "timeout_s": 5.0}],
        )
        self.assertIsNone(executor._transfer_epoch)

    async def test_cleanup_preserves_primary_and_is_idempotent(self):
        class PrimaryError(RuntimeError):
            pass

        class CleanupError(RuntimeError):
            pass

        executor_type = profile_bench.WaveshareHardwareExecutor
        executor = executor_type(self._args(), object(), self._log())

        class Diagnostic:
            def __init__(self):
                self.disconnect_count = 0

            async def disconnect(self):
                self.disconnect_count += 1
                raise CleanupError("diagnostic cleanup")

        diagnostic = Diagnostic()

        async def connect(_address, timeout):
            self.assertEqual(timeout, 20.0)
            return diagnostic

        async def primary_hello(*_args, **_kwargs):
            raise PrimaryError("diagnostic primary")

        with (
            mock.patch.object(profile_bench.PbleCentral, "connect", new=connect),
            mock.patch.object(profile_bench, "hello", new=primary_hello),
        ):
            with self.assertRaisesRegex(
                profile_bench.BenchError,
                "diagnostic and disconnect",
            ) as raised:
                await executor._diagnostic_snapshot()
        self.assertEqual(diagnostic.disconnect_count, 1)
        self.assertIsInstance(raised.exception.__cause__, CleanupError)
        chain = []
        current = raised.exception
        while current is not None and current not in chain:
            chain.append(current)
            current = current.__cause__ or current.__context__
        self.assertTrue(any(isinstance(item, PrimaryError) for item in chain))

        class Measured:
            def __init__(self):
                self.disconnect_count = 0

            async def disconnect(self):
                self.disconnect_count += 1

        measured = Measured()
        executor = executor_type(self._args(), object(), self._log())
        executor._capture_started = True
        executor._measured_connection = measured
        executor._transfer_epoch = 41
        executor._transfer_facts = _transfer_link_facts(
            "waveshare-esp32-s3-lcd-147b"
        )

        async def primary_probe(*_args, **kwargs):
            self.assertEqual(kwargs["projection"], "active")
            self.assertEqual(kwargs["timeout_s"], 5.0)
            raise PrimaryError("pre-disconnect primary")

        with mock.patch.object(
            profile_bench,
            "run_oi1_link_fact_probe",
            new=primary_probe,
        ):
            with self.assertRaises(PrimaryError):
                await executor.disconnect(measured)
            await executor.disconnect(measured)
        self.assertEqual(measured.disconnect_count, 1)


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

    def test_all_2m_final_phy_updates_must_confirm_the_settled_pair(self):
        for profile_id in (
            "esp32-s3-n16r8",
            "waveshare-esp32-s3-lcd-147b",
            "esp32-c3-4mb",
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
    async def test_late_callback_restarts_the_bounded_quiet_window(self):
        events = []

        class Reset:
            def assert_reset(self):
                events.append("assert-confirmed")

            def release_reset(self):
                events.append("release-confirmed")

        class Watcher:
            def __init__(self):
                self.first_match_ns = None

            async def start(self):
                events.append("scanner-started")
                self.first_match_ns = 100

            async def stop(self):
                events.append("scanner-stopped")

            def begin_quiet_interval(self):
                events.append("quiet-boundary")
                self.first_match_ns = None

            async def wait_for_quiet(self, quiet_ms, timeout_ms):
                events.append(("quiet-wait", quiet_ms, timeout_ms))
                self.first_match_ns = 200
                events.append("queued-callback-restarted-window")
                self.first_match_ns = None

            def begin_post_release_interval(self, clock_ns):
                events.append("post-release-boundary")
                self.first_match_ns = None
                return clock_ns()

            async def wait_for_match(self, timeout_ms):
                events.append(("wait", timeout_ms))
                return 12_000_001

        value = await bench.measure_reset_to_advertisement(
            Reset(),
            Watcher(),
            hold_ms=1000,
            timeout_ms=15000,
            monotonic_ns=lambda: 10_000_000,
        )

        self.assertEqual(value, 3)
        self.assertLess(events.index("scanner-started"), events.index("assert-confirmed"))
        self.assertLess(events.index("assert-confirmed"), events.index("quiet-boundary"))
        self.assertLess(
            events.index("quiet-boundary"),
            events.index(("quiet-wait", 1000, 15000)),
        )
        self.assertLess(
            events.index("queued-callback-restarted-window"),
            events.index("release-confirmed"),
        )
        self.assertLess(
            events.index("release-confirmed"),
            events.index("post-release-boundary"),
        )

    async def test_quiet_window_timeout_fails_before_release(self):
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

            def begin_quiet_interval(self):
                return None

            async def wait_for_quiet(self, quiet_ms, timeout_ms):
                raise asyncio.TimeoutError

            def begin_post_release_interval(self, clock_ns):
                raise AssertionError("release boundary must not be reached")

            async def wait_for_match(self, timeout_ms):
                raise AssertionError("post-release scan must not be reached")

        reset = Reset()
        with self.assertRaisesRegex(bench.BenchError, "continuous reset quiet"):
            await bench.measure_reset_to_advertisement(
                reset,
                Watcher(),
                hold_ms=1000,
                timeout_ms=15000,
            )
        self.assertEqual(reset.actions, ["assert"])

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

            def __init__(self):
                self.quiet_boundaries = 0

            async def start(self):
                return None

            async def stop(self):
                return None

            def begin_quiet_interval(self):
                self.quiet_boundaries += 1

            async def wait_for_quiet(self, quiet_ms, timeout_ms):
                self.quiet_args = (quiet_ms, timeout_ms)

            def begin_post_release_interval(self, clock_ns):
                self.post_release_boundaries = getattr(
                    self, "post_release_boundaries", 0
                ) + 1
                return clock_ns()

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
        self.assertEqual(watcher.quiet_boundaries, 1)
        self.assertEqual(watcher.quiet_args, (1000, 15000))
        self.assertEqual(watcher.post_release_boundaries, 1)
        self.assertEqual(watcher.timeout_ms, 15000)

    async def test_waveshare_operator_confirmation_precedes_timer_start(self):
        events = []

        class Reset:
            def assert_reset(self):
                events.append("hold-confirmed")

            def release_reset(self):
                events.append("release-confirmed")

        class Watcher:
            first_match_ns = None

            async def start(self):
                events.append("scanner-started")

            async def stop(self):
                events.append("scanner-stopped")

            def begin_quiet_interval(self):
                events.append("quiet-boundary")

            async def wait_for_quiet(self, quiet_ms, timeout_ms):
                events.append(("quiet-wait", quiet_ms, timeout_ms))

            def begin_post_release_interval(self, clock_ns):
                events.append("post-release-boundary")
                return clock_ns()

            async def wait_for_match(self, timeout_ms):
                events.append(("wait", timeout_ms))
                return 12_000_001

        def clock_ns():
            events.append("timer-started")
            return 10_000_000

        value = await bench.measure_reset_to_advertisement(
            Reset(),
            Watcher(),
            hold_ms=1000,
            timeout_ms=15000,
            monotonic_ns=clock_ns,
        )

        self.assertEqual(value, 3)
        self.assertLess(
            events.index("scanner-started"), events.index("hold-confirmed")
        )
        self.assertLess(
            events.index("hold-confirmed"),
            events.index("quiet-boundary"),
        )
        self.assertLess(
            events.index("quiet-boundary"),
            events.index(("quiet-wait", 1000, 15000)),
        )
        self.assertLess(
            events.index(("quiet-wait", 1000, 15000)),
            events.index("release-confirmed"),
        )
        self.assertLess(
            events.index("release-confirmed"),
            events.index("post-release-boundary"),
        )
        self.assertLess(
            events.index("post-release-boundary"), events.index("timer-started")
        )

    def test_advertisement_watcher_quiet_boundary_replaces_completion_epoch(self):
        watcher = profile_bench.AdvertisementWatcher("AA:BB")
        device = argparse.Namespace(address="AA:BB")
        advertisement = argparse.Namespace(
            service_uuids=[profile_bench.SERVICE_UUID]
        )
        watcher._on_advertisement(device, advertisement)
        prior_event = watcher._match_event

        self.assertIsNotNone(watcher.first_match_ns)
        self.assertTrue(prior_event.is_set())
        watcher.begin_quiet_interval()

        self.assertIsNone(watcher.first_match_ns)
        self.assertIsNot(watcher._match_event, prior_event)
        self.assertFalse(watcher._match_event.is_set())

        watcher._on_advertisement(device, advertisement)
        post_release_ns = watcher.begin_post_release_interval(lambda: 123456)
        self.assertEqual(post_release_ns, 123456)
        self.assertIsNone(watcher.first_match_ns)
        self.assertFalse(watcher._match_event.is_set())

    async def test_advertisement_watcher_restarts_a_complete_quiet_window(self):
        watcher = profile_bench.AdvertisementWatcher("AA:BB")
        device = argparse.Namespace(address="AA:BB")
        advertisement = argparse.Namespace(
            service_uuids=[profile_bench.SERVICE_UUID]
        )
        watcher.begin_quiet_interval()
        loop = asyncio.get_running_loop()
        started = loop.time()
        loop.call_later(
            0.05,
            watcher._on_advertisement,
            device,
            advertisement,
        )

        await watcher.wait_for_quiet(100, 500)

        self.assertGreaterEqual(loop.time() - started, 0.14)
        self.assertIsNone(watcher.first_match_ns)
        self.assertFalse(watcher._match_event.is_set())


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


class WaveshareNativeUsbReopenRedTest(unittest.IsolatedAsyncioTestCase):
    async def test_reopen_is_after_measurement_and_before_ble_session(self):
        events = []

        class Reset:
            def prepare_after_advertisement(self):
                events.append("serial-reopened")

        class RawLog:
            def write(self, event, **_fields):
                events.append(("log", event))

        args = argparse.Namespace(
            address="private-test-address",
            expect_chip="esp32-s3",
            profile="waveshare-esp32-s3-lcd-147b",
        )
        connection = mock.AsyncMock()
        caps = {
            "chip": "esp32-s3",
            "mtu": "247",
            "window": "8",
            "chunk": "229",
            "free_mem": "8192",
        }

        async def measured(_reset, _watcher):
            events.append("advertisement-measured")
            return 321

        async def connect(address):
            self.assertEqual(address, args.address)
            events.append("ble-connect")
            return connection

        with (
            mock.patch.object(
                profile_bench,
                "measure_reset_to_advertisement",
                new=measured,
            ),
            mock.patch.object(
                profile_bench.PbleCentral,
                "connect",
                new=connect,
            ),
            mock.patch.object(
                profile_bench,
                "hello",
                new=mock.AsyncMock(
                    return_value=(caps, (247, 8, 229, 8192))
                ),
            ),
        ):
            executor = profile_bench.HardwareExecutor(args, Reset(), RawLog())
            result = await executor.reset_connect_hello(0)

        self.assertEqual(result[0], 321)
        self.assertIn("serial-reopened", events)
        self.assertLess(
            events.index("advertisement-measured"),
            events.index("serial-reopened"),
        )
        self.assertLess(
            events.index("serial-reopened"),
            events.index("ble-connect"),
        )


class EvidenceAndCliTest(unittest.TestCase):
    def test_waveshare_cli_forbids_serial_reset_port(self):
        required = [
            "--mode",
            "baseline",
            "--profile",
            "waveshare-esp32-s3-lcd-147b",
            "--expect-chip",
            "esp32-s3",
            "--address",
            "test-address",
            "--operator-reset",
            "--application-bin",
            "application.bin",
            "--partition-table-bin",
            "partition-table.bin",
            "--raw-log",
            "raw.jsonl",
            "--output",
            "observation.json",
        ]
        with mock.patch.object(sys, "stderr", mock.MagicMock()):
            try:
                args = profile_bench._parse_args(required)
            except SystemExit:
                self.fail(
                    "HAND-OFF [green]: Waveshare must not require a serial port"
                )
        self.assertIsNone(args.reset_port)
        with mock.patch.object(sys, "stderr", mock.MagicMock()):
            with self.assertRaises(SystemExit):
                profile_bench._parse_args(
                    required + ["--reset-port", "/dev/test-native-usb"]
                )

    def test_waveshare_operator_reset_prompts_are_frozen(self):
        self.assertEqual(
            profile_bench.WAVESHARE_RESET_HOLD_PROMPT,
            "Press and hold RESET on the Waveshare ESP32-S3-LCD-1.47B, "
            "keep holding it, then press Enter: ",
        )
        self.assertEqual(
            profile_bench.WAVESHARE_RESET_RELEASE_PROMPT,
            "Release RESET now, then press Enter immediately: ",
        )

    def test_waveshare_controller_prompts_without_control_line_reset(self):
        control_events = []
        prompts = []

        class Device:
            port = None
            baudrate = None
            timeout = None
            write_timeout = None
            dsrdtr = None
            rtscts = None
            in_waiting = 0

            @property
            def rts(self):
                return False

            @rts.setter
            def rts(self, value):
                control_events.append(("rts", value))

            @property
            def dtr(self):
                return False

            @dtr.setter
            def dtr(self, value):
                control_events.append(("dtr", value))

            def open(self):
                return None

            def reset_input_buffer(self):
                return None

            def close(self):
                return None

        serial_module = argparse.Namespace(Serial=lambda: Device())
        with mock.patch.dict(sys.modules, {"serial": serial_module}):
            controller = profile_bench.WaveshareOperatorResetController(
                "/dev/test-native-usb",
                115200,
                operator_action=prompts.append,
            )
            pre_actions = list(control_events)
            controller.assert_reset()
            controller.release_reset()
            self.assertEqual(control_events, pre_actions)
            controller.close()

        self.assertEqual(
            prompts,
            [
                "Press and hold RESET on the Waveshare ESP32-S3-LCD-1.47B, "
                "keep holding it, then press Enter: ",
                "Release RESET now, then press Enter immediately: ",
            ],
        )

    def test_waveshare_native_usb_never_touches_rts_or_dtr(self):
        control_events = []
        devices = []

        class Device:
            port = None
            baudrate = None
            timeout = None
            write_timeout = None
            dsrdtr = None
            rtscts = None
            in_waiting = 0

            @property
            def rts(self):
                return False

            @rts.setter
            def rts(self, value):
                control_events.append(("rts", value))

            @property
            def dtr(self):
                return False

            @dtr.setter
            def dtr(self, value):
                control_events.append(("dtr", value))

            def open(self):
                return None

            def reset_input_buffer(self):
                return None

            def close(self):
                return None

        def serial_factory():
            device = Device()
            devices.append(device)
            return device

        serial_module = argparse.Namespace(Serial=serial_factory)
        with mock.patch.dict(sys.modules, {"serial": serial_module}):
            controller = profile_bench.WaveshareOperatorResetController(
                "/dev/test-native-usb",
                115200,
                operator_action=lambda _prompt: None,
            )
            self.assertEqual(control_events, [])
            controller.assert_reset()
            controller.release_reset()
            controller.prepare_after_advertisement()
            controller.close()

        self.assertEqual(len(devices), 2)
        self.assertEqual(control_events, [])

    def test_waveshare_posix_open_never_applies_rts_or_dtr(self):
        control_events = []
        devices = []

        class PosixSerialOpenModel:
            """Model pyserial's serialposix.Serial.open control-line branch."""

            port = None
            baudrate = None
            timeout = None
            write_timeout = None
            in_waiting = 0

            def __init__(self, index):
                self.index = index
                self._dsrdtr = False
                self._rtscts = False
                self._dtr_state = True
                self._rts_state = True

            @property
            def dsrdtr(self):
                return self._dsrdtr

            @dsrdtr.setter
            def dsrdtr(self, value):
                self._dsrdtr = value

            @property
            def rtscts(self):
                return self._rtscts

            @rtscts.setter
            def rtscts(self, value):
                self._rtscts = value

            def open(self):
                # pyserial's POSIX backend performs both state updates on
                # every open when the corresponding flow control is false.
                if not self._dsrdtr:
                    control_events.append(
                        ("dtr", self.index, self._dtr_state)
                    )
                if not self._rtscts:
                    control_events.append(
                        ("rts", self.index, self._rts_state)
                    )

            def reset_input_buffer(self):
                return None

            def close(self):
                return None

        def serial_factory():
            device = PosixSerialOpenModel(len(devices))
            devices.append(device)
            return device

        serial_module = argparse.Namespace(Serial=serial_factory)
        with mock.patch.dict(sys.modules, {"serial": serial_module}):
            controller = profile_bench.WaveshareOperatorResetController(
                "/dev/test-native-usb",
                115200,
                operator_action=lambda _prompt: None,
            )
            controller.assert_reset()
            controller.release_reset()
            controller.prepare_after_advertisement()
            controller.close()

        self.assertEqual(len(devices), 2)
        self.assertEqual(control_events, [])

    def test_waveshare_closes_stale_usb_while_held_then_reopens_fresh(self):
        events = []
        devices = []

        class Device:
            port = None
            baudrate = None
            timeout = None
            write_timeout = None
            dsrdtr = None
            rtscts = None
            in_waiting = 0

            def __init__(self, index):
                self.index = index

            def open(self):
                events.append(("open", self.index))

            def reset_input_buffer(self):
                events.append(("reset-input", self.index))

            def close(self):
                events.append(("close", self.index))
                if self.index == 0:
                    raise OSError(errno.ENODEV, "native USB reset")

        def serial_factory():
            device = Device(len(devices))
            devices.append(device)
            return device

        def operator_action(prompt):
            if prompt == profile_bench.WAVESHARE_RESET_HOLD_PROMPT:
                events.append("reset-held-confirmed")
            elif prompt == profile_bench.WAVESHARE_RESET_RELEASE_PROMPT:
                events.append("reset-released-confirmed")
            else:
                self.fail("unexpected operator prompt")

        serial_module = argparse.Namespace(Serial=serial_factory)
        with mock.patch.dict(sys.modules, {"serial": serial_module}):
            controller = profile_bench.WaveshareOperatorResetController(
                "/dev/test-native-usb",
                115200,
                operator_action=operator_action,
            )
            controller.assert_reset()
            self.assertIn(("close", 0), events)
            self.assertLess(
                events.index("reset-held-confirmed"),
                events.index(("close", 0)),
            )
            controller.release_reset()
            events.append("advertisement-measured")
            controller.prepare_after_advertisement()

            self.assertLess(
                events.index("advertisement-measured"),
                events.index(("open", 1)),
            )
            self.assertEqual(devices[1].port, "/dev/test-native-usb")
            self.assertEqual(devices[1].baudrate, 115200)
            controller.close()

        self.assertEqual(
            events.count("reset-held-confirmed"),
            1,
        )
        self.assertEqual(
            events.count("reset-released-confirmed"),
            1,
        )

    def test_waveshare_run_selects_operator_reset_controller(self):
        args = argparse.Namespace(
            mode="verify",
            profile="waveshare-esp32-s3-lcd-147b",
            expect_chip="esp32-s3",
            address="test-address",
            reset_port=None,
            reset_baud=115200,
            application_bin="application.bin",
            partition_table_bin="partition-table.bin",
            operator_reset=True,
            firmware_bin=None,
            firmware_uf2=None,
            policy="oi1-gates.json",
            raw_log="raw.jsonl",
            output="observation.json",
            board_manufacturer="Waveshare",
            board_model="ESP32-S3-LCD-1.47B",
            module_marking="ESP32-S3-WROOM-1-N16R8",
            device_flash_capacity_bytes=16 * 1024 * 1024,
            device_psram_capacity_bytes=8 * 1024 * 1024,
            firmware_sha256=None,
            manifest_sha256="b" * 64,
            install_sha256="a" * 64,
            ble_backend="CoreBluetooth",
            ble_adapter="built-in",
        )
        oi1_build = {
            "application_image_bytes": 100,
            "factory_partition_bytes": 200,
            "application_headroom_bytes": 100,
        }
        observation = {"raw_log_sha256": "c" * 64}
        raw_log = mock.MagicMock()
        operator_reset = mock.MagicMock()
        executor = mock.MagicMock()

        async def run_case():
            with (
                mock.patch.object(
                    profile_bench,
                    "oi1_build_from_paths",
                    return_value=oi1_build,
                ),
                mock.patch.object(
                    profile_bench,
                    "RedactedRawLog",
                    return_value=raw_log,
                ),
                mock.patch.object(
                    profile_bench,
                    "WavesharePromptResetController",
                    return_value=operator_reset,
                ) as waveshare_controller,
                mock.patch.object(
                    profile_bench,
                    "WaveshareOperatorResetController",
                ) as serial_waveshare_controller,
                mock.patch.object(
                    profile_bench,
                    "SerialResetController",
                ) as serial_controller,
                mock.patch.object(
                    profile_bench,
                    "WaveshareHardwareExecutor",
                    return_value=executor,
                ) as hardware_executor,
                mock.patch.object(
                    profile_bench,
                    "collect_observation",
                    new=mock.AsyncMock(return_value=observation),
                ),
                mock.patch.object(
                    profile_bench,
                    "_load_policy_thresholds",
                    return_value={},
                ),
                mock.patch.object(profile_bench, "evaluate_thresholds"),
                mock.patch.object(
                    profile_bench,
                    "build_baseline_profile",
                    return_value={"profile_id": args.profile},
                ),
                mock.patch.object(
                    profile_bench,
                    "output_for_mode",
                    return_value=observation,
                ),
                mock.patch.object(profile_bench, "atomic_write_canonical_json"),
            ):
                result = await profile_bench._run(args)

            self.assertEqual(result, 0)
            waveshare_controller.assert_called_once_with()
            serial_waveshare_controller.assert_not_called()
            serial_controller.assert_not_called()
            hardware_executor.assert_called_once_with(
                args,
                operator_reset,
                raw_log,
            )

        asyncio.run(run_case())

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
        reset_index = waveshare.index("--reset-port")
        waveshare = waveshare[:reset_index] + waveshare[reset_index + 2 :]
        with self.assertRaises(SystemExit):
            profile_bench._parse_args(waveshare)
        waveshare += ["--operator-reset"]
        waveshare_args = profile_bench._parse_args(waveshare)
        self.assertEqual(
            waveshare_args.profile,
            "waveshare-esp32-s3-lcd-147b",
        )
        self.assertEqual(waveshare_args.expect_chip, "esp32-s3")
        self.assertIsNone(waveshare_args.reset_port)
        with self.assertRaises(SystemExit):
            profile_bench._parse_args(
                waveshare + ["--reset-port", "/dev/test-native-usb"]
            )
        for profile_id, chip in (
            ("esp32-4mb", "esp32"),
            ("esp32-s3-n16r8", "esp32-s3"),
            ("esp32-c3-4mb", "esp32-c3"),
        ):
            scoped = list(required)
            scoped[scoped.index("esp32-4mb")] = profile_id
            scoped[scoped.index("esp32")] = chip
            with self.subTest(operator_reset_forbidden=profile_id):
                with self.assertRaises(SystemExit):
                    profile_bench._parse_args(scoped + ["--operator-reset"])
            serial_index = scoped.index("--reset-port")
            without_serial = scoped[:serial_index] + scoped[serial_index + 2 :]
            with self.subTest(reset_port_required=profile_id):
                with self.assertRaises(SystemExit):
                    profile_bench._parse_args(without_serial)
        for missing_flag in ("--reset-port", "--raw-log", "--output"):
            with self.subTest(missing=missing_flag):
                index = required.index(missing_flag)
                without = required[:index] + required[index + 2 :]
                with self.assertRaises(SystemExit):
                    profile_bench._parse_args(without)
        c3 = list(required)
        c3[c3.index("esp32-4mb")] = "esp32-c3-4mb"
        c3[c3.index("esp32")] = "esp32-c3"
        self.assertEqual(profile_bench._parse_args(c3).profile, "esp32-c3-4mb")
        pico = list(required)
        pico[pico.index("esp32-4mb")] = "rpi-pico2-w"
        pico[pico.index("esp32")] = "rpi-pico2-w"
        with self.assertRaises(SystemExit):
            profile_bench._parse_args(pico)
        pico_only = [
            "--mode",
            "baseline",
            "--profile",
            "rpi-pico2-w",
            "--expect-chip",
            "rpi-pico2-w",
            "--address",
            "test-address",
            "--operator-reset",
            "--firmware-bin",
            "firmware.bin",
            "--firmware-uf2",
            "firmware.uf2",
            "--raw-log",
            "raw.jsonl",
            "--output",
            "observation.json",
        ]
        self.assertEqual(
            profile_bench._parse_args(pico_only).profile,
            "rpi-pico2-w",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
