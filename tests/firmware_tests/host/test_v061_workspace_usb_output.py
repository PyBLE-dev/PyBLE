#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Native USB output regression with an explicit hostile, host-only FIFO model.

No board, BLE, serial endpoint, firmware image, or physical receipt is used.
"""
import builtins
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_v061_workspace_acquisition as fixture
import test_v061_workspace_hardware as hardware_fixture

HARDWARE = hardware_fixture.HARDWARE
KIND = fixture.GATE.WORKSPACE_PROVISIONING_ORDER[1]
PREFIX = b"PYBLE_WORKSPACE_OBSERVATION:"


class OverwritableFIFO:
    """DTR-low finite TX queue; only modeled host drain events deliver bytes.

    Writes return their requested length even after overwriting old bytes,
    matching why that return value cannot prove native USB delivery.
    """
    def __init__(self, capacity=256, *, drain=True, cooked=False):
        self.capacity, self.drain_enabled, self.cooked = capacity, drain, cooked
        self.pending, self.delivered = bytearray(), bytearray()
        self.writes, self.sleeps = [], []
        self.lost = 0
        self.on_sleep = None

    def write(self, value):
        self.writes.append(value)
        raw = value.encode("ascii")
        if self.cooked:
            raw = raw.replace(b"\n", b"\r\n")
        self.pending.extend(raw)
        excess = max(0, len(self.pending) - self.capacity)
        self.lost += excess
        del self.pending[:excess]
        return len(value)

    def sleep_ms(self, duration):
        if type(duration) is not int or duration not in (50, 100):
            raise AssertionError("unexpected or unbounded pacing")
        self.sleeps.append(duration)
        if self.on_sleep:
            self.on_sleep()
        if self.drain_enabled:
            self.drain()

    def drain(self):
        self.delivered.extend(self.pending)
        self.pending.clear()

    def finish(self):
        self.drain()
        return bytes(self.delivered)


def expected_output(observation):
    return b"\n" + PREFIX + json.dumps({"observation": observation, "workspace_probe": None}).encode() + b"\n"


def execute_source(source, observation, fifo, *, inspect_spies=None):
    getter = mock.Mock(return_value=copy.deepcopy(observation))
    serializer = mock.Mock(wraps=json.dumps)
    modules = {"os": SimpleNamespace(statvfs=mock.Mock(side_effect=AssertionError("refusal cannot probe filesystem"))),
               "json": SimpleNamespace(dumps=serializer),
               "pyble_workspace": SimpleNamespace(read_boot_observation=getter),
               "sys": SimpleNamespace(stdout=fifo), "time": SimpleNamespace(sleep_ms=fifo.sleep_ms)}
    def imported(name, *args, **kwargs):
        if name not in modules:
            raise AssertionError("unreviewed import or side effect: " + name)
        return modules[name]
    def printed(*values, sep=" ", end="\n"):
        fifo.write(sep.join(str(value) for value in values) + end)
    environment = {"__builtins__": {**vars(builtins), "__import__": imported, "print": printed}}
    if inspect_spies:
        inspect_spies(getter, serializer)
    exec(compile(source, "<host-generated-readonly-query>", "exec"), environment)
    return getter, serializer


class NativeUSBOutputTests(unittest.IsolatedAsyncioTestCase):
    async def source_for(self, profile="waveshare-esp32-s3-lcd-147b", *, transport="usb-repl"):
        with tempfile.TemporaryDirectory(prefix="pyble-usb-source-host-") as directory:
            backend = HARDWARE.WorkspaceHardware(fixture.synthetic_binding(profile),
                                                  repo_root=Path(directory), candidate_dir=Path(directory))
            backend.work_dir = Path(directory)
            backend.kind = KIND if transport == "usb-repl" else fixture.GATE.WORKSPACE_PROVISIONING_ORDER[0]
            backend.phase = "booted"
            backend._usb_command = mock.AsyncMock(return_value=b"host transcript")
            backend._ble_command = mock.AsyncMock(return_value=b"host transcript")
            with mock.patch.object(HARDWARE, "_usb_exact", return_value=True):
                await backend.observe(fixture.CHALLENGE, transport)
            called = backend._usb_command if transport == "usb-repl" else backend._ble_command
            called.assert_awaited_once()
            return called.call_args.args[0]

    def observation(self):
        return dict(fixture.boot_observation(KIND),
                    challenge=fixture.CHALLENGE, boot_id=fixture.BOOT_ID)

    def test_old_one_shot_stdout_loses_prefix_in_hostile_dtr_low_fifo(self):
        fifo = OverwritableFIFO()
        wanted = expected_output(self.observation())
        self.assertGreater(len(wanted), fifo.capacity)
        self.assertEqual(fifo.write(wanted.decode()), len(wanted))
        raw = fifo.finish()
        self.assertGreater(fifo.lost, 0)
        with self.assertRaises(fixture.GATE.QualificationError):
            fixture.GATE.parse_workspace_response(raw)

    async def test_native_query_survives_fifo_with_exact_unchanged_parser_bytes(self):
        for profile in ("waveshare-esp32-s3-lcd-147b", "rpi-pico2-w"):
            source = await self.source_for(profile)
            for capacity in (64, 256):
                for cooked in (False, True):
                    with self.subTest(profile=profile, capacity=capacity, cooked=cooked):
                        fifo = OverwritableFIFO(capacity, cooked=cooked)
                        observation = self.observation()
                        getter, serializer = execute_source(source, observation, fifo)
                        wanted = expected_output(observation)
                        if cooked:
                            wanted = wanted.replace(b"\n", b"\r\n")
                        self.assertEqual(fifo.finish(), wanted)
                        self.assertEqual(fifo.lost, 0)
                        self.assertTrue(all(0 < len(part) <= 16 for part in fifo.writes))
                        self.assertEqual(fifo.sleeps, [100] + [50] * len(fifo.writes) + [100])
                        self.assertLessEqual(sum(fifo.sleeps), 3400)
                        getter.assert_called_once_with(fixture.CHALLENGE)
                        serializer.assert_called_once()
                        reply = fixture.GATE.parse_workspace_response(fifo.finish())
                        fixture.GATE._validate_boot_observation(
                            {"challenge": fixture.CHALLENGE, "boot_id": fixture.BOOT_ID}, reply, KIND)

    async def test_native_query_serializes_once_before_any_delays(self):
        source = await self.source_for()
        observation = self.observation()
        fifo = OverwritableFIFO()
        spies = []
        def mutate():
            self.assertEqual([spy.call_count for spy in spies], [1, 1])
            observation["mount_attempts"] = 65535
        wanted = expected_output(observation)
        fifo.on_sleep = mutate
        getter, serializer = execute_source(
            source, observation, fifo, inspect_spies=lambda *values: spies.extend(values))
        self.assertEqual(fifo.finish(), wanted)
        getter.assert_called_once()
        serializer.assert_called_once()

    async def test_max_counter_values_fit_bound_but_still_cannot_qualify(self):
        source = await self.source_for()
        observation = self.observation()
        for key, value in observation.items():
            if type(value) is int and key != "schema_version":
                observation[key] = 65535
        fifo = OverwritableFIFO()
        execute_source(source, observation, fifo)
        self.assertLessEqual(len(fifo.finish()), 1024)
        self.assertLessEqual(sum(fifo.sleeps), 3400)
        with self.assertRaises(fixture.GATE.QualificationError):
            fixture.GATE._validate_boot_observation(
                {"challenge": fixture.CHALLENGE, "boot_id": fixture.BOOT_ID},
                fixture.GATE.parse_workspace_response(fifo.finish()), KIND)

    async def test_exact_output_ceiling_has_at_most_3400ms_requested_pacing(self):
        observation = dict(self.observation(), extra="")
        observation["extra"] = "x" * (1024 - len(expected_output(observation)))
        self.assertEqual(len(expected_output(observation)), 1024)
        fifo = OverwritableFIFO()
        execute_source(await self.source_for(), observation, fifo)
        self.assertEqual(fifo.finish(), expected_output(observation))
        self.assertEqual(sum(fifo.sleeps), 3400)
        self.assertEqual(len(fifo.writes), 64)

    async def test_oversize_or_non_ascii_rejected_before_first_write(self):
        source = await self.source_for()
        for added in ("x" * 1024, "\u00e9"):
            observation = dict(self.observation(), unexpected=added)
            fifo = OverwritableFIFO()
            # MicroPython may emit UTF-8 rather than CPython's ASCII escapes.
            with mock.patch.object(json, "dumps", wraps=lambda value: ORIGINAL_DUMPS(value, ensure_ascii=False)):
                with self.assertRaises((ValueError, RuntimeError)):
                    execute_source(source, observation, fifo)
            self.assertEqual(fifo.writes, [])
            self.assertEqual(fifo.sleeps, [])

    async def test_pacing_is_not_delivery_proof_when_host_never_drains(self):
        fifo = OverwritableFIFO(drain=False)
        execute_source(await self.source_for(), self.observation(), fifo)
        self.assertGreater(fifo.lost, 0)
        with self.assertRaises(fixture.GATE.QualificationError):
            fixture.GATE.parse_workspace_response(fifo.finish())

    async def test_duplicate_marker_or_missing_bytes_are_not_repaired(self):
        fifo = OverwritableFIFO()
        execute_source(await self.source_for(), self.observation(), fifo)
        raw = fifo.finish()
        for invalid in (raw + raw, raw.replace(PREFIX, b"", 1), raw[:-10]):
            with self.subTest(raw=invalid[:30]), self.assertRaises(fixture.GATE.QualificationError):
                fixture.GATE.parse_workspace_response(invalid)

    async def test_faulted_incomplete_or_overflow_record_remains_unqualified(self):
        source = await self.source_for()
        for field, value in (("fault", True), ("complete", False), ("overflow", True)):
            fifo = OverwritableFIFO()
            execute_source(source, dict(self.observation(), **{field: value}), fifo)
            with self.subTest(field=field), self.assertRaises(fixture.GATE.QualificationError):
                fixture.GATE._validate_boot_observation(
                    {"challenge": fixture.CHALLENGE, "boot_id": fixture.BOOT_ID},
                    fixture.GATE.parse_workspace_response(fifo.finish()), KIND)

    async def test_bridge_and_ble_paths_retain_original_unpaced_source(self):
        for profile, transport in (("esp32-4mb", "usb-repl"), ("esp32-c3-4mb", "usb-repl"),
                                   ("esp32-s3-n16r8", "usb-repl"),
                                   ("waveshare-esp32-s3-lcd-147b", "pble-run"),
                                   ("rpi-pico2-w", "pble-run")):
            source = await self.source_for(profile, transport=transport)
            self.assertNotIn("sleep_ms", source)
            self.assertNotIn("stdout.write", source)
            self.assertEqual(source.count("read_boot_observation("), 1)
            self.assertEqual(source.count("json.dumps("), 1)


ORIGINAL_DUMPS = json.dumps


class RawREPLGuards(unittest.TestCase):
    def probe(self, *, stderr=b"", complete=True, identity=True, cancel=False):
        temporary = tempfile.TemporaryDirectory(prefix="pyble-usb-framing-host-")
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        backend = HARDWARE.WorkspaceHardware(hardware_fixture.binding(), repo_root=folder, candidate_dir=folder)
        backend.work_dir = folder
        clock = SimpleNamespace(value=0.0)
        observation = dict(fixture.boot_observation(KIND),
                           challenge=fixture.CHALLENGE, boot_id=fixture.BOOT_ID)
        output = expected_output(observation).replace(b"\n", b"\r\n")
        test = self
        class Port:
            def __init__(self):
                self.queue = bytearray()
                self.writes = []
                self.commands = 0
                self.closed = False
                self.query_reads = 0
            def open(self):
                test.assertIs(self.dtr, False)
                test.assertIs(self.rts, False)
            def close(self):
                self.closed = True
            def write(self, value):
                self.writes.append(value)
                if value == b"\x03\x03\x02\x01":
                    self.queue.extend(fixture.RECOVERY + b"raw REPL; CTRL-B to exit\r\n>")
                elif value == b"\x04":
                    self.commands += 1
                    if self.commands == 1:
                        uid = backend.binding["device_id"].replace(":", "") if identity else "wrong-physical-id"
                        self.queue.extend(b"OK\r\nPYBLE_PHYSICAL_UID:" + uid.encode() + b"\r\n\x04\x04>")
                    else:
                        self.queue.extend(b"OK" + (output if complete else output[:20]))
                        if complete:
                            self.queue.extend(b"\x04" + stderr + b"\x04>")
                return len(value)
            def read(self, size):
                test.assertEqual(size, 1)
                clock.value += 0.001 if self.queue else 0.2
                if self.commands == 2:
                    self.query_reads += 1
                    if cancel and self.query_reads == 4:
                        backend._serial_cancelled.set()
                result = bytes(self.queue[:1])
                del self.queue[:1]
                return result
        port = Port()
        with mock.patch.dict(sys.modules, {"serial": SimpleNamespace(Serial=lambda **kwargs: port)}), \
             mock.patch.object(HARDWARE.importlib.metadata, "version", return_value="3.5"), \
             mock.patch.object(HARDWARE, "_usb_exact") as exact, \
             mock.patch.object(HARDWARE.time, "monotonic", side_effect=lambda: clock.value):
            failure = None
            try:
                raw = backend._usb_command_sync("readonly-observation-placeholder", False)
            except BaseException as error:
                failure, raw = error, None
        self.assertTrue(port.closed)
        self.assertIsNone(backend._serial)
        exact.assert_called_once_with(backend.binding["application_usb"], idle=True)
        self.assertEqual(port.writes[0], b"\x03\x03\x02\x01")
        self.assertEqual(port.writes.count(b"\x04"), 2 if identity else 1)
        retained = (folder / "usb-observation.bin").read_bytes()
        self.assertTrue(retained.startswith(fixture.RECOVERY))
        return raw, failure, retained, clock.value, port

    def test_same_raw_repl_delimiters_recovery_and_control_lines(self):
        raw, failure, retained, _elapsed, port = self.probe()
        self.assertIsNone(failure)
        self.assertEqual(raw, retained)
        self.assertEqual(port.commands, 2)
        reply = fixture.GATE.parse_workspace_response(raw)
        fixture.GATE._validate_boot_observation(
            {"challenge": fixture.CHALLENGE, "boot_id": fixture.BOOT_ID}, reply, KIND)

    def test_nonempty_stderr_preserves_failed_raw_and_never_returns_observation(self):
        raw, failure, retained, _elapsed, _port = self.probe(stderr=b"emission failed")
        self.assertIsNone(raw)
        self.assertIsInstance(failure, ValueError)
        self.assertIn("stderr", str(failure))
        self.assertIn(b"emission failed", retained)

    def test_incomplete_stdout_still_uses_absolute_12_second_deadline(self):
        raw, failure, retained, elapsed, port = self.probe(complete=False)
        self.assertIsNone(raw)
        self.assertIsInstance(failure, TimeoutError)
        self.assertGreaterEqual(elapsed, 12)
        self.assertLess(elapsed, 13)
        self.assertEqual(port.commands, 2)
        self.assertIn(b"PYBLE_WORKSPACE", retained)

    def test_wrong_uid_fails_before_observation_command(self):
        raw, failure, retained, _elapsed, port = self.probe(identity=False)
        self.assertIsNone(raw)
        self.assertIsInstance(failure, ValueError)
        self.assertIn("bound physical board", str(failure))
        self.assertEqual(port.commands, 1)
        self.assertNotIn(PREFIX, retained)

    def test_cancellation_preserves_partial_bytes_and_closes_without_retry(self):
        raw, failure, retained, _elapsed, port = self.probe(cancel=True)
        self.assertIsNone(raw)
        self.assertIsInstance(failure, ValueError)
        self.assertIn("cancelled", str(failure))
        self.assertEqual(port.commands, 2)
        self.assertNotIn(PREFIX, retained)


if __name__ == "__main__":
    unittest.main()
