#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for the real RP2 branch of the OI-1 profile bench.

Every dependency below is a host fake.  The suite never scans, opens a tty,
flashes a board, or claims a qualification result.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import redirect_stderr
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock


HOST_DIR = Path(__file__).resolve().parent
HIL_DIR = HOST_DIR.parent / "hil"
sys.path.insert(0, str(HIL_DIR))

import _pble_bench as bench  # noqa: E402
import oi1_profile_bench as profile_bench  # noqa: E402


PICO_PROFILE = "rpi-pico2-w"
RP2_IMAGE_LIMIT_BYTES = 1_572_864
RP2_BUILD_KEYS = {
    "firmware_bin_bytes",
    "firmware_image_limit_bytes",
    "firmware_image_headroom_bytes",
}
RP2_HEAP_KEYS = {"gc_free_bytes", "gc_allocated_bytes"}
RP2_LINK_FACTS = {
    "ble_host": "btstack",
    "observed_att_mtu": 247,
    "observed_window": 4,
    "observed_chunk_bytes": 229,
    "console_tx_budget_ms": 103,
}


def _rp2_observation() -> dict:
    heap = {"gc_free_bytes": 9001, "gc_allocated_bytes": 1000}
    durations = [1_000_000_000] * 5
    return {
        "observed_att_mtu": 247,
        "observed_window": 4,
        "observed_chunk_bytes": 229,
        "reset_to_service_advertisement_ms": [100] * 10,
        "heap_default_free_post_hello_bytes": [8192] * 10,
        "heap_post_hello": [dict(heap) for _ in range(10)],
        "put_unique_committed_bytes": [65536] * 5,
        "put_duration_ns": durations,
        "put_committed_goodput_bytes_per_second": [65536] * 5,
        "get_unique_verified_bytes": [65536] * 5,
        "get_duration_ns": durations,
        "get_verified_goodput_bytes_per_second": [65536] * 5,
        "put_retransmitted_chunks": [0] * 5,
        "put_retransmitted_bytes": [0] * 5,
        "get_retransmitted_chunks": [0] * 5,
        "get_retransmitted_bytes": [0] * 5,
        "roundtrip_integrity_verified": 5,
        "get_offset_sequences_validated": 5,
        "roundtrip_unexpected_disconnects": 0,
        "roundtrip_integrity_failures": 0,
        "heap_post_roundtrip": [dict(heap) for _ in range(5)],
        "reliability": {
            "attempted_files": 20,
            "completed_files": 20,
            "verified_files": 20,
            "bytes_per_file": 16384,
            "total_payload_bytes": 327680,
            "unexpected_disconnects": 0,
            "integrity_failures": 0,
            "failed_statuses": 0,
            "retransmitted_chunks": 0,
            "retransmitted_bytes": 0,
            "rewinds": 0,
        },
        "heap_post_reliability": dict(heap),
        "transfer_link_facts": dict(RP2_LINK_FACTS),
        "physical_power_cycle_advertising": "passed",
        "raw_log_sha256": "a" * 64,
    }


def _common_cli(profile: str, chip: str) -> list[str]:
    return [
        "--mode",
        "baseline",
        "--profile",
        profile,
        "--expect-chip",
        chip,
        "--address",
        "private-test-address",
        "--raw-log",
        "raw.jsonl",
        "--output",
        "profile.json",
    ]


def _esp_cli() -> list[str]:
    return _common_cli("esp32-4mb", "esp32") + [
        "--reset-port",
        "/dev/private-test-reset",
        "--application-bin",
        "application.bin",
        "--partition-table-bin",
        "partition-table.bin",
    ]


def _rp2_cli() -> list[str]:
    return _common_cli(PICO_PROFILE, PICO_PROFILE) + [
        "--operator-reset",
        "--firmware-bin",
        "firmware.bin",
        "--firmware-uf2",
        "firmware.uf2",
    ]


def _uf2_block(
    *,
    flags: int,
    address: int,
    payload: bytes,
    block_number: int,
    total_blocks: int,
    family: int,
) -> bytes:
    block = bytearray(512)
    struct.pack_into(
        "<IIIIIIII",
        block,
        0,
        0x0A324655,
        0x9E5D5157,
        flags,
        address,
        len(payload),
        block_number,
        total_blocks,
        family,
    )
    block[32 : 32 + len(payload)] = payload
    struct.pack_into("<I", block, 508, 0x0AB16F30)
    return bytes(block)


def _rp2350_uf2(raw_image: bytes) -> bytes:
    padded = bytes(raw_image)
    padded += b"\0" * ((-len(padded)) % 256)
    arm_count = len(padded) // 256
    blocks = [
        _uf2_block(
            flags=0x00002000,
            address=0x10000000 + index * 256,
            payload=padded[index * 256 : (index + 1) * 256],
            block_number=index,
            total_blocks=arm_count,
            family=0xE48BFF59,
        )
        for index in range(arm_count)
    ]
    blocks.append(
        _uf2_block(
            flags=0x0000A000,
            address=0x10FFFF00,
            payload=b"\0" * 256,
            block_number=0,
            total_blocks=2,
            family=0xE48BFF57,
        )
    )
    return b"".join(blocks)


class Rp2CliDiscriminationTests(unittest.TestCase):
    def test_existing_esp_cli_stays_unchanged(self):
        with redirect_stderr(io.StringIO()):
            args = profile_bench._parse_args(_esp_cli())

        self.assertEqual(args.profile, "esp32-4mb")
        self.assertEqual(args.reset_port, "/dev/private-test-reset")
        self.assertEqual(args.application_bin, "application.bin")
        self.assertEqual(args.partition_table_bin, "partition-table.bin")
        self.assertFalse(args.operator_reset)
        self.assertIsNone(args.firmware_bin)
        self.assertIsNone(args.firmware_uf2)
        self.assertFalse(hasattr(args, "console_tx_budget_ms"))

    def test_rp2_cli_requires_only_rp2_artifacts_and_operator_reset(self):
        with redirect_stderr(io.StringIO()):
            args = profile_bench._parse_args(_rp2_cli())

        self.assertEqual(args.profile, PICO_PROFILE)
        self.assertTrue(args.operator_reset)
        self.assertEqual(args.firmware_bin, "firmware.bin")
        self.assertEqual(args.firmware_uf2, "firmware.uf2")
        self.assertFalse(hasattr(args, "console_tx_budget_ms"))
        self.assertIsNone(args.reset_port)
        self.assertIsNone(args.application_bin)
        self.assertIsNone(args.partition_table_bin)

    def test_rp2_cli_rejects_missing_or_mixed_esp_inputs(self):
        invalid = {
            "missing-operator-reset": [
                value
                for value in _rp2_cli()
                if value != "--operator-reset"
            ],
            "missing-uf2": _rp2_cli()[:-2],
            "operator-pacing-override": _rp2_cli()
            + ["--console-tx-budget-ms", "1"],
            "serial-reset": _rp2_cli()
            + ["--reset-port", "/dev/private-test-reset"],
            "esp-artifacts": _rp2_cli()
            + [
                "--application-bin",
                "application.bin",
                "--partition-table-bin",
                "partition-table.bin",
            ],
        }
        for label, argv in invalid.items():
            with self.subTest(label=label), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    profile_bench._parse_args(argv)

    def test_esp_cli_rejects_rp2_only_inputs(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            profile_bench._parse_args(
                _esp_cli()
                + [
                    "--operator-reset",
                    "--firmware-bin",
                    "firmware.bin",
                    "--firmware-uf2",
                    "firmware.uf2",
                ]
            )


class Rp2BuildAndHeapTests(unittest.TestCase):
    def test_rp2_build_facts_bind_matching_raw_bin_and_uf2(self):
        raw_image = bytes(range(256))
        with tempfile.TemporaryDirectory(prefix="pyble-rp2-oi1-build-") as tmp:
            root = Path(tmp)
            firmware_bin = root / "firmware.bin"
            firmware_uf2 = root / "firmware.uf2"
            firmware_bin.write_bytes(raw_image)
            firmware_uf2.write_bytes(_rp2350_uf2(raw_image))

            build = profile_bench.rp2_oi1_build_from_paths(
                firmware_bin,
                firmware_uf2,
            )

        self.assertEqual(set(build), RP2_BUILD_KEYS)
        self.assertEqual(build["firmware_bin_bytes"], len(raw_image))
        self.assertEqual(
            build["firmware_image_limit_bytes"],
            RP2_IMAGE_LIMIT_BYTES,
        )
        self.assertEqual(
            build["firmware_image_headroom_bytes"],
            RP2_IMAGE_LIMIT_BYTES - len(raw_image),
        )

    def test_rp2_build_rejects_over_limit_or_nonmatching_uf2(self):
        with tempfile.TemporaryDirectory(prefix="pyble-rp2-oi1-invalid-") as tmp:
            root = Path(tmp)
            firmware_bin = root / "firmware.bin"
            firmware_uf2 = root / "firmware.uf2"

            firmware_bin.write_bytes(b"x" * (RP2_IMAGE_LIMIT_BYTES + 1))
            firmware_uf2.write_bytes(_rp2350_uf2(b"x" * 256))
            with self.assertRaises(bench.BenchError):
                profile_bench.rp2_oi1_build_from_paths(
                    firmware_bin,
                    firmware_uf2,
                )

            firmware_bin.write_bytes(b"a" * 256)
            firmware_uf2.write_bytes(_rp2350_uf2(b"b" * 256))
            with self.assertRaises(bench.BenchError):
                profile_bench.rp2_oi1_build_from_paths(
                    firmware_bin,
                    firmware_uf2,
                )

    def test_rp2_heap_probe_is_gc_only_and_strict(self):
        source = profile_bench.rp2_heap_probe_source("nonce")
        self.assertIn("import gc", source)
        self.assertNotIn("esp32", source)
        self.assertEqual(
            profile_bench.parse_rp2_heap_probe_output(
                [b"noise\n__PYBLE_OI1_HEAP_nonce=9001,1000\n"],
                "nonce",
            ),
            {"gc_free_bytes": 9001, "gc_allocated_bytes": 1000},
        )
        with self.assertRaises(bench.BenchError):
            profile_bench.parse_rp2_heap_probe_output(
                [b"__PYBLE_OI1_HEAP_nonce=9001,1000,1,1,1\n"],
                "nonce",
            )

    def test_rp2_thresholds_and_observation_are_target_discriminated(self):
        build = {
            "firmware_bin_bytes": 256,
            "firmware_image_limit_bytes": RP2_IMAGE_LIMIT_BYTES,
            "firmware_image_headroom_bytes": RP2_IMAGE_LIMIT_BYTES - 256,
        }
        observation = _rp2_observation()
        self.assertIs(
            bench.validate_observation(observation, profile_id=PICO_PROFILE),
            observation,
        )
        thresholds = bench.derive_thresholds(build, observation)
        self.assertEqual(
            thresholds,
            {
                "firmware_bin_max_bytes": 256,
                "firmware_image_headroom_min_bytes": (
                    RP2_IMAGE_LIMIT_BYTES - 256
                ),
                "gc_free_min_bytes": 8192,
                "reset_to_service_advertisement_max_ms": 3000,
                "put_committed_goodput_min_bytes_per_second": 62200,
                "get_verified_goodput_min_bytes_per_second": 62200,
            },
        )
        self.assertEqual(
            bench.evaluate_thresholds(build, observation, thresholds),
            thresholds,
        )

        contaminated = _rp2_observation()
        contaminated["heap_post_hello"][0]["idf_internal_free_bytes"] = 1
        with self.assertRaises(bench.BenchError):
            bench.validate_observation(
                contaminated,
                profile_id=PICO_PROFILE,
            )

    def test_rp2_baseline_fragment_binds_install_and_resource_hashes(self):
        profile = profile_bench.build_baseline_profile(
            profile_id=PICO_PROFILE,
            board_manufacturer="Raspberry Pi",
            board_model="Pico 2 W",
            module_marking="RP2350 + CYW43439",
            device_flash_capacity_bytes=4 * 1024 * 1024,
            device_psram_capacity_bytes=0,
            firmware_sha256="1" * 64,
            manifest_sha256=None,
            install_sha256="2" * 64,
            resource_image_sha256="1" * 64,
            environment={
                "desktop_os": "host-fake",
                "ble_backend": "host-fake",
                "ble_adapter": "host-fake",
                "python_version": "host-fake",
            },
            oi1_build={},
            oi1_observation={},
        )
        self.assertEqual(profile["resource_kind"], "rp2")
        self.assertEqual(profile["install_sha256"], "2" * 64)
        self.assertEqual(profile["resource_image_sha256"], "1" * 64)
        self.assertNotIn("manifest_sha256", profile)
        self.assertNotIn("firmware_sha256", profile)


class _FakeLog:
    def __init__(self):
        self.records = []

    def write(self, event, **fields):
        self.records.append((event, fields))

    def sha256(self):
        return "a" * 64


class _FakeRp2Reset:
    """Deliberately has no UART buffer API."""

    def __init__(self):
        self.actions = []

    def assert_reset(self):
        self.actions.append("assert_reset")

    def release_reset(self):
        self.actions.append("release_reset")

    def power_off(self):
        self.actions.append("power_off")

    def power_on(self):
        self.actions.append("power_on")

    def close(self, **_kwargs):
        self.actions.append("close")


class Rp2ExecutorTests(unittest.IsolatedAsyncioTestCase):
    def _executor(self):
        args = argparse.Namespace(
            address="private-test-address",
            expect_chip=PICO_PROFILE,
            profile=PICO_PROFILE,
        )
        reset = _FakeRp2Reset()
        log = _FakeLog()
        return profile_bench.Rp2HardwareExecutor(args, reset, log), reset, log

    async def test_btstack_facts_and_heap_never_use_the_esp_uart_path(self):
        executor, reset, log = self._executor()
        connection = mock.AsyncMock()
        connection.backend_mtu = 247
        caps = {
            "chip": PICO_PROFILE,
            "mtu": "247",
            "window": "4",
            "chunk": "229",
            "free_mem": "8192",
        }

        with (
            mock.patch.object(
                profile_bench,
                "LinkFactParser",
                side_effect=AssertionError("RP2 must not parse ESP UART facts"),
            ),
            mock.patch.object(
                profile_bench,
                "measure_reset_to_advertisement",
                new=mock.AsyncMock(return_value=123),
            ),
            mock.patch.object(
                profile_bench.PbleCentral,
                "connect",
                new=mock.AsyncMock(return_value=connection),
            ),
            mock.patch.object(
                profile_bench,
                "hello",
                new=mock.AsyncMock(return_value=(caps, (247, 4, 229, 8192))),
            ),
            mock.patch.object(
                profile_bench,
                "run_heap_probe",
                side_effect=AssertionError("RP2 must not import esp32 for heap"),
            ),
            mock.patch.object(
                profile_bench,
                "run_rp2_heap_probe",
                new=mock.AsyncMock(
                    return_value={
                        "gc_free_bytes": 9001,
                        "gc_allocated_bytes": 1000,
                    }
                ),
                create=True,
            ) as rp2_probe,
        ):
            await executor.begin_transfer_link_capture(PICO_PROFILE)
            latency, got_caps, mtu, got_connection = (
                await executor.reset_connect_hello(9)
            )
            await executor.await_transfer_link_settlement(5000)
            heap = await executor.heap_snapshot(connection)
            facts = await executor.seal_transfer_link_facts(2000)
            await executor.disconnect(connection)

        self.assertEqual((latency, got_caps, mtu, got_connection), (123, caps, 247, connection))
        self.assertEqual(heap, {"gc_free_bytes": 9001, "gc_allocated_bytes": 1000})
        self.assertEqual(set(heap), RP2_HEAP_KEYS)
        self.assertEqual(facts, RP2_LINK_FACTS)
        rp2_probe.assert_awaited_once()
        connection.disconnect.assert_awaited_once()
        self.assertEqual(reset.actions, [])
        self.assertIn(("transfer_link_facts", {"facts": RP2_LINK_FACTS}), log.records)

    async def test_btstack_facts_require_and_bind_the_observed_hello_values(self):
        executor, _reset, _log = self._executor()

        await executor.begin_transfer_link_capture(PICO_PROFILE)
        with self.assertRaisesRegex(
            bench.BenchError,
            "HELLO transport observation",
        ):
            await executor.seal_transfer_link_facts(2000)

        connection = mock.AsyncMock()
        connection.backend_mtu = 247
        caps = {
            "chip": PICO_PROFILE,
            "mtu": "247",
            "window": "4",
            "chunk": "229",
            "free_mem": "8192",
        }
        with (
            mock.patch.object(
                profile_bench,
                "measure_reset_to_advertisement",
                new=mock.AsyncMock(return_value=123),
            ),
            mock.patch.object(
                profile_bench.PbleCentral,
                "connect",
                new=mock.AsyncMock(return_value=connection),
            ),
            mock.patch.object(
                profile_bench,
                "hello",
                new=mock.AsyncMock(return_value=(caps, (247, 4, 229, 8192))),
            ),
        ):
            await executor.reset_connect_hello(9)

        self.assertEqual(
            await executor.seal_transfer_link_facts(2000),
            RP2_LINK_FACTS,
        )

    async def test_rp2_physical_cycle_uses_the_injected_operator_seam(self):
        executor, reset, _log = self._executor()

        class Watcher:
            first_match_ns = None

            def __init__(self, _address):
                self.started = False
                self.stopped = False

            async def start(self):
                self.started = True

            async def wait_for_match(self, _timeout_ms):
                self.first_match_ns = 2
                return 2

            async def stop(self):
                self.stopped = True

        with (
            mock.patch.object(profile_bench, "AdvertisementWatcher", Watcher),
            mock.patch.object(
                profile_bench.asyncio,
                "sleep",
                new=mock.AsyncMock(return_value=None),
            ),
            mock.patch("builtins.input", side_effect=AssertionError("hard-coded input seam")),
        ):
            self.assertEqual(await executor.physical_power_cycle(), "passed")

        self.assertIn("power_off", reset.actions)
        self.assertIn("power_on", reset.actions)
        self.assertLess(
            reset.actions.index("power_off"),
            reset.actions.index("power_on"),
        )


class Rp2RunRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_dispatch_never_constructs_esp_build_or_uart_objects(self):
        args = argparse.Namespace(
            mode="baseline",
            profile=PICO_PROFILE,
            expect_chip=PICO_PROFILE,
            address="private-test-address",
            operator_reset=True,
            firmware_bin="firmware.bin",
            firmware_uf2="firmware.uf2",
            application_bin=None,
            partition_table_bin=None,
            reset_port=None,
            reset_baud=115200,
            policy=None,
            raw_log="raw.jsonl",
            output="profile.json",
            board_manufacturer="Raspberry Pi",
            board_model="Pico 2 W",
            module_marking="RP2350 + CYW43439",
            device_flash_capacity_bytes=4 * 1024 * 1024,
            device_psram_capacity_bytes=0,
            firmware_sha256="1" * 64,
            manifest_sha256=None,
            install_sha256="2" * 64,
            ble_backend="host-fake",
            ble_adapter="host-fake",
        )
        build = {
            "firmware_bin_bytes": 256,
            "firmware_image_limit_bytes": RP2_IMAGE_LIMIT_BYTES,
            "firmware_image_headroom_bytes": RP2_IMAGE_LIMIT_BYTES - 256,
        }
        raw_log = mock.Mock()
        reset = mock.Mock()
        executor = mock.Mock()
        observation = {"target-specific": "host-fake"}

        with (
            mock.patch.object(profile_bench, "_validate_run_metadata"),
            mock.patch.object(
                profile_bench,
                "rp2_oi1_build_from_paths",
                return_value=build,
                create=True,
            ) as rp2_build,
            mock.patch.object(
                profile_bench,
                "oi1_build_from_paths",
                side_effect=AssertionError("RP2 entered ESP build arithmetic"),
            ),
            mock.patch.object(profile_bench, "RedactedRawLog", return_value=raw_log),
            mock.patch.object(
                profile_bench,
                "Rp2OperatorResetController",
                return_value=reset,
                create=True,
            ) as reset_type,
            mock.patch.object(
                profile_bench,
                "SerialResetController",
                side_effect=AssertionError("RP2 opened an ESP reset tty"),
            ),
            mock.patch.object(
                profile_bench,
                "Rp2HardwareExecutor",
                return_value=executor,
                create=True,
            ) as executor_type,
            mock.patch.object(
                profile_bench,
                "HardwareExecutor",
                side_effect=AssertionError("RP2 constructed the ESP executor"),
            ),
            mock.patch.object(
                profile_bench,
                "collect_observation",
                new=mock.AsyncMock(return_value=observation),
            ),
            mock.patch.object(
                profile_bench,
                "build_baseline_profile",
                return_value={"baseline": "host-fake"},
            ),
            mock.patch.object(profile_bench, "output_for_mode", return_value={}),
            mock.patch.object(profile_bench, "atomic_write_canonical_json"),
        ):
            self.assertEqual(await profile_bench._run(args), 0)

        rp2_build.assert_called_once_with("firmware.bin", "firmware.uf2")
        reset_type.assert_called_once_with()
        executor_type.assert_called_once_with(args, reset, raw_log)


if __name__ == "__main__":
    unittest.main(verbosity=2)
