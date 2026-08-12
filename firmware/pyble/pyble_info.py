# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Identity & caps for the rpi-pico2-w port (F-25, plan C7; port spec P1).
#
# ONE payload source for the frozen protocol.md §7 capability text: the same
# caps bytes feed the HELLO RSP, the DEVICE_INFO RSP, and the INFO
# characteristic read. Serialization is the frozen 2026-07-02 form —
# newline-separated ASCII `key=value` lines with the SHORT key tokens, in the
# native twin's (pble_info.c) emission order. RSP payloads lead with
# [status:u8]; the INFO characteristic serves the caps text verbatim.
#
# Port-frozen values (ports/rpi-pico2-w.md P1):
#   chip=rpi-pico2-w · window=4 (initial; raise only on HIL evidence) ·
#   chunk = mtu − 18 (PBLE_CHUNK_OVERHEAD twin: one §3.1 file DATA message
#   per notify packet; mtu − 4 was the 11.9 kB download-stall bug) ·
#   has_identify=0 (IDENTIFY → EUNSUPPORTED this increment; identify_led=255)
#   device_id from machine.unique_id() — NEVER ble.config('mac') (BTstack may
#   fall back to a per-boot random static address).
#
# Runs on MicroPython v1.28 and imports under CPython 3.9+ (host suite).

import sys

PROTO_VERSION = 1        # §9: the single supported PBLE/1 protocol version

_STATUS_OK = 0x00        # §8 frozen OK status; RSP payloads lead with it

CHIP = "rpi-pico2-w"     # P1: the port's frozen §7 open `chip` identifier
FS_ROOT = "/"            # workspace-jail root (§7)
PUT_WINDOW = 4           # P1: initial window; raised only on HIL evidence
CHUNK_OVERHEAD = 18      # PBLE_CHUNK_OVERHEAD twin (§3.1 header+offset+crc)
HAS_SD = 0               # no SD on this port
HAS_IDENTIFY = 0         # IDENTIFY → EUNSUPPORTED this increment (spec-legal)
IDENTIFY_LED_NONE = 255  # §7: identify_led byte 0xFF = none

_AGENT_VERSION_FALLBACK = "0.0.0-dev"   # native twin's dev default (BLD-12)


def agent_version():
    """The agent SemVer, resolved AT CALL TIME from the build-generated
    frozen `_version.py` (single-sourced from versions.lock [pyble], the
    BLD-12 equivalent). Dev images without the generated module fall back to
    the native twin's default — never a hardcoded release string."""
    try:
        import _version
        return _version.AGENT_VERSION
    except (ImportError, AttributeError):
        return _AGENT_VERSION_FALLBACK


def device_id_from_unique_id(uid):
    """Last two machine.unique_id() bytes as UPPERCASE zero-padded hex.
    The stable flash ID — never the BLE MAC (P1)."""
    return "%02X%02X" % (uid[-2], uid[-1])


def device_id_now():
    """Live device_id on target hardware (host tests inject instead)."""
    import machine
    return device_id_from_unique_id(machine.unique_id())


def free_mem_now():
    """Live free heap via gc.mem_free(); guarded so a CPython host import
    (no mem_free) degrades to 0 instead of raising."""
    try:
        import gc
        return gc.mem_free()
    except (ImportError, AttributeError):
        return 0


def chunk_size(mtu):
    """chunk = mtu − 18, floored at 0 (native twin guard, never negative)."""
    if mtu > CHUNK_OVERHEAD:
        return mtu - CHUNK_OVERHEAD
    return 0


def _mpy_version():
    """The MicroPython version string (MICROPY_VERSION_STRING twin). On a
    CPython host this is the interpreter version — non-empty either way."""
    v = sys.implementation.version
    return "%d.%d.%d" % (v[0], v[1], v[2])


def caps_payload(mtu, free_mem, device_id, label, auto_run):
    """THE single §7 caps source: ASCII `key=value\n` lines in the native
    twin's frozen token order. Injected args carry the live/persisted state
    (mtu from the link, free_mem, device_id, label, auto_run flag)."""
    pairs = (
        ("proto", "%d" % PROTO_VERSION),
        ("agent", agent_version()),
        ("chip", CHIP),
        ("mpy", _mpy_version()),
        ("fs_root", FS_ROOT),
        ("mtu", "%d" % mtu),
        ("window", "%d" % PUT_WINDOW),
        ("chunk", "%d" % chunk_size(mtu)),
        ("free_mem", "%d" % free_mem),
        ("has_sd", "%d" % HAS_SD),
        ("has_identify", "%d" % HAS_IDENTIFY),
        ("identify_led", "%d" % IDENTIFY_LED_NONE),
        ("auto_run", "%d" % auto_run),
        ("device_id", device_id),
        ("label", label),
    )
    out = ""
    for key, value in pairs:
        out += key + "=" + value + "\n"
    return out.encode()


def hello_rsp_payload(mtu, free_mem, device_id, label, auto_run):
    """§7 HELLO RSP payload: [status:u8 = OK] + the caps text."""
    return bytes((_STATUS_OK,)) + caps_payload(
        mtu, free_mem, device_id, label, auto_run)


def device_info_rsp_payload(mtu, free_mem, device_id, label, auto_run):
    """DEVICE_INFO RSP == HELLO RSP byte-identically (single source)."""
    return hello_rsp_payload(mtu, free_mem, device_id, label, auto_run)


def info_char_payload(mtu, free_mem, device_id, label, auto_run):
    """An INFO characteristic read serves the caps text VERBATIM — the same
    DEVICE_INFO payload, no status prefix (§7 frozen)."""
    return caps_payload(mtu, free_mem, device_id, label, auto_run)


def negotiate(offered):
    """FR-INFO-5: choose a supported proto version from the client's offer;
    refuse (None) an offer without v1 — never silently mis-speak."""
    return PROTO_VERSION if PROTO_VERSION in offered else None
