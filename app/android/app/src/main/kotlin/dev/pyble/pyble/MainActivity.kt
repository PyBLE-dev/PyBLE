// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

package dev.pyble.pyble

import android.view.inputmethod.InputMethodManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "dev.pyble/keyboard")
            .setMethodCallHandler { call, result ->
                if (call.method == "dismissKeyboard") {
                    val manager = getSystemService(InputMethodManager::class.java)
                    window.decorView.windowToken?.let { token ->
                        manager?.hideSoftInputFromWindow(token, 0)
                    }
                    // Acknowledge the request; Flutter observes actual view insets.
                    result.success(null)
                } else {
                    result.notImplemented()
                }
            }
    }
}
