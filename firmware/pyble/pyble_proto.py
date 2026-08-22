# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# pyble_proto — PBLE/1 protocol engine (Layer 3, pure Python, MicroPython-safe).
#
# This module MIRRORS protocol.md; it never redefines the wire. Every constant
# and byte layout below is copied from the FROZEN v1.0 sections:
#   §3.1 message frame, §3.2 fragmentation (G0 · 2026-07-01)
#   §4 opcodes, §8 status                 (G1 · 2026-07-01, OI-4 closed)
#
# Responsibilities (F-02 / FR-PROTO-1..9, FR-BLE-8/10):
#   * §3.1 frame encode/decode (VER/TYPE/OPCODE/ID/LEN/PAYLOAD/CRC32).
#   * IEEE CRC-32 over VER..PAYLOAD (little-endian), validated on every message.
#   * §3.2 fragmentation split + byte-identical reassembly over the MTU matrix.
#   * Table-driven opcode -> handler dispatch with request/response ID
#     correlation; events use ID=0.
#   * Full 1-byte status mapping (§8), incl. every error code.
#
# Pure Python only — NO `bluetooth` / `machine` imports. The ble<->proto
# contract is: pyble_ble delivers reassembled bytes to `Dispatcher.on_message`;
# pyble_proto returns encoded RSP/EVT bytes for pyble_ble to fragment + Notify.

# --- Protocol version (protocol.md §3.1) -------------------------------------
VER = 0x01

# --- Frame TYPE (protocol.md §3.1) -------------------------------------------
CMD = 0x01
RSP = 0x02
EVT = 0x03

# --- Opcodes (protocol.md §4, FROZEN v1.0) -----------------------------------
OPCODES = {
    "HELLO": 0x01,
    "DEVICE_INFO": 0x02,
    "FILE_LIST": 0x10,
    "FILE_STAT": 0x11,
    "FILE_GET_BEGIN": 0x12,
    "FILE_GET_DATA": 0x13,
    "FILE_GET_END": 0x14,
    "FILE_PUT_BEGIN": 0x15,
    "FILE_PUT_DATA": 0x16,
    "FILE_PUT_END": 0x17,
    "FILE_DELETE": 0x18,
    "MKDIR": 0x19,
    "FILE_RENAME": 0x1A,
    "RUN": 0x20,
    "STOP": 0x21,
    "SOFT_REBOOT": 0x22,
    "SET_AUTORUN": 0x23,  # additive §9 opcode (S6 F-12), auto_run-cap gated
    "CONSOLE_DATA": 0x30,
    "CONSOLE_INPUT": 0x31,
    "RUN_STATE": 0x40,
    "FILE_PUT_ACK": 0x41,
    "SET_LABEL": 0x50,
    "SET_IDENTIFY_LED": 0x51,
    "IDENTIFY": 0x52,
}

# --- Status / error codes (protocol.md §8, FROZEN v1.0) ----------------------
STATUS = {
    "OK": 0x00,
    "EBADREQ": 0x01,
    "ENOENT": 0x02,
    "EACCES": 0x03,
    "ENOSPC": 0x04,
    "EIO": 0x05,
    "ENOMEM": 0x06,
    "EBUSY": 0x07,
    "ECRC": 0x08,
    "ERANGE": 0x09,
    "EUNSUPPORTED": 0x0A,
    "EINTERNAL": 0xFF,
}

# --- Fragmentation header bits (protocol.md §3.2) ----------------------------
FRAG_FIRST = 0x80  # bit7
FRAG_LAST = 0x40   # bit6
FRAG_INDEX_MASK = 0x3F  # bits5..0 = index mod 64

_HEADER_LEN = 6  # VER + TYPE + OPCODE + ID + LEN(2)
_CRC_LEN = 4
_MIN_FRAME = _HEADER_LEN + _CRC_LEN  # smallest valid frame (empty payload)


class ProtocolError(ValueError):
    """A structurally malformed §3.1 frame (short header or LEN overrun)."""


# --- IEEE CRC-32 (protocol.md §3.1 / FR-PROTO-3) -----------------------------
# Native fast path: `binascii.crc32` (zlib-compatible IEEE CRC-32) where the
# runtime provides it (MicroPython rp2, CPython). The pure-Python table below
# stays as the fallback so the module imports anywhere; both forms are
# BIT-IDENTICAL (guarded by the shared conformance corpus + the rp2 streaming
# suite, tests/firmware_tests/host/test_pyble_proto_opcode_parity.py).
try:
    from binascii import crc32 as _crc32_native
except ImportError:
    _crc32_native = None

# Pure-Python, table-driven, reflected CRC-32 (poly 0xEDB88320, init/xorout
# 0xFFFFFFFF) — bit-identical to zlib.crc32 on both CPython and MicroPython,
# with no dependency on the host `zlib`/`binascii` module.
_CRC_TABLE = []
for _n in range(256):
    _c = _n
    for _k in range(8):
        _c = (0xEDB88320 ^ (_c >> 1)) if (_c & 1) else (_c >> 1)
    _CRC_TABLE.append(_c & 0xFFFFFFFF)
del _n, _c, _k


def _crc32_pure_update(crc, chunk):
    """Pure-table streaming step, chained exactly like binascii.crc32(chunk, crc)
    (un-finalize the running value, fold the chunk, re-finalize)."""
    crc = (crc ^ 0xFFFFFFFF) & 0xFFFFFFFF
    for byte in chunk:
        crc = _CRC_TABLE[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


def crc32_update(crc, chunk):
    """Streaming IEEE CRC-32 (F-25): seed 0, chain c = crc32_update(c, chunk);
    the final value equals crc32(b"".join(chunks)). Accepts bytes / bytearray /
    memoryview chunks (the rp2 file worker streams flash reads through
    memoryviews). Native `binascii.crc32` fast path where available."""
    if _crc32_native is not None:
        return _crc32_native(chunk, crc) & 0xFFFFFFFF
    return _crc32_pure_update(crc, chunk)


def crc32(buf):
    """IEEE CRC-32 (zlib-compatible) over `buf`, returned as a uint32."""
    return crc32_update(0, buf)


class Frame:
    """A decoded §3.1 message: VER / TYPE / OPCODE / ID / PAYLOAD."""

    __slots__ = ("ver", "type", "opcode", "id", "payload")

    def __init__(self, ver, type_, opcode, id_, payload):
        self.ver = ver
        self.type = type_
        self.opcode = opcode
        self.id = id_
        self.payload = payload

    def __repr__(self):
        return "Frame(ver=%d, type=%d, opcode=0x%02x, id=%d, len=%d)" % (
            self.ver, self.type, self.opcode, self.id, len(self.payload)
        )


def encode(type_, opcode, id_, payload=b""):
    """Build a §3.1 frame with a valid IEEE CRC-32 over VER..PAYLOAD."""
    payload = bytes(payload)
    header = bytes((VER, type_ & 0xFF, opcode & 0xFF, id_ & 0xFF)) + \
        (len(payload) & 0xFFFF).to_bytes(2, "little") + payload
    return header + crc32(header).to_bytes(4, "little")


def decode(msg):
    """Parse a §3.1 frame into a Frame (structural only — does NOT validate the
    CRC; the dispatcher checks CRC so it can answer EVT ERROR(ECRC) on failure).
    Raises ProtocolError on a structurally malformed frame (FR-PROTO-8)."""
    msg = bytes(msg)
    if len(msg) < _MIN_FRAME:
        raise ProtocolError("frame shorter than the §3.1 minimum")
    length = int.from_bytes(msg[4:6], "little")
    if len(msg) != _HEADER_LEN + length + _CRC_LEN:
        raise ProtocolError("LEN does not match the §3.1 frame length")
    payload = msg[_HEADER_LEN:_HEADER_LEN + length]
    return Frame(msg[0], msg[1], msg[2], msg[3], payload)


def _crc_ok(msg):
    """True iff the trailing 4-byte CRC matches IEEE CRC-32 over VER..PAYLOAD."""
    got = int.from_bytes(msg[-_CRC_LEN:], "little")
    return crc32(msg[:-_CRC_LEN]) == got


# --- §3.2 fragmentation ------------------------------------------------------
def fragment(msg, mtu):
    """Split a §3.1 message into §3.2 packets: 1-byte FRAG_HDR + up to (MTU-4)
    data bytes. FIRST on the first packet, LAST on the last, bits5..0 = index
    mod 64. An empty message still yields one FIRST|LAST packet."""
    msg = bytes(msg)
    data_size = mtu - 4
    if data_size < 1:
        raise ValueError("MTU too small to carry a fragment")
    chunks = [msg[i:i + data_size] for i in range(0, len(msg), data_size)]
    if not chunks:
        chunks = [b""]
    last = len(chunks) - 1
    packets = []
    for i, chunk in enumerate(chunks):
        hdr = i & FRAG_INDEX_MASK
        if i == 0:
            hdr |= FRAG_FIRST
        if i == last:
            hdr |= FRAG_LAST
        packets.append(bytes((hdr,)) + chunk)
    return packets


def reassemble(packets):
    """Concatenate §3.2 FRAGMENT DATA (each packet minus its 1-byte header) back
    into the original §3.1 message, byte-identically."""
    return b"".join(bytes(pkt[1:]) for pkt in packets)


class Dispatcher:
    """Table-driven OPCODE -> handler registry (FR-PROTO-5). Decodes an inbound
    reassembled message, validates CRC, and returns the encoded RSP/EVT bytes.

    Contract (ble -> proto): `on_message(msg: bytes) -> bytes | None`.
      * handler(frame) -> RSP payload (payload[0] is the §8 status). The
        dispatcher wraps it in a RSP echoing the request opcode + ID.
      * unknown opcode  -> RSP payload[0]=EUNSUPPORTED, echoing id + opcode.
      * CRC failure     -> EVT id=0, opcode=offending, payload[0]=ECRC (dropped,
        never dispatched).
      * malformed frame -> RSP payload[0]=EBADREQ.
    """

    def __init__(self):
        self._handlers = {}

    def register(self, opcode, handler):
        """Bind a handler to an opcode. handler(frame) -> RSP payload bytes."""
        self._handlers[opcode] = handler

    def on_message(self, msg):
        msg = bytes(msg)
        # 1. Structural parse. A malformed frame -> EBADREQ (FR-PROTO-8). We
        #    best-effort recover opcode/id for the RSP header when present.
        try:
            frame = decode(msg)
        except ProtocolError:
            opcode = msg[2] if len(msg) > 2 else 0x00
            id_ = msg[3] if len(msg) > 3 else 0x00
            return encode(RSP, opcode, id_, bytes((STATUS["EBADREQ"],)))
        # 2. Version gate (FR-PROTO-7): PBLE/1 serves only VER=0x01. Refuse a
        #    structurally-valid other-version frame before opcode dispatch.
        if frame.ver != VER:
            return encode(RSP, frame.opcode, frame.id,
                          bytes((STATUS["EBADREQ"],)))
        # 3. CRC gate (FR-PROTO-3): a mismatch drops the frame and answers
        #    EVT ERROR(ECRC) referencing the opcode; the handler is NOT called.
        if not _crc_ok(msg):
            return encode(EVT, frame.opcode, 0, bytes((STATUS["ECRC"],)))
        # 4. Dispatch by opcode (FR-PROTO-5). Unknown/unregistered opcode ->
        #    EUNSUPPORTED (FR-PROTO-9), echoing the request id + opcode.
        handler = self._handlers.get(frame.opcode)
        if handler is None:
            return encode(RSP, frame.opcode, frame.id,
                          bytes((STATUS["EUNSUPPORTED"],)))
        rsp_payload = handler(frame)
        if rsp_payload is None:
            return None  # handler emits its own events (e.g. CMD-only opcodes)
        # 5. RSP echoes the request opcode + ID (FR-PROTO-4).
        return encode(RSP, frame.opcode, frame.id, bytes(rsp_payload))
