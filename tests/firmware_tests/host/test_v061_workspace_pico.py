#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Host-only RED contracts for the guarded RP2350 acquisition adapter."""

import asyncio
import copy
import importlib.util
import inspect
from pathlib import Path
import plistlib
import struct
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[3]
HIL = ROOT / "tests/firmware_tests/hil"
sys.path.insert(0, str(HIL))
SOURCE = HIL / "_v061_workspace_pico.py"
if SOURCE.exists():
    SPEC = importlib.util.spec_from_file_location("_v061_workspace_pico", SOURCE)
    PICO = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(PICO)
else:
    PICO = None


def binding():
    return {
        "schema_version": 1, "profile_id": "rpi-pico2-w",
        "device_id": "0123456789abcdef", "ble_address": "test-physical-pico",
        "application_usb": {"port": "/dev/cu.test-pico", "vid": 0x2E8A, "pid": 5,
                            "serial_number": "0123456789abcdef", "location": "1-1.2",
                            "product": "Pico"},
        "loader_usb": {"port": None, "vid": 0x2E8A, "pid": 15,
                       "serial_number": "0123456789ABCDEF", "location": 0x01120000,
                       "product": "RP2350 Boot"},
        "flash": {"chip": "RP2350", "revision": "A2", "package": "QFN60",
                  "unique_id": "0123456789abcdef", "family_id": 0xE48BFF59,
                  "size_bytes": 0x400000, "secure_boot": False},
        "transfer": {"kind": "picotool"},
    }


DEVICE_INFO = b"""Program Information
 target chip: RP2350
Device Information
 type: RP2350
 revision: A2
 package: QFN60
 chipid: 0x0123456789abcdef
 flash devinfo: 0x0c00
 current cpu: ARM
 secure boot: 0
 flash size: 4096K
"""


def ioreg_tree():
    return {"IORegistryEntryChildren": [{
        "idVendor": 0x2E8A, "idProduct": 15, "locationID": 0x01120000,
        "USB Serial Number": "0123456789ABCDEF", "USB Product Name": "RP2350 Boot",
    }]}


def uf2_image():
    records = []
    for index in range(3):
        extension = index == 0
        block = bytearray(512)
        struct.pack_into("<8I", block, 0, 0x0A324655, 0x9E5D5157,
                         0xA000 if extension else 0x2000,
                         0x10FFFF00 if extension else 0x10000000 + (index - 1) * 256,
                         256, 0 if extension else index - 1, 2,
                         0xE48BFF57 if extension else 0xE48BFF59)
        if extension:
            struct.pack_into("<I", block, 288, 0x9957E304)
        else:
            block[32:288] = bytes([index]) * 256
        struct.pack_into("<I", block, 508, 0x0AB16F30)
        records.append(bytes(block))
    return b"".join(records)


class PicoAdapterGuardTests(unittest.TestCase):
    def api(self, name):
        self.assertIsNotNone(PICO, "[red] maintained Pico workspace adapter missing")
        value = getattr(PICO, name, None)
        self.assertTrue(callable(value), "[red] missing Pico adapter seam: " + name)
        return value

    def test_adapter_exposes_only_explicit_async_loader_operations(self):
        cls = self.api("PicoAdapter")
        for name in ("loader_present", "connect", "erase", "write_image", "write_prefix",
                     "read_flash", "read_install", "boot", "close"):
            self.assertTrue(inspect.iscoroutinefunction(getattr(cls, name, None)), name)

    def test_binding_is_exact_and_detached(self):
        original = binding()
        value = self.api("validate_pico_binding_details")(original)
        self.assertEqual(value, original)
        original["flash"]["size_bytes"] = 1
        self.assertEqual(value["flash"]["size_bytes"], 0x400000)

    def test_wrong_flash_identity_geometry_security_or_boolean_values_are_refused(self):
        validate = self.api("validate_pico_binding_details")
        for field, wrong in (("chip", "RP2040"), ("revision", "A4"), ("package", "QFN80"),
                             ("unique_id", "ffffffffffffffff"), ("size_bytes", 0x200000),
                             ("size_bytes", True), ("secure_boot", 0), ("secure_boot", True),
                             ("family_id", 0xE48BFF56)):
            value = binding()
            value["flash"][field] = wrong
            with self.subTest(field=field, wrong=wrong), self.assertRaises(ValueError):
                validate(value)

    def test_loader_and_application_usb_must_bind_same_unique_id(self):
        validate = self.api("validate_pico_binding_details")
        cases = []
        for which, field, wrong in (("loader_usb", "serial_number", "FFFFFFFFFFFFFFFF"),
                                    ("loader_usb", "port", "/dev/cu.other"),
                                    ("loader_usb", "pid", 5),
                                    ("loader_usb", "location", True),
                                    ("application_usb", "serial_number", "ffffffffffffffff")):
            value = binding()
            value[which][field] = wrong
            cases.append(value)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(value)

    def test_ioreg_accepts_real_dictionary_root_and_equivalent_list_root(self):
        present = self.api("pico_loader_present")
        for tree in (ioreg_tree(), [ioreg_tree()]):
            self.assertTrue(present(plistlib.dumps(tree), binding()))
        self.assertFalse(present(plistlib.dumps({"IORegistryEntryChildren": []}), binding()))

    def test_duplicate_uid_or_changed_usb_location_is_not_silently_selected(self):
        present = self.api("pico_loader_present")
        for change in ("duplicate", "location", "product"):
            tree = ioreg_tree()
            child = tree["IORegistryEntryChildren"][0]
            if change == "duplicate":
                tree["IORegistryEntryChildren"].append(copy.deepcopy(child))
            elif change == "location":
                child["locationID"] += 1
            else:
                child["USB Product Name"] = "Unreviewed device"
            with self.subTest(change=change), self.assertRaises(ValueError):
                present(plistlib.dumps(tree), binding())

    def test_device_info_requires_actual_chip_uid_capacity_and_security(self):
        parse = self.api("parse_pico_device_info")
        value = parse(DEVICE_INFO, binding())
        self.assertEqual(value["unique_id"], binding()["device_id"])
        self.assertEqual(value["size_bytes"], 0x400000)
        self.assertIs(value["secure_boot"], False)
        for before, after in ((b"secure boot: 0", b"secure boot: 1"),
                              (b"flash size: 4096K", b"flash size: 2048K"),
                              (b"revision: A2", b"revision: A4"),
                              (b"0x0123456789abcdef", b"0xffffffffffffffff")):
            with self.subTest(before=before), self.assertRaises(ValueError):
                parse(DEVICE_INFO.replace(before, after), binding())
        with self.assertRaises(ValueError):
            parse(DEVICE_INFO + b" secure boot: 0\n", binding())

    def test_full_flash_read_uses_explicit_range_even_after_blank_erase(self):
        args = self.api("pico_read_argv")(0, 0x400000, Path("private-read.bin"))
        self.assertEqual(args, ["save", "-r", "0x10000000", "0x10400000", "-v",
                                "private-read.bin", "-t", "bin"])
        workspace = self.api("pico_read_argv")(0x180000, 0x280000, Path("workspace.bin"))
        self.assertEqual(workspace[2:4], ["0x10180000", "0x10400000"])
        self.assertNotIn("-a", args)

    def test_invalid_or_xip_confused_read_ranges_are_refused(self):
        fn = self.api("pico_read_argv")
        for offset, size in ((True, 256), (0, True), (-1, 256), (0, 0),
                             (0x400000, 1), (0x3FFFFF, 2), (0x10000000, 256)):
            with self.subTest(offset=offset, size=size), self.assertRaises(ValueError):
                fn(offset, size, Path("read.bin"))

    def test_actual_picotool_sector_padding_is_zero_not_ff(self):
        footprint = self.api("pico_programmed_footprint")(uf2_image())
        self.assertEqual(footprint, b"\1" * 256 + b"\2" * 256 + b"\0" * (4096 - 512))

    def test_prefix_write_is_only_exact_two_workspace_blocks_with_no_execute_flag(self):
        fn = self.api("pico_prefix_argv")
        args = fn(0x180000, b"\0" * 8192, Path("incompatible.bin"))
        self.assertEqual(args, ["load", "-v", "incompatible.bin", "-t", "bin", "-o", "0x10180000"])
        self.assertNotIn("-x", args)
        for offset, value in ((0, b"\0" * 8192), (0x180000, b"\0" * 4096),
                              (0x180000, b"\xff" * 8192), (True, b"\0" * 8192)):
            with self.subTest(offset=offset, size=len(value)), self.assertRaises(ValueError):
                fn(offset, value, Path("prefix.bin"))

    def test_readback_reconstructs_only_actual_payloads_not_uf2_metadata(self):
        image = uf2_image()
        calls = []
        def read(address, size):
            calls.append((address, size))
            return b"x" * size
        raw = self.api("reconstruct_uf2_readback")(image, read)
        self.assertEqual(calls, [(0x10000000, 256), (0x10000100, 256)])
        self.assertEqual(raw[:512], image[:512])
        self.assertEqual(raw[512:544], image[512:544])
        self.assertEqual(raw[544:800], b"x" * 256)
        self.assertNotEqual(raw, image)

    def test_bad_uf2_fails_before_any_physical_reader_call(self):
        fn = self.api("reconstruct_uf2_readback")
        image = uf2_image()
        for invalid in (b"", image[:-1], image[:1024], image[:1024] + image[512:1024]):
            calls = []
            with self.subTest(size=len(invalid)), self.assertRaises(ValueError):
                fn(invalid, lambda *args: calls.append(args))
            self.assertEqual(calls, [])

    def test_short_or_nonbyte_flash_response_is_not_an_install_artifact(self):
        fn = self.api("reconstruct_uf2_readback")
        for raw in (b"short", bytearray(256), None):
            with self.subTest(raw=type(raw).__name__), self.assertRaises(ValueError):
                fn(uf2_image(), lambda *_args: raw)

    def test_image_cannot_be_written_without_verified_full_erase(self):
        cls = self.api("PicoAdapter")
        async def exercise(directory):
            adapter = cls(binding(), repo_root=ROOT, work_dir=directory)
            adapter._run = AsyncMock(return_value=DEVICE_INFO)
            await adapter.connect()
            with self.assertRaises((ValueError, RuntimeError)):
                await adapter.write_image(uf2_image())
            self.assertEqual(adapter._run.await_args_list[0].args[0], ["info", "-a"])
            self.assertEqual(adapter._run.await_count, 1)
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(Path(directory)))

    def test_failed_erased_readback_never_authorizes_image_write(self):
        cls = self.api("PicoAdapter")
        async def exercise(directory):
            adapter = cls(binding(), repo_root=ROOT, work_dir=directory)
            adapter._run = AsyncMock(return_value=DEVICE_INFO)
            await adapter.connect()
            adapter.read_flash = AsyncMock(return_value=b"\0" + b"\xff" * (0x400000 - 1))
            with self.assertRaises((ValueError, RuntimeError)):
                await adapter.erase()
            with self.assertRaises((ValueError, RuntimeError)):
                await adapter.write_image(uf2_image())
            self.assertEqual([item.args[0] for item in adapter._run.await_args_list],
                             [["info", "-a"], ["erase", "-a"]])
            adapter.read_flash.assert_awaited_once_with(0, 0x400000)
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(Path(directory)))

    def test_close_is_idempotent_and_never_implicitly_reboots(self):
        cls = self.api("PicoAdapter")
        async def exercise(directory):
            adapter = cls(binding(), repo_root=ROOT, work_dir=directory)
            adapter._run = AsyncMock()
            await adapter.close()
            await adapter.close()
            adapter._run.assert_not_awaited()
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(Path(directory)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
