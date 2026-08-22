# Contributing to PyBLE

Thank you for helping build an open, BLE-first MicroPython IDE. Contributions
to the app, firmware, PBLE/1 protocol, documentation, translations, tests, and
new validated board ports are welcome.

By participating, you agree to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Before starting

1. Read [`AGENTS.md`](AGENTS.md) for the repository’s clean-room,
   spec-driven, test-driven, licensing, naming, and commit rules.
2. Search existing issues and discussions before starting a substantial
   change.
3. For a public contract change, propose or update the relevant file under
   `docs/specifications/` first.
4. Keep pull requests focused on one concern.

## Development method

PyBLE follows red → green → refactor:

1. Add an automated test that demonstrates the missing behavior.
2. Commit it with a `[red]` prefix.
3. Implement the smallest complete fix and commit it with `[green]`.
4. Use `[refactor]` for behavior-preserving cleanup.

Documentation, build, and maintenance commits use `[docs]`, `[build]`, and
`[chore]`. Every commit must be signed off:

```sh
git commit -s -m "[red] Describe the missing behavior"
```

The sign-off certifies compliance with the
[Developer Certificate of Origin](https://developercertificate.org/). PyBLE
uses DCO sign-off instead of a contributor license agreement.

## Clean-room and licensing rules

- Author PyBLE changes fresh under MIT.
- Never paste proprietary or unknown-licensed code, protocol values, UUIDs,
  board profiles, teaching content, or product identifiers.
- Do not edit the pinned upstream submodules in place.
- Record third-party dependencies and preserve their license notices.
- Run the repository gates before submitting:

```sh
tools/ci/no_leak.sh
tools/ci/spdx_lint.sh
tests/firmware_tests/test_governance_files.sh
```

## Set up the repository

```sh
git clone --recurse-submodules https://github.com/PyBLE-dev/PyBLE.git
cd PyBLE
```

If the repository was cloned without submodules:

```sh
git submodule update --init --recursive
```

### Flutter app

The app is one Flutter package:

```sh
cd app
flutter pub get --enforce-lockfile
flutter gen-l10n
dart format --output=none --set-exit-if-changed lib test integration_test
flutter analyze
flutter test --exclude-tags golden
```

On macOS, also run the renderer-specific pixel baselines:

```sh
flutter test --tags golden
```

Use a recent stable Flutter SDK matching the version pinned by CI.

Use the normal package directly on iOS:

```sh
flutter run -d <ios-device>
```

Always name an Android flavor. `production` is the normal launcher, while
`integration` uses the disposable `dev.pyble.pyble.integrationtest` package:

```sh
flutter run --flavor production --target lib/main.dart -d <android-device>
flutter build apk --release --flavor production --target lib/main.dart
flutter drive --flavor integration \
  --driver test_driver/integration_test.dart \
  --target integration_test/android_smoke_test.dart \
  -d <android-device>
```

Debug runs use the normal Android development key. Every release task fails
closed unless the owner or CI supplies the BLD-12 signing environment:

```sh
export PYBLE_ANDROID_KEYSTORE_PATH=/absolute/path/to/upload-key.p12
export PYBLE_ANDROID_KEYSTORE_PASSWORD='<from secret manager>'
export PYBLE_ANDROID_KEY_ALIAS='<from secret manager>'
export PYBLE_ANDROID_KEY_PASSWORD='<from secret manager>'

flutter build apk --release --flavor production --target lib/main.dart
flutter build appbundle --release --flavor production --target lib/main.dart
```

Never commit or print these values. The public CI job uses a disposable CI-only
key to exercise the same release path; it never receives the Play upload key.
Before uploading an AAB, verify its JAR signature and compare its signer
SHA-256 certificate fingerprint with the owner-controlled upload certificate.

### Firmware

Host-side protocol and release tests do not require hardware:

```sh
tests/firmware_tests/run_tests.sh
```

Prepare the pinned toolchains and build one of the initial ports:

```sh
firmware/scripts/install_esp_idf.sh
firmware/scripts/build.sh esp32
firmware/scripts/build.sh esp32-s3
firmware/scripts/build.sh esp32-c3
```

New ports must provide a maintained PBLE/1 BLE GATT peripheral agent and pass
the documented build, conformance, resource, recovery, release, and HIL gates.
Stock MicroPython plus a Bluetooth radio is not automatically compatible.

### Website

```sh
cd tools/web
npm ci
npm run check
```

## Pull-request checklist

- [ ] The relevant specification changed first when a contract changed.
- [ ] Tests cover the behavior and pass.
- [ ] Every commit is DCO-signed.
- [ ] The no-leak and SPDX gates pass.
- [ ] Dependencies and notices are updated when needed.
- [ ] User-facing strings retain localization parity.
- [ ] Hardware claims include the required HIL evidence.
- [ ] The changelog or public roadmap is updated when appropriate.

For BLE or hardware reports, include the exact board, memory profile, firmware
version, app version and platform, reproduction steps, and sanitized console
output. Report security-sensitive findings privately as described in
[SECURITY.md](SECURITY.md).
