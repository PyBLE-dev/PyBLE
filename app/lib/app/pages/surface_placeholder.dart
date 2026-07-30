// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-05 — the shared surface empty-state component (design-system.md §7.9, §8),
/// the `SurfacePlaceholder` successor. Every surface's "nothing here yet" state
/// is built from [EmptyState]: a tonal illustration badge, a title, supporting
/// text, and an optional call-to-action slot — all on the Signal tokens.
///
/// This widget lives in `lib/app` (not `lib/theme`) because it BEARS strings:
/// every user-facing string is passed in by the caller from `AppLocalizations`
/// (so the locale-parity gate, which scans `lib/app`, covers it). The component
/// itself holds no display literals. It binds to no transport type and holds no
/// state (D2, CON-8).
library;

import 'package:flutter/material.dart';

import 'package:pyble/theme/theme.dart';

/// The tonal treatment of an [EmptyState]'s illustration badge (§7.9). Signals
/// intent by color: an action entry point vs read-only reference vs a quiet,
/// neutral surface.
enum SurfaceTone {
  /// Primary entry point (e.g. Connect) — `primaryContainer` badge.
  action,

  /// Read-only / informational (e.g. the pin reference) — `tertiaryContainer`
  /// badge, so it reads as reference, not action (CON-7).
  informational,

  /// Quiet, neutral surface (Editor / Console / Files) — `surfaceContainerHigh`
  /// badge.
  neutral,
}

/// A centered, overflow-safe empty state for a surface. Scrolls rather than
/// overflowing when height-constrained or at large `textScaleFactor` (§9).
class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    this.detail = '',
    this.tone = SurfaceTone.neutral,
    this.action,
  });

  /// The surface's representative icon, shown inside the badge.
  final IconData icon;

  /// The empty-state title. Callers pass a localized string (rendered verbatim).
  final String title;

  /// A one-line supporting hint. May be empty. May embed a verbatim technical
  /// identifier (FR-I18N-4).
  final String detail;

  /// The badge's tonal treatment (§7.9).
  final SurfaceTone tone;

  /// Optional primary/secondary call-to-action, placed below the detail. Wired
  /// by the surface's feature owner; `null` renders no action.
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final (Color badgeFill, Color badgeIcon) = _toneColors(tone, scheme);

    final Widget content = Column(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        // Illustration badge — a rounded square holding the surface icon (§7.9).
        Container(
          width: 72,
          height: 72,
          decoration: BoxDecoration(
            color: badgeFill,
            borderRadius: BorderRadius.circular(SignalRadius.lg),
          ),
          child: Icon(icon, size: 40, color: badgeIcon),
        ),
        const SizedBox(height: SignalSpacing.md),
        Text(
          title,
          textAlign: TextAlign.center,
          style: theme.textTheme.titleLarge?.copyWith(color: scheme.onSurface),
        ),
        if (detail.isNotEmpty) ...<Widget>[
          const SizedBox(height: SignalSpacing.sm),
          Text(
            detail,
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: scheme.onSurfaceVariant,
            ),
          ),
        ],
        if (action != null) ...<Widget>[
          const SizedBox(height: SignalSpacing.xl),
          action!,
        ],
      ],
    );

    // Overflow-safe: center when it fits, scroll when constrained (never
    // overflows at any breakpoint or text scale, §9).
    return LayoutBuilder(
      builder: (BuildContext context, BoxConstraints constraints) {
        return SingleChildScrollView(
          child: ConstrainedBox(
            constraints: BoxConstraints(
              minHeight: constraints.maxHeight.isFinite
                  ? constraints.maxHeight
                  : 0,
            ),
            child: Center(
              child: Padding(
                padding: const EdgeInsets.all(SignalSpacing.xl),
                child: content,
              ),
            ),
          ),
        );
      },
    );
  }
}

/// A prominent, non-overlaying empty-state band for a surface that must keep
/// its primary content reachable, such as the empty Blockly canvas/toolbox.
class EmptyStateBanner extends StatelessWidget {
  const EmptyStateBanner({
    super.key,
    required this.icon,
    required this.title,
    required this.detail,
    required this.action,
    this.tone = SurfaceTone.neutral,
  });

  final IconData icon;
  final String title;
  final String detail;
  final Widget action;
  final SurfaceTone tone;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final (Color fill, Color foreground) = _toneColors(tone, scheme);
    final Widget message = Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        ConstrainedBox(
          constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
          child: Icon(icon, color: foreground),
        ),
        const SizedBox(width: SignalSpacing.sm),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(
                title,
                style: theme.textTheme.titleMedium?.copyWith(color: foreground),
              ),
              const SizedBox(height: SignalSpacing.xs),
              Text(
                detail,
                style: theme.textTheme.bodySmall?.copyWith(color: foreground),
              ),
            ],
          ),
        ),
      ],
    );

    return Semantics(
      container: true,
      child: Material(
        color: fill,
        child: LayoutBuilder(
          builder: (BuildContext context, BoxConstraints constraints) {
            final bool stack = constraints.maxWidth < 600;
            return SingleChildScrollView(
              child: Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: SignalSpacing.lg,
                  vertical: SignalSpacing.md,
                ),
                child: stack
                    ? Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: <Widget>[
                          message,
                          const SizedBox(height: SignalSpacing.sm),
                          Align(
                            alignment: Alignment.centerRight,
                            child: action,
                          ),
                        ],
                      )
                    : Row(
                        children: <Widget>[
                          Expanded(child: message),
                          const SizedBox(width: SignalSpacing.lg),
                          action,
                        ],
                      ),
              ),
            );
          },
        ),
      ),
    );
  }
}

(Color, Color) _toneColors(SurfaceTone tone, ColorScheme scheme) {
  switch (tone) {
    case SurfaceTone.action:
      return (scheme.primaryContainer, scheme.onPrimaryContainer);
    case SurfaceTone.informational:
      return (scheme.tertiaryContainer, scheme.onTertiaryContainer);
    case SurfaceTone.neutral:
      return (scheme.surfaceContainerHigh, scheme.onSurfaceVariant);
  }
}
