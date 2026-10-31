// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Two launches of an isolated qualification application exercise actual
/// platform storage. Run seed, terminate the process, then run verify with the
/// same application ID/data container. This uses a recording board seam and
/// does not qualify physical BLE or a store-distributed binary.
library;

import 'dart:io';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:pyble/app/providers.dart';
import 'package:pyble/data/draft_repository.dart';
import 'package:pyble/data/drift_draft_repository.dart';
import 'package:pyble/editor/board_target_guard.dart';
import 'package:pyble/editor/draft_recovery.dart';
import 'package:pyble/editor/editor_document.dart';
import 'package:pyble/editor/save_controller.dart';
import 'package:pyble/pble/pble.dart';
import '../test/support/recording_connection.dart';

const _source = '# recovery qualification — ทดสอบ\nprint(“exact text”)\n';
const _phase = String.fromEnvironment(
  'PYBLE_RECOVERY_TEST_PHASE',
  defaultValue: 'seed',
);

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('platform durable recovery ($_phase)', (tester) async {
    final directory = await getApplicationSupportDirectory();
    final file = File('${directory.path}/qualification-current-draft.sqlite');
    final repository = await DriftDraftRepository.open(file);
    try {
      final existing = await repository.load();
      if (_phase == 'seed') {
        await repository.write(
          DraftSnapshot(
            name: 'qualification.py',
            content: _source,
            originPath: '/previous-board/qualification.py',
            generation: existing.generation + 1,
            checkpointTime: DateTime.now().toUtc(),
          ),
          expectedGeneration: existing.generation,
        );
        expect((await repository.load()).snapshot!.content, _source);
      } else {
        expect(_phase, 'verify');
        expect(
          existing.snapshot,
          isNotNull,
          reason: 'The seed must survive a separate app process launch.',
        );
        final connection = RecordingConnection(initial: ConnState.ready);
        final container = ProviderContainer(
          overrides: [
            draftRepositoryProvider.overrideWithValue(repository),
            connectionProvider.overrideWithValue(connection),
            boardTargetConfirmationProvider.overrideWithValue(
              (_) async => false,
            ),
          ],
        );
        try {
          final recovery = container.read(draftRecoveryProvider.notifier);
          await recovery.start();
          expect(
            container.read(draftRecoveryProvider).status,
            DraftRecoveryStatus.decision,
          );
          expect(recovery.restore(), isTrue);
          expect(container.read(editorDocumentProvider).content, _source);
          expect(container.read(editorDocumentProvider).boardPath, isNull);
          expect(container.read(editorDocumentProvider).dirty, isTrue);
          expect(connection.putFileCalls, isEmpty);
          expect(connection.runFileCalls, isEmpty);
          await expectLater(
            container.read(saveControllerProvider).save(),
            throwsA(isA<BoardActionCancelled>()),
          );
          expect(connection.putFileCalls, isEmpty);
        } finally {
          container.dispose();
        }
      }
    } finally {
      await repository.close();
    }
  });
}
