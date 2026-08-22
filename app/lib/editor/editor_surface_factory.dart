// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// ADR-0012 editor-surface composition and its test/fallback injection seam.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'editor_surface.dart';
import 'plain_editor_surface.dart';
import 'rich_editor_surface.dart';

EditorSurface richEditorSurfaceBuilder(
  EditorSurfaceConfiguration configuration,
) => RichEditorSurface(configuration: configuration);

EditorSurface plainEditorSurfaceBuilder(
  EditorSurfaceConfiguration configuration,
) => PlainEditorSurface(configuration: configuration);

final Provider<EditorSurfaceBuilder> editorSurfaceBuilderProvider =
    Provider<EditorSurfaceBuilder>((_) => richEditorSurfaceBuilder);
