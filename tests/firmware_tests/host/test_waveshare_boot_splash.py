# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""ADR-0024/0029 host contract for the exact Waveshare boot splash."""

import ast
import hashlib
import importlib.util
import inspect
import pathlib
import struct
import sys
import types
import unittest
from unittest import mock


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE_PATH = (
    REPO_ROOT
    / "firmware"
    / "board_overlays"
    / "waveshare-esp32-s3-lcd-147b"
    / "pyble_waveshare_lcd147b.py"
)

QR_PAYLOAD = b"https://pyble.dev/app"
QR_ROWS = (
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
QR_ROWS_SHA256 = "6b00240151e36ff2fdbb1d556d6f3b0dd75f8fcce13683ea21033e8149687875"
NVS_NOT_FOUND = -0x1102

DISABLED_BOOT_EVIDENCE = (
    ("guard-enter",),
    ("enabled", False),
    ("return", False),
)
SUCCESS_BOOT_EVIDENCE = (
    ("guard-enter",),
    ("enabled", True),
    ("wait-ready", 1500, True),
    ("display-start",),
    ("frame-show",),
    ("resources-released",),
    ("wait-ready", 0, True),
    ("backlight-high",),
    ("return", True),
)

_UNSET = object()


def rgb565(red, green, blue):
    return ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)


PALETTE = {
    "navy": rgb565(8, 15, 31),
    "white": rgb565(255, 255, 255),
    "black": rgb565(0, 0, 0),
    "brand": rgb565(45, 91, 255),
    "muted": rgb565(148, 163, 184),
    "ready": rgb565(34, 197, 94),
}


class SyntheticFault(Exception):
    pass


class FakeNVS:
    def __init__(self, owner):
        self.owner = owner

    def get_i32(self, key):
        self.owner.events.append(("nvs.get_i32", key))
        if self.owner.read_error is not None:
            raise self.owner.read_error
        return self.owner.read_value

    def set_i32(self, key, value):
        self.owner.events.append(("nvs.set_i32", key, value))
        if self.owner.set_error is not None:
            raise self.owner.set_error

    def commit(self):
        self.owner.events.append(("nvs.commit",))
        if self.owner.commit_error is not None:
            raise self.owner.commit_error


class FakeEsp32(types.ModuleType):
    def __init__(self, events):
        super().__init__("esp32")
        self.events = events
        self.read_value = 0
        self.open_error = None
        self.read_error = None
        self.set_error = None
        self.commit_error = None

    def NVS(self, namespace):
        self.events.append(("nvs.open", namespace))
        if self.open_error is not None:
            raise self.open_error
        return FakeNVS(self)


class FakePin:
    def __init__(self, owner, number, mode, initial):
        self.owner = owner
        self.number = number
        self.mode = mode
        self.current = None if initial is _UNSET else initial
        self.fail_values = {}

    def __call__(self, value=_UNSET):
        if value is _UNSET:
            return self.current
        self.owner.events.append(("pin.write", self.number, value))
        error = self.fail_values.get(value)
        if error is not None:
            raise error
        self.current = value

    def value(self, value=_UNSET):
        return self(value)


class FakePinFactory:
    OUT = 1

    def __init__(self, owner):
        self.owner = owner
        self.created = []
        self.fail_index = None
        self.failure = None

    def __call__(self, number, mode, *, value=_UNSET):
        index = len(self.created)
        event_value = "<unset>" if value is _UNSET else value
        self.owner.events.append(("pin.new", number, mode, event_value))
        if index == self.fail_index:
            raise self.failure
        pin = FakePin(self.owner, number, mode, value)
        self.created.append(pin)
        return pin

    def by_number(self, number):
        for pin in self.created:
            if pin.number == number:
                return pin
        return None


class FakeMachine(types.ModuleType):
    def __init__(self, events):
        super().__init__("machine")
        self.events = events
        self.Pin = FakePinFactory(self)


class FakeDisplay:
    def __init__(self, owner, arguments):
        self.owner = owner
        self.arguments = arguments
        self.method_faults = {}
        self.deinit_count = 0

    def _call(self, name, *arguments):
        self.owner.events.append(("display." + name, *arguments))
        error = self.method_faults.get(name)
        if error is not None:
            raise error

    def fill(self, colour):
        self._call("fill", colour)

    def fill_rect(self, x, y, width, height, colour):
        self._call("fill_rect", x, y, width, height, colour)

    def text(self, value, x, y, colour):
        self._call("text", value, x, y, colour)

    def show(self):
        backlight = self.arguments["backlight_pin"]
        self.owner.events.append(("display.show", backlight.current))
        error = self.method_faults.get("show")
        if error is not None:
            raise error

    def deinit(self):
        self.deinit_count += 1
        self.owner.events.append(("display.deinit", self.deinit_count))
        # Model the real ADR-0023 driver's fail-closed GPIO behavior.
        for name, value in (("backlight_pin", 0), ("cs_pin", 1)):
            try:
                self.arguments[name](value)
            except Exception:
                pass
        error = self.method_faults.get("deinit")
        if error is not None:
            raise error


class FakeDriver(types.ModuleType):
    def __init__(self, events):
        super().__init__("pyble_st7789")
        self.events = events
        self.construct_error = None
        self.next_method_faults = {}
        self.displays = []
        self.colour_inputs = []

    def rgb565(self, red, green, blue):
        self.colour_inputs.append((red, green, blue))
        return rgb565(red, green, blue)

    def ST7789(
        self,
        spi_id,
        baudrate,
        polarity,
        phase,
        sck_pin,
        mosi_pin,
        cs_pin,
        dc_pin,
        reset_pin,
        backlight_pin,
        width,
        height,
        x_offset,
        y_offset,
        bgr,
        inversion,
    ):
        arguments = {
            "spi_id": spi_id,
            "baudrate": baudrate,
            "polarity": polarity,
            "phase": phase,
            "sck_pin": sck_pin,
            "mosi_pin": mosi_pin,
            "cs_pin": cs_pin,
            "dc_pin": dc_pin,
            "reset_pin": reset_pin,
            "backlight_pin": backlight_pin,
            "width": width,
            "height": height,
            "x_offset": x_offset,
            "y_offset": y_offset,
            "bgr": bgr,
            "inversion": inversion,
        }
        self.events.append(("display.new", arguments))
        if self.construct_error is not None:
            raise self.construct_error
        display = FakeDisplay(self, arguments)
        display.method_faults.update(self.next_method_faults)
        self.displays.append(display)
        return display


class FakeGC(types.ModuleType):
    def __init__(self, events):
        super().__init__("gc")
        self.events = events
        self.error = None

    def collect(self):
        self.events.append(("gc.collect",))
        if self.error is not None:
            raise self.error


class FakePbleBle(types.ModuleType):
    def __init__(self, events):
        super().__init__("pble_ble")
        self.events = events
        self.results = [True]
        self.error = None

    def wait_ready(self, timeout_ms):
        self.events.append(("wait_ready", timeout_ms))
        if self.error is not None:
            raise self.error
        if not self.results:
            raise AssertionError("unexpected readiness call")
        return self.results.pop(0)


class RuntimeHarness:
    def __init__(self):
        self.events = []
        self.esp32 = FakeEsp32(self.events)
        self.machine = FakeMachine(self.events)
        self.driver = FakeDriver(self.events)
        self.gc = FakeGC(self.events)
        self.pble_ble = FakePbleBle(self.events)
        self.pyble = types.ModuleType("pyble")
        self.pyble.__version__ = "9.8.7-host"

    @property
    def modules(self):
        return {
            "esp32": self.esp32,
            "machine": self.machine,
            "pyble_st7789": self.driver,
            "gc": self.gc,
            "pble_ble": self.pble_ble,
            "pyble": self.pyble,
        }

    def load(self, forbid_runtime_imports=False):
        if not MODULE_PATH.is_file():
            raise AssertionError(
                "missing exact-board companion: {}".format(
                    MODULE_PATH.relative_to(REPO_ROOT)
                )
            )
        spec = importlib.util.spec_from_file_location(
            "pyble_waveshare_lcd147b_under_test", MODULE_PATH
        )
        if spec is None or spec.loader is None:
            raise AssertionError("cannot load exact-board companion")
        module = importlib.util.module_from_spec(spec)
        imported = []
        original_import = __import__
        forbidden = {
            "esp32",
            "machine",
            "pyble",
            "pyble_st7789",
            "pble_ble",
            "gc",
            "framebuf",
            "bluetooth",
            "network",
            "_thread",
            "time",
        }

        def guarded_import(name, *args, **kwargs):
            imported.append(name)
            if forbid_runtime_imports and name.split(".", 1)[0] in forbidden:
                raise AssertionError("runtime import at module load: " + name)
            return original_import(name, *args, **kwargs)

        with mock.patch.dict(sys.modules, self.modules), mock.patch(
            "builtins.__import__", side_effect=guarded_import
        ):
            spec.loader.exec_module(module)
        module._host_imports = tuple(imported)
        return module

    def invoke(self, function, *arguments):
        with mock.patch.dict(sys.modules, self.modules):
            return function(*arguments)


def _function_modules(size):
    """Return the QR Model-2 function-module map independently of firmware."""
    result = [[False] * size for _ in range(size)]

    # Timing patterns are drawn first; finder footprints supersede their ends.
    for index in range(size):
        result[6][index] = True
        result[index][6] = True

    for center_x, center_y in ((3, 3), (size - 4, 3), (3, size - 4)):
        for delta_y in range(-4, 5):
            for delta_x in range(-4, 5):
                x = center_x + delta_x
                y = center_y + delta_y
                if 0 <= x < size and 0 <= y < size:
                    result[y][x] = True

    # Version 2 has one non-overlapping alignment pattern at (18, 18).
    for y in range(16, 21):
        for x in range(16, 21):
            result[y][x] = True

    # Both format-information copies and the fixed dark module.
    for index in range(6):
        result[index][8] = True
    result[7][8] = True
    result[8][8] = True
    result[8][7] = True
    for index in range(9, 15):
        result[8][14 - index] = True
    for index in range(8):
        result[8][size - 1 - index] = True
    for index in range(8, 15):
        result[size - 15 + index][8] = True
    result[size - 8][8] = True
    return result


def _format_bits(data):
    remainder = data
    for _ in range(10):
        remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537)
    return ((data << 10) | remainder) ^ 0x5412


def decode_reviewed_qr(rows):
    """Decode this V2 byte-mode QR without a QR library or golden payload."""
    size = len(rows)
    if size != 25:
        raise AssertionError("reviewed symbol is not QR Version 2")
    modules = [
        [bool(row & (1 << (size - 1 - x))) for x in range(size)]
        for row in rows
    ]

    first_format = 0
    for index in range(6):
        first_format |= int(modules[index][8]) << index
    first_format |= int(modules[7][8]) << 6
    first_format |= int(modules[8][8]) << 7
    first_format |= int(modules[8][7]) << 8
    for index in range(9, 15):
        first_format |= int(modules[8][14 - index]) << index

    second_format = 0
    for index in range(8):
        second_format |= int(modules[8][size - 1 - index]) << index
    for index in range(8, 15):
        second_format |= int(modules[size - 15 + index][8]) << index

    # Error correction M is 00 and mask 2 is 010, hence format data 0b00010.
    expected_format = _format_bits(0b00010)
    if (first_format, second_format) != (expected_format, expected_format):
        raise AssertionError("symbol is not ECC-M/mask-2")

    function = _function_modules(size)
    data_bits = []
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        upward = ((right + 1) & 2) == 0
        for vertical in range(size):
            y = size - 1 - vertical if upward else vertical
            for offset in range(2):
                x = right - offset
                if function[y][x]:
                    continue
                bit = modules[y][x]
                if x % 3 == 0:  # QR mask pattern 2
                    bit = not bit
                data_bits.append(int(bit))
        right -= 2

    def take(count, position):
        value = 0
        for bit in data_bits[position : position + count]:
            value = (value << 1) | bit
        return value, position + count

    mode, position = take(4, 0)
    if mode != 0b0100:
        raise AssertionError("reviewed symbol is not byte mode")
    length, position = take(8, position)
    payload = bytearray()
    for _ in range(length):
        value, position = take(8, position)
        payload.append(value)
    if data_bits[position : position + 4] != [0, 0, 0, 0]:
        raise AssertionError("reviewed byte segment has no terminator")
    return bytes(payload)


class WaveshareBootSplashContractTest(unittest.TestCase):
    def test_import_is_electrically_inert_and_public_surface_is_exact(self):
        harness = RuntimeHarness()
        module = harness.load(forbid_runtime_imports=True)

        self.assertEqual(harness.events, [])
        self.assertEqual(
            tuple(module.__all__),
            (
                "boot_splash_enabled",
                "enable_boot_splash",
                "disable_boot_splash",
                "show_boot_splash",
            ),
        )
        for name in module.__all__:
            self.assertEqual(
                tuple(inspect.signature(getattr(module, name)).parameters), ()
            )
        self.assertNotIn("_maybe_show_boot_splash", module.__all__)
        self.assertNotIn("_show_boot_splash", module.__all__)
        self.assertNotIn("_boot_evidence", module.__all__)
        self.assertEqual(tuple(inspect.signature(module._boot_evidence).parameters), ())
        self.assertEqual(module._boot_evidence(), ())

        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn(
            "https://pyble.dev/app",
            source,
            "the firmware must carry reviewed QR rows, not QR payload/encoder data",
        )
        tree = ast.parse(source, filename=str(MODULE_PATH))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
        self.assertTrue(
            imports.isdisjoint({"qrcode", "urllib", "requests", "socket", "network"})
        )

    def test_enabled_is_true_only_for_exact_nvs_integer_one(self):
        for value, expected in ((0, False), (1, True), (2, False), (-1, False)):
            with self.subTest(value=value):
                harness = RuntimeHarness()
                harness.esp32.read_value = value
                module = harness.load()
                result = harness.invoke(module.boot_splash_enabled)
                self.assertIs(result, expected)
                self.assertEqual(
                    harness.events,
                    [("nvs.open", "pyble"), ("nvs.get_i32", "lcd147splash")],
                )

    def test_erased_missing_key_defaults_enabled_without_persisting_or_io(self):
        harness = RuntimeHarness()
        harness.esp32.read_error = OSError(NVS_NOT_FOUND, "synthetic missing key")
        module = harness.load()

        self.assertIs(harness.invoke(module.boot_splash_enabled), True)
        self.assertEqual(
            harness.events,
            [("nvs.open", "pyble"), ("nvs.get_i32", "lcd147splash")],
        )
        self.assertEqual(harness.machine.Pin.created, [])
        self.assertEqual(harness.driver.displays, [])

    def test_non_missing_nvs_failures_are_disabled(self):
        failures = (
            ("open", OSError("synthetic NVS open failure")),
            ("wrong-type", OSError(-0x1103, "synthetic type mismatch")),
            ("read", OSError(5, "synthetic read failure")),
        )
        for stage, error in failures:
            with self.subTest(stage=stage):
                harness = RuntimeHarness()
                if stage == "open":
                    harness.esp32.open_error = error
                else:
                    harness.esp32.read_error = error
                module = harness.load()
                self.assertIs(harness.invoke(module.boot_splash_enabled), False)

    def test_erased_missing_key_boot_renders_after_ble_readiness(self):
        harness = RuntimeHarness()
        harness.esp32.read_error = OSError(NVS_NOT_FOUND, "synthetic missing key")
        module = harness.load()
        wait_calls = []

        result = harness.invoke(
            module._maybe_show_boot_splash,
            lambda timeout: wait_calls.append(timeout) or True,
        )

        self.assertIs(result, True)
        self.assertEqual(wait_calls, [1500, 0])
        self.assertEqual(module._boot_evidence(), SUCCESS_BOOT_EVIDENCE)
        self.assertEqual(harness.machine.Pin.by_number(46).current, 1)

    def test_enable_persists_exact_one_commits_and_never_touches_hardware(self):
        harness = RuntimeHarness()
        module = harness.load()

        self.assertIsNone(harness.invoke(module.enable_boot_splash))

        self.assertEqual(
            harness.events,
            [
                ("nvs.open", "pyble"),
                ("nvs.set_i32", "lcd147splash", 1),
                ("nvs.commit",),
            ],
        )
        self.assertEqual(harness.machine.Pin.created, [])
        self.assertEqual(harness.driver.displays, [])

    def test_enable_write_and_commit_faults_propagate_without_false_success(self):
        for stage in ("set", "commit"):
            with self.subTest(stage=stage):
                harness = RuntimeHarness()
                original = SyntheticFault("synthetic " + stage + " fault")
                if stage == "set":
                    harness.esp32.set_error = original
                else:
                    harness.esp32.commit_error = original
                module = harness.load()
                with self.assertRaises(SyntheticFault) as caught:
                    harness.invoke(module.enable_boot_splash)
                self.assertIs(caught.exception, original)
                self.assertEqual(harness.machine.Pin.created, [])

    def test_disable_commits_exact_zero_then_best_effort_blanks_gpio46(self):
        harness = RuntimeHarness()
        module = harness.load()

        self.assertIsNone(harness.invoke(module.disable_boot_splash))

        self.assertEqual(
            harness.events,
            [
                ("nvs.open", "pyble"),
                ("nvs.set_i32", "lcd147splash", 0),
                ("nvs.commit",),
                ("pin.new", 46, harness.machine.Pin.OUT, 0),
            ],
        )

        harness = RuntimeHarness()
        harness.machine.Pin.fail_index = 0
        harness.machine.Pin.failure = SyntheticFault("synthetic GPIO failure")
        module = harness.load()
        self.assertIsNone(harness.invoke(module.disable_boot_splash))
        self.assertEqual(harness.events[0:3], [
            ("nvs.open", "pyble"),
            ("nvs.set_i32", "lcd147splash", 0),
            ("nvs.commit",),
        ])

    def test_disable_does_not_blank_when_persistence_did_not_commit(self):
        for stage in ("set", "commit"):
            with self.subTest(stage=stage):
                harness = RuntimeHarness()
                original = SyntheticFault("synthetic " + stage + " fault")
                if stage == "set":
                    harness.esp32.set_error = original
                else:
                    harness.esp32.commit_error = original
                module = harness.load()
                with self.assertRaises(SyntheticFault) as caught:
                    harness.invoke(module.disable_boot_splash)
                self.assertIs(caught.exception, original)
                self.assertEqual(harness.machine.Pin.created, [])

    def test_disabled_boot_guard_never_waits_or_imports_hardware(self):
        harness = RuntimeHarness()
        harness.esp32.read_value = 0
        module = harness.load()
        wait_calls = []

        result = harness.invoke(
            module._maybe_show_boot_splash,
            lambda timeout: wait_calls.append(timeout) or True,
        )

        self.assertIs(result, False)
        self.assertEqual(wait_calls, [])
        self.assertEqual(harness.machine.Pin.created, [])
        self.assertEqual(harness.driver.displays, [])
        self.assertNotIn(("wait_ready", 1500), harness.events)
        self.assertEqual(module._boot_evidence(), DISABLED_BOOT_EVIDENCE)

    def test_successful_boot_evidence_is_exact_immutable_and_privacy_safe(self):
        harness = RuntimeHarness()
        harness.esp32.read_value = 1
        module = harness.load()
        wait_calls = []

        def wait_ready(timeout):
            wait_calls.append(timeout)
            return True

        self.assertIs(
            harness.invoke(module._maybe_show_boot_splash, wait_ready), True
        )

        evidence = module._boot_evidence()
        self.assertEqual(wait_calls, [1500, 0])
        self.assertEqual(evidence, SUCCESS_BOOT_EVIDENCE)
        self.assertIsInstance(evidence, tuple)
        self.assertTrue(all(isinstance(event, tuple) for event in evidence))
        self.assertTrue(
            all(
                type(field) in (str, int, bool)
                for event in evidence
                for field in event
            )
        )
        rendered = repr(evidence).lower()
        for forbidden in (
            "ble address",
            "device id",
            "device_id",
            "label",
            "raw info",
            "firmware v",
            "pyble.dev/app",
            "mac",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_boot_evidence_resets_per_guard_invocation_and_is_vm_local(self):
        harness = RuntimeHarness()
        harness.esp32.read_value = 1
        module = harness.load()

        self.assertIs(
            harness.invoke(module._maybe_show_boot_splash, lambda _timeout: True),
            True,
        )
        self.assertEqual(module._boot_evidence(), SUCCESS_BOOT_EVIDENCE)

        harness.esp32.read_value = 0
        self.assertIs(
            harness.invoke(
                module._maybe_show_boot_splash,
                lambda _timeout: self.fail("disabled boot performed a wait"),
            ),
            False,
        )
        self.assertEqual(module._boot_evidence(), DISABLED_BOOT_EVIDENCE)

        fresh_module = RuntimeHarness().load(forbid_runtime_imports=True)
        self.assertEqual(fresh_module._boot_evidence(), ())

    def test_explicit_show_never_manufactures_or_changes_boot_evidence(self):
        harness = RuntimeHarness()
        module = harness.load()
        harness.pble_ble.results = [True]

        self.assertIs(harness.invoke(module.show_boot_splash), True)
        self.assertEqual(module._boot_evidence(), ())

        harness.esp32.read_value = 0
        self.assertIs(
            harness.invoke(module._maybe_show_boot_splash, self.fail), False
        )
        before = module._boot_evidence()
        harness.pble_ble.results = [True]
        self.assertIs(harness.invoke(module.show_boot_splash), True)
        self.assertIs(module._boot_evidence(), before)
        self.assertEqual(before, DISABLED_BOOT_EVIDENCE)

    def test_boot_evidence_records_only_completed_stages_and_redacts_faults(self):
        cases = (
            (
                "initial-not-ready",
                None,
                (False,),
                (
                    ("guard-enter",),
                    ("enabled", True),
                    ("wait-ready", 1500, False),
                    ("return", False),
                ),
            ),
            (
                "constructor-fault",
                "constructor",
                (True,),
                (
                    ("guard-enter",),
                    ("enabled", True),
                    ("wait-ready", 1500, True),
                    ("display-start",),
                    ("fault",),
                    ("return", False),
                ),
            ),
            (
                "show-fault",
                "show",
                (True,),
                (
                    ("guard-enter",),
                    ("enabled", True),
                    ("wait-ready", 1500, True),
                    ("display-start",),
                    ("fault",),
                    ("return", False),
                ),
            ),
            (
                "gc-fault",
                "gc",
                (True,),
                (
                    ("guard-enter",),
                    ("enabled", True),
                    ("wait-ready", 1500, True),
                    ("display-start",),
                    ("frame-show",),
                    ("fault",),
                    ("return", False),
                ),
            ),
            (
                "final-not-ready",
                None,
                (True, False),
                (
                    ("guard-enter",),
                    ("enabled", True),
                    ("wait-ready", 1500, True),
                    ("display-start",),
                    ("frame-show",),
                    ("resources-released",),
                    ("wait-ready", 0, False),
                    ("return", False),
                ),
            ),
        )

        for name, fault_stage, readiness, expected in cases:
            with self.subTest(name=name):
                harness = RuntimeHarness()
                harness.esp32.read_value = 1
                secret = SyntheticFault(
                    "private-device-id-AA55 raw-info owner-label 01:23:45:67:89:AB"
                )
                if fault_stage == "constructor":
                    harness.driver.construct_error = secret
                elif fault_stage == "show":
                    harness.driver.next_method_faults["show"] = secret
                elif fault_stage == "gc":
                    harness.gc.error = secret
                module = harness.load()
                results = list(readiness)

                self.assertIs(
                    harness.invoke(
                        module._maybe_show_boot_splash,
                        lambda _timeout: results.pop(0),
                    ),
                    False,
                )
                evidence = module._boot_evidence()
                self.assertEqual(evidence, expected)
                self.assertNotIn("aa55", repr(evidence).lower())
                self.assertNotIn("01:23:45", repr(evidence))

    def test_boot_guard_waits_exactly_1500_only_when_enabled_and_fails_open(self):
        harness = RuntimeHarness()
        harness.esp32.read_value = 1
        module = harness.load()
        wait_calls = []

        self.assertIs(
            harness.invoke(
                module._maybe_show_boot_splash,
                lambda timeout: wait_calls.append(timeout) or False,
            ),
            False,
        )
        self.assertEqual(wait_calls, [1500])
        self.assertEqual(harness.machine.Pin.created, [])

        for failure_site in ("initial_wait", "render"):
            with self.subTest(failure_site=failure_site):
                harness = RuntimeHarness()
                harness.esp32.read_value = 1
                module = harness.load()
                original = SyntheticFault("synthetic boot-wrapper fault")

                if failure_site == "initial_wait":
                    def wait_ready(_timeout):
                        raise original
                else:
                    harness.driver.construct_error = original

                    def wait_ready(timeout):
                        return timeout == 1500

                self.assertIs(
                    harness.invoke(module._maybe_show_boot_splash, wait_ready),
                    False,
                )

    def test_qr_rows_digest_bit_order_format_and_independent_payload_decode(self):
        module = RuntimeHarness().load()
        rows = tuple(module._QR_ROWS)

        self.assertEqual(rows, QR_ROWS)
        self.assertEqual(len(rows), 25)
        self.assertTrue(all(type(row) is int and 0 <= row < (1 << 25) for row in rows))
        packed = b"".join(struct.pack(">I", row) for row in rows)
        self.assertEqual(hashlib.sha256(packed).hexdigest(), QR_ROWS_SHA256)
        self.assertEqual(decode_reviewed_qr(rows), QR_PAYLOAD)

        # Both top finder borders occupy X=0..6 and X=18..24. Checking those
        # asymmetric bit positions explicitly makes a reversed row convention
        # fail before the independent data traversal runs.
        top = [bool(rows[0] & (1 << (24 - x))) for x in range(25)]
        self.assertEqual(top[0:7], [True] * 7)
        self.assertIs(top[7], False)
        self.assertIs(top[17], False)
        self.assertEqual(top[18:25], [True] * 7)

    def test_exact_wiring_driver_configuration_palette_layout_and_privacy(self):
        harness = RuntimeHarness()
        module = harness.load()
        harness.pble_ble.results = [True]

        self.assertIs(harness.invoke(module.show_boot_splash), True)

        pins = harness.machine.Pin.created
        self.assertEqual([pin.number for pin in pins], [46, 42, 40, 45, 41, 39])
        self.assertEqual(
            harness.events[0:2],
            [
                ("pin.new", 46, harness.machine.Pin.OUT, 0),
                ("pin.new", 42, harness.machine.Pin.OUT, 1),
            ],
        )
        arguments = harness.driver.displays[0].arguments
        self.assertEqual(
            {
                key: arguments[key]
                for key in (
                    "spi_id", "baudrate", "polarity", "phase", "width",
                    "height", "x_offset", "y_offset", "bgr", "inversion",
                )
            },
            {
                "spi_id": 1,
                "baudrate": 40_000_000,
                "polarity": 0,
                "phase": 0,
                "width": 172,
                "height": 320,
                "x_offset": 34,
                "y_offset": 0,
                "bgr": True,
                "inversion": True,
            },
        )
        self.assertEqual(arguments["sck_pin"].number, 40)
        self.assertEqual(arguments["mosi_pin"].number, 45)
        self.assertEqual(arguments["cs_pin"].number, 42)
        self.assertEqual(arguments["dc_pin"].number, 41)
        self.assertEqual(arguments["reset_pin"].number, 39)
        self.assertEqual(arguments["backlight_pin"].number, 46)
        draw_events = [event for event in harness.events if event[0].startswith("display.")]
        used_colours = {
            event[-1]
            for event in draw_events
            if event[0] in ("display.fill", "display.fill_rect", "display.text")
        }
        self.assertEqual(used_colours, set(PALETTE.values()))
        self.assertIn(("display.fill", PALETTE["navy"]), draw_events)
        for expected in (
            ("display.fill_rect", 10, 10, 30, 30, PALETTE["brand"]),
            ("display.text", ">_", 16, 21, PALETTE["white"]),
            ("display.text", "PyBLE", 48, 14, PALETTE["white"]),
            ("display.text", "PYTHON OVER BLE", 48, 27, PALETTE["muted"]),
            ("display.fill_rect", 0, 45, 172, 2, PALETTE["brand"]),
            ("display.fill_rect", 3, 52, 165, 165, PALETTE["white"]),
            ("display.text", "SCAN TO INSTALL", 26, 225, PALETTE["white"]),
            ("display.text", "pyble.dev/app", 34, 243, PALETTE["muted"]),
            ("display.fill_rect", 36, 270, 6, 6, PALETTE["ready"]),
            ("display.text", "BLE READY", 50, 269, PALETTE["white"]),
            ("display.text", "Firmware v9.8.7-host", 26, 296, PALETTE["muted"]),
        ):
            self.assertIn(expected, draw_events)

        text_values = [event[1] for event in draw_events if event[0] == "display.text"]
        self.assertEqual(
            text_values,
            [
                ">_",
                "PyBLE",
                "PYTHON OVER BLE",
                "SCAN TO INSTALL",
                "pyble.dev/app",
                "BLE READY",
                "Firmware v9.8.7-host",
            ],
        )
        rendered = " ".join(text_values).lower()
        for private_field in (
            "mac", "device id", "device_id", "ble address", "label",
            "owner", "raw info", "telemetry",
        ):
            self.assertNotIn(private_field, rendered)

    def test_qr_quiet_zone_and_every_dark_module_are_drawn_exactly(self):
        harness = RuntimeHarness()
        module = harness.load()
        harness.pble_ble.results = [True]
        self.assertIs(harness.invoke(module.show_boot_splash), True)

        rectangles = [event for event in harness.events if event[0] == "display.fill_rect"]
        self.assertIn(
            ("display.fill_rect", 3, 52, 165, 165, PALETTE["white"]),
            rectangles,
        )
        actual_modules = {
            event[1:]
            for event in rectangles
            if event[3:5] == (5, 5) and event[5] == PALETTE["black"]
        }
        expected_modules = {
            (3 + (column + 4) * 5, 52 + (row + 4) * 5, 5, 5, PALETTE["black"])
            for row, mask in enumerate(QR_ROWS)
            for column in range(25)
            if mask & (1 << (24 - column))
        }
        self.assertEqual(len(expected_modules), 334)
        self.assertEqual(actual_modules, expected_modules)
        self.assertTrue(all(23 <= item[0] <= 143 for item in actual_modules))
        self.assertTrue(all(72 <= item[1] <= 192 for item in actual_modules))

    def test_success_shows_once_unlit_then_releases_collects_rechecks_and_lights(self):
        harness = RuntimeHarness()
        module = harness.load()
        harness.pble_ble.results = [True]

        self.assertIs(harness.invoke(module.show_boot_splash), True)

        show_events = [event for event in harness.events if event[0] == "display.show"]
        self.assertEqual(show_events, [("display.show", 0)])
        display = harness.driver.displays[0]
        self.assertEqual(display.deinit_count, 1)
        significant = [
            event for event in harness.events
            if event[0] in ("display.show", "display.deinit", "gc.collect", "wait_ready")
            or (event[0] == "pin.write" and event[1] == 46 and event[2] == 1)
        ]
        self.assertEqual(
            significant,
            [
                ("display.show", 0),
                ("display.deinit", 1),
                ("gc.collect",),
                ("wait_ready", 0),
                ("pin.write", 46, 1),
            ],
        )
        self.assertEqual(harness.events[-1], ("pin.write", 46, 1))
        self.assertEqual(harness.machine.Pin.by_number(46).current, 1)
        self.assertEqual(harness.machine.Pin.by_number(42).current, 1)

    def test_final_readiness_loss_returns_false_and_never_lights_panel(self):
        harness = RuntimeHarness()
        module = harness.load()
        harness.pble_ble.results = [False]

        self.assertIs(harness.invoke(module.show_boot_splash), False)

        self.assertEqual(
            [event for event in harness.events if event[0] == "wait_ready"],
            [("wait_ready", 0)],
        )
        self.assertNotIn(("pin.write", 46, 1), harness.events)
        self.assertEqual(harness.machine.Pin.by_number(46).current, 0)
        self.assertEqual(harness.machine.Pin.by_number(42).current, 1)
        self.assertEqual(harness.driver.displays[0].deinit_count, 1)

    def test_enabled_boot_guard_observes_readiness_before_and_after_render(self):
        harness = RuntimeHarness()
        harness.esp32.read_value = 1
        module = harness.load()
        readiness = [True, True]
        wait_calls = []

        def wait_ready(timeout):
            wait_calls.append(timeout)
            return readiness.pop(0)

        self.assertIs(
            harness.invoke(module._maybe_show_boot_splash, wait_ready), True
        )
        self.assertEqual(wait_calls, [1500, 0])

        harness = RuntimeHarness()
        harness.esp32.read_value = 1
        module = harness.load()
        readiness = [True, False]
        self.assertIs(
            harness.invoke(
                module._maybe_show_boot_splash,
                lambda timeout: readiness.pop(0),
            ),
            False,
        )
        self.assertNotIn(("pin.write", 46, 1), harness.events)

    def test_every_partial_pin_failure_preserves_original_and_fails_closed(self):
        for failure_index in range(6):
            with self.subTest(failure_index=failure_index):
                harness = RuntimeHarness()
                original = SyntheticFault("pin {} fault".format(failure_index))
                harness.machine.Pin.fail_index = failure_index
                harness.machine.Pin.failure = original
                module = harness.load()

                with self.assertRaises(SyntheticFault) as caught:
                    harness.invoke(module._show_boot_splash, lambda _timeout: True)
                self.assertIs(caught.exception, original)
                backlight = harness.machine.Pin.by_number(46)
                cs = harness.machine.Pin.by_number(42)
                if backlight is not None:
                    self.assertEqual(backlight.current, 0)
                if cs is not None:
                    self.assertEqual(cs.current, 1)
                self.assertEqual(harness.driver.displays, [])

    def test_constructor_draw_transfer_deinit_gc_wait_and_light_faults_cleanup(self):
        stages = (
            "constructor",
            "fill",
            "fill_rect",
            "text",
            "show",
            "deinit",
            "gc",
            "wait",
            "light",
        )
        for stage in stages:
            with self.subTest(stage=stage):
                harness = RuntimeHarness()
                original = SyntheticFault("synthetic {} fault".format(stage))
                if stage == "constructor":
                    harness.driver.construct_error = original
                elif stage in ("fill", "fill_rect", "text", "show", "deinit"):
                    harness.driver.next_method_faults[stage] = original
                elif stage == "gc":
                    harness.gc.error = original
                elif stage == "wait":
                    harness.pble_ble.error = original
                module = harness.load()

                if stage == "light":
                    # Install the final-write fault after construction, without
                    # changing the exact production transaction.
                    def wait_ready(timeout):
                        pin = harness.machine.Pin.by_number(46)
                        pin.fail_values[1] = original
                        return True
                else:
                    wait_ready = harness.pble_ble.wait_ready

                with self.assertRaises(SyntheticFault) as caught:
                    harness.invoke(module._show_boot_splash, wait_ready)
                self.assertIs(caught.exception, original)

                backlight = harness.machine.Pin.by_number(46)
                cs = harness.machine.Pin.by_number(42)
                self.assertIsNotNone(backlight)
                self.assertIsNotNone(cs)
                self.assertEqual(backlight.current, 0)
                self.assertEqual(cs.current, 1)
                if harness.driver.displays:
                    self.assertGreaterEqual(harness.driver.displays[0].deinit_count, 1)

    def test_cleanup_faults_do_not_replace_the_original_explicit_call_error(self):
        harness = RuntimeHarness()
        primary = SyntheticFault("primary draw fault")
        cleanup = SyntheticFault("secondary cleanup fault")
        harness.driver.next_method_faults["fill"] = primary
        harness.driver.next_method_faults["deinit"] = cleanup
        module = harness.load()

        with self.assertRaises(SyntheticFault) as caught:
            harness.invoke(module._show_boot_splash, lambda _timeout: True)

        self.assertIs(caught.exception, primary)
        self.assertEqual(harness.machine.Pin.by_number(46).current, 0)
        self.assertEqual(harness.machine.Pin.by_number(42).current, 1)


if __name__ == "__main__":
    unittest.main()
