// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import type { Metadata } from "next";

import {
  type FirmwareReleaseDescriptor,
  hasExactFirmwareProfileDescriptors,
  releaseIncludesWaveshareLcd147b,
} from "@/lib/firmware-release";
import {
  type LocalFirmwarePreviewDescriptor,
  localFirmwareProfileTable,
} from "@/lib/local-firmware-preview";

export const siteConfig = {
  name: "PyBLE",
  expandedName: "Python over Bluetooth Low Energy",
  origin: "https://pyble.dev",
  alternateOrigin: "https://pyble.org",
  description:
    "A free, open-source, tablet-first IDE for MicroPython boards with compatible Bluetooth Low Energy agent firmware.",
  supportEmail: "viwat.v@chula.ac.th",
  testFlightUrl: "https://testflight.apple.com/join/yU4e8s6d",
  googlePlayInternalTestUrl:
    "https://play.google.com/store/apps/details?id=dev.pyble.pyble",
  repositoryUrl: "https://github.com/PyBLE-dev/PyBLE",
  bugReportUrl:
    "https://github.com/PyBLE-dev/PyBLE/issues/new?template=bug.yml",
} as const;

export const navigation = [
  { label: "What it does", href: "/#features" },
  { label: "Blocks", href: "/#blocks" },
  { label: "Firmware", href: "/flash" },
  { label: "Support", href: "/support" },
] as const;

const firmwareTargetDefinitions = [
  {
    id: "esp32-4mb",
    target: "Classic ESP32",
    constraint: "4 MiB external SPI flash · no PSRAM assumed",
  },
  {
    id: "esp32-s3-n16r8",
    target: "ESP32-S3 N16R8",
    constraint: "16 MiB flash · 8 MiB Octal PSRAM",
  },
  {
    id: "waveshare-esp32-s3-lcd-147b",
    target: "Waveshare ESP32-S3-LCD-1.47B",
    constraint: "Exact B version · 16 MiB flash · 8 MiB Octal PSRAM",
  },
  {
    id: "esp32-c3-4mb",
    target: "ESP32-C3",
    constraint: "4 MiB external SPI flash · no PSRAM assumed",
  },
  {
    id: "rpi-pico2-w",
    target: "Raspberry Pi Pico 2 W",
    constraint: "RP2350 + CYW43439 · UF2 / BOOTSEL",
  },
] as const;

// Ports whose availability is derived from the selected release's profile
// set: absent from the release, they are presented as planned, never as a
// silently missing target.
const deferredUntilIncluded = new Set<string>(["esp32-c3-4mb", "rpi-pico2-w"]);

export function firmwareTargetsForRelease(
  release: FirmwareReleaseDescriptor | null,
) {
  const includesWaveshareLcd147b = releaseIncludesWaveshareLcd147b(release);
  const validProfileSet = Boolean(
    release &&
    (release.deployment === "public-beta" ||
      hasExactFirmwareProfileDescriptors(release.version, release.profiles)),
  );

  return firmwareTargetDefinitions
    .map((target) => ({
      target,
      included: Boolean(
        validProfileSet && release?.profiles.some(({ id }) => id === target.id),
      ),
    }))
    .filter(
      ({ target, included }) =>
        target.id !== "waveshare-esp32-s3-lcd-147b" || included,
    )
    .map(({ target, included }) => {
      const planned = !included && deferredUntilIncluded.has(target.id);
      const includesWaveshareProfile =
        target.id === "esp32-s3-n16r8"
          ? Boolean(
              validProfileSet &&
              release?.profiles.some(
                ({ id }) => id === "waveshare-esp32-s3-lcd-147b",
              ),
            )
          : false;
      let status = "Installer unavailable";
      if (planned) {
        status = "Planned · installer unavailable pending exact-profile HIL";
      } else if (included && release?.deployment === "public-beta") {
        status = `v${release.version} hardware-tested beta · browser install/recovery passed · release qualification pending`;
      } else if (included && release && includesWaveshareLcd147b) {
        status = `v${release.version} qualified public release`;
      } else if (included && release?.deployment === "candidate") {
        status = `v${release.version} protected candidate · HIL pending`;
      }
      const targetName = includesWaveshareProfile
        ? `${target.target} · lean generic`
        : target.target;
      return { ...target, target: targetName, planned, status };
    });
}

export const initialFirmwareTargets = firmwareTargetsForRelease(null);

export function firmwareTargetsForLocalPreview(
  preview: LocalFirmwarePreviewDescriptor,
) {
  return preview.profiles.map((profile) => {
    const definition = localFirmwareProfileTable.find(
      ({ id }) => id === profile.id,
    );
    if (!definition) {
      throw new Error(`unknown local firmware target: ${profile.id}`);
    }
    return {
      id: profile.id,
      target: definition.label,
      constraint: definition.requirements,
      method:
        profile.method === "esp-web-tools" ? "ESP Web Serial" : "UF2 / BOOTSEL",
      status: `v${preview.version} local engineering preview · unqualified · not public`,
      planned: false,
      preview: true,
    } as const;
  });
}

export function absoluteUrl(path: string): string {
  return new URL(path, siteConfig.origin).toString();
}

export const socialImage = {
  url: absoluteUrl("/social/pyble-beta-og-277eee8a-1200x630.png"),
  width: 1200,
  height: 630,
  alt: "Actual PyBLE iPad app showing GPIO 48 NeoPixel Blocks and generated MicroPython code",
} as const;

export function pageMetadata({
  title,
  description,
  path,
}: {
  title: string;
  description: string;
  path: string;
}): Metadata {
  const url = absoluteUrl(path);

  return {
    title,
    description,
    alternates: {
      canonical: url,
    },
    openGraph: {
      type: "website",
      siteName: siteConfig.name,
      title,
      description,
      url,
      images: [{ ...socialImage }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [socialImage.url],
    },
  };
}
