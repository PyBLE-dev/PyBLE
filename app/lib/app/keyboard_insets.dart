// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

const MethodChannel _channel = MethodChannel('dev.pyble/keyboard/insets');

/// Supplements notification-derived iOS metrics with the current window's
/// keyboard layout guide. UIKit points and Flutter logical pixels coincide.
class KeyboardInsets extends StatefulWidget {
  const KeyboardInsets({required this.child, super.key});

  final Widget child;

  @override
  State<KeyboardInsets> createState() => _KeyboardInsetsState();
}

class _KeyboardInsetsState extends State<KeyboardInsets>
    with WidgetsBindingObserver {
  static int _nextGeneration = 0;
  late final bool _enabled =
      !kIsWeb && defaultTargetPlatform == TargetPlatform.iOS;
  int? _generation;
  double _nativeBottom = 0;
  double _viewHeight = 0;
  bool _refreshScheduled = false;

  @override
  void initState() {
    super.initState();
    if (!_enabled) return;
    _channel.setMethodCallHandler(_handleInset);
    WidgetsBinding.instance.addObserver(this);
    _generation = ++_nextGeneration;
    _refreshAfterFrame();
  }

  Future<void> _handleInset(MethodCall call) async {
    final Object? arguments = call.arguments;
    if (!mounted ||
        _generation == null ||
        call.method != 'inset' ||
        arguments is! Map ||
        arguments['generation'] != _generation) {
      return;
    }
    final Object? raw = arguments['bottom'];
    if (raw is! num) return;
    final double bottom = raw.toDouble();
    if (!bottom.isFinite || bottom < 0 || bottom > _viewHeight) return;
    if (_nativeBottom != bottom) setState(() => _nativeBottom = bottom);
  }

  Future<void> _request(String method, int generation) async {
    try {
      await _channel.invokeMethod<void>(method, generation);
    } on MissingPluginException {
      // Host-only widget tests have no UIKit registrar. Flutter's ordinary
      // metrics remain usable; the shipping iOS runner registers this channel.
    }
  }

  void _refreshAfterFrame() {
    if (_refreshScheduled || _generation == null) return;
    _refreshScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _refreshScheduled = false;
      final int? generation = _generation;
      if (mounted && generation != null) {
        unawaited(_request('observe', generation));
      }
    });
  }

  @override
  void didChangeMetrics() => _refreshAfterFrame();

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      _stop();
      if (_nativeBottom != 0) setState(() => _nativeBottom = 0);
    } else if (state == AppLifecycleState.resumed) {
      _generation ??= ++_nextGeneration;
      _refreshAfterFrame();
    }
  }

  void _stop() {
    final int? generation = _generation;
    _generation = null;
    if (generation != null) unawaited(_request('stop', generation));
  }

  @override
  void dispose() {
    if (_enabled) {
      _stop();
      WidgetsBinding.instance.removeObserver(this);
      _channel.setMethodCallHandler(null);
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_enabled) return widget.child;
    final MediaQueryData original = MediaQuery.of(context);
    _viewHeight = original.size.height;
    final double bottom = math.max(
      original.viewInsets.bottom,
      _nativeBottom.clamp(0, _viewHeight),
    );
    return MediaQuery(
      data: original.copyWith(
        viewInsets: original.viewInsets.copyWith(bottom: bottom),
        padding: original.padding.copyWith(
          bottom: math.max(0, original.viewPadding.bottom - bottom),
        ),
      ),
      child: widget.child,
    );
  }
}
