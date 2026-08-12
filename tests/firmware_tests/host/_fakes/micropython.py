# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# HOST-ONLY GUARD for the MicroPython `micropython` module (const / schedule /
# kbd_intr). Injected via host/_fakes/ sys.path so a host import of the rp2
# agent scaffolds does not fail under CPython. Provides NO runtime semantics:
# `schedule` and `kbd_intr` are NO-OPS by design — scheduled-callback and
# keyboard-interrupt behaviour is HIL-verified on real hardware (the rp2 port
# additionally swallows scheduled-callback exceptions, which is exactly why the
# port spec P3 routes STOP through the dupterm 0x03 channel instead). Any test
# that depends on these doing something is a test smell.


def const(value):
    """MicroPython compile-time constant marker — identity on the host."""
    return value


def schedule(func, arg):
    """NO-OP: scheduled execution is a HIL-only surface, never host-faked."""
    return None


def kbd_intr(chr_):
    """NO-OP: interrupt-char plumbing is a HIL-only surface, never host-faked."""
    return None
