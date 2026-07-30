// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { execFile as execFileCallback } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";

import { describe, expect, it } from "vitest";

import { firmwareReleaseSelectedAtBuild } from "@/lib/firmware-release-selection";
import { pendingPublicFirmwareRelease } from "@/test/fixtures/firmware-release";

const execFile = promisify(execFileCallback);

function noticeSection(notice: string, installedPath: string) {
  const marker = `Installed path: ${installedPath}`;
  const markerIndex = notice.indexOf(marker);
  if (markerIndex < 0) {
    throw new Error(`Website notice is missing ${installedPath}`);
  }
  const separator = "=".repeat(80);
  const start = notice.lastIndexOf(separator, markerIndex);
  const end = notice.indexOf(separator, markerIndex);
  return notice.slice(start, end < 0 ? undefined : end);
}

describe("production build contract", () => {
  it("builds the portable export and the Sites vinext artifact", async () => {
    const packageJson = JSON.parse(
      await readFile(join(process.cwd(), "package.json"), "utf8"),
    ) as {
      scripts: Record<string, string>;
    };

    expect(packageJson.scripts).toMatchObject({
      build: "npm run build:static && npm run build:sites",
      "build:static": "next build",
      "build:sites": "vinext build && node scripts/prepare-sites-output.js",
    });
  });

  it("pins the locally bundled ESP Web Tools package exactly", async () => {
    const [packageJson, packageLock] = await Promise.all(
      ["package.json", "package-lock.json"].map(async (file) =>
        JSON.parse(await readFile(join(process.cwd(), file), "utf8")),
      ),
    );

    expect(packageJson.dependencies?.["esp-web-tools"]).toBe("10.4.0");
    expect(packageLock.packages?.["node_modules/esp-web-tools"]).toMatchObject({
      version: "10.4.0",
      resolved:
        "https://registry.npmjs.org/esp-web-tools/-/esp-web-tools-10.4.0.tgz",
      integrity:
        "sha512-3pwkeFFm5Fj7UQo8SJNYK5RXrtNCpq6X9QoI6bMT4GBZWgrJqjn0YvM9ihG74BtMoSFYXfmDtkehuxe50PTMPQ==",
      license: "Apache-2.0",
    });
  });

  it("checks and publishes a deterministic notice for the exact website dependency closure", async () => {
    const [packageJson, notice] = await Promise.all([
      readFile(join(process.cwd(), "package.json"), "utf8").then(
        (value) =>
          JSON.parse(value) as {
            scripts: Record<string, string>;
          },
      ),
      readFile(
        join(process.cwd(), "public", "WEBSITE_THIRD_PARTY_LICENSES.txt"),
        "utf8",
      ),
    ]);

    expect(packageJson.scripts["licenses:web"]).toBe(
      "node scripts/generate-website-third-party-licenses.js --check",
    );
    expect(packageJson.scripts.check).toContain("npm run licenses:web");
    expect(notice).toContain("esp-web-tools");
    expect(notice).toContain("Apache-2.0");
    expect(notice).not.toMatch(
      /(?:THIRD_PARTY_LICENSES\.txt|firmware-embedded dependencies)/i,
    );
  });

  it("publishes each bundled package's complete exact license and copyright notices", async () => {
    const notice = await readFile(
      join(process.cwd(), "public", "WEBSITE_THIRD_PARTY_LICENSES.txt"),
      "utf8",
    );
    const base64 = noticeSection(notice, "node_modules/base64-js");
    const codePointAt = noticeSection(
      notice,
      "node_modules/string.prototype.codepointat",
    );
    const pako = noticeSection(
      notice,
      "node_modules/esptool-js/node_modules/pako",
    );

    expect.soft(base64).toContain("Copyright (c) 2014");
    expect.soft(base64).not.toContain("Meta Platforms");
    expect.soft(codePointAt).toContain("Copyright Mathias Bynens");
    expect.soft(codePointAt).not.toContain("Meta Platforms");
    expect.soft(pako).toContain("SPDX license: (MIT AND Zlib)");
    expect.soft(pako).toContain("Jean-loup Gailly and Mark Adler");
    expect
      .soft(pako)
      .toContain("This software is provided 'as-is', without any express");
  });

  it("keeps the checked-in public selection unavailable and stages no firmware by default", async () => {
    const [selectionSource, packageJson, trackedFirmware] = await Promise.all([
      readFile(
        join(process.cwd(), "src", "lib", "firmware-release-selection.ts"),
        "utf8",
      ),
      readFile(join(process.cwd(), "package.json"), "utf8").then(
        (value) =>
          JSON.parse(value) as {
            scripts: Record<string, string>;
          },
      ),
      execFile("git", [
        "-C",
        join(process.cwd(), "..", ".."),
        "ls-files",
        "--",
        "tools/web/public/firmware",
      ]),
    ]);

    expect(selectionSource).toMatch(
      /selectedFirmwareRelease[\s\S]{0,120}=\s*null/,
    );
    expect(selectionSource).not.toMatch(/\/firmware\/v\d/);
    expect(packageJson.scripts.build).toBe(
      "npm run build:static && npm run build:sites",
    );
    expect(packageJson.scripts.build).not.toContain("firmware:stage");
    expect(trackedFirmware.stdout.trim()).toBe("");
  });

  it("rejects an unknown deployment mode at the build-selection boundary", async () => {
    const selectionRoot = await mkdtemp(
      join(tmpdir(), "pyble-invalid-selection-"),
    );
    const selectionFile = join(selectionRoot, "selection.json");
    const descriptor = structuredClone(
      pendingPublicFirmwareRelease,
    ) as unknown as Record<string, unknown>;
    descriptor.deployment = "publci";
    await writeFile(selectionFile, JSON.stringify(descriptor), "utf8");

    const previousSelection = process.env.PYBLE_FLASH_SELECTION_FILE;
    process.env.PYBLE_FLASH_SELECTION_FILE = selectionFile;
    try {
      expect(() => firmwareReleaseSelectedAtBuild()).toThrow(/deployment/i);
    } finally {
      if (previousSelection === undefined) {
        delete process.env.PYBLE_FLASH_SELECTION_FILE;
      } else {
        process.env.PYBLE_FLASH_SELECTION_FILE = previousSelection;
      }
      await rm(selectionRoot, { recursive: true, force: true });
    }
  });

  it("requires explicit server-side build inputs for protected candidate staging", async () => {
    const [packageJson, stagingSource] = await Promise.all([
      readFile(join(process.cwd(), "package.json"), "utf8").then(
        (value) =>
          JSON.parse(value) as {
            scripts: Record<string, string>;
          },
      ),
      readFile(
        join(process.cwd(), "scripts", "stage-firmware-release.js"),
        "utf8",
      ),
    ]);

    expect(packageJson.scripts["firmware:stage"]).toBe(
      "node scripts/stage-firmware-release.js",
    );
    expect(stagingSource).toContain("PYBLE_FIRMWARE_BUNDLE_DIR");
    expect(stagingSource).toMatch(
      /PYBLE_FIRMWARE_OUTPUT_DIR[\s\S]{0,240}(?:required|failure)/i,
    );
    expect(stagingSource).not.toMatch(
      /PYBLE_FIRMWARE_OUTPUT_DIR\s*\?\?\s*join\(packageRoot,\s*["']public["']\)/,
    );
    expect(stagingSource).toContain("PYBLE_FLASH_DEPLOYMENT");
    expect(stagingSource).toContain("PYBLE_FLASH_ACCESS_CONTROLLED");
    expect(stagingSource).toMatch(
      /PYBLE_FLASH_DEPLOYMENT[\s\S]{0,500}(?:disabled|unavailable)/,
    );
    expect(stagingSource).not.toContain("NEXT_PUBLIC_");
    expect(stagingSource).not.toMatch(
      /\b(?:window|document|location|localStorage|sessionStorage)\s*(?:\.|\[)|\bURLSearchParams\s*\(/,
    );
  });

  it("keeps installer runtime dependencies on the PyBLE origin", async () => {
    const authoredInstallerSources = await Promise.all(
      [
        join(process.cwd(), "src", "app", "flash", "page.tsx"),
        join(process.cwd(), "src", "components", "flash-status.tsx"),
      ].map((path) => readFile(path, "utf8")),
    );

    expect(authoredInstallerSources.join("\n")).not.toMatch(
      /https?:\/\/(?:unpkg\.com|cdn\.jsdelivr\.net|esm\.sh)/i,
    );
  });
});
