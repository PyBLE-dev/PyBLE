// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { execFile as execFileCallback } from "node:child_process";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { pathToFileURL } from "node:url";
import { promisify } from "node:util";

import { describe, expect, it } from "vitest";

import { firmwareReleaseSelectedAtBuild } from "@/lib/firmware-release-selection";
import {
  pendingPublicFirmwareRelease,
  publicBetaFirmwareRelease,
} from "@/test/fixtures/firmware-release";

const execFile = promisify(execFileCallback);

async function authoredFiles(root: string, relative = ""): Promise<string[]> {
  const entries = await readdir(join(root, relative), { withFileTypes: true });
  const paths: string[] = [];
  for (const entry of entries) {
    const child = join(relative, entry.name);
    if (entry.isDirectory()) {
      paths.push(...(await authoredFiles(root, child)));
    } else {
      paths.push(child);
    }
  }
  return paths;
}

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
  it("refuses loopback preview artifacts before either production build", async () => {
    const [packageJson, guardSource] = await Promise.all([
      readFile(join(process.cwd(), "package.json"), "utf8").then(JSON.parse),
      readFile(
        join(process.cwd(), "scripts", "assert-no-local-firmware-preview.js"),
        "utf8",
      ),
    ]);

    expect(packageJson.scripts["build:static"]).toMatch(
      /^node scripts\/assert-no-local-firmware-preview\.js && /,
    );
    expect(packageJson.scripts["build:sites"]).toMatch(
      /^node scripts\/assert-no-local-firmware-preview\.js && /,
    );
    expect(guardSource).toContain(".pyble-local-preview");
    expect(guardSource).toMatch(/lstat|stat/);
    expect(guardSource).toMatch(/refus|forbid|local preview/i);
  });

  it("builds the portable export and the Sites vinext artifact", async () => {
    const packageJson = JSON.parse(
      await readFile(join(process.cwd(), "package.json"), "utf8"),
    ) as {
      scripts: Record<string, string>;
    };

    expect(packageJson.scripts).toMatchObject({
      build: "npm run build:static && npm run build:sites",
      "build:static":
        "node scripts/assert-no-local-firmware-preview.js && next build",
      "build:sites":
        "node scripts/assert-no-local-firmware-preview.js && vinext build && node scripts/prepare-sites-output.js",
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

  it("pins the audited build closure and excludes the vulnerable image parser package", async () => {
    const [packageJson, packageLock, appFiles, sourceFiles] = await Promise.all(
      [
        readFile(join(process.cwd(), "package.json"), "utf8").then(JSON.parse),
        readFile(join(process.cwd(), "package-lock.json"), "utf8").then(
          JSON.parse,
        ),
        authoredFiles(join(process.cwd(), "src", "app")),
        authoredFiles(join(process.cwd(), "src")),
      ],
    );

    expect(packageJson.dependencies?.vinext).toBe("1.0.0-beta.8");
    expect(packageJson.devDependencies?.["@vitejs/plugin-rsc"]).toBe("0.5.34");
    expect(packageJson.scripts?.["audit:dependencies"]).toBe(
      "npm audit --audit-level=high",
    );
    expect(packageJson.scripts?.check).toContain("npm run audit:dependencies");
    expect(packageJson.overrides?.next?.postcss).toBe("8.5.26");
    expect(packageLock.packages?.["node_modules/vinext"]?.version).toBe(
      "1.0.0-beta.8",
    );
    expect(
      packageLock.packages?.["node_modules/@vitejs/plugin-rsc"]?.version,
    ).toBe("0.5.34");
    expect(packageLock.packages?.["node_modules/postcss"]?.version).toBe(
      "8.5.26",
    );
    expect(packageLock.packages?.["node_modules/nanoid"]?.version).toBe(
      "3.3.18",
    );
    expect(packageLock.packages?.["node_modules/image-size"]).toBeUndefined();
    expect(
      (
        Object.values(packageLock.packages ?? {}) as Array<{
          dependencies?: Record<string, string>;
          optionalDependencies?: Record<string, string>;
        }>
      ).some(
        (entry) =>
          entry?.dependencies?.["image-size"] !== undefined ||
          entry?.optionalDependencies?.["image-size"] !== undefined,
      ),
    ).toBe(false);

    const metadataImageRoute =
      /^(?:favicon|icon|apple-icon|opengraph-image|twitter-image)(?:\..+)?$/;
    expect(
      appFiles.filter((path) => metadataImageRoute.test(basename(path))),
    ).toEqual([]);

    const sourceImageImport = [
      /\bfrom\s*["'][^"']+\.(?:avif|gif|ico|icns|jpe?g|jxl|png|svg|webp)(?:\?[^"']*)?["']/,
      /\bimport\s*["'][^"']+\.(?:avif|gif|ico|icns|jpe?g|jxl|png|svg|webp)(?:\?[^"']*)?["']/,
      /\bimport\s*\(\s*["'][^"']+\.(?:avif|gif|ico|icns|jpe?g|jxl|png|svg|webp)(?:\?[^"']*)?["']\s*\)/,
      /\brequire\s*\(\s*["'][^"']+\.(?:avif|gif|ico|icns|jpe?g|jxl|png|svg|webp)(?:\?[^"']*)?["']\s*\)/,
    ];
    const sourceImageImports = (
      await Promise.all(
        sourceFiles
          .filter((path) => /\.(?:js|jsx|ts|tsx)$/.test(path))
          .map(async (path) => ({
            path,
            source: await readFile(join(process.cwd(), "src", path), "utf8"),
          })),
      )
    )
      .filter(({ source }) =>
        sourceImageImport.some((pattern) => pattern.test(source)),
      )
      .map(({ path }) => path);
    expect(sourceImageImports).toEqual([]);
  });

  it("hardens and attributes the image parser bundled inside vinext", async () => {
    const bundledParserPath = join(
      process.cwd(),
      "node_modules",
      "vinext",
      "dist",
      "deps",
      ".pnpm",
      "image-size@2.0.2",
      "deps",
      "image-size",
      "dist",
      "index.js",
    );
    const [packageJson, parserSource, notice] = await Promise.all([
      readFile(join(process.cwd(), "package.json"), "utf8").then(JSON.parse),
      readFile(bundledParserPath, "utf8"),
      readFile(
        join(process.cwd(), "public", "WEBSITE_THIRD_PARTY_LICENSES.txt"),
        "utf8",
      ),
    ]);

    expect(packageJson.scripts?.postinstall).toBe(
      "node scripts/patch-vinext-image-size.js",
    );
    expect(parserSource).toContain(
      'if (imageHeader[1] <= 0) throw new TypeError("Invalid ICNS, zero-length image entry");',
    );
    expect(parserSource).toContain(
      'if (ispeBox.size <= 0) throw new TypeError("Invalid HEIF, zero-length ispe box");',
    );
    expect(parserSource).toContain(
      'if (jxlpBox.size <= 0) throw new TypeError("Invalid JXL, zero-length jxlp box");',
    );
    expect(notice).toContain("image-size 2.0.2");
    expect(notice).toContain(
      "Copyright © 2013-Present Aditya Yadav, http://netroy.in",
    );
  });

  it("applies all bundled parser guards idempotently and rejects upstream drift", async () => {
    const vulnerableFragments = [
      "\t\t\tconst imageHeader = readImageHeader(input, imageOffset);\n\t\t\tconst imageSize2 = getImageSize2(imageHeader[0]);",
      '\t\t\tconst ispeBox = findBox(input, "ispe", currentOffset);\n\t\t\tif (!ispeBox) break;\n\t\t\tconst rawWidth = readUInt32BE(input, ispeBox.offset + 12);',
      '\t\tconst jxlpBox = findBox(input, "jxlp", offset);\n\t\tif (!jxlpBox) break;\n\t\tpartialStreams.push(input.slice(jxlpBox.offset + 12, jxlpBox.offset + jxlpBox.size));',
    ].join("\n");

    const patcherUrl = pathToFileURL(
      join(process.cwd(), "scripts", "patch-vinext-image-size.js"),
    ).href;
    const childSource = `
      import { hardenBundledImageSize } from ${JSON.stringify(patcherUrl)};
      const vulnerable = ${JSON.stringify(vulnerableFragments)};
      const hardened = hardenBundledImageSize(vulnerable);
      for (const marker of [
        "Invalid ICNS, zero-length image entry",
        "Invalid HEIF, zero-length ispe box",
        "Invalid JXL, zero-length jxlp box",
      ]) {
        if (!hardened.includes(marker)) throw new Error(\`missing \${marker}\`);
      }
      if (hardenBundledImageSize(hardened) !== hardened) {
        throw new Error("hardening is not idempotent");
      }
      let driftRejected = false;
      try {
        hardenBundledImageSize("upstream source drift");
      } catch (error) {
        driftRejected = String(error).includes(
          "Cannot apply GHSA-w3rx-r6r6-pgpr hardening",
        );
      }
      if (!driftRejected) throw new Error("upstream drift was not rejected");
      console.log("ok");
    `;
    const result = await execFile(
      process.execPath,
      ["--input-type=module", "--eval", childSource],
      { timeout: 2_000 },
    );
    expect(result.stderr).toBe("");
    expect(result.stdout).toBe("ok\n");
  });

  it("terminates safely for all three bundled parser advisory inputs", async () => {
    const bundledParserUrl = pathToFileURL(
      join(
        process.cwd(),
        "node_modules/vinext/dist/deps/.pnpm/image-size@2.0.2/deps/image-size/dist/index.js",
      ),
    ).href;
    const parserPocs = [
      {
        name: "ICNS",
        expected: "Invalid ICNS, zero-length image entry",
        bytes: [
          0x69, 0x63, 0x6e, 0x73, 0x00, 0x00, 0x00, 0x10, 0x69, 0x73, 0x33,
          0x32, 0x00, 0x00, 0x00, 0x00,
        ],
      },
      {
        name: "HEIF/AVIF",
        expected: "Invalid HEIF, zero-length ispe box",
        bytes: [
          0, 0, 0, 16, 0x66, 0x74, 0x79, 0x70, 0x61, 0x76, 0x69, 0x66, 0, 0, 0,
          0, 0, 0, 0, 36, 0x6d, 0x65, 0x74, 0x61, 0, 0, 0, 0, 0, 0, 0, 8, 0x69,
          0x70, 0x72, 0x70, 0, 0, 0, 20, 0x69, 0x70, 0x63, 0x6f, 0, 0, 0, 0,
          0x69, 0x73, 0x70, 0x65, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        ],
      },
      {
        name: "JXL",
        expected: "Invalid JXL, zero-length jxlp box",
        bytes: [
          0, 0, 0, 12, 0x4a, 0x58, 0x4c, 0x20, 0x0d, 0x0a, 0x87, 0x0a, 0, 0, 0,
          12, 0x66, 0x74, 0x79, 0x70, 0x6a, 0x78, 0x6c, 0x20, 0, 0, 0, 0, 0x6a,
          0x78, 0x6c, 0x70,
        ],
      },
    ] as const;

    for (const poc of parserPocs) {
      const childSource = `
        import { imageSize } from ${JSON.stringify(bundledParserUrl)};
        try {
          imageSize(Uint8Array.from(${JSON.stringify(poc.bytes)}));
          console.error("unexpected parser success");
          process.exit(3);
        } catch (error) {
          if (!(error instanceof TypeError)) throw error;
          console.log(error.message);
        }
      `;
      const result = await execFile(
        process.execPath,
        ["--input-type=module", "--eval", childSource],
        { timeout: 2_000 },
      );
      expect(result.stderr, poc.name).toBe("");
      expect(result.stdout.trim(), poc.name).toBe(poc.expected);
    }
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
    const hexRgb = noticeSection(notice, "node_modules/hex-rgb");
    const pako = noticeSection(
      notice,
      "node_modules/esptool-js/node_modules/pako",
    );

    expect.soft(base64).toContain("Copyright (c) 2014");
    expect.soft(base64).not.toContain("Meta Platforms");
    expect.soft(codePointAt).toContain("Copyright Mathias Bynens");
    expect.soft(codePointAt).not.toContain("Meta Platforms");
    expect.soft(hexRgb).toContain("License file: license");
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

  it("accepts only the exact attested public-beta selector at the build boundary", async () => {
    const selectionRoot = await mkdtemp(
      join(tmpdir(), "pyble-beta-selection-"),
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
      expect(firmwareReleaseSelectedAtBuild()).toEqual(
        publicBetaFirmwareRelease,
      );

      const altered = structuredClone(publicBetaFirmwareRelease);
      altered.releaseJson.sha256 = "0".repeat(64);
      await writeFile(selectionFile, JSON.stringify(altered), "utf8");
      expect(() => firmwareReleaseSelectedAtBuild()).toThrow(/public beta/i);
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

  it("gives an active public beta truthful page-level context", async () => {
    const page = await readFile(
      join(process.cwd(), "src", "app", "flash", "page.tsx"),
      "utf8",
    );

    expect(page).toContain('release?.deployment === "public-beta"');
    expect(page).toMatch(/hardware-tested firmware beta/i);
    expect(page).toMatch(/production chrome.*install/i);
    expect(page).toMatch(/interrupted-flash recovery.*both exact profiles/i);
    expect(page).toMatch(/complete release qualification.*pending/i);
    expect(page).not.toMatch(/full HIL pending|use at your own risk/i);
  });
});
