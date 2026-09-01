// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { execFile as execFileCallback } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { promisify } from "node:util";

import { afterEach, describe, expect, it } from "vitest";

import * as sitesOutput from "../../scripts/prepare-sites-output";
import { stageFirmwareRelease } from "../../scripts/stage-firmware-release";
import {
  bundleFiles,
  createCurrentFirmwareReleaseFixture,
} from "@/test/fixtures/firmware-release";

const temporaryDirectories: string[] = [];
const execFile = promisify(execFileCallback);
const acceptSyntheticFixture = async () => undefined;
const { prepareSitesOutput } = sitesOutput;
const featureDiagramPath =
  "/features/pyble-firmware-v0.6.0-functional-block-diagram-473a85d475aa.svg";
const learnDocumentRoutes = [
  "/learn",
  "/learn/setup",
  "/learn/first-program",
  "/learn/files",
  "/learn/github-import",
  "/learn/blocks",
  "/learn/examples",
  "/learn/hardware",
  "/learn/configured-hardware",
  "/learn/pico-2-w",
  "/learn/waveshare-lcd-147b",
] as const;
const requiredPrerenderedRoutes = [
  "/",
  "/app",
  "/features",
  "/flash",
  "/privacy",
  "/support",
  ...learnDocumentRoutes,
  "/404",
] as const;
const delegatedLearnPaths = learnDocumentRoutes.flatMap((route) => [
  route,
  `${route}/`,
]);
const delegatedFeaturePaths = [
  "/features",
  "/features/",
  featureDiagramPath,
] as const;

afterEach(async () => {
  await Promise.all(
    temporaryDirectories
      .splice(0)
      .map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

async function writeSitesSkeleton(root: string) {
  const binding = '{\n  "project_id": "appgprj_test"\n}\n';
  const serverEntry =
    "export default function handler(request, context) {\n" +
    "  return new Response(`vinext:${new URL(request.url).pathname}:${context.marker}`);\n" +
    "}\n";
  const prerenderManifest = JSON.stringify({
    routes: requiredPrerenderedRoutes.map((route) => ({
      route,
      status: "rendered",
    })),
  });

  await mkdir(join(root, ".openai"), { recursive: true });
  await mkdir(join(root, "dist", "server", "ssr"), { recursive: true });
  await mkdir(join(root, "dist", "client", ".vite"), { recursive: true });
  await writeFile(join(root, "package.json"), '{"type":"module"}');
  await writeFile(join(root, ".openai", "hosting.json"), binding);
  await writeFile(join(root, "dist", "server", "index.js"), serverEntry);
  await writeFile(
    join(root, "dist", "server", "ssr", "index.js"),
    "export function render() {}\n",
  );
  await writeFile(
    join(root, "dist", "server", "vinext-prerender.json"),
    prerenderManifest,
  );
  await writeFile(join(root, "dist", "client", ".vite", "manifest.json"), "{}");
  await writeFile(join(root, "dist", "client", "404.html"), "<h1>404</h1>");
  await Promise.all(
    ["robots.txt", "sitemap.xml", "manifest.webmanifest"].map((file) =>
      writeFile(join(root, "dist", "client", file), file),
    ),
  );
}

describe("Sites vinext-output adapter", () => {
  it("selects preserved validation only for the exact deploy-derived mode", () => {
    const resolveReleaseValidator = (
      sitesOutput as typeof sitesOutput & {
        sitesFirmwareReleaseValidator?: () => {
          name: string;
        };
      }
    ).sitesFirmwareReleaseValidator;
    const mode = "PYBLE_FIRMWARE_VALIDATION_MODE";
    const previousMode = process.env[mode];

    expect(resolveReleaseValidator).toBeTypeOf("function");
    if (!resolveReleaseValidator) {
      return;
    }
    try {
      delete process.env[mode];
      expect(resolveReleaseValidator().name).toBe(
        "validateFreshDeploymentBundle",
      );

      process.env[mode] = "preserved-public";
      expect(resolveReleaseValidator().name).toBe(
        "validatePreservedDeploymentBundle",
      );

      process.env[mode] = "preserved";
      expect(() => resolveReleaseValidator()).toThrow(
        "PYBLE_FIRMWARE_VALIDATION_MODE",
      );
    } finally {
      if (previousMode === undefined) {
        delete process.env[mode];
      } else {
        process.env[mode] = previousMode;
      }
    }
  });

  it("wraps vinext with a static 404 boundary and copies the exact project binding", async () => {
    const root = await mkdtemp(join(tmpdir(), "pyble-web-output-"));
    temporaryDirectories.push(root);

    const binding = '{\n  "project_id": "appgprj_test"\n}\n';
    const serverEntry =
      "export default function handler(request, context) {\n" +
      "  return new Response(`vinext:${new URL(request.url).pathname}:${context.marker}`);\n" +
      "}\n";
    const ssrEntry = "export function render() {}\n";
    const clientEntry = "<h1>PyBLE</h1>\n";
    const notFoundEntry = "<h1>That path wandered off.</h1>\n";
    const prerenderManifest = JSON.stringify({
      routes: requiredPrerenderedRoutes.map((route) => ({
        route,
        status: "rendered",
      })),
    });

    await mkdir(join(root, ".openai"), { recursive: true });
    await mkdir(join(root, "dist", ".openai"), { recursive: true });
    await mkdir(join(root, "dist", "server", "ssr"), { recursive: true });
    await mkdir(join(root, "dist", "client", ".vite"), { recursive: true });
    await writeFile(join(root, "package.json"), '{"type":"module"}');
    await writeFile(join(root, ".openai", "hosting.json"), binding);
    await writeFile(join(root, "dist", ".openai", "hosting.json"), "stale");
    await writeFile(join(root, "dist", "server", "index.js"), serverEntry);
    await writeFile(join(root, "dist", "server", "ssr", "index.js"), ssrEntry);
    await writeFile(
      join(root, "dist", "server", "vinext-prerender.json"),
      prerenderManifest,
    );
    await writeFile(
      join(root, "dist", "client", ".vite", "manifest.json"),
      "{}",
    );
    await writeFile(join(root, "dist", "client", "index.html"), clientEntry);
    await writeFile(join(root, "dist", "client", "404.html"), notFoundEntry);
    await Promise.all(
      ["robots.txt", "sitemap.xml", "manifest.webmanifest"].map((file) =>
        writeFile(join(root, "dist", "client", file), file),
      ),
    );

    await prepareSitesOutput(root);

    await expect(
      readFile(join(root, "dist", ".openai", "hosting.json"), "utf8"),
    ).resolves.toBe(binding);
    await expect(
      readFile(join(root, "dist", "server", "vinext-handler.js"), "utf8"),
    ).resolves.toBe(serverEntry);
    await expect(
      readFile(join(root, "dist", "server", "ssr", "index.js"), "utf8"),
    ).resolves.toBe(ssrEntry);
    await expect(
      readFile(join(root, "dist", "client", "index.html"), "utf8"),
    ).resolves.toBe(clientEntry);

    const entrypointUrl = pathToFileURL(
      join(root, "dist", "server", "index.js"),
    );
    const probe = `
      const { default: worker } = await import(${JSON.stringify(entrypointUrl.href)});
      if (typeof worker.fetch !== "function") {
        throw new TypeError("Sites entrypoint must export a module-worker fetch method");
      }
      const context = { marker: "execution-context" };
      const features = Object.fromEntries(await Promise.all(
        ${JSON.stringify(delegatedFeaturePaths)}.map(async (pathname) => {
          const response = await worker.fetch(
            new Request("https://pyble.dev" + pathname),
            {},
            context,
          );
          return [
            pathname,
            { status: response.status, body: await response.text() },
          ];
        }),
      ));
      const learn = Object.fromEntries(await Promise.all(
        ${JSON.stringify(delegatedLearnPaths)}.map(async (pathname) => {
          const response = await worker.fetch(
            new Request("https://pyble.dev" + pathname),
            {},
            context,
          );
          return [
            pathname,
            { status: response.status, body: await response.text() },
          ];
        }),
      ));
      const privacy = await worker.fetch(
        new Request("https://pyble.dev/privacy"),
        { marker: "environment-must-not-reach-vinext" },
        context,
      );
      const app = await worker.fetch(
        new Request("https://pyble.dev/app"),
        {},
        context,
      );
      const brand = await worker.fetch(
        new Request("https://pyble.dev/brand/pyble-prompt-chip.svg"),
        {},
        context,
      );
      const appCapture = await worker.fetch(
        new Request(
          "https://pyble.dev/app/pyble-neopixel-gpio48-ipad-raw.png",
        ),
        {},
        context,
      );
      const testFlightQr = await worker.fetch(
        new Request(
          "https://pyble.dev/testflight/pyble-testflight-qr.svg",
        ),
        {},
        context,
      );
      const googlePlayQr = await worker.fetch(
        new Request(
          "https://pyble.dev/google-play/pyble-google-play-internal-test-qr.svg",
        ),
        {},
        context,
      );
      const firmwareManifest = await worker.fetch(
        new Request(
          "https://pyble.dev/firmware/v0.4.2/esp32-s3-n16r8/manifest.json",
        ),
        {},
        context,
      );
      const firmwareBinary = await worker.fetch(
        new Request(
          "https://pyble.dev/firmware/v0.4.2/esp32-s3-n16r8/firmware.bin",
        ),
        {},
        context,
      );
      const notFound = await worker.fetch(
        new Request("https://pyble.dev/not-found-smoke"),
        {},
        context,
      );
      const unknownLearn = await worker.fetch(
        new Request("https://pyble.dev/learn/not-a-tutorial"),
        {},
        context,
      );
      const unknownLearnTrailingSlash = await worker.fetch(
        new Request("https://pyble.dev/learn/not-a-tutorial/"),
        {},
        context,
      );
      console.log(JSON.stringify({
        features,
        learn,
        privacy: { status: privacy.status, body: await privacy.text() },
        app: { status: app.status, body: await app.text() },
        brand: { status: brand.status, body: await brand.text() },
        appCapture: {
          status: appCapture.status,
          body: await appCapture.text(),
        },
        testFlightQr: {
          status: testFlightQr.status,
          body: await testFlightQr.text(),
        },
        googlePlayQr: {
          status: googlePlayQr.status,
          body: await googlePlayQr.text(),
        },
        firmwareManifest: {
          status: firmwareManifest.status,
          body: await firmwareManifest.text(),
        },
        firmwareBinary: {
          status: firmwareBinary.status,
          body: await firmwareBinary.text(),
        },
        notFound: { status: notFound.status, body: await notFound.text() },
        unknownLearn: {
          status: unknownLearn.status,
          body: await unknownLearn.text(),
        },
        unknownLearnTrailingSlash: {
          status: unknownLearnTrailingSlash.status,
          body: await unknownLearnTrailingSlash.text(),
        },
      }));
    `;
    const { stdout } = await execFile(
      process.execPath,
      ["--input-type=module", "--eval", probe],
      { cwd: root },
    );

    expect(JSON.parse(stdout)).toEqual({
      features: Object.fromEntries(
        delegatedFeaturePaths.map((pathname) => [
          pathname,
          {
            status: 200,
            body: `vinext:${pathname}:execution-context`,
          },
        ]),
      ),
      learn: Object.fromEntries(
        delegatedLearnPaths.map((pathname) => [
          pathname,
          {
            status: 200,
            body: `vinext:${pathname}:execution-context`,
          },
        ]),
      ),
      privacy: {
        status: 200,
        body: "vinext:/privacy:execution-context",
      },
      app: {
        status: 200,
        body: "vinext:/app:execution-context",
      },
      brand: {
        status: 200,
        body: "vinext:/brand/pyble-prompt-chip.svg:execution-context",
      },
      appCapture: {
        status: 200,
        body: "vinext:/app/pyble-neopixel-gpio48-ipad-raw.png:execution-context",
      },
      testFlightQr: {
        status: 200,
        body: "vinext:/testflight/pyble-testflight-qr.svg:execution-context",
      },
      googlePlayQr: {
        status: 200,
        body: "vinext:/google-play/pyble-google-play-internal-test-qr.svg:execution-context",
      },
      firmwareManifest: {
        status: 200,
        body: "vinext:/firmware/v0.4.2/esp32-s3-n16r8/manifest.json:execution-context",
      },
      firmwareBinary: {
        status: 200,
        body: "vinext:/firmware/v0.4.2/esp32-s3-n16r8/firmware.bin:execution-context",
      },
      notFound: { status: 404, body: notFoundEntry },
      unknownLearn: { status: 404, body: notFoundEntry },
      unknownLearnTrailingSlash: { status: 404, body: notFoundEntry },
    });
  });

  it("fails clearly when the vinext server entrypoint is missing", async () => {
    const root = await mkdtemp(join(tmpdir(), "pyble-web-output-"));
    temporaryDirectories.push(root);

    await mkdir(join(root, ".openai"), { recursive: true });
    await writeFile(
      join(root, ".openai", "hosting.json"),
      '{"project_id":"appgprj_test"}',
    );

    await expect(prepareSitesOutput(root)).rejects.toThrow(
      /vinext server entrypoint is missing/i,
    );
  });

  it("fails clearly when the Sites project binding is missing", async () => {
    const root = await mkdtemp(join(tmpdir(), "pyble-web-output-"));
    temporaryDirectories.push(root);

    await mkdir(join(root, "dist", "server"), { recursive: true });
    await writeFile(join(root, "dist", "server", "index.js"), "export {};");

    await expect(prepareSitesOutput(root)).rejects.toThrow(
      /Sites project binding is missing/i,
    );
  });

  it("rejects an exact Learn route that vinext did not prerender", async () => {
    const root = await mkdtemp(join(tmpdir(), "pyble-web-output-"));
    temporaryDirectories.push(root);

    await mkdir(join(root, ".openai"), { recursive: true });
    await mkdir(join(root, "dist", "server"), { recursive: true });
    await writeFile(
      join(root, ".openai", "hosting.json"),
      '{"project_id":"appgprj_test"}',
    );
    await writeFile(join(root, "dist", "server", "index.js"), "export {};");
    await writeFile(
      join(root, "dist", "server", "vinext-prerender.json"),
      JSON.stringify({
        routes: requiredPrerenderedRoutes
          .filter((route) => route !== "/learn/github-import")
          .map((route) => ({ route, status: "rendered" })),
      }),
    );

    await expect(prepareSitesOutput(root)).rejects.toThrow(
      /launch route was not prerendered: \/learn\/github-import/i,
    );
  });

  it("rejects the Features route when vinext did not prerender it", async () => {
    const root = await mkdtemp(join(tmpdir(), "pyble-web-output-"));
    temporaryDirectories.push(root);

    await mkdir(join(root, ".openai"), { recursive: true });
    await mkdir(join(root, "dist", "server"), { recursive: true });
    await writeFile(
      join(root, ".openai", "hosting.json"),
      '{"project_id":"appgprj_test"}',
    );
    await writeFile(join(root, "dist", "server", "index.js"), "export {};");
    await writeFile(
      join(root, "dist", "server", "vinext-prerender.json"),
      JSON.stringify({
        routes: requiredPrerenderedRoutes
          .filter((route) => route !== "/features")
          .map((route) => ({ route, status: "rendered" })),
      }),
    );

    await expect(prepareSitesOutput(root)).rejects.toThrow(
      /launch route was not prerendered: \/features/i,
    );
  });

  it("copies only the freshly revalidated prospective v0.5.1 three-profile candidate into the Sites artifact", async () => {
    const fixture = createCurrentFirmwareReleaseFixture({
      deployment: "candidate",
      accessControlled: true,
      hilStatus: "pending",
    });
    const bundleRoot = await mkdtemp(join(tmpdir(), "pyble-sites-bundle-"));
    const stagedRoot = await mkdtemp(join(tmpdir(), "pyble-sites-staged-"));
    const sitesRoot = await mkdtemp(join(tmpdir(), "pyble-sites-output-"));
    temporaryDirectories.push(bundleRoot, stagedRoot, sitesRoot);

    for (const [relativePath, bytes] of bundleFiles(fixture)) {
      const path = join(bundleRoot, relativePath);
      await mkdir(join(path, ".."), { recursive: true });
      await writeFile(path, bytes);
    }
    await stageFirmwareRelease({
      accessControlled: true,
      bundleDirectory: bundleRoot,
      deployment: "candidate",
      outputDirectory: stagedRoot,
      releaseValidator: acceptSyntheticFixture,
    });
    await writeSitesSkeleton(sitesRoot);

    const prepareWithFirmware = prepareSitesOutput as (
      packageRoot: string,
      stagedFirmwareRoot?: string,
      releaseValidator?: typeof acceptSyntheticFixture,
    ) => Promise<void>;
    const previousSelection = process.env.PYBLE_FLASH_SELECTION_FILE;
    process.env.PYBLE_FLASH_SELECTION_FILE = join(
      stagedRoot,
      ".pyble-firmware-release-selection.json",
    );
    try {
      await prepareWithFirmware(sitesRoot, stagedRoot, acceptSyntheticFixture);
    } finally {
      if (previousSelection === undefined) {
        delete process.env.PYBLE_FLASH_SELECTION_FILE;
      } else {
        process.env.PYBLE_FLASH_SELECTION_FILE = previousSelection;
      }
    }

    await expect(
      readFile(
        join(
          sitesRoot,
          "dist",
          "client",
          "firmware",
          "v0.5.1",
          "waveshare-esp32-s3-lcd-147b",
          "firmware.bin",
        ),
      ).then((value) => Array.from(value)),
    ).resolves.toEqual(Array.from(fixture.firmwareBytes));
    await expect(
      readFile(
        join(
          sitesRoot,
          "dist",
          "client",
          "firmware",
          "v0.5.1",
          "esp32-c3-4mb",
          "manifest.json",
        ),
      ),
    ).rejects.toThrow();
    await expect(
      readFile(
        join(sitesRoot, "dist", "client", "firmware", "v0.4.2", "release.json"),
      ),
    ).rejects.toThrow();
    await expect(
      readFile(join(sitesRoot, "public", "firmware")),
    ).rejects.toThrow();
  });

  it("requires the Sites selector and staged firmware root to be one exact pair", async () => {
    const fixture = createCurrentFirmwareReleaseFixture({
      deployment: "candidate",
      accessControlled: true,
      hilStatus: "pending",
    });
    const bundleRoot = await mkdtemp(
      join(tmpdir(), "pyble-sites-binding-bundle-"),
    );
    const stagedRoot = await mkdtemp(
      join(tmpdir(), "pyble-sites-binding-staged-"),
    );
    const externalSelectionRoot = await mkdtemp(
      join(tmpdir(), "pyble-sites-binding-selection-"),
    );
    temporaryDirectories.push(bundleRoot, stagedRoot, externalSelectionRoot);

    for (const [relativePath, bytes] of bundleFiles(fixture)) {
      const path = join(bundleRoot, relativePath);
      await mkdir(join(path, ".."), { recursive: true });
      await writeFile(path, bytes);
    }
    await stageFirmwareRelease({
      accessControlled: true,
      bundleDirectory: bundleRoot,
      deployment: "candidate",
      outputDirectory: stagedRoot,
      releaseValidator: acceptSyntheticFixture,
    });
    const externalSelection = join(externalSelectionRoot, "selection.json");
    await writeFile(externalSelection, "{}\n");

    const prepareWithFirmware = prepareSitesOutput as (
      packageRoot: string,
      stagedFirmwareRoot?: string,
      releaseValidator?: typeof acceptSyntheticFixture,
    ) => Promise<void>;
    const previousSelection = process.env.PYBLE_FLASH_SELECTION_FILE;
    const previousStagedRoot = process.env.PYBLE_FIRMWARE_STAGED_ROOT;
    delete process.env.PYBLE_FIRMWARE_STAGED_ROOT;
    const outcomes: string[] = [];
    try {
      const missingSelectorRoot = await mkdtemp(
        join(tmpdir(), "pyble-sites-binding-missing-selector-"),
      );
      temporaryDirectories.push(missingSelectorRoot);
      await writeSitesSkeleton(missingSelectorRoot);
      delete process.env.PYBLE_FLASH_SELECTION_FILE;
      try {
        await prepareWithFirmware(
          missingSelectorRoot,
          stagedRoot,
          acceptSyntheticFixture,
        );
        outcomes.push("accepted staged root without selector");
      } catch {
        outcomes.push("rejected");
      }

      const mismatchedSelectorRoot = await mkdtemp(
        join(tmpdir(), "pyble-sites-binding-mismatched-selector-"),
      );
      temporaryDirectories.push(mismatchedSelectorRoot);
      await writeSitesSkeleton(mismatchedSelectorRoot);
      process.env.PYBLE_FLASH_SELECTION_FILE = externalSelection;
      try {
        await prepareWithFirmware(
          mismatchedSelectorRoot,
          stagedRoot,
          acceptSyntheticFixture,
        );
        outcomes.push("accepted selector outside staged root");
      } catch {
        outcomes.push("rejected");
      }

      const missingFirmwareRoot = await mkdtemp(
        join(tmpdir(), "pyble-sites-binding-missing-firmware-"),
      );
      temporaryDirectories.push(missingFirmwareRoot);
      await writeSitesSkeleton(missingFirmwareRoot);
      process.env.PYBLE_FLASH_SELECTION_FILE = join(
        stagedRoot,
        ".pyble-firmware-release-selection.json",
      );
      try {
        await prepareWithFirmware(
          missingFirmwareRoot,
          undefined,
          acceptSyntheticFixture,
        );
        outcomes.push("accepted selector without staged root");
      } catch {
        outcomes.push("rejected");
      }
    } finally {
      if (previousSelection === undefined) {
        delete process.env.PYBLE_FLASH_SELECTION_FILE;
      } else {
        process.env.PYBLE_FLASH_SELECTION_FILE = previousSelection;
      }
      if (previousStagedRoot === undefined) {
        delete process.env.PYBLE_FIRMWARE_STAGED_ROOT;
      } else {
        process.env.PYBLE_FIRMWARE_STAGED_ROOT = previousStagedRoot;
      }
    }

    expect(outcomes).toEqual(["rejected", "rejected", "rejected"]);
  });
});
