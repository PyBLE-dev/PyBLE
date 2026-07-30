// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-31 — the authored Blockly host must load only pinned, app-bundled assets.

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/blocks/blocks.dart';

import '../support/repo_paths.dart';

void main() {
  group('A-31 Blockly asset policy', () {
    late File index;
    late String html;

    setUpAll(() {
      index = File('${appPackageRoot().path}/assets/blockly/index.html');
      expect(
        index.existsSync(),
        isTrue,
        reason: 'the bundled Blockly host must exist',
      );
      html = index.readAsStringSync();
    });

    test('references only relative local resources', () {
      final references = RegExp(
        r'''(?:src|href)\s*=\s*["']([^"']+)["']''',
        caseSensitive: false,
      ).allMatches(html).map((match) => match.group(1)!).toList();

      expect(
        references,
        containsAll(<String>[
          'pyble_blockly.css',
          'vendor/blockly_compressed.js',
          'vendor/blocks_compressed.js',
          'vendor/python_compressed.js',
          'vendor/msg/en.js',
          'pyble_blockly.js',
        ]),
      );
      expect(references, isNotEmpty);
      for (final reference in references) {
        final uri = Uri.parse(reference);
        expect(uri.hasScheme, isFalse, reason: 'external resource: $reference');
        expect(
          reference.startsWith('//') || reference.startsWith('/'),
          isFalse,
          reason: 'resource must be relative to the app asset: $reference',
        );
        expect(
          File('${index.parent.path}/$reference').existsSync(),
          isTrue,
          reason: 'referenced app-bundled resource is missing: $reference',
        );
      }
    });

    test("CSP disables network connections with connect-src 'none'", () {
      final compactHtml = html.replaceAll(RegExp(r'\s+'), ' ');
      expect(
        RegExp(r"connect-src\s+'none'").hasMatch(compactHtml),
        isTrue,
        reason: "Blockly host CSP must contain connect-src 'none'",
      );
    });

    test('packages the Python generator as store-signable JavaScript data', () {
      final String generator = File(
        '${index.parent.path}/vendor/python_compressed.js',
      ).readAsStringSync();
      final RegExp rawPythonTry = RegExp(r'^[ \t]*try:', multiLine: true);
      final RegExp interpolatedTry = RegExp(
        r'^[ \t]*\$\{"try"\}:',
        multiLine: true,
      );

      expect(
        rawPythonTry.hasMatch(generator),
        isFalse,
        reason:
            'raw multiline Python makes Apple classify this sealed JS asset '
            'as unsigned nested code',
      );
      expect(
        interpolatedTry.allMatches(generator),
        hasLength(5),
        reason: 'the deterministic JS interpolation must preserve runtime try:',
      );
    });

    test('styles the live Blockly 13 toolbox with tablet touch targets', () {
      final String css = File(
        '${index.parent.path}/pyble_blockly.css',
      ).readAsStringSync();

      expect(css, contains('.blocklyToolbox[layout="v"]'));
      expect(
        css,
        contains('.blocklyToolbox[layout="v"] .blocklyToolboxCategory'),
      );
      expect(css, contains('min-height: 48px'));
      expect(
        css,
        contains('.blocklyToolbox[layout="v"] .blocklyToolboxCategoryLabel'),
      );
      expect(
        css,
        isNot(contains('.blocklyToolboxDiv')),
        reason: 'Blockly 13 removed the legacy toolbox selector',
      );
    });

    test('coalesces host and viewport resizes before sizing Blockly', () {
      final String script = File(
        '${index.parent.path}/pyble_blockly.js',
      ).readAsStringSync();

      expect(script, contains('new ResizeObserver(resizeWorkspace)'));
      expect(script, contains('requestAnimationFrame'));
      expect(script, contains('cancelAnimationFrame'));
      expect(
        script,
        contains('window.addEventListener("resize", resizeWorkspace)'),
      );
    });
  });

  group('A-31 Blockly navigation policy', () {
    test('admits only the exact bundled Flutter asset locations', () {
      expect(
        isAllowedBlocklyNavigation(
          'file:///android_asset/flutter_assets/assets/blockly/index.html',
        ),
        isTrue,
      );
      expect(
        isAllowedBlocklyNavigation(
          'file:///private/app/Frameworks/App.framework/flutter_assets/'
          'assets/blockly/index.html',
        ),
        isTrue,
      );
      expect(
        isAllowedBlocklyNavigation(
          'https://appassets.androidplatform.net/assets/'
          'assets/blockly/index.html',
        ),
        isTrue,
      );
      expect(isAllowedBlocklyNavigation('about:blank'), isTrue);
    });

    test('rejects unrelated files, traversal, network, and custom schemes', () {
      for (final String url in <String>[
        'file:///etc/passwd',
        'file:///android_asset/flutter_assets/assets/blockly/../secret.html',
        'https://example.com/assets/blockly/index.html',
        'https://user@appassets.androidplatform.net/assets/assets/blockly/index.html',
        'https://appassets.androidplatform.net:443/assets/assets/blockly/index.html',
        'http://appassets.androidplatform.net/assets/assets/blockly/index.html',
        'custom://appassets.androidplatform.net/assets/assets/blockly/index.html',
        'about:srcdoc',
        'javascript:alert(1)',
      ]) {
        expect(
          isAllowedBlocklyNavigation(url),
          isFalse,
          reason: 'unexpectedly admitted $url',
        );
      }
    });
  });

  test(
    'only an accepted snapshot or terminal host error stops startup watch',
    () {
      expect(
        shouldCancelBlocksStartupWatchdog(BlocksBridgeResult.snapshotAccepted),
        isTrue,
      );
      expect(
        shouldCancelBlocksStartupWatchdog(BlocksBridgeResult.hostError),
        isTrue,
      );
      expect(
        shouldCancelBlocksStartupWatchdog(BlocksBridgeResult.workspaceError),
        isTrue,
        reason: 'an accepted repairable workspace error proves the host loaded',
      );
      expect(
        shouldCancelBlocksStartupWatchdog(BlocksBridgeResult.staleSnapshot),
        isFalse,
        reason: 'the retained workspace still needs to be restored',
      );
      expect(
        shouldCancelBlocksStartupWatchdog(BlocksBridgeResult.ignored),
        isFalse,
      );
    },
  );

  group('Blockly scratch preview result decoding', () {
    const String source = "print('Hello, PyBLE!')\n";
    final String payload = jsonEncode(<String, Object?>{
      'source': source,
      'workspace': <String, Object?>{
        'blocks': <String, Object?>{
          'languageVersion': 0,
          'blocks': <Object?>[],
        },
      },
    });

    test('accepts the direct JSON string returned by WKWebView', () {
      final BlocksExamplePreview preview = decodeBlocksExamplePreviewResult(
        payload,
      );

      expect(preview.source, source);
      expect(jsonDecode(preview.workspaceJson), <String, Object?>{
        'blocks': <String, Object?>{
          'languageVersion': 0,
          'blocks': <Object?>[],
        },
      });
    });

    test('unwraps the JSON string literal returned by Android WebView', () {
      final BlocksExamplePreview preview = decodeBlocksExamplePreviewResult(
        jsonEncode(payload),
      );

      expect(preview.source, source);
      expect(jsonDecode(preview.workspaceJson), <String, Object?>{
        'blocks': <String, Object?>{
          'languageVersion': 0,
          'blocks': <Object?>[],
        },
      });
    });

    test('rejects malformed and excessively wrapped results', () {
      for (final Object result in <Object>[
        42,
        'null',
        jsonEncode(<String, Object?>{'source': source}),
        jsonEncode(jsonEncode(payload)),
      ]) {
        expect(
          () => decodeBlocksExamplePreviewResult(result),
          throwsA(isA<FormatException>()),
          reason: 'unexpectedly accepted $result',
        );
      }
    });
  });
}
