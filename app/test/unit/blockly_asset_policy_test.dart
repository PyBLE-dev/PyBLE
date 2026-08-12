// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-31 — the authored Blockly host must load only pinned, app-bundled assets.
// A-38 — GPIO slots accept named MicroPython pins (FR-BLOCKS-1B).

import 'dart:async';
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

    test('announces host readiness only after the authored API exists', () {
      final String script = File(
        '${index.parent.path}/pyble_blockly.js',
      ).readAsStringSync();
      final int apiIndex = script.indexOf(
        'window.pybleBlocks = Object.freeze({',
      );
      final Iterable<RegExpMatch> readyMessages = RegExp(
        r'type:\s*"hostReady"',
      ).allMatches(script);

      expect(apiIndex, greaterThanOrEqualTo(0));
      expect(readyMessages, hasLength(1));
      expect(
        readyMessages.single.start,
        greaterThan(apiIndex),
        reason: 'Dart must never configure a partially loaded authored host',
      );
    });
  });

  group('A-31 Blockly host readiness gate', () {
    const String ready = '{"version":1,"type":"hostReady"}';
    const String firstSnapshot =
        '{"version":1,"type":"snapshot","hostEpoch":101}';
    const String secondSnapshot =
        '{"version":1,"type":"snapshot","hostEpoch":202}';

    test('routes one readiness per page and swallows exact duplicates', () {
      final BlocklyHostStartupGate gate = BlocklyHostStartupGate();

      expect(
        gate.classify(ready),
        BlocklyHostChannelDisposition.ignore,
        reason: 'readiness before an allowed main-frame start is inert',
      );
      gate.beginPage(hostEpoch: 101);
      expect(gate.classify(ready), BlocklyHostChannelDisposition.initialise);
      gate.finishInitialisation(gate.generation, succeeded: true);
      expect(gate.classify(ready), BlocklyHostChannelDisposition.ignore);
      expect(
        gate.classify(firstSnapshot),
        BlocklyHostChannelDisposition.forward,
      );

      gate.beginPage(hostEpoch: 202);
      expect(
        gate.classify(ready),
        BlocklyHostChannelDisposition.initialise,
        reason: 'an allowed reload must configure its new document generation',
      );
      gate.finishInitialisation(gate.generation, succeeded: true);
      expect(gate.classify(ready), BlocklyHostChannelDisposition.ignore);
      expect(
        gate.classify(firstSnapshot),
        BlocklyHostChannelDisposition.ignore,
        reason: 'traffic from the superseded document epoch must stay inert',
      );
      expect(
        gate.classify(secondSnapshot),
        BlocklyHostChannelDisposition.forward,
      );
    });

    test('re-arms failed readiness and retries one duplicate in flight', () {
      final BlocklyHostStartupGate gate = BlocklyHostStartupGate()
        ..beginPage(hostEpoch: 101);
      final int generation = gate.generation;

      expect(gate.classify(ready), BlocklyHostChannelDisposition.initialise);
      expect(
        gate.classify(ready),
        BlocklyHostChannelDisposition.ignore,
        reason: 'a duplicate must not configure the same page concurrently',
      );
      expect(
        gate.finishInitialisation(generation, succeeded: false),
        isTrue,
        reason: 'the queued readiness must trigger one serialized retry',
      );
      expect(gate.finishInitialisation(generation, succeeded: false), isFalse);
      expect(
        gate.classify(ready),
        BlocklyHostChannelDisposition.initialise,
        reason: 'a failed retry must leave the generation re-armed',
      );
      expect(gate.finishInitialisation(generation, succeeded: true), isFalse);
      expect(gate.classify(ready), BlocklyHostChannelDisposition.ignore);
    });

    test(
      'dispatch never forwards duplicate readiness to the document bridge',
      () {
        final BlocklyHostStartupGate gate = BlocklyHostStartupGate();
        int initialisations = 0;
        int rejections = 0;
        final List<String> forwarded = <String>[];
        void dispatch(String message) => dispatchBlocklyHostChannelMessage(
          gate: gate,
          message: message,
          initialise: () => initialisations += 1,
          forward: forwarded.add,
          reject: () => rejections += 1,
        );

        dispatch(ready);
        expect(initialisations, 0);
        expect(forwarded, isEmpty);

        gate.beginPage(hostEpoch: 101);
        dispatch(ready);
        dispatch(ready);
        gate.finishInitialisation(gate.generation, succeeded: true);
        dispatch(firstSnapshot);
        expect(initialisations, 1);
        expect(forwarded, <String>[firstSnapshot]);
        expect(rejections, 0);

        gate.beginPage(hostEpoch: 202);
        dispatch(ready);
        gate.finishInitialisation(gate.generation, succeeded: true);
        dispatch(firstSnapshot);
        dispatch(secondSnapshot);
        expect(initialisations, 2);
        expect(forwarded, <String>[firstSnapshot, secondSnapshot]);
        expect(rejections, 0);
      },
    );

    test('rejects malformed epochs and ignores superseded epochs', () {
      final BlocklyHostStartupGate gate = BlocklyHostStartupGate()
        ..beginPage(hostEpoch: 202);
      for (final String message in <String>[
        '{"version":1,"type":"snapshot"}',
        '{"version":1,"type":"snapshot","hostEpoch":"202"}',
        '{"version":2,"type":"hostReady"}',
        '{"version":1,"type":"hostReady","unexpected":true}',
        'not JSON',
      ]) {
        expect(
          gate.classify(message),
          BlocklyHostChannelDisposition.reject,
          reason: message,
        );
      }
      expect(
        gate.classify(firstSnapshot),
        BlocklyHostChannelDisposition.ignore,
      );
      expect(
        gate.classify(secondSnapshot),
        BlocklyHostChannelDisposition.forward,
      );
      expect(gate.classify(ready), BlocklyHostChannelDisposition.initialise);
    });

    test(
      'serializes JavaScript, channel, and navigation controller setup',
      () async {
        final Completer<void> javascript = Completer<void>();
        final Completer<void> channel = Completer<void>();
        final Completer<void> navigation = Completer<void>();
        final List<String> events = <String>[];

        final Future<void> setup = configureBlocklyControllerSequentially(
          isCancelled: () => false,
          enableJavaScript: () async {
            events.add('javascript');
            await javascript.future;
          },
          installJavaScriptChannel: () async {
            events.add('channel');
            await channel.future;
          },
          installNavigationDelegate: () async {
            events.add('navigation');
            await navigation.future;
          },
        );

        await Future<void>.delayed(Duration.zero);
        expect(events, <String>['javascript']);
        javascript.complete();
        await Future<void>.delayed(Duration.zero);
        expect(events, <String>['javascript', 'channel']);
        channel.complete();
        await Future<void>.delayed(Duration.zero);
        expect(events, <String>['javascript', 'channel', 'navigation']);
        navigation.complete();
        await setup;
      },
    );

    test('controller setup stops between phases after cancellation', () async {
      final Completer<void> javascript = Completer<void>();
      final List<String> events = <String>[];
      bool cancelled = false;
      final Future<void> setup = configureBlocklyControllerSequentially(
        isCancelled: () => cancelled,
        enableJavaScript: () async {
          events.add('javascript');
          await javascript.future;
        },
        installJavaScriptChannel: () async => events.add('channel'),
        installNavigationDelegate: () async => events.add('navigation'),
      );

      await Future<void>.delayed(Duration.zero);
      cancelled = true;
      javascript.complete();
      await setup;
      expect(events, <String>['javascript']);
    });

    test(
      'withholds the page load until asynchronous controller setup ends',
      () async {
        final Completer<void> setup = Completer<void>();
        final Completer<void> loadAllowed = Completer<void>();
        bool loaded = false;
        final Future<void> startup = loadBlocklyAssetAfterControllerSetup(
          setup: setup.future,
          waitUntilLoadAllowed: () => loadAllowed.future,
          isCancelled: () => false,
          load: () async {
            loaded = true;
          },
        );

        await Future<void>.delayed(Duration.zero);
        expect(loaded, isFalse);
        setup.complete();
        await Future<void>.delayed(Duration.zero);
        expect(loaded, isFalse);
        loadAllowed.complete();
        await startup;
        expect(loaded, isTrue);
      },
    );

    test('page load stays cancelled after setup or frame readiness', () async {
      for (final bool cancelDuringSetup in <bool>[true, false]) {
        final Completer<void> setup = Completer<void>();
        final Completer<void> loadAllowed = Completer<void>();
        bool cancelled = false;
        bool loaded = false;
        final Future<void> startup = loadBlocklyAssetAfterControllerSetup(
          setup: setup.future,
          waitUntilLoadAllowed: () => loadAllowed.future,
          isCancelled: () => cancelled,
          load: () async {
            loaded = true;
          },
        );

        if (cancelDuringSetup) cancelled = true;
        setup.complete();
        await Future<void>.delayed(Duration.zero);
        if (!cancelDuringSetup) cancelled = true;
        loadAllowed.complete();
        await startup;
        expect(loaded, isFalse, reason: 'cancelDuringSetup=$cancelDuringSetup');
      }
    });

    test(
      'guard owns startup errors and suppresses them after disposal',
      () async {
        for (final bool cancelled in <bool>[false, true]) {
          final Completer<void> mayReport = Completer<void>();
          final List<Object> errors = <Object>[];
          final Future<void> startup = runBlocklyStartupGuarded(
            startup: () async => throw StateError('setup failed'),
            waitUntilFailureCanBeReported: () => mayReport.future,
            isCancelled: () => cancelled,
            reportFailure: errors.add,
          );

          await Future<void>.delayed(Duration.zero);
          expect(errors, isEmpty);
          mayReport.complete();
          await startup;
          expect(errors, cancelled ? isEmpty : hasLength(1));
        }
      },
    );
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
      expect(
        isBlocklyAssetDocumentNavigation('about:blank'),
        isFalse,
        reason: 'the inert bootstrap page must not re-arm host readiness',
      );
      expect(
        isBlocklyAssetDocumentNavigation(
          'https://appassets.androidplatform.net/assets/'
          'assets/blockly/index.html',
        ),
        isTrue,
      );
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

  group('A-38 named MicroPython pins asset policy (FR-BLOCKS-1B)', () {
    late String script;

    setUpAll(() {
      script = File(
        '${appPackageRoot().path}/assets/blockly/pyble_blockly.js',
      ).readAsStringSync();
    });

    test('the GPIO slot declares the frozen pin-name pattern', () {
      expect(
        script,
        contains(r'^[A-Za-z][A-Za-z0-9_]{0,15}$'),
        reason:
            'FR-BLOCKS-1B freezes exactly this pin-name grammar for every '
            'GPIO slot in the sealed asset',
      );
    });

    test('codegen quotes pin names and keeps integers bare', () {
      expect(
        script,
        contains('Pin("'),
        reason:
            'a named pin must be emitted as a quoted Python string literal, '
            'e.g. Pin("LED", ...)',
      );
      expect(
        script,
        contains(r'/^(?:0|[1-9][0-9]*)$/'),
        reason:
            'the bare non-negative integer grammar must survive unchanged '
            'next to the name grammar',
      );
    });

    test('ships no per-board pin-name suggestions or defaults (CON-7)', () {
      for (final String token in <String>[
        'WL_GPIO',
        'EXT_GPIO',
        '"LED"',
        '"BOOT"',
        '"BUTTON"',
        '"NEOPIXEL"',
      ]) {
        expect(
          script,
          isNot(contains(token)),
          reason:
              'CON-7: the sealed asset must not hardcode board-specific pin '
              'names or suggestion lists ($token)',
        );
      }
    });
  });

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
