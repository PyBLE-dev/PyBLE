// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Resolves an explicit Editor → Blocks request.
///
/// A valid adjacent companion yields exact workspace recovery. Missing, stale,
/// malformed, or unreadable companions never become trusted state; the same
/// captured source is passed to the strict offline importer instead.
library;

import 'dart:convert';

import 'package:flutter/foundation.dart' show immutable;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/pble/pble.dart';

import 'blocks_companion.dart';
import 'python_to_blocks.dart';

enum PythonBlocksPreparationOrigin { exactCompanion, importedPython }

enum PythonBlocksCompanionIssue { invalid, sourceMismatch, unreadable }

@immutable
class PythonBlocksPreparation {
  const PythonBlocksPreparation({
    required this.capturedDocument,
    required this.targetPath,
    required this.origin,
    required this.workspaceJson,
    required this.expectedSource,
    required this.semanticFingerprint,
    required this.diagnostics,
    required this.companionIssue,
  });

  final EditorDocument capturedDocument;
  final String targetPath;
  final PythonBlocksPreparationOrigin origin;
  final String? workspaceJson;
  final String? expectedSource;
  final String? semanticFingerprint;
  final List<PythonBlocksDiagnostic> diagnostics;
  final PythonBlocksCompanionIssue? companionIssue;

  bool get canPreview =>
      workspaceJson != null &&
      !diagnostics.any(
        (PythonBlocksDiagnostic diagnostic) => diagnostic.severity == 'error',
      );
}

class PythonBlocksPreparationService {
  const PythonBlocksPreparationService(this._ref);

  final Ref _ref;

  Future<PythonBlocksPreparation> prepare(
    EditorDocument captured, {
    bool readCompanion = false,
  }) async {
    final String targetPath = boardPathForDocument(captured);
    PythonBlocksCompanionIssue? issue;
    try {
      blocksCompanionPathFor(targetPath);
    } on ArgumentError {
      return PythonBlocksPreparation(
        capturedDocument: captured,
        targetPath: targetPath,
        origin: PythonBlocksPreparationOrigin.importedPython,
        workspaceJson: null,
        expectedSource: null,
        semanticFingerprint: null,
        diagnostics: const <PythonBlocksDiagnostic>[
          PythonBlocksDiagnostic(
            code: 'invalid_target_path',
            line: 1,
            column: 1,
            endLine: 1,
            endColumn: 1,
            messageKey: 'pythonBlocksInvalidTargetPath',
          ),
        ],
        companionIssue: null,
      );
    }

    // Only the explicit File Explorer "Open as Blocks" action authorizes the
    // adjacent board read. Editor conversion is a pure local import even when
    // its buffer is bound to a board path.
    if (readCompanion) {
      final String? boardPath = captured.boardPath;
      if (boardPath != null) {
        try {
          final List<int> bytes = await _ref
              .read(connectionProvider)
              .getFile(blocksCompanionPathFor(boardPath));
          if (bytes.length > kMaxBlocksCompanionBytes) {
            throw const BlocksCompanionFormatException(
              'companion exceeds the 1 MiB admission limit',
            );
          }
          final BlocksCompanion companion = BlocksCompanion.parse(
            utf8.decode(bytes),
          );
          if (companion.matchesPython(
            path: boardPath,
            source: captured.content,
          )) {
            return PythonBlocksPreparation(
              capturedDocument: captured,
              targetPath: boardPath,
              origin: PythonBlocksPreparationOrigin.exactCompanion,
              workspaceJson: companion.workspaceJson,
              expectedSource: captured.content,
              semanticFingerprint: null,
              diagnostics: const <PythonBlocksDiagnostic>[],
              companionIssue: null,
            );
          }
          issue = PythonBlocksCompanionIssue.sourceMismatch;
        } on ENoEnt {
          // Absence is normal for a Python file not authored in Blocks.
        } on BlocksCompanionFormatException {
          issue = PythonBlocksCompanionIssue.invalid;
        } on FormatException {
          issue = PythonBlocksCompanionIssue.invalid;
        } on PbleException {
          issue = PythonBlocksCompanionIssue.unreadable;
        }
      }
    }

    final PythonBlocksConversion conversion = const PythonToBlocksConverter()
        .convert(captured.content);
    return PythonBlocksPreparation(
      capturedDocument: captured,
      targetPath: targetPath,
      origin: PythonBlocksPreparationOrigin.importedPython,
      workspaceJson: conversion.workspaceJson,
      expectedSource: null,
      semanticFingerprint: conversion.semanticFingerprint,
      diagnostics: conversion.diagnostics,
      companionIssue: issue,
    );
  }
}

final Provider<PythonBlocksPreparationService> pythonBlocksPreparationProvider =
    Provider<PythonBlocksPreparationService>(
      (Ref ref) => PythonBlocksPreparationService(ref),
    );
