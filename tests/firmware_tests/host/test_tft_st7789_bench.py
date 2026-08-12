# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Host-only contract tests for the ADR-0023 exact-board TFT HIL runner.

BLE, clock, and device output are faked.  No connected hardware is touched.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
HIL_DIR = HERE.parent / "hil"
RUNNER_SOURCE = HERE.parents[2] / "firmware" / "user_c_modules" / "pyble" / "pble_runner.c"
sys.path.insert(0, str(HIL_DIR))

import _pble_wire as wire  # noqa: E402
import _pble_central as central_module  # noqa: E402
import tft_st7789_bench as bench  # noqa: E402


CAPS = (
    b"proto=1\n"
    b"agent=0.5.1\n"
    b"chip=esp32-s3\n"
    b"mpy=1.28.0\n"
    b"fs_root=/\n"
    b"mtu=247\n"
    b"window=8\n"
    b"chunk=229\n"
    b"free_mem=262144\n"
    b"has_sd=0\n"
    b"has_identify=0\n"
    b"identify_led=255\n"
    b"auto_run=0\n"
    b"device_id=personal-device-id-must-not-leak\n"
    b"label=personal-label-must-not-leak\n"
)

EXPECTED_VM_SENTINEL = "__PYBLE_TFT_VM_EPOCH_V1__"
EXPECTED_PRE_REBOOT_MARKER = "__PYBLE_TFT_V1_PRE_REBOOT=armed"
EXPECTED_CANDIDATE_MARKER = "__PYBLE_TFT_V1_CANDIDATE"
EXPECTED_STALE_VM_MARKER = "__PYBLE_TFT_V1_STALE_VM=detected"


def candidate_attestation(size_bytes=1_761_488, sha256="cd" * 32):
    spans = [
        {"offset": 0, "size_bytes": 0x9000},
        {"offset": 0x10000, "size_bytes": size_bytes - 0x10000},
    ]
    return {
        "sha256": sha256,
        "size_bytes": sum(item["size_bytes"] for item in spans),
        "spans": spans,
    }


def rechain_qualification(value):
    exercise = value["exercise"]
    exercise["record_sha256"] = bench.record_sha256(
        {key: item for key, item in exercise.items() if key != "record_sha256"}
    )
    predecessor = exercise["record_sha256"]
    for cycle in value["cycles"]:
        cycle["predecessor_sha256"] = predecessor
        cycle["record_sha256"] = bench.record_sha256(
            {key: item for key, item in cycle.items() if key != "record_sha256"}
        )
        predecessor = cycle["record_sha256"]
    value["qualification"]["terminal_record_sha256"] = predecessor
    return value


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


class FakeCentral:
    """PBLE central fake which emits one successful deterministic TFT run."""

    def __init__(
        self,
        *,
        terminal_state=2,
        omit_cleanup=False,
        stderr=b"",
        stale_vm=False,
        omit_pre_marker=False,
        live_immutable_sha256=None,
        post_failure=False,
        post_link_loss=False,
        link_loss_while_connected=False,
        disconnect_error=False,
        already_dropped=False,
        clock=None,
        post_probe_advance_s=0,
        input_link_loss=False,
        input_error=None,
        malformed_terminal=False,
    ):
        self.commands = []
        self.events = []
        self.info_reads = 0
        self.terminal_state = terminal_state
        self.omit_cleanup = omit_cleanup
        self.stderr = stderr
        self.stale_vm = stale_vm
        self.omit_pre_marker = omit_pre_marker
        self.live_immutable_sha256 = live_immutable_sha256
        self.post_failure = post_failure
        self.post_link_loss = post_link_loss
        self.link_loss_while_connected = link_loss_while_connected
        self.disconnect_error = disconnect_error
        self.already_dropped = already_dropped
        self.clock = clock
        self.post_probe_advance_s = post_probe_advance_s
        self.input_link_loss = input_link_loss
        self.input_error = input_error
        self.stopped = False
        self.malformed_terminal = malformed_terminal
        self.console_inputs = []
        self.release_event = asyncio.Event()
        self.is_connected = True
        self.disconnected = False
        self._emitter = None

    def event_cursor(self):
        return len(self.events)

    def events_since(self, cursor):
        return len(self.events), self.events[cursor:]

    async def read_info(self):
        self.info_reads += 1
        await asyncio.sleep(0)
        return CAPS

    async def disconnect(self):
        if self.already_dropped:
            self.is_connected = False
            raise OSError("link already dropped")
        if self.disconnect_error:
            raise OSError("disconnect failed while link remained up")
        self.is_connected = False
        self.disconnected = True
        await asyncio.sleep(0)

    async def send_cmd(self, opcode, request_id, payload=b"", timeout=10.0):
        del timeout
        self.commands.append((opcode, request_id, bytes(payload), len(self.events)))
        if opcode == wire.OP_HELLO:
            return response(opcode, request_id, CAPS)
        if opcode == wire.OP_DEVICE_INFO:
            await asyncio.sleep(0)
            return response(opcode, request_id, CAPS)
        if opcode == wire.OP_SOFT_REBOOT:
            return response(opcode, request_id)
        if opcode == wire.OP_STOP:
            self.stopped = True
            self.release_event.set()
            return response(opcode, request_id)
        if opcode != wire.OP_RUN:
            raise AssertionError("unexpected opcode 0x%02x" % opcode)
        source = bytes(payload)
        if (
            bench.POST_REBOOT_MARKER.encode("ascii") in source
            and self.post_link_loss
        ):
            self.is_connected = self.link_loss_while_connected
            raise central_module.PbleLinkLossError(
                "reset transition dropped the probe transport"
            )
        self._emitter = asyncio.create_task(self._emit_source(source))
        return response(opcode, request_id)

    async def send_cmd_no_rsp(self, opcode, request_id, payload=b""):
        self.commands.append((opcode, request_id, bytes(payload), len(self.events)))
        if opcode != wire.OP_CONSOLE_INPUT:
            raise AssertionError("unexpected no-response opcode")
        self.console_inputs.append(bytes(payload))
        if self.input_link_loss:
            self.is_connected = False
            self.release_event.set()
            raise central_module.PbleLinkLossError("input release link loss")
        if self.input_error is not None:
            raise self.input_error
        self.release_event.set()
        await asyncio.sleep(0)

    async def _emit_source(self, source):
        is_candidate = EXPECTED_CANDIDATE_MARKER.encode("ascii") in source
        is_pre_reboot = EXPECTED_PRE_REBOOT_MARKER.encode("ascii") in source
        is_post_reboot = bench.POST_REBOOT_MARKER.encode("ascii") in source
        terminal_state = self.terminal_state
        self.events.append(event(wire.OP_RUN_STATE, b"\x01"))
        await asyncio.sleep(0)
        if is_candidate:
            expected = re.search(rb'_expected="([0-9a-f]{64})"', source)
            if expected is None:
                raise AssertionError("candidate probe omitted its expected digest")
            expected_digest = expected.group(1).decode("ascii")
            actual_digest = self.live_immutable_sha256 or expected_digest
            self.events.append(
                event(
                    wire.OP_CONSOLE_DATA,
                    b"\x00"
                    + EXPECTED_CANDIDATE_MARKER.encode("ascii")
                    + b"="
                    + actual_digest.encode("ascii")
                    + b"\r\n",
                )
            )
            if actual_digest != expected_digest:
                self.events.append(
                    event(wire.OP_CONSOLE_DATA, b"\x01candidate mismatch\r\n")
                )
                terminal_state = 3
        elif is_pre_reboot:
            if not self.omit_pre_marker:
                self.events.append(
                    event(
                        wire.OP_CONSOLE_DATA,
                        b"\x00"
                        + EXPECTED_PRE_REBOOT_MARKER.encode("ascii")
                        + b"\r\n",
                    )
                )
            if self.stderr:
                self.events.append(event(wire.OP_CONSOLE_DATA, b"\x01" + self.stderr))
        elif is_post_reboot and self.stale_vm:
            self.events.append(
                event(
                    wire.OP_CONSOLE_DATA,
                    b"\x00" + EXPECTED_STALE_VM_MARKER.encode("ascii") + b"\r\n",
                )
            )
            self.events.append(event(wire.OP_CONSOLE_DATA, b"\x01stale VM\r\n"))
            terminal_state = 3
        elif is_post_reboot and self.post_failure:
            self.events.append(
                event(wire.OP_CONSOLE_DATA, b"\x01pyble_st7789 import failed\r\n")
            )
            terminal_state = 3
        elif is_post_reboot:
            if self.clock is not None:
                self.clock.advance(self.post_probe_advance_s)
            self.events.append(
                event(
                    wire.OP_CONSOLE_DATA,
                    b"\x00" + bench.POST_REBOOT_MARKER.encode("ascii") + b"\n",
                )
            )
        else:
            interactive = bench.VISUAL_RELEASE_MARKER.encode("ascii") in source
            lines = [
                "%s=%d,%d,%d,%d"
                % (
                    bench.MEMORY_MARKER,
                    16 * 1024 * 1024,
                    7_900_000,
                    7_700_000,
                    120_000,
                ),
                "%s=0" % bench.BACKLIGHT_MARKER,
                "%s=ready" % bench.PATTERN_MARKER,
                "%s=0,before" % bench.REFRESH_MARKER,
                "%s=0,after" % bench.REFRESH_MARKER,
                "%s=1" % bench.BACKLIGHT_MARKER,
            ]
            if interactive:
                lines.append("%s=1" % bench.VISUAL_RELEASE_MARKER)
            for index in range(1, bench.REFRESH_COUNT):
                lines.append("%s=%d,before" % (bench.REFRESH_MARKER, index))
                lines.append("%s=%d,after" % (bench.REFRESH_MARKER, index))
            lines.extend(
                [
                    "%s=0" % bench.BACKLIGHT_MARKER,
                ]
            )
            if not self.omit_cleanup:
                lines.append("%s=1" % bench.CLEANUP_MARKER)
            for line in lines:
                if (
                    self.stopped
                    and (
                        line == "%s=1" % bench.VISUAL_RELEASE_MARKER
                        or line.startswith("%s=" % bench.REFRESH_MARKER)
                    )
                ):
                    continue
                # Deliberately split every marker across notifications.
                # MicroPython's USB/dupterm console uses CRLF on hardware.
                # Keep the fake byte-accurate so live marker recognition cannot
                # accidentally certify only host-native LF output.
                encoded = (line + "\r\n").encode("ascii")
                split = max(1, len(encoded) // 2)
                self.events.append(
                    event(wire.OP_CONSOLE_DATA, b"\x00" + encoded[:split])
                )
                await asyncio.sleep(0)
                self.events.append(
                    event(wire.OP_CONSOLE_DATA, b"\x00" + encoded[split:])
                )
                await asyncio.sleep(0)
                if line == "%s=1" % bench.BACKLIGHT_MARKER and interactive:
                    await self.release_event.wait()
            if self.stderr:
                self.events.append(event(wire.OP_CONSOLE_DATA, b"\x01" + self.stderr))
        if self.stopped:
            terminal_state = 0
        terminal_payload = (
            b"\xff" if self.malformed_terminal else bytes((terminal_state,))
        )
        self.events.append(event(wire.OP_RUN_STATE, terminal_payload))


class FakeConnector:
    """Return a deliberate sequence of fresh fake BLE connections."""

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
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, tuple):
            advance_s, item = item
            self.clock.advance(advance_s)
        return item


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.delays = []

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds

    async def sleep(self, seconds):
        self.delays.append(seconds)
        self.advance(seconds)
        await asyncio.sleep(0)


class FrozenExactBoardContractTest(unittest.TestCase):
    def test_exact_profile_geometry_pins_and_workload_are_frozen(self):
        self.assertEqual(bench.SCHEMA_VERSION, 1)
        self.assertEqual(bench.PROFILE_ID, "waveshare-esp32-s3-lcd-147b")
        self.assertEqual(bench.EXPECTED_CHIP, "esp32-s3")
        self.assertEqual(bench.BOARD_MODEL, "ESP32-S3-LCD-1.47B")
        self.assertEqual(bench.FLASH_CAPACITY_BYTES, 16 * 1024 * 1024)
        self.assertEqual(bench.PSRAM_CAPACITY_BYTES, 8 * 1024 * 1024)
        self.assertEqual((bench.WIDTH, bench.HEIGHT), (172, 320))
        self.assertEqual((bench.X_OFFSET, bench.Y_OFFSET), (34, 0))
        self.assertEqual(bench.DEFAULT_OPERATOR_TIMEOUT_S, 900.0)
        self.assertEqual(bench.MAX_OPERATOR_TIMEOUT_S, 900.0)
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
        self.assertGreaterEqual(bench.REFRESH_COUNT, 3)

    def test_generated_source_is_bounded_explicit_and_cleanup_safe(self):
        source = bench.build_exercise_source()
        encoded = source.encode("utf-8")
        self.assertLessEqual(len(encoded), 2048, "RUN{source} firmware limit")
        compile(source, "<tft-hil>", "exec")
        self.assertIn("from pyble_st7789 import ST7789,rgb565", source)
        self.assertIn(
            "ST7789(1,40000000,0,0,Pin(40,Pin.OUT),Pin(45,Pin.OUT),"
            "Pin(42,Pin.OUT),Pin(41,Pin.OUT),Pin(39,Pin.OUT),"
            "Pin(46,Pin.OUT),172,320,34,0,True,True)",
            source,
        )
        self.assertNotIn("ST7789(2,40000000", source)
        self.assertGreaterEqual(bench.RESPONSIVENESS_WINDOW_MS, 250)
        self.assertLessEqual(bench.RESPONSIVENESS_WINDOW_MS, 1000)
        self.assertIn(
            "sleep_ms(%d);d.show()" % bench.RESPONSIVENESS_WINDOW_MS,
            source,
        )
        self.assertIn("esp.flash_size()", source)
        self.assertIn("esp32.idf_heap_info(1024)", source)
        self.assertIn("d.rect(0,0,172,320", source)
        for coordinate in ("d.pixel(0,0", "d.pixel(171,0", "d.pixel(0,319", "d.pixel(171,319"):
            self.assertIn(coordinate, source)
        for colour in ("rgb565(255,0,0)", "rgb565(0,255,0)", "rgb565(0,0,255)"):
            self.assertIn(colour, source)
        self.assertIn('d.text("PyBLE"', source)
        self.assertIn("try:", source)
        self.assertIn("finally:", source)
        self.assertIn("d.backlight(False)", source)
        self.assertIn("d.backlight(True)", source)
        self.assertIn("d.deinit()", source)
        self.assertEqual(source.count("d.show()"), 1)
        self.assertIn("sleep_ms(%d)" % bench.VISUAL_CONFIRMATION_HOLD_MS, source)
        interactive = bench.build_exercise_source(interactive_confirmation=True)
        self.assertNotIn(
            "sleep_ms(%d)" % bench.VISUAL_CONFIRMATION_HOLD_MS,
            interactive,
        )
        self.assertLess(
            interactive.index("_release=input()"),
            interactive.index("sleep_ms(80)"),
            "operator release must precede refreshes 1 through 5",
        )

    def test_candidate_probe_hashes_only_the_exact_immutable_live_spans(self):
        attestation = candidate_attestation()
        source = bench.build_candidate_probe_source(attestation)
        self.assertLessEqual(len(source.encode("utf-8")), 2048)
        compile(source, "<candidate-hil>", "exec")
        self.assertIn("esp.flash_read", source)
        self.assertIn("hashlib.sha256", source)
        self.assertIn("(0,36864)", source)
        self.assertIn("(65536,1695952)", source)
        self.assertNotIn("(36864,28672)", source)
        self.assertIn('_expected="%s"' % ("cd" * 32), source)
        self.assertIn(bench.CANDIDATE_MARKER, source)
        for invalid in (
            {**attestation, "sha256": "AB" * 32},
            {**attestation, "size_bytes": 1},
            {**attestation, "spans": list(reversed(attestation["spans"]))},
            {**attestation, "spans": [{"offset": 0, "size_bytes": 0x10000}]},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(bench.BenchError):
                bench.build_candidate_probe_source(invalid)
        maximum = candidate_attestation(0x210000)
        self.assertIn("(65536,2097152)", bench.build_candidate_probe_source(maximum))
        with self.assertRaises(bench.BenchError):
            bench.build_candidate_probe_source(candidate_attestation(0x210001))

    def test_post_reboot_probe_is_import_only_and_bounded(self):
        source = bench.build_post_reboot_source()
        self.assertLessEqual(len(source.encode("utf-8")), 2048)
        self.assertIn("import sys", source)
        self.assertIn(EXPECTED_VM_SENTINEL, source)
        self.assertIn('raise RuntimeError("VM epoch did not reset")', source)
        self.assertIn("import pyble_st7789", source)
        self.assertIn(bench.POST_REBOOT_MARKER, source)
        self.assertLess(source.index(EXPECTED_VM_SENTINEL), source.index("import pyble_st7789"))
        self.assertNotIn("Pin(", source)
        self.assertNotIn("ST7789(", source)

    def test_pre_reboot_probe_arms_a_volatile_sentinel_and_is_bounded(self):
        source = bench.build_pre_reboot_source()
        self.assertLessEqual(len(source.encode("utf-8")), 2048)
        self.assertIn("import sys", source)
        self.assertIn('sys.path.append("%s")' % EXPECTED_VM_SENTINEL, source)
        self.assertIn(EXPECTED_PRE_REBOOT_MARKER, source)
        self.assertNotIn("pyble_st7789", source)


class PreflightAndRedactionTest(unittest.TestCase):
    def test_preflight_requires_exact_nonpersonal_discovery_record(self):
        self.assertEqual(bench.validate_preflight(preflight()), preflight())
        for key, changed in (
            ("profile_id", "esp32-4mb"),
            ("chip", "esp32"),
            ("board_model", "ESP32-S3-LCD-1.47"),
            ("flash_capacity_bytes", 4 * 1024 * 1024),
            ("psram_capacity_bytes", 0),
            ("discovery_method", "operator-guess"),
        ):
            record = preflight()
            record[key] = changed
            with self.subTest(key=key), self.assertRaises(bench.BenchError):
                bench.validate_preflight(record)
        personal = preflight()
        personal["ble_address"] = "not-permitted"
        with self.assertRaises(bench.BenchError):
            bench.validate_preflight(personal)

    def test_caps_are_guarded_and_personal_fields_are_redacted(self):
        value = bench.validate_and_redact_caps(CAPS)
        self.assertEqual(
            set(value),
            {"proto", "agent", "chip", "mpy", "mtu", "window", "chunk", "free_mem_bytes"},
        )
        self.assertEqual(value["chip"], "esp32-s3")
        encoded = json.dumps(value)
        self.assertNotIn("personal-device-id", encoded)
        self.assertNotIn("personal-label", encoded)
        with self.assertRaises(bench.BenchError):
            bench.validate_and_redact_caps(CAPS.replace(b"esp32-s3", b"esp32"))

    def test_runtime_memory_requires_exact_flash_and_visible_psram(self):
        valid = {
            "flash_size_bytes": 16 * 1024 * 1024,
            "psram_idf_heap_region_bytes": 7_900_000,
            "gc_free_bytes": 7_700_000,
            "gc_allocated_bytes": 120_000,
        }
        self.assertEqual(bench.validate_runtime_memory(valid), valid)
        for changed in (
            {**valid, "flash_size_bytes": 4 * 1024 * 1024},
            {**valid, "psram_idf_heap_region_bytes": 0, "gc_free_bytes": 32_000},
            {**valid, "gc_free_bytes": -1},
        ):
            with self.assertRaises(bench.BenchError):
                bench.validate_runtime_memory(changed)


class EvidenceParserTest(unittest.TestCase):
    def test_split_console_markers_produce_exact_evidence(self):
        text = (
            "%s=16777216,7900000,7700000,120000\n"
            "%s=0\n"
            "%s=ready\n"
            "%s=0,before\n%s=0,after\n"
            "%s=1,before\n%s=1,after\n"
            "%s=2,before\n%s=2,after\n"
            "%s=1\n%s=0\n%s=1\n"
            % (
                bench.MEMORY_MARKER,
                bench.BACKLIGHT_MARKER,
                bench.PATTERN_MARKER,
                bench.REFRESH_MARKER,
                bench.REFRESH_MARKER,
                bench.REFRESH_MARKER,
                bench.REFRESH_MARKER,
                bench.REFRESH_MARKER,
                bench.REFRESH_MARKER,
                bench.BACKLIGHT_MARKER,
                bench.BACKLIGHT_MARKER,
                bench.CLEANUP_MARKER,
            )
        ).encode("ascii")
        parsed = bench.parse_console_evidence([text[:17], text[17:91], text[91:]])
        self.assertEqual(parsed["backlight_sequence"], [False, True, False])
        self.assertEqual(parsed["refreshes_completed"], 3)
        self.assertTrue(parsed["pattern_ready"])
        self.assertTrue(parsed["cleanup_completed"])
        self.assertEqual(parsed["memory"]["flash_size_bytes"], 16 * 1024 * 1024)

    def test_duplicate_memory_bad_refresh_or_missing_cleanup_is_rejected(self):
        base = (
            "%s=16777216,7900000,7700000,120000\n"
            "%s=0\n%s=ready\n"
            "%s=0,before\n%s=0,after\n"
            "%s=1\n%s=0\n%s=1\n"
            % (
                bench.MEMORY_MARKER,
                bench.BACKLIGHT_MARKER,
                bench.PATTERN_MARKER,
                bench.REFRESH_MARKER,
                bench.REFRESH_MARKER,
                bench.BACKLIGHT_MARKER,
                bench.BACKLIGHT_MARKER,
                bench.CLEANUP_MARKER,
            )
        )
        for invalid in (
            "%s=16777216,1,1,1\n%s" % (bench.MEMORY_MARKER, base),
            base.replace(",after", ",unexpected"),
            base.replace("%s=1\n" % bench.CLEANUP_MARKER, ""),
        ):
            with self.subTest(invalid=invalid[-30:]), self.assertRaises(bench.BenchError):
                bench.parse_console_evidence([invalid.encode("ascii")])


class ExerciseOrchestrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_operator_wait_does_not_consume_the_run_device_deadline(self):
        central = FakeCentral()
        clock = FakeClock()

        async def delayed_confirmation(_pattern_id):
            clock.advance(3.0)
            await asyncio.sleep(0)
            return True

        with mock.patch.object(
            bench,
            "time",
            new=types.SimpleNamespace(monotonic=clock.monotonic),
        ):
            result = await bench.run_exercise(
                central,
                preflight(),
                timeout_s=2.0,
                operator_timeout_s=10.0,
                poll_interval_s=0,
                confirm_visual_during_run=delayed_confirmation,
            )

        self.assertTrue(result["operator_observation"]["confirmed"])
        self.assertEqual(
            central.console_inputs,
            [bench.VISUAL_RELEASE_INPUT + b"\n"],
        )
        self.assertEqual(
            [item.payload for item in central.events if item.opcode == wire.OP_RUN_STATE],
            [b"\x01", b"\x02"],
        )

    async def test_invalid_operator_budget_fails_before_any_device_command(self):
        for invalid in (True, 0, -1, float("nan"), float("inf"), 900.01):
            central = FakeCentral()
            with self.subTest(invalid=invalid), self.assertRaises(bench.BenchError):
                await bench.run_exercise(
                    central,
                    preflight(),
                    timeout_s=2.0,
                    operator_timeout_s=invalid,
                    poll_interval_s=0,
                    confirm_visual_during_run=lambda _pattern_id: True,
                )
            self.assertEqual(central.commands, [])

    async def test_optional_operator_callback_runs_while_pattern_is_lit_and_run_active(self):
        central = FakeCentral()
        observations = []

        async def confirm_while_visible(pattern_id):
            observations.append(
                {
                    "pattern_id": pattern_id,
                    "run_terminal_seen": any(
                        item.opcode == wire.OP_RUN_STATE and item.payload in (b"\x00", b"\x02", b"\x03")
                        for item in central.events
                    ),
                    "central_connected": central.is_connected,
                    "release_seen_before_callback": bool(central.console_inputs),
                }
            )
            await asyncio.sleep(0)
            return True

        result = await bench.run_exercise(
            central,
            preflight(),
            timeout_s=2.0,
            poll_interval_s=0,
            confirm_visual_during_run=confirm_while_visible,
        )

        self.assertEqual(
            observations,
            [
                {
                    "pattern_id": bench.VISUAL_PATTERN_ID,
                    "run_terminal_seen": False,
                    "central_connected": True,
                    "release_seen_before_callback": False,
                }
            ],
        )
        self.assertEqual(
            result["operator_observation"],
            {
                "confirmed": True,
                "pattern_id": bench.VISUAL_PATTERN_ID,
                "while_run_active": True,
                "stdin_release_sent": True,
            },
        )
        self.assertGreater(result["run"]["stdout_marker_bytes"], 0)
        self.assertEqual(
            central.console_inputs,
            [bench.VISUAL_RELEASE_INPUT + b"\n"],
        )
        release_calls = [
            call for call in central.commands if call[0] == wire.OP_CONSOLE_INPUT
        ]
        self.assertEqual(len(release_calls), 1)
        self.assertGreater(release_calls[0][1], 0)
        self.assertEqual(
            [call[1] for call in central.commands],
            list(range(1, len(central.commands) + 1)),
            "no-RSP release still consumes the next frozen CMD request ID",
        )
        release_index = next(
            index
            for index, call in enumerate(central.commands)
            if call[0] == wire.OP_CONSOLE_INPUT
        )
        post_release_info = [
            call
            for call in central.commands[release_index + 1 :]
            if call[0] == wire.OP_DEVICE_INFO
        ]
        self.assertGreaterEqual(
            len(post_release_info),
            bench.MIN_RESPONSIVE_PROBES,
            "live responsiveness must be sampled after the operator releases input()",
        )
        self.assertGreaterEqual(
            len(
                [
                    index
                    for index in result["pble_responsiveness"]["refresh_indexes"]
                    if index > 0
                ]
            ),
            bench.MIN_RESPONSIVE_PROBES,
            "post-release probes must cover later refresh windows",
        )

    async def test_optional_operator_callback_must_confirm_before_run_can_pass(self):
        central = FakeCentral()

        with self.assertRaises(bench.BenchError):
            await bench.run_exercise(
                central,
                preflight(),
                timeout_s=2.0,
                poll_interval_s=0,
                confirm_visual_during_run=lambda _pattern_id: False,
            )
        self.assertEqual(
            central.console_inputs,
            [],
            "operator refusal must not release the remaining visual workload",
        )
        self.assertIn(wire.OP_STOP, [call[0] for call in central.commands])
        self.assertTrue(central._emitter.done())
        if central._emitter is not None:
            await central._emitter
        self.assertEqual(
            [item.payload for item in central.events if item.opcode == wire.OP_RUN_STATE][-1],
            b"\x00",
        )

    async def test_operator_confirmation_rejects_display_dark_or_done_while_callback_waits(self):
        for queued_events in (
            [
                event(
                    wire.OP_CONSOLE_DATA,
                    b"\x00" + bench.BACKLIGHT_MARKER.encode("ascii") + b"=0\r\n",
                )
            ],
            [event(wire.OP_RUN_STATE, b"\x02")],
        ):
            central = FakeCentral()

            async def confirm_after_hardware_advanced(_pattern_id, queued=queued_events):
                central.events.extend(queued)
                await asyncio.sleep(0)
                return True

            with self.subTest(queued_events=queued_events), self.assertRaises(
                bench.BenchError
            ):
                await bench.run_exercise(
                    central,
                    preflight(),
                    timeout_s=2.0,
                    poll_interval_s=0,
                    confirm_visual_during_run=confirm_after_hardware_advanced,
                )
            self.assertEqual(central.console_inputs, [])
            self.assertIn(
                wire.OP_STOP,
                [command[0] for command in central.commands],
                "stale terminal evidence requires bounded idempotent STOP cleanup",
            )
            self.assertTrue(central._emitter.done())
            if central._emitter is not None:
                await central._emitter

    async def test_visual_release_link_loss_is_terminal(self):
        central = FakeCentral(input_link_loss=True)

        with self.assertRaises(central_module.PbleLinkLossError):
            await bench.run_exercise(
                central,
                preflight(),
                timeout_s=2.0,
                poll_interval_s=0,
                confirm_visual_during_run=lambda _pattern_id: True,
            )
        self.assertFalse(central.is_connected)
        self.assertEqual(
            central.console_inputs,
            [bench.VISUAL_RELEASE_INPUT + b"\n"],
        )
        if central._emitter is not None:
            await central._emitter

    async def test_callback_timeout_or_cancellation_stops_and_drains_finally(self):
        timeout_central = FakeCentral()
        never = asyncio.Event()

        async def never_confirms(_pattern_id):
            await never.wait()
            return True

        with self.assertRaises(bench.BenchError):
            await bench.run_exercise(
                timeout_central,
                preflight(),
                timeout_s=0.4,
                operator_timeout_s=0.05,
                poll_interval_s=0,
                confirm_visual_during_run=never_confirms,
            )
        self.assertEqual(
            timeout_central.console_inputs,
            [],
        )
        self.assertIn(wire.OP_STOP, [call[0] for call in timeout_central.commands])
        self.assertTrue(timeout_central._emitter.done())
        if timeout_central._emitter is not None:
            await timeout_central._emitter

        cancelled_central = FakeCentral()
        original = asyncio.CancelledError("preserve exact operator cancellation")

        async def cancel(_pattern_id):
            raise original

        with self.assertRaises(asyncio.CancelledError) as caught:
            await bench.run_exercise(
                cancelled_central,
                preflight(),
                timeout_s=2.0,
                poll_interval_s=0,
                confirm_visual_during_run=cancel,
            )
        self.assertIs(caught.exception, original)
        self.assertEqual(
            cancelled_central.console_inputs,
            [],
        )
        self.assertIn(wire.OP_STOP, [call[0] for call in cancelled_central.commands])
        self.assertTrue(cancelled_central._emitter.done())
        if cancelled_central._emitter is not None:
            await cancelled_central._emitter

    async def test_connected_release_failure_stops_and_drains_before_propagating(self):
        original = OSError("connected CONSOLE_INPUT write failed")
        central = FakeCentral(input_error=original)

        with self.assertRaises(OSError) as caught:
            await bench.run_exercise(
                central,
                preflight(),
                timeout_s=2.0,
                poll_interval_s=0,
                confirm_visual_during_run=lambda _pattern_id: True,
            )
        self.assertIs(caught.exception, original)
        self.assertIn(wire.OP_STOP, [call[0] for call in central.commands])
        if central._emitter is not None:
            await central._emitter
        output = b"".join(
            item.payload[1:]
            for item in central.events
            if item.opcode == wire.OP_CONSOLE_DATA
            and item.payload
            and item.payload[0] == 0
        )
        self.assertIn(bench.BACKLIGHT_MARKER.encode("ascii") + b"=0", output)
        self.assertIn(bench.CLEANUP_MARKER.encode("ascii") + b"=1", output)
        self.assertEqual(
            [item.payload for item in central.events if item.opcode == wire.OP_RUN_STATE][-1],
            b"\x00",
        )

    async def test_callback_process_control_wins_over_remote_drain_error(self):
        for exception in (asyncio.CancelledError("exact cancellation"),):
            central = FakeCentral(terminal_state=3, stderr=b"remote cleanup error")

            async def stop_operator(_pattern_id, value=exception):
                raise value

            with self.subTest(exception=type(exception).__name__):
                with self.assertRaises(type(exception)) as caught:
                    await bench.run_exercise(
                        central,
                        preflight(),
                        timeout_s=2.0,
                        poll_interval_s=0,
                        confirm_visual_during_run=stop_operator,
                    )
                self.assertIs(caught.exception, exception)
            if central._emitter is not None:
                await central._emitter

        original = asyncio.CancelledError("malformed terminal cancellation")
        central = FakeCentral(malformed_terminal=True)

        async def cancel_before_malformed_terminal(_pattern_id):
            raise original

        with self.assertRaises(asyncio.CancelledError) as caught:
            await bench.run_exercise(
                central,
                preflight(),
                timeout_s=2.0,
                poll_interval_s=0,
                confirm_visual_during_run=cancel_before_malformed_terminal,
            )
        self.assertIs(caught.exception, original)
        self.assertEqual(
            central.console_inputs,
            [],
        )
        self.assertIn(wire.OP_STOP, [call[0] for call in central.commands])
        if central._emitter is not None:
            await central._emitter

    async def test_malformed_event_during_callback_cancellation_still_stops_and_drains(self):
        original = asyncio.CancelledError("exact queued-event cancellation")
        central = FakeCentral()

        async def cancel_with_malformed_event(_pattern_id):
            central.events.append(event(wire.OP_RUN_STATE, b"\xff"))
            raise original

        with self.assertRaises(asyncio.CancelledError) as caught:
            await bench.run_exercise(
                central,
                preflight(),
                timeout_s=2.0,
                poll_interval_s=0,
                confirm_visual_during_run=cancel_with_malformed_event,
            )
        self.assertIs(caught.exception, original)
        self.assertEqual(
            central.console_inputs,
            [],
        )
        self.assertIn(wire.OP_STOP, [call[0] for call in central.commands])
        self.assertTrue(
            central._emitter.done(),
            "initiating cancellation propagated before the remote finally drained",
        )
        if central._emitter is not None:
            await central._emitter
        output = b"".join(
            item.payload[1:]
            for item in central.events
            if item.opcode == wire.OP_CONSOLE_DATA
            and item.payload
            and item.payload[0] == 0
        )
        self.assertIn(bench.BACKLIGHT_MARKER.encode("ascii") + b"=0", output)
        self.assertIn(bench.CLEANUP_MARKER.encode("ascii") + b"=1", output)

    async def test_run_captures_states_console_memory_and_live_info(self):
        central = FakeCentral()
        result = await bench.run_exercise(
            central,
            preflight(),
            timeout_s=2.0,
            poll_interval_s=0,
        )
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["stage"], "exercise")
        self.assertEqual(result["profile_id"], "waveshare-esp32-s3-lcd-147b")
        self.assertEqual(result["board_model"], "ESP32-S3-LCD-1.47B")
        self.assertEqual(result["display"]["geometry"], [172, 320, 34, 0])
        self.assertEqual(result["display"]["refreshes_completed"], bench.REFRESH_COUNT)
        self.assertEqual(result["display"]["backlight_sequence"], [False, True, False])
        self.assertTrue(result["display"]["cleanup_completed"])
        self.assertEqual(result["run"]["state_sequence"], ["running", "done"])
        self.assertEqual(result["run"]["stderr_bytes"], 0)
        self.assertGreaterEqual(result["pble_responsiveness"]["info_reads"], 1)
        self.assertGreaterEqual(result["pble_responsiveness"]["device_info_commands"], 1)
        self.assertGreaterEqual(
            len(result["pble_responsiveness"]["refresh_indexes"]),
            bench.MIN_RESPONSIVE_PROBES,
        )
        self.assertEqual(
            result["pble_responsiveness"]["refresh_indexes"],
            sorted(set(result["pble_responsiveness"]["refresh_indexes"])),
        )
        self.assertEqual(result["next_stage"], "soft-reboot")

        opcodes = [call[0] for call in central.commands]
        self.assertEqual(opcodes[0], wire.OP_HELLO, "HELLO must be first")
        self.assertIn(wire.OP_RUN, opcodes)
        self.assertIn(wire.OP_DEVICE_INFO, opcodes)
        run_index = opcodes.index(wire.OP_RUN)
        info_index = opcodes.index(wire.OP_DEVICE_INFO)
        self.assertGreater(info_index, run_index)
        # Event-count snapshot proves DEVICE_INFO was served before terminal.
        self.assertLess(central.commands[info_index][3], len(central.events))

        encoded = json.dumps(result, sort_keys=True)
        for forbidden in (
            "personal-device-id",
            "personal-label",
            "ble_address",
            "address",
        ):
            self.assertNotIn(forbidden, encoded)

    async def test_stderr_error_state_or_missing_cleanup_cannot_pass(self):
        for central in (
            FakeCentral(stderr=b"synthetic failure"),
            FakeCentral(terminal_state=3),
            FakeCentral(omit_cleanup=True),
        ):
            with self.subTest(central=central), self.assertRaises(bench.BenchError):
                await bench.run_exercise(
                    central,
                    preflight(),
                    timeout_s=2.0,
                    poll_interval_s=0,
                )


class CancellablePromptTest(unittest.IsolatedAsyncioTestCase):
    async def test_operator_wait_preserves_callback_process_control_and_timeout(self):
        for original in (
            asyncio.CancelledError("callback cancellation"),
            KeyboardInterrupt("callback interrupt"),
            SystemExit("callback exit"),
            asyncio.TimeoutError("callback-owned timeout"),
        ):
            async def fail(value=original):
                raise value

            with self.subTest(exception=type(original).__name__), self.assertRaises(
                type(original)
            ) as caught:
                await bench._await_operator_callback(
                    fail,
                    timeout_s=1.0,
                    label="test operator callback",
                )
            self.assertIs(caught.exception, original)

    async def test_stdin_line_reader_unregisters_on_success_and_cancellation(self):
        loop = asyncio.get_running_loop()

        read_fd, write_fd = os.pipe()
        stream = os.fdopen(read_fd, "r", encoding="utf-8")
        try:
            with mock.patch.object(sys, "stdin", stream), mock.patch.object(
                asyncio,
                "to_thread",
                side_effect=AssertionError("operator input must not start a thread"),
            ):
                pending = asyncio.create_task(bench._read_stdin_line())
                await asyncio.sleep(0)
                os.write(write_fd, b"VISIBLE\n")
                self.assertEqual(await asyncio.wait_for(pending, 1), "VISIBLE\n")
                self.assertFalse(loop.remove_reader(read_fd))
        finally:
            os.close(write_fd)
            stream.close()

        read_fd, write_fd = os.pipe()
        stream = os.fdopen(read_fd, "r", encoding="utf-8")
        try:
            with mock.patch.object(sys, "stdin", stream), mock.patch.object(
                asyncio,
                "to_thread",
                side_effect=AssertionError("operator input must not start a thread"),
            ):
                pending = asyncio.create_task(bench._read_stdin_line())
                await asyncio.sleep(0)
                pending.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await pending
                self.assertFalse(
                    loop.remove_reader(read_fd),
                    "cancelled input left a background event-loop reader",
                )
        finally:
            os.close(write_fd)
            stream.close()


class RebootWorkflowTest(unittest.IsolatedAsyncioTestCase):
    async def test_soft_reboot_is_acknowledged_as_a_separate_bounded_stage(self):
        central = FakeCentral()
        result = await bench.run_soft_reboot(central, preflight(), timeout_s=2.0)
        self.assertEqual(
            [call[0] for call in central.commands],
            [wire.OP_HELLO, wire.OP_RUN, wire.OP_SOFT_REBOOT],
        )
        self.assertEqual(result["stage"], "soft-reboot")
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["volatile_sentinel_armed"])
        self.assertEqual(result["pre_reboot_run"]["state_sequence"], ["running", "done"])
        self.assertEqual(result["pre_reboot_run"]["stderr_bytes"], 0)
        self.assertTrue(result["soft_reboot_acknowledged"])
        self.assertEqual(result["next_stage"], "post-reboot")
        self.assertNotIn(EXPECTED_VM_SENTINEL, json.dumps(result, sort_keys=True))

    async def test_pre_arm_failure_never_transmits_soft_reboot(self):
        for central in (
            FakeCentral(omit_pre_marker=True),
            FakeCentral(stderr=b"pre-arm failed"),
            FakeCentral(terminal_state=3),
        ):
            with self.subTest(central=central), self.assertRaises(bench.BenchError):
                await bench.run_soft_reboot(central, preflight(), timeout_s=2.0)
            self.assertNotIn(
                wire.OP_SOFT_REBOOT,
                [call[0] for call in central.commands],
            )

    async def test_fresh_connection_import_probe_completes_post_reboot_stage(self):
        central = FakeCentral()
        result = await bench.run_post_reboot(
            central,
            preflight(),
            timeout_s=2.0,
            poll_interval_s=0,
        )
        self.assertEqual([call[0] for call in central.commands[:2]], [wire.OP_HELLO, wire.OP_RUN])
        self.assertEqual(result["stage"], "post-reboot")
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["runtime_imported"])
        self.assertTrue(result["volatile_sentinel_absent"])
        self.assertEqual(result["run"]["state_sequence"], ["running", "done"])
        self.assertIsNone(result["next_stage"])

    async def test_post_reboot_rejects_a_connection_to_the_stale_vm_epoch(self):
        with self.assertRaises(bench.StaleVmEpochError):
            await bench.run_post_reboot(
                FakeCentral(stale_vm=True),
                preflight(),
                timeout_s=2.0,
                poll_interval_s=0,
            )


class QualificationWorkflowTest(unittest.IsolatedAsyncioTestCase):
    CANDIDATE_SIZE = 1_761_488

    def _connections(self, *, candidate_sha256="ab" * 32, stale_first_post=False):
        connections = [FakeCentral(live_immutable_sha256="cd" * 32)]
        for cycle in range(bench.QUALIFICATION_REBOOT_CYCLES):
            connections.append(FakeCentral())
            if cycle == 0 and stale_first_post:
                connections.append(FakeCentral(stale_vm=True))
            connections.append(FakeCentral())
        return connections

    async def test_one_exercise_and_exact_hash_chained_three_cycle_qualification(self):
        candidate_sha256 = "ab" * 32
        connections = self._connections(
            candidate_sha256=candidate_sha256,
            stale_first_post=True,
        )
        clock = FakeClock()
        connector = FakeConnector(connections, clock=clock)
        confirmations = []

        async def confirm_visual(pattern_id):
            confirmations.append(pattern_id)
            await asyncio.sleep(0)
            return True

        session_id = "12" * 16
        result = await bench.run_qualification(
            connector,
            "private-input-only",
            preflight(),
            candidate_sha256,
            self.CANDIDATE_SIZE,
            candidate_attestation(self.CANDIDATE_SIZE),
            timeout_s=2.0,
            poll_interval_s=0,
            sleep=clock.sleep,
            clock=clock.monotonic,
            confirm_visual=confirm_visual,
            session_id=session_id,
        )

        self.assertEqual(result["stage"], "qualification")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["session_id"], session_id)
        self.assertEqual(result["candidate_firmware_sha256"], candidate_sha256)
        self.assertEqual(result["candidate_firmware_size_bytes"], self.CANDIDATE_SIZE)
        self.assertEqual(
            result["exercise"]["candidate_verification"]["live_immutable_sha256"],
            "cd" * 32,
        )
        self.assertEqual(
            result["exercise"]["candidate_verification"]["immutable_bytes_verified"],
            candidate_attestation(self.CANDIDATE_SIZE)["size_bytes"],
        )
        self.assertEqual(
            result["exercise"]["candidate_verification"]["immutable_spans"],
            candidate_attestation(self.CANDIDATE_SIZE)["spans"],
        )
        self.assertEqual(
            result["exercise"]["operator_observation"],
            {"confirmed": True, "pattern_id": bench.VISUAL_PATTERN_ID},
        )
        self.assertEqual(confirmations, [bench.VISUAL_PATTERN_ID])
        self.assertEqual(result["exercise"]["stage_result"]["stage"], "exercise")
        self.assertEqual(len(result["cycles"]), 3)
        self.assertEqual([item["cycle"] for item in result["cycles"]], [1, 2, 3])

        predecessor = result["exercise"]["record_sha256"]
        self.assertEqual(
            predecessor,
            bench.record_sha256(
                {key: value for key, value in result["exercise"].items() if key != "record_sha256"}
            ),
        )
        for cycle in result["cycles"]:
            self.assertEqual(cycle["session_id"], session_id)
            self.assertEqual(cycle["candidate_firmware_sha256"], candidate_sha256)
            self.assertEqual(cycle["candidate_firmware_size_bytes"], self.CANDIDATE_SIZE)
            self.assertEqual(cycle["predecessor_sha256"], predecessor)
            self.assertTrue(cycle["old_connection_closed"])
            self.assertEqual(cycle["soft_reboot"]["stage"], "soft-reboot")
            self.assertEqual(cycle["post_reboot"]["stage"], "post-reboot")
            self.assertTrue(cycle["post_reboot"]["volatile_sentinel_absent"])
            self.assertEqual(
                cycle["record_sha256"],
                bench.record_sha256(
                    {key: value for key, value in cycle.items() if key != "record_sha256"}
                ),
            )
            predecessor = cycle["record_sha256"]

        self.assertEqual(result["qualification"]["reboot_cycles"], 3)
        self.assertEqual(result["qualification"]["fresh_vm_cycles"], 3)
        self.assertEqual(result["qualification"]["terminal_record_sha256"], predecessor)
        self.assertGreaterEqual(len(connector.calls), 8, "stale transition must be retried")
        self.assertTrue(all(item.disconnected for item in connections))
        self.assertGreaterEqual(
            clock.delays.count(bench.REBOOT_DELIVERY_GRACE_S),
            bench.QUALIFICATION_REBOOT_CYCLES,
        )
        self.assertIs(bench.validate_qualification_result(result), result)

        encoded = json.dumps(result, sort_keys=True)
        for forbidden in (
            EXPECTED_VM_SENTINEL,
            "private-input-only",
            "personal-device-id",
            "personal-label",
            "stdout_chunks",
            "raw_info",
        ):
            self.assertNotIn(forbidden, encoded)

    async def test_live_candidate_mismatch_fails_before_exercise(self):
        candidate_sha256 = "ab" * 32
        central = FakeCentral(live_immutable_sha256="ef" * 32)
        connector = FakeConnector([central])
        confirmation_called = False

        async def confirm_visual(_pattern_id):
            nonlocal confirmation_called
            confirmation_called = True
            return True

        with self.assertRaises(bench.BenchError):
            await bench.run_qualification(
                connector,
                "private-input-only",
                preflight(),
                candidate_sha256,
                self.CANDIDATE_SIZE,
                candidate_attestation(self.CANDIDATE_SIZE),
                timeout_s=2.0,
                poll_interval_s=0,
                confirm_visual=confirm_visual,
                session_id="56" * 16,
            )
        self.assertFalse(confirmation_called)
        self.assertEqual(
            [call[0] for call in central.commands],
            [wire.OP_HELLO, wire.OP_RUN],
            "the display exercise must not start after a live digest mismatch",
        )

    async def test_operator_confirmation_is_required_before_any_reboot(self):
        connections = self._connections()
        connector = FakeConnector(connections)

        async def refuse_visual(_pattern_id):
            return False

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
                confirm_visual=refuse_visual,
                session_id="56" * 16,
            )
        self.assertEqual(len(connector.calls), 1)
        self.assertNotIn(
            wire.OP_SOFT_REBOOT,
            [call[0] for call in connections[0].commands],
        )

    async def test_nontransition_post_failure_is_terminal_and_never_retried(self):
        initial = FakeCentral(live_immutable_sha256="cd" * 32)
        soft = FakeCentral()
        broken_post = FakeCentral(post_failure=True)
        would_pass = FakeCentral()
        connector = FakeConnector([initial, soft, broken_post, would_pass])

        async def confirm_visual(_pattern_id):
            return True

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
                confirm_visual=confirm_visual,
                session_id="56" * 16,
            )
        self.assertEqual(len(connector.calls), 3)
        self.assertEqual(connector.centrals, [would_pass])

    async def test_disconnected_probe_link_loss_retries_but_connected_io_is_terminal(self):
        clock = FakeClock()
        lost = FakeCentral(post_link_loss=True)
        fresh = FakeCentral()
        result, attempts = await bench._await_fresh_post_reboot(
            FakeConnector([lost, fresh], clock=clock),
            "private-input-only",
            preflight(),
            timeout_s=1.0,
            poll_interval_s=0,
            sleep=clock.sleep,
            clock=clock.monotonic,
        )
        self.assertEqual(result["stage"], "post-reboot")
        self.assertEqual(attempts, 2)
        self.assertFalse(lost.is_connected)

        connected = FakeCentral(
            post_link_loss=True,
            link_loss_while_connected=True,
        )
        connector = FakeConnector([connected, FakeCentral()], clock=FakeClock())
        with self.assertRaises(central_module.PbleLinkLossError):
            await bench._await_fresh_post_reboot(
                connector,
                "private-input-only",
                preflight(),
                timeout_s=1.0,
                poll_interval_s=0,
                sleep=asyncio.sleep,
            )
        self.assertEqual(len(connector.calls), 1)

    async def test_more_than_twenty_connection_failures_recover_before_deadline(self):
        clock = FakeClock()
        transient = [
            central_module.PbleConnectError("temporarily unavailable")
            for _ in range(25)
        ]
        connections = [
            FakeCentral(live_immutable_sha256="cd" * 32),
            FakeCentral(),
            *transient,
            FakeCentral(),
            FakeCentral(),
            FakeCentral(),
            FakeCentral(),
            FakeCentral(),
        ]
        connector = FakeConnector(connections, clock=clock)

        async def confirm_visual(_pattern_id):
            return True

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
        self.assertEqual(result["cycles"][0]["reconnect_attempts"], 26)
        self.assertEqual(result["status"], "passed")

    async def test_reconnect_deadline_covers_probe_and_has_no_extra_window(self):
        clock = FakeClock()
        central = FakeCentral(
            clock=clock,
            post_probe_advance_s=0.02,
        )
        connector = FakeConnector([(0.24, central)], clock=clock)
        with self.assertRaises(bench.BenchError):
            await bench._await_fresh_post_reboot(
                connector,
                "private-input-only",
                preflight(),
                timeout_s=0.5,
                poll_interval_s=0,
                sleep=clock.sleep,
                clock=clock.monotonic,
            )
        self.assertGreaterEqual(clock.now, 0.5)
        self.assertLess(clock.now, 0.6)

    async def test_persistent_stale_vm_stops_at_the_one_deadline(self):
        clock = FakeClock()
        connector = FakeConnector(
            [FakeCentral(stale_vm=True) for _ in range(100)],
            clock=clock,
        )
        with self.assertRaises(bench.BenchError):
            await bench._await_fresh_post_reboot(
                connector,
                "private-input-only",
                preflight(),
                timeout_s=0.65,
                poll_interval_s=0,
                sleep=clock.sleep,
                clock=clock.monotonic,
            )
        self.assertGreaterEqual(clock.now, 0.649)
        self.assertLess(clock.now, 0.75)
        self.assertLess(len(connector.calls), 100)

    async def test_old_link_must_be_proven_closed(self):
        async def confirm_visual(_pattern_id):
            return True

        already_dropped = self._connections()
        already_dropped[1] = FakeCentral(already_dropped=True)
        passed = await bench.run_qualification(
            FakeConnector(already_dropped),
            "private-input-only",
            preflight(),
            "ab" * 32,
            self.CANDIDATE_SIZE,
            candidate_attestation(self.CANDIDATE_SIZE),
            timeout_s=2.0,
            poll_interval_s=0,
            confirm_visual=confirm_visual,
            session_id="9a" * 16,
        )
        self.assertTrue(passed["cycles"][0]["old_connection_closed"])

        stuck = self._connections()
        stuck[1] = FakeCentral(disconnect_error=True)
        connector = FakeConnector(stuck)
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
                confirm_visual=confirm_visual,
                session_id="9b" * 16,
            )
        self.assertEqual(len(connector.calls), 2)

    async def test_complete_qualification_round_trips_exclusively_as_private_json(self):
        connector = FakeConnector(self._connections(candidate_sha256="cd" * 32))

        async def confirm_visual(_pattern_id):
            return True

        result = await bench.run_qualification(
            connector,
            "private-input-only",
            preflight(),
            "cd" * 32,
            self.CANDIDATE_SIZE,
            candidate_attestation(self.CANDIDATE_SIZE),
            timeout_s=2.0,
            poll_interval_s=0,
            confirm_visual=confirm_visual,
            session_id="34" * 16,
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "qualification.json"
            payload = bench.write_result_exclusive(target, result)
            loaded = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(loaded, result)
            self.assertEqual(payload, target.read_bytes())
            self.assertEqual(os.stat(target).st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                bench.write_result_exclusive(target, result)

        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn(EXPECTED_VM_SENTINEL, encoded)
        self.assertNotIn("personal-device-id", encoded)
        self.assertNotIn("personal-label", encoded)
        self.assertNotIn("private-input-only", encoded)

        mutations = []
        for mutate in (
            lambda value: value.update({"session_id": "ff" * 16}),
            lambda value: value.update({"candidate_firmware_size_bytes": 1}),
            lambda value: value["exercise"]["candidate_verification"].update(
                {"immutable_spans": [{"offset": 0, "size_bytes": 1}]}
            ),
            lambda value: value["exercise"].update({"record_sha256": "00" * 32}),
            lambda value: value["cycles"][0].update({"predecessor_sha256": "00" * 32}),
            lambda value: value["cycles"][1].update({"cycle": 1}),
            lambda value: value["cycles"][2].update({"record_sha256": "00" * 32}),
            lambda value: value["cycles"][0]["post_reboot"].update({"status": "error"}),
            lambda value: value["qualification"].update(
                {"terminal_record_sha256": "00" * 32}
            ),
            lambda value: value.update({"unexpected": True}),
            lambda value: value["exercise"].update({"raw_info": "forbidden"}),
        ):
            changed = json.loads(json.dumps(result))
            mutate(changed)
            mutations.append(changed)
        for changed in mutations:
            with self.subTest(changed=changed), self.assertRaises(bench.BenchError):
                bench.validate_qualification_result(changed)

        semantic_mutations = []
        for mutate in (
            lambda value: value["exercise"]["stage_result"]["memory"].update(
                {"gc_free_bytes": "personal-memory-label"}
            ),
            lambda value: value["exercise"]["stage_result"][
                "pble_responsiveness"
            ].update(
                {"info_reads": 0, "device_info_commands": 0, "refresh_indexes": []}
            ),
            lambda value: value["cycles"][0]["post_reboot"]["runtime"].update(
                {"agent": "personal-device-id"}
            ),
            lambda value: value["cycles"][1]["post_reboot"]["runtime"].update(
                {"agent": "0.5.0"}
            ),
            lambda value: value["exercise"]["operator_observation"].update(
                {"confirmed": 1}
            ),
            lambda value: value["exercise"]["candidate_verification"].update(
                {"schema_version": True}
            ),
            lambda value: value["exercise"]["candidate_verification"][
                "immutable_spans"
            ][0].update({"offset": 0.0}),
            lambda value: value["exercise"]["candidate_attestation"].update(
                {
                    "size_bytes": float(
                        value["exercise"]["candidate_attestation"]["size_bytes"]
                    )
                }
            ),
            lambda value: value["exercise"].update(
                {
                    "candidate_firmware_size_bytes": float(
                        value["exercise"]["candidate_firmware_size_bytes"]
                    )
                }
            ),
            lambda value: value["cycles"][0].update(
                {
                    "candidate_firmware_size_bytes": float(
                        value["cycles"][0]["candidate_firmware_size_bytes"]
                    )
                }
            ),
            lambda value: value["cycles"][0].update({"cycle": 1.0}),
            lambda value: value["exercise"]["stage_result"]["display"].update(
                {"geometry": [172.0, 320.0, 34.0, 0.0]}
            ),
            lambda value: value["exercise"]["stage_result"]["display"].update(
                {"backlight_sequence": [0, 1, 0]}
            ),
            lambda value: value["cycles"][0]["post_reboot"]["run"].update(
                {"stderr_bytes": False}
            ),
            lambda value: value["cycles"][0]["post_reboot"]["run"].update(
                {"stdout_bytes": 0}
            ),
        ):
            changed = json.loads(json.dumps(result))
            mutate(changed)
            semantic_mutations.append(rechain_qualification(changed))
        for changed in semantic_mutations:
            with self.subTest(semantic=changed), self.assertRaises(bench.BenchError):
                bench.validate_qualification_result(changed)

        with tempfile.TemporaryDirectory() as directory:
            for index, changed in enumerate(mutations[:1] + semantic_mutations):
                rejected = Path(directory) / ("rejected-%d.json" % index)
                with self.assertRaises(bench.BenchError):
                    bench.write_result_exclusive(rejected, changed)
                self.assertFalse(rejected.exists())


class PbleCentralConnectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_notify_setup_failure_transactionally_disconnects_the_link(self):
        clients = []

        class FakeBleakClient:
            def __init__(self, _address, timeout):
                self.timeout = timeout
                self.is_connected = False
                self.disconnect_calls = 0
                clients.append(self)

            async def connect(self):
                self.is_connected = True

            async def start_notify(self, _uuid, _callback):
                raise OSError("GATT cache is restarting")

            async def disconnect(self):
                self.disconnect_calls += 1
                self.is_connected = False

        fake_bleak = types.ModuleType("bleak")
        fake_bleak.BleakClient = FakeBleakClient
        fake_bleak.BleakScanner = object
        with mock.patch.dict(sys.modules, {"bleak": fake_bleak}):
            with self.assertRaises(central_module.PbleConnectError):
                await central_module.PbleCentral.connect(
                    "private-input-only",
                    timeout=0.5,
                )
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0].disconnect_calls, 1)
        self.assertFalse(clients[0].is_connected)

    async def test_cleanup_returning_with_a_retained_link_is_terminal(self):
        clients = []

        class FakeBleakClient:
            def __init__(self, _address, timeout):
                self.timeout = timeout
                self.is_connected = False
                self.disconnect_calls = 0
                clients.append(self)

            async def connect(self):
                self.is_connected = True

            async def start_notify(self, _uuid, _callback):
                raise OSError("notify setup failed")

            async def disconnect(self):
                self.disconnect_calls += 1
                # Deliberately return without closing the partial link.

        fake_bleak = types.ModuleType("bleak")
        fake_bleak.BleakClient = FakeBleakClient
        fake_bleak.BleakScanner = object
        with mock.patch.dict(sys.modules, {"bleak": fake_bleak}):
            with self.assertRaises(central_module.PbleConnectCleanupError):
                await central_module.PbleCentral.connect(
                    "private-input-only",
                    timeout=0.5,
                )
        self.assertEqual(clients[0].disconnect_calls, 1)
        self.assertTrue(clients[0].is_connected)

    async def test_process_control_exceptions_are_cleaned_and_preserved(self):
        for exception_type in (KeyboardInterrupt, SystemExit, GeneratorExit):
            clients = []

            class FakeBleakClient:
                def __init__(self, _address, timeout):
                    self.timeout = timeout
                    self.is_connected = False
                    clients.append(self)

                async def connect(self):
                    self.is_connected = True

                async def start_notify(self, _uuid, _callback):
                    raise exception_type("operator stop")

                async def disconnect(self):
                    self.is_connected = False

            fake_bleak = types.ModuleType("bleak")
            fake_bleak.BleakClient = FakeBleakClient
            fake_bleak.BleakScanner = object
            with self.subTest(exception=exception_type), mock.patch.dict(
                sys.modules,
                {"bleak": fake_bleak},
            ):
                with self.assertRaises(exception_type):
                    await central_module.PbleCentral.connect(
                        "private-input-only",
                        timeout=0.5,
                    )
            self.assertFalse(clients[0].is_connected)

    async def test_setup_and_cleanup_exception_precedence_matrix(self):
        cases = (
            (
                asyncio.CancelledError("original cancellation"),
                SystemExit("cleanup exit"),
                False,
                "original",
            ),
            (
                KeyboardInterrupt("original interrupt"),
                asyncio.CancelledError("cleanup cancellation"),
                False,
                "original",
            ),
            (
                RuntimeError("ordinary setup failure"),
                asyncio.CancelledError("cleanup cancellation"),
                False,
                "cleanup",
            ),
            (
                RuntimeError("ordinary setup failure"),
                OSError("ordinary cleanup failure"),
                False,
                central_module.PbleConnectError,
            ),
            (
                RuntimeError("ordinary setup failure"),
                OSError("ordinary cleanup failure"),
                True,
                central_module.PbleConnectCleanupError,
            ),
        )

        for original, cleanup, retain_link, expected in cases:
            clients = []

            class FakeBleakClient:
                def __init__(self, _address, timeout):
                    self.timeout = timeout
                    self.is_connected = False
                    clients.append(self)

                async def connect(self):
                    self.is_connected = True

                async def start_notify(self, _uuid, _callback):
                    raise original

                async def disconnect(self):
                    if not retain_link:
                        self.is_connected = False
                    raise cleanup

            fake_bleak = types.ModuleType("bleak")
            fake_bleak.BleakClient = FakeBleakClient
            fake_bleak.BleakScanner = object
            expected_type = type(original) if expected == "original" else type(cleanup)
            if isinstance(expected, type):
                expected_type = expected

            with self.subTest(
                original=type(original).__name__,
                cleanup=type(cleanup).__name__,
                retain_link=retain_link,
            ), mock.patch.dict(sys.modules, {"bleak": fake_bleak}):
                with self.assertRaises(expected_type) as raised:
                    await central_module.PbleCentral.connect(
                        "private-input-only",
                        timeout=0.5,
                    )

            if expected == "original":
                self.assertIs(raised.exception, original)
            elif expected == "cleanup":
                self.assertIs(raised.exception, cleanup)
            else:
                self.assertIs(raised.exception.__cause__, original)
            self.assertEqual(clients[0].is_connected, retain_link)

    async def test_setup_timeout_reserves_cleanup_inside_the_supplied_budget(self):
        clients = []
        cancelled_at = []
        loop = asyncio.get_running_loop()

        class FakeBleakClient:
            def __init__(self, _address, timeout):
                self.timeout = timeout
                self.is_connected = False
                clients.append(self)

            async def connect(self):
                self.is_connected = True
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled_at.append(loop.time())
                    raise

            async def start_notify(self, _uuid, _callback):
                raise AssertionError("unreachable")

            async def disconnect(self):
                self.is_connected = False

        fake_bleak = types.ModuleType("bleak")
        fake_bleak.BleakClient = FakeBleakClient
        fake_bleak.BleakScanner = object
        timeout = 0.12
        started = loop.time()
        with mock.patch.dict(sys.modules, {"bleak": fake_bleak}):
            with self.assertRaises(central_module.PbleConnectError):
                await asyncio.wait_for(
                    central_module.PbleCentral.connect(
                        "private-input-only",
                        timeout=timeout,
                    ),
                    timeout=timeout + 0.1,
                )
        elapsed = loop.time() - started
        self.assertEqual(len(cancelled_at), 1)
        self.assertLess(cancelled_at[0] - started, timeout)
        self.assertLessEqual(elapsed, timeout + 0.03)
        self.assertFalse(clients[0].is_connected)

    async def test_link_loss_type_requires_independent_disconnected_state(self):
        class FakeBleakClient:
            def __init__(self, connected):
                self.is_connected = connected

            async def write_gatt_char(self, _uuid, _packet, response):
                del response
                raise OSError("backend write failed")

        disconnected = central_module.PbleCentral(FakeBleakClient(False))
        with self.assertRaises(central_module.PbleLinkLossError):
            await disconnected._write(b"frame")

        connected = central_module.PbleCentral(FakeBleakClient(True))
        with self.assertRaises(OSError):
            await connected._write(b"frame")

        with self.assertRaises(central_module.PbleLinkLossError):
            await disconnected._await_rsp(1, 0)
        with self.assertRaises(asyncio.TimeoutError):
            await connected._await_rsp(1, 0)


class NativeSoftRebootOrderingTest(unittest.TestCase):
    def test_ok_response_has_a_bounded_delivery_grace_before_vm_reset(self):
        source = RUNNER_SOURCE.read_text(encoding="utf-8", errors="strict")
        start = source.index("uint8_t pble_runner_soft_reboot(")
        end = source.index("// Auto-run entry", start)
        body = source[start:end]

        response = "pble_proto_emit_id(PBLE_TYPE_RSP"
        timer_start = (
            "esp_timer_start_once(g_soft_reboot_timer, "
            "PBLE_SOFT_REBOOT_GRACE_US)"
        )
        self.assertIn(response, body)
        self.assertIn(timer_start, body)
        self.assertLess(
            body.index(response),
            body.index(timer_start),
            "SOFT_REBOOT must submit RSP{OK} before arming VM teardown",
        )
        self.assertNotIn(
            "mp_sched_exception(",
            body,
            "the host-task handler must not tear the VM down inline",
        )
        self.assertIn("return PBLE_NO_RSP;", body)

        self.assertIn('#include "esp_timer.h"', source)
        self.assertIn("#define PBLE_SOFT_REBOOT_GRACE_US 250000ULL", source)
        self.assertIn("static esp_timer_handle_t g_soft_reboot_timer;", source)
        self.assertIn("static volatile bool g_soft_reboot_pending;", source)

        callback_start = source.index("static void soft_reboot_timer_cb(")
        callback_end = source.index("uint8_t pble_runner_soft_reboot(", callback_start)
        callback = source[callback_start:callback_end]
        self.assertIn("mp_sched_exception(se)", callback)
        self.assertIn("mp_hal_wake_main_task()", callback)

        register_start = source.index("void pble_runner_register(void)")
        register_end = source.index("// =", register_start)
        register = source[register_start:register_end]
        self.assertIn("esp_timer_create(", register)

    def test_duplicate_or_unsendable_reboot_never_schedules_reset(self):
        source = RUNNER_SOURCE.read_text(encoding="utf-8", errors="strict")
        start = source.index("uint8_t pble_runner_soft_reboot(")
        end = source.index("// Auto-run entry", start)
        body = source[start:end]

        self.assertIn("if (g_soft_reboot_pending)", body)
        self.assertIn("return PBLE_EBUSY;", body)
        response = body.index("pble_proto_emit_id(PBLE_TYPE_RSP")
        timer_start = body.index("esp_timer_start_once(")
        self.assertLess(response, timer_start)
        before_response = body[:response]
        self.assertNotIn("esp_timer_start_once(", before_response)

    def test_cli_is_exact_profile_staged_and_never_accepts_identity_output(self):
        required = [
            "--stage",
            "exercise",
            "--address",
            "private-input-only",
            "--preflight",
            "preflight.json",
            "--output",
            "result.json",
        ]
        args = bench._parse_args(required)
        self.assertEqual(args.stage, "exercise")
        self.assertEqual(args.address, "private-input-only")
        for stage in ("exercise", "soft-reboot", "post-reboot"):
            changed = list(required)
            changed[changed.index("exercise")] = stage
            self.assertEqual(bench._parse_args(changed).stage, stage)
        qualified = list(required)
        qualified[qualified.index("exercise")] = "qualification"
        qualified.extend(["--firmware-bin", "firmware.bin"])
        self.assertEqual(bench._parse_args(qualified).stage, "qualification")
        with self.assertRaises(SystemExit):
            bench._parse_args(
                [item for item in qualified if item not in ("--firmware-bin", "firmware.bin")]
            )
        with self.assertRaises(SystemExit):
            bench._parse_args(required + ["--firmware-bin", "firmware.bin"])
        for missing in ("--address", "--preflight", "--output"):
            changed = list(required)
            index = changed.index(missing)
            del changed[index : index + 2]
            with self.subTest(missing=missing), self.assertRaises(SystemExit):
                bench._parse_args(changed)
        with self.assertRaises(SystemExit):
            bench._parse_args(required + ["--profile", "esp32"])


class EvidenceFileTest(unittest.TestCase):
    def test_preflight_load_and_result_write_are_strict_and_non_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preflight_path = root / "preflight.json"
            preflight_path.write_text(json.dumps(preflight()), encoding="utf-8")
            self.assertEqual(bench.load_preflight(preflight_path), preflight())

            result_path = root / "result.json"
            result = {"schema_version": 1, "status": "passed"}
            payload = bench.write_result_exclusive(result_path, result)
            self.assertEqual(result_path.read_bytes(), payload)
            self.assertEqual(json.loads(payload), result)
            self.assertEqual(os.stat(result_path).st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                bench.write_result_exclusive(result_path, result)

            link_path = root / "preflight-link.json"
            link_path.symlink_to(preflight_path)
            with self.assertRaises(bench.BenchError):
                bench.load_preflight(link_path)

    def test_candidate_firmware_inspection_binds_only_immutable_live_spans(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "firmware.bin"
            payload = bytearray(b"\xff" * 0x10020)
            payload[:16] = b"candidate-boot!!"
            payload[0x8000:0x8010] = b"partition-table!"
            payload[0x10000:] = b"candidate-application".ljust(0x20, b"!")
            candidate.write_bytes(payload)
            expected_sha256 = hashlib.sha256(payload).hexdigest()
            immutable_bytes = bytes(payload[:0x9000] + payload[0x10000:])
            expected_attestation = {
                "sha256": hashlib.sha256(immutable_bytes).hexdigest(),
                "size_bytes": len(immutable_bytes),
                "spans": [
                    {"offset": 0, "size_bytes": 0x9000},
                    {"offset": 0x10000, "size_bytes": 0x20},
                ],
            }
            self.assertEqual(
                bench.hash_candidate_firmware(candidate),
                expected_sha256,
            )
            self.assertEqual(
                bench.inspect_candidate_firmware(candidate),
                {
                    "sha256": expected_sha256,
                    "size_bytes": len(payload),
                    "attestation": expected_attestation,
                },
            )

            live_flash = bytearray(payload)
            live_flash[0x9000:0x10000] = b"\x00" * 0x7000
            live_immutable = bytes(live_flash[:0x9000] + live_flash[0x10000:])
            self.assertNotEqual(hashlib.sha256(live_flash).hexdigest(), expected_sha256)
            self.assertEqual(
                hashlib.sha256(live_immutable).hexdigest(),
                expected_attestation["sha256"],
                "runtime-owned NVS/PHY bytes must not invalidate immutable firmware",
            )

            malformed = root / "malformed" / "firmware.bin"
            malformed.parent.mkdir()
            malformed_payload = bytearray(payload)
            malformed_payload[0x9000] = 0
            malformed.write_bytes(malformed_payload)
            with self.assertRaises(bench.BenchError):
                bench.inspect_candidate_firmware(malformed)

            metadata = candidate.stat()
            changed_metadata = types.SimpleNamespace(
                st_mode=metadata.st_mode,
                st_size=metadata.st_size,
                st_ino=metadata.st_ino,
                st_dev=metadata.st_dev,
                st_mtime_ns=metadata.st_mtime_ns + 1,
                st_ctime_ns=metadata.st_ctime_ns + 1,
            )
            with mock.patch.object(
                bench.os,
                "fstat",
                side_effect=[metadata, changed_metadata],
            ), self.assertRaises(bench.BenchError):
                bench.inspect_candidate_firmware(candidate)

            class ChangingStream:
                def __init__(self, descriptor):
                    self.descriptor = descriptor
                    self.reads = 0

                def __enter__(self):
                    return self

                def __exit__(self, _type, _value, _traceback):
                    os.close(self.descriptor)

                def fileno(self):
                    return self.descriptor

                def seek(self, _offset):
                    return 0

                def read(self, _size):
                    self.reads += 1
                    changed = bytearray(payload)
                    if self.reads > 1:
                        changed[0] ^= 0x01
                    return bytes(changed)

            with mock.patch.object(
                bench.os,
                "fdopen",
                side_effect=lambda descriptor, _mode: ChangingStream(descriptor),
            ), self.assertRaises(bench.BenchError):
                bench.inspect_candidate_firmware(candidate)

            linked = root / "linked"
            linked.mkdir()
            link = linked / "firmware.bin"
            link.symlink_to(candidate)
            with self.assertRaises(bench.BenchError):
                bench.hash_candidate_firmware(link)
            empty = root / "empty" / "firmware.bin"
            empty.parent.mkdir()
            empty.write_bytes(b"")
            with self.assertRaises(bench.BenchError):
                bench.hash_candidate_firmware(empty)
            wrong_name = root / "application.bin"
            wrong_name.write_bytes(b"not the merged image")
            with self.assertRaises(bench.BenchError):
                bench.hash_candidate_firmware(wrong_name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
