#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for the independent RP2 release-license observer.

The v0.6 release may reuse neither ESP-IDF SBOM conclusions nor a directory
walk presented as linked-input evidence.  These tests intentionally use tiny,
synthetic objects and legally neutral license text.  They freeze the semantic
interfaces and fail-closed properties needed before schema-2 evidence may be
generated; they do not represent a completed legal review.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
RELEASE_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "release_bundle.py"

# These names are local to the synthetic fixture.  The production policy is
# deliberately checked by source coverage and license semantics, never by a
# fixed owner-name or owner-count allowlist.
FIXTURE_SOURCE_ROOTS = {
    "fixture-pyble": (
        ("repo", "firmware/board_overlays/rpi-pico2-w"),
        ("repo", "firmware/pyble"),
        ("repo", "firmware/user_c_modules/pyble"),
    ),
    "fixture-micropython-mit": (
        ("micropython", "drivers"),
        ("micropython", "extmod"),
        ("micropython", "py"),
        ("micropython", "shared"),
    ),
    "fixture-micropython-rp2-mit": (("micropython", "ports/rp2"),),
    "fixture-micropython-rp2-bsd": (
        ("micropython", "ports/rp2/clocks_extra.c"),
        ("micropython", "ports/rp2/mutex_extra.c"),
    ),
    "fixture-micropython-mbedtls-apache": (
        ("micropython", "extmod/mbedtls"),
        ("micropython", "lib/mbedtls_errors"),
    ),
    "fixture-lwip": (("micropython", "lib/lwip"),),
    "fixture-mbedtls-upstream": (("micropython", "lib/mbedtls"),),
    "fixture-littlefs": (("micropython", "lib/littlefs"),),
    "fixture-oofatfs": (("micropython", "lib/oofatfs"),),
    "fixture-libm-mit": (("micropython", "lib/libm/math.c"),),
    "fixture-libm-fdlibm": (("micropython", "lib/libm/sf_sin.c"),),
    "fixture-pico-sdk-bsd": (("micropython", "lib/pico-sdk/src"),),
    "fixture-pico-sdk-printf-mit": (
        (
            "micropython",
            "lib/pico-sdk/src/rp2_common/pico_printf/printf.c",
        ),
    ),
    "fixture-pico-sdk-cmsis-reviewed": (
        (
            "micropython",
            "lib/pico-sdk/src/rp2_common/cmsis/stub/CMSIS/Device/"
            "RP2350/Source/system_RP2350.c",
        ),
    ),
    "fixture-btstack": (("micropython", "lib/btstack"),),
    "fixture-cyw43": (("micropython", "lib/cyw43-driver"),),
    "fixture-tinyusb": (("micropython", "lib/tinyusb"),),
}

FIXTURE_DIRECT_SOURCES = (
    ("fixture-pyble", "repo", "firmware/user_c_modules/pyble/pble_agent.c"),
    ("fixture-micropython-mit", "micropython", "py/runtime.c"),
    ("fixture-micropython-mit", "micropython", "extmod/modmachine.c"),
    ("fixture-micropython-mit", "micropython", "shared/runtime/pyexec.c"),
    ("fixture-micropython-mit", "micropython", "drivers/bus/softspi.c"),
    ("fixture-micropython-rp2-mit", "micropython", "ports/rp2/main.c"),
    (
        "fixture-micropython-rp2-bsd",
        "micropython",
        "ports/rp2/clocks_extra.c",
    ),
    (
        "fixture-micropython-rp2-bsd",
        "micropython",
        "ports/rp2/mutex_extra.c",
    ),
    (
        "fixture-micropython-mbedtls-apache",
        "micropython",
        "extmod/mbedtls/mbedtls_alt.c",
    ),
    (
        "fixture-micropython-mbedtls-apache",
        "micropython",
        "lib/mbedtls_errors/mp_mbedtls_errors.c",
    ),
    ("fixture-lwip", "micropython", "lib/lwip/src/core/init.c"),
    (
        "fixture-mbedtls-upstream",
        "micropython",
        "lib/mbedtls/library/aes.c",
    ),
    ("fixture-littlefs", "micropython", "lib/littlefs/lfs1.c"),
    ("fixture-littlefs", "micropython", "lib/littlefs/lfs2.c"),
    ("fixture-oofatfs", "micropython", "lib/oofatfs/ff.c"),
    ("fixture-libm-mit", "micropython", "lib/libm/math.c"),
    ("fixture-libm-fdlibm", "micropython", "lib/libm/sf_sin.c"),
    (
        "fixture-pico-sdk-bsd",
        "micropython",
        "lib/pico-sdk/src/common/hardware_claim/claim.c",
    ),
    (
        "fixture-pico-sdk-printf-mit",
        "micropython",
        "lib/pico-sdk/src/rp2_common/pico_printf/printf.c",
    ),
    (
        "fixture-pico-sdk-cmsis-reviewed",
        "micropython",
        "lib/pico-sdk/src/rp2_common/cmsis/stub/CMSIS/Device/"
        "RP2350/Source/system_RP2350.c",
    ),
    ("fixture-btstack", "micropython", "lib/btstack/src/hci.c"),
    (
        "fixture-cyw43",
        "micropython",
        "lib/cyw43-driver/src/cyw43_ctrl.c",
    ),
    (
        "fixture-tinyusb",
        "micropython",
        "lib/tinyusb/src/device/usbd.c",
    ),
)

FIXTURE_RUNTIME_ROOTS = {
    "fixture-arm-gcc-runtime": (
        "lib/crti.o",
        "lib/crtbegin.o",
        "lib/libgcc.a",
        "lib/libstdc++.a",
    ),
    "fixture-arm-newlib-runtime": (
        "lib/libg.a",
        "lib/libm.a",
        "lib/libc.a",
    ),
}
FIXTURE_RUNTIME_CONTRIBUTORS = {
    "lib/crti.o": None,
    "lib/crtbegin.o": None,
    "lib/libgcc.a": "shared.o",
    "lib/libg.a": "shared.o",
    "lib/libm.a": "lib_a-sinf.o",
}
FIXTURE_OWNER_IDS = tuple(
    sorted((*FIXTURE_SOURCE_ROOTS, *FIXTURE_RUNTIME_ROOTS))
)
FIXTURE_THIRD_PARTY_IDS = tuple(
    owner for owner in FIXTURE_OWNER_IDS if owner != "fixture-pyble"
)


def load_release_module():
    spec = importlib.util.spec_from_file_location(
        "pyble_release_v060_rp2_license_semantics_red",
        RELEASE_SCRIPT,
    )
    if spec is None or spec.loader is None:
        return None, "cannot load release_bundle.py"
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - surfaced as a skip reason.
        return None, "cannot import release_bundle.py: %s" % exc
    return module, ""


RELEASE, RELEASE_LOAD_ERROR = load_release_module()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def archive_bytes(members: list[tuple[str, bytes]]) -> bytes:
    """Build a tiny deterministic SysV ar fixture without host tooling."""

    result = bytearray(b"!<arch>\n")
    for name, payload in members:
        encoded_name = (name + "/").encode("ascii")
        if len(encoded_name) > 16:
            raise AssertionError("synthetic ar member name is too long")
        header = (
            encoded_name.ljust(16, b" ")
            + b"0".ljust(12, b" ")
            + b"0".ljust(6, b" ")
            + b"0".ljust(6, b" ")
            + b"100644".ljust(8, b" ")
            + str(len(payload)).encode("ascii").ljust(10, b" ")
            + b"`\n"
        )
        result.extend(header)
        result.extend(payload)
        if len(payload) % 2:
            result.extend(b"\n")
    return bytes(result)


def policy_owner_for_path(
    owners: list[dict[str, object]], namespace: str, logical_path: str
) -> dict[str, object]:
    matches: list[tuple[int, dict[str, object]]] = []
    for owner in owners:
        for root in owner["source_roots"]:
            if root["namespace"] != namespace:
                continue
            root_path = root["path"].rstrip("/")
            if logical_path == root_path or logical_path.startswith(root_path + "/"):
                matches.append((len(root_path), owner))
    if not matches:
        raise AssertionError(
            "policy has no %s owner for %s" % (namespace, logical_path)
        )
    specificity = max(length for length, _owner in matches)
    winners = {
        owner["id"]: owner
        for length, owner in matches
        if length == specificity
    }
    if len(winners) != 1:
        raise AssertionError(
            "policy has ambiguous %s owners for %s: %s"
            % (namespace, logical_path, sorted(winners))
        )
    return next(iter(winners.values()))


def owner_license_identifiers(owner: dict[str, object]) -> set[str]:
    return {record["identifier"] for record in owner["license_texts"]}


class RP2SemanticFixture:
    """Synthetic complete-link fixture with one input for every owner."""

    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="pyble-v060-rp2-license-red-"
        )
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        # Production builds live below the checkout.  Keeping the fixture in
        # that conventional layout exercises the narrower build namespace
        # whenever an input is also lexically below the repository root.
        self.build = self.repo / "firmware" / "build"
        self.target = self.build / "rpi-pico2-w"
        self.source = (
            self.build / ".sources" / "rpi-pico2-w" / "micropython"
        )
        self.repo.mkdir()
        self.target.mkdir(parents=True)
        self.source.mkdir(parents=True)
        self._make_sources()
        self._initialize_retained_checkout()
        self._make_build()
        self.policy = self._make_policy()
        self.provenance = json.loads(
            (self.target / "pyble-build-provenance.json").read_text(
                encoding="utf-8"
            )
        )

    def close(self) -> None:
        self.temporary.cleanup()

    def write(self, root: Path, relative: str, value: bytes) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return path

    @staticmethod
    def git(root: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return completed.stdout.strip()

    def _make_sources(self) -> None:
        self.write(
            self.repo,
            "firmware/versions.lock",
            ((
                '[micropython]\ncommit = "%s"\nrepo = '
                '"https://github.com/micropython/micropython"\n'
                'ref = "v1.28.0"\n'
                '[esp_idf]\ncommit = "%s"\nrepo = '
                '"https://github.com/espressif/esp-idf"\n'
                'ref = "v5.5.1"\n'
                '[pyble]\nagent_version = "0.6.0"\n'
                'protocol_version = "PBLE/1"\n'
                '[arm_gnu_toolchain]\nrelease = "14.2.Rel1"\n'
                'gcc_version = "14.2.1 20241119"\n'
                'url = "https://example.invalid/arm-gnu.tar.xz"\n'
                'sha256 = "%s"\n'
            ) % ("1" * 40, "4" * 40, "2" * 64)).encode("utf-8"),
        )
        self.write(
            self.repo,
            "firmware/board_overlays/rpi-pico2-w/manifest.py",
            (
                'module("rp2.py", base_path="$(PORT_DIR)/modules", opt=3)\n'
                'include("$(MPY_DIR)/extmod/asyncio")\n'
            ).encode(),
        )
        self.write(
            self.source,
            "extmod/asyncio/manifest.py",
            (
                'package("asyncio", ("__init__.py", "core.py"), '
                'base_path="..", opt=3)\n'
                'module("uasyncio.py", opt=3)\n'
            ).encode(),
        )
        for relative in (
            "extmod/asyncio/__init__.py",
            "extmod/asyncio/core.py",
            "extmod/asyncio/uasyncio.py",
        ):
            self.write(self.source, relative, b"# synthetic asyncio input\n")

        for owner, namespace, logical_path in FIXTURE_DIRECT_SOURCES:
            root = self.repo if namespace == "repo" else self.source
            self.write(
                root,
                logical_path,
                ("/* synthetic linked source for %s */\n" % owner).encode(),
            )
        for owner in FIXTURE_OWNER_IDS:
            self.write(
                self.repo,
                "firmware/licenses/fixture/%s.txt" % owner,
                ("Synthetic complete reviewed terms for %s.\n" % owner).encode(),
            )
        self.write(
            self.source,
            "lib/pico-sdk/src/rp2_common/pico_btstack/LICENSE.RP",
            b"Synthetic complete BTstack Raspberry Pi grant.\n",
        )
        self.write(
            self.source,
            "lib/btstack/LICENSE",
            b"Synthetic complete BTstack stock restricted terms.\n",
        )
        self.write(
            self.source,
            "lib/cyw43-driver/LICENSE.RP",
            b"Synthetic complete CYW43 Raspberry Pi grant.\n",
        )
        self.write(
            self.source,
            "lib/cyw43-driver/LICENSE",
            b"Synthetic complete CYW43 stock restricted terms.\n",
        )
        self.write(
            self.source,
            "ports/rp2/modules/rp2.py",
            b"# synthetic frozen RP2 module\n",
        )
        for path, value in (
            ("firmware/pyble/pyble_agent.py", b"# synthetic agent\n"),
            (
                "firmware/.arm-gnu/licenses/COPYING3",
                b"Synthetic GPLv3 text.\n",
            ),
            (
                "firmware/.arm-gnu/licenses/GCC-RUNTIME-LIBRARY-EXCEPTION",
                b"Synthetic GCC exception text.\n",
            ),
            (
                "firmware/.arm-gnu/licenses/NEWLIB-COPYING",
                b"Synthetic newlib terms.\n",
            ),
        ):
            self.write(self.repo, path, value)
        for logical_path in {
            path
            for paths in FIXTURE_RUNTIME_ROOTS.values()
            for path in paths
        }:
            member = FIXTURE_RUNTIME_CONTRIBUTORS.get(logical_path)
            value = (
                archive_bytes(
                    [
                        (
                            member,
                            (
                                "synthetic member %s from %s\n"
                                % (member, logical_path)
                            ).encode(),
                        )
                    ]
                )
                if member is not None
                else ("synthetic runtime input %s\n" % logical_path).encode()
            )
            self.write(
                self.repo,
                "firmware/.arm-gnu/%s" % logical_path,
                value,
            )

    def _initialize_retained_checkout(self) -> None:
        self.source_refs: dict[str, tuple[str, str]] = {}
        nested = {
            "fixture-lwip": "lwip",
            "fixture-mbedtls-upstream": "mbedtls",
            "fixture-pico-sdk-bsd": "pico-sdk",
            "fixture-btstack": "btstack",
            "fixture-cyw43": "cyw43-driver",
            "fixture-tinyusb": "tinyusb",
        }
        for owner, directory in nested.items():
            root = self.source / "lib" / directory
            origin = "https://example.invalid/%s" % directory
            self.git(root, "init", "-q")
            self.git(root, "add", "-A")
            self.git(
                root,
                "-c",
                "user.name=PyBLE Test",
                "-c",
                "user.email=test@pyble.dev",
                "commit",
                "-q",
                "-m",
                "synthetic retained source",
            )
            self.git(root, "remote", "add", "origin", origin)
            self.source_refs[owner] = (self.git(root, "rev-parse", "HEAD"), origin)
        for owner in (
            "fixture-pico-sdk-cmsis-reviewed",
            "fixture-pico-sdk-printf-mit",
        ):
            self.source_refs[owner] = self.source_refs["fixture-pico-sdk-bsd"]
        origin = "https://github.com/micropython/micropython"
        self.git(self.source, "init", "-q")
        self.git(self.source, "add", "-A")
        self.git(
            self.source,
            "-c",
            "user.name=PyBLE Test",
            "-c",
            "user.email=test@pyble.dev",
            "commit",
            "-q",
            "-m",
            "synthetic retained MicroPython",
        )
        self.git(self.source, "remote", "add", "origin", origin)
        commit = self.git(self.source, "rev-parse", "HEAD")
        for owner in (
            "fixture-micropython-mit",
            "fixture-micropython-rp2-mit",
            "fixture-micropython-rp2-bsd",
            "fixture-micropython-mbedtls-apache",
            "fixture-littlefs",
            "fixture-oofatfs",
            "fixture-libm-mit",
            "fixture-libm-fdlibm",
        ):
            self.source_refs[owner] = (commit, origin)
        lock = self.repo / "firmware/versions.lock"
        lock.write_text(
            lock.read_text(encoding="utf-8").replace("1" * 40, commit),
            encoding="utf-8",
        )

    def _make_build(self) -> None:
        objects: list[str] = []
        object_owners: dict[str, str] = {}
        self.direct_objects: dict[str, list[str]] = {}
        direct_mappings: list[tuple[Path, Path]] = []
        asm_mappings: list[tuple[Path, Path]] = []
        for index, (owner, namespace, logical_path) in enumerate(
            FIXTURE_DIRECT_SOURCES
        ):
            source = (
                self.repo / logical_path
                if namespace == "repo"
                else self.source / logical_path
            )
            stem = owner.removeprefix("fixture-").replace("-", "_")
            obj = self.write(
                self.target,
                "CMakeFiles/firmware.dir/fixture/%02d_%s.o" % (index, stem),
                (
                    "synthetic linked object %s for %s\n"
                    % (index, owner)
                ).encode(),
            )
            relative = obj.relative_to(self.target).as_posix()
            objects.append(relative)
            object_owners[relative] = owner
            self.direct_objects.setdefault(owner, []).append(relative)
            if logical_path == "ports/rp2/main.c":
                asm_mappings.append((source, obj))
            else:
                direct_mappings.append((source, obj))
        generated_sources = {
            "pins_PYBLE_RPI_PICO2_W.c": "pins_PYBLE_RPI_PICO2_W.c",
            "frozen_content.c": "frozen_content.c",
            "bs2_default_padded_checksummed.S": (
                "pico-sdk/src/rp2350/boot_stage2/bs2_default_padded_checksummed.S"
            ),
        }
        for name, relative in generated_sources.items():
            generated_source = self.write(
                self.target,
                relative,
                ("/* synthetic derived %s */\n" % name).encode(),
            )
            if name == "bs2_default_padded_checksummed.S":
                object_relative = (
                    "pico-sdk/src/rp2350/boot_stage2/CMakeFiles/"
                    "bs2_default_library.dir/bs2_default_padded_checksummed.S.o"
                )
            else:
                object_relative = "CMakeFiles/firmware.dir/generated/%s.o" % name
            generated_object = self.write(
                self.target,
                object_relative,
                ("synthetic derived object %s\n" % name).encode(),
            )
            object_relative = generated_object.relative_to(self.target).as_posix()
            objects.append(object_relative)
            object_owners[object_relative] = "generated"
        runtime_inputs = tuple(
            self.repo / "firmware/.arm-gnu" / logical_path
            for owner in FIXTURE_RUNTIME_ROOTS
            for logical_path in FIXTURE_RUNTIME_ROOTS[owner]
        )
        link = "arm-none-eabi-g++ %s %s -o firmware.elf\n" % (
            " ".join('"%s"' % path for path in objects),
            " ".join('"%s"' % path for path in runtime_inputs),
        )
        self.write(
            self.target,
            "CMakeFiles/firmware.dir/link.txt",
            link.encode(),
        )
        map_records = [
            "Archive member included to satisfy reference by file (symbol)",
            "",
        ]
        map_records.extend(
            "%s(%s)"
            % (self.repo / "firmware/.arm-gnu" / logical_path, member)
            for logical_path, member in FIXTURE_RUNTIME_CONTRIBUTORS.items()
            if member is not None
        )
        map_records.extend(["", "Discarded input sections", ""])
        map_records.extend("LOAD %s" % path for path in objects)
        map_records.extend("LOAD %s" % path for path in runtime_inputs)
        address = 0x10000000
        for path in objects:
            map_records.append(
                " .text.%s 0x%08x 0x4 %s"
                % (object_owners[path].replace("-", "_"), address, path)
            )
            address += 4
        for logical_path, member in FIXTURE_RUNTIME_CONTRIBUTORS.items():
            runtime = self.repo / "firmware/.arm-gnu" / logical_path
            suffix = "(%s)" % member if member is not None else ""
            map_records.append(
                " .text.runtime_%08x 0x%08x 0x4 %s%s"
                % (address, address, runtime, suffix)
            )
            address += 4
        self.write(
            self.target,
            "firmware.elf.map",
            ("\n".join(map_records) + "\n").encode(),
        )
        mappings = []
        for source, output in direct_mappings:
            self.write(
                self.target,
                output.relative_to(self.target).as_posix() + ".d",
                b"synthetic dependency file\n",
            )
            mappings.append(
                '  "%s" "%s" "gcc" "%s.d"'
                % (source, output, output)
            )
        for name, relative in generated_sources.items():
            if name == "bs2_default_padded_checksummed.S":
                continue
            source = self.target / relative
            output = self.target / ("CMakeFiles/firmware.dir/generated/%s.o" % name)
            self.write(
                self.target,
                output.relative_to(self.target).as_posix() + ".d",
                b"synthetic generated dependency file\n",
            )
            mappings.append(
                '  "%s" "%s" "gcc" "%s.d"'
                % (source, output, output)
            )
        self.write(
            self.target,
            "CMakeFiles/firmware.dir/DependInfo.cmake",
            (
                "set(CMAKE_DEPENDS_DEPENDENCY_FILES\n%s\n)\n"
                "set(CMAKE_DEPENDS_CHECK_ASM\n%s\n)\n"
                % (
                    "\n".join(mappings),
                    "\n".join(
                        '  "%s" "%s"' % (source, output)
                        for source, output in asm_mappings
                    ),
                )
            ).encode(),
        )
        bootstage_source = self.target / generated_sources[
            "bs2_default_padded_checksummed.S"
        ]
        bootstage_output = (
            self.target
            / "pico-sdk/src/rp2350/boot_stage2/CMakeFiles/"
            "bs2_default_library.dir/bs2_default_padded_checksummed.S.o"
        )
        self.write(
            self.target,
            "pico-sdk/src/rp2350/boot_stage2/CMakeFiles/"
            "bs2_default_library.dir/DependInfo.cmake",
            (
                'set(CMAKE_DEPENDS_CHECK_ASM\n  "%s" "%s"\n)\n'
                % (bootstage_source, bootstage_output)
            ).encode(),
        )
        self.write(self.target, "firmware.elf", b"\x7fELF synthetic complete\n")
        self.write(
            self.target,
            "CMakeCache.txt",
            (
                "CMAKE_HOME_DIRECTORY:INTERNAL=%s\n"
                "MICROPY_BOARD_DIR:UNINITIALIZED=%s\n"
                "PICO_SDK_PATH:PATH=%s\n"
                % (
                    self.source / "ports/rp2",
                    self.source / "ports/rp2/boards/PYBLE_RPI_PICO2_W",
                    self.source / "lib/pico-sdk",
                )
            ).encode(),
        )
        self.write(
            self.target,
            "genhdr/qstrdefs.preprocessed.h",
            b"/* synthetic generated qstr input */\n",
        )
        self.write(
            self.target,
            "pyble-build-provenance.json",
            canonical_json_bytes(
                {
                    "schema_version": 1,
                    "target": "rpi-pico2-w",
                    "port": "rp2",
                    "board": "PYBLE_RPI_PICO2_W",
                    "source_date_epoch": 1786464000,
                    "pyble": {"commit": "3" * 40, "clean": True},
                    "micropython": {
                        "commit": self.source_refs["fixture-micropython-mit"][0],
                    },
                    "arm_gnu_toolchain": {
                        "release": "14.2.Rel1",
                        "gcc": "arm-none-eabi-gcc 14.2.1 20241119",
                    },
                    "picotool": "picotool v2.3.0 (synthetic)",
                    "firmware_bin_bytes": 4,
                }
            ),
        )

    def _make_policy(self) -> dict[str, object]:
        terms = {
            "fixture-pyble": ("MIT", "MIT"),
            "fixture-micropython-mit": ("MIT", "MIT"),
            "fixture-micropython-rp2-mit": ("MIT", "MIT"),
            "fixture-micropython-rp2-bsd": (
                "BSD-3-Clause",
                "BSD-3-Clause",
            ),
            "fixture-micropython-mbedtls-apache": (
                "Apache-2.0",
                "Apache-2.0",
            ),
            "fixture-lwip": ("BSD-3-Clause", "BSD-3-Clause"),
            "fixture-mbedtls-upstream": (
                "(Apache-2.0 OR GPL-2.0-or-later)",
                "Apache-2.0",
            ),
            "fixture-littlefs": ("BSD-3-Clause", "BSD-3-Clause"),
            "fixture-oofatfs": ("BSD-1-Clause", "BSD-1-Clause"),
            "fixture-libm-mit": ("MIT", "MIT"),
            "fixture-libm-fdlibm": (
                "LicenseRef-PyBLE-Fdlibm-Sun",
                "LicenseRef-PyBLE-Fdlibm-Sun",
            ),
            "fixture-pico-sdk-bsd": (
                "BSD-3-Clause",
                "BSD-3-Clause",
            ),
            "fixture-pico-sdk-printf-mit": ("MIT", "MIT"),
            "fixture-pico-sdk-cmsis-reviewed": (
                "Apache-2.0 AND BSD-3-Clause",
                "Apache-2.0 AND BSD-3-Clause",
            ),
            "fixture-btstack": (
                "(LicenseRef-PyBLE-BTstack-Noncommercial OR "
                "LicenseRef-PyBLE-BTstack-Raspberry-Pi)",
                "LicenseRef-PyBLE-BTstack-Raspberry-Pi",
            ),
            "fixture-cyw43": (
                "(LicenseRef-PyBLE-CYW43-Noncommercial OR "
                "LicenseRef-PyBLE-CYW43-Raspberry-Pi)",
                "LicenseRef-PyBLE-CYW43-Raspberry-Pi",
            ),
            "fixture-tinyusb": ("MIT", "MIT"),
            "fixture-arm-gcc-runtime": (
                "GPL-3.0-or-later WITH GCC-exception-3.1",
                "GPL-3.0-or-later WITH GCC-exception-3.1",
            ),
            "fixture-arm-newlib-runtime": (
                "LicenseRef-PyBLE-Newlib-Multilicense",
                "LicenseRef-PyBLE-Newlib-Multilicense",
            ),
        }
        owners = []
        for owner in FIXTURE_OWNER_IDS:
            roots = FIXTURE_SOURCE_ROOTS.get(owner)
            if roots is None:
                roots = tuple(
                    ("arm-gnu-toolchain", path)
                    for path in FIXTURE_RUNTIME_ROOTS[owner]
                )
            source_expression, selected_expression = terms[owner]
            source_ref, source_url = self._owner_source_identity(owner)
            license_texts = self._owner_license_texts(
                owner,
                source_expression=source_expression,
                selected_expression=selected_expression,
            )
            owners.append(
                {
                    "id": owner,
                    "source_roots": [
                        {"namespace": namespace, "path": path}
                        for namespace, path in sorted(roots)
                    ],
                    "source_ref": source_ref,
                    "source_url": source_url,
                    "source_spdx_expression": source_expression,
                    "selected_spdx_expression": selected_expression,
                    "copyright": "Synthetic copyright for %s" % owner,
                    "license_texts": license_texts,
                    "notice_files": [],
                    "disposition": (
                        "project-owned" if owner == "fixture-pyble" else "allow"
                    ),
                }
            )
        return {
            "schema_version": 1,
            "profile_id": "rpi-pico2-w",
            "target": "rpi-pico2-w",
            "source_owners": owners,
        }

    def _owner_source_identity(self, owner: str) -> tuple[str, str]:
        if owner == "fixture-pyble":
            return "0.6.0", "https://github.com/PyBLE-dev/PyBLE"
        if owner in FIXTURE_RUNTIME_ROOTS:
            return "14.2.Rel1", "https://example.invalid/arm-gnu.tar.xz"
        return self.source_refs[owner]

    def _owner_license_texts(
        self,
        owner: str,
        *,
        source_expression: str,
        selected_expression: str,
    ) -> list[dict[str, str]]:
        if owner == "fixture-btstack":
            records = (
                (
                    "LicenseRef-PyBLE-BTstack-Noncommercial",
                    "build/.sources/rpi-pico2-w/micropython/lib/btstack/LICENSE",
                ),
                (
                    "LicenseRef-PyBLE-BTstack-Raspberry-Pi",
                    "build/.sources/rpi-pico2-w/micropython/lib/pico-sdk/"
                    "src/rp2_common/pico_btstack/LICENSE.RP",
                ),
            )
        elif owner == "fixture-cyw43":
            records = (
                (
                    "LicenseRef-PyBLE-CYW43-Noncommercial",
                    "build/.sources/rpi-pico2-w/micropython/"
                    "lib/cyw43-driver/LICENSE",
                ),
                (
                    "LicenseRef-PyBLE-CYW43-Raspberry-Pi",
                    "build/.sources/rpi-pico2-w/micropython/"
                    "lib/cyw43-driver/LICENSE.RP",
                ),
            )
        elif owner == "fixture-mbedtls-upstream":
            records = tuple(
                (
                    identifier,
                    "repo/firmware/licenses/fixture/%s-%s.txt"
                    % (owner, identifier),
                )
                for identifier in ("Apache-2.0", "GPL-2.0-or-later")
            )
        elif owner == "fixture-pico-sdk-cmsis-reviewed":
            records = tuple(
                (
                    identifier,
                    "repo/firmware/licenses/fixture/%s-%s.txt"
                    % (owner, identifier),
                )
                for identifier in ("Apache-2.0", "BSD-3-Clause")
            )
        elif owner == "fixture-arm-gcc-runtime":
            records = (
                (
                    "GCC-exception-3.1",
                    "repo/firmware/.arm-gnu/licenses/"
                    "GCC-RUNTIME-LIBRARY-EXCEPTION",
                ),
                (
                    "GPL-3.0-or-later",
                    "repo/firmware/.arm-gnu/licenses/COPYING3",
                ),
            )
        elif owner == "fixture-arm-newlib-runtime":
            records = (
                (
                    "LicenseRef-PyBLE-Newlib-Multilicense",
                    "repo/firmware/.arm-gnu/licenses/NEWLIB-COPYING",
                ),
            )
        else:
            records = (
                (
                    selected_expression,
                    "repo/firmware/licenses/fixture/%s.txt" % owner,
                ),
            )
        result = []
        for identifier, logical_path in records:
            prefix, relative = logical_path.split("/", 1)
            file_path = (
                self.repo / relative if prefix == "repo" else self.build / relative
            )
            if not file_path.exists():
                self.write(
                    self.repo,
                    relative,
                    (
                        "Synthetic complete reviewed %s terms for %s.\n"
                        % (identifier, owner)
                    ).encode(),
                )
                file_path = self.repo / relative
            result.append(
                {
                    "identifier": identifier,
                    "path": logical_path,
                    "sha256": digest(file_path.read_bytes()),
                }
            )
        return sorted(result, key=lambda record: record["identifier"])
    def observer(self):
        observer = getattr(RELEASE, "_audit_observe_rp2_license_inputs", None)
        self.assert_callable(observer)
        return observer

    @staticmethod
    def assert_callable(observer) -> None:
        if not callable(observer):
            raise AssertionError(
                "release_bundle.py lacks _audit_observe_rp2_license_inputs"
            )

    def observe(self, policy=None):
        observer = getattr(RELEASE, "_audit_observe_rp2_license_inputs", None)
        self.assert_callable(observer)
        return observer(
            build_root=self.build,
            repo_root=self.repo,
            provenance=self.provenance,
            policy=self.policy if policy is None else policy,
        )


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class RP2PolicyAndObserverContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = RP2SemanticFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_policy_schema_and_owner_catalog_are_exact(self) -> None:
        validate = getattr(RELEASE, "_audit_validate_rp2_license_policy", None)
        self.assertTrue(
            callable(validate),
            "release_bundle.py lacks _audit_validate_rp2_license_policy",
        )
        if not callable(validate):
            return
        validated = validate(
            self.fixture.policy,
            repo_root=self.fixture.repo,
            build_root=self.fixture.build,
        )
        self.assertEqual(set(validated), set(self.fixture.policy))
        self.assertIs(type(validated["schema_version"]), int)
        self.assertEqual(validated["schema_version"], 1)
        self.assertEqual(
            [owner["id"] for owner in validated["source_owners"]],
            list(FIXTURE_OWNER_IDS),
        )
        for owner in validated["source_owners"]:
            self.assertEqual(
                set(owner),
                {
                    "id",
                    "source_roots",
                    "source_ref",
                    "source_url",
                    "source_spdx_expression",
                    "selected_spdx_expression",
                    "copyright",
                    "license_texts",
                    "notice_files",
                    "disposition",
                },
            )
            self.assertTrue(owner["source_roots"])
            self.assertEqual(
                owner["source_roots"],
                sorted(
                    owner["source_roots"],
                    key=lambda record: (record["namespace"], record["path"]),
                ),
            )
            for root in owner["source_roots"]:
                self.assertEqual(set(root), {"namespace", "path"})
                self.assertIn(
                    root["namespace"],
                    {"repo", "micropython", "arm-gnu-toolchain"},
                )
            for record in owner["license_texts"]:
                self.assertEqual(set(record), {"identifier", "path", "sha256"})
            for record in owner["notice_files"]:
                self.assertEqual(set(record), {"path", "sha256"})

    def test_policy_spdx_semantics_and_locked_bytes_fail_closed(self) -> None:
        validate = RELEASE._audit_validate_rp2_license_policy
        policy = copy.deepcopy(self.fixture.policy)
        cmsis = next(
            owner
            for owner in policy["source_owners"]
            if owner["id"] == "fixture-pico-sdk-cmsis-reviewed"
        )
        cmsis["selected_spdx_expression"] = "Apache-2.0 OR BSD-3-Clause"
        with self.assertRaisesRegex(RELEASE.ReleaseError, "SPDX|weakens|terms"):
            validate(
                policy,
                repo_root=self.fixture.repo,
                build_root=self.fixture.build,
            )

        policy = copy.deepcopy(self.fixture.policy)
        ordinary = next(
            owner
            for owner in policy["source_owners"]
            if owner["id"] == "fixture-micropython-mit"
        )
        ordinary["source_spdx_expression"] = "Unknown-9.9"
        ordinary["selected_spdx_expression"] = "Unknown-9.9"
        with self.assertRaisesRegex(RELEASE.ReleaseError, "unknown|SPDX"):
            validate(
                policy,
                repo_root=self.fixture.repo,
                build_root=self.fixture.build,
            )

        policy = copy.deepcopy(self.fixture.policy)
        ordinary = next(
            owner
            for owner in policy["source_owners"]
            if owner["id"] == "fixture-micropython-mit"
        )
        ordinary["source_spdx_expression"] = "LicenseRef-PyBLE-Unbound"
        ordinary["selected_spdx_expression"] = "LicenseRef-PyBLE-Unbound"
        with self.assertRaisesRegex(RELEASE.ReleaseError, "license|cover|text"):
            validate(
                policy,
                repo_root=self.fixture.repo,
                build_root=self.fixture.build,
            )

        policy_path = (
            self.fixture.repo / "firmware/licenses/rp2-license-policy.json"
        )
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_bytes(canonical_json_bytes(self.fixture.policy))
        locked = {
            "inputs": {
                "rp2_license_policy_path": (
                    "firmware/licenses/rp2-license-policy.json"
                ),
                "rp2_license_policy_sha256": digest(policy_path.read_bytes()),
            }
        }
        RELEASE._audit_load_rp2_license_policy(
            self.fixture.repo,
            self.fixture.build,
            locked,
        )
        for label, mutate in (
            (
                "missing-hash",
                lambda value: value["inputs"].pop(
                    "rp2_license_policy_sha256"
                ),
            ),
            (
                "wrong-path",
                lambda value: value["inputs"].__setitem__(
                    "rp2_license_policy_path", "firmware/licenses/missing.json"
                ),
            ),
            (
                "wrong-hash",
                lambda value: value["inputs"].__setitem__(
                    "rp2_license_policy_sha256", "f" * 64
                ),
            ),
        ):
            with self.subTest(label=label):
                changed = copy.deepcopy(locked)
                mutate(changed)
                with self.assertRaises(RELEASE.ReleaseError):
                    RELEASE._audit_load_rp2_license_policy(
                        self.fixture.repo,
                        self.fixture.build,
                        changed,
                    )

    def test_checked_in_policy_is_canonical_and_retains_reviewed_terms(self) -> None:
        path = REPO_ROOT / "firmware/licenses/rp2-license-policy.json"
        self.assertTrue(path.is_file(), "the reviewed RP2 policy is missing")
        if not path.is_file():
            return
        raw = path.read_bytes()
        policy = json.loads(raw.decode("utf-8", errors="strict"))
        self.assertEqual(raw, canonical_json_bytes(policy))
        self.assertEqual(
            set(policy),
            {"schema_version", "profile_id", "target", "source_owners"},
        )
        self.assertIs(type(policy["schema_version"]), int)
        self.assertEqual(policy["schema_version"], 2)
        self.assertEqual(policy["profile_id"], "rpi-pico2-w")
        self.assertEqual(policy["target"], "rpi-pico2-w")
        owners = policy["source_owners"]
        self.assertEqual(
            [owner["id"] for owner in owners],
            sorted(owner["id"] for owner in owners),
        )
        self.assertEqual(
            len({owner["id"] for owner in owners}),
            len(owners),
        )

        exact_terms = {
            ("repo", "firmware/user_c_modules/pyble/pble_agent.c"): (
                "MIT",
                "MIT",
            ),
            ("micropython", "py/runtime.c"): ("MIT", "MIT"),
            ("micropython", "extmod/modmachine.c"): ("MIT", "MIT"),
            ("micropython", "shared/runtime/pyexec.c"): ("MIT", "MIT"),
            ("micropython", "drivers/bus/softspi.c"): ("MIT", "MIT"),
            ("micropython", "ports/rp2/main.c"): ("MIT", "MIT"),
            ("micropython", "ports/rp2/clocks_extra.c"): (
                "BSD-3-Clause",
                "BSD-3-Clause",
            ),
            ("micropython", "ports/rp2/mutex_extra.c"): (
                "BSD-3-Clause",
                "BSD-3-Clause",
            ),
            ("micropython", "extmod/mbedtls/mbedtls_alt.c"): (
                "Apache-2.0",
                "Apache-2.0",
            ),
            (
                "micropython",
                "lib/mbedtls_errors/mp_mbedtls_errors.c",
            ): ("Apache-2.0", "Apache-2.0"),
            ("micropython", "lib/lwip/src/core/init.c"): (
                "BSD-3-Clause",
                "BSD-3-Clause",
            ),
            ("micropython", "lib/mbedtls/library/aes.c"): (
                "(Apache-2.0 OR GPL-2.0-or-later)",
                "Apache-2.0",
            ),
            ("micropython", "lib/littlefs/lfs1.c"): (
                "BSD-3-Clause",
                "BSD-3-Clause",
            ),
            ("micropython", "lib/littlefs/lfs2.c"): (
                "BSD-3-Clause",
                "BSD-3-Clause",
            ),
            ("micropython", "lib/oofatfs/ff.c"): (
                "BSD-1-Clause",
                "BSD-1-Clause",
            ),
            (
                "micropython",
                "lib/pico-sdk/src/common/hardware_claim/claim.c",
            ): ("BSD-3-Clause", "BSD-3-Clause"),
            (
                "micropython",
                "lib/pico-sdk/src/rp2_common/pico_printf/printf.c",
            ): ("MIT", "MIT"),
            ("micropython", "lib/tinyusb/src/device/usbd.c"): ("MIT", "MIT"),
        }
        for (namespace, logical_path), terms in exact_terms.items():
            with self.subTest(logical_path=logical_path):
                owner = policy_owner_for_path(owners, namespace, logical_path)
                self.assertEqual(
                    (
                        owner["source_spdx_expression"],
                        owner["selected_spdx_expression"],
                    ),
                    terms,
                )

        libm_mit = policy_owner_for_path(
            owners, "micropython", "lib/libm/math.c"
        )
        libm_fdlibm = policy_owner_for_path(
            owners, "micropython", "lib/libm/sf_sin.c"
        )
        self.assertNotEqual(libm_mit["id"], libm_fdlibm["id"])
        self.assertEqual(libm_mit["selected_spdx_expression"], "MIT")
        self.assertIn(
            "LicenseRef",
            libm_fdlibm["selected_spdx_expression"],
        )
        self.assertFalse(
            any(
                root["namespace"] == "micropython"
                and root["path"].rstrip("/") == "lib/libm"
                for owner in owners
                for root in owner["source_roots"]
            ),
            "heterogeneous lib/libm cannot be owned by one broad root",
        )

        ordinary_sdk = policy_owner_for_path(
            owners,
            "micropython",
            "lib/pico-sdk/src/common/hardware_claim/claim.c",
        )
        printf_sdk = policy_owner_for_path(
            owners,
            "micropython",
            "lib/pico-sdk/src/rp2_common/pico_printf/printf.c",
        )
        cmsis_sdk = policy_owner_for_path(
            owners,
            "micropython",
            "lib/pico-sdk/src/rp2_common/cmsis/stub/CMSIS/Device/"
            "RP2350/Source/system_RP2350.c",
        )
        self.assertEqual(len({ordinary_sdk["id"], printf_sdk["id"], cmsis_sdk["id"]}), 3)
        self.assertTrue(
            {"Apache-2.0", "BSD-3-Clause"}
            <= owner_license_identifiers(cmsis_sdk)
        )
        self.assertIn("Apache-2.0", cmsis_sdk["source_spdx_expression"])
        self.assertIn("BSD-3-Clause", cmsis_sdk["source_spdx_expression"])

        for dependency, source_path, stock_suffix, grant_suffix in (
            (
                "BTstack",
                "lib/btstack/src/hci.c",
                "lib/btstack/LICENSE",
                "lib/pico-sdk/src/rp2_common/pico_btstack/LICENSE.RP",
            ),
            (
                "CYW43",
                "lib/cyw43-driver/src/cyw43_ctrl.c",
                "lib/cyw43-driver/LICENSE",
                "lib/cyw43-driver/LICENSE.RP",
            ),
        ):
            with self.subTest(dependency=dependency):
                owner = policy_owner_for_path(
                    owners, "micropython", source_path
                )
                self.assertNotEqual(
                    owner["source_spdx_expression"],
                    owner["selected_spdx_expression"],
                )
                records = {
                    record["identifier"]: record
                    for record in owner["license_texts"]
                }
                selected = owner["selected_spdx_expression"]
                self.assertIn(selected, records)
                self.assertTrue(records[selected]["path"].endswith(grant_suffix))
                stock = [
                    identifier
                    for identifier, record in records.items()
                    if record["path"].endswith(stock_suffix)
                ]
                self.assertEqual(len(stock), 1)
                self.assertIn(stock[0], owner["source_spdx_expression"])
                self.assertIn(selected, owner["source_spdx_expression"])

        runtime_owners = {
            owner["id"]: owner
            for owner in owners
            if any(
                root["namespace"] == "arm-gnu-toolchain"
                for root in owner["source_roots"]
            )
        }
        self.assertGreaterEqual(len(runtime_owners), 2)
        runtime_terms = {
            owner["selected_spdx_expression"]
            for owner in runtime_owners.values()
        }
        self.assertTrue(
            any(
                "GPL-3.0-or-later" in expression
                and "GCC-exception-3.1" in expression
                for expression in runtime_terms
            )
        )
        self.assertTrue(
            any(
                "LicenseRef" in expression and "newlib" in expression.lower()
                for expression in runtime_terms
            )
        )
    def test_complete_observation_has_no_owner_or_input_gap(self) -> None:
        observed = self.fixture.observe()
        self.assertTrue(
            {
                "semantic_sha256",
                "input_sha256",
                "owners",
                "notice_records",
                "role_documents",
                "generated_object_derivations",
            }
            <= set(observed),
        )
        self.assertRegex(observed["semantic_sha256"], r"^[0-9a-f]{64}$")
        observed_ids = {owner["id"] for owner in observed["owners"]}
        self.assertEqual(set(FIXTURE_OWNER_IDS), observed_ids)
        contributing = {
            owner["id"] for owner in observed["owners"] if owner["contributing_inputs"]
        }
        self.assertEqual(contributing, observed_ids)
        self.assertEqual(
            {record["id"] for record in observed["notice_records"]},
            set(FIXTURE_THIRD_PARTY_IDS),
        )
        self.assertEqual(
            set(observed["role_documents"]),
            set(RELEASE.RP2_LICENSE_AUDIT_ROLES),
        )
        self.assertTrue(observed["input_sha256"])
        self.assertFalse(
            any(str(self.fixture.root) in key for key in observed["input_sha256"]),
            "semantic receipts must use logical paths, not host paths",
        )
        nested_build = self.fixture.repo / "firmware/build"
        nested_input = self.fixture.write(
            nested_build,
            "rpi-pico2-w/namespace.o",
            b"synthetic nested build input\n",
        )
        self.assertEqual(
            RELEASE._audit_rp2_logical_path(
                nested_input,
                repo_root=self.fixture.repo,
                build_root=nested_build,
            ),
            "build/rpi-pico2-w/namespace.o",
        )

    def test_review_required_is_observable_and_semantically_bound(self) -> None:
        baseline = self.fixture.observe()
        policy = copy.deepcopy(self.fixture.policy)
        selected = next(
            owner
            for owner in policy["source_owners"]
            if owner["id"] == "fixture-arm-newlib-runtime"
        )
        selected["disposition"] = "review-required"
        observed = self.fixture.observe(policy)
        owner = next(
            item
            for item in observed["owners"]
            if item["id"] == selected["id"]
        )
        self.assertEqual(owner["disposition"], "review-required")
        self.assertNotEqual(
            observed["semantic_sha256"], baseline["semantic_sha256"]
        )

    def test_retained_checkout_is_mandatory_and_canonical_source_is_rejected(self) -> None:
        retained = self.fixture.source
        canonical = self.fixture.repo / "firmware/upstream/micropython"
        canonical.parent.mkdir(parents=True)
        shutil.copytree(retained, canonical)
        cache = self.fixture.target / "CMakeCache.txt"
        link = self.fixture.target / "CMakeFiles/firmware.dir/link.txt"
        cache.write_text(
            cache.read_text(encoding="utf-8").replace(str(retained), str(canonical)),
            encoding="utf-8",
        )
        link.write_text(
            link.read_text(encoding="utf-8").replace(str(retained), str(canonical)),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            RELEASE.ReleaseError,
            "retained|\\.sources|canonical|source",
        ):
            self.fixture.observe()

    def test_retained_commit_origin_and_clean_tree_are_recomputed(self) -> None:
        original = copy.deepcopy(self.fixture.provenance)
        self.fixture.provenance["micropython"]["commit"] = "f" * 40
        with self.assertRaises(RELEASE.ReleaseError):
            self.fixture.observe()
        self.fixture.provenance = original
        original_origin = self.fixture.git(
            self.fixture.source, "remote", "get-url", "origin"
        )
        self.fixture.git(
            self.fixture.source,
            "remote",
            "set-url",
            "origin",
            "https://example.invalid/substitute",
        )
        with self.assertRaises(RELEASE.ReleaseError):
            self.fixture.observe()
        self.fixture.git(
            self.fixture.source,
            "remote",
            "set-url",
            "origin",
            original_origin,
        )
        selected = self.fixture.source / "lib/tinyusb/src/device/usbd.c"
        selected.write_bytes(selected.read_bytes() + b"/* dirty */\n")
        with self.assertRaisesRegex(RELEASE.ReleaseError, "dirty|changed|source"):
            self.fixture.observe()

    def test_arbitrary_rp2_board_paths_are_not_treated_as_generated(self) -> None:
        generated = (
            self.fixture.source
            / "ports/rp2/boards/PYBLE_RPI_PICO2_W/generated.c"
        )
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_text("/* generated board input */\n", encoding="utf-8")
        with self.assertRaisesRegex(
            RELEASE.ReleaseError, "board|inventory|untracked|unowned|generated"
        ):
            self.fixture.observe()

    def test_link_command_rejects_shell_response_duplicate_escape_and_map_gaps(self) -> None:
        link = self.fixture.target / "CMakeFiles/firmware.dir/link.txt"
        original_link = link.read_text(encoding="utf-8")
        linker_map = self.fixture.target / "firmware.elf.map"
        original_map = linker_map.read_text(encoding="utf-8")
        first_object = self.fixture.direct_objects["fixture-pyble"][0]
        mutations = {
            "shell": original_link.rstrip() + " ; touch escaped\n",
            "response": original_link.replace(first_object, "@objects.rsp", 1),
            "wrapped-response": original_link.replace(
                first_object, "-Wl,@objects.rsp", 1
            ),
            "duplicate": original_link.replace(
                first_object, "%s %s" % (first_object, first_object), 1
            ),
            "escape": original_link.replace(first_object, "../escaped.o", 1),
        }
        for label, changed in mutations.items():
            with self.subTest(label=label):
                link.write_text(changed, encoding="utf-8")
                with self.assertRaises(RELEASE.ReleaseError):
                    self.fixture.observe()
                link.write_text(original_link, encoding="utf-8")
        with self.subTest(label="map-only-gap"):
            linker_map.write_text(
                original_map + "LOAD CMakeFiles/firmware.dir/unowned.o\n",
                encoding="utf-8",
            )
            with self.assertRaises(RELEASE.ReleaseError):
                self.fixture.observe()

        with self.subTest(label="symlink-parent-bypass"):
            alternate = self.fixture.target / "alternate-link-root"
            alternate.mkdir()
            symlink = self.fixture.target / "linked-parent"
            symlink.symlink_to(alternate, target_is_directory=True)
            changed = original_link.replace(
                first_object,
                "linked-parent/../%s" % first_object,
                1,
            )
            link.write_text(changed, encoding="utf-8")
            with self.assertRaisesRegex(RELEASE.ReleaseError, "symlink|RP2"):
                self.fixture.observe()

    def test_allocated_map_contribution_not_load_presence_defines_shipment(self) -> None:
        linker_map = self.fixture.target / "firmware.elf.map"
        link = self.fixture.target / "CMakeFiles/firmware.dir/link.txt"
        unused = self.fixture.write(
            self.fixture.target,
            "CMakeFiles/firmware.dir/configured-but-unused.o",
            b"synthetic noncontributing object\n",
        )
        link.write_text(
            link.read_text(encoding="utf-8").replace(
                " -o firmware.elf",
                ' "%s" -o firmware.elf' % unused.relative_to(self.fixture.target),
            ),
            encoding="utf-8",
        )
        linker_map.write_text(
            linker_map.read_text(encoding="utf-8")
            + "LOAD %s\n" % unused.relative_to(self.fixture.target),
            encoding="utf-8",
        )
        observed = self.fixture.observe()
        self.assertTrue(
            any(
                record.get("logical_path", "").endswith(
                    "configured-but-unused.o"
                )
                and record.get("contributes") is False
                for owner in observed["owners"]
                for record in owner.get("link_inputs", [])
            ),
            "a command-listed noncontributor must be bound without being shipped",
        )

    def test_runtime_archive_members_are_path_distinct_and_byte_bound(self) -> None:
        observed = self.fixture.observe()
        runtime_records = {
            Path(record["logical_path"]).name: record
            for owner in observed["owners"]
            for record in owner.get("link_inputs", [])
            if record.get("archive_members")
        }
        self.assertIn("libgcc.a", runtime_records)
        self.assertIn("libg.a", runtime_records)
        gcc_member = runtime_records["libgcc.a"]["archive_members"][0]
        newlib_member = runtime_records["libg.a"]["archive_members"][0]
        self.assertEqual(gcc_member["member"], newlib_member["member"])
        self.assertNotEqual(
            gcc_member["member_sha256"],
            newlib_member["member_sha256"],
            "equal basenames in different archives must retain distinct bytes",
        )

        archive = self.fixture.repo / "firmware/.arm-gnu/lib/libgcc.a"
        archive.write_bytes(
            archive_bytes(
                [(gcc_member["member"], b"tampered synthetic member\n")]
            )
        )
        changed = self.fixture.observe()
        self.assertNotEqual(
            observed["semantic_sha256"],
            changed["semantic_sha256"],
            "an archive-member byte mutation must change the semantic receipt",
        )

    def test_generated_linked_objects_require_derivation_not_prefix_ownership(self) -> None:
        generated = (
            "pins_PYBLE_RPI_PICO2_W.c",
            "frozen_content.c",
            "bs2_default_padded_checksummed.S",
        )
        observed = self.fixture.observe()
        derivations = observed.get("generated_object_derivations")
        self.assertIsInstance(derivations, list)
        self.assertEqual(
            {record["generated_source"] for record in derivations},
            set(generated),
        )
        for record in derivations:
            self.assertEqual(
                set(record),
                {
                    "generated_source",
                    "generated_sha256",
                    "linked_object",
                    "linked_object_sha256",
                    "generator_inputs",
                },
            )
            self.assertTrue(record["generator_inputs"])

    def test_depend_info_source_object_bijection_is_exact(self) -> None:
        depend_info = self.fixture.target / "CMakeFiles/firmware.dir/DependInfo.cmake"
        original = depend_info.read_text(encoding="utf-8")
        first = self.fixture.direct_objects["fixture-pyble"][0]
        second = self.fixture.direct_objects["fixture-micropython-mit"][0]
        mutations = {
            "missing-source-map": "\n".join(
                line for line in original.splitlines() if first not in line
            ) + "\n",
            "duplicate-output-map": original.replace(
                second,
                first,
            ),
            "canonical-source-map": original.replace(
                str(self.fixture.source),
                str(self.fixture.repo / "firmware/upstream/micropython"),
            ),
            "duplicate-asm-map": original.replace(
                "set(CMAKE_DEPENDS_CHECK_ASM\n",
                "set(CMAKE_DEPENDS_CHECK_ASM\n"
                + next(
                    line + "\n"
                    for line in original.splitlines()
                    if '"asm"' not in line
                    and "ports/rp2/main.c" in line
                ),
            ),
        }
        for label, changed in mutations.items():
            with self.subTest(label=label):
                depend_info.write_text(changed, encoding="utf-8")
                with self.assertRaises(RELEASE.ReleaseError):
                    self.fixture.observe()
                depend_info.write_text(original, encoding="utf-8")

    def test_ambiguous_missing_and_noncontributing_owner_fail_closed(self) -> None:
        for label, mutate in (
            (
                "ambiguous-root",
                lambda policy: policy["source_owners"][2]["source_roots"].append(
                    copy.deepcopy(policy["source_owners"][1]["source_roots"][0])
                ),
            ),
            (
                "missing-owner",
                lambda policy: policy["source_owners"].pop(
                    next(
                        index
                        for index, owner in enumerate(policy["source_owners"])
                        if owner["id"] == "fixture-tinyusb"
                    )
                ),
            ),
        ):
            with self.subTest(label=label):
                policy = copy.deepcopy(self.fixture.policy)
                mutate(policy)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.fixture.observe(policy)
        link = self.fixture.target / "CMakeFiles/firmware.dir/link.txt"
        linker_map = self.fixture.target / "firmware.elf.map"
        tinyusb_object = self.fixture.direct_objects["fixture-tinyusb"][0]
        link.write_text(
            link.read_text(encoding="utf-8").replace(tinyusb_object, ""),
            encoding="utf-8",
        )
        linker_map.write_text(
            "\n".join(
                line
                for line in linker_map.read_text(encoding="utf-8").splitlines()
                if tinyusb_object not in line
            )
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RELEASE.ReleaseError, "tinyusb|contribut"):
            self.fixture.observe()

    def test_literal_frozen_runtime_and_license_bytes_fail_closed(self) -> None:
        manifest = (
            self.fixture.repo
            / "firmware/board_overlays/rpi-pico2-w/manifest.py"
        )
        original_manifest = manifest.read_text(encoding="utf-8")
        for label, changed in (
            ("execution", "import os\n" + original_manifest),
            (
                "computed",
                'name = "rp2.py"\nmodule(name, base_path="$(PORT_DIR)/modules")\n',
            ),
            (
                "escape",
                'module("../rp2.py", base_path="$(PORT_DIR)/modules")\n',
            ),
            (
                "duplicate",
                original_manifest + original_manifest,
            ),
            (
                "directory-recursion",
                'freeze("$(BOARD_DIR)/pyble", opt=3)\n',
            ),
        ):
            with self.subTest(kind="frozen", mutation=label):
                manifest.write_text(changed, encoding="utf-8")
                with self.assertRaises(RELEASE.ReleaseError):
                    self.fixture.observe()
                manifest.write_text(original_manifest, encoding="utf-8")

        link = self.fixture.target / "CMakeFiles/firmware.dir/link.txt"
        linker_map = self.fixture.target / "firmware.elf.map"
        original_link = link.read_text(encoding="utf-8")
        original_map = linker_map.read_text(encoding="utf-8")
        runtime = str(self.fixture.repo / "firmware/.arm-gnu/lib/libgcc.a")
        link.write_text(
            original_link.replace('"%s"' % runtime, ""),
            encoding="utf-8",
        )
        linker_map.write_text(
            "\n".join(
                line
                for line in linker_map.read_text(encoding="utf-8").splitlines()
                if runtime not in line
            )
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RELEASE.ReleaseError, "libgcc|runtime|owner"):
            self.fixture.observe()
        link.write_text(original_link, encoding="utf-8")
        linker_map.write_text(original_map, encoding="utf-8")

        with self.subTest(runtime="misleading-literal-without-map-proof"):
            linker_map.write_text(
                "\n".join(
                    line
                    for line in original_map.splitlines()
                    if runtime not in line
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                RELEASE.ReleaseError, "libgcc|runtime|map|link"
            ):
                self.fixture.observe()
            linker_map.write_text(original_map, encoding="utf-8")

        with self.subTest(runtime="unpinned-substitution"):
            substitute = self.fixture.write(
                self.fixture.target,
                "unreviewed/libgcc.a",
                (
                    self.fixture.repo / "firmware/.arm-gnu/lib/libgcc.a"
                ).read_bytes(),
            )
            link.write_text(
                original_link.replace(runtime, str(substitute)),
                encoding="utf-8",
            )
            linker_map.write_text(
                original_map.replace(runtime, str(substitute)),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                RELEASE.ReleaseError, "libgcc|runtime|owner|toolchain"
            ):
                self.fixture.observe()
            link.write_text(original_link, encoding="utf-8")
            linker_map.write_text(original_map, encoding="utf-8")

        policy = copy.deepcopy(self.fixture.policy)
        policy["source_owners"][0]["license_texts"][0]["sha256"] = "f" * 64
        with self.assertRaisesRegex(RELEASE.ReleaseError, "license|digest|changed"):
            self.fixture.observe(policy)


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class RP2AuditOrchestrationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = RP2SemanticFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_rp2_observation_is_repeated_and_mutation_aborts_publication(self) -> None:
        observer = getattr(RELEASE, "_audit_observe_rp2_license_inputs", None)
        self.assertTrue(callable(observer))
        if not callable(observer):
            return
        stable = {
            "semantic_sha256": "d" * 64,
            "input_sha256": {"rp2/fixture": "e" * 64},
            "owners": [],
            "notice_records": [],
            "role_documents": {},
            "generated_object_derivations": [],
        }
        mutated = copy.deepcopy(stable)
        mutated["semantic_sha256"] = "f" * 64
        evidence = self.fixture.root / "evidence"
        with (
            mock.patch.object(RELEASE, "_audit_load_tool_lock") as load_lock,
            mock.patch.object(RELEASE, "_audit_load_policy") as load_esp_policy,
            mock.patch.object(
                RELEASE,
                "_audit_load_rp2_license_policy",
                create=True,
                return_value=self.fixture.policy,
            ),
            mock.patch.object(
                RELEASE,
                "_audit_observe_rp2_license_inputs",
                side_effect=(stable, mutated),
            ) as observe,
            mock.patch.object(RELEASE, "_audit_release_licenses_v2") as esp_audit,
        ):
            load_lock.return_value = {
                "inputs": {
                    "excluded_cves_path": "firmware/excluded-cves.json",
                    "license_policy_path": "firmware/license-policy.json",
                    "rp2_license_policy_path": "firmware/licenses/rp2-license-policy.json",
                },
                "_artifact_hashes": {"fixture": "a" * 64},
            }
            excluded = self.fixture.repo / "firmware/excluded-cves.json"
            excluded.parent.mkdir(exist_ok=True)
            excluded.write_text("{}\n", encoding="utf-8")
            load_esp_policy.return_value = {"schema_version": 2}
            esp_audit.return_value = {
                "third_party_licenses": "Synthetic ESP notice.\n",
                "input_sha256": {"esp": "b" * 64},
            }
            with self.assertRaisesRegex(
                RELEASE.ReleaseError,
                "changed|mutation|RP2|semantic",
            ):
                RELEASE.audit_release_licenses(
                    build_root=self.fixture.build,
                    repo_root=self.fixture.repo,
                    evidence_dir=evidence,
                    runner=lambda *_args, **_kwargs: None,
                )
        self.assertEqual(observe.call_count, 2)
        self.assertFalse(evidence.exists())

    def test_review_required_observation_cannot_publish(self) -> None:
        policy = copy.deepcopy(self.fixture.policy)
        policy["source_owners"][-1]["disposition"] = "review-required"
        observed = self.fixture.observe(policy)
        evidence = self.fixture.root / "review-required-evidence"
        with (
            mock.patch.object(
                RELEASE,
                "_audit_load_tool_lock",
                return_value={
                    "inputs": {
                        "excluded_cves_path": "firmware/excluded-cves.json",
                    },
                    "_artifact_hashes": {"fixture": "a" * 64},
                },
            ),
            mock.patch.object(
                RELEASE,
                "_audit_load_policy",
                return_value={"schema_version": 2},
            ),
            mock.patch.object(
                RELEASE,
                "_audit_load_rp2_license_policy",
                return_value=policy,
            ),
            mock.patch.object(
                RELEASE,
                "_audit_observe_rp2_license_inputs",
                return_value=observed,
            ),
            mock.patch.object(RELEASE, "_audit_release_licenses_v2") as esp,
        ):
            excluded = self.fixture.repo / "firmware/excluded-cves.json"
            excluded.parent.mkdir(exist_ok=True)
            excluded.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(RELEASE.ReleaseError, "review-required"):
                RELEASE.audit_release_licenses(
                    build_root=self.fixture.build,
                    repo_root=self.fixture.repo,
                    evidence_dir=evidence,
                    runner=lambda *_args, **_kwargs: None,
                )
        esp.assert_not_called()
        self.assertFalse(evidence.exists())

    def test_public_replay_rejects_live_build_and_policy_mutations(self) -> None:
        helper = getattr(RELEASE, "_audit_verify_rp2_semantic_replay", None)
        self.assertTrue(callable(helper))
        if not callable(helper):
            return
        observed = self.fixture.observe()
        receipt_inputs = {
            "semantic/rp2-license-closure": observed["semantic_sha256"],
            **{
                "rp2-input/%s" % name: value
                for name, value in observed["input_sha256"].items()
            },
        }
        policy_holder = [self.fixture.policy]
        with (
            mock.patch.object(RELEASE, "_audit_load_tool_lock", return_value={}),
            mock.patch.object(
                RELEASE,
                "_audit_load_rp2_license_policy",
                side_effect=lambda *_args: policy_holder[0],
            ),
        ):
            helper(
                receipt_inputs=receipt_inputs,
                persisted_documents=observed["role_documents"],
                build_root=self.fixture.build,
                repo_root=self.fixture.repo,
                provenance=self.fixture.provenance,
            )
            paths = (
                self.fixture.target / "firmware.elf.map",
                self.fixture.target / "CMakeCache.txt",
                self.fixture.target
                / self.fixture.direct_objects["fixture-pyble"][0],
            )
            for path in paths:
                with self.subTest(path=path.name):
                    original = path.read_bytes()
                    path.write_bytes(original + b"\n# post-review mutation\n")
                    try:
                        with self.assertRaises(RELEASE.ReleaseError):
                            helper(
                                receipt_inputs=receipt_inputs,
                                persisted_documents=observed["role_documents"],
                                build_root=self.fixture.build,
                                repo_root=self.fixture.repo,
                                provenance=self.fixture.provenance,
                            )
                    finally:
                        path.write_bytes(original)
            policy_holder[0] = copy.deepcopy(self.fixture.policy)
            policy_holder[0]["source_owners"][-1][
                "disposition"
            ] = "review-required"
            with self.assertRaisesRegex(RELEASE.ReleaseError, "review-required"):
                helper(
                    receipt_inputs=receipt_inputs,
                    persisted_documents=observed["role_documents"],
                    build_root=self.fixture.build,
                    repo_root=self.fixture.repo,
                    provenance=self.fixture.provenance,
                )

    def test_notice_merge_is_semantic_sorted_and_hash_deduplicated(self) -> None:
        merge = getattr(RELEASE, "_audit_merge_release_notices", None)
        self.assertTrue(
            callable(merge),
            "release_bundle.py lacks _audit_merge_release_notices",
        )
        if not callable(merge):
            return
        shared_text = "Synthetic complete shared license text.\n"
        records = [
            {
                "id": owner,
                "name": owner,
                "version_ref": "%040x" % index,
                "source_url": "https://example.invalid/%s" % owner,
                "spdx_expression": "MIT",
                "copyright": "Synthetic copyright",
                "notice_texts": [],
                "license_texts": [
                    {
                        "identifier": "MIT",
                        "sha256": digest(shared_text.encode()),
                        "text": shared_text,
                    }
                ],
            }
            for index, owner in enumerate(reversed(FIXTURE_THIRD_PARTY_IDS), 1)
        ]
        merged = merge(
            esp_notice="Synthetic ESP notice.\n",
            rp2_notice_records=records,
        )
        self.assertTrue(merged.startswith("Synthetic ESP notice.\n"))
        positions = [
            merged.index("Name: %s" % owner)
            for owner in sorted(FIXTURE_THIRD_PARTY_IDS)
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(merged.count(shared_text.strip()), 1)
        self.assertNotIn(str(self.fixture.root), merged)

    def test_structural_role_documents_alone_cannot_generate_v060_evidence(self) -> None:
        evidence = self.fixture.root / "structural-only"
        structural = {
            role: {
                "schema_version": 1,
                "profile_id": "rpi-pico2-w",
                "target": "rpi-pico2-w",
                "resource_kind": "rp2",
                "role": role,
                "build_provenance_sha256": "a" * 64,
                "source_identity": {},
                "inputs": [{"kind": "linked-source", "logical_path": "build/x", "sha256": "b" * 64}],
                "license_inputs": [{"kind": "license", "logical_path": "build/LICENSE", "sha256": "c" * 64}],
            }
            for role in RELEASE.RP2_LICENSE_AUDIT_ROLES
        }
        excluded = self.fixture.repo / "firmware/excluded-cves.json"
        excluded.parent.mkdir(exist_ok=True)
        excluded.write_text("{}\n", encoding="utf-8")

        def esp_only(**kwargs):
            Path(kwargs["evidence_dir"]).mkdir(parents=True)
            return {
                "third_party_licenses": "Synthetic ESP notice.\n",
                "input_sha256": {"esp": "b" * 64},
            }

        with (
            mock.patch.object(
                RELEASE,
                "_audit_load_tool_lock",
                return_value={
                    "inputs": {
                        "excluded_cves_path": "firmware/excluded-cves.json",
                        "license_policy_path": "firmware/license-policy.json",
                        "rp2_license_policy_path": (
                            "firmware/licenses/rp2-license-policy.json"
                        ),
                    },
                    "_artifact_hashes": {"fixture": "a" * 64},
                },
            ),
            mock.patch.object(
                RELEASE,
                "_audit_load_policy",
                return_value={"schema_version": 2},
            ),
            mock.patch.object(
                RELEASE,
                "_audit_load_rp2_license_policy",
                create=True,
                return_value=self.fixture.policy,
            ),
            mock.patch.object(
                RELEASE,
                "_audit_observe_rp2_license_inputs",
                create=True,
                return_value={"role_documents": structural},
            ),
            mock.patch.object(
                RELEASE,
                "_audit_release_licenses_v2",
                side_effect=esp_only,
            ),
        ):
            with self.assertRaises(RELEASE.ReleaseError):
                RELEASE.audit_release_licenses(
                    evidence_dir=evidence,
                    build_root=self.fixture.build,
                    repo_root=self.fixture.repo,
                    runner=lambda *_args, **_kwargs: None,
                )
        self.assertFalse(evidence.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
