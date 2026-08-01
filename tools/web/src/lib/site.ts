// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import type { Metadata } from "next";

import type { FirmwareReleaseDescriptor } from "@/lib/firmware-release";

export const siteConfig = {
  name: "PyBLE",
  expandedName: "Python over Bluetooth Low Energy",
  origin: "https://pyble.dev",
  alternateOrigin: "https://pyble.org",
  description:
    "A free, open-source, tablet-first IDE for MicroPython boards with compatible Bluetooth Low Energy agent firmware.",
  supportEmail: "viwat.v@chula.ac.th",
  testFlightUrl: "https://testflight.apple.com/join/yU4e8s6d",
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
    id: "esp32-c3-4mb",
    target: "ESP32-C3",
    constraint: "4 MiB external SPI flash · no PSRAM assumed",
    planned: true,
  },
] as const;

export function firmwareTargetsForRelease(
  release: FirmwareReleaseDescriptor | null,
) {
  return firmwareTargetDefinitions.map((target) => {
    let status = "Installer unavailable";
    if (target.planned) {
      status = "Planned · installer unavailable pending exact-profile HIL";
    } else if (release?.deployment === "public-beta") {
      status = `v${release.version} hardware-tested beta · browser install/recovery passed · release qualification pending`;
    } else if (
      release?.deployment === "public" &&
      release.hilStatus === "passed"
    ) {
      status = `v${release.version} qualified public release`;
    } else if (release?.deployment === "candidate") {
      status = `v${release.version} protected candidate · HIL pending`;
    }
    return { ...target, status };
  });
}

export const initialFirmwareTargets = firmwareTargetsForRelease(null);

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
