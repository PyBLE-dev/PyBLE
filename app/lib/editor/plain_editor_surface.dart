// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// ADR-0012's executable plain-TextField fallback.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show TextInputFormatter;

import 'editor_surface.dart';
import 'smart_punctuation.dart';

const Key kEditorPlainSurfaceKey = ValueKey<String>('editorPlainSurface');

class PlainEditorSurface extends EditorSurface {
  const PlainEditorSurface({required this.configuration, super.key});

  final EditorSurfaceConfiguration configuration;

  @override
  State<PlainEditorSurface> createState() => _PlainEditorSurfaceState();
}

class _PlainEditorSurfaceState extends State<PlainEditorSurface> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.configuration.text);
  }

  @override
  void didUpdateWidget(PlainEditorSurface oldWidget) {
    super.didUpdateWidget(oldWidget);
    final String next = widget.configuration.text;
    if (next != _controller.text) {
      _controller.value = TextEditingValue(
        text: next,
        selection: TextSelection.collapsed(offset: next.length),
      );
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final EditorSurfaceConfiguration config = widget.configuration;
    return ColoredBox(
      color: config.backgroundColor,
      child: Padding(
        padding: config.contentPadding,
        child: TextField(
          key: kEditorPlainSurfaceKey,
          controller: _controller,
          onChanged: config.onChanged,
          expands: true,
          maxLines: null,
          minLines: null,
          keyboardType: TextInputType.multiline,
          smartQuotesType: SmartQuotesType.disabled,
          smartDashesType: SmartDashesType.disabled,
          autocorrect: false,
          enableSuggestions: false,
          textCapitalization: TextCapitalization.none,
          inputFormatters: const <TextInputFormatter>[
            SmartPunctuationFormatter(),
          ],
          textAlignVertical: TextAlignVertical.top,
          cursorColor: config.cursorColor,
          style: config.textStyle,
          decoration: InputDecoration(
            isCollapsed: true,
            border: InputBorder.none,
            hintText: config.hintText,
            hintStyle: config.textStyle.copyWith(color: config.gutterColor),
          ),
        ),
      ),
    );
  }
}
