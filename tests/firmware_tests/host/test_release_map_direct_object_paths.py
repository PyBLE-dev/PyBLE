#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] BLD-8 — Normalize only redundant dot segments in map direct objects.
#
# Frozen sources:
#   docs/specifications/firmware/browser-flashing.md §6 rule 4
#   docs/specifications/firmware/specs.md BLD-8

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SCRIPT = REPO_ROOT / "firmware" / "scripts" / "release_bundle.py"


def load_release_module():
    spec = importlib.util.spec_from_file_location(
        "pyble_release_map_direct_object_paths",
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


class MapDirectObjectPathTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="pyble-map-direct-object-paths-"
        )
        self.role_build = Path(self.temporary.name) / "esp32"
        self.role_build.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def object_file(self, relative: str) -> Path:
        path = self.role_build / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic linked object\n")
        return path.resolve()

    def direct_outputs(
        self,
        token: str,
        *,
        compile_outputs: set[Path],
    ) -> set[Path]:
        map_path = self.role_build / "micropython.map"
        map_path.write_text("LOAD %s\n" % token, encoding="utf-8")
        return RELEASE._audit_map_direct_outputs(
            map_path,
            role_build=self.role_build,
            compile_outputs={
                output: self.role_build / "synthetic-source.c"
                for output in compile_outputs
            },
        )

    def test_real_berkeley_shape_removes_one_redundant_dot_segment(self):
        canonical = (
            "esp-idf/main/CMakeFiles/micropy_extmod_btree.dir/"
            "private/tmp/build/.sources/esp32/micropython/lib/"
            "berkeley-db-1.xx/btree/bt_close.c.obj"
        )
        output = self.object_file(canonical)
        token = canonical.replace(
            "micropy_extmod_btree.dir/private",
            "micropy_extmod_btree.dir/./private",
        )

        self.assertEqual(
            self.direct_outputs(token, compile_outputs={output}),
            {output},
        )

    def test_dot_normalization_is_generic_to_direct_load_tokens(self):
        output = self.object_file("objects/nested/widget.o")

        self.assertEqual(
            self.direct_outputs(
                "./objects/./nested/widget.o",
                compile_outputs={output},
            ),
            {output},
            "the syntax rule must not be coupled to the Berkeley topology",
        )

    def test_other_noncanonical_or_escaping_forms_remain_rejected(self):
        output = self.object_file("objects/widget.obj")
        (self.role_build / "objects" / "nested").mkdir()
        invalid = (
            "objects/nested/../widget.obj",
            "objects//widget.obj",
            "objects\\widget.obj",
            output.as_posix(),
        )

        for token in invalid:
            with self.subTest(token=token), self.assertRaises(
                RELEASE.ReleaseError
            ):
                self.direct_outputs(token, compile_outputs={output})

    def test_symlinked_component_remains_rejected_after_dot_normalization(self):
        output = self.object_file("objects/real/widget.obj")
        alias = self.role_build / "objects" / "alias"
        alias.symlink_to("real", target_is_directory=True)

        with self.assertRaises(RELEASE.ReleaseError):
            self.direct_outputs(
                "objects/./alias/widget.obj",
                compile_outputs={output},
            )

    def test_normalized_path_must_match_one_exact_compile_output(self):
        compiled = self.object_file("objects/compiled.obj")
        self.object_file("objects/unmatched.obj")

        with self.assertRaises(RELEASE.ReleaseError):
            self.direct_outputs(
                "objects/./unmatched.obj",
                compile_outputs={compiled},
            )

    def test_dot_admission_does_not_broaden_shared_relative_paths(self):
        with self.assertRaises(RELEASE.ReleaseError):
            RELEASE._safe_relative_path(
                "objects/./widget.obj",
                "non-map path",
            )


if __name__ == "__main__":
    unittest.main()
