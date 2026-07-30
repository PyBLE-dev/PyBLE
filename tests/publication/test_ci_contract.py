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
        self.assertIn("timeout --signal=TERM --kill-after=30s 12m", android)
        self.assertIn("--no-pub", android)
        self.assertIn("flutter drive \\", android)
        self.assertIn(
            "--driver test_driver/integration_test.dart",
            android,
        )
        self.assertIn(
            "--use-application-binary "
            "build/app/outputs/flutter-apk/app-debug.apk",
            android,
        )
        self.assertNotIn("            flutter test \\", android)

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
        driver = (
            REPO_ROOT / "app" / "test_driver" / "integration_test.dart"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "import 'package:integration_test/integration_test_driver.dart';",
            driver,
        )
        self.assertIn(
            "Future<void> main() => integrationDriver(",
            driver,
        )
        self.assertIn(
            "timeout: const Duration(minutes: 10),",
            driver,
        )
        self.assertIn(
            "writeResponseOnFailure: true,",
            driver,
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

        self.assertIn(
            "GRADLE_USER_HOME: /tmp/pyble-gradle-home",
            android,
        )
        self.assertIn(
            "'org.gradle.jvmargs=-Xmx3072m "
            "-XX:MaxMetaspaceSize=1024m "
            "-XX:ReservedCodeCacheSize=256m'",
            android,
        )
        self.assertIn(
            "'org.gradle.daemon=false'",
            android,
        )
        self.assertIn(
            "'org.gradle.workers.max=1'",
            android,
        )
        self.assertIn(
            "'kotlin.compiler.execution.strategy=in-process'",
            android,
        )
        self.assertIn(
            '> "$GRADLE_USER_HOME/gradle.properties"',
            android,
        )
        self.assertIn("--set 'hw.ramSize=4096'", android)
        self.assertIn("--set 'hw.cpu.ncore=4'", android)
        self.assertIn("-memory 4096", android)
        self.assertIn("-cores 4", android)
        self.assertIn(
            "settings put global device_provisioned 1",
            android,
        )
        self.assertIn(
            "settings put secure user_setup_complete 1",
            android,
        )
        self.assertIn(
            "settings put system accelerometer_rotation 0",
            android,
        )
        self.assertIn(
            "settings put system user_rotation 0",
            android,
        )
        self.assertIn("getprop init.svc.bootanim", android)
        self.assertIn("getprop sys.user.0.ce_available", android)
        self.assertIn("sleep 20", android)

        prebuild = android.index(
            "- name: Prebuild Android integration application"
        )
        boot = android.index("- name: Boot headless emulator")
        integration = android.index(
            "- name: Real About + Blockly integration"
        )
        self.assertLess(prebuild, boot)
        self.assertLess(boot, integration)
        self.assertLess(
            android.index("getprop init.svc.bootanim"),
            integration,
        )
        self.assertLess(android.index("sleep 20"), integration)
        self.assertEqual(1, android.count("flutter build apk"))
        self.assertIn(
            "flutter build apk \\\n"
            "            --debug \\\n"
            "            --no-pub \\\n"
            "            --target-platform android-x64 \\\n"
            "            --target integration_test/android_smoke_test.dart",
            android,
        )
        self.assertIn(
            '>"$PYBLE_ANDROID_LOG_DIR/flutter-build.log" 2>&1',
            android,
        )
        self.assertIn(
            "test -s build/app/outputs/flutter-apk/app-debug.apk",
            android,
        )
        self.assertIn("./android/gradlew --stop", android)
        self.assertIn(
            '>"$PYBLE_ANDROID_LOG_DIR/flutter-drive.log" 2>&1',
            android,
        )
        self.assertIn(
            "--use-application-binary "
            "build/app/outputs/flutter-apk/app-debug.apk",
            android,
        )
        self.assertNotIn(
            '2>&1 | tee "$PYBLE_ANDROID_LOG_DIR/flutter-drive.log"',
            android,
        )

    def test_android_integration_uses_full_aosp_without_gms(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        android_start = workflow.index("  android-webview:")
        build_start = workflow.index("\n  build:", android_start)
        android = workflow[android_start:build_start]

        self.assertIn(
            "PYBLE_ANDROID_IMAGE: system-images;android-34;default;x86_64",
            android,
        )
        self.assertIn(
            "PYBLE_ANDROID_AVD: pyble_api34_aosp",
            android,
        )
        self.assertIn(
            "- name: Create API 34 AOSP x86_64 tablet AVD",
            android,
        )
        self.assertNotIn("google_apis", android)
        self.assertNotIn("aosp_atd", android)
        self.assertIn(
            "pm list packages com.google.android.gms",
            android,
        )
        self.assertIn(
            "dumpsys webviewupdate",
            android,
        )
        self.assertIn(
            "Current WebView package (name, version): (com.android.webview,",
            android,
        )

    def test_workflow_has_no_adjacent_duplicate_shell_key(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("        shell: bash\n        shell: bash\n", workflow)


if __name__ == "__main__":
    unittest.main()
