// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/pble/pble.dart';

import '../support/fake_readiness_seam.dart';
import '../support/recording_connection.dart';

final class _ScriptedBundleFailureConnection extends RecordingConnection {
  _ScriptedBundleFailureConnection({
    this.failPutAt,
    this.putError = const ENoSpc('filesystem full'),
    this.runError,
  }) : super(initial: ConnState.ready);

  final int? failPutAt;
  final PbleException putError;
  final PbleException? runError;

  int _putCount = 0;

  @override
  Future<void> putFile(String path, Uint8List bytes, {ProgressCb? onProgress}) {
    _putCount++;
    if (_putCount == failPutAt) injectError(putError);
    return super.putFile(path, bytes, onProgress: onProgress);
  }

  @override
  Future<void> runFile(String path) {
    final PbleException? error = runError;
    if (error != null) injectError(error);
    return super.runFile(path);
  }
}

final class _GatedPutConnection extends RecordingConnection {
  _GatedPutConnection({required this.pauseAfterPut})
    : super(initial: ConnState.ready);

  final int pauseAfterPut;
  final Completer<void> paused = Completer<void>();
  final Completer<void> release = Completer<void>();

  int _putCount = 0;

  @override
  Future<void> putFile(
    String path,
    Uint8List bytes, {
    ProgressCb? onProgress,
  }) async {
    await super.putFile(path, bytes, onProgress: onProgress);
    _putCount++;
    if (_putCount == pauseAfterPut) {
      paused.complete();
      await release.future;
    }
  }
}

void main() {
  ProviderContainer bind(RecordingConnection connection) {
    final ProviderContainer container = ProviderContainer(
      overrides: <Override>[connectionProvider.overrideWithValue(connection)],
    );
    addTearDown(container.dispose);
    return container;
  }

  ProviderContainer bindManager(PbleConnectionManager manager) {
    final ProviderContainer container = ProviderContainer(
      overrides: <Override>[
        connectionManagerProvider.overrideWithValue(manager),
      ],
    );
    addTearDown(container.dispose);
    addTearDown(manager.dispose);
    return container;
  }

  group('ADR-0013 shared file-backed ProgramActions', () {
    test('saveSource uploads the exact normalized UTF-8 source', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);

      final String path = await container
          .read(programActionsProvider)
          .saveSource(path: '/visual.py', source: 'print(\u201cHello\u201d)\n');

      expect(path, '/visual.py');
      expect(connection.putFileCalls, hasLength(1));
      expect(connection.putFileCalls.single.path, '/visual.py');
      expect(
        utf8.decode(connection.putFileCalls.single.bytes),
        'print("Hello")\n',
      );
    });

    test(
      'runSourceFile uploads first, then runs that same board path',
      () async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final ProviderContainer container = bind(connection);
        final String source = List<String>.filled(
          400,
          'print("large")',
        ).join('\n');
        expect(utf8.encode(source).length, greaterThan(2048));

        await container
            .read(programActionsProvider)
            .runSourceFile(path: '/large.py', source: source);

        expect(connection.putFileCalls, hasLength(1));
        expect(connection.putFileCalls.single.path, '/large.py');
        expect(utf8.decode(connection.putFileCalls.single.bytes), source);
        expect(connection.runFileCalls, <String>['/large.py']);
        expect(
          connection.runSourceCalls,
          isEmpty,
          reason: 'normal programs must not use the 2 KiB inline-source path',
        );
      },
    );

    test('a failed upload never invokes runFile', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      connection.injectError(const ENoSpc('filesystem full'));

      await expectLater(
        container
            .read(programActionsProvider)
            .runSourceFile(path: '/large.py', source: 'print(1)\n'),
        throwsA(isA<ENoSpc>()),
      );

      expect(connection.runFileCalls, isEmpty);
    });

    test('bundle writes source then raw companion then runs', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      const String companion =
          '{"workspace":{"text":"Keep \u201ccurly data\u201d"}}';

      await container
          .read(programActionsProvider)
          .runSourceBundle(
            path: '/blocks.py',
            source: 'print(\u201cHello\u201d)\n',
            companionPath: '/blocks.py.pyble-blocks.json',
            companionJson: companion,
          );

      expect(connection.operationLog, <String>[
        'putFile:/blocks.py',
        'putFile:/blocks.py.pyble-blocks.json',
        'runFile:/blocks.py',
      ]);
      expect(
        utf8.decode(connection.putFileCalls[0].bytes),
        'print(\u201cHello\u201d)\n',
        reason: 'Blocks bundle source must stay byte-exact',
      );
      expect(
        utf8.decode(connection.putFileCalls[1].bytes),
        companion,
        reason: 'opaque workspace text must not be punctuation-normalized',
      );
    });

    test('source PUT failure attempts no sidecar and never runs', () async {
      final _ScriptedBundleFailureConnection connection =
          _ScriptedBundleFailureConnection(failPutAt: 1);
      final ProviderContainer container = bind(connection);

      await expectLater(
        container
            .read(programActionsProvider)
            .runSourceBundle(
              path: '/blocks.py',
              source: 'print(1)\n',
              companionPath: '/blocks.py.pyble-blocks.json',
              companionJson: '{}',
            ),
        throwsA(isA<ENoSpc>()),
      );

      expect(connection.operationLog, <String>['putFile:/blocks.py']);
      expect(
        connection.putFileCalls.map((PutFileCall call) => call.path),
        <String>['/blocks.py'],
      );
      expect(connection.runFileCalls, isEmpty);
      await expectLater(
        connection.getFile('/blocks.py'),
        throwsA(isA<ENoEnt>()),
      );
    });

    test(
      'sidecar PUT failure reports an incomplete pair and never runs',
      () async {
        const ENoSpc sidecarError = ENoSpc('sidecar filesystem full');
        final _ScriptedBundleFailureConnection connection =
            _ScriptedBundleFailureConnection(
              failPutAt: 2,
              putError: sidecarError,
            );
        final ProviderContainer container = bind(connection);

        await expectLater(
          container
              .read(programActionsProvider)
              .runSourceBundle(
                path: '/blocks.py',
                source: 'print(2)\n',
                companionPath: '/blocks.py.pyble-blocks.json',
                companionJson: '{"workspace":{}}',
              ),
          throwsA(
            isA<ProgramBundleIncomplete>()
                .having(
                  (ProgramBundleIncomplete error) => error.sourcePath,
                  'sourcePath',
                  '/blocks.py',
                )
                .having(
                  (ProgramBundleIncomplete error) => error.companionPath,
                  'companionPath',
                  '/blocks.py.pyble-blocks.json',
                )
                .having(
                  (ProgramBundleIncomplete error) => error.cause,
                  'cause',
                  same(sidecarError),
                ),
          ),
        );

        expect(connection.operationLog, <String>[
          'putFile:/blocks.py',
          'putFile:/blocks.py.pyble-blocks.json',
        ]);
        expect(connection.runFileCalls, isEmpty);
        expect(
          utf8.decode(await connection.getFile('/blocks.py')),
          'print(2)\n',
        );
        await expectLater(
          connection.getFile('/blocks.py.pyble-blocks.json'),
          throwsA(isA<ENoEnt>()),
        );
      },
    );

    test('run failure is attempted only after a valid pair exists', () async {
      const EBusy runError = EBusy('already running');
      final _ScriptedBundleFailureConnection connection =
          _ScriptedBundleFailureConnection(runError: runError);
      final ProviderContainer container = bind(connection);
      const String companion = '{"workspace":{"blocks":[]}}';

      await expectLater(
        container
            .read(programActionsProvider)
            .runSourceBundle(
              path: '/blocks.py',
              source: 'print(3)\n',
              companionPath: '/blocks.py.pyble-blocks.json',
              companionJson: companion,
            ),
        throwsA(same(runError)),
      );

      expect(connection.operationLog, <String>[
        'putFile:/blocks.py',
        'putFile:/blocks.py.pyble-blocks.json',
        'runFile:/blocks.py',
      ]);
      expect(connection.runFileCalls, <String>['/blocks.py']);
      expect(utf8.decode(await connection.getFile('/blocks.py')), 'print(3)\n');
      expect(
        utf8.decode(await connection.getFile('/blocks.py.pyble-blocks.json')),
        companion,
      );
    });

    test('overlong source path fails before any board mutation', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      final String path = '/${'x' * 125}.py';
      expect(utf8.encode(path).length, greaterThan(128));

      await expectLater(
        container
            .read(programActionsProvider)
            .saveSourceBundle(
              path: path,
              source: 'print(1)\n',
              companionPath: '/blocks.py.pyble-blocks.json',
              companionJson: '{}',
            ),
        throwsA(
          isA<ProgramBundlePathTooLong>().having(
            (ProgramBundlePathTooLong error) => error.path,
            'path',
            path,
          ),
        ),
      );
      expect(connection.operationLog, isEmpty);
      expect(connection.putFileCalls, isEmpty);
    });

    test('overlong companion path fails before any board mutation', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);
      final String path = '/${'x' * 112}.py';
      expect(utf8.encode(path).length, lessThanOrEqualTo(128));
      expect(utf8.encode('$path.pyble-blocks.json').length, greaterThan(128));

      await expectLater(
        container
            .read(programActionsProvider)
            .saveSourceBundle(
              path: path,
              source: 'print(1)\n',
              companionPath: '$path.pyble-blocks.json',
              companionJson: '{}',
            ),
        throwsA(isA<ProgramBundlePathTooLong>()),
      );
      expect(connection.operationLog, isEmpty);
      expect(connection.putFileCalls, isEmpty);
    });

    test(
      'non-canonical, reserved, and non-Python sources fail before mutation',
      () async {
        for (final String path in <String>[
          'relative.py',
          '/notes.txt',
          '/../main.py',
          '/lib/../main.py',
          '/lib//main.py',
          r'/lib\main.py',
          '/main.py.pbltmp',
          '/pyble_agent.py',
          '/pble_config.py',
          '/_boot.py',
          '/boot.py',
        ]) {
          final RecordingConnection connection = RecordingConnection(
            initial: ConnState.ready,
          );
          final ProviderContainer container = bind(connection);

          await expectLater(
            container
                .read(programActionsProvider)
                .saveSourceBundle(
                  path: path,
                  source: 'print(1)\n',
                  companionPath: '$path.pyble-blocks.json',
                  companionJson: '{}',
                ),
            throwsA(isA<ProgramBundlePathTooLong>()),
            reason: path,
          );
          expect(connection.operationLog, isEmpty, reason: path);
          expect(connection.putFileCalls, isEmpty, reason: path);
        }
      },
    );

    test('a non-adjacent companion fails before any board mutation', () async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer container = bind(connection);

      await expectLater(
        container
            .read(programActionsProvider)
            .saveSourceBundle(
              path: '/blocks.py',
              source: 'print(1)\n',
              companionPath: '/other.py.pyble-blocks.json',
              companionJson: '{}',
            ),
        throwsA(
          isA<ProgramBundlePathTooLong>().having(
            (ProgramBundlePathTooLong error) => error.path,
            'path',
            '/other.py.pyble-blocks.json',
          ),
        ),
      );
      expect(connection.operationLog, isEmpty);
      expect(connection.putFileCalls, isEmpty);
    });

    test(
      'a board swap after source PUT cannot send the sidecar to the new board',
      () async {
        final _GatedPutConnection first = _GatedPutConnection(pauseAfterPut: 1);
        final RecordingConnection second = RecordingConnection(
          initial: ConnState.ready,
        );
        final Map<String, Connection> boards = <String, Connection>{
          'first': first,
          'second': second,
        };
        final PbleConnectionManager manager = PbleConnectionManager(
          scanner: FakeScanner(),
          readiness: FakeSeamReadiness(BleReadiness.ready),
          connectionFactory: (String id) async => boards[id]!,
        );
        final ProviderContainer container = bindManager(manager);
        await manager.connect('first');

        final Future<void> action = container
            .read(programActionsProvider)
            .runSourceBundle(
              path: '/blocks.py',
              source: 'print(1)\n',
              companionPath: '/blocks.py.pyble-blocks.json',
              companionJson: '{"workspace":{}}',
            );
        await first.paused.future;

        await manager.connect('second');
        first.release.complete();

        await expectLater(
          action,
          throwsA(
            isA<ProgramBundleSessionChanged>().having(
              (ProgramBundleSessionChanged error) => error.nextOperation,
              'nextOperation',
              ProgramBundleNextOperation.writeCompanion,
            ),
          ),
        );
        expect(first.operationLog, <String>['putFile:/blocks.py']);
        expect(second.operationLog, isEmpty);
      },
    );

    test(
      'disconnect after the pair commit prevents Run on another session',
      () async {
        final _GatedPutConnection first = _GatedPutConnection(pauseAfterPut: 2);
        final PbleConnectionManager manager = PbleConnectionManager(
          scanner: FakeScanner(),
          readiness: FakeSeamReadiness(BleReadiness.ready),
          connectionFactory: (String id) async => first,
        );
        final ProviderContainer container = bindManager(manager);
        await manager.connect('first');

        final Future<void> action = container
            .read(programActionsProvider)
            .runSourceBundle(
              path: '/blocks.py',
              source: 'print(2)\n',
              companionPath: '/blocks.py.pyble-blocks.json',
              companionJson: '{"workspace":{}}',
            );
        await first.paused.future;

        await manager.disconnect();
        first.release.complete();

        await expectLater(
          action,
          throwsA(
            isA<ProgramBundleSessionChanged>().having(
              (ProgramBundleSessionChanged error) => error.nextOperation,
              'nextOperation',
              ProgramBundleNextOperation.runFile,
            ),
          ),
        );
        expect(first.operationLog, <String>[
          'putFile:/blocks.py',
          'putFile:/blocks.py.pyble-blocks.json',
        ]);
        expect(first.runFileCalls, isEmpty);
      },
    );
  });
}
