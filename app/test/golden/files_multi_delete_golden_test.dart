// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-30 / ADR-0043 [red] — adaptive visual coverage for Files regular-file
// multi-selection and its exact, non-atomic delete confirmation. Every board
// entry is an authored in-memory fixture and all filesystem access crosses the
// neutral Connection seam.

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/files/files.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';
import 'package:pyble/theme/theme.dart';

import '../support/recording_connection.dart';

const String _examplesFolder = 'examples';
const String _nestedFolder = 'assets';
const String _rootPythonFile = 'main.py';
const String _rootDataFile = 'classroom_notes.txt';
const String _protectedRootFile = 'pyble_conf.json';
const String _scratchRootFile = 'interrupted_upload.pbltmp';

const List<String> _longExampleFiles = <String>[
  'ambient_temperature_calibration_sequence.py',
  'greenhouse_humidity_alarm_controller.py',
  'motor_encoder_diagnostic_capture_sequence.py',
  'session_observations_and_measurements.csv',
  'wireless_status_dashboard_controller.py',
];

Uint8List _bytes(String value) => Uint8List.fromList(utf8.encode(value));

Future<RecordingConnection> _fixtureConnection() async {
  final RecordingConnection connection = RecordingConnection(
    initial: ConnState.ready,
  );

  await connection.mkdir('/$_examplesFolder');
  await connection.mkdir('/$_examplesFolder/$_nestedFolder');
  await connection.putFile('/$_rootPythonFile', _bytes("print('PyBLE')\n"));
  await connection.putFile(
    '/$_rootDataFile',
    _bytes('Session 4 observations\n'),
  );
  await connection.putFile(
    '/$_protectedRootFile',
    _bytes('{"fixture": true}\n'),
  );
  await connection.putFile(
    '/$_scratchRootFile',
    _bytes('incomplete transfer fixture\n'),
  );
  for (final String name in _longExampleFiles) {
    await connection.putFile(
      '/$_examplesFolder/$name',
      _bytes('# authored golden fixture: $name\n'),
    );
  }

  // Fixture construction is not part of the interaction under test.
  connection.operationLog.clear();
  connection.putFileCalls.clear();
  connection.mkdirCalls.clear();
  return connection;
}

Future<void> _pumpGoldenHost(
  WidgetTester tester, {
  required RecordingConnection connection,
  required Size size,
  double textScale = 1,
  bool highContrast = false,
}) async {
  tester.view.devicePixelRatio = 2;
  tester.view.physicalSize = size * 2;
  tester.view.viewInsets = const FakeViewPadding();
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetViewInsets);

  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[connectionProvider.overrideWithValue(connection)],
      child: MaterialApp(
        debugShowCheckedModeBanner: false,
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        theme: highContrast ? PybleTheme.highContrastLight : PybleTheme.light,
        highContrastTheme: PybleTheme.highContrastLight,
        builder: (BuildContext context, Widget? child) {
          final MediaQueryData media = MediaQuery.of(context);
          return MediaQuery(
            data: media.copyWith(
              highContrast: highContrast,
              textScaler: TextScaler.linear(textScale),
            ),
            child: child!,
          );
        },
        home: const Scaffold(body: FilesView()),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

AppLocalizations _l10n(WidgetTester tester) =>
    AppLocalizations.of(tester.element(find.byType(Scaffold).first));

Key _selectionKey(String name) => ValueKey<String>('fileSelect_$name');

Future<void> _openExamples(WidgetTester tester) async {
  await tester.tap(
    find.byKey(const ValueKey<String>('fileEntry_$_examplesFolder')),
  );
  await tester.pumpAndSettle();
}

Future<void> _enterSelection(WidgetTester tester) async {
  await tester.tap(find.byKey(kFilesSelectActionKey));
  await tester.pumpAndSettle();
}

Future<void> _toggleFile(WidgetTester tester, String name) async {
  final Finder checkbox = find.byKey(_selectionKey(name));
  await tester.ensureVisible(checkbox);
  await tester.pumpAndSettle();
  await tester.tap(checkbox);
  await tester.pump();
}

Future<void> _expectGolden(WidgetTester tester, String name) => expectLater(
  find.byType(MaterialApp),
  matchesGoldenFile('goldens/$name.png'),
);

void main() {
  group('A-30 Files visible-file multi-delete goldens', () {
    testWidgets(
      '320 dp pane reflows the contextual selection bar without selecting folders or locked files',
      (WidgetTester tester) async {
        final RecordingConnection connection = await _fixtureConnection();
        addTearDown(connection.dispose);

        await _pumpGoldenHost(
          tester,
          connection: connection,
          size: const Size(320, 700),
        );
        final AppLocalizations l10n = _l10n(tester);

        await _enterSelection(tester);
        await _toggleFile(tester, _rootDataFile);
        await _toggleFile(tester, _rootPythonFile);

        expect(find.byKey(kFilesSelectionBarKey), findsOneWidget);
        expect(find.text(l10n.filesSelectionSelectedCount(2)), findsOneWidget);
        expect(find.byKey(kFilesSelectAllShownKey), findsOneWidget);
        expect(find.byKey(kFilesBulkDeleteActionKey), findsOneWidget);
        expect(find.text(l10n.filesSelectionFilesOnly), findsOneWidget);
        expect(find.byKey(_selectionKey(_examplesFolder)), findsNothing);
        expect(find.byKey(_selectionKey(_protectedRootFile)), findsNothing);
        expect(find.byKey(_selectionKey(_scratchRootFile)), findsNothing);
        expect(connection.deleteCalls, isEmpty);

        await _expectGolden(tester, 'files_multi_delete_320_selection_context');
      },
      tags: const <String>['golden'],
    );

    testWidgets(
      'iPad confirmation shows the exact folder and several ordered long filenames',
      (WidgetTester tester) async {
        final RecordingConnection connection = await _fixtureConnection();
        addTearDown(connection.dispose);

        await _pumpGoldenHost(
          tester,
          connection: connection,
          size: const Size(1024, 768),
        );
        final AppLocalizations l10n = _l10n(tester);
        await _openExamples(tester);
        await _enterSelection(tester);

        final List<String> selected = _longExampleFiles.take(4).toList();
        for (final String name in selected) {
          await _toggleFile(tester, name);
        }
        await tester.tap(find.byKey(kFilesBulkDeleteActionKey));
        await tester.pumpAndSettle();

        final Finder dialog = find.byType(AlertDialog);
        expect(dialog, findsOneWidget);
        expect(
          find.descendant(
            of: dialog,
            matching: find.text(
              l10n.filesDeleteSelectedConfirmTitle(selected.length),
            ),
          ),
          findsOneWidget,
        );
        expect(
          find.descendant(
            of: dialog,
            matching: find.text(
              l10n.filesDeleteSelectedConfirmBody('/$_examplesFolder'),
            ),
          ),
          findsOneWidget,
        );
        expect(
          find.descendant(
            of: dialog,
            matching: find.text(l10n.filesDeleteSelectedListLabel),
          ),
          findsOneWidget,
        );
        for (final String name in selected) {
          expect(
            find.descendant(of: dialog, matching: find.text(name)),
            findsOneWidget,
          );
        }
        final Finder cancel = find.descendant(
          of: dialog,
          matching: find.text(l10n.commonCancel),
        );
        expect(cancel, findsOneWidget);
        expect(Focus.of(tester.element(cancel)).hasFocus, isTrue);
        expect(connection.deleteCalls, isEmpty);

        await _expectGolden(
          tester,
          'files_multi_delete_ipad_exact_confirmation',
        );
      },
      tags: const <String>['golden'],
    );

    testWidgets(
      'compact 2x high-contrast confirmation remains scrollable and actionable',
      (WidgetTester tester) async {
        final RecordingConnection connection = await _fixtureConnection();
        addTearDown(connection.dispose);

        await _pumpGoldenHost(
          tester,
          connection: connection,
          size: const Size(390, 844),
          textScale: 2,
          highContrast: true,
        );
        final AppLocalizations l10n = _l10n(tester);
        await _openExamples(tester);
        await _enterSelection(tester);
        await tester.tap(find.byKey(kFilesSelectAllShownKey));
        await tester.pumpAndSettle();

        expect(
          find.text(l10n.filesSelectionSelectedCount(_longExampleFiles.length)),
          findsOneWidget,
        );
        expect(find.byKey(_selectionKey(_nestedFolder)), findsNothing);
        await tester.tap(find.byKey(kFilesBulkDeleteActionKey));
        await tester.pumpAndSettle();

        final Finder dialog = find.byType(AlertDialog);
        expect(dialog, findsOneWidget);
        final Finder title = find.descendant(
          of: dialog,
          matching: find.text(
            l10n.filesDeleteSelectedConfirmTitle(_longExampleFiles.length),
          ),
        );
        expect(title, findsOneWidget);
        expect(title.hitTestable(), findsOneWidget);
        expect(
          find
              .descendant(of: dialog, matching: find.text(l10n.commonCancel))
              .hitTestable(),
          findsOneWidget,
        );
        expect(
          find
              .descendant(of: dialog, matching: find.text(l10n.commonDelete))
              .hitTestable(),
          findsOneWidget,
        );
        expect(connection.deleteCalls, isEmpty);

        await _expectGolden(
          tester,
          'files_multi_delete_390_2x_high_contrast_confirmation',
        );
      },
      tags: const <String>['golden'],
    );
  });
}
