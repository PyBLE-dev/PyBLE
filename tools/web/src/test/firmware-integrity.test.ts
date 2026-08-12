// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { webcrypto } from "node:crypto";

import { describe, expect, it, vi } from "vitest";

import { verifyFirmwareProfile } from "@/lib/firmware-integrity";
import {
  createCurrentFirmwareReleaseFixture,
  createFirmwareReleaseFixture,
  firmwareOrigin,
  jsonBytes,
  type FirmwareReleaseFixture,
  type TestManifest,
  type TestRelease,
} from "@/test/fixtures/firmware-release";

interface FetchOverrides {
  redirected?: ReadonlySet<string>;
  responseUrls?: ReadonlyMap<string, string>;
}

function relativeArtifactPath(pathname: string, version: string) {
  const prefix = `/firmware/v${version}/`;
  return pathname.startsWith(prefix)
    ? pathname.slice(prefix.length)
    : undefined;
}

function inputUrl(input: RequestInfo | URL) {
  if (typeof input === "string") {
    return input;
  }
  if (input instanceof URL) {
    return input.href;
  }
  return input.url;
}

function mockFetch(
  fixture: FirmwareReleaseFixture,
  overrides: FetchOverrides = {},
) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    void init;
    const requestedUrl = new URL(inputUrl(input), firmwareOrigin);
    const relativePath = relativeArtifactPath(
      requestedUrl.pathname,
      fixture.descriptor.version,
    );
    const bytes = relativePath ? fixture.files.get(relativePath) : undefined;
    const response = new Response(bytes?.slice().buffer ?? "not found", {
      status: bytes ? 200 : 404,
      headers: {
        "Content-Type": relativePath?.endsWith(".bin")
          ? "application/octet-stream"
          : "application/json",
      },
    });

    Object.defineProperties(response, {
      redirected: {
        configurable: true,
        value: overrides.redirected?.has(relativePath ?? "") ?? false,
      },
      url: {
        configurable: true,
        value:
          overrides.responseUrls?.get(relativePath ?? "") ?? requestedUrl.href,
      },
    });
    return response;
  });
}

function verify(fixture: FirmwareReleaseFixture, fetcher = mockFetch(fixture)) {
  return verifyFirmwareProfile({
    descriptor: fixture.descriptor,
    fetcher,
    origin: firmwareOrigin,
    profileId: fixture.profileId,
    subtle: webcrypto.subtle as unknown as SubtleCrypto,
  });
}

function selectedProfile(release: TestRelease) {
  const profile = release.profiles.find(({ id }) => id === "esp32-s3-n16r8");
  if (!profile) {
    throw new Error("S3 test profile is missing");
  }
  return profile;
}

function selectedBuild(manifest: TestManifest) {
  const build = manifest.builds[0];
  if (!build) {
    throw new Error("Test manifest build is missing");
  }
  return build;
}

describe("firmware integrity verifier", () => {
  it("verifies the separate prospective v0.5.1 profile without aliasing generic S3 bytes", async () => {
    const current = createCurrentFirmwareReleaseFixture({
      deployment: "candidate",
      accessControlled: true,
      hilStatus: "pending",
    });
    const fixture = current as unknown as FirmwareReleaseFixture;
    const fetcher = mockFetch(fixture);

    await expect(
      verifyFirmwareProfile({
        descriptor: current.descriptor as unknown as Parameters<
          typeof verifyFirmwareProfile
        >[0]["descriptor"],
        fetcher,
        origin: firmwareOrigin,
        profileId: "waveshare-esp32-s3-lcd-147b" as Parameters<
          typeof verifyFirmwareProfile
        >[0]["profileId"],
        subtle: webcrypto.subtle as unknown as SubtleCrypto,
      }),
    ).resolves.toEqual({
      chipFamily: "ESP32-S3",
      firmwarePath: "/firmware/v0.5.1/waveshare-esp32-s3-lcd-147b/firmware.bin",
      manifestBuildCount: 1,
      manifestPath:
        "/firmware/v0.5.1/waveshare-esp32-s3-lcd-147b/manifest.json",
      profileId: "waveshare-esp32-s3-lcd-147b",
      version: "0.5.1",
    });
    expect(current.descriptor.profiles[2].firmwarePath).not.toBe(
      current.descriptor.profiles[1].firmwarePath,
    );
    expect(current.firmwareBytes).not.toEqual(
      current.files.get("esp32-s3-n16r8/firmware.bin"),
    );
  });

  it("verifies the exact public release root, schema, selected manifest, and merged image only", async () => {
    const fixture = createFirmwareReleaseFixture();
    const fetcher = mockFetch(fixture);

    await expect(verify(fixture, fetcher)).resolves.toEqual({
      chipFamily: "ESP32-S3",
      firmwarePath: "/firmware/v0.4.2/esp32-s3-n16r8/firmware.bin",
      manifestBuildCount: 1,
      manifestPath: "/firmware/v0.4.2/esp32-s3-n16r8/manifest.json",
      profileId: "esp32-s3-n16r8",
      version: "0.4.2",
    });
    expect(
      fetcher.mock.calls.map(([input]) => {
        const url = new URL(inputUrl(input), firmwareOrigin);
        return {
          pathname: url.pathname,
          releaseKey: url.searchParams.get("pyble_release"),
        };
      }),
    ).toEqual([
      {
        pathname: "/firmware/v0.4.2/release.json",
        releaseKey: fixture.descriptor.releaseJson.sha256,
      },
      {
        pathname: "/firmware/v0.4.2/release.schema.json",
        releaseKey: fixture.descriptor.releaseJson.sha256,
      },
      {
        pathname: "/firmware/v0.4.2/esp32-s3-n16r8/manifest.json",
        releaseKey: fixture.descriptor.releaseJson.sha256,
      },
      {
        pathname: "/firmware/v0.4.2/esp32-s3-n16r8/firmware.bin",
        releaseKey: fixture.descriptor.releaseJson.sha256,
      },
    ]);
    expect(fetcher.mock.calls.map(([, init]) => init?.cache)).toEqual([
      "reload",
      "reload",
      "reload",
      "reload",
    ]);
  });

  it("fetches the versioned release schema with redirects rejected before trusting release metadata", async () => {
    const fixture = createFirmwareReleaseFixture();
    const fetcher = mockFetch(fixture);

    await expect(verify(fixture, fetcher)).resolves.toMatchObject({
      profileId: "esp32-s3-n16r8",
    });
    const schemaCall = fetcher.mock.calls.find(([input]) => {
      return (
        new URL(inputUrl(input), firmwareOrigin).pathname ===
        "/firmware/v0.4.2/release.schema.json"
      );
    });
    expect(schemaCall).toBeDefined();
    expect(schemaCall?.[1]).toMatchObject({
      cache: "reload",
      credentials: "same-origin",
      redirect: "error",
    });
  });

  it("rejects release metadata that fails its versioned JSON Schema", async () => {
    const fixture = createFirmwareReleaseFixture();
    fixture.files.set(
      "release.schema.json",
      jsonBytes({
        $schema: "https://json-schema.org/draft/2020-12/schema",
        type: "array",
      }),
    );

    await expect(verify(fixture)).rejects.toThrow(/schema/i);
  });

  it("accepts pending HIL only for an explicitly access-controlled candidate", async () => {
    const protectedCandidate = createFirmwareReleaseFixture({
      deployment: "candidate",
      accessControlled: true,
      hilStatus: "pending",
    });
    const publicPending = createFirmwareReleaseFixture({
      deployment: "public",
      hilStatus: "pending",
    });
    const exposedCandidate = createFirmwareReleaseFixture({
      deployment: "candidate",
      accessControlled: false,
      hilStatus: "pending",
    });

    await expect(verify(protectedCandidate)).resolves.toMatchObject({
      profileId: "esp32-s3-n16r8",
      version: "0.4.2",
    });
    await expect(verify(publicPending)).rejects.toThrow();
    await expect(verify(exposedCandidate)).rejects.toThrow();
  });

  it("rejects an unknown deployment mode before fetching pending firmware", async () => {
    const fixture = createFirmwareReleaseFixture({
      hilStatus: "pending",
      mutateDescriptor: (descriptor) => {
        (descriptor as unknown as Record<string, unknown>).deployment =
          "publci";
      },
    });
    const fetcher = mockFetch(fixture);

    await expect(verify(fixture, fetcher)).rejects.toThrow(/deployment/i);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each(["1.2.3-01", "1.2.3-a..b", "1.2.3-a.", "1.2.3-.a", "1.2.3+build..1"])(
    "rejects non-canonical selected SemVer %s before any network request",
    async (version) => {
      const fixture = createFirmwareReleaseFixture({
        mutateDescriptor: (descriptor) => {
          descriptor.version = version;
          descriptor.releaseJson.path = `/firmware/v${version}/release.json`;
          descriptor.schemaPath = `/firmware/v${version}/release.schema.json`;
          descriptor.recoveryPath = `/firmware/v${version}/RECOVERY.md`;
          descriptor.profiles = structuredClone(descriptor.profiles);
          for (const profile of descriptor.profiles as unknown as Array<{
            firmwarePath: string;
            id: string;
            manifestPath: string;
          }>) {
            profile.manifestPath = `/firmware/v${version}/${profile.id}/manifest.json`;
            profile.firmwarePath = `/firmware/v${version}/${profile.id}/firmware.bin`;
          }
        },
      });
      const fetcher = mockFetch(fixture);

      await expect(verify(fixture, fetcher)).rejects.toThrow(/semver/i);
      expect(fetcher).not.toHaveBeenCalled();
    },
  );

  it("accepts only the frozen silicon-revision window for both current release profiles", async () => {
    const fixture = createFirmwareReleaseFixture();

    expect(
      fixture.release.profiles.map(({ id, silicon_revision }) => ({
        id,
        silicon_revision,
      })),
    ).toEqual([
      {
        id: "esp32-4mb",
        silicon_revision: { minimum_full: 0, maximum_full: 399 },
      },
      {
        id: "esp32-s3-n16r8",
        silicon_revision: { minimum_full: 0, maximum_full: 99 },
      },
    ]);
    await expect(verify(fixture)).resolves.toMatchObject({
      profileId: "esp32-s3-n16r8",
    });
  });

  it("rejects a public release when the non-selected current profile has stale HIL evidence", async () => {
    const fixture = createFirmwareReleaseFixture({
      hilStatus: "passed",
      profileHilStatus: { "esp32-4mb": "pending" },
    });

    await expect(verify(fixture)).rejects.toThrow();
  });

  it("rejects a release root whose bytes do not match the build-selected SHA-256", async () => {
    const fixture = createFirmwareReleaseFixture({
      mutateDescriptor: (descriptor) => {
        descriptor.releaseJson.sha256 = "0".repeat(64);
      },
    });

    await expect(verify(fixture)).rejects.toThrow();
  });

  it.each([
    "release.json",
    "release.schema.json",
    "esp32-s3-n16r8/manifest.json",
    "esp32-s3-n16r8/firmware.bin",
  ])("rejects a redirect while fetching %s", async (redirectedPath) => {
    const fixture = createFirmwareReleaseFixture();
    const fetcher = mockFetch(fixture, {
      redirected: new Set([redirectedPath]),
    });

    await expect(verify(fixture, fetcher)).rejects.toThrow();
  });

  it.each([
    {
      name: "unknown release key",
      mutate: (release: TestRelease) => {
        release.unexpected = true;
      },
    },
    {
      name: "legacy schema version",
      mutate: (release: TestRelease) => {
        release.schema_version = 1;
      },
    },
    {
      name: "missing exact profile",
      mutate: (release: TestRelease) => {
        release.profiles.pop();
      },
    },
    {
      name: "duplicate exact profile",
      mutate: (release: TestRelease) => {
        release.profiles[1] = structuredClone(release.profiles[0]);
      },
    },
    {
      name: "abbreviated source commit",
      mutate: (release: TestRelease) => {
        release.provenance.pyble.commit = "1234";
      },
    },
    {
      name: "different installer package version",
      mutate: (release: TestRelease) => {
        release.installer.version = "10.4.1";
      },
    },
    {
      name: "missing silicon revision",
      mutate: (release: TestRelease) => {
        Reflect.deleteProperty(selectedProfile(release), "silicon_revision");
      },
    },
    {
      name: "deferred C3 profile",
      mutate: (release: TestRelease) => {
        const deferred = structuredClone(release.profiles[0]);
        const identity = deferred as unknown as {
          id: string;
          chip_family: string;
        };
        identity.id = "esp32-c3-4mb";
        identity.chip_family = "ESP32-C3";
        release.profiles.push(deferred);
      },
    },
    {
      name: "wrong S3 silicon revision",
      mutate: (release: TestRelease) => {
        selectedProfile(release).silicon_revision.maximum_full = 100;
      },
    },
  ])("rejects an inexact release schema: $name", async ({ mutate }) => {
    const fixture = createFirmwareReleaseFixture({ mutateRelease: mutate });

    await expect(verify(fixture)).rejects.toThrow();
  });

  it.each([
    {
      name: "parent traversal",
      path: "../firmware.bin",
    },
    {
      name: "root absolute",
      path: "/firmware.bin",
    },
    {
      name: "cross origin",
      path: "https://example.invalid/firmware.bin",
    },
    {
      name: "query alias",
      path: "esp32-s3-n16r8/firmware.bin?latest=1",
    },
    {
      name: "backslash",
      path: String.raw`esp32-s3-n16r8\firmware.bin`,
    },
  ])("rejects an unsafe release artifact path: $name", async ({ path }) => {
    const fixture = createFirmwareReleaseFixture({
      mutateRelease: (release) => {
        selectedProfile(release).install.path = path;
      },
    });

    await expect(verify(fixture)).rejects.toThrow();
  });

  it("rejects a cross-origin selected release descriptor before requesting it", async () => {
    const fixture = createFirmwareReleaseFixture({
      mutateDescriptor: (descriptor) => {
        descriptor.releaseJson.path =
          "https://example.invalid/firmware/v0.4.2/release.json";
      },
    });
    const fetcher = mockFetch(fixture);

    await expect(verify(fixture, fetcher)).rejects.toThrow();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("rejects a response whose final URL escaped the selected immutable origin", async () => {
    const fixture = createFirmwareReleaseFixture();
    const fetcher = mockFetch(fixture, {
      responseUrls: new Map([
        ["esp32-s3-n16r8/firmware.bin", "https://example.invalid/firmware.bin"],
      ]),
    });

    await expect(verify(fixture, fetcher)).rejects.toThrow();
  });

  it.each([
    {
      name: "unknown top-level key",
      mutate: (manifest: TestManifest) => {
        Object.assign(manifest, { digest: "not-an-ESP-Web-Tools-field" });
      },
    },
    {
      name: "extra build",
      mutate: (manifest: TestManifest) => {
        manifest.builds.push(structuredClone(selectedBuild(manifest)));
      },
    },
    {
      name: "extra part",
      mutate: (manifest: TestManifest) => {
        selectedBuild(manifest).parts.push({
          path: "application.bin",
          offset: 0x10000,
        });
      },
    },
    {
      name: "wrong family",
      mutate: (manifest: TestManifest) => {
        selectedBuild(manifest).chipFamily = "ESP32";
      },
    },
    {
      name: "wrong install path",
      mutate: (manifest: TestManifest) => {
        selectedBuild(manifest).parts[0].path = "other.bin";
      },
    },
    {
      name: "unsafe install path",
      mutate: (manifest: TestManifest) => {
        selectedBuild(manifest).parts[0].path = "../firmware.bin";
      },
    },
    {
      name: "wrong offset",
      mutate: (manifest: TestManifest) => {
        selectedBuild(manifest).parts[0].offset = 4096;
      },
    },
    {
      name: "stale version",
      mutate: (manifest: TestManifest) => {
        manifest.version = "0.3.0";
      },
    },
  ])(
    "rejects a manifest that is not the selected profile's exact one-build shape: $name",
    async ({ mutate }) => {
      const fixture = createFirmwareReleaseFixture({
        mutateManifest: mutate,
      });

      await expect(verify(fixture)).rejects.toThrow();
    },
  );

  it.each([
    {
      name: "same-size corrupt firmware",
      fixture: () =>
        createFirmwareReleaseFixture({
          servedFirmware: (bytes) => {
            const corrupt = bytes.slice();
            corrupt[corrupt.length - 1] ^= 0xff;
            return corrupt;
          },
        }),
    },
    {
      name: "truncated firmware",
      fixture: () =>
        createFirmwareReleaseFixture({
          servedFirmware: (bytes) => bytes.slice(0, -1),
        }),
    },
    {
      name: "corrupt manifest",
      fixture: () =>
        createFirmwareReleaseFixture({
          servedManifest: (bytes) => {
            const corrupt = bytes.slice();
            corrupt[0] ^= 0xff;
            return corrupt;
          },
        }),
    },
    {
      name: "declared firmware size mismatch",
      fixture: () =>
        createFirmwareReleaseFixture({
          mutateRelease: (release) => {
            selectedProfile(release).install.size += 1;
          },
        }),
    },
    {
      name: "declared manifest digest mismatch",
      fixture: () =>
        createFirmwareReleaseFixture({
          mutateRelease: (release) => {
            selectedProfile(release).manifest.sha256 = "f".repeat(64);
          },
        }),
    },
  ])(
    "rejects corrupt, truncated, or mismatched bytes: $name",
    async (testCase) => {
      await expect(verify(testCase.fixture())).rejects.toThrow();
    },
  );

  it.each([
    {
      name: "release identity",
      mutate: (release: TestRelease) => {
        release.identity.version = "0.3.0";
      },
    },
    {
      name: "agent identity",
      mutate: (release: TestRelease) => {
        release.identity.agent_version = "0.3.0";
      },
    },
    {
      name: "tag identity",
      mutate: (release: TestRelease) => {
        release.identity.tag = "firmware-v0.3.0";
      },
    },
  ])("rejects stale or mismatched version state: $name", async ({ mutate }) => {
    const fixture = createFirmwareReleaseFixture({ mutateRelease: mutate });

    await expect(verify(fixture)).rejects.toThrow();
  });
});
