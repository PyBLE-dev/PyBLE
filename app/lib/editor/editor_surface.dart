// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// The package-independent editor presentation seam fixed by ADR-0012.
library;

import 'package:flutter/material.dart';

@immutable
class EditorSurfaceConfiguration {
  const EditorSurfaceConfiguration({
    required this.text,
    required this.onChanged,
    required this.textStyle,
    required this.backgroundColor,
    required this.cursorColor,
    required this.gutterColor,
    required this.hintText,
    required this.contentPadding,
  });

  /// Push-in document snapshot. The surface never owns canonical source.
  final String text;

  /// Stream-out edits. The document provider remains the source of truth.
  final ValueChanged<String> onChanged;
  final TextStyle textStyle;
  final Color backgroundColor;
  final Color cursorColor;
  final Color gutterColor;
  final String hintText;
  final EdgeInsets contentPadding;
}

/// Base type implemented by both executable ADR-0012 surfaces.
abstract class EditorSurface extends StatefulWidget {
  const EditorSurface({super.key});
}

typedef EditorSurfaceBuilder =
    EditorSurface Function(EditorSurfaceConfiguration configuration);
