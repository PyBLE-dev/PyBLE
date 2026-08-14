#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] BLD-8 — Observe the exact schema-v2 redistributed inputs.
#
# This suite pins one production seam:
#
#   _audit_observe_policy_v2_inputs(
#       policy,
#       *,
#       repo_root,
#       build_root,
#   ) -> list[dict]
#
# The pure policy resolver is covered by test_release_license_policy_v2.py.
# These tests cover the build-side observation boundary and its integration
# with audit_release_licenses.

from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock


BASE_TEST = Path(__file__).with_name("test_release_license_audit.py")


def load_base_module():
    spec = importlib.util.spec_from_file_location(
        "pyble_release_license_audit_v2_integration_fixtures",
        BASE_TEST,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load release-license fixture module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


BASE = load_base_module()
RELEASE = BASE.RELEASE
PROFILE_TARGETS = BASE.PROFILE_TARGETS
PROFILE_ROLES = BASE.PROFILE_ROLES
RELEASE_LOAD_ERROR = BASE.RELEASE_LOAD_ERROR
CANDIDATE_MARKER = BASE.CANDIDATE_MARKER
extract_notice = BASE.extract_notice
patched_bytes = BASE.patched_bytes
MICROPYTHON_ORIGIN = "https://github.com/micropython/micropython"


def fixture_git(checkout: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(checkout), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "fixture git failed: %s\n%s"
            % (" ".join(arguments), completed.stderr)
        )
    return completed.stdout.strip()


def archive_id(name: str, profile_id: str, role: str) -> str:
    return "%s--%s--%s" % (name, profile_id, role)


def spdx_package_id(identifier: str) -> str:
    return "SPDXRef-Package-" + re.sub(r"[^A-Za-z0-9.-]", "-", identifier)


def tar_xz_bytes(root_name: str, files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(
        fileobj=output,
        mode="w:xz",
        format=tarfile.PAX_FORMAT,
    ) as archive:
        for relative, value in sorted(files.items()):
            info = tarfile.TarInfo("%s/%s" % (root_name, relative))
            info.size = len(value)
            info.mode = 0o755 if relative.startswith("bin/") else 0o644
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            archive.addfile(info, io.BytesIO(value))
    return output.getvalue()


@contextmanager
def changed_json(path: Path, mutation):
    before = path.read_bytes()
    try:
        value = json.loads(before)
        mutation(value)
        BASE.write_json(path, value)
        yield
    finally:
        path.write_bytes(before)


@contextmanager
def installed_policy(fixture, policy: dict):
    before_policy = fixture.policy_path.read_bytes()
    before_lock = fixture.lock_path.read_bytes()
    try:
        BASE.write_json(fixture.policy_path, policy)
        fixture.refresh_locked_policy_hash()
        yield
    finally:
        fixture.policy_path.write_bytes(before_policy)
        fixture.lock_path.write_bytes(before_lock)


MAIN_GENERATED_HEADERS = (
    "compressed.data.h",
    "moduledefs.h",
    "mpversion.h",
    "pins.h",
    "qstrdefs.generated.h",
    "root_pointers.h",
)


def write_ninja_link_graph(
    role_root: Path,
    *,
    app_elf: str,
    compiler: str,
    explicit_inputs: list[str],
    implicit_inputs: list[str],
    link_libraries: list[str],
) -> dict:
    """Write the exact bounded Ninja final-link shape frozen by BLD-8."""

    rule_name = "CXX_LINK" if compiler.endswith("++") else "C_LINK"
    description = (
        "Linking CXX executable $TARGET_FILE"
        if rule_name == "CXX_LINK"
        else "Linking C executable $TARGET_FILE"
    )
    build_ninja = role_root / "build.ninja"
    rules_ninja = role_root / "CMakeFiles" / "rules.ninja"
    rules_ninja.parent.mkdir(parents=True, exist_ok=True)
    build_ninja.write_text(
        "# exact synthetic CMake Ninja graph\n"
        "include CMakeFiles/rules.ninja\n"
        "build %s: %s %s | %s || graph-order\n"
        % (
            app_elf,
            rule_name,
            " ".join(explicit_inputs),
            " ".join(implicit_inputs),
        )
        + "  FLAGS =\n"
        + "  LINK_FLAGS =\n"
        + "  LINK_LIBRARIES = %s\n" % " ".join(link_libraries)
        + "  LINK_PATH =\n"
        + "  OBJECT_DIR = CMakeFiles/%s.dir\n" % app_elf
        + "  POST_BUILD = :\n"
        + "  PRE_LINK = :\n"
        + "  TARGET_COMPILE_PDB = CMakeFiles/%s.dir/\n" % app_elf
        + "  TARGET_FILE = %s\n" % app_elf
        + "  TARGET_PDB = %s.pdb\n" % app_elf,
        encoding="utf-8",
    )
    rules_ninja.write_text(
        "rule %s\n" % rule_name
        + "  command = $PRE_LINK && %s $FLAGS $LINK_FLAGS $in "
        "-o $TARGET_FILE $LINK_PATH $LINK_LIBRARIES && $POST_BUILD\n"
        % compiler
        + "  description = %s\n" % description
        + "  restat = $RESTAT\n",
        encoding="utf-8",
    )
    argv = [compiler, *explicit_inputs, "-o", app_elf, *link_libraries]
    canonical_argv = (
        json.dumps(argv, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return {
        "argv": argv,
        "build_ninja_path": build_ninja,
        "build_ninja_sha256": BASE.sha256_path(build_ninja),
        "rules_ninja_path": rules_ninja,
        "rules_ninja_sha256": BASE.sha256_path(rules_ninja),
        "linker_command_sha256": hashlib.sha256(canonical_argv).hexdigest(),
    }


@contextmanager
def real_idf_main_topology(fixture):
    """Install the source/output shapes emitted by the real ESP32 build."""

    profile_id = "esp32-4mb"
    target = "esp32"
    idf_target = "esp32"
    role_root = fixture.build_root / target
    description_path = role_root / "project_description.json"
    commands_path = role_root / "compile_commands.json"
    map_path = role_root / "micropython.map"
    baseline_link = fixture.ninja_links[(target, "application")]
    archive = baseline_link["main_archive"]
    command_directory = role_root / "compiler-working-directory"
    command_directory.mkdir(parents=True, exist_ok=True)

    pyble_source = (
        fixture.firmware
        / "user_c_modules"
        / "pyble"
        / "pble_proto.c"
    )
    berkeley_source = (
        fixture.build_root
        / ".sources"
        / target
        / "micropython"
        / "lib"
        / "berkeley-db-1.xx"
        / "btree"
        / "bt_close.c"
    )
    project_source = role_root / "project_elf_src_esp32.c"
    build_only_source = (
        fixture.firmware / "components" / "app_core" / "build_only.c"
    )
    main_source = baseline_link["main_source"]

    app_output_relative = baseline_link["main_output_relative"]
    pyble_archive_output_relative = (
        "esp-idf/main/CMakeFiles/main.dir/%s.obj"
        % pyble_source.as_posix().lstrip("/")
    )
    pyble_direct_output_relative = (
        "CMakeFiles/micropython.elf.dir/%s.obj"
        % pyble_source.as_posix().lstrip("/")
    )
    berkeley_direct_output_relative = (
        "esp-idf/main/CMakeFiles/micropy_extmod_btree.dir/%s.obj"
        % berkeley_source.as_posix().lstrip("/")
    )
    project_output_relative = (
        "CMakeFiles/micropython.elf.dir/"
        "project_elf_src_esp32.c.obj"
    )
    build_only_output_relative = (
        "build-only/CMakeFiles/generator.dir/build_only.c.obj"
    )
    direct_loads = {
        "project": project_output_relative,
        "pyble": pyble_direct_output_relative,
        "berkeley": berkeley_direct_output_relative,
    }
    build_ninja_path = role_root / "build.ninja"
    rules_ninja_path = role_root / "CMakeFiles" / "rules.ninja"

    generated_headers = [
        role_root / "genhdr" / name for name in MAIN_GENERATED_HEADERS
    ]
    output_values = {
        role_root / app_output_relative: b"synthetic app-core object\n",
        role_root
        / pyble_archive_output_relative: b"synthetic archived PyBLE object\n",
        role_root
        / pyble_direct_output_relative: b"synthetic direct PyBLE object\n",
        role_root
        / berkeley_direct_output_relative: b"synthetic direct Berkeley object\n",
        role_root
        / project_output_relative: b"synthetic empty-anchor object\n",
        role_root
        / build_only_output_relative: b"synthetic unlinked generator object\n",
    }

    tracked: dict[Path, bytes | None] = {}

    def write_bytes(path: Path, value: bytes) -> None:
        if path not in tracked:
            tracked[path] = (
                path.read_bytes() if path.exists() or path.is_symlink() else None
            )
        if path.is_symlink():
            path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    def write_json(path: Path, value) -> None:
        write_bytes(
            path,
            (
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                + "\n"
            ).encode("utf-8"),
        )

    try:
        for index, header in enumerate(generated_headers):
            write_bytes(
                header,
                (
                    "/* synthetic generated main header %d */\n" % index
                ).encode("utf-8"),
            )
        write_bytes(project_source, b"")
        write_bytes(
            build_only_source,
            b"// SPDX-License-Identifier: MIT\n"
            b"int fixture_build_only(void) { return 1; }\n",
        )
        for output, value in output_values.items():
            write_bytes(output, value)
        write_bytes(
            archive,
            BASE.make_ar_bytes(
                [
                    ("fixture_main.o", output_values[role_root / app_output_relative]),
                    (
                        "pble_proto.c.obj",
                        output_values[role_root / pyble_archive_output_relative],
                    ),
                ]
            ),
        )

        description = json.loads(description_path.read_text(encoding="utf-8"))
        component = description["build_component_info"]["main"]
        component.update(
            {
                "file": str(archive),
                "lib": "main",
                "sources": [
                    str(main_source),
                    str(build_only_source),
                    *(str(path) for path in generated_headers),
                ],
            }
        )
        write_json(description_path, description)

        commands = json.loads(commands_path.read_text(encoding="utf-8"))
        main_command = next(
            command
            for command in commands
            if command["file"] == str(main_source)
        )
        main_command["directory"] = str(command_directory)
        main_command["output"] = app_output_relative
        main_command["command"] = re.sub(
            r"(?<= -o )\S+",
            "../" + app_output_relative,
            main_command["command"],
            count=1,
        )
        compiler = baseline_link["argv"][0]

        def compile_command(source: Path, output_relative: str) -> dict:
            return {
                "directory": str(role_root),
                "command": "%s -c %s -o %s"
                % (compiler, source, output_relative),
                "file": str(source),
                "output": output_relative,
            }

        commands.extend(
            [
                compile_command(pyble_source, pyble_archive_output_relative),
                compile_command(pyble_source, pyble_direct_output_relative),
                compile_command(berkeley_source, berkeley_direct_output_relative),
                compile_command(build_only_source, build_only_output_relative),
            ]
        )
        write_json(commands_path, commands)

        map_text = map_path.read_text(encoding="utf-8")
        map_text = map_text.replace(
            "Linker script and memory map",
            (
                "%s(pble_proto.c.obj)\n"
                "                              (fixture_pble_proto)\n\n"
                "Linker script and memory map"
            )
            % baseline_link["main_archive_relative"],
            1,
        )
        map_text += "".join(
            "LOAD %s\n" % value
            for name, value in direct_loads.items()
            if name != "project"
        )
        write_bytes(map_path, map_text.encode("utf-8"))

        archives = [
            match.group(1)
            for line in map_text.splitlines()
            if (match := re.fullmatch(r"LOAD (\S+\.a)", line)) is not None
        ]
        write_bytes(build_ninja_path, build_ninja_path.read_bytes())
        write_bytes(rules_ninja_path, rules_ninja_path.read_bytes())
        graph = write_ninja_link_graph(
            role_root,
            app_elf="micropython.elf",
            compiler=compiler,
            explicit_inputs=[
                direct_loads["project"],
                direct_loads["pyble"],
            ],
            implicit_inputs=[direct_loads["berkeley"], *archives],
            link_libraries=[direct_loads["berkeley"], *archives],
        )

        policy = copy.deepcopy(fixture.policy)
        identifier = archive_id("main", profile_id, "application")
        yield {
            "policy": policy,
            "identifier": identifier,
            "role_root": role_root,
            "description_path": description_path,
            "commands_path": commands_path,
            "map_path": map_path,
            **graph,
            "archive": archive,
            "generated_headers": generated_headers,
            "main_source": main_source,
            "pyble_source": pyble_source,
            "berkeley_source": berkeley_source,
            "project_source": project_source,
            "build_only_source": build_only_source,
            "direct_loads": direct_loads,
            "outputs": {
                "app": app_output_relative,
                "pyble_archive": pyble_archive_output_relative,
                "pyble_direct": pyble_direct_output_relative,
                "berkeley_direct": berkeley_direct_output_relative,
                "project": project_output_relative,
                "build_only": build_only_output_relative,
            },
        }
    finally:
        for path, before in reversed(list(tracked.items())):
            if path.exists() or path.is_symlink():
                path.unlink()
            if before is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(before)


class FrozenTagValueRunner(BASE.FakeTagValueSbomRunner):
    """Keep raw SPDX independent of the policy file replaced during a v2 run."""

    def __init__(self, fixture):
        super().__init__(fixture)
        self._documents = {}
        for identity in PROFILE_ROLES:
            document = BASE.FakeOfflineSbomRunner.spdx_document(
                self,
                *identity,
            )
            document["packages"] = [
                package
                for package in document["packages"]
                if package["SPDXID"]
                != spdx_package_id("fixture-neopixel")
            ]
            self._documents[identity] = document

    def spdx_document(self, profile_id: str, role: str) -> dict:
        return copy.deepcopy(self._documents[(profile_id, role)])


class ObservationV2Fixture:
    """Schema-v2 policy over real project descriptions, maps, and archives."""

    FROZEN_OBJECT_PREFIX = b"synthetic compiled frozen object\n"

    MBED_COMPONENTS = (
        ("mbedcrypto", "aes.o"),
        ("mbedtls", "ssl_tls.o"),
        ("mbedx509", "x509.o"),
    )

    def __init__(self):
        self.base = BASE.ReleaseLicenseFixture()
        self.root = self.base.root
        self.repo = self.base.repo
        self.build_root = self.base.build_root
        self.evidence = self.base.evidence
        self.firmware = self.base.firmware
        self.policy_path = self.base.policy_path
        self.lock_path = self.base.lock_path
        self.legacy_policy = self.base.policy()
        self._install_main_auxiliary_source_fixtures()
        self._install_first_party_waveshare_frozen_fixtures()
        self._install_frozen_proof_fixture()
        self._install_external_toolchain()
        self._install_frozen_object_bindings()
        self._add_mbedtls_archives()
        self._install_compile_output_fixtures()
        self._rewrite_maps()
        self._install_ninja_link_fixtures()
        self._install_retained_source_checkouts()
        self.runner = FrozenTagValueRunner(self.base)
        self.expected_inputs = self._make_expected_inputs()
        self.policy = self._make_policy()
        self.observed_documents = {
            (record["profile_id"], record["role"]): {
                "packages": copy.deepcopy(record["packages"]),
                "relationships": copy.deepcopy(record["relationships"]),
            }
            for record in self.policy["raw_documents"]
        }

    def _install_main_auxiliary_source_fixtures(self):
        """Install the two non-component source roots emitted by real ESP-IDF."""

        pyble = self.firmware / "user_c_modules" / "pyble"
        pyble.mkdir(parents=True)
        for name in (
            "pble_proto.c",
            "pble_ble.c",
        ):
            (pyble / name).write_text(
                "// SPDX-License-Identifier: MIT\n"
                "int fixture_%s(void) { return 1; }\n"
                % name.removesuffix(".c"),
                encoding="utf-8",
            )

        berkeley = (
            self.firmware
            / "upstream"
            / "micropython"
            / "lib"
            / "berkeley-db-1.xx"
            / "btree"
        )
        berkeley.mkdir(parents=True)
        (berkeley / "bt_close.c").write_text(
            "/* SPDX-License-Identifier: BSD-3-Clause */\n"
            "int fixture_bt_close(void) { return 1; }\n",
            encoding="utf-8",
        )

    def _install_first_party_waveshare_frozen_fixtures(self):
        """Install exact-board-only first-party frozen Python sources."""

        canonical = self.firmware / "python_modules" / "pyble_st7789.py"
        canonical.parent.mkdir(parents=True)
        canonical.write_text(
            "# SPDX-License-Identifier: MIT\n"
            "# Synthetic first-party PyBLE ST7789 fixture.\n"
            "class ST7789:\n"
            "    pass\n",
            encoding="utf-8",
        )
        companion = (
            self.firmware
            / "board_overlays"
            / "waveshare-esp32-s3-lcd-147b"
            / "pyble_waveshare_lcd147b.py"
        )
        companion.write_text(
            "# SPDX-License-Identifier: MIT\n"
            "# Synthetic first-party PyBLE Waveshare LCD fixture.\n",
            encoding="utf-8",
        )
        waveshare_manifest = (
            self.firmware
            / "board_overlays"
            / "waveshare-esp32-s3-lcd-147b"
            / "manifest.py"
        )
        with waveshare_manifest.open("a", encoding="utf-8") as output:
            output.write(
                'module("pyble_st7789.py", base_path="$(BOARD_DIR)")\n'
                'module("pyble_waveshare_lcd147b.py", '
                'base_path="$(BOARD_DIR)")\n'
            )

    def close(self):
        self.base.close()

    def _install_retained_source_checkouts(self):
        """Bind each synthetic build to one pinned, target-local checkout."""

        canonical = self.firmware / "upstream" / "micropython"
        generated_backup = self.root / "generated-board-staging"
        generated_backup.mkdir()
        generated_boards = []
        try:
            for _profile_id, target, _idf_target in PROFILE_TARGETS:
                board_name = RELEASE.FROZEN_TARGET_SETTINGS[target]["board"]
                board = (
                    canonical
                    / "ports"
                    / "esp32"
                    / "boards"
                    / board_name
                )
                backup = generated_backup / target
                board.rename(backup)
                generated_boards.append((board, backup))

            fixture_git(canonical, "init", "-q")
            fixture_git(canonical, "config", "user.name", "PyBLE Test")
            fixture_git(canonical, "config", "user.email", "test@pyble.invalid")
            fixture_git(canonical, "add", ".")
            fixture_git(
                canonical,
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-q",
                "-m",
                "synthetic pinned MicroPython",
            )
        finally:
            for board, backup in reversed(generated_boards):
                backup.rename(board)
            generated_backup.rmdir()
        commit = fixture_git(canonical, "rev-parse", "HEAD")
        fixture_git(
            canonical,
            "remote",
            "add",
            "origin",
            MICROPYTHON_ORIGIN,
        )
        self.micropython_commit = commit
        self.esp_idf_commit = "1" * 40
        (self.firmware / "versions.lock").write_text(
            (
                '[micropython]\nrepo = "%s"\nref = "v1.28.0"\n'
                'commit = "%s"\n\n'
                '[esp_idf]\nrepo = "https://github.com/espressif/esp-idf"\n'
                'ref = "v5.5.1"\ncommit = "%s"\n\n'
                '[pyble]\nagent_version = "0.5.0"\n'
                'protocol_version = "PBLE/1"\n'
            )
            % (MICROPYTHON_ORIGIN, commit, self.esp_idf_commit),
            encoding="utf-8",
        )

        records = []
        for _profile_id, target, _idf_target in PROFILE_TARGETS:
            checkout = (
                self.build_root
                / ".sources"
                / target
                / "micropython"
            )
            checkout.parent.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run(
                [
                    "git",
                    "clone",
                    "--quiet",
                    "--no-hardlinks",
                    str(canonical),
                    str(checkout),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if completed.returncode != 0:
                raise AssertionError(completed.stderr)
            fixture_git(
                checkout,
                "remote",
                "set-url",
                "origin",
                MICROPYTHON_ORIGIN,
            )
            board_name = RELEASE.FROZEN_TARGET_SETTINGS[target]["board"]
            shutil.copytree(
                canonical
                / "ports"
                / "esp32"
                / "boards"
                / board_name,
                checkout
                / "ports"
                / "esp32"
                / "boards"
                / board_name,
            )
            description_path = (
                self.build_root / target / "project_description.json"
            )
            description = json.loads(
                description_path.read_text(encoding="utf-8")
            )
            description["project_path"] = str(
                checkout / "ports" / "esp32"
            )
            BASE.write_json(description_path, description)
            provenance_path = (
                self.build_root
                / target
                / "pyble-build-provenance.json"
            )
            provenance = json.loads(
                provenance_path.read_text(encoding="utf-8")
            )
            provenance["micropython"]["commit"] = commit
            provenance["esp_idf"]["commit"] = self.esp_idf_commit
            BASE.write_json(provenance_path, provenance)
            records.append(
                {
                    "target": target,
                    "project_path": (
                        ".sources/%s/micropython/ports/esp32" % target
                    ),
                    "project_description_sha256": BASE.sha256_path(
                        description_path
                    ),
                    "commit": commit,
                    "origin": MICROPYTHON_ORIGIN,
                }
            )
        self.retained_source_records = sorted(
            records,
            key=lambda record: record["target"],
        )

    def rebind_build_provenance(self):
        """Restore retained source identity after another fixture copies inputs."""

        for _profile_id, target, _idf_target in PROFILE_TARGETS:
            provenance_path = (
                self.build_root
                / target
                / "pyble-build-provenance.json"
            )
            provenance = json.loads(
                provenance_path.read_text(encoding="utf-8")
            )
            provenance["micropython"]["commit"] = self.micropython_commit
            provenance["esp_idf"]["commit"] = self.esp_idf_commit
            BASE.write_json(provenance_path, provenance)

    def _install_frozen_proof_fixture(self):
        """Install a deterministic synthetic clean-reconstruction toolchain."""

        micropython = self.firmware / "upstream" / "micropython"
        generator_files = {
            "mpy-cross/mpy_cross/__init__.py": (
                "# synthetic mpy_cross package fixture\n"
            ),
            "py/makeqstrdata.py": "# synthetic qstr generator fixture\n",
            "tools/manifestfile.py": "# synthetic manifest parser fixture\n",
            "tools/mpy-tool.py": """#!/usr/bin/env python3
from pathlib import Path
import hashlib
import sys

files = [Path(value) for value in sys.argv[1:] if value.endswith(".mpy")]
qstr = Path(sys.argv[sys.argv.index("-q") + 1])
print("// qstr-sha256: %s" % hashlib.sha256(qstr.read_bytes()).hexdigest())
for path in files:
    parts = path.parts
    root_index = parts.index("frozen_mpy")
    relative = Path(*parts[root_index + 1 :]).as_posix()
    destination = relative[:-4] + ".py"
    print("// - original source file: %s" % path)
    print("// - frozen file name: %s" % destination)
    print("// mpy-sha256 %s: %s" % (destination, path.read_bytes().hex()))
""",
        }
        for relative, value in generator_files.items():
            path = micropython / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-8")

        mpy_cross_source = micropython / "mpy-cross" / "fixture-mpy-cross.sh"
        mpy_cross_source.write_text(
            "#!/bin/sh\n# synthetic source-built mpy-cross fixture\nexit 0\n",
            encoding="utf-8",
        )
        mpy_cross_source.chmod(0o755)
        (micropython / "mpy-cross" / "Makefile").write_text(
            "BUILD ?= build\n"
            ".PHONY: all\n"
            "all:\n"
            '\t@/bin/mkdir -p "$(BUILD)"\n'
            '\t@/bin/cp fixture-mpy-cross.sh "$(BUILD)/mpy-cross"\n'
            '\t@/bin/chmod 755 "$(BUILD)/mpy-cross"\n',
            encoding="utf-8",
        )
        mpy_cross = micropython / "mpy-cross" / "build" / "mpy-cross"
        mpy_cross.parent.mkdir(parents=True, exist_ok=True)
        mpy_cross.write_bytes(mpy_cross_source.read_bytes())
        mpy_cross.chmod(0o755)

        makemanifest = micropython / "tools" / "makemanifest.py"
        makemanifest.write_text(
            """#!/usr/bin/env python3
import hashlib
import os
from pathlib import Path
import sys

arguments = sys.argv[1:]
variables = {}
index = 0
while index < len(arguments):
    if arguments[index] == "-v":
        name, value = arguments[index + 1].split("=", 1)
        variables[name] = Path(value)
        index += 2
        continue
    index += 1
output = Path(arguments[arguments.index("-o") + 1])
build = Path(arguments[arguments.index("-b") + 1])
architecture = next(
    value.split("=", 1)[1]
    for value in arguments
    if value.startswith("-f-march=")
)
mpy = variables["MPY_DIR"]
port = variables["PORT_DIR"]
board = variables["BOARD_DIR"]
sources = (
    ("flashbdev.py", port / "modules" / "flashbdev.py"),
    ("inisetup.py", port / "modules" / "inisetup.py"),
    ("asyncio/__init__.py", mpy / "extmod" / "asyncio" / "__init__.py"),
    ("asyncio/core.py", mpy / "extmod" / "asyncio" / "core.py"),
    (
        "neopixel.py",
        mpy
        / "lib"
        / "micropython-lib"
        / "micropython"
        / "drivers"
        / "led"
        / "neopixel"
        / "neopixel.py",
    ),
    ("_boot.py", board / "_boot.py"),
    ("pyble/pyble_agent.py", board / "pyble" / "pyble_agent.py"),
)
if (board / "pyble_st7789.py").is_file():
    sources += (("pyble_st7789.py", board / "pyble_st7789.py"),)
if (board / "pyble_waveshare_lcd147b.py").is_file():
    sources += (
        (
            "pyble_waveshare_lcd147b.py",
            board / "pyble_waveshare_lcd147b.py",
        ),
    )
manifest_bytes = b"".join(
    path.read_bytes()
    for path in (
        board / "manifest.py",
        mpy / "extmod" / "asyncio" / "manifest.py",
        mpy
        / "lib"
        / "micropython-lib"
        / "micropython"
        / "drivers"
        / "led"
        / "neopixel"
        / "manifest.py",
    )
)
qstr = (build / "genhdr" / "qstrdefs.preprocessed.h").read_bytes()
records = []
for destination, source in sources:
    value = source.read_bytes()
    if destination == "neopixel.py" and b"__version__ =" not in value:
        value += b"\\n\\n__version__ = '0.1.0'\\n"
    digest = hashlib.sha256(
        architecture.encode()
        + b"\\0"
        + destination.encode()
        + b"\\0"
        + manifest_bytes
        + b"\\0"
        + qstr
        + b"\\0"
        + value
    ).digest()
    relative = destination[:-3] + ".mpy"
    destination_path = build / "frozen_mpy" / relative
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_bytes(digest)
    records.append((destination, digest))
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(
    "//\\n"
    "// Content for MICROPY_MODULE_FROZEN_STR\\n"
    "//\\n"
    "#include <stdint.h>\\n"
    "#define MP_FROZEN_STR_NAMES \\\\\\n"
    "\\n"
    "const uint32_t mp_frozen_str_sizes[] = { 0 };\\n"
    "const char mp_frozen_str_content[] = {\\n"
    "\\"\\\\0\\"\\n"
    "};\\n\\n"
    "//\\n"
    "// Content for MICROPY_MODULE_FROZEN_MPY\\n"
    "//\\n"
    + "// qstr-sha256: %s\\n" % hashlib.sha256(qstr).hexdigest()
    + "".join(
        "// - original source file: %s\\n"
        "// - frozen file name: %s\\n"
        "// mpy-sha256 %s: %s\\n"
        % (
            build / "frozen_mpy" / (destination[:-3] + ".mpy"),
            destination,
            destination,
            digest.hex(),
        )
        for destination, digest in records
    ),
    encoding="utf-8",
)
""",
            encoding="utf-8",
        )
        makemanifest.chmod(0o755)

        for _profile_id, target, _idf_target in PROFILE_TARGETS:
            settings = RELEASE.FROZEN_TARGET_SETTINGS[target]
            overlay = self.firmware / "board_overlays" / target
            board = (
                micropython
                / "ports"
                / "esp32"
                / "boards"
                / settings["board"]
            )
            shutil.copytree(overlay, board)
            if target == "waveshare-esp32-s3-lcd-147b":
                shutil.copyfile(
                    self.firmware / "python_modules" / "pyble_st7789.py",
                    board / "pyble_st7789.py",
                )
            target_build = self.build_root / target
            qstr = target_build / "genhdr" / "qstrdefs.preprocessed.h"
            qstr.parent.mkdir(parents=True, exist_ok=True)
            qstr.write_text(
                "QCFG(BYTES_IN_LEN, 1)\nQCFG(BYTES_IN_HASH, 1)\n",
                encoding="utf-8",
            )
            self.regenerate_frozen_payload(target)

    def regenerate_frozen_payload(self, target: str) -> None:
        """Regenerate one internally consistent synthetic frozen payload."""

        micropython = self.firmware / "upstream" / "micropython"
        settings = RELEASE.FROZEN_TARGET_SETTINGS[target]
        canonical_board = (
            micropython
            / "ports"
            / "esp32"
            / "boards"
            / settings["board"]
        )
        retained_board = (
            self.build_root
            / ".sources"
            / target
            / "micropython"
            / "ports"
            / "esp32"
            / "boards"
            / settings["board"]
        )
        board = retained_board if retained_board.is_dir() else canonical_board
        target_build = self.build_root / target
        makemanifest = micropython / "tools" / "makemanifest.py"
        completed = os.spawnve(
            os.P_WAIT,
            sys.executable,
            [
                sys.executable,
                os.fspath(makemanifest),
                "-o",
                os.fspath(target_build / "frozen_content.c"),
                "-v",
                "BOARD_DIR=%s" % board,
                "-v",
                "MPY_DIR=%s" % micropython,
                "-v",
                "MPY_LIB_DIR=%s"
                % (micropython / "lib" / "micropython-lib"),
                "-v",
                "PORT_DIR=%s" % (micropython / "ports" / "esp32"),
                "-b",
                os.fspath(target_build),
                "-f-march=%s" % settings["architecture"],
                "--mpy-tool-flags=",
                os.fspath(board / "manifest.py"),
            ],
            dict(os.environ),
        )
        if completed != 0:
            raise AssertionError("synthetic frozen proof generation failed")

    def _install_external_toolchain(self):
        root_name = "fixture-toolchain-1.0-aarch64-apple-darwin"
        name = "fixture-gcc"
        version = "1.0"
        platform_name = "aarch64-apple-darwin"
        compiler_relatives = sorted(
            [
                "bin/fixture-g++",
                "bin/fixture-gcc",
            ]
        )
        frozen_compiler = (
            b"#!/bin/sh\n"
            b"input=\n"
            b"output=\n"
            b"while [ \"$#\" -gt 0 ]; do\n"
            b"    case \"$1\" in\n"
            b"        -c) shift; input=$1 ;;\n"
            b"        -o) shift; output=$1 ;;\n"
            b"    esac\n"
            b"    shift\n"
            b"done\n"
            b"test -n \"$input\" && test -n \"$output\" || exit 2\n"
            b"{\n"
            b"    printf '%s\\n' 'synthetic compiled frozen object'\n"
            b"    /bin/cat \"$input\"\n"
            b"} > \"$output\"\n"
        )
        archive_values = {
            "lib/gcc/fixture/1.0/libgcc.a": BASE.make_ar_bytes(
                [
                    ("_divsi3.o", b"synthetic libgcc application member\n"),
                    ("_clzsi2.o", b"synthetic libgcc boot member\n"),
                ]
            ),
            "fixture/lib/libc.a": BASE.make_ar_bytes(
                [
                    ("memcpy.o", b"synthetic newlib application member\n"),
                    ("memset.o", b"synthetic newlib boot member\n"),
                ]
            ),
        }
        files = {
            compiler_relatives[0]: (
                b"#!/bin/sh\n# synthetic external C++ compiler\n"
            ),
            compiler_relatives[1]: frozen_compiler,
            **archive_values,
        }
        tools_home = (self.root / "idf-tools-home").resolve()
        install_root_relative = (
            Path("tools") / name / version / root_name
        ).as_posix()
        installed_root = tools_home / install_root_relative
        for relative, value in files.items():
            path = installed_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
            if relative in compiler_relatives:
                path.chmod(0o755)
        filename = "%s.tar.xz" % root_name
        distribution = tools_home / "dist" / filename
        distribution.parent.mkdir(parents=True)
        distribution.write_bytes(tar_xz_bytes(root_name, files))
        compilers = {
            relative: installed_root / relative
            for relative in compiler_relatives
        }
        url = "https://example.invalid/toolchains/%s" % filename
        metadata_path = (
            self.repo / "firmware" / ".esp-idf" / "tools" / "tools.json"
        )
        metadata_path.parent.mkdir(parents=True)
        BASE.write_json(
            metadata_path,
            {
                "version": 1,
                "tools": [
                    {
                        "name": name,
                        "description": (
                            "Synthetic schema-v2 integration GCC fixture"
                        ),
                        "export_paths": [[root_name, "bin"]],
                        "export_vars": {},
                        "install": "always",
                        "license": "GPL-3.0-with-GCC-exception",
                        "supported_targets": [
                            target for _profile, target, _idf in PROFILE_TARGETS
                        ],
                        "version_cmd": ["fixture-gcc", "--version"],
                        "version_regex": "(fixture-[0-9._-]+)",
                        "versions": [
                            {
                                "name": version,
                                "status": "recommended",
                                platform_name: {
                                    "url": url,
                                    "size": distribution.stat().st_size,
                                    "sha256": BASE.sha256_path(distribution),
                                },
                            }
                        ],
                    }
                ],
            },
        )
        self.toolchain = {
            "id": "fixture-external-toolchain",
            "name": name,
            "version": version,
            "platform": platform_name,
            "root_name": root_name,
            "tools_home": tools_home,
            "install_root_relative": install_root_relative,
            "installed_root": installed_root,
            "compiler_relatives": compiler_relatives,
            "compilers": compilers,
            "gcc": compilers[
                next(
                    relative
                    for relative in compiler_relatives
                    if relative.endswith("-gcc")
                )
            ],
            "gxx": compilers[
                next(
                    relative
                    for relative in compiler_relatives
                    if relative.endswith("-g++")
                )
            ],
            "archive_values": archive_values,
            "distribution": distribution,
            "distribution_filename": filename,
            "distribution_url": url,
            "metadata_path": metadata_path,
            "files": files,
        }

        old_prefix = "/fixture/"
        for _profile_id, target, _idf_target in PROFILE_TARGETS:
            for role, role_root in (
                ("application", self.build_root / target),
                ("bootloader", self.build_root / target / "bootloader"),
            ):
                commands_path = role_root / "compile_commands.json"
                commands = json.loads(commands_path.read_text(encoding="utf-8"))
                replaced = 0
                for command in commands:
                    argv = command["command"].split(" ", 1)
                    if argv[0].startswith(old_prefix):
                        relative = (
                            compiler_relatives[0]
                            if role == "application" and replaced == 0
                            else compiler_relatives[1]
                        )
                        command["command"] = "%s %s" % (
                            compilers[relative],
                            argv[1],
                        )
                        replaced += 1
                if replaced == 0:
                    raise RuntimeError(
                        "fixture compile commands contain no replaceable compiler"
                    )
                BASE.write_json(commands_path, commands)

    @classmethod
    def frozen_object_bytes(cls, frozen_content: bytes) -> bytes:
        return cls.FROZEN_OBJECT_PREFIX + frozen_content

    def _install_frozen_object_bindings(self):
        """Make each linked frozen.o equal a replay of its compile command."""

        for _profile_id, target, _idf_target in PROFILE_TARGETS:
            build = self.build_root / target
            frozen = build / "frozen_content.c"
            frozen_object = self.frozen_object_bytes(frozen.read_bytes())
            output = (
                build
                / "micropython"
                / "CMakeFiles"
                / "micropython.dir"
                / "frozen.o"
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(frozen_object)

            archive = build / "micropython" / "libmicropython.a"
            members = BASE.parse_ar_members(archive.read_bytes())
            archive.write_bytes(
                BASE.make_ar_bytes(
                    [
                        ("vm.o", members["vm.o"]),
                        ("frozen.o", frozen_object),
                    ]
                )
            )

    def _add_mbedtls_archives(self):
        source_root = (
            self.firmware
            / "upstream"
            / "esp-idf"
            / "components"
            / "mbedtls"
            / "mbedtls"
            / "library"
        )
        source_root.mkdir(parents=True)
        self.mbed_root = source_root.parent.parent
        source_names = {
            "mbedcrypto": "aes.c",
            "mbedtls": "ssl_tls.c",
            "mbedx509": "x509.c",
        }
        for component, _member in self.MBED_COMPONENTS:
            (source_root / source_names[component]).write_text(
                "// SPDX-License-Identifier: MIT\n"
                "int fixture_%s(void) { return 1; }\n" % component,
                encoding="utf-8",
            )

        for _profile_id, target, _idf_target in PROFILE_TARGETS:
            build = self.build_root / target
            description_path = build / "project_description.json"
            commands_path = build / "compile_commands.json"
            description = json.loads(
                description_path.read_text(encoding="utf-8")
            )
            commands = json.loads(commands_path.read_text(encoding="utf-8"))
            for component, member in self.MBED_COMPONENTS:
                source = source_root / source_names[component]
                archive = (
                    build
                    / "esp-idf"
                    / "mbedtls"
                    / "mbedtls"
                    / "library"
                    / ("lib%s.a" % component)
                )
                archive.parent.mkdir(parents=True, exist_ok=True)
                archive.write_bytes(
                    BASE.make_ar_bytes(
                        [(member, ("synthetic %s object\n" % component).encode())]
                    )
                )
                output = (
                    build
                    / "esp-idf"
                    / "mbedtls"
                    / "mbedtls"
                    / "library"
                    / "CMakeFiles"
                    / ("%s.dir" % component)
                    / member
                )
                commands.append(
                    {
                        "directory": str(build),
                        "command": "%s -c %s -o %s"
                        % (
                            self.toolchain["gcc"],
                            source,
                            output,
                        ),
                        "file": str(source),
                        "output": str(output),
                    }
                )
                description["build_components"].append(component)
                description["build_component_info"][component] = {
                    "dir": str(source_root),
                    "type": "LIBRARY",
                    "file": str(archive),
                    "sources": [str(source)],
                }
            BASE.write_json(description_path, description)
            BASE.write_json(commands_path, commands)

    def _install_compile_output_fixtures(self):
        """Give every synthetic compile command an existing regular output."""

        for _profile_id, target, _idf_target in PROFILE_TARGETS:
            for role_root in (
                self.build_root / target,
                self.build_root / target / "bootloader",
            ):
                description_path = role_root / "project_description.json"
                description = json.loads(
                    description_path.read_text(encoding="utf-8")
                )
                for name, component in description[
                    "build_component_info"
                ].items():
                    component.setdefault("lib", name)
                BASE.write_json(description_path, description)

                commands = json.loads(
                    (role_root / "compile_commands.json").read_text(
                        encoding="utf-8"
                    )
                )
                for index, command in enumerate(commands):
                    output = Path(command["output"])
                    if not output.is_absolute():
                        output = role_root / output
                    output.parent.mkdir(parents=True, exist_ok=True)
                    if not output.exists():
                        output.write_bytes(
                            (
                                "synthetic compile output %d\n" % index
                            ).encode("utf-8")
                        )

    def _rewrite_maps(self):
        toolchain = self.toolchain
        libgcc = (
            toolchain["installed_root"]
            / "lib/gcc/fixture/1.0/libgcc.a"
        )
        libc = toolchain["installed_root"] / "fixture/lib/libc.a"
        for _profile_id, target, _idf_target in PROFILE_TARGETS:
            build = self.build_root / target
            app_entries = [
                (
                    "esp-idf/app_core/libfixture_app.a",
                    "app_core.o",
                    "fixture_app_core",
                ),
                (
                    "micropython/libmicropython.a",
                    "vm.o",
                    "mp_execute_bytecode",
                ),
                (
                    "micropython/libmicropython.a",
                    "frozen.o",
                    "mp_frozen_names",
                ),
            ]
            for category, member in (
                ("controller", "controller.o"),
                ("phy", "phy.o"),
                ("wifi", "wifi.o"),
                ("coex", "coex.o"),
            ):
                app_entries.append(
                    (
                        "vendor/%s/libfixture_%s.a" % (category, category),
                        member,
                        "fixture_%s_symbol" % category,
                    )
                )
            for component, member in self.MBED_COMPONENTS:
                app_entries.append(
                    (
                        "esp-idf/mbedtls/mbedtls/library/lib%s.a" % component,
                        member,
                        "fixture_%s" % component,
                    )
                )
            app_entries.extend(
                [
                    (str(libgcc), "_divsi3.o", "__divsi3"),
                    (str(libc), "memcpy.o", "memcpy"),
                ]
            )
            (build / "micropython.map").write_text(
                self.base._map_text(app_entries),
                encoding="utf-8",
            )
            boot_entries = [
                (
                    "esp-idf/boot_core/libfixture_boot.a",
                    "boot_core.o",
                    "call_start_cpu0",
                ),
                (str(libgcc), "_clzsi2.o", "__clzsi2"),
                (str(libc), "memset.o", "memset"),
            ]
            (build / "bootloader" / "bootloader.map").write_text(
                self.base._map_text(boot_entries),
                encoding="utf-8",
            )

    def _install_ninja_link_fixtures(self):
        """Add the exact generated-main and final-link evidence to all roles."""

        self.ninja_links = {}
        main_sources = {}
        for role in ("application", "bootloader"):
            source = (
                self.firmware
                / "components"
                / ("fixture_main_app" if role == "application" else "fixture_main_boot")
                / "fixture_main.c"
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                "// SPDX-License-Identifier: MIT\n"
                "int fixture_%s_main(void) { return 1; }\n"
                % ("app" if role == "application" else "boot"),
                encoding="utf-8",
            )
            main_sources[role] = source

        for profile_id, target, idf_target in PROFILE_TARGETS:
            for role in ("application", "bootloader"):
                role_root = self.build_root / target
                map_name = "micropython.map"
                app_elf = "micropython.elf"
                if role == "bootloader":
                    role_root /= "bootloader"
                    map_name = "bootloader.map"
                    app_elf = "bootloader.elf"

                description_path = role_root / "project_description.json"
                commands_path = role_root / "compile_commands.json"
                map_path = role_root / map_name
                description = json.loads(
                    description_path.read_text(encoding="utf-8")
                )
                commands = json.loads(
                    commands_path.read_text(encoding="utf-8")
                )
                compiler = shlex.split(commands[0]["command"], posix=True)[0]

                main_source = main_sources[role]
                main_archive_relative = "esp-idf/main/libfixture_main.a"
                main_archive = role_root / main_archive_relative
                main_output_relative = (
                    "esp-idf/main/CMakeFiles/main.dir/fixture_main.o"
                )
                main_output = role_root / main_output_relative
                anchor_source = role_root / ("project_elf_src_%s.c" % idf_target)
                anchor_output_relative = (
                    "CMakeFiles/%s.dir/%s.obj" % (app_elf, anchor_source.name)
                )
                anchor_output = role_root / anchor_output_relative

                main_output.parent.mkdir(parents=True, exist_ok=True)
                main_output.write_bytes(
                    ("synthetic %s main object\n" % role).encode("utf-8")
                )
                anchor_source.write_bytes(b"")
                anchor_output.parent.mkdir(parents=True, exist_ok=True)
                anchor_output.write_bytes(
                    ("synthetic %s project anchor\n" % role).encode("utf-8")
                )
                main_archive.parent.mkdir(parents=True, exist_ok=True)
                main_archive.write_bytes(
                    BASE.make_ar_bytes(
                        [("fixture_main.o", main_output.read_bytes())]
                    )
                )

                metadata = []
                if role == "application":
                    for index, name in enumerate(MAIN_GENERATED_HEADERS):
                        header = role_root / "genhdr" / name
                        header.parent.mkdir(parents=True, exist_ok=True)
                        header.write_text(
                            "/* synthetic generated main header %d */\n" % index,
                            encoding="utf-8",
                        )
                        metadata.append(header)

                description["app_elf"] = app_elf
                description["build_components"].append("main")
                description["build_component_info"]["main"] = {
                    "dir": str(main_source.parent),
                    "type": "LIBRARY",
                    "lib": "main",
                    "file": str(main_archive),
                    "sources": [
                        str(main_source),
                        *(str(path) for path in metadata),
                    ],
                }
                BASE.write_json(description_path, description)

                def compile_command(source: Path, output_relative: str) -> dict:
                    return {
                        "directory": str(role_root),
                        "command": "%s -c %s -o %s"
                        % (compiler, source, output_relative),
                        "file": str(source),
                        "output": output_relative,
                    }

                commands.extend(
                    [
                        compile_command(main_source, main_output_relative),
                        compile_command(anchor_source, anchor_output_relative),
                    ]
                )
                BASE.write_json(commands_path, commands)

                map_text = map_path.read_text(encoding="utf-8")
                map_text = map_text.replace(
                    "\nLinker script and memory map\n",
                    (
                        "%s(fixture_main.o)\n"
                        "                              (fixture_main)\n\n"
                        "Linker script and memory map\n"
                    )
                    % main_archive_relative,
                    1,
                )
                map_text += "LOAD %s\nLOAD %s\n" % (
                    main_archive_relative,
                    anchor_output_relative,
                )
                map_path.write_text(map_text, encoding="utf-8")

                archives = [
                    match.group(1)
                    for line in map_text.splitlines()
                    if (match := re.fullmatch(r"LOAD (\S+\.a)", line))
                    is not None
                ]
                graph = write_ninja_link_graph(
                    role_root,
                    app_elf=app_elf,
                    compiler=compiler,
                    explicit_inputs=[anchor_output_relative],
                    implicit_inputs=archives,
                    link_libraries=archives,
                )
                stale_link = (
                    role_root / "CMakeFiles" / ("%s.dir" % app_elf) / "link.txt"
                )
                if stale_link.exists():
                    stale_link.unlink()
                self.ninja_links[(target, role)] = {
                    **graph,
                    "profile_id": profile_id,
                    "app_elf": app_elf,
                    "main_source": main_source,
                    "main_archive": main_archive,
                    "main_archive_relative": main_archive_relative,
                    "main_output": main_output,
                    "main_output_relative": main_output_relative,
                    "anchor_source": anchor_source,
                    "anchor_output": anchor_output,
                    "anchor_output_relative": anchor_output_relative,
                    "metadata": metadata,
                }

    def _source_path(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.repo.resolve()).as_posix()
        except ValueError:
            return "build/" + resolved.relative_to(
                self.build_root.resolve()
            ).as_posix()

    @staticmethod
    def _role_paths(build: Path, role: str) -> tuple[Path, Path, Path]:
        if role == "application":
            return (
                build / "project_description.json",
                build / "compile_commands.json",
                build / "micropython.map",
            )
        root = build / "bootloader"
        return (
            root / "project_description.json",
            root / "compile_commands.json",
            root / "bootloader.map",
        )

    def _generated_observation(
        self,
        *,
        profile_id: str,
        target: str,
        role: str,
        component: str,
    ) -> dict:
        build = self.build_root / target
        description_path, commands_path, map_path = self._role_paths(build, role)
        description = json.loads(
            description_path.read_text(encoding="utf-8")
        )
        record = description["build_component_info"][component]
        archive = Path(record["file"])
        members = sorted(BASE.parse_ar_members(archive.read_bytes()))
        source_paths = [Path(source) for source in record["sources"]]
        if component == "main":
            metadata_paths = set(self.ninja_links[(target, role)]["metadata"])
            source_paths = [
                source for source in source_paths if source not in metadata_paths
            ]
        sources = [
            {
                "path": self._source_path(source),
                "sha256": BASE.sha256_path(source),
            }
            for source in source_paths
        ]
        kind = (
            "generated-supplemental-archive"
            if component in {item[0] for item in self.MBED_COMPONENTS}
            else "generated-component-archive"
        )
        generated_binding = {
            "component": component,
            "project_description_sha256": BASE.sha256_path(
                description_path
            ),
            "compile_commands_sha256": BASE.sha256_path(commands_path),
            "linker_map_sha256": BASE.sha256_path(map_path),
            "sources": sorted(sources, key=lambda item: item["path"]),
            "members": members,
        }
        if component == "main":
            link = self.ninja_links[(target, role)]
            generated_binding.update(
                {
                    "linker_command_sha256": link["linker_command_sha256"],
                    "build_ninja_sha256": link["build_ninja_sha256"],
                    "rules_ninja_sha256": link["rules_ninja_sha256"],
                    "metadata_inputs": [
                        {
                            "path": self._source_path(path),
                            "sha256": BASE.sha256_path(path),
                        }
                        for path in link["metadata"]
                    ],
                    "direct_objects": [
                        {
                            "output": {
                                "path": self._source_path(link["anchor_output"]),
                                "sha256": BASE.sha256_path(
                                    link["anchor_output"]
                                ),
                            },
                            "source": {
                                "path": self._source_path(link["anchor_source"]),
                                "sha256": BASE.sha256_path(
                                    link["anchor_source"]
                                ),
                            },
                        }
                    ],
                }
            )
        return {
            "id": archive_id(component, profile_id, role),
            "profile_id": profile_id,
            "role": role,
            "kind": kind,
            "observed_path": str(archive.resolve()),
            "sha256": BASE.sha256_path(archive),
            "generated_binding": generated_binding,
        }

    def _make_expected_inputs(self) -> list[dict]:
        inputs = []
        toolchain = self.toolchain
        source_tree = (
            self.firmware
            / "upstream"
            / "micropython"
            / "lib"
            / "micropython-lib"
            / "micropython"
            / "drivers"
            / "led"
            / "neopixel"
        )
        for profile_id, target, _idf_target in PROFILE_TARGETS:
            for component in (
                "app_core",
                "main",
                "micropython",
                *(item[0] for item in self.MBED_COMPONENTS),
            ):
                inputs.append(
                    self._generated_observation(
                        profile_id=profile_id,
                        target=target,
                        role="application",
                        component=component,
                    )
                )
            inputs.append(
                self._generated_observation(
                    profile_id=profile_id,
                    target=target,
                    role="bootloader",
                    component="boot_core",
                )
            )
            inputs.append(
                self._generated_observation(
                    profile_id=profile_id,
                    target=target,
                    role="bootloader",
                    component="main",
                )
            )
            build = self.build_root / target
            for category in ("controller", "phy", "wifi", "coex"):
                source_relative = (
                    "firmware/fixture-vendor/%s/libfixture_%s.a"
                    % (category, category)
                )
                archive = (
                    build
                    / "vendor"
                    / category
                    / ("libfixture_%s.a" % category)
                )
                inputs.append(
                    {
                        "id": archive_id(
                            category,
                            profile_id,
                            "application",
                        ),
                        "profile_id": profile_id,
                        "role": "application",
                        "kind": "opaque-archive",
                        "observed_path": str(archive.resolve()),
                        "sha256": BASE.sha256_path(archive),
                        "reviewed_source_path": source_relative,
                    }
                )
            for role in ("application", "bootloader"):
                for name, relative in (
                    ("libgcc", "lib/gcc/fixture/1.0/libgcc.a"),
                    ("libc", "fixture/lib/libc.a"),
                ):
                    archive = toolchain["installed_root"] / relative
                    inputs.append(
                        {
                            "id": archive_id(name, profile_id, role),
                            "profile_id": profile_id,
                            "role": role,
                            "kind": "toolchain-archive",
                            "observed_path": str(archive.absolute()),
                            "sha256": BASE.sha256_path(archive),
                            "toolchain_id": toolchain["id"],
                            "relative_path": relative,
                            "compiler_paths": [
                                str(path.absolute())
                                for path in (
                                    [
                                        toolchain["compilers"][
                                            compiler_relative
                                        ]
                                        for compiler_relative in toolchain[
                                            "compiler_relatives"
                                        ]
                                    ]
                                    if role == "application"
                                    else [toolchain["gcc"]]
                                )
                            ],
                        }
                    )
            inputs.append(
                {
                    "id": archive_id(
                        "neopixel",
                        profile_id,
                        "application",
                    ),
                    "profile_id": profile_id,
                    "role": "application",
                    "kind": "frozen-source-tree",
                    "observed_path": str(source_tree.resolve()),
                    "sha256": BASE.sha256_tree(source_tree),
                    "frozen_destinations": ["neopixel.py"],
                }
            )
        return sorted(inputs, key=lambda item: item["id"])

    def _policy_input(self, observation: dict) -> dict:
        owners = {
            "app_core": "fixture-app-core",
            "boot_core": "fixture-boot-core",
            "micropython": "micropython-runtime",
            "controller": "fixture-controller-blob",
            "phy": "fixture-phy-blob",
            "wifi": "fixture-wifi-blob",
            "coex": "fixture-coex-blob",
            "libgcc": "fixture-gcc-runtime",
            "libc": "fixture-newlib-runtime",
            "neopixel": "supplemental-neopixel",
            "mbedcrypto": "supplemental-mbedtls",
            "mbedtls": "supplemental-mbedtls",
            "mbedx509": "supplemental-mbedtls",
        }
        common = {
            key: observation[key]
            for key in ("id", "profile_id", "role", "kind")
        }
        name = observation["id"].split("--", 1)[0]
        common["reviewed_package_id"] = (
            "fixture-app-core"
            if name == "main" and observation["role"] == "application"
            else "fixture-boot-core"
            if name == "main"
            else owners[name]
        )
        kind = observation["kind"]
        if kind.startswith("generated-"):
            return {
                **common,
                "generated_matcher": {
                    "component": observation["generated_binding"]["component"],
                },
            }
        if kind == "opaque-archive":
            return {
                **common,
                "reviewed_source_path": observation[
                    "reviewed_source_path"
                ],
                "sha256": observation["sha256"],
            }
        if kind == "toolchain-archive":
            return {
                **common,
                "toolchain_id": observation["toolchain_id"],
                "relative_path": observation["relative_path"],
                "sha256": observation["sha256"],
            }
        source = Path(observation["observed_path"])
        return {
            **common,
            "path": source.resolve().relative_to(
                self.repo.resolve()
            ).as_posix(),
            "sha256": observation["sha256"],
            "frozen_destinations": observation["frozen_destinations"],
        }

    def _raw_documents(self) -> list[dict]:
        records = []
        for identity in PROFILE_ROLES:
            raw = BASE.spdx22_tag_value_from_document(
                self.runner.spdx_document(*identity)
            )
            document = RELEASE._audit_parse_spdx_tag_value(raw)
            records.append(
                {
                    "profile_id": identity[0],
                    "role": identity[1],
                    "packages": document["packages"],
                    "relationships": document["relationships"],
                }
            )
        return records

    @staticmethod
    def _identified_license_texts(records: list[dict]) -> list[dict]:
        identifiers = {
            "MIT.txt": "MIT",
            "MIT.fixture.txt": "MIT",
            "BSD-2-Clause.txt": "BSD-2-Clause",
            "Apache-2.0.txt": "Apache-2.0",
            "Apache-2.0.fixture.txt": "Apache-2.0",
            "GPL-3.0-or-later.txt": "GPL-3.0-or-later",
            "GPL-3.0-or-later.fixture.txt": "GPL-3.0-or-later",
            "GCC-exception-3.1.txt": "GCC-exception-3.1",
            "GCC-exception-3.1.fixture.txt": "GCC-exception-3.1",
            "COPYING.NEWLIB.txt": "LicenseRef-PyBLE-Newlib-Multilicense",
            "COPYING.NEWLIB.fixture.txt": (
                "LicenseRef-PyBLE-Test-Newlib-Multilicense"
            ),
            "Fixture-Controller.txt": "LicenseRef-PyBLE-Test-Controller",
            "Fixture-PHY.txt": "LicenseRef-PyBLE-Test-PHY",
            "Fixture-WiFi.txt": "LicenseRef-PyBLE-Test-WiFi",
            "Fixture-Coex.txt": "LicenseRef-PyBLE-Test-Coex",
        }
        return [
            {
                **copy.deepcopy(record),
                "spdx_id": identifiers[Path(record["path"]).name],
            }
            for record in records
        ]

    def _reviewed_packages(self) -> list[dict]:
        return [
            {
                "id": entry["id"],
                "dependency": copy.deepcopy(entry["dependency"]),
                "source": copy.deepcopy(entry["source"]),
                "reviewed_raw_package_expression": entry[
                    "spdx_expression"
                ],
                "license_texts": self._identified_license_texts(
                    entry["license_texts"]
                ),
                "notice": copy.deepcopy(entry["notice"]),
            }
            for entry in self.legacy_policy["entries"]
            if entry["id"] != "fixture-neopixel"
        ]

    def _resolution_inputs(self, identifier: str) -> list[str]:
        prefixes = {
            "fixture-app-core": ("app_core--",),
            "fixture-boot-core": ("boot_core--",),
            "micropython-runtime": ("micropython--",),
            "fixture-controller-blob": ("controller--",),
            "fixture-phy-blob": ("phy--",),
            "fixture-wifi-blob": ("wifi--",),
            "fixture-coex-blob": ("coex--",),
            "fixture-gcc-runtime": ("libgcc--",),
            "fixture-newlib-runtime": ("libc--",),
        }[identifier]
        return sorted(
            item["id"]
            for item in self.expected_inputs
            if item["id"].startswith(prefixes)
            or (
                item["id"].startswith("main--")
                and (
                    (
                        identifier == "fixture-app-core"
                        and item["role"] == "application"
                    )
                    or (
                        identifier == "fixture-boot-core"
                        and item["role"] == "bootloader"
                    )
                )
            )
        )

    def _resolutions(self) -> list[dict]:
        resolutions = []
        for entry in self.legacy_policy["entries"]:
            if entry["id"] == "fixture-neopixel":
                continue
            resolutions.append(
                {
                    "id": "resolve-" + entry["id"],
                    "reviewed_package_id": entry["id"],
                    "package_refs": [
                        {
                            **identity,
                            "spdx_id": spdx_package_id(entry["id"]),
                        }
                        for identity in entry["applicability"]
                    ],
                    "input_refs": self._resolution_inputs(entry["id"]),
                    "resolved_input_expression": entry[
                        "spdx_expression"
                    ],
                    "disposition": "allow",
                    "attribution": (
                        "Resolved against exact synthetic fixture provenance."
                    ),
                }
            )
        return resolutions

    def _supplemental_packages(self) -> list[dict]:
        neo = next(
            entry
            for entry in self.legacy_policy["entries"]
            if entry["id"] == "fixture-neopixel"
        )
        neo_input = next(
            item
            for item in self.expected_inputs
            if item["kind"] == "frozen-source-tree"
        )
        neo_source = copy.deepcopy(neo["source"])
        neo_source.update(
            {
                "tree_path": Path(neo_input["observed_path"])
                .resolve()
                .relative_to(self.repo.resolve())
                .as_posix(),
                "tree_sha256": neo_input["sha256"],
            }
        )
        neo_record = {
            "id": "supplemental-neopixel",
            "dependency": copy.deepcopy(neo["dependency"]),
            "source": neo_source,
            "source_spdx_expression": neo["spdx_expression"],
            "selected_spdx_expression": neo["spdx_expression"],
            "input_refs": sorted(
                item["id"]
                for item in self.expected_inputs
                if item["kind"] == "frozen-source-tree"
            ),
            "relationship": {
                "relationship_type": "DEPENDS_ON",
                "related_reviewed_package_id": "micropython-runtime",
            },
            "license_texts": self._identified_license_texts(
                neo["license_texts"]
            ),
            "notice": copy.deepcopy(neo["notice"]),
            "disposition": "allow",
        }
        mbed_record = {
            "id": "supplemental-mbedtls",
            "dependency": {
                "name": "Fixture nested Mbed TLS archives",
                "version_ref": "fixture-mbedtls@%s" % ("b" * 40),
                "source_url": (
                    "https://example.invalid/mbedtls/commit/%s" % ("b" * 40)
                ),
                "copyright": "Copyright 2099 synthetic fixture authors",
            },
            "source": {
                "ref": "fixture-mbedtls@%s" % ("b" * 40),
                "url": (
                    "https://example.invalid/mbedtls/commit/%s" % ("b" * 40)
                ),
                "tree_path": self.mbed_root.relative_to(self.repo).as_posix(),
                "tree_sha256": BASE.sha256_tree(self.mbed_root),
            },
            "source_spdx_expression": "MIT",
            "selected_spdx_expression": "MIT",
            "input_refs": sorted(
                item["id"]
                for item in self.expected_inputs
                if item["kind"] == "generated-supplemental-archive"
            ),
            "relationship": {
                "relationship_type": "DEPENDS_ON",
                "related_reviewed_package_id": "micropython-runtime",
            },
            "license_texts": self._identified_license_texts(
                neo["license_texts"]
            ),
            "notice": copy.deepcopy(neo["notice"]),
            "disposition": "allow",
        }
        return [neo_record, mbed_record]

    def _make_policy(self) -> dict:
        toolchain = self.toolchain
        inputs = []
        neo_root = (
            self.firmware
            / "upstream"
            / "micropython"
            / "lib"
            / "micropython-lib"
            / "micropython"
            / "drivers"
            / "led"
            / "neopixel"
        )
        for observation in self.expected_inputs:
            record = self._policy_input(observation)
            if observation["kind"] == "frozen-source-tree":
                record["path"] = neo_root.relative_to(self.repo).as_posix()
            inputs.append(record)
        distribution = toolchain["distribution"]
        review_relative = next(
            entry["notice"]["path"]
            for entry in self.legacy_policy["entries"]
            if entry["notice"]["required"]
        )
        review_path = self.repo / review_relative
        policy = {
            "schema_version": 2,
            "approved_license_refs": copy.deepcopy(
                self.legacy_policy["approved_license_refs"]
            ),
            "review_files": [
                {
                    "id": "fixture-upstream-attribution",
                    "purpose": "Synthetic upstream attribution evidence.",
                    "path": review_relative,
                    "sha256": BASE.sha256_path(review_path),
                    "source_identities": [
                        "a" * 40,
                        BASE.sha256_path(review_path),
                    ],
                }
            ],
            "raw_documents": self._raw_documents(),
            "reviewed_packages": self._reviewed_packages(),
            "resolved_inputs": inputs,
            "resolutions": self._resolutions(),
            "supplemental_packages": self._supplemental_packages(),
            "toolchains": [
                {
                    "id": toolchain["id"],
                    "name": toolchain["name"],
                    "version": toolchain["version"],
                    "platform": toolchain["platform"],
                    "install_root_relative": toolchain[
                        "install_root_relative"
                    ],
                    "compiler_frontends": [
                        {
                            "relative_path": relative,
                            "sha256": BASE.sha256_path(
                                toolchain["compilers"][relative]
                            ),
                        }
                        for relative in toolchain[
                            "compiler_relatives"
                        ]
                    ],
                    "distribution": {
                        "url": toolchain["distribution_url"],
                        "filename": toolchain["distribution_filename"],
                        "size": distribution.stat().st_size,
                        "sha256": BASE.sha256_path(distribution),
                        "archive_format": "tar.xz",
                        "archive_root": toolchain["root_name"],
                    },
                    "metadata": {
                        "path": toolchain["metadata_path"]
                        .relative_to(self.repo)
                        .as_posix(),
                        "sha256": BASE.sha256_path(
                            toolchain["metadata_path"]
                        ),
                    },
                    "admitted_archive_paths": sorted(
                        toolchain["archive_values"]
                    ),
                }
            ],
        }
        self.refresh_shipment_review(policy)
        return policy

    def refresh_shipment_review(self, policy: dict) -> None:
        dispositions = {
            (
                package_ref["profile_id"],
                package_ref["role"],
                package_ref["spdx_id"],
            ): resolution["disposition"]
            for resolution in policy["resolutions"]
            for package_ref in resolution["package_refs"]
        }
        raw_occurrences = {
            (
                document["profile_id"],
                document["role"],
                package["SPDXID"],
            )
            for document in policy["raw_documents"]
            for package in document["packages"]
        }
        if set(dispositions) != raw_occurrences:
            raise AssertionError("fixture shipment ledger coverage mismatch")
        document = {
            "schema_version": 1,
            "occurrences": [
                {
                    "profile_id": profile_id,
                    "role": role,
                    "spdx_id": spdx_id,
                    "disposition": dispositions[(profile_id, role, spdx_id)],
                }
                for profile_id, role, spdx_id in sorted(raw_occurrences)
            ],
        }
        path = (
            self.firmware
            / "licenses"
            / "evidence"
            / "shipment-review.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                document,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        policy["shipment_review"] = {
            "path": path.relative_to(self.repo).as_posix(),
            "sha256": BASE.sha256_path(path),
        }


class ReleaseLicenseFixture(ObservationV2Fixture):
    """Persist the valid schema-v2 policy for downstream release tests.

    The observation fixture normally installs its policy only inside a narrow
    context manager so mutation tests can restore the legacy seed policy.  The
    release-bundle, finalization, and snapshot suites need the same valid v2
    graph to remain installed while they create and subsequently revalidate a
    candidate.  Their repository is temporary, so no restoration is required.
    """

    def __init__(self):
        super().__init__()
        BASE.write_json(self.policy_path, self.policy)
        self.base.refresh_locked_policy_hash()


def FakeOfflineSbomRunner(fixture: ReleaseLicenseFixture):
    """Return a fresh copy of the fixture's pre-normalized v2 runner."""

    runner = copy.copy(fixture.runner)
    runner.calls = []
    runner.temporary_paths = set()
    runner.raw_namespaces = []
    runner.raw_values = []
    runner._documents = copy.deepcopy(fixture.runner._documents)
    return runner


@unittest.skipUnless(RELEASE is not None, "release_bundle.py is unavailable")
class LogicalReceiptPathTests(unittest.TestCase):
    def test_direct_output_under_nested_build_root_is_build_relative(self):
        with tempfile.TemporaryDirectory(
            prefix="pyble-nested-build-logical-path-"
        ) as temporary:
            repo_root = Path(temporary) / "repo"
            build_root = repo_root / "firmware" / "build"
            direct_output = (
                build_root
                / "esp32"
                / "CMakeFiles"
                / "micropython.elf.dir"
                / "project_elf_src_esp32.c.obj"
            )
            direct_output.parent.mkdir(parents=True)
            direct_output.write_bytes(b"synthetic direct object\n")

            record = RELEASE._audit_v2_source_record(
                direct_output,
                repo_root=repo_root,
                build_root=build_root,
            )

            self.assertEqual(
                record["path"],
                "build/esp32/CMakeFiles/micropython.elf.dir/"
                "project_elf_src_esp32.c.obj",
            )
            self.assertEqual(
                record["sha256"],
                BASE.sha256_path(direct_output),
            )


@unittest.skipUnless(RELEASE is not None, "release_bundle.py is unavailable")
class ObservePolicyV2InputsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = ObservationV2Fixture()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.close()

    def observe_context(self, policy=None):
        seam = getattr(RELEASE, "_audit_observe_policy_v2_context", None)
        self.assertTrue(
            callable(seam),
            "release_bundle.py lacks _audit_observe_policy_v2_context",
        )
        return seam(
            self.fixture.policy if policy is None else policy,
            repo_root=self.fixture.repo,
            build_root=self.fixture.build_root,
        )

    def observe(self, policy=None):
        return self.observe_context(policy)["observed_inputs"]

    def assert_rejected(self, policy=None):
        with self.assertRaises(RELEASE.ReleaseError):
            self.observe(policy)

    def by_id(self, observations, identifier):
        return next(item for item in observations if item["id"] == identifier)

    def test_generated_component_binds_file_sources_archive_members_and_map(self):
        observations = self.observe()
        identifier = "app_core--esp32-4mb--application"
        observed = self.by_id(observations, identifier)
        expected = self.by_id(self.fixture.expected_inputs, identifier)
        self.assertEqual(observed, expected)
        self.assertEqual(
            observed["generated_binding"]["sources"],
            [
                {
                    "path": "firmware/components/app_core/app_core.c",
                    "sha256": BASE.sha256_path(
                        self.fixture.firmware
                        / "components"
                        / "app_core"
                        / "app_core.c"
                    ),
                }
            ],
        )
        self.assertEqual(
            observed["generated_binding"]["members"],
            ["app_core.o"],
        )
        self.assertNotIn(
            "sha256",
            next(
                item
                for item in self.fixture.policy["resolved_inputs"]
                if item["id"] == identifier
            ),
            "generated archive bytes belong in observations/receipts",
        )

        description = self.fixture.build_root / "esp32/project_description.json"
        with changed_json(
            description,
            lambda value: value["build_component_info"]["app_core"].update(
                {"sources": []}
            ),
        ):
            self.assert_rejected()
        map_path = self.fixture.build_root / "esp32/micropython.map"
        changed_map = map_path.read_text(encoding="utf-8").replace(
            "libfixture_app.a(app_core.o)",
            "libfixture_app.a(unreviewed.o)",
        )
        with BASE.patched_text(map_path, changed_map):
            self.assert_rejected()

    def test_component_source_directory_marker_is_scoped_and_non_recursive(self):
        description = self.fixture.build_root / "esp32/project_description.json"
        component_dir = (
            self.fixture.firmware / "components" / "app_core"
        ).absolute()
        identifier = "app_core--esp32-4mb--application"

        def replace_sources(value, sources):
            value["build_component_info"]["app_core"]["sources"] = sources

        with changed_json(
            description,
            lambda value: replace_sources(value, [str(component_dir)]),
        ):
            observed = self.by_id(self.observe(), identifier)
            self.assertEqual(
                [item["path"] for item in observed["generated_binding"]["sources"]],
                ["firmware/components/app_core/app_core.c"],
                "a directory marker covers compiled descendants without "
                "recursively adding other files",
            )

        for invalid in (
            self.fixture.firmware,
            component_dir / "missing-source-directory",
        ):
            with self.subTest(invalid=invalid), changed_json(
                description,
                lambda value, path=invalid: replace_sources(value, [str(path)]),
            ):
                self.assert_rejected()

        marker = component_dir / "symlinked-source-directory"
        marker.symlink_to(component_dir, target_is_directory=True)
        try:
            with changed_json(
                description,
                lambda value: replace_sources(value, [str(marker)]),
            ):
                self.assert_rejected()
        finally:
            marker.unlink()

    def test_real_idf_main_metadata_and_direct_object_topology_is_observed(self):
        with real_idf_main_topology(self.fixture) as topology:
            observed = self.by_id(
                self.observe(topology["policy"]),
                topology["identifier"],
            )
            binding = observed["generated_binding"]

            expected_sources = {
                self.fixture._source_path(path)
                for path in (
                    topology["main_source"],
                    topology["pyble_source"],
                )
            }
            self.assertEqual(
                {item["path"] for item in binding["sources"]},
                expected_sources,
                "ordinary archive sources must come only from its exact "
                "object root; the duplicated direct PyBLE output is not a "
                "second archive source",
            )
            self.assertNotIn(
                self.fixture._source_path(topology["build_only_source"]),
                {item["path"] for item in binding["sources"]},
                "an unlinked build-only output is not redistributed",
            )
            self.assertEqual(
                binding["metadata_inputs"],
                [
                    {
                        "path": self.fixture._source_path(path),
                        "sha256": BASE.sha256_path(path),
                    }
                    for path in topology["generated_headers"]
                ],
                "the six generated main headers are hash-bound metadata, "
                "not archive sources",
            )
            expected_direct = []
            for name, source in (
                ("project", topology["project_source"]),
                ("pyble", topology["pyble_source"]),
                ("berkeley", topology["berkeley_source"]),
            ):
                output = (
                    topology["role_root"]
                    / topology["direct_loads"][name]
                )
                expected_direct.append(
                    {
                        "output": {
                            "path": self.fixture._source_path(output),
                            "sha256": BASE.sha256_path(output),
                        },
                        "source": {
                            "path": self.fixture._source_path(source),
                            "sha256": BASE.sha256_path(source),
                        },
                    }
                )
            self.assertEqual(
                binding["direct_objects"],
                sorted(
                    expected_direct,
                    key=lambda item: item["output"]["path"],
                ),
                "direct objects bind their exact output and logical source",
            )
            self.assertEqual(
                binding["linker_command_sha256"],
                topology["linker_command_sha256"],
            )
            self.assertEqual(
                binding["build_ninja_sha256"],
                topology["build_ninja_sha256"],
            )
            self.assertEqual(
                binding["rules_ninja_sha256"],
                topology["rules_ninja_sha256"],
            )
            self.assertEqual(
                binding["members"],
                ["fixture_main.o", "pble_proto.c.obj"],
                "ordinary archive membership comes from the exact object root",
            )

    def test_generated_header_expected_path_rejects_symlink_alias(self):
        with real_idf_main_topology(self.fixture) as topology:
            expected = topology["generated_headers"][0]
            alias_target = (
                topology["role_root"]
                / "metadata-alias"
                / expected.name
            )
            original = str(expected)

            def use_alias_target(description):
                sources = description["build_component_info"]["main"][
                    "sources"
                ]
                sources[sources.index(original)] = str(alias_target)

            with BASE.new_file(
                alias_target,
                expected.read_bytes(),
            ), BASE.symlink_instead(
                expected,
                alias_target,
            ), changed_json(
                topology["description_path"],
                use_alias_target,
            ):
                self.assertTrue(expected.is_symlink())
                with self.assertRaisesRegex(
                    RELEASE.ReleaseError,
                    "symlink",
                ):
                    self.observe(topology["policy"])

    def test_project_anchor_expected_path_rejects_symlink_alias(self):
        with real_idf_main_topology(self.fixture) as topology:
            expected = topology["project_source"]
            alias_target = (
                topology["role_root"]
                / "project-anchor-alias"
                / expected.name
            )
            original = str(expected)

            def use_alias_target(commands):
                command = next(
                    item for item in commands if item["file"] == original
                )
                command["file"] = str(alias_target)
                command["command"] = command["command"].replace(
                    original,
                    str(alias_target),
                    1,
                )

            with BASE.new_file(
                alias_target,
                b"",
            ), BASE.symlink_instead(
                expected,
                alias_target,
            ), changed_json(
                topology["commands_path"],
                use_alias_target,
            ):
                self.assertTrue(expected.is_symlink())
                with self.assertRaisesRegex(
                    RELEASE.ReleaseError,
                    "symlink",
                ):
                    self.observe(topology["policy"])

    def test_berkeley_direct_output_expected_root_rejects_symlink_alias(self):
        with real_idf_main_topology(self.fixture) as topology:
            expected_relative = topology["direct_loads"]["berkeley"]
            expected_output = topology["role_root"] / expected_relative
            expected_root = (
                topology["role_root"]
                / "esp-idf"
                / "main"
                / "CMakeFiles"
                / "micropy_extmod_btree.dir"
            )
            output_suffix = expected_output.relative_to(expected_root)
            alias_root = topology["role_root"] / "berkeley-output-alias"
            alias_output = alias_root / output_suffix
            alias_relative = alias_output.relative_to(
                topology["role_root"]
            ).as_posix()

            def use_alias_output(commands):
                command = next(
                    item
                    for item in commands
                    if item["file"] == str(topology["berkeley_source"])
                )
                command["output"] = alias_relative
                command["command"] = re.sub(
                    r"(?<= -o )\S+",
                    alias_relative,
                    command["command"],
                    count=1,
                )

            changed_map = (
                topology["map_path"]
                .read_text(encoding="utf-8")
                .replace(
                    "LOAD %s\n" % expected_relative,
                    "LOAD %s\n" % alias_relative,
                )
            )
            changed_link = (
                topology["build_ninja_path"]
                .read_text(encoding="utf-8")
                .replace(expected_relative, alias_relative)
            )

            expected_root.rename(alias_root)
            try:
                expected_root.symlink_to(
                    alias_root,
                    target_is_directory=True,
                )
                with changed_json(
                    topology["commands_path"],
                    use_alias_output,
                ), BASE.patched_text(
                    topology["map_path"],
                    changed_map,
                ), BASE.patched_text(
                    topology["build_ninja_path"],
                    changed_link,
                ):
                    self.assertTrue(expected_root.is_symlink())
                    self.assertTrue(alias_output.is_file())
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        "symlink",
                    ):
                        self.observe(topology["policy"])
            finally:
                if expected_root.exists() or expected_root.is_symlink():
                    expected_root.unlink()
                if alias_root.exists():
                    alias_root.rename(expected_root)

    def test_json_output_and_compiler_o_are_resolved_from_distinct_bases(self):
        with real_idf_main_topology(self.fixture) as topology:
            # Positive case: JSON `output` is role-relative, while compiler
            # `-o` is relative to a nested command working directory.
            self.observe(topology["policy"])

            wrong_output = topology["role_root"] / "wrong" / "app_core.o"
            with BASE.new_file(wrong_output, b"wrong compiler output\n"):

                def mismatch_compiler_output(commands):
                    command = next(
                        item
                        for item in commands
                        if item["file"].endswith(
                            "/components/app_core/app_core.c"
                        )
                    )
                    command["command"] = re.sub(
                        r"(?<= -o )\S+",
                        "../wrong/app_core.o",
                        command["command"],
                        count=1,
                    )

                with changed_json(
                    topology["commands_path"],
                    mismatch_compiler_output,
                ):
                    self.assert_rejected(topology["policy"])

    def test_compile_command_text_rejects_shell_and_response_control(self):
        commands_path = (
            self.fixture.build_root / "esp32" / "compile_commands.json"
        )
        cases = (
            (
                "shell control",
                lambda command: (
                    command
                    + " && cp other.o %s" % command.rsplit(" ", 1)[-1]
                ),
                "shell",
            ),
            (
                "shell comment before operands",
                lambda command: command.replace(
                    " -c ",
                    " # -c ",
                    1,
                ),
                "shell|comment",
            ),
            (
                "direct response file",
                lambda command: command + " @compile-options.rsp",
                "response file",
            ),
            (
                "driver-wrapped response file",
                lambda command: command + " -Wl,@objects.rsp",
                "response file",
            ),
        )
        for label, mutate, expected_error in cases:
            with self.subTest(control=label):

                def change_command(commands):
                    commands[0]["command"] = mutate(
                        commands[0]["command"]
                    )

                with changed_json(commands_path, change_command):
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        expected_error,
                    ):
                        self.observe()

    def test_compile_arguments_keep_shell_looking_tokens_literal(self):
        commands_path = (
            self.fixture.build_root / "esp32" / "compile_commands.json"
        )

        def use_arguments(commands):
            command = commands[0]
            command["arguments"] = [
                *shlex.split(command.pop("command"), posix=True),
                "&&",
            ]

        with changed_json(commands_path, use_arguments):
            self.observe()

    def test_compile_arguments_reject_response_file_wrappers(self):
        commands_path = (
            self.fixture.build_root / "esp32" / "compile_commands.json"
        )
        for wrapper in (
            "-Wl,@linker-objects.rsp",
            "-Wa,@assembler-options.rsp",
            "-Wp,@preprocessor-options.rsp",
        ):
            with self.subTest(response_wrapper=wrapper):

                def use_arguments(commands):
                    command = commands[0]
                    command["arguments"] = [
                        *shlex.split(
                            command.pop("command"),
                            posix=True,
                        ),
                        wrapper,
                    ]

                with changed_json(commands_path, use_arguments):
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        "response file",
                    ):
                        self.observe()

    def test_compile_source_operand_rejects_symlink_dotdot_traversal(self):
        with real_idf_main_topology(self.fixture) as topology:
            directory = topology["role_root"]
            expected = topology["project_source"]
            link = directory / "source-operand-link"
            literal_operand = "%s/../%s" % (link.name, expected.name)

            with tempfile.TemporaryDirectory(
                prefix="pyble-source-operand-outside-",
                dir=self.fixture.root,
            ) as temporary:
                outside = Path(temporary)
                (outside / "child").mkdir()
                kernel_source = outside / expected.name
                kernel_source.write_bytes(b"")

                def use_traversal(commands):
                    command = next(
                        item
                        for item in commands
                        if item["file"] == str(expected)
                    )
                    command["command"] = command["command"].replace(
                        str(expected),
                        literal_operand,
                        1,
                    )

                with BASE.new_symlink(
                    link,
                    outside / "child",
                ), changed_json(
                    topology["commands_path"],
                    use_traversal,
                ):
                    self.assertEqual(
                        Path(
                            os.path.abspath(directory / literal_operand)
                        ),
                        expected,
                        "the vulnerable lexical collapse appears in-root",
                    )
                    self.assertEqual(
                        (directory / literal_operand).resolve(strict=True),
                        kernel_source.resolve(),
                        "kernel traversal follows the symlink before `..`",
                    )
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        "symlink|travers|unsafe",
                    ):
                        self.observe(topology["policy"])

    def test_compile_output_operand_rejects_symlink_dotdot_traversal(self):
        with real_idf_main_topology(self.fixture) as topology:
            directory = topology["role_root"]
            expected_relative = topology["direct_loads"]["project"]
            expected = directory / expected_relative
            link = directory / "output-operand-link"
            literal_operand = "%s/../%s" % (
                link.name,
                expected_relative,
            )

            with tempfile.TemporaryDirectory(
                prefix="pyble-output-operand-outside-",
                dir=self.fixture.root,
            ) as temporary:
                outside = Path(temporary)
                (outside / "child").mkdir()
                kernel_output = outside / expected_relative
                kernel_output.parent.mkdir(parents=True, exist_ok=True)
                kernel_output.write_bytes(b"outside direct object\n")

                def use_traversal(commands):
                    command = next(
                        item
                        for item in commands
                        if item["file"] == str(topology["project_source"])
                    )
                    command["command"] = re.sub(
                        r"(?<= -o )\S+",
                        literal_operand,
                        command["command"],
                        count=1,
                    )

                with BASE.new_symlink(
                    link,
                    outside / "child",
                ), changed_json(
                    topology["commands_path"],
                    use_traversal,
                ):
                    self.assertEqual(
                        Path(
                            os.path.abspath(directory / literal_operand)
                        ),
                        expected,
                        "the vulnerable lexical collapse appears in-root",
                    )
                    self.assertEqual(
                        (directory / literal_operand).resolve(strict=True),
                        kernel_output.resolve(),
                        "kernel traversal follows the symlink before `..`",
                    )
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        "symlink|travers|unsafe",
                    ):
                        self.observe(topology["policy"])

    def test_generated_main_header_near_match_is_rejected(self):
        with real_idf_main_topology(self.fixture) as topology:
            self.observe(topology["policy"])
            wrong_header = (
                topology["role_root"] / "generated-headers" / "mpversion.h"
            )
            with BASE.new_file(wrong_header, b"/* wrong header root */\n"):

                def use_wrong_header(description):
                    sources = description["build_component_info"]["main"][
                        "sources"
                    ]
                    expected = str(
                        topology["role_root"] / "genhdr" / "mpversion.h"
                    )
                    sources[sources.index(expected)] = str(wrong_header)

                with changed_json(
                    topology["description_path"],
                    use_wrong_header,
                ):
                    self.assert_rejected(topology["policy"])

    def test_main_external_source_near_match_roots_are_rejected(self):
        with real_idf_main_topology(self.fixture) as topology:
            self.observe(topology["policy"])
            wrong_pyble = (
                self.fixture.firmware
                / "user_c_modules"
                / "pyble-lookalike"
                / "pble_proto.c"
            )
            with BASE.new_file(
                wrong_pyble,
                b"// SPDX-License-Identifier: MIT\n",
            ):
                original = str(topology["pyble_source"])

                def use_wrong_pyble(commands):
                    for command in commands:
                        if command["file"] == original:
                            command["file"] = str(wrong_pyble)
                            command["command"] = command["command"].replace(
                                original,
                                str(wrong_pyble),
                            )

                with changed_json(topology["commands_path"], use_wrong_pyble):
                    self.assert_rejected(topology["policy"])

        with real_idf_main_topology(self.fixture) as topology:
            self.observe(topology["policy"])
            wrong_berkeley = (
                self.fixture.firmware
                / "upstream"
                / "micropython"
                / "lib"
                / "berkeley-db-1.xx"
                / "btree"
                / "bt_close.c"
            )
            original = str(topology["berkeley_source"])

            def use_shared_berkeley(commands):
                command = next(
                    item for item in commands if item["file"] == original
                )
                command["file"] = str(wrong_berkeley)
                command["command"] = command["command"].replace(
                    original,
                    str(wrong_berkeley),
                )

            with changed_json(
                topology["commands_path"],
                use_shared_berkeley,
            ):
                self.assert_rejected(topology["policy"])

    def test_sources_cannot_bind_unrelated_component_archive(self):
        cases = (
            ("described main component", None, "foreign_app.o"),
            ("PyBLE", "pyble_source", "pble_proto.c.obj"),
            ("Berkeley DB", "berkeley_source", "bt_close.c.obj"),
        )
        for label, source_key, member in cases:
            with self.subTest(source_family=label):
                with real_idf_main_topology(self.fixture) as topology:
                    source = (
                        topology["main_source"]
                        if source_key is None
                        else topology[source_key]
                    )
                    if source_key is None:
                        description = json.loads(
                            topology["description_path"].read_text(
                                encoding="utf-8"
                            )
                        )
                        self.assertEqual(
                            [
                                name
                                for name, component in description[
                                    "build_component_info"
                                ].items()
                                if str(source) in component["sources"]
                            ],
                            ["main"],
                            "the ordinary source belongs only to component A",
                        )
                    archive = (
                        topology["role_root"]
                        / "micropython"
                        / "libmicropython.a"
                    )
                    output_relative = (
                        "micropython/CMakeFiles/micropython.dir/%s"
                        % member
                    )
                    output = topology["role_root"] / output_relative
                    commands = json.loads(
                        topology["commands_path"].read_text(
                            encoding="utf-8"
                        )
                    )
                    compiler = commands[0]["command"].split(" ", 1)[0]
                    unrelated_command = {
                        "directory": str(topology["role_root"]),
                        "command": "%s -c %s -o %s"
                        % (compiler, source, output_relative),
                        "file": str(source),
                        "output": output_relative,
                    }
                    members = BASE.parse_ar_members(archive.read_bytes())
                    changed_archive = BASE.make_ar_bytes(
                        [
                            *members.items(),
                            (member, b"misowned exact-source object\n"),
                        ]
                    )
                    changed_map = (
                        topology["map_path"].read_text(encoding="utf-8")
                        + "micropython/libmicropython.a(%s)\n" % member
                    )

                    with BASE.new_file(
                        output,
                        b"misowned exact-source object\n",
                    ), BASE.patched_bytes(
                        archive,
                        changed_archive,
                    ), changed_json(
                        topology["commands_path"],
                        lambda value: value.append(unrelated_command),
                    ), BASE.patched_text(
                        topology["map_path"],
                        changed_map,
                    ):
                        with self.assertRaises(RELEASE.ReleaseError):
                            self.observe(topology["policy"])

    def test_direct_load_requires_exact_path_not_matching_basename(self):
        with real_idf_main_topology(self.fixture) as topology:
            self.observe(topology["policy"])
            exact = topology["direct_loads"]["pyble"]
            wrong = "wrong-direct-root/pble_proto.c.obj"
            wrong_object = topology["role_root"] / wrong
            with BASE.new_file(wrong_object, b"wrong direct object\n"):
                changed = (
                    topology["map_path"]
                    .read_text(encoding="utf-8")
                    .replace("LOAD %s\n" % exact, "LOAD %s\n" % wrong)
                )
                with BASE.patched_text(topology["map_path"], changed):
                    self.assert_rejected(topology["policy"])

    def test_direct_object_wrong_root_is_rejected(self):
        with real_idf_main_topology(self.fixture) as topology:
            self.observe(topology["policy"])
            exact = topology["direct_loads"]["berkeley"]
            wrong = exact.replace(
                "CMakeFiles/micropy_extmod_btree.dir/",
                "CMakeFiles/micropy_extmod_btree-lookalike.dir/",
            )
            wrong_object = topology["role_root"] / wrong
            with BASE.new_file(wrong_object, b"wrong Berkeley output root\n"):

                def move_berkeley_output(commands):
                    command = next(
                        item
                        for item in commands
                        if item["file"] == str(topology["berkeley_source"])
                    )
                    command["output"] = wrong
                    command["command"] = re.sub(
                        r"(?<= -o )\S+",
                        wrong,
                        command["command"],
                        count=1,
                    )

                changed_map = (
                    topology["map_path"]
                    .read_text(encoding="utf-8")
                    .replace("LOAD %s\n" % exact, "LOAD %s\n" % wrong)
                )
                changed_link = (
                    topology["build_ninja_path"]
                    .read_text(encoding="utf-8")
                    .replace(exact, wrong)
                )
                with changed_json(
                    topology["commands_path"],
                    move_berkeley_output,
                ), BASE.patched_text(
                    topology["map_path"],
                    changed_map,
                ), BASE.patched_text(
                    topology["build_ninja_path"], changed_link
                ):
                    self.assert_rejected(topology["policy"])

    def test_unlinked_direct_like_output_is_allowed_but_extra_load_is_rejected(self):
        with real_idf_main_topology(self.fixture) as topology:
            self.observe(topology["policy"])
            extra_source = (
                self.fixture.firmware
                / "user_c_modules"
                / "pyble"
                / "pble_ble.c"
            )
            extra_relative = (
                "CMakeFiles/micropython.elf.dir/%s.obj"
                % extra_source.as_posix().lstrip("/")
            )
            extra_output = topology["role_root"] / extra_relative
            commands = json.loads(
                topology["commands_path"].read_text(encoding="utf-8")
            )
            compiler = commands[0]["command"].split(" ", 1)[0]
            extra_command = {
                "directory": str(topology["role_root"]),
                "command": "%s -c %s -o %s"
                % (compiler, extra_source, extra_relative),
                "file": str(extra_source),
                "output": extra_relative,
            }
            with BASE.new_file(extra_output, b"unlinked direct PyBLE object\n"):
                with changed_json(
                    topology["commands_path"],
                    lambda value: value.append(extra_command),
                ):
                    observed = self.by_id(
                        self.observe(topology["policy"]),
                        topology["identifier"],
                    )
                    self.assertNotIn(
                        self.fixture._source_path(extra_source),
                        {
                            item["path"]
                            for item in observed["generated_binding"]["sources"]
                        },
                        "a compile output absent from archive membership and "
                        "the map is build-only even under a direct-like root",
                    )
                    self.assertNotIn(
                        self.fixture._source_path(extra_source),
                        {
                            item["source"]["path"]
                            for item in observed["generated_binding"][
                                "direct_objects"
                            ]
                        },
                    )

        with real_idf_main_topology(self.fixture) as topology:
            self.observe(topology["policy"])
            ghost = "CMakeFiles/micropython.elf.dir/ghost.c.obj"
            ghost_path = topology["role_root"] / ghost
            with BASE.new_file(ghost_path, b"uncompiled direct object\n"):
                changed_map = (
                    topology["map_path"].read_text(encoding="utf-8")
                    + "LOAD %s\n" % ghost
                )
                with BASE.patched_text(
                    topology["map_path"],
                    changed_map,
                ):
                    self.assert_rejected(topology["policy"])

    def test_map_direct_objects_must_equal_link_command_objects(self):
        with real_idf_main_topology(self.fixture) as topology:
            self.observe(topology["policy"])
            exact = topology["direct_loads"]["pyble"]
            replacement = topology["outputs"]["build_only"]
            changed_link = (
                topology["build_ninja_path"]
                .read_text(encoding="utf-8")
                .replace(exact, replacement)
            )
            with BASE.patched_text(
                topology["build_ninja_path"], changed_link
            ):
                self.assert_rejected(topology["policy"])

    def test_link_command_rejects_driver_wrapped_response_file(self):
        with real_idf_main_topology(self.fixture) as topology:
            changed_link = (
                topology["rules_ninja_path"]
                .read_text(encoding="utf-8")
                .replace(
                    " -o $TARGET_FILE",
                    " -Wl,@objects.rsp -o $TARGET_FILE",
                )
            )
            with BASE.patched_text(
                topology["rules_ninja_path"], changed_link
            ):
                with self.assertRaises(RELEASE.ReleaseError):
                    self.observe(topology["policy"])

    def test_link_command_rejects_shell_comment_before_direct_objects(self):
        with real_idf_main_topology(self.fixture) as topology:
            original = topology["rules_ninja_path"].read_text(
                encoding="utf-8"
            )
            changed_link = original.replace(
                " -o $TARGET_FILE",
                " # attacker -o $TARGET_FILE",
            )
            with BASE.patched_text(
                topology["rules_ninja_path"], changed_link
            ):
                with self.assertRaises(RELEASE.ReleaseError):
                    self.observe(topology["policy"])

    def test_opaque_archive_requires_exact_reviewed_bytes(self):
        observations = self.observe()
        identifier = "controller--esp32-4mb--application"
        observed = self.by_id(observations, identifier)
        reviewed = (
            self.fixture.repo / observed["reviewed_source_path"]
        )
        linked = Path(observed["observed_path"])
        self.assertEqual(linked.read_bytes(), reviewed.read_bytes())
        self.assertEqual(observed["sha256"], BASE.sha256_path(reviewed))

        changed = BASE.make_ar_bytes(
            [("controller.o", b"changed but still a valid archive\n")]
        )
        with BASE.patched_bytes(linked, changed):
            self.assert_rejected()

    def test_external_toolchain_root_is_derived_from_all_frontends(self):
        observations = self.observe()
        identifier = "libgcc--esp32-4mb--application"
        observed = self.by_id(observations, identifier)
        toolchain = self.fixture.toolchain
        self.assertFalse(
            Path(observed["observed_path"]).is_relative_to(
                self.fixture.repo
            )
        )
        self.assertEqual(
            observed["compiler_paths"],
            [
                str(
                    toolchain["compilers"][relative].resolve()
                )
                for relative in toolchain["compiler_relatives"]
            ],
        )
        self.assertEqual(
            Path(observed["observed_path"]),
            (
                toolchain["installed_root"]
                / observed["relative_path"]
            ).resolve(),
        )

        sibling = (
            toolchain["installed_root"].parent
            / (toolchain["root_name"] + "-unreviewed")
        )
        shutil.copytree(toolchain["installed_root"], sibling)
        commands = self.fixture.build_root / "esp32/compile_commands.json"

        def reroot_frontends(values):
            for item in values:
                for relative in toolchain["compiler_relatives"]:
                    item["command"] = item["command"].replace(
                        str(toolchain["compilers"][relative]),
                        str(sibling / relative),
                        1,
                    )

        try:
            with changed_json(
                commands,
                reroot_frontends,
            ):
                self.assert_rejected()
        finally:
            shutil.rmtree(sibling)

    def test_mbedtls_is_exactly_three_nested_linked_archives(self):
        observations = self.observe()
        mbed = [
            item
            for item in observations
            if item["profile_id"] == "esp32-4mb"
            and item["kind"] == "generated-supplemental-archive"
        ]
        self.assertEqual(
            {Path(item["observed_path"]).name for item in mbed},
            {"libmbedcrypto.a", "libmbedtls.a", "libmbedx509.a"},
        )
        self.assertTrue(
            all(
                "/esp-idf/mbedtls/mbedtls/library/" in item["observed_path"]
                for item in mbed
            )
        )

        map_path = self.fixture.build_root / "esp32/micropython.map"
        value = map_path.read_text(encoding="utf-8")
        changed = "\n".join(
            line for line in value.splitlines() if "libmbedx509.a" not in line
        ) + "\n"
        with BASE.patched_text(map_path, changed):
            self.assert_rejected()

    def test_frozen_source_tree_comes_from_literal_manifest_selection(self):
        observations = self.observe()
        identifier = "neopixel--esp32-4mb--application"
        observed = self.by_id(observations, identifier)
        self.assertEqual(observed["frozen_destinations"], ["neopixel.py"])
        self.assertEqual(
            observed["sha256"],
            BASE.sha256_tree(Path(observed["observed_path"])),
        )

        manifest_lines = (
            'module("flashbdev.py", base_path="$(PORT_DIR)/modules")\n',
            'module("inisetup.py", base_path="$(PORT_DIR)/modules")\n',
            'include("$(MPY_DIR)/extmod/asyncio")\n',
            'require("neopixel")\n',
            'module("_boot.py", base_path="$(BOARD_DIR)")\n',
            (
                'module("pyble/pyble_agent.py", '
                'base_path="$(BOARD_DIR)")\n'
            ),
        )
        frozen_names = (
            "flashbdev.py",
            "inisetup.py",
            "asyncio/__init__.py",
            "asyncio/core.py",
            "_boot.py",
            "pyble/pyble_agent.py",
            "neopixel.py",
        )
        for _profile_id, target, _idf_target in PROFILE_TARGETS:
            manifest = (
                self.fixture.firmware
                / "board_overlays"
                / target
                / "manifest.py"
            )
            frozen = (
                self.fixture.build_root / target / "frozen_content.c"
            )
            manifest_before = manifest.read_text(encoding="utf-8")
            frozen_before = frozen.read_text(encoding="utf-8")

            expected_manifest_lines = manifest_lines + (
                (
                    'module("pyble_st7789.py", '
                    'base_path="$(BOARD_DIR)")\n'
                ),
                (
                    'module("pyble_waveshare_lcd147b.py", '
                    'base_path="$(BOARD_DIR)")\n'
                ),
            ) if target == "waveshare-esp32-s3-lcd-147b" else manifest_lines
            expected_frozen_names = frozen_names + (
                ("pyble_st7789.py", "pyble_waveshare_lcd147b.py")
                if target == "waveshare-esp32-s3-lcd-147b"
                else ()
            )

            for manifest_line in expected_manifest_lines:
                self.assertIn(manifest_line, manifest_before)
                with self.subTest(
                    target=target,
                    manifest_missing=manifest_line.strip(),
                ):
                    with BASE.patched_text(
                        manifest,
                        manifest_before.replace(manifest_line, "", 1),
                    ):
                        self.assert_rejected()

            for frozen_name in expected_frozen_names:
                with self.subTest(
                    target=target,
                    generated_missing=frozen_name,
                ):
                    changed = "\n".join(
                        line
                        for line in frozen_before.splitlines()
                        if frozen_name not in line
                    )
                    with BASE.patched_text(frozen, changed + "\n"):
                        self.assert_rejected()

            with self.subTest(target=target, inventory="manifest-only"):
                with BASE.patched_text(
                    manifest,
                    manifest_before
                    + 'freeze("fixture", "only_manifest.py")\n',
                ):
                    self.assert_rejected()
            with self.subTest(target=target, inventory="generated-only"):
                with BASE.patched_text(
                    frozen,
                    frozen_before
                    + "// - frozen file name: only_generated.py\n",
                ):
                    self.assert_rejected()

        selected_source = (
            self.fixture.firmware
            / "upstream"
            / "micropython"
            / "extmod"
            / "asyncio"
            / "core.py"
        )
        original_stat = selected_source.stat()
        with BASE.patched_bytes(
            selected_source,
            selected_source.read_bytes() + b"# stale-timestamp mutation\n",
        ):
            os.utime(
                selected_source,
                ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
            )
            self.assert_rejected()

    def test_frozen_proof_uses_retained_board_when_ambient_boards_are_absent(self):
        ambient_boards = []
        backup_root = self.fixture.root / "ambient-generated-board-backup"
        backup_root.mkdir()
        try:
            for _profile_id, target, _idf_target in PROFILE_TARGETS:
                board_name = RELEASE.FROZEN_TARGET_SETTINGS[target]["board"]
                ambient = (
                    self.fixture.firmware
                    / "upstream"
                    / "micropython"
                    / "ports"
                    / "esp32"
                    / "boards"
                    / board_name
                )
                retained = (
                    self.fixture.build_root
                    / ".sources"
                    / target
                    / "micropython"
                    / "ports"
                    / "esp32"
                    / "boards"
                    / board_name
                )
                self.assertTrue(retained.is_dir())
                backup = backup_root / target
                ambient.rename(backup)
                ambient_boards.append((ambient, backup))

            context = self.observe_context()
            self.assertEqual(
                {record["target"] for record in context["manifest_evidence"]},
                {target for _profile, target, _idf in PROFILE_TARGETS},
            )
        finally:
            for ambient, backup in reversed(ambient_boards):
                backup.rename(ambient)
            backup_root.rmdir()

    def test_retained_board_missing_or_drift_rejects_ambient_decoy(self):
        target = "esp32"
        board_name = RELEASE.FROZEN_TARGET_SETTINGS[target]["board"]
        relative = Path("ports") / "esp32" / "boards" / board_name
        ambient = (
            self.fixture.firmware / "upstream" / "micropython" / relative
        )
        retained = (
            self.fixture.build_root
            / ".sources"
            / target
            / "micropython"
            / relative
        )
        self.assertEqual(
            (ambient / "manifest.py").read_bytes(),
            (retained / "manifest.py").read_bytes(),
            "the ambient tree must be a convincing decoy for this boundary test",
        )

        with self.subTest(retained="missing"):
            with BASE.removed_file(retained / "manifest.py"):
                self.assert_rejected()
        with self.subTest(retained="drift"):
            boot = retained / "_boot.py"
            with BASE.patched_bytes(
                boot,
                boot.read_bytes() + b"# retained target-local drift\n",
            ):
                self.assert_rejected()

    def test_generated_board_evidence_uses_build_namespace(self):
        context = self.observe_context()
        evidence = {
            record["target"]: record
            for record in context["manifest_evidence"]
        }
        for _profile_id, target, _idf_target in PROFILE_TARGETS:
            board_name = RELEASE.FROZEN_TARGET_SETTINGS[target]["board"]
            prefix = (
                "build/.sources/%s/micropython/ports/esp32/boards/%s/"
                % (target, board_name)
            )
            self.assertEqual(
                evidence[target]["generated_board_manifest"],
                prefix + "manifest.py",
            )
            for record in evidence[target]["first_party_frozen_sources"]:
                self.assertEqual(
                    record["generated_path"],
                    prefix + record["destination"],
                )

    def test_first_party_sources_are_mit_identical_and_waveshare_only(self):
        context = self.observe_context()
        evidence = {
            record["target"]: record
            for record in context["manifest_evidence"]
        }
        canonical_relative = "firmware/python_modules/pyble_st7789.py"
        canonical = self.fixture.repo / canonical_relative
        companion_relative = (
            "firmware/board_overlays/waveshare-esp32-s3-lcd-147b/"
            "pyble_waveshare_lcd147b.py"
        )
        companion = self.fixture.repo / companion_relative

        for _profile_id, target, _idf_target in PROFILE_TARGETS:
            board = RELEASE.FROZEN_TARGET_SETTINGS[target]["board"]
            generated_relative = (
                "build/.sources/%s/micropython/ports/esp32/boards/%s/"
                "pyble_st7789.py" % (target, board)
            )
            selected = {
                item["destination"]: item
                for item in evidence[target]["selections"]
            }
            first_party = evidence[target]["first_party_frozen_sources"]
            if target == "waveshare-esp32-s3-lcd-147b":
                self.assertEqual(
                    selected["pyble_st7789.py"]["source_path"],
                    canonical_relative,
                )
                self.assertEqual(
                    selected["pyble_waveshare_lcd147b.py"]["source_path"],
                    companion_relative,
                )
                self.assertEqual(
                    first_party,
                    [
                        {
                            "destination": "pyble_st7789.py",
                            "canonical_path": canonical_relative,
                            "generated_path": generated_relative,
                            "sha256": BASE.sha256_path(canonical),
                            "spdx_expression": "MIT",
                        },
                        {
                            "destination": "pyble_waveshare_lcd147b.py",
                            "canonical_path": companion_relative,
                            "generated_path": generated_relative.replace(
                                "pyble_st7789.py",
                                "pyble_waveshare_lcd147b.py",
                            ),
                            "sha256": BASE.sha256_path(companion),
                            "spdx_expression": "MIT",
                        },
                    ],
                )
            else:
                self.assertNotIn("pyble_st7789.py", selected)
                self.assertNotIn("pyble_waveshare_lcd147b.py", selected)
                self.assertEqual(first_party, [])

        settings = RELEASE.FROZEN_TARGET_SETTINGS[
            "waveshare-esp32-s3-lcd-147b"
        ]
        generated = (
            self.fixture.build_root
            / ".sources"
            / "waveshare-esp32-s3-lcd-147b"
            / "micropython"
            / "ports"
            / "esp32"
            / "boards"
            / settings["board"]
            / "pyble_st7789.py"
        )
        with self.subTest(mutation="canonical-copy-drift"):
            with BASE.patched_bytes(
                canonical,
                canonical.read_bytes() + b"# canonical drift\n",
            ):
                self.assert_rejected()
        with self.subTest(mutation="generated-copy-drift"):
            with BASE.patched_bytes(
                generated,
                generated.read_bytes() + b"# generated drift\n",
            ):
                self.assert_rejected()

        canonical_before = canonical.read_bytes()
        generated_before = generated.read_bytes()
        non_mit = canonical_before.replace(
            b"SPDX-License-Identifier: MIT",
            b"SPDX-License-Identifier: Apache-2.0",
            1,
        )
        self.assertNotEqual(non_mit, canonical_before)
        try:
            canonical.write_bytes(non_mit)
            generated.write_bytes(non_mit)
            self.fixture.regenerate_frozen_payload(
                "waveshare-esp32-s3-lcd-147b"
            )
            with self.subTest(mutation="non-mit-first-party-source"):
                self.assert_rejected()
        finally:
            canonical.write_bytes(canonical_before)
            generated.write_bytes(generated_before)
            self.fixture.regenerate_frozen_payload(
                "waveshare-esp32-s3-lcd-147b"
            )

        for target in ("esp32", "esp32-s3", "esp32-c3"):
            board = RELEASE.FROZEN_TARGET_SETTINGS[target]["board"]
            stray = (
                self.fixture.build_root
                / ".sources"
                / target
                / "micropython"
                / "ports"
                / "esp32"
                / "boards"
                / board
                / "pyble_st7789.py"
            )
            with self.subTest(mutation="stray-generated-copy", target=target):
                with BASE.new_file(stray, canonical_before):
                    self.assert_rejected()

    def test_policy_and_link_map_reject_missing_or_extra_inputs(self):
        self.observe()
        missing = copy.deepcopy(self.fixture.policy)
        missing["resolved_inputs"] = [
            item
            for item in missing["resolved_inputs"]
            if item["id"] != "app_core--esp32-4mb--application"
        ]
        self.assert_rejected(missing)

        extra = copy.deepcopy(self.fixture.policy)
        ghost = copy.deepcopy(
            next(
                item
                for item in extra["resolved_inputs"]
                if item["id"] == "app_core--esp32-4mb--application"
            )
        )
        ghost["id"] = "ghost--esp32-4mb--application"
        ghost["generated_matcher"]["component"] = "ghost"
        extra["resolved_inputs"].append(ghost)
        self.assert_rejected(extra)

        archive = self.fixture.build_root / "esp32/libunreviewed.a"
        map_path = self.fixture.build_root / "esp32/micropython.map"
        linked = map_path.read_text(encoding="utf-8") + (
            "libunreviewed.a(unreviewed.o)\nLOAD libunreviewed.a\n"
        )
        with BASE.new_file(
            archive,
            BASE.make_ar_bytes(
                [("unreviewed.o", b"unreviewed linked object\n")]
            ),
        ):
            with BASE.patched_text(map_path, linked):
                self.assert_rejected()

    def test_frozen_payload_reconstruction_rejects_stale_or_substituted_bytes(self):
        target_build = self.fixture.build_root / "esp32"
        qstr = target_build / "genhdr" / "qstrdefs.preprocessed.h"
        retained_mpy = target_build / "frozen_mpy" / "asyncio" / "core.mpy"
        frozen = target_build / "frozen_content.c"

        for label, path in (
            ("qstr", qstr),
            ("retained-mpy", retained_mpy),
            ("frozen-c", frozen),
        ):
            with self.subTest(mutation=label):
                with BASE.patched_bytes(
                    path,
                    path.read_bytes() + b"\n# substituted bytes\n",
                ):
                    self.assert_rejected()

        outside = self.fixture.root / "equal-retained-core.mpy"
        outside.write_bytes(retained_mpy.read_bytes())
        try:
            with BASE.symlink_instead(retained_mpy, outside):
                self.assert_rejected()
        finally:
            outside.unlink()

        manifest = (
            self.fixture.firmware
            / "board_overlays"
            / "esp32"
            / "manifest.py"
        )
        original = manifest.read_text(encoding="utf-8")
        with BASE.patched_text(
            manifest,
            original.replace(
                'module("flashbdev.py", base_path="$(PORT_DIR)/modules")',
                'module("flashbdev.py", base_path="$(PORT_DIR)/modules", opt=3)',
                1,
            ),
        ):
            self.assert_rejected()

    def test_internally_consistent_frozen_replacement_rejects_unchanged_archive(
        self,
    ):
        target_build = self.fixture.build_root / "esp32"
        qstr = target_build / "genhdr" / "qstrdefs.preprocessed.h"
        frozen = target_build / "frozen_content.c"
        retained_root = target_build / "frozen_mpy"
        archive = target_build / "micropython" / "libmicropython.a"
        object_path = (
            target_build
            / "micropython"
            / "CMakeFiles"
            / "micropython.dir"
            / "frozen.o"
        )
        frozen_before = frozen.read_bytes()
        qstr_before = qstr.read_bytes()
        retained_before = {
            path.relative_to(retained_root).as_posix(): path.read_bytes()
            for path in retained_root.rglob("*.mpy")
        }
        archive_before = archive.read_bytes()
        linked_members = BASE.parse_ar_members(archive_before)
        expected_object = self.fixture.frozen_object_bytes(frozen_before)
        self.assertEqual(object_path.read_bytes(), expected_object)
        self.assertEqual(linked_members["frozen.o"], expected_object)

        try:
            qstr.write_bytes(
                qstr_before
                + b"QCFG(SYNTHETIC_REPLACEMENT, enabled)\n"
            )
            self.fixture.regenerate_frozen_payload("esp32")
            retained_after = {
                path.relative_to(retained_root).as_posix(): path.read_bytes()
                for path in retained_root.rglob("*.mpy")
            }
            self.assertEqual(set(retained_after), set(retained_before))
            self.assertTrue(
                all(
                    retained_after[name] != retained_before[name]
                    for name in retained_before
                ),
                "the attack fixture did not replace every retained MPY",
            )
            self.assertNotEqual(frozen.read_bytes(), frozen_before)
            self.assertEqual(
                archive.read_bytes(),
                archive_before,
                "the attack must leave the linked archive unchanged",
            )
            self.assert_rejected()
        finally:
            qstr.write_bytes(qstr_before)
            frozen.write_bytes(frozen_before)
            for relative, value in retained_before.items():
                (retained_root / relative).write_bytes(value)

    def test_duplicate_frozen_input_cannot_own_the_same_destination(self):
        policy = copy.deepcopy(self.fixture.policy)
        original = next(
            item
            for item in policy["resolved_inputs"]
            if item["id"] == "neopixel--esp32-4mb--application"
        )
        duplicate = copy.deepcopy(original)
        duplicate["id"] = "neopixel-shadow--esp32-4mb--application"
        policy["resolved_inputs"].append(duplicate)
        self.assert_rejected(policy)

    def test_frozen_reconstruction_environment_drops_loader_and_python_injection(
        self,
    ):
        actual_run = RELEASE.subprocess.run
        observed_environments = []

        def sanitized_execution(*args, **kwargs):
            environment = kwargs.get("env")
            self.assertIsInstance(environment, dict)
            observed_environments.append(dict(environment))
            safe_kwargs = dict(kwargs)
            safe_environment = dict(environment)
            safe_environment.pop("DYLD_INSERT_LIBRARIES", None)
            safe_environment.pop("PYTHONPATH", None)
            safe_kwargs["env"] = safe_environment
            return actual_run(*args, **safe_kwargs)

        poisoned = {
            "DYLD_INSERT_LIBRARIES": "/untrusted/injection.dylib",
            "PYTHONPATH": "/untrusted/python-modules",
        }
        with mock.patch.dict(os.environ, poisoned, clear=False):
            with mock.patch.object(
                RELEASE.subprocess,
                "run",
                side_effect=sanitized_execution,
            ):
                self.observe()

        self.assertGreaterEqual(
            len(observed_environments),
            2 * len(PROFILE_TARGETS),
        )
        inherited = [
            {
                name
                for name in ("DYLD_INSERT_LIBRARIES", "PYTHONPATH")
                if name in environment
            }
            for environment in observed_environments
        ]
        self.assertEqual(
            inherited,
            [set() for _environment in observed_environments],
        )

    def test_clean_mpy_cross_proof_uses_the_candidate_source_date_epoch(self):
        candidate_epochs = {
            json.loads(
                (
                    self.fixture.build_root
                    / target
                    / "pyble-build-provenance.json"
                ).read_text(encoding="utf-8")
            )["source_date_epoch"]
            for _profile_id, target, _idf_target in PROFILE_TARGETS
        }
        self.assertEqual(
            len(candidate_epochs),
            1,
            "the fixture must represent one candidate source identity",
        )
        expected_epoch = str(candidate_epochs.pop())
        actual_run = RELEASE.subprocess.run
        observed_mpy_cross_epochs = []

        def capture_clean_compiler_build(*args, **kwargs):
            command = [
                os.fspath(value)
                for value in (args[0] if args else kwargs.get("args", ()))
            ]
            if (
                command
                and Path(command[0]).name in {"make", "gmake"}
                and any("mpy-cross" in value for value in command[1:])
            ):
                environment = kwargs.get("env")
                self.assertIsInstance(environment, dict)
                observed_mpy_cross_epochs.append(
                    environment.get("SOURCE_DATE_EPOCH")
                )
            return actual_run(*args, **kwargs)

        with mock.patch.dict(
            os.environ,
            {"SOURCE_DATE_EPOCH": "1"},
            clear=False,
        ):
            with mock.patch.object(
                RELEASE.subprocess,
                "run",
                side_effect=capture_clean_compiler_build,
            ):
                self.observe()

        self.assertEqual(
            observed_mpy_cross_epochs,
            [expected_epoch],
            "the clean compiler proof must use the candidate commit epoch, "
            "not the wall clock or an inherited override",
        )

    def test_manifest_metadata_version_rejects_absolute_or_unsafe_tokens(self):
        board_manifest = (
            self.fixture.firmware
            / "board_overlays"
            / "esp32"
            / "manifest.py"
        )
        package_manifest = (
            self.fixture.firmware
            / "upstream"
            / "micropython"
            / "lib"
            / "micropython-lib"
            / "micropython"
            / "drivers"
            / "led"
            / "neopixel"
            / "manifest.py"
        )
        original = package_manifest.read_text(encoding="utf-8")
        for unsafe in (
            "/tmp/absolute-version",
            "version with spaces",
        ):
            with self.subTest(metadata_version=unsafe):
                changed = original.replace(
                    'version="0.1.0"',
                    'version="%s"' % unsafe,
                    1,
                )
                self.assertNotEqual(changed, original)
                with BASE.patched_text(package_manifest, changed):
                    with self.assertRaises(RELEASE.ReleaseError):
                        RELEASE._audit_resolve_manifest_context(
                            board_manifest,
                            repo_root=self.fixture.repo,
                            board_dir=board_manifest.parent,
                        )

    def test_audit_consumes_v2_observations_and_normalizes_reviewed_raw_docs(self):
        if self.fixture.evidence.exists():
            shutil.rmtree(self.fixture.evidence)
        self.fixture.evidence.mkdir()
        observer = getattr(RELEASE, "_audit_observe_policy_v2_context", None)
        self.assertTrue(
            callable(observer),
            "release_bundle.py lacks _audit_observe_policy_v2_context",
        )
        normalizer = RELEASE._audit_normalize_spdx
        with installed_policy(self.fixture.base, self.fixture.policy):
            with mock.patch.object(
                RELEASE,
                "_audit_observe_policy_v2_context",
                wraps=observer,
            ) as observed_call:
                with mock.patch.object(
                    RELEASE,
                    "_audit_normalize_spdx",
                    wraps=normalizer,
                ) as normalize_call:
                    result = RELEASE.audit_release_licenses(
                        build_root=self.fixture.build_root,
                        repo_root=self.fixture.repo,
                        evidence_dir=self.fixture.evidence,
                        runner=self.fixture.runner,
                    )

        observed_call.assert_called_once()
        self.assertEqual(normalize_call.call_count, len(PROFILE_ROLES))
        raw_paths = sorted(
            (self.fixture.evidence / "raw").glob("*.spdx.tag")
        )
        reviewed_paths = sorted(
            (self.fixture.evidence / "spdx").glob("*.spdx.json")
        )
        self.assertEqual(len(raw_paths), len(PROFILE_ROLES))
        self.assertEqual(len(reviewed_paths), len(PROFILE_ROLES))
        self.assertEqual(len(self.fixture.runner.raw_values), len(PROFILE_ROLES))
        self.assertEqual(
            sorted(path.read_text(encoding="utf-8") for path in raw_paths),
            sorted(self.fixture.runner.raw_values),
            "the audit must retain the exact raw SPDX tag/value bytes",
        )
        self.assertTrue(
            all(
                "NOASSERTION" in path.read_text(encoding="utf-8")
                for path in raw_paths
            )
        )
        for raw in self.fixture.runner.raw_values:
            self.assertIn("SPDXVersion: SPDX-2.2\n", raw)
            self.assertIn("Creator: Tool: ESP-IDF SBOM builder\n", raw)
            self.assertIn("PackageComment: <text>\n", raw)
            self.assertIn(
                "Relationship: SPDXRef-DOCUMENT DESCRIBES ",
                raw,
            )
            self.assertIn(" DEPENDS_ON ", raw)

        expected_licenses = {
            package["dependency"]["name"]: resolution[
                "resolved_input_expression"
            ]
            for package in self.fixture.policy["reviewed_packages"]
            for resolution in self.fixture.policy["resolutions"]
            if resolution["reviewed_package_id"] == package["id"]
        }
        for path in reviewed_paths:
            value = path.read_text(encoding="utf-8")
            self.assertNotIn("NOASSERTION", value)
            self.assertNotIn(str(self.fixture.root), value)
            document = json.loads(value)
            self.assertEqual(document["spdxVersion"], "SPDX-2.3")
            self.assertEqual(document["dataLicense"], "CC0-1.0")
            package_ids = {
                package["SPDXID"] for package in document["packages"]
            }
            self.assertEqual(
                len(package_ids),
                len(document["packages"]),
            )
            self.assertEqual(
                document["creationInfo"].get("comment"),
                (
                    "Generated by the pinned offline tool.\n"
                    "This deliberately spans two lines."
                ),
            )
            for package in document["packages"]:
                self.assertEqual(
                    package["licenseDeclared"],
                    expected_licenses[package["name"]],
                )
                self.assertRegex(
                    package.get("comment", ""),
                    (
                        r"^\nfixture-index: \d+\n"
                        r"source: project_description\.json\n$"
                    ),
                )
            self.assertIn(
                "DEPENDS_ON",
                {
                    relationship["relationshipType"]
                    for relationship in document["relationships"]
                },
            )
        self.assertNotIn("NOASSERTION", BASE.extract_notice(result))
        retained_digest = BASE.sha256_bytes(
            json.dumps(
                self.fixture.retained_source_records,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )
        self.assertEqual(
            result["input_sha256"].get(
                "semantic/retained_source_checkouts"
            ),
            retained_digest,
            "the semantic audit receipt must hash-bind all three retained "
            "checkout identities without host-specific absolute paths",
        )

        receipt = json.loads(
            (self.fixture.evidence / "audit-receipt.json").read_text(
                encoding="utf-8"
            )
        )
        # Policy schema v2 deliberately does not redefine the independently
        # versioned, frozen audit-receipt schema.
        self.assertEqual(receipt["schema_version"], 1)
        self.assertEqual(
            receipt["identities"],
            [
                {"profile_id": profile_id, "role": role}
                for profile_id, role in sorted(PROFILE_ROLES)
            ],
        )
        expected_inputs = {
            "release-tools.lock",
            "license-policy.json",
            "excluded-cves",
            *(
                "resolved-input/%s" % item["id"]
                for item in self.fixture.expected_inputs
            ),
            *(
                "semantic/%s" % collection
                for collection in (
                    "raw_documents",
                    "review_files",
                    "shipment_review",
                    "shipment_classifications",
                    "reviewed_packages",
                    "resolved_inputs",
                    "resolutions",
                    "generated_bindings",
                    "frozen_manifest_evidence",
                    "retained_source_checkouts",
                    "supplemental_packages",
                    "toolchains",
                )
            ),
        }
        self.assertEqual(set(receipt["input_sha256"]), expected_inputs)
        self.assertEqual(
            receipt["executed_artifacts"],
            self.fixture.runner.executed_artifacts,
        )
        self.assertEqual(
            receipt["execution_identity"],
            self.fixture.runner.execution_identity,
        )
        expected_paths = {
            "%s/%s--%s.%s"
            % (directory, profile_id, role, extension)
            for profile_id, role in PROFILE_ROLES
            for directory, extension in (
                ("raw", "spdx.tag"),
                ("spdx", "spdx.json"),
            )
        }
        self.assertEqual(set(receipt["evidence_sha256"]), expected_paths)
        for relative, digest in receipt["evidence_sha256"].items():
            self.assertEqual(
                BASE.sha256_path(self.fixture.evidence / relative),
                digest,
            )


@unittest.skipUnless(RELEASE is not None, "release_bundle.py is unavailable")
class PolicyV2AuditMigrationTests(unittest.TestCase):
    """Unique schema-v1 audit coverage, migrated onto real schema-v2 inputs."""

    ACTIVE_NOTICE_PROFILES = (
        "esp32-4mb",
        "esp32-s3-n16r8",
        "waveshare-esp32-s3-lcd-147b",
    )

    def setUp(self):
        self.fixture = ObservationV2Fixture()

    def tearDown(self):
        self.fixture.close()

    @staticmethod
    def _reset_evidence(fixture):
        if fixture.evidence.exists():
            shutil.rmtree(fixture.evidence)
        fixture.evidence.mkdir()

    def _run_installed(self, fixture=None, runner=None):
        fixture = fixture or self.fixture
        runner = runner or fixture.runner
        self._reset_evidence(fixture)
        result = RELEASE.audit_release_licenses(
            build_root=fixture.build_root,
            repo_root=fixture.repo,
            evidence_dir=fixture.evidence,
            runner=runner,
        )
        notice = BASE.extract_notice(result)
        self.assertTrue(notice.endswith("\n"))
        self.assertTrue(
            any(path.is_file() for path in fixture.evidence.rglob("*")),
            "audit retained no review evidence",
        )
        return notice, result, runner

    def run_audit(self, fixture=None, runner=None, policy=None):
        fixture = fixture or self.fixture
        selected_policy = fixture.policy if policy is None else policy
        with installed_policy(fixture.base, selected_policy):
            return self._run_installed(fixture, runner)

    def assert_audit_rejected(self, *, runner=None, policy=None):
        with self.assertRaises(RELEASE.ReleaseError):
            self.run_audit(runner=runner, policy=policy)

    @staticmethod
    def _three_profile_notice_policy(policy):
        """Give the fixture two dependencies owned only by the deferred C3.

        The release still audits all eight application/bootloader descriptions.
        Only the distributable notice is scoped to the three profiles shipped by
        this release.
        """

        scoped = copy.deepcopy(policy)
        c3_prefix = "esp32-c3-4mb--"
        renamed_inputs = {}
        for record in scoped["resolved_inputs"]:
            if record["profile_id"] != "esp32-c3-4mb":
                continue
            old_identifier = record["id"]
            suffix = old_identifier.replace("--esp32-c3-4mb--", "--")
            new_identifier = c3_prefix + suffix
            renamed_inputs[old_identifier] = new_identifier
            record["id"] = new_identifier
        for collection in ("resolutions", "supplemental_packages"):
            for record in scoped[collection]:
                record["input_refs"] = [
                    renamed_inputs.get(identifier, identifier)
                    for identifier in record["input_refs"]
                ]

        def split_c3_resolution(
            reviewed_package_id,
            c3_reviewed_package_id,
            dependency_name,
        ):
            inputs = {
                record["id"]: record for record in scoped["resolved_inputs"]
            }
            reviewed = next(
                record
                for record in scoped["reviewed_packages"]
                if record["id"] == reviewed_package_id
            )
            c3_reviewed = copy.deepcopy(reviewed)
            c3_reviewed["id"] = c3_reviewed_package_id
            source_commit = "a" * 40
            source_url = (
                "https://example.invalid/%s/commit/%s"
                % (c3_reviewed_package_id, source_commit)
            )
            source_ref = "%s@%s" % (c3_reviewed_package_id, source_commit)
            c3_reviewed["dependency"]["name"] = dependency_name
            c3_reviewed["dependency"]["source_url"] = source_url
            c3_reviewed["dependency"]["version_ref"] = source_ref
            c3_reviewed["source"] = {"url": source_url, "ref": source_ref}

            resolution = next(
                record
                for record in scoped["resolutions"]
                if record["reviewed_package_id"] == reviewed_package_id
            )
            c3_resolution = copy.deepcopy(resolution)
            c3_resolution["id"] = "resolve-%s" % c3_reviewed_package_id
            c3_resolution["reviewed_package_id"] = c3_reviewed_package_id
            c3_resolution["package_refs"] = [
                record
                for record in resolution["package_refs"]
                if record["profile_id"] == "esp32-c3-4mb"
            ]
            resolution["package_refs"] = [
                record
                for record in resolution["package_refs"]
                if record["profile_id"] != "esp32-c3-4mb"
            ]
            c3_resolution["input_refs"] = [
                identifier
                for identifier in resolution["input_refs"]
                if inputs[identifier]["profile_id"] == "esp32-c3-4mb"
            ]
            resolution["input_refs"] = [
                identifier
                for identifier in resolution["input_refs"]
                if inputs[identifier]["profile_id"] != "esp32-c3-4mb"
            ]
            for identifier in c3_resolution["input_refs"]:
                inputs[identifier][
                    "reviewed_package_id"
                ] = c3_reviewed_package_id
            scoped["reviewed_packages"].append(c3_reviewed)
            scoped["resolutions"].append(c3_resolution)

        split_c3_resolution(
            "fixture-app-core",
            "fixture-c3-component-riscv",
            "component-riscv",
        )
        split_c3_resolution(
            "fixture-gcc-runtime",
            "fixture-c3-toolchain-riscv32",
            "toolchain-riscv32-esp-elf",
        )
        return scoped

    @staticmethod
    @contextmanager
    def _captured_notice_graph():
        captured = {"validated": [], "frozen_names": []}
        validate = RELEASE._audit_validate_policy_v2
        render = RELEASE._audit_notice_v2

        def capture_validated(*args, **kwargs):
            result = validate(*args, **kwargs)
            captured["validated"].append(
                copy.deepcopy(result["notice_records"])
            )
            return result

        def capture_render(records, *, repo_root, frozen_names):
            captured["frozen_names"].append(set(frozen_names))
            return render(
                records,
                repo_root=repo_root,
                frozen_names=frozen_names,
            )

        with mock.patch.object(
            RELEASE,
            "_audit_validate_policy_v2",
            side_effect=capture_validated,
        ), mock.patch.object(
            RELEASE,
            "_audit_notice_v2",
            side_effect=capture_render,
        ):
            yield captured

    def _reference_notice(
        self,
        records,
        policy,
        frozen_names,
        profile_ids,
    ):
        profiles_by_input = {
            record["id"]: record["profile_id"]
            for record in policy["resolved_inputs"]
        }
        selected = []
        for record in records:
            scoped = copy.deepcopy(record)
            scoped["input_refs"] = [
                identifier
                for identifier in record["input_refs"]
                if profiles_by_input[identifier] in profile_ids
            ]
            if scoped["input_refs"]:
                selected.append(scoped)
        return RELEASE._audit_notice_v2(
            selected,
            repo_root=self.fixture.repo,
            frozen_names=frozen_names,
        )

    @staticmethod
    def _bind_receipt_to_notice(evidence, notice):
        receipt_path = evidence / "audit-receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["notice_sha256"] = BASE.sha256_bytes(notice.encode("utf-8"))
        BASE.write_json(receipt_path, receipt)

    def make_audited_candidate(self, notice):
        spec = importlib.util.spec_from_file_location(
            "pyble_release_bundle_fixture_for_v2_audit_migration",
            BASE.RELEASE_BUNDLE_TEST,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(spec.name, None)

        bundle_fixture = module.ReleaseFixture()
        try:
            (self.fixture.repo / "firmware" / "patches").mkdir(
                exist_ok=True
            )
            module.install_fixture_qualification_policy(
                self.fixture.repo,
                self.fixture.build_root,
            )
            self.fixture.rebind_build_provenance()
            reproducibility_build_root = (
                bundle_fixture.root / "audited-build-reproducibility"
            )
            shutil.copytree(
                self.fixture.build_root,
                reproducibility_build_root,
            )
            notice_path = bundle_fixture.root / "audited-notice.txt"
            notice_path.write_text(notice, encoding="utf-8")
            candidate = Path(
                RELEASE.create_bundle(
                    build_root=self.fixture.build_root,
                    reproducibility_build_root=reproducibility_build_root,
                    output_dir=bundle_fixture.bundle,
                    repo_root=self.fixture.repo,
                    installer_version="10.4.0",
                    built_at="2026-07-30T12:00:00Z",
                    provenance={
                        "pyble": {"commit": "1" * 40, "clean": True},
                        "micropython": {
                            "ref": "v1.28.0",
                            "commit": self.fixture.micropython_commit,
                        },
                        "esp_idf": {
                            "ref": "v5.5.1",
                            "commit": self.fixture.esp_idf_commit,
                        },
                        "patch_count": 0,
                        "runner": {
                            "os": "FixtureOS 1",
                            "architecture": "fixture64",
                        },
                        "tools": [
                            {"name": "python", "version": "3.13.5"},
                        ],
                    },
                    audited_notice=notice_path,
                    license_evidence_dir=self.fixture.evidence,
                    license_build_root=self.fixture.build_root,
                    public=False,
                )
            )
            return bundle_fixture, candidate
        except Exception:
            bundle_fixture.cleanup()
            raise

    def validate_audited_candidate(self, bundle):
        return RELEASE.validate_bundle(
            bundle,
            public=False,
            license_evidence_dir=self.fixture.evidence,
            license_build_root=self.fixture.build_root,
            repo_root=self.fixture.repo,
        )

    def test_v2_notice_contains_the_complete_sorted_shipped_dependency_union(self):
        notice, _result, _runner = self.run_audit()
        self.assertNotIn(BASE.CANDIDATE_MARKER, notice)
        self.assertNotIn("esp-web-tools", notice.lower())
        self.assertNotIn("website_third_party_licenses", notice.lower())
        for frozen_upstream in (
            "flashbdev.py",
            "inisetup.py",
            "asyncio",
            "NeoPixel",
        ):
            self.assertIn(frozen_upstream, notice)

        resolutions = {
            item["reviewed_package_id"]: item
            for item in self.fixture.policy["resolutions"]
        }
        profiles_by_input = {
            item["id"]: item["profile_id"]
            for item in self.fixture.policy["resolved_inputs"]
        }
        records = []
        for package in self.fixture.policy["reviewed_packages"]:
            resolution = resolutions[package["id"]]
            shipped_inputs = [
                identifier
                for identifier in resolution["input_refs"]
                if profiles_by_input[identifier] in self.ACTIVE_NOTICE_PROFILES
            ]
            if shipped_inputs:
                records.append(
                    (
                        package,
                        resolution["resolved_input_expression"],
                        shipped_inputs,
                    )
                )
        for package in self.fixture.policy["supplemental_packages"]:
            shipped_inputs = [
                identifier
                for identifier in package["input_refs"]
                if profiles_by_input[identifier] in self.ACTIVE_NOTICE_PROFILES
            ]
            if shipped_inputs:
                records.append(
                    (
                        package,
                        package["selected_spdx_expression"],
                        shipped_inputs,
                    )
                )

        deferred_inputs = {
            identifier
            for identifier, profile_id in profiles_by_input.items()
            if profile_id == "esp32-c3-4mb"
        }
        leaked_inputs = sorted(
            identifier for identifier in deferred_inputs if identifier in notice
        )
        self.assertFalse(
            leaked_inputs,
            "deferred C3 input references leaked into the shipped notice: %s"
            % ", ".join(leaked_inputs),
        )

        for package, expression, input_refs in records:
            dependency = package["dependency"]
            for field in (
                dependency["name"],
                dependency["version_ref"],
                dependency["source_url"],
                dependency["copyright"],
                expression,
            ):
                with self.subTest(package=package["id"], field=field):
                    self.assertIn(field, notice)
            for input_ref in input_refs:
                with self.subTest(package=package["id"], input=input_ref):
                    self.assertIn(input_ref, notice)
            notice_record = package["notice"]
            if notice_record["required"]:
                complete = (
                    BASE.safe_fixture_path(
                        self.fixture.repo,
                        notice_record["path"],
                    )
                    .read_text(encoding="utf-8")
                    .rstrip()
                )
                self.assertIn(complete, notice)

        sorted_names = sorted(
            package["dependency"]["name"]
            for package, _expression, _inputs in records
        )
        self.assertEqual(
            [notice.index(name) for name in sorted_names],
            sorted(notice.index(name) for name in sorted_names),
            "dependency union is not sorted by stable dependency name",
        )

        unique_texts = {}
        for package, _expression, _inputs in records:
            for record in package["license_texts"]:
                complete = (
                    BASE.safe_fixture_path(
                        self.fixture.repo,
                        record["path"],
                    )
                    .read_text(encoding="utf-8")
                    .rstrip()
                )
                unique_texts.setdefault(record["sha256"], complete)
        for digest, complete in unique_texts.items():
            with self.subTest(complete_text_sha256=digest):
                self.assertEqual(
                    notice.count(complete),
                    1,
                    "identical complete text is not deduplicated by hash",
                )

    def test_release_notice_is_scoped_to_the_exact_three_shipped_profiles(self):
        policy = self._three_profile_notice_policy(self.fixture.policy)
        with self._captured_notice_graph() as captured:
            notice, _result, _runner = self.run_audit(policy=policy)

        self.assertEqual(len(captured["validated"]), 1)
        self.assertEqual(len(captured["frozen_names"]), 1)
        expected = self._reference_notice(
            captured["validated"][0],
            policy,
            captured["frozen_names"][0],
            self.ACTIVE_NOTICE_PROFILES,
        )
        self.assertEqual(
            BASE.sha256_bytes(notice.encode("utf-8")),
            BASE.sha256_bytes(expected.encode("utf-8")),
            "the notice is not the exact deterministic three-profile rendering",
        )

        c3_input_refs = {
            record["id"]
            for record in policy["resolved_inputs"]
            if record["profile_id"] == "esp32-c3-4mb"
        }
        self.assertTrue(c3_input_refs)
        self.assertTrue(
            all(
                identifier.startswith("esp32-c3-4mb--")
                for identifier in c3_input_refs
            )
        )
        leaked_inputs = sorted(
            identifier for identifier in c3_input_refs if identifier in notice
        )
        self.assertFalse(
            leaked_inputs,
            "deferred C3 input references leaked into the shipped notice: %s"
            % ", ".join(leaked_inputs),
        )
        for c3_only_dependency in (
            "component-riscv",
            "toolchain-riscv32-esp-elf",
        ):
            with self.subTest(c3_only_dependency=c3_only_dependency):
                self.assertNotIn(c3_only_dependency, notice)
        for active_or_shared in (
            "Fixture application component",
            "Fixture GCC runtime archive",
            "Fixture upstream MicroPython runtime",
            "Fixture frozen NeoPixel package",
        ):
            with self.subTest(active_or_shared=active_or_shared):
                self.assertIn(active_or_shared, notice)

    def test_three_profile_notice_keeps_all_eight_full_audit_evidence_sets(self):
        policy = self._three_profile_notice_policy(self.fixture.policy)
        notice, _result, runner = self.run_audit(policy=policy)
        self.assertTrue(notice.endswith("\n"))
        self.assertEqual(len(runner.calls), len(PROFILE_ROLES))

        receipt = json.loads(
            (self.fixture.evidence / "audit-receipt.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            receipt["identities"],
            [
                {"profile_id": profile_id, "role": role}
                for profile_id, role in sorted(PROFILE_ROLES)
            ],
        )
        expected_evidence = {
            "%s/%s--%s.%s"
            % (directory, profile_id, role, extension)
            for profile_id, role in PROFILE_ROLES
            for directory, extension in (
                ("raw", "spdx.tag"),
                ("spdx", "spdx.json"),
            )
        }
        self.assertEqual(
            set(receipt["evidence_sha256"]),
            expected_evidence,
        )

    def test_audited_candidate_rejects_full_four_and_one_profile_notices(self):
        policy = self._three_profile_notice_policy(self.fixture.policy)
        with installed_policy(self.fixture.base, policy):
            with self._captured_notice_graph() as captured:
                _notice, _result, runner = self._run_installed()

            self.assertEqual(len(runner.calls), len(PROFILE_ROLES))
            full_records = captured["validated"][0]
            frozen_names = captured["frozen_names"][0]
            expected = self._reference_notice(
                full_records,
                policy,
                frozen_names,
                self.ACTIVE_NOTICE_PROFILES,
            )
            full_four = self._reference_notice(
                full_records,
                policy,
                frozen_names,
                {
                    "esp32-4mb",
                    "esp32-s3-n16r8",
                    "waveshare-esp32-s3-lcd-147b",
                    "esp32-c3-4mb",
                },
            )
            underscoped_one = self._reference_notice(
                full_records,
                policy,
                frozen_names,
                {"esp32-4mb"},
            )
            self.assertNotEqual(expected, full_four)
            self.assertNotEqual(expected, underscoped_one)

            self._bind_receipt_to_notice(self.fixture.evidence, expected)
            bundle_fixture, bundle = self.make_audited_candidate(expected)
            try:
                try:
                    baseline = self.validate_audited_candidate(bundle)
                except RELEASE.ReleaseError as exc:
                    self.fail(
                        "the exact three-profile notice with all eight evidence "
                        "sets must pass audited-candidate verification: %s"
                        % exc
                    )
                self.assertIsNotNone(baseline)
                for label, invalid_notice in (
                    ("full-four-profile", full_four),
                    ("underscoped-one-profile", underscoped_one),
                ):
                    with self.subTest(notice_scope=label):
                        (bundle / "THIRD_PARTY_LICENSES.txt").write_text(
                            invalid_notice,
                            encoding="utf-8",
                        )
                        self._bind_receipt_to_notice(
                            self.fixture.evidence,
                            invalid_notice,
                        )
                        bundle_fixture.refresh_declared_hashes()
                        with self.assertRaises(RELEASE.ReleaseError):
                            self.validate_audited_candidate(bundle)
            finally:
                bundle_fixture.cleanup()

    def test_v2_audit_binds_the_offline_runner_and_exact_eight_descriptions(self):
        _notice, _result, runner = self.run_audit()
        self.assertEqual(len(runner.calls), len(PROFILE_ROLES))
        receipt = json.loads(
            (self.fixture.evidence / "audit-receipt.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            receipt["execution_identity"],
            runner.execution_identity,
        )
        self.assertEqual(
            receipt["executed_artifacts"],
            runner.executed_artifacts,
        )

        descriptions = []
        for call in runner.calls:
            command = call["argv"]
            self.assertTrue(call["check"])
            self.assertTrue(call["network_disabled"])
            normalized = " ".join(command).lower().replace("-", "_")
            self.assertIn("esp_idf_sbom", normalized)
            self.assertIn("create", normalized)
            for flag in ("--rem-unused", "--rem-config", "--file-tags"):
                self.assertEqual(command.count(flag), 1)
            for forbidden in (
                "--add-unused-deps",
                "--add-config-deps",
                "--add-unused",
                "--add-config",
            ):
                self.assertNotIn(forbidden, command)
            descriptions.extend(
                Path(value).resolve()
                for value in command
                if value.endswith("project_description.json")
            )
            self.assertEqual(
                Path(call["env"]["SBOM_EXCLUDED_CVES_FILE"]).resolve(),
                self.fixture.base.excluded_cves.resolve(),
            )
        self.assertEqual(
            set(descriptions),
            {
                path.resolve()
                for path in self.fixture.base.project_descriptions()
            },
        )
        for temporary in runner.temporary_paths:
            self.assertFalse(temporary.exists())

        wrong = FrozenTagValueRunner(self.fixture.base)
        wrong.executed_artifacts[BASE.SBOM_NAME] = "0" * 64
        self.assert_audit_rejected(runner=wrong)

        extra = FrozenTagValueRunner(self.fixture.base)
        extra.executed_artifacts["unlocked-fixture"] = "f" * 64
        self.assert_audit_rejected(runner=extra)

        unisolated = FrozenTagValueRunner(self.fixture.base)
        unisolated.network_isolated = False
        self.assert_audit_rejected(runner=unisolated)

    def test_v2_requires_each_description_and_exact_raw_identity(self):
        self.run_audit()
        for description in self.fixture.base.project_descriptions():
            with self.subTest(missing=description):
                with BASE.removed_file(description):
                    self.assert_audit_rejected()

        for mode in ("rotate", "duplicate"):
            runner = FrozenTagValueRunner(self.fixture.base)
            runner.identity_mode = mode
            with self.subTest(identity_mode=mode):
                self.assert_audit_rejected(runner=runner)

    def test_v2_audit_rejects_malformed_tag_value_singletons_and_text(self):
        self.run_audit()

        class MalformedRunner(FrozenTagValueRunner):
            def __init__(self, fixture, malformed):
                super().__init__(fixture)
                self.malformed = malformed

            def __call__(self, argv, **kwargs):
                completed = super().__call__(argv, **kwargs)
                command = [str(item) for item in argv]
                output = Path(
                    command[command.index("--output-file") + 1]
                )
                value = output.read_text(encoding="utf-8")
                document = RELEASE._audit_parse_spdx_tag_value(value)
                if self.malformed == "duplicate-document-field":
                    value = value.replace(
                        "SPDXVersion: SPDX-2.2\n",
                        (
                            "SPDXVersion: SPDX-2.2\n"
                            "SPDXVersion: SPDX-2.2\n"
                        ),
                        1,
                    )
                elif self.malformed == "duplicate-package-field":
                    first = document["packages"][0]["name"]
                    line = "PackageName: %s\n" % first
                    value = value.replace(line, line + line, 1)
                elif self.malformed == "relationship":
                    first = document["packages"][0]["SPDXID"]
                    value = value.replace(
                        (
                            "Relationship: SPDXRef-DOCUMENT DESCRIBES "
                            + first
                        ),
                        "Relationship: SPDXRef-DOCUMENT DESCRIBES",
                        1,
                    )
                elif self.malformed == "unterminated-text":
                    value = value.replace(
                        "This deliberately spans two lines.</text>",
                        "This deliberately spans two lines.",
                        1,
                    )
                else:
                    raise AssertionError(
                        "unknown malformed fixture: %s" % self.malformed
                    )
                self.raw_values[-1] = value
                output.write_text(value, encoding="utf-8")
                return completed

        for label in (
            "duplicate-document-field",
            "duplicate-package-field",
            "relationship",
            "unterminated-text",
        ):
            with self.subTest(malformed=label):
                self.assert_audit_rejected(
                    runner=MalformedRunner(self.fixture.base, label)
                )

    def test_v2_review_files_and_frozen_source_tree_are_hash_bound(self):
        self.run_audit()
        unsafe = copy.deepcopy(self.fixture.policy)
        unsafe["reviewed_packages"][0]["license_texts"][0]["path"] = (
            "../outside-license.txt"
        )
        self.assert_audit_rejected(policy=unsafe)

        denied = copy.deepcopy(self.fixture.policy)
        denied["resolutions"][0]["disposition"] = "deny"
        self.assert_audit_rejected(policy=denied)

        package = self.fixture.policy["reviewed_packages"][0]
        license_path = BASE.safe_fixture_path(
            self.fixture.repo,
            package["license_texts"][0]["path"],
        )
        notice_path = BASE.safe_fixture_path(
            self.fixture.repo,
            package["notice"]["path"],
        )
        for label, path in (
            ("license", license_path),
            ("notice", notice_path),
        ):
            with self.subTest(kind=label, mutation="changed"):
                with BASE.patched_bytes(
                    path,
                    path.read_bytes() + b"changed\n",
                ):
                    self.assert_audit_rejected()
            with self.subTest(kind=label, mutation="missing"):
                with BASE.removed_file(path):
                    self.assert_audit_rejected()

        outside = self.fixture.root / "outside-license-copy.txt"
        with BASE.new_file(outside, license_path.read_bytes()):
            with BASE.symlink_instead(license_path, outside):
                self.assert_audit_rejected()

        neopixel = (
            self.fixture.firmware
            / "upstream"
            / "micropython"
            / "lib"
            / "micropython-lib"
            / "micropython"
            / "drivers"
            / "led"
            / "neopixel"
            / "neopixel.py"
        )
        with BASE.patched_bytes(
            neopixel,
            neopixel.read_bytes() + b"# changed\n",
        ):
            self.assert_audit_rejected()

    def test_mpy_cross_mutation_after_clean_source_build_is_rejected(self):
        admitted = (
            self.fixture.firmware
            / "upstream"
            / "micropython"
            / "mpy-cross"
            / "build"
            / "mpy-cross"
        )
        admitted_before = admitted.read_bytes()
        admitted_mode = admitted.stat().st_mode
        actual_run = RELEASE.subprocess.run
        saw_clean_build = False

        def mutate_after_clean_build(*args, **kwargs):
            nonlocal saw_clean_build
            completed = actual_run(*args, **kwargs)
            command = [
                os.fspath(value)
                for value in (args[0] if args else kwargs.get("args", ()))
            ]
            executable = Path(command[0]).name if command else ""
            working_directory = os.fspath(kwargs.get("cwd", ""))
            if (
                not saw_clean_build
                and executable in {"make", "gmake"}
                and (
                    any("mpy-cross" in value for value in command[1:])
                    or "mpy-cross" in working_directory
                )
                and completed.returncode == 0
            ):
                saw_clean_build = True
                admitted.write_bytes(
                    admitted.read_bytes()
                    + b"# post-anchor admitted-compiler mutation\n"
                )
                admitted.chmod(admitted_mode)
            return completed

        rejection = None
        try:
            with mock.patch.object(
                RELEASE.subprocess,
                "run",
                side_effect=mutate_after_clean_build,
            ):
                try:
                    self.run_audit()
                except RELEASE.ReleaseError as exc:
                    rejection = exc
        finally:
            admitted.write_bytes(admitted_before)
            admitted.chmod(admitted_mode)

        self.assertTrue(
            saw_clean_build,
            "the audit did not establish a clean source-built mpy-cross anchor",
        )
        self.assertIsNotNone(
            rejection,
            "mutating admitted mpy-cross after its clean build was accepted",
        )

    def test_v2_normalized_evidence_is_semantically_deterministic(self):
        second = ObservationV2Fixture()
        try:
            first_notice, _first_result, first_runner = self.run_audit()
            second_notice, _second_result, second_runner = self.run_audit(
                fixture=second,
            )
            first = BASE.evidence_semantics(self.fixture.evidence)
            other = BASE.evidence_semantics(second.evidence)
            first_reviewed = {
                path: value
                for path, value in first.items()
                if path.startswith("spdx/")
            }
            other_reviewed = {
                path: value
                for path, value in other.items()
                if path.startswith("spdx/")
            }
            self.assertEqual(first_notice, second_notice)
            self.assertEqual(first_reviewed, other_reviewed)

            reviewed_serialized = first_notice + "\n" + json.dumps(
                first_reviewed,
                sort_keys=True,
            )
            for forbidden in (
                str(self.fixture.root),
                str(second.root),
                "2099-12-31T23:59:59Z",
            ):
                self.assertNotIn(forbidden, reviewed_serialized)
            documents = BASE.nested_spdx_documents(first_reviewed)
            self.assertEqual(len(documents), len(PROFILE_ROLES))
            self.assertEqual(
                {document["name"] for document in documents},
                {
                    "PyBLE license review %s/%s" % identity
                    for identity in PROFILE_ROLES
                },
            )
            namespaces = [
                document["documentNamespace"] for document in documents
            ]
            self.assertEqual(len(set(namespaces)), len(PROFILE_ROLES))
            for runner in (first_runner, second_runner):
                for temporary in runner.temporary_paths:
                    self.assertFalse(temporary.exists())
            self.assertNotIn("2099-12-31", first_notice)
            self.assertIsNone(BASE.UUID_PATTERN.search(first_notice))
        finally:
            second.close()

    def test_audited_candidate_binds_v2_notice_and_fresh_inputs(self):
        with installed_policy(self.fixture.base, self.fixture.policy):
            notice, _result, _runner = self._run_installed()
            bundle_fixture, bundle = self.make_audited_candidate(notice)
            try:
                self.assertIsNotNone(
                    self.validate_audited_candidate(bundle)
                )

                notice_path = bundle / "THIRD_PARTY_LICENSES.txt"
                with BASE.patched_bytes(
                    notice_path,
                    notice_path.read_bytes() + b"tampered\n",
                ):
                    bundle_fixture.refresh_declared_hashes()
                    with self.assertRaises(RELEASE.ReleaseError):
                        self.validate_audited_candidate(bundle)
                bundle_fixture.refresh_declared_hashes()

                stale_inputs = (
                    self.fixture.build_root
                    / "esp32"
                    / "project_description.json",
                    self.fixture.build_root / "esp32" / "micropython.map",
                    self.fixture.build_root
                    / "esp32-s3"
                    / "compile_commands.json",
                    self.fixture.build_root
                    / "esp32-c3"
                    / "frozen_content.c",
                    self.fixture.firmware
                    / "upstream"
                    / "micropython"
                    / "extmod"
                    / "asyncio"
                    / "core.py",
                    self.fixture.base.excluded_cves,
                    self.fixture.policy_path,
                    self.fixture.lock_path,
                )
                for source_input in stale_inputs:
                    with self.subTest(stale_review_input=source_input):
                        with BASE.patched_bytes(
                            source_input,
                            source_input.read_bytes() + b"\n",
                        ):
                            with self.assertRaises(RELEASE.ReleaseError):
                                self.validate_audited_candidate(bundle)
            finally:
                bundle_fixture.cleanup()

    def test_audited_candidate_rejects_tampered_or_misnamed_v2_evidence(self):
        with installed_policy(self.fixture.base, self.fixture.policy):
            notice, _result, _runner = self._run_installed()
            bundle_fixture, bundle = self.make_audited_candidate(notice)
            try:
                self.assertIsNotNone(
                    self.validate_audited_candidate(bundle)
                )
                raw_path = (
                    self.fixture.evidence
                    / "raw"
                    / "esp32-4mb--application.spdx.tag"
                )
                with BASE.patched_bytes(
                    raw_path,
                    raw_path.read_bytes() + b"\n",
                ):
                    with self.assertRaises(RELEASE.ReleaseError):
                        self.validate_audited_candidate(bundle)

                spdx_path = (
                    self.fixture.evidence
                    / "spdx"
                    / "esp32-4mb--application.spdx.json"
                )
                document = json.loads(
                    spdx_path.read_text(encoding="utf-8")
                )
                document["packages"][0]["licenseDeclared"] = "NOASSERTION"
                document["packages"][0]["licenseConcluded"] = "NOASSERTION"
                changed_spdx = (
                    json.dumps(document, indent=2, sort_keys=True) + "\n"
                ).encode()
                receipt_path = (
                    self.fixture.evidence / "audit-receipt.json"
                )
                receipt = json.loads(
                    receipt_path.read_text(encoding="utf-8")
                )
                relative = spdx_path.relative_to(
                    self.fixture.evidence
                ).as_posix()
                receipt["evidence_sha256"][relative] = BASE.sha256_bytes(
                    changed_spdx
                )
                changed_receipt = (
                    json.dumps(receipt, indent=2, sort_keys=False) + "\n"
                ).encode()
                with BASE.patched_bytes(spdx_path, changed_spdx):
                    with BASE.patched_bytes(
                        receipt_path,
                        changed_receipt,
                    ):
                        with self.assertRaises(RELEASE.ReleaseError):
                            self.validate_audited_candidate(bundle)

                original = (
                    self.fixture.evidence
                    / "spdx"
                    / "esp32-c3-4mb--bootloader.spdx.json"
                )
                renamed = original.with_name(
                    "renamed-valid-looking.spdx.json"
                )
                receipt_before = receipt_path.read_bytes()
                original.rename(renamed)
                try:
                    moved_receipt = json.loads(receipt_before)
                    original_key = original.relative_to(
                        self.fixture.evidence
                    ).as_posix()
                    renamed_key = renamed.relative_to(
                        self.fixture.evidence
                    ).as_posix()
                    moved_receipt["evidence_sha256"][renamed_key] = (
                        moved_receipt["evidence_sha256"].pop(original_key)
                    )
                    receipt_path.write_text(
                        json.dumps(
                            moved_receipt,
                            indent=2,
                            sort_keys=False,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    with self.assertRaises(RELEASE.ReleaseError):
                        self.validate_audited_candidate(bundle)
                finally:
                    receipt_path.write_bytes(receipt_before)
                    renamed.rename(original)
            finally:
                bundle_fixture.cleanup()

    def test_audited_candidate_rejects_v2_evidence_root_symlink(self):
        with installed_policy(self.fixture.base, self.fixture.policy):
            notice, _result, _runner = self._run_installed()
            bundle_fixture, bundle = self.make_audited_candidate(notice)
            real_evidence = self.fixture.root / "real-review-evidence"
            try:
                self.assertIsNotNone(
                    self.validate_audited_candidate(bundle)
                )
                self.fixture.evidence.rename(real_evidence)
                self.fixture.evidence.symlink_to(
                    real_evidence,
                    target_is_directory=True,
                )
                with self.assertRaises(RELEASE.ReleaseError):
                    self.validate_audited_candidate(bundle)
            finally:
                if self.fixture.evidence.is_symlink():
                    self.fixture.evidence.unlink()
                if real_evidence.exists():
                    real_evidence.rename(self.fixture.evidence)
                bundle_fixture.cleanup()


if __name__ == "__main__":
    unittest.main()
