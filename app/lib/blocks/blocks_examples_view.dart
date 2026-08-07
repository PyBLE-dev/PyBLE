// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Native, localized chooser for the bundled beginner Blockly examples.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/localization/localization.dart';
import 'package:pyble/theme/theme.dart';

import 'blocks_document.dart';
import 'blocks_examples.dart';

const Key kBlocksExamplesCatalogKey = ValueKey<String>('blocksExamplesCatalog');
const Key kBlocksExamplePreviewButtonKey = ValueKey<String>(
  'blocksExamplePreviewButton',
);
const Key kBlocksExampleCreateCopyButtonKey = ValueKey<String>(
  'blocksExampleCreateCopyButton',
);
const Key kBlocksExampleReplaceWorkspaceButtonKey = ValueKey<String>(
  'blocksExampleReplaceWorkspaceButton',
);

typedef BlocksExamplePreviewer =
    Future<BlocksExamplePreview> Function(String workspaceJson);

/// Fakeable seam around the production WebView scratch generator.
final Provider<BlocksExamplePreviewer> blocksExamplePreviewerProvider =
    Provider<BlocksExamplePreviewer>(
      (Ref ref) => ref.read(blocksDocumentProvider.notifier).previewExample,
    );

class _ExampleLoadRequest {
  const _ExampleLoadRequest({required this.preview, required this.replace});

  final BlocksExamplePreview preview;
  final bool replace;
}

/// Opens the shared chooser used by the native toolbar, empty CTA, and toolbox.
Future<void> showBlocksExampleCatalog(
  BuildContext context,
  WidgetRef ref, {
  String? initialExampleId,
}) async {
  final AppLocalizations l10n = AppLocalizations.of(context);
  final BlocksExampleCatalog catalog;
  try {
    catalog = await ref.read(blocksExampleCatalogProvider.future);
  } catch (error) {
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(l10n.blocksExamplesLoadFailed(error.toString()))),
    );
    return;
  }
  if (!context.mounted) return;

  final BlocksDocument before = ref.read(blocksDocumentProvider);
  final bool workspaceEmpty = isSemanticallyEmptyBlocksWorkspace(
    before.retainedWorkspaceJson,
  );
  final bool useBottomSheet = MediaQuery.sizeOf(context).width < 600;
  Widget chooser(BuildContext dialogContext) => _BlocksExamplesDialog(
    catalog: catalog,
    initialExampleId: initialExampleId,
    workspaceEmpty: workspaceEmpty,
    previewer: ref.read(blocksExamplePreviewerProvider),
    asBottomSheet: useBottomSheet,
  );
  final _ExampleLoadRequest? request = useBottomSheet
      ? await showModalBottomSheet<_ExampleLoadRequest>(
          context: context,
          isScrollControlled: true,
          useSafeArea: true,
          backgroundColor: Colors.transparent,
          builder: (BuildContext sheetContext) => AnimatedPadding(
            duration: const Duration(milliseconds: 180),
            curve: Curves.easeOut,
            padding: EdgeInsets.only(
              bottom: MediaQuery.viewInsetsOf(sheetContext).bottom,
            ),
            child: FractionallySizedBox(
              heightFactor: 0.96,
              child: chooser(sheetContext),
            ),
          ),
        )
      : await showDialog<_ExampleLoadRequest>(
          context: context,
          barrierDismissible: true,
          builder: chooser,
        );
  if (request == null || !context.mounted) return;

  if (request.replace) {
    final bool confirmed =
        await showDialog<bool>(
          context: context,
          builder: (BuildContext dialogContext) => AlertDialog(
            title: Text(l10n.blocksExamplesReplaceTitle),
            content: Text(l10n.blocksExamplesReplaceDetail),
            actions: <Widget>[
              TextButton(
                onPressed: () => Navigator.of(dialogContext).pop(false),
                child: Text(l10n.commonCancel),
              ),
              FilledButton(
                onPressed: () => Navigator.of(dialogContext).pop(true),
                child: Text(l10n.blocksExamplesReplace),
              ),
            ],
          ),
        ) ??
        false;
    if (!confirmed || !context.mounted) return;
  }

  try {
    await ref
        .read(blocksDocumentProvider.notifier)
        .loadExampleWorkspace(request.preview, replace: request.replace);
    if (!context.mounted) return;
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(l10n.blocksExamplesLoaded)));
  } catch (error) {
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(l10n.blocksExamplesLoadFailed(error.toString()))),
    );
  }
}

class _BlocksExamplesDialog extends StatefulWidget {
  const _BlocksExamplesDialog({
    required this.catalog,
    required this.initialExampleId,
    required this.workspaceEmpty,
    required this.previewer,
    required this.asBottomSheet,
  });

  final BlocksExampleCatalog catalog;
  final String? initialExampleId;
  final bool workspaceEmpty;
  final BlocksExamplePreviewer previewer;
  final bool asBottomSheet;

  @override
  State<_BlocksExamplesDialog> createState() => _BlocksExamplesDialogState();
}

class _BlocksExamplesDialogState extends State<_BlocksExamplesDialog> {
  late BlocksExampleTemplate _selected;
  final Map<String, TextEditingController> _gpioControllers =
      <String, TextEditingController>{};
  final Map<String, GlobalKey> _gpioFieldKeys = <String, GlobalKey>{};
  BlocksExamplePreview? _preview;
  Object? _previewError;
  bool _generating = false;
  int _generationEpoch = 0;

  @override
  void initState() {
    super.initState();
    final String? initialId = widget.initialExampleId;
    _selected = initialId != null && kBlocksExampleIds.contains(initialId)
        ? widget.catalog.byId(initialId)
        : widget.catalog.examples.first;
    _resetGpioControllers();
  }

  @override
  void dispose() {
    for (final TextEditingController controller in _gpioControllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  void _resetGpioControllers() {
    for (final TextEditingController controller in _gpioControllers.values) {
      controller.dispose();
    }
    _gpioControllers
      ..clear()
      ..addEntries(
        _selected.gpioRoles.map(
          (BlocksExampleGpioRole role) =>
              MapEntry<String, TextEditingController>(
                role.role,
                TextEditingController(),
              ),
        ),
      );
    _gpioFieldKeys
      ..clear()
      ..addEntries(
        _selected.gpioRoles.map(
          (BlocksExampleGpioRole role) => MapEntry<String, GlobalKey>(
            role.role,
            GlobalKey(debugLabel: 'blocks-example-${role.role}-gpio'),
          ),
        ),
      );
  }

  Map<String, int>? get _gpioValues {
    final Map<String, int> values = <String, int>{};
    for (final BlocksExampleGpioRole role in _selected.gpioRoles) {
      final int? gpio = parseBlocksExampleGpio(
        _gpioControllers[role.role]!.text,
      );
      if (gpio == null) return null;
      values[role.role] = gpio;
    }
    if (values.length > 1 && values.values.toSet().length != values.length) {
      return null;
    }
    return values;
  }

  bool get _gpioValuesConflict {
    if (_selected.gpioRoles.length < 2) return false;
    final List<int?> values = _selected.gpioRoles
        .map(
          (BlocksExampleGpioRole role) =>
              parseBlocksExampleGpio(_gpioControllers[role.role]!.text),
        )
        .toList(growable: false);
    return values.every((int? value) => value != null) &&
        values.whereType<int>().toSet().length != values.length;
  }

  String? _gpioError(AppLocalizations l10n, BlocksExampleGpioRole role) {
    final String text = _gpioControllers[role.role]!.text;
    if (text.isNotEmpty && parseBlocksExampleGpio(text) == null) {
      return l10n.blocksExamplesPinInvalid;
    }
    if (_gpioValuesConflict) return l10n.blocksExamplesPinsMustDiffer;
    return null;
  }

  bool get _candidateIsValid => !_selected.requiresGpio || _gpioValues != null;

  void _select(BlocksExampleTemplate example) {
    if (identical(example, _selected)) return;
    setState(() {
      _generationEpoch += 1;
      _selected = example;
      _preview = null;
      _previewError = null;
      _generating = false;
      _resetGpioControllers();
    });
  }

  void _onGpioChanged() {
    setState(() {
      _generationEpoch += 1;
      _preview = null;
      _previewError = null;
      _generating = false;
    });
  }

  Future<BlocksExamplePreview?> _generatePreview() async {
    final Map<String, int>? gpioValues = _gpioValues;
    if (_selected.requiresGpio && gpioValues == null) return null;
    final int epoch = ++_generationEpoch;
    final String workspaceJson;
    try {
      workspaceJson = _selected.materializeWorkspaceJson(
        gpioValues ?? const <String, int>{},
      );
    } catch (error) {
      if (!mounted || epoch != _generationEpoch) return null;
      setState(() => _previewError = error);
      return null;
    }

    setState(() {
      _generating = true;
      _previewError = null;
    });
    try {
      final BlocksExamplePreview preview = await widget.previewer(
        workspaceJson,
      );
      if (!mounted || epoch != _generationEpoch) return null;
      setState(() {
        _preview = preview;
        _generating = false;
      });
      return preview;
    } catch (error) {
      if (!mounted || epoch != _generationEpoch) return null;
      setState(() {
        _preview = null;
        _previewError = error;
        _generating = false;
      });
      return null;
    }
  }

  Future<BlocksExamplePreview?> _ensurePreview() async =>
      _preview ?? _generatePreview();

  Future<void> _showLargePreview() async {
    final BlocksExamplePreview? preview = await _ensurePreview();
    if (preview == null || !mounted) return;
    final AppLocalizations l10n = AppLocalizations.of(context);
    final ColorScheme scheme = Theme.of(context).colorScheme;
    await showDialog<void>(
      context: context,
      builder: (BuildContext dialogContext) => AlertDialog(
        title: Text(l10n.blocksCodePreviewTitle),
        content: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 680, maxHeight: 520),
          child: _ExampleSource(
            source: preview.source,
            background: scheme.surfaceContainerLowest,
          ),
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: Text(
              MaterialLocalizations.of(dialogContext).closeButtonLabel,
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _requestLoad() async {
    final BlocksExamplePreview? preview = await _ensurePreview();
    if (preview == null || !mounted) return;
    Navigator.of(context).pop(
      _ExampleLoadRequest(preview: preview, replace: !widget.workspaceEmpty),
    );
  }

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = AppLocalizations.of(context);
    final ColorScheme scheme = Theme.of(context).colorScheme;
    final MediaQueryData media = MediaQuery.of(context);
    final bool compactHeader =
        widget.asBottomSheet ||
        media.size.height < 520 ||
        media.textScaler.scale(1) > 1.3;
    final Widget content = Semantics(
      key: kBlocksExamplesCatalogKey,
      container: true,
      explicitChildNodes: true,
      label: l10n.blocksExamplesCatalogSemantics,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 980, maxHeight: 720),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Padding(
              padding: const EdgeInsets.fromLTRB(
                SignalSpacing.lg,
                SignalSpacing.lg,
                SignalSpacing.sm,
                SignalSpacing.md,
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Text(
                          l10n.blocksExamples,
                          style: Theme.of(context).textTheme.headlineSmall,
                        ),
                        if (!compactHeader) ...<Widget>[
                          const SizedBox(height: SignalSpacing.xs),
                          Text(
                            l10n.blocksExamplesIntro,
                            style: Theme.of(context).textTheme.bodyMedium
                                ?.copyWith(color: scheme.onSurfaceVariant),
                          ),
                        ],
                      ],
                    ),
                  ),
                  IconButton(
                    tooltip: MaterialLocalizations.of(
                      context,
                    ).closeButtonTooltip,
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: LayoutBuilder(
                builder: (BuildContext context, BoxConstraints constraints) {
                  final Widget catalog = _buildCatalog(context);
                  final bool shortLayout = constraints.maxHeight < 520;
                  final Widget detail = _buildDetail(
                    context,
                    scrollActions: constraints.maxHeight < 380,
                    includeIntro: compactHeader,
                  );
                  if (constraints.maxWidth >= 720 ||
                      (shortLayout && constraints.maxWidth >= 480)) {
                    final double catalogWidth = (constraints.maxWidth * 0.34)
                        .clamp(180, 280)
                        .toDouble();
                    return Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: <Widget>[
                        SizedBox(width: catalogWidth, child: catalog),
                        const VerticalDivider(width: 1),
                        Expanded(child: detail),
                      ],
                    );
                  }
                  final double catalogHeight = (constraints.maxHeight * 0.28)
                      .clamp(96, 200)
                      .toDouble();
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: <Widget>[
                      SizedBox(height: catalogHeight, child: catalog),
                      const Divider(height: 1),
                      Expanded(child: detail),
                    ],
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
    if (widget.asBottomSheet) {
      return Material(
        color: scheme.surface,
        clipBehavior: Clip.antiAlias,
        borderRadius: const BorderRadius.vertical(
          top: Radius.circular(SignalRadius.lg),
        ),
        child: content,
      );
    }
    return Dialog(child: content);
  }

  Widget _buildCatalog(BuildContext context) {
    final AppLocalizations l10n = AppLocalizations.of(context);
    final ColorScheme scheme = Theme.of(context).colorScheme;
    return Material(
      color: scheme.surfaceContainerLow,
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(SignalSpacing.sm),
        child: Column(
          children: widget.catalog.examples
              .map((BlocksExampleTemplate example) {
                final bool selected = identical(example, _selected);
                return Padding(
                  padding: const EdgeInsets.only(bottom: SignalSpacing.xs),
                  child: Material(
                    color: selected
                        ? scheme.secondaryContainer
                        : Colors.transparent,
                    borderRadius: BorderRadius.circular(SignalRadius.sm),
                    child: ListTile(
                      key: ValueKey<String>('blocksExampleCard-${example.id}'),
                      selected: selected,
                      minTileHeight: 56,
                      leading: Icon(_iconFor(example.id), size: 22),
                      title: Text(_catalogMessage(l10n, example.titleKey)),
                      trailing: selected
                          ? Icon(
                              Icons.chevron_right,
                              color: scheme.onSecondaryContainer,
                            )
                          : null,
                      onTap: () => _select(example),
                    ),
                  ),
                );
              })
              .toList(growable: false),
        ),
      ),
    );
  }

  Widget _buildDetail(
    BuildContext context, {
    required bool scrollActions,
    required bool includeIntro,
  }) {
    final AppLocalizations l10n = AppLocalizations.of(context);
    final ColorScheme scheme = Theme.of(context).colorScheme;
    final TextTheme textTheme = Theme.of(context).textTheme;
    final bool canAct = _candidateIsValid;
    final Widget body = Padding(
      padding: const EdgeInsets.all(SignalSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          if (includeIntro) ...<Widget>[
            Text(
              l10n.blocksExamplesIntro,
              style: textTheme.bodyMedium?.copyWith(
                color: scheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(height: SignalSpacing.lg),
          ],
          Text(
            _catalogMessage(l10n, _selected.summaryKey),
            style: textTheme.titleMedium,
          ),
          const SizedBox(height: SignalSpacing.lg),
          Text(l10n.blocksExamplesConcepts, style: textTheme.labelLarge),
          const SizedBox(height: SignalSpacing.sm),
          Wrap(
            spacing: SignalSpacing.sm,
            runSpacing: SignalSpacing.sm,
            children: _selected.conceptKeys
                .map(
                  (String key) => Chip(
                    label: Text(_catalogMessage(l10n, key)),
                    visualDensity: VisualDensity.compact,
                  ),
                )
                .toList(growable: false),
          ),
          if (_selected.requiresGpio) ...<Widget>[
            const SizedBox(height: SignalSpacing.lg),
            _GuidanceCard(
              icon: Icons.pin_outlined,
              message: l10n.blocksExamplesChoosePins,
              color: scheme.tertiaryContainer,
              foreground: scheme.onTertiaryContainer,
            ),
            const SizedBox(height: SignalSpacing.md),
            ..._selected.gpioRoles.map(
              (BlocksExampleGpioRole role) => Padding(
                padding: const EdgeInsets.only(bottom: SignalSpacing.md),
                child: TextField(
                  key: _gpioFieldKeys[role.role],
                  controller: _gpioControllers[role.role],
                  keyboardType: TextInputType.number,
                  textInputAction: TextInputAction.next,
                  decoration: InputDecoration(
                    labelText: _catalogMessage(l10n, role.labelKey),
                    helperText: l10n.blocksExamplesPinHint,
                    errorText: _gpioError(l10n, role),
                    border: const OutlineInputBorder(),
                  ),
                  onChanged: (_) => _onGpioChanged(),
                ),
              ),
            ),
          ],
          const SizedBox(height: SignalSpacing.lg),
          Text(l10n.blocksExamplesWiring, style: textTheme.labelLarge),
          const SizedBox(height: SignalSpacing.sm),
          _GuidanceCard(
            icon: Icons.electrical_services_outlined,
            message: _catalogMessage(l10n, _selected.wiringNotesKey),
            color: scheme.surfaceContainerHigh,
            foreground: scheme.onSurfaceVariant,
          ),
          const SizedBox(height: SignalSpacing.lg),
          Text(l10n.blocksCodePreviewTitle, style: textTheme.labelLarge),
          const SizedBox(height: SignalSpacing.sm),
          SizedBox(height: 190, child: _buildSourcePreview(context)),
        ],
      ),
    );
    final Widget footer = Padding(
      padding: const EdgeInsets.all(SignalSpacing.md),
      child: Wrap(
        alignment: WrapAlignment.end,
        spacing: SignalSpacing.sm,
        runSpacing: SignalSpacing.sm,
        children: <Widget>[
          OutlinedButton.icon(
            key: kBlocksExamplePreviewButtonKey,
            onPressed: canAct ? _showLargePreview : null,
            icon: const Icon(Icons.code),
            label: Text(l10n.blocksExamplesPreview),
          ),
          FilledButton.icon(
            key: widget.workspaceEmpty
                ? kBlocksExampleCreateCopyButtonKey
                : kBlocksExampleReplaceWorkspaceButtonKey,
            onPressed: canAct ? _requestLoad : null,
            icon: Icon(
              widget.workspaceEmpty ? Icons.copy_outlined : Icons.find_replace,
            ),
            label: Text(
              widget.workspaceEmpty
                  ? l10n.blocksExamplesCreateCopy
                  : l10n.blocksExamplesReplace,
            ),
          ),
        ],
      ),
    );
    if (scrollActions) {
      return SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[body, const Divider(height: 1), footer],
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Expanded(child: SingleChildScrollView(child: body)),
        const Divider(height: 1),
        footer,
      ],
    );
  }

  Widget _buildSourcePreview(BuildContext context) {
    final AppLocalizations l10n = AppLocalizations.of(context);
    final ColorScheme scheme = Theme.of(context).colorScheme;
    if (!_candidateIsValid) {
      return _PreviewPlaceholder(
        icon: Icons.pin_outlined,
        message: l10n.blocksExamplesPreviewWaiting,
      );
    }
    if (_generating) {
      return _PreviewPlaceholder(
        icon: Icons.hourglass_top,
        message: l10n.blocksExamplesPreviewLoading,
        progress: true,
      );
    }
    if (_previewError != null) {
      return _PreviewPlaceholder(
        icon: Icons.error_outline,
        message: l10n.blocksExamplesLoadFailed(_previewError.toString()),
      );
    }
    final BlocksExamplePreview? preview = _preview;
    if (preview == null) {
      return _PreviewPlaceholder(
        icon: Icons.code,
        message: l10n.blocksExamplesPreviewIdle,
      );
    }
    return Semantics(
      container: true,
      liveRegion: true,
      label: l10n.blocksCodePreviewTitle,
      child: _ExampleSource(
        source: preview.source,
        background: scheme.surfaceContainerLowest,
      ),
    );
  }
}

class _GuidanceCard extends StatelessWidget {
  const _GuidanceCard({
    required this.icon,
    required this.message,
    required this.color,
    required this.foreground,
  });

  final IconData icon;
  final String message;
  final Color color;
  final Color foreground;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: color,
      borderRadius: BorderRadius.circular(SignalRadius.sm),
    ),
    child: Padding(
      padding: const EdgeInsets.all(SignalSpacing.md),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(icon, color: foreground, size: 20),
          const SizedBox(width: SignalSpacing.sm),
          Expanded(
            child: Text(
              message,
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: foreground),
            ),
          ),
        ],
      ),
    ),
  );
}

class _PreviewPlaceholder extends StatelessWidget {
  const _PreviewPlaceholder({
    required this.icon,
    required this.message,
    this.progress = false,
  });

  final IconData icon;
  final String message;
  final bool progress;

  @override
  Widget build(BuildContext context) {
    final ColorScheme scheme = Theme.of(context).colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: scheme.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(SignalRadius.sm),
        border: Border.all(color: scheme.outlineVariant),
      ),
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(SignalSpacing.lg),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              if (progress)
                const SizedBox.square(
                  dimension: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              else
                Icon(icon, color: scheme.onSurfaceVariant, size: 20),
              const SizedBox(width: SignalSpacing.sm),
              Flexible(
                child: Text(
                  message,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: scheme.onSurfaceVariant,
                  ),
                  textAlign: TextAlign.center,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ExampleSource extends StatelessWidget {
  const _ExampleSource({required this.source, required this.background});

  final String source;
  final Color background;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: background,
      borderRadius: BorderRadius.circular(SignalRadius.sm),
      border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
    ),
    child: SingleChildScrollView(
      padding: const EdgeInsets.all(SignalSpacing.md),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: SelectableText(
          source,
          style: SignalType.codeOn(Theme.of(context).colorScheme),
        ),
      ),
    ),
  );
}

IconData _iconFor(String id) => switch (id) {
  'hello-pyble' => Icons.waving_hand_outlined,
  'count-repeatedly' => Icons.repeat,
  'blink-led' => Icons.lightbulb_outline,
  'blink-neopixel' => Icons.flare_outlined,
  'read-button' => Icons.radio_button_checked,
  'button-controls-led' => Icons.alt_route,
  'reusable-function' => Icons.functions,
  _ => Icons.account_tree_outlined,
};

String _catalogMessage(AppLocalizations l10n, String key) => switch (key) {
  'blocksExampleHelloTitle' => l10n.blocksExampleHelloTitle,
  'blocksExampleHelloSummary' => l10n.blocksExampleHelloSummary,
  'blocksExampleCountTitle' => l10n.blocksExampleCountTitle,
  'blocksExampleCountSummary' => l10n.blocksExampleCountSummary,
  'blocksExampleBlinkTitle' => l10n.blocksExampleBlinkTitle,
  'blocksExampleBlinkSummary' => l10n.blocksExampleBlinkSummary,
  'blocksExampleNeoPixelTitle' => l10n.blocksExampleNeoPixelTitle,
  'blocksExampleNeoPixelSummary' => l10n.blocksExampleNeoPixelSummary,
  'blocksExampleReadButtonTitle' => l10n.blocksExampleReadButtonTitle,
  'blocksExampleReadButtonSummary' => l10n.blocksExampleReadButtonSummary,
  'blocksExampleButtonLedTitle' => l10n.blocksExampleButtonLedTitle,
  'blocksExampleButtonLedSummary' => l10n.blocksExampleButtonLedSummary,
  'blocksExampleFunctionTitle' => l10n.blocksExampleFunctionTitle,
  'blocksExampleFunctionSummary' => l10n.blocksExampleFunctionSummary,
  'blocksExampleNoWiring' => l10n.blocksExampleNoWiring,
  'blocksExampleBlinkWiring' => l10n.blocksExampleBlinkWiring,
  'blocksExampleNeoPixelWiring' => l10n.blocksExampleNeoPixelWiring,
  'blocksExampleButtonWiring' => l10n.blocksExampleButtonWiring,
  'blocksExampleButtonLedWiring' => l10n.blocksExampleButtonLedWiring,
  'blocksExampleLedGpio' => l10n.blocksExampleLedGpio,
  'blocksExampleButtonGpio' => l10n.blocksExampleButtonGpio,
  'blocksExampleNeoPixelGpio' => l10n.blocksExampleNeoPixelGpio,
  'blocksExampleConceptText' => l10n.blocksExampleConceptText,
  'blocksExampleConceptConsole' => l10n.blocksExampleConceptConsole,
  'blocksExampleConceptVariables' => l10n.blocksExampleConceptVariables,
  'blocksExampleConceptLoops' => l10n.blocksExampleConceptLoops,
  'blocksExampleConceptTiming' => l10n.blocksExampleConceptTiming,
  'blocksExampleConceptGpioOutput' => l10n.blocksExampleConceptGpioOutput,
  'blocksExampleConceptGpioInput' => l10n.blocksExampleConceptGpioInput,
  'blocksExampleConceptAddressableRgb' =>
    l10n.blocksExampleConceptAddressableRgb,
  'blocksExampleConceptConditions' => l10n.blocksExampleConceptConditions,
  'blocksExampleConceptFunctions' => l10n.blocksExampleConceptFunctions,
  'blocksExampleConceptParameters' => l10n.blocksExampleConceptParameters,
  _ => throw BlocksExampleFormatException('unknown localized catalog key $key'),
};
