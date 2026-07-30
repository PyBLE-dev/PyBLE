// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-22 — the scan/connect surface (FR-CONNECT-1/2/5/6, SEC-4, ADR-0009).
///
/// Scan → connect → use, with NO pairing code, account, or identity gate
/// (FR-CONNECT-5, SEC-9). The flow, built on the Signal design system:
///
///   readiness banner (adapter-off / unauthorized / unsupported rationale)
///   → filtered scan CTA → live [ScanHit] list (advertised name + RSSI)
///   → connecting progress → connected Board-info card (chip / MicroPython /
///   free memory — the round-trip PROOF) + Disconnect → failure prompt,
///
/// plus an always-on compact diagnostics panel (adapter state, scan running,
/// boards seen, last error) for on-hardware (HIL) debugging.
///
/// Binds ONLY to the neutral [ConnectController] over the [ConnectionManager]
/// seam (CON-8, FR-BLE-8): NO `lib/ble` / `flutter_blue_plus` import, never a
/// raw device list (SEC-4). All copy is sourced from [AppLocalizations];
/// technical identifiers (the chip target, RSSI dBm, byte counts) render
/// verbatim (FR-I18N-4).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/app/pages/surface_placeholder.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';
import 'package:pyble/theme/theme.dart';

import 'connect_controller.dart';

/// Stable interactive keys (mirrored by the widget suite + used for HIL).
const Key _scanKey = ValueKey<String>('connectScanButton');
const Key _stopKey = ValueKey<String>('connectStopButton');
const Key _disconnectKey = ValueKey<String>('connectDisconnectButton');
Key _hitKey(String id) => ValueKey<String>('connectHit_$id');

/// The Connect surface — the scan/connect flow. A [ConsumerWidget] bound to the
/// [connectControllerProvider]; every rebuild reads the merged [ConnectState].
class ConnectScreen extends ConsumerWidget {
  const ConnectScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ConnectController controller = ref.watch(connectControllerProvider);
    final ConnectState state = controller.state;
    final AppLocalizations l10n = AppLocalizations.of(context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Expanded(
          child: _MainContent(controller: controller, state: state),
        ),
        const Divider(height: 1),
        _DiagnosticsPanel(state: state, l10n: l10n),
      ],
    );
  }
}

/// Picks the surface content for the current [ConnectState].
class _MainContent extends StatelessWidget {
  const _MainContent({required this.controller, required this.state});

  final ConnectController controller;
  final ConnectState state;

  @override
  Widget build(BuildContext context) {
    // Readiness gates everything: no scan while the adapter is off / not
    // permitted / unsupported (FR-BLE-6/7).
    if (!state.isReady) {
      return _ReadinessBanner(readiness: state.readiness);
    }
    switch (state.phase) {
      case ConnectPhase.connecting:
        return _ConnectingView(state: state);
      case ConnectPhase.connected:
        return _ConnectedView(controller: controller, state: state);
      case ConnectPhase.failed:
        return _FailedView(controller: controller, state: state);
      case ConnectPhase.scanning:
      case ConnectPhase.idle:
        if (state.hits.isEmpty) {
          return state.isScanning
              ? _ScanningEmpty(controller: controller)
              : _IdleHero(controller: controller);
        }
        return _HitList(controller: controller, state: state);
    }
  }
}

// ---------------------------------------------------------------------------
// Readiness banners (adapter-off / unauthorized / unsupported).
// ---------------------------------------------------------------------------

class _ReadinessBanner extends StatelessWidget {
  const _ReadinessBanner({required this.readiness});

  final BleReadiness readiness;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = AppLocalizations.of(context);
    final (IconData icon, String title, String detail) = switch (readiness) {
      BleReadiness.adapterOff => (
        Icons.bluetooth_disabled,
        l10n.connectAdapterOffTitle,
        l10n.connectAdapterOffDetail,
      ),
      BleReadiness.unauthorized => (
        Icons.lock_outline,
        l10n.connectUnauthorizedTitle,
        l10n.connectUnauthorizedDetail,
      ),
      BleReadiness.unsupported => (
        Icons.bluetooth_disabled,
        l10n.connectUnsupportedTitle,
        l10n.connectUnsupportedDetail,
      ),
      // `ready` never reaches this banner; render a neutral fallback safely.
      BleReadiness.ready => (
        Icons.bluetooth,
        l10n.connectEmptyTitle,
        l10n.connectEmptyDetail,
      ),
    };
    // No scan action — the adapter cannot scan in these states.
    return EmptyState(icon: icon, title: title, detail: detail);
  }
}

// ---------------------------------------------------------------------------
// Idle / scanning / list.
// ---------------------------------------------------------------------------

/// First-run / disconnected hero: an inviting "scan for boards" entry point.
class _IdleHero extends StatelessWidget {
  const _IdleHero({required this.controller});

  final ConnectController controller;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = AppLocalizations.of(context);
    return EmptyState(
      icon: Icons.bluetooth_searching,
      tone: SurfaceTone.action,
      title: l10n.connectEmptyTitle,
      detail: l10n.connectEmptyDetail,
      action: FilledButton.icon(
        key: _scanKey,
        onPressed: () => controller.startScan(),
        icon: const Icon(Icons.bluetooth_searching),
        label: Text(l10n.connectScanCta),
      ),
    );
  }
}

/// A scan is running but no board has answered yet.
class _ScanningEmpty extends StatelessWidget {
  const _ScanningEmpty({required this.controller});

  final ConnectController controller;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final AppLocalizations l10n = AppLocalizations.of(context);
    return _CenteredScroll(
      children: <Widget>[
        const SizedBox(
          width: 40,
          height: 40,
          child: CircularProgressIndicator(strokeWidth: 3),
        ),
        const SizedBox(height: SignalSpacing.lg),
        Text(l10n.connectScanning, style: theme.textTheme.titleMedium),
        const SizedBox(height: SignalSpacing.sm),
        Text(
          l10n.connectNoBoardsDetail,
          textAlign: TextAlign.center,
          style: theme.textTheme.bodyMedium?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: SignalSpacing.xl),
        OutlinedButton.icon(
          key: _stopKey,
          onPressed: () => controller.stopScan(),
          icon: const Icon(Icons.stop),
          label: Text(l10n.connectStopScan),
        ),
      ],
    );
  }
}

/// The live list of discovered PyBLE boards (name + RSSI), with a scanning /
/// rescan header. Tapping a row runs the connect handshake.
class _HitList extends StatelessWidget {
  const _HitList({required this.controller, required this.state});

  final ConnectController controller;
  final ConnectState state;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final AppLocalizations l10n = AppLocalizations.of(context);
    final bool scanning = state.isScanning;

    final Widget header = Padding(
      padding: const EdgeInsets.fromLTRB(
        SignalSpacing.lg,
        SignalSpacing.md,
        SignalSpacing.lg,
        SignalSpacing.sm,
      ),
      child: Row(
        children: <Widget>[
          if (scanning) ...<Widget>[
            const SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            const SizedBox(width: SignalSpacing.sm),
            Text(
              l10n.connectScanning,
              style: theme.textTheme.labelLarge?.copyWith(
                color: scheme.onSurfaceVariant,
              ),
            ),
          ] else
            Text(
              l10n.connectDiagHitCount(state.hitCount),
              style: theme.textTheme.labelLarge?.copyWith(
                color: scheme.onSurfaceVariant,
              ),
            ),
          const Spacer(),
          if (scanning)
            OutlinedButton.icon(
              key: _stopKey,
              onPressed: () => controller.stopScan(),
              icon: const Icon(Icons.stop),
              label: Text(l10n.connectStopScan),
            )
          else
            OutlinedButton.icon(
              key: _scanKey,
              onPressed: () => controller.startScan(),
              icon: const Icon(Icons.refresh),
              label: Text(l10n.connectRescan),
            ),
        ],
      ),
    );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        header,
        const Divider(height: 1),
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.symmetric(vertical: SignalSpacing.sm),
            itemCount: state.hits.length,
            itemBuilder: (BuildContext context, int i) => _HitTile(
              hit: state.hits[i],
              onTap: () => controller.connect(state.hits[i].id),
            ),
          ),
        ),
      ],
    );
  }
}

/// One discovered board: signal glyph + advertised name (verbatim) + RSSI.
class _HitTile extends StatelessWidget {
  const _HitTile({required this.hit, required this.onTap});

  final ScanHit hit;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final AppLocalizations l10n = AppLocalizations.of(context);
    return ListTile(
      key: _hitKey(hit.id),
      onTap: onTap,
      leading: Icon(_rssiGlyph(hit.rssi), color: scheme.primary),
      // The advertised name (user label else Pyble-XXXX) — display-only (SEC-9).
      title: Text(hit.name),
      subtitle: Text(l10n.connectRssiDbm(hit.rssi)),
      trailing: const Icon(Icons.chevron_right),
    );
  }
}

/// Signal-strength glyph for an RSSI (dBm): stronger nearer 0.
IconData _rssiGlyph(int rssi) {
  if (rssi >= -60) return Icons.signal_cellular_alt;
  if (rssi >= -75) return Icons.signal_cellular_alt_2_bar;
  return Icons.signal_cellular_alt_1_bar;
}

// ---------------------------------------------------------------------------
// Connecting / connected / failed.
// ---------------------------------------------------------------------------

class _ConnectingView extends StatelessWidget {
  const _ConnectingView({required this.state});

  final ConnectState state;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final AppLocalizations l10n = AppLocalizations.of(context);
    final String name = state.selected?.name ?? '';
    return _CenteredScroll(
      children: <Widget>[
        const SizedBox(
          width: 44,
          height: 44,
          child: CircularProgressIndicator(strokeWidth: 3),
        ),
        const SizedBox(height: SignalSpacing.lg),
        Text(
          l10n.connectConnecting(name),
          textAlign: TextAlign.center,
          style: theme.textTheme.titleMedium,
        ),
      ],
    );
  }
}

/// The connected state: the Board-info card (the round-trip PROOF) + Disconnect.
class _ConnectedView extends StatelessWidget {
  const _ConnectedView({required this.controller, required this.state});

  final ConnectController controller;
  final ConnectState state;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final AppLocalizations l10n = AppLocalizations.of(context);
    final DeviceInfo? info = state.deviceInfo;
    final String name = state.selected?.name ?? '';

    return SingleChildScrollView(
      padding: const EdgeInsets.all(SignalSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(
                Icons.check_circle,
                color: SignalStateColors.of(context).ready,
              ),
              const SizedBox(width: SignalSpacing.sm),
              Expanded(
                child: Text(
                  l10n.connectConnected(name),
                  style: theme.textTheme.titleMedium?.copyWith(
                    color: scheme.onSurface,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: SignalSpacing.lg),
          // The live DeviceInfo card — proof the GATT → HELLO round-trip works.
          Card(
            elevation: SignalElevation.level1,
            color: SignalElevation.tier(scheme, 1),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(SignalRadius.md),
            ),
            child: Padding(
              padding: const EdgeInsets.all(SignalSpacing.lg),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: <Widget>[
                  Text(
                    l10n.connectDeviceInfoTitle,
                    style: theme.textTheme.titleSmall?.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
                  ),
                  const SizedBox(height: SignalSpacing.md),
                  if (info == null)
                    const Center(
                      child: Padding(
                        padding: EdgeInsets.all(SignalSpacing.md),
                        child: SizedBox(
                          width: 24,
                          height: 24,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                      ),
                    )
                  else ...<Widget>[
                    // Chip is a technical identifier — rendered verbatim (FR-I18N-4).
                    _InfoRow(label: l10n.connectDeviceChip, value: info.chip),
                    _InfoRow(
                      label: l10n.connectDeviceMpyVersion,
                      value: info.mpyVersion,
                    ),
                    _InfoRow(
                      label: l10n.connectDeviceFreeMem,
                      value: l10n.connectFreeMemBytes(info.freeMem),
                    ),
                  ],
                ],
              ),
            ),
          ),
          const SizedBox(height: SignalSpacing.xl),
          OutlinedButton.icon(
            key: _disconnectKey,
            onPressed: () => controller.disconnect(),
            icon: const Icon(Icons.bluetooth_disabled),
            label: Text(l10n.connectDisconnect),
          ),
        ],
      ),
    );
  }
}

/// One label/value row in the Board-info card.
class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: SignalSpacing.xs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          SizedBox(
            width: 120,
            child: Text(
              label,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: scheme.onSurfaceVariant,
              ),
            ),
          ),
          const SizedBox(width: SignalSpacing.md),
          Expanded(
            child: Text(
              value,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: scheme.onSurface,
                fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// A connect attempt failed. Shows the localized reason (an unsupported
/// `proto_version` gets the firmware-update prompt, FR-CONNECT-6), the raw error
/// text for HIL debugging, and a retry.
class _FailedView extends StatelessWidget {
  const _FailedView({required this.controller, required this.state});

  final ConnectController controller;
  final ConnectState state;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final AppLocalizations l10n = AppLocalizations.of(context);
    final Object? error = state.lastError;
    final bool unsupported = error is UnsupportedProtocolException;
    final String title = unsupported
        ? l10n.connectUnsupportedFirmwareTitle
        : l10n.connectFailed;
    final String? detail = unsupported
        ? l10n.connectUnsupportedFirmwareDetail
        : null;

    return _CenteredScroll(
      children: <Widget>[
        Icon(Icons.error_outline, size: 40, color: scheme.error),
        const SizedBox(height: SignalSpacing.md),
        Text(
          title,
          textAlign: TextAlign.center,
          style: theme.textTheme.titleMedium?.copyWith(color: scheme.onSurface),
        ),
        if (detail != null) ...<Widget>[
          const SizedBox(height: SignalSpacing.sm),
          Text(
            detail,
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: scheme.onSurfaceVariant,
            ),
          ),
        ],
        const SizedBox(height: SignalSpacing.lg),
        // Raw diagnostic detail — verbatim, for on-hardware debugging.
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(SignalSpacing.md),
          decoration: BoxDecoration(
            color: scheme.surfaceContainerLowest,
            borderRadius: BorderRadius.circular(SignalRadius.sm),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(
                l10n.connectErrorDetailLabel,
                style: theme.textTheme.labelSmall?.copyWith(
                  color: scheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: SignalSpacing.xs),
              Text(
                '${error ?? ''}',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: scheme.onSurface,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: SignalSpacing.xl),
        FilledButton.icon(
          key: _scanKey,
          onPressed: () => controller.startScan(),
          icon: const Icon(Icons.refresh),
          label: Text(l10n.connectRescan),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Diagnostics panel (always visible, compact) — HIL debugging aid.
// ---------------------------------------------------------------------------

class _DiagnosticsPanel extends StatelessWidget {
  const _DiagnosticsPanel({required this.state, required this.l10n});

  final ConnectState state;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;

    final String adapter = switch (state.readiness) {
      BleReadiness.ready => l10n.connectDiagAdapterOn,
      BleReadiness.adapterOff => l10n.connectDiagAdapterOff,
      BleReadiness.unauthorized => l10n.connectDiagAdapterUnauthorized,
      BleReadiness.unsupported => l10n.connectDiagAdapterUnsupported,
    };
    final Object? error = state.lastError;

    return Container(
      width: double.infinity,
      color: SignalElevation.tier(scheme, 1),
      padding: const EdgeInsets.symmetric(
        horizontal: SignalSpacing.lg,
        vertical: SignalSpacing.sm,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(
                Icons.monitor_heart_outlined,
                size: 16,
                color: scheme.onSurfaceVariant,
              ),
              const SizedBox(width: SignalSpacing.xs),
              Text(
                l10n.connectDiagnosticsTitle,
                style: theme.textTheme.labelMedium?.copyWith(
                  color: scheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
          const SizedBox(height: SignalSpacing.xs),
          Wrap(
            spacing: SignalSpacing.lg,
            runSpacing: SignalSpacing.xs,
            children: <Widget>[
              _DiagChip(label: l10n.connectDiagAdapter, value: adapter),
              // Scan running is shown as a live dot rather than a word, so it
              // never collides with the main view's "Scanning…" label.
              _ScanDiag(
                label: l10n.connectDiagScan,
                idleText: l10n.connectDiagScanIdle,
                scanning: state.isScanning,
              ),
              _DiagChip(value: l10n.connectDiagHitCount(state.hitCount)),
              if (error != null)
                _DiagChip(label: l10n.connectDiagLastError, value: '$error'),
            ],
          ),
        ],
      ),
    );
  }
}

/// A compact `label: value` (or bare `value`) diagnostics readout. Uses plain
/// [Text] widgets (not `RichText`) so the value is independently findable.
class _DiagChip extends StatelessWidget {
  const _DiagChip({this.label, required this.value});

  final String? label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final String? label = this.label;
    final TextStyle? valueStyle = theme.textTheme.bodySmall?.copyWith(
      color: scheme.onSurface,
    );
    if (label == null) {
      return Text(value, style: valueStyle);
    }
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Text(
          '$label: ',
          style: theme.textTheme.bodySmall?.copyWith(
            color: scheme.onSurfaceVariant,
          ),
        ),
        Text(value, style: valueStyle),
      ],
    );
  }
}

/// The scan-running diagnostic: `Scan: ` + a live dot while scanning, else the
/// idle word. The dot avoids duplicating the main view's "Scanning…" label.
class _ScanDiag extends StatelessWidget {
  const _ScanDiag({
    required this.label,
    required this.idleText,
    required this.scanning,
  });

  final String label;
  final String idleText;
  final bool scanning;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Text(
          '$label: ',
          style: theme.textTheme.bodySmall?.copyWith(
            color: scheme.onSurfaceVariant,
          ),
        ),
        if (scanning)
          Icon(
            Icons.circle,
            size: 10,
            color: SignalStateColors.of(context).running,
          )
        else
          Text(
            idleText,
            style: theme.textTheme.bodySmall?.copyWith(color: scheme.onSurface),
          ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Shared layout helper.
// ---------------------------------------------------------------------------

/// A centered, overflow-safe column (scrolls when height-constrained or at large
/// text scale), matching the [EmptyState] layout contract.
class _CenteredScroll extends StatelessWidget {
  const _CenteredScroll({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
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
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: children,
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}
