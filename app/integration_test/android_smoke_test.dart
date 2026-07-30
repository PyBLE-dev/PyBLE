// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// One Android application bundle for the real package-metadata and Blockly
// platform-WebView smoke tests. Flutter builds once per integration test file.

import 'about_page_test.dart' as about_page;
import 'blockly_webview_test.dart' as blockly_webview;

void main() {
  about_page.main();
  blockly_webview.main();
}
