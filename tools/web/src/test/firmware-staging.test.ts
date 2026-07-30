// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { execFile as execFileCallback } from "node:child_process";
import {
  chmod,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
import { promisify } from "node:util";

import { afterEach, describe, expect, it } from "vitest";

import { stageFirmwareRelease } from "../../scripts/stage-firmware-release";
import {
  bundleFiles,
  createFirmwareReleaseFixture,
  jsonBytes,
  sha256,
  type FirmwareReleaseFixture,
} from "@/test/fixtures/firmware-release";

const temporaryDirectories: string[] = [];
const acceptSyntheticFixture = async () => undefined;

function stageFixture(
  options: Omit<Parameters<typeof stageFirmwareRelease>[0], "releaseValidator">,
) {
  return stageFirmwareRelease({
    ...options,
    releaseValidator: acceptSyntheticFixture,
  });
}
const execFile = promisify(execFileCallback);

afterEach(async () => {
  await Promise.all(
    temporaryDirectories
      .splice(0)
      .map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

async function temporaryDirectory(label: string) {
  const directory = await mkdtemp(join(tmpdir(), `pyble-${label}-`));
  temporaryDirectories.push(directory);
  return directory;
}

async function writeExternalBundle(
  directory: string,
  fixture: FirmwareReleaseFixture,
) {
  for (const [relativePath, bytes] of bundleFiles(fixture)) {
    const path = join(directory, relativePath);
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, bytes);
  }
}

function rewriteFixtureVersion(
  fixture: FirmwareReleaseFixture,
  version: string,
) {
  fixture.release.identity.version = version;
  fixture.release.identity.tag = `firmware-v${version}`;
  fixture.release.identity.agent_version = version;

  for (const profile of fixture.release.profiles) {
    const manifestBytes = fixture.files.get(profile.manifest.path);
    if (!manifestBytes) {
      throw new Error(`Fixture manifest is missing: ${profile.manifest.path}`);
    }
    const manifest = JSON.parse(
      new TextDecoder().decode(manifestBytes),
    ) as Record<string, unknown>;
    manifest.version = version;
    const rewrittenManifest = jsonBytes(manifest);
    fixture.files.set(profile.manifest.path, rewrittenManifest);
    profile.manifest.size = rewrittenManifest.byteLength;
    profile.manifest.sha256 = sha256(rewrittenManifest);
  }

  fixture.files.set("release.json", jsonBytes(fixture.release));
  return fixture;
}

describe("external firmware bundle staging", () => {
  it("validates and stages an explicit all-HIL-passed public bundle outside the source tree", async () => {
    const fixture = createFirmwareReleaseFixture();
    const bundleDirectory = await temporaryDirectory("release-bundle");
    const outputDirectory = await temporaryDirectory("staged-public");
    await writeExternalBundle(bundleDirectory, fixture);

    await expect(
      stageFixture({
        accessControlled: false,
        bundleDirectory,
        deployment: "public",
        outputDirectory,
      }),
    ).resolves.toEqual(fixture.descriptor);
    await expect(
      readFile(
        join(
          outputDirectory,
          "firmware",
          "v0.4.1",
          "esp32-s3-n16r8",
          "manifest.json",
        ),
      ).then((value) => Array.from(value)),
    ).resolves.toEqual(Array.from(fixture.manifestBytes));
    await expect(
      readFile(
        join(
          outputDirectory,
          "firmware",
          "v0.4.1",
          "esp32-s3-n16r8",
          "firmware.bin",
        ),
      ).then((value) => Array.from(value)),
    ).resolves.toEqual(Array.from(fixture.firmwareBytes));
    await expect(
      readdir(join(outputDirectory, "firmware", "v0.4.1")),
    ).resolves.not.toContain("esp32-c3-4mb");
    expect(fixture.descriptor.profiles.map(({ id }) => id)).toEqual([
      "esp32-4mb",
      "esp32-s3-n16r8",
    ]);
    expect(outputDirectory).not.toBe(join(process.cwd(), "public"));
  });

  it("allows pending HIL only when candidate mode and access control are both explicit", async () => {
    const fixture = createFirmwareReleaseFixture({
      deployment: "candidate",
      accessControlled: true,
      hilStatus: "pending",
    });
    const bundleDirectory = await temporaryDirectory("candidate-bundle");
    await writeExternalBundle(bundleDirectory, fixture);

    await expect(
      stageFixture({
        accessControlled: true,
        bundleDirectory,
        deployment: "candidate",
        outputDirectory: await temporaryDirectory("protected-candidate"),
      }),
    ).resolves.toMatchObject({
      accessControlled: true,
      deployment: "candidate",
      hilStatus: "pending",
      version: "0.4.1",
    });
    await expect(
      stageFixture({
        accessControlled: false,
        bundleDirectory,
        deployment: "candidate",
        outputDirectory: await temporaryDirectory("exposed-candidate"),
      }),
    ).rejects.toThrow();
    await expect(
      stageFixture({
        accessControlled: false,
        bundleDirectory,
        deployment: "public",
        outputDirectory: await temporaryDirectory("public-pending"),
      }),
    ).rejects.toThrow();
  });

  it("rejects external bytes that no longer match the generated bundle checksums", async () => {
    const fixture = createFirmwareReleaseFixture();
    const bundleDirectory = await temporaryDirectory("corrupt-bundle");
    const outputDirectory = await temporaryDirectory("corrupt-output");
    await writeExternalBundle(bundleDirectory, fixture);
    await writeFile(
      join(bundleDirectory, "esp32-s3-n16r8", "firmware.bin"),
      new Uint8Array([0xe9]),
    );

    await expect(
      stageFixture({
        accessControlled: false,
        bundleDirectory,
        deployment: "public",
        outputDirectory,
      }),
    ).rejects.toThrow();
  });

  it("rejects an external public bundle if either current profile is still pending", async () => {
    const fixture = createFirmwareReleaseFixture({
      hilStatus: "passed",
      profileHilStatus: { "esp32-4mb": "pending" },
    });
    const bundleDirectory = await temporaryDirectory("stale-hil-bundle");
    await writeExternalBundle(bundleDirectory, fixture);

    await expect(
      stageFixture({
        accessControlled: false,
        bundleDirectory,
        deployment: "public",
        outputDirectory: await temporaryDirectory("stale-hil-output"),
      }),
    ).rejects.toThrow();
  });

  it("rejects a release that does not validate against its versioned JSON Schema", async () => {
    const fixture = createFirmwareReleaseFixture();
    fixture.files.set(
      "release.schema.json",
      jsonBytes({
        $schema: "https://json-schema.org/draft/2020-12/schema",
        type: "array",
      }),
    );
    const bundleDirectory = await temporaryDirectory("schema-mismatch-bundle");
    await writeExternalBundle(bundleDirectory, fixture);

    await expect(
      stageFixture({
        accessControlled: false,
        bundleDirectory,
        deployment: "public",
        outputDirectory: await temporaryDirectory("schema-mismatch-output"),
      }),
    ).rejects.toThrow(/schema/i);
  });

  it("rejects missing release-license and HIL evidence even when SHA256SUMS exactly covers the remaining files", async () => {
    const fixture = createFirmwareReleaseFixture();
    fixture.files.delete("THIRD_PARTY_LICENSES.txt");
    fixture.files.delete("HIL_REPORT.md");
    const bundleDirectory = await temporaryDirectory("missing-evidence-bundle");
    await writeExternalBundle(bundleDirectory, fixture);

    await expect(
      stageFixture({
        accessControlled: false,
        bundleDirectory,
        deployment: "public",
        outputDirectory: await temporaryDirectory("missing-evidence-output"),
      }),
    ).rejects.toThrow(/(?:license|hil|document|evidence)/i);
  });

  it("rejects invalid provenance and component evidence instead of trusting self-consistent checksums", async () => {
    const fixture = createFirmwareReleaseFixture({
      mutateRelease: (release) => {
        release.provenance.micropython.commit = "unknown";
        release.profiles[0]!.components[0]!.sha256 = "0".repeat(64);
      },
    });
    const bundleDirectory = await temporaryDirectory("invalid-evidence-bundle");
    await writeExternalBundle(bundleDirectory, fixture);

    await expect(
      stageFixture({
        accessControlled: false,
        bundleDirectory,
        deployment: "public",
        outputDirectory: await temporaryDirectory("invalid-evidence-output"),
      }),
    ).rejects.toThrow(/(?:provenance|commit|component)/i);
  });

  it.each(["1.2.3-01", "1.2.3-a..b", "1.2.3-a.", "1.2.3-.a", "1.2.3+build..1"])(
    "rejects non-canonical SemVer %s before staging",
    async (version) => {
      const fixture = rewriteFixtureVersion(
        createFirmwareReleaseFixture(),
        version,
      );
      const bundleDirectory = await temporaryDirectory(
        "invalid-semver-release-bundle",
      );
      await writeExternalBundle(bundleDirectory, fixture);

      await expect(
        stageFixture({
          accessControlled: false,
          bundleDirectory,
          deployment: "public",
          outputDirectory: await temporaryDirectory("invalid-semver-output"),
        }),
      ).rejects.toThrow(/(?:semver|version|schema)/i);
    },
  );

  it("accepts canonical prerelease and build SemVer during staging", async () => {
    const version = "1.2.3-alpha.1+build.01";
    const fixture = rewriteFixtureVersion(
      createFirmwareReleaseFixture(),
      version,
    );
    const bundleDirectory = await temporaryDirectory(
      "canonical-semver-release-bundle",
    );
    await writeExternalBundle(bundleDirectory, fixture);

    await expect(
      stageFixture({
        accessControlled: false,
        bundleDirectory,
        deployment: "public",
        outputDirectory: await temporaryDirectory("canonical-semver-output"),
      }),
    ).resolves.toMatchObject({ version });
  });

  it("publishes a canonical SemVer pattern in the frozen release schema", async () => {
    const schema = JSON.parse(
      await readFile(
        join(process.cwd(), "src", "lib", "firmware-release-schema.json"),
        "utf8",
      ),
    ) as {
      properties?: {
        identity?: {
          properties?: {
            version?: {
              pattern?: string;
            };
          };
        };
      };
    };
    const pattern = schema.properties?.identity?.properties?.version?.pattern;

    expect(pattern).toBeTypeOf("string");
    if (typeof pattern !== "string") {
      return;
    }
    const releaseVersion = new RegExp(pattern);
    for (const version of [
      "0.0.0",
      "1.2.3-alpha.1+build.01",
      "10.20.30-0.3.7",
    ]) {
      expect.soft(releaseVersion.test(version), version).toBe(true);
    }
    for (const version of [
      "1.2.3-01",
      "1.2.3-a..b",
      "1.2.3-a.",
      "1.2.3-.a",
      "1.2.3+build..1",
    ]) {
      expect.soft(releaseVersion.test(version), version).toBe(false);
    }
  });

  it("freezes release schema version 2 to exactly the two currently qualified profiles", async () => {
    const schema = JSON.parse(
      await readFile(
        join(process.cwd(), "src", "lib", "firmware-release-schema.json"),
        "utf8",
      ),
    ) as {
      properties?: {
        schema_version?: { const?: unknown };
        profiles?: {
          minItems?: unknown;
          maxItems?: unknown;
          items?: {
            properties?: {
              id?: { enum?: unknown[] };
            };
          };
        };
      };
    };

    expect(schema.properties?.schema_version?.const).toBe(2);
    expect(schema.properties?.profiles).toMatchObject({
      minItems: 2,
      maxItems: 2,
    });
    expect(schema.properties?.profiles?.items?.properties?.id?.enum).toEqual([
      "esp32-4mb",
      "esp32-s3-n16r8",
    ]);
    expect(JSON.stringify(schema)).not.toContain("esp32-c3-4mb");
  });

  it("makes the production CLI invoke the canonical validator for both public and candidate bundles", async () => {
    const stagingScript = join(
      process.cwd(),
      "scripts",
      "stage-firmware-release.js",
    );
    const stagingSource = await readFile(stagingScript, "utf8");

    expect.soft(stagingSource).toContain("release_bundle.py");
    expect.soft(stagingSource).toMatch(/["']validate["']/);
    expect.soft(stagingSource).toMatch(/["']--public["']/);
    expect.soft(stagingSource).toContain("PYBLE_FIRMWARE_LICENSE_EVIDENCE_DIR");
    expect.soft(stagingSource).toContain("PYBLE_FIRMWARE_LICENSE_BUILD_ROOT");
    expect.soft(stagingSource).toContain("--license-evidence-dir");
    expect.soft(stagingSource).toContain("--license-build-root");
    expect.soft(stagingSource).toContain("--repo-root");

    for (const deployment of ["public", "candidate"] as const) {
      const fixture = createFirmwareReleaseFixture({
        deployment,
        accessControlled: deployment === "candidate",
        hilStatus: deployment === "candidate" ? "pending" : "passed",
      });
      const bundleDirectory = await temporaryDirectory(
        `${deployment}-canonical-validator-bundle`,
      );
      const outputDirectory = await temporaryDirectory(
        `${deployment}-canonical-validator-output`,
      );
      await writeExternalBundle(bundleDirectory, fixture);

      let rejected = false;
      try {
        await execFile(process.execPath, [stagingScript], {
          cwd: process.cwd(),
          env: {
            ...process.env,
            PYBLE_FIRMWARE_BUNDLE_DIR: bundleDirectory,
            PYBLE_FIRMWARE_OUTPUT_DIR: outputDirectory,
            PYBLE_FLASH_ACCESS_CONTROLLED:
              deployment === "candidate" ? "1" : "0",
            PYBLE_FLASH_DEPLOYMENT: deployment,
          },
        });
      } catch {
        rejected = true;
      }
      expect
        .soft(
          rejected,
          `${deployment} CLI staging accepted self-consistent seven-byte fake firmware`,
        )
        .toBe(true);
    }
  });

  it("requires public-grade license evidence when canonically validating a protected candidate", async () => {
    const stagingScript = join(
      process.cwd(),
      "scripts",
      "stage-firmware-release.js",
    );
    const repositoryRoot = join(process.cwd(), "..", "..");
    const bundleDirectory = await temporaryDirectory(
      "candidate-license-validation-bundle",
    );
    const licenseEvidenceDirectory = await temporaryDirectory(
      "candidate-license-evidence",
    );
    const licenseBuildRoot = await temporaryDirectory(
      "candidate-license-build",
    );
    const fakeBin = await temporaryDirectory("candidate-validator-bin");
    const fakePython = join(fakeBin, "python3");
    await writeFile(
      fakePython,
      [
        "#!/bin/sh",
        'printf "%s\\n" "$@" > "${PYBLE_TEST_VALIDATOR_CAPTURE}"',
        "",
      ].join("\n"),
      "utf8",
    );
    await chmod(fakePython, 0o755);

    const validationProgram = [
      `const staging = await import(${JSON.stringify(pathToFileURL(stagingScript).href)});`,
      `await staging.validateWithCanonicalReleaseTool(${JSON.stringify(bundleDirectory)}, "candidate");`,
    ].join("\n");
    const validationEnvironment: NodeJS.ProcessEnv = {
      ...process.env,
      PATH: `${fakeBin}:${process.env.PATH ?? ""}`,
    };
    delete validationEnvironment.PYBLE_FIRMWARE_LICENSE_EVIDENCE_DIR;
    delete validationEnvironment.PYBLE_FIRMWARE_LICENSE_BUILD_ROOT;

    for (const [label, evidenceEnvironment] of [
      ["both evidence inputs", {}],
      [
        "the exact build root",
        {
          PYBLE_FIRMWARE_LICENSE_EVIDENCE_DIR: licenseEvidenceDirectory,
        },
      ],
      [
        "the retained evidence directory",
        {
          PYBLE_FIRMWARE_LICENSE_BUILD_ROOT: licenseBuildRoot,
        },
      ],
    ] as const) {
      let rejected = false;
      try {
        await execFile(
          process.execPath,
          ["--input-type=module", "--eval", validationProgram],
          {
            cwd: process.cwd(),
            env: {
              ...validationEnvironment,
              ...evidenceEnvironment,
              PYBLE_TEST_VALIDATOR_CAPTURE: join(
                fakeBin,
                `missing-${label.replaceAll(" ", "-")}.txt`,
              ),
            },
          },
        );
      } catch {
        rejected = true;
      }
      expect
        .soft(
          rejected,
          `protected candidate validation accepted without ${label}`,
        )
        .toBe(true);
    }

    const captureFile = join(fakeBin, "candidate-arguments.txt");
    await execFile(
      process.execPath,
      ["--input-type=module", "--eval", validationProgram],
      {
        cwd: process.cwd(),
        env: {
          ...validationEnvironment,
          PYBLE_FIRMWARE_LICENSE_BUILD_ROOT: licenseBuildRoot,
          PYBLE_FIRMWARE_LICENSE_EVIDENCE_DIR: licenseEvidenceDirectory,
          PYBLE_TEST_VALIDATOR_CAPTURE: captureFile,
        },
      },
    );
    const arguments_ = (await readFile(captureFile, "utf8"))
      .trimEnd()
      .split("\n");

    expect.soft(arguments_).not.toContain("--public");
    expect.soft(arguments_).toContain("--license-evidence-dir");
    expect
      .soft(arguments_[arguments_.indexOf("--license-evidence-dir") + 1])
      .toBe(licenseEvidenceDirectory);
    expect.soft(arguments_).toContain("--license-build-root");
    expect
      .soft(arguments_[arguments_.indexOf("--license-build-root") + 1])
      .toBe(licenseBuildRoot);
    expect.soft(arguments_).toContain("--repo-root");
    expect
      .soft(arguments_[arguments_.indexOf("--repo-root") + 1])
      .toBe(repositoryRoot);
  });

  it("leaves no finalized version or selector when final staged-root validation fails", async () => {
    const fixture = createFirmwareReleaseFixture();
    const realBundleDirectory = await temporaryDirectory("real-release-bundle");
    const symlinkParent = await temporaryDirectory("linked-release-parent");
    const linkedBundleDirectory = join(symlinkParent, "release-bundle");
    const outputDirectory = await temporaryDirectory("atomic-stage-output");
    await writeExternalBundle(realBundleDirectory, fixture);
    await symlink(realBundleDirectory, linkedBundleDirectory, "dir");

    await expect(
      stageFixture({
        accessControlled: false,
        bundleDirectory: linkedBundleDirectory,
        deployment: "public",
        outputDirectory,
      }),
    ).rejects.toThrow();
    await expect(readdir(outputDirectory)).resolves.toEqual([]);
  });

  it("revalidates the complete staged root before any deployment packages it", async () => {
    const fixture = createFirmwareReleaseFixture({
      deployment: "candidate",
      accessControlled: true,
      hilStatus: "pending",
    });
    const bundleDirectory = await temporaryDirectory("candidate-source");
    const stagedRoot = await temporaryDirectory("candidate-staged");
    await writeExternalBundle(bundleDirectory, fixture);
    const descriptor = await stageFixture({
      accessControlled: true,
      bundleDirectory,
      deployment: "candidate",
      outputDirectory: stagedRoot,
    });

    const stagingModule =
      (await import("../../scripts/stage-firmware-release")) as unknown as {
        validateStagedFirmwareRelease?: (
          stagedRoot: string,
          options: {
            releaseValidator: typeof acceptSyntheticFixture;
          },
        ) => Promise<typeof descriptor>;
      };
    expect(
      stagingModule.validateStagedFirmwareRelease,
      "deployment needs a fresh validation seam, not trust in an earlier staging run",
    ).toBeTypeOf("function");
    if (!stagingModule.validateStagedFirmwareRelease) {
      return;
    }

    await expect(
      stagingModule.validateStagedFirmwareRelease(stagedRoot, {
        releaseValidator: acceptSyntheticFixture,
      }),
    ).resolves.toEqual(descriptor);

    await writeFile(
      join(stagedRoot, "firmware", "v0.4.1", "release.json"),
      new Uint8Array([0x7b, 0x7d, 0x0a]),
    );
    await expect(
      stagingModule.validateStagedFirmwareRelease(stagedRoot, {
        releaseValidator: acceptSyntheticFixture,
      }),
    ).rejects.toThrow();
  });

  it("requires explicit published-GitHub evidence with byte equality before public activation", async () => {
    const fixture = createFirmwareReleaseFixture();
    const bundleDirectory = await temporaryDirectory(
      "published-evidence-source",
    );
    const stagedRoot = await temporaryDirectory("published-evidence-staged");
    const publishedBundleDirectory = await temporaryDirectory(
      "published-evidence-github",
    );
    await writeExternalBundle(bundleDirectory, fixture);
    await writeExternalBundle(publishedBundleDirectory, fixture);
    const descriptor = await stageFixture({
      accessControlled: false,
      bundleDirectory,
      deployment: "public",
      outputDirectory: stagedRoot,
    });

    const stagingModule =
      (await import("../../scripts/stage-firmware-release")) as unknown as {
        validatePublishedFirmwareRelease?: (
          stagedRoot: string,
          options: {
            publishedBundleDirectory: string;
            releaseValidator: typeof acceptSyntheticFixture;
          },
        ) => Promise<typeof descriptor>;
      };
    const validatePublished = stagingModule.validatePublishedFirmwareRelease;
    expect
      .soft(
        validatePublished,
        "public activation needs an injectable local evidence boundary for GitHub release bytes",
      )
      .toBeTypeOf("function");
    if (!validatePublished) {
      return;
    }

    await expect(
      validatePublished(stagedRoot, {
        publishedBundleDirectory,
        releaseValidator: acceptSyntheticFixture,
      }),
    ).resolves.toEqual(descriptor);

    await writeFile(
      join(publishedBundleDirectory, "esp32-s3-n16r8", "firmware.bin"),
      new Uint8Array([0xe9, 0xff]),
    );
    await expect(
      validatePublished(stagedRoot, {
        publishedBundleDirectory,
        releaseValidator: acceptSyntheticFixture,
      }),
    ).rejects.toThrow(/(?:github|published|byte|digest|checksum)/i);

    await expect(
      validatePublished(stagedRoot, {
        publishedBundleDirectory: join(
          publishedBundleDirectory,
          "missing-evidence",
        ),
        releaseValidator: acceptSyntheticFixture,
      }),
    ).rejects.toThrow(/(?:github|published|evidence|missing)/i);
  });
});
