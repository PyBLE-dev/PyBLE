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
        self.assertIn(
            "      - name: Initialize pinned MicroPython host dependency\n"
            "        run: |\n"
            "          git -C firmware/upstream/micropython submodule update "
            "--init --depth 1 \\\n"
            "            lib/micropython-lib\n",
            firmware_host,
        )

    def test_pixel_goldens_run_on_pinned_macos(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        app_start = workflow.index("  app:")
        goldens_start = workflow.index("\n  app-goldens:", app_start)
        android_start = workflow.index("\n  android-webview:", goldens_start)
        app = workflow[app_start:goldens_start]
        goldens = workflow[goldens_start:android_start]
        android = workflow[android_start:]

        self.assertIn("run: flutter test --exclude-tags golden", app)
        self.assertIn("runs-on: macos-15", goldens)
        self.assertIn("run: flutter test --tags golden", goldens)
        self.assertIn("needs: [app, app-goldens]", android)

        for relative in (
            "app/test/golden/app_shell_golden_test.dart",
            "app/test/golden/about_page_golden_test.dart",
        ):
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            self.assertEqual(
                source.count("tags: const ['golden']"),
                source.count("testWidgets("),
                f"every testWidgets call in {relative} must carry the golden tag",
            )

    def test_android_avd_uses_bounded_storage(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        android_start = workflow.index("  android-webview:")
        build_start = workflow.index("\n  build:", android_start)
        android = workflow[android_start:build_start]

        self.assertIn("../tools/ci/android_avd_config.py", android)
        self.assertIn("'disk.dataPartition.size=2048M'", android)

    def test_workflow_has_no_adjacent_duplicate_shell_key(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("        shell: bash\n        shell: bash\n", workflow)


if __name__ == "__main__":
    unittest.main()
