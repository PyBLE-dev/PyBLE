// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AppPage, { metadata as appMetadata } from "@/app/app/page";
import FlashPage, { metadata as flashMetadata } from "@/app/flash/page";
import { metadata as rootMetadata } from "@/app/layout";
import HomePage, { metadata as homeMetadata } from "@/app/page";
import PrivacyPage, { metadata as privacyMetadata } from "@/app/privacy/page";
import SupportPage, { metadata as supportMetadata } from "@/app/support/page";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import {
  firmwareTargetsForRelease,
  initialFirmwareTargets,
  navigation,
  siteConfig,
} from "@/lib/site";
import type { FirmwareReleaseDescriptor } from "@/lib/firmware-release";
import * as firmwareSelection from "@/lib/firmware-release-selection";
import { localFirmwareProfileTable } from "@/lib/local-firmware-preview";
import {
  currentPendingCandidateFirmwareRelease,
  hypotheticalPassedPublicFirmwareRelease,
  publicBetaFirmwareRelease,
} from "@/test/fixtures/firmware-release";
import { localFiveTargetPreview } from "@/test/fixtures/local-firmware-preview";

function hypotheticalQualifiedReleaseAtVersion(
  version: string,
): FirmwareReleaseDescriptor {
  const release = structuredClone(
    hypotheticalPassedPublicFirmwareRelease,
  ) as unknown as {
    version: string;
    builtAt: string;
    releaseJson: { path: string };
    schemaPath: string;
    recoveryPath: string;
    profiles: Array<{ manifestPath: string; firmwarePath: string }>;
  };
  release.version = version;
  release.builtAt = "2026-08-02T00:00:00Z";
  release.releaseJson.path = `/firmware/v${version}/release.json`;
  release.schemaPath = `/firmware/v${version}/release.schema.json`;
  release.recoveryPath = `/firmware/v${version}/RECOVERY.md`;
  for (const profile of release.profiles) {
    profile.manifestPath = profile.manifestPath.replace(
      "/firmware/v0.5.1/",
      `/firmware/v${version}/`,
    );
    profile.firmwarePath = profile.firmwarePath.replace(
      "/firmware/v0.5.1/",
      `/firmware/v${version}/`,
    );
  }
  return release as unknown as FirmwareReleaseDescriptor;
}

function jpegDimensions(bytes: Buffer): { width: number; height: number } {
  if (bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== 0xd8) {
    throw new Error("not a JPEG");
  }
  const startOfFrame = new Set([
    0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce,
    0xcf,
  ]);
  let offset = 2;
  while (offset + 8 < bytes.length) {
    if (bytes[offset] !== 0xff) {
      throw new Error("invalid JPEG marker");
    }
    while (bytes[offset] === 0xff) {
      offset += 1;
    }
    const marker = bytes[offset];
    offset += 1;
    if (marker === undefined || marker === 0xd9 || marker === 0xda) {
      break;
    }
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) {
      continue;
    }
    const length = bytes.readUInt16BE(offset);
    if (length < 2 || offset + length > bytes.length) {
      throw new Error("invalid JPEG segment");
    }
    if (startOfFrame.has(marker)) {
      return {
        height: bytes.readUInt16BE(offset + 3),
        width: bytes.readUInt16BE(offset + 5),
      };
    }
    offset += length;
  }
  throw new Error("JPEG dimensions are missing");
}

describe("public-site contract", () => {
  it("keeps pyble.dev canonical and presents the four launch routes", () => {
    expect(siteConfig.origin).toBe("https://pyble.dev");
    expect(siteConfig.alternateOrigin).toBe("https://pyble.org");
    expect(navigation.map((item) => item.href)).toEqual([
      "/#features",
      "/#blocks",
      "/flash",
      "/support",
    ]);
  });

  it("publishes canonical metadata and static discovery files", async () => {
    expect(siteConfig.description).toBe(
      "A free, open-source, tablet-first IDE for MicroPython boards with compatible Bluetooth Low Energy agent firmware.",
    );
    expect(homeMetadata.title).toEqual({
      absolute: "PyBLE — Python over Bluetooth Low Energy",
    });
    expect(homeMetadata.alternates).toEqual({ canonical: "https://pyble.dev" });
    expect(appMetadata.alternates).toEqual({
      canonical: "https://pyble.dev/app",
    });
    expect(appMetadata.title).toBe("PyBLE for iPad and Android");
    expect(appMetadata.description).toMatch(
      /ipad external beta.*android internal test/i,
    );
    expect(privacyMetadata.alternates).toEqual({
      canonical: "https://pyble.dev/privacy",
    });
    expect(privacyMetadata.title).toBe("PyBLE Privacy Policy");
    expect(supportMetadata.alternates).toEqual({
      canonical: "https://pyble.dev/support",
    });
    expect(flashMetadata.alternates).toEqual({
      canonical: "https://pyble.dev/flash",
    });

    const publicDirectory = join(process.cwd(), "public");
    const robots = await readFile(join(publicDirectory, "robots.txt"), "utf8");
    const sitemap = await readFile(
      join(publicDirectory, "sitemap.xml"),
      "utf8",
    );
    const manifest = JSON.parse(
      await readFile(join(publicDirectory, "manifest.webmanifest"), "utf8"),
    ) as Record<string, unknown>;

    expect(
      Array.from(sitemap.matchAll(/<loc>([^<]+)<\/loc>/g), (match) => match[1]),
    ).toEqual([
      "https://pyble.dev/",
      "https://pyble.dev/app",
      "https://pyble.dev/privacy",
      "https://pyble.dev/support",
      "https://pyble.dev/flash",
    ]);
    expect(sitemap).toMatch(
      /<loc>https:\/\/pyble\.dev\/privacy<\/loc>\s*<lastmod>2026-08-07T00:00:00\.000Z<\/lastmod>/,
    );
    expect(sitemap).toMatch(
      /<loc>https:\/\/pyble\.dev\/<\/loc>\s*<lastmod>2026-08-12T00:00:00\.000Z<\/lastmod>/,
    );
    expect(sitemap).toMatch(
      /<loc>https:\/\/pyble\.dev\/app<\/loc>\s*<lastmod>2026-08-07T00:00:00\.000Z<\/lastmod>/,
    );
    expect(robots).toContain("Host: https://pyble.dev");
    expect(robots).toContain("Sitemap: https://pyble.dev/sitemap.xml");
    expect(manifest).toMatchObject({
      short_name: "PyBLE",
      description:
        "A free, open-source, tablet-first IDE for MicroPython boards with compatible Bluetooth Low Energy agent firmware.",
      start_url: "/",
      theme_color: "#081B35",
    });
  });

  it("publishes a real-app large social card and local TestFlight card", async () => {
    const socialPngName = "pyble-beta-og-277eee8a-1200x630.png";
    const socialSvgName = "pyble-beta-og-b47b6d10-1200x630.svg";
    const socialUrl = `https://pyble.dev/social/${socialPngName}`;
    expect(rootMetadata.openGraph?.images).toEqual([
      {
        url: socialUrl,
        width: 1200,
        height: 630,
        alt: "Actual PyBLE iPad app showing GPIO 48 NeoPixel Blocks and generated MicroPython code",
      },
    ]);
    expect(rootMetadata.twitter).toMatchObject({
      card: "summary_large_image",
      images: [socialUrl],
    });
    expect(supportMetadata.openGraph?.images).toEqual(
      rootMetadata.openGraph?.images,
    );
    expect(supportMetadata.twitter).toMatchObject({
      card: "summary_large_image",
      images: [socialUrl],
    });

    const publicDirectory = join(process.cwd(), "public");
    const [socialPng, socialSvg, qrCardPng, qrCardSvg] = await Promise.all([
      readFile(join(publicDirectory, "social", socialPngName)),
      readFile(join(publicDirectory, "social", socialSvgName), "utf8"),
      readFile(join(publicDirectory, "social", "pyble-testflight-qr-1080.png")),
      readFile(
        join(publicDirectory, "social", "pyble-testflight-qr-1080.svg"),
        "utf8",
      ),
    ]);
    expect([socialPng.readUInt32BE(16), socialPng.readUInt32BE(20)]).toEqual([
      1200, 630,
    ]);
    expect(socialSvg).toContain("One-time USB setup.");
    expect(socialSvg).toContain("Everyday coding over BLE.");
    expect(socialSvg).toContain("WEB FLASHING VALIDATED");
    expect(socialSvg).not.toContain("FIRMWARE HIL PENDING");
    const socialPngSha256 = createHash("sha256")
      .update(socialPng)
      .digest("hex");
    const socialSvgSha256 = createHash("sha256")
      .update(socialSvg)
      .digest("hex");
    expect(socialPngSha256).toBe(
      "277eee8ae859c3e26444df830cf1b03f624f2be1f1524bc3246ce2d946332023",
    );
    expect(socialSvgSha256).toBe(
      "b47b6d10d6de3e16a5687680d8f34f115f9a276d0fdbde06051751de2270ddfd",
    );
    expect(socialPngName).toContain(socialPngSha256.slice(0, 8));
    expect(socialSvgName).toContain(socialSvgSha256.slice(0, 8));
    expect([qrCardPng.readUInt32BE(16), qrCardPng.readUInt32BE(20)]).toEqual([
      1080, 1080,
    ]);
    expect(qrCardSvg).toContain("testflight.apple.com/join/yU4e8s6d");
    expect(qrCardSvg).not.toMatch(/https?:\/\/[^<]*\.(?:png|svg|jpg)/i);
  });

  it("exposes accessible primary navigation", () => {
    render(<SiteHeader />);

    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(
      within(nav).getByRole("link", { name: "What it does" }),
    ).toHaveAttribute("href", "/#features");
    expect(within(nav).getByRole("link", { name: "Blocks" })).toHaveAttribute(
      "href",
      "/#blocks",
    );
    expect(within(nav).getByRole("link", { name: "Firmware" })).toHaveAttribute(
      "href",
      "/flash",
    );
    expect(within(nav).getByRole("link", { name: "Support" })).toHaveAttribute(
      "href",
      "/support",
    );
    expect(screen.getByRole("link", { name: "Get PyBLE" })).toHaveAttribute(
      "href",
      "/app",
    );
  });

  it("states the vendor-neutral vision without claiming unavailable firmware is active", () => {
    render(<HomePage />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Code your MicroPython board. Leave the cable behind.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /designed for boards that run MicroPython and support Bluetooth Low Energy/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(/firmware installer is currently unavailable/i),
    ).toHaveLength(1);
    expect(
      screen.queryByText(/unqualified firmware beta is available/i),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/ESP32-C3 and Raspberry Pi Pico 2 W/i),
    ).toHaveTextContent(
      /engineering validation.*unavailable in the public installer/i,
    );
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: "MicroPython + Bluetooth, not one chip family.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Public firmware availability"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/a validated PyBLE agent port is still required/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Python over Bluetooth Low Energy"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("iPad external beta + Android internal test"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: "Install PyBLE on iPad or Android",
      }),
    ).toHaveAttribute("href", "/app");
    expect(
      screen.queryByText(/available on the app store/i),
    ).not.toBeInTheDocument();
  });

  it("summarizes the exact five-target local preview without changing public support claims", () => {
    const preview = localFiveTargetPreview();
    const previewSelection = vi
      .spyOn(firmwareSelection, "localFirmwarePreviewSelectedAtBuild")
      .mockReturnValue(preview);

    try {
      render(<HomePage />);

      expect(screen.getByRole("main")).toHaveTextContent(
        /LOCAL ENGINEERING PREVIEW v0\.6\.0 — UNQUALIFIED/i,
      );
      expect(screen.getByRole("main")).toHaveTextContent(
        /not a public release or support claim/i,
      );
      expect(
        screen.getByRole("link", {
          name: /review five-target firmware preview/i,
        }),
      ).toHaveAttribute("href", "/flash");

      const targetGrid = screen.getByLabelText(
        "Five exact v0.6.0 engineering targets",
      );
      const cards = Array.from(
        targetGrid.querySelectorAll<HTMLElement>(".target-grid__target"),
      );
      expect(
        cards.map((card) => card.querySelector("strong")?.textContent),
      ).toEqual(preview.profiles.map(({ id }) => id));
      for (const [index, definition] of localFirmwareProfileTable.entries()) {
        expect(cards[index]).toHaveTextContent(definition.requirements);
        expect(cards[index]).toHaveTextContent(
          definition.method === "esp-web-tools"
            ? "ESP Web Serial"
            : "UF2 / BOOTSEL",
        );
        expect(cards[index]).toHaveTextContent(
          "v0.6.0 local engineering preview · unqualified · not public",
        );
      }

      expect(screen.getByRole("main")).not.toHaveTextContent(
        /firmware installer is currently unavailable/i,
      );
      expect(screen.getByRole("main")).not.toHaveTextContent(
        /ESP32-C3.*planned/i,
      );
      expect(screen.getByRole("main")).not.toHaveTextContent(
        /v0\.4\.2|v0\.5\.1|hardware-tested firmware beta|qualified public firmware/i,
      );
      expect(
        screen.queryByRole("img", {
          name: /actual waveshare esp32-s3-lcd-1\.47b/i,
        }),
      ).not.toBeInTheDocument();

      const previewStep = screen.getByText("Provision once").closest("li");
      expect(previewStep).toHaveTextContent(
        /four ESP targets.*Web Serial.*Pico 2 W.*UF2.*BOOTSEL/i,
      );
      expect(previewStep).toHaveTextContent(/unqualified/i);

      expect(
        screen.getByText(/explicit numeric or named GPIO pins/i),
      ).toHaveTextContent(/Pin\("LED"\)/i);
    } finally {
      previewSelection.mockRestore();
    }
  });

  it("publishes the canonical MIT source repository from the home page and global footer", () => {
    const repositoryUrl = "https://github.com/PyBLE-dev/PyBLE";

    expect(siteConfig.repositoryUrl).toBe(repositoryUrl);

    render(
      <>
        <HomePage />
        <SiteFooter />
      </>,
    );

    const sourceSection = screen.getByRole("region", {
      name: "See how PyBLE is built.",
    });
    expect(
      within(sourceSection).getByText(
        /tablet app, board-agent firmware, PBLE\/1 protocol, tests, and documentation/i,
      ),
    ).toHaveTextContent(/developed in public under the MIT license/i);

    const sourceLink = within(sourceSection).getByRole("link", {
      name: "Explore PyBLE on GitHub",
    });
    expect(sourceLink).toHaveAttribute("href", repositoryUrl);
    expect(sourceLink).toHaveAttribute("target", "_blank");
    expect(sourceLink).toHaveAttribute("rel", "noopener noreferrer");

    const footer = screen.getByRole("navigation", { name: "Footer" });
    const footerLink = within(footer).getByRole("link", { name: "GitHub" });
    expect(footerLink).toHaveAttribute("href", repositoryUrl);
    expect(footerLink).toHaveAttribute("target", "_blank");
    expect(footerLink).toHaveAttribute("rel", "noopener noreferrer");
    expect(
      screen.getByText(/independent MIT-licensed project/i),
    ).toHaveTextContent(/maintained under the SciLabPro project name/i);
  });

  it("publishes the approved iPad and Android testing links with verified local QR codes", async () => {
    const testFlightUrl = "https://testflight.apple.com/join/yU4e8s6d";
    const googlePlayUrl =
      "https://play.google.com/store/apps/details?id=dev.pyble.pyble";

    render(<HomePage />);

    const channelGroup = screen.getByRole("region", {
      name: "Choose your tablet beta.",
    });
    const testFlightSection = screen.getByRole("region", {
      name: "Join the PyBLE beta on TestFlight.",
    });
    expect(
      within(testFlightSection).getByText(/external testing is open/i),
    ).toBeInTheDocument();
    expect(testFlightSection).toHaveTextContent(
      /firmware availability and qualification depend on the exact target.*check the firmware installer/i,
    );
    expect(testFlightSection).not.toHaveTextContent(
      /ESP32-C3 is unavailable|v0\.4\.2|v0\.5\.1/i,
    );

    const androidSection = screen.getByRole("region", {
      name: "Join the PyBLE Android internal test.",
    });
    expect(channelGroup).toContainElement(testFlightSection);
    expect(channelGroup).toContainElement(androidSection);
    expect(testFlightSection.parentElement).toBe(androidSection.parentElement);
    expect(testFlightSection.parentElement).toHaveClass("beta-channel-grid");
    expect(testFlightSection.nextElementSibling).toBe(androidSection);
    expect(
      within(androidSection).getByText(/approved internal testers/i),
    ).toBeInTheDocument();
    expect(
      within(androidSection).getByText(/not a public Google Play release/i),
    ).toBeInTheDocument();
    expect(
      within(androidSection).getByText(/unapproved.*may.*unavailable/i),
    ).toBeInTheDocument();

    const testFlightLink = within(testFlightSection).getByRole("link", {
      name: "Open in TestFlight",
    });
    expect(testFlightLink).toHaveAttribute("href", testFlightUrl);
    expect(testFlightLink).toHaveAttribute("target", "_blank");
    expect(testFlightLink).toHaveAttribute("rel", "noopener noreferrer");

    const googlePlayLink = within(androidSection).getByRole("link", {
      name: "Open Android internal test",
    });
    expect(googlePlayLink).toHaveAttribute("href", googlePlayUrl);
    expect(googlePlayLink).toHaveAttribute("target", "_blank");
    expect(googlePlayLink).toHaveAttribute("rel", "noopener noreferrer");

    const testFlightQrDescription =
      "QR code for the PyBLE beta on Apple TestFlight";
    const testFlightQrLink = within(testFlightSection).getByRole("link", {
      name: testFlightQrDescription,
    });
    expect(testFlightQrLink).toHaveAttribute("href", testFlightUrl);
    expect(testFlightQrLink).toHaveAttribute("target", "_blank");
    expect(testFlightQrLink).toHaveAttribute("rel", "noopener noreferrer");
    expect(
      within(testFlightSection).getByRole("img", {
        name: testFlightQrDescription,
      }),
    ).toHaveAttribute("src", "/testflight/pyble-testflight-qr.svg");

    const googlePlayQrDescription =
      "QR code for the PyBLE Android internal test on Google Play";
    const googlePlayQrLink = within(androidSection).getByRole("link", {
      name: googlePlayQrDescription,
    });
    expect(googlePlayQrLink).toHaveAttribute("href", googlePlayUrl);
    expect(googlePlayQrLink).toHaveAttribute("target", "_blank");
    expect(googlePlayQrLink).toHaveAttribute("rel", "noopener noreferrer");
    expect(
      within(androidSection).getByRole("img", {
        name: googlePlayQrDescription,
      }),
    ).toHaveAttribute(
      "src",
      "/google-play/pyble-google-play-internal-test-qr.svg",
    );

    expect(
      within(testFlightSection).getByText("testflight.apple.com/join/yU4e8s6d"),
    ).toBeInTheDocument();
    expect(within(androidSection).getByText(googlePlayUrl)).toBeInTheDocument();

    expect(
      screen.getByRole("link", {
        name: "Install PyBLE on iPad or Android",
      }),
    ).toHaveAttribute("href", "/app");
    expect(
      screen.queryByText(/preparing for public (?:beta|testing)/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/available on the app store/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/^available on google play$/i),
    ).not.toBeInTheDocument();

    const qrAssets = [
      {
        path: join(
          process.cwd(),
          "public",
          "testflight",
          "pyble-testflight-qr.svg",
        ),
        sha256:
          "4ab6c814a8526c4d69a3b330dc563298edf5bf7eadbea4babd262fa75568e305",
      },
      {
        path: join(
          process.cwd(),
          "public",
          "google-play",
          "pyble-google-play-internal-test-qr.svg",
        ),
        sha256:
          "fbd84d11d773346d0a2cd23f0e3193d02ff02e6c9780298294431d95dd07f32d",
      },
    ];
    for (const expected of qrAssets) {
      const qrAsset = await readFile(expected.path);
      expect(createHash("sha256").update(qrAsset).digest("hex")).toBe(
        expected.sha256,
      );
      expect(qrAsset.toString("utf8")).not.toMatch(
        /<(?:script|image)\b|(?:href|xlink:href)=/i,
      );
    }
  });

  it("publishes both testing channels and support paths on the canonical app route", () => {
    render(<AppPage />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /install pyble.*ipad.*android/i,
      }),
    ).toBeInTheDocument();

    expect(siteConfig.testFlightUrl).toBe(
      "https://testflight.apple.com/join/yU4e8s6d",
    );
    expect(siteConfig.googlePlayInternalTestUrl).toBe(
      "https://play.google.com/store/apps/details?id=dev.pyble.pyble",
    );

    const testFlightLink = screen.getByRole("link", {
      name: "Open PyBLE in TestFlight",
    });
    expect(testFlightLink).toHaveAttribute("href", siteConfig.testFlightUrl);
    expect(testFlightLink).toHaveAttribute("target", "_blank");
    expect(testFlightLink).toHaveAttribute("rel", "noopener noreferrer");

    const googlePlayLink = screen.getByRole("link", {
      name: "Open Android internal test",
    });
    expect(googlePlayLink).toHaveAttribute(
      "href",
      siteConfig.googlePlayInternalTestUrl,
    );
    expect(googlePlayLink).toHaveAttribute("target", "_blank");
    expect(googlePlayLink).toHaveAttribute("rel", "noopener noreferrer");

    expect(
      screen.getByRole("img", {
        name: "QR code for the PyBLE beta on Apple TestFlight",
      }),
    ).toHaveAttribute("src", "/testflight/pyble-testflight-qr.svg");
    expect(
      screen.getByText(siteConfig.testFlightUrl, {
        selector: ".app-install__direct span",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: "QR code for the PyBLE Android internal test on Google Play",
      }),
    ).toHaveAttribute(
      "src",
      "/google-play/pyble-google-play-internal-test-qr.svg",
    );
    expect(
      screen.getByText(siteConfig.googlePlayInternalTestUrl, {
        selector: ".app-install__direct span",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/approved internal testers/i)).toBeInTheDocument();
    expect(
      screen.getByText(/not a public Google Play release/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/unapproved.*may.*unavailable/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /open firmware installer/i }),
    ).toHaveAttribute("href", "/flash");
    expect(
      screen.getByRole("link", { name: /(?:get|contact|open) support/i }),
    ).toHaveAttribute("href", "/support");
  });

  it("shows a reviewed capture of the actual app instead of a fabricated hero UI", async () => {
    render(<HomePage />);

    expect(
      screen.getByRole("img", {
        name: "Actual PyBLE app showing a GPIO 48 NeoPixel Blocks program beside its generated Python",
      }),
    ).toHaveAttribute("src", "/app/pyble-neopixel-gpio48-ipad-raw.png");
    expect(
      screen.getByText("NeoPixel Blocks · GPIO 48 · Generated Python"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("img", {
        name: /illustration of pyble editing and running/i,
      }),
    ).not.toBeInTheDocument();

    const capture = await readFile(
      join(
        process.cwd(),
        "public",
        "app",
        "pyble-neopixel-gpio48-ipad-raw.png",
      ),
    );
    expect(capture.subarray(0, 8)).toEqual(
      Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    );
    expect(capture.readUInt32BE(16)).toBe(2048);
    expect(capture.readUInt32BE(20)).toBe(2732);
  });

  it("names every exact profile, memory constraint, and qualification state", () => {
    expect(initialFirmwareTargets).toEqual([
      {
        id: "esp32-4mb",
        target: "Classic ESP32",
        constraint: "4 MiB external SPI flash · no PSRAM assumed",
        status: "Installer unavailable",
        planned: false,
      },
      {
        id: "esp32-s3-n16r8",
        target: "ESP32-S3 N16R8",
        constraint: "16 MiB flash · 8 MiB Octal PSRAM",
        status: "Installer unavailable",
        planned: false,
      },
      {
        id: "esp32-c3-4mb",
        target: "ESP32-C3",
        constraint: "4 MiB external SPI flash · no PSRAM assumed",
        status: "Planned · installer unavailable pending exact-profile HIL",
        planned: true,
      },
    ]);
    expect(
      firmwareTargetsForRelease(publicBetaFirmwareRelease)
        .filter(({ planned }) => !planned)
        .map(({ status }) => status),
    ).toEqual([
      "v0.4.2 hardware-tested beta · browser install/recovery passed · release qualification pending",
      "v0.4.2 hardware-tested beta · browser install/recovery passed · release qualification pending",
    ]);
    expect(
      firmwareTargetsForRelease(currentPendingCandidateFirmwareRelease)
        .filter(({ planned }) => !planned)
        .map(({ status }) => status),
    ).toEqual([
      "v0.5.1 protected candidate · HIL pending",
      "v0.5.1 protected candidate · HIL pending",
      "v0.5.1 protected candidate · HIL pending",
    ]);
    expect(
      firmwareTargetsForRelease(hypotheticalPassedPublicFirmwareRelease)
        .filter(({ planned }) => !planned)
        .map(({ status }) => status),
    ).toEqual([
      "v0.5.1 qualified public release",
      "v0.5.1 qualified public release",
      "v0.5.1 qualified public release",
    ]);

    render(<HomePage />);

    for (const target of initialFirmwareTargets) {
      const targetCard = screen.getByText(target.id).closest("div");
      expect(targetCard).toHaveTextContent(target.target);
      expect(targetCard).toHaveTextContent(target.constraint);
      expect(targetCard).toHaveTextContent(target.status);
    }
    expect(screen.getByText(/provision once/i).closest("li")).toHaveTextContent(
      /check firmware status.*installer is currently unavailable/i,
    );
    expect(
      screen.getByRole("link", { name: /open firmware installer/i }),
    ).toHaveAttribute("href", "/flash");
    expect(
      screen.queryByRole("img", {
        name: /actual waveshare esp32-s3-lcd-1\.47b/i,
      }),
    ).not.toBeInTheDocument();
  });

  it("defines future-qualified v0.5.1 Waveshare copy without claiming it is current", async () => {
    const selectionRoot = await mkdtemp(
      join(tmpdir(), "pyble-site-waveshare-selection-"),
    );
    const selectionFile = join(selectionRoot, "selection.json");
    const previousSelection = process.env.PYBLE_FLASH_SELECTION_FILE;
    process.env.PYBLE_FLASH_SELECTION_FILE = selectionFile;

    try {
      await writeFile(
        selectionFile,
        JSON.stringify(hypotheticalQualifiedReleaseAtVersion("0.5.1")),
        "utf8",
      );
      const home = render(<HomePage />);

      const s3Target = screen.getByText("esp32-s3-n16r8").closest("div");
      expect(s3Target).toHaveTextContent(/lean generic/i);
      expect(s3Target).toHaveTextContent(/16 MiB flash.*8 MiB Octal PSRAM/i);
      expect(s3Target).not.toHaveTextContent(/Waveshare ESP32-S3-LCD-1\.47B/i);
      const exactTarget = screen
        .getByText("waveshare-esp32-s3-lcd-147b")
        .closest("div");
      expect(exactTarget).toHaveTextContent(/Waveshare ESP32-S3-LCD-1\.47B/i);
      expect(exactTarget).toHaveTextContent(
        /exact B version.*16 MiB flash.*8 MiB Octal PSRAM/i,
      );
      expect(
        screen.getByText(/qualified public v0\.5\.1 firmware/i),
      ).toHaveTextContent(
        /esp32-4mb.*lean generic esp32-s3-n16r8.*separate waveshare-esp32-s3-lcd-147b/i,
      );
      expect(
        screen.getByText(
          /build offline with eight editable beginner examples/i,
        ),
      ).toHaveTextContent(/explicit TFT display example/i);
      expect(
        screen.getByText("Qualified public firmware targets"),
      ).toBeInTheDocument();
      expect(
        screen.getByLabelText("Qualified public firmware targets"),
      ).toBeInTheDocument();
      expect(
        screen.queryByText("Initial beta firmware targets"),
      ).not.toBeInTheDocument();
      const boardPhoto = screen.getByRole("img", {
        name: "Actual Waveshare ESP32-S3-LCD-1.47B displaying the PyBLE v0.5.0 boot splash and app QR",
      });
      expect(boardPhoto).toHaveAttribute(
        "src",
        "/boards/esp32-s3-lcd-1.47b-pyble-v0.5.0.jpg",
      );
      const boardFigure = boardPhoto.closest("figure");
      expect(boardFigure).toHaveTextContent(
        /Actual board.*PyBLE firmware v0\.5\.0/i,
      );
      expect(
        within(boardFigure!).getByRole("link", {
          name: /open this board's installer/i,
        }),
      ).toHaveAttribute("href", "/flash");

      const photoBytes = await readFile(
        join(
          process.cwd(),
          "public",
          "boards",
          "esp32-s3-lcd-1.47b-pyble-v0.5.0.jpg",
        ),
      );
      expect(photoBytes.length).toBe(195079);
      expect(photoBytes.length).toBeLessThanOrEqual(250000);
      expect(photoBytes.subarray(0, 3)).toEqual(
        Buffer.from([0xff, 0xd8, 0xff]),
      );
      expect(jpegDimensions(photoBytes)).toEqual({ width: 1600, height: 1116 });
      expect(createHash("sha256").update(photoBytes).digest("hex")).toBe(
        "b939abb9b7ac19c7be8f429faaa61d08aadc7f027eac181582e036fd22949d12",
      );
      expect(photoBytes.includes(Buffer.from("Exif\0\0", "binary"))).toBe(
        false,
      );

      home.unmount();
      render(<SupportPage />);
      expect(
        screen.getByText(/qualified v0\.5\.1 firmware is available/i),
      ).toHaveTextContent(
        /three exact profiles.*lean generic esp32-s3-n16r8.*separate waveshare-esp32-s3-lcd-147b/i,
      );
    } finally {
      if (previousSelection === undefined) {
        delete process.env.PYBLE_FLASH_SELECTION_FILE;
      } else {
        process.env.PYBLE_FLASH_SELECTION_FILE = previousSelection;
      }
      await rm(selectionRoot, { recursive: true, force: true });
    }
  });

  it("shows the scoped hardware-tested beta claims only when its build selector is active", async () => {
    const selectionRoot = await mkdtemp(
      join(tmpdir(), "pyble-site-beta-selection-"),
    );
    const selectionFile = join(selectionRoot, "selection.json");
    await writeFile(
      selectionFile,
      JSON.stringify(publicBetaFirmwareRelease),
      "utf8",
    );
    const previousSelection = process.env.PYBLE_FLASH_SELECTION_FILE;
    process.env.PYBLE_FLASH_SELECTION_FILE = selectionFile;

    try {
      const home = render(<HomePage />);
      expect(screen.getByText(/public v0\.4\.2 firmware/i)).toHaveTextContent(
        /hardware-tested beta for the exact esp32-4mb and esp32-s3-n16r8 profiles/i,
      );
      expect(screen.getByText(/public v0\.4\.2 firmware/i)).toHaveTextContent(
        /production chrome install.*interrupted-flash recovery passed on both exact profiles.*complete release qualification continues/i,
      );
      for (const target of firmwareTargetsForRelease(
        publicBetaFirmwareRelease,
      ).filter(({ planned }) => !planned)) {
        expect(screen.getByText(target.id).closest("div")).toHaveTextContent(
          "v0.4.2 hardware-tested beta · browser install/recovery passed · release qualification pending",
        );
      }
      home.unmount();

      render(<SupportPage />);
      expect(
        screen.getByText(/v0\.4\.2 hardware-tested beta is available/i),
      ).toHaveTextContent(
        /production chrome install.*interrupted-flash recovery passed on both exact profiles.*complete release qualification continues/i,
      );
      expect(screen.queryByText(/full HIL pending/i)).toBeNull();
      expect(screen.queryByText(/use at your own risk/i)).toBeNull();
    } finally {
      if (previousSelection === undefined) {
        delete process.env.PYBLE_FLASH_SELECTION_FILE;
      } else {
        process.env.PYBLE_FLASH_SELECTION_FILE = previousSelection;
      }
      await rm(selectionRoot, { recursive: true, force: true });
    }
  });

  it("keeps hypothetical future-qualified and prospective-candidate copy distinct", async () => {
    const selectionRoot = await mkdtemp(
      join(tmpdir(), "pyble-site-release-selection-"),
    );
    const selectionFile = join(selectionRoot, "selection.json");
    const previousSelection = process.env.PYBLE_FLASH_SELECTION_FILE;
    process.env.PYBLE_FLASH_SELECTION_FILE = selectionFile;

    try {
      await writeFile(
        selectionFile,
        JSON.stringify(hypotheticalPassedPublicFirmwareRelease),
        "utf8",
      );
      const qualifiedHome = render(<HomePage />);
      expect(
        screen.getByText(/qualified public v0\.5\.1 firmware/i),
      ).toHaveTextContent(
        /esp32-4mb.*lean generic esp32-s3-n16r8.*separate waveshare-esp32-s3-lcd-147b/i,
      );
      qualifiedHome.unmount();
      const qualifiedSupport = render(<SupportPage />);
      expect(
        screen.getByText(/qualified v0\.5\.1 firmware is available/i),
      ).toBeInTheDocument();
      qualifiedSupport.unmount();

      await writeFile(
        selectionFile,
        JSON.stringify(currentPendingCandidateFirmwareRelease),
        "utf8",
      );
      const candidateHome = render(<HomePage />);
      expect(
        screen.getByText(/protected candidate v0\.5\.1 is staged/i),
      ).toBeInTheDocument();
      candidateHome.unmount();
      render(<SupportPage />);
      expect(
        screen.getByText(/firmware installer is currently unavailable/i),
      ).toBeInTheDocument();
    } finally {
      if (previousSelection === undefined) {
        delete process.env.PYBLE_FLASH_SELECTION_FILE;
      } else {
        process.env.PYBLE_FLASH_SELECTION_FILE = previousSelection;
      }
      await rm(selectionRoot, { recursive: true, force: true });
    }
  });

  it("keeps the public installer unavailable while explaining exact profiles, BLE use, and recovery", () => {
    render(<FlashPage />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Firmware installer" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/one-time wired provisioning/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/develop over bluetooth low energy/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /public install action remains unavailable until the final v0\.6\.0-derived bytes pass hardware validation on every included profile/i,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/esp32-s3-n16r8/i)).toBeInTheDocument();
    expect(
      screen.getByText(/16 mib flash.*8 mib octal psram/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/not for every esp32-s3 board/i),
    ).toBeInTheDocument();
    const currentProfiles = screen
      .getByRole("heading", { name: /choose the exact module profile/i })
      .closest("section");
    expect(currentProfiles).toBeDefined();
    expect(
      within(currentProfiles as HTMLElement).queryByText(/esp32-c3-4mb/i),
    ).not.toBeInTheDocument();

    const plannedProfiles = screen
      .getByRole("heading", { name: /planned profile/i })
      .closest("section");
    expect(plannedProfiles).toBeDefined();
    const deferredC3 = within(plannedProfiles as HTMLElement)
      .getByText("esp32-c3-4mb")
      .closest("li");
    expect(deferredC3).toHaveAttribute("aria-disabled", "true");
    expect(deferredC3).toHaveTextContent(/unavailable/i);
    expect(deferredC3).toHaveTextContent(
      /exact-profile real-hardware validation/i,
    );
    expect(
      screen.getByRole("heading", { name: /recover an interrupted flash/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /esp web tools/i }),
    ).toHaveAttribute("href", "https://esphome.github.io/esp-web-tools/");
    expect(
      screen.getByRole("link", { name: /website third-party notices/i }),
    ).toHaveAttribute("href", "/WEBSITE_THIRD_PARTY_LICENSES.txt");
    expect(
      screen.getByRole("button", { name: "Installer coming soon" }),
    ).toBeDisabled();
    expect(document.querySelector("esp-web-install-button")).toBeNull();
  });

  it("keeps the visible recovery section complete without client JavaScript", () => {
    render(<FlashPage />);

    const recovery = screen
      .getByRole("heading", { name: /recover an interrupted flash/i })
      .closest("section")?.textContent;

    expect(recovery).toBeDefined();
    expect.soft(recovery).toMatch(/back up.*user files|user files.*back up/i);
    expect.soft(recovery).toMatch(/data-capable/i);
    expect.soft(recovery).toMatch(/stable[- ]power|stable power/i);
    expect.soft(recovery).toMatch(/automatic reset/i);
    expect.soft(recovery).toMatch(/BOOT.*RESET/i);
    expect.soft(recovery).toMatch(/button labels vary/i);
    expect
      .soft(recovery)
      .toMatch(/permission (?:denial|denied)|denied permission/i);
    expect.soft(recovery).toMatch(/disconnect/i);
    expect.soft(recovery).toMatch(/timeout|timed out/i);
    expect
      .soft(recovery)
      .toMatch(/interrupted erase|erase (?:was )?interrupted/i);
    expect
      .soft(recovery)
      .toMatch(/interrupted write|write (?:was )?interrupted/i);
    expect.soft(recovery).toMatch(/verification (?:failure|fails?)/i);
    expect.soft(recovery).toMatch(/no longer boots|does not boot/i);
    expect.soft(recovery).toMatch(/ROM bootloader/i);
    expect.soft(recovery).toMatch(/same verified profile/i);
    expect.soft(recovery).toMatch(/esptool/i);
    expect
      .soft(recovery)
      .toContain(
        "python -m esptool --chip esp32 write_flash 0x1000 esp32-4mb/firmware.bin",
      );
    expect
      .soft(recovery)
      .toContain(
        "python -m esptool --chip esp32s3 write_flash 0x0 esp32-s3-n16r8/firmware.bin",
      );
    expect.soft(recovery).not.toContain("--chip esp32c3");
    expect.soft(recovery).not.toContain("esp32-c3-4mb/firmware.bin");
    expect.soft(recovery).not.toContain("write-flash");
    expect.soft(recovery).toMatch(/0x(?:0+|1000)\b/i);
    expect.soft(recovery).toMatch(/component offsets/i);
    expect.soft(recovery).not.toMatch(/ESP32-S3\/ESP32-C3/i);
    expect.soft(recovery).toMatch(/hard reset|power cycle/i);
    expect.soft(recovery).toMatch(/PyBLE-XXXX/i);
    expect
      .soft(recovery)
      .toMatch(/wrong memory profile|memory profile (?:is )?wrong/i);
    expect.soft(recovery).toMatch(/random images/i);
    expect.soft(recovery).toMatch(/release version/i);
    expect.soft(recovery).toMatch(/profile ID/i);
    expect.soft(recovery).toMatch(/board model|module marking/i);
    expect
      .soft(recovery)
      .toMatch(
        /browser.*(?:OS|operating system)|(?:OS|operating system).*browser/i,
      );
    expect.soft(recovery).toMatch(/stage.*error|error.*stage/i);
    expect.soft(recovery).toMatch(/secrets/i);
    expect.soft(recovery).toMatch(/personal device labels/i);
  });

  it("does not misdescribe SHA-rooted release metadata as signed", () => {
    render(<FlashPage />);

    const recovery = screen
      .getByRole("heading", { name: /recover an interrupted flash/i })
      .closest("section");

    expect(recovery).not.toHaveTextContent(/signed release metadata/i);
  });

  it("publishes a complete Play-ready privacy policy for the app and website", () => {
    render(<PrivacyPage />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "PyBLE Privacy Policy",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("7 August 2026").closest("time")).toHaveAttribute(
      "datetime",
      "2026-08-07",
    );
    expect(
      screen.getByText(
        /independent open-source project maintained by Viwat Vchirawongkwin/i,
      ),
    ).toHaveTextContent(/under the SciLabPro project name/i);
    expect(
      screen.getByText(
        /not an official Chulalongkorn University project or app/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "PyBLE app" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "This website" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /no account, advertising, analytics, telemetry, or crash reporting/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Save, Run, a Files operation, or send console input/i),
    ).toHaveTextContent(/directly over BLE to the board you selected/i);
    expect(
      screen.getByText(
        /PBLE\/1 does not require Bluetooth pairing or BLE link encryption/i,
      ),
    ).toHaveTextContent(
      /do not send passwords, API keys, tokens, private keys/i,
    );
    expect(
      screen.getByText(/legacy Android location permission/i),
    ).toHaveTextContent(
      /does not derive, store, or transmit your physical location/i,
    );
    expect(
      screen.getByText(/clear PyBLE's app storage or uninstall it/i),
    ).toHaveTextContent(/does not delete files on a board or exported copies/i);
    expect(
      screen.getByText(/delete board files through Files.*Delete/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /no PyBLE server-side copy of your app project content/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /contains no advertising, analytics, crash-reporting, or account SDK/i,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/GitHub import/i)).not.toBeInTheDocument();
    expect(
      screen.getByText(/Cloudflare and the VPS hosting infrastructure/i),
    ).toHaveTextContent(/ordinary request data/i);
    expect(
      screen.getByRole("link", { name: siteConfig.supportEmail }),
    ).toHaveAttribute("href", `mailto:${siteConfig.supportEmail}`);
  });

  it("gives beta users an exact installer intake and preferred bug template", () => {
    render(<SupportPage />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Support" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/exact installer profile ID/i)).toBeInTheDocument();
    expect(
      screen.getByText(/exact board model and module marking/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/flash capacity, PSRAM capacity, and PSRAM type/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/browser name\/version and desktop OS name\/version/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/failed installer stage and redacted error text/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/exact tablet or device model/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/iPadOS or Android name\/version/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/firmware installer is currently unavailable/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/ESP32-C3 is not currently available/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /boards route LEDs, buttons, and NeoPixels differently/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("PyBLE app and agent versions"),
    ).toBeInTheDocument();
    expect(siteConfig.bugReportUrl).toBe(
      "https://github.com/PyBLE-dev/PyBLE/issues/new?template=bug.yml",
    );
    const preferredReport = screen.getByRole("link", {
      name: "Open the GitHub bug template",
    });
    expect(preferredReport).toHaveAttribute("href", siteConfig.bugReportUrl);
    expect(preferredReport).toHaveAttribute("target", "_blank");
    expect(preferredReport).toHaveAttribute("rel", "noopener noreferrer");
  });
});
