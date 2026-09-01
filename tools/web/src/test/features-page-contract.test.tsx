// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import FeaturesPage, { metadata } from "@/app/features/page";

const diagramPath =
  "/features/pyble-firmware-v0.6.0-functional-block-diagram-24b9ab9fd54b.svg";
const diagramSha256 =
  "24b9ab9fd54b04b45c00fbee34d0c41840c73639cba1c6ca27f714b5278b2295";

const operationGroups = [
  ["HELLO", "DEVICE_INFO"],
  [
    "FILE_LIST",
    "FILE_STAT",
    "FILE_GET_BEGIN",
    "FILE_GET_DATA",
    "FILE_GET_END",
    "FILE_PUT_BEGIN",
    "FILE_PUT_DATA",
    "FILE_PUT_END",
    "FILE_DELETE",
    "MKDIR",
    "FILE_RENAME",
    "FILE_PUT_ACK",
  ],
  ["RUN", "STOP", "SOFT_REBOOT", "SET_AUTORUN", "RUN_STATE"],
  ["CONSOLE_DATA", "CONSOLE_INPUT"],
  ["SET_LABEL", "SET_IDENTIFY_LED", "IDENTIFY"],
] as const;

const profileOrder = [
  "esp32-4mb",
  "esp32-s3-n16r8",
  "waveshare-esp32-s3-lcd-147b",
  "esp32-c3-4mb",
  "rpi-pico2-w",
] as const;

describe("firmware feature reference", () => {
  it("publishes canonical metadata and an inspectable functional diagram", () => {
    expect(metadata.title).toBe("PyBLE Firmware Architecture");
    expect(metadata.description).toMatch(/PBLE\/1 functional architecture/i);
    expect(metadata.alternates).toEqual({
      canonical: "https://pyble.dev/features",
    });

    const page = render(<FeaturesPage />);
    expect(page.container.querySelector("main#main-content")).not.toBeNull();
    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "How PyBLE firmware works",
      }),
    ).toBeVisible();

    const diagram = screen.getByRole("img", {
      name: /functional block diagram.*not a board drawing.*pinout/i,
    });
    expect(diagram).toHaveAttribute("src", diagramPath);
    expect(diagram).toHaveAttribute("width", "1920");
    expect(diagram).toHaveAttribute("height", "1470");
    expect(
      screen.getByRole("region", {
        name: "Scrollable PyBLE firmware diagram",
      }),
    ).toHaveAttribute("tabindex", "0");
    expect(
      screen.getByRole("link", {
        name: "Open full-size SVG diagram (opens in a new tab)",
      }),
    ).toHaveAttribute("href", diagramPath);
    expect(
      screen.getByText(/original PyBLE diagram.*not a board drawing/i),
    ).toBeVisible();
  });

  it("repeats every material diagram claim as reflowing semantic HTML", () => {
    render(<FeaturesPage />);

    const description = screen.getByRole("region", {
      name: "Diagram description",
    });
    expect(description).toHaveTextContent(/iPadOS or Android/i);
    expect(description).toHaveTextContent(/Bluetooth Low Energy/i);
    expect(description).toHaveTextContent(/24 opcodes/i);
    expect(description).toHaveTextContent(/\.pbltmp sibling/i);
    expect(description).toHaveTextContent(/zero PyBLE patches/i);
    expect(description).toHaveTextContent(/memory alone does not identify/i);

    const reference = screen.getByRole("region", {
      name: "Complete PBLE/1 feature reference",
    });
    for (const operation of operationGroups.flat()) {
      expect(within(reference).getByText(operation)).toBeVisible();
    }
    expect(operationGroups.flat()).toHaveLength(24);
    for (const heading of [
      "BLE transport",
      "Identity and capabilities",
      "Safe boot and persistence",
      "Security and privacy",
      "Files",
      "Run and control",
      "Live console",
      "Lifecycle and reliability",
      "MicroPython runtime",
    ]) {
      expect(
        within(reference).getByRole("heading", { level: 3, name: heading }),
      ).toBeVisible();
    }
  });

  it("keeps the five qualified profiles ordered and distinguishes exact-board boundaries", () => {
    render(<FeaturesPage />);

    const profiles = screen.getByRole("region", {
      name: "Qualified firmware 0.6.0 profiles",
    });
    const table = within(profiles).getByRole("table", {
      name: /five qualified release profiles/i,
    });
    const profileHeadings = within(table)
      .getAllByRole("rowheader")
      .map((heading) => heading.textContent?.trim());
    expect(profileHeadings).toEqual(profileOrder);
    expect(table).toHaveTextContent(/lean, board-neutral/i);
    expect(table).toHaveTextContent(/no TFT or boot splash/i);
    expect(table).toHaveTextContent(/exact.*B-version/i);
    expect(table).toHaveTextContent(/ST7789.*fresh-install splash/i);
    expect(table).toHaveTextContent(/UF2.*BOOTSEL/i);
    expect(table).toHaveTextContent(/evidence, not visual board detection/i);
  });

  it("keeps installation authority on flash and links immutable evidence", async () => {
    render(<FeaturesPage />);

    expect(
      screen.getByRole("link", {
        name: /check current firmware availability/i,
      }),
    ).toHaveAttribute("href", "/flash");
    expect(
      screen.getByRole("link", { name: /start the guided tutorials/i }),
    ).toHaveAttribute("href", "/learn");
    expect(
      screen.getByRole("link", { name: /release descriptor/i }),
    ).toHaveAttribute("href", "/firmware/v0.6.0/release.json");
    expect(
      screen.getByRole("link", { name: /firmware v0\.6\.0 source tag/i }),
    ).toHaveAttribute(
      "href",
      "https://github.com/PyBLE-dev/PyBLE/releases/tag/firmware-v0.6.0",
    );
    expect(
      screen.getByRole("link", { name: /PBLE\/1 specification/i }),
    ).toHaveAttribute(
      "href",
      "https://github.com/PyBLE-dev/PyBLE/blob/firmware-v0.6.0/docs/specifications/protocol.md",
    );

    const source = await readFile(
      join(process.cwd(), "src", "app", "features", "page.tsx"),
      "utf8",
    );
    expect(source).not.toContain('"use client"');
    expect(source).not.toContain("firmware-release-selection");
    expect(source).not.toContain("FlashStatus");
    expect(source).not.toContain("esp-web-tools");
    expect(source).not.toMatch(/\bfetch\s*\(/);
    expect(source).not.toMatch(/<esp-web-install-button/i);
  });

  it("binds the reviewed, self-contained SVG to its clean-room provenance", async () => {
    const [diagram, provenance] = await Promise.all([
      readFile(join(process.cwd(), "public", diagramPath), "utf8"),
      readFile(
        join(
          process.cwd(),
          "..",
          "..",
          "docs",
          "testing",
          "website",
          "firmware-functional-diagram-provenance-2026-09-01.md",
        ),
        "utf8",
      ),
    ]);

    expect(Buffer.byteLength(diagram)).toBe(22_029);
    expect(createHash("sha256").update(diagram).digest("hex")).toBe(
      diagramSha256,
    );
    expect(diagram).toContain("<!-- SPDX-License-Identifier: MIT -->");
    expect(diagram).toMatch(
      /<svg[^>]*width="1920"[^>]*height="1470"[^>]*viewBox="0 0 1920 1470"[^>]*role="img"/,
    );
    expect(diagram).toMatch(
      /<title[^>]*>[^<]*functional block diagram<\/title>/i,
    );
    expect(diagram).toMatch(
      /<desc[^>]*>[^<]*not a board drawing[^<]*<\/desc>/i,
    );
    expect(diagram).not.toMatch(/<(?:script|image|foreignObject)\b/i);
    expect(diagram).not.toMatch(/\b(?:href|xlink:href)\s*=/i);
    expect(diagram).not.toMatch(/(?:st\.com|STM32|Magnific|Freepik)/i);

    expect(provenance).toContain(diagramPath);
    expect(provenance).toContain(diagramSha256);
    expect(provenance).toMatch(/original.*functional architecture/i);
    expect(provenance).toMatch(/no vendor artwork.*no generated board/i);
  });
});
