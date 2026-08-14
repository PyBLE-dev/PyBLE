#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] BLD-8 — Retain and independently replay Ninja final-link evidence.
#
# Frozen sources:
#   docs/specifications/firmware/browser-flashing.md §6 rule 4
#   docs/specifications/firmware/specs.md BLD-8

from __future__ import annotations

import importlib.util
import hashlib
import inspect
import json
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "release_bundle.py"


def load_release_module():
    spec = importlib.util.spec_from_file_location(
        "pyble_release_ninja_link_evidence",
        RELEASE_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load release_bundle.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


RELEASE = load_release_module()
SEAM_NAME = "_audit_ninja_link_command_evidence"


class NinjaLinkEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="pyble-ninja-link-evidence-"
        )
        self.role_build = (Path(self.temporary.name) / "esp32").resolve()
        (self.role_build / "CMakeFiles").mkdir(parents=True)
        self.outputs = {
            self._object("CMakeFiles/micropython.elf.dir/project.c.obj"),
            self._object("esp-idf/main/CMakeFiles/btree.dir/bt_close.c.obj"),
        }
        self.explicit = "CMakeFiles/micropython.elf.dir/project.c.obj"
        self.implicit = "esp-idf/main/CMakeFiles/btree.dir/bt_close.c.obj"
        self.map_outputs = set(self.outputs)
        self.map_path = self.role_build / "micropython.map"
        self.map_path.write_text("synthetic linker map\n", encoding="utf-8")
        self.map_flag = "-Wl,--Map=%s" % self.map_path
        self.argv = [
            "/toolchain/bin/fixture-g++",
            self.map_flag,
            self.explicit,
            "-o",
            "micropython.elf",
            self.implicit,
            "esp-idf/main/libmain.a",
        ]
        self._write_ninja()

    def tearDown(self):
        self.temporary.cleanup()

    def _object(self, relative: str) -> Path:
        path = self.role_build / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic object\n")
        return path.resolve()

    @property
    def direct_relatives(self) -> list[str]:
        return sorted(
            path.relative_to(self.role_build).as_posix() for path in self.outputs
        )

    def _write_ninja(
        self,
        *,
        edge_suffix: str = "",
        include: str | None = None,
        flags: str = "",
    ):
        include_line = include or "include CMakeFiles/rules.ninja"
        (self.role_build / "build.ninja").write_text(
            "# exact synthetic CMake Ninja graph\n"
            + include_line
            + "\n"
            + "build micropython.elf: CXX_LINK %s | %s "
            "esp-idf/main/libmain.a || graph-order%s\n"
            % (self.explicit, self.implicit, edge_suffix)
            + "  FLAGS = %s%s\n" % (self.map_flag, flags)
            + "  LINK_FLAGS =\n"
            + "  LINK_LIBRARIES = %s esp-idf/main/libmain.a\n" % self.implicit
            + "  LINK_PATH =\n"
            + "  OBJECT_DIR = CMakeFiles/micropython.elf.dir\n"
            + "  POST_BUILD = :\n"
            + "  PRE_LINK = :\n"
            + "  TARGET_COMPILE_PDB = CMakeFiles/micropython.elf.dir/\n"
            + "  TARGET_FILE = micropython.elf\n"
            + "  TARGET_PDB = micropython.elf.pdb\n",
            encoding="utf-8",
        )
        (self.role_build / "CMakeFiles" / "rules.ninja").write_text(
            "rule CXX_LINK\n"
            "  command = $PRE_LINK && /toolchain/bin/fixture-g++ "
            "$FLAGS $LINK_FLAGS $in -o $TARGET_FILE $LINK_PATH "
            "$LINK_LIBRARIES && $POST_BUILD\n"
            "  description = Linking CXX executable $TARGET_FILE\n"
            "  restat = $RESTAT\n",
            encoding="utf-8",
        )

    def observe(
        self,
        *,
        compile_outputs: set[Path] | None = None,
        map_outputs: set[Path] | None = None,
        compiler_paths: set[Path] | None = None,
        dependency_roots: tuple[Path, ...] | None = None,
    ):
        seam = getattr(RELEASE, SEAM_NAME, None)
        self.assertTrue(
            callable(seam),
            "release_bundle.py lacks %s" % SEAM_NAME,
        )
        arguments = {
            "role_build": self.role_build,
            "app_elf": "micropython.elf",
            "compile_outputs": {
                path: self.role_build / "source.c"
                for path in (
                    self.outputs if compile_outputs is None else compile_outputs
                )
            },
            "map_direct_outputs": (
                self.map_outputs if map_outputs is None else map_outputs
            ),
            "compiler_paths": (
                {Path("/toolchain/bin/fixture-g++")}
                if compiler_paths is None
                else compiler_paths
            ),
        }
        if "map_path" in inspect.signature(seam).parameters:
            arguments["map_path"] = self.map_path
        if dependency_roots is not None:
            arguments["dependency_roots"] = dependency_roots
        return seam(**arguments)

    def test_exact_ninja_graph_replays_one_canonical_link_command(self):
        observed = self.observe()
        self.assertEqual(observed["argv"], self.argv)
        self.assertEqual(observed["direct_outputs"], self.outputs)
        encoded = (
            json.dumps(self.argv, ensure_ascii=False, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        self.assertEqual(
            observed["linker_command_sha256"],
            hashlib.sha256(encoded).hexdigest(),
        )
        self.assertEqual(
            set(observed),
            {
                "app_elf",
                "argv",
                "direct_outputs",
                "linker_command_sha256",
                "build_ninja_path",
                "build_ninja_sha256",
                "rules_ninja_path",
                "rules_ninja_sha256",
            },
        )

    def test_missing_ninja_graph_is_not_replaced_by_fabricated_link_txt(self):
        (self.role_build / "build.ninja").unlink()
        link_txt = self.role_build / "CMakeFiles/micropython.elf.dir/link.txt"
        link_txt.parent.mkdir(exist_ok=True)
        link_txt.write_text(" ".join(self.argv) + "\n", encoding="utf-8")

        with self.assertRaises(RELEASE.ReleaseError):
            self.observe()

    def test_linker_frontend_must_be_compile_toolchain_admitted(self):
        with self.assertRaises(RELEASE.ReleaseError):
            self.observe(compiler_paths={Path("/attacker/bin/fixture-g++")})

    def test_duplicate_elf_edge_or_linker_rule_is_rejected(self):
        build_ninja = self.role_build / "build.ninja"
        rules_ninja = self.role_build / "CMakeFiles/rules.ninja"
        mutations = (
            (
                build_ninja,
                "build micropython.elf: CXX_LINK CMakeFiles/other.obj\n",
            ),
            (
                rules_ninja,
                "rule CXX_LINK\n  command = /attacker/linker\n",
            ),
        )
        for path, addition in mutations:
            with self.subTest(path=path.name):
                original = path.read_text(encoding="utf-8")
                path.write_text(original + addition, encoding="utf-8")
                try:
                    with self.assertRaises(RELEASE.ReleaseError):
                        self.observe()
                finally:
                    path.write_text(original, encoding="utf-8")

    def test_canonical_or_variable_output_alias_is_rejected(self):
        build_ninja = self.role_build / "build.ninja"
        additions = (
            "build ./micropython.elf: phony\n",
            "elf_alias = micropython.elf\nbuild $elf_alias: phony\n",
            (
                "elf_alias = micropython.elf\n"
                "build $elf_alias: phony\n"
                "elf_alias = harmless.out\n"
            ),
        )
        for addition in additions:
            with self.subTest(addition=addition):
                original = build_ninja.read_text(encoding="utf-8")
                build_ninja.write_text(original + addition, encoding="utf-8")
                try:
                    with self.assertRaises(RELEASE.ReleaseError):
                        self.observe()
                finally:
                    build_ninja.write_text(original, encoding="utf-8")

    def test_redundant_separator_elf_output_alias_is_rejected(self):
        build_ninja = self.role_build / "build.ninja"
        original = build_ninja.read_text(encoding="utf-8")
        build_ninja.write_text(
            original + "build .//micropython.elf: phony\n",
            encoding="utf-8",
        )

        with self.assertRaises(RELEASE.ReleaseError):
            self.observe()

    def test_immediate_variable_expansion_cannot_hide_duplicate_elf_edge(self):
        build_ninja = self.role_build / "build.ninja"
        original = build_ninja.read_text(encoding="utf-8")
        build_ninja.write_text(
            original
            + "base = micropython.elf\n"
            + "elf_alias = $base\n"
            + "base = harmless.out\n"
            + "build $elf_alias: phony\n",
            encoding="utf-8",
        )

        with self.assertRaises(RELEASE.ReleaseError):
            self.observe()

    def test_ninja_spacing_cannot_hide_duplicate_elf_edge(self):
        build_ninja = self.role_build / "build.ninja"
        original = build_ninja.read_text(encoding="utf-8")
        additions = (
            (
                "elf_alias = harmless.out\n"
                "elf_alias=micropython.elf\n"
                "build $elf_alias: phony\n"
            ),
            (
                "elf_alias = harmless.out\n"
                "elf_alias =micropython.elf\n"
                "build $elf_alias: phony\n"
            ),
            (
                "elf_alias = harmless.out\n"
                "elf_alias   = micropython.elf\n"
                "build $elf_alias: phony\n"
            ),
            (
                "elf_alias = harmless.out\n"
                "elf_alias\t=\tmicropython.elf\n"
                "build $elf_alias: phony\n"
            ),
            (
                "elf = harmless.out\n"
                "elf-alias = micropython.elf\n"
                "build $elf-alias: phony\n"
            ),
            "build\tmicropython.elf: phony\n",
        )
        for addition in additions:
            with self.subTest(addition=addition):
                build_ninja.write_text(original + addition, encoding="utf-8")
                try:
                    with self.assertRaises(RELEASE.ReleaseError):
                        self.observe()
                finally:
                    build_ninja.write_text(original, encoding="utf-8")

    def test_alternate_include_or_nested_subninja_is_rejected(self):
        for injected in (
            "include ../outside/rules.ninja",
            "include CMakeFiles/rules.ninja\nsubninja attacker.ninja",
        ):
            with self.subTest(injected=injected):
                self._write_ninja(include=injected)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.observe()

    def test_response_file_shell_or_unknown_variable_is_rejected(self):
        rules = self.role_build / "CMakeFiles/rules.ninja"
        original = rules.read_text(encoding="utf-8")
        attacks = (" @$rspfile", " ; attacker", " $unknown")
        for attack in attacks:
            with self.subTest(attack=attack):
                rules.write_text(
                    original.replace(" -o $TARGET_FILE", attack + " -o $TARGET_FILE"),
                    encoding="utf-8",
                )
                try:
                    with self.assertRaises(RELEASE.ReleaseError):
                        self.observe()
                finally:
                    rules.write_text(original, encoding="utf-8")

    def test_linker_assignment_tokenization_must_be_shell_neutral(self):
        for flags in (
            " -Lfirst\N{NO-BREAK SPACE}-Lsecond",
            " -L*",
        ):
            with self.subTest(flags=flags):
                self._write_ninja(flags=flags)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.observe()

    def test_linker_assignment_rejects_shell_brace_expansion(self):
        for flags in (
            " --for-linker={-o,attacker.elf}",
            " -Wl,{--Map=attacker.map,--gc-sections}",
        ):
            with self.subTest(flags=flags):
                self._write_ninja(flags=flags)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.observe()

    def test_linker_assignment_rejects_home_and_parenthesis_expansion(self):
        for flags in (
            " ~/attacker.a",
            " (attacker)",
            " foo(bar)",
        ):
            with self.subTest(flags=flags):
                self._write_ninja(flags=flags)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.observe()

    def test_driver_wrapped_alternate_output_is_rejected(self):
        for flags in (
            " -Wl,-o,attacker.elf",
            " -Wl,--output=attacker.elf",
            " -Xlinker -o -Xlinker attacker.elf",
        ):
            with self.subTest(flags=flags):
                self._write_ninja(flags=flags)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.observe()

    def test_gcc_for_linker_wrapped_outputs_are_rejected(self):
        for flags in (
            " --for-linker=-o --for-linker=attacker.elf",
            " --for-linker=--Map=attacker.map",
        ):
            with self.subTest(flags=flags):
                self._write_ninja(flags=flags)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.observe()

    def test_gcc_separate_for_linker_outputs_are_rejected(self):
        for flags in (
            " --for-linker -o --for-linker attacker.elf",
            " --for-linker -Map=attacker.map",
            " --for-linker -Map --for-linker attacker.map",
        ):
            with self.subTest(flags=flags):
                self._write_ninja(flags=flags)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.observe()

    def test_gnu_ld_abbreviated_output_options_are_rejected(self):
        for flags in (
            " -Wl,-Ma=attacker.map",
            " -Wl,--Ma=attacker.map",
            " -Wl,--out=attacker.elf",
            " --for-linker=-Ma=attacker.map",
            " --for-linker=--out=attacker.elf",
            " -Xlinker -Ma=attacker.map",
            " -Xlinker --out=attacker.elf",
        ):
            with self.subTest(flags=flags):
                self._write_ninja(flags=flags)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.observe()

    def test_gnu_ld_short_map_option_is_rejected(self):
        for flags in (
            " -Wl,--M=attacker.map",
            " -Wl,--M,attacker.map",
            " --for-linker=--M=attacker.map",
            " --for-linker --M --for-linker attacker.map",
            " -Xlinker --M -Xlinker attacker.map",
        ):
            with self.subTest(flags=flags):
                self._write_ninja(flags=flags)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.observe()

    def test_only_the_pinned_gcc_specs_file_is_admitted(self):
        for flags in (
            " -specs=attacker.specs",
            " --specs=attacker.specs",
        ):
            with self.subTest(flags=flags):
                self._write_ninja(flags=flags)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.observe()

        self._write_ninja(flags=" --specs=nano.specs")
        observed = self.observe()
        self.assertIn("--specs=nano.specs", observed["argv"])

    def test_linker_map_output_must_match_the_observed_map(self):
        build_ninja = self.role_build / "build.ninja"
        attacker_map = self.role_build / "attacker.map"
        original = build_ninja.read_text(encoding="utf-8")
        build_ninja.write_text(
            original.replace(str(self.map_path), str(attacker_map), 1),
            encoding="utf-8",
        )

        with self.assertRaises(RELEASE.ReleaseError):
            self.observe()

    def test_variable_cycle_or_duplicate_edge_assignment_is_rejected(self):
        for flags in (" $FLAGS", " one\n  FLAGS = two"):
            with self.subTest(flags=flags):
                self._write_ninja(flags=flags)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.observe()

    def test_selected_edge_or_rule_rejects_noncanonical_binding_indentation(
        self,
    ):
        build_ninja = self.role_build / "build.ninja"
        rules_ninja = self.role_build / "CMakeFiles" / "rules.ninja"
        mutations = (
            (
                build_ninja,
                " FLAGS = --for-linker=-o --for-linker=attacker.elf\n",
            ),
            (build_ninja, " TARGET_FILE = attacker.elf\n"),
            (
                rules_ninja,
                " command = /attacker/linker -o attacker.elf\n",
            ),
        )
        for path, addition in mutations:
            with self.subTest(path=path.name, addition=addition):
                original = path.read_text(encoding="utf-8")
                path.write_text(original + addition, encoding="utf-8")
                try:
                    with self.assertRaises(RELEASE.ReleaseError):
                        self.observe()
                finally:
                    path.write_text(original, encoding="utf-8")

    def test_comment_does_not_end_selected_edge_or_rule_binding_scope(self):
        build_ninja = self.role_build / "build.ninja"
        rules_ninja = self.role_build / "CMakeFiles" / "rules.ninja"
        mutations = (
            (
                build_ninja,
                "# gap\n"
                "  FLAGS = --for-linker=-o --for-linker=attacker.elf\n",
            ),
            (
                rules_ninja,
                "# gap\n"
                "  command = /attacker/linker -o attacker.elf\n",
            ),
        )
        for path, addition in mutations:
            with self.subTest(path=path.name):
                original = path.read_text(encoding="utf-8")
                path.write_text(original + addition, encoding="utf-8")
                try:
                    with self.assertRaises(RELEASE.ReleaseError):
                        self.observe()
                finally:
                    path.write_text(original, encoding="utf-8")

    def test_tab_indented_edge_or_rule_bindings_are_rejected(self):
        paths = (
            self.role_build / "build.ninja",
            self.role_build / "CMakeFiles" / "rules.ninja",
        )
        for path in paths:
            with self.subTest(path=path.name):
                original = path.read_text(encoding="utf-8")
                tab_indented = original.replace("\n  ", "\n\t")
                self.assertNotEqual(tab_indented, original)
                self.assertNotIn("\n  ", tab_indented)
                path.write_text(tab_indented, encoding="utf-8")
                try:
                    with self.assertRaises(RELEASE.ReleaseError):
                        self.observe()
                finally:
                    path.write_text(original, encoding="utf-8")

    def test_direct_objects_must_match_map_and_compile_evidence(self):
        missing = next(iter(self.outputs))
        for kwargs in (
            {"compile_outputs": self.outputs - {missing}},
            {"map_outputs": self.map_outputs - {missing}},
        ):
            with self.subTest(kwargs=sorted(kwargs)):
                with self.assertRaises(RELEASE.ReleaseError):
                    self.observe(**kwargs)

    def test_ninja_object_operand_must_be_canonical_before_argv_digest(self):
        build_ninja = self.role_build / "build.ninja"
        original = build_ninja.read_text(encoding="utf-8")
        build_ninja.write_text(
            original.replace(
                "build micropython.elf: CXX_LINK %s" % self.explicit,
                "build micropython.elf: CXX_LINK ./%s" % self.explicit,
                1,
            ),
            encoding="utf-8",
        )

        with self.assertRaises(RELEASE.ReleaseError):
            self.observe()

    def test_explicit_link_inputs_must_be_exact_compile_outputs(self):
        linker_script = self.role_build / "extra-linker-script.ld"
        linker_script.write_text("SECTIONS {}\n", encoding="utf-8")
        build_ninja = self.role_build / "build.ninja"
        original = build_ninja.read_text(encoding="utf-8")
        build_ninja.write_text(
            original.replace(
                "%s |" % self.explicit,
                "%s %s |" % (self.explicit, linker_script.name),
                1,
            ),
            encoding="utf-8",
        )

        with self.assertRaises(RELEASE.ReleaseError):
            self.observe()

    def test_absolute_dependency_must_be_a_regular_file(self):
        directory_dependency = self.role_build.parent / "directory-dependency"
        directory_dependency.mkdir()
        build_ninja = self.role_build / "build.ninja"
        original = build_ninja.read_text(encoding="utf-8")
        build_ninja.write_text(
            original.replace(
                " || graph-order",
                " %s || graph-order" % directory_dependency,
                1,
            ),
            encoding="utf-8",
        )

        with self.assertRaises(RELEASE.ReleaseError):
            self.observe(dependency_roots=(self.role_build.parent,))

    def test_graph_inputs_must_not_be_symlinks(self):
        rules = self.role_build / "CMakeFiles/rules.ninja"
        real_rules = self.role_build / "CMakeFiles/rules-real.ninja"
        rules.rename(real_rules)
        rules.symlink_to(real_rules.name)

        with self.assertRaises(RELEASE.ReleaseError):
            self.observe()

    def test_oversized_graph_is_rejected_before_unbounded_read(self):
        rules = self.role_build / "CMakeFiles/rules.ninja"
        with rules.open("r+b") as stream:
            stream.truncate(1024 * 1024 + 1)

        original_reader = RELEASE._audit_stable_regular_file_bytes

        def guarded_reader(path, label):
            if Path(path) == rules:
                self.fail("oversized Ninja graph reached the unbounded read seam")
            return original_reader(path, label)

        RELEASE._audit_stable_regular_file_bytes = guarded_reader
        try:
            with self.assertRaises(RELEASE.ReleaseError):
                self.observe()
        finally:
            RELEASE._audit_stable_regular_file_bytes = original_reader

    def test_growing_graph_stream_is_never_read_past_bound(self):
        rules = self.role_build / "CMakeFiles/rules.ninja"
        rules_stat = rules.stat()
        rules_identity = (rules_stat.st_dev, rules_stat.st_ino)
        maximum = 1024 * 1024
        streamed = 0
        original_read = RELEASE.os.read

        def guarded_read(descriptor, count):
            nonlocal streamed
            opened = RELEASE.os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != rules_identity:
                return original_read(descriptor, count)
            if streamed >= maximum + 1:
                self.fail("growing Ninja graph was read beyond its bound")
            size = min(count, 64 * 1024, maximum + 1 - streamed)
            streamed += size
            return b"x" * size

        RELEASE.os.read = guarded_read
        try:
            with self.assertRaises(RELEASE.ReleaseError):
                self.observe()
        finally:
            RELEASE.os.read = original_read

    def test_graph_parent_swap_cannot_supply_external_rules(self):
        cmake_files = self.role_build / "CMakeFiles"
        held_cmake_files = self.role_build / "CMakeFiles-held"
        rules = cmake_files / "rules.ninja"
        admitted_rules = rules.read_bytes()
        rules.write_text("invalid local rules\n", encoding="utf-8")
        external = self.role_build.parent / "external-rules"
        external.mkdir()
        (external / "rules.ninja").write_bytes(admitted_rules)

        original_check = RELEASE._audit_no_symlink_components
        original_lstat = RELEASE.Path.lstat
        armed = False
        path_stats = 0
        races = 0

        def swap_after_check(root, path, label):
            nonlocal armed, path_stats, races
            original_check(root, path, label)
            if Path(path) == rules:
                self.assertFalse(armed)
                cmake_files.rename(held_cmake_files)
                cmake_files.symlink_to(external, target_is_directory=True)
                armed = True
                path_stats = 0
                races += 1

        def restore_after_second_stat(path, *args, **kwargs):
            nonlocal armed, path_stats
            result = original_lstat(path, *args, **kwargs)
            if armed and Path(path) == rules:
                path_stats += 1
                if path_stats == 2:
                    cmake_files.unlink()
                    held_cmake_files.rename(cmake_files)
                    armed = False
            return result

        RELEASE._audit_no_symlink_components = swap_after_check
        RELEASE.Path.lstat = restore_after_second_stat
        rejected = False
        try:
            try:
                self.observe()
            except RELEASE.ReleaseError:
                rejected = True
        finally:
            RELEASE._audit_no_symlink_components = original_check
            RELEASE.Path.lstat = original_lstat
            if armed:
                cmake_files.unlink()
                held_cmake_files.rename(cmake_files)

        self.assertGreaterEqual(races, 1, "parent-swap race did not fire")
        if not rejected:
            self.assertEqual(races, 2, "accepted graph was not raced twice")
        self.assertTrue(rejected, "external rules graph was accepted")

    def test_path_escape_and_line_continuation_are_rejected(self):
        for edge_suffix in (
            " ../outside.obj",
            " /attacker/libevil.a",
            " $",
        ):
            with self.subTest(edge_suffix=edge_suffix):
                self._write_ninja(edge_suffix=edge_suffix)
                with self.assertRaises(RELEASE.ReleaseError):
                    self.observe()


if __name__ == "__main__":
    unittest.main()
