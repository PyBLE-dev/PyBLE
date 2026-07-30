// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// One Android application bundle for the real package-metadata and Blockly
// platform-WebView smoke tests. Flutter builds once per integration test file.

import 'package:integration_test/integration_test.dart';

import 'about_page_suite.dart' as about_page;
import 'blockly_webview_suite.dart' as blockly_webview;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  about_page.registerAboutPageIntegrationTests();
  blockly_webview.registerBlocklyWebViewIntegrationTests();
}
