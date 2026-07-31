// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import FlashPage, { metadata as flashMetadata } from "@/app/flash/page";
import { metadata as rootMetadata } from "@/app/layout";
import HomePage, { metadata as homeMetadata } from "@/app/page";
import PrivacyPage, { metadata as privacyMetadata } from "@/app/privacy/page";
import SupportPage, { metadata as supportMetadata } from "@/app/support/page";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { initialFirmwareTargets, navigation, siteConfig } from "@/lib/site";

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
    expect(privacyMetadata.alternates).toEqual({
      canonical: "https://pyble.dev/privacy",
    });
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
      "https://pyble.dev/privacy",
      "https://pyble.dev/support",
      "https://pyble.dev/flash",
    ]);
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
    const socialUrl = "https://pyble.dev/social/pyble-beta-og-1200x630.png";
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
      readFile(join(publicDirectory, "social", "pyble-beta-og-1200x630.png")),
      readFile(
        join(publicDirectory, "social", "pyble-beta-og-1200x630.svg"),
        "utf8",
      ),
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
    expect(socialSvg).toContain("FIRMWARE HIL PENDING");
    expect(socialSvg).not.toContain("WEB FLASHER");
    expect(createHash("sha256").update(socialPng).digest("hex")).toBe(
      "7e7e037d9bd2e58e2e66f516bfd6f1b753bda472c402b8130f8a8a6dd8f19ba9",
    );
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
  });

  it("states the vendor-neutral vision and the truthful pre-activation firmware state", () => {
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
    expect(screen.getByText(/public v0\.4\.2 firmware/i)).toHaveTextContent(
      /pending HIL for the exact esp32-4mb and esp32-s3-n16r8 profiles/i,
    );
    expect(screen.getByText(/public v0\.4\.2 firmware/i)).toHaveTextContent(
      /public browser installer stays unavailable until both exact profiles pass HIL/i,
    );
    expect(
      screen.getByText(
        /ESP32-C3 and more microcontroller families remain planned/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: "MicroPython + Bluetooth, not one chip family.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Initial beta firmware targets"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/a validated PyBLE agent port is still required/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Python over Bluetooth Low Energy"),
    ).toBeInTheDocument();
    expect(screen.getByText("iPad beta now open")).toBeInTheDocument();
    expect(
      screen.queryByText(/available on the app store/i),
    ).not.toBeInTheDocument();
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
  });

  it("publishes the approved TestFlight invitation as a link and verified local QR code", async () => {
    const testFlightUrl = "https://testflight.apple.com/join/yU4e8s6d";

    render(<HomePage />);

    const betaSection = screen.getByRole("region", {
      name: "Join the PyBLE beta on TestFlight.",
    });
    expect(
      within(betaSection).getByText(/external testing is open/i),
    ).toBeInTheDocument();

    const directLink = within(betaSection).getByRole("link", {
      name: "Open in TestFlight",
    });
    expect(directLink).toHaveAttribute("href", testFlightUrl);
    expect(directLink).toHaveAttribute("target", "_blank");
    expect(directLink).toHaveAttribute("rel", "noopener noreferrer");

    const qrDescription = "QR code for the PyBLE beta on Apple TestFlight";
    const qrLink = within(betaSection).getByRole("link", {
      name: qrDescription,
    });
    expect(qrLink).toHaveAttribute("href", testFlightUrl);
    expect(qrLink).toHaveAttribute("target", "_blank");
    expect(qrLink).toHaveAttribute("rel", "noopener noreferrer");
    expect(
      within(betaSection).getByRole("img", { name: qrDescription }),
    ).toHaveAttribute("src", "/testflight/pyble-testflight-qr.svg");
    expect(
      within(betaSection).getByText("testflight.apple.com/join/yU4e8s6d"),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("link", { name: "Join the iPad beta" }),
    ).toHaveAttribute("href", "#testflight");
    expect(
      screen.queryByText(/preparing for public (?:beta|testing)/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/available on the app store/i),
    ).not.toBeInTheDocument();

    const qrAsset = await readFile(
      join(process.cwd(), "public", "testflight", "pyble-testflight-qr.svg"),
    );
    expect(createHash("sha256").update(qrAsset).digest("hex")).toBe(
      "4ab6c814a8526c4d69a3b330dc563298edf5bf7eadbea4babd262fa75568e305",
    );
    expect(qrAsset.toString("utf8")).not.toMatch(
      /<(?:script|image)\b|(?:href|xlink:href)=/i,
    );
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
    ]);

    render(<HomePage />);

    for (const target of initialFirmwareTargets) {
      const targetCard = screen.getByText(target.id).closest("div");
      expect(targetCard).toHaveTextContent(target.target);
      expect(targetCard).toHaveTextContent(target.constraint);
      expect(targetCard).toHaveTextContent(target.status);
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
        /public install action remains unavailable until the final bytes pass hardware validation on both exact current release profiles/i,
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

  it("publishes the app and website privacy promises separately", () => {
    render(<PrivacyPage />);

    expect(
      screen.getByRole("heading", { name: "PyBLE app" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "This website" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/no account, advertising, analytics, or telemetry/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/tablet or the connected board you choose/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/tablet or the ESP32 board/i),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/ordinary request data/i)).toBeInTheDocument();
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
      screen.getByText(
        /public installer is unavailable while v0\.4\.2 HIL runs for esp32-4mb and esp32-s3-n16r8/i,
      ),
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
