// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// X-11 / BLD-10/13 — platform launchers and deployment metadata preserve the
// PyBLE distribution contract.

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import '../support/repo_paths.dart';

final class _PngInfo {
  const _PngInfo({
    required this.width,
    required this.height,
    required this.bitDepth,
    required this.colorType,
  });

  final int width;
  final int height;
  final int bitDepth;
  final int colorType;
}

_PngInfo _readPng(File file) {
  expect(file.existsSync(), isTrue, reason: '${file.path} must exist');
  final Uint8List bytes = file.readAsBytesSync();
  expect(
    bytes.take(8),
    orderedEquals(const <int>[137, 80, 78, 71, 13, 10, 26, 10]),
    reason: '${file.path} must be a PNG',
  );
  expect(
    String.fromCharCodes(bytes.sublist(12, 16)),
    'IHDR',
    reason: '${file.path} must start with a PNG IHDR chunk',
  );

  int uint32At(int offset) =>
      ByteData.sublistView(bytes, offset, offset + 4).getUint32(0);

  return _PngInfo(
    width: uint32At(16),
    height: uint32At(20),
    bitDepth: bytes[24],
    colorType: bytes[25],
  );
}

void _expectOpaqueRgbPng(File file, int size) {
  final _PngInfo png = _readPng(file);
  expect(png.width, size, reason: '${file.path} width');
  expect(png.height, size, reason: '${file.path} height');
  expect(png.bitDepth, 8, reason: '${file.path} bit depth');
  expect(
    png.colorType,
    2,
    reason: '${file.path} must be opaque true-color RGB, without alpha',
  );
}

void _expectOpaqueGrayscalePng(File file, int size) {
  final _PngInfo png = _readPng(file);
  expect(png.width, size, reason: '${file.path} width');
  expect(png.height, size, reason: '${file.path} height');
  expect(png.bitDepth, 8, reason: '${file.path} bit depth');
  expect(
    png.colorType,
    0,
    reason: '${file.path} must be opaque 8-bit grayscale',
  );
}

void _expectRgbaPng(File file, int size) {
  final _PngInfo png = _readPng(file);
  expect(png.width, size, reason: '${file.path} width');
  expect(png.height, size, reason: '${file.path} height');
  expect(png.bitDepth, 8, reason: '${file.path} bit depth');
  expect(
    png.colorType,
    6,
    reason: '${file.path} must be 8-bit true-color RGBA',
  );
}

void main() {
  final Directory app = appPackageRoot();

  test('package metadata describes the board-neutral product scope', () {
    final String pubspec = File('${app.path}/pubspec.yaml').readAsStringSync();

    expect(
      pubspec,
      contains(
        'a free, MIT, tablet-first IDE for compatible MicroPython boards '
        'over BLE',
      ),
    );
    expect(pubspec, isNot(contains('generic ESP32 / ESP32-S3 / ESP32-C3')));
  });

  test('iOS package metadata uses the exact PyBLE wordmark', () {
    final String plist = File(
      '${app.path}/ios/Runner/Info.plist',
    ).readAsStringSync();

    expect(
      plist,
      contains(
        '<key>CFBundleDisplayName</key>\n'
        '\t<string>PyBLE</string>',
      ),
    );
    expect(
      plist,
      contains('<key>CFBundleName</key>\n\t<string>PyBLE</string>'),
    );
  });

  test('iOS project does not publish a maintainer signing team', () {
    final String project = File(
      '${app.path}/ios/Runner.xcodeproj/project.pbxproj',
    ).readAsStringSync();

    expect(
      project,
      isNot(contains('DEVELOPMENT_TEAM =')),
      reason:
          'distribution signing must be supplied from maintainer-local '
          'configuration',
    );
  });

  test('iOS project pins every configuration to deployment target 15', () {
    final String project = File(
      '${app.path}/ios/Runner.xcodeproj/project.pbxproj',
    ).readAsStringSync();
    final List<String> deploymentTargets =
        RegExp(r'^\s*IPHONEOS_DEPLOYMENT_TARGET = ([^;]+);$', multiLine: true)
            .allMatches(project)
            .map((RegExpMatch match) {
              return match.group(1)!;
            })
            .toList(growable: false);

    expect(
      deploymentTargets,
      hasLength(3),
      reason: 'Profile, Debug, and Release must each declare one target',
    );
    expect(
      deploymentTargets,
      everyElement('15.0'),
      reason: 'every authored iOS deployment target must use the BLD-13 floor',
    );

    final String plist = File(
      '${app.path}/ios/Runner/Info.plist',
    ).readAsStringSync();
    expect(
      plist,
      isNot(contains('<key>MinimumOSVersion</key>')),
      reason: 'Xcode must derive MinimumOSVersion from the deployment target',
    );
  });

  test('Android launcher metadata uses the exact PyBLE wordmark', () {
    final String manifest = File(
      '${app.path}/android/app/src/main/AndroidManifest.xml',
    ).readAsStringSync();

    expect(manifest, contains('android:label="PyBLE"'));
    expect(manifest, contains('android:icon="@mipmap/ic_launcher"'));
  });

  test('Prompt Chip has a flat grid-defined vector source', () {
    final String source = File(
      '${app.path}/assets/branding/pyble-prompt-chip.svg',
    ).readAsStringSync();

    expect(source, contains('viewBox="0 0 108 108"'));
    expect(source, contains('#081B35'));
    expect(source, contains('#2F8CFF'));
    expect(source, contains('#F4F7FF'));
    expect(source, contains('id="chip-frame"'));
    expect(source, contains('id="chip-pins"'));
    expect(source, contains('id="terminal-prompt"'));
    expect(source, contains('id="radio-signal"'));
    expect(RegExp(r'<path\b').allMatches(source), hasLength(4));
    expect(source, isNot(contains('<text')));
    expect(source, isNot(contains('<linearGradient')));
    expect(source, isNot(contains('<radialGradient')));
    expect(source, isNot(contains('<filter')));
  });

  test('Prompt Chip master is the opaque iOS default icon', () {
    final File master = File(
      '${app.path}/assets/branding/pyble-prompt-chip-master.png',
    );
    final File marketing = File(
      '${app.path}/ios/Runner/Assets.xcassets/AppIcon.appiconset/'
      'Icon-App-1024x1024@1x.png',
    );

    _expectOpaqueRgbPng(master, 1024);
    _expectOpaqueRgbPng(marketing, 1024);
    expect(
      marketing.readAsBytesSync(),
      orderedEquals(master.readAsBytesSync()),
    );
  });

  test('iOS icon catalog declares default, dark, and tinted appearances', () {
    final File manifest = File(
      '${app.path}/ios/Runner/Assets.xcassets/AppIcon.appiconset/Contents.json',
    );
    final Map<String, dynamic> catalog =
        jsonDecode(manifest.readAsStringSync()) as Map<String, dynamic>;
    final List<Map<String, dynamic>> images =
        (catalog['images'] as List<dynamic>).cast<Map<String, dynamic>>();

    expect(images, hasLength(3));

    Map<String, dynamic> imageNamed(String filename) => images.singleWhere(
      (Map<String, dynamic> image) => image['filename'] == filename,
    );

    final Map<String, dynamic> defaultIcon = imageNamed(
      'Icon-App-1024x1024@1x.png',
    );
    final Map<String, dynamic> darkIcon = imageNamed(
      'Icon-App-1024x1024-dark@1x.png',
    );
    final Map<String, dynamic> tintedIcon = imageNamed(
      'Icon-App-1024x1024-tinted@1x.png',
    );

    for (final Map<String, dynamic> image in images) {
      expect(image['idiom'], 'universal');
      expect(image['platform'], 'ios');
      expect(image['size'], '1024x1024');
    }
    expect(defaultIcon, isNot(contains('appearances')));
    expect(darkIcon['appearances'], <Map<String, String>>[
      <String, String>{'appearance': 'luminosity', 'value': 'dark'},
    ]);
    expect(tintedIcon['appearances'], <Map<String, String>>[
      <String, String>{'appearance': 'luminosity', 'value': 'tinted'},
    ]);

    final String root = manifest.parent.path;
    _expectOpaqueRgbPng(File('$root/${darkIcon['filename']}'), 1024);
    _expectOpaqueGrayscalePng(File('$root/${tintedIcon['filename']}'), 1024);
  });

  test('iOS launcher set keeps every opaque legacy QA size', () {
    final String root =
        '${app.path}/ios/Runner/Assets.xcassets/AppIcon.appiconset';
    const Map<String, int> sizes = <String, int>{
      'Icon-App-20x20@1x.png': 20,
      'Icon-App-20x20@2x.png': 40,
      'Icon-App-20x20@3x.png': 60,
      'Icon-App-29x29@1x.png': 29,
      'Icon-App-29x29@2x.png': 58,
      'Icon-App-29x29@3x.png': 87,
      'Icon-App-40x40@1x.png': 40,
      'Icon-App-40x40@2x.png': 80,
      'Icon-App-40x40@3x.png': 120,
      'Icon-App-60x60@2x.png': 120,
      'Icon-App-60x60@3x.png': 180,
      'Icon-App-76x76@1x.png': 76,
      'Icon-App-76x76@2x.png': 152,
      'Icon-App-83.5x83.5@2x.png': 167,
      'Icon-App-1024x1024@1x.png': 1024,
    };

    for (final MapEntry<String, int> entry in sizes.entries) {
      _expectOpaqueRgbPng(File('$root/${entry.key}'), entry.value);
    }
  });

  test('Android launcher has adaptive and monochrome vector layers', () {
    final String root = '${app.path}/android/app/src/main/res';
    final String source = File(
      '${app.path}/assets/branding/pyble-prompt-chip.svg',
    ).readAsStringSync();
    final String adaptive = File(
      '$root/mipmap-anydpi-v26/ic_launcher.xml',
    ).readAsStringSync();
    final String colors = File('$root/values/colors.xml').readAsStringSync();
    final String foreground = File(
      '$root/drawable/ic_launcher_foreground.xml',
    ).readAsStringSync();
    final String monochrome = File(
      '$root/drawable/ic_launcher_monochrome.xml',
    ).readAsStringSync();
    String canonicalPath(String id) {
      final RegExpMatch? match = RegExp(
        'id="$id"[\\s\\S]*?d="([^"]+)"',
      ).firstMatch(source);
      expect(match, isNotNull, reason: 'missing canonical $id path');
      return match!.group(1)!;
    }

    expect(
      adaptive,
      contains(
        '<background android:drawable="@color/ic_launcher_background" />',
      ),
    );
    expect(
      adaptive,
      contains(
        '<foreground android:drawable="@drawable/ic_launcher_foreground" />',
      ),
    );
    expect(
      adaptive,
      contains(
        '<monochrome android:drawable="@drawable/ic_launcher_monochrome" />',
      ),
    );
    expect(
      colors,
      contains('<color name="ic_launcher_background">#081B35</color>'),
    );

    for (final String layer in <String>[foreground, monochrome]) {
      expect(layer, contains('android:width="108dp"'));
      expect(layer, contains('android:height="108dp"'));
      expect(layer, contains('android:viewportWidth="108"'));
      expect(layer, contains('android:viewportHeight="108"'));
      expect(layer, contains('android:strokeLineCap="round"'));
      expect(layer, contains('android:strokeLineJoin="round"'));
    }
    expect(foreground, contains('#2F8CFF'));
    expect(foreground, contains('#F4F7FF'));
    expect(monochrome, contains('#FFFFFFFF'));
    for (final String id in <String>[
      'chip-frame',
      'chip-pins',
      'terminal-prompt',
      'radio-signal',
    ]) {
      final String path = canonicalPath(id);
      expect(foreground, contains('android:pathData="$path"'));
      expect(monochrome, contains('android:pathData="$path"'));
    }
  });

  test('Android launcher set contains every opaque density size', () {
    final String root = '${app.path}/android/app/src/main/res';
    const Map<String, int> sizes = <String, int>{
      'mipmap-mdpi/ic_launcher.png': 48,
      'mipmap-hdpi/ic_launcher.png': 72,
      'mipmap-xhdpi/ic_launcher.png': 96,
      'mipmap-xxhdpi/ic_launcher.png': 144,
      'mipmap-xxxhdpi/ic_launcher.png': 192,
    };

    for (final MapEntry<String, int> entry in sizes.entries) {
      _expectOpaqueRgbPng(File('$root/${entry.key}'), entry.value);
    }
  });

  test('Google Play listing icon is a 512-pixel RGBA asset', () {
    final File listing = File(
      '${app.path}/assets/branding/pyble-google-play-512.png',
    );
    _expectRgbaPng(listing, 512);
    expect(listing.lengthSync(), lessThan(1024 * 1024));
  });
}
