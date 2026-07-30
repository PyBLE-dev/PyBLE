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

    def test_android_avd_reclaims_runner_disk_for_its_required_storage(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        android_start = workflow.index("  android-webview:")
        build_start = workflow.index("\n  build:", android_start)
        android = workflow[android_start:build_start]

        self.assertIn("../tools/ci/android_avd_config.py", android)
        self.assertIn("mapfile -t PYBLE_UNUSED_NDKS", android)
        self.assertIn(
            '"$SDKMANAGER" --uninstall "${PYBLE_UNUSED_NDKS[@]}"',
            android,
        )
        self.assertIn('"$SDKMANAGER" --list_installed', android)
        self.assertIn(
            '| tee "$PYBLE_ANDROID_LOG_DIR/sdk-list-installed.log"',
            android,
        )
        self.assertLess(
            android.index('"$SDKMANAGER" --list_installed'),
            android.index("mapfile -t PYBLE_UNUSED_NDKS"),
        )
        self.assertLess(
            android.index('"$SDKMANAGER" --uninstall'),
            android.index('"$SDKMANAGER" --channel=0'),
        )
        self.assertIn(
            '[ ! -d "$PYBLE_PINNED_NDK_ROOT" ]',
            android,
        )
        for variable in (
            "ANDROID_NDK",
            "ANDROID_NDK_HOME",
            "ANDROID_NDK_ROOT",
            "ANDROID_NDK_PATH",
            "ANDROID_NDK_LATEST_HOME",
        ):
            self.assertIn(f'"{variable}=${variable}"', android)
        self.assertIn("'disk.dataPartition.size=6144M'", android)
        self.assertIn("-partition-size 6144", android)
        self.assertNotIn("partition-size 2048", android)
        self.assertIn(
            "|vm\\.heapSize)[[:space:]]*=[[:space:]]*'",
            android,
        )

    def test_android_integration_builds_one_application_bundle(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        android_start = workflow.index("  android-webview:")
        build_start = workflow.index("\n  build:", android_start)
        android = workflow[android_start:build_start]

        self.assertIn("integration_test/android_smoke_test.dart", android)
        self.assertNotIn("integration_test/about_page_test.dart", android)
        self.assertNotIn("integration_test/blockly_webview_test.dart", android)
        self.assertIn("timeout --signal=TERM --kill-after=30s 30m", android)
        self.assertIn("--no-pub", android)

        integration_root = REPO_ROOT / "app" / "integration_test"
        self.assertEqual(
            ["android_smoke_test.dart"],
            sorted(path.name for path in integration_root.glob("*_test.dart")),
        )
        harness = (integration_root / "android_smoke_test.dart").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "import 'about_page_suite.dart' as about_page;",
            harness,
        )
        self.assertIn(
            "import 'blockly_webview_suite.dart' as blockly_webview;",
            harness,
        )
        self.assertEqual(
            1,
            harness.count(
                "IntegrationTestWidgetsFlutterBinding.ensureInitialized();"
            ),
        )
        self.assertIn(
            "about_page.registerAboutPageIntegrationTests();",
            harness,
        )
        self.assertIn(
            "blockly_webview.registerBlocklyWebViewIntegrationTests();",
            harness,
        )

    def test_android_integration_prebuilds_with_bounded_runner_resources(
        self,
    ) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        android_start = workflow.index("  android-webview:")
        build_start = workflow.index("\n  build:", android_start)
        android = workflow[android_start:build_start]
        gradle_properties = (
            REPO_ROOT / "app" / "android" / "gradle.properties"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "org.gradle.jvmargs=-Xmx3072m "
            "-XX:MaxMetaspaceSize=1024m "
            "-XX:ReservedCodeCacheSize=256m",
            gradle_properties,
        )
        self.assertIn(
            "GRADLE_OPTS: -Dorg.gradle.daemon=false "
            "-Dorg.gradle.workers.max=1",
            android,
        )
        self.assertIn("--set 'hw.ramSize=2048'", android)
        self.assertIn("--set 'hw.cpu.ncore=1'", android)
        self.assertIn("-memory 2048", android)
        self.assertIn("-cores 1", android)

        prebuild = android.index(
            "- name: Prebuild Android integration application"
        )
        boot = android.index("- name: Boot headless emulator")
        integration = android.index(
            "- name: Real About + Blockly integration"
        )
        self.assertLess(prebuild, boot)
        self.assertLess(boot, integration)
        self.assertIn(
            "flutter build apk \\\n"
            "            --debug \\\n"
            "            --no-pub \\\n"
            "            --target integration_test/android_smoke_test.dart",
            android,
        )
        self.assertIn(
            '>"$PYBLE_ANDROID_LOG_DIR/flutter-build.log" 2>&1',
            android,
        )
        self.assertIn("./android/gradlew --stop", android)
        self.assertIn(
            '>"$PYBLE_ANDROID_LOG_DIR/flutter-test.log" 2>&1',
            android,
        )
        self.assertNotIn(
            '2>&1 | tee "$PYBLE_ANDROID_LOG_DIR/flutter-test.log"',
            android,
        )

    def test_workflow_has_no_adjacent_duplicate_shell_key(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("        shell: bash\n        shell: bash\n", workflow)


if __name__ == "__main__":
    unittest.main()
