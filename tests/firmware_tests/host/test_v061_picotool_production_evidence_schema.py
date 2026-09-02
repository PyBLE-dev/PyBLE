#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contract for the checked-in v0.6.1 picotool evidence schema.

This suite is deliberately offline.  It distinguishes the reviewed production
documents from the older compact synthetic fixture: production admission must
bind the complete canonical policy, attribution manifest, and every referenced
license/provenance byte.
"""

from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import tomllib
import unittest

import test_release_v060_license_generation as generation_fixture
import test_v061_picotool_license_admission as compact_fixture


RELEASE = generation_fixture.RELEASE
RELEASE_LOAD_ERROR = generation_fixture.RELEASE_LOAD_ERROR
REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_RELATIVE = Path(
    "firmware/licenses/rp2-build-tools-license-policy.json"
)
ATTRIBUTION_RELATIVE = Path(
    "firmware/licenses/evidence/rp2/picotool/2.3.0/"
    "distribution-attribution-v1.json"
)
POLICY_SHA256 = (
    "d0b5920297c78280d509b93cc0ab356839e8b2adfacaab42f352150390b645e9"
)
ATTRIBUTION_SHA256 = (
    "9d96bdff715a08582506220d3ba1e332cc3b86dd9eaa13e7d7169856734a6e88"
)
COMPACT_COMPONENTS = [
    {"name": "CMake package scripts", "license": "CMake-package-script-grant"},
    {"name": "Mbed TLS", "license": "Apache-2.0"},
    {"name": "Pico SDK", "license": "BSD-3-Clause"},
    {"name": "clipp", "license": "MIT"},
    {"name": "littlefs", "license": "BSD-3-Clause"},
    {"name": "nlohmann JSON", "license": "MIT"},
    {"name": "ooFatFs R0.13c", "license": "LicenseRef-ooFatFs-R0.13c"},
    {"name": "picotool", "license": "BSD-3-Clause"},
    {"name": "whereami", "license": "MIT"},
]

# This is the complete repository-file closure referenced by the production
# policy and its nested attribution document.  Archive/install-tree identities
# are a separate build observation and intentionally do not appear here.
EXPECTED_REVIEWED_INPUTS = {
    "repo/firmware/licenses/evidence/mbedtls-LICENSE.txt": (
        "9b405ef4c89342f5eae1dd828882f931747f71001cfba7d114801039b52ad09b"
    ),
    "repo/firmware/licenses/evidence/rp2/picotool/2.3.0/clipp-LICENSE": (
        "72c5d1a6f8c76c88b4559d26710c3a298a0ba9822ab3d187d0b4a5b2e8e2b219"
    ),
    (
        "repo/firmware/licenses/evidence/rp2/picotool/2.3.0/"
        "cmake-copying-cmake-scripts"
    ): "8c33ed647ccfaa4e682ffe56b677f4d5d0dc51e2ccc40038015df784c7be51dd",
    (
        "repo/firmware/licenses/evidence/rp2/picotool/2.3.0/"
        "distribution-attribution-v1.json"
    ): ATTRIBUTION_SHA256,
    (
        "repo/firmware/licenses/evidence/rp2/picotool/2.3.0/"
        "homebrew-libusb.rb"
    ): "5da3b9c199276c00cd14ef7da6a10e4dc7fd8b65eaa638ab356a049597491d74",
    "repo/firmware/licenses/evidence/rp2/picotool/2.3.0/libusb-AUTHORS": (
        "27fd82b016838197d5276ba98d2187ed5a1ad0e171767322f356f0a9f6395941"
    ),
    "repo/firmware/licenses/evidence/rp2/picotool/2.3.0/libusb-COPYING": (
        "5df07007198989c622f5d41de8d703e7bef3d0e79d62e24332ee739a452af62a"
    ),
    "repo/firmware/licenses/evidence/rp2/picotool/2.3.0/libusb-README": (
        "1d3dc1c6be134b121b0697ad7190f8c20911d509f2dfef69f72484c95b8a2b87"
    ),
    "repo/firmware/licenses/evidence/rp2/picotool/2.3.0/libusb-version.h": (
        "8ef05de838404213f63f3a27a073aee0e2bc072dc4415734772e756d34def7f8"
    ),
    (
        "repo/firmware/licenses/evidence/rp2/picotool/2.3.0/"
        "libusb-version_nano.h"
    ): "243da8ad18f946e4ee896b296ac56834bf6b50c6211af1b62603483b60f58d50",
    "repo/firmware/licenses/evidence/rp2/picotool/2.3.0/littlefs-LICENSE.md": (
        "0cb4ff1daf5fdc1359c6a6ee3116092f08fc100c9d58b1b77ab17bfd801f856d"
    ),
    (
        "repo/firmware/licenses/evidence/rp2/picotool/2.3.0/"
        "nlohmann-json-LICENSE.MIT"
    ): "86b998c792894ccb911a1cb7994f7a9652894e7a094c0b5e45be2f553f45cf14",
    "repo/firmware/licenses/evidence/rp2/picotool/2.3.0/oofatfs-LICENSE": (
        "4449f912502843f47a0a258e740054f916a21586f849a27ce40f936c095e2f6c"
    ),
    "repo/firmware/licenses/evidence/rp2/picotool/2.3.0/picotool-LICENSE.TXT": (
        "483f865953435b66c443dee7558debe3cc3cf8fcbb6a112fd9fc6a795d53f1f6"
    ),
    "repo/firmware/licenses/evidence/rp2/picotool/2.3.0/whereami-LICENSE.MIT": (
        "3633afb48d2f5fb9a1942eead37adbe0ab6c70a79468c1b69e5a1e771ec4b119"
    ),
    (
        "repo/firmware/licenses/evidence/rp2/picotool/2.3.0/"
        "whereami-LICENSE.WTFPLv2"
    ): "8b3d9ef07a62cfaa0194bdd64fa1bb61bbc18e4a156a83f8a52d937bd945239b",
    "repo/firmware/licenses/rp2-build-tools-license-policy.json": POLICY_SHA256,
    "repo/firmware/licenses/texts/Apache-2.0.txt": (
        "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"
    ),
    "repo/firmware/licenses/texts/LGPL-2.1-or-later.txt": (
        "5df07007198989c622f5d41de8d703e7bef3d0e79d62e24332ee739a452af62a"
    ),
}


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_canonical(path: Path) -> tuple[bytes, object]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8", errors="strict"))
    if raw != canonical_json_bytes(value):
        raise AssertionError("%s is not canonical JSON" % path)
    return raw, value


def referenced_license_assets(*documents: object) -> dict[str, str]:
    """Collect exact checked-in license/provenance references recursively."""

    result: dict[str, str] = {}

    def walk(value: object) -> None:
        if isinstance(value, dict):
            path = value.get("path")
            digest = value.get("sha256")
            if (
                isinstance(path, str)
                and path.startswith("firmware/licenses/")
                and isinstance(digest, str)
            ):
                previous = result.setdefault("repo/" + path, digest)
                if previous != digest:
                    raise AssertionError(
                        "conflicting digests for reviewed asset %s" % path
                    )
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    for document in documents:
        walk(document)
    return dict(sorted(result.items()))


@unittest.skipUnless(RELEASE is not None, RELEASE_LOAD_ERROR)
class PicotoolProductionEvidenceSchemaTests(unittest.TestCase):
    def test_production_validator_rejects_compact_four_key_attribution(self):
        fixture = compact_fixture.PicotoolPolicyFixture()
        try:
            compact_attribution = {
                "schema_version": 1,
                "archive_sha256": compact_fixture.PICOTOOL_LOCK["sha256"],
                "components": copy.deepcopy(COMPACT_COMPONENTS),
                "packaging_provenance": {
                    "name": "pico-sdk-tools",
                    "license": "Apache-2.0",
                    "repo": compact_fixture.PICOTOOL_LOCK[
                        "distribution_repo"
                    ],
                    "ref": compact_fixture.PICOTOOL_LOCK["distribution_ref"],
                    "commit": compact_fixture.PICOTOOL_LOCK[
                        "distribution_commit"
                    ],
                    "ownership": "packaging-only",
                },
            }
            self.assertEqual(
                set(compact_attribution),
                {
                    "schema_version",
                    "archive_sha256",
                    "components",
                    "packaging_provenance",
                },
            )
            compact_fixture.write_json(fixture.attribution, compact_attribution)
            compact_digest = compact_fixture.sha256_path(fixture.attribution)
            policy = copy.deepcopy(fixture.policy)

            def rebind_attribution(value: object) -> None:
                if isinstance(value, dict):
                    if value.get("path") == compact_fixture.ATTRIBUTION_PATH:
                        value["sha256"] = compact_digest
                    for nested in value.values():
                        rebind_attribution(nested)
                elif isinstance(value, list):
                    for nested in value:
                        rebind_attribution(nested)

            rebind_attribution(policy)
            with self.assertRaises(
                RELEASE.ReleaseError,
                msg=(
                    "[red] production admitted the compact synthetic picotool "
                    "attribution without frozen production bytes"
                ),
            ):
                RELEASE._audit_validate_rp2_build_tools_license_policy(
                    policy,
                    repo_root=fixture.repo,
                    build_root=fixture.build,
                    picotool_lock=compact_fixture.PICOTOOL_LOCK,
                )
        finally:
            fixture.close()

    def test_checked_in_complete_evidence_is_offline_frozen_and_admitted(self):
        policy_path = REPO_ROOT / POLICY_RELATIVE
        attribution_path = REPO_ROOT / ATTRIBUTION_RELATIVE
        policy_raw, policy = load_canonical(policy_path)
        attribution_raw, attribution = load_canonical(attribution_path)

        self.assertEqual(sha256_bytes(policy_raw), POLICY_SHA256)
        self.assertEqual(sha256_bytes(attribution_raw), ATTRIBUTION_SHA256)
        self.assertEqual(RELEASE._PICOTOOL_V061_POLICY_SHA256, POLICY_SHA256)
        self.assertEqual(
            RELEASE._PICOTOOL_V061_ATTRIBUTION_SHA256,
            ATTRIBUTION_SHA256,
        )
        self.assertEqual(
            set(attribution),
            {
                "archive",
                "archive_members",
                "components",
                "distribution_provenance",
                "libusb_binary_provenance",
                "schema_version",
                "source",
            },
        )

        versions = tomllib.loads(
            (REPO_ROOT / "firmware/versions.lock").read_text(encoding="utf-8")
        )
        tool_lock = tomllib.loads(
            (REPO_ROOT / "firmware/release-tools.lock").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            tool_lock["inputs"]["rp2_build_tools_license_policy_path"],
            POLICY_RELATIVE.as_posix(),
        )
        self.assertEqual(
            tool_lock["inputs"]["rp2_build_tools_license_policy_sha256"],
            POLICY_SHA256,
        )

        with tempfile.TemporaryDirectory(
            prefix="pyble-v061-production-evidence-red-"
        ) as temporary:
            build_root = Path(temporary)
            validated = RELEASE._audit_validate_rp2_build_tools_license_policy(
                policy,
                repo_root=REPO_ROOT,
                build_root=build_root,
                picotool_lock=versions["picotool"],
            )
            loaded = RELEASE._audit_load_rp2_build_tools_license_policy(
                REPO_ROOT,
                build_root,
                tool_lock,
            )
            observed_inputs = RELEASE._audit_picotool_policy_input_hashes(
                policy=validated,
                repo_root=REPO_ROOT,
                build_root=build_root,
            )

        self.assertEqual(validated, policy)
        self.assertEqual(loaded, policy)
        self.assertEqual(observed_inputs, EXPECTED_REVIEWED_INPUTS)
        self.assertEqual(
            referenced_license_assets(policy, attribution),
            {
                key: digest
                for key, digest in EXPECTED_REVIEWED_INPUTS.items()
                if key
                != "repo/firmware/licenses/rp2-build-tools-license-policy.json"
            },
        )
        for logical_path, expected_digest in EXPECTED_REVIEWED_INPUTS.items():
            relative = logical_path.removeprefix("repo/")
            path = REPO_ROOT / relative
            mode = path.lstat().st_mode
            self.assertTrue(stat.S_ISREG(mode), logical_path)
            self.assertFalse(path.is_symlink(), logical_path)
            self.assertEqual(sha256_bytes(path.read_bytes()), expected_digest)

        members = policy["distribution_provenance"]["member_inventory"]
        self.assertEqual(attribution["archive_members"], members)
        software_members = sorted(
            member["path"]
            for member in members
            if member["kind"] == "regular" and member["path"] != ".keep"
        )
        owner_ids = [owner["id"] for owner in policy["source_owners"]]
        self.assertEqual(
            owner_ids,
            [
                "picotool-composite-build-tool",
                "picotool-libusb-build-tool",
            ],
        )
        roots = [
            root["path"]
            for owner in policy["source_owners"]
            for root in owner["source_roots"]
        ]
        self.assertEqual(sorted(roots), software_members)
        self.assertTrue(all(count == 1 for count in Counter(roots).values()))
        self.assertEqual(
            [
                root["path"]
                for root in policy["source_owners"][1]["source_roots"]
            ],
            [versions["picotool"]["bundled_libusb_path"]],
        )


if __name__ == "__main__":
    unittest.main()
