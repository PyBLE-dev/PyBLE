# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Opt-in boot splash for the exact Waveshare ESP32-S3-LCD-1.47B."""


__all__ = (
    "boot_splash_enabled",
    "enable_boot_splash",
    "disable_boot_splash",
    "show_boot_splash",
)


_NVS_NAMESPACE = "pyble"
_NVS_KEY = "lcd147splash"
# MicroPython maps ESP_ERR_NVS_NOT_FOUND (0x1102) to negative OSError errno.
_NVS_NOT_FOUND = -0x1102
_BOOT_EVIDENCE = ()

# Reviewed QR Model 2 Version 2, byte mode, ECC M, mask 2. Bit 24 is X=0.
_QR_ROWS = (
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


def _boot_evidence():
    """Return the immutable, VM-local observation from the latest boot guard."""
    return _BOOT_EVIDENCE


def _record_boot_event(event):
    global _BOOT_EVIDENCE

    try:
        _BOOT_EVIDENCE = _BOOT_EVIDENCE + (event,)
    except Exception:
        # Evidence must never turn an otherwise fail-open boot into a failure.
        pass


def boot_splash_enabled():
    """Return the persisted choice, defaulting an erased exact image on."""
    try:
        from esp32 import NVS

        value = NVS(_NVS_NAMESPACE).get_i32(_NVS_KEY)
    except OSError as error:
        # A full-chip web install erases NVS. Only the pinned missing-key code
        # selects the exact profile's factory state; every other NVS fault is
        # conservative and leaves the display disabled.
        return bool(error.args) and error.args[0] == _NVS_NOT_FOUND
    except Exception:
        return False
    return type(value) is int and value == 1


def enable_boot_splash():
    """Persist the exact-board splash opt-in without touching display pins."""
    from esp32 import NVS

    nvs = NVS(_NVS_NAMESPACE)
    nvs.set_i32(_NVS_KEY, 1)
    nvs.commit()


def disable_boot_splash():
    """Persist splash disablement, then best-effort blank its backlight."""
    from esp32 import NVS

    nvs = NVS(_NVS_NAMESPACE)
    nvs.set_i32(_NVS_KEY, 0)
    nvs.commit()

    try:
        from machine import Pin

        Pin(46, Pin.OUT, value=0)
    except Exception:
        pass


def _best_effort_pin(pin, value):
    if pin is not None:
        try:
            pin(value)
        except BaseException:
            pass


def _best_effort_deinit(display):
    if display is not None:
        try:
            display.deinit()
        except BaseException:
            pass


def _show_boot_splash(wait_ready, boot_event=None):
    backlight = None
    chip_select = None
    display = None
    retained = False

    try:
        if boot_event is not None:
            boot_event(("display-start",))

        from machine import Pin

        # GPIO46 and GPIO45 are strapping pins. They are touched only inside
        # this explicit exact-board transaction; import and disabled boot stay
        # electrically inert.
        backlight = Pin(46, Pin.OUT, value=0)
        chip_select = Pin(42, Pin.OUT, value=1)
        clock = Pin(40, Pin.OUT)
        data = Pin(45, Pin.OUT)
        data_command = Pin(41, Pin.OUT)
        reset = Pin(39, Pin.OUT)

        from pyble_st7789 import ST7789, rgb565

        display = ST7789(
            1,
            40_000_000,
            0,
            0,
            clock,
            data,
            chip_select,
            data_command,
            reset,
            backlight,
            172,
            320,
            34,
            0,
            True,
            True,
        )

        from pyble import __version__

        navy = rgb565(8, 15, 31)
        white = rgb565(255, 255, 255)
        black = rgb565(0, 0, 0)
        brand = rgb565(45, 91, 255)
        muted = rgb565(148, 163, 184)
        ready = rgb565(34, 197, 94)

        display.fill(navy)
        display.fill_rect(10, 10, 30, 30, brand)
        display.text(">_", 16, 21, white)
        display.text("PyBLE", 48, 14, white)
        display.text("PYTHON OVER BLE", 48, 27, muted)
        display.fill_rect(0, 45, 172, 2, brand)

        # The 25x25 reviewed matrix is surrounded by a four-module quiet zone.
        display.fill_rect(3, 52, 165, 165, white)
        for row, mask in enumerate(_QR_ROWS):
            for column in range(25):
                if mask & (1 << (24 - column)):
                    display.fill_rect(
                        3 + (column + 4) * 5,
                        52 + (row + 4) * 5,
                        5,
                        5,
                        black,
                    )

        display.text("SCAN TO INSTALL", 26, 225, white)
        display.text("pyble.dev/app", 34, 243, muted)
        display.fill_rect(36, 270, 6, 6, ready)
        display.text("BLE READY", 50, 269, white)
        display.text("Firmware v{}".format(__version__), 26, 296, muted)

        # Transfer one complete frame while unlit, then relinquish SPI and the
        # framebuffer before the final zero-wait readiness snapshot.
        display.show()
        if boot_event is not None:
            boot_event(("frame-show",))
        display.deinit()
        display = None

        import gc

        gc.collect()
        if boot_event is not None:
            boot_event(("resources-released",))

        ready = bool(wait_ready(0))
        if boot_event is not None:
            boot_event(("wait-ready", 0, ready))
        if not ready:
            return False

        backlight(1)
        if boot_event is not None:
            boot_event(("backlight-high",))
        retained = True
        return True
    finally:
        if not retained:
            _best_effort_deinit(display)
            _best_effort_pin(chip_select, 1)
            _best_effort_pin(backlight, 0)


def show_boot_splash():
    """Render explicitly and propagate display faults to the caller."""
    import pble_ble

    return _show_boot_splash(pble_ble.wait_ready)


def _maybe_show_boot_splash(wait_ready):
    """Fail-open boot hook; disabled state never waits or imports hardware."""
    global _BOOT_EVIDENCE

    _BOOT_EVIDENCE = ()
    _record_boot_event(("guard-enter",))
    try:
        enabled = boot_splash_enabled()
        _record_boot_event(("enabled", enabled))
        if not enabled:
            _record_boot_event(("return", False))
            return False

        ready = bool(wait_ready(1500))
        _record_boot_event(("wait-ready", 1500, ready))
        if not ready:
            _record_boot_event(("return", False))
            return False

        result = _show_boot_splash(wait_ready, _record_boot_event)
        _record_boot_event(("return", result))
        return result
    except Exception:
        _record_boot_event(("fault",))
        _record_boot_event(("return", False))
        return False
