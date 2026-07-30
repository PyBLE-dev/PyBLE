# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# PBLE/1 wire codec for the HIL bench harness (host-side, pure Python, no deps).
#
# This is the SAME frozen wire the firmware `pble_proto` codec and the Dart `pble`
# client implement — referenced from protocol.md, NEVER redefined here:
#   §3.1 message frame : [VER:u8][TYPE:u8][OPCODE:u8][ID:u8][LEN:u16 LE][PAYLOAD][CRC32:u32 LE]
#                        CRC32 = IEEE CRC-32 (zlib) over VER..PAYLOAD, little-endian.
#   §3.2 fragmentation : each GATT packet = [FRAG_HDR:u8][FRAGMENT DATA <= MTU-4]
#                        FRAG_HDR bit7=FIRST, bit6=LAST, bits5..0 = index mod 64.
#   §4 opcodes / §8 status : the frozen number sets (mirrored below for the bench).
#
# All values are FROZEN for v1.0 (protocol.md §2/§3 G0, §4/§8 G1, 2026-07-01).
# host/conformance/test_hil_wire.py cross-checks this codec byte-for-byte against
# the SHARED corpus (host/conformance/corpus.json), so the HIL harness cannot
# drift from the firmware<->Dart contract. If this file and the corpus disagree,
# the harness is wrong, not the wire.

import zlib

VER = 0x01

# §3.1 TYPE
CMD = 0x01
RSP = 0x02
EVT = 0x03

# §4 opcodes (frozen set/numbers) — only those the bench and the S6 stories touch.
OP_HELLO = 0x01
OP_DEVICE_INFO = 0x02
OP_FILE_LIST = 0x10
OP_FILE_STAT = 0x11
OP_FILE_GET_BEGIN = 0x12
OP_FILE_GET_DATA = 0x13
OP_FILE_GET_END = 0x14
OP_FILE_PUT_BEGIN = 0x15
OP_FILE_PUT_DATA = 0x16
OP_FILE_PUT_END = 0x17
OP_FILE_DELETE = 0x18
OP_MKDIR = 0x19
OP_FILE_RENAME = 0x1A
OP_RUN = 0x20
OP_STOP = 0x21
OP_SOFT_REBOOT = 0x22
OP_CONSOLE_DATA = 0x30
OP_CONSOLE_INPUT = 0x31
OP_RUN_STATE = 0x40
OP_FILE_PUT_ACK = 0x41
OP_SET_LABEL = 0x50
OP_SET_IDENTIFY_LED = 0x51
OP_IDENTIFY = 0x52

# §8 status (frozen numbers)
ST_OK = 0x00
ST_EBADREQ = 0x01
ST_ENOENT = 0x02
ST_EACCES = 0x03
ST_ENOSPC = 0x04
ST_EIO = 0x05
ST_ENOMEM = 0x06
ST_EBUSY = 0x07
ST_ECRC = 0x08
ST_ERANGE = 0x09
ST_EUNSUPPORTED = 0x0A
ST_EINTERNAL = 0xFF

STATUS_NAME = {
    ST_OK: "OK", ST_EBADREQ: "EBADREQ", ST_ENOENT: "ENOENT", ST_EACCES: "EACCES",
    ST_ENOSPC: "ENOSPC", ST_EIO: "EIO", ST_ENOMEM: "ENOMEM", ST_EBUSY: "EBUSY",
    ST_ECRC: "ECRC", ST_ERANGE: "ERANGE", ST_EUNSUPPORTED: "EUNSUPPORTED",
    ST_EINTERNAL: "EINTERNAL",
}


def crc32(data: bytes) -> int:
    """IEEE CRC-32 (zlib-compatible), the frozen §3.1 checksum."""
    return zlib.crc32(data) & 0xFFFFFFFF


class Frame:
    __slots__ = ("type", "opcode", "id", "payload")

    def __init__(self, type_, opcode, id_, payload=b""):
        self.type = type_
        self.opcode = opcode
        self.id = id_
        self.payload = bytes(payload)

    def __repr__(self):
        return "Frame(type=%d op=0x%02x id=%d len=%d)" % (
            self.type, self.opcode, self.id, len(self.payload))


def encode(type_: int, opcode: int, id_: int, payload: bytes = b"") -> bytes:
    """Encode a §3.1 message frame (header + payload + trailing CRC-32 LE)."""
    payload = bytes(payload)
    if len(payload) > 0xFFFF:
        raise ValueError("payload exceeds LEN:u16")
    body = bytes((VER, type_ & 0xFF, opcode & 0xFF, id_ & 0xFF)) + \
        len(payload).to_bytes(2, "little") + payload
    return body + crc32(body).to_bytes(4, "little")


def decode(frame: bytes) -> Frame:
    """Decode + CRC-verify a reassembled §3.1 message. Raises on bad VER/LEN/CRC."""
    if len(frame) < 10:
        raise ValueError("frame shorter than the 10-byte minimum")
    ver = frame[0]
    if ver != VER:
        raise ValueError("unsupported VER 0x%02x (v1.0 accepts only 0x01)" % ver)
    type_ = frame[1]
    opcode = frame[2]
    id_ = frame[3]
    plen = int.from_bytes(frame[4:6], "little")
    if len(frame) != 6 + plen + 4:
        raise ValueError("LEN %d disagrees with frame length %d" % (plen, len(frame)))
    payload = frame[6:6 + plen]
    got = int.from_bytes(frame[6 + plen:6 + plen + 4], "little")
    want = crc32(frame[:6 + plen])
    if got != want:
        raise ValueError("CRC mismatch: got 0x%08x want 0x%08x" % (got, want))
    return Frame(type_, opcode, id_, payload)


def fragment(frame: bytes, mtu: int):
    """Split a §3.1 message into §3.2 GATT packets. Fragment data <= MTU-4 bytes;
    FRAG_HDR carries FIRST/LAST + (index mod 64)."""
    cap = mtu - 4
    if cap < 1:
        raise ValueError("MTU %d too small for a fragment" % mtu)
    packets = []
    n = (len(frame) + cap - 1) // cap or 1
    for i in range(n):
        hdr = (i % 64) & 0x3F
        if i == 0:
            hdr |= 0x80          # FIRST
        if i == n - 1:
            hdr |= 0x40          # LAST
        packets.append(bytes((hdr,)) + frame[i * cap:(i + 1) * cap])
    return packets


class Reassembler:
    """Accumulates §3.2 GATT packets into §3.1 messages. Feed one packet at a
    time; returns a decoded Frame when a LAST packet completes a message, else
    None. A FIRST bit restarts the buffer (drops a partial run)."""

    def __init__(self):
        self._buf = bytearray()
        self._open = False

    def feed(self, packet: bytes):
        if not packet:
            return None
        hdr = packet[0]
        first = bool(hdr & 0x80)
        last = bool(hdr & 0x40)
        data = packet[1:]
        if first:
            self._buf = bytearray()
            self._open = True
        if not self._open:
            return None
        self._buf.extend(data)
        if last:
            self._open = False
            return decode(bytes(self._buf))
        return None
