# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class CiContractTest(unittest.TestCase):
    def test_pico_build_is_a_real_pinned_arm64_ci_job(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "  build-rp2:",
            workflow,
            "CI must define a distinct real Pico build job",
        )
        start = workflow.index("  build-rp2:")
        following = re.search(
            r"(?m)^  [a-z0-9_-]+:\s*$",
            workflow[start + len("  build-rp2:") :],
        )
        end = (
            len(workflow)
            if following is None
            else start + len("  build-rp2:") + following.start()
        )
        job = workflow[start:end]

        self.assertIn(
            "needs: [no-leak, spdx, sha-drift, patches, firmware-host]",
            job,
        )
        self.assertIn("runs-on: macos-15", job)
        self.assertRegex(job, r"timeout-minutes: (?:[3-9][0-9]|[1-9][0-9]{2,})")
        self.assertRegex(job, r"uses: actions/checkout@[0-9a-f]{40}\b")
        self.assertIn("fetch-depth: 0", job)
        self.assertNotIn("submodules: true", job)
        self.assertIn('test "$(uname -s)" = "Darwin"', job)
        self.assertIn('test "$(uname -m)" = "arm64"', job)

        logical = re.sub(r"\\\n[ \t]*", " ", job)
        outer_submodule = (
            "git submodule update --init --depth 1 -- "
            "firmware/upstream/micropython"
        )
        nested_prefix = (
            "git -C firmware/upstream/micropython submodule update "
            "--init --depth 1 --"
        )
        self.assertIn(outer_submodule, logical)
        self.assertIn(nested_prefix, logical)
        self.assertNotRegex(
            logical,
            r"git(?: -C [^ ]+)? submodule update[^\n]* --recursive\b",
        )

        for submodule in (
            "lib/btstack",
            "lib/cyw43-driver",
            "lib/lwip",
            "lib/mbedtls",
            "lib/micropython-lib",
            "lib/pico-sdk",
            "lib/tinyusb",
        ):
            with self.subTest(submodule=submodule):
                self.assertIn(submodule, job)

        self.assertIn("firmware/scripts/install_arm_toolchain.sh", job)
        self.assertIn("firmware/scripts/install_picotool.sh", job)
        self.assertIn(
            "firmware/scripts/build_rp2.sh rpi-pico2-w",
            job,
        )
        self.assertNotIn("build_rp2.sh --plan", job)
        self.assertNotRegex(job, r"\bbrew\s+(?:install\s+)?picotool\b")
        self.assertNotRegex(job, r"(?s)actions/cache@.*?firmware/\.picotool")
        self.assertRegex(job, r"uses: actions/upload-artifact@[0-9a-f]{40}\b")
        self.assertIn("if-no-files-found: error", job)
        self.assertRegex(job, r"retention-days: [1-9][0-9]*")
        for artifact in (
            "firmware.uf2",
            "firmware.bin",
            "firmware.elf",
            "firmware.elf.map",
            "pyble-build-provenance.json",
        ):
            with self.subTest(artifact=artifact):
                self.assertIn(
                    f"firmware/build/rpi-pico2-w/{artifact}",
                    job,
                )

        ordered_tokens = (
            'test "$(uname -m)" = "arm64"',
            outer_submodule,
            "firmware/scripts/install_arm_toolchain.sh",
            "firmware/scripts/install_picotool.sh",
            "firmware/scripts/build_rp2.sh rpi-pico2-w",
            "uses: actions/upload-artifact@",
        )
        positions = [logical.index(token) for token in ordered_tokens]
        self.assertEqual(
            positions,
            sorted(positions),
            "the isolated RP2 job prerequisite/build/publication order changed",
        )

    def test_firmware_host_checks_out_full_history_and_pinned_submodules(
        self,
    ) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        start = workflow.index("  firmware-host:")
        end = workflow.index("\n  app:", start)
        firmware_host = workflow[start:end]

        self.assertIn(
            "      - uses: actions/checkout@v4\n"
            "        with:\n"
            "          fetch-depth: 0\n"
            "          submodules: true\n",
            firmware_host,
        )
        self.assertIn(
            "      - name: Initialize pinned MicroPython host dependencies\n"
            "        run: |\n"
            "          git -C firmware/upstream/micropython submodule update "
            "--init --depth 1 \\\n"
            "            lib/micropython-lib \\\n"
            "            lib/cyw43-driver\n",
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

    def test_android_integration_uses_one_isolated_application_bundle(self) -> None:
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
        self.assertIn("--flavor integration", android)
        self.assertIn(
            "--driver test_driver/integration_test.dart",
            android,
        )
        self.assertIn(
            "--use-application-binary "
            "build/app/outputs/flutter-apk/app-integration-debug.apk",
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
        self.assertEqual(2, android.count("flutter build apk"))
        self.assertIn(
            "flutter build apk --release --flavor production "
            "--target lib/main.dart",
            android,
        )
        self.assertIn("package: name='dev.pyble.pyble'", android)
        self.assertIn(
            "flutter build apk \\\n"
            "            --debug \\\n"
            "            --flavor integration \\\n"
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
            "test -s "
            "build/app/outputs/flutter-apk/app-integration-debug.apk",
            android,
        )
        self.assertIn("./android/gradlew --stop", android)
        self.assertIn(
            '>"$PYBLE_ANDROID_LOG_DIR/flutter-drive.log" 2>&1',
            android,
        )
        self.assertIn(
            "--use-application-binary "
            "build/app/outputs/flutter-apk/app-integration-debug.apk",
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

    def test_android_blockly_smoke_reveals_ime_occluded_actions(self) -> None:
        suite = (
            REPO_ROOT / "app" / "integration_test" / "blockly_webview_suite.dart"
        ).read_text(encoding="utf-8")

        tap_visible_start = suite.index("Future<void> _tapVisible(")
        tap_visible_end = suite.index("\n}\n", tap_visible_start)
        tap_visible = suite[tap_visible_start:tap_visible_end]
        preview_snippets = (
            "FocusManager.instance.primaryFocus?.unfocus();",
            "tester.binding.focusedEditable = null;",
            "SystemChannels.textInput.invokeMethod<void>('TextInput.hide');",
            "await tester.ensureVisible(finder);",
            "await _pumpUntil(",
            "() => finder.hitTestable().evaluate().length == 1,",
            (
                "reason: 'the action did not become hit-testable after the "
                "Android IME hide',"
            ),
            "await tester.tap(finder);",
        )
        preview_positions = []
        for snippet in preview_snippets:
            self.assertIn(
                snippet,
                tap_visible,
                f"missing Android preview interaction contract: {snippet}",
            )
            preview_positions.append(tap_visible.index(snippet))
        self.assertEqual(preview_positions, sorted(preview_positions))

        stable_field = suite.index(
            "final Finder ledGpioField = find.byKey(ledGpioFieldKey!);"
        )
        enter_gpio = suite.index(
            "await tester.enterText(ledGpioField, '17');", stable_field
        )
        required_snippets = (
            "final Finder replaceWorkspaceAction = find.byKey(",
            "kBlocksExampleReplaceWorkspaceButtonKey",
            "await tester.ensureVisible(replaceWorkspaceAction);",
            "expect(replaceWorkspaceAction.hitTestable(), findsOneWidget);",
            "await tester.tap(replaceWorkspaceAction);",
        )
        for snippet in required_snippets:
            self.assertTrue(
                snippet in suite,
                f"missing Android Blockly interaction contract: {snippet}",
            )

        define_action = suite.index(required_snippets[0], enter_gpio)
        action_key = suite.index(required_snippets[1], define_action)
        reveal_action = suite.index(
            required_snippets[2],
            action_key,
        )
        hit_test = suite.index(
            required_snippets[3],
            reveal_action,
        )
        tap_action = suite.index(
            required_snippets[4],
            hit_test,
        )

        self.assertLess(enter_gpio, define_action)
        self.assertLess(define_action, action_key)
        self.assertLess(action_key, reveal_action)
        self.assertLess(reveal_action, hit_test)
        self.assertLess(hit_test, tap_action)

    def test_ios_distribution_validator_enforces_deployment_floor(self) -> None:
        validator = (
            REPO_ROOT / "tools" / "validate_ios_ipa.sh"
        ).read_text(encoding="utf-8")

        required_snippets = (
            "readonly IOS_DEPLOYMENT_FLOOR='15.0'",
            "version_at_least() {",
            "plutil -extract MinimumOSVersion raw",
            "plutil -extract CFBundleExecutable raw",
            '"$VTOOL_PATH" -show-build "$APP_EXECUTABLE_PATH"',
            "expected iOS deployment floor",
            "compiled iOS minimum",
        )
        positions = []
        for snippet in required_snippets:
            self.assertIn(
                snippet,
                validator,
                f"missing iOS deployment-floor validator contract: {snippet}",
            )
            positions.append(validator.index(snippet))

        self.assertEqual(positions, sorted(positions))
        self.assertLess(
            validator.index("compiled iOS minimum"),
            validator.index("codesign --verify --deep --strict"),
        )

    def test_workflow_has_no_adjacent_duplicate_shell_key(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("        shell: bash\n        shell: bash\n", workflow)


if __name__ == "__main__":
    unittest.main()
