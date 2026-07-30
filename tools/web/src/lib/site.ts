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
} as const;

export const navigation = [
  { label: "What it does", href: "/#features" },
  { label: "Blocks", href: "/#blocks" },
  { label: "Firmware", href: "/flash" },
  { label: "Support", href: "/support" },
] as const;

export const initialFirmwareTargets = [
  { name: "ESP32", availability: "Released profile" },
  { name: "ESP32-S3", availability: "Released profile" },
  { name: "ESP32-C3", availability: "Planned profile" },
] as const;

export function absoluteUrl(path: string): string {
  return new URL(path, siteConfig.origin).toString();
}

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
      images: [
        {
          url: absoluteUrl("/brand/pyble-prompt-chip-master.png"),
          width: 1024,
          height: 1024,
          alt: "PyBLE Prompt Chip mark",
        },
      ],
    },
    twitter: {
      card: "summary",
      title,
      description,
      images: [absoluteUrl("/brand/pyble-prompt-chip-master.png")],
    },
  };
}
