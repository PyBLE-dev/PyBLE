# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""A smaller write-fragment size must not falsify negotiated MTU evidence."""
import pathlib
import sys
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'hil'))
from _pble_central import PbleCentral


class Client:
    mtu_size = 247
    def __init__(self):
        self.packets = []
    async def write_gatt_char(self, char, data, response=False):
        self.packets.append(bytes(data))


class FragmentLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_limits_packets_without_changing_actual_mtu(self):
        client = Client()
        c = PbleCentral(client)
        c.confirm_caps_mtu(247)
        c.limit_write_fragmentation(23)
        self.assertEqual(c.backend_mtu, 247)
        self.assertEqual(c._confirmed_caps_mtu, 247)
        self.assertEqual(c.mtu, 23)
        await c._write(bytes(range(40)))
        self.assertEqual([len(p) for p in client.packets], [20, 20, 3])
        with self.assertRaises(ValueError):
            c.confirm_caps_mtu(23)

    async def test_refuses_invalid_or_larger_limits(self):
        c = PbleCentral(Client())
        for value in [True, 22, 248, 23.5]:
            with self.assertRaises(ValueError, msg=str(value)):
                c.limit_write_fragmentation(value)
        c.confirm_caps_mtu(247)
        with self.assertRaises(ValueError):
            c.limit_write_fragmentation(248)


if __name__ == '__main__':
    unittest.main()
