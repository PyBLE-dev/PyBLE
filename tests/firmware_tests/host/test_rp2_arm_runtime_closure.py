#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for the exact Arm GNU RP2 runtime-license closure."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "docs/specifications/firmware.md"
POLICY = ROOT / "firmware/licenses/rp2-license-policy.json"
LOCK = ROOT / "firmware/versions.lock"
RELEASE_BUNDLE = ROOT / "firmware/scripts/release_bundle.py"
ATTRIBUTION = (
    ROOT
    / "firmware/licenses/evidence/rp2/arm-gnu-toolchain/14.2.rel1"
    / "runtime-attribution-v1.json"
)
LIBGLOSS = (
    ROOT
    / "firmware/licenses/texts/COPYING.LIBGLOSS.arm-gnu-14.2.rel1.txt"
)

ATTRIBUTION_SHA256 = (
    "6c8fd8e26105c96e370738c3d8e210a7c40ab03f58f7edbb82fb7d854c96b891"
)
LIBGLOSS_SHA256 = (
    "bdaffd5fff30cb5fc7a239a4fa0b95f703590f7b3813ca7f4e76ff46437aeb81"
)
NEWLIB_SHA256 = (
    "fcfb5ec69b6ab52676dcc4dab7cf4338c8000ef97812dadd35b8592a640a8419"
)

OWNER_CONTRACT = {
    "arm-gnu-binutils-build-tools": {
        "kind": "build-tool",
        "expression": "GPL-3.0-or-later",
        "roots": {
            "arm-none-eabi/bin/as",
            "arm-none-eabi/bin/ld",
        },
    },
    "arm-gnu-gcc-build-tools": {
        "kind": "build-tool",
        "expression": "GPL-3.0-or-later",
        "roots": {
            "bin/arm-none-eabi-g++",
            "bin/arm-none-eabi-gcc",
            "libexec/gcc/arm-none-eabi/14.2.1/collect2",
        },
    },
    "arm-gnu-gcc-runtime": {
        "kind": "runtime",
        "expression": "GPL-3.0-or-later WITH GCC-exception-3.1",
        "roots": {
            "arm-none-eabi/include/c++/14.2.1",
            "arm-none-eabi/lib/thumb/v8-m.main+fp/softfp/libstdc++.a",
            "lib/gcc/arm-none-eabi/14.2.1/include",
            "lib/gcc/arm-none-eabi/14.2.1/thumb/v8-m.main+fp/softfp/crtbegin.o",
            "lib/gcc/arm-none-eabi/14.2.1/thumb/v8-m.main+fp/softfp/crtend.o",
            "lib/gcc/arm-none-eabi/14.2.1/thumb/v8-m.main+fp/softfp/crti.o",
            "lib/gcc/arm-none-eabi/14.2.1/thumb/v8-m.main+fp/softfp/crtn.o",
            "lib/gcc/arm-none-eabi/14.2.1/thumb/v8-m.main+fp/softfp/libgcc.a",
        },
    },
    "arm-gnu-libgloss-runtime": {
        "kind": "runtime",
        "expression": "LicenseRef-PyBLE-Libgloss-Multilicense",
        "roots": {
            "arm-none-eabi/lib/thumb/v8-m.main+fp/softfp/crt0.o",
            "arm-none-eabi/lib/thumb/v8-m.main+fp/softfp/libnosys.a",
        },
    },
    "arm-gnu-newlib-runtime": {
        "kind": "runtime",
        "expression": "LicenseRef-PyBLE-Newlib-Multilicense",
        "roots": {
            "arm-none-eabi/include",
            "arm-none-eabi/lib/thumb/v8-m.main+fp/softfp/libc.a",
            "arm-none-eabi/lib/thumb/v8-m.main+fp/softfp/libg.a",
            "arm-none-eabi/lib/thumb/v8-m.main+fp/softfp/libm.a",
        },
    },
}

SOURCE_LOCK_CONTRACT = {
    "source_archive_bytes": 311_500_280,
    "source_archive_filename": (
        "arm-gnu-toolchain-src-snapshot-14.2.rel1.tar.xz"
    ),
    "source_archive_format": "tar.xz",
    "source_archive_sha256": (
        "e6405f20f8a817a50d92dbf7974d0ee77708dfdf9e79900a59c5d343b464ef9c"
    ),
    "source_archive_url": (
        "https://developer.arm.com/-/media/Files/downloads/gnu/14.2.rel1/"
        "srcrel/arm-gnu-toolchain-src-snapshot-14.2.rel1.tar.xz"
    ),
    "source_manifest_path": (
        "firmware/licenses/evidence/rp2/arm-gnu-toolchain/14.2.rel1/"
        "source-manifest.txt"
    ),
    "source_manifest_sha256": (
        "470cdb8bae9f5fed96c17b10834bbd22820e933cfad99914c3f37997cae36745"
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_release_module():
    spec = importlib.util.spec_from_file_location(
        "release_bundle_arm_runtime_red", RELEASE_BUNDLE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELEASE = load_release_module()


class RP2ArmRuntimeClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.attribution = json.loads(ATTRIBUTION.read_text(encoding="utf-8"))

    def test_spec_freezes_build_input_vs_shipped_contribution(self) -> None:
        value = SPEC.read_text(encoding="utf-8")
        for required in (
            "### 6.1 RP2 Arm GNU runtime-license closure",
            "**build tool**",
            "**link input**",
            "**compiler-dependency header**",
            "**allocated contributor**",
            "**install payload**",
            "`contributes: false`",
            "Eligible Compilation",
        ):
            with self.subTest(required=required):
                self.assertIn(required, value)

    def test_exact_attribution_and_license_assets_are_hash_bound(self) -> None:
        self.assertEqual(sha256(ATTRIBUTION), ATTRIBUTION_SHA256)
        self.assertEqual(sha256(LIBGLOSS), LIBGLOSS_SHA256)
        newlib = (
            ROOT
            / "firmware/licenses/texts/"
            "COPYING.NEWLIB.arm-gnu-14.2.rel1.txt"
        )
        self.assertEqual(sha256(newlib), NEWLIB_SHA256)

        identity = self.attribution["identity"]
        self.assertEqual(
            identity["binary_archive"],
            {
                "bytes": 134_812_148,
                "filename": (
                    "arm-gnu-toolchain-14.2.rel1-darwin-arm64-"
                    "arm-none-eabi.tar.xz"
                ),
                "sha256": (
                    "c7c78ffab9bebfce91d99d3c24da6bf4b81c01e16cf551eb2ff9f25b9e0a3818"
                ),
            },
        )
        self.assertEqual(
            identity["source_archive"]["sha256"],
            SOURCE_LOCK_CONTRACT["source_archive_sha256"],
        )
        self.assertEqual(
            identity["source_commits"],
            {
                "binutils-gdb": "74c7803f0cc8d3d66513b6d6549bff2fbe737a7d",
                "gcc": "a05ea1e5ee0867191bb432a84c055be99dbdbc16",
                "newlib-cygwin": (
                    "7923059bff6c120c6fb74b63c7553ea345c0a8f3"
                ),
            },
        )

    def test_attribution_freezes_five_components_and_exact_closure_counts(
        self,
    ) -> None:
        components = {item["id"]: item for item in self.attribution["components"]}
        self.assertEqual(set(components), set(OWNER_CONTRACT))
        for owner_id, expected in OWNER_CONTRACT.items():
            with self.subTest(owner=owner_id):
                self.assertEqual(components[owner_id]["kind"], expected["kind"])
                self.assertEqual(
                    components[owner_id]["license_basis"],
                    expected["expression"],
                )

        self.assertEqual(
            self.attribution["summary"],
            {
                "allocated_archive_member_count": 29,
                "build_tool_count": 5,
                "direct_contributor_count": 3,
                "exact_header_count": 62,
                "generated_header_count": 4,
                "header_count": 66,
                "owner_count": 5,
            },
        )
        counts = {
            item[1]: item[3] for item in self.attribution["runtime_archives"]
        }
        self.assertEqual(
            counts,
            {
                "lib/gcc/arm-none-eabi/14.2.1/thumb/"
                "v8-m.main+fp/softfp/libgcc.a": 6,
                "arm-none-eabi/lib/thumb/v8-m.main+fp/softfp/libstdc++.a": 0,
                "arm-none-eabi/lib/thumb/v8-m.main+fp/softfp/libc.a": 0,
                "arm-none-eabi/lib/thumb/v8-m.main+fp/softfp/libg.a": 22,
                "arm-none-eabi/lib/thumb/v8-m.main+fp/softfp/libm.a": 1,
                "arm-none-eabi/lib/thumb/v8-m.main+fp/softfp/libnosys.a": 0,
            },
        )

    def test_direct_and_archive_member_source_mappings_are_exact(self) -> None:
        direct = {Path(item[1]).name: item for item in self.attribution["direct_inputs"]}
        self.assertEqual(
            {name for name, item in direct.items() if item[3]},
            {"crti.o", "crtbegin.o", "crtend.o"},
        )
        self.assertFalse(direct["crt0.o"][3])
        self.assertEqual(direct["crt0.o"][0], "arm-gnu-libgloss-runtime")
        self.assertEqual(
            direct["crt0.o"][4:],
            [
                "newlib-cygwin/libgloss/arm/crt0.S",
                "762e48eab82804f83574c682ca55fb8f7e212f10229928586814f860155ea1a8",
                "libgloss-default-compilation",
            ],
        )
        self.assertFalse(direct["crtn.o"][3])

        members = self.attribution["archive_members"]
        self.assertEqual(len(members), 29)
        self.assertEqual(
            {item[1] for item in members}, {"libgcc.a", "libg.a", "libm.a"}
        )
        self.assertEqual(len({(item[1], item[2]) for item in members}), 29)
        for item in members:
            with self.subTest(archive=item[1], member=item[2]):
                self.assertRegex(item[3], r"^[0-9a-f]{64}$")
                self.assertRegex(item[5], r"^[0-9a-f]{64}$")
                self.assertIn(
                    item[6],
                    {
                        "gcc-runtime-exception",
                        "newlib-default-compilation",
                        "source-header",
                    },
                )

    def test_all_66_headers_and_four_generation_recipes_are_frozen(self) -> None:
        exact = self.attribution["headers"]
        generated = self.attribution["generated_headers"]
        self.assertEqual(len(exact), 62)
        self.assertEqual(len(generated), 4)
        all_paths = [item[1] for item in exact + generated]
        self.assertEqual(len(all_paths), len(set(all_paths)))
        self.assertEqual(
            sum(path.startswith("arm-none-eabi/include/c++/") for path in all_paths),
            7,
        )
        self.assertEqual(
            sum(path.startswith("lib/gcc/") for path in all_paths), 9
        )
        self.assertEqual(len(all_paths) - 7 - 9, 50)
        generated_by_name = {Path(item[1]).name: item for item in generated}
        self.assertEqual(
            set(generated_by_name),
            {"_newlib_version.h", "newlib.h", "c++config.h", "limits.h"},
        )
        syslimits = next(
            item
            for item in exact
            if item[1].startswith("lib/gcc/")
            and item[1].endswith("syslimits.h")
        )
        self.assertEqual(syslimits[3], "gcc/gcc/gsyslimits.h")
        self.assertEqual(
            syslimits[2],
            "22dd0ab81baadd5a8d455b445855f341d419c7b0267beca235de00b7ec78e529",
        )

    def test_policy_v2_has_the_exact_five_allow_owner_split(self) -> None:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        self.assertEqual(policy["schema_version"], 2)
        owners = {item["id"]: item for item in policy["source_owners"]}
        for owner_id, expected in OWNER_CONTRACT.items():
            with self.subTest(owner=owner_id):
                self.assertIn(owner_id, owners)
                owner = owners[owner_id]
                self.assertEqual(owner["component_kind"], expected["kind"])
                self.assertEqual(owner["disposition"], "allow")
                self.assertEqual(
                    owner["source_spdx_expression"], expected["expression"]
                )
                self.assertEqual(
                    owner["selected_spdx_expression"], expected["expression"]
                )
                toolchain_roots = {
                    item["path"]
                    for item in owner["source_roots"]
                    if item["namespace"] == "arm-gnu-toolchain"
                }
                self.assertEqual(toolchain_roots, expected["roots"])

        self.assertNotIn(
            "bin/arm-none-eabi-gcc",
            OWNER_CONTRACT["arm-gnu-gcc-runtime"]["roots"],
        )
        self.assertNotIn(
            "arm-none-eabi/lib/thumb/v8-m.main+fp/softfp/crt0.o",
            OWNER_CONTRACT["arm-gnu-newlib-runtime"]["roots"],
        )

    def test_versions_lock_pins_the_replayable_official_source_archive(self) -> None:
        arm = tomllib.loads(LOCK.read_text(encoding="utf-8"))["arm_gnu_toolchain"]
        for key, expected in SOURCE_LOCK_CONTRACT.items():
            with self.subTest(key=key):
                self.assertEqual(arm.get(key), expected)

    def expected_observation(self) -> dict[str, object]:
        attribution = self.attribution
        return {
            "identity": copy.deepcopy(attribution["identity"]),
            "build_tools": copy.deepcopy(attribution["build_tools"]),
            "runtime_archives": copy.deepcopy(attribution["runtime_archives"]),
            "direct_inputs": copy.deepcopy(attribution["direct_inputs"]),
            "archive_members": copy.deepcopy(attribution["archive_members"]),
            "headers": copy.deepcopy(attribution["headers"]),
            "generated_headers": copy.deepcopy(attribution["generated_headers"]),
            "eligible_compilation_receipt": {
                "bound_kinds": copy.deepcopy(
                    attribution["eligible_compilation"]["required_receipt_kinds"]
                ),
                "compiler_launchers": [],
                "external_ir_consumers": [],
                "compile_recipes": [
                    {
                        "language": "C",
                        "driver": "bin/arm-none-eabi-gcc",
                        "arguments": ["-Os"],
                    },
                    {
                        "language": "CXX",
                        "driver": "bin/arm-none-eabi-g++",
                        "arguments": ["-Os"],
                    },
                    {
                        "language": "ASM",
                        "driver": "bin/arm-none-eabi-gcc",
                        "arguments": ["-Os"],
                    },
                ],
                "link_driver": "bin/arm-none-eabi-g++",
                "link_arguments": ["-Wl,--gc-sections"],
                "source_archive_sha256": (
                    SOURCE_LOCK_CONTRACT["source_archive_sha256"]
                ),
            },
        }

    def validator(self):
        value = getattr(RELEASE, "_audit_validate_rp2_arm_runtime_closure", None)
        self.assertTrue(
            callable(value),
            "missing fail-closed Arm runtime attribution/receipt validator",
        )
        return value

    def validate(self, observed: dict[str, object]) -> dict[str, object]:
        return self.validator()(
            copy.deepcopy(self.attribution),
            observed,
            repo_root=ROOT,
        )

    def test_validator_derives_notice_scope_from_contribution_not_load(self) -> None:
        result = self.validate(self.expected_observation())
        self.assertTrue(result["eligible_compilation"])
        self.assertEqual(
            set(result["contributing_owner_ids"]),
            {"arm-gnu-gcc-runtime", "arm-gnu-newlib-runtime"},
        )
        self.assertEqual(
            set(result["public_notice_owner_ids"]),
            {"arm-gnu-gcc-runtime", "arm-gnu-newlib-runtime"},
        )
        self.assertNotIn("arm-gnu-libgloss-runtime", result["public_notice_owner_ids"])
        self.assertTrue(
            all(
                not owner.endswith("build-tools")
                for owner in result["public_notice_owner_ids"]
            )
        )

    def test_validator_fails_closed_on_identity_mapping_or_recipe_drift(self) -> None:
        cases = {}
        source = self.expected_observation()
        source["identity"]["source_archive"]["sha256"] = "0" * 64
        cases["source-archive"] = source

        member = self.expected_observation()
        member["archive_members"][0][3] = "0" * 64
        cases["member"] = member

        header = self.expected_observation()
        header["headers"][0][2] = "0" * 64
        cases["header"] = header

        generated = self.expected_observation()
        generated["generated_headers"][0][3][0][1] = "0" * 64
        cases["generated-header-recipe"] = generated

        extra = self.expected_observation()
        extra["archive_members"].append(
            [
                "arm-gnu-newlib-runtime",
                "libg.a",
                "unmapped.o",
                "1" * 64,
                "newlib-cygwin/newlib/unmapped.c",
                "2" * 64,
                "newlib-default-compilation",
            ]
        )
        cases["extra-member"] = extra

        for label, observed in cases.items():
            with self.subTest(case=label), self.assertRaises(RELEASE.ReleaseError):
                self.validate(observed)

    def test_eligible_compilation_rejects_unreviewed_ir_and_tool_paths(self) -> None:
        cases = {}
        launcher = self.expected_observation()
        launcher["eligible_compilation_receipt"]["compiler_launchers"] = [
            "/tmp/wrapper"
        ]
        cases["launcher"] = launcher

        plugin = self.expected_observation()
        plugin["eligible_compilation_receipt"]["compile_recipes"][0][
            "arguments"
        ].append("-fplugin=/tmp/plugin.dylib")
        cases["plugin"] = plugin

        lto = self.expected_observation()
        lto["eligible_compilation_receipt"]["compile_recipes"][0][
            "arguments"
        ].append("-flto")
        cases["lto"] = lto

        external_ir = self.expected_observation()
        external_ir["eligible_compilation_receipt"]["external_ir_consumers"] = [
            "/tmp/optimizer"
        ]
        cases["external-ir"] = external_ir

        driver = self.expected_observation()
        driver["eligible_compilation_receipt"]["compile_recipes"][0][
            "driver"
        ] = "/usr/bin/clang"
        cases["driver"] = driver

        missing = self.expected_observation()
        missing["eligible_compilation_receipt"]["bound_kinds"].remove("depfile")
        cases["missing-receipt-kind"] = missing

        for label, observed in cases.items():
            with self.subTest(case=label), self.assertRaises(RELEASE.ReleaseError):
                self.validate(observed)

    def test_a_new_exact_libgloss_contribution_requires_its_notice(self) -> None:
        observed = self.expected_observation()
        crt0 = next(item for item in observed["direct_inputs"] if item[1].endswith("crt0.o"))
        crt0[3] = True
        result = self.validate(observed)
        self.assertIn("arm-gnu-libgloss-runtime", result["contributing_owner_ids"])
        self.assertIn("arm-gnu-libgloss-runtime", result["public_notice_owner_ids"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
