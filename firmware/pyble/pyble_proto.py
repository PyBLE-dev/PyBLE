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
_HELLO_MAX = 192
_HELLO_FIELD_MAX = 32
_HELLO_OFFERS_MAX = 8
_NO_RSP_COMMANDS = (OPCODES["FILE_PUT_DATA"], OPCODES["CONSOLE_INPUT"])


def strict_utf8_decode(data):
    """Decode only shortest-form Unicode scalar UTF-8, else return ``None``.

    Some supported MicroPython builds accept overlong encodings or surrogate
    code points in ``bytes.decode``.  Wire text therefore validates the bytes
    explicitly before asking the runtime to construct the string.
    """
    try:
        data = bytes(data)
    except Exception:
        return None

    length = len(data)
    index = 0
    while index < length:
        first = data[index]
        if first <= 0x7F:
            index += 1
            continue

        if 0xC2 <= first <= 0xDF:
            if index + 1 >= length:
                return None
            second = data[index + 1]
            if not 0x80 <= second <= 0xBF:
                return None
            index += 2
            continue

        if 0xE0 <= first <= 0xEF:
            if index + 2 >= length:
                return None
            second = data[index + 1]
            third = data[index + 2]
            if first == 0xE0:
                second_ok = 0xA0 <= second <= 0xBF
            elif first == 0xED:
                second_ok = 0x80 <= second <= 0x9F
            else:
                second_ok = 0x80 <= second <= 0xBF
            if not second_ok or not 0x80 <= third <= 0xBF:
                return None
            index += 3
            continue

        if 0xF0 <= first <= 0xF4:
            if index + 3 >= length:
                return None
            second = data[index + 1]
            third = data[index + 2]
            fourth = data[index + 3]
            if first == 0xF0:
                second_ok = 0x90 <= second <= 0xBF
            elif first == 0xF4:
                second_ok = 0x80 <= second <= 0x8F
            else:
                second_ok = 0x80 <= second <= 0xBF
            if (not second_ok or not 0x80 <= third <= 0xBF or
                    not 0x80 <= fourth <= 0xBF):
                return None
            index += 4
            continue

        return None

    try:
        return data.decode("utf-8")
    except Exception:
        # The byte grammar above is complete, but fail closed if a particular
        # runtime still cannot materialize one otherwise-valid scalar.
        return None


def _path_end(payload, offset):
    """Return the byte after one `[plen:u16][path]`, or None if truncated."""
    if offset < 0 or offset + 2 > len(payload):
        return None
    path_len = payload[offset] | (payload[offset + 1] << 8)
    end = offset + 2 + path_len
    return end if end <= len(payload) else None


def _payload_exact(opcode, payload):
    """PBLE/1's fixed/structured payload-consumption grammar.

    Semantic range and path-jail checks stay in opcode handlers.  This reducer
    only proves that every declared field consumes the complete payload, so a
    valid prefix cannot hide extension bytes from the handler.
    """
    length = len(payload)
    if opcode in (OPCODES["DEVICE_INFO"], OPCODES["STOP"],
                  OPCODES["SOFT_REBOOT"]):
        return length == 0
    if opcode in (OPCODES["FILE_LIST"], OPCODES["FILE_STAT"],
                  OPCODES["FILE_DELETE"], OPCODES["MKDIR"]):
        return _path_end(payload, 0) == length
    if opcode == OPCODES["FILE_GET_BEGIN"]:
        return length >= 4 and _path_end(payload, 4) == length
    if opcode == OPCODES["FILE_PUT_BEGIN"]:
        return length >= 8 and _path_end(payload, 8) == length
    if opcode == OPCODES["FILE_PUT_END"]:
        return length == 4
    if opcode == OPCODES["FILE_RENAME"]:
        first = _path_end(payload, 0)
        return first is not None and _path_end(payload, first) == length
    if opcode == OPCODES["SET_AUTORUN"]:
        return length == 1
    if opcode == OPCODES["SET_IDENTIFY_LED"]:
        return length in (0, 2)
    if opcode == OPCODES["IDENTIFY"]:
        return length <= 1
    # HELLO owns its text grammar. RUN, PUT_DATA, CONSOLE_INPUT, and SET_LABEL
    # explicitly consume their last field as every remaining byte.
    return True


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


def _valid_hello_key(key):
    if not key or len(key) > _HELLO_FIELD_MAX:
        return False
    first = key[0]
    if first < 0x61 or first > 0x7A:
        return False
    for value in key[1:]:
        if not (0x61 <= value <= 0x7A or 0x30 <= value <= 0x39 or
                value == 0x5F):
            return False
    return True


def hello_status(payload):
    """Return the §8 status for one bounded, canonical HELLO payload."""
    payload = bytes(payload)
    if len(payload) > _HELLO_MAX:
        return STATUS["EBADREQ"]
    for value in payload:
        if value != 0x0A and not 0x20 <= value <= 0x7E:
            return STATUS["EBADREQ"]

    lines = payload.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()                       # one optional trailing LF
    if not lines or any(line == b"" for line in lines):
        return STATUS["EBADREQ"]

    required = {}
    required_keys = (b"proto_versions", b"app_name", b"app_version")
    for line in lines:
        split = line.find(b"=")
        if split <= 0:
            return STATUS["EBADREQ"]
        key = line[:split]
        value = line[split + 1:]
        if (not _valid_hello_key(key) or
                len(value) > _HELLO_FIELD_MAX):
            return STATUS["EBADREQ"]
        if key in required_keys:
            if key in required:
                return STATUS["EBADREQ"]
            required[key] = value

    if any(key not in required for key in required_keys):
        return STATUS["EBADREQ"]
    app_name = required[b"app_name"]
    app_version = required[b"app_version"]
    if not app_name or not app_version:
        return STATUS["EBADREQ"]

    offers = required[b"proto_versions"].split(b",")
    if not 1 <= len(offers) <= _HELLO_OFFERS_MAX:
        return STATUS["EBADREQ"]
    supports_v1 = False
    for token in offers:
        if (not token or (len(token) > 1 and token[0] == 0x30) or
                any(value < 0x30 or value > 0x39 for value in token)):
            return STATUS["EBADREQ"]
        number = 0
        for value in token:
            number = number * 10 + value - 0x30
            if number > 255:
                return STATUS["EBADREQ"]
        if number == VER:
            supports_v1 = True
    return STATUS["OK"] if supports_v1 else STATUS["EUNSUPPORTED"]


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

    def __init__(self, link=None):
        self._handlers = {}
        self._link = link
        self._negotiated_session = None
        self._publish_callback = None

    def reset_session(self):
        """Clear per-connection negotiation and any unpublished receipt."""
        self._negotiated_session = None
        self._publish_callback = None

    def take_publish_callback(self):
        """Return and consume the receipt belonging to the latest response."""
        callback = self._publish_callback
        self._publish_callback = None
        return callback

    def _session_token(self):
        if self._link is None:
            return None
        return self._link.session_token()

    def _negotiated(self, session):
        return session is not None and session == self._negotiated_session

    def _record_violation(self, session):
        if self._link is None:
            return True
        record = getattr(self._link, "record_protocol_violation", None)
        if record is None:
            return True
        return record(session)

    def _arm_hello_commit(self, session):
        def _commit():
            if (self._link is not None and session is not None and
                    self._link.session_token() == session):
                self._negotiated_session = session

        self._publish_callback = _commit

    def register(self, opcode, handler):
        """Bind a handler to an opcode. handler(frame) -> RSP payload bytes."""
        self._handlers[opcode] = handler

    def on_message(self, msg):
        msg = bytes(msg)
        # Receipts are response-local. A caller that failed/raised before
        # consuming the prior one cannot accidentally publish it later.
        self._publish_callback = None
        session = self._session_token()

        # 1. Exact structural length. Refuse only a complete safely correlated
        #    v1/CMD/nonzero-ID header; all malformed inputs still debit once.
        try:
            frame = decode(msg)
        except ProtocolError:
            admitted = self._record_violation(session)
            if (admitted and len(msg) >= _HEADER_LEN and msg[0] == VER and
                    msg[1] == CMD and msg[3] != 0):
                return encode(
                    RSP, msg[2], msg[3], bytes((STATUS["EBADREQ"],)))
            return None

        # 2. CRC gate (FR-PROTO-3): a mismatch drops the frame and answers
        #    EVT ERROR(ECRC) referencing the opcode; the handler is NOT called.
        if not _crc_ok(msg):
            if not self._record_violation(session):
                return None
            return encode(EVT, frame.opcode, 0, bytes((STATUS["ECRC"],)))

        # 3. Direction/request correlation precedes VER so inbound responses
        #    can never create response loops.
        if frame.type != CMD or frame.id == 0:
            self._record_violation(session)
            return None

        # 4. Version gate (FR-PROTO-7): PBLE/1 serves only VER=0x01.
        if frame.ver != VER:
            if not self._record_violation(session):
                return None
            return encode(RSP, frame.opcode, frame.id,
                          bytes((STATUS["EBADREQ"],)))

        # 5. HELLO and per-session admission. A session-less Dispatcher remains
        #    a strict low-level codec seam and deliberately skips this policy.
        if self._link is not None:
            if frame.opcode == OPCODES["HELLO"]:
                status = hello_status(frame.payload)
                if status != STATUS["OK"]:
                    if (status == STATUS["EBADREQ"] and
                            not self._record_violation(session)):
                        return None
                    return encode(RSP, frame.opcode, frame.id, bytes((status,)))
            elif not self._negotiated(session):
                if not self._record_violation(session):
                    return None
                if frame.opcode in _NO_RSP_COMMANDS:
                    return None
                return encode(RSP, frame.opcode, frame.id,
                              bytes((STATUS["EBADREQ"],)))

        # 6. Dispatch by opcode (FR-PROTO-5). Unknown/unregistered opcode ->
        #    EUNSUPPORTED (FR-PROTO-9), echoing the request id + opcode.
        handler = self._handlers.get(frame.opcode)
        if handler is None:
            return encode(RSP, frame.opcode, frame.id,
                          bytes((STATUS["EUNSUPPORTED"],)))
        if not _payload_exact(frame.opcode, frame.payload):
            if frame.opcode in _NO_RSP_COMMANDS:
                return None
            return encode(RSP, frame.opcode, frame.id,
                          bytes((STATUS["EBADREQ"],)))
        rsp_payload = handler(frame)
        if rsp_payload is None:
            return None  # handler emits its own events (e.g. CMD-only opcodes)
        # 7. RSP echoes the request opcode + ID (FR-PROTO-4). Successful HELLO
        #    only arms an exact-session callback; the Agent publishes it at the
        #    final-fragment local acceptance cut.
        rsp_payload = bytes(rsp_payload)
        response = encode(RSP, frame.opcode, frame.id, rsp_payload)
        if (self._link is not None and frame.opcode == OPCODES["HELLO"] and
                rsp_payload and rsp_payload[0] == STATUS["OK"]):
            self._arm_hello_commit(session)
        return response
