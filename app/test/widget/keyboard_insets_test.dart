// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pyble/console/console.dart';
import 'package:pyble/pble/pble.dart';

import '../support/shell_harness.dart';

const MethodChannel _channel = MethodChannel('dev.pyble/keyboard/insets');

void main() {
  final List<MethodCall> calls = <MethodCall>[];
  setUp(() {
    calls.clear();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_channel, (MethodCall call) async {
          calls.add(call);
          return null;
        });
  });
  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_channel, null);
  });

  int generation() =>
      (calls.lastWhere((MethodCall call) => call.method == 'observe').arguments
          as int);

  Future<void> sendReport(
    WidgetTester tester,
    double bottom, {
    int? epoch,
  }) async {
    await tester.binding.defaultBinaryMessenger.handlePlatformMessage(
      _channel.name,
      _channel.codec.encodeMethodCall(
        MethodCall('inset', <String, Object>{
          'generation': epoch ?? generation(),
          'bottom': bottom,
        }),
      ),
      (_) {},
    );
  }

  Future<void> report(WidgetTester tester, double bottom, {int? epoch}) async {
    await sendReport(tester, bottom, epoch: epoch);
    await tester.pump();
  }

  MediaQueryData geometry(WidgetTester tester) =>
      MediaQuery.of(tester.element(find.byType(Scaffold).first));

  testWidgets(
    'iPad palette reopening keeps Expand above the actual keyboard',
    (WidgetTester tester) async {
      await pumpShell(
        tester,
        connection: fakeConnection(initial: ConnState.ready),
      );
      expect(
        calls.where((MethodCall call) => call.method == 'observe'),
        isNotEmpty,
      );
      final EditableText editor = tester.widget(
        find.byType(EditableText).first,
      );
      editor.controller.text = '# retained across native geometry';
      editor.controller.selection = const TextSelection.collapsed(offset: 5);
      await report(tester, 81.5);
      expect(geometry(tester).viewInsets.bottom, 81.5);
      await report(tester, 498);
      expect(geometry(tester).viewInsets.bottom, 498);
      expect(
        tester.getRect(find.byKey(kConsoleStripToggleKey)).bottom,
        lessThanOrEqualTo(1024 - 498),
      );
      expect(find.byKey(kConsoleStripToggleKey).hitTestable(), findsOneWidget);
      expect(editor.controller.text, '# retained across native geometry');
      expect(
        editor.controller.selection,
        const TextSelection.collapsed(offset: 5),
      );
      expect(tester.takeException(), isNull);
    },
    variant: TargetPlatformVariant.only(TargetPlatform.iOS),
  );

  testWidgets(
    'native guide keeps the Blocks host and dismissal control usable',
    (WidgetTester tester) async {
      const MethodChannel keyboard = MethodChannel('dev.pyble/keyboard');
      final List<String> requests = <String>[];
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        keyboard,
        (MethodCall call) async => requests.add(call.method),
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          keyboard,
          null,
        ),
      );
      await pumpShell(
        tester,
        connection: fakeConnection(initial: ConnState.ready),
      );
      await tester.tap(
        find.descendant(
          of: find.byType(NavigationRail),
          matching: find.text('Blocks'),
        ),
      );
      await tester.pump();
      final Finder workspace = find.byKey(
        const ValueKey<String>('blocksWorkspaceHost-0'),
      );
      final Element host = tester.element(workspace);
      await report(tester, 498);
      expect(
        tester.getRect(find.byKey(kConsoleStripToggleKey)).bottom,
        lessThanOrEqualTo(1024 - 498),
      );
      await tester.tap(find.byKey(kConsoleStripToggleKey));
      await tester.pump();
      expect(requests, <String>['dismissKeyboard']);
      expect(
        tester
            .widget<ConsoleStripView>(find.byType(ConsoleStripView))
            .collapsed,
        isTrue,
      );
      expect(tester.element(workspace), same(host));
      await report(tester, 0);
      expect(
        tester
            .widget<ConsoleStripView>(find.byType(ConsoleStripView))
            .collapsed,
        isFalse,
      );
      expect(tester.element(workspace), same(host));
      expect(tester.takeException(), isNull);
    },
    variant: TargetPlatformVariant.only(TargetPlatform.iOS),
  );

  testWidgets(
    'guide and Flutter insets combine by maximum and restore padding',
    (WidgetTester tester) async {
      await pumpShell(
        tester,
        connection: fakeConnection(initial: ConnState.ready),
      );
      tester.view.viewPadding = const FakeViewPadding(bottom: 40);
      tester.view.padding = const FakeViewPadding(bottom: 40);
      tester.view.viewInsets = const FakeViewPadding(bottom: 996);
      addTearDown(tester.view.resetViewPadding);
      addTearDown(tester.view.resetPadding);
      addTearDown(tester.view.resetViewInsets);
      await tester.pump();
      await report(tester, 498);
      expect(geometry(tester).viewInsets.bottom, 498);
      expect(geometry(tester).padding.bottom, 0);
      await report(tester, 81.5);
      expect(geometry(tester).viewInsets.bottom, 498);
      tester.view.resetViewInsets();
      await tester.pump();
      expect(geometry(tester).viewInsets.bottom, 81.5);
      await report(tester, 0);
      expect(geometry(tester).viewInsets.bottom, 0);
      expect(geometry(tester).padding.bottom, 20);
    },
    variant: TargetPlatformVariant.only(TargetPlatform.iOS),
  );

  testWidgets(
    'post-metrics refresh recovers a guide value that preceded window resizing',
    (WidgetTester tester) async {
      await pumpShell(
        tester,
        connection: fakeConnection(initial: ConnState.ready),
        surface: const ShellSurface('short_window', Size(1366, 600), 2),
      );
      await report(tester, 650);
      expect(geometry(tester).viewInsets.bottom, 0);
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(_channel, (
        MethodCall call,
      ) async {
        calls.add(call);
        if (call.method == 'observe') {
          // Native observe returns a current snapshot even when unchanged.
          await sendReport(tester, 650, epoch: call.arguments as int);
        }
        return null;
      });
      tester.view.physicalSize = const Size(2732, 2048);
      await tester.pump();
      await tester.pump();
      expect(geometry(tester).viewInsets.bottom, 650);
      expect(
        tester.getRect(find.byKey(kConsoleStripToggleKey)).bottom,
        lessThanOrEqualTo(1024 - 650),
      );
      expect(tester.takeException(), isNull);
    },
    variant: TargetPlatformVariant.only(TargetPlatform.iOS),
  );

  testWidgets(
    'background resets observation and stale or invalid reports are inert',
    (WidgetTester tester) async {
      await pumpShell(
        tester,
        connection: fakeConnection(initial: ConnState.ready),
      );
      final int old = generation();
      await report(tester, 498);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump();
      expect(geometry(tester).viewInsets.bottom, 0);
      await report(tester, 498, epoch: old);
      expect(geometry(tester).viewInsets.bottom, 0);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pump();
      expect(generation(), isNot(old));
      await report(tester, 498, epoch: old);
      await report(tester, -1);
      await report(tester, double.infinity);
      await report(tester, 2048);
      expect(geometry(tester).viewInsets.bottom, 0);
      await report(tester, 70.5);
      expect(geometry(tester).viewInsets.bottom, 70.5);
      await tester.pumpWidget(const SizedBox());
      expect(calls.last.method, 'stop');
    },
    variant: TargetPlatformVariant.only(TargetPlatform.iOS),
  );

  testWidgets(
    'Android retains ordinary Flutter keyboard geometry',
    (WidgetTester tester) async {
      await pumpShell(
        tester,
        connection: fakeConnection(initial: ConnState.ready),
      );
      expect(calls, isEmpty);
      tester.view.viewInsets = const FakeViewPadding(bottom: 808);
      addTearDown(tester.view.resetViewInsets);
      await tester.pump();
      expect(geometry(tester).viewInsets.bottom, 404);
    },
    variant: TargetPlatformVariant.only(TargetPlatform.android),
  );
}
