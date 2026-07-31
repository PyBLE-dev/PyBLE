// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import "@/app/globals.css";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { siteConfig, socialImage } from "@/lib/site";

export const metadata: Metadata = {
  metadataBase: new URL(siteConfig.origin),
  title: {
    default: "PyBLE — Python over Bluetooth Low Energy",
    template: "%s — PyBLE",
  },
  description: siteConfig.description,
  applicationName: siteConfig.name,
  authors: [{ name: "PyBLE contributors" }],
  creator: "PyBLE contributors",
  publisher: "PyBLE contributors",
  category: "developer tools",
  keywords: [
    "PyBLE",
    "MicroPython",
    "MicroPython boards",
    "ESP32",
    "Bluetooth Low Energy",
    "Bluetooth microcontrollers",
    "BLE",
    "embedded Python",
    "Python IDE",
    "Blockly",
    "iPad",
    "Android",
  ],
  alternates: {
    canonical: siteConfig.origin,
  },
  icons: {
    icon: [
      {
        url: "/brand/pyble-prompt-chip.svg",
        type: "image/svg+xml",
      },
      {
        url: "/brand/pyble-prompt-chip-512.png",
        type: "image/png",
        sizes: "512x512",
      },
    ],
    apple: [
      {
        url: "/brand/pyble-prompt-chip-512.png",
        sizes: "512x512",
        type: "image/png",
      },
    ],
  },
  manifest: "/manifest.webmanifest",
  openGraph: {
    type: "website",
    locale: "en",
    url: siteConfig.origin,
    siteName: siteConfig.name,
    title: "PyBLE — Python over Bluetooth Low Energy",
    description: siteConfig.description,
    images: [{ ...socialImage }],
  },
  twitter: {
    card: "summary_large_image",
    title: "PyBLE — Python over Bluetooth Low Energy",
    description: siteConfig.description,
    images: [socialImage.url],
  },
};

export const viewport: Viewport = {
  colorScheme: "light",
  themeColor: "#081B35",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <SiteHeader />
        {children}
        <SiteFooter />
      </body>
    </html>
  );
}
