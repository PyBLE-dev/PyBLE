// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-05 — the connection-status pill (design-system.md §7.6, FR-UI-6,
/// FR-CONN-5). The app's primary state signal: it binds to the read-only
/// [connStateProvider] through the [Connection] seam (CON-8 — no `lib/ble`
/// import) and renders `disconnected` / `connecting` / `ready` / `running` with
/// a distinct per-state glyph + localized label + the frozen `SignalStateColors`
/// (glyph / border / tint). Once connected it retains the display-only PBLE/1
/// board ID and PyBLE firmware from [connectControllerProvider], because the
/// pre-connection Connect surface is no longer mounted (ADR-0011). State is
/// legible by shape + text, with color as reinforcement — never color alone,
/// never text alone.
///
/// **Motion (deferred, harness-gated):** §7.6/§6 call for a `connecting`/
/// `running` opacity breathe under the reduced-motion gate. A perpetual
/// `AnimationController.repeat()` makes `WidgetTester.pumpAndSettle()` time out,
/// and the frozen widget suite (`app/test/widget/app_shell_test.dart`) pumps
/// with animations ENABLED (flutter_test's `disableAnimations: false` default).
/// Until the harness disables animations (as §6 already assumes) or the pill
/// test switches to `pump(Duration)`, the pill renders a legible STATIC frame —
/// which §6 explicitly requires state to survive ("fully legible without the
/// pulse"). The glyph + label + color carry the full signal.
library;

import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show ValueListenable;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/connect/connect_controller.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';
import 'package:pyble/theme/theme.dart';

import '../providers.dart';

/// The per-state glyph map (§7.6). Shape carries state independent of color,
/// motion, and text, so the signal survives greyscale and reduced motion.
IconData _glyphFor(ConnState state) {
  switch (state) {
    case ConnState.disconnected:
      return Icons.bluetooth_disabled;
    case ConnState.connecting:
      return Icons.bluetooth_searching;
    case ConnState.ready:
      return Icons.check_circle;
    case ConnState.running:
      return Icons.play_circle;
  }
}

/// The localized state word (§7.6), sourced from [AppLocalizations].
String _wordFor(AppLocalizations l10n, ConnState state) {
  switch (state) {
    case ConnState.disconnected:
      return l10n.connStatusDisconnected;
    case ConnState.connecting:
      return l10n.connStatusConnecting;
    case ConnState.ready:
      return l10n.connStatusReady;
    case ConnState.running:
      return l10n.connStatusRunning;
  }
}

/// The connection-status pill. Read-only: it consumes the observable
/// [ConnState] via a `ValueListenableBuilder` and never mutates the board.
class ConnectionStatusPill extends ConsumerWidget {
  const ConnectionStatusPill({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ValueListenable<ConnState> listenable = ref.watch(connStateProvider);
    final DeviceInfo? deviceInfo = ref.watch(
      connectControllerProvider.select(
        (ConnectController controller) => controller.state.deviceInfo,
      ),
    );
    final AppLocalizations l10n = AppLocalizations.of(context);
    return ValueListenableBuilder<ConnState>(
      valueListenable: listenable,
      builder: (BuildContext context, ConnState state, _) {
        final ThemeData theme = Theme.of(context);
        final ColorScheme scheme = theme.colorScheme;
        final Color stateColor = SignalStateColors.of(context).colorFor(state);
        final bool isDark = scheme.brightness == Brightness.dark;
        final bool connected =
            state == ConnState.ready || state == ConnState.running;
        final DeviceInfo? visibleInfo = connected ? deviceInfo : null;
        final String stateWord = _wordFor(l10n, state);
        final String? deviceId = visibleInfo == null
            ? null
            : visibleInfo.deviceId.isEmpty
            ? l10n.connectDeviceNotReported
            : visibleInfo.deviceId;
        final String? agentVersion = visibleInfo == null
            ? null
            : visibleInfo.agentVersion.isEmpty
            ? l10n.connectDeviceNotReported
            : visibleInfo.agentVersion;

        // Tint fill = state color at 16 % (light) / 24 % (dark), composited to an
        // OPAQUE color over the pill's actual host surface (level 4) so contrast
        // and goldens stay deterministic (§1.3).
        final Color fill = Color.alphaBlend(
          stateColor.withValues(alpha: isDark ? 0.24 : 0.16),
          scheme.surfaceContainerHighest,
        );

        final Widget pill = DecoratedBox(
          decoration: ShapeDecoration(
            color: fill,
            // Always-on 1 px full-strength state-color border (§7.6).
            shape: StadiumBorder(side: BorderSide(color: stateColor, width: 1)),
          ),
          child: Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: SignalSpacing.md,
              vertical: SignalSpacing.xs,
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                // Glyph = state color at full strength (≥ 3:1 graphic).
                Icon(_glyphFor(state), size: 18, color: stateColor),
                const SizedBox(width: SignalSpacing.sm),
                // The full localized state word is the minimum signal and never
                // ellipsizes. Only the appended identity summary may truncate.
                Text(
                  stateWord,
                  maxLines: 1,
                  textScaler: MediaQuery.textScalerOf(
                    context,
                  ).clamp(maxScaleFactor: 1.3),
                  style: theme.textTheme.labelMedium?.copyWith(
                    color: scheme.onSurface,
                  ),
                ),
                if (deviceId != null && agentVersion != null) ...<Widget>[
                  const SizedBox(width: SignalSpacing.xs),
                  Flexible(
                    child: Text(
                      l10n.connStatusBoardInfoSummary(deviceId, agentVersion),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      textScaler: MediaQuery.textScalerOf(
                        context,
                      ).clamp(maxScaleFactor: 1.3),
                      style: theme.textTheme.labelMedium?.copyWith(
                        color: scheme.onSurface,
                        fontFeatures: const <FontFeature>[
                          FontFeature.tabularFigures(),
                        ],
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        );

        return Semantics(
          container: true,
          excludeSemantics: true,
          label: deviceId == null || agentVersion == null
              ? l10n.connStatusSemanticLabel(stateWord)
              : l10n.connStatusBoardInfoSemanticLabel(
                  stateWord,
                  deviceId,
                  agentVersion,
                ),
          child: ConstrainedBox(
            // ≥ 48 dp tall hit area (FR-UI-6); the visual pill is centered in it.
            constraints: const BoxConstraints(minHeight: 48),
            child: Center(
              widthFactor: 1,
              child: KeyedSubtree(
                // Stable key so widget + golden tests target the pill
                // independent of locale and color (§7.6).
                key: const ValueKey<String>('connStatusPill'),
                child: pill,
              ),
            ),
          ),
        );
      },
    );
  }
}
