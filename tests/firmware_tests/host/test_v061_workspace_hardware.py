#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Host RED for exact-target workspace acquisition hardware guards.

No USB, serial, BLE, flash programming, or physical qualification occurs here.
"""
import importlib.util
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
HIL = ROOT / "tests/firmware_tests/hil"
sys.path.insert(0, str(HIL))
BACKEND = HIL / "_v061_workspace_hardware.py"
if BACKEND.exists():
    SPEC = importlib.util.spec_from_file_location("_v061_workspace_hardware", BACKEND)
    HARDWARE = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(HARDWARE)
else:
    HARDWARE = None


def binding():
    usb = dict(port="/dev/cu.pyble-test-bridge", vid=0x1A86, pid=0x55D3,
               serial_number="TEST-SERIAL", location="1-1.2", product="Test serial bridge")
    return dict(schema_version=1, profile_id="esp32-s3-n16r8",
                device_id="02:00:00:00:56:44", ble_address="test-ble-address",
                application_usb=usb, loader_usb=dict(usb),
                flash=dict(chip="ESP32-S3", chip_id=9, revision=1,
                           base_mac="02:00:00:00:56:44", jedec_id=0x184068,
                           size_bytes=0x1000000),
                transfer=dict(initial_baud=115200, baud=460800,
                              ram_block_bytes=64, flash_block_bytes=64))


def uf2_image():
    records = []
    for index in range(3):
        block = bytearray(512)
        extension = index == 0
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


class WorkspaceHardwareGuardTests(unittest.TestCase):
    def api(self, name):
        self.assertIsNotNone(HARDWARE, "[red] maintained workspace hardware backend is missing")
        value = getattr(HARDWARE, name, None)
        self.assertTrue(callable(value), "[red] workspace hardware seam missing: " + name)
        return value

    def test_backend_exposes_bounded_async_acquisition_methods(self):
        import inspect
        cls = self.api("WorkspaceHardware")
        for method in ("prepare", "read_media", "boot", "observe", "close"):
            self.assertTrue(inspect.iscoroutinefunction(getattr(cls, method, None)), method)

    def test_exact_private_binding_is_accepted_without_hardware_access(self):
        value = binding()
        self.assertEqual(self.api("validate_binding")(value), value)

    def test_binding_is_detached_from_caller_mutation(self):
        value = binding()
        validated = self.api("validate_binding")(value)
        value["flash"]["size_bytes"] = 1
        self.assertEqual(validated["flash"]["size_bytes"], 0x1000000)

    def test_wrong_profile_geometry_or_family_is_rejected(self):
        validate = self.api("validate_binding")
        for field, wrong in (("size_bytes", 0x400000), ("chip_id", 5), ("chip", "ESP32-C3")):
            value = binding()
            value["flash"][field] = wrong
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(value)

    def test_binding_cannot_substitute_another_device_or_unsafe_endpoint(self):
        validate = self.api("validate_binding")
        cases = []
        value = binding()
        value["device_id"] = "02:00:00:00:00:00"
        cases.append(value)
        value = binding()
        value["loader_usb"]["port"] = "/tmp/owner-file"
        cases.append(value)
        value = binding()
        value["loader_usb"]["port"] = "/dev/../tmp/owner-file"
        cases.append(value)
        value = binding()
        value["transfer"]["shell"] = "arbitrary command"
        cases.append(value)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(value)

    def test_unsafe_or_boolean_transport_geometry_is_rejected(self):
        validate = self.api("validate_binding")
        for field, wrong in (("initial_baud", 9600), ("baud", 4000000),
                             ("ram_block_bytes", True), ("flash_block_bytes", 0)):
            value = binding()
            value["transfer"][field] = wrong
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(value)

    def test_pico_install_readback_substitutes_every_actual_loadable_payload(self):
        image = uf2_image()
        actual = bytes([1]) * 256 + bytes([2]) * 256
        calls = []
        def read(address, size):
            calls.append((address, size))
            offset = address - 0x10000000
            return actual[offset:offset + size]
        result = self.api("reconstruct_uf2_readback")(image, read)
        self.assertEqual(result, image)
        self.assertEqual(calls, [(0x10000000, 256), (0x10000100, 256)])

    def test_corrupt_device_payload_cannot_reuse_the_candidate_hash(self):
        image = uf2_image()
        result = self.api("reconstruct_uf2_readback")(image, lambda _address, size: b"x" * size)
        self.assertNotEqual(result, image)
        self.assertEqual(result[512 + 32:512 + 288], b"x" * 256)
        self.assertEqual(result[1024 + 32:1024 + 288], b"x" * 256)
        self.assertEqual(result[:512], image[:512])  # ignored extension is not flashed

    def test_duplicate_missing_or_reordered_uf2_records_fail_before_read(self):
        image = uf2_image()
        variants = (image[:1024] + image[512:1024], image[:1024],
                    image[:512] + image[1024:] + image[512:1024])
        for invalid in variants:
            called = []
            with self.subTest(size=len(invalid)), self.assertRaises(ValueError):
                self.api("reconstruct_uf2_readback")(invalid, lambda *args: called.append(args))
            self.assertEqual(called, [])

    def test_workspace_overlap_and_wrong_family_fail_before_any_read(self):
        image = uf2_image()
        for field_offset, replacement in ((512 + 12, 0x10180000),
                                          (512 + 28, 0xE48BFF56), (512 + 16, 0)):
            changed = bytearray(image)
            struct.pack_into("<I", changed, field_offset, replacement)
            called = []
            with self.subTest(field=field_offset), self.assertRaises(ValueError):
                self.api("reconstruct_uf2_readback")(bytes(changed), lambda *args: called.append(args))
            self.assertEqual(called, [])

    def test_short_nonbyte_or_failed_physical_read_never_produces_artifact(self):
        image = uf2_image()
        for result in (b"short", bytearray(256), None):
            with self.subTest(type=type(result).__name__), self.assertRaises(ValueError):
                self.api("reconstruct_uf2_readback")(image, lambda _address, _size: result)
        def failed(_address, _size):
            raise OSError("physical read failed")
        with self.assertRaises(OSError):
            self.api("reconstruct_uf2_readback")(image, failed)

    def test_nonblank_precondition_is_explicitly_incompatible_without_full_device_zero_write(self):
        fn = self.api("nonblank_prefix")
        self.assertEqual(fn(4096), b"\x00" * 8192)
        for invalid in (True, 0, 256, 4095, 8192):
            with self.subTest(block_size=invalid), self.assertRaises(ValueError):
                fn(invalid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
