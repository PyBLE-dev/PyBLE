// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-21 — the live console surfaces (ADR-0010, TDD §11.6c, specs.md FR-CONSOLE
/// §4.7). Two widgets, one buffer:
///
///   * [ConsoleView] — the full Console surface: a run-state indicator, copy +
///     clear actions, the scrolling output well, and an interactive stdin row.
///   * [ConsoleStripView] — the landscape bottom strip: a titled, output-focused
///     monitor (run-state + copy + clear + the same output well), sized to the
///     resting strip height. The interactive stdin lives on [ConsoleView].
///
/// Both render the SAME [consoleBufferProvider], so output is identical and
/// survives navigation. Streams are differentiated by [SignalCodeColors]
/// (stdout / stderr / system, FR-CONSOLE-2); the raw traceback is ALWAYS shown
/// (annotate-never-hide, FR-ERR-2). Output auto-scrolls, with a scroll-lock the
/// user takes by scrolling up and releases with "resume auto-scroll". Binds
/// through the seam only (CON-8).
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show Clipboard, ClipboardData;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';
import 'package:pyble/theme/theme.dart';

import 'console_controller.dart';

/// Resting height of the landscape console strip (§7.5): title + run-state row,
/// the output well (≥ 6 code lines), and insets, so a short traceback fits at
/// rest. Exported so the shell can host [ConsoleStripView] at the same height.
const double kConsoleStripHeight = 184;

/// Height of focused Blocks' on-demand console title/toggle row (ADR-0014).
const double kConsoleCollapsedStripHeight = 48;

/// Stable test/semantics key for the focused Blocks console disclosure.
const Key kConsoleStripToggleKey = ValueKey<String>('consoleStripToggle');

/// Distance (px) from the bottom within which the view is considered "at the
/// bottom" and keeps following live output.
const double _kFollowThreshold = 24;

// ---------------------------------------------------------------------------
// Full Console surface.
// ---------------------------------------------------------------------------

/// The full, interactive Console surface.
class ConsoleView extends StatelessWidget {
  const ConsoleView({super.key});

  @override
  Widget build(BuildContext context) {
    return const Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        _ConsoleActionBar(),
        Divider(height: 1),
        Expanded(child: _ConsoleOutput()),
        Divider(height: 1),
        _ConsoleInputRow(),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Landscape strip (output monitor; stdin lives on the Console surface).
// ---------------------------------------------------------------------------

/// The landscape bottom console strip: a titled, output-focused monitor.
class ConsoleStripView extends StatelessWidget {
  const ConsoleStripView({super.key, this.collapsed = false, this.onToggle});

  /// Collapsed mode retains run state and actions but gives the workspace back
  /// the output well's height.
  final bool collapsed;

  /// Present only when the host permits explicit expand/collapse.
  final VoidCallback? onToggle;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: collapsed ? kConsoleCollapsedStripHeight : kConsoleStripHeight,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          _ConsoleActionBar(
            showTitle: true,
            compact: collapsed,
            collapsed: collapsed,
            onToggle: onToggle,
          ),
          if (!collapsed) ...const <Widget>[
            Divider(height: 1),
            Expanded(child: _ConsoleOutput()),
          ],
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Shared: the action bar (title? + run-state + copy + clear).
// ---------------------------------------------------------------------------

class _ConsoleActionBar extends ConsumerWidget {
  const _ConsoleActionBar({
    this.showTitle = false,
    this.compact = false,
    this.collapsed = false,
    this.onToggle,
  });

  /// Whether to lead with the localized console title (the landscape strip).
  final bool showTitle;
  final bool compact;
  final bool collapsed;
  final VoidCallback? onToggle;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final AppLocalizations l10n = AppLocalizations.of(context);
    return Container(
      color: SignalElevation.tier(scheme, 2),
      padding: EdgeInsets.only(
        left: SignalSpacing.lg,
        right: SignalSpacing.sm,
        top: compact ? 0 : SignalSpacing.xs,
        bottom: compact ? 0 : SignalSpacing.xs,
      ),
      child: Row(
        children: <Widget>[
          if (showTitle) ...<Widget>[
            Text(
              l10n.consoleTitle,
              style: theme.textTheme.labelLarge?.copyWith(
                color: scheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(width: SignalSpacing.md),
          ],
          const _RunStateIndicator(),
          const Spacer(),
          IconButton(
            icon: const Icon(Icons.copy_outlined),
            tooltip: l10n.consoleCopyTooltip,
            onPressed: () {
              final String text = ref
                  .read(consoleBufferProvider)
                  .map(
                    (ConsoleEvent e) =>
                        utf8.decode(e.bytes, allowMalformed: true),
                  )
                  .join();
              Clipboard.setData(ClipboardData(text: text));
            },
          ),
          IconButton(
            icon: const Icon(Icons.delete_outline),
            tooltip: l10n.consoleClearTooltip,
            onPressed: () => ref.read(consoleBufferProvider.notifier).clear(),
          ),
          if (onToggle != null)
            IconButton(
              key: kConsoleStripToggleKey,
              icon: Icon(
                collapsed ? Icons.keyboard_arrow_up : Icons.keyboard_arrow_down,
              ),
              tooltip: collapsed
                  ? l10n.consoleExpandTooltip
                  : l10n.consoleCollapseTooltip,
              onPressed: onToggle,
            ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Shared: the run-state indicator (off the live Connection.runState stream).
// ---------------------------------------------------------------------------

class _RunStateIndicator extends ConsumerWidget {
  const _RunStateIndicator();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final Connection connection = ref.watch(connectionProvider);
    return StreamBuilder<RunState>(
      stream: connection.runState,
      builder: (BuildContext context, AsyncSnapshot<RunState> snapshot) {
        return _RunStateBadge(snapshot.data ?? RunState.idle);
      },
    );
  }
}

class _RunStateBadge extends StatelessWidget {
  const _RunStateBadge(this.runState);

  final RunState runState;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final AppLocalizations l10n = AppLocalizations.of(context);
    final SignalStateColors states = SignalStateColors.of(context);

    final (IconData icon, Color color, String label) = switch (runState) {
      RunState.idle => (
        Icons.circle_outlined,
        scheme.onSurfaceVariant,
        l10n.runStateIdle,
      ),
      RunState.running => (
        Icons.play_circle,
        states.running,
        l10n.runStateRunning,
      ),
      RunState.done => (Icons.check_circle, states.ready, l10n.runStateDone),
      RunState.error => (Icons.error_outline, scheme.error, l10n.runStateError),
    };

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Icon(icon, size: 16, color: color),
        const SizedBox(width: SignalSpacing.xs),
        Text(
          label,
          style: theme.textTheme.labelMedium?.copyWith(color: scheme.onSurface),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Shared: the scrolling output well (auto-scroll + scroll-lock).
// ---------------------------------------------------------------------------

class _ConsoleOutput extends ConsumerStatefulWidget {
  const _ConsoleOutput();

  @override
  ConsumerState<_ConsoleOutput> createState() => _ConsoleOutputState();
}

class _ConsoleOutputState extends ConsumerState<_ConsoleOutput> {
  final ScrollController _scroll = ScrollController();
  bool _follow = true;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_onScroll);
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (!_scroll.hasClients) return;
    final ScrollPosition p = _scroll.position;
    final bool atBottom = p.pixels >= p.maxScrollExtent - _kFollowThreshold;
    if (atBottom != _follow) {
      setState(() => _follow = atBottom);
    }
  }

  void _jumpToBottom() {
    if (!_scroll.hasClients) return;
    _scroll.jumpTo(_scroll.position.maxScrollExtent);
  }

  @override
  Widget build(BuildContext context) {
    // Observe the ring listenable directly (not `ref.watch`) so a live console
    // event rebuilds this in the same frame it arrives (see the controller doc).
    final ConsoleBufferController controller = ref.watch(
      consoleBufferProvider.notifier,
    );
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final SignalCodeColors code = SignalCodeColors.of(context);

    return ValueListenableBuilder<List<ConsoleEvent>>(
      valueListenable: controller.events,
      builder: (BuildContext context, List<ConsoleEvent> events, _) {
        // Follow live output while the user hasn't scrolled up.
        if (_follow) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted && _follow) _jumpToBottom();
          });
        }

        final List<InlineSpan> spans = <InlineSpan>[
          for (final ConsoleEvent e in events)
            TextSpan(
              text: utf8.decode(e.bytes, allowMalformed: true),
              style: TextStyle(color: code.streamColor(e.stream)),
            ),
        ];

        return Stack(
          children: <Widget>[
            Positioned.fill(
              child: Container(
                color: scheme.surfaceContainerLowest,
                child: Scrollbar(
                  controller: _scroll,
                  child: SingleChildScrollView(
                    controller: _scroll,
                    padding: const EdgeInsets.symmetric(
                      horizontal: SignalSpacing.lg,
                      vertical: SignalSpacing.md,
                    ),
                    child: SizedBox(
                      width: double.infinity,
                      child: Text.rich(
                        TextSpan(children: spans),
                        style: SignalType.code,
                      ),
                    ),
                  ),
                ),
              ),
            ),
            if (!_follow)
              Positioned(
                right: SignalSpacing.md,
                bottom: SignalSpacing.md,
                child: _ResumeAutoscrollButton(
                  onPressed: () {
                    setState(() => _follow = true);
                    WidgetsBinding.instance.addPostFrameCallback(
                      (_) => _jumpToBottom(),
                    );
                  },
                ),
              ),
          ],
        );
      },
    );
  }
}

class _ResumeAutoscrollButton extends StatelessWidget {
  const _ResumeAutoscrollButton({required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = AppLocalizations.of(context);
    return FloatingActionButton.small(
      heroTag: null,
      tooltip: l10n.consoleResumeAutoscroll,
      onPressed: onPressed,
      child: const Icon(Icons.arrow_downward),
    );
  }
}

// ---------------------------------------------------------------------------
// Shared: the stdin input row (or the disconnected guidance).
// ---------------------------------------------------------------------------

class _ConsoleInputRow extends ConsumerStatefulWidget {
  const _ConsoleInputRow();

  @override
  ConsumerState<_ConsoleInputRow> createState() => _ConsoleInputRowState();
}

class _ConsoleInputRowState extends ConsumerState<_ConsoleInputRow> {
  final TextEditingController _input = TextEditingController();

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  void _send() {
    final String text = _input.text;
    if (text.isEmpty) return;
    // Submit a line (append newline) so the program's stdin read gets a line.
    ref.read(consoleBufferProvider.notifier).sendInput('$text\n');
    _input.clear();
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final AppLocalizations l10n = AppLocalizations.of(context);
    final Connection connection = ref.watch(connectionProvider);

    return Container(
      color: SignalElevation.tier(scheme, 2),
      padding: const EdgeInsets.symmetric(
        horizontal: SignalSpacing.lg,
        vertical: SignalSpacing.sm,
      ),
      child: ValueListenableBuilder<ConnState>(
        valueListenable: connection.state,
        builder: (BuildContext context, ConnState state, _) {
          // No board attached: guide the user, and offer no send affordance.
          if (state == ConnState.disconnected) {
            return Row(
              children: <Widget>[
                Icon(
                  Icons.info_outline,
                  size: 18,
                  color: scheme.onSurfaceVariant,
                ),
                const SizedBox(width: SignalSpacing.sm),
                Expanded(
                  child: Text(
                    l10n.consoleInputDisabledHint,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
                  ),
                ),
              ],
            );
          }
          return Row(
            children: <Widget>[
              Expanded(
                child: TextField(
                  controller: _input,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (_) => _send(),
                  // stdin for a running program is DATA, not prose: iPadOS
                  // Smart Punctuation would rewrite " -> “ ” and autocorrect
                  // would rewrite words, so the program would receive bytes the
                  // user never typed (FR-CON-3).
                  smartQuotesType: SmartQuotesType.disabled,
                  smartDashesType: SmartDashesType.disabled,
                  autocorrect: false,
                  enableSuggestions: false,
                  textCapitalization: TextCapitalization.none,
                  style: SignalType.codeOn(scheme),
                  decoration: InputDecoration(
                    isDense: true,
                    hintText: l10n.consoleInputHint,
                    border: const OutlineInputBorder(),
                  ),
                ),
              ),
              const SizedBox(width: SignalSpacing.sm),
              IconButton.filledTonal(
                icon: const Icon(Icons.send),
                tooltip: l10n.consoleSendTooltip,
                onPressed: _send,
              ),
            ],
          );
        },
      ),
    );
  }
}
