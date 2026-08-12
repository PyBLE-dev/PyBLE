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

/// Routing decision for one JavaScript-channel message during host startup.
enum BlocklyHostChannelDisposition { initialise, forward, ignore, reject }

/// Admits the authored host's versioned readiness event once per page.
///
/// All other channel traffic remains available to the document controller.
/// Requiring the exact two-field envelope prevents a malformed message from
/// closing the startup gate before the JavaScript API exists.
class BlocklyHostStartupGate {
  int _pageGeneration = 0;
  int _hostEpoch = 0;
  int _attemptingGeneration = 0;
  int _configuredGeneration = 0;
  int _queuedReadinessGeneration = 0;

  int get generation => _pageGeneration;

  void beginPage({required int hostEpoch}) {
    if (hostEpoch < 1) {
      throw ArgumentError.value(hostEpoch, 'hostEpoch', 'must be positive');
    }
    _pageGeneration += 1;
    _hostEpoch = hostEpoch;
    _attemptingGeneration = 0;
    _configuredGeneration = 0;
    _queuedReadinessGeneration = 0;
  }

  bool isCurrentGeneration(int generation) =>
      generation == _pageGeneration && generation > 0;

  BlocklyHostChannelDisposition classify(String message) {
    try {
      final Object? decoded = jsonDecode(message);
      if (decoded is Map<String, dynamic> &&
          decoded.length == 2 &&
          decoded['version'] == kBlocksBridgeVersion &&
          decoded['type'] == 'hostReady') {
        if (_pageGeneration == 0 || _configuredGeneration == _pageGeneration) {
          return BlocklyHostChannelDisposition.ignore;
        }
        if (_attemptingGeneration == _pageGeneration) {
          _queuedReadinessGeneration = _pageGeneration;
          return BlocklyHostChannelDisposition.ignore;
        }
        _attemptingGeneration = _pageGeneration;
        return BlocklyHostChannelDisposition.initialise;
      }

      if (decoded is! Map<String, dynamic>) {
        return BlocklyHostChannelDisposition.reject;
      }
      final Object? messageHostEpoch = decoded['hostEpoch'];
      if (messageHostEpoch is! int || messageHostEpoch < 1) {
        return BlocklyHostChannelDisposition.reject;
      }
      if (_pageGeneration == 0 || messageHostEpoch != _hostEpoch) {
        return BlocklyHostChannelDisposition.ignore;
      }
      return BlocklyHostChannelDisposition.forward;
    } on FormatException {
      return BlocklyHostChannelDisposition.reject;
    }
  }

  /// Commits one configuration attempt and requests a serialized retry when a
  /// readiness duplicate arrived while the failed attempt was in flight.
  bool finishInitialisation(int generation, {required bool succeeded}) {
    if (!isCurrentGeneration(generation) ||
        _attemptingGeneration != generation) {
      return false;
    }
    _attemptingGeneration = 0;
    if (succeeded) {
      _configuredGeneration = generation;
      _queuedReadinessGeneration = 0;
      return false;
    }
    if (_queuedReadinessGeneration == generation) {
      _queuedReadinessGeneration = 0;
      _attemptingGeneration = generation;
      return true;
    }
    return false;
  }
}

/// Keeps readiness control traffic out of the document bridge.
@visibleForTesting
void dispatchBlocklyHostChannelMessage({
  required BlocklyHostStartupGate gate,
  required String message,
  required VoidCallback initialise,
  required ValueChanged<String> forward,
  required VoidCallback reject,
}) {
  switch (gate.classify(message)) {
    case BlocklyHostChannelDisposition.initialise:
      initialise();
      return;
    case BlocklyHostChannelDisposition.forward:
      forward(message);
      return;
    case BlocklyHostChannelDisposition.ignore:
      return;
    case BlocklyHostChannelDisposition.reject:
      reject();
      return;
  }
}

/// Serializes native setup against the controller's lazily created WebView.
@visibleForTesting
Future<void> configureBlocklyControllerSequentially({
  required bool Function() isCancelled,
  required Future<void> Function() enableJavaScript,
  required Future<void> Function() installJavaScriptChannel,
  required Future<void> Function() installNavigationDelegate,
}) async {
  if (isCancelled()) return;
  await enableJavaScript();
  if (isCancelled()) return;
  await installJavaScriptChannel();
  if (isCancelled()) return;
  await installNavigationDelegate();
}

/// Loads the bundled page only after every asynchronous controller hook exists.
Future<void> loadBlocklyAssetAfterControllerSetup({
  required Future<void> setup,
  required Future<void> Function() waitUntilLoadAllowed,
  required bool Function() isCancelled,
  required Future<void> Function() load,
}) async {
  await setup;
  if (isCancelled()) return;
  await waitUntilLoadAllowed();
  if (isCancelled()) return;
  await load();
}

/// Owns startup errors immediately while deferring provider mutation until a
/// descendant can safely report after its first Flutter frame.
@visibleForTesting
Future<void> runBlocklyStartupGuarded({
  required Future<void> Function() startup,
  required Future<void> Function() waitUntilFailureCanBeReported,
  required bool Function() isCancelled,
  required ValueChanged<Object> reportFailure,
}) async {
  try {
    await startup();
  } catch (error) {
    await waitUntilFailureCanBeReported();
    if (isCancelled()) return;
    reportFailure(error);
  }
}

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

/// Whether a main-frame start is an authored Blockly document generation.
@visibleForTesting
bool isBlocklyAssetDocumentNavigation(String value) =>
    value != 'about:blank' && isAllowedBlocklyNavigation(value);

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
        'waveshare-esp32-s3-lcd-147b': l10n.blocksExampleTftTitle,
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
      'tftCategory': l10n.blocksTftCategory,
      'tftCreateMessage': l10n.blocksTftCreate(
        '%1',
        '%2',
        '%3',
        '%4',
        '%5',
        '%6',
        '%7',
        '%8',
        '%9',
        '%10',
        '%11',
        '%12',
        '%13',
        '%14',
        '%15',
        '%16',
      ),
      'tftRgb565Message': l10n.blocksTftRgb565('%1', '%2', '%3'),
      'tftFillMessage': l10n.blocksTftFill('%1', '%2'),
      'tftPixelMessage': l10n.blocksTftPixel('%1', '%2', '%3', '%4'),
      'tftRectMessage': l10n.blocksTftRect(
        '%1',
        '%2',
        '%3',
        '%4',
        '%5',
        '%6',
        '%7',
      ),
      'tftTextMessage': l10n.blocksTftText('%1', '%2', '%3', '%4', '%5'),
      'tftShowMessage': l10n.blocksTftShow('%1'),
      'tftBacklightMessage': l10n.blocksTftBacklight('%1', '%2'),
      'tftRectOutline': l10n.blocksTftRectOutline,
      'tftRectFilled': l10n.blocksTftRectFilled,
      'tftCreateTooltip': l10n.blocksTftCreateTooltip,
      'tftRgb565Tooltip': l10n.blocksTftRgb565Tooltip,
      'tftFillTooltip': l10n.blocksTftFillTooltip,
      'tftPixelTooltip': l10n.blocksTftPixelTooltip,
      'tftRectTooltip': l10n.blocksTftRectTooltip,
      'tftTextTooltip': l10n.blocksTftTextTooltip,
      'tftShowTooltip': l10n.blocksTftShowTooltip,
      'tftBacklightTooltip': l10n.blocksTftBacklightTooltip,
      'tftCreateInputRequiredError': l10n.blocksTftCreateInputRequired,
      'tftSpiIdInvalidError': l10n.blocksTftSpiIdInvalid,
      'tftBaudrateInvalidError': l10n.blocksTftBaudrateInvalid,
      'tftSpiModeInvalidError': l10n.blocksTftSpiModeInvalid,
      'tftGeometryInvalidError': l10n.blocksTftGeometryInvalid,
      'tftOffsetInvalidError': l10n.blocksTftOffsetInvalid,
      'tftColorComponentRequiredError': l10n.blocksTftColorComponentRequired,
      'tftDisplayRequiredError': l10n.blocksTftDisplayRequired,
      'tftColorRequiredError': l10n.blocksTftColorRequired,
      'tftCoordinateRequiredError': l10n.blocksTftCoordinateRequired,
      'tftTextRequiredError': l10n.blocksTftTextRequired,
      'tftBacklightRequiredError': l10n.blocksTftBacklightRequired,
      'tftRectStyleInvalidError': l10n.blocksTftRectStyleInvalid,
      'tftRestoreStyleInvalidError': l10n.blocksTftRestoreStyleInvalid,
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
  late final Completer<void> _startupLoadAllowed;
  late final Future<void> _startupFuture;
  late final BlocksDocumentController _documentController;
  late int _hostId;
  final BlocklyHostStartupGate _startupGate = BlocklyHostStartupGate();
  Timer? _firstMessageTimer;
  bool _assetPageStarted = false;
  bool _startupCancelled = false;

  @override
  void initState() {
    super.initState();
    _documentController = ref.read(blocksDocumentProvider.notifier);
    _controller = WebViewController();
    _startupLoadAllowed = Completer<void>();
    _hostId = _beginDocumentHost();
    final int bootstrapHostId = _hostId;
    final Future<void> controllerSetup = configureBlocklyControllerSequentially(
      isCancelled: () => _startupCancelled,
      enableJavaScript: () =>
          _controller.setJavaScriptMode(JavaScriptMode.unrestricted),
      installJavaScriptChannel: () => _controller.addJavaScriptChannel(
        _channelName,
        onMessageReceived: (JavaScriptMessage message) {
          if (!mounted) return;
          dispatchBlocklyHostChannelMessage(
            gate: _startupGate,
            message: message.message,
            initialise: () {
              final int hostId = _hostId;
              final int generation = _startupGate.generation;
              unawaited(_initialiseHost(hostId, generation));
            },
            forward: (String bridgeMessage) {
              final int hostId = _hostId;
              final BlocksBridgeResult result = _documentController
                  .receiveBridgeMessage(bridgeMessage, hostId: hostId);
              if (shouldCancelBlocksStartupWatchdog(result)) {
                _firstMessageTimer?.cancel();
              }
            },
            reject: () {
              final int hostId = _hostId;
              _firstMessageTimer?.cancel();
              _documentController.reportHostError(
                'Blockly bridge message has an invalid host epoch',
                hostId: hostId,
              );
            },
          );
        },
      ),
      installNavigationDelegate: () => _controller.setNavigationDelegate(
        NavigationDelegate(
          onPageStarted: _onPageStarted,
          onNavigationRequest: (NavigationRequest request) =>
              isAllowedBlocklyNavigation(request.url)
              ? NavigationDecision.navigate
              : NavigationDecision.prevent,
        ),
      ),
    );
    bool startupIsCancelled() =>
        _startupCancelled || !mounted || bootstrapHostId != _hostId;
    _startupFuture = runBlocklyStartupGuarded(
      startup: () => loadBlocklyAssetAfterControllerSetup(
        setup: controllerSetup,
        waitUntilLoadAllowed: () => _startupLoadAllowed.future,
        isCancelled: startupIsCancelled,
        load: () => _controller.loadFlutterAsset(_assetPath),
      ),
      waitUntilFailureCanBeReported: () => _startupLoadAllowed.future,
      isCancelled: startupIsCancelled,
      reportFailure: (Object error) {
        _firstMessageTimer?.cancel();
        _documentController.reportHostError(
          error.toString(),
          hostId: bootstrapHostId,
        );
      },
    );
    unawaited(_startupFuture);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        if (!_startupLoadAllowed.isCompleted) _startupLoadAllowed.complete();
        return;
      }
      _documentController.markHostLoading(_hostId);
      _armFirstSnapshotWatchdog();
      if (!_startupLoadAllowed.isCompleted) _startupLoadAllowed.complete();
    });
  }

  int _beginDocumentHost() => _documentController.beginHost(
    previewExample: _previewExample,
    requestSnapshot: _requestFreshSnapshot,
  );

  void _onPageStarted(String url) {
    if (!mounted || !isBlocklyAssetDocumentNavigation(url)) return;
    if (_assetPageStarted) {
      _hostId = _beginDocumentHost();
    } else {
      _assetPageStarted = true;
    }
    _startupGate.beginPage(hostEpoch: _hostId);
    _documentController.markHostLoading(_hostId);
    _armFirstSnapshotWatchdog();
  }

  void _armFirstSnapshotWatchdog() {
    _firstMessageTimer?.cancel();
    final int hostId = _hostId;
    final int generation = _startupGate.generation;
    _firstMessageTimer = Timer(_firstSnapshotTimeout, () {
      if (!mounted || hostId != _hostId) return;
      if (_startupGate.generation != generation) return;
      _documentController.reportHostError(
        AppLocalizations.of(context).blocksStartupTimeout,
        hostId: hostId,
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

  Future<void> _initialiseHost(int hostId, int generation) async {
    if (!mounted ||
        hostId != _hostId ||
        !_startupGate.isCurrentGeneration(generation)) {
      return;
    }
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
        '$messages, $hostId$retainedArguments);',
      );
      if (!mounted ||
          hostId != _hostId ||
          !_startupGate.isCurrentGeneration(generation)) {
        return;
      }
      if (!_javascriptTrue(configured)) {
        throw const FormatException('Blockly rejected localized host messages');
      }
      _startupGate.finishInitialisation(generation, succeeded: true);
    } catch (error) {
      if (!mounted ||
          hostId != _hostId ||
          !_startupGate.isCurrentGeneration(generation)) {
        return;
      }
      final bool retry = _startupGate.finishInitialisation(
        generation,
        succeeded: false,
      );
      if (retry) {
        unawaited(_initialiseHost(hostId, generation));
        return;
      }
      _documentController.reportHostError(error.toString(), hostId: hostId);
    }
  }

  @override
  void dispose() {
    _startupCancelled = true;
    if (!_startupLoadAllowed.isCompleted) _startupLoadAllowed.complete();
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
