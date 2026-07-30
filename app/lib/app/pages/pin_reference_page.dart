// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-05 — the read-only, chip-keyed pin-reference pane (FR-UI-4, CON-7). Hosted
/// by the shell's landscape right pane; extracted here so app-viz-engineer can
/// own its populated content (the chip pin table) without re-opening the shell
/// frame.
///
/// **Strictly informational (CON-7).** The chip identity is read through the
/// [Connection] seam (`deviceInfo().chip`) — never `lib/ble` (CON-8) — and the
/// pane renders reference-only: no switches, inputs, editable fields, or CTA,
/// and it is NEVER a stored/enforced board/routing/pin profile or capability
/// map. The chip identifier is a technical token rendered verbatim (FR-I18N-4).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';
import 'package:pyble/theme/theme.dart';

import '../providers.dart';
import 'surface_placeholder.dart';

/// The read-only pin-reference pane content. Keyed off the connected chip; shows
/// a generic reference before the chip is known.
///
/// This is the pre-feature first-run state for the pane: a designed
/// informational empty state that, once a board is connected, surfaces the
/// chip identity as a read-only tag. The populated pin table lands later on the
/// same seam — this state never becomes editable or a stored profile (CON-7).
class PinReferencePage extends ConsumerWidget {
  const PinReferencePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final Connection connection = ref.watch(connectionProvider);
    final AppLocalizations l10n = AppLocalizations.of(context);
    return FutureBuilder<DeviceInfo>(
      future: connection.deviceInfo(),
      builder: (BuildContext context, AsyncSnapshot<DeviceInfo> snapshot) {
        final String chip = snapshot.data?.chip ?? '';
        final bool chipKnown = chip.isNotEmpty;
        // `chip` (e.g. esp32-s3) is a technical identifier carried verbatim via
        // the {chip} placeholder — never localized (FR-I18N-4).
        final String detail = chipKnown
            ? l10n.pinReferenceDetailForChip(chip)
            : l10n.pinReferenceDetailGeneric;
        // Informational tone (§7.9): reads as reference, not action (CON-7).
        // Once the chip is known, its identity rides in the (non-interactive)
        // action slot as a read-only tag — the pane still exposes no CTA.
        return EmptyState(
          icon: Icons.developer_board_outlined,
          title: l10n.pinReferenceTitle,
          detail: detail,
          tone: SurfaceTone.informational,
          action: chipKnown ? _ChipIdentityTag(chip: chip) : null,
        );
      },
    );
  }
}

/// A read-only tag rendering the connected chip identifier verbatim (FR-I18N-4).
///
/// Intentionally NOT a button or input: it is a static, `readOnly` reference tag
/// so the pane can never read as an editable or stored profile (CON-7). The
/// identifier uses the monospace code style (a verbatim technical token), tinted
/// to match the informational badge (`tertiaryContainer`).
class _ChipIdentityTag extends StatelessWidget {
  const _ChipIdentityTag({required this.chip});

  /// The chip target (e.g. `esp32-s3`), rendered verbatim — never localized.
  final String chip;

  @override
  Widget build(BuildContext context) {
    final ColorScheme scheme = Theme.of(context).colorScheme;
    return Semantics(
      readOnly: true,
      child: Container(
        padding: const EdgeInsets.symmetric(
          horizontal: SignalSpacing.md,
          vertical: SignalSpacing.sm,
        ),
        decoration: ShapeDecoration(
          color: scheme.tertiaryContainer,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(SignalRadius.sm),
          ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(
              Icons.memory_outlined,
              size: 18,
              color: scheme.onTertiaryContainer,
            ),
            const SizedBox(width: SignalSpacing.xs),
            Text(
              chip,
              style: SignalType.code.copyWith(
                color: scheme.onTertiaryContainer,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
