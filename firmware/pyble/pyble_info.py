# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Pure host seam for the native pble_info module.
#
# Runtime capability collection and INFO/HELLO serving remain native in
# pble_info.c. These deterministic values exercise the frozen capability shape,
# negotiation rule, and single-payload-source invariant without pretending to
# read target hardware. Board manifests deliberately do not freeze this twin.

PROTO_VERSION = 1

_CAPS = {
    "chip": "esp32",
    "mpy_version": "1.28.0",
    "fs_root": "/",
    "max_file_size": 2 * 1024 * 1024,
    "put_window": 8,
    "chunk_size": 229,
    "has_sd": False,
    "free_mem": 0,
    "device_id": "0000",
    "label": "",
    "has_identify": False,
    "identify_led": None,
    "mtu": 247,
}

_PAYLOAD_FIELDS = (
    "chip",
    "mpy_version",
    "fs_root",
    "max_file_size",
    "put_window",
    "chunk_size",
    "has_sd",
    "free_mem",
    "device_id",
    "label",
    "has_identify",
    "identify_led",
    "mtu",
)


def caps():
    """Return a fresh view of the stable native capability contract."""
    return dict(_CAPS)


def device_info():
    """DEVICE_INFO and HELLO share the same capability source."""
    return caps()


def _payload_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def device_info_payload():
    """Return a deterministic host representation of the INFO payload."""
    info = device_info()
    return "".join(
        "{}={}\n".format(field, _payload_value(info[field]))
        for field in _PAYLOAD_FIELDS
    ).encode("utf-8")


def info_read_value():
    """INFO reads serve the exact DEVICE_INFO payload bytes."""
    return device_info_payload()


def negotiate(offered):
    """Choose PBLE/1 only when the client explicitly offers it."""
    return PROTO_VERSION if PROTO_VERSION in offered else None
