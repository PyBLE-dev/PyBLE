# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Minimal PBLE/1 BLE central for the HIL harness, over `bleak` (CoreBluetooth on
# macOS, BlueZ on Linux). This is TEST/BENCH plumbing owned by
# firmware-test-author — it is NOT firmware and never ships.
#
# It speaks the frozen PBLE/1 wire (protocol.md §2 GATT, §3 framing) via
# _pble_wire: scan filtered to the Service UUID (§2 / SEC-5), request the highest
# MTU the platform allows (app requests 247, §2), subscribe TX-notify, write CMDs
# to RX, reassemble TX notifications into §3.1 frames.
#
# CLEAN-ROOM: only PyBLE-owned UUIDs/names. No proprietary identifiers, no
# telemetry, no off-device transmission (SEC-8) — the harness only talks to the
# board under test.
#
# bleak is a HIL-only dependency: import is deferred so the host-runnable wire
# guard (test_hil_wire) never needs it. `pip install bleak` on the HIL runner.

import asyncio

import _pble_wire as wire

# protocol.md §2 (FROZEN G0) — PyBLE-owned GATT UUID base (ASCII "pybl").
SERVICE_UUID = "7079626c-1ab1-4d50-9e3a-000000000001"
RX_UUID = "7079626c-1ab1-4d50-9e3a-000000000002"   # app -> board (write)
TX_UUID = "7079626c-1ab1-4d50-9e3a-000000000003"   # board -> app (notify)
INFO_UUID = "7079626c-1ab1-4d50-9e3a-000000000004"  # board -> app (read)

REQUESTED_MTU = 247  # §2: the app requests MTU 247
DEFAULT_ATT_MTU = 23  # safe pre-HELLO fragmentation; never certification evidence


class AckCursor:
    """A transfer-scoped view over cumulative FILE_PUT_ACK events.

    PBLE/1 ACK events have id=0 and therefore cannot be correlated by command
    ID.  A fresh cursor is created only after FILE_PUT_BEGIN succeeds.  It
    retains every raw watermark so the bench can reject an impossible/stale
    watermark instead of silently accepting the process-global maximum.
    """

    def __init__(self, central, initial):
        self._central = central
        self._index = len(central._ack_history)
        self.watermark = int(initial)

    def poll(self, *, sent_limit, total, valid_offsets=None):
        history = self._central._ack_history
        while self._index < len(history):
            ack = history[self._index]
            self._index += 1
            if ack is None:
                raise ValueError("FILE_PUT_ACK payload must contain exactly u32")
            if ack < 0 or ack > total or ack > sent_limit:
                raise ValueError(
                    "FILE_PUT_ACK watermark %d is outside sent range 0..%d"
                    % (ack, sent_limit)
                )
            if valid_offsets is not None and ack not in valid_offsets:
                raise ValueError(
                    "FILE_PUT_ACK watermark %d is not a transmitted boundary" % ack
                )
            if ack > self.watermark:
                self.watermark = ack
        return self.watermark


def _require_bleak():
    try:
        import bleak  # noqa: F401
        from bleak import BleakClient, BleakScanner  # noqa: F401
        return bleak
    except Exception as exc:  # pragma: no cover - HIL-only path
        raise RuntimeError(
            "bleak is required for the HIL harness (pip install bleak); "
            "this is a hardware-in-the-loop bench, not a host unit test. (%s)" % exc)


class PbleCentral:
    """One connection to a PyBLE board. Correlates RSPs by frame ID, tracks the
    latest cumulative FILE_PUT_ACK watermark, and buffers async EVTs."""

    def __init__(self, client):
        self._client = client
        self._re = wire.Reassembler()
        self._rsp_by_id = {}
        self._rsp_event = asyncio.Event()
        self._confirmed_caps_mtu = None
        self._ack_history = []
        self.last_ack = 0            # highest FILE_PUT_ACK{ack_offset} seen
        self.events = []             # non-RSP, non-ACK frames (RUN_STATE, CONSOLE_*)
        self.rx_frames = 0

    # ---- lifecycle -----------------------------------------------------------
    @classmethod
    async def scan(cls, timeout=8.0):
        """Return (address, name) tuples of boards advertising the PyBLE service.
        Filtered to the Service UUID — never a raw device list (§2 / SEC-5)."""
        bleak = _require_bleak()
        from bleak import BleakScanner
        found = await BleakScanner.discover(timeout=timeout, service_uuids=[SERVICE_UUID])
        return [(d.address, d.name) for d in found]

    @classmethod
    async def connect(cls, address, timeout=20.0):
        bleak = _require_bleak()
        from bleak import BleakClient
        client = BleakClient(address, timeout=timeout)
        await client.connect()
        self = cls(client)
        await client.start_notify(TX_UUID, self._on_notify)
        return self

    async def disconnect(self):
        try:
            await self._client.stop_notify(TX_UUID)
        except Exception:
            pass
        await self._client.disconnect()

    @property
    def backend_mtu(self):
        """Return only an MTU actually exposed by the BLE backend.

        ``None`` is deliberately preserved.  In particular, REQUESTED_MTU is
        never substituted here: a requested or guessed value is not OI-1
        certification evidence.
        """
        try:
            value = getattr(self._client, "mtu_size", None)
        except Exception:
            return None
        if isinstance(value, bool):
            return None
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        return value if value >= DEFAULT_ATT_MTU else None

    @property
    def mtu(self):
        """MTU used for fragmentation, not an evidence field.

        HELLO is safely fragmented at the mandatory ATT default of 23.  Only
        after the device's HELLO caps have been validated may the bench use the
        reported negotiated value for subsequent writes.
        """
        return self._confirmed_caps_mtu or DEFAULT_ATT_MTU

    def confirm_caps_mtu(self, mtu):
        """Enable post-HELLO fragmentation at ``mtu``.

        If the backend exposes a negotiated ATT MTU it must agree.  An unknown
        backend value remains unknown, while HELLO stays the authoritative
        device-side value.
        """
        if isinstance(mtu, bool):
            raise ValueError("HELLO MTU must be an integer")
        try:
            mtu = int(mtu)
        except (TypeError, ValueError) as exc:
            raise ValueError("HELLO MTU must be an integer") from exc
        if mtu < DEFAULT_ATT_MTU:
            raise ValueError("HELLO MTU is below the ATT default")
        backend = self.backend_mtu
        if backend is not None and backend != mtu:
            raise ValueError(
                "backend ATT MTU %d disagrees with HELLO mtu=%d" % (backend, mtu)
            )
        self._confirmed_caps_mtu = mtu

    @property
    def is_connected(self):
        value = getattr(self._client, "is_connected", True)
        return bool(value)

    def event_cursor(self):
        return len(self.events)

    def events_since(self, cursor):
        if cursor < 0 or cursor > len(self.events):
            raise ValueError("invalid event cursor")
        return len(self.events), self.events[cursor:]

    def begin_ack_scope(self, initial=0):
        return AckCursor(self, initial)

    async def read_info(self):
        """§2: an INFO read returns the DEVICE_INFO payload (opaque here — the
        caps byte layout is not byte-frozen, so the bench does not parse it)."""
        return bytes(await self._client.read_gatt_char(INFO_UUID))

    # ---- notify path ---------------------------------------------------------
    def _on_notify(self, _char, data):
        frame = None
        try:
            frame = self._re.feed(bytes(data))
        except ValueError:
            # A CRC/format-bad reassembly: drop (the board would answer ECRC).
            return
        if frame is None:
            return
        self.rx_frames += 1
        if frame.type == wire.RSP:
            self._rsp_by_id[frame.id] = frame
            self._rsp_event.set()
        elif frame.opcode == wire.OP_FILE_PUT_ACK:
            if len(frame.payload) == 4:
                ack = int.from_bytes(frame.payload, "little")
                self._ack_history.append(ack)
                if ack > self.last_ack:
                    self.last_ack = ack
            else:
                # Preserve the malformed event in the transfer scope so the
                # sender fails explicitly instead of timing out or certifying it.
                self._ack_history.append(None)
        else:
            self.events.append(frame)

    # ---- request / response --------------------------------------------------
    async def _write(self, frame_bytes):
        for pkt in wire.fragment(frame_bytes, self.mtu):
            # Write-Without-Response for throughput (RX supports it, §2).
            await self._client.write_gatt_char(RX_UUID, pkt, response=False)

    async def send_cmd_no_rsp(self, opcode, id_, payload=b""):
        await self._write(wire.encode(wire.CMD, opcode, id_, payload))

    async def send_cmd(self, opcode, id_, payload=b"", timeout=10.0):
        """Send a CMD and await the matching RSP (same ID). Returns a Frame."""
        self._rsp_by_id.pop(id_, None)
        await self._write(wire.encode(wire.CMD, opcode, id_, payload))
        return await self._await_rsp(id_, timeout)

    async def _await_rsp(self, id_, timeout):
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while id_ not in self._rsp_by_id:
            self._rsp_event.clear()
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError("no RSP for id %d within %.1fs" % (id_, timeout))
            try:
                await asyncio.wait_for(self._rsp_event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                raise asyncio.TimeoutError("no RSP for id %d within %.1fs" % (id_, timeout))
        return self._rsp_by_id.pop(id_)


def rsp_status(frame):
    """RSP payload byte 0 is the frozen §8 status (handler ABI: [status][extra])."""
    return frame.payload[0] if frame.payload else wire.ST_EINTERNAL


def status_name(code):
    return wire.STATUS_NAME.get(code, "0x%02x" % code)
