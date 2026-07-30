// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { describe, expect, it, vi } from "vitest";

import { installReleaseKeyedArtifactFetch } from "@/lib/firmware-fetch-cache";

const origin = "https://pyble.dev";
const releaseKey = "a".repeat(64);
const manifestPath = "/firmware/v0.4.1/esp32-4mb/manifest.json";
const firmwarePath = "/firmware/v0.4.1/esp32-4mb/firmware.bin";

function response(url: string) {
  const result = new Response("bytes");
  Object.defineProperties(result, {
    redirected: { configurable: true, value: false },
    url: { configurable: true, value: url },
  });
  return result;
}

describe("ESP Web Tools release-keyed fetch bridge", () => {
  it("rewrites only the two verified artifact paths and restores fetch", async () => {
    const nativeFetch = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        void init;
        const url =
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.href
              : input.url;
        return response(url);
      },
    );
    const scope = { fetch: nativeFetch as unknown as typeof fetch };
    const restore = installReleaseKeyedArtifactFetch({
      origin,
      paths: [manifestPath, firmwarePath],
      releaseKey,
      scope,
    });

    await scope.fetch(`${origin}${manifestPath}`);
    await scope.fetch(`${origin}${firmwarePath}`);
    await scope.fetch(`${origin}/support`);

    for (const [input, init] of nativeFetch.mock.calls.slice(0, 2)) {
      const url = new URL(
        typeof input === "string" ? input : (input as URL).href,
      );
      expect(url.searchParams.get("pyble_release")).toBe(releaseKey);
      expect(init).toMatchObject({
        cache: "reload",
        credentials: "same-origin",
        redirect: "error",
      });
    }
    expect(nativeFetch.mock.calls[2]?.[0]).toBe(`${origin}/support`);

    restore();
    expect(scope.fetch).toBe(nativeFetch);
  });

  it("rejects a redirected or mismatched release-keyed response", async () => {
    const nativeFetch = vi.fn(async () => response(`${origin}${firmwarePath}`));
    const scope = { fetch: nativeFetch as unknown as typeof fetch };
    installReleaseKeyedArtifactFetch({
      origin,
      paths: [manifestPath, firmwarePath],
      releaseKey,
      scope,
    });

    await expect(scope.fetch(`${origin}${firmwarePath}`)).rejects.toThrow(
      /transport request failed/i,
    );
  });
});
