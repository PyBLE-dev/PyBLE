# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Small explicit ST7789 framebuffer driver for PyBLE user programs."""

import micropython
import framebuf
from time import sleep_ms


__all__ = ("ST7789", "rgb565")


# ``ptr8`` is a Viper cast on MicroPython.  Keeping this ordinary fallback makes
# the same clean-room source executable by the CPython host contract tests.
def ptr8(buffer):
    return buffer


@micropython.viper
def _swap_rgb565_bytes(buffer, start: int, end: int):
    data = ptr8(buffer)
    index = int(start)
    limit = int(end)
    while index < limit:
        value = data[index]
        data[index] = data[index + 1]
        data[index + 1] = value
        index += 2


def _require_int(name, value, minimum, maximum=None):
    if type(value) is not int:
        raise TypeError("{} must be an integer".format(name))
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError("{} is out of range".format(name))


def rgb565(red, green, blue):
    """Pack validated 8-bit RGB channels into one RGB565 word."""
    for name, channel in (("red", red), ("green", green), ("blue", blue)):
        _require_int(name, channel, 0, 255)
    return ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)


class ST7789:
    """Explicit write-only ST7789 display backed by one RGB565 framebuffer."""

    def __init__(
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
        _require_int("spi_id", spi_id, 0)
        _require_int("baudrate", baudrate, 1)
        _require_int("polarity", polarity, 0, 1)
        _require_int("phase", phase, 0, 1)
        _require_int("width", width, 1, 0x10000)
        _require_int("height", height, 1, 0x10000)
        _require_int("x_offset", x_offset, 0, 0xFFFF)
        _require_int("y_offset", y_offset, 0, 0xFFFF)
        if x_offset + width - 1 > 0xFFFF:
            raise ValueError("column window is out of range")
        if y_offset + height - 1 > 0xFFFF:
            raise ValueError("row window is out of range")
        if type(bgr) is not bool or type(inversion) is not bool:
            raise TypeError("bgr and inversion must be Boolean")

        from machine import Pin, SPI

        for name, pin in (
            ("sck_pin", sck_pin),
            ("mosi_pin", mosi_pin),
            ("cs_pin", cs_pin),
            ("dc_pin", dc_pin),
            ("reset_pin", reset_pin),
            ("backlight_pin", backlight_pin),
        ):
            if not isinstance(pin, Pin):
                raise TypeError("{} must be a Pin object".format(name))

        self._width = width
        self._height = height
        self._x_offset = x_offset
        self._y_offset = y_offset
        self._cs = cs_pin
        self._dc = dc_pin
        self._reset = reset_pin
        self._backlight = backlight_pin
        self._spi = None
        self._buffer = None
        self._framebuf = None
        self._closed = True

        try:
            # Establish inactive output levels before allocating or touching the
            # controller.  Pins are explicit Pin.OUT objects owned by the caller.
            self._cs(1)
            self._backlight(0)

            self._spi = SPI(
                spi_id,
                baudrate=baudrate,
                polarity=polarity,
                phase=phase,
                sck=sck_pin,
                mosi=mosi_pin,
            )
            self._buffer = bytearray(width * height * 2)
            self._framebuf = framebuf.FrameBuffer(
                self._buffer, width, height, framebuf.RGB565
            )

            self._reset(1)
            sleep_ms(10)
            self._reset(0)
            sleep_ms(10)
            self._reset(1)
            sleep_ms(120)

            self._command(0x01)
            sleep_ms(150)
            self._command(0x11)
            sleep_ms(120)
            self._command(0x3A, b"\x55")
            self._command(0x36, b"\x08" if bgr else b"\x00")
            self._command(0x21 if inversion else 0x20)
            self._command(0x13)
            self._command(0x29)
            sleep_ms(100)
            self._closed = False
        except BaseException:
            self._cleanup()
            raise

    def _cleanup(self):
        try:
            self._backlight(0)
        except BaseException:
            pass
        try:
            self._cs(1)
        except BaseException:
            pass
        spi = self._spi
        if spi is not None:
            try:
                spi.deinit()
            except BaseException:
                pass
        self._spi = None
        self._framebuf = None
        self._buffer = None
        self._closed = True

    def _fail_transfer_outputs_closed(self):
        try:
            self._backlight(0)
        except BaseException:
            pass
        try:
            self._cs(1)
        except BaseException:
            pass

    def _require_open(self):
        if self._closed:
            raise RuntimeError("display is deinitialized")

    def _command(self, command, data=None):
        error = None
        try:
            self._cs(0)
            self._dc(0)
            self._spi.write(bytes((command,)))
            if data is not None:
                self._dc(1)
                self._spi.write(data)
        except BaseException as caught:
            error = caught
            raise
        finally:
            try:
                self._cs(1)
            except BaseException:
                if error is None:
                    raise

    def fill(self, colour):
        self._require_open()
        self._framebuf.fill(colour)

    def pixel(self, x, y, colour):
        self._require_open()
        self._framebuf.pixel(x, y, colour)

    def line(self, x0, y0, x1, y1, colour):
        self._require_open()
        self._framebuf.line(x0, y0, x1, y1, colour)

    def rect(self, x, y, width, height, colour):
        self._require_open()
        self._framebuf.rect(x, y, width, height, colour)

    def fill_rect(self, x, y, width, height, colour):
        self._require_open()
        self._framebuf.fill_rect(x, y, width, height, colour)

    def text(self, value, x, y, colour):
        self._require_open()
        self._framebuf.text(value, x, y, colour)

    @staticmethod
    def _window(start, extent):
        end = start + extent - 1
        return bytes((start >> 8, start & 0xFF, end >> 8, end & 0xFF))

    def show(self):
        self._require_open()
        try:
            self._command(0x2A, self._window(self._x_offset, self._width))
            self._command(0x2B, self._window(self._y_offset, self._height))

            error = None
            try:
                self._cs(0)
                self._dc(0)
                self._spi.write(b"\x2c")
                self._dc(1)
                buffer = self._buffer
                view = memoryview(buffer)
                for start in range(0, len(buffer), 4092):
                    end = min(start + 4092, len(buffer))
                    _swap_rgb565_bytes(buffer, start, end)
                    try:
                        self._spi.write(view[start:end])
                    finally:
                        _swap_rgb565_bytes(buffer, start, end)
            except BaseException as caught:
                error = caught
                raise
            finally:
                try:
                    self._cs(1)
                except BaseException:
                    if error is None:
                        raise
        except BaseException:
            self._fail_transfer_outputs_closed()
            raise

    def backlight(self, enabled):
        self._require_open()
        if type(enabled) is not bool:
            raise TypeError("enabled must be Boolean")
        self._backlight(1 if enabled else 0)

    def deinit(self):
        if self._closed:
            return
        self._cleanup()
