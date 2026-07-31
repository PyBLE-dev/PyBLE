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
import {
  type FirmwareReleaseDescriptor,
  firmwareProfiles,
  installerConsents,
  passedPublicFirmwareRelease,
  pendingCandidateFirmwareRelease,
  pendingPublicFirmwareRelease,
  publicBetaFirmwareRelease,
  type FirmwareProfileId,
  uncontrolledCandidateFirmwareRelease,
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
      verifiedProfile(profileId),
  );
  const loadInstaller = vi.fn(async () => undefined);
  const installArtifactFetch = vi.fn(() => () => undefined);

  const rendered = render(
    <InstallerUnderTest
      capabilities={supportedCapabilities}
      installArtifactFetch={installArtifactFetch}
      loadInstaller={loadInstaller}
      release={passedPublicFirmwareRelease}
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

function releaseAtVersion(
  version: string,
  builtAt: string,
): FirmwareReleaseDescriptor {
  const release = structuredClone(passedPublicFirmwareRelease) as unknown as {
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
      "/firmware/v0.4.1/",
      `/firmware/v${version}/`,
    );
    profile.firmwarePath = profile.firmwarePath.replace(
      "/firmware/v0.4.1/",
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
    manifestPath: "/firmware/v0.4.1/esp32-c3-4mb/manifest.json",
    firmwarePath: "/firmware/v0.4.1/esp32-c3-4mb/firmware.bin",
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
      <InstallerUnderTest release={passedPublicFirmwareRelease} />,
    );

    expect(html).toMatch(/checking browser support/i);
    expect(html).not.toMatch(
      /open this page over https|use a supported desktop browser/i,
    );
  });

  it("keeps the checked-in public default unavailable until a release passes every gate", () => {
    render(<InstallerUnderTest capabilities={supportedCapabilities} />);

    expect(screen.getByRole("status")).toHaveTextContent(
      /installer unavailable.*hardware validation.*both exact current release profiles/i,
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
      release: pendingPublicFirmwareRelease,
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
      release: uncontrolledCandidateFirmwareRelease,
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
      release: withDeferredC3(passedPublicFirmwareRelease),
    },
    {
      name: "candidate",
      release: withDeferredC3(pendingCandidateFirmwareRelease),
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
    renderInstaller({ release: pendingCandidateFirmwareRelease });

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

  it("offers the exact unrestricted v0.4.1 beta with prominent unqualified warnings", async () => {
    renderInstaller({ release: publicBetaFirmwareRelease });

    expect(screen.getByRole("status")).toHaveTextContent(
      /unqualified firmware beta.*full hardware-in-the-loop.*pending.*use at your own risk/i,
    );
    expect(screen.queryByText(/protected release candidate/i)).toBeNull();
    expect(screen.queryByText(/qualified release/i)).toBeNull();

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
    expect(screen.getByText(/unqualified beta.*use at your own risk/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: /install unqualified beta pyble 0\.4\.1/i,
      }),
    ).toBeInTheDocument();
  });

  it("starts disabled with exactly both qualified profiles and keeps deferred C3 out of the selector", () => {
    renderInstaller();

    const profileGroup = screen.getByRole("radiogroup", {
      name: /select the exact module profile/i,
    });
    expect(within(profileGroup).getAllByRole("radio")).toHaveLength(2);
    expect(
      within(profileGroup).getByRole("radio", {
        name: /^esp32-4mb.*4 mib flash.*no psram required$/i,
      }),
    ).toBeInTheDocument();
    expect(
      within(profileGroup).getByRole("radio", {
        name: /esp32-s3.*n16r8.*16 mib flash.*8 mib octal psram/i,
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
    expect(document.querySelector("esp-web-install-button")).toBeNull();
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
      passedPublicFirmwareRelease,
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
      passedPublicFirmwareRelease,
      "esp32-s3-n16r8",
    );
    expect(loadInstaller).toHaveBeenCalledOnce();
    expect(installArtifactFetch).toHaveBeenCalledWith(
      verifiedProfile("esp32-s3-n16r8"),
      passedPublicFirmwareRelease.releaseJson.sha256,
    );
    expect(installElement).toHaveAttribute(
      "manifest",
      "/firmware/v0.4.1/esp32-s3-n16r8/manifest.json",
    );
    expect(installElement).not.toHaveAttribute(
      "manifest",
      "/firmware/v0.4.1/manifest.json",
    );
    expect(
      within(installElement).getByRole("button", {
        name: /install pyble 0\.4\.1/i,
      }),
    ).toHaveAttribute("slot", "activate");
    expect(screen.getByText(/artifacts verified/i)).toBeInTheDocument();
    expect(screen.getAllByText(/esp32-s3-n16r8/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/july 30, 2026/i)).toBeInTheDocument();
    expect(
      screen.getAllByText(/installation erases the device/i).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByRole("link", { name: /version 0\.4\.1 recovery/i }),
    ).toHaveAttribute("href", "/firmware/v0.4.1/RECOVERY.md");
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

    const replacement = releaseAtVersion("0.5.0", "2026-07-30T12:00:00Z");
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
        release={releaseAtVersion("0.5.0", "2026-07-30T12:00:00Z")}
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
        manifestPath: "/firmware/v0.4.1/esp32-4mb/manifest.json",
      },
      {
        id: "esp32-s3-n16r8",
        manifestPath: "/firmware/v0.4.1/esp32-s3-n16r8/manifest.json",
      },
    ]);
    expect(passedPublicFirmwareRelease.releaseJson.path).toBe(
      "/firmware/v0.4.1/release.json",
    );
    expect(JSON.stringify(passedPublicFirmwareRelease)).not.toContain(
      "esp32-c3-4mb",
    );
    expect(passedPublicFirmwareRelease.releaseJson.sha256).toMatch(
      /^[0-9a-f]{64}$/,
    );
  });
});
