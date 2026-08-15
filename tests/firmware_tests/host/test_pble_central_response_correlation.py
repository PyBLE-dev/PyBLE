# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Host-only RED for exact PBLE/1 HIL-central response correlation."""

import asyncio
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
HIL_DIR = HERE.parent / "hil"
sys.path.insert(0, str(HIL_DIR))

import _pble_central as central_module  # noqa: E402
import _pble_wire as wire  # noqa: E402


class _FakeBleakClient:
    is_connected = True

    def __init__(self, on_write):
        self._on_write = on_write

    async def write_gatt_char(self, _uuid, _packet, response):
        if not response:
            raise AssertionError("response-bearing commands require Write")
        await self._on_write()


def _deliver(central, frame):
    encoded = wire.encode(frame.type, frame.opcode, frame.id, frame.payload)
    for fragment in wire.fragment(encoded, central_module.DEFAULT_ATT_MTU):
        central._on_notify(None, fragment)


def _rsp(opcode, request_id, marker):
    return wire.Frame(
        wire.RSP,
        opcode,
        request_id,
        bytes((wire.ST_OK, marker)),
    )


class ExactResponseCorrelationTest(unittest.IsolatedAsyncioTestCase):
    async def _send_with_order(self, opcode, request_id, frames):
        central = None

        async def on_write():
            for frame in frames:
                _deliver(central, frame)

        central = central_module.PbleCentral(_FakeBleakClient(on_write))
        response = await central.send_cmd(
            opcode,
            request_id,
            timeout=0.1,
        )
        return response

    async def test_wrong_then_exact_same_id_returns_the_exact_response(self):
        request_id = 101
        exact = _rsp(wire.OP_RUN, request_id, 0x11)
        wrong = _rsp(wire.OP_HELLO, request_id, 0x22)

        observed = await self._send_with_order(
            wire.OP_RUN,
            request_id,
            (wrong, exact),
        )

        self.assertEqual(observed.opcode, wire.OP_RUN)
        self.assertEqual(observed.payload, exact.payload)

    async def test_exact_then_wrong_same_id_cannot_overwrite_the_exact_response(self):
        request_id = 102
        exact = _rsp(wire.OP_RUN, request_id, 0x33)
        wrong = _rsp(wire.OP_HELLO, request_id, 0x44)

        observed = await self._send_with_order(
            wire.OP_RUN,
            request_id,
            (exact, wrong),
        )

        self.assertEqual(observed.opcode, wire.OP_RUN)
        self.assertEqual(observed.payload, exact.payload)

    async def test_non_rsp_nonzero_id_cannot_hide_exact_in_either_order(self):
        request_id = 103
        exact = _rsp(wire.OP_RUN, request_id, 0x55)
        unrelated = wire.Frame(wire.CMD, wire.OP_RUN, request_id, b"bad")

        for frames in ((unrelated, exact), (exact, unrelated)):
            with self.subTest(order=tuple(frame.type for frame in frames)):
                observed = await self._send_with_order(
                    wire.OP_RUN,
                    request_id,
                    frames,
                )
                self.assertEqual(observed.opcode, wire.OP_RUN)
                self.assertEqual(observed.payload, exact.payload)

    async def test_reused_id_stale_prior_opcode_cannot_hide_new_response(self):
        request_id = 104
        write_count = 0
        central = None
        old_exact = _rsp(wire.OP_HELLO, request_id, 0x66)
        new_exact = _rsp(wire.OP_RUN, request_id, 0x77)
        stale_old = _rsp(wire.OP_HELLO, request_id, 0x88)

        async def on_write():
            nonlocal write_count
            write_count += 1
            if write_count == 1:
                _deliver(central, old_exact)
            else:
                _deliver(central, new_exact)
                _deliver(central, stale_old)

        central = central_module.PbleCentral(_FakeBleakClient(on_write))
        old_observed = await central.send_cmd(
            wire.OP_HELLO,
            request_id,
            timeout=0.1,
        )
        new_observed = await central.send_cmd(
            wire.OP_RUN,
            request_id,
            timeout=0.1,
        )

        self.assertEqual(old_observed.payload, old_exact.payload)
        self.assertEqual(new_observed.opcode, wire.OP_RUN)
        self.assertEqual(new_observed.payload, new_exact.payload)

    async def test_on_time_exact_arrival_survives_late_wrong_response(self):
        request_id = 105

        async def on_write():
            raise AssertionError("direct response-wait test does not write")

        central = central_module.PbleCentral(_FakeBleakClient(on_write))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 0.02
        exact = _rsp(wire.OP_RUN, request_id, 0x99)
        _deliver(central, exact)
        await asyncio.sleep(0.03)
        _deliver(central, _rsp(wire.OP_HELLO, request_id, 0xAA))

        observed = await central._await_rsp(
            wire.OP_RUN,
            request_id,
            0.02,
            deadline=deadline,
        )

        self.assertEqual(observed.opcode, wire.OP_RUN)
        self.assertEqual(observed.payload, exact.payload)


if __name__ == "__main__":
    unittest.main()
