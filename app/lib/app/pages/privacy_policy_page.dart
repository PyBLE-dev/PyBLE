// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// X-11 — the complete, bundled policy, available without a board or network.
library;

import 'package:flutter/material.dart';

import 'package:pyble/localization/localization.dart';
import 'package:pyble/theme/theme.dart';

/// Offline counterpart of https://pyble.dev/privacy (FR-ABOUT-9).
class PrivacyPolicyPage extends StatelessWidget {
  const PrivacyPolicyPage({super.key});

  static const String routeName = '/about/privacy';
  // Technical contact identifiers remain verbatim across locales (FR-I18N-4).
  static const String _policyUrl = 'https://pyble.dev/privacy';
  static const String _contactEmail = 'viwat.v@chula.ac.th';

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = AppLocalizations.of(context);
    final TextTheme textTheme = Theme.of(context).textTheme;
    final List<({String title, String body})>
    sections = <({String title, String body})>[
      (title: l10n.privacyMaintainerTitle, body: l10n.privacyMaintainerBody),
      (title: l10n.privacyAppTitle, body: l10n.privacyAppBody),
      (title: l10n.privacyGithubTitle, body: l10n.privacyGithubBody),
      (title: l10n.privacyBoardTitle, body: l10n.privacyBoardBody),
      (title: l10n.privacyTransportTitle, body: l10n.privacyTransportBody),
      (title: l10n.privacyPermissionsTitle, body: l10n.privacyPermissionsBody),
      (title: l10n.privacyRetentionTitle, body: l10n.privacyRetentionBody),
      (title: l10n.privacyComponentsTitle, body: l10n.privacyComponentsBody),
      (title: l10n.privacyWebsiteTitle, body: l10n.privacyWebsiteBody),
      (title: l10n.privacyChangesTitle, body: l10n.privacyChangesBody),
      (title: l10n.privacyContactTitle, body: l10n.privacyContactBody),
    ];

    return Scaffold(
      key: const Key('privacyPolicyPage'),
      appBar: AppBar(title: Text(l10n.privacyPolicyTitle)),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(SignalSpacing.lg),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 800),
              child: SelectionArea(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: <Widget>[
                    Text(l10n.privacyPolicyIntroduction),
                    const SizedBox(height: SignalSpacing.md),
                    Text(l10n.privacyPolicyEffectiveDate),
                    const SizedBox(height: SignalSpacing.sm),
                    const Text(_policyUrl),
                    for (final ({String title, String body}) section
                        in sections) ...<Widget>[
                      const SizedBox(height: SignalSpacing.xl),
                      Semantics(
                        header: true,
                        child: Text(section.title, style: textTheme.titleLarge),
                      ),
                      const SizedBox(height: SignalSpacing.sm),
                      Text(section.body),
                    ],
                    const SizedBox(height: SignalSpacing.sm),
                    const Text(_contactEmail),
                    const SizedBox(height: SignalSpacing.lg),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
