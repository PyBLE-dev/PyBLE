// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-20 — the Editor surface host. Delegates to the live [EditorView] in
/// `lib/editor` (owner: app-editor-console-engineer), which edits the volatile
/// in-memory current document (ADR-0010). This page is a thin app-layer host: it
/// bears no display copy (all strings live in the feature view, sourced from
/// `AppLocalizations`) and binds to no transport type (CON-8, D2).
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/blocks/blocks.dart';
import 'package:pyble/editor/editor.dart';

/// The Editor surface — the live MicroPython editing surface.
class EditorPage extends ConsumerWidget {
  const EditorPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bool converting = ref.watch(pythonBlocksFlowBusyProvider);
    return EditorView(
      convertingToBlocks: converting,
      onConvertToBlocks: converting
          ? null
          : () {
              unawaited(showPythonToBlocksConversion(context));
            },
    );
  }
}
