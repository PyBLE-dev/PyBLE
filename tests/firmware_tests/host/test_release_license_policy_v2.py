#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] BLD-8 — Fail-closed schema-v2 release-license resolution.
#
# Frozen sources:
#   docs/specifications/firmware/browser-flashing.md §6 rules 4–9
#   docs/specifications/firmware/TDD.md §10.7 and §14.3
#
# This suite pins one pure production seam:
#
#   _audit_validate_policy_v2(
#       policy,
#       *,
#       repo_root,
#       observed_documents,
#       observed_inputs,
#       toolchain_roots=None,
#   )
#
# It validates policy against already parsed raw SPDX and already reconciled
# build observations. Process execution, tag/value parsing, and receipt writing
# remain covered by test_release_license_audit.py.

from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_TEST = Path(__file__).with_name("test_release_license_audit.py")


def load_base_module():
    spec = importlib.util.spec_from_file_location(
        "pyble_release_license_audit_v2_fixtures",
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
VALIDATE_V2 = (
    getattr(RELEASE, "_audit_validate_policy_v2", None) if RELEASE is not None else None
)
VERIFY_EVIDENCE = (
    getattr(RELEASE, "_audit_verify_release_evidence", None)
    if RELEASE is not None
    else None
)
PROFILE_ROLES = BASE.PROFILE_ROLES


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_tree(path: Path) -> str:
    return BASE.sha256_tree(path)


def package_id(identifier: str) -> str:
    return "SPDXRef-Package-" + re.sub(r"[^A-Za-z0-9.-]", "-", identifier)


def deep_scalars(value: object):
    if isinstance(value, dict):
        for child in value.values():
            yield from deep_scalars(child)
    elif isinstance(value, list):
        for child in value:
            yield from deep_scalars(child)
    elif isinstance(value, (str, int, float, bool)) or value is None:
        yield value


def toolchain_tar_bytes(
    *,
    root_name: str,
    files: dict[str, bytes],
    unsafe_symlink: bool = False,
) -> bytes:
    output = io.BytesIO()
    with tarfile.open(
        fileobj=output, mode="w:xz", format=tarfile.PAX_FORMAT
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
        if unsafe_symlink:
            info = tarfile.TarInfo("%s/unsafe-link" % root_name)
            info.type = tarfile.SYMTYPE
            info.linkname = "../../outside"
            info.mode = 0o777
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            archive.addfile(info)
    return output.getvalue()


class PolicyV2Fixture:
    """Small, legally neutral, real-shaped schema-v2 fixture."""

    def __init__(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="pyble-license-policy-v2-")
        self.root = Path(self._temporary.name)
        self.repo = self.root / "repo"
        self.build = self.root / "build"
        self.repo.mkdir()
        self.build.mkdir()
        self.licenses = self.repo / "firmware" / "licenses"
        self.texts = self.licenses / "texts"
        self.notices = self.licenses / "notices"
        self.texts.mkdir(parents=True)
        self.notices.mkdir(parents=True)
        (self.repo / "firmware" / "versions.lock").write_text(
            """[micropython]
repo = "https://github.com/micropython/micropython"
ref = "v1.28.0"
commit = "2222222222222222222222222222222222222222"
[esp_idf]
repo = "https://github.com/espressif/esp-idf"
ref = "v5.5.1"
commit = "3333333333333333333333333333333333333333"
[pyble]
agent_version = "0.5.0"
protocol_version = "PBLE/1"
""",
            encoding="utf-8",
        )
        self._write_reviewed_texts()
        self.neopixel_tree = (
            self.repo
            / "firmware"
            / "upstream"
            / "micropython"
            / "lib"
            / "micropython-lib"
            / "micropython"
            / "drivers"
            / "led"
            / "neopixel"
        )
        self.mbedtls_tree = (
            self.repo / "firmware" / "upstream" / "esp-idf" / "components" / "mbedtls"
        )
        self._write_supplemental_sources()
        self.manifest_evidence = self._make_manifest_evidence()
        self.toolchain = self._make_toolchain()
        self.observed_documents = self._make_observed_documents()
        self.observed_inputs = self._make_observed_inputs()
        self.policy = self._make_policy()

    def close(self):
        self._temporary.cleanup()

    def _write_reviewed_texts(self):
        (self.texts / "MIT.txt").write_text(
            "MIT License\n\nComplete synthetic fixture text.\n",
            encoding="utf-8",
        )
        (self.texts / "Apache-2.0.txt").write_text(
            "Apache License 2.0\n\nComplete synthetic fixture text.\n",
            encoding="utf-8",
        )
        (self.texts / "GPL-3.0-or-later.txt").write_text(
            "GPL-3.0-or-later\n\nComplete synthetic fixture text.\n",
            encoding="utf-8",
        )
        (self.texts / "GCC-exception-3.1.txt").write_text(
            "GCC Runtime Library Exception 3.1\n\n"
            "Complete synthetic fixture text.\n",
            encoding="utf-8",
        )
        (self.notices / "source.txt").write_text(
            "Retain this synthetic source attribution.\n",
            encoding="utf-8",
        )
        (self.notices / "runtime.txt").write_text(
            "Retain this synthetic runtime attribution.\n",
            encoding="utf-8",
        )

    def _write_supplemental_sources(self):
        core_source = self.repo / "firmware" / "components" / "core" / "core.c"
        core_source.parent.mkdir(parents=True)
        core_source.write_bytes(b"synthetic core source\n")
        canonical_tft = (
            self.repo / "firmware" / "python_modules" / "pyble_st7789.py"
        )
        canonical_tft.parent.mkdir(parents=True)
        canonical_tft.write_text(
            "# SPDX-License-Identifier: MIT\n"
            "# Synthetic first-party PyBLE ST7789 fixture.\n",
            encoding="utf-8",
        )
        canonical_companion = (
            self.repo
            / "firmware"
            / "board_overlays"
            / "waveshare-esp32-s3-lcd-147b"
            / "pyble_waveshare_lcd147b.py"
        )
        canonical_companion.parent.mkdir(parents=True)
        canonical_companion.write_text(
            "# SPDX-License-Identifier: MIT\n"
            "# Synthetic first-party PyBLE Waveshare LCD fixture.\n",
            encoding="utf-8",
        )
        self.neopixel_tree.mkdir(parents=True)
        (self.neopixel_tree / "manifest.py").write_text(
            'metadata(version="0.1.0")\nmodule("neopixel.py")\n',
            encoding="utf-8",
        )
        (self.neopixel_tree / "neopixel.py").write_text(
            "# SPDX-License-Identifier: MIT\nclass NeoPixel:\n    pass\n",
            encoding="utf-8",
        )
        for component in ("mbedcrypto", "mbedtls", "mbedx509"):
            source = self.mbedtls_tree / component / ("%s.c" % component)
            source.parent.mkdir(parents=True)
            source.write_text(
                "// SPDX-License-Identifier: Apache-2.0\n"
                "int fixture_%s(void) { return 1; }\n" % component,
                encoding="utf-8",
            )

    def _make_manifest_evidence(self) -> list[dict]:
        manifest = self.neopixel_tree / "manifest.py"
        source = self.neopixel_tree / "neopixel.py"
        generator_relatives = (
            "firmware/upstream/micropython/mpy-cross/mpy_cross/__init__.py",
            "firmware/upstream/micropython/py/makeqstrdata.py",
            "firmware/upstream/micropython/tools/makemanifest.py",
            "firmware/upstream/micropython/tools/manifestfile.py",
            "firmware/upstream/micropython/tools/mpy-tool.py",
        )
        for relative in generator_relatives:
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "# synthetic frozen generator fixture: %s\n" % relative,
                encoding="utf-8",
            )
        mpy_cross_relative = (
            "firmware/upstream/micropython/mpy-cross/build/mpy-cross"
        )
        mpy_cross = self.repo / mpy_cross_relative
        mpy_cross.parent.mkdir(parents=True, exist_ok=True)
        mpy_cross.write_text(
            "#!/bin/sh\n# synthetic mpy-cross fixture\n",
            encoding="utf-8",
        )
        mpy_cross.chmod(0o755)
        generators = [
            {
                "path": relative,
                "sha256": BASE.sha256_path(self.repo / relative),
            }
            for relative in generator_relatives
        ]
        canonical_tft = (
            self.repo / "firmware" / "python_modules" / "pyble_st7789.py"
        )
        canonical_companion = (
            self.repo
            / "firmware"
            / "board_overlays"
            / "waveshare-esp32-s3-lcd-147b"
            / "pyble_waveshare_lcd147b.py"
        )
        generated_tft = None
        generated_companion = None
        for target, settings in RELEASE.FROZEN_TARGET_SETTINGS.items():
            copied_manifest = (
                self.repo
                / "firmware"
                / "upstream"
                / "micropython"
                / "ports"
                / "esp32"
                / "boards"
                / settings["board"]
                / "manifest.py"
            )
            copied_manifest.parent.mkdir(parents=True, exist_ok=True)
            copied_manifest.write_bytes(manifest.read_bytes())
            if target == "waveshare-esp32-s3-lcd-147b":
                generated_tft = copied_manifest.parent / "pyble_st7789.py"
                generated_tft.write_bytes(canonical_tft.read_bytes())
                generated_companion = (
                    copied_manifest.parent / "pyble_waveshare_lcd147b.py"
                )
                generated_companion.write_bytes(
                    canonical_companion.read_bytes()
                )

        records = []
        for target in sorted(
            target
            for _profile_id, target, _idf_target in RELEASE.LICENSE_AUDIT_PROFILES
        ):
            selections = [
                {
                    "destination": "neopixel.py",
                    "source_path": source.relative_to(self.repo).as_posix(),
                    "sha256": BASE.sha256_path(source),
                    "optimization": 3,
                    "metadata_version": "0.1.0",
                }
            ]
            frozen_mpy = [
                {
                    "destination": "neopixel.mpy",
                    "sha256": sha256_bytes(
                        ("synthetic neopixel mpy/%s" % target).encode()
                    ),
                }
            ]
            first_party = []
            if target == "waveshare-esp32-s3-lcd-147b":
                selections.extend(
                    [
                        {
                            "destination": "pyble_st7789.py",
                            "source_path": canonical_tft.relative_to(
                                self.repo
                            ).as_posix(),
                            "sha256": BASE.sha256_path(canonical_tft),
                            "optimization": 3,
                            "metadata_version": None,
                        },
                        {
                            "destination": "pyble_waveshare_lcd147b.py",
                            "source_path": canonical_companion.relative_to(
                                self.repo
                            ).as_posix(),
                            "sha256": BASE.sha256_path(
                                canonical_companion
                            ),
                            "optimization": 3,
                            "metadata_version": None,
                        },
                    ]
                )
                frozen_mpy.extend(
                    [
                        {
                            "destination": "pyble_st7789.mpy",
                            "sha256": sha256_bytes(
                                b"synthetic pyble_st7789 mpy/"
                                b"waveshare-esp32-s3-lcd-147b"
                            ),
                        },
                        {
                            "destination": "pyble_waveshare_lcd147b.mpy",
                            "sha256": sha256_bytes(
                                b"synthetic pyble_waveshare_lcd147b mpy/"
                                b"waveshare-esp32-s3-lcd-147b"
                            ),
                        },
                    ]
                )
                first_party.extend(
                    [
                        {
                            "destination": "pyble_st7789.py",
                            "canonical_path": canonical_tft.relative_to(
                                self.repo
                            ).as_posix(),
                            "generated_path": generated_tft.relative_to(
                                self.repo
                            ).as_posix(),
                            "sha256": BASE.sha256_path(canonical_tft),
                            "spdx_expression": "MIT",
                        },
                        {
                            "destination": "pyble_waveshare_lcd147b.py",
                            "canonical_path": canonical_companion.relative_to(
                                self.repo
                            ).as_posix(),
                            "generated_path": (
                                generated_companion.relative_to(
                                    self.repo
                                ).as_posix()
                            ),
                            "sha256": BASE.sha256_path(
                                canonical_companion
                            ),
                            "spdx_expression": "MIT",
                        },
                    ]
                )
            records.append(
                {
                    "target": target,
                    "architecture": RELEASE.FROZEN_TARGET_SETTINGS[target][
                        "architecture"
                    ],
                    "frozen_content_sha256": sha256_bytes(
                        ("synthetic frozen content/%s" % target).encode()
                    ),
                    "qstrdefs_sha256": sha256_bytes(
                        ("synthetic qstr/%s" % target).encode()
                    ),
                    "mpy_cross": {
                        "path": mpy_cross_relative,
                        "sha256": BASE.sha256_path(mpy_cross),
                    },
                    "generator_tools": copy.deepcopy(generators),
                    "frozen_mpy": frozen_mpy,
                    "linked_frozen_object": {
                        "component": "main",
                        "archive_path": "%s/esp-idf/main/libmain.a" % target,
                        "member": "frozen_content.c.obj",
                        "sha256": sha256_bytes(
                            ("synthetic frozen object/%s" % target).encode()
                        ),
                    },
                    "generated_board_manifest": (
                        "firmware/upstream/micropython/ports/esp32/boards/%s/"
                        "manifest.py"
                        % RELEASE.FROZEN_TARGET_SETTINGS[target]["board"]
                    ),
                    "first_party_frozen_sources": first_party,
                    "manifests": [
                        {
                            "path": manifest.relative_to(self.repo).as_posix(),
                            "sha256": BASE.sha256_path(manifest),
                        }
                    ],
                    "selections": sorted(
                        selections,
                        key=lambda item: item["destination"],
                    ),
                }
            )
        return records

    def _make_toolchain(self) -> dict:
        root_name = "xtensa-esp-elf-14.2.0_20241119-aarch64-apple-darwin"
        name = "xtensa-esp-elf"
        version = "14.2.0_20241119"
        platform_name = "aarch64-apple-darwin"
        compiler_relatives = sorted(
            [
                "bin/xtensa-esp-elf-g++",
                "bin/xtensa-esp-elf-gcc",
            ]
        )
        runtime_relative = "lib/gcc/xtensa-esp-elf/14.2.0/libgcc.a"
        files = {
            compiler_relatives[0]: (
                b"#!/bin/sh\n# synthetic C++ compiler identity\n"
            ),
            compiler_relatives[1]: (
                b"#!/bin/sh\n# synthetic C compiler identity\n"
            ),
            runtime_relative: BASE.make_ar_bytes(
                [("_divsi3.o", b"synthetic runtime object\n")]
            ),
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
        distribution = tools_home / "dist" / ("%s.tar.xz" % root_name)
        distribution.parent.mkdir(parents=True)
        distribution.write_bytes(toolchain_tar_bytes(root_name=root_name, files=files))
        distribution_url = (
            "https://example.invalid/toolchains/%s" % distribution.name
        )
        metadata = (
            self.repo / "firmware" / ".esp-idf" / "tools" / "tools.json"
        )
        BASE.write_json(
            metadata,
            {
                "version": 1,
                "tools": [
                    {
                        "name": name,
                        "export_paths": [[root_name, "bin"]],
                        "versions": [
                            {
                                "name": version,
                                platform_name: {
                                    "url": distribution_url,
                                    "size": distribution.stat().st_size,
                                    "sha256": BASE.sha256_path(distribution),
                                },
                            }
                        ],
                    }
                ],
            },
        )
        return {
            "id": "fixture-xtensa-toolchain",
            "name": name,
            "version": version,
            "platform": platform_name,
            "root_name": root_name,
            "tools_home": tools_home,
            "install_root_relative": install_root_relative,
            "installed_root": installed_root,
            "compiler_relatives": compiler_relatives,
            "runtime_relative": runtime_relative,
            "files": files,
            "distribution": distribution,
            "distribution_url": distribution_url,
            "metadata": metadata,
        }

    @staticmethod
    def _raw_package(
        *,
        identifier: str,
        profile_id: str,
        role: str,
        concluded: str,
    ) -> dict:
        return {
            "name": "Fixture %s" % identifier,
            "SPDXID": package_id(identifier),
            "versionInfo": "raw-build-version",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": concluded,
            "licenseDeclared": "NOASSERTION",
            "copyrightText": "NOASSERTION",
            "checksums": [
                {
                    "algorithm": "SHA256",
                    "checksumValue": sha256_bytes(
                        ("%s/%s/%s" % (profile_id, role, identifier)).encode()
                    ),
                }
            ],
            "externalRefs": [
                {
                    "referenceCategory": "OTHER",
                    "referenceType": "purl",
                    "referenceLocator": (
                        "pkg:generic/%s@raw?profile=%s&role=%s"
                        % (identifier, profile_id, role)
                    ),
                }
            ],
            "comment": "exact raw linked-only package",
            "summary": "Weak raw provenance is intentionally preserved.",
            "supplier": "NOASSERTION",
            "originator": "NOASSERTION",
        }

    def _make_observed_documents(self) -> dict[tuple[str, str], dict]:
        documents = {}
        for profile_id, role in PROFILE_ROLES:
            packages = [
                self._raw_package(
                    identifier="core",
                    profile_id=profile_id,
                    role=role,
                    concluded=(
                        "MIT"
                        if (profile_id, role) == PROFILE_ROLES[0]
                        else "NOASSERTION"
                    ),
                ),
                self._raw_package(
                    identifier="runtime",
                    profile_id=profile_id,
                    role=role,
                    concluded="NOASSERTION",
                ),
            ]
            if role == "application":
                packages.append(
                    self._raw_package(
                        identifier="opaque",
                        profile_id=profile_id,
                        role=role,
                        concluded="Apache-2.0",
                    )
                )
            relationships = [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": package_id("core"),
                },
                {
                    "spdxElementId": package_id("core"),
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": package_id("runtime"),
                },
            ]
            if role == "application":
                relationships.append(
                    {
                        "spdxElementId": package_id("core"),
                        "relationshipType": "DEPENDS_ON",
                        "relatedSpdxElement": package_id("opaque"),
                    }
                )
            documents[(profile_id, role)] = {
                "packages": packages,
                "relationships": relationships,
            }
        return documents

    def _observed_input(
        self,
        *,
        identifier: str,
        profile_id: str,
        role: str,
        kind: str,
        path: Path,
        **metadata,
    ) -> dict:
        return {
            "id": identifier,
            "profile_id": profile_id,
            "role": role,
            "kind": kind,
            "observed_path": str(path.resolve()),
            "sha256": BASE.sha256_path(path),
            **metadata,
        }

    def _make_observed_inputs(self) -> list[dict]:
        inputs = []
        opaque_reviewed = self.repo / "firmware" / "prebuilt" / "libfixture_opaque.a"
        opaque_reviewed.parent.mkdir(parents=True)
        opaque_reviewed.write_bytes(
            BASE.make_ar_bytes([("opaque.o", b"synthetic opaque object\n")])
        )
        for profile_id, role in PROFILE_ROLES:
            role_root = self.build / profile_id / role
            generated = role_root / "libfixture_core.a"
            generated.parent.mkdir(parents=True)
            generated.write_bytes(
                BASE.make_ar_bytes([("core.o", b"synthetic generated object\n")])
            )
            inputs.append(
                self._observed_input(
                    identifier="core--%s--%s" % (profile_id, role),
                    profile_id=profile_id,
                    role=role,
                    kind="generated-component-archive",
                    path=generated,
                    generated_binding={
                        "component": "core",
                        "project_description_sha256": sha256_bytes(
                            ("description/%s/%s" % (profile_id, role)).encode()
                        ),
                        "compile_commands_sha256": sha256_bytes(
                            ("compile/%s/%s" % (profile_id, role)).encode()
                        ),
                        "linker_map_sha256": sha256_bytes(
                            ("map/%s/%s" % (profile_id, role)).encode()
                        ),
                        "sources": [
                            {
                                "path": "firmware/components/core/core.c",
                                "sha256": sha256_bytes(b"synthetic core source\n"),
                            }
                        ],
                        "members": ["core.o"],
                    },
                )
            )
            runtime = (
                self.toolchain["installed_root"] / self.toolchain["runtime_relative"]
            )
            inputs.append(
                self._observed_input(
                    identifier="runtime--%s--%s" % (profile_id, role),
                    profile_id=profile_id,
                    role=role,
                    kind="toolchain-archive",
                    path=runtime,
                    toolchain_id=self.toolchain["id"],
                    relative_path=self.toolchain["runtime_relative"],
                    compiler_paths=[
                        str(
                            (
                                self.toolchain["installed_root"]
                                / relative
                            ).resolve()
                        )
                        for relative in self.toolchain["compiler_relatives"]
                    ],
                )
            )
            if role == "application":
                opaque = role_root / "libfixture_opaque.a"
                shutil.copyfile(opaque_reviewed, opaque)
                inputs.append(
                    self._observed_input(
                        identifier="opaque--%s" % profile_id,
                        profile_id=profile_id,
                        role=role,
                        kind="opaque-archive",
                        path=opaque,
                        reviewed_source_path=("firmware/prebuilt/libfixture_opaque.a"),
                    )
                )
                neo_id = "neopixel--%s" % profile_id
                inputs.append(
                    {
                        "id": neo_id,
                        "profile_id": profile_id,
                        "role": role,
                        "kind": "frozen-source-tree",
                        "observed_path": str(self.neopixel_tree.resolve()),
                        "sha256": sha256_tree(self.neopixel_tree),
                        "frozen_destinations": ["neopixel.py"],
                    }
                )
                for component, member in (
                    ("mbedcrypto", "aes.o"),
                    ("mbedtls", "ssl_tls.o"),
                    ("mbedx509", "x509.o"),
                ):
                    archive = role_root / ("lib%s.a" % component)
                    archive.write_bytes(
                        BASE.make_ar_bytes(
                            [
                                (
                                    member,
                                    ("synthetic %s object\n" % component).encode(),
                                )
                            ]
                        )
                    )
                    source = self.mbedtls_tree / component / ("%s.c" % component)
                    inputs.append(
                        self._observed_input(
                            identifier="%s--%s" % (component, profile_id),
                            profile_id=profile_id,
                            role=role,
                            kind="generated-supplemental-archive",
                            path=archive,
                            generated_binding={
                                "component": component,
                                "project_description_sha256": sha256_bytes(
                                    (
                                        "description/%s/%s"
                                        % (profile_id, role)
                                    ).encode()
                                ),
                                "compile_commands_sha256": sha256_bytes(
                                    (
                                        "compile/%s/%s" % (profile_id, role)
                                    ).encode()
                                ),
                                "linker_map_sha256": sha256_bytes(
                                    (
                                        "map/%s/%s" % (profile_id, role)
                                    ).encode()
                                ),
                                "sources": [
                                    {
                                        "path": source.relative_to(
                                            self.repo
                                        ).as_posix(),
                                        "sha256": BASE.sha256_path(source),
                                    }
                                ],
                                "members": [member],
                            },
                        )
                    )
        return sorted(inputs, key=lambda item: item["id"])

    def _review_files(self, expression: str) -> list[dict]:
        records = {
            "MIT": (("MIT", "MIT.txt"),),
            "Apache-2.0": (("Apache-2.0", "Apache-2.0.txt"),),
            "GPL-3.0-or-later WITH GCC-exception-3.1": (
                ("GPL-3.0-or-later", "GPL-3.0-or-later.txt"),
                ("GCC-exception-3.1", "GCC-exception-3.1.txt"),
            ),
        }[expression]
        return [
            {
                "spdx_id": spdx_id,
                "path": "firmware/licenses/texts/%s" % name,
                "sha256": BASE.sha256_path(self.texts / name),
            }
            for spdx_id, name in records
        ]

    def _notice(self, name: str) -> dict:
        path = self.notices / name
        return {
            "required": True,
            "path": "firmware/licenses/notices/%s" % name,
            "sha256": BASE.sha256_path(path),
        }

    @staticmethod
    def _immutable_dependency(identifier: str) -> tuple[dict, dict]:
        commit = {
            "core": "1",
            "runtime": "2",
            "opaque": "3",
            "neopixel": "4",
            "mbedtls": "5",
        }[identifier] * 40
        dependency = {
            "name": "Fixture %s" % identifier,
            "version_ref": "fixture-%s@%s" % (identifier, commit),
            "source_url": (
                "https://example.invalid/%s/commit/%s" % (identifier, commit)
            ),
            "copyright": "Copyright 2099 synthetic fixture authors",
        }
        source = {
            "ref": dependency["version_ref"],
            "url": dependency["source_url"],
        }
        return dependency, source

    def _reviewed_package(self, identifier: str, expression: str) -> dict:
        dependency, source = self._immutable_dependency(identifier)
        return {
            "id": identifier,
            "dependency": dependency,
            "source": source,
            "reviewed_raw_package_expression": expression,
            "license_texts": self._review_files(expression),
            "notice": self._notice(
                "runtime.txt" if identifier == "runtime" else "source.txt"
            ),
        }

    def _policy_input(self, observation: dict) -> dict:
        owners = {
            "core": "core",
            "runtime": "runtime",
            "opaque": "opaque",
            "neopixel": "supplemental-neopixel",
            "mbedcrypto": "supplemental-mbedtls",
            "mbedtls": "supplemental-mbedtls",
            "mbedx509": "supplemental-mbedtls",
        }
        common = {
            key: observation[key]
            for key in ("id", "profile_id", "role", "kind")
        }
        common["reviewed_package_id"] = owners[observation["id"].split("--", 1)[0]]
        if observation["kind"].startswith("generated-"):
            return {
                **common,
                "generated_matcher": {
                    "component": observation["generated_binding"]["component"],
                },
            }
        if observation["kind"] == "opaque-archive":
            return {
                **common,
                "reviewed_source_path": observation["reviewed_source_path"],
                "sha256": observation["sha256"],
            }
        if observation["kind"] == "toolchain-archive":
            return {
                **common,
                "toolchain_id": observation["toolchain_id"],
                "relative_path": observation["relative_path"],
                "sha256": observation["sha256"],
            }
        if observation["kind"] == "frozen-source-tree":
            return {
                **common,
                "path": self.neopixel_tree.relative_to(self.repo).as_posix(),
                "sha256": observation["sha256"],
                "frozen_destinations": observation["frozen_destinations"],
            }
        raise AssertionError("unhandled observed input")

    def _raw_policy_documents(self) -> list[dict]:
        return [
            {
                "profile_id": profile_id,
                "role": role,
                "packages": copy.deepcopy(document["packages"]),
                "relationships": copy.deepcopy(document["relationships"]),
            }
            for (profile_id, role), document in sorted(self.observed_documents.items())
        ]

    def _resolution(
        self,
        identifier: str,
        *,
        expression: str,
        roles: set[str],
    ) -> dict:
        package_refs = [
            {
                "profile_id": profile_id,
                "role": role,
                "spdx_id": package_id(identifier),
            }
            for profile_id, role in PROFILE_ROLES
            if role in roles
        ]
        prefix = identifier + "--"
        input_refs = [
            item["id"] for item in self.observed_inputs if item["id"].startswith(prefix)
        ]
        return {
            "id": "resolve-%s" % identifier,
            "reviewed_package_id": identifier,
            "package_refs": package_refs,
            "input_refs": sorted(input_refs),
            "resolved_input_expression": expression,
            "disposition": "allow",
            "attribution": "Resolved by reviewed package %s." % identifier,
        }

    def _supplemental(
        self,
        identifier: str,
        *,
        expression: str,
        input_prefixes: tuple[str, ...],
        related: str,
    ) -> dict:
        dependency, source = self._immutable_dependency(identifier)
        if identifier == "mbedtls":
            source.update(
                {
                    "tree_path": self.mbedtls_tree.relative_to(self.repo).as_posix(),
                    "tree_sha256": sha256_tree(self.mbedtls_tree),
                }
            )
        elif identifier == "neopixel":
            source.update(
                {
                    "tree_path": self.neopixel_tree.relative_to(self.repo).as_posix(),
                    "tree_sha256": sha256_tree(self.neopixel_tree),
                }
            )
        return {
            "id": "supplemental-%s" % identifier,
            "dependency": dependency,
            "source": source,
            "source_spdx_expression": expression,
            "selected_spdx_expression": expression,
            "input_refs": sorted(
                item["id"]
                for item in self.observed_inputs
                if item["id"].startswith(input_prefixes)
            ),
            "relationship": {
                "relationship_type": "DEPENDS_ON",
                "related_reviewed_package_id": related,
            },
            "license_texts": self._review_files(expression),
            "notice": self._notice("source.txt"),
            "disposition": "allow",
        }

    def _make_policy(self) -> dict:
        distribution = self.toolchain["distribution"]
        review_file = self.notices / "source.txt"
        policy = {
            "schema_version": 2,
            "approved_license_refs": [],
            "review_files": [
                {
                    "id": "fixture-source-attribution",
                    "purpose": "Synthetic upstream attribution evidence.",
                    "path": review_file.relative_to(self.repo).as_posix(),
                    "sha256": BASE.sha256_path(review_file),
                    "source_identities": [
                        "a" * 40,
                        BASE.sha256_path(review_file),
                    ],
                }
            ],
            "raw_documents": self._raw_policy_documents(),
            "reviewed_packages": [
                self._reviewed_package("core", "MIT"),
                self._reviewed_package(
                    "runtime",
                    "GPL-3.0-or-later WITH GCC-exception-3.1",
                ),
                self._reviewed_package("opaque", "Apache-2.0"),
            ],
            "resolved_inputs": [
                self._policy_input(item) for item in self.observed_inputs
            ],
            "resolutions": [
                self._resolution(
                    "core",
                    expression="MIT",
                    roles={"application", "bootloader"},
                ),
                self._resolution(
                    "runtime",
                    expression=("GPL-3.0-or-later WITH GCC-exception-3.1"),
                    roles={"application", "bootloader"},
                ),
                self._resolution(
                    "opaque",
                    expression="Apache-2.0",
                    roles={"application"},
                ),
            ],
            "supplemental_packages": [
                self._supplemental(
                    "neopixel",
                    expression="MIT",
                    input_prefixes=("neopixel--",),
                    related="core",
                ),
                self._supplemental(
                    "mbedtls",
                    expression="Apache-2.0",
                    input_prefixes=("mbedcrypto--", "mbedtls--", "mbedx509--"),
                    related="core",
                ),
            ],
            "toolchains": [
                {
                    "id": self.toolchain["id"],
                    "name": self.toolchain["name"],
                    "version": self.toolchain["version"],
                    "platform": self.toolchain["platform"],
                    "install_root_relative": self.toolchain[
                        "install_root_relative"
                    ],
                    "compiler_frontends": [
                        {
                            "relative_path": relative,
                            "sha256": sha256_bytes(
                                self.toolchain["files"][relative]
                            ),
                        }
                        for relative in self.toolchain["compiler_relatives"]
                    ],
                    "metadata": {
                        "path": self.toolchain["metadata"]
                        .relative_to(self.repo)
                        .as_posix(),
                        "sha256": BASE.sha256_path(self.toolchain["metadata"]),
                    },
                    "distribution": {
                        "url": self.toolchain["distribution_url"],
                        "filename": distribution.name,
                        "size": distribution.stat().st_size,
                        "sha256": BASE.sha256_path(distribution),
                        "archive_format": "tar.xz",
                        "archive_root": self.toolchain["root_name"],
                    },
                    "admitted_archive_paths": [self.toolchain["runtime_relative"]],
                }
            ],
        }
        self.refresh_shipment_review(policy)
        return policy

    def refresh_shipment_review(self, policy: dict) -> None:
        """Write the independent canonical shipment ledger for a fixture policy."""

        dispositions = {}
        for resolution in policy["resolutions"]:
            for package_ref in resolution["package_refs"]:
                identity = (
                    package_ref["profile_id"],
                    package_ref["role"],
                    package_ref["spdx_id"],
                )
                if identity in dispositions:
                    raise AssertionError("duplicate fixture shipment occurrence")
                dispositions[identity] = resolution["disposition"]
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
        path = self.licenses / "evidence" / "shipment-review.json"
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

    @contextmanager
    def changed_policy(self, mutation):
        before = copy.deepcopy(self.policy)
        try:
            mutation(self.policy)
            yield
        finally:
            self.policy = before

    def observed_input(self, identifier: str) -> dict:
        return next(item for item in self.observed_inputs if item["id"] == identifier)

    def policy_input(self, identifier: str) -> dict:
        return next(
            item for item in self.policy["resolved_inputs"] if item["id"] == identifier
        )

    def toolchain_context(self) -> dict[str, dict[str, str]]:
        root = self.toolchain["installed_root"].resolve()
        tools_home = self.toolchain["tools_home"].resolve()
        distribution = self.toolchain["distribution"].resolve()
        return {
            self.toolchain["id"]: {
                "root": str(root),
                "trusted_anchor": str(tools_home),
                "root_relative": self.toolchain["install_root_relative"],
                "distribution_cache_path": str(distribution),
                "distribution_cache_relative": (
                    "dist/%s" % distribution.name
                ),
            }
        }

    @contextmanager
    def sibling_toolchain_root(self):
        original = self.toolchain["installed_root"]
        sibling = original.parent / (self.toolchain["root_name"] + "-sibling")
        shutil.copytree(original, sibling)
        try:
            yield sibling
        finally:
            shutil.rmtree(sibling)


@unittest.skipUnless(
    RELEASE is not None,
    "schema-v2 RED behavior waits for release_bundle.py",
)
class PolicyV2FailClosedTests(unittest.TestCase):
    def setUp(self):
        self.fixture = PolicyV2Fixture()

    def tearDown(self):
        self.fixture.close()

    def validate(self, **overrides):
        self.assertTrue(
            callable(VALIDATE_V2),
            "release_bundle.py lacks _audit_validate_policy_v2",
        )
        arguments = {
            "repo_root": self.fixture.repo,
            "observed_documents": self.fixture.observed_documents,
            "observed_inputs": self.fixture.observed_inputs,
            "manifest_evidence": self.fixture.manifest_evidence,
            "toolchain_roots": self.fixture.toolchain_context(),
        }
        arguments.update(overrides)
        return VALIDATE_V2(self.fixture.policy, **arguments)

    def assert_rejected(self, **overrides):
        with self.assertRaises(RELEASE.ReleaseError):
            self.validate(**overrides)

    def test_schema_v1_is_rejected_instead_of_silently_reinterpreted(self):
        self.assertTrue(callable(getattr(RELEASE, "_audit_load_policy", None)))
        legacy = BASE.ReleaseLicenseFixture()
        try:
            lock = RELEASE._audit_load_tool_lock(legacy.repo)
            with self.assertRaises(RELEASE.ReleaseError):
                RELEASE._audit_load_policy(legacy.repo, lock)
        finally:
            legacy.close()

        schema_v1 = copy.deepcopy(self.fixture.policy)
        schema_v1["schema_version"] = 1
        with self.fixture.changed_policy(lambda policy: policy.update(schema_v1)):
            self.assert_rejected()

    def test_policy_schema_version_requires_the_exact_integer_two(self):
        self.validate()
        for invalid in (True, 2.0):
            with self.subTest(schema_version=repr(invalid)):
                with self.fixture.changed_policy(
                    lambda policy, invalid=invalid: policy.update(
                        {"schema_version": invalid}
                    )
                ):
                    with self.assertRaisesRegex(
                        RELEASE.ReleaseError,
                        r"policy schema_version",
                    ):
                        self.validate()

    def test_shipment_ledger_schema_version_requires_the_exact_integer_one(self):
        self.validate()
        reference = self.fixture.policy["shipment_review"]
        path = self.fixture.repo / reference["path"]
        original = json.loads(path.read_text(encoding="utf-8"))
        for invalid in (True, 1.0):
            with self.subTest(schema_version=repr(invalid)):
                changed = copy.deepcopy(original)
                changed["schema_version"] = invalid
                source = (
                    json.dumps(
                        changed,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
                    + "\n"
                ).encode("utf-8")
                with BASE.patched_bytes(path, source):
                    with self.fixture.changed_policy(
                        lambda policy, source=source: policy[
                            "shipment_review"
                        ].update({"sha256": sha256_bytes(source)})
                    ):
                        with self.assertRaisesRegex(
                            RELEASE.ReleaseError,
                            r"shipment review ledger schema_version",
                        ):
                            self.validate()

    def test_release_tool_lock_schema_version_requires_the_exact_integer_one(self):
        legacy = BASE.ReleaseLicenseFixture()
        try:
            original = legacy.lock_path.read_bytes()
            marker = b"schema_version = 1"
            self.assertIn(marker, original)
            for invalid in (b"true", b"1.0"):
                with self.subTest(schema_version=invalid.decode("ascii")):
                    changed = original.replace(
                        marker,
                        b"schema_version = " + invalid,
                        1,
                    )
                    with BASE.patched_bytes(legacy.lock_path, changed):
                        with self.assertRaisesRegex(
                            RELEASE.ReleaseError,
                            r"release-tools\.lock schema version",
                        ):
                            RELEASE._audit_load_tool_lock(legacy.repo)
        finally:
            legacy.close()

    def test_audit_receipt_schema_version_requires_the_exact_integer_one(self):
        self.assertTrue(
            callable(VERIFY_EVIDENCE),
            "release_bundle.py lacks _audit_verify_release_evidence",
        )
        evidence = self.fixture.root / "receipt-evidence"
        evidence.mkdir()
        receipt_path = evidence / "audit-receipt.json"
        for invalid in (True, 1.0):
            with self.subTest(schema_version=repr(invalid)):
                receipt = {
                    "schema_version": invalid,
                    "notice_sha256": sha256_bytes(b""),
                    "input_sha256": {},
                    "executed_artifacts": {},
                    "execution_identity": {},
                    "identities": {},
                    "evidence_sha256": {},
                }
                receipt_path.write_text(
                    json.dumps(receipt, indent=2, sort_keys=False) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    RELEASE.ReleaseError,
                    r"license audit receipt version",
                ):
                    VERIFY_EVIDENCE(
                        notice="",
                        evidence_dir=evidence,
                        build_root=self.fixture.build,
                        repo_root=self.fixture.repo,
                    )

    def test_exact_raw_package_properties_and_relationship_multisets(self):
        self.validate()
        identity = PROFILE_ROLES[0]
        policy_document = next(
            item
            for item in self.fixture.policy["raw_documents"]
            if (item["profile_id"], item["role"]) == identity
        )
        selected_id = policy_document["packages"][0]["SPDXID"]
        mutations = {
            "name": lambda value: value + " changed",
            "SPDXID": lambda value: value + "-changed",
            "versionInfo": lambda value: value + "-changed",
            "downloadLocation": lambda _value: "NONE",
            "filesAnalyzed": lambda value: not value,
            "licenseConcluded": lambda _value: "Apache-2.0",
            "licenseDeclared": lambda _value: "MIT",
            "copyrightText": lambda _value: "Copyright changed",
            "checksums": lambda value: value
            + [{"algorithm": "SHA1", "checksumValue": "0" * 40}],
            "externalRefs": lambda value: value
            + [
                {
                    "referenceCategory": "OTHER",
                    "referenceType": "other",
                    "referenceLocator": "changed",
                }
            ],
            "comment": lambda value: value + " changed",
            "summary": lambda value: value + " changed",
            "supplier": lambda _value: "Organization: Changed",
            "originator": lambda _value: "Person: Changed",
        }
        for field, mutate in mutations.items():
            with self.subTest(raw_field=field):

                def change(policy, field=field, mutate=mutate):
                    document = next(
                        item
                        for item in policy["raw_documents"]
                        if (item["profile_id"], item["role"]) == identity
                    )
                    package = next(
                        item
                        for item in document["packages"]
                        if item["SPDXID"] == selected_id
                    )
                    package[field] = mutate(package[field])

                with self.fixture.changed_policy(change):
                    self.assert_rejected()

        relationship_mutations = {
            "missing": lambda values: values.pop(),
            "duplicate": lambda values: values.append(copy.deepcopy(values[0])),
            "changed": lambda values: values[0].update(
                {"relationshipType": "CONTAINS"}
            ),
        }
        for label, mutation in relationship_mutations.items():
            with self.subTest(relationship=label):

                def change(policy, mutation=mutation):
                    document = next(
                        item
                        for item in policy["raw_documents"]
                        if (item["profile_id"], item["role"]) == identity
                    )
                    mutation(document["relationships"])

                with self.fixture.changed_policy(change):
                    self.assert_rejected()

    def test_many_to_many_resolution_consumes_each_observation_once(self):
        self.validate()
        core = next(
            item
            for item in self.fixture.policy["resolutions"]
            if item["id"] == "resolve-core"
        )
        self.assertEqual(len(core["package_refs"]), len(PROFILE_ROLES))
        self.assertEqual(len(core["input_refs"]), len(PROFILE_ROLES))

        def core_resolution(policy):
            return next(
                item for item in policy["resolutions"] if item["id"] == "resolve-core"
            )

        mutations = {
            "missing-package": lambda record: record["package_refs"].pop(),
            "duplicate-package": lambda record: record["package_refs"].append(
                copy.deepcopy(record["package_refs"][0])
            ),
            "missing-input": lambda record: record["input_refs"].pop(),
            "duplicate-input": lambda record: record["input_refs"].append(
                record["input_refs"][0]
            ),
        }
        for label, mutation in mutations.items():
            with self.subTest(coverage=label):

                def change(policy, mutation=mutation):
                    mutation(core_resolution(policy))

                with self.fixture.changed_policy(change):
                    self.assert_rejected()

        def duplicate_resolution(policy):
            duplicate = copy.deepcopy(core_resolution(policy))
            duplicate["id"] = "resolve-core-again"
            policy["resolutions"].append(duplicate)

        with self.fixture.changed_policy(duplicate_resolution):
            self.assert_rejected()

    def test_raw_reviewed_and_redistributed_expressions_are_separate(self):
        self.validate()
        raw = self.fixture.observed_documents[PROFILE_ROLES[0]]["packages"][0]
        reviewed = next(
            item
            for item in self.fixture.policy["reviewed_packages"]
            if item["id"] == "core"
        )
        resolution = next(
            item
            for item in self.fixture.policy["resolutions"]
            if item["id"] == "resolve-core"
        )
        self.assertEqual(raw["licenseDeclared"], "NOASSERTION")
        self.assertEqual(raw["licenseConcluded"], "MIT")
        self.assertEqual(reviewed["reviewed_raw_package_expression"], "MIT")
        self.assertEqual(resolution["resolved_input_expression"], "MIT")

        def contradict_concrete_raw(policy):
            package = next(
                item for item in policy["reviewed_packages"] if item["id"] == "core"
            )
            package["reviewed_raw_package_expression"] = "Apache-2.0"

        with self.fixture.changed_policy(contradict_concrete_raw):
            self.assert_rejected()

        def unresolved_input_expression(policy):
            resolution = next(
                item for item in policy["resolutions"] if item["id"] == "resolve-core"
            )
            resolution["resolved_input_expression"] = "NOASSERTION"

        with self.fixture.changed_policy(unresolved_input_expression):
            self.assert_rejected()

    def test_license_text_catalog_exactly_covers_expression_identifiers(self):
        def identifier_for(record):
            return {
                "MIT.txt": "MIT",
                "Apache-2.0.txt": "Apache-2.0",
                "GPL-3.0-or-later.txt": "GPL-3.0-or-later",
                "GCC-exception-3.1.txt": "GCC-exception-3.1",
            }[Path(record["path"]).name]

        def identify_every_text(policy):
            for collection in ("reviewed_packages", "supplemental_packages"):
                for package in policy[collection]:
                    for record in package["license_texts"]:
                        record["spdx_id"] = identifier_for(record)

        with self.fixture.changed_policy(identify_every_text):
            self.validate()

            core = next(
                item
                for item in self.fixture.policy["reviewed_packages"]
                if item["id"] == "core"
            )
            core["license_texts"][0]["spdx_id"] = "Apache-2.0"
            self.assert_rejected()

        def omit_exception(policy):
            identify_every_text(policy)
            runtime = next(
                item
                for item in policy["reviewed_packages"]
                if item["id"] == "runtime"
            )
            runtime["license_texts"] = [
                record
                for record in runtime["license_texts"]
                if record["spdx_id"] != "GCC-exception-3.1"
            ]

        with self.fixture.changed_policy(omit_exception):
            self.assert_rejected()

        def add_unreferenced_text(policy):
            identify_every_text(policy)
            core = next(
                item
                for item in policy["reviewed_packages"]
                if item["id"] == "core"
            )
            apache = next(
                item
                for item in policy["reviewed_packages"]
                if item["id"] == "opaque"
            )
            core["license_texts"].append(copy.deepcopy(apache["license_texts"][0]))

        with self.fixture.changed_policy(add_unreferenced_text):
            self.assert_rejected()

    def test_neopixel_and_three_linked_mbedtls_archives_are_supplemental(self):
        self.validate()
        raw_text = json.dumps(
            list(self.fixture.observed_documents.values()),
            sort_keys=True,
        )
        self.assertNotIn("neopixel", raw_text.lower())
        self.assertNotIn("mbedtls", raw_text.lower())
        supplementals = {
            item["id"]: item for item in self.fixture.policy["supplemental_packages"]
        }
        self.assertEqual(
            len(supplementals["supplemental-neopixel"]["input_refs"]),
            len(BASE.PROFILE_TARGETS),
        )
        self.assertEqual(
            len(supplementals["supplemental-mbedtls"]["input_refs"]),
            3 * len(BASE.PROFILE_TARGETS),
        )

        for identifier in ("supplemental-neopixel", "supplemental-mbedtls"):
            with self.subTest(missing=identifier):

                def remove(policy, identifier=identifier):
                    policy["supplemental_packages"] = [
                        item
                        for item in policy["supplemental_packages"]
                        if item["id"] != identifier
                    ]

                with self.fixture.changed_policy(remove):
                    self.assert_rejected()

        def omit_one_mbed_archive(policy):
            package = next(
                item
                for item in policy["supplemental_packages"]
                if item["id"] == "supplemental-mbedtls"
            )
            package["input_refs"].pop()

        with self.fixture.changed_policy(omit_one_mbed_archive):
            self.assert_rejected()

        def wrong_relationship(policy):
            package = next(
                item
                for item in policy["supplemental_packages"]
                if item["id"] == "supplemental-mbedtls"
            )
            package["relationship"]["related_reviewed_package_id"] = "runtime"

        with self.fixture.changed_policy(wrong_relationship):
            self.assert_rejected()

        neo_source = self.fixture.neopixel_tree / "neopixel.py"
        with BASE.patched_bytes(
            neo_source,
            neo_source.read_bytes() + b"# changed\n",
        ):
            changed_inputs = copy.deepcopy(self.fixture.observed_inputs)
            observed = next(
                item for item in changed_inputs if item["id"].startswith("neopixel--")
            )
            observed["sha256"] = sha256_tree(self.fixture.neopixel_tree)
            self.assert_rejected(observed_inputs=changed_inputs)

        mbed_source = self.fixture.mbedtls_tree / "mbedtls" / "mbedtls.c"
        with BASE.patched_bytes(
            mbed_source,
            mbed_source.read_bytes() + b"// changed\n",
        ):
            changed_inputs = copy.deepcopy(self.fixture.observed_inputs)
            for item in changed_inputs:
                if item["id"].startswith("mbedtls--"):
                    item["generated_binding"]["sources"][0]["sha256"] = (
                        BASE.sha256_path(mbed_source)
                    )
            self.assert_rejected(observed_inputs=changed_inputs)

    def test_generated_archives_are_receipt_bound_and_opaque_inputs_are_pinned(self):
        result = self.validate()
        generated_id = "core--esp32-4mb--application"
        generated_policy = self.fixture.policy_input(generated_id)
        self.assertNotIn("sha256", generated_policy)
        self.assertEqual(
            generated_policy["generated_matcher"],
            {"component": "core"},
        )
        self.assertNotIn(
            "project_description_sha256",
            json.dumps(generated_policy, sort_keys=True),
        )
        opaque_id = "opaque--esp32-4mb"
        opaque_policy = self.fixture.policy_input(opaque_id)
        self.assertRegex(opaque_policy["sha256"], r"^[0-9a-f]{64}$")
        generated_observed = self.fixture.observed_input(generated_id)
        self.assertIn(generated_observed["sha256"], set(deep_scalars(result)))

        generated_path = Path(generated_observed["observed_path"])
        changed = BASE.make_ar_bytes([("core.o", b"changed valid generated object\n")])
        with BASE.patched_bytes(generated_path, changed):
            observed_inputs = copy.deepcopy(self.fixture.observed_inputs)
            next(item for item in observed_inputs if item["id"] == generated_id)[
                "sha256"
            ] = sha256_bytes(changed)
            changed_result = self.validate(observed_inputs=observed_inputs)
            self.assertIn(sha256_bytes(changed), set(deep_scalars(changed_result)))

        def pin_generated_digest(policy):
            next(
                item for item in policy["resolved_inputs"] if item["id"] == generated_id
            )["sha256"] = generated_observed["sha256"]

        with self.fixture.changed_policy(pin_generated_digest):
            self.assert_rejected()

        def remove_generated_matcher_component(policy):
            next(
                item for item in policy["resolved_inputs"] if item["id"] == generated_id
            )["generated_matcher"].pop("component")

        with self.fixture.changed_policy(remove_generated_matcher_component):
            self.assert_rejected()

        opaque_observed = self.fixture.observed_input(opaque_id)
        opaque_path = Path(opaque_observed["observed_path"])
        tampered = BASE.make_ar_bytes([("opaque.o", b"tampered opaque object\n")])
        with BASE.patched_bytes(opaque_path, tampered):
            observed_inputs = copy.deepcopy(self.fixture.observed_inputs)
            next(item for item in observed_inputs if item["id"] == opaque_id)[
                "sha256"
            ] = sha256_bytes(tampered)
            self.assert_rejected(observed_inputs=observed_inputs)

        def remove_opaque_digest(policy):
            next(
                item for item in policy["resolved_inputs"] if item["id"] == opaque_id
            ).pop("sha256")

        with self.fixture.changed_policy(remove_opaque_digest):
            self.assert_rejected()

    def test_toolchain_root_distribution_bytes_and_symlinks_fail_closed(self):
        self.validate()
        toolchain = self.fixture.toolchain
        runtime = toolchain["installed_root"] / toolchain["runtime_relative"]
        outside = self.fixture.root / "outside-libgcc.a"
        outside.write_bytes(runtime.read_bytes())
        with BASE.symlink_instead(runtime, outside):
            self.assert_rejected()

        tampered_runtime = BASE.make_ar_bytes(
            [("_divsi3.o", b"tampered installed runtime\n")]
        )
        with BASE.patched_bytes(runtime, tampered_runtime):
            changed_inputs = copy.deepcopy(self.fixture.observed_inputs)
            for item in changed_inputs:
                if item["kind"] == "toolchain-archive":
                    item["sha256"] = sha256_bytes(tampered_runtime)
            self.assert_rejected(observed_inputs=changed_inputs)

        distribution = toolchain["distribution"]
        with BASE.patched_bytes(
            distribution,
            distribution.read_bytes() + b"tampered",
        ):
            self.assert_rejected()

        unsafe = toolchain_tar_bytes(
            root_name=toolchain["root_name"],
            files=toolchain["files"],
            unsafe_symlink=True,
        )
        with BASE.patched_bytes(distribution, unsafe):

            def approve_changed_bytes(policy):
                record = policy["toolchains"][0]["distribution"]
                record["size"] = len(unsafe)
                record["sha256"] = sha256_bytes(unsafe)

            with self.fixture.changed_policy(approve_changed_bytes):
                self.assert_rejected()

        with self.fixture.sibling_toolchain_root() as sibling:
            self.assert_rejected(toolchain_roots={toolchain["id"]: sibling})

        def caller_selected_root(policy):
            policy["toolchains"][0]["install_root_relative"] = (
                "tools/xtensa-esp-elf/caller-selected/"
                + toolchain["root_name"]
            )

        with self.fixture.changed_policy(caller_selected_root):
            self.assert_rejected()


if __name__ == "__main__":
    unittest.main()
