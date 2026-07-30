// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-05 — the responsive app shell (FR-UI-1/2/5/7), styled to the "Signal"
/// design system (design-system.md, ADR-0008). Owns the navigation frame, the
/// responsive-layout scaffold, the toolbar + console-strip slots, and the
/// focused Blocks workspace. Every widget binds to a board exclusively through
/// the [Connection] seam (CON-8) — no file here imports `lib/ble`, and no
/// transport type is referenced (D2).
///
/// Chrome themes entirely from `Theme.of(context)` + the Signal tokens
/// (`package:pyble/theme/theme.dart`); no `Colors.*` literals and no per-surface
/// brand/state colors (NFR-MAINT-2). All copy is sourced from
/// [AppLocalizations].
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/console/console.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';
import 'package:pyble/theme/theme.dart';

import 'pages/about_page.dart';
import 'pages/blocks_page.dart';
import 'pages/connect_page.dart';
import 'pages/console_page.dart';
import 'pages/editor_page.dart';
import 'pages/files_page.dart';
import 'pages/pin_reference_page.dart';
import 'providers.dart';
import 'widgets/connection_status_pill.dart';

/// Below this width the shell is a single-pane stacked layout (FR-UI-5).
const double kPhoneMaxWidth = 600;

/// At or above this width a genuinely landscape surface uses the three-pane
/// layout (FR-UI-1). Portrait stays stacked even on a 1024 dp-wide iPad
/// (FR-UI-2); width alone must not misclassify its orientation.
const double kTabletLandscapeMinWidth = 900;

/// Below this toolbar width the app wordmark is dropped first (§7.1 shrink
/// order) so the connection-status signal + actions never overflow on a phone.
const double _kToolbarWordmarkMinWidth = 480;

/// Shell navigation destination icons, in [AppSurface] order (FR-UI).
const List<IconData> _destinationIcons = <IconData>[
  Icons.bluetooth,
  Icons.code,
  Icons.terminal,
  Icons.folder_outlined,
  Icons.account_tree_outlined,
];

/// Navigation labels, in [AppSurface] order (FR-UI), sourced from
/// [AppLocalizations] so they follow the active locale (FR-I18N-1).
List<String> _destinationLabels(AppLocalizations l10n) => <String>[
  l10n.navConnect,
  l10n.navEditor,
  l10n.navConsole,
  l10n.navFiles,
  l10n.navBlocks,
];

/// Non-platform-view surface bodies, in their first four [AppSurface] slots.
/// Kept in an [IndexedStack] so their state survives navigation. Blocks is
/// intentionally built lazily outside this stack.
const List<Widget> _surfaces = <Widget>[
  ConnectPage(),
  EditorPage(),
  ConsolePage(),
  FilesPage(),
];

/// The IDE navigation destinations, shown once a board is connected. Connect is
/// deliberately absent — it is the pre-connection full-screen surface, not an
/// IDE tab (ADR-0011). In landscape Files is the collapsible left sidebar (a
/// rail toggle), while Blocks switches to its canvas-first focused workbench.
const List<AppSurface> _ideNavSurfaces = <AppSurface>[
  AppSurface.editor,
  AppSurface.console,
  AppSurface.files,
  AppSurface.blocks,
];

/// Full-width destinations in the stacked connected IDE (FR-UI-2, ADR-0013).
const List<AppSurface> _stackedNavSurfaces = <AppSurface>[
  AppSurface.editor,
  AppSurface.console,
  AppSurface.files,
  AppSurface.blocks,
];

/// The centre work surface for the text landscape workbench — Editor or Console
/// only (Connect is pre-connection; Files is the left sidebar). Blocks owns a
/// separate focused workbench. Defaults to Editor.
AppSurface _centreSurface(AppSurface selected) {
  switch (selected) {
    case AppSurface.editor:
    case AppSurface.console:
      return selected;
    case AppSurface.connect:
    case AppSurface.files:
    case AppSurface.blocks:
      return AppSurface.editor;
  }
}

/// The top-level responsive shell (FR-UI-1/2/5, NFR-COMPAT-1). Connection-gated
/// (ADR-0011): before a board is connected the app is a full-screen Connect
/// experience; the IDE chrome (Files sidebar, Pin-reference pane, console strip)
/// appears only once a board is ready — so Files/Pins/console never flank the
/// pre-connection flow. Above the ready threshold it picks the landscape three-
/// pane or the stacked layout by available width.
class PybleShell extends ConsumerWidget {
  const PybleShell({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final connState = ref.watch(connStateProvider);
    return ValueListenableBuilder<ConnState>(
      valueListenable: connState,
      builder: (BuildContext context, ConnState state, _) {
        final bool boardReady =
            state == ConnState.ready || state == ConnState.running;
        if (!boardReady) {
          return const _DisconnectedShell();
        }
        return LayoutBuilder(
          builder: (BuildContext context, BoxConstraints constraints) {
            final bool wideLandscape =
                constraints.maxWidth >= kTabletLandscapeMinWidth &&
                constraints.maxWidth > constraints.maxHeight;
            if (wideLandscape) {
              return const _LandscapeShell();
            }
            return const _StackedShell();
          },
        );
      },
    );
  }
}

/// The pre-connection shell (FR-UI-1, ADR-0011): the status toolbar over a
/// full-screen Connect surface, with NO IDE chrome — no Files sidebar,
/// Pin-reference pane, or console strip, none of which means anything without a
/// board. The toolbar's connection action is an inert Connect slot here (the
/// live scan/connect flow is the surface below); Run/Stop are disabled.
class _DisconnectedShell extends StatelessWidget {
  const _DisconnectedShell();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: SafeArea(
        child: Column(
          children: <Widget>[
            _Toolbar(),
            Divider(height: 1),
            Expanded(child: ConnectPage()),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Landscape (w >= 900): the navigation rail switches between the text
// workbench (Files | Editor/Console | Pin reference) and a focused, canvas-first
// Blocks workbench (ADR-0014).
// ---------------------------------------------------------------------------

class _LandscapeShell extends ConsumerWidget {
  const _LandscapeShell();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppSurface selected = ref.watch(selectedSurfaceProvider);
    final bool filesCollapsed = ref.watch(filesPaneCollapsedProvider);
    final bool blocksFocused = selected == AppSurface.blocks;
    final bool blocksConsoleExpanded = ref.watch(blocksConsoleExpandedProvider);
    final AppLocalizations l10n = AppLocalizations.of(context);

    final AppSurface centre = _centreSurface(selected);

    // A new output event should reveal itself without stealing focus or
    // overlaying the workspace. Clearing the buffer does not expand the strip.
    ref.listen<List<ConsoleEvent>>(consoleBufferProvider, (
      List<ConsoleEvent>? previous,
      List<ConsoleEvent> next,
    ) {
      if (previous == null ||
          next.isEmpty ||
          identical(previous, next) ||
          ref.read(selectedSurfaceProvider) != AppSurface.blocks) {
        return;
      }
      ref.read(blocksConsoleExpandedProvider.notifier).state = true;
    });

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: <Widget>[
            // Keep the console ring subscribed regardless of the focused surface
            // (FR-CONSOLE-7); zero-size, always mounted.
            const _ConsoleKeepAlive(),
            _Toolbar(showRun: !blocksFocused),
            const Divider(height: 1),
            Expanded(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: <Widget>[
                  _SurfaceRail(
                    selected: blocksFocused ? AppSurface.blocks : centre,
                    filesCollapsed: filesCollapsed,
                  ),
                  const VerticalDivider(width: 1),
                  if (blocksFocused)
                    Expanded(
                      key: const ValueKey<String>('focusedBlocksWorkspace'),
                      child: BlocksPage(
                        onRunStarted: () {
                          ref
                                  .read(blocksConsoleExpandedProvider.notifier)
                                  .state =
                              true;
                        },
                      ),
                    )
                  else ...<Widget>[
                    // Files lives in the left pane of the text workbench and
                    // never competes with the focused Blocks canvas.
                    if (filesCollapsed)
                      _CollapsedFilesRail(
                        onExpand: () =>
                            ref
                                    .read(filesPaneCollapsedProvider.notifier)
                                    .state =
                                false,
                      )
                    else
                      Expanded(
                        flex: 3,
                        child: _TitledPane(
                          title: l10n.navFiles,
                          trailing: IconButton(
                            icon: const Icon(Icons.chevron_left),
                            iconSize: 18,
                            visualDensity: VisualDensity.compact,
                            padding: EdgeInsets.zero,
                            constraints: const BoxConstraints(
                              minWidth: 32,
                              minHeight: 32,
                            ),
                            tooltip: l10n.filesPaneCollapse,
                            onPressed: () =>
                                ref
                                        .read(
                                          filesPaneCollapsedProvider.notifier,
                                        )
                                        .state =
                                    true,
                          ),
                          child: const FilesPage(),
                        ),
                      ),
                    const VerticalDivider(width: 1),
                    Expanded(
                      flex: 5,
                      child: _TitledPane(
                        title: _destinationLabels(l10n)[centre.index],
                        child: IndexedStack(
                          index: centre.index,
                          children: _surfaces,
                        ),
                      ),
                    ),
                    const VerticalDivider(width: 1),
                    Expanded(
                      flex: 3,
                      child: _TitledPane(
                        title: l10n.pinReferenceTitle,
                        child: const PinReferencePage(),
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const Divider(height: 1),
            ConsoleStripView(
              collapsed: blocksFocused && !blocksConsoleExpanded,
              onToggle: blocksFocused
                  ? () {
                      ref.read(blocksConsoleExpandedProvider.notifier).state =
                          !blocksConsoleExpanded;
                    }
                  : null,
            ),
          ],
        ),
      ),
    );
  }
}

/// The collapsed state of the landscape Files sidebar (FR-UI-1): a thin rail
/// with an expand affordance so the pane can be restored. Tapping anywhere on
/// the rail (or the Files navigation destination) re-expands it.
class _CollapsedFilesRail extends StatelessWidget {
  const _CollapsedFilesRail({required this.onExpand});
  final VoidCallback onExpand;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = AppLocalizations.of(context);
    final ColorScheme scheme = Theme.of(context).colorScheme;
    return SizedBox(
      width: 44,
      child: Column(
        children: <Widget>[
          SizedBox(
            height: 44,
            child: IconButton(
              icon: const Icon(Icons.chevron_right),
              iconSize: 18,
              tooltip: l10n.filesPaneExpand,
              onPressed: onExpand,
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: InkWell(
              onTap: onExpand,
              child: Center(
                child: RotatedBox(
                  quarterTurns: 3,
                  child: Text(
                    l10n.navFiles,
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// The persistent left navigation rail for the landscape layout. Shows all four
/// destination labels (FR-UI); themed via `navigationRailTheme` (§7.2).
class _SurfaceRail extends ConsumerWidget {
  const _SurfaceRail({required this.selected, required this.filesCollapsed});

  /// The selected destination. Files remains a sidebar toggle in the text
  /// workbench; Blocks is a full focused destination.
  final AppSurface selected;
  final bool filesCollapsed;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final List<String> labels = _destinationLabels(
      AppLocalizations.of(context),
    );
    final int selectedIndex = _ideNavSurfaces.indexOf(selected);
    return NavigationRail(
      selectedIndex: selectedIndex < 0 ? 0 : selectedIndex,
      labelType: NavigationRailLabelType.all,
      onDestinationSelected: (int index) {
        final AppSurface surface = _ideNavSurfaces[index];
        if (surface == AppSurface.files) {
          if (selected == AppSurface.blocks) {
            // Leaving focused Blocks for Files restores the text workbench with
            // its sidebar visible.
            ref.read(selectedSurfaceProvider.notifier).state =
                AppSurface.editor;
            ref.read(filesPaneCollapsedProvider.notifier).state = false;
          } else {
            ref.read(filesPaneCollapsedProvider.notifier).state =
                !filesCollapsed;
          }
        } else {
          if (surface == AppSurface.blocks && selected != AppSurface.blocks) {
            ref.read(blocksConsoleExpandedProvider.notifier).state = false;
          }
          ref.read(selectedSurfaceProvider.notifier).state = surface;
        }
      },
      destinations: <NavigationRailDestination>[
        for (final AppSurface s in _ideNavSurfaces)
          NavigationRailDestination(
            // The Files icon reflects the sidebar state (open when expanded).
            icon: Icon(
              s == AppSurface.files
                  ? (filesCollapsed ? Icons.folder_outlined : Icons.folder_open)
                  : _destinationIcons[s.index],
            ),
            label: Text(labels[s.index]),
          ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Stacked (w < 900): a single primary surface with a bottom NavigationBar.
// Serves both portrait tablet (FR-UI-2) and phone (FR-UI-5, best-effort).
// ---------------------------------------------------------------------------

class _StackedShell extends ConsumerWidget {
  const _StackedShell();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppSurface selected = ref.watch(selectedSurfaceProvider);
    // Connect is the pre-connection screen (ADR-0011); default the stacked IDE
    // to the editor when no work surface has been chosen yet.
    final AppSurface current = selected == AppSurface.connect
        ? AppSurface.editor
        : selected;
    final List<String> labels = _destinationLabels(
      AppLocalizations.of(context),
    );
    final int navIndex = _stackedNavSurfaces.indexOf(current);
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: <Widget>[
            // Keep the console ring subscribed even while another surface is
            // focused, so early output survives navigation (FR-CONSOLE-7).
            const _ConsoleKeepAlive(),
            // No always-visible strip here: Run focuses the Console surface.
            _Toolbar(
              focusConsoleOnRun: current != AppSurface.blocks,
              showRun: current != AppSurface.blocks,
            ),
            const Divider(height: 1),
            Expanded(
              child: current == AppSurface.blocks
                  // Platform views are expensive and awkward offstage. The
                  // provider retains/restores Blockly JSON, so build it only
                  // while the destination is visible (ADR-0013).
                  ? const BlocksPage()
                  : IndexedStack(index: current.index, children: _surfaces),
            ),
          ],
        ),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: navIndex < 0 ? 0 : navIndex,
        onDestinationSelected: (int index) {
          final AppSurface surface = _stackedNavSurfaces[index];
          ref.read(selectedSurfaceProvider.notifier).state = surface;
        },
        destinations: <NavigationDestination>[
          for (final AppSurface s in _stackedNavSurfaces)
            NavigationDestination(
              icon: Icon(_destinationIcons[s.index]),
              label: labels[s.index],
            ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Toolbar slot (FR-UI-3, §7.1). The shell owns the SLOT and wires the three run-
// control actions (Run / Stop / Soft-reboot) to [runControllerProvider], with
// each button's enabled state derived from [runAvailabilityProvider] (the live
// ConnState). Connect stays an inert slot — its live flow is the Connect surface
// (app-connect-engineer's story). EBusy from Run is surfaced honestly via
// `runBusyMessage`, never swallowed (FR-RUN-3). All board access crosses the
// Connection seam only (CON-8); no `lib/ble` import.
// ---------------------------------------------------------------------------

enum _ToolbarMoreAction { softReboot, about }

class _Toolbar extends ConsumerWidget {
  const _Toolbar({this.focusConsoleOnRun = false, this.showRun = true});

  /// In the stacked layout there is no always-visible console strip, so Run
  /// focuses the Console surface to keep output in view (§7.5). The landscape
  /// layout leaves this false (the strip is always shown).
  final bool focusConsoleOnRun;

  /// The toolbar Run targets the text editor. Focused Blocks owns its one Run
  /// action in the feature strip, so this slot is omitted there (ADR-0014).
  final bool showRun;

  Future<void> _run(BuildContext context, WidgetRef ref) async {
    if (focusConsoleOnRun) {
      ref.read(selectedSurfaceProvider.notifier).state = AppSurface.console;
    }
    // Capture before the await so no BuildContext is used across the async gap.
    final ScaffoldMessengerState messenger = ScaffoldMessenger.of(context);
    final AppLocalizations l10n = AppLocalizations.of(context);
    try {
      await ref.read(runControllerProvider).run();
    } on EBusy {
      // EBusy is never swallowed: tell the user a program is already running.
      messenger.showSnackBar(SnackBar(content: Text(l10n.runBusyMessage)));
    } catch (e) {
      // NOTHING else was surfaced before: every other failure (a typed ERange
      // for an over-long buffer, a link timeout, a torn-down connection)
      // became an unhandled async error, so pressing Run did LITERALLY nothing
      // visible. FR-RUN-3 requires the failure to be honest.
      messenger.showSnackBar(
        SnackBar(content: Text(l10n.runFailed(_reasonOf(e)))),
      );
    }
  }

  /// Fires a run-control verb that has no success feedback (Stop / Soft-reboot),
  /// surfacing any failure instead of dropping it on the floor.
  static Future<void> _guard(
    ScaffoldMessengerState messenger,
    AppLocalizations l10n,
    Future<void> Function() action,
  ) async {
    try {
      await action();
    } catch (e) {
      messenger.showSnackBar(
        SnackBar(content: Text(l10n.runFailed(_reasonOf(e)))),
      );
    }
  }

  /// The technical reason token for [e]. A typed PBLE/1 §8 status name is a
  /// technical identifier rendered verbatim (FR-I18N-4).
  static String _reasonOf(Object e) =>
      e is PbleException ? e.runtimeType.toString() : e.toString();

  static void _openAbout(BuildContext context) {
    Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        settings: const RouteSettings(name: AboutPage.routeName),
        builder: (BuildContext context) => const AboutPage(),
      ),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    final AppLocalizations l10n = AppLocalizations.of(context);
    final RunAvailability run = ref.watch(runAvailabilityProvider);

    // A disabled Run explains why: no board vs a program already running.
    final String runTooltip = run.canRun
        ? l10n.toolbarRun
        : run.isRunning
        ? l10n.runBusyMessage
        : l10n.runDisconnectedHint;

    return Material(
      // Level 4 tonal surface, no shadow (§4, §7.1).
      color: SignalElevation.tier(scheme, 4),
      child: LayoutBuilder(
        builder: (BuildContext context, BoxConstraints constraints) {
          final bool showWordmark =
              constraints.maxWidth >= _kToolbarWordmarkMinWidth;
          final bool compactActions = constraints.maxWidth < kPhoneMaxWidth;
          // Min-height, not a fixed box: grows with textScale rather than
          // clipping (§7.1).
          return ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 56),
            child: Padding(
              padding: const EdgeInsets.only(
                left: SignalSpacing.lg,
                right: SignalSpacing.sm,
              ),
              child: Row(
                children: <Widget>[
                  if (showWordmark) ...<Widget>[
                    // Brand proper noun, verbatim; cosmetic chrome clamps ≤ 1.3.
                    Text(
                      l10n.appTitle,
                      style: theme.textTheme.titleMedium?.copyWith(
                        color: scheme.onSurface,
                      ),
                      textScaler: MediaQuery.textScalerOf(
                        context,
                      ).clamp(maxScaleFactor: 1.3),
                    ),
                    const SizedBox(width: SignalSpacing.lg),
                  ],
                  const ConnectionStatusPill(),
                  const Spacer(),
                  // Connection action: Disconnect when a board is connected —
                  // returns to the full-screen Connect flow (ADR-0011); otherwise
                  // an inert Connect slot (the live scan/connect flow is the
                  // full-screen Connect surface). `canSoftReboot` ⇔ board present.
                  if (run.canSoftReboot)
                    IconButton(
                      icon: const Icon(Icons.link_off),
                      tooltip: l10n.toolbarDisconnect,
                      onPressed: () =>
                          ref.read(connectionManagerProvider).disconnect(),
                    )
                  else
                    IconButton(
                      icon: const Icon(Icons.bluetooth),
                      tooltip: l10n.toolbarConnect,
                      onPressed: null, // slot only (FR-UI-3)
                    ),
                  if (showRun)
                    // Run the current editor buffer via run-control
                    // (FR-RUN-1/4).
                    IconButton(
                      icon: const Icon(Icons.play_arrow),
                      tooltip: runTooltip,
                      onPressed: run.canRun ? () => _run(context, ref) : null,
                    ),
                  // Stop the running program (FR-RUN-1).
                  IconButton(
                    icon: const Icon(Icons.stop),
                    tooltip: l10n.toolbarStop,
                    onPressed: run.canStop
                        ? () => _guard(
                            ScaffoldMessenger.of(context),
                            l10n,
                            () => ref.read(runControllerProvider).stop(),
                          )
                        : null,
                  ),
                  if (compactActions)
                    PopupMenuButton<_ToolbarMoreAction>(
                      key: const Key('toolbarMoreButton'),
                      icon: const Icon(Icons.more_vert),
                      tooltip: l10n.toolbarMore,
                      onSelected: (_ToolbarMoreAction action) {
                        switch (action) {
                          case _ToolbarMoreAction.softReboot:
                            _guard(
                              ScaffoldMessenger.of(context),
                              l10n,
                              () =>
                                  ref.read(runControllerProvider).softReboot(),
                            );
                            break;
                          case _ToolbarMoreAction.about:
                            _openAbout(context);
                            break;
                        }
                      },
                      itemBuilder: (BuildContext context) =>
                          <PopupMenuEntry<_ToolbarMoreAction>>[
                            PopupMenuItem<_ToolbarMoreAction>(
                              key: const Key('toolbarSoftRebootMenuItem'),
                              value: _ToolbarMoreAction.softReboot,
                              enabled: run.canSoftReboot,
                              child: _ToolbarMenuLabel(
                                icon: Icons.restart_alt,
                                label: l10n.toolbarSoftReboot,
                              ),
                            ),
                            PopupMenuItem<_ToolbarMoreAction>(
                              key: const Key('toolbarAboutMenuItem'),
                              value: _ToolbarMoreAction.about,
                              child: _ToolbarMenuLabel(
                                icon: Icons.info_outline,
                                label: l10n.toolbarAbout,
                              ),
                            ),
                          ],
                    )
                  else ...<Widget>[
                    // Soft-reboot stays direct on roomy toolbars (FR-RUN-1).
                    IconButton(
                      icon: const Icon(Icons.restart_alt),
                      tooltip: l10n.toolbarSoftReboot,
                      onPressed: run.canSoftReboot
                          ? () => _guard(
                              ScaffoldMessenger.of(context),
                              l10n,
                              () =>
                                  ref.read(runControllerProvider).softReboot(),
                            )
                          : null,
                    ),
                    IconButton(
                      key: const Key('toolbarAboutButton'),
                      icon: const Icon(Icons.info_outline),
                      tooltip: l10n.toolbarAbout,
                      onPressed: () => _openAbout(context),
                    ),
                  ],
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

class _ToolbarMenuLabel extends StatelessWidget {
  const _ToolbarMenuLabel({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: <Widget>[
        Icon(icon, size: 20),
        const SizedBox(width: SignalSpacing.md),
        Text(label),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Console keep-alive sentinel (FR-CONSOLE-7). A zero-size, always-mounted
// consumer that subscribes the console ring buffer from the shell root so live
// output is captured before the Console surface is first shown and survives
// tab/nav switches. Watches the notifier (stable identity), so console events
// never rebuild the shell chrome. Binds through the seam only (CON-8).
// ---------------------------------------------------------------------------

class _ConsoleKeepAlive extends ConsumerWidget {
  const _ConsoleKeepAlive();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.watch(consoleBufferProvider.notifier);
    return const SizedBox.shrink();
  }
}

// ---------------------------------------------------------------------------
// Titled pane wrapper for the landscape three-pane layout (§7.4): a title header
// (labelLarge / onSurfaceVariant) + hairline + Expanded body. §7.4's trailing
// affordance slot (the right-pane switcher §7.12 / breadcrumb / multi-select bar
// §7.13) is added by its feature owner when that content lands.
// ---------------------------------------------------------------------------

class _TitledPane extends StatelessWidget {
  const _TitledPane({required this.title, required this.child, this.trailing});
  final String title;
  final Widget child;

  /// Optional header-trailing control (e.g. the Files-pane collapse button).
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme scheme = theme.colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        // A 56 dp minimum lets the segmented right-pane actions retain 48 dp
        // targets and grows rather than clipping under larger text.
        ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 56),
          child: Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: SignalSpacing.md,
              vertical: SignalSpacing.xs,
            ),
            child: Row(
              children: <Widget>[
                Expanded(
                  child: Text(
                    title,
                    style: theme.textTheme.labelLarge?.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                ?trailing,
              ],
            ),
          ),
        ),
        const Divider(height: 1),
        Expanded(child: child),
      ],
    );
  }
}
