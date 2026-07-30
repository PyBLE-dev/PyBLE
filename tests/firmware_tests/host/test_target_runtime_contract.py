#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] F-14/F-24 — Frozen three-target runtime and ESP32-C3 release contract.
#
# Frozen sources:
#   docs/specifications/firmware/TDD.md §§10.6, 11
#   docs/specifications/firmware/browser-flashing.md §1
#
# Source tests resolve manifests from the pinned MicroPython checkout. Generated
# checks are conditional because a plain host checkout has no cross-build tree;
# when all three build outputs are supplied they inspect authoritative generated
# content rather than orphan-prone frozen_mpy/*.mpy intermediates.

from __future__ import annotations

import ast
from collections import Counter
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import tomllib
import unittest


HOST_DIR = Path(__file__).resolve().parent
REPO_ROOT = HOST_DIR.parents[2]
FIRMWARE_DIR = REPO_ROOT / "firmware"
OVERLAYS = FIRMWARE_DIR / "board_overlays"
UPSTREAM_DIR = FIRMWARE_DIR / "upstream" / "micropython"
MPY_LIB_DIR = UPSTREAM_DIR / "lib" / "micropython-lib"
BUILD_ROOT = Path(
    os.environ.get("PYBLE_BUILD_ROOT", FIRMWARE_DIR / "build")
).resolve()

TARGETS = {
    "esp32": "PYBLE_ESP32",
    "esp32-s3": "PYBLE_ESP32_S3",
    "esp32-c3": "PYBLE_ESP32_C3",
}

EXPECTED_FROZEN_PATHS = Counter(
    {
        "flashbdev.py": 1,
        "inisetup.py": 1,
        "asyncio/__init__.py": 1,
        "asyncio/core.py": 1,
        "asyncio/event.py": 1,
        "asyncio/funcs.py": 1,
        "asyncio/lock.py": 1,
        "asyncio/stream.py": 1,
        "uasyncio.py": 1,
        "neopixel.py": 1,
        "_boot.py": 1,
        "pyble/__init__.py": 1,
        "pyble/pyble_ble.py": 1,
        "pyble/pyble_proto.py": 1,
    }
)

EXPECTED_FROZEN_SYMBOLS = {
    "flashbdev",
    "inisetup",
    "asyncio___init__",
    "asyncio_core",
    "asyncio_event",
    "asyncio_funcs",
    "asyncio_lock",
    "asyncio_stream",
    "uasyncio",
    "neopixel",
    "_boot",
    "pyble___init__",
    "pyble_pyble_ble",
    "pyble_pyble_proto",
}

FORBIDDEN_NETWORKING_PATHS = {
    "aioespnow.py",
    "espnow.py",
    "mip/__init__.py",
    "ntptime.py",
    "requests/__init__.py",
    "ssl.py",
    "umqtt/robust.py",
    "umqtt/simple.py",
    "urequests.py",
    "webrepl.py",
    "webrepl_setup.py",
}

PBLE_NATIVE_MODULES = {
    "pble_ble",
    "pble_boot",
    "pble_console",
    "pble_fs",
    "pble_proto",
    "pble_runner",
}


def _load_manifestfile():
    path = UPSTREAM_DIR / "tools" / "manifestfile.py"
    spec = importlib.util.spec_from_file_location(
        "pyble_runtime_manifestfile", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load pinned MicroPython manifest resolver")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _resolved_manifest(target: str, board_name: str):
    manifestfile = _load_manifestfile()
    with tempfile.TemporaryDirectory(
        prefix="pyble-runtime-manifest-"
    ) as temporary_dir:
        board_dir = Path(temporary_dir) / board_name
        shutil.copytree(OVERLAYS / target, board_dir)
        shutil.copytree(FIRMWARE_DIR / "pyble", board_dir / "pyble")
        resolver = manifestfile.ManifestFile(
            manifestfile.MODE_FREEZE,
            {
                "MPY_DIR": str(UPSTREAM_DIR),
                "PORT_DIR": str(UPSTREAM_DIR / "ports" / "esp32"),
                "BOARD_DIR": str(board_dir),
                "MPY_LIB_DIR": str(MPY_LIB_DIR),
            },
        )
        resolver.execute(str(board_dir / "manifest.py"))
        yield board_dir, resolver.files()


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return "{}.{}".format(prefix, node.attr) if prefix else node.attr
    if isinstance(node, ast.Call):
        return _dotted_name(node.func)
    return ""


def _sdkconfig_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        disabled = re.fullmatch(r"# (CONFIG_[A-Z0-9_]+) is not set", line)
        if disabled:
            values[disabled.group(1)] = "n"
            continue
        setting = re.fullmatch(r"(CONFIG_[A-Z0-9_]+)=(.*)", line)
        if setting:
            values[setting.group(1)] = setting.group(2)
    return values


def _image_header(path: Path) -> dict[str, int]:
    header = path.read_bytes()[:24]
    if len(header) != 24:
        raise AssertionError("{} has a truncated ESP image header".format(path))
    return {
        "magic": header[0],
        "spi_mode": header[2],
        "spi_size_freq": header[3],
        "chip_id": struct.unpack_from("<H", header, 12)[0],
        "min_chip_rev_full": struct.unpack_from("<H", header, 15)[0],
        "max_chip_rev_full": struct.unpack_from("<H", header, 17)[0],
    }


def _elf32_sections(path: Path) -> dict[str, bytes]:
    """Return named ELF32 little-endian sections without a toolchain helper."""
    data = path.read_bytes()
    if data[:6] != b"\x7fELF\x01\x01":
        raise AssertionError("{} is not a little-endian ELF32 object".format(path))
    section_offset = struct.unpack_from("<I", data, 32)[0]
    section_entry_size = struct.unpack_from("<H", data, 46)[0]
    section_count = struct.unpack_from("<H", data, 48)[0]
    names_index = struct.unpack_from("<H", data, 50)[0]
    if section_entry_size < 40 or names_index >= section_count:
        raise AssertionError("{} has invalid ELF section metadata".format(path))

    headers = []
    for index in range(section_count):
        offset = section_offset + index * section_entry_size
        if offset + 40 > len(data):
            raise AssertionError("{} has a truncated ELF section table".format(path))
        headers.append(struct.unpack_from("<10I", data, offset))

    names_header = headers[names_index]
    names = data[names_header[4]:names_header[4] + names_header[5]]
    result = {}
    for header in headers:
        name_offset = header[0]
        if name_offset >= len(names):
            raise AssertionError("{} has an invalid ELF section name".format(path))
        name_end = names.find(b"\0", name_offset)
        if name_end < 0:
            raise AssertionError("{} has an unterminated ELF section name".format(path))
        name = names[name_offset:name_end].decode("ascii", errors="strict")
        result[name] = data[header[4]:header[4] + header[5]]
    return result


class EffectiveManifestContractTests(unittest.TestCase):
    def test_all_targets_resolve_the_exact_lean_runtime_allowlist(self):
        for target, board_name in TARGETS.items():
            with self.subTest(target=target), _resolved_manifest(
                target, board_name
            ) as (_, files):
                paths = Counter(result.target_path for result in files)
                self.assertEqual(
                    paths,
                    EXPECTED_FROZEN_PATHS,
                    "{} must freeze only boot/VFS, asyncio, one standard "
                    "NeoPixel, board boot, and PyBLE runtime files".format(
                        target
                    ),
                )
                self.assertTrue(
                    FORBIDDEN_NETWORKING_PATHS.isdisjoint(paths),
                    "{} must not inherit the broad networking manifest".format(
                        target
                    ),
                )

    def test_no_target_includes_the_broad_esp32_board_manifest(self):
        broad_include = re.compile(
            r"""include\s*\(\s*["']\$\(PORT_DIR\)/boards/manifest\.py["']"""
        )
        for target in TARGETS:
            with self.subTest(target=target):
                text = (OVERLAYS / target / "manifest.py").read_text(
                    encoding="utf-8"
                )
                self.assertNotRegex(
                    text,
                    broad_include,
                    "{} must declare the lean allowlist explicitly".format(
                        target
                    ),
                )

    def test_every_effective_boot_is_board_owned_and_has_full_lifecycle(self):
        boot_sources: dict[str, bytes] = {}
        for target, board_name in TARGETS.items():
            with self.subTest(target=target), _resolved_manifest(
                target, board_name
            ) as (board_dir, files):
                boot_modules = [
                    item for item in files if item.target_path == "_boot.py"
                ]
                self.assertEqual(
                    len(boot_modules),
                    1,
                    "{} must freeze exactly one _boot.py".format(target),
                )
                expected_boot = (board_dir / "_boot.py").resolve()
                actual_boot = Path(boot_modules[0].full_path).resolve()
                self.assertEqual(
                    actual_boot,
                    expected_boot,
                    "{} must freeze its board-owned PyBLE boot, not upstream "
                    "ports/esp32/modules/_boot.py".format(target),
                )

                source = expected_boot.read_bytes()
                boot_sources[target] = source
                tree = ast.parse(source, filename=str(expected_boot))
                calls = [
                    (_dotted_name(node.func), node)
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                ]
                by_name: dict[str, list[ast.Call]] = {}
                for name, node in calls:
                    by_name.setdefault(name, []).append(node)

                for required in (
                    "vfs.mount",
                    "inisetup.setup",
                    "pble_ble.init_agent",
                    "os.dupterm",
                    "pble_boot.maybe_autorun",
                    "gc.collect",
                ):
                    self.assertEqual(
                        len(by_name.get(required, [])),
                        1,
                        "{} _boot.py must call {} exactly once".format(
                            target, required
                        ),
                    )

                worker_calls = {}
                for call in by_name.get("_thread.start_new_thread", []):
                    if call.args:
                        worker_calls[_dotted_name(call.args[0])] = call
                self.assertEqual(
                    set(worker_calls),
                    {"pble_runner.worker", "pble_fs.worker"},
                    "{} must launch exactly the runner and filesystem workers".format(
                        target
                    ),
                )

                dupterm = by_name["os.dupterm"][0]
                self.assertEqual(len(dupterm.args), 1)
                self.assertIsInstance(dupterm.args[0], ast.Call)
                self.assertEqual(
                    _dotted_name(dupterm.args[0]),
                    "pble_console.stream",
                    "{} must attach the native BLE console stream".format(
                        target
                    ),
                )

                lifecycle_lines = (
                    by_name["pble_ble.init_agent"][0].lineno,
                    worker_calls["pble_runner.worker"].lineno,
                    worker_calls["pble_fs.worker"].lineno,
                    by_name["os.dupterm"][0].lineno,
                    by_name["pble_boot.maybe_autorun"][0].lineno,
                    by_name["gc.collect"][0].lineno,
                )
                self.assertEqual(
                    lifecycle_lines,
                    tuple(sorted(lifecycle_lines)),
                    "{} lifecycle must be agent -> runner -> filesystem -> "
                    "console -> autorun -> final GC".format(target),
                )
                self.assertLess(
                    by_name["vfs.mount"][0].lineno,
                    by_name["pble_ble.init_agent"][0].lineno,
                )
                self.assertLess(
                    by_name["inisetup.setup"][0].lineno,
                    by_name["pble_ble.init_agent"][0].lineno,
                )

        self.assertEqual(
            len(set(boot_sources.values())),
            1,
            "all targets must freeze the same chip-agnostic PyBLE _boot.py",
        )


class BoardConfigurationSourceContractTests(unittest.TestCase):
    def test_board_overlays_supply_canonical_pble_target_ids(self):
        expected = {
            "esp32": "esp32",
            "esp32-s3": "esp32-s3",
            "esp32-c3": "esp32-c3",
        }
        for target, target_id in expected.items():
            with self.subTest(target=target):
                header = (OVERLAYS / target / "mpconfigboard.h").read_text(
                    encoding="utf-8"
                )
                matches = re.findall(
                    r'(?m)^\s*#\s*define\s+PBLE_TARGET_ID\s+"([^"]+)"\s*$',
                    header,
                )
                self.assertEqual(
                    matches,
                    [target_id],
                    "{} must define its one canonical PBLE/1 target ID".format(
                        target
                    ),
                )

        info = (
            FIRMWARE_DIR / "user_c_modules" / "pyble" / "pble_info.c"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "PBLE_TARGET_ID",
            info,
            "DEVICE_INFO must serialize the board-overlay PBLE target ID",
        )
        self.assertNotIn(
            "CONFIG_IDF_TARGET",
            info,
            "raw ESP-IDF target spellings are not PBLE/1 target IDs",
        )

    def test_untrusted_identify_gpio_is_bounded_before_idf_output_check(self):
        source_path = (
            FIRMWARE_DIR
            / "user_c_modules"
            / "pyble"
            / "pble_device_config.c"
        )
        source = source_path.read_text(encoding="utf-8")
        helper = re.search(
            r"static\s+bool\s+dc_gpio_is_valid_output\s*"
            r"\(\s*int\s+gpio\s*\)\s*\{(?P<body>.*?)\}",
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(
            helper,
            "untrusted BLE/NVS GPIO bytes need one int-valued safety helper",
        )
        body = helper.group("body")
        self.assertRegex(
            body,
            r"gpio\s*>=\s*0\s*&&\s*"
            r"gpio\s*<\s*GPIO_NUM_MAX\s*&&\s*"
            r"GPIO_IS_VALID_OUTPUT_GPIO\s*\(\s*gpio\s*\)",
            "the GPIO_NUM_MAX bound must short-circuit before ESP-IDF's "
            "mask-shift macro",
        )

        without_helper = source[: helper.start()] + source[helper.end() :]
        self.assertNotRegex(
            without_helper,
            r"\bGPIO_IS_VALID_OUTPUT_GPIO\s*\(",
            "all untrusted identify-GPIO validation must use the bounded helper",
        )
        self.assertEqual(
            source.count("dc_gpio_is_valid_output("),
            3,
            "the bounded helper must validate both persisted and BLE values",
        )

    def test_all_targets_leave_board_startup_at_upstream_default(self):
        define = re.compile(
            r"(?m)^\s*#\s*define\s+MICROPY_BOARD_STARTUP(?:\s|\()"
        )
        source_append = re.compile(
            r"(?mi)^\s*list\s*\(\s*APPEND\s+MICROPY_SOURCE_BOARD\b"
        )
        for target in TARGETS:
            with self.subTest(target=target):
                header = (OVERLAYS / target / "mpconfigboard.h").read_text(
                    encoding="utf-8"
                )
                cmake = (
                    OVERLAYS / target / "mpconfigboard.cmake"
                ).read_text(encoding="utf-8")
                self.assertNotRegex(
                    header,
                    define,
                    "{} must use upstream boardctrl_startup()".format(target),
                )
                self.assertNotRegex(
                    cmake,
                    source_append,
                    "{} must not compile a replacement startup hook".format(
                        target
                    ),
                )

    def test_c3_source_selects_riscv_size_and_explicit_release_settings(self):
        overlay = OVERLAYS / "esp32-c3"
        cmake = (overlay / "mpconfigboard.cmake").read_text(encoding="utf-8")
        riscv_fragment = (
            UPSTREAM_DIR / "ports" / "esp32" / "boards" / "sdkconfig.riscv"
        ).read_text(encoding="utf-8")
        board_fragment = (overlay / "sdkconfig.board").read_text(
            encoding="utf-8"
        )
        header = (overlay / "mpconfigboard.h").read_text(encoding="utf-8")

        defaults = (
            "boards/sdkconfig.base",
            "boards/sdkconfig.riscv",
            "boards/sdkconfig.ble",
            "${CMAKE_CURRENT_LIST_DIR}/sdkconfig.board",
        )
        positions = []
        for fragment in defaults:
            self.assertEqual(
                cmake.count(fragment),
                1,
                "C3 must select {} exactly once".format(fragment),
            )
            positions.append(cmake.index(fragment))
        self.assertEqual(
            positions,
            sorted(positions),
            "C3 SDK defaults must resolve base -> RISC-V -> BLE -> board",
        )
        self.assertRegex(
            riscv_fragment,
            r"(?m)^CONFIG_COMPILER_OPTIMIZATION_SIZE=y$",
        )

        for setting in (
            "CONFIG_ESP_SYSTEM_HW_STACK_GUARD=n",
            "CONFIG_ESPTOOLPY_FLASHMODE_DIO=y",
            "CONFIG_ESPTOOLPY_FLASHFREQ_80M=y",
            "CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y",
            "CONFIG_PARTITION_TABLE_CUSTOM=y",
            'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions.csv"',
            "CONFIG_ESP32C3_REV_MIN_3=y",
        ):
            with self.subTest(setting=setting):
                self.assertRegex(
                    board_fragment,
                    r"(?m)^{}$".format(re.escape(setting)),
                    "C3 release settings must be explicit, not comments or "
                    "ambient Kconfig defaults",
                )

        self.assertRegex(
            header,
            r"(?m)^\s*#\s*define\s+MICROPY_HW_ENABLE_UART_REPL\s+\(1\)",
            "C3 must keep UART0 REPL/debug parity",
        )


class GeneratedRuntimeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = [
            BUILD_ROOT / target / relative
            for target in TARGETS
            for relative in (
                "frozen_content.c",
                "genhdr/moduledefs.collected",
                "sdkconfig",
                "flasher_args.json",
                "bootloader/bootloader.bin",
                "micropython.bin",
            )
        ]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise unittest.SkipTest(
                "three-target cross-build outputs unavailable: {}".format(
                    ", ".join(missing)
                )
            )

    def test_generated_frozen_content_is_exact_lean_runtime(self):
        symbol_pattern = re.compile(
            r"^static const mp_frozen_module_t "
            r"frozen_module_([A-Za-z0-9_]+) =",
            re.MULTILINE,
        )
        for target in TARGETS:
            with self.subTest(target=target):
                text = (
                    BUILD_ROOT / target / "frozen_content.c"
                ).read_text(encoding="utf-8")
                symbols = symbol_pattern.findall(text)
                self.assertEqual(
                    Counter(symbols),
                    Counter({name: 1 for name in EXPECTED_FROZEN_SYMBOLS}),
                    "{} generated frozen content must contain the exact lean "
                    "allowlist and one NeoPixel".format(target),
                )

                boot = re.search(
                    r"// frozen module _boot\b(?P<body>.*?)"
                    r"(?=// frozen module |\Z)",
                    text,
                    re.DOTALL,
                )
                self.assertIsNotNone(
                    boot, "{} must generate a frozen _boot module".format(target)
                )
                for qstr in (
                    "MP_QSTR_pble_ble",
                    "MP_QSTR_init_agent",
                    "MP_QSTR_pble_runner",
                    "MP_QSTR_pble_fs",
                    "MP_QSTR_dupterm",
                    "MP_QSTR_pble_console",
                    "MP_QSTR_pble_boot",
                    "MP_QSTR_maybe_autorun",
                ):
                    self.assertIn(
                        qstr,
                        boot.group("body"),
                        "{} generated _boot must contain {}".format(
                            target, qstr
                        ),
                    )

    def test_generated_outputs_bind_the_selected_root_and_one_source_identity(self):
        expected_source_commit = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        expected_source_epoch = int(
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(REPO_ROOT),
                    "show",
                    "-s",
                    "--format=%ct",
                    expected_source_commit,
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
        )
        with (FIRMWARE_DIR / "versions.lock").open("rb") as handle:
            lock = tomllib.load(handle)
        expected_micropython = lock["micropython"]["commit"]
        expected_esp_idf = lock["esp_idf"]["commit"]
        actual_micropython = subprocess.run(
            ["git", "-C", str(UPSTREAM_DIR), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        actual_esp_idf = subprocess.run(
            [
                "git",
                "-C",
                str(FIRMWARE_DIR / ".esp-idf"),
                "rev-parse",
                "HEAD",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        self.assertEqual(actual_micropython, expected_micropython)
        self.assertEqual(actual_esp_idf, expected_esp_idf)

        identities = []
        expected_keys = {
            "schema_version",
            "target",
            "source_date_epoch",
            "pyble",
            "micropython",
            "esp_idf",
        }
        for target in TARGETS:
            with self.subTest(target=target):
                build = BUILD_ROOT / target
                provenance_path = build / "pyble-build-provenance.json"
                self.assertTrue(
                    provenance_path.is_file(),
                    "{} must carry its build provenance in the selected "
                    "PYBLE_BUILD_ROOT".format(target),
                )
                provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                self.assertEqual(set(provenance), expected_keys)
                self.assertEqual(provenance["schema_version"], 1)
                self.assertEqual(provenance["target"], target)
                self.assertIs(type(provenance["source_date_epoch"]), int)
                self.assertEqual(set(provenance["pyble"]), {"commit", "clean"})
                self.assertEqual(set(provenance["micropython"]), {"commit"})
                self.assertEqual(set(provenance["esp_idf"]), {"commit"})
                self.assertIs(provenance["pyble"]["clean"], True)
                for item in ("pyble", "micropython", "esp_idf"):
                    self.assertRegex(provenance[item]["commit"], r"^[0-9a-f]{40}$")

                description = json.loads(
                    (build / "project_description.json").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    Path(description["build_dir"]).resolve(),
                    build.resolve(),
                    "{} generated metadata must identify this selected build "
                    "root, not a copied/stale root".format(target),
                )
                identities.append(
                    (
                        provenance["source_date_epoch"],
                        provenance["pyble"]["commit"],
                        provenance["micropython"]["commit"],
                        provenance["esp_idf"]["commit"],
                    )
                )

        self.assertEqual(
            len(set(identities)),
            1,
            "all three generated targets must come from one source identity",
        )
        self.assertEqual(
            identities[0],
            (
                expected_source_epoch,
                expected_source_commit,
                expected_micropython,
                expected_esp_idf,
            ),
        )

    def test_all_generated_images_register_every_native_pble_module(self):
        registration = re.compile(
            r"MP_REGISTER_MODULE\(MP_QSTR_(pble_[a-z0-9_]+),"
        )
        for target in TARGETS:
            with self.subTest(target=target):
                text = (
                    BUILD_ROOT / target / "genhdr/moduledefs.collected"
                ).read_text(encoding="utf-8")
                modules = registration.findall(text)
                self.assertEqual(
                    Counter(modules),
                    Counter({name: 1 for name in PBLE_NATIVE_MODULES}),
                    "{} must register every native PBLE module exactly once".format(
                        target
                    ),
                )

    def test_generated_pble_info_objects_embed_canonical_target_ids(self):
        expected = {
            "esp32": b"esp32\0",
            "esp32-s3": b"esp32-s3\0",
            "esp32-c3": b"esp32-c3\0",
        }
        section_prefix = ".rodata.pble_info_device_info.str"
        for target, target_id in expected.items():
            with self.subTest(target=target):
                objects = sorted(
                    (BUILD_ROOT / target).rglob("pble_info.c.obj")
                )
                self.assertTrue(
                    objects,
                    "{} must compile pble_info.c into the generated build".format(
                        target
                    ),
                )
                for obj in objects:
                    sections = _elf32_sections(obj)
                    literals = b"".join(
                        contents
                        for name, contents in sections.items()
                        if name.startswith(section_prefix)
                    )
                    self.assertTrue(
                        literals,
                        "{} must carry pble_info_device_info string literals".format(
                            obj
                        ),
                    )
                    self.assertIn(
                        target_id,
                        literals,
                        "{} must serialize canonical chip={} from its generated "
                        "pble_info object".format(obj, target),
                    )

    def test_c3_resolved_configuration_matches_release_contract(self):
        config = _sdkconfig_values(BUILD_ROOT / "esp32-c3" / "sdkconfig")
        expected = {
            "CONFIG_IDF_TARGET": '"esp32c3"',
            "CONFIG_IDF_TARGET_ESP32C3": "y",
            "CONFIG_COMPILER_OPTIMIZATION_SIZE": "y",
            "CONFIG_COMPILER_OPTIMIZATION_PERF": "n",
            "CONFIG_ESP_SYSTEM_HW_STACK_GUARD": "n",
            "CONFIG_ESPTOOLPY_FLASHMODE_DIO": "y",
            "CONFIG_ESPTOOLPY_FLASHMODE": '"dio"',
            "CONFIG_ESPTOOLPY_FLASHFREQ_80M": "y",
            "CONFIG_ESPTOOLPY_FLASHFREQ": '"80m"',
            "CONFIG_ESPTOOLPY_FLASHSIZE_4MB": "y",
            "CONFIG_ESPTOOLPY_FLASHSIZE": '"4MB"',
            "CONFIG_PARTITION_TABLE_CUSTOM": "y",
            "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME": '"partitions.csv"',
            "CONFIG_ESP32C3_REV_MIN_3": "y",
            "CONFIG_ESP32C3_REV_MIN_FULL": "3",
            "CONFIG_ESP32C3_REV_MAX_FULL": "199",
        }
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertEqual(
                    config.get(key),
                    value,
                    "resolved C3 sdkconfig must set {}={}".format(key, value),
                )

    def test_c3_flasher_args_and_esp_headers_are_exact(self):
        build = BUILD_ROOT / "esp32-c3"
        args = json.loads(
            (build / "flasher_args.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            args["flash_settings"],
            {
                "flash_mode": "dio",
                "flash_size": "4MB",
                "flash_freq": "80m",
            },
        )
        self.assertEqual(args["extra_esptool_args"]["chip"], "esp32c3")
        self.assertEqual(
            args["flash_files"],
            {
                "0x0": "bootloader/bootloader.bin",
                "0x8000": "partition_table/partition-table.bin",
                "0x10000": "micropython.bin",
            },
        )

        expected_header = {
            "magic": 0xE9,
            "spi_mode": 2,  # ESP image DIO enum
            "spi_size_freq": 0x2F,  # 4 MiB / 80 MHz
            "chip_id": 5,  # ESP32-C3
            "min_chip_rev_full": 3,
            "max_chip_rev_full": 199,
        }
        for relative in ("bootloader/bootloader.bin", "micropython.bin"):
            with self.subTest(image=relative):
                self.assertEqual(
                    _image_header(build / relative),
                    expected_header,
                    "{} must encode the frozen C3 image contract".format(
                        relative
                    ),
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
