# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Host-only contract tests for the ADR-0024 boot-splash HIL runner.

BLE, time, operator input, and board output are faked.  The suite never opens a
BLE adapter or a serial port.  A qualification can pass only after an injected
operator callback confirms both frozen visual phases and returns the exact URL
read from the physical QR code.
"""

import asyncio
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import tomllib
import types
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
HIL_DIR = HERE.parent / "hil"
sys.path.insert(0, str(HIL_DIR))

import _pble_wire as wire  # noqa: E402
import _pble_central as central_module  # noqa: E402
import tft_st7789_bench as tft_bench  # noqa: E402
import waveshare_boot_splash_bench as bench  # noqa: E402


with (HERE.parents[2] / "firmware" / "versions.lock").open("rb") as handle:
    SELECTED_AGENT_VERSION = tomllib.load(handle)["pyble"]["agent_version"]


CAPS = (
    b"proto=1\n"
    + ("agent=%s\n" % SELECTED_AGENT_VERSION).encode("ascii")
    + b"chip=esp32-s3\n"
    b"mpy=1.28.0\n"
    b"fs_root=/\n"
    b"mtu=247\n"
    b"window=8\n"
    b"chunk=229\n"
    b"free_mem=7799000\n"
    b"has_sd=0\n"
    b"has_identify=0\n"
    b"identify_led=255\n"
    b"auto_run=0\n"
    b"device_id=personal-device-id-must-not-leak\n"
    b"label=personal-label-must-not-leak\n"
)

QR_ROW_MASKS = (
    0x1FCF87F,
    0x104EE41,
    0x175155D,
    0x1758F5D,
    0x175315D,
    0x1056341,
    0x1FD557F,
    0x0017700,
    0x17C2E7C,
    0x1CA55A2,
    0x097720B,
    0x06A13C1,
    0x0BC7EF7,
    0x181452A,
    0x166F27B,
    0x113A131,
    0x166E1F4,
    0x0019B18,
    0x1FCCD57,
    0x1059B1B,
    0x17597F7,
    0x175C0DF,
    0x175300D,
    0x104E7B9,
    0x1FD207F,
)

EXPECTED_REBOOT_ARM_MARKER = "__PYBLE_SPLASH_V1_REBOOT_ARM=armed"
EXPECTED_LIFECYCLE_STAGE_NAMES = (
    "disabled-reboot",
    "initial-disabled",
    "enable-reboot",
    "enabled-boot",
    "resource-reuse",
    "redraw-reboot",
    "redraw-boot",
    "final-disabled",
)


def response(opcode, request_id, payload=b"", status=wire.ST_OK):
    return wire.Frame(wire.RSP, opcode, request_id, bytes((status,)) + payload)


def event(opcode, payload=b""):
    return wire.Frame(wire.EVT, opcode, 0, payload)


def preflight():
    return {
        "schema_version": 1,
        "profile_id": "waveshare-esp32-s3-lcd-147b",
        "chip": "esp32-s3",
        "board_model": "ESP32-S3-LCD-1.47B",
        "flash_capacity_bytes": 16 * 1024 * 1024,
        "psram_capacity_bytes": 8 * 1024 * 1024,
        "discovery_method": "esptool-read-only",
    }


def candidate_attestation(size_bytes=1_761_808, sha256="cd" * 32):
    spans = [
        {"offset": 0, "size_bytes": 0x9000},
        {"offset": 0x10000, "size_bytes": size_bytes - 0x10000},
    ]
    return {
        "sha256": sha256,
        "size_bytes": sum(item["size_bytes"] for item in spans),
        "spans": spans,
    }


def combined_run_summaries(value):
    keys = {"stdout_bytes", "stdout_marker_bytes", "stderr_bytes", "state_sequence"}
    found = []

    def visit(item):
        if type(item) is dict:
            if set(item) == keys:
                found.append(item)
            else:
                for nested in item.values():
                    visit(nested)
        elif type(item) is list:
            for nested in item:
                visit(nested)

    visit(value)
    return found


def _stdout(line):
    return event(wire.OP_CONSOLE_DATA, b"\x00" + line.encode("ascii") + b"\r\n")


class FakeCentral:
    """A fresh PBLE connection for one frozen lifecycle segment."""

    PROBES = {
        # Every probe runs after HELLO on a live PBLE connection. Disabled
        # proves only that the automatic display path stayed off.
        "initial-disabled": (0, 1, 0, 0, 7_900_000),
        "enabled-boot": (1, 1, 1, 1, 7_895_000),
        "redraw-boot": (1, 1, 1, 1, 7_894_000),
        "final-disabled": (0, 1, 0, 0, 7_900_000),
    }

    def __init__(
        self,
        name,
        *,
        stale_probe_phase=None,
        disconnect_error=False,
        already_dropped=False,
        fail_disable=False,
    ):
        self.name = name
        self.commands = []
        self.command_timeouts = []
        self.events = []
        self.stale_probe_phase = stale_probe_phase
        self.disconnect_error = disconnect_error
        self.already_dropped = already_dropped
        self.fail_disable = fail_disable
        self.disable_attempted = False
        self.is_connected = True
        self.disconnected = False

    def event_cursor(self):
        return len(self.events)

    def events_since(self, cursor):
        return len(self.events), self.events[cursor:]

    async def read_info(self):
        await asyncio.sleep(0)
        return CAPS

    async def disconnect(self):
        if self.already_dropped:
            self.is_connected = False
            raise OSError("link already dropped")
        if self.disconnect_error:
            raise OSError("disconnect failed while link remained connected")
        self.is_connected = False
        self.disconnected = True
        await asyncio.sleep(0)

    async def send_cmd(self, opcode, request_id, payload=b"", timeout=10.0):
        source = bytes(payload)
        self.commands.append((opcode, request_id, source))
        self.command_timeouts.append(timeout)
        if opcode == wire.OP_HELLO:
            return response(opcode, request_id, CAPS)
        if opcode == wire.OP_SOFT_REBOOT:
            return response(opcode, request_id)
        if opcode == wire.OP_STOP:
            return response(opcode, request_id)
        if opcode != wire.OP_RUN:
            raise AssertionError("unexpected opcode 0x%02x" % opcode)

        lines = []
        if tft_bench.CANDIDATE_MARKER.encode("ascii") in source:
            expected = re.search(rb'_expected="([0-9a-f]{64})"', source)
            if expected is None:
                raise AssertionError("candidate probe omitted its expected digest")
            lines.append(
                "%s=%s"
                % (tft_bench.CANDIDATE_MARKER, expected.group(1).decode("ascii"))
            )
        elif bench.ENABLE_MARKER.encode("ascii") in source:
            lines.append("%s=1" % bench.ENABLE_MARKER)
        elif bench.DISABLE_MARKER.encode("ascii") in source:
            self.disable_attempted = True
            if self.fail_disable:
                raise RuntimeError("injected cleanup disable failure")
            lines.append("%s=0,0" % bench.DISABLE_MARKER)
        elif EXPECTED_REBOOT_ARM_MARKER.encode("ascii") in source:
            lines.append(EXPECTED_REBOOT_ARM_MARKER)
        elif bench.REUSE_MARKER.encode("ascii") in source:
            lines.append(
                "%s=7800000,7660000,7799000,1,1,1"
                % bench.REUSE_MARKER
            )
        elif bench.PROBE_MARKER.encode("ascii") in source:
            phase = next(
                (item for item in self.PROBES if item.encode("ascii") in source),
                None,
            )
            if phase is None:
                raise AssertionError("probe source omitted a frozen phase")
            enabled, wait_ready, rendered, backlight, heap = self.PROBES[phase]
            if phase == self.stale_probe_phase:
                self.events.append(event(wire.OP_RUN_STATE, b"\x01"))
                self.events.append(_stdout(bench.STALE_VM_MARKER))
                self.events.append(event(wire.OP_RUN_STATE, b"\x03"))
                return response(opcode, request_id)
            if rendered != int(bool(enabled and wait_ready and backlight)):
                raise AssertionError("fake retained-frame conjunction drifted")
            lines.append(
                "%s=%s,%d,%d,%d,%s,%d"
                % (
                    bench.PROBE_MARKER,
                    phase,
                    enabled,
                    wait_ready,
                    backlight,
                    bench.EXPECTED_FIRMWARE_VERSION,
                    heap,
                )
            )
        else:
            raise AssertionError("unrecognized splash runner source")

        self.events.append(event(wire.OP_RUN_STATE, b"\x01"))
        self.events.extend(_stdout(line) for line in lines)
        self.events.append(event(wire.OP_RUN_STATE, b"\x02"))
        return response(opcode, request_id)


class FakeConnector:
    def __init__(self, centrals, *, clock=None):
        self.centrals = list(centrals)
        self.calls = []
        self.clock = clock

    async def __call__(self, address, *, timeout):
        self.calls.append((address, timeout))
        await asyncio.sleep(0)
        if not self.centrals:
            raise AssertionError("qualification requested an unexpected connection")
        item = self.centrals.pop(0)
        if isinstance(item, tuple):
            delay, item = item
            if self.clock is None:
                raise AssertionError("a delayed connection requires the fake clock")
            await self.clock.sleep(delay)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.delays = []

    def monotonic(self):
        return self.now

    async def sleep(self, seconds):
        if seconds < 0:
            raise AssertionError("negative fake delay")
        self.delays.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)


def ordered_run_sources(centrals):
    return [
        (central_index, command_index, source.decode("ascii", errors="strict"))
        for central_index, central in enumerate(centrals)
        for command_index, (opcode, _request_id, source) in enumerate(
            central.commands
        )
        if opcode == wire.OP_RUN
    ]


def rechain_splash_result(value):
    predecessor = bench.record_sha256(value["binding"])
    for record in value["lifecycle_records"]:
        record["predecessor_sha256"] = predecessor
        record["record_sha256"] = bench.record_sha256(
            {
                key: item
                for key, item in record.items()
                if key != "record_sha256"
            }
        )
        predecessor = record["record_sha256"]
    value["terminal_record_sha256"] = predecessor
    value["record_sha256"] = bench.record_sha256(
        {key: item for key, item in value.items() if key != "record_sha256"}
    )
    return value


class FrozenConstantsTest(unittest.TestCase):
    def test_exact_board_url_qr_and_visual_pattern_are_frozen(self):
        self.assertEqual(bench.SCHEMA_VERSION, 1)
        self.assertEqual(bench.PROFILE_ID, "waveshare-esp32-s3-lcd-147b")
        self.assertEqual(bench.EXPECTED_CHIP, "esp32-s3")
        self.assertEqual(bench.BOARD_MODEL, "ESP32-S3-LCD-1.47B")
        self.assertEqual(bench.EXPECTED_FIRMWARE_VERSION, SELECTED_AGENT_VERSION)
        self.assertEqual(bench.QR_URL, "https://pyble.dev/app")
        self.assertEqual(bench.DEFAULT_OPERATOR_TIMEOUT_S, 900.0)
        self.assertEqual(bench.MAX_OPERATOR_TIMEOUT_S, 900.0)
        self.assertEqual(bench.QR_VERSION, 2)
        self.assertEqual(bench.QR_ECC, "M")
        self.assertEqual(bench.QR_MASK, 2)
        self.assertEqual(bench.QR_SIZE, 25)
        self.assertEqual(bench.QR_ROW_MASKS, QR_ROW_MASKS)
        self.assertEqual(
            bench.QR_MATRIX_SHA256,
            "6b00240151e36ff2fdbb1d556d6f3b0dd75f8fcce13683ea21033e8149687875",
        )
        packed = b"".join(item.to_bytes(4, "big") for item in bench.QR_ROW_MASKS)
        self.assertEqual(hashlib.sha256(packed).hexdigest(), bench.QR_MATRIX_SHA256)
        self.assertEqual(
            bench.SPLASH_PATTERN_ID,
            "waveshare-lcd147b-pyble-boot-splash-v1",
        )

    def test_geometry_wiring_and_resource_threshold_are_exact(self):
        self.assertEqual((bench.WIDTH, bench.HEIGHT), (172, 320))
        self.assertEqual((bench.X_OFFSET, bench.Y_OFFSET), (34, 0))
        self.assertEqual(
            bench.PINS,
            {
                "sck": 40,
                "mosi": 45,
                "cs": 42,
                "dc": 41,
                "reset": 39,
                "backlight": 46,
            },
        )
        self.assertEqual(bench.FRAMEBUFFER_BYTES, 172 * 320 * 2)
        self.assertGreaterEqual(bench.MAX_REUSE_HEAP_DRIFT_BYTES, 0)
        self.assertLess(bench.MAX_REUSE_HEAP_DRIFT_BYTES, bench.FRAMEBUFFER_BYTES)

    def test_lifecycle_chain_reset_retry_and_splash_heap_limits_are_frozen(self):
        self.assertEqual(
            bench.LIFECYCLE_STAGE_NAMES,
            EXPECTED_LIFECYCLE_STAGE_NAMES,
        )
        self.assertEqual(bench.REBOOT_ARM_MARKER, EXPECTED_REBOOT_ARM_MARKER)
        self.assertEqual(
            bench.REBOOT_DELIVERY_GRACE_S,
            tft_bench.REBOOT_DELIVERY_GRACE_S,
        )
        self.assertEqual(bench.RECONNECT_POLL_S, tft_bench.RECONNECT_POLL_S)
        self.assertEqual(bench.MAX_SPLASH_HEAP_DRIFT_BYTES, 8192)
        self.assertGreaterEqual(bench.MAX_SPLASH_HEAP_DRIFT_BYTES, 0)
        self.assertLess(
            bench.MAX_SPLASH_HEAP_DRIFT_BYTES,
            bench.FRAMEBUFFER_BYTES,
        )


class RunSourceContractTest(unittest.TestCase):
    def test_enable_disable_probe_and_reuse_sources_are_deterministic_and_bounded(self):
        builders = [
            (bench.build_enable_source, ()),
            (bench.build_disable_source, ()),
            (bench.build_reuse_source, ()),
        ]
        builders.extend(
            (bench.build_probe_source, (phase, enabled))
            for phase, enabled in (
                ("initial-disabled", False),
                ("enabled-boot", True),
                ("redraw-boot", True),
                ("final-disabled", False),
            )
        )
        for builder, args in builders:
            with self.subTest(builder=builder.__name__, args=args):
                first = builder(*args)
                second = builder(*args)
                self.assertEqual(first, second)
                encoded = first.encode("ascii", errors="strict")
                self.assertLessEqual(len(encoded), bench.RUN_SOURCE_LIMIT)
                for forbidden in (
                    "ble_address",
                    "device_id",
                    "unique_id",
                    "personal",
                    "raw_info",
                ):
                    self.assertNotIn(forbidden, first.lower())

    def test_enable_and_disable_only_use_the_exact_opt_in_adapter(self):
        enabled = bench.build_enable_source()
        self.assertIn("import pyble_waveshare_lcd147b", enabled)
        self.assertIn(".enable_boot_splash()", enabled)
        self.assertIn(".boot_splash_enabled()", enabled)
        self.assertIn(bench.ENABLE_MARKER, enabled)
        self.assertNotIn("ST7789(", enabled)

        disabled = bench.build_disable_source()
        self.assertIn("import pyble_waveshare_lcd147b", disabled)
        self.assertIn(".disable_boot_splash()", disabled)
        self.assertIn(".boot_splash_enabled()", disabled)
        self.assertIn("Pin(46", disabled)
        self.assertIn(bench.DISABLE_MARKER, disabled)
        self.assertNotIn("ST7789(", disabled)

        combined = enabled + disabled
        for invented in (".enable()", ".disable()", ".is_enabled()", ".boot_status()"):
            self.assertNotIn(invented, combined)

    def test_disabled_reboot_is_armed_and_its_probe_rejects_a_stale_vm(self):
        source = bench.build_reboot_arm_source()
        self.assertEqual(source, bench.build_reboot_arm_source())
        self.assertIn(bench.VM_SENTINEL, source)
        self.assertIn(bench.REBOOT_ARM_MARKER, source)
        self.assertNotIn("enable_boot_splash", source)
        self.assertNotIn("disable_boot_splash", source)
        self.assertNotIn("ST7789(", source)
        self.assertLessEqual(len(source.encode("ascii")), bench.RUN_SOURCE_LIMIT)

        disabled_probe = bench.build_probe_source("initial-disabled", False)
        self.assertIn(bench.VM_SENTINEL, disabled_probe)
        self.assertIn(bench.STALE_VM_MARKER, disabled_probe)
        self.assertLess(
            disabled_probe.index(bench.VM_SENTINEL),
            disabled_probe.index("import pyble_waveshare_lcd147b"),
        )

    def test_probe_records_config_ready_render_backlight_version_and_heap(self):
        for phase, enabled, ready in (
            ("initial-disabled", False, True),
            ("enabled-boot", True, True),
            ("redraw-boot", True, True),
            ("final-disabled", False, True),
        ):
            source = bench.build_probe_source(phase, enabled)
            with self.subTest(phase=phase):
                self.assertIn(".boot_splash_enabled()", source)
                self.assertIn("import pble_ble", source)
                self.assertIn("pble_ble.wait_ready(0)", source)
                self.assertIn("Pin(46", source)
                self.assertIn("pyble.__version__", source)
                self.assertIn("gc.collect()", source)
                self.assertIn("gc.mem_free()", source)
                self.assertIn(bench.PROBE_MARKER, source)
                self.assertIn(phase, source)
                self.assertIn("1" if enabled else "0", source)
                self.assertTrue(ready, "post-HELLO probes must always be BLE-ready")
                for invented in (".is_enabled()", ".boot_status()"):
                    self.assertNotIn(invented, source)
        for invalid in (
            ("unknown", True),
            ("enabled-boot", False),
            ("initial-disabled", True),
            (1, False),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(bench.BenchError):
                bench.build_probe_source(*invalid)

    def test_reuse_source_proves_framebuffer_reclamation_and_ordinary_driver_reuse(self):
        source = bench.build_reuse_source()
        for required in (
            "from pyble_st7789 import ST7789",
            "ST7789(1,40000000,0,0",
            "Pin(40,Pin.OUT)",
            "Pin(45,Pin.OUT)",
            "Pin(42,Pin.OUT)",
            "Pin(41,Pin.OUT)",
            "Pin(39,Pin.OUT)",
            "Pin(46,Pin.OUT)",
            "172,320,34,0,True,True",
            ".show()",
            ".deinit()",
            "gc.mem_free()",
            ".boot_splash_enabled()",
            bench.REUSE_MARKER,
        ):
            self.assertIn(required, source)
        self.assertLess(source.index(".show()"), source.index(".deinit()"))
        self.assertNotIn(".is_enabled()", source)
        self.assertNotIn(".boot_status()", source)


class EvidenceParsingTest(unittest.TestCase):
    def _probe_line(self, phase, enabled, ready, backlight, heap=7_800_000):
        return (
            "%s=%s,%d,%d,%d,%s,%d\r\n"
            % (
                bench.PROBE_MARKER,
                phase,
                enabled,
                ready,
                backlight,
                bench.EXPECTED_FIRMWARE_VERSION,
                heap,
            )
        ).encode("ascii")

    def test_probe_evidence_distinguishes_both_boots_and_disabled_states(self):
        cases = (
            ("initial-disabled", False, True, False, False),
            ("enabled-boot", True, True, True, True),
            ("redraw-boot", True, True, True, True),
            ("final-disabled", False, True, False, False),
        )
        for phase, enabled, ready, rendered, backlight in cases:
            line = self._probe_line(
                phase,
                int(enabled),
                int(ready),
                int(backlight),
            )
            with self.subTest(phase=phase):
                parsed = bench.parse_probe_evidence(
                    [line[:11], line[11:]],
                    phase,
                    expected_enabled=enabled,
                )
                self.assertEqual(
                    parsed,
                    {
                        "phase": phase,
                        "enabled": enabled,
                        "wait_ready": ready,
                        "rendered": rendered,
                        "backlight_on": backlight,
                        "firmware_version": SELECTED_AGENT_VERSION,
                        "gc_free_bytes": 7_800_000,
                    },
                )

    def test_probe_rejects_wrong_version_state_readiness_or_duplicate_marker(self):
        valid = self._probe_line("enabled-boot", 1, 1, 1)
        invalid = (
            valid.replace(SELECTED_AGENT_VERSION.encode("ascii"), b"0.4.2"),
            valid.replace(b"enabled-boot,1", b"enabled-boot,0"),
            valid.replace(
                b",1,1,1," + SELECTED_AGENT_VERSION.encode("ascii"),
                b",1,0,1," + SELECTED_AGENT_VERSION.encode("ascii"),
            ),
            valid.replace(
                b",1,1,1," + SELECTED_AGENT_VERSION.encode("ascii"),
                b",1,1,0," + SELECTED_AGENT_VERSION.encode("ascii"),
            ),
            valid + valid,
            valid + (bench.PROBE_MARKER + "=malformed\n").encode("ascii"),
        )
        for value in invalid:
            with self.subTest(value=value[-40:]), self.assertRaises(bench.BenchError):
                bench.parse_probe_evidence(
                    [value],
                    "enabled-boot",
                    expected_enabled=True,
                )

        for phase in ("initial-disabled", "final-disabled"):
            with self.subTest(phase=phase), self.assertRaises(bench.BenchError):
                bench.parse_probe_evidence(
                    [self._probe_line(phase, 0, 0, 0)],
                    phase,
                    expected_enabled=False,
                )

    def test_reuse_evidence_requires_real_allocation_recovery_show_and_cleanup(self):
        valid = (
            "%s=7800000,7660000,7799000,1,1,1\n" % bench.REUSE_MARKER
        ).encode("ascii")
        parsed = bench.parse_reuse_evidence([valid])
        self.assertTrue(parsed["framebuffer_reclaimed"])
        self.assertTrue(parsed["ordinary_driver_reused"])
        self.assertTrue(parsed["enabled_after_reuse"])
        self.assertTrue(parsed["backlight_off_after_reuse"])
        self.assertGreaterEqual(
            parsed["gc_before_bytes"] - parsed["gc_during_bytes"],
            bench.FRAMEBUFFER_BYTES,
        )
        self.assertLessEqual(
            parsed["gc_before_bytes"] - parsed["gc_after_bytes"],
            bench.MAX_REUSE_HEAP_DRIFT_BYTES,
        )

        for invalid in (
            valid.replace(b"7660000", b"7790000"),
            valid.replace(b"7799000", b"7600000"),
            valid.replace(b",1,1,1", b",0,1,1"),
            valid.replace(b",1,1,1", b",1,0,1"),
            valid.replace(b",1,1,1", b",1,1,0"),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(bench.BenchError):
                bench.parse_reuse_evidence([invalid])

    def test_operator_observation_must_be_human_supplied_and_exact(self):
        value = {
            "phase": "enabled-boot",
            "confirmed": True,
            "pattern_id": bench.SPLASH_PATTERN_ID,
            "scanned_url": bench.QR_URL,
        }
        self.assertEqual(bench.validate_operator_observation(value), value)
        for changed in (
            {**value, "confirmed": False},
            {**value, "scanned_url": "https://pyble.dev/#testflight"},
            {**value, "scanned_url": ""},
            {**value, "pattern_id": "similar-looking-pattern"},
            {**value, "phase": "automated-screenshot"},
            {**value, "device_id": "must-not-be-recorded"},
        ):
            with self.subTest(changed=changed), self.assertRaises(bench.BenchError):
                bench.validate_operator_observation(changed)


class QualificationWorkflowTest(unittest.IsolatedAsyncioTestCase):
    CANDIDATE_SIZE = 1_761_808

    def _connections(self):
        return [
            FakeCentral("disabled-enable-reboot"),
            FakeCentral("enabled-boot"),
            FakeCentral("reuse-reboot"),
            FakeCentral("redraw-disable"),
        ]

    async def _run(self, callback=None):
        connections = self._connections()
        connector = FakeConnector(connections)
        observations = []

        async def confirm_visual(phase, pattern_id, qr_url):
            observations.append((phase, pattern_id, qr_url))
            if callback is None:
                return qr_url
            return callback(phase, pattern_id, qr_url)

        result = await bench.run_qualification(
            connector,
            "private-input-only",
            preflight(),
            "ab" * 32,
            self.CANDIDATE_SIZE,
            candidate_attestation(self.CANDIDATE_SIZE),
            timeout_s=2.0,
            poll_interval_s=0,
            confirm_visual=confirm_visual,
            session_id="12" * 16,
        )
        return result, connector, connections, observations

    async def test_full_disabled_enabled_redraw_reuse_and_disable_lifecycle(self):
        result, connector, connections, observations = await self._run()

        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["stage"], "qualification")
        self.assertEqual(result["session_id"], "12" * 16)
        self.assertEqual(result["candidate_firmware_sha256"], "ab" * 32)
        self.assertEqual(result["candidate_firmware_size_bytes"], self.CANDIDATE_SIZE)
        self.assertEqual(
            result["binding"],
            {
                "session_id": "12" * 16,
                "candidate_firmware_sha256": "ab" * 32,
                "candidate_firmware_size_bytes": self.CANDIDATE_SIZE,
                "candidate_attestation": candidate_attestation(self.CANDIDATE_SIZE),
            },
        )
        self.assertEqual(result["firmware_version"], SELECTED_AGENT_VERSION)
        self.assertEqual(result["profile_id"], "waveshare-esp32-s3-lcd-147b")
        self.assertEqual(result["board_model"], "ESP32-S3-LCD-1.47B")
        self.assertEqual(
            result["qr"],
            {
                "url": bench.QR_URL,
                "version": 2,
                "ecc": "M",
                "mask": 2,
                "size": 25,
                "matrix_sha256": bench.QR_MATRIX_SHA256,
                "pattern_id": bench.SPLASH_PATTERN_ID,
            },
        )

        lifecycle = result["lifecycle"]
        self.assertFalse(lifecycle["initial_disabled"]["enabled"])
        self.assertTrue(lifecycle["initial_disabled"]["wait_ready"])
        self.assertFalse(lifecycle["initial_disabled"]["rendered"])
        self.assertFalse(lifecycle["initial_disabled"]["backlight_on"])
        self.assertTrue(lifecycle["enable_persisted"])
        self.assertTrue(lifecycle["first_soft_reboot_acknowledged"])
        self.assertTrue(lifecycle["enabled_boot"]["enabled"])
        self.assertTrue(lifecycle["enabled_boot"]["wait_ready"])
        self.assertTrue(lifecycle["enabled_boot"]["rendered"])
        self.assertTrue(lifecycle["enabled_boot"]["backlight_on"])
        self.assertTrue(lifecycle["resource_reuse"]["framebuffer_reclaimed"])
        self.assertTrue(lifecycle["resource_reuse"]["ordinary_driver_reused"])
        self.assertTrue(lifecycle["second_soft_reboot_acknowledged"])
        self.assertTrue(lifecycle["redraw_boot"]["wait_ready"])
        self.assertTrue(lifecycle["redraw_boot"]["rendered"])
        self.assertTrue(lifecycle["disable_persisted"])
        self.assertFalse(lifecycle["final_disabled"]["enabled"])
        self.assertTrue(lifecycle["final_disabled"]["wait_ready"])
        self.assertFalse(lifecycle["final_disabled"]["rendered"])
        self.assertFalse(lifecycle["final_disabled"]["backlight_on"])

        self.assertEqual(
            observations,
            [
                ("enabled-boot", bench.SPLASH_PATTERN_ID, bench.QR_URL),
                ("redraw-boot", bench.SPLASH_PATTERN_ID, bench.QR_URL),
            ],
        )
        self.assertEqual(
            [item["scanned_url"] for item in result["operator_observations"]],
            [bench.QR_URL, bench.QR_URL],
        )
        self.assertEqual(result["connection_evidence"]["fresh_reconnects"], 3)
        self.assertEqual(
            result["connection_evidence"]["hello_while_splash_visible"],
            ["enabled-boot", "redraw-boot"],
        )
        self.assertEqual(len(connector.calls), 4)
        self.assertTrue(all(item.disconnected for item in connections))
        for central in connections:
            self.assertEqual(
                central.commands[0][0],
                wire.OP_HELLO,
                "%s did not begin with HELLO" % central.name,
            )
        self.assertEqual(
            sum(
                call[0] == wire.OP_SOFT_REBOOT
                for central in connections
                for call in central.commands
            ),
            3,
        )
        self.assertIs(bench.validate_qualification_result(result), result)

        encoded = json.dumps(result, sort_keys=True)
        for forbidden in (
            "private-input-only",
            "personal-device-id",
            "personal-label",
            "ble_address",
            "device_id",
            "raw_info",
            "stdout_chunks",
        ):
            self.assertNotIn(forbidden, encoded)

    async def test_disabled_state_reboots_into_a_fresh_vm_before_enable(self):
        result, connector, connections, _observations = await self._run()
        sources = ordered_run_sources(connections)
        soft_reboots = [
            central_index
            for central_index, central in enumerate(connections)
            for opcode, _request_id, _source in central.commands
            if opcode == wire.OP_SOFT_REBOOT
        ]
        self.assertEqual(
            soft_reboots,
            [0, 1, 2],
            "disabled, first-enabled, and redraw boots need distinct acknowledgements",
        )

        initial_probe = next(
            item for item in sources if "initial-disabled" in item[2]
        )
        enable = next(
            item for item in sources if bench.ENABLE_MARKER in item[2]
        )
        enabled_probe = next(item for item in sources if "enabled-boot" in item[2])
        reuse = next(item for item in sources if bench.REUSE_MARKER in item[2])
        self.assertEqual(initial_probe[0], 1)
        self.assertEqual(enable[0], 1)
        self.assertLess(initial_probe[1], enable[1])
        self.assertEqual(enabled_probe[0], 2)
        self.assertEqual(reuse[0], 2)
        self.assertLess(enabled_probe[1], reuse[1])
        self.assertEqual(len(connector.calls), 4)

        lifecycle = result["lifecycle"]
        self.assertTrue(lifecycle["disabled_soft_reboot_acknowledged"])
        self.assertTrue(lifecycle["disabled_old_connection_closed"])
        self.assertEqual(result["connection_evidence"]["fresh_reconnects"], 3)
        self.assertFalse(lifecycle["initial_disabled"]["enabled"])
        self.assertTrue(lifecycle["initial_disabled"]["wait_ready"])
        self.assertFalse(lifecycle["initial_disabled"]["rendered"])
        self.assertFalse(lifecycle["initial_disabled"]["backlight_on"])

    async def test_all_lifecycle_stages_are_candidate_session_hash_chained(self):
        result, _connector, _connections, _observations = await self._run()
        records = result["lifecycle_records"]
        self.assertEqual(
            [record["stage"] for record in records],
            list(EXPECTED_LIFECYCLE_STAGE_NAMES),
        )
        self.assertEqual(
            [record["ordinal"] for record in records],
            list(range(1, len(EXPECTED_LIFECYCLE_STAGE_NAMES) + 1)),
        )
        predecessor = bench.record_sha256(result["binding"])
        exact_keys = {
            "ordinal",
            "stage",
            "session_id",
            "candidate_firmware_sha256",
            "candidate_firmware_size_bytes",
            "predecessor_sha256",
            "evidence",
            "record_sha256",
        }
        for record in records:
            self.assertEqual(set(record), exact_keys)
            self.assertEqual(record["session_id"], result["session_id"])
            self.assertEqual(
                record["candidate_firmware_sha256"],
                result["candidate_firmware_sha256"],
            )
            self.assertEqual(
                record["candidate_firmware_size_bytes"],
                result["candidate_firmware_size_bytes"],
            )
            self.assertEqual(record["predecessor_sha256"], predecessor)
            unsigned = {
                key: item for key, item in record.items() if key != "record_sha256"
            }
            self.assertEqual(record["record_sha256"], bench.record_sha256(unsigned))
            predecessor = record["record_sha256"]
        self.assertEqual(result["terminal_record_sha256"], predecessor)

        reboot_records = {
            record["stage"]: record for record in records if "reboot" in record["stage"]
        }
        self.assertEqual(
            set(reboot_records),
            {"disabled-reboot", "enable-reboot", "redraw-reboot"},
        )
        for record in reboot_records.values():
            self.assertTrue(record["evidence"]["soft_reboot_acknowledged"])
            self.assertTrue(record["evidence"]["old_connection_closed"])

    async def test_validator_rejects_fully_rehashed_lifecycle_chain_tampering(self):
        result, _connector, _connections, _observations = await self._run()
        mutations = []

        changed = copy.deepcopy(result)
        changed["lifecycle_records"][3]["session_id"] = "ff" * 16
        mutations.append(rechain_splash_result(changed))

        changed = copy.deepcopy(result)
        changed["lifecycle_records"][2], changed["lifecycle_records"][3] = (
            changed["lifecycle_records"][3],
            changed["lifecycle_records"][2],
        )
        for ordinal, record in enumerate(changed["lifecycle_records"], 1):
            record["ordinal"] = ordinal
        mutations.append(rechain_splash_result(changed))

        changed = copy.deepcopy(result)
        changed["lifecycle_records"].pop(4)
        for ordinal, record in enumerate(changed["lifecycle_records"], 1):
            record["ordinal"] = ordinal
        mutations.append(rechain_splash_result(changed))

        for changed in mutations:
            with self.subTest(stages=len(changed["lifecycle_records"])):
                with self.assertRaises(bench.BenchError):
                    bench.validate_qualification_result(changed)

    async def test_post_splash_heap_is_bound_to_disabled_fresh_vm_baseline(self):
        result, _connector, _connections, _observations = await self._run()
        lifecycle = result["lifecycle"]
        proof = lifecycle["splash_framebuffer_reclamation"]
        baseline = lifecycle["initial_disabled"]["gc_free_bytes"]
        enabled = lifecycle["enabled_boot"]["gc_free_bytes"]
        redraw = lifecycle["redraw_boot"]["gc_free_bytes"]
        expected = {
            "disabled_baseline_gc_free_bytes": baseline,
            "enabled_boot_gc_free_bytes": enabled,
            "redraw_boot_gc_free_bytes": redraw,
            "enabled_boot_free_deficit_bytes": max(0, baseline - enabled),
            "redraw_boot_free_deficit_bytes": max(0, baseline - redraw),
            "max_drift_bytes": bench.MAX_SPLASH_HEAP_DRIFT_BYTES,
            "framebuffer_bytes": bench.FRAMEBUFFER_BYTES,
            "framebuffer_reclaimed": True,
        }
        self.assertEqual(proof, expected)
        self.assertLessEqual(
            proof["enabled_boot_free_deficit_bytes"],
            proof["max_drift_bytes"],
        )
        self.assertLessEqual(
            proof["redraw_boot_free_deficit_bytes"],
            proof["max_drift_bytes"],
        )
        self.assertLess(proof["max_drift_bytes"], proof["framebuffer_bytes"])

        retained = copy.deepcopy(result)
        retained_proof = retained["lifecycle"][
            "splash_framebuffer_reclamation"
        ]
        retained_proof["enabled_boot_gc_free_bytes"] = (
            baseline - bench.FRAMEBUFFER_BYTES
        )
        retained_proof["enabled_boot_free_deficit_bytes"] = (
            bench.FRAMEBUFFER_BYTES
        )
        retained_proof["framebuffer_reclaimed"] = True
        rechain_splash_result(retained)
        with self.assertRaises(bench.BenchError):
            bench.validate_qualification_result(retained)

    async def test_post_reset_connect_retries_share_one_residual_deadline(self):
        clock = FakeClock()
        connections = [
            FakeCentral("disabled-reboot"),
            *(
                central_module.PbleConnectError("reset transition unavailable")
                for _ in range(25)
            ),
            (0.05, FakeCentral("initial-disabled-enable-reboot")),
            FakeCentral("enabled-boot-and-reuse"),
            FakeCentral("redraw-and-disable"),
        ]
        connector = FakeConnector(connections, clock=clock)

        async def confirm_visual(_phase, _pattern_id, qr_url):
            return qr_url

        result = await bench.run_qualification(
            connector,
            "private-input-only",
            preflight(),
            "ab" * 32,
            self.CANDIDATE_SIZE,
            candidate_attestation(self.CANDIDATE_SIZE),
            timeout_s=5.0,
            poll_interval_s=0,
            sleep=clock.sleep,
            clock=clock.monotonic,
            confirm_visual=confirm_visual,
            session_id="78" * 16,
        )
        self.assertEqual(result["status"], "passed")
        self.assertGreater(len(connector.calls), 20)
        self.assertGreaterEqual(
            clock.delays.count(bench.REBOOT_DELIVERY_GRACE_S),
            3,
        )
        first_transition_timeouts = [
            timeout for _address, timeout in connector.calls[1:27]
        ]
        self.assertTrue(
            all(
                later <= earlier
                for earlier, later in zip(
                    first_transition_timeouts,
                    first_transition_timeouts[1:],
                )
            )
        )
        self.assertLess(first_transition_timeouts[-1], first_transition_timeouts[0])

        initial = next(
            item
            for item in connections
            if isinstance(item, tuple)
        )[1]
        self.assertLess(initial.command_timeouts[0], connector.calls[26][1])

    async def test_stale_vm_is_retryable_on_every_post_reset_probe(self):
        clock = FakeClock()
        centrals = [
            FakeCentral("disabled-reboot"),
            FakeCentral("stale-initial", stale_probe_phase="initial-disabled"),
            FakeCentral("initial-disabled-enable-reboot"),
            FakeCentral("stale-enabled", stale_probe_phase="enabled-boot"),
            FakeCentral("enabled-boot-and-reuse"),
            FakeCentral("stale-redraw", stale_probe_phase="redraw-boot"),
            FakeCentral("redraw-and-disable"),
        ]
        connector = FakeConnector(centrals, clock=clock)

        async def confirm_visual(_phase, _pattern_id, qr_url):
            return qr_url

        result = await bench.run_qualification(
            connector,
            "private-input-only",
            preflight(),
            "ab" * 32,
            self.CANDIDATE_SIZE,
            candidate_attestation(self.CANDIDATE_SIZE),
            timeout_s=2.0,
            poll_interval_s=0,
            sleep=clock.sleep,
            clock=clock.monotonic,
            confirm_visual=confirm_visual,
            session_id="79" * 16,
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(connector.calls), 7)
        self.assertTrue(all(item.disconnected for item in centrals))

    async def test_failure_after_enable_best_effort_disables_and_darkens(self):
        for failure_phase, exception in (
            ("enabled-boot", asyncio.CancelledError("operator cancelled")),
            ("redraw-boot", RuntimeError("late operator callback failed")),
        ):
            connections = [FakeCentral("segment-%d" % index) for index in range(6)]
            connector = FakeConnector(connections)

            async def abort(phase, _pattern_id, qr_url, value=exception):
                if phase == failure_phase:
                    raise value
                return qr_url

            with self.subTest(
                phase=failure_phase,
                exception=type(exception).__name__,
            ):
                with self.assertRaises(type(exception)) as caught:
                    await bench.run_qualification(
                        connector,
                        "private-input-only",
                        preflight(),
                        "ab" * 32,
                        self.CANDIDATE_SIZE,
                        candidate_attestation(self.CANDIDATE_SIZE),
                        timeout_s=2.0,
                        poll_interval_s=0,
                        confirm_visual=abort,
                        session_id="80" * 16,
                    )
                self.assertIs(caught.exception, exception)

            sources = ordered_run_sources(connections)
            enable_index = next(
                index
                for index, item in enumerate(sources)
                if bench.ENABLE_MARKER in item[2]
            )
            later_disables = [
                item
                for item in sources[enable_index + 1 :]
                if bench.DISABLE_MARKER in item[2]
            ]
            self.assertEqual(len(later_disables), 1)
            self.assertIn("Pin(46", later_disables[0][2])

    async def test_cleanup_failure_preserves_the_original_cancellation(self):
        original = asyncio.CancelledError("preserve this exact cancellation")
        connections = [FakeCentral("initial")]
        connections.extend(
            FakeCentral("cleanup-%d" % index, fail_disable=True)
            for index in range(6)
        )
        connector = FakeConnector(connections)

        async def cancel(_phase, _pattern_id, _qr_url):
            raise original

        with self.assertRaises(asyncio.CancelledError) as caught:
            await bench.run_qualification(
                connector,
                "private-input-only",
                preflight(),
                "ab" * 32,
                self.CANDIDATE_SIZE,
                candidate_attestation(self.CANDIDATE_SIZE),
                timeout_s=2.0,
                poll_interval_s=0,
                confirm_visual=cancel,
                session_id="81" * 16,
            )
        self.assertIs(caught.exception, original)
        self.assertTrue(
            any(central.disable_attempted for central in connections[1:]),
            "post-enable cleanup never attempted the exact disable/darken action",
        )

    async def test_cleanup_failure_preserves_the_original_regular_exception(self):
        original = RuntimeError("preserve this exact qualification failure")
        connections = [FakeCentral("initial")]
        connections.extend(
            FakeCentral("cleanup-%d" % index, fail_disable=True)
            for index in range(6)
        )
        connector = FakeConnector(connections)

        async def fail(_phase, _pattern_id, _qr_url):
            raise original

        with self.assertRaises(RuntimeError) as caught:
            await bench.run_qualification(
                connector,
                "private-input-only",
                preflight(),
                "ab" * 32,
                self.CANDIDATE_SIZE,
                candidate_attestation(self.CANDIDATE_SIZE),
                timeout_s=2.0,
                poll_interval_s=0,
                confirm_visual=fail,
                session_id="82" * 16,
            )
        self.assertIs(caught.exception, original)
        self.assertTrue(
            any(central.disable_attempted for central in connections[1:]),
            "post-enable cleanup never attempted the exact disable/darken action",
        )

    async def test_returned_cleanup_exception_obeys_process_control_precedence(self):
        cases = (
            (
                asyncio.CancelledError("original cancellation"),
                SystemExit("returned cleanup exit"),
                "original",
            ),
            (
                KeyboardInterrupt("original interrupt"),
                asyncio.CancelledError("returned cleanup cancellation"),
                "original",
            ),
            (
                SystemExit("original exit"),
                KeyboardInterrupt("returned cleanup interrupt"),
                "original",
            ),
            (
                RuntimeError("ordinary qualification failure"),
                asyncio.CancelledError("returned cleanup cancellation"),
                "cleanup",
            ),
            (
                RuntimeError("ordinary qualification failure"),
                OSError("ordinary returned cleanup failure"),
                "original",
            ),
        )
        for original, cleanup, winner in cases:
            connections = self._connections()
            connector = FakeConnector(connections)

            async def fail(_phase, _pattern_id, _qr_url, value=original):
                raise value

            expected = original if winner == "original" else cleanup
            with self.subTest(
                original=type(original).__name__,
                cleanup=type(cleanup).__name__,
                winner=winner,
            ):
                with mock.patch.object(
                    bench,
                    "_best_effort_disable",
                    return_value=cleanup,
                ) as disable:
                    with self.assertRaises(type(expected)) as caught:
                        await bench.run_qualification(
                            connector,
                            "private-input-only",
                            preflight(),
                            "ab" * 32,
                            self.CANDIDATE_SIZE,
                            candidate_attestation(self.CANDIDATE_SIZE),
                            timeout_s=2.0,
                            poll_interval_s=0,
                            confirm_visual=fail,
                            session_id="83" * 16,
                        )
                self.assertIs(caught.exception, expected)
                disable.assert_awaited_once()

    async def test_pre_return_cleanup_exception_obeys_process_control_precedence(self):
        cases = (
            (
                asyncio.CancelledError("original cancellation"),
                RuntimeError("raised cleanup failure"),
                "original",
            ),
            (
                KeyboardInterrupt("original interrupt"),
                asyncio.CancelledError("raised cleanup cancellation"),
                "original",
            ),
            (
                SystemExit("original exit"),
                KeyboardInterrupt("raised cleanup interrupt"),
                "original",
            ),
            (
                RuntimeError("ordinary qualification failure"),
                OSError("ordinary raised cleanup failure"),
                "original",
            ),
            (
                RuntimeError("ordinary qualification failure"),
                asyncio.CancelledError("raised cleanup cancellation"),
                "cleanup",
            ),
            (
                RuntimeError("ordinary qualification failure"),
                KeyboardInterrupt("raised cleanup interrupt"),
                "cleanup",
            ),
        )
        for original, cleanup, winner in cases:
            connections = self._connections()
            connector = FakeConnector(connections)
            cleanup_started = False

            def clock():
                if cleanup_started:
                    raise cleanup
                return 0.0

            async def fail(_phase, _pattern_id, _qr_url, value=original):
                nonlocal cleanup_started
                cleanup_started = True
                raise value

            expected = original if winner == "original" else cleanup
            with self.subTest(
                original=type(original).__name__,
                cleanup=type(cleanup).__name__,
                winner=winner,
            ):
                with self.assertRaises(type(expected)) as caught:
                    await bench.run_qualification(
                        connector,
                        "private-input-only",
                        preflight(),
                        "ab" * 32,
                        self.CANDIDATE_SIZE,
                        candidate_attestation(self.CANDIDATE_SIZE),
                        timeout_s=2.0,
                        poll_interval_s=0,
                        clock=clock,
                        confirm_visual=fail,
                        session_id="84" * 16,
                    )
                self.assertIs(caught.exception, expected)

    async def test_no_default_or_wrong_operator_scan_can_pass(self):
        connector = FakeConnector(self._connections())
        with self.assertRaises(bench.BenchError):
            await bench.run_qualification(
                connector,
                "private-input-only",
                preflight(),
                "ab" * 32,
                self.CANDIDATE_SIZE,
                candidate_attestation(self.CANDIDATE_SIZE),
                timeout_s=2.0,
                poll_interval_s=0,
                confirm_visual=None,
                session_id="34" * 16,
            )
        self.assertEqual(connector.calls, [])

        for invalid in (True, None, "", "https://pyble.dev/flash", "wrong-url"):
            with self.subTest(invalid=invalid), self.assertRaises(bench.BenchError):
                await self._run(
                    callback=lambda phase, pattern, url, value=invalid: value
                )

    async def test_result_validator_rejects_rehashed_semantic_or_private_tampering(self):
        result, _, _, _ = await self._run()
        changes = []

        changed = copy.deepcopy(result)
        changed["session_id"] = "56" * 16
        changes.append(changed)

        changed = copy.deepcopy(result)
        changed["candidate_firmware_sha256"] = "ef" * 32
        changes.append(changed)

        changed = copy.deepcopy(result)
        changed["operator_observations"][0]["scanned_url"] = "https://pyble.dev"
        changes.append(changed)

        changed = copy.deepcopy(result)
        changed["lifecycle"]["final_disabled"]["backlight_on"] = True
        changes.append(changed)

        changed = copy.deepcopy(result)
        changed["raw_info"] = "private bytes"
        changes.append(changed)

        for changed in changes:
            changed["record_sha256"] = bench.record_sha256(
                {
                    key: value
                    for key, value in changed.items()
                    if key != "record_sha256"
                }
            )
            with self.subTest(keys=set(changed)), self.assertRaises(bench.BenchError):
                bench.validate_qualification_result(changed)

    async def test_result_digest_and_exclusive_mode_0600_writer_are_mandatory(self):
        result, _, _, _ = await self._run()
        unsigned = {key: value for key, value in result.items() if key != "record_sha256"}
        self.assertEqual(result["record_sha256"], bench.record_sha256(unsigned))

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "splash-qualification.json"
            payload = bench.write_result_exclusive(destination, result)
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(json.loads(payload), result)
            self.assertEqual(os.stat(destination).st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                bench.write_result_exclusive(destination, result)

            linked = Path(directory) / "linked.json"
            target = Path(directory) / "target.json"
            target.write_text("keep", encoding="utf-8")
            linked.symlink_to(target)
            with self.assertRaises((FileExistsError, bench.BenchError)):
                bench.write_result_exclusive(linked, result)
            self.assertEqual(target.read_text(encoding="utf-8"), "keep")


def production_app_evidence():
    """Sanitized evidence shape owned by ``_production_app_probe``."""
    digest = "de" * 32
    return {
        "schema_version": 1,
        "app": {"status": 200, "size_bytes": 1200, "sha256": digest},
        "qr": {
            "status": 200,
            "size_bytes": bench.production_app.EXPECTED_QR_SIZE_BYTES,
            "sha256": bench.production_app.EXPECTED_QR_SHA256,
        },
        "flash": {"status": 200, "size_bytes": 900, "sha256": "be" * 32},
        "normalized_redirect": {
            "status": 308,
            "location": "/app?pyble_hil=1",
        },
        "link_facts": {
            "main_content": True,
            "testflight_href": True,
            "testflight_visible_fallback": True,
            "flash_href": True,
            "support_href": True,
            "qr_src": True,
        },
        "active_release_path": "/firmware/v0.5.1/release.json",
    }


class CombinedFakeCentral(FakeCentral):
    """Fresh central for the combined website/splash/TFT qualification."""

    def __init__(
        self,
        name,
        *,
        omit_enable=False,
        omit_disable=False,
        omit_arm=False,
        wrong_boot_phase=None,
        live_candidate_sha256=None,
        hello_payload=CAPS,
        probe_link_loss_phase=None,
        link_loss_connected=False,
        tft_failure=False,
        clock=None,
        disconnect_advance_s=0,
        probe_advance_s=0,
        input_link_loss=False,
        input_error=None,
        stale_boot_phase=None,
        **kwargs,
    ):
        super().__init__(name, **kwargs)
        self.omit_enable = omit_enable
        self.omit_disable = omit_disable
        self.omit_arm = omit_arm
        self.wrong_boot_phase = wrong_boot_phase
        self.live_candidate_sha256 = live_candidate_sha256
        self.hello_payload = hello_payload
        self.probe_link_loss_phase = probe_link_loss_phase
        self.link_loss_connected = link_loss_connected
        self.tft_failure = tft_failure
        self.clock = clock
        self.disconnect_advance_s = disconnect_advance_s
        self.probe_advance_s = probe_advance_s
        self.input_link_loss = input_link_loss
        self.input_error = input_error
        self.stale_boot_phase = stale_boot_phase
        self.stopped = False
        self.visual_confirmed = False
        self.console_inputs = []
        self.release_event = asyncio.Event()
        self._emitter = None

    async def disconnect(self):
        if self.clock is not None:
            self.clock.now += self.disconnect_advance_s
        return await super().disconnect()

    async def send_cmd(self, opcode, request_id, payload=b"", timeout=10.0):
        source = bytes(payload)
        if opcode == wire.OP_HELLO and self.hello_payload != CAPS:
            self.commands.append((opcode, request_id, source))
            self.command_timeouts.append(timeout)
            return response(opcode, request_id, self.hello_payload)
        if opcode == wire.OP_DEVICE_INFO:
            self.commands.append((opcode, request_id, source))
            self.command_timeouts.append(timeout)
            await asyncio.sleep(0)
            return response(opcode, request_id, CAPS)
        if opcode == wire.OP_STOP:
            self.commands.append((opcode, request_id, source))
            self.command_timeouts.append(timeout)
            self.stopped = True
            self.release_event.set()
            return response(opcode, request_id)
        if opcode == wire.OP_RUN and tft_bench.MEMORY_MARKER.encode("ascii") in source:
            self.commands.append((opcode, request_id, source))
            self.command_timeouts.append(timeout)
            self._emitter = asyncio.create_task(self._emit_tft_exercise(source))
            return response(opcode, request_id)
        if opcode == wire.OP_RUN and tft_bench.CANDIDATE_MARKER.encode("ascii") in source and self.live_candidate_sha256 is not None:
            self.commands.append((opcode, request_id, source))
            self.command_timeouts.append(timeout)
            self.events.append(event(wire.OP_RUN_STATE, b"\x01"))
            self.events.append(
                _stdout("%s=%s" % (tft_bench.CANDIDATE_MARKER, self.live_candidate_sha256))
            )
            self.events.append(event(wire.OP_RUN_STATE, b"\x02"))
            return response(opcode, request_id)
        if opcode == wire.OP_RUN and bench.BOOT_EVIDENCE_MARKER.encode("ascii") in source:
            self.commands.append((opcode, request_id, source))
            self.command_timeouts.append(timeout)
            phase = next(
                (item for item in bench.COMBINED_BOOT_PHASES if item.encode("ascii") in source),
                None,
            )
            if phase is None:
                raise AssertionError("combined boot probe omitted phase")
            if self.stale_boot_phase == phase:
                self.events.append(event(wire.OP_RUN_STATE, b"\x01"))
                self.events.append(_stdout(bench.STALE_VM_MARKER))
                self.events.append(event(wire.OP_RUN_STATE, b"\x03"))
                return response(opcode, request_id)
            if self.clock is not None:
                self.clock.now += self.probe_advance_s
            if self.probe_link_loss_phase == phase:
                self.is_connected = self.link_loss_connected
                raise central_module.PbleLinkLossError("injected boot-probe link loss")
            enabled = phase in ("setup-enabled", "cycle-1")
            if self.wrong_boot_phase == phase:
                enabled = not enabled
            trace = "success" if enabled else "disabled"
            backlight = int(enabled)
            self.events.append(event(wire.OP_RUN_STATE, b"\x01"))
            self.events.append(
                _stdout(
                    "%s=%s,%d,1,%d,%s,7900000,%s"
                    % (
                        bench.BOOT_EVIDENCE_MARKER,
                        phase,
                        int(enabled),
                        backlight,
                        bench.EXPECTED_FIRMWARE_VERSION,
                        trace,
                    )
                )
            )
            self.events.append(event(wire.OP_RUN_STATE, b"\x02"))
            return response(opcode, request_id)
        if opcode == wire.OP_RUN and bench.ENABLE_MARKER.encode("ascii") in source and self.omit_enable:
            self.commands.append((opcode, request_id, source))
            self.command_timeouts.append(timeout)
            self.events.extend(
                [event(wire.OP_RUN_STATE, b"\x01"), event(wire.OP_RUN_STATE, b"\x02")]
            )
            return response(opcode, request_id)
        if opcode == wire.OP_RUN and bench.DISABLE_MARKER.encode("ascii") in source and self.omit_disable:
            self.disable_attempted = True
            self.commands.append((opcode, request_id, source))
            self.command_timeouts.append(timeout)
            self.events.extend(
                [event(wire.OP_RUN_STATE, b"\x01"), event(wire.OP_RUN_STATE, b"\x02")]
            )
            return response(opcode, request_id)
        if opcode == wire.OP_RUN and bench.REBOOT_ARM_MARKER.encode("ascii") in source and self.omit_arm:
            self.commands.append((opcode, request_id, source))
            self.command_timeouts.append(timeout)
            self.events.extend(
                [event(wire.OP_RUN_STATE, b"\x01"), event(wire.OP_RUN_STATE, b"\x02")]
            )
            return response(opcode, request_id)
        return await super().send_cmd(opcode, request_id, payload, timeout)

    async def send_cmd_no_rsp(self, opcode, request_id, payload=b""):
        self.commands.append((opcode, request_id, bytes(payload)))
        self.command_timeouts.append(None)
        if opcode != wire.OP_CONSOLE_INPUT:
            raise AssertionError("unexpected combined no-response opcode")
        self.console_inputs.append(bytes(payload))
        if self.input_link_loss:
            self.is_connected = False
            self.release_event.set()
            raise central_module.PbleLinkLossError(
                "combined visual release link loss"
            )
        if self.input_error is not None:
            raise self.input_error
        self.release_event.set()
        await asyncio.sleep(0)

    async def _emit_tft_exercise(self, source):
        interactive = bench.tft.VISUAL_RELEASE_MARKER.encode("ascii") in source
        self.events.append(event(wire.OP_RUN_STATE, b"\x01"))
        lines = [
            "%s=%d,%d,%d,%d"
            % (
                tft_bench.MEMORY_MARKER,
                16 * 1024 * 1024,
                7_900_000,
                7_700_000,
                120_000,
            ),
            "%s=0" % tft_bench.BACKLIGHT_MARKER,
            "%s=ready" % tft_bench.PATTERN_MARKER,
            "%s=0,before" % tft_bench.REFRESH_MARKER,
            "%s=0,after" % tft_bench.REFRESH_MARKER,
            "%s=1" % tft_bench.BACKLIGHT_MARKER,
        ]
        if interactive:
            lines.append("%s=1" % tft_bench.VISUAL_RELEASE_MARKER)
        for index in range(1, tft_bench.REFRESH_COUNT):
            lines.extend(
                (
                    "%s=%d,before" % (tft_bench.REFRESH_MARKER, index),
                    "%s=%d,after" % (tft_bench.REFRESH_MARKER, index),
                )
            )
        lines.extend(
            (
                "%s=0" % tft_bench.BACKLIGHT_MARKER,
                "%s=1" % tft_bench.CLEANUP_MARKER,
            )
        )
        for line in lines:
            if (
                self.stopped
                and (
                    line == "%s=1" % tft_bench.VISUAL_RELEASE_MARKER
                    or line.startswith("%s=" % tft_bench.REFRESH_MARKER)
                )
            ):
                continue
            encoded = (line + "\r\n").encode("ascii")
            split = max(1, len(encoded) // 2)
            self.events.append(event(wire.OP_CONSOLE_DATA, b"\x00" + encoded[:split]))
            await asyncio.sleep(0)
            self.events.append(event(wire.OP_CONSOLE_DATA, b"\x00" + encoded[split:]))
            await asyncio.sleep(0)
            if line == "%s=1" % tft_bench.BACKLIGHT_MARKER and interactive:
                await self.release_event.wait()
        if self.stopped:
            self.events.append(event(wire.OP_RUN_STATE, b"\x00"))
        elif self.tft_failure:
            self.events.append(event(wire.OP_CONSOLE_DATA, b"\x01exercise failed\r\n"))
            self.events.append(event(wire.OP_RUN_STATE, b"\x03"))
        else:
            self.events.append(event(wire.OP_RUN_STATE, b"\x02"))


class CombinedFakeConnector(FakeConnector):
    def __init__(self, centrals, *, event_log=None, clock=None):
        super().__init__(centrals, clock=clock)
        self.event_log = event_log if event_log is not None else []
        self.last = None

    async def __call__(self, address, *, timeout):
        self.event_log.append("connect")
        central = await super().__call__(address, timeout=timeout)
        self.last = central
        return central


def rechain_combined_result(value):
    predecessor = bench.record_sha256(value["binding"])
    for ordinal, record in enumerate(value["records"], 1):
        record["ordinal"] = ordinal
        record["predecessor_sha256"] = predecessor
        record["record_sha256"] = bench.record_sha256(
            {key: item for key, item in record.items() if key != "record_sha256"}
        )
        predecessor = record["record_sha256"]
    value["terminal_record_sha256"] = predecessor
    value["qualification"]["terminal_record_sha256"] = predecessor
    value["record_sha256"] = bench.record_sha256(
        {key: item for key, item in value.items() if key != "record_sha256"}
    )
    return value


class CombinedQualificationContractTest(unittest.IsolatedAsyncioTestCase):
    CANDIDATE_SIZE = 1_761_808

    def _connections(self, **first_options):
        return [
            CombinedFakeCentral("candidate/setup-disabled", **first_options),
            CombinedFakeCentral("setup-disabled/setup-enabled"),
            CombinedFakeCentral("setup-enabled/exercise/cycle-1-arm"),
            CombinedFakeCentral("cycle-1/final-disable/cycle-2-arm"),
            CombinedFakeCentral("cycle-2/cycle-3-arm"),
            CombinedFakeCentral("cycle-3/final-proof"),
        ]

    async def _run(self, connections=None, *, production_probe=None, splash=None, tft=None):
        event_log = []
        connections = connections or self._connections()
        connector = CombinedFakeConnector(connections, event_log=event_log)
        splash_calls = []
        tft_calls = []

        async def app_probe():
            event_log.append("production-probe")
            if production_probe is not None:
                return await production_probe()
            return production_app_evidence()

        async def confirm_splash(phase, pattern_id, qr_url):
            splash_calls.append(
                (
                    phase,
                    pattern_id,
                    qr_url,
                    list(connector.last.commands),
                    connector.last.is_connected,
                )
            )
            if splash is not None:
                return await splash(phase, pattern_id, qr_url)
            return qr_url

        async def confirm_tft(pattern_id):
            run_states = [
                item.payload
                for item in connector.last.events
                if item.opcode == wire.OP_RUN_STATE
            ]
            terminal_seen = not run_states or run_states[-1] != b"\x01"
            tft_calls.append((pattern_id, terminal_seen, connector.last.is_connected))
            connector.last.visual_confirmed = True
            if tft is not None:
                return await tft(pattern_id)
            return True

        result = await bench.run_combined_qualification(
            connector,
            "private-input-only",
            preflight(),
            "ab" * 32,
            self.CANDIDATE_SIZE,
            candidate_attestation(self.CANDIDATE_SIZE),
            timeout_s=2.0,
            poll_interval_s=0,
            production_app_probe=app_probe,
            confirm_splash=confirm_splash,
            confirm_tft=confirm_tft,
            session_id="91" * 16,
        )
        return result, connector, connections, event_log, splash_calls, tft_calls

    async def _invoke(
        self,
        connector,
        *,
        clock=None,
        sleep=asyncio.sleep,
        confirm_splash=None,
        confirm_tft=None,
        operator_timeout_s=None,
    ):
        options = {}
        if clock is not None:
            options["clock"] = clock.monotonic
        if operator_timeout_s is not None:
            options["operator_timeout_s"] = operator_timeout_s

        def default_confirm_tft(_pattern):
            connector.last.visual_confirmed = True
            return True

        if confirm_splash is None:
            confirm_splash = lambda _phase, _pattern, qr_url: qr_url
        if confirm_tft is None:
            confirm_tft = default_confirm_tft

        return await bench.run_combined_qualification(
            connector,
            "private-input-only",
            preflight(),
            "ab" * 32,
            self.CANDIDATE_SIZE,
            candidate_attestation(self.CANDIDATE_SIZE),
            timeout_s=2.0,
            poll_interval_s=0,
            sleep=sleep,
            production_app_probe=production_app_evidence,
            confirm_splash=confirm_splash,
            confirm_tft=confirm_tft,
            session_id="98" * 16,
            **options,
        )

    async def test_exact_combined_sequence_has_five_resets_and_six_ble_segments(self):
        result, connector, connections, event_log, splash_calls, tft_calls = await self._run()

        self.assertEqual(event_log[0], "production-probe")
        self.assertEqual(result["production_app_evidence"], production_app_evidence())
        self.assertEqual(
            result["binding"]["production_app_evidence"],
            production_app_evidence(),
        )
        self.assertEqual(len(connector.calls), 6)
        self.assertEqual(
            sum(
                opcode == wire.OP_SOFT_REBOOT
                for central in connections
                for opcode, _request_id, _payload in central.commands
            ),
            5,
        )
        for central in connections[:5]:
            reboot_index = next(
                index
                for index, command in enumerate(central.commands)
                if command[0] == wire.OP_SOFT_REBOOT
            )
            self.assertGreater(reboot_index, 0)
            self.assertEqual(central.commands[reboot_index - 1][0], wire.OP_RUN)
            self.assertIn(
                bench.REBOOT_ARM_MARKER.encode("ascii"),
                central.commands[reboot_index - 1][2],
                "every reset requires its own immediately preceding successful arm RUN",
            )
        self.assertEqual(
            [record["stage"] for record in result["records"]],
            [
                "candidate-verification",
                "setup-disabled",
                "setup-enabled",
                "exercise",
                "cycle-1",
                "cycle-2",
                "cycle-3",
            ],
        )
        self.assertEqual([item["cycle"] for item in result["cycles"]], [1, 2, 3])
        self.assertEqual(result["qualification"]["acknowledged_resets"], 5)
        self.assertEqual(result["qualification"]["ble_segments"], 6)
        self.assertEqual(result["qualification"]["tft_exercises"], 1)
        self.assertEqual(result["qualification"]["tft_reboot_cycles"], 3)

        self.assertEqual([item[0] for item in splash_calls], ["setup-enabled", "cycle-1"])
        for _phase, pattern_id, qr_url, commands, connected in splash_calls:
            self.assertEqual(pattern_id, bench.SPLASH_PATTERN_ID)
            self.assertEqual(qr_url, bench.QR_URL)
            self.assertEqual(commands, [], "physical splash/QR proof must precede first HELLO")
            self.assertTrue(connected)
        self.assertEqual(
            tft_calls,
            [(tft_bench.VISUAL_PATTERN_ID, False, True)],
            "TFT confirmation must happen during the visible RUN",
        )
        for central in connections:
            hellos = [item for item in central.commands if item[0] == wire.OP_HELLO]
            self.assertEqual(len(hellos), 1)
            self.assertEqual(
                [item[1] for item in central.commands],
                list(range(1, len(central.commands) + 1)),
                "%s did not retain one continuous nonzero CMD ID stream"
                % central.name,
            )
        release_calls = [
            item
            for item in connections[2].commands
            if item[0] == wire.OP_CONSOLE_INPUT
        ]
        self.assertEqual(
            release_calls,
            [
                (
                    wire.OP_CONSOLE_INPUT,
                    release_calls[0][1],
                    tft_bench.VISUAL_RELEASE_INPUT + b"\n",
                )
            ],
        )
        self.assertGreater(release_calls[0][1], 0)
        exercise_commands = connections[2].commands
        release_index = next(
            index
            for index, command in enumerate(exercise_commands)
            if command[0] == wire.OP_CONSOLE_INPUT
        )
        cycle_arm_index = next(
            index
            for index, command in enumerate(exercise_commands)
            if command[0] == wire.OP_RUN
            and bench.REBOOT_ARM_MARKER.encode("ascii") in command[2]
        )
        post_release_info_indexes = [
            index
            for index, command in enumerate(exercise_commands)
            if command[0] == wire.OP_DEVICE_INFO
            and release_index < index < cycle_arm_index
        ]
        self.assertGreaterEqual(
            len(post_release_info_indexes),
            tft_bench.MIN_RESPONSIVE_PROBES,
        )
        self.assertLess(release_index, min(post_release_info_indexes))
        self.assertLess(max(post_release_info_indexes), cycle_arm_index)
        self.assertTrue(all(item.disconnected for item in connections))

        disabled = result["setup"]["disabled"]["post_reboot"]["probe"]
        enabled = result["setup"]["enabled"]["post_reboot"]["probe"]
        self.assertEqual(disabled["boot_evidence"], [list(item) for item in bench.DISABLED_BOOT_EVIDENCE])
        self.assertEqual(enabled["boot_evidence"], [list(item) for item in bench.SUCCESS_BOOT_EVIDENCE])
        self.assertEqual(result["cycles"][0]["post_reboot"]["probe"]["boot_evidence"], [list(item) for item in bench.SUCCESS_BOOT_EVIDENCE])
        self.assertTrue(
            result["setup"]["enabled"]["pre_reboot"]["arm"]["armed"]
        )
        for cycle in result["cycles"][1:]:
            self.assertEqual(cycle["post_reboot"]["probe"]["boot_evidence"], [list(item) for item in bench.DISABLED_BOOT_EVIDENCE])
        self.assertTrue(result["cycles"][0]["final_disable"]["persisted"])
        self.assertTrue(result["cycles"][0]["final_disable"]["darkened"])

        for record in result["records"]:
            self.assertEqual(record["session_id"], result["session_id"])
            self.assertEqual(record["candidate_firmware_sha256"], result["candidate_firmware_sha256"])
            self.assertEqual(record["candidate_firmware_size_bytes"], result["candidate_firmware_size_bytes"])
            summaries = combined_run_summaries(record)
            self.assertTrue(summaries)
            for summary in summaries:
                self.assertGreater(summary["stdout_bytes"], 0)
                self.assertGreater(summary["stdout_marker_bytes"], 0)
                self.assertEqual(summary["stderr_bytes"], 0)
                self.assertEqual(summary["state_sequence"], ["running", "done"])
        self.assertIs(bench.validate_combined_qualification_result(result), result)

        encoded = json.dumps(result, sort_keys=True)
        for forbidden in (
            "private-input-only",
            "personal-device-id",
            "personal-label",
            "operator_timeout",
            "raw_info",
            "stdout_chunks",
            bench.VM_SENTINEL,
            '"source"',
            '"sentinel"',
        ):
            self.assertNotIn(forbidden, encoded)

    async def test_production_probe_is_mandatory_validated_and_precedes_ble(self):
        connector = CombinedFakeConnector(self._connections())
        with self.assertRaises(bench.BenchError):
            await bench.run_combined_qualification(
                connector,
                "private-input-only",
                preflight(),
                "ab" * 32,
                self.CANDIDATE_SIZE,
                candidate_attestation(self.CANDIDATE_SIZE),
                production_app_probe=None,
                confirm_splash=lambda *_args: bench.QR_URL,
                confirm_tft=lambda *_args: True,
                session_id="92" * 16,
            )
        self.assertEqual(connector.calls, [])

        for returned in (None, {}, {**production_app_evidence(), "raw_body": "private"}):
            connector = CombinedFakeConnector(self._connections())

            async def invalid_probe(value=returned):
                return value

            with self.subTest(returned=returned), self.assertRaises(Exception):
                await bench.run_combined_qualification(
                    connector,
                    "private-input-only",
                    preflight(),
                    "ab" * 32,
                    self.CANDIDATE_SIZE,
                    candidate_attestation(self.CANDIDATE_SIZE),
                    production_app_probe=invalid_probe,
                    confirm_splash=lambda *_args: bench.QR_URL,
                    confirm_tft=lambda *_args: True,
                    session_id="93" * 16,
                )
            self.assertEqual(connector.calls, [])

    async def test_prearm_failures_cannot_transmit_the_guarded_reset_or_enable(self):
        for option in ("omit_disable", "omit_arm"):
            connections = self._connections(**{option: True})
            connector = CombinedFakeConnector(connections)
            with self.subTest(option=option), self.assertRaises(bench.BenchError):
                await bench.run_combined_qualification(
                    connector,
                    "private-input-only",
                    preflight(),
                    "ab" * 32,
                    self.CANDIDATE_SIZE,
                    candidate_attestation(self.CANDIDATE_SIZE),
                    production_app_probe=production_app_evidence,
                    confirm_splash=lambda *_args: bench.QR_URL,
                    confirm_tft=lambda *_args: True,
                    session_id="94" * 16,
                    timeout_s=2,
                    poll_interval_s=0,
                )
            all_commands = [item for central in connections for item in central.commands]
            self.assertNotIn(wire.OP_SOFT_REBOOT, [item[0] for item in all_commands])
            self.assertFalse(any(bench.ENABLE_MARKER.encode("ascii") in item[2] for item in all_commands))

        connections = self._connections()
        connections[1].omit_enable = True
        connector = CombinedFakeConnector(connections)
        with self.assertRaises(bench.BenchError):
            await bench.run_combined_qualification(
                connector,
                "private-input-only",
                preflight(),
                "ab" * 32,
                self.CANDIDATE_SIZE,
                candidate_attestation(self.CANDIDATE_SIZE),
                production_app_probe=production_app_evidence,
                confirm_splash=lambda *_args: bench.QR_URL,
                confirm_tft=lambda *_args: True,
                session_id="95" * 16,
                timeout_s=2,
                poll_interval_s=0,
            )
        self.assertEqual(
            sum(item[0] == wire.OP_SOFT_REBOOT for central in connections for item in central.commands),
            1,
        )

    async def test_candidate_or_hello_failure_precedes_every_board_mutation(self):
        cases = (
            {"live_candidate_sha256": "ef" * 32},
            {"hello_payload": CAPS.replace(b"proto=1", b"proto=2")},
        )
        for options in cases:
            connections = self._connections(**options)
            connector = CombinedFakeConnector(connections)
            with self.subTest(options=options), self.assertRaises(bench.BenchError):
                await self._invoke(connector)
            sources = [
                item[2]
                for central in connections
                for item in central.commands
                if item[0] == wire.OP_RUN
            ]
            self.assertFalse(
                any(
                    marker.encode("ascii") in source
                    for source in sources
                    for marker in (bench.DISABLE_MARKER, bench.ENABLE_MARKER)
                )
            )
            self.assertEqual(
                sum(
                    item[0] == wire.OP_SOFT_REBOOT
                    for central in connections
                    for item in central.commands
                ),
                0,
            )
            self.assertEqual(len(connector.calls), 1)

    async def test_transactional_connect_and_link_loss_retry_matrix(self):
        good = self._connections()
        retry_connector = CombinedFakeConnector(
            [good[0], central_module.PbleConnectError("transition"), *good[1:]]
        )
        result = await self._invoke(retry_connector)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(retry_connector.calls), 7)

        good = self._connections()
        dropped = CombinedFakeCentral(
            "dropped setup-disabled",
            probe_link_loss_phase="setup-disabled",
            link_loss_connected=False,
            already_dropped=True,
        )
        retry_connector = CombinedFakeConnector([good[0], dropped, *good[1:]])
        result = await self._invoke(retry_connector)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(retry_connector.calls), 7)

        good = self._connections()
        connected_loss = CombinedFakeCentral(
            "connected setup-disabled loss",
            probe_link_loss_phase="setup-disabled",
            link_loss_connected=True,
        )
        connector = CombinedFakeConnector([good[0], connected_loss, *good[1:]])
        with mock.patch.object(bench, "_best_effort_disable", return_value=None):
            with self.assertRaises(central_module.PbleLinkLossError):
                await self._invoke(connector)
        self.assertEqual(len(connector.calls), 2, "connected link loss is terminal")

    async def test_connect_cleanup_and_stuck_old_link_are_terminal(self):
        good = self._connections()
        connector = CombinedFakeConnector(
            [
                good[0],
                central_module.PbleConnectCleanupError("transaction cleanup failed"),
                *good[1:],
            ]
        )
        with mock.patch.object(bench, "_best_effort_disable", return_value=None):
            with self.assertRaises(central_module.PbleConnectCleanupError):
                await self._invoke(connector)
        self.assertEqual(len(connector.calls), 2)

        connections = self._connections(disconnect_error=True)
        connector = CombinedFakeConnector(connections)
        with self.assertRaises(bench.BenchError):
            await self._invoke(connector)
        self.assertEqual(len(connector.calls), 1)
        self.assertEqual(
            sum(
                item[0] == wire.OP_SOFT_REBOOT
                for central in connections
                for item in central.commands
            ),
            1,
        )

    async def test_residual_deadline_exhaustion_in_disconnect_or_probe_is_terminal(self):
        for location in ("disconnect", "probe"):
            clock = FakeClock()
            options = {"clock": clock}
            if location == "disconnect":
                options["disconnect_advance_s"] = 2.1
            connections = self._connections(**options)
            if location == "probe":
                connections[1].clock = clock
                connections[1].probe_advance_s = 2.1
            connector = CombinedFakeConnector(connections, clock=clock)
            with self.subTest(location=location), mock.patch.object(
                bench, "_best_effort_disable", return_value=None
            ):
                with self.assertRaises(bench.BenchError):
                    await self._invoke(connector, clock=clock, sleep=clock.sleep)
            self.assertLessEqual(len(connector.calls), 2)

    async def test_splash_operator_wait_does_not_consume_device_deadline(self):
        clock = FakeClock()
        connections = self._connections()
        connector = CombinedFakeConnector(connections, clock=clock)
        phases = []

        async def delayed_confirmation(phase, _pattern_id, qr_url):
            phases.append(phase)
            clock.now += 3.0
            await asyncio.sleep(0)
            return qr_url

        result = await self._invoke(
            connector,
            clock=clock,
            sleep=clock.sleep,
            confirm_splash=delayed_confirmation,
            operator_timeout_s=10.0,
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(phases, ["setup-enabled", "cycle-1"])
        self.assertTrue(all(item.disconnected for item in connections))

    async def test_operator_timeout_cancels_prompt_then_stops_and_disables(self):
        connections = self._connections()
        connector = CombinedFakeConnector(connections)
        prompt_cancelled = asyncio.Event()

        async def never_confirms(_phase, _pattern_id, _qr_url):
            try:
                await asyncio.Event().wait()
            finally:
                prompt_cancelled.set()

        with self.assertRaises(bench.BenchError) as caught:
            await self._invoke(
                connector,
                confirm_splash=never_confirms,
                operator_timeout_s=0.02,
            )

        self.assertNotIsInstance(caught.exception, asyncio.CancelledError)
        self.assertTrue(prompt_cancelled.is_set())
        self.assertTrue(connections[3].disable_attempted)
        self.assertTrue(connections[3].disconnected)

    async def test_invalid_operator_budget_fails_before_probe_or_ble(self):
        for invalid in (True, 0, -1, float("nan"), float("inf"), 900.01):
            connector = CombinedFakeConnector(self._connections())
            probe_called = False

            async def production_probe():
                nonlocal probe_called
                probe_called = True
                return production_app_evidence()

            with self.subTest(invalid=invalid), self.assertRaises(bench.BenchError):
                await bench.run_combined_qualification(
                    connector,
                    "private-input-only",
                    preflight(),
                    "ab" * 32,
                    self.CANDIDATE_SIZE,
                    candidate_attestation(self.CANDIDATE_SIZE),
                    timeout_s=2.0,
                    operator_timeout_s=invalid,
                    poll_interval_s=0,
                    production_app_probe=production_probe,
                    confirm_splash=lambda *_args: bench.QR_URL,
                    confirm_tft=lambda *_args: True,
                    session_id="99" * 16,
                )
            self.assertFalse(probe_called)
            self.assertEqual(connector.calls, [])

    async def test_splash_operator_budget_is_aggregate_across_stale_retry(self):
        clock = FakeClock()
        connections = self._connections()
        stale = CombinedFakeCentral(
            "stale setup-enabled",
            stale_boot_phase="setup-enabled",
        )
        connections = [connections[0], connections[1], stale, *connections[2:]]
        connector = CombinedFakeConnector(connections, clock=clock)
        phases = []

        async def delayed_confirmation(phase, _pattern_id, qr_url):
            phases.append(phase)
            clock.now += 0.6
            await asyncio.sleep(0)
            return qr_url

        with self.assertRaises(bench.BenchError):
            await self._invoke(
                connector,
                clock=clock,
                sleep=clock.sleep,
                confirm_splash=delayed_confirmation,
                operator_timeout_s=1.0,
            )

        self.assertEqual(phases, ["setup-enabled", "setup-enabled"])

    async def test_tft_or_final_disable_failure_stops_later_reset_cycles(self):
        connections = self._connections()
        connections[2].tft_failure = True
        connector = CombinedFakeConnector(connections)
        with self.assertRaises(bench.BenchError):
            await self._invoke(connector)
        self.assertEqual(
            sum(
                item[0] == wire.OP_SOFT_REBOOT
                for central in connections
                for item in central.commands
            ),
            2,
            "failed TFT exercise must not arm cycle 1",
        )

        connections = self._connections()
        connections[3].fail_disable = True
        connector = CombinedFakeConnector(connections)
        with self.assertRaises(RuntimeError):
            await self._invoke(connector)
        self.assertEqual(
            sum(
                item[0] == wire.OP_SOFT_REBOOT
                for central in connections
                for item in central.commands
            ),
            3,
            "failed final disable must not arm cycles 2 or 3",
        )

    async def test_visual_release_link_loss_reconnects_stops_then_disables(self):
        connections = self._connections()
        connections[2].input_link_loss = True
        connector = CombinedFakeConnector(connections)

        with self.assertRaises(central_module.PbleLinkLossError):
            await self._invoke(connector)

        cleanup_commands = connections[3].commands
        stop_index = next(
            index
            for index, command in enumerate(cleanup_commands)
            if command[0] == wire.OP_STOP
        )
        disable_index = next(
            index
            for index, command in enumerate(cleanup_commands)
            if command[0] == wire.OP_RUN
            and bench.DISABLE_MARKER.encode("ascii") in command[2]
        )
        self.assertLess(stop_index, disable_index)
        self.assertTrue(connections[3].disable_attempted)
        self.assertTrue(connections[3].disconnected)
        self.assertEqual(
            sum(
                command[0] == wire.OP_SOFT_REBOOT
                for central in connections
                for command in central.commands
            ),
            2,
        )

    async def test_fully_rehashed_cross_session_and_cycle_tampering_is_rejected(self):
        result, *_rest = await self._run()
        changes = []

        changed = copy.deepcopy(result)
        changed["records"][4]["session_id"] = "ff" * 16
        changes.append(rechain_combined_result(changed))

        changed = copy.deepcopy(result)
        changed["records"][4], changed["records"][5] = changed["records"][5], changed["records"][4]
        changed["cycles"][0], changed["cycles"][1] = changed["cycles"][1], changed["cycles"][0]
        changes.append(rechain_combined_result(changed))

        changed = copy.deepcopy(result)
        changed["binding"]["session_id"] = "ee" * 16
        changes.append(rechain_combined_result(changed))

        for changed in changes:
            with self.assertRaises(bench.BenchError):
                bench.validate_combined_qualification_result(changed)

    async def test_final_disabled_drift_rearms_cleanup_disable(self):
        connections = self._connections()
        connections[-1].wrong_boot_phase = "cycle-3"
        connections.append(CombinedFakeCentral("cleanup re-disable"))
        connector = CombinedFakeConnector(connections)

        with self.assertRaises(bench.BenchError):
            await bench.run_combined_qualification(
                connector,
                "private-input-only",
                preflight(),
                "ab" * 32,
                self.CANDIDATE_SIZE,
                candidate_attestation(self.CANDIDATE_SIZE),
                production_app_probe=production_app_evidence,
                confirm_splash=lambda *_args: bench.QR_URL,
                confirm_tft=lambda *_args: True,
                session_id="96" * 16,
                timeout_s=2,
                poll_interval_s=0,
            )
        disables = [
            item
            for central in connections
            for item in central.commands
            if item[0] == wire.OP_RUN and bench.DISABLE_MARKER.encode("ascii") in item[2]
        ]
        self.assertGreaterEqual(len(disables), 3, "final drift must trigger a fresh re-disable")

    async def test_cleanup_process_control_precedence_is_exact(self):
        cases = (
            (asyncio.CancelledError("original"), SystemExit("cleanup"), "original"),
            (RuntimeError("ordinary"), asyncio.CancelledError("cleanup"), "cleanup"),
            (RuntimeError("ordinary"), OSError("cleanup"), "original"),
        )
        for original, cleanup, winner in cases:
            connections = self._connections()
            connector = CombinedFakeConnector(connections)

            async def fail_tft(_pattern_id, value=original):
                raise value

            expected = original if winner == "original" else cleanup
            with self.subTest(winner=winner), mock.patch.object(
                bench,
                "_best_effort_disable",
                return_value=cleanup,
            ):
                with self.assertRaises(type(expected)) as caught:
                    await bench.run_combined_qualification(
                        connector,
                        "private-input-only",
                        preflight(),
                        "ab" * 32,
                        self.CANDIDATE_SIZE,
                        candidate_attestation(self.CANDIDATE_SIZE),
                        production_app_probe=production_app_evidence,
                        confirm_splash=lambda *_args: bench.QR_URL,
                        confirm_tft=fail_tft,
                        session_id="97" * 16,
                        timeout_s=2,
                        poll_interval_s=0,
                    )
            self.assertIs(caught.exception, expected)
            self.assertEqual(connections[2].console_inputs, [])
            self.assertIn(
                wire.OP_STOP,
                [command[0] for command in connections[2].commands],
            )

    async def test_rejected_link_cleanup_uses_the_same_exception_precedence(self):
        cases = (
            (asyncio.CancelledError("original"), OSError("cleanup"), "original"),
            (RuntimeError("original"), KeyboardInterrupt("cleanup"), "cleanup"),
            (RuntimeError("original"), OSError("cleanup"), "original"),
        )
        for original, cleanup, winner in cases:
            expected = original if winner == "original" else cleanup
            with self.subTest(winner=winner), mock.patch.object(
                bench.tft,
                "_close_connection",
                side_effect=cleanup,
            ):
                with self.assertRaises(type(expected)) as caught:
                    await bench._close_rejected_connection(
                        object(),
                        1.0,
                        lambda: 0.0,
                        "rejected",
                        original,
                    )
            self.assertIs(caught.exception, expected)

    async def test_splash_callback_preserves_process_control_before_cleanup(self):
        cases = (
            (asyncio.CancelledError("original"), SystemExit("cleanup"), "original"),
            (RuntimeError("original"), asyncio.CancelledError("cleanup"), "cleanup"),
            (RuntimeError("original"), OSError("cleanup"), "original"),
        )
        for original, cleanup, winner in cases:
            connections = self._connections()
            connector = CombinedFakeConnector(connections)

            async def fail_splash(
                _phase,
                _pattern_id,
                _qr_url,
                value=original,
            ):
                raise value

            expected = original if winner == "original" else cleanup
            with self.subTest(winner=winner), mock.patch.object(
                bench,
                "_best_effort_disable",
                return_value=cleanup,
            ):
                with self.assertRaises(type(expected)) as caught:
                    await self._invoke(
                        connector,
                        confirm_splash=fail_splash,
                    )
            self.assertIs(caught.exception, expected)

    async def test_combined_writer_is_canonical_private_exclusive_and_validates_first(self):
        result, *_rest = await self._run()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "combined.json"
            payload = bench.write_combined_result_exclusive(destination, result)
            self.assertEqual(payload, bench.canonical_json_bytes(result))
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(json.loads(payload), result)
            self.assertEqual(os.stat(destination).st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                bench.write_combined_result_exclusive(destination, result)

            target = root / "target.json"
            target.write_text("keep", encoding="utf-8")
            linked = root / "linked.json"
            linked.symlink_to(target)
            with self.assertRaises((FileExistsError, bench.BenchError, OSError)):
                bench.write_combined_result_exclusive(linked, result)
            self.assertEqual(target.read_text(encoding="utf-8"), "keep")

            invalid = copy.deepcopy(result)
            invalid["status"] = "failed"
            invalid_destination = root / "invalid.json"
            with self.assertRaises(bench.BenchError):
                bench.write_combined_result_exclusive(
                    invalid_destination,
                    invalid,
                )
            self.assertFalse(invalid_destination.exists())

    async def test_operator_prompts_use_cancellable_shared_reader(self):
        with mock.patch.object(
            bench.tft,
            "_read_stdin_line",
            new=mock.AsyncMock(
                side_effect=["VISIBLE\n", bench.QR_URL + "\n"],
            ),
        ) as reader:
            scanned = await bench._prompt_visual_confirmation(
                "setup-enabled",
                bench.SPLASH_PATTERN_ID,
                bench.QR_URL,
            )
        self.assertEqual(scanned, bench.QR_URL)
        self.assertEqual(reader.await_count, 2)

    def test_combined_cli_operator_timeout_defaults_to_full_bounded_window(self):
        args = bench._parse_args(
            [
                "--address",
                "private-input-only",
                "--preflight",
                "preflight.json",
                "--firmware-bin",
                "firmware.bin",
                "--output",
                "combined.json",
            ]
        )
        self.assertEqual(args.timeout, 120.0)
        self.assertEqual(args.operator_timeout, 900.0)
        custom = bench._parse_args(
            [
                "--address",
                "private-input-only",
                "--preflight",
                "preflight.json",
                "--firmware-bin",
                "firmware.bin",
                "--output",
                "combined.json",
                "--operator-timeout",
                "12.5",
            ]
        )
        self.assertEqual(custom.operator_timeout, 12.5)

    async def test_cli_prints_no_result_payload(self):
        private_result = {"status": "passed", "secret": "must-not-print"}
        args = types.SimpleNamespace(
            preflight="preflight.json",
            firmware="firmware.bin",
            address="private-address",
            output="evidence.json",
            timeout=2.0,
            operator_timeout=30.0,
        )
        inspection = {
            "sha256": "ab" * 32,
            "size_bytes": self.CANDIDATE_SIZE,
            "attestation": candidate_attestation(self.CANDIDATE_SIZE),
        }
        with mock.patch.object(bench.tft, "load_preflight", return_value=preflight()), mock.patch.object(
            bench.tft, "inspect_candidate_firmware", return_value=inspection
        ), mock.patch.object(bench, "run_combined_qualification", return_value=private_result) as run, mock.patch.object(
            bench, "write_combined_result_exclusive", return_value=b"private-json"
        ), mock.patch.object(bench, "PbleCentral", return_value=object()), mock.patch.object(
            sys, "stdout", new_callable=lambda: __import__("io").StringIO()
        ) as output:
            await bench._run_cli(args)
        rendered = output.getvalue()
        self.assertNotIn("must-not-print", rendered)
        self.assertNotIn("private-json", rendered)
        self.assertNotIn("private-address", rendered)
        self.assertEqual(run.await_args.kwargs["operator_timeout_s"], 30.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
