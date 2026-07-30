// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-20 — the editor SAVE seam (specs.md FR-EDIT-2, ADR-0010, TDD §11.6a).
///
/// Writes the current [EditorDocument] buffer to the board through the abstract
/// [Connection] (CON-8) and marks the buffer saved on success.
///
/// Two rules this seam exists to enforce, both of which the pre-existing
/// files-surface upload got wrong:
///
///   * **Save targets the document's OWN [EditorDocument.boardPath]** when it has
///     one. The files-surface upload writes to `cwd/name`, so a file opened from
///     `/lib/util.py` and saved after the explorer had moved (or after a
///     reconnect, which resets `cwd` to `fs_root`) silently created a NEW
///     `/util.py` while leaving the edited file untouched — and then re-bound the
///     document to the wrong path, making the damage sticky.
///   * **A save either succeeds or throws.** The typed [PbleException] propagates
///     so the caller can surface it; a save is never reported as done when the
///     bytes did not land. Success is CRC-verified end-to-end by the seam.
///
/// Binds to no transport type and imports no `lib/ble` (CON-8, D2).
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/pble/pble.dart';

import 'editor_document.dart';
import 'program_actions.dart';
import 'smart_punctuation.dart';

/// The board path a save would write to, for the given [doc].
///
/// A document opened from (or previously saved to) the board keeps its own
/// absolute path. A never-saved buffer lands at the filesystem root under its
/// display name — an ASCII technical identifier, never localized (FR-I18N-4).
String saveTargetFor(EditorDocument doc) {
  return boardPathForDocument(doc);
}

/// Imperative save controller. Holds no state: it reads the live [Connection]
/// and the current document through [Ref] on each call, so it always writes the
/// current buffer to the current board.
class SaveController {
  const SaveController(this._ref);

  final Ref _ref;

  /// Writes the current buffer to the board and marks it saved.
  ///
  /// Returns the board path written. A typed [PbleException] is NEVER swallowed —
  /// it propagates for the caller to surface (FR-EDIT-2, FR-RUN-3), and the
  /// buffer stays dirty so the user does not believe work was persisted.
  Future<String> save({ProgressCb? onProgress}) async {
    EditorDocument doc = _ref.read(editorDocumentProvider);
    final String path = saveTargetFor(doc);

    // LAST LINE OF DEFENCE (FR-ERR). The editor field already runs
    // SmartPunctuationFormatter, but that is a widget-level guard: content can
    // also arrive from a platform substitution the field did not mediate, and
    // iOS is documented to honour `smartQuotesType` only "on iOS" — which was
    // observed NOT to hold on a real iPad, producing a board file of
    //   b'print(\xe2\x80\x9cHello world!!\xe2\x80\x9d)\n'
    // that could never run. Normalising here makes the guarantee unconditional:
    // whatever is in the buffer, what reaches the BOARD always tokenizes.
    //
    // The buffer is updated to match, so the screen and the board never
    // disagree about what was saved.
    final String cleaned = normalizeSmartPunctuation(doc.content);
    if (cleaned != doc.content) {
      _ref.read(editorDocumentProvider.notifier).setContent(cleaned);
      doc = _ref.read(editorDocumentProvider);
    }

    await _ref
        .read(programActionsProvider)
        .saveSource(path: path, source: cleaned, onProgress: onProgress);

    // Only after CRC-verified success, and only if this is still the document
    // whose bytes were uploaded: clear dirty and adopt the path. A user may edit
    // or open another document while a BLE transfer is in flight.
    if (_ref.read(editorDocumentProvider) == doc) {
      _ref.read(editorDocumentProvider.notifier).markSaved(boardPath: path);
    }
    return path;
  }
}

/// The save seam every Save affordance calls (FR-EDIT-2).
final Provider<SaveController> saveControllerProvider =
    Provider<SaveController>((Ref ref) => SaveController(ref));
