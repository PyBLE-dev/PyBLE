// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-20 — the working-loop current document (ADR-0010, TDD §11.6a, specs.md
/// FR-EDIT §4.6). A single, volatile in-memory buffer the editor edits,
/// run-control runs, and the files explorer opens-into / uploads-from.
///
/// It survives navigation (a keep-alive `NotifierProvider`) but NOT a process
/// restart: persistence to Drift is the A-24 hook, reached through
/// [EditorDocumentController.openFromBoard] / [EditorDocumentController.markSaved]
/// — a RECORDED deviation from FR-EDIT-7 (carried, not dropped).
///
/// Binds to no transport type and imports no `lib/ble` (CON-8, D2): the document
/// is a pure value; the seam verbs live in `run_controller.dart` /
/// `file_explorer_controller.dart`.
library;

import 'package:flutter/foundation.dart' show immutable;
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// The default filename for a fresh, never-saved buffer.
///
/// A TECHNICAL identifier (a filename), so it is an ASCII constant and is NEVER
/// localized (FR-I18N-4) — the same rule that keeps port-defined chip values,
/// board paths, and status names verbatim.
const String kDefaultDocumentName = 'untitled.py';

/// The editable current document: its display name, buffer content, unsaved
/// flag, and the board path it maps to (or `null` for a never-saved buffer).
///
/// All field names are ASCII (FR-I18N-4); the value carries no display copy.
@immutable
class EditorDocument {
  const EditorDocument({
    required this.name,
    required this.content,
    required this.dirty,
    this.boardPath,
  });

  /// A fresh, empty, never-saved buffer named [kDefaultDocumentName].
  const EditorDocument.untitled()
    : name = kDefaultDocumentName,
      content = '',
      dirty = false,
      boardPath = null;

  /// Display filename, e.g. `main.py`. A technical identifier — never localized.
  final String name;

  /// The buffer contents.
  final String content;

  /// Whether the buffer has edits not yet written back to the board (A-24).
  final bool dirty;

  /// The absolute board path this buffer maps to, or `null` when it has never
  /// been opened from / saved to a board.
  final String? boardPath;

  @override
  bool operator ==(Object other) =>
      other is EditorDocument &&
      other.name == name &&
      other.content == content &&
      other.dirty == dirty &&
      other.boardPath == boardPath;

  @override
  int get hashCode => Object.hash(name, content, dirty, boardPath);
}

/// The [EditorDocument] controller (ADR-0010). Owns the single current buffer;
/// the editor writes edits, run-control reads the content, and the files
/// explorer opens into / marks it saved — all through this one seam.
class EditorDocumentController extends Notifier<EditorDocument> {
  @override
  EditorDocument build() => const EditorDocument.untitled();

  /// Resets to a fresh, empty untitled buffer (dirty=false, boardPath=null).
  void newDocument() {
    state = const EditorDocument.untitled();
    _bumpEpoch();
  }

  /// Sets the buffer [content]. Marks the buffer dirty ONLY when the content
  /// actually changes, so re-entering identical text never dirties a clean file.
  void setContent(String content) {
    if (content == state.content) return;
    state = EditorDocument(
      name: state.name,
      content: content,
      dirty: true,
      boardPath: state.boardPath,
    );
    _bumpEpoch();
  }

  /// Adopts a file downloaded from the board: the display name becomes the leaf
  /// of [path], [boardPath] becomes [path], and the buffer is clean.
  void openFromBoard({required String path, required String content}) {
    state = EditorDocument(
      name: _leaf(path),
      content: content,
      dirty: false,
      boardPath: path,
    );
    _bumpEpoch();
  }

  /// Copies generated source into an independent, dirty editor document.
  ///
  /// The generated view is intentionally one-way (ADR-0013): adopting it does
  /// not bind the editor back to the visual workspace. [name] is a filename,
  /// not a board path, and [boardPath] stays null until the normal editor Save
  /// succeeds.
  void openGenerated({required String name, required String content}) {
    state = EditorDocument(
      name: _leaf(name),
      content: content,
      dirty: true,
      boardPath: null,
    );
    _bumpEpoch();
  }

  /// Clears the dirty flag after a successful save and, if [boardPath] is given,
  /// adopts it (A-24 persistence hook). The buffer content is never changed.
  void markSaved({String? boardPath}) {
    state = EditorDocument(
      name: state.name,
      content: state.content,
      dirty: false,
      boardPath: boardPath ?? state.boardPath,
    );
    _bumpEpoch();
  }

  void _bumpEpoch() {
    ref.read(editorDocumentEpochProvider.notifier).state += 1;
  }

  /// The leaf (last path segment) of an absolute board [path].
  static String _leaf(String path) => path.substring(path.lastIndexOf('/') + 1);
}

/// The absolute board target for an editor [document].
///
/// Bound files keep their path. A generated/fresh document uses its technical
/// filename at the board filesystem root.
String boardPathForDocument(EditorDocument document) {
  final String? bound = document.boardPath;
  if (bound != null && bound.isNotEmpty) return bound;
  final String name = document.name.isEmpty
      ? kDefaultDocumentName
      : document.name;
  return name.startsWith('/') ? name : '/$name';
}

/// The single current-document seam (ADR-0010, TDD §11.6a). A plain (non-
/// autoDispose) provider so the buffer survives navigation between surfaces.
final NotifierProvider<EditorDocumentController, EditorDocument>
editorDocumentProvider =
    NotifierProvider<EditorDocumentController, EditorDocument>(
      EditorDocumentController.new,
    );

/// Monotonic in-process identity for guarded asynchronous document actions.
///
/// Value equality alone cannot detect "edit away, then back" while a Preview is
/// open. Every explicit document mutation increments this epoch, allowing a
/// captured conversion to fail closed even when all four visible fields later
/// happen to match again.
final StateProvider<int> editorDocumentEpochProvider = StateProvider<int>(
  (Ref ref) => 0,
);
