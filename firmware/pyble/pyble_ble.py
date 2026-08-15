# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# pyble_ble — Layer-3 NimBLE peripheral & byte transport (F-01).
#
# This is the ONLY agent module that touches Layer-1 `bluetooth` (NimBLE). It
# owns exactly one primary GATT service on the PyBLE UUID base with RX
# (Write / Write-Without-Response), TX (Notify) and INFO (Read); `PyBLE-XXXX`
# advertising filtered to the Service UUID; MTU 247 negotiation; and the PBLE/1
# byte transport up to `pyble_proto` via `on_message` / down via `send_message`.
# It does NOT decode frames, compute CRC-32, author DEVICE_INFO/caps, or read
# NVS — it moves bytes only.
#
# Wire constants below MIRROR protocol.md §2 (GATT) and §3.2 (fragmentation);
# they are never redefined here. Any wire change goes through the
# firmware-architect and lands in protocol.md first.
#
# HOST-TESTABILITY SPLIT (S2 environment reality):
#   * The BLE-INDEPENDENT helpers (`device_id_from_mac`, `advertised_name`,
#     `payload_size`, `info_read_value`) are PURE and import under CPython with
#     no NimBLE — they are host-unit-tested (FR-BLE-5/8/12/4).
#   * `import bluetooth` / `import machine` are DEFERRED into the `BleLink`
#     peripheral wiring, so importing the pure helpers on the host never needs —
#     and never fakes — NimBLE. The peripheral itself (GATT service, RX/TX/INFO,
#     scan-filtered advertising, MTU-247 accept, subscribe/notify) is
#     HIL-verified on a classic ESP32, NEVER host-faked.

# ---------------------------------------------------------------------------
# Wire constants — mirrored from protocol.md §2 / §3.2 (FROZEN v1.0). Never
# redefine here; route any change to the firmware-architect via protocol.md.
# ---------------------------------------------------------------------------

# §2 GATT: one primary service on the PyBLE-owned 128-bit base `7079626c-…`
# (ASCII `pybl`). Kept as canonical strings so the pure helpers carry no NimBLE
# dependency; wrapped in `bluetooth.UUID(...)` only inside BleLink at wiring time.
SERVICE_UUID = "7079626c-1ab1-4d50-9e3a-000000000001"
RX_UUID = "7079626c-1ab1-4d50-9e3a-000000000002"  # app -> board: Write / WWR
TX_UUID = "7079626c-1ab1-4d50-9e3a-000000000003"  # board -> app: Notify
INFO_UUID = "7079626c-1ab1-4d50-9e3a-000000000004"  # board -> app: Read

# §2 advertising: default name `PyBLE-` + device_id; a set label replaces it.
NAME_PREFIX = "PyBLE-"

# §2 MTU: app requests 247; usable per-packet payload is MTU-3 (ATT) minus the
# 1-byte §3.2 fragmentation header.
ATT_HEADER = 3
FRAG_HEADER = 1
DEFAULT_MTU = 23  # BLE default; the transport MUST stay correct down to this.
PREFERRED_MTU = 247

# §3.2 FRAG_HDR bit layout: bit7 = FIRST, bit6 = LAST, bits5..0 = index mod 64.
FRAG_FIRST = 0x80
FRAG_LAST = 0x40
FRAG_INDEX_MASK = 0x3F
FRAG_INDEX_MOD = 64

# Reassembled-message cap (ports/rpi-pico2-w.md P6, FROZEN): covers RUN source
# <= 2048 plus headers with margin. An oversize message is dropped and reported
# via `on_oversize` so the agent can answer RSP ERANGE with an opcode/id echo.
RX_MAX = 4096


def _noop_published():
    pass

# MicroPython BLE IRQ event codes, module-local by REQUIREMENT (port spec P7):
# rp2 modbluetooth exports NO `_IRQ_*` attributes (hardware-verified
# 2026-08-11), so reading `bluetooth._IRQ_*` raises AttributeError on device.
# These are the stable numeric codes MicroPython documents for all ports.
_IRQ_CENTRAL_CONNECT = 1
_IRQ_CENTRAL_DISCONNECT = 2
_IRQ_GATTS_WRITE = 3
_IRQ_MTU_EXCHANGED = 21


# ---------------------------------------------------------------------------
# PURE, BLE-INDEPENDENT helpers (host-testable — no `bluetooth`/`machine`).
# ---------------------------------------------------------------------------

def device_id_from_mac(mac):
    """FR-BLE-5: the stable `XXXX` name suffix = the last two BLE-MAC bytes in
    UPPERCASE, zero-padded hex (e.g. MAC ...9F:3A -> '9F3A'). Recognition/display
    only — never an access/trust/routing signal (SEC-11, CON-7)."""
    return "{:02X}{:02X}".format(mac[-2], mac[-1])


def advertised_name(device_id, label=""):
    """FR-BLE-5 / FR-BLE-12: the advertised device name. Default is
    `PyBLE-` + device_id; a non-empty label REPLACES it (label length bounding is
    enforced upstream in the device-config store, not here — SEC-10, OI-6)."""
    if label:
        return label
    return NAME_PREFIX + device_id


def payload_size(mtu):
    """FR-BLE-8: usable per-packet PBLE/1 payload = MTU-3 (ATT header) minus the
    1-byte §3.2 fragmentation header. At MTU 247 this is 243 bytes; at the BLE
    default MTU 23 it is 19."""
    return mtu - ATT_HEADER - FRAG_HEADER


def info_read_value(payload):
    """FR-BLE-4: the INFO characteristic Read value is the DEVICE_INFO-equivalent
    payload served VERBATIM. pyble_ble does not author or transform these bytes —
    the encoding is owned by pyble_info (F-03); this module only serves them."""
    return bytes(payload)


# ---------------------------------------------------------------------------
# NimBLE peripheral & byte transport — HIL-ONLY (classic ESP32 bench).
#
# Everything below drives the real NimBLE stack. `import bluetooth` / `import
# machine` are DEFERRED into `start()` so importing the pure helpers above on the
# host never loads NimBLE. This class is HIL-verified, NEVER host-faked and NEVER
# claimed green from a host run (see tests/firmware_tests/gates/g1_check.sh).
# ---------------------------------------------------------------------------

class BleLink:
    """The NimBLE peripheral realizing the frozen ble<->proto contract.

    Inbound  (NimBLE RX -> proto):  reassemble §3.2 fragments -> on_message(bytes)
    Outbound (proto -> NimBLE TX):  send_message(bytes) -> fragment -> Notify on TX

    Chip-agnostic (D2): no chip conditionals live here. Per-chip NimBLE tuning is
    the Layer-2 board overlay's; this class reads the BLE MAC at runtime and is
    otherwise identical across esp32 / esp32-s3 / esp32-c3 (sets up M3)."""

    def __init__(self):
        self._ble = None            # bluetooth.BLE(), bound in start()
        self._conn_handle = None
        self._mtu = DEFAULT_MTU     # until the central negotiates upward
        self._mac = b"\x00" * 6     # raw BLE MAC, read from the stack in start()
        self._info_payload = b""
        self._adv_name = NAME_PREFIX + "0000"
        self._service_uuid = None   # bluetooth.UUID, built in start()
        # GATT value handles, populated by gatts_register_services():
        self._rx_handle = None
        self._tx_handle = None
        self._info_handle = None
        # §3.2 reassembly accumulator (bytes seen since the FIRST fragment):
        self._rx_buf = bytearray()
        self._rx_active = False
        self._rx_next_index = 0
        # up-calls into pyble_proto / pyble_agent (registered before start()):
        self._on_message = None
        self._on_connect = None
        self._on_disconnect = None
        self._on_oversize = None

    # -- frozen ble<->proto contract ---------------------------------------

    def on_message(self, cb):
        """Register the reassembled-message callback: cb(msg: bytes). pyble_proto
        decodes/validates CRC and dispatches — pyble_ble does neither."""
        self._on_message = cb

    def on_connect(self, cb):
        self._on_connect = cb

    def on_disconnect(self, cb):
        self._on_disconnect = cb

    def on_oversize(self, cb):
        """Register the P6 oversize-report callback: cb(head: bytes) fires ONCE
        per reassembled message exceeding RX_MAX, with `head` carrying at least
        the §3.1 header bytes (head[2]=opcode, head[3]=id) so the agent can
        echo RSP ERANGE. The oversize message itself is dropped, never
        delivered; reassembly recovers on the next FIRST fragment."""
        self._on_oversize = cb

    def mtu(self):
        """FR-BLE-7/8: the negotiated ATT MTU (247 once the central requests it,
        the BLE default until then). Sizes proto/storage buffers and the
        DEVICE_INFO.mtu field read by pyble_info."""
        return self._mtu

    def mac(self):
        """Raw 6-byte BLE MAC. Exposed to pyble_info/identity for device_id
        derivation (FR-BLE-5) — pyble_ble never derives device_id itself."""
        return self._mac

    def set_info_payload(self, payload):
        """FR-BLE-4: update the INFO characteristic's served bytes (authored by
        pyble_info). Served verbatim; not decoded here."""
        self._info_payload = info_read_value(payload)
        if self._ble is not None and self._info_handle is not None:
            self._ble.gatts_write(self._info_handle, self._info_payload)

    def set_adv_name(self, name):
        """FR-BLE-12: replace the advertised name (label-else-`PyBLE-XXXX`) and
        re-advertise pre-connect so the change shows in the scan list. The name is
        display-only; never an access/trust/routing signal (SEC-5/7/11)."""
        self._adv_name = name
        if self._ble is not None and self._conn_handle is None:
            self._start_advertising()

    def send_message(self, msg, on_published=None):
        """Sole TX path: fragment `msg` to `payload_size(mtu)` and Notify each
        §3.2 fragment on TX (FR-BLE-3/10). `msg` is already-encoded PBLE/1 bytes
        from pyble_proto — never inspected/decoded here. An optional receipt is
        called immediately after local acceptance of the final fragment."""
        if self._ble is None or self._conn_handle is None:
            return
        published = (_noop_published if on_published is None
                     else on_published)
        fragments = tuple(_fragment(msg, payload_size(self._mtu)))
        for frag in fragments[:-1]:
            self._ble.gatts_notify(self._conn_handle, self._tx_handle, frag)
        # Keep these two calls branch-adjacent. The pinned MicroPython VM checks
        # pending exceptions at branch points, while BTstack returns only after
        # copying or queueing the Notify. The receipt therefore commits before
        # a deferred STOP KeyboardInterrupt can be raised.
        self._ble.gatts_notify(
            self._conn_handle, self._tx_handle, fragments[-1])
        published()

    def start(self, info_payload=b""):
        """Boot the NimBLE peripheral: bind the stack, read the MAC, register the
        one GATT service (RX/TX/INFO), then advertise the Service UUID + name so
        the app can scan FILTERED to the Service UUID (FR-BLE-1..6/9). HIL-only.

        NimBLE only — Bluedroid is never built or referenced (FR-BLE-9, CON-5)."""
        import bluetooth  # DEFERRED: keeps the pure helpers host-importable.

        self._info_payload = info_read_value(info_payload)
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        # P7: pin the ATT MTU ceiling to 247 — only accepted AFTER active(True).
        self._ble.config(mtu=PREFERRED_MTU)
        self._ble.irq(self._irq)

        # Per-chip overlay hook (M3): the BLE MAC is the only chip-varying value
        # read here; NimBLE buffer tuning is the Layer-2 overlay's, not this code.
        self._mac = bytes(self._ble.config("mac")[1])
        self._adv_name = advertised_name(device_id_from_mac(self._mac))

        self._service_uuid = bluetooth.UUID(SERVICE_UUID)
        rx = (bluetooth.UUID(RX_UUID),
              bluetooth.FLAG_WRITE | bluetooth.FLAG_WRITE_NO_RESPONSE)
        tx = (bluetooth.UUID(TX_UUID), bluetooth.FLAG_NOTIFY)
        info = (bluetooth.UUID(INFO_UUID), bluetooth.FLAG_READ)
        service = (self._service_uuid, (rx, tx, info))
        ((self._rx_handle, self._tx_handle, self._info_handle),) = \
            self._ble.gatts_register_services((service,))

        # P7 (hardware-verified): the default ~20-byte GATTS attribute buffer
        # SILENTLY TRUNCATES writes — arm RX for one full MTU-247 write
        # immediately after registration, BEFORE the board is connectable.
        # append=False: one-chunk-one-packet stays the default (the blob
        # reframer is a HIL-evidence contingency only).
        self._ble.gatts_set_buffer(self._rx_handle, PREFERRED_MTU, False)

        self._ble.gatts_write(self._info_handle, self._info_payload)
        self._start_advertising()

    # -- NimBLE wiring internals (HIL-only) --------------------------------

    def _start_advertising(self):
        """Advertise the Service UUID (so scans filter to it, FR-BLE-6) with the
        current name. The name goes in the scan response since one 128-bit UUID
        already fills most of the 31-byte adv packet."""
        adv, resp = _advertising_payloads(self._adv_name, self._service_uuid)
        self._ble.gap_advertise(100_000, adv_data=adv, resp_data=resp)

    def _irq(self, event, data):
        # Module-local NUMERIC event codes only (port spec P7): rp2 modbluetooth
        # exports no `_IRQ_*` attributes, so `bluetooth._IRQ_*` reads raise on
        # device. The ENTIRE dispatch is try/except-wrapped — an exception
        # escaping a BLE irq handler permanently disables it (and on rp2 the
        # scheduled-callback exception would be swallowed silently), so nothing
        # may ever propagate from here.
        try:
            if event == _IRQ_CENTRAL_CONNECT:
                self._conn_handle = data[0]
                self._reset_reassembly()
                if self._on_connect is not None:
                    self._on_connect()
            elif event == _IRQ_CENTRAL_DISCONNECT:
                self._conn_handle = None
                self._mtu = DEFAULT_MTU
                self._reset_reassembly()
                if self._on_disconnect is not None:
                    try:
                        self._on_disconnect()
                    except Exception:
                        pass  # a faulting up-call must not block re-advertising
                self._start_advertising()  # link outlives session (FR-BLE-11)
            elif event == _IRQ_MTU_EXCHANGED:
                self._mtu = data[1]   # FR-BLE-7: accept the negotiated MTU (247)
            elif event == _IRQ_GATTS_WRITE:
                if data[1] == self._rx_handle:
                    self._on_rx(self._ble.gatts_read(self._rx_handle))
            # Unknown event codes are ignored (forward-compatible).
        except Exception:
            pass

    # -- §3.2 byte transport (fragment on TX, reassemble on RX) ------------

    def _reset_reassembly(self):
        self._rx_buf = bytearray()
        self._rx_active = False
        self._rx_next_index = 0

    def _on_rx(self, packet):
        """Reassemble §3.2: strip the 1-byte FRAG_HDR, concatenate FRAGMENT DATA
        from FIRST through LAST (index increasing mod 64), then hand the complete
        §3.1 message up via on_message. CRC/structure validation is pyble_proto's."""
        if not packet:
            return
        hdr = packet[0]
        first = bool(hdr & FRAG_FIRST)
        last = bool(hdr & FRAG_LAST)
        index = hdr & FRAG_INDEX_MASK

        if first:
            self._rx_buf = bytearray()
            self._rx_active = True
            self._rx_next_index = index
        elif not self._rx_active or index != self._rx_next_index:
            self._reset_reassembly()  # gap/out-of-order: drop; app retransmits
            return

        self._rx_buf += packet[1:]
        self._rx_next_index = (index + 1) % FRAG_INDEX_MOD

        if len(self._rx_buf) > RX_MAX:
            # P6: oversize — report ONCE (head carries the §3.1 header bytes so
            # the agent can echo opcode/id in RSP ERANGE), drop the message,
            # and recover on the next FIRST fragment. Trailing fragments of the
            # same message fall into the inactive/gap branch above and stay
            # silent (no further report).
            head = bytes(self._rx_buf[:8])
            self._reset_reassembly()
            if self._on_oversize is not None:
                self._on_oversize(head)
            return

        if last:
            msg = bytes(self._rx_buf)
            self._reset_reassembly()
            if self._on_message is not None:
                self._on_message(msg)


def _fragment(msg, size):
    """Split `msg` into §3.2 packets of at most `size` FRAGMENT-DATA bytes, each
    prefixed with a 1-byte FRAG_HDR (bit7 FIRST, bit6 LAST, bits5..0 index mod 64).
    A zero-length message yields one FIRST+LAST empty packet. Byte-identical to the
    receiver's reassembly (FR-BLE-10)."""
    if size < 1:
        size = 1
    total = len(msg)
    if total == 0:
        yield bytes((FRAG_FIRST | FRAG_LAST | 0,))
        return
    offset = 0
    index = 0
    while offset < total:
        chunk = msg[offset:offset + size]
        offset += size
        hdr = index % FRAG_INDEX_MOD
        if index == 0:
            hdr |= FRAG_FIRST
        if offset >= total:
            hdr |= FRAG_LAST
        yield bytes((hdr,)) + chunk
        index += 1


def _advertising_payloads(name, service_uuid):
    """Build the (adv_data, scan_response) AD-structure blobs: adv carries Flags +
    the Complete 128-bit Service UUID (so scans filter to it, FR-BLE-6); the name
    goes in the scan response. HIL-only — exercised on the ESP32 bench."""
    # Flags: LE General Discoverable + BR/EDR not supported.
    adv = bytes((2, 0x01, 0x06))
    adv += bytes((17, 0x07)) + _uuid128_le(service_uuid)  # Complete 128-bit UUIDs
    name_bytes = name.encode("utf-8")
    resp = bytes((len(name_bytes) + 1, 0x09)) + name_bytes  # Complete Local Name
    return adv, resp


def _uuid128_le(service_uuid):
    """The 16-byte little-endian form of the Service UUID for the AD structure.
    Accepts the canonical string form (host/build time) or a NimBLE UUID whose
    bytes are already the on-air little-endian order (device)."""
    hexstr = str(service_uuid).replace("-", "")
    if len(hexstr) == 32:
        return bytes.fromhex(hexstr)[::-1]
    return bytes(service_uuid)
