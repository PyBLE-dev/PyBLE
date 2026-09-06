#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Host RED for exact-target workspace acquisition hardware guards.

No USB, serial, BLE, flash programming, or physical qualification occurs here.
"""
import importlib.util
import hashlib
import asyncio
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

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

    def test_known_native_application_is_not_mistaken_for_wrong_loader(self):
        self.api("validate_binding")
        application = binding()["application_usb"]
        loader = dict(application, vid=0x303a, pid=0x1001)
        with mock.patch.object(HARDWARE, "_ports", return_value=[application]):
            self.assertFalse(HARDWARE._usb_exact(loader, absent_ok=True, alternate=application))
        wrong = dict(application, serial_number="OTHER-TARGET")
        with mock.patch.object(HARDWARE, "_ports", return_value=[wrong]), self.assertRaises(ValueError):
            HARDWARE._usb_exact(loader, absent_ok=True, alternate=application)

    def test_duplicate_serial_alias_must_be_idle_before_open(self):
        self.api("validate_binding")
        selected = binding()["application_usb"]
        alias = dict(selected, port="/dev/cu.duplicate-test-alias")
        with mock.patch.object(HARDWARE, "_ports", return_value=[selected, alias]), \
             mock.patch.object(HARDWARE.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=b"occupied")) as run:
            with self.assertRaises(ValueError):
                HARDWARE._usb_exact(selected, idle=True)
            self.assertEqual(run.call_args.args[0], ["/usr/sbin/lsof", selected["port"],
                selected["port"].replace("/dev/cu.", "/dev/tty."), alias["port"],
                alias["port"].replace("/dev/cu.", "/dev/tty.")])


class WorkspaceHardwareLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.assertIsNotNone(HARDWARE)
        self.temporary = tempfile.TemporaryDirectory(prefix="pyble-hardware-host-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.backend = HARDWARE.WorkspaceHardware(binding(), repo_root=self.root, candidate_dir=self.root)
        self.backend.work_dir = self.root
        self.backend.kind = "erased-media-first-boot"

    async def test_boot_cannot_precede_complete_pre_read_or_repeat(self):
        self.backend.adapter = SimpleNamespace(boot=mock.AsyncMock(return_value=b"first boot"))
        for phase in ("new", "prepared", "pre-reading", "booted", "observed"):
            self.backend.phase = phase
            with self.subTest(phase=phase), self.assertRaises(ValueError):
                await self.backend.boot()
        self.backend.adapter.boot.assert_not_awaited()
        self.backend.phase = "pre-read"
        self.assertEqual(await self.backend.boot(), b"first boot")
        self.assertEqual(self.backend.phase, "booted")
        with self.assertRaises(ValueError):
            await self.backend.boot()
        self.backend.adapter.boot.assert_awaited_once()

    async def test_failed_actual_read_does_not_authorize_boot(self):
        self.backend.phase = "prepared"
        self.backend.adapter = SimpleNamespace(read_flash=mock.AsyncMock(return_value=b"short"),
                                               boot=mock.AsyncMock())
        with self.assertRaises(ValueError):
            await self.backend.read_media(0x210000, 0xdf0000)
        with self.assertRaises(ValueError):
            await self.backend.boot()
        self.backend.adapter.boot.assert_not_awaited()

    async def test_wrong_transport_or_repeated_observation_never_contacts_runtime(self):
        self.backend.phase = "booted"
        self.backend._ble_command = mock.AsyncMock()
        self.backend._usb_command = mock.AsyncMock()
        for challenge, transport in (("a" * 32, "usb-repl"), ("A" * 32, "pble-run")):
            with self.assertRaises(ValueError):
                await self.backend.observe(challenge, transport)
        self.backend._ble_command.assert_not_awaited()
        self.backend._usb_command.assert_not_awaited()

    async def test_wave_hello_validates_chip_not_board_profile_token(self):
        import _pble_central
        import target_smoke
        self.backend.binding["profile_id"] = "waveshare-esp32-s3-lcd-147b"
        central = SimpleNamespace(send_cmd=mock.AsyncMock(return_value=SimpleNamespace(payload=b"\0")),
                                  disconnect=mock.AsyncMock())
        with mock.patch.object(HARDWARE, "_usb_exact"), \
             mock.patch.object(HARDWARE.importlib.metadata, "version", return_value="3.0.2"), \
             mock.patch.object(_pble_central.PbleCentral, "connect", return_value=central), \
             mock.patch.object(target_smoke, "validate_caps", side_effect=RuntimeError("stop after caps")) as validate:
            with self.assertRaisesRegex(RuntimeError, "stop after caps"):
                await self.backend._ble_command("pass")
            self.assertEqual(validate.call_args.args[1], "esp32-s3")
        central.disconnect.assert_awaited_once()

    async def test_close_never_resets_or_implicitly_boots(self):
        adapter = SimpleNamespace(close=mock.AsyncMock(), boot=mock.AsyncMock())
        self.backend.adapter = adapter
        await self.backend.close()
        await self.backend.close()
        adapter.boot.assert_not_awaited()
        self.assertEqual(self.backend.phase, "closed")

    async def test_raw_repl_reentry_explicitly_exits_previous_raw_mode_without_soft_reset(self):
        writes = []
        class Port:
            def open(self):
                pass
            def close(self):
                pass
            def write(self, raw):
                writes.append(raw)
                raise OSError("stop after entry bytes")
        serial = SimpleNamespace(Serial=lambda **kwargs: Port())
        with mock.patch.dict(sys.modules, {"serial": serial}), \
             mock.patch.object(HARDWARE.importlib.metadata, "version", return_value="3.5"), \
             mock.patch.object(HARDWARE, "_usb_exact"):
            with self.assertRaisesRegex(OSError, "stop after entry bytes"):
                self.backend._usb_command_sync("pass", False)
        self.assertEqual(writes, [b"\x03\x03\x02\x01"])

    async def test_esp_erase_needs_unchanged_candidate_and_verified_full_chip_digest(self):
        validate = mock.Mock(side_effect=ValueError("candidate changed"))
        adapter = HARDWARE._EspAdapter(binding(), self.root, validate)
        adapter._check = mock.Mock()
        adapter.esp = SimpleNamespace(erase_flash=mock.Mock(), flash_md5sum=mock.Mock(return_value="bad"))
        with self.assertRaisesRegex(ValueError, "candidate changed"):
            adapter._erase()
        adapter.esp.erase_flash.assert_not_called()
        validate.side_effect = None
        with self.assertRaisesRegex(ValueError, "complete flash erase"):
            adapter._erase()
        self.assertFalse(adapter.erased)
        adapter.esp.flash_md5sum.assert_called_once_with(0, 0x1000000)

    async def test_esp_write_retains_exact_loader_and_never_adds_force_or_reset_flags(self):
        raw = b"host-only firmware bytes"
        validate = mock.Mock()
        adapter = HARDWARE._EspAdapter(binding(), self.root, validate)
        adapter._check = mock.Mock()
        adapter.erased = True
        adapter.esp = SimpleNamespace(_port=SimpleNamespace(is_open=True),
                                     flash_md5sum=mock.Mock(return_value=hashlib.md5(raw).hexdigest()))
        tool = SimpleNamespace(main=mock.Mock())
        with mock.patch.dict(sys.modules, {"esptool": tool}):
            adapter._write(0, raw, "host-input.bin")
        argv = tool.main.call_args.args[0]
        self.assertEqual(tool.main.call_args.kwargs, {"esp": adapter.esp})
        self.assertEqual(argv[argv.index("--before") + 1], "no_reset_no_sync")
        self.assertEqual(argv[argv.index("--after") + 1], "no_reset_stub")
        self.assertEqual(argv[argv.index("--connect-attempts") + 1], "1")
        self.assertEqual(argv[-2:], ["0x0", str(self.root / "host-input.bin")])
        self.assertNotIn("--force", argv)
        self.assertNotIn("--erase-all", argv)
        self.assertNotIn("--encrypt", argv)
        self.assertEqual(validate.call_count, 2)

    async def test_esp_failed_read_keeps_real_bytes_from_becoming_candidate_evidence(self):
        adapter = HARDWARE._EspAdapter(binding(), self.root, mock.Mock())
        adapter._check = mock.Mock()
        adapter.esp = SimpleNamespace(flash_md5sum=mock.Mock(return_value=hashlib.md5(b"good").hexdigest()),
                                     read_flash=mock.Mock(return_value=b"evil"))
        with self.assertRaisesRegex(ValueError, "actual flash read"):
            adapter._read(0, 4)

    async def test_candidate_byte_change_prevents_esp_write_even_after_successful_erase(self):
        adapter = HARDWARE._EspAdapter(binding(), self.root,
                                      mock.Mock(side_effect=ValueError("changed candidate")))
        adapter._check = mock.Mock()
        adapter.erased = True
        tool = SimpleNamespace(main=mock.Mock())
        with mock.patch.dict(sys.modules, {"esptool": tool}), self.assertRaisesRegex(ValueError, "changed candidate"):
            adapter._write(0, b"new", "unadmitted.bin")
        tool.main.assert_not_called()
        self.assertFalse((self.root / "unadmitted.bin").exists())

    async def test_cancelled_ble_command_bounds_disconnect_even_when_backend_hangs(self):
        import _pble_central
        import target_smoke
        started = asyncio.Event()
        never = asyncio.Event()
        command_count = [0]
        async def send(*args, **kwargs):
            command_count[0] += 1
            if command_count[0] == 2:
                started.set()
                await never.wait()
            return SimpleNamespace(payload=b"\0")
        central = SimpleNamespace(send_cmd=send, disconnect=mock.AsyncMock(side_effect=never.wait),
                                  events=[], confirm_caps_mtu=mock.Mock(), is_connected=True)
        real_wait_for = asyncio.wait_for
        bounded_cleanup = []
        async def bounded(awaitable, timeout):
            bounded_cleanup.append(timeout)
            return await real_wait_for(awaitable, min(timeout, 0.01))
        with mock.patch.object(HARDWARE, "_usb_exact"), \
             mock.patch.object(HARDWARE.importlib.metadata, "version", return_value="3.0.2"), \
             mock.patch.object(_pble_central.PbleCentral, "connect", return_value=central), \
             mock.patch.object(target_smoke, "parse_caps", return_value={"auto_run": "0", "mtu": "247"}), \
             mock.patch.object(target_smoke, "validate_caps"), \
             mock.patch.object(HARDWARE.asyncio, "wait_for", side_effect=bounded):
            task = asyncio.create_task(self.backend._ble_command("pass"))
            await real_wait_for(started.wait(), 0.2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await real_wait_for(task, 0.2)
        self.assertTrue(bounded_cleanup, "BLE teardown never used a bounded wait")
        self.assertTrue(all(0 < seconds <= 5 for seconds in bounded_cleanup))


if __name__ == "__main__":
    unittest.main(verbosity=2)
