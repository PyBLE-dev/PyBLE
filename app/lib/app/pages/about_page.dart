// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// X-11 — responsive, board-independent About and open-source information.
library;

import 'package:flutter/material.dart';

import 'package:pyble/localization/localization.dart';
import 'package:pyble/theme/theme.dart';

import '../app_build_info.dart';

const double _kAboutMaxWidth = 1080;
const double _kAboutTwoColumnMinWidth = 840;
const double _kAboutHeroRowMinWidth = 640;
const String _kProjectWebsite = 'pyble.dev';
const List<String> _kPlatformIdentifiers = <String>[
  'esp32',
  'esp32-s3',
  'esp32-c3',
  'PBLE/1',
];

/// A full About route that owns no board/provider state (FR-ABOUT-1..8).
class AboutPage extends StatefulWidget {
  const AboutPage({
    this.buildInfoLoader = defaultAppBuildInfoLoader,
    super.key,
  });

  /// Stable route name for diagnostics and restoration tests.
  static const String routeName = '/about';

  /// Runtime package-metadata seam; production uses the installed package.
  final AppBuildInfoLoader buildInfoLoader;

  @override
  State<AboutPage> createState() => _AboutPageState();
}

class _AboutPageState extends State<AboutPage> {
  late final Future<AppBuildInfo> _buildInfoFuture;
  AppBuildInfo? _resolvedBuildInfo;

  @override
  void initState() {
    super.initState();
    _buildInfoFuture = Future<AppBuildInfo>.sync(widget.buildInfoLoader).then((
      AppBuildInfo value,
    ) {
      _resolvedBuildInfo = value;
      return value;
    });
  }

  String _versionText(AppLocalizations l10n, AppBuildInfo info) {
    final String version = info.version.trim();
    if (version.isEmpty) return l10n.aboutVersionUnavailable;
    final String buildNumber = info.buildNumber.trim();
    return buildNumber.isEmpty
        ? l10n.aboutVersion(version)
        : l10n.aboutVersionWithBuild(version, buildNumber);
  }

  void _openLicenses(AppLocalizations l10n) {
    final AppBuildInfo? info = _resolvedBuildInfo;
    final String? applicationVersion = info == null
        ? null
        : _versionText(l10n, info);
    Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        settings: const RouteSettings(name: '/about/licenses'),
        builder: (BuildContext context) => LicensePage(
          applicationName: l10n.appTitle,
          applicationVersion: applicationVersion,
          applicationLegalese: l10n.aboutLegalese,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = AppLocalizations.of(context);
    return Scaffold(
      key: const Key('aboutPage'),
      appBar: AppBar(title: Text(l10n.aboutTitle)),
      body: SafeArea(
        child: LayoutBuilder(
          builder: (BuildContext context, BoxConstraints constraints) {
            final bool useTwoColumns =
                constraints.maxWidth >= _kAboutTwoColumnMinWidth;
            return SingleChildScrollView(
              key: const Key('aboutPageScroll'),
              padding: EdgeInsets.symmetric(
                horizontal: constraints.maxWidth < 600
                    ? SignalSpacing.lg
                    : SignalSpacing.xxl,
                vertical: SignalSpacing.xl,
              ),
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: _kAboutMaxWidth),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: <Widget>[
                      _AboutHero(
                        buildInfoFuture: _buildInfoFuture,
                        versionText: (AppBuildInfo info) =>
                            _versionText(l10n, info),
                      ),
                      const SizedBox(height: SignalSpacing.xl),
                      if (useTwoColumns)
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: <Widget>[
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.stretch,
                                children: <Widget>[
                                  _PlatformCard(l10n: l10n),
                                  const SizedBox(height: SignalSpacing.lg),
                                  _OpenSourceCard(
                                    l10n: l10n,
                                    onOpenLicenses: () => _openLicenses(l10n),
                                  ),
                                ],
                              ),
                            ),
                            const SizedBox(width: SignalSpacing.lg),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.stretch,
                                children: <Widget>[
                                  _PrivacyCard(l10n: l10n),
                                  const SizedBox(height: SignalSpacing.lg),
                                  _ProjectCard(l10n: l10n),
                                ],
                              ),
                            ),
                          ],
                        )
                      else
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: <Widget>[
                            _PlatformCard(l10n: l10n),
                            const SizedBox(height: SignalSpacing.lg),
                            _OpenSourceCard(
                              l10n: l10n,
                              onOpenLicenses: () => _openLicenses(l10n),
                            ),
                            const SizedBox(height: SignalSpacing.lg),
                            _PrivacyCard(l10n: l10n),
                            const SizedBox(height: SignalSpacing.lg),
                            _ProjectCard(l10n: l10n),
                          ],
                        ),
                      const SizedBox(height: SignalSpacing.xl),
                      Text(
                        l10n.aboutLegalese,
                        key: const Key('aboutPageEnd'),
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                        textAlign: TextAlign.center,
                      ),
                    ],
                  ),
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _AboutHero extends StatelessWidget {
  const _AboutHero({required this.buildInfoFuture, required this.versionText});

  final Future<AppBuildInfo> buildInfoFuture;
  final String Function(AppBuildInfo info) versionText;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = AppLocalizations.of(context);
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(SignalSpacing.xl),
        child: LayoutBuilder(
          builder: (BuildContext context, BoxConstraints constraints) {
            final Widget badge = ExcludeSemantics(
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.primaryContainer,
                  borderRadius: BorderRadius.circular(SignalRadius.lg),
                ),
                child: SizedBox(
                  width: 80,
                  height: 80,
                  child: Icon(
                    Icons.bluetooth_connected,
                    size: 42,
                    color: Theme.of(context).colorScheme.onPrimaryContainer,
                  ),
                ),
              ),
            );
            final Widget copy = _HeroCopy(
              buildInfoFuture: buildInfoFuture,
              versionText: versionText,
              l10n: l10n,
            );
            if (constraints.maxWidth < _kAboutHeroRowMinWidth) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  badge,
                  const SizedBox(height: SignalSpacing.lg),
                  copy,
                ],
              );
            }
            return Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: <Widget>[
                badge,
                const SizedBox(width: SignalSpacing.xl),
                Expanded(child: copy),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _HeroCopy extends StatelessWidget {
  const _HeroCopy({
    required this.buildInfoFuture,
    required this.versionText,
    required this.l10n,
  });

  final Future<AppBuildInfo> buildInfoFuture;
  final String Function(AppBuildInfo info) versionText;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Semantics(
          header: true,
          child: Text(
            l10n.appTitle,
            key: const Key('aboutProductHeading'),
            style: Theme.of(context).textTheme.headlineMedium,
          ),
        ),
        const SizedBox(height: SignalSpacing.xs),
        Text(
          l10n.aboutTagline,
          style: Theme.of(context).textTheme.titleMedium?.copyWith(
            color: Theme.of(context).colorScheme.primary,
          ),
        ),
        const SizedBox(height: SignalSpacing.md),
        FutureBuilder<AppBuildInfo>(
          future: buildInfoFuture,
          builder:
              (BuildContext context, AsyncSnapshot<AppBuildInfo> snapshot) {
                final String label;
                if (snapshot.connectionState != ConnectionState.done) {
                  label = l10n.aboutVersionLabel;
                } else if (snapshot.hasError || !snapshot.hasData) {
                  label = l10n.aboutVersionUnavailable;
                } else {
                  label = versionText(snapshot.requireData);
                }
                return Chip(
                  key: const Key('aboutVersionChip'),
                  avatar: const Icon(Icons.verified_outlined, size: 18),
                  label: Text(label),
                );
              },
        ),
        const SizedBox(height: SignalSpacing.md),
        Text(l10n.aboutProductBody),
      ],
    );
  }
}

class _PlatformCard extends StatelessWidget {
  const _PlatformCard({required this.l10n});

  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    return _AboutSectionCard(
      icon: Icons.developer_board_outlined,
      title: l10n.aboutPlatformTitle,
      titleKey: const Key('aboutPlatformHeading'),
      body: l10n.aboutPlatformBody,
      child: Wrap(
        spacing: SignalSpacing.sm,
        runSpacing: SignalSpacing.sm,
        children: <Widget>[
          for (final String identifier in _kPlatformIdentifiers)
            Chip(label: Text(identifier)),
        ],
      ),
    );
  }
}

class _OpenSourceCard extends StatelessWidget {
  const _OpenSourceCard({required this.l10n, required this.onOpenLicenses});

  final AppLocalizations l10n;
  final VoidCallback onOpenLicenses;

  @override
  Widget build(BuildContext context) {
    return _AboutSectionCard(
      icon: Icons.code,
      title: l10n.aboutOpenSourceTitle,
      titleKey: const Key('aboutOpenSourceHeading'),
      body: l10n.aboutOpenSourceBody,
      child: Align(
        alignment: AlignmentDirectional.centerStart,
        child: OutlinedButton.icon(
          key: const Key('aboutOpenSourceLicensesAction'),
          onPressed: onOpenLicenses,
          icon: const Icon(Icons.description_outlined),
          label: Text(l10n.aboutOpenSourceLicensesAction),
        ),
      ),
    );
  }
}

class _PrivacyCard extends StatelessWidget {
  const _PrivacyCard({required this.l10n});

  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    return _AboutSectionCard(
      icon: Icons.shield_outlined,
      title: l10n.aboutPrivacyTitle,
      titleKey: const Key('aboutPrivacyHeading'),
      body: l10n.aboutPrivacyBody,
    );
  }
}

class _ProjectCard extends StatelessWidget {
  const _ProjectCard({required this.l10n});

  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    return _AboutSectionCard(
      icon: Icons.public,
      title: l10n.aboutProjectTitle,
      titleKey: const Key('aboutProjectHeading'),
      body: l10n.aboutProjectBody,
      child: SelectionArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(
              l10n.aboutProjectWebsiteLabel,
              style: Theme.of(context).textTheme.labelLarge,
            ),
            const SizedBox(height: SignalSpacing.xs),
            Text(
              _kProjectWebsite,
              style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                color: Theme.of(context).colorScheme.primary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AboutSectionCard extends StatelessWidget {
  const _AboutSectionCard({
    required this.icon,
    required this.title,
    required this.titleKey,
    required this.body,
    this.child,
  });

  final IconData icon;
  final String title;
  final Key titleKey;
  final String body;
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    final ColorScheme scheme = Theme.of(context).colorScheme;
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(SignalSpacing.xl),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            ExcludeSemantics(
              child: Icon(icon, color: scheme.primary, size: 28),
            ),
            const SizedBox(height: SignalSpacing.md),
            Semantics(
              header: true,
              child: Text(
                title,
                key: titleKey,
                style: Theme.of(context).textTheme.titleLarge,
              ),
            ),
            const SizedBox(height: SignalSpacing.sm),
            Text(body),
            if (child != null) ...<Widget>[
              const SizedBox(height: SignalSpacing.lg),
              child!,
            ],
          ],
        ),
      ),
    );
  }
}
