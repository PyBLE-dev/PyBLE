# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Exact RP2350 BOOTSEL adapter for physical workspace acquisition.

This module never enters a running board's bootloader, connects BLE, or opens
the USB REPL. The shared hardware owner performs those separately. Offsets at
this interface are physical-flash-relative; only picotool arguments use XIP
addresses. Closing the adapter never boots or modifies the board.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import time
import tomllib

FLASH_BYTES = 0x400000
WORKSPACE_OFFSET = 0x180000
XIP_BASE = 0x10000000
SECTOR_BYTES = 4096
_USB_KEYS = {"port", "vid", "pid", "serial_number", "location", "product"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_pico_binding_details(value):
    """Reject identity/geometry substitutions without hardware access."""
    _require(type(value) is dict and value.get("profile_id") == "rpi-pico2-w",
             "Pico binding profile is invalid")
    _require(type(value.get("schema_version")) is int and value["schema_version"] == 1,
             "Pico binding schema is invalid")
    uid = value.get("device_id")
    _require(type(uid) is str and re.fullmatch(r"[0-9a-f]{16}", uid), "Pico UID is invalid")
    _require(type(value.get("ble_address")) is str and 0 < len(value["ble_address"]) <= 128,
             "Pico BLE binding is invalid")
    flash = value.get("flash")
    _require(type(flash) is dict and set(flash) == {
        "chip", "revision", "package", "unique_id", "family_id", "size_bytes", "secure_boot"},
        "Pico flash binding fields are invalid")
    _require(flash["chip"] == "RP2350" and flash["revision"] == "A2"
             and flash["package"] == "QFN60" and flash["unique_id"] == uid,
             "Pico chip identity is invalid")
    _require(type(flash["size_bytes"]) is int and flash["size_bytes"] == FLASH_BYTES
             and type(flash["family_id"]) is int and flash["family_id"] == 0xE48BFF59
             and flash["secure_boot"] is False, "Pico geometry or security is invalid")
    application, loader = value.get("application_usb"), value.get("loader_usb")
    for usb in (application, loader):
        _require(type(usb) is dict and set(usb) == _USB_KEYS, "Pico USB binding fields are invalid")
        _require(type(usb["vid"]) is int and usb["vid"] == 0x2E8A
                 and type(usb["pid"]) is int, "Pico USB vendor/product is invalid")
    _require(loader["pid"] == 15 and loader["port"] is None
             and loader["serial_number"] == uid.upper() and loader["product"] == "RP2350 Boot"
             and type(loader["location"]) is int and 0 < loader["location"] <= 0xFFFFFFFF,
             "Pico BOOTSEL identity is invalid")
    _require(application["pid"] == 5 and application["serial_number"] == uid
             and type(application["port"]) is str
             and re.fullmatch(r"/dev/cu\.[A-Za-z0-9_.-]+", application["port"])
             and type(application["location"]) is str and 0 < len(application["location"]) <= 128
             and type(application["product"]) is str and 0 < len(application["product"]) <= 128,
             "Pico application USB identity is invalid")
    _require(value.get("transfer") == {"kind": "picotool"}, "Pico transfer policy is invalid")
    return copy.deepcopy(value)


def pico_loader_present(raw, binding):
    """Interpret real macOS ioreg -a -l output, including dictionary roots."""
    cfg = validate_pico_binding_details(binding)["loader_usb"]
    _require(type(raw) is bytes and 0 < len(raw) <= 2 * 1024 * 1024, "ioreg response is invalid")
    try:
        root = plistlib.loads(raw)
    except Exception as exc:
        raise ValueError("ioreg response is not a plist") from exc
    pending = [(root, 0)]
    records = []
    count = 0
    while pending:
        node, depth = pending.pop()
        count += 1
        _require(depth <= 64 and count <= 16384, "ioreg tree exceeds its bound")
        if type(node) is list:
            pending.extend((item, depth + 1) for item in node)
            continue
        _require(type(node) is dict, "ioreg tree node is invalid")
        if node.get("idVendor") == 0x2E8A and node.get("idProduct") == 15:
            serial = node.get("USB Serial Number")
            if type(serial) is str and serial.upper() == cfg["serial_number"]:
                records.append({"port": None, "vid": node.get("idVendor"),
                    "pid": node.get("idProduct"), "serial_number": serial,
                    "location": node.get("locationID"), "product": node.get("USB Product Name")})
        children = node.get("IORegistryEntryChildren", [])
        _require(type(children) is list, "ioreg child inventory is invalid")
        pending.extend((item, depth + 1) for item in children)
    if not records:
        return False
    _require(len(records) == 1 and records[0] == cfg, "Pico BOOTSEL identity changed or is ambiguous")
    return True


def parse_pico_device_info(raw, binding):
    """Parse only actual Device Information, not candidate program metadata."""
    cfg = validate_pico_binding_details(binding)["flash"]
    _require(type(raw) is bytes and len(raw) <= 65536, "picotool device response is invalid")
    try:
        lines = raw.decode("utf-8", errors="strict").splitlines()
    except UnicodeError as exc:
        raise ValueError("picotool device response is not UTF-8") from exc
    starts = [index for index, line in enumerate(lines) if line == "Device Information"]
    _require(len(starts) == 1, "picotool device section is missing or ambiguous")
    fields = {}
    for line in lines[starts[0] + 1:]:
        if line and not line[0].isspace():
            break
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        _require(key not in fields, "duplicate picotool device fact")
        fields[key] = value
    expected = {"type": cfg["chip"], "revision": cfg["revision"], "package": cfg["package"],
                "chipid": "0x" + cfg["unique_id"], "flash size": "4096K", "secure boot": "0"}
    _require(all(fields.get(key) == value for key, value in expected.items()),
             "Pico chip, UID, revision, capacity or security changed")
    return {key: cfg[key] for key in ("chip", "revision", "package", "unique_id", "size_bytes", "secure_boot")}


def pico_read_argv(offset, size, path):
    _require(type(offset) is int and type(size) is int and 0 <= offset < FLASH_BYTES
             and 0 < size <= FLASH_BYTES - offset, "Pico physical read range is invalid")
    return ["save", "-r", hex(XIP_BASE + offset), hex(XIP_BASE + offset + size),
            "-v", os.fspath(path), "-t", "bin"]


def _payload(image):
    # Binding-only finalizers load this module without the HIL import path.
    # Runtime UF2 operations run in the source-bound HIL execution closure.
    from _pble_bench import BenchError, _reconstruct_rp2350_uf2

    _require(type(image) is bytes and 0 < len(image) <= (WORKSPACE_OFFSET // 256 + 1) * 512,
             "Pico candidate UF2 bytes are invalid")
    try:
        payload = _reconstruct_rp2350_uf2(image)
    except (BenchError, ValueError) as exc:
        raise ValueError("Pico candidate UF2 structure is invalid") from exc
    _require(0 < len(payload) <= WORKSPACE_OFFSET, "Pico UF2 overlaps the workspace")
    return payload


def pico_programmed_footprint(image):
    payload = _payload(image)
    # Pinned picotool 2.3.0 main.cpp:5299-5308 rounds each flash load to 4096 bytes,
    # inserting zeros, not FF, after the last partial program sector.
    size = (len(payload) + SECTOR_BYTES - 1) // SECTOR_BYTES * SECTOR_BYTES
    return payload + b"\0" * (size - len(payload))


def pico_prefix_argv(offset, data, path):
    _require(type(offset) is int and offset == WORKSPACE_OFFSET
             and type(data) is bytes and data == b"\0" * (2 * SECTOR_BYTES),
             "Pico incompatible-media write must be exactly the first two workspace blocks")
    return ["load", "-v", os.fspath(path), "-t", "bin", "-o", hex(XIP_BASE + offset)]


def reconstruct_uf2_readback(image, read):
    """Retain candidate container metadata; replace every loadable data byte."""
    payload = _payload(image)  # Complete structural validation precedes all reads.
    result = bytearray(image)
    for index in range(len(payload) // 256):
        actual = read(XIP_BASE + index * 256, 256)
        _require(type(actual) is bytes and len(actual) == 256, "Pico payload read is incomplete")
        start = (index + 1) * 512 + 32  # Validated first record is the ignored extension.
        result[start:start + 256] = actual
    return bytes(result)


def _regular_bytes(path, maximum):
    path = Path(path)
    _require(path.is_absolute(), "Pico input path must be absolute")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        first = os.fstat(descriptor)
        _require(stat.S_ISREG(first.st_mode) and first.st_nlink == 1 and first.st_size <= maximum,
                 "Pico input is not a bounded single-link regular file")
        raw = bytearray()
        while len(raw) < first.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, first.st_size - len(raw)))
            _require(chunk, "Pico input read was short")
            raw.extend(chunk)
        final = os.fstat(descriptor)
        visible = path.lstat()
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                                 info.st_ctime_ns, info.st_mode, info.st_nlink)
        _require(identity(first) == identity(final) == identity(visible), "Pico input changed while read")
        return bytes(raw)
    finally:
        os.close(descriptor)


class PicoAdapter:
    """One acquisition's exact loader, with retained private command artifacts."""

    def __init__(self, binding, *, repo_root, work_dir):
        self.binding = validate_pico_binding_details(binding)
        self.repo_root = Path(repo_root)
        self.work_dir = Path(work_dir)
        _require(self.repo_root == Path(__file__).resolve().parents[3], "Pico adapter checkout changed")
        _require(self.work_dir.is_absolute() and not self.work_dir.is_symlink(), "Pico work directory is invalid")
        info = self.work_dir.stat()
        _require(stat.S_ISDIR(info.st_mode) and info.st_mode & 0o7777 == 0o700,
                 "Pico work directory must be private mode0700")
        self._directory_identity = (info.st_dev, info.st_ino)
        self._directory_fd = os.open(self.work_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self._counter = 0
        self._connected = self._erased = self._image_written = self._prefix_written = False
        self._closed = self._failed = self._booted = False
        self._process = None
        self._lock_raw = None
        self._image = None
        self._tool = None

    def _directory_guard(self):
        _require(not self._closed, "Pico adapter is closed")
        info, visible = os.fstat(self._directory_fd), self.work_dir.lstat()
        _require(stat.S_ISDIR(visible.st_mode) and visible.st_mode & 0o7777 == 0o700
                 and (info.st_dev, info.st_ino) == (visible.st_dev, visible.st_ino)
                 == self._directory_identity, "Pico work directory changed")

    def _new_file(self, suffix, raw=b""):
        self._directory_guard()
        self._counter += 1
        name = "pico-%04d-%s" % (self._counter, suffix)
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=self._directory_fd)
        try:
            offset = 0
            while offset < len(raw):
                count = os.write(descriptor, raw[offset:])
                _require(count > 0, "Pico private file write was short")
                offset += count
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return self.work_dir / name

    def _tools_guard(self):
        _require(not any(key.startswith(("DYLD_", "PICOTOOL_")) for key in os.environ),
                 "Pico tool environment override is not allowed")
        raw = _regular_bytes(self.repo_root / "firmware/versions.lock", 65536)
        if self._lock_raw is None:
            self._lock_raw = raw
        _require(raw == self._lock_raw, "Pico tool lock changed")
        pin = tomllib.loads(raw.decode("utf-8"))["picotool"]
        _require(pin["version"] == "2.3.0" and pin["executable_path"] == "picotool/picotool"
                 and pin["bundled_libusb_path"] == "picotool/libusb-1.0.0.dylib",
                 "Pico tool layout or version changed")
        base = self.repo_root / "firmware/.picotool"
        for path_key, sha_key in (("executable_path", "executable_sha256"),
                                  ("bundled_libusb_path", "bundled_libusb_sha256")):
            path = base / pin[path_key]
            _require(path.resolve() == path, "Pico tool path contains a symlink")
            _require(hashlib.sha256(_regular_bytes(path, 64 * 1024 * 1024)).hexdigest() == pin[sha_key],
                     "Pinned Pico tool bytes changed")
        self._tool = base / pin["executable_path"]
        return pin

    async def _child(self, command, timeout):
        """Bounded child; partial output survives timeout/cancellation and close."""
        self._directory_guard()
        _require(self._process is None, "Pico command is already active")
        self._new_file("command.json", (json.dumps({"argv": command, "monotonic_ns": time.monotonic_ns()},
                       sort_keys=True) + "\n").encode())
        output = self._new_file("output.log")
        descriptor = os.open(output.name, os.O_WRONLY | os.O_NOFOLLOW, dir_fd=self._directory_fd)
        process = None
        code = None
        try:
            process = await asyncio.create_subprocess_exec(*command, stdout=descriptor,
                                                           stderr=asyncio.subprocess.STDOUT)
            self._process = process
            await asyncio.wait_for(process.wait(), timeout=timeout)
            code = process.returncode
        finally:
            if process is not None and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            self._process = None
            os.fsync(descriptor)
            os.close(descriptor)
            self._new_file("command-end.json", (json.dumps({"returncode": code,
                "monotonic_ns": time.monotonic_ns()}, sort_keys=True) + "\n").encode())
        raw = _regular_bytes(output, 2 * 1024 * 1024)
        _require(code == 0, "Pico command failed; retained private output: " + output.name)
        return raw

    async def loader_present(self):
        _require(not self._failed and not self._closed, "Pico adapter is not usable")
        raw = await self._child(["/usr/sbin/ioreg", "-a", "-l", "-p", "IOUSB"], 10)
        return pico_loader_present(raw, self.binding)

    async def _run(self, args, *, input_guard=None):
        try:
            self._directory_guard()
            _require(not self._failed, "Pico adapter has a prior failure")
            self._tools_guard()
            _require(await self.loader_present(), "Exact Pico BOOTSEL target is absent")
            if input_guard is not None:
                path, expected = input_guard
                _require(_regular_bytes(path, 4 * 1024 * 1024) == expected, "Pico staged input changed")
            usb = self.binding["loader_usb"]
            command = [str(self._tool), *args, "--ser", usb["serial_number"],
                       "--vid", hex(usb["vid"]), "--pid", hex(usb["pid"])]
            raw = await self._child(command, 180)
            self._tools_guard()
            if input_guard is not None:
                _require(_regular_bytes(path, 4 * 1024 * 1024) == expected, "Pico staged input changed during command")
            return raw
        except BaseException:
            self._failed = True
            raise

    async def connect(self):
        _require(not self._closed and not self._failed, "Pico adapter is not usable")
        self._connected = False
        # _run pins executable/dependency bytes. Version is also inspected,
        # once, without any device-selection or reset flags.
        if self._tool is None:
            pin = self._tools_guard()
            version = await self._child([str(self._tool), "version"], 10)
            _require(version.decode("utf-8").strip() == pin["version_line"], "Pico tool version changed")
        self.device_facts = parse_pico_device_info(await self._run(["info", "-a"]), self.binding)
        self._connected = True

    def _ready(self):
        _require(self._connected and not self._failed and not self._closed, "Pico loader is not connected")

    async def erase(self):
        self._ready()
        _require(not self._erased and not self._image_written and not self._booted, "Pico erase is one-shot")
        await self._run(["erase", "-a"])
        raw = await self.read_flash(0, FLASH_BYTES)
        if raw != b"\xff" * FLASH_BYTES:
            self._failed = True
            raise ValueError("Pico whole-chip erase is not independently verified")
        self._erased = True

    async def write_image(self, candidate_uf2):
        self._ready()
        _require(self._erased and not self._image_written and not self._booted,
                 "Pico image needs a verified one-shot full erase")
        footprint = pico_programmed_footprint(candidate_uf2)
        path = self._new_file("candidate.uf2", candidate_uf2)
        await self._run(["load", "-v", str(path)], input_guard=(path, candidate_uf2))
        if await self.read_flash(0, len(footprint)) != footprint:
            self._failed = True
            raise ValueError("Pico actual program and pinned zero-sector padding differ")
        self._image = candidate_uf2
        self._image_written = True

    async def write_prefix(self, offset, data):
        self._ready()
        _require(self._image_written and not self._prefix_written and not self._booted,
                 "Pico incompatible prefix is one-shot before first boot")
        pico_prefix_argv(offset, data, "guard-only")
        path = self._new_file("incompatible.bin", data)
        await self._run(pico_prefix_argv(offset, data, path), input_guard=(path, data))
        if await self.read_flash(offset, len(data)) != data:
            self._failed = True
            raise ValueError("Pico incompatible prefix readback differs")
        self._prefix_written = True

    async def read_flash(self, offset, size):
        self._ready()
        pico_read_argv(offset, size, "guard-only")
        path = self._new_file("readback.bin")
        identity = path.stat()
        await self._run(pico_read_argv(offset, size, path))
        raw = _regular_bytes(path, FLASH_BYTES)
        final = path.stat()
        if len(raw) != size or (identity.st_dev, identity.st_ino) != (final.st_dev, final.st_ino):
            self._failed = True
            raise ValueError("Pico physical readback is incomplete or was replaced")
        return raw

    async def read_install(self, candidate_uf2):
        self._ready()
        _require(self._image_written and candidate_uf2 == self._image, "Pico candidate changed after load")
        payload = _payload(candidate_uf2)
        actual = await self.read_flash(0, len(payload))
        return reconstruct_uf2_readback(candidate_uf2,
            lambda address, size: actual[address - XIP_BASE:address - XIP_BASE + size])

    async def boot(self):
        self._ready()
        _require(self._image_written and not self._booted, "Pico boot is one-shot after image verification")
        await self._run(["reboot", "-a"])
        self._connected = False
        self._booted = True

    async def close(self):
        if self._closed:
            return
        _require(self._process is None, "Pico command must finish or cancel before close")
        os.close(self._directory_fd)
        self._closed = True
        self._connected = False
