// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Local recovery consent and replacement seams. No transport implementation.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:pyble/app/providers.dart';
import 'package:pyble/pble/pble.dart';
import 'draft_recovery.dart';
import 'editor_document.dart';

class BoardTargetRequest {
  const BoardTargetRequest({
    required this.path,
    required this.run,
    required this.docName,
  });
  final String path;
  final bool run;
  final String docName;
}

/// Production injects ARB-backed dialogs through the root navigator. Missing
/// confirmation fails closed; controller tests can provide a recording choice.
final boardTargetConfirmationProvider =
    Provider<Future<bool> Function(BoardTargetRequest)?>((ref) => null);
final editorReplacementConfirmationProvider =
    Provider<Future<bool> Function()?>((ref) => null);

final editorVolatileReplacementConfirmationProvider =
    Provider<Future<bool> Function()?>((ref) => null);

class BoardActionCancelled implements Exception {
  const BoardActionCancelled();
}

/// A recovered path is historical context, never permission to overwrite a
/// board. Every explicit action is confirmed against its current destination.
Future<bool> confirmBoardTarget(
  Ref ref, {
  required String path,
  required bool run,
}) async {
  if (!ref.read(editorRecoveredDraftProvider)) return true;
  final int epoch = ref.read(editorDocumentEpochProvider);
  final connection = ref.read(connectionProvider);
  final stamp = connectionSessionStampOf(connection);
  final confirm = ref.read(boardTargetConfirmationProvider);
  if (confirm == null) return false;
  final accepted = await confirm(
    BoardTargetRequest(
      path: path,
      run: run,
      docName: ref.read(editorDocumentProvider).name,
    ),
  );
  return accepted &&
      ref.read(editorDocumentEpochProvider) == epoch &&
      identical(ref.read(connectionProvider), connection) &&
      identical(connectionSessionStampOf(connection), stamp);
}

Future<bool> confirmEditorReplacement(
  Ref ref, {
  required int expectedEpoch,
}) async {
  if (ref.read(editorDocumentEpochProvider) != expectedEpoch) return false;
  final recovery = ref.read(draftRecoveryProvider);
  if (recovery.status == DraftRecoveryStatus.disabled) return true;
  final document = ref.read(editorDocumentProvider);
  final meaningful =
      document.content.isNotEmpty ||
      document.name != kDefaultDocumentName ||
      document.boardPath != null;
  final needsChoice =
      recovery.status == DraftRecoveryStatus.decision ||
      (meaningful &&
          (document.dirty || recovery.status != DraftRecoveryStatus.saved));
  if (!needsChoice) return true;
  final confirm = ref.read(editorReplacementConfirmationProvider);
  if (confirm == null || !await confirm()) return false;
  return ref.read(editorDocumentEpochProvider) == expectedEpoch;
}

/// Preserve the live document on failure; volatile replacement needs its own
/// explicit decision bound to the same document and board session.
Future<bool> replaceEditorDocument(
  Ref ref,
  EditorDocument replacement, {
  required int expectedEpoch,
  bool Function()? isStillValid,
}) async {
  bool valid() =>
      ref.read(editorDocumentEpochProvider) == expectedEpoch &&
      (isStillValid?.call() ?? true);
  if (!valid()) return false;
  final controller = ref.read(draftRecoveryProvider.notifier);
  final replaced = await controller.replaceDocument(
    replacement,
    expectedEpoch: expectedEpoch,
    allowVolatile:
        ref.read(draftRecoveryProvider).status == DraftRecoveryStatus.volatile,
    isStillValid: isStillValid,
  );
  if (replaced ||
      !valid() ||
      ref.read(draftRecoveryProvider).status != DraftRecoveryStatus.failed) {
    return replaced;
  }
  final confirm = ref.read(editorVolatileReplacementConfirmationProvider);
  if (confirm == null || !await confirm() || !valid()) return false;
  controller.continueWithoutRecovery();
  return controller.replaceDocument(
    replacement,
    expectedEpoch: expectedEpoch,
    allowVolatile: true,
    isStillValid: isStillValid,
  );
}
