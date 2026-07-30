# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class CiContractTest(unittest.TestCase):
    def test_firmware_host_checks_out_pinned_submodules(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        start = workflow.index("  firmware-host:")
        end = workflow.index("\n  app:", start)
        firmware_host = workflow[start:end]

        self.assertIn(
            "      - uses: actions/checkout@v4\n"
            "        with:\n"
            "          submodules: true\n",
            firmware_host,
        )


if __name__ == "__main__":
    unittest.main()
