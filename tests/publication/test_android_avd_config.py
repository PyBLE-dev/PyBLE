# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "ci"))

from android_avd_config import apply_overrides  # noqa: E402


class AndroidAvdConfigTest(unittest.TestCase):
    def test_overrides_replace_every_existing_copy_of_a_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.ini"
            config.write_text(
                "AvdId=pyble\n"
                "disk.dataPartition.size=6G\n"
                "hw.ramSize = 1536\n"
                "disk.dataPartition.size=4096M\n"
                "unrelated.setting=yes\n",
                encoding="utf-8",
            )

            apply_overrides(
                config,
                (
                    "disk.dataPartition.size=2048M",
                    "hw.ramSize=3072",
                ),
            )

            lines = config.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                [
                    line
                    for line in lines
                    if line.partition("=")[0].strip()
                    == "disk.dataPartition.size"
                ],
                ["disk.dataPartition.size=2048M"],
            )
            self.assertEqual(
                [
                    line
                    for line in lines
                    if line.partition("=")[0].strip() == "hw.ramSize"
                ],
                ["hw.ramSize=3072"],
            )
            self.assertIn("AvdId=pyble", lines)
            self.assertIn("unrelated.setting=yes", lines)

    def test_rejects_duplicate_or_malformed_requested_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.ini"
            config.write_text("AvdId=pyble\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "duplicate"):
                apply_overrides(config, ("hw.ramSize=2048", "hw.ramSize=3072"))
            with self.assertRaisesRegex(ValueError, "KEY=VALUE"):
                apply_overrides(config, ("not-an-assignment",))


if __name__ == "__main__":
    unittest.main()
