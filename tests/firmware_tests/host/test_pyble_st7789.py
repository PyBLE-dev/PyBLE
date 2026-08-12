# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""ADR-0023 host contract for the clean-room ST7789 user runtime."""

import importlib.util
import pathlib
import sys
import types
import unittest
from unittest import mock


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "firmware" / "python_modules" / "pyble_st7789.py"


class FakePin:
    def __init__(self, name):
        self.name = name
        self.value = None
        self.history = []

    def __call__(self, value=None):
        if value is None:
            return self.value
        self.value = value
        self.history.append(value)


class FakeSPI:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.writes = []
        self.write_attempts = []
        self.fail_on_write_index = None
        self.deinit_count = 0

    def write(self, payload):
        value = bytes(payload)
        write_index = len(self.write_attempts)
        self.write_attempts.append(value)
        if self.fail_on_write_index == write_index:
            raise OSError("synthetic SPI failure")
        self.writes.append(value)

    def reset_writes(self):
        self.writes.clear()
        self.write_attempts.clear()
        self.fail_on_write_index = None

    def deinit(self):
        self.deinit_count += 1


class FakeMachine(types.ModuleType):
    def __init__(self):
        super().__init__("machine")
        self.Pin = FakePin
        self.created = []
        self.next_spi_fail_on_write_index = None

    def SPI(self, *args, **kwargs):
        spi = FakeSPI(*args, **kwargs)
        spi.fail_on_write_index = self.next_spi_fail_on_write_index
        self.created.append(spi)
        return spi


class FakeFrameBuffer:
    def __init__(self, buffer, width, height, pixel_format):
        self.buffer = buffer
        self.width = width
        self.height = height
        self.pixel_format = pixel_format
        self.calls = []

    def fill(self, colour):
        self.calls.append(("fill", colour))
        for y in range(self.height):
            for x in range(self.width):
                self._set_pixel(x, y, colour)

    def _set_pixel(self, x, y, colour):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        index = (y * self.width + x) * 2
        self.buffer[index] = colour & 0xFF
        self.buffer[index + 1] = (colour >> 8) & 0xFF

    def pixel(self, x, y, colour):
        self.calls.append(("pixel", x, y, colour))
        self._set_pixel(x, y, colour)

    def line(self, *args):
        self.calls.append(("line", *args))

    def rect(self, *args):
        self.calls.append(("rect", *args))

    def fill_rect(self, x, y, width, height, colour):
        self.calls.append(("fill_rect", x, y, width, height, colour))
        for draw_y in range(y, y + height):
            for draw_x in range(x, x + width):
                self._set_pixel(draw_x, draw_y, colour)

    def text(self, *args):
        self.calls.append(("text", *args))


class RuntimeHarness:
    def __init__(self):
        self.machine = FakeMachine()
        self.sleeps = []
        self.framebuffers = []
        self.framebuffer_error = None
        self.framebuf = types.ModuleType("framebuf")
        self.framebuf.RGB565 = 1

        def create_framebuffer(buffer, width, height, pixel_format):
            if self.framebuffer_error is not None:
                raise self.framebuffer_error
            framebuffer = FakeFrameBuffer(buffer, width, height, pixel_format)
            self.framebuffers.append(framebuffer)
            return framebuffer

        self.framebuf.FrameBuffer = create_framebuffer
        self.time = types.ModuleType("time")
        self.time.sleep_ms = self.sleeps.append
        self.micropython = types.ModuleType("micropython")
        self.micropython.const = lambda value: value
        self.micropython.viper = lambda function: function

    def load(self):
        if not MODULE_PATH.is_file():
            raise AssertionError(
                "missing canonical runtime: {}".format(
                    MODULE_PATH.relative_to(REPO_ROOT)
                )
            )
        spec = importlib.util.spec_from_file_location(
            "pyble_st7789_under_test", MODULE_PATH
        )
        if spec is None or spec.loader is None:
            raise AssertionError("cannot load pyble_st7789")
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(
            sys.modules,
            {
                "machine": self.machine,
                "framebuf": self.framebuf,
                "time": self.time,
                "micropython": self.micropython,
            },
        ):
            spec.loader.exec_module(module)
        return module


def make_pins():
    return {
        name: FakePin(name)
        for name in ("sck", "mosi", "cs", "dc", "reset", "backlight")
    }


def construct_display(module, harness, pins=None, **overrides):
    if pins is None:
        pins = make_pins()
    values = {
        "spi_id": 2,
        "baudrate": 40_000_000,
        "polarity": 0,
        "phase": 0,
        "sck_pin": pins["sck"],
        "mosi_pin": pins["mosi"],
        "cs_pin": pins["cs"],
        "dc_pin": pins["dc"],
        "reset_pin": pins["reset"],
        "backlight_pin": pins["backlight"],
        "width": 2,
        "height": 2,
        "x_offset": 34,
        "y_offset": 0,
        "bgr": True,
        "inversion": True,
    }
    values.update(overrides)
    argument_order = (
        "spi_id",
        "baudrate",
        "polarity",
        "phase",
        "sck_pin",
        "mosi_pin",
        "cs_pin",
        "dc_pin",
        "reset_pin",
        "backlight_pin",
        "width",
        "height",
        "x_offset",
        "y_offset",
        "bgr",
        "inversion",
    )
    with mock.patch.dict(sys.modules, {"machine": harness.machine}):
        display = module.ST7789(*(values[name] for name in argument_order))
    return display, pins


def make_display(module, harness, width=2, height=2, x_offset=34, y_offset=0):
    pins = {
        name: FakePin(name)
        for name in ("sck", "mosi", "cs", "dc", "reset", "backlight")
    }
    display, _ = construct_display(
        module,
        harness,
        pins,
        width=width,
        height=height,
        x_offset=x_offset,
        y_offset=y_offset,
    )
    return display, pins, harness.machine.created[-1]


class ST7789RuntimeContractTest(unittest.TestCase):
    def test_import_is_inert_and_exports_only_the_frozen_surface(self):
        harness = RuntimeHarness()
        module = harness.load()
        self.assertEqual(harness.machine.created, [])
        self.assertEqual(harness.sleeps, [])
        self.assertEqual(tuple(module.__all__), ("ST7789", "rgb565"))

    def test_rgb565_validates_channels_and_packs_exactly(self):
        module = RuntimeHarness().load()
        self.assertEqual(module.rgb565(255, 0, 0), 0xF800)
        self.assertEqual(module.rgb565(0, 255, 0), 0x07E0)
        self.assertEqual(module.rgb565(0, 0, 255), 0x001F)
        self.assertEqual(module.rgb565(8, 18, 40), 0x0885)
        for values in ((-1, 0, 0), (0, 256, 0), (0, 0, 1.5), (True, 0, 0)):
            with self.subTest(values=values), self.assertRaises(
                (TypeError, ValueError)
            ):
                module.rgb565(*values)

    def test_constructor_rejects_every_invalid_scalar_before_hardware_output(self):
        invalid_cases = (
            ("spi_id negative", {"spi_id": -1}),
            ("spi_id Boolean", {"spi_id": True}),
            ("baudrate zero", {"baudrate": 0}),
            ("polarity high", {"polarity": 2}),
            ("phase negative", {"phase": -1}),
            ("width zero", {"width": 0}),
            ("width non-integer", {"width": 1.5}),
            ("height zero", {"height": 0}),
            ("x offset negative", {"x_offset": -1}),
            ("y offset negative", {"y_offset": -1}),
            ("column window overflow", {"width": 2, "x_offset": 0xFFFF}),
            ("row window overflow", {"height": 2, "y_offset": 0xFFFF}),
            ("bgr non-Boolean", {"bgr": 1}),
            ("inversion non-Boolean", {"inversion": 0}),
        )
        for label, overrides in invalid_cases:
            with self.subTest(label=label):
                harness = RuntimeHarness()
                module = harness.load()
                pins = make_pins()

                with self.assertRaises((TypeError, ValueError)):
                    construct_display(module, harness, pins, **overrides)

                self.assertEqual(harness.machine.created, [])
                self.assertEqual(harness.framebuffers, [])
                self.assertEqual(harness.sleeps, [])
                self.assertTrue(
                    all(pin.history == [] for pin in pins.values()),
                    "scalar validation must precede every GPIO write",
                )

    def test_constructor_requires_real_machine_pin_instances_before_output(self):
        for role in ("sck", "mosi", "cs", "dc", "reset", "backlight"):
            with self.subTest(role=role):
                harness = RuntimeHarness()
                module = harness.load()
                pins = make_pins()
                pins[role] = lambda value=None: value

                with self.assertRaisesRegex(TypeError, "must be a Pin object"):
                    construct_display(module, harness, pins)

                self.assertEqual(harness.machine.created, [])
                self.assertEqual(harness.framebuffers, [])
                self.assertEqual(harness.sleeps, [])
                self.assertTrue(
                    all(
                        pin.history == []
                        for pin in pins.values()
                        if isinstance(pin, FakePin)
                    ),
                    "pin validation must precede every GPIO write",
                )

    def test_constructor_uses_explicit_bus_and_exact_ordered_initialization(self):
        harness = RuntimeHarness()
        module = harness.load()
        _, pins, spi = make_display(module, harness)

        self.assertEqual(spi.args, (2,))
        self.assertEqual(spi.kwargs["baudrate"], 40_000_000)
        self.assertEqual(spi.kwargs["polarity"], 0)
        self.assertEqual(spi.kwargs["phase"], 0)
        self.assertIs(spi.kwargs["sck"], pins["sck"])
        self.assertIs(spi.kwargs["mosi"], pins["mosi"])
        self.assertEqual(pins["cs"].history[0], 1)
        self.assertEqual(pins["backlight"].history, [0])
        self.assertEqual(pins["backlight"].value, 0)
        self.assertIn(0, pins["reset"].history)
        self.assertEqual(pins["reset"].history[-1], 1)
        self.assertEqual(
            spi.writes,
            [
                b"\x01",
                b"\x11",
                b"\x3a",
                b"\x55",
                b"\x36",
                b"\x08",
                b"\x21",
                b"\x13",
                b"\x29",
            ],
        )
        self.assertEqual(harness.sleeps, [10, 10, 120, 150, 120, 100])
        self.assertEqual(
            pins["cs"].history,
            [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
        )
        self.assertNotIn(bytes((0x2C,)), spi.writes, "construction must not show")

    def test_constructor_applies_supplied_rgb_order_and_inversion_exactly(self):
        harness = RuntimeHarness()
        module = harness.load()
        display, _ = construct_display(
            module, harness, bgr=False, inversion=False
        )
        spi = harness.machine.created[-1]

        self.assertEqual(spi.writes[4:7], [b"\x36", b"\x00", b"\x20"])
        display.deinit()

    def test_partial_constructor_failures_release_owned_resources_fail_closed(self):
        harness = RuntimeHarness()
        module = harness.load()
        pins = make_pins()
        harness.framebuffer_error = MemoryError("synthetic framebuffer failure")

        with self.assertRaisesRegex(MemoryError, "synthetic framebuffer failure"):
            construct_display(module, harness, pins)

        spi = harness.machine.created[-1]
        self.assertEqual(spi.deinit_count, 1)
        self.assertEqual(pins["backlight"].value, 0)
        self.assertEqual(pins["cs"].value, 1)
        self.assertEqual(harness.sleeps, [])

        harness = RuntimeHarness()
        module = harness.load()
        pins = make_pins()
        harness.machine.next_spi_fail_on_write_index = 0
        with self.assertRaisesRegex(OSError, "synthetic SPI failure"):
            construct_display(module, harness, pins)

        spi = harness.machine.created[-1]
        self.assertEqual(spi.deinit_count, 1)
        self.assertEqual(pins["backlight"].value, 0)
        self.assertEqual(pins["cs"].value, 1)

    def test_draws_only_to_framebuffer_until_explicit_show(self):
        harness = RuntimeHarness()
        module = harness.load()
        display, _, spi = make_display(module, harness)
        writes_after_init = len(spi.writes)

        display.fill(0x1234)
        display.pixel(0, 0, 1)
        display.line(0, 0, 1, 1, 2)
        display.rect(0, 0, 2, 2, 3)
        display.fill_rect(0, 0, 1, 1, 4)
        display.text("P", 0, 0, 5)

        self.assertEqual(len(spi.writes), writes_after_init)
        self.assertEqual(
            [call[0] for call in display._framebuf.calls],
            ["fill", "pixel", "line", "rect", "fill_rect", "text"],
        )

    def test_framebuffer_delegation_clips_out_of_bounds_drawing(self):
        harness = RuntimeHarness()
        module = harness.load()
        display, _, spi = make_display(module, harness, width=2, height=2)
        writes_after_init = len(spi.writes)
        display.fill(0)

        display.pixel(-1, 0, 0xFFFF)
        display.pixel(2, 0, 0xFFFF)
        display.pixel(0, -1, 0xFFFF)
        display.pixel(0, 2, 0xFFFF)
        self.assertEqual(bytes(display._buffer), b"\x00" * 8)

        display.fill_rect(-1, -1, 2, 2, 0x1234)
        self.assertEqual(bytes(display._buffer), b"\x34\x12" + b"\x00" * 6)
        self.assertEqual(len(display._buffer), 2 * 2 * 2)
        self.assertEqual(len(spi.writes), writes_after_init)

    def test_show_sets_inclusive_window_chunks_and_restores_byte_order(self):
        harness = RuntimeHarness()
        module = harness.load()
        display, pins, spi = make_display(
            module, harness, width=50, height=50, x_offset=34, y_offset=7
        )
        display.fill(0x1234)
        before = bytes(display._buffer)
        spi.reset_writes()

        display.show()

        self.assertEqual(pins["cs"].value, 1)
        self.assertEqual(bytes(display._buffer), before)
        self.assertEqual(spi.writes[0:6], [
            b"\x2a",
            b"\x00\x22\x00\x53",
            b"\x2b",
            b"\x00\x07\x00\x38",
            b"\x2c",
            b"\x12\x34" * 2046,
        ])
        payloads = spi.writes[5:]
        self.assertEqual(sum(map(len, payloads)), 50 * 50 * 2)
        self.assertTrue(all(0 < len(value) <= 4092 for value in payloads))
        self.assertTrue(all(len(value) % 2 == 0 for value in payloads))

    def test_ram_write_failure_fails_outputs_closed_and_remains_retryable(self):
        harness = RuntimeHarness()
        module = harness.load()
        display, pins, spi = make_display(module, harness, width=4, height=2)
        display.fill(0xABCD)
        display.backlight(True)
        before = bytes(display._buffer)
        spi.reset_writes()
        spi.fail_on_write_index = 4

        with self.assertRaisesRegex(OSError, "synthetic SPI failure"):
            display.show()

        self.assertEqual(spi.write_attempts[4], b"\x2c")
        self.assertEqual(bytes(display._buffer), before)
        self.assertEqual(pins["cs"].value, 1)
        self.assertEqual(pins["backlight"].value, 0)
        self.assertEqual(spi.deinit_count, 0)
        self.assertFalse(display._closed)

        spi.reset_writes()
        display.show()
        self.assertEqual(bytes(display._buffer), before)
        self.assertEqual(spi.writes[4], b"\x2c")

    def test_later_chunk_failure_restores_entire_buffer_and_remains_retryable(self):
        harness = RuntimeHarness()
        module = harness.load()
        display, pins, spi = make_display(module, harness, width=50, height=50)
        display.fill(0xABCD)
        display.backlight(True)
        before = bytes(display._buffer)
        spi.reset_writes()
        spi.fail_on_write_index = 6

        with self.assertRaisesRegex(OSError, "synthetic SPI failure"):
            display.show()

        self.assertEqual(len(spi.write_attempts[5]), 4092)
        self.assertEqual(len(spi.write_attempts[6]), len(before) - 4092)
        self.assertEqual(bytes(display._buffer), before)
        self.assertEqual(pins["cs"].value, 1)
        self.assertEqual(pins["backlight"].value, 0)
        self.assertEqual(spi.deinit_count, 0)
        self.assertFalse(display._closed)

        spi.reset_writes()
        display.show()
        self.assertEqual(bytes(display._buffer), before)
        self.assertEqual(sum(map(len, spi.writes[5:])), len(before))

    def test_backlight_and_deinit_fail_closed(self):
        harness = RuntimeHarness()
        module = harness.load()
        display, pins, spi = make_display(module, harness)
        display.backlight(True)
        display.backlight(False)
        self.assertEqual(pins["backlight"].history[-2:], [1, 0])
        with self.assertRaises(TypeError):
            display.backlight(1)

        display.deinit()
        display.deinit()
        self.assertEqual(pins["backlight"].value, 0)
        self.assertEqual(pins["cs"].value, 1)
        self.assertEqual(spi.deinit_count, 1)
        for action in (
            lambda: display.fill(0),
            display.show,
            lambda: display.backlight(True),
        ):
            with self.assertRaises(RuntimeError):
                action()


if __name__ == "__main__":
    unittest.main(verbosity=2)
