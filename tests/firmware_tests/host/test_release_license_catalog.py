#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] BLD-8 — Commit the complete, identifier-exact firmware license catalog.
#
# Frozen sources:
#   docs/specifications/firmware/browser-flashing.md §6 rules 4–9
#   docs/specifications/firmware/TDD.md §10.7
#
# These tests deliberately inspect only committed files below
# `firmware/licenses/`. They do not read an ignored ESP-IDF checkout, an
# installed compiler, a cached compiler distribution, or a prior build.

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
LICENSE_ROOT = REPO_ROOT / "firmware" / "licenses"
POLICY_PATH = LICENSE_ROOT / "license-policy.json"

BERKELEY_LICENSE_REF = (
    "LicenseRef-PyBLE-Berkeley-DB-1xx-Rescinded-Advertising"
)
NEWLIB_LICENSE_REF = "LicenseRef-PyBLE-Newlib-Multilicense"

# Toolchain files with a historical/common filename remain distinct evidence
# records. In particular, the ESP-IDF component compilation is not the larger
# newlib compilation shipped by the pinned GCC distributions.
PINNED_TEXT_FILES = {
    "firmware/licenses/texts/GPL-3.0-or-later.txt": (
        "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903"
    ),
    "firmware/licenses/texts/GCC-exception-3.1.txt": (
        "9d6b43ce4d8de0c878bf16b54d8e7a10d9bd42b75178153e3af6a815bdc90f74"
    ),
    "firmware/licenses/texts/COPYING.NEWLIB.esp-idf.txt": (
        "0681089a556e93791da82718d68011ba452de245f7f59c3846936304756ac0c0"
    ),
    "firmware/licenses/texts/COPYING.NEWLIB.toolchain.txt": (
        "422aa40293093fb54fc66e692a0d68fd0b24ed5602e5d1d33ad05ba3909057e9"
    ),
}

# Every raw, reviewed, resolved-input, or supplemental identifier/exception has
# one complete text record with an explicit `spdx_id`. The paths below freeze a
# deterministic committed layout without relying on an ignored source tree.
IDENTIFIER_TEXT_FILES = {
    "Apache-2.0": "firmware/licenses/texts/Apache-2.0.txt",
    "BSD-1-Clause": "firmware/licenses/texts/BSD-1-Clause.txt",
    "BSD-2-Clause": "firmware/licenses/texts/BSD-2-Clause.txt",
    "BSD-2-Clause-Views": "firmware/licenses/texts/BSD-2-Clause-Views.txt",
    "BSD-3-Clause": "firmware/licenses/texts/BSD-3-Clause.txt",
    "CC0-1.0": "firmware/licenses/texts/CC0-1.0.txt",
    "GCC-exception-3.1": (
        "firmware/licenses/texts/GCC-exception-3.1.txt"
    ),
    "GPL-2.0-or-later": "firmware/licenses/texts/GPL-2.0-or-later.txt",
    "GPL-3.0-or-later": "firmware/licenses/texts/GPL-3.0-or-later.txt",
    "ISC": "firmware/licenses/texts/ISC.txt",
    "LLVM-exception": "firmware/licenses/texts/LLVM-exception.txt",
    "MIT": "firmware/licenses/texts/MIT.txt",
    "Unlicense": "firmware/licenses/texts/Unlicense.txt",
    NEWLIB_LICENSE_REF: (
        "firmware/licenses/texts/COPYING.NEWLIB.toolchain.txt"
    ),
    BERKELEY_LICENSE_REF: (
        "firmware/licenses/texts/"
        "LicenseRef-PyBLE-Berkeley-DB-1xx-Rescinded-Advertising.txt"
    ),
}

# These are exact reviewed source artifacts. Public notice synthesis can
# deduplicate their contents, but the audit needs the exact committed bytes and
# policy binding. The NeoPixel record deliberately points to the pinned
# upstream source itself so PyBLE never carries a copied driver.
PINNED_EVIDENCE_FILES = {
    "firmware/licenses/evidence/nimble-NOTICE.txt": (
        "b838c4733a5020cd8e2bafbe70842acd8c8dc7816012965b77d10c1f4c0727f6"
    ),
    "firmware/licenses/evidence/esp-idf-COPYRIGHT.rst": (
        "461b6a126c59fce1ea9182f35b0e4f33b42654acd337d5b83996340e1ad2b581"
    ),
    "firmware/licenses/evidence/esp32-controller-README.rst": (
        "4a040fae88f8a6fb70dc563ef5636b9be8a767b8c0fe702bc7c8a7192a17ddd7"
    ),
    "firmware/licenses/evidence/esp32c3-family-controller-README.md": (
        "08a874b6747136b0f5b3443c660a1338c5d5ad50510aeb6f68e36b38ebc78ef2"
    ),
    "firmware/licenses/evidence/esp-coex-README.md": (
        "a4518406da8311ff23f796437bafe2d6f036863de3d0215d381d54980eaab5a2"
    ),
    "firmware/licenses/evidence/esp-phy-README.rst": (
        "ba87dc777ff15fdf6b10d7a31035fae20c9a30ff0ab3e64a6d9e8cb4aa889382"
    ),
    "firmware/licenses/evidence/esp-wifi-README.rst": (
        "022e8b5b4aef443c7284f09ad3b5f78db534b42c7d018bc19c274b8af01cf46e"
    ),
    (
        "firmware/upstream/micropython/lib/micropython-lib/"
        "micropython/drivers/led/neopixel/neopixel.py"
    ): (
        "c303d7b1723613b6ffa6d7ebda7cbf7b19eb6d29824f75f79693ca484498ffa7"
    ),
    "firmware/licenses/evidence/micropython-lib-LICENSE.txt": (
        "a38cf48836aa313254cdcf3de9fb7c24da4a2eab75ead2cc0cecd998336e7800"
    ),
    "firmware/licenses/evidence/mbedtls-LICENSE.txt": (
        "9b405ef4c89342f5eae1dd828882f931747f71001cfba7d114801039b52ad09b"
    ),
    "firmware/licenses/evidence/mbedtls-sbom.yml": (
        "743c872a2d6f9c14e3865d9ab9f2d91552b733f7b50fa9e0f480788d542c89d1"
    ),
    "firmware/licenses/evidence/lan867x-LICENSE.txt": (
        "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
    ),
    "firmware/licenses/evidence/tinyusb-LICENSE.txt": (
        "b171720e8a442e7a3957d83c62cd3299dbb29da3db534cc626f9dded0de2ca44"
    ),
}

# Source identity belongs in the committed reviewed catalog; an evidence file
# with the right bytes but an unrelated/unpinned source is insufficient.
REQUIRED_SOURCE_IDENTITIES = {
    "ESP-IDF": "fcae32885b0296b32044cb99ecbdc50d98dddb83",
    "MicroPython": "e0e9fbb17ed6fd06bb76e266ae554784c9c80804",
    "micropython-lib NeoPixel": (
        "8380c7bb8f9e5e5260e9539156742925e00366b2"
    ),
    "NeoPixel source tree": (
        "32c72fa231bb00f3d58029e4de80b08b53329f30f67c1d960a7bc19359193a28"
    ),
    "Mbed TLS": "b5d87eaa6748b7a6fa70593178c08b4480e9b71e",
    "LAN867x": "b5060aec053b13a67c4bf8369cc80f6797682219",
    "LAN867x component hash": (
        "0ff9dae3affeff53811e7c8283e67c6d36dc0c03e3bc5102c0fba629e08bf6c4"
    ),
    "TinyUSB managed fork": (
        "e4c0ec3caab3d9c25374de7047653b9ced8f14ff"
    ),
    "TinyUSB component hash": (
        "ee1c962cff61eb975d508258d509974d58031cc27ff0d6c4117a67a613a49594"
    ),
    "ESP32 controller": "185c7205db1f5082d070d00ea5dfdbb24c291d05",
    "ESP32-C3/S3 controller": (
        "0c68809d62e432427de97b5294f6619307f62f40"
    ),
    "ESP coexistence libraries": (
        "2d68674e3d522fb025e4666217f9cc1ca2af9399"
    ),
    "ESP PHY libraries": "45ce2703403784b4c3983a52e453988d61eb0e9d",
    "ESP Wi-Fi libraries": "c1f74dcf9151ae21b7a3850b90952796a2806358",
}


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def deep_mappings(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from deep_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from deep_mappings(child)


def deep_scalars(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from deep_scalars(child)
    elif isinstance(value, list):
        for child in value:
            yield from deep_scalars(child)
    elif isinstance(value, (str, int, float, bool)) or value is None:
        yield value


def policy_path_hash_pairs(policy: object) -> set[tuple[str, str]]:
    pairs = set()
    for record in deep_mappings(policy):
        path = record.get("path")
        digest = record.get("sha256")
        if isinstance(path, str) and isinstance(digest, str):
            pairs.add((path, digest))
    return pairs


def policy_license_text_records(policy: object) -> list[dict]:
    records = []
    for mapping in deep_mappings(policy):
        values = mapping.get("license_texts")
        if not isinstance(values, list):
            continue
        records.extend(record for record in values if isinstance(record, dict))
    return records


class ReleaseLicenseCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not POLICY_PATH.is_file():
            raise AssertionError(
                "missing committed firmware license policy: %s" % POLICY_PATH
            )
        cls.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    @staticmethod
    def _file_errors(
        expected: dict[str, str],
        *,
        require_policy_binding: bool,
        policy: object,
    ) -> list[str]:
        errors = []
        bindings = policy_path_hash_pairs(policy)
        for relative, expected_sha256 in sorted(expected.items()):
            path = REPO_ROOT / relative
            if path.is_symlink():
                errors.append("%s must be a regular committed file" % relative)
                continue
            if not path.is_file():
                errors.append("missing %s" % relative)
                continue
            actual_sha256 = sha256_path(path)
            if actual_sha256 != expected_sha256:
                errors.append(
                    "%s SHA-256 %s != %s"
                    % (relative, actual_sha256, expected_sha256)
                )
            if require_policy_binding and (
                relative,
                expected_sha256,
            ) not in bindings:
                errors.append(
                    "license-policy.json does not bind %s to %s"
                    % (relative, expected_sha256)
                )
        return errors

    def test_toolchain_and_component_terms_are_exact_distinct_files(self):
        errors = self._file_errors(
            PINNED_TEXT_FILES,
            require_policy_binding=True,
            policy=self.policy,
        )
        paths = tuple(PINNED_TEXT_FILES)
        if len(set(paths)) != len(paths):
            errors.append("pinned historical license texts must use distinct paths")
        hashes = tuple(PINNED_TEXT_FILES.values())
        if len(set(hashes)) != len(hashes):
            errors.append("pinned historical license texts must retain distinct bytes")
        self.assertEqual([], errors, "\n" + "\n".join(errors))

    def test_identifier_exact_text_catalog_is_complete(self):
        errors = []
        records = policy_license_text_records(self.policy)
        actual = {}
        for record in records:
            identifier = record.get("spdx_id")
            path = record.get("path")
            if isinstance(identifier, str) and isinstance(path, str):
                actual.setdefault(identifier, set()).add(path)

        for identifier, expected_path in sorted(IDENTIFIER_TEXT_FILES.items()):
            paths = actual.get(identifier, set())
            if paths != {expected_path}:
                errors.append(
                    "%s must map exactly once to %s, got %s"
                    % (identifier, expected_path, sorted(paths))
                )
            path = REPO_ROOT / expected_path
            if path.is_symlink() or not path.is_file():
                errors.append("missing regular text file %s" % expected_path)
            elif not path.read_bytes().strip():
                errors.append("empty license text %s" % expected_path)

        approved = self.policy.get("approved_license_refs")
        if not isinstance(approved, list):
            errors.append("approved_license_refs must be an array")
        else:
            missing_refs = sorted(
                {BERKELEY_LICENSE_REF, NEWLIB_LICENSE_REF} - set(approved)
            )
            if missing_refs:
                errors.append(
                    "unapproved required LicenseRef values: %s"
                    % ", ".join(missing_refs)
                )

        berkeley_path = REPO_ROOT / IDENTIFIER_TEXT_FILES[BERKELEY_LICENSE_REF]
        if berkeley_path.is_file():
            berkeley = berkeley_path.read_text(encoding="utf-8", errors="strict")
            for required in (
                "<advertising clause removed",
                "Effective immediately",
                "no longer required",
            ):
                if required not in berkeley:
                    errors.append(
                        "%s is missing exact rescission marker %r"
                        % (
                            IDENTIFIER_TEXT_FILES[BERKELEY_LICENSE_REF],
                            required,
                        )
                    )

        self.assertEqual([], errors, "\n" + "\n".join(errors))

    def test_upstream_notices_and_source_evidence_are_exact_and_bound(self):
        errors = self._file_errors(
            PINNED_EVIDENCE_FILES,
            require_policy_binding=True,
            policy=self.policy,
        )
        self.assertEqual([], errors, "\n" + "\n".join(errors))

    def test_reviewed_catalog_pins_all_source_identities(self):
        scalars = set(deep_scalars(self.policy))
        missing = [
            "%s: %s" % (name, value)
            for name, value in sorted(REQUIRED_SOURCE_IDENTITIES.items())
            if value not in scalars
        ]
        self.assertEqual(
            [],
            missing,
            "\nlicense-policy.json is missing reviewed source identities:\n"
            + "\n".join(missing),
        )


if __name__ == "__main__":
    unittest.main()
