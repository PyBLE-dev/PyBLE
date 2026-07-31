// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import type { Metadata } from "next";

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

export const initialFirmwareTargets = [
  {
    id: "esp32-4mb",
    target: "Classic ESP32",
    constraint: "4 MiB external SPI flash · no PSRAM assumed",
    status: "v0.4.2 HIL pending · installer unavailable",
    planned: false,
  },
  {
    id: "esp32-s3-n16r8",
    target: "ESP32-S3 N16R8",
    constraint: "16 MiB flash · 8 MiB Octal PSRAM",
    status: "v0.4.2 HIL pending · installer unavailable",
    planned: false,
  },
  {
    id: "esp32-c3-4mb",
    target: "ESP32-C3",
    constraint: "4 MiB external SPI flash · no PSRAM assumed",
    status: "Planned · installer unavailable pending exact-profile HIL",
    planned: true,
  },
] as const;

export function absoluteUrl(path: string): string {
  return new URL(path, siteConfig.origin).toString();
}

export const socialImage = {
  url: absoluteUrl("/social/pyble-beta-og-7e7e037d-1200x630.png"),
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
