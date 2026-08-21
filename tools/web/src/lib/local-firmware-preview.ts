// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

export const localFirmwareProfileTable = [
  {
    id: "esp32-4mb",
    label: "ESP32 · 4 MiB flash",
    selectLabel: "Classic ESP32 · 4 MiB flash",
    buildTarget: "esp32",
    chipFamily: "ESP32",
    method: "esp-web-tools",
    offset: 4096,
    group: "ESP Web Serial",
    requirements: "4 MiB external SPI flash · no PSRAM required",
    warning: "Use only for a classic ESP32 module with exactly 4 MiB flash.",
  },
  {
    id: "esp32-s3-n16r8",
    label: "ESP32-S3 · N16R8 · lean generic",
    selectLabel: "ESP32-S3 N16R8 · lean generic",
    buildTarget: "esp32-s3",
    chipFamily: "ESP32-S3",
    method: "esp-web-tools",
    offset: 0,
    group: "ESP Web Serial",
    requirements: "16 MiB flash · 8 MiB Octal PSRAM",
    warning:
      "This lean image is not for every ESP32-S3 board and includes no TFT runtime or boot splash.",
  },
  {
    id: "waveshare-esp32-s3-lcd-147b",
    label: "Waveshare ESP32-S3-LCD-1.47B · N16R8",
    selectLabel: "Waveshare ESP32-S3-LCD-1.47B · exact B version",
    buildTarget: "waveshare-esp32-s3-lcd-147b",
    chipFamily: "ESP32-S3",
    method: "esp-web-tools",
    offset: 0,
    group: "ESP Web Serial",
    requirements: "Exact B version · 16 MiB flash · 8 MiB Octal PSRAM",
    warning:
      "ESP32-S3 family detection cannot identify this board or its display wiring; confirm the exact B version.",
  },
  {
    id: "esp32-c3-4mb",
    label: "ESP32-C3 revision v0.3+ · 4 MiB flash",
    selectLabel: "ESP32-C3 · revision v0.3+ · 4 MiB",
    buildTarget: "esp32-c3",
    chipFamily: "ESP32-C3",
    method: "esp-web-tools",
    offset: 0,
    group: "ESP Web Serial",
    requirements: "Silicon revision v0.3 or newer · 4 MiB flash · no PSRAM",
    warning:
      "Engineering image only: ESP32-C3 production qualification is still pending.",
  },
  {
    id: "rpi-pico2-w",
    label: "Raspberry Pi Pico 2 W",
    selectLabel: "Raspberry Pi Pico 2 W · RP2350",
    buildTarget: "rpi-pico2-w",
    chipFamily: "RP2350",
    method: "uf2-download",
    group: "UF2 / BOOTSEL",
    requirements: "Exact Raspberry Pi Pico 2 W · RP2350 · Wi-Fi/BLE model",
    warning:
      "Engineering image only: download the verified UF2, enter BOOTSEL, and copy it to the mounted RP2350 volume.",
  },
] as const;

export type LocalFirmwareProfileId =
  (typeof localFirmwareProfileTable)[number]["id"];
export type LocalFirmwareMethod =
  (typeof localFirmwareProfileTable)[number]["method"];

export interface LocalPreviewArtifact {
  readonly path: string;
  readonly size: number;
  readonly sha256: string;
}

interface LocalPreviewProfileBase {
  readonly id: LocalFirmwareProfileId;
  readonly label: string;
  readonly chipFamily: string;
  readonly buildTarget: string;
  readonly qualified: false;
  readonly status: "engineering-preview";
  readonly firmware: LocalPreviewArtifact;
}

export interface LocalPreviewEspProfile extends LocalPreviewProfileBase {
  readonly method: "esp-web-tools";
  readonly offset: number;
  readonly manifest: LocalPreviewArtifact;
}

export interface LocalPreviewUf2Profile extends LocalPreviewProfileBase {
  readonly id: "rpi-pico2-w";
  readonly method: "uf2-download";
}

export type LocalFirmwarePreviewProfile =
  LocalPreviewEspProfile | LocalPreviewUf2Profile;

export interface LocalFirmwarePreviewDescriptor {
  readonly schemaVersion: 1;
  readonly deployment: "local-preview";
  readonly localOnly: true;
  readonly qualified: false;
  readonly version: string;
  readonly sourceCommit: string;
  readonly builtAt: string;
  readonly profiles: readonly LocalFirmwarePreviewProfile[];
}

export interface VerifiedLocalPreviewProfile {
  readonly profileId: LocalFirmwareProfileId;
  readonly method: LocalFirmwareMethod;
  readonly manifestPath?: string;
  readonly firmwarePath: string;
  readonly version: string;
  readonly downloadUrl?: string;
  readonly verifiedFirmwareBytes?: ArrayBuffer;
  readonly verifiedManifestBytes?: ArrayBuffer;
}

type Fetcher = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: string[]) {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return (
    actual.length === wanted.length &&
    actual.every((key, index) => key === wanted[index])
  );
}

function isArtifact(
  value: unknown,
  expectedPath: string,
): value is LocalPreviewArtifact {
  if (!isObject(value) || !hasExactKeys(value, ["path", "sha256", "size"])) {
    return false;
  }
  return (
    value.path === expectedPath &&
    Number.isInteger(value.size) &&
    (value.size as number) > 0 &&
    typeof value.sha256 === "string" &&
    /^[0-9a-f]{64}$/.test(value.sha256)
  );
}

function isUtcTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/.test(value) &&
    !Number.isNaN(Date.parse(value))
  );
}

function isSemver(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(
      value,
    )
  );
}

export function isLocalFirmwarePreviewDescriptor(
  value: unknown,
): value is LocalFirmwarePreviewDescriptor {
  if (
    !isObject(value) ||
    !hasExactKeys(value, [
      "builtAt",
      "deployment",
      "localOnly",
      "profiles",
      "qualified",
      "schemaVersion",
      "sourceCommit",
      "version",
    ]) ||
    value.schemaVersion !== 1 ||
    value.deployment !== "local-preview" ||
    value.localOnly !== true ||
    value.qualified !== false ||
    !isSemver(value.version) ||
    typeof value.sourceCommit !== "string" ||
    !/^[0-9a-f]{40}$/.test(value.sourceCommit) ||
    !isUtcTimestamp(value.builtAt) ||
    !Array.isArray(value.profiles) ||
    value.profiles.length !== localFirmwareProfileTable.length
  ) {
    return false;
  }

  return value.profiles.every((candidate, index) => {
    const expected = localFirmwareProfileTable[index];
    if (!expected || !isObject(candidate)) {
      return false;
    }
    const baseKeys = [
      "buildTarget",
      "chipFamily",
      "firmware",
      "id",
      "label",
      "method",
      "qualified",
      "status",
    ];
    const expectedKeys =
      expected.method === "esp-web-tools"
        ? [...baseKeys, "manifest", "offset"]
        : baseKeys;
    const extension = expected.method === "esp-web-tools" ? "bin" : "uf2";
    const root = `/.pyble-local-preview/${expected.id}`;
    return (
      hasExactKeys(candidate, expectedKeys) &&
      candidate.id === expected.id &&
      candidate.label === expected.label &&
      candidate.chipFamily === expected.chipFamily &&
      candidate.buildTarget === expected.buildTarget &&
      candidate.method === expected.method &&
      candidate.qualified === false &&
      candidate.status === "engineering-preview" &&
      isArtifact(candidate.firmware, `${root}/firmware.${extension}`) &&
      (expected.method === "uf2-download" ||
        (candidate.offset === expected.offset &&
          isArtifact(candidate.manifest, `${root}/manifest.json`)))
    );
  });
}

function hex(bytes: ArrayBuffer) {
  return [...new Uint8Array(bytes)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

async function fetchVerifiedArtifact({
  artifact,
  fetcher,
  origin,
  subtle,
}: {
  artifact: LocalPreviewArtifact;
  fetcher: Fetcher;
  origin: string;
  subtle: SubtleCrypto;
}) {
  const url = new URL(artifact.path, origin);
  if (url.origin !== origin || url.pathname !== artifact.path) {
    throw new Error("Local preview artifact path is not same-origin");
  }
  const response = await fetcher(url, {
    cache: "reload",
    credentials: "same-origin",
    redirect: "error",
  });
  if (!response.ok || response.redirected || response.url !== url.href) {
    throw new Error("Local preview artifact request failed");
  }
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength !== artifact.size) {
    throw new Error("Local preview artifact size mismatch");
  }
  const digest = hex(await subtle.digest("SHA-256", bytes));
  if (digest !== artifact.sha256) {
    throw new Error("Local preview artifact SHA-256 mismatch");
  }
  return bytes;
}

function validateRp2350Uf2(bytes: ArrayBuffer) {
  if (bytes.byteLength === 0 || bytes.byteLength % 512 !== 0) {
    throw new Error("Pico 2 W artifact is not a complete UF2 stream");
  }
  const view = new DataView(bytes);
  const rp2350Blocks: Array<{
    readonly address: number;
    readonly blockNumber: number;
    readonly payloadBytes: number;
    readonly totalBlocks: number;
  }> = [];
  let extensionBlocks = 0;
  for (let offset = 0; offset < bytes.byteLength; offset += 512) {
    if (
      view.getUint32(offset, true) !== 0x0a324655 ||
      view.getUint32(offset + 4, true) !== 0x9e5d5157 ||
      view.getUint32(offset + 508, true) !== 0x0ab16f30
    ) {
      throw new Error("Pico 2 W UF2 block magic is invalid");
    }
    const payloadBytes = view.getUint32(offset + 16, true);
    if (payloadBytes === 0 || payloadBytes > 476) {
      throw new Error("Pico 2 W UF2 payload length is invalid");
    }
    const flags = view.getUint32(offset + 8, true);
    const family = view.getUint32(offset + 28, true);
    if (flags === 0x00002000 && family === 0xe48bff59) {
      rp2350Blocks.push({
        address: view.getUint32(offset + 12, true),
        blockNumber: view.getUint32(offset + 20, true),
        payloadBytes,
        totalBlocks: view.getUint32(offset + 24, true),
      });
    } else if (
      flags === 0x0000a000 &&
      family === 0xe48bff57 &&
      view.getUint32(offset + 12, true) === 0x10ffff00 &&
      payloadBytes === 256 &&
      view.getUint32(offset + 20, true) === 0 &&
      view.getUint32(offset + 24, true) === 2
    ) {
      extensionBlocks += 1;
    } else {
      throw new Error("Pico 2 W UF2 contains an unexpected family block");
    }
  }
  if (rp2350Blocks.length === 0 || extensionBlocks !== 1) {
    throw new Error("Pico 2 W UF2 has no RP2350 Arm image blocks");
  }
  const totalBlocks = rp2350Blocks[0]?.totalBlocks ?? 0;
  const payloadBytes = rp2350Blocks[0]?.payloadBytes ?? 0;
  const baseAddress = rp2350Blocks[0]?.address ?? 0;
  if (
    totalBlocks !== rp2350Blocks.length ||
    payloadBytes !== 256 ||
    baseAddress !== 0x10000000 ||
    rp2350Blocks.some(
      (block, index) =>
        block.totalBlocks !== totalBlocks ||
        block.payloadBytes !== payloadBytes ||
        block.blockNumber !== index ||
        block.address !== baseAddress + index * payloadBytes,
    )
  ) {
    throw new Error("Pico 2 W UF2 RP2350 Arm block sequence is incomplete");
  }
}

function exactObjectKeys(
  value: unknown,
  expected: readonly string[],
): value is Record<string, unknown> {
  return isObject(value) && hasExactKeys(value, [...expected]);
}

function validateLocalEspManifest({
  bytes,
  descriptor,
  origin,
  profile,
}: {
  bytes: ArrayBuffer;
  descriptor: LocalFirmwarePreviewDescriptor;
  origin: string;
  profile: LocalPreviewEspProfile;
}) {
  const parsed: unknown = JSON.parse(new TextDecoder().decode(bytes));
  if (
    !exactObjectKeys(parsed, [
      "builds",
      "name",
      "new_install_improv_wait_time",
      "new_install_prompt_erase",
      "version",
    ]) ||
    parsed.name !== "PyBLE" ||
    parsed.version !== descriptor.version ||
    parsed.new_install_prompt_erase !== false ||
    parsed.new_install_improv_wait_time !== 0 ||
    !Array.isArray(parsed.builds) ||
    parsed.builds.length !== 1
  ) {
    throw new Error("Local ESP manifest contract is invalid");
  }
  const build = parsed.builds[0];
  if (
    !exactObjectKeys(build, ["chipFamily", "parts"]) ||
    build.chipFamily !== profile.chipFamily ||
    !Array.isArray(build.parts) ||
    build.parts.length !== 1
  ) {
    throw new Error("Local ESP manifest build is invalid");
  }
  const part = build.parts[0];
  if (
    !exactObjectKeys(part, ["offset", "path"]) ||
    typeof part.path !== "string" ||
    part.path !== "firmware.bin" ||
    part.offset !== profile.offset
  ) {
    throw new Error("Local ESP manifest part is invalid");
  }
  const manifestUrl = new URL(profile.manifest.path, origin);
  const firmwareUrl = new URL(part.path, manifestUrl);
  if (
    firmwareUrl.origin !== origin ||
    firmwareUrl.pathname !== profile.firmware.path ||
    firmwareUrl.search ||
    firmwareUrl.hash
  ) {
    throw new Error("Local ESP manifest does not bind the selected firmware");
  }
}

export async function verifyLocalFirmwarePreviewProfile({
  descriptor,
  fetcher = fetch,
  origin = globalThis.location.origin,
  profileId,
  subtle = globalThis.crypto.subtle,
}: {
  descriptor: LocalFirmwarePreviewDescriptor;
  fetcher?: Fetcher;
  origin?: string;
  profileId: LocalFirmwareProfileId;
  subtle?: SubtleCrypto;
}): Promise<VerifiedLocalPreviewProfile> {
  if (!isLocalFirmwarePreviewDescriptor(descriptor)) {
    throw new Error("Local firmware preview descriptor is invalid");
  }
  const profile = descriptor.profiles.find(({ id }) => id === profileId);
  if (!profile) {
    throw new Error("Local firmware preview profile is unavailable");
  }

  if (profile.method === "esp-web-tools") {
    const [manifestBytes, firmwareBytes] = await Promise.all([
      fetchVerifiedArtifact({
        artifact: profile.manifest,
        fetcher,
        origin,
        subtle,
      }),
      fetchVerifiedArtifact({
        artifact: profile.firmware,
        fetcher,
        origin,
        subtle,
      }),
    ]);
    validateLocalEspManifest({
      bytes: manifestBytes,
      descriptor,
      origin,
      profile,
    });
    return {
      profileId,
      method: profile.method,
      manifestPath: profile.manifest.path,
      firmwarePath: profile.firmware.path,
      version: descriptor.version,
      verifiedFirmwareBytes: firmwareBytes,
      verifiedManifestBytes: manifestBytes,
    };
  }

  const firmwareBytes = await fetchVerifiedArtifact({
    artifact: profile.firmware,
    fetcher,
    origin,
    subtle,
  });
  validateRp2350Uf2(firmwareBytes);
  const downloadUrl = URL.createObjectURL(
    new Blob([firmwareBytes], { type: "application/octet-stream" }),
  );
  return {
    profileId,
    method: profile.method,
    firmwarePath: profile.firmware.path,
    version: descriptor.version,
    downloadUrl,
    verifiedFirmwareBytes: firmwareBytes,
  };
}

export function installVerifiedLocalPreviewFetch({
  origin = globalThis.location.origin,
  profile,
  scope = globalThis,
}: {
  origin?: string;
  profile: VerifiedLocalPreviewProfile;
  scope?: { fetch: typeof fetch };
}) {
  if (
    profile.method !== "esp-web-tools" ||
    !profile.manifestPath ||
    !profile.verifiedManifestBytes ||
    !profile.verifiedFirmwareBytes
  ) {
    throw new Error("Verified local ESP bytes are unavailable");
  }
  const exactBytes = new Map<string, { bytes: ArrayBuffer; type: string }>([
    [
      profile.manifestPath,
      { bytes: profile.verifiedManifestBytes, type: "application/json" },
    ],
    [
      profile.firmwarePath,
      {
        bytes: profile.verifiedFirmwareBytes,
        type: "application/octet-stream",
      },
    ],
  ]);
  const originalFetch = scope.fetch;
  const verifiedFetch: typeof fetch = async (input, init) => {
    const requested = new URL(
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url,
      origin,
    );
    const artifact =
      requested.origin === origin && !requested.search && !requested.hash
        ? exactBytes.get(requested.pathname)
        : undefined;
    if (!artifact) {
      return originalFetch.call(scope, input, init);
    }
    if (init?.signal?.aborted) {
      throw init.signal.reason;
    }
    return new Response(artifact.bytes.slice(0), {
      status: 200,
      headers: { "Content-Type": artifact.type },
    });
  };
  scope.fetch = verifiedFetch;
  return () => {
    if (scope.fetch === verifiedFetch) {
      scope.fetch = originalFetch;
    }
  };
}

export function isLoopbackHostname(hostname: string) {
  return (
    hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]"
  );
}
