#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for the retained-RP2 compiler dependency closure.

This deliberately extends the small RP2 semantic fixture instead of reading a
developer's current build.  It freezes the evidence needed to prove which
source, header, firmware-array, and pinned toolchain bytes compiled into the
Pico 2 W candidate.  The production observer does not implement this contract
yet, so the focused wrapper must remain RED until the matching green change.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shlex
import tarfile
import unittest


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
SEMANTIC_TEST = HERE / "test_release_v060_rp2_license_semantics.py"


def load_semantic_fixture():
    spec = importlib.util.spec_from_file_location(
        "pyble_release_v060_rp2_depfile_fixture", SEMANTIC_TEST
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load RP2 semantic fixture")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SEMANTIC = load_semantic_fixture()
RELEASE = SEMANTIC.RELEASE


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def make_escape(path: str) -> str:
    return (
        path.replace("\\", "\\\\")
        .replace(" ", "\\ ")
        .replace("#", "\\#")
        .replace(":", "\\:")
    )


class RP2DepfileFixture:
    """Add real-shaped depfiles and a retained ARM distribution to the fixture."""

    CYW43_PAYLOADS = (
        "lib/cyw43-driver/firmware/wb43439A0_7_95_49_00_combined.h",
        "lib/cyw43-driver/firmware/cyw43_btfw_43439.h",
        "lib/cyw43-driver/firmware/wifi_nvram_43439.h",
    )
    CYW43_ALTERNATE = "lib/cyw43-driver/firmware/wb4343WA1_alt_combined.h"
    CMSIS_INPUTS = (
        "lib/pico-sdk/src/rp2_common/cmsis/stub/CMSIS/Core/Include/cmsis_compiler.h",
        "lib/pico-sdk/src/rp2_common/cmsis/stub/CMSIS/Core/Include/cmsis_gcc.h",
        "lib/pico-sdk/src/rp2_common/cmsis/stub/CMSIS/Device/RP2350/Include/system_RP2350.h",
        "lib/pico-sdk/src/rp2_common/cmsis/stub/CMSIS/Device/RP2350/Include/RP2350.h",
    )
    LIBM_HEADER = "lib/libm/libm.h"
    GCC_HEADER = "lib/gcc/arm-none-eabi/14.2.1/include/stdint.h"
    NEWLIB_HEADER = "arm-none-eabi/include/sys/reent.h"
    ARCHIVE_NAME = "arm-gnu-toolchain-14.2.rel1-darwin-arm64-arm-none-eabi.tar.xz"
    ARCHIVE_ROOT = "arm-gnu-toolchain-14.2.Rel1-darwin-arm64-arm-none-eabi"
    RELEASE_MANIFEST = "14.2.rel1-darwin-arm64-arm-none-eabi-manifest.txt"

    def __init__(self) -> None:
        self.base = SEMANTIC.RP2SemanticFixture()
        self.repo = self.base.repo
        self.build = self.base.build
        self.target = self.base.target
        self.source = self.base.source
        self.toolchain = self.repo / "firmware/.arm-gnu"
        self._add_retained_dependencies()
        self._extend_policy_roots()
        self._make_toolchain_distribution()
        self._write_cache_identity()
        self._write_depfiles()

    def close(self) -> None:
        self.base.close()

    def write(self, root: Path, relative: str, value: bytes) -> Path:
        return self.base.write(root, relative, value)

    def _commit(self, checkout: Path, message: str) -> None:
        self.base.git(checkout, "add", "-A")
        self.base.git(
            checkout,
            "-c",
            "user.name=PyBLE Test",
            "-c",
            "user.email=test@pyble.dev",
            "commit",
            "-q",
            "-m",
            message,
        )

    def _add_retained_dependencies(self) -> None:
        for relative in self.CYW43_PAYLOADS:
            self.write(self.source, relative, ("/* %s */\n" % relative).encode())
        self.write(
            self.source,
            self.CYW43_ALTERNATE,
            ("/* %s */\n" % self.CYW43_ALTERNATE).encode(),
        )
        for relative in self.CMSIS_INPUTS:
            self.write(self.source, relative, ("/* %s */\n" % relative).encode())
        for relative in (self.LIBM_HEADER, "ports/rp2/escaped header #1.h"):
            self.write(self.source, relative, ("/* %s */\n" % relative).encode())

        # Nested dependency commits and the enclosing retained checkout must
        # all remain clean and mutually consistent after adding fixture bytes.
        self._commit(self.source / "lib/cyw43-driver", "fixture CYW43 payloads")
        self._commit(self.source / "lib/pico-sdk", "fixture CMSIS headers")
        self._commit(self.source, "fixture compiler dependencies")
        root_commit = self.base.git(self.source, "rev-parse", "HEAD")

        lock = self.repo / "firmware/versions.lock"
        lock_data = lock.read_text(encoding="utf-8")
        old_commit = self.base.provenance["micropython"]["commit"]
        lock.write_text(lock_data.replace(old_commit, root_commit), encoding="utf-8")
        self.base.provenance["micropython"]["commit"] = root_commit
        (self.target / "pyble-build-provenance.json").write_bytes(
            SEMANTIC.canonical_json_bytes(self.base.provenance)
        )

        # Rebind every policy owner to the checkout that actually contains its
        # most-specific source root; no owner-name allowlist is involved.
        for owner in self.base.policy["source_owners"]:
            roots = owner["source_roots"]
            if {item["namespace"] for item in roots} != {"micropython"}:
                continue
            first = self.source / roots[0]["path"]
            probe = first if first.is_dir() else first.parent
            checkout = Path(
                self.base.git(probe, "rev-parse", "--show-toplevel")
            )
            owner["source_ref"] = self.base.git(checkout, "rev-parse", "HEAD")
            owner["source_url"] = self.base.git(
                checkout, "remote", "get-url", "origin"
            )

    def _extend_policy_roots(self) -> None:
        owners = {
            owner["id"]: owner for owner in self.base.policy["source_owners"]
        }

        def add(owner_id: str, namespace: str, *paths: str) -> None:
            roots = owners[owner_id]["source_roots"]
            roots.extend({"namespace": namespace, "path": path} for path in paths)
            owners[owner_id]["source_roots"] = sorted(
                roots, key=lambda item: (item["namespace"], item["path"])
            )

        add("fixture-libm-fdlibm", "micropython", self.LIBM_HEADER)
        add(
            "fixture-pico-sdk-cmsis-reviewed",
            "micropython",
            *self.CMSIS_INPUTS,
        )
        add(
            "fixture-arm-gcc-runtime",
            "arm-gnu-toolchain",
            "bin/arm-none-eabi-gcc",
            "bin/arm-none-eabi-g++",
            self.GCC_HEADER,
        )
        add(
            "fixture-arm-newlib-runtime",
            "arm-gnu-toolchain",
            self.NEWLIB_HEADER,
        )

    def _make_toolchain_distribution(self) -> None:
        installed = {
            "bin/arm-none-eabi-gcc": b"synthetic pinned gcc frontend\n",
            "bin/arm-none-eabi-g++": b"synthetic pinned g++ frontend\n",
            self.GCC_HEADER: b"/* synthetic GCC builtin header */\n",
            self.NEWLIB_HEADER: b"/* synthetic newlib target header */\n",
            self.RELEASE_MANIFEST: b"Synthetic official ARM release manifest\n",
        }
        for relative, value in installed.items():
            self.write(self.toolchain, relative, value)

        # Runtime archives/objects observed by the linker are distribution
        # members too, not merely files that happen to be installed.
        for roots in SEMANTIC.FIXTURE_RUNTIME_ROOTS.values():
            for relative in roots:
                installed[relative] = (self.toolchain / relative).read_bytes()

        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:xz") as archive:
            for relative, value in sorted(installed.items()):
                info = tarfile.TarInfo("%s/%s" % (self.ARCHIVE_ROOT, relative))
                info.size = len(value)
                info.mode = 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(value))
        archive_bytes = payload.getvalue()
        archive_path = self.write(
            self.toolchain, ".pyble-dist/%s" % self.ARCHIVE_NAME, archive_bytes
        )

        gcc = self.toolchain / "bin/arm-none-eabi-gcc"
        gxx = self.toolchain / "bin/arm-none-eabi-g++"
        manifest = self.toolchain / self.RELEASE_MANIFEST
        lock = self.repo / "firmware/versions.lock"
        text = lock.read_text(encoding="utf-8")
        text = text.replace('sha256 = "%s"' % ("2" * 64), 'sha256 = "%s"' % sha256(archive_bytes))
        text = text.replace(
            'url = "https://example.invalid/arm-gnu.tar.xz"',
            'url = "https://example.invalid/%s"' % self.ARCHIVE_NAME,
        )
        text += (
            'archive_filename = "%s"\n'
            'archive_bytes = %d\n'
            'archive_format = "tar.xz"\n'
            'archive_root = "%s"\n'
            'release_manifest_path = "%s"\n'
            'release_manifest_sha256 = "%s"\n'
            'c_asm_frontend_path = "bin/arm-none-eabi-gcc"\n'
            'c_asm_frontend_sha256 = "%s"\n'
            'cxx_frontend_path = "bin/arm-none-eabi-g++"\n'
            'cxx_frontend_sha256 = "%s"\n'
            % (
                self.ARCHIVE_NAME,
                archive_path.stat().st_size,
                self.ARCHIVE_ROOT,
                self.RELEASE_MANIFEST,
                sha256(manifest.read_bytes()),
                sha256(gcc.read_bytes()),
                sha256(gxx.read_bytes()),
            )
        )
        lock.write_text(text, encoding="utf-8")

    def _write_cache_identity(self) -> None:
        gcc = self.toolchain / "bin/arm-none-eabi-gcc"
        gxx = self.toolchain / "bin/arm-none-eabi-g++"
        cache = self.target / "CMakeCache.txt"
        cache.write_text(
            cache.read_text(encoding="utf-8")
            + "PICO_BOARD:STRING=pico2_w\n"
            + "PICO_PLATFORM:STRING=rp2350-arm-s\n"
            + "CMAKE_C_COMPILER:STRING=%s\n" % gcc
            + "CMAKE_ASM_COMPILER:STRING=%s\n" % gcc
            + "CMAKE_CXX_COMPILER:STRING=%s\n" % gxx
            + "PICO_COMPILER_CC:FILEPATH=%s\n" % gcc
            + "PICO_COMPILER_ASM:INTERNAL=%s\n" % gcc
            + "PICO_COMPILER_CXX:FILEPATH=%s\n" % gxx,
            encoding="utf-8",
        )
        link = self.target / "CMakeFiles/firmware.dir/link.txt"
        words = shlex.split(link.read_text(encoding="utf-8"))
        words[0] = str(gxx)
        link.write_text(shlex.join(words) + "\n", encoding="utf-8")

    def _write_depfiles(self) -> None:
        mappings = RELEASE._audit_rp2_depend_info(
            self.target / "CMakeFiles/firmware.dir/DependInfo.cmake",
            target_root=self.target,
            repo_root=self.repo,
            source_root=self.source,
        )
        special: dict[str, tuple[Path, ...]] = {
            "cyw43_ctrl.c": tuple(self.source / item for item in self.CYW43_PAYLOADS),
            "system_RP2350.c": tuple(self.source / item for item in self.CMSIS_INPUTS),
            "math.c": (self.source / self.LIBM_HEADER,),
            "pble_agent.c": (
                self.source / "ports/rp2/escaped header #1.h",
                # GCC depfiles can repeat a header reached through separate
                # include paths.  The raw depfile digest binds multiplicity;
                # every token must still be parsed and owner-classified.
                self.source / "ports/rp2/escaped header #1.h",
                self.toolchain / self.GCC_HEADER,
                self.toolchain / self.NEWLIB_HEADER,
            ),
        }
        self.depfiles: list[Path] = []
        for obj, source in mappings.items():
            depfile = Path(str(obj) + ".d")
            if not depfile.is_file():
                # The fixture's ASM mappings mirror the real CMake behavior:
                # their sources are direct evidence and have no compiler depfile.
                continue
            dependencies = (source, *special.get(source.name, ()))
            target = obj.relative_to(self.target.resolve()).as_posix()
            escaped = [make_escape(str(item)) for item in dependencies]
            depfile.write_text(
                "%s: %s \\\n  %s\n"
                % (make_escape(target), escaped[0], " \\\n  ".join(escaped[1:])),
                encoding="utf-8",
            )
            self.depfiles.append(depfile)

    def observe(self, policy=None):
        return self.base.observe(self.base.policy if policy is None else policy)


@unittest.skipUnless(RELEASE is not None, SEMANTIC.RELEASE_LOAD_ERROR)
class RP2CompilerDependencyClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = RP2DepfileFixture()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.close()

    def test_complete_closure_is_canonical_owned_and_hash_bound(self) -> None:
        observed = self.fixture.observe()
        closure = observed.get("compiler_dependency_closure")
        self.assertIsInstance(closure, list)
        self.assertEqual(len(closure), len(self.fixture.depfiles))
        required = {
            *("build/.sources/rpi-pico2-w/micropython/%s" % item for item in self.fixture.CYW43_PAYLOADS),
            *("build/.sources/rpi-pico2-w/micropython/%s" % item for item in self.fixture.CMSIS_INPUTS),
            "build/.sources/rpi-pico2-w/micropython/%s" % self.fixture.LIBM_HEADER,
            "repo/firmware/.arm-gnu/%s" % self.fixture.GCC_HEADER,
            "repo/firmware/.arm-gnu/%s" % self.fixture.NEWLIB_HEADER,
        }
        dependencies = {
            item["logical_path"]: item
            for record in closure
            for item in record["dependencies"]
        }
        self.assertTrue(required <= set(dependencies))
        for record in closure:
            self.assertEqual(
                set(record),
                {
                    "object",
                    "object_sha256",
                    "source",
                    "source_sha256",
                    "depfile",
                    "depfile_sha256",
                    "dependencies",
                },
            )
            for dependency in record["dependencies"]:
                self.assertEqual(
                    set(dependency), {"logical_path", "sha256", "owner_id"}
                )
        self.assertEqual(closure, sorted(closure, key=lambda item: item["object"]))

    def test_depfile_grammar_inventory_and_bytes_fail_closed(self) -> None:
        self.fixture.observe()
        depfile = self.fixture.depfiles[0]
        original = depfile.read_bytes()
        mutations = (
            original + b"hidden.o: hidden.h\n",
            original.replace(b": ", b": $(UNREVIEWED) ", 1),
            original + b"include injected.mk\n",
            original + b"dangling: path\\\n",
        )
        for changed in mutations:
            with self.subTest(changed=changed[-24:]):
                depfile.write_bytes(changed)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.fixture.observe()
                depfile.write_bytes(original)

        depfile.unlink()
        try:
            with self.assertRaises(RELEASE.ReleaseError):
                self.fixture.observe()
        finally:
            depfile.write_bytes(original)

        extra = (
            self.fixture.target
            / "CMakeFiles/firmware.dir/fixture/unowned-extra.o.d"
        )
        extra.write_text(
            "CMakeFiles/firmware.dir/fixture/unowned-extra.o: %s\n"
            % make_escape(str(self.fixture.source / "ports/rp2/main.c")),
            encoding="utf-8",
        )
        try:
            with self.assertRaises(RELEASE.ReleaseError):
                self.fixture.observe()
        finally:
            extra.unlink()

    def test_board_platform_and_all_frontend_identities_are_exact(self) -> None:
        self.fixture.observe()
        cache = self.fixture.target / "CMakeCache.txt"
        original = cache.read_text(encoding="utf-8")
        substitutions = (
            ("PICO_BOARD:STRING=pico2_w", "PICO_BOARD:STRING=pico2"),
            ("PICO_PLATFORM:STRING=rp2350-arm-s", "PICO_PLATFORM:STRING=rp2350-riscv"),
            ("PICO_COMPILER_CC:FILEPATH=", "PICO_COMPILER_CC:FILEPATH=/tmp/"),
            ("PICO_COMPILER_CXX:FILEPATH=", "PICO_COMPILER_CXX:FILEPATH=/tmp/"),
            ("PICO_COMPILER_ASM:INTERNAL=", "PICO_COMPILER_ASM:INTERNAL=/tmp/"),
        )
        for old, new in substitutions:
            with self.subTest(field=old.partition(":")[0]):
                cache.write_text(original.replace(old, new, 1), encoding="utf-8")
                with self.assertRaises(RELEASE.ReleaseError):
                    self.fixture.observe()
                cache.write_text(original, encoding="utf-8")

    def test_official_binary_archive_manifest_and_installed_bytes_are_bound(self) -> None:
        observed = self.fixture.observe()
        distribution = observed.get("toolchain_distribution")
        self.assertIsInstance(distribution, dict)
        self.assertEqual(
            set(distribution),
            {"archive", "release_manifest", "frontends", "installed_inputs"},
        )
        self.assertEqual(distribution["archive"]["filename"], self.fixture.ARCHIVE_NAME)
        self.assertEqual(distribution["archive"]["root"], self.fixture.ARCHIVE_ROOT)
        self.assertEqual(
            {tuple(item["languages"]) for item in distribution["frontends"]},
            {("ASM", "C"), ("CXX",)},
        )

        gcc = self.fixture.toolchain / "bin/arm-none-eabi-gcc"
        original = gcc.read_bytes()
        gcc.write_bytes(original + b"tampered\n")
        try:
            with self.assertRaises(RELEASE.ReleaseError):
                self.fixture.observe()
        finally:
            gcc.write_bytes(original)

    def test_selected_cyw43_payload_set_is_exact(self) -> None:
        observed = self.fixture.observe()
        closure = observed.get("compiler_dependency_closure")
        self.assertIsInstance(closure, list)
        paths = {
            dependency["logical_path"]
            for record in closure
            for dependency in record["dependencies"]
            if "/lib/cyw43-driver/firmware/" in dependency["logical_path"]
        }
        self.assertEqual(
            paths,
            {
                "build/.sources/rpi-pico2-w/micropython/%s" % item
                for item in self.fixture.CYW43_PAYLOADS
            },
        )
        depfile = next(
            path
            for path in self.fixture.depfiles
            if "cyw43_ctrl" in path.read_text(encoding="utf-8")
        )
        original = depfile.read_text(encoding="utf-8")
        depfile.write_text(
            original.rstrip("\n")
            + " \\\n  "
            + make_escape(
                str(self.fixture.source / self.fixture.CYW43_ALTERNATE)
            )
            + "\n",
            encoding="utf-8",
        )
        try:
            with self.assertRaisesRegex(
                RELEASE.ReleaseError, "CYW43|payload|dependency"
            ):
                self.fixture.observe()
        finally:
            depfile.write_text(original, encoding="utf-8")

    def test_custom_license_ref_authority_does_not_cross_owner_boundary(self) -> None:
        validate = RELEASE._audit_validate_rp2_license_policy
        policy = copy.deepcopy(self.fixture.base.policy)
        custom = next(
            owner for owner in policy["source_owners"]
            if owner["id"] == "fixture-libm-fdlibm"
        )
        other = next(
            owner for owner in policy["source_owners"]
            if owner["id"] == "fixture-micropython-mit"
        )
        record = custom["license_texts"].pop()
        other["license_texts"].append(record)
        other["license_texts"] = sorted(
            other["license_texts"], key=lambda item: item["identifier"]
        )
        with self.assertRaises(RELEASE.ReleaseError):
            validate(policy, repo_root=self.fixture.repo, build_root=self.fixture.build)


if __name__ == "__main__":
    unittest.main(verbosity=2)
