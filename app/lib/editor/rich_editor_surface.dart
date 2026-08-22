// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// The independently integrated `flutter_code_editor` adapter from ADR-0012.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart'
    show HardwareKeyboard, KeyDownEvent, KeyRepeatEvent, LogicalKeyboardKey;
import 'package:flutter_code_editor/flutter_code_editor.dart';
import 'package:highlight/languages/python.dart' show python;

import 'editor_surface.dart';
import 'smart_punctuation.dart';

const Key kEditorRichSurfaceKey = ValueKey<String>('editorRichSurface');

class RichEditorSurface extends EditorSurface {
  const RichEditorSurface({required this.configuration, super.key});

  final EditorSurfaceConfiguration configuration;

  @override
  State<RichEditorSurface> createState() => _RichEditorSurfaceState();
}

class _RichEditorSurfaceState extends State<RichEditorSurface> {
  late final _PybleCodeController _controller;
  late final FocusNode _focusNode;
  late String _lastEmittedText;
  bool _applyingExternalText = false;

  @override
  void initState() {
    super.initState();
    _controller = _PybleCodeController(text: widget.configuration.text);
    _lastEmittedText = _controller.fullText;
    _controller.addListener(_handleControllerChanged);
    _focusNode = FocusNode();
    HardwareKeyboard.instance.addHandler(_handleHardwareKey);
  }

  @override
  void didUpdateWidget(RichEditorSurface oldWidget) {
    super.didUpdateWidget(oldWidget);
    final String next = widget.configuration.text;
    if (next != _controller.fullText) {
      _applyingExternalText = true;
      try {
        _controller.replaceExternalText(next);
        _lastEmittedText = next;
      } finally {
        _applyingExternalText = false;
      }
    }
  }

  @override
  void dispose() {
    HardwareKeyboard.instance.removeHandler(_handleHardwareKey);
    _focusNode.dispose();
    _controller.removeListener(_handleControllerChanged);
    _controller.dispose();
    super.dispose();
  }

  bool _handleHardwareKey(KeyEvent event) {
    if (!_focusNode.hasFocus ||
        (event is! KeyDownEvent && event is! KeyRepeatEvent) ||
        event.logicalKey != LogicalKeyboardKey.tab) {
      return false;
    }
    final bool reverse = HardwareKeyboard.instance.logicalKeysPressed.contains(
      LogicalKeyboardKey.shift,
    );
    _controller.handleTab(reverse: reverse);
    return true;
  }

  /// CodeField's `onChanged` omits controller-driven edits such as Undo.
  /// Listening at the controller keeps every user-visible edit flowing through
  /// the app-owned surface seam while external document snapshots do not echo.
  void _handleControllerChanged() {
    if (_applyingExternalText) return;
    final String next = _controller.fullText;
    if (next == _lastEmittedText) return;
    _lastEmittedText = next;
    widget.configuration.onChanged(next);
  }

  @override
  Widget build(BuildContext context) {
    final EditorSurfaceConfiguration config = widget.configuration;
    final ColorScheme scheme = Theme.of(context).colorScheme;
    final double gutterStyleWidth = _gutterStyleWidth(context, config);
    final double gutterPaintedWidth = gutterStyleWidth - 32;
    return Stack(
      children: <Widget>[
        Positioned.fill(
          child: Semantics(
            key: kEditorRichSurfaceKey,
            label: config.hintText,
            child: CodeTheme(
              data: CodeThemeData(styles: _pythonStyles(config, scheme)),
              child: CodeField(
                controller: _controller,
                focusNode: _focusNode,
                expands: true,
                maxLines: null,
                minLines: null,
                wrap: false,
                background: config.backgroundColor,
                cursorColor: config.cursorColor,
                padding: config.contentPadding,
                textStyle: config.textStyle,
                smartQuotesType: SmartQuotesType.disabled,
                smartDashesType: SmartDashesType.disabled,
                gutterStyle: GutterStyle(
                  width: gutterStyleWidth,
                  textStyle: config.textStyle.copyWith(
                    color: config.gutterColor,
                  ),
                  background: config.backgroundColor,
                  showLineNumbers: true,
                  showErrors: false,
                  showFoldingHandles: false,
                ),
              ),
            ),
          ),
        ),
        if (config.text.isEmpty)
          PositionedDirectional(
            start: 8 + gutterPaintedWidth,
            top: 16,
            child: ExcludeSemantics(
              child: IgnorePointer(
                child: Text(
                  config.hintText,
                  style: config.textStyle.copyWith(color: config.gutterColor),
                ),
              ),
            ),
          ),
      ],
    );
  }
}

/// `GutterStyle.width` includes two dormant 16 dp package columns even when
/// errors and folding handles are disabled. Size the remaining line-number
/// column for the current digit count and the fully scaled code font.
double _gutterStyleWidth(
  BuildContext context,
  EditorSurfaceConfiguration config,
) {
  final int lineCount = '\n'.allMatches(config.text).length + 1;
  final int digits = lineCount.toString().length.clamp(2, 8).toInt();
  final double scaledFontSize = MediaQuery.textScalerOf(
    context,
  ).scale(config.textStyle.fontSize ?? 14);
  const double dormantColumns = 32;
  const double gutterMargin = 10;
  const double breathingRoom = 8;
  return dormantColumns +
      gutterMargin +
      breathingRoom +
      (digits * scaledFontSize * 0.65);
}

Map<String, TextStyle> _pythonStyles(
  EditorSurfaceConfiguration config,
  ColorScheme scheme,
) => <String, TextStyle>{
  'root': config.textStyle.copyWith(
    color: scheme.onSurface,
    backgroundColor: config.backgroundColor,
  ),
  'comment': config.textStyle.copyWith(
    color: scheme.onSurfaceVariant,
    fontStyle: FontStyle.italic,
  ),
  'keyword': config.textStyle.copyWith(
    color: scheme.primary,
    fontWeight: FontWeight.w600,
  ),
  'built_in': config.textStyle.copyWith(color: scheme.tertiary),
  'type': config.textStyle.copyWith(color: scheme.tertiary),
  'literal': config.textStyle.copyWith(color: scheme.primary),
  'number': config.textStyle.copyWith(color: scheme.tertiary),
  'string': config.textStyle.copyWith(color: scheme.secondary),
  'title': config.textStyle.copyWith(color: scheme.primary),
  'meta': config.textStyle.copyWith(color: scheme.onSurfaceVariant),
};

/// Owns the correctness adaptations required by ADR-0012.
class _PybleCodeController extends CodeController {
  _PybleCodeController({required String text})
    : super(
        text: text,
        language: python,
        // Upstream's TabModifier normalizes every literal tab in the complete
        // buffer to spaces. Literal tabs are valid source bytes and may arrive
        // from a board or paste, so PyBLE retains the other editing modifiers
        // while owning hardware-Tab insertion at the adapter boundary.
        modifiers: CodeController.defaultCodeModifiers
            .where((CodeModifier modifier) => modifier is! TabModifier)
            .toList(growable: false),
      ) {
    // The dormant upstream creates this lazily on first Undo, which would make
    // edits performed before that moment unavailable. Seed it with the initial
    // document so font-only rebuilds retain a complete history.
    historyController.deleteHistory();
  }

  static const SmartPunctuationFormatter _formatter =
      SmartPunctuationFormatter();

  @override
  set value(TextEditingValue next) {
    final TextEditingValue filtered = _formatter.formatEditUpdate(value, next);
    super.value = filtered;
  }

  /// External board/New snapshots are displayed verbatim; only user edits are
  /// intercepted. This preserves the explicit punctuation warning/fix flow.
  void replaceExternalText(String text) {
    fullText = text;
    super.value = TextEditingValue(
      text: text,
      selection: TextSelection.collapsed(offset: text.length),
    );
    historyController.deleteHistory();
  }

  /// Neutralizes the package's duplicate, data-losing Tab shortcut. The global
  /// adapter handler calls [handleTab] once before focus shortcuts run.
  @override
  void onTabKeyAction() {}

  void handleTab({required bool reverse}) {
    if (reverse) {
      outdentSelection();
    } else {
      indentSelection();
    }
  }

  /// The package autocomplete surface is explicitly out of this increment.
  @override
  Future<void> generateSuggestions() async {
    popupController.hide();
  }

  /// The package find surface contains non-localizable UI; PyBLE owns it later.
  @override
  void showSearch() {}
}
