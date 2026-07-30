# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# HOST-ONLY GUARD for the MicroPython `machine` module (Pin/Timer/unique_id).
# Injected into sys.modules before importing pyble_ble so a host import of the
# module's PURE helpers does not fail. Provides NO hardware semantics; any GPIO/
# timer behaviour is HIL-verified on real hardware, never faked here.


class Pin:  # noqa: N801
    IN = 0
    OUT = 1

    def __init__(self, *a, **k):
        raise NotImplementedError("machine.Pin is a HIL-only surface, not host-faked")


class Timer:  # noqa: N801
    def __init__(self, *a, **k):
        raise NotImplementedError("machine.Timer is a HIL-only surface, not host-faked")


def unique_id():
    raise NotImplementedError("machine.unique_id is a HIL-only surface, not host-faked")
