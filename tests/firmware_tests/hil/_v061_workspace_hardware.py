# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Exact-target, disposable-board workspace acquisition hardware.

This module is not a general installer. It has no target discovery fallback,
shell passthrough, write retry, or implicit runtime boot on failure/close.
The collector owns source binding, chronology, and publication. All temporary
hardware inputs and transcripts remain in an ignored private directory.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import tempfile
import threading
import time


_ESP = {
    "esp32-4mb": ("ESP32", 0, 0x400000, 0x1000, "esp32"),
    "esp32-c3-4mb": ("ESP32-C3", 5, 0x400000, 0, "esp32c3"),
    "esp32-s3-n16r8": ("ESP32-S3", 9, 0x1000000, 0, "esp32s3"),
    "waveshare-esp32-s3-lcd-147b": ("ESP32-S3", 9, 0x1000000, 0, "esp32s3"),
}
_MEDIA = {
    "esp32-4mb": (0x200000, 0x200000),
    "esp32-c3-4mb": (0x200000, 0x200000),
    "esp32-s3-n16r8": (0x210000, 0xDF0000),
    "waveshare-esp32-s3-lcd-147b": (0x210000, 0xDF0000),
    "rpi-pico2-w": (0x180000, 0x280000),
}
_KINDS = ("erased-media-first-boot", "nonblank-media-refusal")
_USB_KEYS = {"port", "vid", "pid", "serial_number", "location", "product"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _text(value, maximum=128):
    return (type(value) is str and 0 < len(value) <= maximum
            and all(32 <= ord(char) < 127 for char in value))


def _pico_module():
    path = Path(__file__).with_name("_v061_workspace_pico.py")
    spec = importlib.util.spec_from_file_location("pyble_workspace_pico_adapter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_binding(value):
    """Validate explicit private facts without opening any hardware."""
    _require(type(value) is dict and set(value) == {
        "schema_version", "profile_id", "device_id", "ble_address",
        "application_usb", "loader_usb", "flash", "transfer"}, "binding keys changed")
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1,
             "binding schema changed")
    profile = value["profile_id"]
    _require(type(profile) is str and profile in _MEDIA, "unsupported physical profile")
    _require(_text(value["device_id"]) and _text(value["ble_address"]), "invalid board identity")
    for key in ("application_usb", "loader_usb"):
        usb = value[key]
        _require(type(usb) is dict and set(usb) == _USB_KEYS, "USB binding keys changed")
        _require(_integer(usb["vid"], 1, 65535) and _integer(usb["pid"], 1, 65535),
                 "invalid USB VID/PID")
        _require(usb["serial_number"] is None or _text(usb["serial_number"]), "invalid USB serial")
        _require(_text(usb["product"]), "missing USB product")
        if profile == "rpi-pico2-w" and key == "loader_usb":
            _require(usb["port"] is None and _integer(usb["location"], 1, 0xffffffff),
                     "Pico loader requires an exact USB location, not a serial endpoint")
        else:
            _require(type(usb["port"]) is str
                     and re.fullmatch(r"/dev/cu\.[A-Za-z0-9_-]+", usb["port"]) is not None,
                     "unsafe serial endpoint")
            _require(_text(usb["location"]), "missing exact USB topology")
    flash = value["flash"]
    transfer = value["transfer"]
    if profile == "rpi-pico2-w":
        _pico_module().validate_pico_binding_details(value)
    else:
        _require(type(flash) is dict and set(flash) == {
            "chip", "chip_id", "revision", "base_mac", "jedec_id", "size_bytes"},
            "ESP flash identity keys changed")
        chip, chip_id, size, _offset, _tool_chip = _ESP[profile]
        _require(flash["chip"] == chip and type(flash["chip_id"]) is int
                 and flash["chip_id"] == chip_id and type(flash["size_bytes"]) is int
                 and flash["size_bytes"] == size, "wrong profile family or flash geometry")
        _require(_integer(flash["revision"], 0, 999)
                 and _integer(flash["jedec_id"], 1, 0xffffff), "invalid ROM revision or JEDEC ID")
        _require(type(flash["base_mac"]) is str
                 and re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", flash["base_mac"])
                 and value["device_id"] == flash["base_mac"], "wrong exact physical MAC")
        # The capacity byte is not replaced by the configured partition size.
        _require(1 << ((flash["jedec_id"] >> 16) & 255) == size,
                 "JEDEC capacity disagrees with admitted flash size")
        _require(type(transfer) is dict and set(transfer) == {
            "initial_baud", "baud", "ram_block_bytes", "flash_block_bytes"},
            "transport keys changed")
        _require(type(transfer["initial_baud"]) is int and transfer["initial_baud"] == 115200
                 and type(transfer["baud"]) is int and transfer["baud"] in (115200, 460800),
                 "unreviewed serial baud")
        for field in ("ram_block_bytes", "flash_block_bytes"):
            _require(type(transfer[field]) is int and transfer[field] in (64, 1024, 4096),
                     "unreviewed serial block geometry")
        if profile != "waveshare-esp32-s3-lcd-147b":
            _require(value["loader_usb"] == value["application_usb"],
                     "serial bridge identity cannot change across boot")
    return copy.deepcopy(value)


def nonblank_prefix(block_size):
    _require(type(block_size) is int and block_size == 4096, "unsupported workspace block size")
    return b"\0" * (2 * block_size)


def reconstruct_uf2_readback(image, read):
    from _v061_workspace_pico import reconstruct_uf2_readback as reconstruct
    return reconstruct(image, read)


def _stable_bytes(path, maximum=32 * 1024 * 1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                 and 0 <= before.st_size <= maximum, "unsafe hardware input")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    current = os.stat(path, follow_symlinks=False)
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    _require(identity(before) == identity(after) == identity(current)
             and len(raw) == before.st_size, "hardware input changed during read")
    return raw


def _save(path, raw):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _require(_stable_bytes(path) == raw, "retained hardware input changed")


def _ports():
    from serial.tools import list_ports
    return [{"port": item.device, "vid": item.vid, "pid": item.pid,
             "serial_number": item.serial_number, "location": item.location,
             "product": item.product} for item in list_ports.comports()]


def _usb_exact(expected, *, idle=False, absent_ok=False, alternate=None):
    ports = _ports()
    selected = [item for item in ports if item["port"] == expected["port"]]
    if absent_ok and (not selected or (alternate is not None and selected == [alternate])):
        return False
    _require(selected == [expected], "exact USB endpoint changed")
    if idle:
        aliases = [item["port"] for item in ports
                   if all(item[key] == expected[key] for key in _USB_KEYS - {"port"})]
        endpoints = []
        for alias in aliases:
            endpoints.extend((alias, alias.replace("/dev/cu.", "/dev/tty.")))
        result = subprocess.run(["/usr/sbin/lsof", *endpoints], capture_output=True, timeout=10)
        _require(result.returncode == 1 and not result.stdout, "USB endpoint or duplicate alias is occupied")
    return True


class _EspAdapter:
    """One retained loader session per phase, with no automatic write retry."""

    def __init__(self, binding, work_dir, validate_candidate):
        self.binding = binding
        self.work_dir = work_dir
        self.validate_candidate = validate_candidate
        self.esp = None
        self.cancelled = threading.Event()
        self.erased = False
        self.closed = False
        self.sequence = 0

    def _check(self):
        _require(not self.cancelled.is_set() and not self.closed, "hardware operation was cancelled")
        _usb_exact(self.binding["loader_usb"])

    def _record(self, name, **facts):
        self.sequence += 1
        _save(self.work_dir / ("esp-%03d-%s.json" % (self.sequence, name)),
              (json.dumps({"event": name, "monotonic_ns": time.monotonic_ns(), **facts},
                          sort_keys=True) + "\n").encode())

    async def _call(self, function, *args):
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            self.cancelled.set()
            if self.esp is not None:
                self.esp._port.close()
            # Closing the serial descriptor interrupts reads; never leave a
            # detached worker that could continue to the next destructive step.
            try:
                await asyncio.wait_for(asyncio.shield(task), 15)
            except (Exception, asyncio.CancelledError):
                pass
            raise

    async def loader_present(self):
        return await self._call(_usb_exact, self.binding["loader_usb"])

    def _connect(self):
        from esptool.config import load_config_file
        from esptool.targets import CHIP_DEFS
        _require(importlib.metadata.version("esptool") == "4.12.0"
                 and importlib.metadata.version("pyserial") == "3.5", "unreviewed serial tool versions")
        _require(not any(key.startswith("ESPTOOL_") for key in os.environ)
                 and load_config_file()[1] is None, "custom esptool configuration is not admitted")
        self._check()
        _usb_exact(self.binding["loader_usb"], idle=True)
        transfer = self.binding["transfer"]
        mode = "no_reset" if self.binding["profile_id"] == "waveshare-esp32-s3-lcd-147b" else "default_reset"
        # Bind the expected ROM class and retain its open handle before the
        # one connection attempt. Automatic chip detection has an internal
        # reconnect fallback even when its connect_attempts argument is one.
        tool_chip = _ESP[self.binding["profile_id"]][4]
        esp = CHIP_DEFS[tool_chip](self.binding["loader_usb"]["port"], transfer["initial_baud"])
        self.esp = esp
        esp.connect(mode, attempts=1, detecting=True)
        self._check()
        _require(not esp.IS_STUB and not esp.sync_stub_detected, "unexpected pre-existing stub")
        expected = self.binding["flash"]
        if expected["chip_id"] == 0:
            # This legacy ROM does not support GET_SECURITY_INFO. Its actual
            # magic read, followed by eFuse security checks below, is required.
            magic = esp.read_reg(esp.CHIP_DETECT_MAGIC_REG_ADDR)
            _require(magic == 0x00F01D83 and esp.IMAGE_CHIP_ID == 0,
                     "wrong classic ROM magic")
            rom_detection = {"magic": magic}
        else:
            chip_id = esp.get_chip_id()
            _require(type(chip_id) is int and chip_id == expected["chip_id"], "wrong actual ROM chip ID")
            info = esp.get_security_info()
            esp.secure_download_mode = info["parsed_flags"]["SECURE_DOWNLOAD_ENABLE"]
            rom_detection = {"chip_id": chip_id}
        actual = {"chip": esp.CHIP_NAME, "chip_id": esp.IMAGE_CHIP_ID,
                  "revision": esp.get_chip_revision(), "base_mac": bytes(esp.read_mac()).hex(":")}
        _require(all(actual[key] == expected[key] for key in actual), "wrong ROM chip identity")
        _require(not esp.secure_download_mode and not esp.get_secure_boot_enabled()
                 and not esp.get_flash_encryption_enabled(), "secure target is not disposable-test eligible")
        esp._post_connect()
        esp.flash_spi_attach(0)
        flash_id = esp.flash_id()
        _require(flash_id == expected["jedec_id"]
                 and 1 << ((flash_id >> 16) & 255) == expected["size_bytes"], "physical flash geometry changed")
        self._record("rom-identity", **actual, jedec_id=flash_id,
                     flash_bytes=expected["size_bytes"], security_modes_disabled=True,
                     actual_rom_detection=rom_detection)
        esp.ESP_RAM_BLOCK = transfer["ram_block_bytes"]
        self.esp = esp.run_stub()
        _require(self.esp.IS_STUB, "RAM stub did not start")
        self.esp.flash_set_parameters(expected["size_bytes"])
        self.esp.change_baud(transfer["baud"])
        self.esp.FLASH_WRITE_SIZE = transfer["flash_block_bytes"]
        self.esp.WRITE_FLASH_ATTEMPTS = 1
        self._check()

    async def connect(self):
        _require(self.esp is None, "loader session already open")
        await self._call(self._connect)

    def _erase(self):
        self._check()
        self.validate_candidate()
        self._record("erase-start")
        self.esp.erase_flash()
        self._check()
        size = self.binding["flash"]["size_bytes"]
        digest = self.esp.flash_md5sum(0, size).lower()
        _require(digest == hashlib.md5(b"\xff" * size).hexdigest(), "complete flash erase was not verified")
        self.erased = True
        self._record("erase-verified", size_bytes=size, device_md5=digest)

    async def erase(self):
        await self._call(self._erase)

    def _write(self, offset, raw, name):
        import esptool
        self._check()
        _require(self.erased, "write requires a verified complete erase in this retained session")
        self.validate_candidate()
        path = self.work_dir / name
        _save(path, raw)
        chip = _ESP[self.binding["profile_id"]][4]
        argv = ["--chip", chip, "--port", self.binding["loader_usb"]["port"],
                "--baud", str(self.binding["transfer"]["baud"]),
                "--before", "no_reset_no_sync", "--after", "no_reset_stub", "--no-stub",
                "--connect-attempts", "1", "write_flash", "--flash_mode", "keep",
                "--flash_freq", "keep", "--flash_size", "keep", "--compress", hex(offset), str(path)]
        self._record("write-start", offset=offset, size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), argv=argv)
        port = self.esp._port
        self.validate_candidate()
        self._check()
        _require(_stable_bytes(path) == raw, "private install input changed immediately before write")
        esptool.main(argv, esp=self.esp)
        _require(self.esp._port is port and port.is_open, "write reconnected or closed the loader")
        self._check()
        _require(self.esp.flash_md5sum(offset, len(raw)).lower() == hashlib.md5(raw).hexdigest(),
                 "written bytes failed device MD5 verification")
        self._record("write-verified", offset=offset, size_bytes=len(raw))

    async def write_image(self, raw):
        await self._call(self._write, _ESP[self.binding["profile_id"]][3], raw, "firmware-input.bin")

    async def write_prefix(self, offset, raw):
        _require(offset == _MEDIA[self.binding["profile_id"]][0]
                 and raw == nonblank_prefix(4096), "unsafe nonblank precondition write")
        await self._call(self._write, offset, raw, "incompatible-prefix.bin")

    def _read(self, offset, size):
        self._check()
        _require(_integer(offset, 0, self.binding["flash"]["size_bytes"])
                 and _integer(size, 1, self.binding["flash"]["size_bytes"] - offset), "flash read outside physical bounds")
        before = self.esp.flash_md5sum(offset, size).lower()
        last = [time.monotonic()]
        def progress(done, total):
            _require(not self.cancelled.is_set(), "physical flash read cancelled")
            if time.monotonic() - last[0] >= 20 or done == total:
                self._check()
                print("Workspace physical flash read: %d/%d bytes" % (done, total), flush=True)
                last[0] = time.monotonic()
        raw = self.esp.read_flash(offset, size, progress)
        self._check()
        after = self.esp.flash_md5sum(offset, size).lower()
        _require(type(raw) is bytes and len(raw) == size
                 and hashlib.md5(raw).hexdigest() == before == after,
                 "actual flash read was incomplete or changed during acquisition")
        self._record("read-verified", offset=offset, size_bytes=size,
                     sha256=hashlib.sha256(raw).hexdigest(), device_md5=after)
        return raw

    async def read_flash(self, offset, size):
        return await self._call(self._read, offset, size)

    async def read_install(self, raw):
        return await self.read_flash(_ESP[self.binding["profile_id"]][3], len(raw))

    def _boot(self):
        self._check()
        self._record("first-runtime-reset-start")
        if self.binding["profile_id"] != "waveshare-esp32-s3-lcd-147b":
            self.esp.change_baud(115200)
        self.esp.hard_reset()
        # One reset only. The bridge remains open with both controls released
        # while capturing this very first boot; native USB may disappear.
        if self.binding["profile_id"] == "waveshare-esp32-s3-lcd-147b":
            self.esp._port.close()
            self.esp = None
            return b""
        port = self.esp._port
        port.dtr = False
        port.rts = False
        port.baudrate = 115200
        port.timeout = 0.2
        raw = bytearray()
        until = time.monotonic() + 6
        while time.monotonic() < until:
            raw.extend(port.read(4096))
            _require(len(raw) <= 128 * 1024, "boot transcript exceeded its bound")
        port.close()
        self.esp = None
        return bytes(raw)

    async def boot(self):
        return await self._call(self._boot)

    async def close(self):
        if self.esp is not None:
            self.esp._port.close()
            self.esp = None
        self.closed = True


class WorkspaceHardware:
    """Strict prepare → pre-read → boot → observe → post-read lifecycle."""

    def __init__(self, private_binding, *, repo_root, candidate_dir):
        self.binding = validate_binding(private_binding)
        self.repo_root = Path(repo_root)
        self.candidate_dir = Path(candidate_dir)
        self.work_dir = None
        self.adapter = None
        self.candidate = None
        self.image = None
        self.kind = None
        self.phase = "new"
        self._serial = None
        self._serial_cancelled = threading.Event()

    def _candidate_bytes(self):
        # Reopen the release AND image with the same maintained candidate
        # validation immediately before every erase/write. Hash equality alone
        # does not excuse a replacement inode or changed release descriptor.
        from v061_workspace_acquire import gate
        current = gate._candidate_snapshot(self.candidate_dir, self.binding["profile_id"])
        _require(all(current[key] == self.candidate[key] for key in current), "candidate snapshot changed")
        raw = _stable_bytes(current["artifact"])
        _require(hashlib.sha256(raw).hexdigest() == current["install_sha256"], "candidate bytes changed")
        if self.image is not None:
            _require(raw == self.image, "candidate changed after preparation began")
        if self.binding["profile_id"] in _ESP:
            release = json.loads(_stable_bytes(self.candidate_dir / "release.json"))
            matches = [row for row in release["profiles"] if row["id"] == self.binding["profile_id"]]
            _require(len(matches) == 1 and type(matches[0]["install"].get("offset")) is int
                     and matches[0]["install"]["offset"] == _ESP[self.binding["profile_id"]][3],
                     "candidate install offset changed")
        return raw

    def _validate_esp_image(self, raw):
        profile = self.binding["profile_id"]
        _chip, chip_id, _size, base, _tool = _ESP[profile]
        start, _length = _MEDIA[profile]
        _require(0x10000 < len(raw) < start - base and raw[0] == 0xe9
                 and int.from_bytes(raw[12:14], "little") == chip_id, "candidate image family or footprint changed")
        table = raw[0x8000 - base:0x8c00 - base]
        entries = []
        for offset in range(0, len(table), 32):
            entry = table[offset:offset + 32]
            if entry[:2] == b"\xaa\x50":
                _magic, kind, subtype, address, size, label, flags = struct.unpack("<HBBII16sI", entry)
                if label.rstrip(b"\0") == b"vfs":
                    entries.append((kind, subtype, address, size, flags))
        _require(entries == [(1, 0x81, *_MEDIA[profile], 0)], "candidate workspace partition geometry changed")

    def _new_work_dir(self):
        from v061_workspace_acquire import gate
        local = self.repo_root / "local"
        local.mkdir(mode=0o700, exist_ok=True)
        chain = gate._open_directory_chain(local, label="private hardware workspace")
        try:
            self.work_dir = Path(tempfile.mkdtemp(prefix="workspace-hardware-", dir=local))
            gate._verify_directory_chain(chain, "private hardware workspace")
        finally:
            gate._close_directory_chain(chain)
        _save(self.work_dir / "binding.json", (json.dumps(self.binding, sort_keys=True) + "\n").encode())
        print("Retained private hardware evidence: %s" % self.work_dir, flush=True)

    async def _native_loader_entry(self, *, refusal=False):
        if self.binding["profile_id"] == "rpi-pico2-w":
            if await self.adapter.loader_present():
                return
        elif await asyncio.to_thread(_usb_exact, self.binding["loader_usb"], absent_ok=True,
                                     alternate=self.binding["application_usb"]):
            return
        _usb_exact(self.binding["application_usb"], idle=True)
        if refusal:
            await self._usb_command("import machine,time\ntime.sleep_ms(350)\nmachine.bootloader()", bootloader=True)
        else:
            await self._ble_command("import machine,time\ntime.sleep_ms(350)\nmachine.bootloader()", bootloader=True)
        until = time.monotonic() + 15
        while time.monotonic() < until:
            if self.binding["profile_id"] == "rpi-pico2-w":
                if await self.adapter.loader_present():
                    return
            elif await asyncio.to_thread(_usb_exact, self.binding["loader_usb"], absent_ok=True,
                                         alternate=self.binding["application_usb"]):
                return
            await asyncio.sleep(0.2)
        raise TimeoutError("exact native-USB loader did not appear")

    async def prepare(self, candidate_snapshot, profile_id, kind):
        _require(self.phase == "new" and profile_id == self.binding["profile_id"]
                 and kind in _KINDS, "invalid or repeated hardware preparation")
        self.phase = "preparing"
        self.candidate = dict(candidate_snapshot)
        self.kind = kind
        self.image = self._candidate_bytes()
        if profile_id in _ESP:
            self._validate_esp_image(self.image)
        else:
            # Validate every UF2 record before any hardware access.
            from _pble_bench import _reconstruct_rp2350_uf2
            _require(len(_reconstruct_rp2350_uf2(self.image)) <= _MEDIA[profile_id][0],
                     "candidate UF2 overlaps workspace")
        self._new_work_dir()
        if profile_id == "rpi-pico2-w":
            from _v061_workspace_pico import PicoAdapter
            self.adapter = PicoAdapter(self.binding, repo_root=self.repo_root, work_dir=self.work_dir)
        else:
            self.adapter = _EspAdapter(self.binding, self.work_dir, self._candidate_bytes)
        if profile_id in ("rpi-pico2-w", "waveshare-esp32-s3-lcd-147b"):
            await self._native_loader_entry()
        await self.adapter.connect()
        self._candidate_bytes()
        await self.adapter.erase()
        self._candidate_bytes()
        await self.adapter.write_image(self.image)
        actual = await self.adapter.read_install(self.image)
        _require(type(actual) is bytes and actual == self.image, "physical installed candidate differs")
        if kind == _KINDS[1]:
            self._candidate_bytes()
            await self.adapter.write_prefix(_MEDIA[profile_id][0], nonblank_prefix(4096))
        self.phase = "prepared"
        return {key: self.binding[key] for key in ("device_id", "ble_address")}, actual

    async def read_media(self, offset, size):
        _require((offset, size) == _MEDIA[self.binding["profile_id"]], "wrong full workspace read geometry")
        _require(self.phase in ("prepared", "observed"), "workspace read is out of order")
        post = self.phase == "observed"
        self.phase = "post-reading" if post else "pre-reading"
        if post:
            if self.binding["profile_id"] in ("rpi-pico2-w", "waveshare-esp32-s3-lcd-147b"):
                await self._native_loader_entry(refusal=self.kind == _KINDS[1])
            await self.adapter.connect()
        raw = await self.adapter.read_flash(offset, size)
        _require(type(raw) is bytes and len(raw) == size, "incomplete workspace physical read")
        self.phase = "post-read" if post else "pre-read"
        return raw

    async def boot(self):
        _require(self.phase == "pre-read", "first boot requires a complete prepared pre-read")
        self.phase = "booting"
        raw = await self.adapter.boot()
        raw = b"" if raw is None else raw
        _require(type(raw) is bytes, "boot capture is not raw bytes")
        _save(self.work_dir / "first-boot.bin", raw)
        self.phase = "booted"
        return raw

    def _identity_source(self):
        return "import machine\nprint('\\nPYBLE_PHYSICAL_UID:'+machine.unique_id().hex())"

    def _check_identity(self, raw):
        lines = [line[len(b"PYBLE_PHYSICAL_UID:"):] for line in raw.splitlines()
                 if line.startswith(b"PYBLE_PHYSICAL_UID:")]
        expected = self.binding["device_id"].replace(":", "").encode("ascii")
        _require(lines == [expected], "runtime connection is not the bound physical board")

    async def _ble_command(self, source, *, bootloader=False):
        from _pble_central import PbleCentral, rsp_status
        import _pble_wire as wire
        from target_smoke import parse_caps, validate_caps
        _require(importlib.metadata.version("bleak") == "3.0.2", "unreviewed BLE tool version")
        _usb_exact(self.binding["application_usb"])
        central = await PbleCentral.connect(self.binding["ble_address"], timeout=25)
        failure = None
        async def run(code, command_id):
            cursor = len(central.events)
            response = await central.send_cmd(wire.OP_RUN, command_id, b"\x01" + code.encode())
            _require(rsp_status(response) == wire.ST_OK, "read-only RUN was refused")
            until = time.monotonic() + 20
            while time.monotonic() < until:
                events = central.events[cursor:]
                states = [frame.payload for frame in events if frame.opcode == wire.OP_RUN_STATE]
                _require(b"\x03" not in states, "read-only RUN failed")
                if b"\x02" in states:
                    _require(states == [b"\x01", b"\x02"], "unexpected RUN state sequence")
                    stdout = b"".join(frame.payload[1:] for frame in events
                                      if frame.opcode == wire.OP_CONSOLE_DATA and frame.payload[:1] == b"\0")
                    stderr = b"".join(frame.payload[1:] for frame in events
                                      if frame.opcode == wire.OP_CONSOLE_DATA and frame.payload[:1] == b"\1")
                    _require(not stderr and len(stdout) <= 128 * 1024, "RUN stderr or oversized transcript")
                    return stdout
                await asyncio.sleep(0.025)
            raise TimeoutError("read-only RUN did not complete")
        try:
            response = await central.send_cmd(wire.OP_HELLO, 1,
                b"proto_versions=1\napp_name=workspace-acquisition\napp_version=1")
            _require(rsp_status(response) == wire.ST_OK, "HELLO refused")
            caps = parse_caps(response.payload[1:].decode("utf-8", errors="strict"))
            profile = self.binding["profile_id"]
            target = {"esp32-4mb": "esp32", "esp32-c3-4mb": "esp32-c3",
                      "esp32-s3-n16r8": "esp32-s3",
                      "waveshare-esp32-s3-lcd-147b": "esp32-s3"}.get(profile, profile)
            validate_caps(caps, target, "0.6.1")
            _require(caps["auto_run"] == "0", "runtime autorun is not disabled")
            central.confirm_caps_mtu(int(caps["mtu"]))
            identity = await run(self._identity_source(), 2)
            self._check_identity(identity)
            if bootloader:
                response = await central.send_cmd(wire.OP_RUN, 3, b"\x01" + source.encode())
                _require(rsp_status(response) == wire.ST_OK, "loader-entry RUN refused")
                until = time.monotonic() + 10
                while time.monotonic() < until and central.is_connected:
                    await asyncio.sleep(0.05)
                _require(not central.is_connected, "loader-entry RUN did not disconnect")
                return identity
            return identity + await run(source, 3)
        except BaseException as exc:
            failure = exc
            raise
        finally:
            try:
                await asyncio.wait_for(central.disconnect(), timeout=5)
                _require(not central.is_connected, "BLE teardown left the link connected")
            except BaseException as cleanup_error:
                if isinstance(failure, asyncio.CancelledError):
                    raise failure from cleanup_error
                raise RuntimeError("BLE teardown did not prove link closure within its bound") from cleanup_error

    def _usb_command_sync(self, source, bootloader):
        import serial
        _require(importlib.metadata.version("pyserial") == "3.5", "unreviewed REPL tool version")
        _usb_exact(self.binding["application_usb"], idle=True)
        port = serial.Serial(port=None, baudrate=115200, timeout=0.2, write_timeout=2)
        port.dtr = False
        port.rts = False
        port.port = self.binding["application_usb"]["port"]
        self._serial = port
        transcript = bytearray()
        def until(marker, seconds=12):
            output = bytearray()
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                _require(not self._serial_cancelled.is_set(), "REPL operation cancelled")
                data = port.read(1)
                output.extend(data)
                transcript.extend(data)
                _require(len(transcript) <= 128 * 1024, "REPL transcript exceeded its bound")
                if output.endswith(marker):
                    return bytes(output)
            raise TimeoutError("raw REPL response did not complete")
        def execute(code, loader=False):
            port.write(code.encode("utf-8"))
            port.write(b"\x04")  # execute in raw REPL; not a soft reset
            acknowledgement = until(b"OK")
            _require(acknowledgement == b"OK", "raw REPL did not acknowledge code exactly")
            if loader:
                return b""
            stdout = until(b"\x04")[:-1]
            stderr = until(b"\x04")[:-1]
            _require(not stderr, "raw REPL command emitted stderr")
            until(b">")
            return stdout
        try:
            port.open()
            # Re-enter from either friendly OR a previous raw REPL without
            # Ctrl-D in friendly mode (which would create a second VM boot).
            port.write(b"\x03\x03\x02\x01")
            until(b"raw REPL; CTRL-B to exit\r\n>")
            identity = execute(self._identity_source())
            self._check_identity(identity)
            execute(source, bootloader)
            return bytes(transcript)
        finally:
            port.close()
            self._serial = None
            label = "usb-loader" if bootloader else "usb-observation"
            _save(self.work_dir / (label + ".bin"), bytes(transcript))

    async def _usb_command(self, source, *, bootloader=False):
        task = asyncio.create_task(asyncio.to_thread(self._usb_command_sync, source, bootloader))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            self._serial_cancelled.set()
            if self._serial is not None:
                self._serial.close()
            try:
                await asyncio.wait_for(asyncio.shield(task), 5)
            except (Exception, asyncio.CancelledError):
                pass
            raise

    async def observe(self, challenge, transport):
        _require(self.phase == "booted" and type(challenge) is str
                 and re.fullmatch("[0-9a-f]{32}", challenge), "invalid or repeated boot observation")
        expected = "pble-run" if self.kind == _KINDS[0] else "usb-repl"
        _require(transport == expected, "observation transport changed")
        self.phase = "observing"
        # Both values are measured on the board, in insertion order; the host
        # neither fabricates JSON nor estimates successful mount/write counts.
        probe = "list(os.statvfs('/'))" if transport == "pble-run" else "None"
        source = ("import os,json,pyble_workspace\n"
                  "print('\\nPYBLE_WORKSPACE_OBSERVATION:'+json.dumps({"
                  "'observation':pyble_workspace.read_boot_observation('%s'),"
                  "'workspace_probe':%s}))" % (challenge, probe))
        until = time.monotonic() + 15
        while not _usb_exact(self.binding["application_usb"], absent_ok=True,
                             alternate=self.binding["loader_usb"]):
            _require(time.monotonic() < until, "exact runtime USB did not reappear")
            await asyncio.sleep(0.2)
        if transport == "pble-run":
            raw = await self._ble_command(source)
        else:
            # Native USB can take a bounded time to re-enumerate; opening it
            # with deasserted controls does not request another boot.
            raw = await self._usb_command(source)
        _save(self.work_dir / "observation.bin", raw)
        self.phase = "observed"
        return raw

    async def close(self):
        if self._serial is not None:
            self._serial.close()
            self._serial = None
        if self.adapter is not None:
            await self.adapter.close()
        self.phase = "closed"
