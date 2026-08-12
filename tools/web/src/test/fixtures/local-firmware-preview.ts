// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import type {
  LocalFirmwarePreviewDescriptor,
  LocalPreviewArtifact,
} from "@/lib/local-firmware-preview";

function artifact(path: string, marker: string): LocalPreviewArtifact {
  return {
    path,
    size: 4096,
    sha256: marker.repeat(64),
  };
}

export function localFiveTargetPreview(): LocalFirmwarePreviewDescriptor {
  const root = "/.pyble-local-preview";
  return {
    schemaVersion: 1,
    deployment: "local-preview",
    localOnly: true,
    qualified: false,
    version: "0.6.0",
    sourceCommit: "a".repeat(40),
    builtAt: "2026-08-12T00:00:00.000Z",
    profiles: [
      {
        id: "esp32-4mb",
        label: "ESP32 · 4 MiB flash",
        chipFamily: "ESP32",
        buildTarget: "esp32",
        method: "esp-web-tools",
        qualified: false,
        status: "engineering-preview",
        offset: 4096,
        manifest: artifact(`${root}/esp32-4mb/manifest.json`, "1"),
        firmware: artifact(`${root}/esp32-4mb/firmware.bin`, "2"),
      },
      {
        id: "esp32-s3-n16r8",
        label: "ESP32-S3 · N16R8 · lean generic",
        chipFamily: "ESP32-S3",
        buildTarget: "esp32-s3",
        method: "esp-web-tools",
        qualified: false,
        status: "engineering-preview",
        offset: 0,
        manifest: artifact(`${root}/esp32-s3-n16r8/manifest.json`, "3"),
        firmware: artifact(`${root}/esp32-s3-n16r8/firmware.bin`, "4"),
      },
      {
        id: "waveshare-esp32-s3-lcd-147b",
        label: "Waveshare ESP32-S3-LCD-1.47B · N16R8",
        chipFamily: "ESP32-S3",
        buildTarget: "waveshare-esp32-s3-lcd-147b",
        method: "esp-web-tools",
        qualified: false,
        status: "engineering-preview",
        offset: 0,
        manifest: artifact(
          `${root}/waveshare-esp32-s3-lcd-147b/manifest.json`,
          "5",
        ),
        firmware: artifact(
          `${root}/waveshare-esp32-s3-lcd-147b/firmware.bin`,
          "6",
        ),
      },
      {
        id: "esp32-c3-4mb",
        label: "ESP32-C3 revision v0.3+ · 4 MiB flash",
        chipFamily: "ESP32-C3",
        buildTarget: "esp32-c3",
        method: "esp-web-tools",
        qualified: false,
        status: "engineering-preview",
        offset: 0,
        manifest: artifact(`${root}/esp32-c3-4mb/manifest.json`, "7"),
        firmware: artifact(`${root}/esp32-c3-4mb/firmware.bin`, "8"),
      },
      {
        id: "rpi-pico2-w",
        label: "Raspberry Pi Pico 2 W",
        chipFamily: "RP2350",
        buildTarget: "rpi-pico2-w",
        method: "uf2-download",
        qualified: false,
        status: "engineering-preview",
        firmware: artifact(`${root}/rpi-pico2-w/firmware.uf2`, "9"),
      },
    ],
  };
}
