// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { readFile } from "node:fs/promises";
import { join } from "node:path";
import type { ComponentType } from "react";

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FlashStatus } from "@/components/flash-status";
import type {
  FirmwareProfileId,
  FirmwareReleaseDescriptor,
} from "@/lib/firmware-release";
import {
  currentPendingCandidateFirmwareRelease,
  currentPendingPublicFirmwareRelease,
  currentUncontrolledCandidateFirmwareRelease,
  firmwareProfiles,
  hypotheticalPassedPublicFirmwareRelease,
  installerConsents,
  pendingPublicFirmwareRelease,
  publicBetaFirmwareRelease,
  verifiedProfile,
} from "@/test/fixtures/firmware-release";

interface BrowserCapabilities {
  secureContext: boolean;
  webSerial: boolean;
  webCrypto: boolean;
}

interface VerifiedProfile {
  profileId: FirmwareProfileId;
  chipFamily: string;
  manifestPath: string;
  manifestBuildCount: 1;
  firmwarePath: string;
  version: string;
}

type LocalPreviewProfileId =
  | "esp32-4mb"
  | "esp32-s3-n16r8"
  | "waveshare-esp32-s3-lcd-147b"
  | "esp32-c3-4mb"
  | "rpi-pico2-w";

type LocalPreviewMethod = "esp-web-tools" | "uf2-download";

interface LocalPreviewProfile {
  id: LocalPreviewProfileId;
  label: string;
  chipFamily: string;
  buildTarget: string;
  method: LocalPreviewMethod;
  qualified: false;
  status: "engineering-preview";
  offset?: number;
  manifest?: PreviewArtifact;
  firmware: PreviewArtifact;
}

interface PreviewArtifact {
  path: string;
  size: number;
  sha256: string;
}

interface LocalFirmwarePreviewDescriptor {
  schemaVersion: 1;
  deployment: "local-preview";
  localOnly: true;
  qualified: false;
  version: string;
  sourceCommit: string;
  builtAt: string;
  profiles: readonly LocalPreviewProfile[];
}

interface VerifiedLocalPreviewProfile {
  profileId: LocalPreviewProfileId;
  method: LocalPreviewMethod;
  manifestPath?: string;
  firmwarePath: string;
  downloadUrl?: string;
  version: string;
}

interface FlashStatusContractProps {
  capabilities?: BrowserCapabilities;
  installArtifactFetch?: (
    profile: VerifiedProfile,
    releaseKey: string,
  ) => () => void;
  loadInstaller?: () => Promise<void>;
  preview?: LocalFirmwarePreviewDescriptor | null;
  release?: FirmwareReleaseDescriptor | null;
  verifyProfile?: (
    release: FirmwareReleaseDescriptor,
    profileId: FirmwareProfileId,
  ) => Promise<VerifiedProfile>;
  verifyPreviewProfile?: (
    preview: LocalFirmwarePreviewDescriptor,
    profileId: LocalPreviewProfileId,
  ) => Promise<VerifiedLocalPreviewProfile>;
}

const InstallerUnderTest =
  FlashStatus as ComponentType<FlashStatusContractProps>;

const supportedCapabilities: BrowserCapabilities = {
  secureContext: true,
  webSerial: true,
  webCrypto: true,
};

const localFirmwarePreview: LocalFirmwarePreviewDescriptor = {
  schemaVersion: 1,
  deployment: "local-preview",
  localOnly: true,
  qualified: false,
  version: "0.6.0",
  sourceCommit: "e895a33642627401dbae5c8bd8110802ab143900",
  builtAt: "2026-08-12T00:00:00Z",
  profiles: [
    {
      id: "esp32-4mb",
      label: "ESP32 · 4 MiB flash",
      chipFamily: "ESP32",
      buildTarget: "esp32",
      method: "esp-web-tools",
      qualified: false,
      status: "engineering-preview",
      offset: 4096,
      manifest: {
        path: "/.pyble-local-preview/esp32-4mb/manifest.json",
        size: 234,
        sha256: "1".repeat(64),
      },
      firmware: {
        path: "/.pyble-local-preview/esp32-4mb/firmware.bin",
        size: 1_920_000,
        sha256: "2".repeat(64),
      },
    },
    {
      id: "esp32-s3-n16r8",
      label: "ESP32-S3 · N16R8 · lean generic",
      chipFamily: "ESP32-S3",
      buildTarget: "esp32-s3",
      method: "esp-web-tools",
      qualified: false,
      status: "engineering-preview",
      offset: 0,
      manifest: {
        path: "/.pyble-local-preview/esp32-s3-n16r8/manifest.json",
        size: 237,
        sha256: "3".repeat(64),
      },
      firmware: {
        path: "/.pyble-local-preview/esp32-s3-n16r8/firmware.bin",
        size: 2_150_000,
        sha256: "4".repeat(64),
      },
    },
    {
      id: "waveshare-esp32-s3-lcd-147b",
      label: "Waveshare ESP32-S3-LCD-1.47B · N16R8",
      chipFamily: "ESP32-S3",
      buildTarget: "waveshare-esp32-s3-lcd-147b",
      method: "esp-web-tools",
      qualified: false,
      status: "engineering-preview",
      offset: 0,
      manifest: {
        path: "/.pyble-local-preview/waveshare-esp32-s3-lcd-147b/manifest.json",
        size: 259,
        sha256: "5".repeat(64),
      },
      firmware: {
        path: "/.pyble-local-preview/waveshare-esp32-s3-lcd-147b/firmware.bin",
        size: 2_170_000,
        sha256: "6".repeat(64),
      },
    },
    {
      id: "esp32-c3-4mb",
      label: "ESP32-C3 revision v0.3+ · 4 MiB flash",
      chipFamily: "ESP32-C3",
      buildTarget: "esp32-c3",
      method: "esp-web-tools",
      qualified: false,
      status: "engineering-preview",
      offset: 0,
      manifest: {
        path: "/.pyble-local-preview/esp32-c3-4mb/manifest.json",
        size: 236,
        sha256: "7".repeat(64),
      },
      firmware: {
        path: "/.pyble-local-preview/esp32-c3-4mb/firmware.bin",
        size: 1_850_000,
        sha256: "8".repeat(64),
      },
    },
    {
      id: "rpi-pico2-w",
      label: "Raspberry Pi Pico 2 W",
      chipFamily: "RP2350",
      buildTarget: "rpi-pico2-w",
      method: "uf2-download",
      qualified: false,
      status: "engineering-preview",
      firmware: {
        path: "/.pyble-local-preview/rpi-pico2-w/firmware.uf2",
        size: 1_690_112,
        sha256: "9".repeat(64),
      },
    },
  ],
};

function renderInstaller(overrides: Partial<FlashStatusContractProps> = {}) {
  const verifyProfile = vi.fn(
    async (_release: FirmwareReleaseDescriptor, profileId: FirmwareProfileId) =>
      verifiedProfileForRelease(_release, profileId),
  );
  const loadInstaller = vi.fn(async () => undefined);
  const installArtifactFetch = vi.fn(() => () => undefined);

  const rendered = render(
    <InstallerUnderTest
      capabilities={supportedCapabilities}
      installArtifactFetch={installArtifactFetch}
      loadInstaller={loadInstaller}
      release={hypotheticalPassedPublicFirmwareRelease}
      verifyProfile={verifyProfile}
      {...overrides}
    />,
  );

  return {
    ...rendered,
    installArtifactFetch,
    loadInstaller,
    verifyProfile,
  };
}

function verifiedPreviewProfile(
  profileId: LocalPreviewProfileId,
): VerifiedLocalPreviewProfile {
  const profile = localFirmwarePreview.profiles.find(
    (candidate) => candidate.id === profileId,
  );
  if (!profile) {
    throw new Error(`Unknown local preview profile: ${profileId}`);
  }
  return {
    profileId,
    method: profile.method,
    manifestPath: profile.manifest?.path,
    firmwarePath: profile.firmware.path,
    downloadUrl:
      profile.method === "uf2-download"
        ? `blob:pyble-local-preview-${profile.id}`
        : undefined,
    version: localFirmwarePreview.version,
  };
}

function renderPreviewInstaller(
  overrides: Partial<FlashStatusContractProps> = {},
) {
  const verifyPreviewProfile = vi.fn(
    async (
      _preview: LocalFirmwarePreviewDescriptor,
      profileId: LocalPreviewProfileId,
    ) => verifiedPreviewProfile(profileId),
  );
  const loadInstaller = vi.fn(async () => undefined);

  const rendered = render(
    <InstallerUnderTest
      capabilities={supportedCapabilities}
      loadInstaller={loadInstaller}
      preview={localFirmwarePreview}
      release={null}
      verifyPreviewProfile={verifyPreviewProfile}
      {...overrides}
    />,
  );

  return { ...rendered, loadInstaller, verifyPreviewProfile };
}

function selectPreviewProfile(profileId: LocalPreviewProfileId) {
  fireEvent.change(
    screen.getByRole("combobox", { name: /choose a firmware target/i }),
    { target: { value: profileId } },
  );
}

function acceptPreviewConsents() {
  const acknowledgements = screen.getByRole("group", {
    name: /installation acknowledgements/i,
  });
  for (const checkbox of within(acknowledgements).getAllByRole("checkbox")) {
    fireEvent.click(checkbox);
  }
}

function verifiedProfileForRelease(
  release: FirmwareReleaseDescriptor,
  profileId: FirmwareProfileId,
): VerifiedProfile {
  const profile = release.profiles.find(({ id }) => id === profileId);
  if (!profile) {
    throw new Error(`Unknown test profile: ${profileId}`);
  }
  return {
    profileId,
    chipFamily: profile.chipFamily,
    manifestPath: profile.manifestPath,
    manifestBuildCount: 1,
    firmwarePath: profile.firmwarePath,
    version: release.version,
  };
}

function releaseAtVersion(
  version: string,
  builtAt: string,
): FirmwareReleaseDescriptor {
  const release = structuredClone(
    hypotheticalPassedPublicFirmwareRelease,
  ) as unknown as {
    version: string;
    builtAt: string;
    releaseJson: { path: string; sha256: string };
    schemaPath: string;
    recoveryPath: string;
    profiles: Array<{ manifestPath: string; firmwarePath: string }>;
  };
  release.version = version;
  release.builtAt = builtAt;
  release.releaseJson.path = `/firmware/v${version}/release.json`;
  release.schemaPath = `/firmware/v${version}/release.schema.json`;
  release.recoveryPath = `/firmware/v${version}/RECOVERY.md`;
  for (const profile of release.profiles) {
    profile.manifestPath = profile.manifestPath.replace(
      "/firmware/v0.5.1/",
      `/firmware/v${version}/`,
    );
    profile.firmwarePath = profile.firmwarePath.replace(
      "/firmware/v0.5.1/",
      `/firmware/v${version}/`,
    );
  }
  return release as unknown as FirmwareReleaseDescriptor;
}

function selectS3Profile() {
  fireEvent.click(
    screen.getByRole("radio", {
      name: /esp32-s3.*n16r8.*16 mib flash.*8 mib octal psram/i,
    }),
  );
}

function acceptEveryConsent() {
  for (const consent of installerConsents) {
    fireEvent.click(screen.getByRole("checkbox", { name: consent }));
  }
}

function startVerification() {
  fireEvent.click(
    screen.getByRole("button", {
      name: /verify firmware for esp32-s3.*n16r8/i,
    }),
  );
}

function withDeferredC3(
  release: FirmwareReleaseDescriptor,
): FirmwareReleaseDescriptor {
  const malformed = structuredClone(release) as unknown as {
    profiles: Array<Record<string, unknown>>;
  };
  const deferred = structuredClone(malformed.profiles[0]!);
  Object.assign(deferred, {
    id: "esp32-c3-4mb",
    label: "ESP32-C3 revision v0.3+ · 4 MiB flash",
    chipFamily: "ESP32-C3",
    manifestPath: `/firmware/v${release.version}/esp32-c3-4mb/manifest.json`,
    firmwarePath: `/firmware/v${release.version}/esp32-c3-4mb/firmware.bin`,
    offset: 0,
  });
  malformed.profiles.push(deferred);
  return malformed as unknown as FirmwareReleaseDescriptor;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("browser firmware installer states", () => {
  it("is a client-only component that feature-detects support and imports the exact local package", async () => {
    const source = await readFile(
      join(process.cwd(), "src", "components", "flash-status.tsx"),
      "utf8",
    );

    expect(source).toMatch(/^["']use client["'];/);
    expect(source).toMatch(/["']serial["']\s+in\s+navigator/);
    expect(source).toContain("isSecureContext");
    expect(source).toMatch(/crypto(?:\.|\?\.)subtle/);
    expect(source).toContain('import("esp-web-tools")');
    expect(source).not.toContain("navigator.userAgent");
    expect(source).not.toMatch(/unpkg|cdn\.jsdelivr|esm\.sh/i);
  });

  it("renders a neutral capability-checking state in build-time HTML", () => {
    vi.stubGlobal("window", undefined);
    vi.stubGlobal("navigator", undefined);

    const html = renderToStaticMarkup(
      <InstallerUnderTest release={hypotheticalPassedPublicFirmwareRelease} />,
    );

    expect(html).toMatch(/checking browser support/i);
    expect(html).not.toMatch(
      /open this page over https|use a supported desktop browser/i,
    );
  });

  it("keeps the checked-in public default unavailable until a release passes every gate", () => {
    render(<InstallerUnderTest capabilities={supportedCapabilities} />);

    expect(screen.getByRole("status")).toHaveTextContent(
      /installer unavailable.*hardware validation.*every profile included in a future v0\.6\.0-derived candidate/i,
    );
    expect(
      screen.getByRole("button", { name: /installer coming soon/i }),
    ).toBeDisabled();
    expect(
      screen.queryByRole("radiogroup", {
        name: /select the exact module profile/i,
      }),
    ).not.toBeInTheDocument();
    expect(document.querySelector("esp-web-install-button")).toBeNull();
  });

  it("rejects pending HIL metadata in a public release selection", () => {
    const { verifyProfile } = renderInstaller({
      release: currentPendingPublicFirmwareRelease,
    });

    expect(screen.getByRole("status")).toHaveTextContent(
      /public installer unavailable.*hardware validation.*pending/i,
    );
    expect(
      screen.queryByRole("radiogroup", {
        name: /select the exact module profile/i,
      }),
    ).not.toBeInTheDocument();
    expect(verifyProfile).not.toHaveBeenCalled();
    expect(document.querySelector("esp-web-install-button")).toBeNull();
  });

  it("rejects candidate mode unless its build is explicitly access-controlled", () => {
    const { verifyProfile } = renderInstaller({
      release: currentUncontrolledCandidateFirmwareRelease,
    });

    expect(screen.getByRole("status")).toHaveTextContent(
      /candidate installer unavailable.*access-controlled/i,
    );
    expect(
      screen.queryByRole("radiogroup", {
        name: /select the exact module profile/i,
      }),
    ).not.toBeInTheDocument();
    expect(verifyProfile).not.toHaveBeenCalled();
    expect(document.querySelector("esp-web-install-button")).toBeNull();
  });

  it("fails closed when a build descriptor has an unknown deployment mode", () => {
    const release = structuredClone(
      pendingPublicFirmwareRelease,
    ) as unknown as Record<string, unknown>;
    release.deployment = "publci";
    const { verifyProfile } = renderInstaller({
      release: release as unknown as FirmwareReleaseDescriptor,
    });

    expect(screen.getByRole("status")).toHaveTextContent(
      /installer unavailable.*deployment/i,
    );
    expect(
      screen.queryByRole("radiogroup", {
        name: /select the exact module profile/i,
      }),
    ).not.toBeInTheDocument();
    expect(verifyProfile).not.toHaveBeenCalled();
    expect(document.querySelector("esp-web-install-button")).toBeNull();
  });

  it.each([
    {
      name: "public",
      release: withDeferredC3(hypotheticalPassedPublicFirmwareRelease),
    },
    {
      name: "candidate",
      release: withDeferredC3(currentPendingCandidateFirmwareRelease),
    },
  ])(
    "fails closed when a $name descriptor includes the deferred C3 profile",
    ({ release }) => {
      const { verifyProfile } = renderInstaller({ release });

      expect(screen.getByRole("status")).toHaveTextContent(
        /installer unavailable.*profile/i,
      );
      expect(
        screen.queryByRole("radiogroup", {
          name: /select the exact module profile/i,
        }),
      ).not.toBeInTheDocument();
      expect(verifyProfile).not.toHaveBeenCalled();
      expect(document.querySelector("esp-web-install-button")).toBeNull();
    },
  );

  it("permits pending HIL only in an explicitly selected access-controlled candidate build", () => {
    renderInstaller({ release: currentPendingCandidateFirmwareRelease });

    expect(screen.getByRole("status")).toHaveTextContent(
      /protected release candidate.*hardware validation is pending/i,
    );
    expect(
      screen.getByRole("radiogroup", {
        name: /select the exact module profile/i,
      }),
    ).toBeInTheDocument();
    expect(document.querySelector("esp-web-install-button")).toBeNull();
  });

  it("offers the exact v0.4.2 hardware-tested beta with scoped qualification copy", async () => {
    renderInstaller({ release: publicBetaFirmwareRelease });

    expect(screen.getByRole("status")).toHaveTextContent(
      /hardware-tested firmware beta.*browser installation.*interrupted-flash recovery.*esp32-4mb.*esp32-s3-n16r8.*complete release qualification.*pending.*not a qualified release/i,
    );
    expect(screen.queryByText(/protected release candidate/i)).toBeNull();
    expect(
      screen.queryByRole("heading", { name: /^qualified release$/i }),
    ).toBeNull();
    expect(screen.queryByText(/full HIL pending/i)).toBeNull();
    expect(screen.queryByText(/use at your own risk/i)).toBeNull();

    const profileGroup = screen.getByRole("radiogroup", {
      name: /select the exact module profile/i,
    });
    expect(within(profileGroup).getAllByRole("radio")).toHaveLength(2);
    expect(within(profileGroup).queryByText(/esp32-c3/i)).toBeNull();

    selectS3Profile();
    acceptEveryConsent();
    startVerification();
    await waitFor(() => {
      expect(document.querySelector("esp-web-install-button")).not.toBeNull();
    });
    expect(
      screen.getByText(
        /browser installation.*interrupted-flash recovery.*real hardware.*exact profile.*complete release qualification.*pending/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: /install pyble 0\.4\.2 beta/i,
      }),
    ).toBeInTheDocument();
  });

  it("models a future qualified v0.5.1 selector with exactly three profiles and no deferred C3", () => {
    renderInstaller();

    const profileGroup = screen.getByRole("radiogroup", {
      name: /select the exact module profile/i,
    });
    expect(within(profileGroup).getAllByRole("radio")).toHaveLength(3);
    expect(
      within(profileGroup).getByRole("radio", {
        name: /^esp32-4mb.*4 mib flash.*no psram required$/i,
      }),
    ).toBeInTheDocument();
    expect(
      within(profileGroup).getByRole("radio", {
        name: /esp32-s3-n16r8.*16 mib flash.*8 mib octal psram.*lean generic.*no tft.*no splash/i,
      }),
    ).toBeInTheDocument();
    expect(
      within(profileGroup).getByRole("radio", {
        name: /waveshare-esp32-s3-lcd-147b.*exact b-version board.*16 mib flash.*8 mib octal psram/i,
      }),
    ).toBeInTheDocument();
    expect(
      within(profileGroup).queryByRole("radio", {
        name: /esp32-c3.*revision v0\.3 or newer.*4 mib flash.*no psram required/i,
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/not for every esp32-s3 board/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /exact ESP32-S3-LCD-1\.47B B-version.*family detection.*do not identify/i,
      ),
    ).toBeInTheDocument();
    expect(document.querySelector("esp-web-install-button")).toBeNull();
  });

  it("keeps the lean generic S3 and future-qualified Waveshare actions separate", async () => {
    const release = releaseAtVersion("0.5.1", "2026-08-02T00:00:00Z");
    const verifyProfile = vi.fn(
      async (
        selectedRelease: FirmwareReleaseDescriptor,
        profileId: FirmwareProfileId,
      ) => verifiedProfileForRelease(selectedRelease, profileId),
    );
    renderInstaller({ release, verifyProfile });

    const profileGroup = screen.getByRole("radiogroup", {
      name: /select the exact module profile/i,
    });
    expect(within(profileGroup).getAllByRole("radio")).toHaveLength(3);
    const generic = within(profileGroup).getByRole("radio", {
      name: /esp32-s3-n16r8.*lean generic.*no tft.*no splash/i,
    });
    expect(generic).toHaveAttribute("value", "esp32-s3-n16r8");
    const waveshare = within(profileGroup).getByRole("radio", {
      name: /waveshare-esp32-s3-lcd-147b.*exact b-version board.*16 mib flash.*8 mib octal psram.*st7789.*fresh-install splash/i,
    });
    expect(waveshare).toHaveAttribute("value", "waveshare-esp32-s3-lcd-147b");
    fireEvent.click(waveshare);
    acceptEveryConsent();
    const verifyButton = screen.getByRole("button", {
      name: /verify firmware for waveshare esp32-s3-lcd-1\.47b/i,
    });
    expect(verifyButton).toBeDisabled();
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /exact esp32-s3-lcd-1\.47b b-version.*16 mib flash.*8 mib octal psram/i,
      }),
    );
    expect(verifyButton).toBeEnabled();
    fireEvent.click(verifyButton);

    await waitFor(() => {
      expect(verifyProfile).toHaveBeenCalledWith(
        release,
        "waveshare-esp32-s3-lcd-147b",
      );
    });
    expect(generic).not.toBeChecked();
  });

  it.each([
    {
      capabilities: {
        secureContext: false,
        webSerial: true,
        webCrypto: true,
      },
      message: /open this page over https/i,
    },
    {
      capabilities: {
        secureContext: true,
        webSerial: false,
        webCrypto: true,
      },
      message: /current desktop chromium browser/i,
    },
    {
      capabilities: {
        secureContext: true,
        webSerial: true,
        webCrypto: false,
      },
      message: /web crypto.*not available/i,
    },
  ])(
    "fails closed when required browser capability is absent",
    ({ capabilities, message }) => {
      renderInstaller({ capabilities });

      expect(screen.getByRole("status")).toHaveTextContent(message);
      expect(screen.getByText(/ipadOS cannot perform/i)).toBeInTheDocument();
      expect(document.querySelector("esp-web-install-button")).toBeNull();
    },
  );

  it("requires exact-profile, backup, erase, cable/power, and serial-port consent before verification", () => {
    const { verifyProfile } = renderInstaller();

    selectS3Profile();

    const verifyButton = screen.getByRole("button", {
      name: /verify firmware for esp32-s3.*n16r8/i,
    });
    expect(verifyButton).toBeDisabled();

    for (const consent of installerConsents) {
      expect(screen.getByRole("checkbox", { name: consent })).not.toBeChecked();
    }

    acceptEveryConsent();

    expect(verifyButton).toBeEnabled();
    expect(verifyProfile).not.toHaveBeenCalled();
    expect(document.querySelector("esp-web-install-button")).toBeNull();
  });

  it("stays fail-closed while the selected profile is being verified", async () => {
    let resolveVerification: ((value: VerifiedProfile) => void) | undefined;
    const verifyProfile = vi.fn(
      () =>
        new Promise<VerifiedProfile>((resolve) => {
          resolveVerification = resolve;
        }),
    );
    const loadInstaller = vi.fn(async () => undefined);

    renderInstaller({ loadInstaller, verifyProfile });
    selectS3Profile();
    acceptEveryConsent();
    startVerification();

    expect(await screen.findByRole("status")).toHaveTextContent(
      /verifying firmware/i,
    );
    expect(verifyProfile).toHaveBeenCalledWith(
      hypotheticalPassedPublicFirmwareRelease,
      "esp32-s3-n16r8",
    );
    expect(loadInstaller).not.toHaveBeenCalled();
    expect(document.querySelector("esp-web-install-button")).toBeNull();

    resolveVerification?.(verifiedProfile("esp32-s3-n16r8"));
  });

  it.each([
    "request failed",
    "redirect rejected",
    "release schema mismatch",
    "release digest mismatch",
    "firmware size mismatch",
    "unsafe artifact path",
    "manifest offset mismatch",
    "manifest chip-family mismatch",
    "manifest and release disagree",
  ])("keeps the installer unavailable when %s", async (failure) => {
    const verifyProfile = vi.fn(async () => {
      throw new Error(failure);
    });

    renderInstaller({ verifyProfile });
    selectS3Profile();
    acceptEveryConsent();
    startVerification();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/firmware verification failed/i);
    expect(alert).toHaveTextContent(/no firmware was written/i);
    expect(screen.getByText(new RegExp(failure, "i"))).toBeInTheDocument();
    expect(
      screen.getByRole("radio", {
        name: /esp32-s3.*n16r8/i,
      }),
    ).toBeChecked();
    expect(document.querySelector("esp-web-install-button")).toBeNull();
  });

  it("exposes only the verified selected profile's single-build manifest", async () => {
    const { installArtifactFetch, loadInstaller, verifyProfile } =
      renderInstaller();

    selectS3Profile();
    acceptEveryConsent();
    startVerification();

    await waitFor(() => {
      expect(document.querySelector("esp-web-install-button")).not.toBeNull();
    });

    const installElement = document.querySelector(
      "esp-web-install-button",
    ) as HTMLElement;
    expect(verifyProfile).toHaveBeenCalledWith(
      hypotheticalPassedPublicFirmwareRelease,
      "esp32-s3-n16r8",
    );
    expect(loadInstaller).toHaveBeenCalledOnce();
    expect(installArtifactFetch).toHaveBeenCalledWith(
      verifiedProfileForRelease(
        hypotheticalPassedPublicFirmwareRelease,
        "esp32-s3-n16r8",
      ),
      hypotheticalPassedPublicFirmwareRelease.releaseJson.sha256,
    );
    expect(installElement).toHaveAttribute(
      "manifest",
      "/firmware/v0.5.1/esp32-s3-n16r8/manifest.json",
    );
    expect(installElement).not.toHaveAttribute(
      "manifest",
      "/firmware/v0.5.1/manifest.json",
    );
    expect(
      within(installElement).getByRole("button", {
        name: /install pyble 0\.5\.1/i,
      }),
    ).toHaveAttribute("slot", "activate");
    expect(screen.getByText(/artifacts verified/i)).toBeInTheDocument();
    expect(screen.getAllByText(/esp32-s3-n16r8/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/august 3, 2026/i)).toBeInTheDocument();
    expect(
      screen.getAllByText(/installation erases the device/i).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByRole("link", { name: /version 0\.5\.1 recovery/i }),
    ).toHaveAttribute("href", "/firmware/v0.5.1/RECOVERY.md");
  });

  it("removes prior qualification when the selected profile changes", async () => {
    renderInstaller();
    selectS3Profile();
    acceptEveryConsent();
    startVerification();

    await waitFor(() => {
      expect(document.querySelector("esp-web-install-button")).not.toBeNull();
    });

    fireEvent.click(
      screen.getByRole("radio", {
        name: /^esp32-4mb.*4 mib flash.*no psram required$/i,
      }),
    );

    expect(document.querySelector("esp-web-install-button")).toBeNull();
    expect(screen.queryByText(/artifacts verified/i)).not.toBeInTheDocument();
  });

  it("synchronously revokes prior qualification when release identity changes", async () => {
    const rendered = renderInstaller();
    selectS3Profile();
    acceptEveryConsent();
    startVerification();

    await waitFor(() => {
      expect(document.querySelector("esp-web-install-button")).not.toBeNull();
    });

    const replacement = releaseAtVersion("0.5.1", "2026-07-30T12:00:00Z");
    rendered.rerender(
      <InstallerUnderTest
        capabilities={supportedCapabilities}
        loadInstaller={rendered.loadInstaller}
        release={replacement}
        verifyProfile={rendered.verifyProfile}
      />,
    );

    expect(document.querySelector("esp-web-install-button")).toBeNull();
    expect(screen.queryByText(/artifacts verified/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /version 0\.4\.1 recovery/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/july 30, 2026/i)).not.toBeInTheDocument();
  });

  it("discards an in-flight result when release identity changes", async () => {
    let resolveVerification: ((value: VerifiedProfile) => void) | undefined;
    const verifyProfile = vi.fn(
      () =>
        new Promise<VerifiedProfile>((resolve) => {
          resolveVerification = resolve;
        }),
    );
    const loadInstaller = vi.fn(async () => undefined);
    const rendered = renderInstaller({ loadInstaller, verifyProfile });
    selectS3Profile();
    acceptEveryConsent();
    startVerification();

    expect(await screen.findByRole("status")).toHaveTextContent(
      /verifying firmware/i,
    );

    rendered.rerender(
      <InstallerUnderTest
        capabilities={supportedCapabilities}
        loadInstaller={loadInstaller}
        release={releaseAtVersion("0.5.1", "2026-07-30T12:00:00Z")}
        verifyProfile={verifyProfile}
      />,
    );
    await act(async () => {
      resolveVerification?.(verifiedProfile("esp32-s3-n16r8"));
      await Promise.resolve();
    });

    expect(loadInstaller).not.toHaveBeenCalled();
    expect(document.querySelector("esp-web-install-button")).toBeNull();
    expect(screen.queryByText(/artifacts verified/i)).not.toBeInTheDocument();
  });

  it("discards an in-flight verification result after the selected profile changes", async () => {
    let resolveVerification: ((value: VerifiedProfile) => void) | undefined;
    const verifyProfile = vi.fn(
      () =>
        new Promise<VerifiedProfile>((resolve) => {
          resolveVerification = resolve;
        }),
    );
    const loadInstaller = vi.fn(async () => undefined);

    renderInstaller({ loadInstaller, verifyProfile });
    selectS3Profile();
    acceptEveryConsent();
    startVerification();

    expect(await screen.findByRole("status")).toHaveTextContent(
      /verifying firmware/i,
    );

    fireEvent.click(
      screen.getByRole("radio", {
        name: /^esp32-4mb.*4 mib flash.*no psram required$/i,
      }),
    );

    await act(async () => {
      resolveVerification?.(verifiedProfile("esp32-s3-n16r8"));
      await Promise.resolve();
    });

    expect(loadInstaller).not.toHaveBeenCalled();
    expect(document.querySelector("esp-web-install-button")).toBeNull();
    expect(screen.queryByText(/artifacts verified/i)).not.toBeInTheDocument();
    expect(
      screen.getByRole("radio", {
        name: /^esp32-4mb.*4 mib flash.*no psram required$/i,
      }),
    ).toBeChecked();
  });

  it("defines one immutable profile-scoped manifest URL per active profile", () => {
    expect(
      firmwareProfiles.map(({ id, manifestPath }) => ({ id, manifestPath })),
    ).toEqual([
      {
        id: "esp32-4mb",
        manifestPath: "/firmware/v0.4.2/esp32-4mb/manifest.json",
      },
      {
        id: "esp32-s3-n16r8",
        manifestPath: "/firmware/v0.4.2/esp32-s3-n16r8/manifest.json",
      },
    ]);
    expect(publicBetaFirmwareRelease.releaseJson.path).toBe(
      "/firmware/v0.4.2/release.json",
    );
    expect(JSON.stringify(publicBetaFirmwareRelease)).not.toContain(
      "esp32-c3-4mb",
    );
    expect(publicBetaFirmwareRelease.releaseJson.sha256).toMatch(
      /^[0-9a-f]{64}$/,
    );
  });
});

describe("local five-board engineering preview", () => {
  it("uses an unselected native target combobox grouped by provisioning method", () => {
    renderPreviewInstaller();

    expect(screen.getByRole("status")).toHaveTextContent(
      /local engineering preview.*unqualified.*not a public release/i,
    );
    const selector = screen.getByRole("combobox", {
      name: /choose a firmware target/i,
    });
    expect(selector).toHaveValue("");
    const targetOptions = within(selector)
      .getAllByRole("option")
      .filter((option) => (option as HTMLOptionElement).value !== "");
    expect(targetOptions).toHaveLength(5);
    expect(
      targetOptions.map((option) => (option as HTMLOptionElement).value),
    ).toEqual([
      "esp32-4mb",
      "esp32-s3-n16r8",
      "waveshare-esp32-s3-lcd-147b",
      "esp32-c3-4mb",
      "rpi-pico2-w",
    ]);
    expect(targetOptions.map((option) => option.textContent)).toEqual([
      expect.stringMatching(/classical esp32/i),
      expect.stringMatching(/esp32-s3.*lean/i),
      expect.stringMatching(/waveshare.*exact/i),
      expect.stringMatching(/esp32-c3/i),
      expect.stringMatching(/raspberry pi pico 2 w/i),
    ]);
    const methodGroups = Array.from(selector.querySelectorAll("optgroup"));
    expect(methodGroups).toHaveLength(2);
    expect(methodGroups[0]?.getAttribute("label")).toMatch(
      /esp.*direct install/i,
    );
    expect(methodGroups[0]?.querySelectorAll("option")).toHaveLength(4);
    expect(methodGroups[1]?.getAttribute("label")).toMatch(/rp2.*uf2/i);
    expect(methodGroups[1]?.querySelectorAll("option")).toHaveLength(1);
    expect(
      screen.queryByRole("region", {
        name: /selected firmware target details/i,
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("group", {
        name: /installation acknowledgements/i,
      }),
    ).not.toBeInTheDocument();
  });

  it("keeps explicit target, method, and unqualified status details visible after selection", () => {
    renderPreviewInstaller();

    selectPreviewProfile("esp32-c3-4mb");
    const details = screen.getByRole("region", {
      name: /selected firmware target details/i,
    });
    expect(details).toHaveTextContent(/esp32-c3-4mb/i);
    expect(details).toHaveTextContent(/esp32 web tools.*web serial/i);
    expect(details).toHaveTextContent(
      /local engineering preview.*unqualified/i,
    );
    expect(details).toHaveTextContent(/version 0\.6\.0/i);

    const acknowledgements = screen.getByRole("group", {
      name: /installation acknowledgements/i,
    });
    expect(acknowledgements.tagName).toBe("FIELDSET");
    expect(acknowledgements.querySelector("legend")).toHaveTextContent(
      /installation acknowledgements/i,
    );
    expect(
      screen.getByRole("region", {
        name: /selected firmware target details/i,
      }),
    ).toBe(details);
  });

  it.each([
    {
      id: "esp32-s3-n16r8" as const,
      warning:
        /16 MiB flash.*8 MiB Octal PSRAM.*lean.*no display runtime.*no splash/i,
    },
    {
      id: "waveshare-esp32-s3-lcd-147b" as const,
      warning: /only.*exact.*ESP32-S3-LCD-1\.47B.*B version.*display wiring/i,
    },
    {
      id: "esp32-c3-4mb" as const,
      warning: /ESP32-C3.*revision v0\.3 or newer.*4 MiB flash/i,
    },
    {
      id: "rpi-pico2-w" as const,
      warning: /hold BOOTSEL.*connect.*RP2350.*copy.*UF2/i,
    },
  ])("shows only the relevant $id warning", ({ id, warning }) => {
    renderPreviewInstaller();

    selectPreviewProfile(id);
    const details = screen.getByRole("region", {
      name: /selected firmware target details/i,
    });
    expect(details).toHaveTextContent(warning);
  });

  it("verifies an ESP image before loading its exact ESP Web Tools manifest", async () => {
    let resolveVerification:
      ((value: VerifiedLocalPreviewProfile) => void) | undefined;
    const verifyPreviewProfile = vi.fn(
      () =>
        new Promise<VerifiedLocalPreviewProfile>((resolve) => {
          resolveVerification = resolve;
        }),
    );
    const loadInstaller = vi.fn(async () => undefined);
    renderPreviewInstaller({ loadInstaller, verifyPreviewProfile });

    selectPreviewProfile("esp32-4mb");
    acceptPreviewConsents();
    fireEvent.click(
      screen.getByRole("button", {
        name: /verify firmware.*classical esp32/i,
      }),
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      /verifying.*manifest.*firmware/i,
    );
    expect(verifyPreviewProfile).toHaveBeenCalledWith(
      localFirmwarePreview,
      "esp32-4mb",
    );
    expect(loadInstaller).not.toHaveBeenCalled();
    expect(document.querySelector("esp-web-install-button")).toBeNull();

    await act(async () => {
      resolveVerification?.(verifiedPreviewProfile("esp32-4mb"));
      await Promise.resolve();
    });
    await waitFor(() => expect(loadInstaller).toHaveBeenCalledOnce());
    const installer = document.querySelector("esp-web-install-button");
    expect(installer).toHaveAttribute(
      "manifest",
      "/.pyble-local-preview/esp32-4mb/manifest.json",
    );
    expect(screen.getByText(/local artifacts verified/i)).toBeInTheDocument();
  });

  it("verifies Pico UF2 and exposes BOOTSEL download without Web Serial", async () => {
    const loadInstaller = vi.fn(async () => undefined);
    const { verifyPreviewProfile } = renderPreviewInstaller({
      capabilities: {
        secureContext: true,
        webSerial: false,
        webCrypto: true,
      },
      loadInstaller,
    });

    selectPreviewProfile("rpi-pico2-w");
    acceptPreviewConsents();
    fireEvent.click(
      screen.getByRole("button", {
        name: /verify firmware.*raspberry pi pico 2 w/i,
      }),
    );

    await waitFor(() => {
      expect(
        screen.getByRole("link", { name: /download.*uf2/i }),
      ).toBeInTheDocument();
    });
    expect(verifyPreviewProfile).toHaveBeenCalledWith(
      localFirmwarePreview,
      "rpi-pico2-w",
    );
    const download = screen.getByRole("link", { name: /download.*uf2/i });
    expect(download).toHaveAttribute(
      "href",
      "blob:pyble-local-preview-rpi-pico2-w",
    );
    expect(download).not.toHaveAttribute(
      "href",
      "/.pyble-local-preview/rpi-pico2-w/firmware.uf2",
    );
    expect(download).toHaveAttribute("download");
    expect(screen.getByText(/hold BOOTSEL.*connect/i)).toBeInTheDocument();
    expect(screen.getByText(/copy.*UF2.*mounted.*RP2350/i)).toBeInTheDocument();
    expect(screen.queryByText(/web serial support/i)).not.toBeInTheDocument();
    expect(loadInstaller).not.toHaveBeenCalled();
    expect(document.querySelector("esp-web-install-button")).toBeNull();
  });

  it("resets acknowledgements and verification whenever the target changes", async () => {
    renderPreviewInstaller();
    selectPreviewProfile("esp32-4mb");
    acceptPreviewConsents();
    fireEvent.click(
      screen.getByRole("button", {
        name: /verify firmware.*classical esp32/i,
      }),
    );
    await waitFor(() => {
      expect(document.querySelector("esp-web-install-button")).not.toBeNull();
    });

    selectPreviewProfile("esp32-c3-4mb");

    const acknowledgements = screen.getByRole("group", {
      name: /installation acknowledgements/i,
    });
    for (const checkbox of within(acknowledgements).getAllByRole("checkbox")) {
      expect(checkbox).not.toBeChecked();
    }
    expect(screen.queryByText(/local artifacts verified/i)).toBeNull();
    expect(document.querySelector("esp-web-install-button")).toBeNull();
    expect(
      screen.getByRole("button", { name: /verify firmware.*esp32-c3/i }),
    ).toBeDisabled();
  });

  it("never exposes preview-only C3 or Pico actions without a local descriptor", () => {
    render(
      <InstallerUnderTest
        capabilities={supportedCapabilities}
        preview={null}
        release={null}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      /installer unavailable/i,
    );
    expect(
      screen.queryByRole("combobox", {
        name: /choose a firmware target/i,
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /download.*uf2/i }),
    ).not.toBeInTheDocument();
    expect(document.querySelector("esp-web-install-button")).toBeNull();
  });
});
