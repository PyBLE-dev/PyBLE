plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

val pybleReleaseTaskRequested =
    gradle.startParameter.taskNames.any { taskName ->
        taskName.contains("Release", ignoreCase = true)
    }

// BLD-12: even `flutter run --release --flavor production` must use an
// explicit non-debug signing identity; no release task falls back to debug.

fun pybleReleaseEnvironment(name: String): String? {
    val value = providers.environmentVariable(name).orNull?.trim()
    if (pybleReleaseTaskRequested) {
        require(!value.isNullOrEmpty()) {
            "$name must be provided by the secret manager for Android release builds."
        }
    }
    return value?.takeIf { it.isNotEmpty() }
}

val pybleAndroidKeystorePath =
    pybleReleaseEnvironment("PYBLE_ANDROID_KEYSTORE_PATH")
val pybleAndroidKeystorePassword =
    pybleReleaseEnvironment("PYBLE_ANDROID_KEYSTORE_PASSWORD")
val pybleAndroidKeyAlias =
    pybleReleaseEnvironment("PYBLE_ANDROID_KEY_ALIAS")
val pybleAndroidKeyPassword =
    pybleReleaseEnvironment("PYBLE_ANDROID_KEY_PASSWORD")

android {
    namespace = "dev.pyble.pyble"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "dev.pyble.pyble"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    flavorDimensions += "purpose"
    productFlavors {
        create("production") {
            dimension = "purpose"
        }
        create("integration") {
            dimension = "purpose"
            applicationIdSuffix = ".integrationtest"
        }
    }

    signingConfigs {
        create("release") {
            if (pybleReleaseTaskRequested) {
                val keystore = file(pybleAndroidKeystorePath!!)
                require(keystore.isFile) {
                    "PYBLE_ANDROID_KEYSTORE_PATH must name an existing regular file."
                }
                storeFile = keystore
                storePassword = pybleAndroidKeystorePassword
                keyAlias = pybleAndroidKeyAlias
                keyPassword = pybleAndroidKeyPassword
                storeType = "PKCS12"
            }
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
