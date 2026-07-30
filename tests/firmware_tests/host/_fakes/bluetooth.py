# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# HOST-ONLY GUARD, not production code and NOT a fake of BLE behaviour.
#
# `pyble_ble.py` runs on MicroPython and touches the NimBLE `bluetooth` module,
# which does not exist under CPython. This stub is injected into `sys.modules`
# BEFORE `pyble_ble` is imported (see _support.py) purely so that importing
# `pyble_ble`'s PURE, BLE-INDEPENDENT helpers (PyBLE-XXXX name derivation, INFO
# payload assembly, MTU payload sizing) does not fail with ModuleNotFoundError on
# the host. It deliberately provides NO NimBLE semantics: the peripheral itself
# (GATT service/characteristics, advertising, MTU negotiation, subscribe/notify)
# is HIL-verified on a classic ESP32, NEVER faked (per the S2 environment-reality
# rule). Any test that reaches into these names is a test smell — the pure
# helpers must not depend on live BLE.

_UNFAKED = (
    "bluetooth.BLE is a HIL-only surface: pyble_ble's PURE helpers must not "
    "call it on the host. The NimBLE peripheral is verified on real hardware, "
    "never with a host fake."
)

# Common MicroPython bluetooth IRQ constants, present so a top-level module-scope
# reference in pyble_ble does not NameError at import; they carry no behaviour.
_IRQ_CENTRAL_CONNECT = 1
_IRQ_CENTRAL_DISCONNECT = 2
_IRQ_GATTS_WRITE = 3
_IRQ_MTU_EXCHANGED = 21
FLAG_READ = 0x0002
FLAG_WRITE_NO_RESPONSE = 0x0004
FLAG_WRITE = 0x0008
FLAG_NOTIFY = 0x0010


class BLE:  # noqa: N801 - mirrors the MicroPython class name
    def __getattr__(self, name):
        raise NotImplementedError(_UNFAKED)

    def __call__(self, *a, **k):
        raise NotImplementedError(_UNFAKED)


def UUID(value):  # MicroPython bluetooth.UUID(...)
    # Return the value unchanged so a module-scope UUID table can be built at
    # import time; equality/round-trip of UUID *bytes* is a HIL/native concern.
    return value
