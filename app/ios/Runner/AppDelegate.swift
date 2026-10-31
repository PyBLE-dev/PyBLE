// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import Flutter
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
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
