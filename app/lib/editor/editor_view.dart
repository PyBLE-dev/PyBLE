// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-20 — the EditorView: a monospace, `SignalCodeColors`-styled editable
/// surface over the volatile in-memory current document (ADR-0010, TDD §11.6a,
/// specs.md FR-EDIT §4.6).
///
/// v1 is a REAL editable field (a themed `TextField` over `EditableText`) — no
/// heavy code-editor dependency and no `google_fonts` (OI-1 / NFR-OFF). Syntax
/// highlighting, multi-file tabs, find/replace, and a scroll-synced line-number
/// gutter are deferred to A-24 / OI-1; a bare `TextField` cannot host a synced
/// gutter without a code-editor, so line numbers are intentionally omitted here
/// rather than shipped desynced.
///
/// Run lives on the shell TOOLBAR (single active writer, FR-RUN-1), not in this
/// view, so the editor and the toolbar never present two competing Run controls.
/// Binds through the seam only (CON-8): it reads/writes [editorDocumentProvider]
/// and imports no transport type.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show TextInputFormatter;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';
import 'package:pyble/theme/theme.dart';

import 'editor_document.dart';
import 'run_controller.dart';
import 'save_controller.dart';
import 'smart_punctuation.dart';

/// Stable key for the "New" affordance (widget tests + HIL), mirroring the
/// ConnectScreen key-contract precedent.
const Key kEditorNewButtonKey = ValueKey<String>('editorNewButton');

/// Stable key for the "Save to board" affordance (FR-EDIT-2).
const Key kEditorSaveButtonKey = ValueKey<String>('editorSaveButton');

/// Stable key for the explicit Python → Blocks action.
const Key kEditorConvertToBlocksButtonKey = ValueKey<String>(
  'editorConvertToBlocksButton',
);

/// The live MicroPython editing surface for the current document.
class EditorView extends ConsumerStatefulWidget {
  const EditorView({
    super.key,
    this.onConvertToBlocks,
    this.convertingToBlocks = false,
  });

  /// App-layer action; kept out of `lib/editor` to avoid an editor↔blocks cycle.
  final VoidCallback? onConvertToBlocks;
  final bool convertingToBlocks;

  @override
  ConsumerState<EditorView> createState() => _EditorViewState();
}

class _EditorViewState extends ConsumerState<EditorView> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(
      text: ref.read(editorDocumentProvider).content,
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // Keep the field in sync with EXTERNAL document changes (New, open-from-
    // board) without clobbering the user's cursor on their own edits: when the
    // change originates from typing, the buffer already equals the field text,
    // so the guard skips and the selection is untouched.
    ref.listen<EditorDocument>(editorDocumentProvider, (
      _,
      EditorDocument next,
    ) {
      if (next.content != _controller.text) {
        _controller.value = TextEditingValue(
          text: next.content,
          selection: TextSelection.collapsed(offset: next.content.length),
        );
      }
    });

    final EditorDocument doc = ref.watch(editorDocumentProvider);
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final AppLocalizations l10n = AppLocalizations.of(context);
    final SignalCodeColors code = SignalCodeColors.of(context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        _EditorHeader(
          name: doc.name,
          dirty: doc.dirty,
          onConvertToBlocks: widget.onConvertToBlocks,
          convertingToBlocks: widget.convertingToBlocks,
        ),
        const Divider(height: 1),
        // Typographic characters that cannot compile (FR-ERR). Shown ONLY when
        // present, and it fixes on tap — the buffer is never rewritten behind
        // the user's back.
        const _SmartPunctuationBanner(),
        // The editable code well — a recessed monospace surface (§1.4).
        Expanded(
          child: Container(
            color: scheme.surfaceContainerLowest,
            padding: const EdgeInsets.symmetric(
              horizontal: SignalSpacing.lg,
              vertical: SignalSpacing.md,
            ),
            child: TextField(
              controller: _controller,
              onChanged: (String value) =>
                  ref.read(editorDocumentProvider.notifier).setContent(value),
              expands: true,
              maxLines: null,
              minLines: null,
              keyboardType: TextInputType.multiline,
              // CODE, not prose. iPadOS Smart Punctuation is ON by default and
              // silently rewrites " -> “ ” and -- -> — as the user types, which
              // makes MicroPython answer `SyntaxError: invalid syntax` for a
              // literal that LOOKS correct on screen (U+201C/U+201D are not
              // string delimiters). On a tablet-first MicroPython IDE that
              // breaks the very first `print("hello")` a beginner writes, so
              // every text-assist feature is disabled here.
              smartQuotesType: SmartQuotesType.disabled,
              smartDashesType: SmartDashesType.disabled,
              autocorrect: false,
              enableSuggestions: false,
              textCapitalization: TextCapitalization.none,
              // The flags above are only a HINT — Flutter documents
              // smartQuotesType/smartDashesType as "This flag only affects
              // iOS", so they do nothing on Android/macOS/web and never cover
              // PASTED text on any platform. This formatter is the actual
              // guarantee: it runs on every value change, so a curly quote or
              // an invisible non-breaking space can never reach the buffer.
              inputFormatters: const <TextInputFormatter>[
                SmartPunctuationFormatter(),
              ],
              textAlignVertical: TextAlignVertical.top,
              cursorColor: scheme.primary,
              style: SignalType.codeOn(scheme),
              decoration: InputDecoration(
                isCollapsed: true,
                border: InputBorder.none,
                hintText: l10n.editorHintText,
                hintStyle: SignalType.code.copyWith(color: code.gutter),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// The editor header: the current filename, an unsaved indicator while dirty,
/// and the "New" affordance. Filenames are technical identifiers rendered
/// verbatim (FR-I18N-4); all other copy is from [AppLocalizations].
class _EditorHeader extends ConsumerWidget {
  const _EditorHeader({
    required this.name,
    required this.dirty,
    required this.onConvertToBlocks,
    required this.convertingToBlocks,
  });

  final String name;
  final bool dirty;
  final VoidCallback? onConvertToBlocks;
  final bool convertingToBlocks;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final AppLocalizations l10n = AppLocalizations.of(context);
    return Container(
      color: SignalElevation.tier(scheme, 2),
      padding: const EdgeInsets.only(
        left: SignalSpacing.lg,
        right: SignalSpacing.sm,
        top: SignalSpacing.xs,
        bottom: SignalSpacing.xs,
      ),
      child: LayoutBuilder(
        builder: (BuildContext context, BoxConstraints constraints) {
          final bool compact = constraints.maxWidth < 400;
          return Row(
            children: <Widget>[
              if (!compact) ...<Widget>[
                Icon(
                  Icons.description_outlined,
                  size: 18,
                  color: scheme.onSurfaceVariant,
                ),
                const SizedBox(width: SignalSpacing.sm),
              ],
              // Filename — a technical identifier, monospace + verbatim.
              Expanded(
                child: Text(
                  name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: SignalType.code.copyWith(color: scheme.onSurface),
                ),
              ),
              if (dirty) ...<Widget>[
                const SizedBox(width: SignalSpacing.xs),
                if (compact)
                  _UnsavedDot(label: l10n.editorUnsavedLabel)
                else
                  _UnsavedChip(label: l10n.editorUnsavedLabel),
              ],
              IconButton(
                key: kEditorConvertToBlocksButtonKey,
                icon: convertingToBlocks
                    ? const SizedBox.square(
                        dimension: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.account_tree_outlined),
                tooltip: l10n.editorConvertToBlocks,
                onPressed: convertingToBlocks ? null : onConvertToBlocks,
              ),
              // Save the buffer to the board (FR-EDIT-2). Enabled only when a
              // board is attached.
              Consumer(
                builder: (BuildContext context, WidgetRef ref, _) {
                  final RunAvailability run = ref.watch(
                    runAvailabilityProvider,
                  );
                  final bool canSave = run.canSoftReboot;
                  return IconButton(
                    key: kEditorSaveButtonKey,
                    icon: const Icon(Icons.save_outlined),
                    tooltip: canSave
                        ? l10n.editorSave
                        : l10n.editorSaveDisconnectedHint,
                    onPressed: canSave ? () => _save(context, ref) : null,
                  );
                },
              ),
              IconButton(
                key: kEditorNewButtonKey,
                icon: const Icon(Icons.note_add_outlined),
                tooltip: l10n.editorEmptyCta,
                onPressed: () => _newDocument(context, ref),
              ),
            ],
          );
        },
      ),
    );
  }

  /// Writes the buffer to the board, reporting the outcome honestly: the board
  /// path on success, the typed reason on failure (FR-EDIT-2). A failed save
  /// leaves the buffer dirty — the user is never told work was persisted when it
  /// was not.
  Future<void> _save(BuildContext context, WidgetRef ref) async {
    final ScaffoldMessengerState messenger = ScaffoldMessenger.of(context);
    final AppLocalizations l10n = AppLocalizations.of(context);
    try {
      final String path = await ref.read(saveControllerProvider).save();
      messenger.showSnackBar(SnackBar(content: Text(l10n.editorSaved(path))));
    } on PbleException catch (e) {
      // The typed §8 status name (EBusy / ENoSpc / ECrc …) is a PBLE/1
      // technical identifier: rendered verbatim, never localized (FR-I18N-4).
      // `e.message` is an internal ASCII diagnostic and is deliberately not
      // shown to the user.
      messenger.showSnackBar(
        SnackBar(
          content: Text(l10n.editorSaveFailed(e.runtimeType.toString())),
        ),
      );
    } catch (e) {
      // A non-PBLE failure (link torn down mid-write) must still be visible
      // rather than becoming an unhandled async error that shows nothing.
      messenger.showSnackBar(
        SnackBar(content: Text(l10n.editorSaveFailed(e.toString()))),
      );
    }
  }

  /// Starts a fresh buffer, confirming first when the current one has unsaved
  /// edits — the previous behaviour discarded a dirty buffer with no prompt and
  /// no way to get it back (the document is volatile by design).
  Future<void> _newDocument(BuildContext context, WidgetRef ref) async {
    final AppLocalizations l10n = AppLocalizations.of(context);
    if (ref.read(editorDocumentProvider).dirty) {
      final bool? discard = await showDialog<bool>(
        context: context,
        builder: (BuildContext ctx) => AlertDialog(
          title: Text(l10n.editorDiscardTitle),
          content: Text(l10n.editorDiscardDetail),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: Text(l10n.commonCancel),
            ),
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: Text(l10n.editorDiscardConfirm),
            ),
          ],
        ),
      );
      if (discard != true) return;
    }
    ref.read(editorDocumentProvider.notifier).newDocument();
  }
}

/// Stable key for the smart-punctuation fix affordance (widget tests + HIL).
const Key kEditorFixPunctuationKey = ValueKey<String>('editorFixPunctuation');

/// Warns that the buffer contains curly quotes / dashes / non-breaking spaces
/// that MicroPython cannot parse, and converts them on tap.
///
/// This exists because the board's own answer — `SyntaxError: invalid syntax` —
/// points at a line that looks perfectly correct, and a non-breaking space is
/// not even visible. Suppressing Smart Punctuation on our own field (see the
/// TextField above) stops it while TYPING; it cannot stop it arriving by PASTE,
/// which is how most beginner code gets into a tablet editor.
class _SmartPunctuationBanner extends ConsumerWidget {
  const _SmartPunctuationBanner();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final String content = ref.watch(
      editorDocumentProvider.select((EditorDocument d) => d.content),
    );
    final List<SmartPunctuationHit> hits = findSmartPunctuation(content);
    if (hits.isEmpty) return const SizedBox.shrink();

    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final AppLocalizations l10n = AppLocalizations.of(context);

    return Material(
      color: scheme.errorContainer,
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: SignalSpacing.lg,
          vertical: SignalSpacing.xs,
        ),
        child: Row(
          children: <Widget>[
            Icon(
              Icons.warning_amber_rounded,
              size: 18,
              color: scheme.onErrorContainer,
            ),
            const SizedBox(width: SignalSpacing.sm),
            Expanded(
              child: Text(
                l10n.editorSmartPunctuationWarning(hits.length),
                style: theme.textTheme.bodySmall?.copyWith(
                  color: scheme.onErrorContainer,
                ),
              ),
            ),
            const SizedBox(width: SignalSpacing.sm),
            TextButton(
              key: kEditorFixPunctuationKey,
              onPressed: () {
                final int fixed = hits.length;
                ref
                    .read(editorDocumentProvider.notifier)
                    .setContent(normalizeSmartPunctuation(content));
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(l10n.editorSmartPunctuationFixed(fixed)),
                  ),
                );
              },
              child: Text(l10n.editorFixSmartPunctuation),
            ),
          ],
        ),
      ),
    );
  }
}

/// A quiet "unsaved changes" pill, shown only while the buffer is dirty.
class _UnsavedChip extends StatelessWidget {
  const _UnsavedChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    return DecoratedBox(
      decoration: ShapeDecoration(
        color: scheme.tertiaryContainer,
        shape: const StadiumBorder(),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: SignalSpacing.sm,
          vertical: SignalSpacing.xs,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(Icons.circle, size: 8, color: scheme.onTertiaryContainer),
            const SizedBox(width: SignalSpacing.xs),
            Text(
              label,
              style: theme.textTheme.labelSmall?.copyWith(
                color: scheme.onTertiaryContainer,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _UnsavedDot extends StatelessWidget {
  const _UnsavedDot({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    final ColorScheme scheme = Theme.of(context).colorScheme;
    return Semantics(
      label: label,
      child: Tooltip(
        message: label,
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: scheme.tertiary,
            shape: BoxShape.circle,
          ),
          child: const SizedBox.square(dimension: 8),
        ),
      ),
    );
  }
}
