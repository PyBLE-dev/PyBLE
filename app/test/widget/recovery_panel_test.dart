// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/editor/recovery_panel.dart';
import 'package:pyble/pble/pble.dart';

import '../support/feature_harness.dart';

void main() {
  testWidgets(
    'preview requires an explicit local Restore or confirmed Discard',
    (WidgetTester tester) async {
      int restored = 0;
      int discarded = 0;
      final FakeConnection fake = FakeConnection();
      addTearDown(fake.dispose);
      await pumpSurface(
        tester,
        RecoveryPanel(
          name: 'main.py',
          content: 'print("retained")\n',
          checkpointTime: DateTime.utc(2026, 10, 31, 12),
          onRestore: () async {
            restored += 1;
          },
          onDiscard: () async {
            discarded += 1;
          },
        ),
        connection: fake,
      );
      expect(find.text('print("retained")\n'), findsOneWidget);
      expect(restored, 0);
      expect(discarded, 0);
      await tester.tap(find.byKey(kRecoveryDiscardKey));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(discarded, 0);
      expect(find.byKey(kRecoveryRestoreKey), findsOneWidget);
      await tester.tap(find.byKey(kRecoveryDiscardKey));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(kRecoveryConfirmDiscardKey));
      await tester.pumpAndSettle();
      expect(discarded, 1);
      await tester.tap(find.byKey(kRecoveryRestoreKey));
      await tester.pumpAndSettle();
      expect(restored, 1);
    },
  );

  testWidgets(
    'restored preview stays readable offline and copies only on tap',
    (WidgetTester tester) async {
      int clipboardWrites = 0;
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (MethodCall call) async {
          if (call.method == 'Clipboard.setData') clipboardWrites += 1;
          return null;
        },
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          SystemChannels.platform,
          null,
        ),
      );
      final FakeConnection fake = FakeConnection();
      addTearDown(fake.dispose);
      await pumpSurface(
        tester,
        RecoveryPanel(
          name: 'main.py',
          content: 'print(42)',
          checkpointTime: DateTime.utc(2026),
          restored: true,
          onRestore: () async {},
          onDiscard: () async {},
        ),
        connection: fake,
      );
      expect(find.text('print(42)'), findsOneWidget);
      expect(find.byKey(kRecoveryRestoreKey), findsNothing);
      expect(clipboardWrites, 0);
      await tester.tap(find.byKey(kRecoveryCopyKey));
      await tester.pump();
      expect(clipboardWrites, 1);
    },
  );

  testWidgets(
    'preview and destructive confirmation fit 2x text with keyboard',
    (WidgetTester tester) async {
      tester.platformDispatcher.textScaleFactorTestValue = 2;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      tester.view.viewInsets = const FakeViewPadding(bottom: 250);
      addTearDown(tester.view.resetViewInsets);
      final FakeConnection fake = FakeConnection();
      addTearDown(fake.dispose);
      await pumpSurface(
        tester,
        RecoveryPanel(
          name: 'unicode_µ.py',
          content: List<String>.filled(50, 'print("example")').join('\n'),
          checkpointTime: DateTime.utc(2026),
          onRestore: () async {},
          onDiscard: () async {},
        ),
        connection: fake,
        size: const Size(400, 800),
      );
      await tester.ensureVisible(find.byKey(kRecoveryDiscardKey));
      await tester.tap(find.byKey(kRecoveryDiscardKey));
      await tester.pumpAndSettle();
      expect(find.byKey(kRecoveryConfirmDiscardKey), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('board confirmation identifies destination and explicit Run', (
    WidgetTester tester,
  ) async {
    bool? approved;
    final FakeConnection fake = FakeConnection();
    addTearDown(fake.dispose);
    await pumpSurface(
      tester,
      Builder(
        builder: (BuildContext context) => TextButton(
          onPressed: () async {
            approved = await confirmRecoveryBoardTarget(
              context,
              path: '/main.py',
              run: true,
            );
          },
          child: const Text('open'),
        ),
      ),
      connection: fake,
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    expect(find.textContaining('/main.py'), findsOneWidget);
    expect(find.textContaining('run'), findsWidgets);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(approved, isFalse);
  });
}
