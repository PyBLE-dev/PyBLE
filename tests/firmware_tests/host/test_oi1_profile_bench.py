# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Host-only contract tests for the frozen OI-1 profile HIL bench.  All BLE,
# reset, clock, and file inputs are fakes; no board or serial adapter is used.

import argparse
import asyncio
import hashlib
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
HIL_DIR = HERE.parent / "hil"
sys.path.insert(0, str(HIL_DIR))

import _pble_bench as bench  # noqa: E402
from _pble_central import PbleCentral  # noqa: E402
import _pble_wire as wire  # noqa: E402
import oi1_profile_bench as profile_bench  # noqa: E402


PROFILE_ORDER = ("esp32-4mb", "esp32-s3-n16r8")
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


class FrozenConstantsTest(unittest.TestCase):
    def test_exact_current_profiles_and_workload_are_frozen(self):
        self.assertEqual(tuple(bench.PROFILE_ORDER), PROFILE_ORDER)
        self.assertEqual(
            bench.PROFILE_TARGETS,
            {"esp32-4mb": "esp32", "esp32-s3-n16r8": "esp32-s3"},
        )
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
        with self.assertRaises(ValueError):
            bench.deterministic_payload("esp32-c3-4mb", 0, 65536)


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

    def test_frozen_outward_threshold_rounding(self):
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
                "reset_to_service_advertisement_max_ms": 110,
                "put_committed_goodput_min_bytes_per_second": 32700,
                "get_verified_goodput_min_bytes_per_second": 16300,
            },
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


class WorkloadOrchestrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_exact_sample_counts_and_observation_shape(self):
        class FakeExecutor:
            def __init__(self):
                self.reset_calls = []
                self.heap_calls = []
                self.roundtrip_calls = []
                self.disconnect_calls = []
                self.reliability_calls = 0
                self.power_calls = 0

            async def reset_connect_hello(self, sample_index):
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
                self.disconnect_calls.append(connection)

            async def roundtrip(self, connection, path, payload):
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
                self.power_calls += 1
                return "passed"

            def raw_log_sha256(self):
                return "a" * 64

        fake = FakeExecutor()
        observation = await profile_bench.collect_observation(
            "esp32-s3-n16r8", fake
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
        self.assertEqual(observation["raw_log_sha256"], "a" * 64)
        self.assertEqual(
            fake.disconnect_calls,
            ["connection-%d" % i for i in range(10)],
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
