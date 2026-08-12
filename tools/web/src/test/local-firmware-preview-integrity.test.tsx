// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { createHash } from "node:crypto";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FlashStatus } from "@/components/flash-status";
import {
  installVerifiedLocalPreviewFetch,
  localFirmwareProfileTable,
  verifyLocalFirmwarePreviewProfile,
  type LocalFirmwarePreviewDescriptor,
} from "@/lib/local-firmware-preview";

function digest(bytes: Uint8Array) {
  return createHash("sha256").update(bytes).digest("hex");
}

function fixtureDescriptor({
  firmware,
  manifest,
}: {
  firmware: Uint8Array;
  manifest: Uint8Array;
}): LocalFirmwarePreviewDescriptor {
  return {
    schemaVersion: 1,
    deployment: "local-preview",
    localOnly: true,
    qualified: false,
    version: "0.6.0",
    sourceCommit: "e895a33642627401dbae5c8bd8110802ab143900",
    builtAt: "2026-08-12T00:00:00.000Z",
    profiles: localFirmwareProfileTable.map((profile) => {
      const root = `/.pyble-local-preview/${profile.id}`;
      const artifact =
        profile.id === "esp32-4mb"
          ? { size: firmware.byteLength, sha256: digest(firmware) }
          : { size: 1, sha256: "a".repeat(64) };
      const base = {
        id: profile.id,
        label: profile.label,
        chipFamily: profile.chipFamily,
        buildTarget: profile.buildTarget,
        method: profile.method,
        qualified: false as const,
        status: "engineering-preview" as const,
        firmware: {
          path: `${root}/firmware.${profile.method === "esp-web-tools" ? "bin" : "uf2"}`,
          ...artifact,
        },
      };
      return profile.method === "esp-web-tools"
        ? {
            ...base,
            method: profile.method,
            offset: profile.offset,
            manifest: {
              path: `${root}/manifest.json`,
              size: profile.id === "esp32-4mb" ? manifest.byteLength : 1,
              sha256:
                profile.id === "esp32-4mb" ? digest(manifest) : "b".repeat(64),
            },
          }
        : { ...base, id: profile.id, method: profile.method };
    }),
  };
}

function exactResponse(bytes: Uint8Array, url: string) {
  const body = bytes.buffer.slice(
    bytes.byteOffset,
    bytes.byteOffset + bytes.byteLength,
  ) as ArrayBuffer;
  const response = new Response(body, { status: 200 });
  Object.defineProperty(response, "url", { value: url });
  return response;
}

describe("local firmware preview integrity", () => {
  it("accepts the staged relative ESP manifest only after verifying both exact artifacts", async () => {
    const firmware = Uint8Array.from([0xe9, 0x50, 0x42, 0x4c, 0x45]);
    const manifest = new TextEncoder().encode(
      JSON.stringify({
        name: "PyBLE",
        version: "0.6.0",
        new_install_prompt_erase: false,
        new_install_improv_wait_time: 0,
        builds: [
          {
            chipFamily: "ESP32",
            parts: [{ path: "firmware.bin", offset: 4096 }],
          },
        ],
      }),
    );
    const descriptor = fixtureDescriptor({ firmware, manifest });
    const origin = "http://127.0.0.1:3000";
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(input.toString());
      if (url.pathname.endsWith("/manifest.json")) {
        return exactResponse(manifest, url.href);
      }
      return exactResponse(firmware, url.href);
    });

    const verified = await verifyLocalFirmwarePreviewProfile({
      descriptor,
      fetcher,
      origin,
      profileId: "esp32-4mb",
      subtle: globalThis.crypto.subtle,
    });
    expect(verified).toMatchObject({
      profileId: "esp32-4mb",
      method: "esp-web-tools",
      manifestPath: "/.pyble-local-preview/esp32-4mb/manifest.json",
      firmwarePath: "/.pyble-local-preview/esp32-4mb/firmware.bin",
      version: "0.6.0",
    });
    expect(
      Array.from(new Uint8Array(verified.verifiedManifestBytes ?? [])),
    ).toEqual(Array.from(manifest));
    expect(
      Array.from(new Uint8Array(verified.verifiedFirmwareBytes ?? [])),
    ).toEqual(Array.from(firmware));
    expect(fetcher).toHaveBeenCalledTimes(2);

    const originalFetch = vi.fn(async () => new Response("changed on disk"));
    const scope = { fetch: originalFetch as typeof fetch };
    const cleanup = installVerifiedLocalPreviewFetch({
      origin,
      profile: verified,
      scope,
    });
    await expect(
      scope
        .fetch("/.pyble-local-preview/esp32-4mb/firmware.bin")
        .then((response) => response.arrayBuffer())
        .then((bytes) => Array.from(new Uint8Array(bytes))),
    ).resolves.toEqual(Array.from(firmware));
    expect(originalFetch).not.toHaveBeenCalled();
    cleanup();
    expect(scope.fetch).toBe(originalFetch);
  });

  it("keeps the source identity, digest, destructive effect, and next action visible", () => {
    const firmware = Uint8Array.from([0xe9, 0x50, 0x42, 0x4c, 0x45]);
    const manifest = Uint8Array.from([0x7b, 0x7d]);
    const descriptor = fixtureDescriptor({ firmware, manifest });

    render(
      <FlashStatus
        capabilities={{
          secureContext: true,
          webCrypto: true,
          webSerial: true,
        }}
        preview={descriptor}
        release={null}
      />,
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: /choose a firmware target/i }),
      { target: { value: "esp32-4mb" } },
    );
    const details = screen.getByRole("region", {
      name: /selected firmware target details/i,
    });

    expect(details).toHaveTextContent(descriptor.sourceCommit);
    expect(details).toHaveTextContent(
      descriptor.profiles[0]?.firmware.sha256 ?? "",
    );
    expect(details).toHaveTextContent(/overwrite|erase/i);
    expect(details).toHaveTextContent(/verify.*install/i);
  });
});
