// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

interface FetchScope {
  fetch: typeof fetch;
}

interface InstallReleaseKeyedFetchOptions {
  readonly origin?: string;
  readonly paths: readonly string[];
  readonly releaseKey: string;
  readonly scope?: FetchScope;
}

function inputUrl(input: RequestInfo | URL, origin: string) {
  if (typeof input === "string") {
    return new URL(input, origin);
  }
  if (input instanceof URL) {
    return new URL(input.href);
  }
  return new URL(input.url);
}

export function installReleaseKeyedArtifactFetch({
  origin = globalThis.location.origin,
  paths,
  releaseKey,
  scope = globalThis,
}: InstallReleaseKeyedFetchOptions) {
  if (!/^[0-9a-f]{64}$/.test(releaseKey)) {
    throw new Error("Firmware release cache key is invalid");
  }
  const allowedPaths = new Set(paths);
  if (
    allowedPaths.size !== paths.length ||
    paths.some((path) => {
      const url = new URL(path, origin);
      return (
        url.origin !== origin ||
        url.pathname !== path ||
        Boolean(url.search || url.hash)
      );
    })
  ) {
    throw new Error(
      "Firmware cache paths must be unique exact same-origin paths",
    );
  }

  const originalFetch = scope.fetch;
  const releaseFetch: typeof fetch = async (input, init) => {
    const requested = inputUrl(input, origin);
    if (
      requested.origin !== origin ||
      requested.search ||
      requested.hash ||
      !allowedPaths.has(requested.pathname)
    ) {
      return originalFetch.call(scope, input, init);
    }

    requested.searchParams.set("pyble_release", releaseKey);
    const keyedInput =
      typeof input === "string"
        ? requested.href
        : input instanceof URL
          ? requested
          : new Request(requested, input);
    const response = await originalFetch.call(scope, keyedInput, {
      ...init,
      cache: "reload",
      credentials: "same-origin",
      redirect: "error",
    });
    if (
      !response.ok ||
      response.redirected ||
      response.url !== requested.href
    ) {
      throw new Error("Verified firmware transport request failed");
    }
    return response;
  };

  scope.fetch = releaseFetch;
  return () => {
    if (scope.fetch === releaseFetch) {
      scope.fetch = originalFetch;
    }
  };
}
