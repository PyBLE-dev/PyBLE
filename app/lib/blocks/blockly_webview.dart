// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Sole `webview_flutter` implementation for A-31.
///
/// It loads only the bundled asset, admits only local navigation, and forwards
/// versioned snapshot messages to the pure Dart document controller. It knows
/// no Connection, BLE, board, profile, or PBLE/1 type.
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:webview_flutter/webview_flutter.dart';

import 'package:pyble/localization/localization.dart';

import 'blocks_document.dart';
import 'blocks_examples.dart';

const String _assetPath = 'assets/blockly/index.html';
const String _channelName = 'PybleBlocks';
const Duration _firstSnapshotTimeout = Duration(seconds: 15);

/// Whether [value] is the exact local main-frame location admitted by A-31.
///
/// Relative scripts/media are subresources and do not navigate the main frame.
/// The two file/HTTPS forms cover `loadFlutterAsset` on WKWebView and Android;
/// arbitrary sandbox files, network pages, custom schemes, queries, fragments,
/// and traversal are rejected.
@visibleForTesting
bool isAllowedBlocklyNavigation(String value) {
  final Uri? uri = Uri.tryParse(value);
  if (uri == null || uri.hasQuery || uri.hasFragment) return false;
  if (uri.userInfo.isNotEmpty || uri.hasPort) return false;
  if (uri.scheme == 'https' && uri.authority != uri.host) return false;
  if (uri.scheme == 'about') return value == 'about:blank';
  if (uri.pathSegments.contains('..')) return false;

  const String assetSuffix = '/flutter_assets/assets/blockly/index.html';
  if (uri.scheme == 'file') {
    return uri.host.isEmpty && uri.path.endsWith(assetSuffix);
  }

  return value ==
      'https://appassets.androidplatform.net/assets/assets/blockly/index.html';
}

/// Stale retained revisions are not startup success: the restore handshake must
/// still publish a newer snapshot before the watchdog can stop.
@visibleForTesting
bool shouldCancelBlocksStartupWatchdog(BlocksBridgeResult result) {
  return result == BlocksBridgeResult.snapshotAccepted ||
      result == BlocksBridgeResult.workspaceError ||
      result == BlocksBridgeResult.hostError;
}

/// ARB-derived copy injected before the authored Blockly host is initialized.
@visibleForTesting
Map<String, Object?> blocklyHostMessages(AppLocalizations l10n) =>
    <String, Object?>{
      'examplesCategory': l10n.blocksExamples,
      'exampleTitles': <String, String>{
        'hello-pyble': l10n.blocksExampleHelloTitle,
        'count-repeatedly': l10n.blocksExampleCountTitle,
        'blink-led': l10n.blocksExampleBlinkTitle,
        'blink-neopixel': l10n.blocksExampleNeoPixelTitle,
        'read-button': l10n.blocksExampleReadButtonTitle,
        'button-controls-led': l10n.blocksExampleButtonLedTitle,
        'reusable-function': l10n.blocksExampleFunctionTitle,
      },
      'timeCategory': l10n.blocksTimeCategory,
      'timeBlockMessage': l10n.blocksTimeWait('%1'),
      'timeBlockTooltip': l10n.blocksTimeTooltip,
      'timeRequiredError': l10n.blocksTimeRequired,
      'timeInvalidError': l10n.blocksTimeInvalid,
      'neopixelCategory': l10n.blocksNeoPixelCategory,
      'neopixelCreateMessage': l10n.blocksNeoPixelCreate('%1', '%2'),
      'neopixelRgbMessage': l10n.blocksNeoPixelRgb('%1', '%2', '%3'),
      'neopixelSetPixelMessage': l10n.blocksNeoPixelSetPixel('%1', '%2', '%3'),
      'neopixelFillMessage': l10n.blocksNeoPixelFill('%1', '%2'),
      'neopixelWriteMessage': l10n.blocksNeoPixelWrite('%1'),
      'neopixelCreateTooltip': l10n.blocksNeoPixelCreateTooltip,
      'neopixelRgbTooltip': l10n.blocksNeoPixelRgbTooltip,
      'neopixelSetPixelTooltip': l10n.blocksNeoPixelSetPixelTooltip,
      'neopixelFillTooltip': l10n.blocksNeoPixelFillTooltip,
      'neopixelWriteTooltip': l10n.blocksNeoPixelWriteTooltip,
      'neopixelPinRequiredError': l10n.blocksNeoPixelPinRequired,
      'neopixelPixelsRequiredError': l10n.blocksNeoPixelPixelsRequired,
      'neopixelPixelsInvalidError': l10n.blocksNeoPixelPixelsInvalid,
      'neopixelRedRequiredError': l10n.blocksNeoPixelRedRequired,
      'neopixelGreenRequiredError': l10n.blocksNeoPixelGreenRequired,
      'neopixelBlueRequiredError': l10n.blocksNeoPixelBlueRequired,
      'neopixelStripRequiredError': l10n.blocksNeoPixelStripRequired,
      'neopixelIndexRequiredError': l10n.blocksNeoPixelIndexRequired,
      'neopixelColorRequiredError': l10n.blocksNeoPixelColorRequired,
      'gpioCategory': l10n.blocksGpioCategory,
      'gpioPinMessage': l10n.blocksGpioPin('%1', '%2', '%3'),
      'gpioWriteMessage': l10n.blocksGpioWrite('%1', '%2'),
      'gpioReadMessage': l10n.blocksGpioRead('%1'),
      'gpioModeInput': l10n.blocksGpioModeInput,
      'gpioModeOutput': l10n.blocksGpioModeOutput,
      'gpioPullNone': l10n.blocksGpioPullNone,
      'gpioPullUp': l10n.blocksGpioPullUp,
      'gpioPullDown': l10n.blocksGpioPullDown,
      'gpioLevelLow': l10n.blocksGpioLevelLow,
      'gpioLevelHigh': l10n.blocksGpioLevelHigh,
      'gpioPinTooltip': l10n.blocksGpioPinTooltip,
      'gpioWriteTooltip': l10n.blocksGpioWriteTooltip,
      'gpioReadTooltip': l10n.blocksGpioReadTooltip,
      'gpioPinRequiredError': l10n.blocksGpioPinRequired,
      'gpioPinInvalidError': l10n.blocksGpioPinInvalid,
      'gpioModeInvalidError': l10n.blocksGpioModeInvalid,
      'gpioPullInvalidError': l10n.blocksGpioPullInvalid,
      'gpioWritePinRequiredError': l10n.blocksGpioWritePinRequired,
      'gpioLevelInvalidError': l10n.blocksGpioLevelInvalid,
      'gpioReadPinRequiredError': l10n.blocksGpioReadPinRequired,
      'gpioRestoreModeInvalidError': l10n.blocksGpioRestoreModeInvalid,
      'gpioRestorePullInvalidError': l10n.blocksGpioRestorePullInvalid,
      'gpioRestoreLevelInvalidError': l10n.blocksGpioRestoreLevelInvalid,
      'multilineValueError': l10n.blocksValueMultilineInvalid,
    };

/// Lazy offline Blockly platform host.
class BlocklyWebView extends ConsumerStatefulWidget {
  const BlocklyWebView({super.key});

  @override
  ConsumerState<BlocklyWebView> createState() => _BlocklyWebViewState();
}

class _BlocklyWebViewState extends ConsumerState<BlocklyWebView> {
  late final WebViewController _controller;
  late final BlocksDocumentController _documentController;
  late final int _hostId;
  Timer? _firstMessageTimer;

  @override
  void initState() {
    super.initState();
    _documentController = ref.read(blocksDocumentProvider.notifier);
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..addJavaScriptChannel(
        _channelName,
        onMessageReceived: (JavaScriptMessage message) {
          if (!mounted) return;
          final BlocksBridgeResult result = _documentController
              .receiveBridgeMessage(message.message, hostId: _hostId);
          if (shouldCancelBlocksStartupWatchdog(result)) {
            _firstMessageTimer?.cancel();
          }
        },
      )
      ..setNavigationDelegate(
        NavigationDelegate(
          onNavigationRequest: (NavigationRequest request) {
            return isAllowedBlocklyNavigation(request.url)
                ? NavigationDecision.navigate
                : NavigationDecision.prevent;
          },
          onPageFinished: (String url) {
            if (!mounted ||
                url == 'about:blank' ||
                !isAllowedBlocklyNavigation(url)) {
              return;
            }
            unawaited(_initialiseHost());
          },
          onWebResourceError: (WebResourceError error) {
            if (!mounted) return;
            if (error.isForMainFrame == false) return;
            _firstMessageTimer?.cancel();
            _documentController.reportHostError(
              error.description,
              hostId: _hostId,
            );
          },
        ),
      );
    _hostId = _documentController.beginHost(
      previewExample: _previewExample,
      requestSnapshot: _requestFreshSnapshot,
    );
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _documentController.markHostLoading(_hostId);
      _firstMessageTimer = Timer(_firstSnapshotTimeout, () {
        if (!mounted) return;
        _documentController.reportHostError(
          AppLocalizations.of(context).blocksStartupTimeout,
          hostId: _hostId,
        );
      });
      unawaited(
        _controller.loadFlutterAsset(_assetPath).catchError((Object error) {
          _firstMessageTimer?.cancel();
          if (!mounted) return;
          _documentController.reportHostError(
            error.toString(),
            hostId: _hostId,
          );
        }),
      );
    });
  }

  Future<void> _requestFreshSnapshot(int requestId) =>
      _controller.runJavaScript('window.pybleBlocks.snapshot($requestId);');

  Future<BlocksExamplePreview> _previewExample(String workspaceJson) async {
    final String workspaceLiteral = jsonEncode(workspaceJson);
    final Object result = await _controller.runJavaScriptReturningResult(
      'window.pybleBlocks.previewExample($workspaceLiteral);',
    );
    return decodeBlocksExamplePreviewResult(result);
  }

  Future<void> _initialiseHost() async {
    if (!mounted) return;
    final BlocksDocument document = ref.read(blocksDocumentProvider);
    final String? retainedWorkspaceJson = document.retainedWorkspaceJson;
    final int? retainedWorkspaceRevision = document.retainedWorkspaceRevision;
    try {
      if ((retainedWorkspaceJson == null) !=
          (retainedWorkspaceRevision == null)) {
        throw const FormatException(
          'Blockly retained workspace state is incomplete',
        );
      }
      final String messages = jsonEncode(
        blocklyHostMessages(AppLocalizations.of(context)),
      );
      // jsonEncode(workspaceJson) creates a safe JavaScript string literal;
      // the revision has already crossed the validated bridge boundary.
      final String retainedArguments =
          retainedWorkspaceJson == null || retainedWorkspaceRevision == null
          ? ''
          : ', ${jsonEncode(retainedWorkspaceJson)}, '
                '$retainedWorkspaceRevision';
      final Object configured = await _controller.runJavaScriptReturningResult(
        'window.pybleBlocks.configureHost('
        '$messages$retainedArguments);',
      );
      if (!_javascriptTrue(configured)) {
        throw const FormatException('Blockly rejected localized host messages');
      }
    } catch (error) {
      _firstMessageTimer?.cancel();
      if (!mounted) return;
      _documentController.reportHostError(error.toString(), hostId: _hostId);
    }
  }

  @override
  void dispose() {
    _firstMessageTimer?.cancel();
    _documentController.endHost(_hostId);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => WebViewWidget(controller: _controller);
}

/// Decodes the bounded platform variants of a scratch preview result.
///
/// WKWebView returns the JavaScript string value directly. Android WebView's
/// `evaluateJavascript` callback returns that same value as a JSON string
/// literal, so it needs one additional unwrap before the payload is decoded.
/// No further layers are accepted.
@visibleForTesting
BlocksExamplePreview decodeBlocksExamplePreviewResult(Object result) {
  if (result is! String) {
    throw const FormatException('Blockly example preview did not return JSON');
  }
  Object? decoded = jsonDecode(result);
  if (decoded is String) {
    decoded = jsonDecode(decoded);
  }
  if (decoded is! Map<String, dynamic> ||
      decoded['source'] is! String ||
      decoded['workspace'] is! Map<String, dynamic>) {
    throw const FormatException('Blockly example preview result is malformed');
  }
  return BlocksExamplePreview(
    source: decoded['source']! as String,
    workspaceJson: jsonEncode(decoded['workspace']),
  );
}

bool _javascriptTrue(Object value) => value == true || value == 'true';
