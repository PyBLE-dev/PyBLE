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

interface FlashStatusContractProps {
  capabilities?: BrowserCapabilities;
  installArtifactFetch?: (
    profile: VerifiedProfile,
    releaseKey: string,
  ) => () => void;
  loadInstaller?: () => Promise<void>;
  release?: FirmwareReleaseDescriptor | null;
  verifyProfile?: (
    release: FirmwareReleaseDescriptor,
    profileId: FirmwareProfileId,
  ) => Promise<VerifiedProfile>;
}

const InstallerUnderTest =
  FlashStatus as ComponentType<FlashStatusContractProps>;

const supportedCapabilities: BrowserCapabilities = {
  secureContext: true,
  webSerial: true,
  webCrypto: true,
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
