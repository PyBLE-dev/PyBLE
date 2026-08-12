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
    planned: false,
  },
  {
    id: "esp32-s3-n16r8",
    target: "ESP32-S3 N16R8",
    constraint: "16 MiB flash · 8 MiB Octal PSRAM",
    planned: false,
  },
  {
    id: "waveshare-esp32-s3-lcd-147b",
    target: "Waveshare ESP32-S3-LCD-1.47B",
    constraint: "Exact B version · 16 MiB flash · 8 MiB Octal PSRAM",
    planned: false,
  },
  {
    id: "esp32-c3-4mb",
    target: "ESP32-C3",
    constraint: "4 MiB external SPI flash · no PSRAM assumed",
    planned: true,
  },
] as const;

export function firmwareTargetsForRelease(
  release: FirmwareReleaseDescriptor | null,
) {
  const includesWaveshareLcd147b = releaseIncludesWaveshareLcd147b(release);
  const hasProspectiveProfileSet = Boolean(
    release &&
    release.deployment === "candidate" &&
    hasExactFirmwareProfileDescriptors(release.version, release.profiles),
  );

  return firmwareTargetDefinitions
    .filter(
      (target) =>
        target.id !== "waveshare-esp32-s3-lcd-147b" ||
        includesWaveshareLcd147b ||
        hasProspectiveProfileSet,
    )
    .map((target) => {
      let status = "Installer unavailable";
      if (target.planned) {
        status = "Planned · installer unavailable pending exact-profile HIL";
      } else if (release?.deployment === "public-beta") {
        status = `v${release.version} hardware-tested beta · browser install/recovery passed · release qualification pending`;
      } else if (release && includesWaveshareLcd147b) {
        status = `v${release.version} qualified public release`;
      } else if (release?.deployment === "candidate") {
        status = `v${release.version} protected candidate · HIL pending`;
      }
      const targetName =
        includesWaveshareLcd147b && target.id === "esp32-s3-n16r8"
          ? `${target.target} · lean generic`
          : target.target;
      return { ...target, target: targetName, status };
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
