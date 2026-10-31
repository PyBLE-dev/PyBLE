// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import Flutter
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  private var keyboardInsets: PybleKeyboardInsets?

  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    guard let registrar = engineBridge.pluginRegistry.registrar(forPlugin: "PybleKeyboardDismissal")
    else { return }
    keyboardInsets = PybleKeyboardInsets(registrar: registrar)
    let keyboard = FlutterMethodChannel(
      name: "dev.pyble/keyboard", binaryMessenger: registrar.messenger())
    keyboard.setMethodCallHandler { [weak registrar] call, result in
      guard call.method == "dismissKeyboard" else {
        result(FlutterMethodNotImplemented)
        return
      }
      // End editing in this engine's window, including embedded WKWebView fields.
      registrar?.viewController?.viewIfLoaded?.window?.endEditing(true)
      // Acknowledge the request; Flutter observes actual view insets.
      result(nil)
    }
  }
}

/// Measures the current Flutter view's public layout guide instead of keyboard
/// notification frames, which can be offscreen after an iPad palette transition.
private final class PybleKeyboardInsets {
  private weak var registrar: FlutterPluginRegistrar?
  private let channel: FlutterMethodChannel
  private var observer: PybleKeyboardGuideView?
  private var generation: Int?
  private var lastBottom: CGFloat?

  init(registrar: FlutterPluginRegistrar) {
    self.registrar = registrar
    channel = FlutterMethodChannel(
      name: "dev.pyble/keyboard/insets", binaryMessenger: registrar.messenger())
    channel.setMethodCallHandler { [weak self] call, result in
      guard let self = self, let epoch = call.arguments as? Int else {
        result(FlutterMethodNotImplemented)
        return
      }
      switch call.method {
      case "observe":
        self.observe(generation: epoch)
        result(nil)
      case "stop":
        if self.generation == epoch { self.stop() }
        result(nil)
      default:
        result(FlutterMethodNotImplemented)
      }
    }
  }

  private func observe(generation: Int) {
    if self.generation != generation {
      stop()
      self.generation = generation
    }
    guard let view = registrar?.viewController?.viewIfLoaded else {
      observer?.removeFromSuperview()
      observer = nil
      publish(0)
      return
    }
    if observer?.superview !== view {
      observer?.removeFromSuperview()
      let guideView = PybleKeyboardGuideView()
      guideView.translatesAutoresizingMaskIntoConstraints = false
      guideView.isUserInteractionEnabled = false
      guideView.accessibilityElementsHidden = true
      guideView.backgroundColor = .clear
      guideView.changed = { [weak self] bottom in self?.publish(bottom) }
      observer = guideView
      view.addSubview(guideView)
      NSLayoutConstraint.activate([
        guideView.topAnchor.constraint(equalTo: view.keyboardLayoutGuide.topAnchor),
        guideView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        guideView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
        guideView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
      ])
      view.layoutIfNeeded()
    }
    // An explicit refresh must return a snapshot even if UIKit has not moved:
    // Dart may have rejected the previous value while its window size lagged.
    lastBottom = nil
    observer?.reportOverlap()
  }

  private func publish(_ bottom: CGFloat) {
    guard let generation = generation, bottom != lastBottom else { return }
    lastBottom = bottom
    channel.invokeMethod("inset", arguments: ["generation": generation, "bottom": bottom])
  }

  private func stop() {
    generation = nil
    observer?.removeFromSuperview()
    observer = nil
    lastBottom = nil
  }
}

private final class PybleKeyboardGuideView: UIView {
  var changed: ((CGFloat) -> Void)?

  override func layoutSubviews() {
    super.layoutSubviews()
    reportOverlap()
  }

  override func didMoveToWindow() {
    super.didMoveToWindow()
    reportOverlap()
  }

  func reportOverlap() {
    guard let owner = superview, window != nil else {
      changed?(0)
      return
    }
    // On iOS 15/16 a hidden/undocked guide ends at the safe-area bottom.
    // A real docked keyboard or input palette reports its full overlap.
    let overlap = min(owner.bounds.height, max(0, bounds.height))
    changed?(overlap <= owner.safeAreaInsets.bottom + 0.5 ? 0 : overlap)
  }
}
