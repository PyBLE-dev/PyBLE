#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""RED contracts for candidate-version release-audit routing.

The current validator checkout may be newer than an immutable release being
replayed.  Candidate semantics therefore come from the candidate version,
never implicitly from the validator checkout's ``firmware/versions.lock``.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SCRIPT = REPO_ROOT / "firmware/scripts/release_bundle.py"


def _load_release_module():
    spec = importlib.util.spec_from_file_location(
        "pyble_v061_release_version_routing_subject",
        RELEASE_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load firmware release implementation")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


RELEASE = _load_release_module()


class ToolLockRoutingFixture:
    """Materialize one valid tool lock without borrowing version authority."""

    _BASE_INPUTS = (
        "firmware/licenses/excluded-cves.yaml",
        "firmware/licenses/license-policy.json",
        "firmware/licenses/rp2-license-policy.json",
    )

    def __init__(
        self,
        *,
        validator_version: str,
        include_v061_build_tools: bool,
    ) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix="pyble-v061-version-route-"
        )
        self.repo = Path(self._temporary.name) / "validator-checkout"
        firmware = self.repo / "firmware"
        (firmware / "licenses").mkdir(parents=True)

        for relative in self._BASE_INPUTS:
            source = REPO_ROOT / relative
            destination = self.repo / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)

        versions = (REPO_ROOT / "firmware/versions.lock").read_text(
            encoding="utf-8"
        )
        versions, replacements = re.subn(
            r'(?m)^(agent_version\s*=\s*)"[^"]+"$',
            rf'\1"{validator_version}"',
            versions,
            count=1,
        )
        if replacements != 1:
            raise AssertionError("versions.lock lacks one agent_version")
        (firmware / "versions.lock").write_text(versions, encoding="utf-8")

        tool_lock = (REPO_ROOT / "firmware/release-tools.lock").read_text(
            encoding="utf-8"
        )
        build_path_prefix = "rp2_build_tools_license_policy_path = "
        build_hash_prefix = "rp2_build_tools_license_policy_sha256 = "
        if include_v061_build_tools:
            if (
                build_path_prefix not in tool_lock
                or build_hash_prefix not in tool_lock
            ):
                raise AssertionError(
                    "source tool lock lacks the prospective v0.6.1 binding"
                )
            policy_bytes = b"synthetic v0.6.1 build-tools policy fixture\n"
            policy_path = (
                firmware / "licenses/rp2-build-tools-license-policy.json"
            )
            policy_path.write_bytes(policy_bytes)
            policy_digest = hashlib.sha256(policy_bytes).hexdigest()
            tool_lock, replacements = re.subn(
                r'(?m)^(rp2_build_tools_license_policy_sha256\s*=\s*)"[0-9a-f]{64}"$',
                rf'\1"{policy_digest}"',
                tool_lock,
                count=1,
            )
            if replacements != 1:
                raise AssertionError("tool lock lacks one build-tools digest")
        else:
            tool_lock = "\n".join(
                line
                for line in tool_lock.splitlines()
                if not line.startswith((build_path_prefix, build_hash_prefix))
            ) + "\n"
        (firmware / "release-tools.lock").write_text(
            tool_lock,
            encoding="utf-8",
        )

    def close(self) -> None:
        self._temporary.cleanup()


class CandidateVersionToolLockRoutingTests(unittest.TestCase):
    def test_v060_replay_never_inherits_v061_picotool_policy_from_validator(self):
        fixture = ToolLockRoutingFixture(
            validator_version="0.6.1",
            include_v061_build_tools=False,
        )
        try:
            with mock.patch.object(
                RELEASE,
                "_read_lock",
                side_effect=AssertionError(
                    "candidate routing consulted validator versions.lock"
                ),
            ) as read_validator_lock:
                lock = RELEASE._audit_load_tool_lock(
                    fixture.repo,
                    firmware_version="0.6.0",
                )

            read_validator_lock.assert_not_called()
            self.assertNotIn(
                "rp2_build_tools_license_policy_path",
                lock["inputs"],
            )
        finally:
            fixture.close()

    def test_v061_candidate_selects_picotool_policy_despite_v060_validator_lock(self):
        fixture = ToolLockRoutingFixture(
            validator_version="0.6.0",
            include_v061_build_tools=True,
        )
        try:
            with mock.patch.object(
                RELEASE,
                "_read_lock",
                side_effect=AssertionError(
                    "candidate routing consulted validator versions.lock"
                ),
            ) as read_validator_lock:
                lock = RELEASE._audit_load_tool_lock(
                    fixture.repo,
                    firmware_version="0.6.1",
                )

            read_validator_lock.assert_not_called()
            self.assertEqual(
                lock["inputs"]["rp2_build_tools_license_policy_path"],
                "firmware/licenses/rp2-build-tools-license-policy.json",
            )
        finally:
            fixture.close()


class CompareCliVersionRoutingTests(unittest.TestCase):
    def test_compare_cli_routes_repo_and_strict_source_version(self):
        with tempfile.TemporaryDirectory(
            prefix="pyble-v061-compare-cli-route-"
        ) as raw:
            root = Path(raw)
            left = root / "left"
            right = root / "right"
            repo = root / "validator-checkout"
            left.mkdir()
            right.mkdir()
            (repo / "firmware").mkdir(parents=True)
            shutil.copyfile(
                REPO_ROOT / "firmware/versions.lock",
                repo / "firmware/versions.lock",
            )

            with mock.patch.object(
                RELEASE,
                "compare_build_roots",
                return_value=None,
            ) as compare:
                result = RELEASE._main(
                    [
                        "compare",
                        str(left),
                        str(right),
                        "--repo-root",
                        str(repo),
                    ]
                )

            self.assertEqual(result, 0)
            compare.assert_called_once_with(
                left,
                right,
                repo_root=repo,
                firmware_version="0.6.1",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
