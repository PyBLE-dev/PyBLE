"use client";

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { installReleaseKeyedArtifactFetch } from "@/lib/firmware-fetch-cache";
import { verifyFirmwareProfile } from "@/lib/firmware-integrity";
import {
  hasExactFirmwareProfileDescriptors,
  isExactPublicBetaFirmwareRelease,
  releaseIncludesWaveshareLcd147b,
  type FirmwareProfileDescriptor,
  type FirmwareProfileId,
  type FirmwareReleaseDescriptor,
  type VerifiedFirmwareProfile,
} from "@/lib/firmware-release";
import {
  installVerifiedLocalPreviewFetch,
  isLoopbackHostname,
  localFirmwareProfileTable,
  verifyLocalFirmwarePreviewProfile,
  type LocalFirmwarePreviewDescriptor,
  type LocalFirmwarePreviewProfile,
  type LocalFirmwareProfileId,
  type VerifiedLocalPreviewProfile,
} from "@/lib/local-firmware-preview";

export interface BrowserCapabilities {
  readonly secureContext: boolean;
  readonly webSerial: boolean;
  readonly webCrypto: boolean;
}

export interface FlashStatusProps {
  readonly capabilities?: BrowserCapabilities;
  readonly loadInstaller?: () => Promise<void>;
  readonly preview?: LocalFirmwarePreviewDescriptor | null;
  readonly installArtifactFetch?: (
    profile: VerifiedFirmwareProfile,
    releaseKey: string,
  ) => () => void;
  readonly release?: FirmwareReleaseDescriptor | null;
  readonly verifyProfile?: (
    release: FirmwareReleaseDescriptor,
    profileId: FirmwareProfileId,
  ) => Promise<VerifiedFirmwareProfile>;
  readonly verifyPreviewProfile?: (
    preview: LocalFirmwarePreviewDescriptor,
    profileId: LocalFirmwareProfileId,
  ) => Promise<VerifiedLocalPreviewProfile>;
}

const consentItems = [
  {
    id: "profile",
    label:
      "My module matches the selected chip, silicon revision, flash, and PSRAM profile.",
  },
  {
    id: "backup",
    label: "I backed up the board files and previous firmware I need.",
  },
  {
    id: "erase",
    label: "I understand that installation erases the device.",
  },
  {
    id: "power",
    label: "I am using a data-capable USB cable and stable power.",
  },
  {
    id: "port",
    label: "I closed serial monitors and other apps using this port.",
  },
] as const;

const exactBoardConsentItem = {
  id: "exactBoard",
  label:
    "My board is the exact ESP32-S3-LCD-1.47B B-version with 16 MiB flash and 8 MiB Octal PSRAM.",
} as const;

type ConsentId =
  (typeof consentItems)[number]["id"] | typeof exactBoardConsentItem.id;
type InstallerPhase = "idle" | "verifying" | "verified" | "failed";

function browserCapabilities(): BrowserCapabilities {
  if (typeof window === "undefined" || typeof navigator === "undefined") {
    return {
      secureContext: false,
      webSerial: false,
      webCrypto: false,
    };
  }
  return {
    secureContext: window.isSecureContext,
    webSerial: "serial" in navigator,
    webCrypto: typeof crypto !== "undefined" && Boolean(crypto.subtle),
  };
}

function subscribeToBrowserCapabilities() {
  return () => undefined;
}

function browserCapabilitySnapshot() {
  const capabilities = browserCapabilities();
  return [
    capabilities.secureContext ? "1" : "0",
    capabilities.webSerial ? "1" : "0",
    capabilities.webCrypto ? "1" : "0",
  ].join("");
}

function serverCapabilitySnapshot() {
  return null;
}

function capabilitiesFromSnapshot(
  snapshot: string | null,
): BrowserCapabilities | null {
  if (snapshot === null) {
    return null;
  }
  return {
    secureContext: snapshot[0] === "1",
    webSerial: snapshot[1] === "1",
    webCrypto: snapshot[2] === "1",
  };
}

async function loadEspWebTools() {
  await import("esp-web-tools");
}

function profileDescription(profile: FirmwareProfileDescriptor) {
  if (profile.id === "esp32-s3-n16r8") {
    return "ESP32-S3 · N16R8 · 16 MiB flash · 8 MiB Octal PSRAM · lean generic · no TFT and no splash";
  }
  if (profile.id === "waveshare-esp32-s3-lcd-147b") {
    return "Exact B-version board · 16 MiB flash · 8 MiB Octal PSRAM · bundled ST7789 display runtime and fresh-install splash";
  }
  return "ESP32 · 4 MiB flash · no PSRAM required";
}

function policyFailure(release: FirmwareReleaseDescriptor | null | undefined) {
  if (!release) {
    return {
      heading: "Installer unavailable",
      body: "Hardware validation is still required on every profile included in a future v0.6.0-derived candidate before the public installer can be enabled.",
    };
  }
  if (release.deployment !== "public" && release.deployment !== "candidate") {
    if (
      release.deployment !== "public-beta" ||
      !isExactPublicBetaFirmwareRelease(release)
    ) {
      return {
        heading: "Installer unavailable",
        body: "The selected firmware deployment mode is invalid, so installation remains unavailable.",
      };
    }
  }
  if (
    release.deployment === "public-beta" &&
    !isExactPublicBetaFirmwareRelease(release)
  ) {
    return {
      heading: "Installer unavailable",
      body: "The public beta does not match the exact audited v0.4.2 firmware, so installation remains unavailable.",
    };
  }
  if (
    release.deployment !== "public-beta" &&
    !hasExactFirmwareProfileDescriptors(release.version, release.profiles)
  ) {
    return {
      heading: "Installer unavailable",
      body: "The selected firmware profile set is invalid, so installation remains unavailable.",
    };
  }
  if (release.deployment === "public" && release.hilStatus !== "passed") {
    return {
      heading: "Public installer unavailable",
      body: "Hardware validation is pending, so this public build remains fail-closed.",
    };
  }
  if (
    release.deployment === "public" &&
    !releaseIncludesWaveshareLcd147b(release)
  ) {
    return {
      heading: "Public installer unavailable",
      body: "The selected public descriptor is not an unrestricted qualified v0.5.1-or-newer release, so installation remains unavailable.",
    };
  }
  if (release.deployment === "candidate" && !release.accessControlled) {
    return {
      heading: "Candidate installer unavailable",
      body: "A candidate build must be explicitly access-controlled before it can expose the installer.",
    };
  }
  return null;
}

function capabilityFailure(capabilities: BrowserCapabilities) {
  if (!capabilities.secureContext) {
    return "Open this page over HTTPS before using the wired installer.";
  }
  if (!capabilities.webSerial) {
    return "Use a current desktop Chromium browser with Web Serial support.";
  }
  if (!capabilities.webCrypto) {
    return "Web Crypto verification is not available in this browser.";
  }
  return null;
}

function FlashStatusForRelease({
  capabilities: providedCapabilities,
  installArtifactFetch = (profile, releaseKey) =>
    installReleaseKeyedArtifactFetch({
      paths: [profile.manifestPath, profile.firmwarePath],
      releaseKey,
    }),
  loadInstaller = loadEspWebTools,
  release = null,
  verifyProfile = async (selectedRelease, profileId) =>
    verifyFirmwareProfile({
      descriptor: selectedRelease,
      profileId,
    }),
}: FlashStatusProps) {
  const detectedCapabilities = capabilitiesFromSnapshot(
    useSyncExternalStore(
      subscribeToBrowserCapabilities,
      browserCapabilitySnapshot,
      serverCapabilitySnapshot,
    ),
  );
  const capabilities = providedCapabilities ?? detectedCapabilities;
  const verificationAttempt = useRef(0);
  const artifactFetchCleanup = useRef<(() => void) | null>(null);

  useEffect(() => {
    verificationAttempt.current += 1;
    return () => {
      verificationAttempt.current += 1;
      artifactFetchCleanup.current?.();
      artifactFetchCleanup.current = null;
    };
  }, [release]);
  const [selectedId, setSelectedId] = useState<FirmwareProfileId | null>(null);
  const [consents, setConsents] = useState<Record<ConsentId, boolean>>({
    profile: false,
    backup: false,
    erase: false,
    power: false,
    port: false,
    exactBoard: false,
  });
  const [phase, setPhase] = useState<InstallerPhase>("idle");
  const [verified, setVerified] = useState<VerifiedFirmwareProfile | null>(
    null,
  );
  const [failure, setFailure] = useState<string | null>(null);

  const policy = policyFailure(release);
  if (policy) {
    return (
      <section
        className="flash-status"
        aria-labelledby="installer-status-title"
      >
        <div role="status" className="flash-status__message">
          <p className="flash-status__eyebrow">Installer status</p>
          <h2 id="installer-status-title">{policy.heading}</h2>
          <p>{policy.body}</p>
        </div>
        <button
          className="button button--primary button--disabled"
          type="button"
          disabled
        >
          Installer coming soon
        </button>
      </section>
    );
  }
  // policyFailure always returns a message for the null selection. This
  // explicit guard also keeps the active branch narrowed for TypeScript.
  if (!release) {
    return null;
  }
  const activeRelease = release;

  if (!capabilities) {
    return (
      <section
        className="flash-status"
        aria-labelledby="installer-status-title"
      >
        <div role="status" className="flash-status__message">
          <p className="flash-status__eyebrow">Installer status</p>
          <h2 id="installer-status-title">Checking browser support</h2>
          <p>
            Detecting the secure-context, Web Serial, and Web Crypto
            capabilities required for wired provisioning.
          </p>
        </div>
      </section>
    );
  }

  const capability = capabilityFailure(capabilities);
  if (capability) {
    return (
      <section
        className="flash-status"
        aria-labelledby="installer-status-title"
      >
        <div role="status" className="flash-status__message">
          <p className="flash-status__eyebrow">Installer unsupported here</p>
          <h2 id="installer-status-title">Use a supported desktop browser</h2>
          <p>{capability}</p>
        </div>
        <p>
          iPadOS cannot perform this wired Web Serial provisioning step. After
          provisioning on a desktop, use the tablet-first PyBLE app over BLE.
        </p>
      </section>
    );
  }

  const selectedProfile = activeRelease.profiles.find(
    ({ id }) => id === selectedId,
  );
  const requiredConsentItems =
    selectedProfile?.id === "waveshare-esp32-s3-lcd-147b"
      ? [...consentItems, exactBoardConsentItem]
      : consentItems;
  const everyConsent = requiredConsentItems.every(({ id }) => consents[id]);
  const candidate = activeRelease.deployment === "candidate";
  const publicBeta = activeRelease.deployment === "public-beta";

  function chooseProfile(profileId: FirmwareProfileId) {
    verificationAttempt.current += 1;
    artifactFetchCleanup.current?.();
    artifactFetchCleanup.current = null;
    setSelectedId(profileId);
    setConsents({
      profile: false,
      backup: false,
      erase: false,
      power: false,
      port: false,
      exactBoard: false,
    });
    setPhase("idle");
    setVerified(null);
    setFailure(null);
  }

  function updateConsent(id: ConsentId, checked: boolean) {
    verificationAttempt.current += 1;
    artifactFetchCleanup.current?.();
    artifactFetchCleanup.current = null;
    setConsents((current) => ({ ...current, [id]: checked }));
    setPhase("idle");
    setVerified(null);
    setFailure(null);
  }

  async function startVerification() {
    if (!selectedId || !everyConsent) {
      return;
    }
    const attempt = ++verificationAttempt.current;
    const requestedProfileId = selectedId;
    artifactFetchCleanup.current?.();
    artifactFetchCleanup.current = null;
    setPhase("verifying");
    setVerified(null);
    setFailure(null);
    try {
      const result = await verifyProfile(activeRelease, requestedProfileId);
      if (attempt !== verificationAttempt.current) {
        return;
      }
      const cleanupFetch = installArtifactFetch(
        result,
        activeRelease.releaseJson.sha256,
      );
      if (attempt !== verificationAttempt.current) {
        cleanupFetch();
        return;
      }
      artifactFetchCleanup.current = cleanupFetch;
      await loadInstaller();
      if (attempt !== verificationAttempt.current) {
        cleanupFetch();
        if (artifactFetchCleanup.current === cleanupFetch) {
          artifactFetchCleanup.current = null;
        }
        return;
      }
      setVerified(result);
      setPhase("verified");
    } catch (error) {
      artifactFetchCleanup.current?.();
      artifactFetchCleanup.current = null;
      if (attempt !== verificationAttempt.current) {
        return;
      }
      setFailure(error instanceof Error ? error.message : "Unknown error");
      setPhase("failed");
    }
  }

  const releaseDate = new Intl.DateTimeFormat("en-US", {
    day: "numeric",
    month: "long",
    timeZone: "UTC",
    year: "numeric",
  }).format(new Date(activeRelease.builtAt));
  const includesWaveshareLcd147b =
    releaseIncludesWaveshareLcd147b(activeRelease);

  return (
    <section className="flash-status" aria-labelledby="installer-status-title">
      <div className="flash-status__header">
        <div>
          <p className="flash-status__eyebrow">Installer status</p>
          <h2 id="installer-status-title">
            {candidate
              ? "Protected release candidate"
              : publicBeta
                ? "Hardware-tested firmware beta"
                : "Qualified release"}
          </h2>
        </div>
      </div>

      <div
        role={candidate || publicBeta ? "status" : undefined}
        className="flash-status__message"
      >
        {candidate
          ? "Protected release candidate: hardware validation is pending."
          : publicBeta
            ? "Hardware-tested firmware beta: exact PyBLE v0.4.2 browser installation and interrupted-flash recovery passed on real esp32-4mb and esp32-s3-n16r8 hardware. Complete release qualification is still pending; this is not a qualified release."
            : "Select and verify the exact module profile before installation."}
      </div>

      <div
        className="profile-options"
        role="radiogroup"
        aria-label="Select the exact module profile"
      >
        {activeRelease.profiles.map((profile) => (
          <label key={profile.id} className="profile-option">
            <input
              type="radio"
              name="firmware-profile"
              value={profile.id}
              checked={selectedId === profile.id}
              onChange={() => chooseProfile(profile.id)}
            />
            <span>
              <strong>{profile.id}</strong>
              {profileDescription(profile)}
            </span>
          </label>
        ))}
      </div>

      <p className="flash-warning">
        The <strong>esp32-s3-n16r8</strong> image is not for every ESP32-S3
        board. It requires 16 MiB flash and 8 MiB Octal PSRAM and is the lean,
        board-neutral image: it bundles no Waveshare TFT runtime or boot splash.
      </p>

      {includesWaveshareLcd147b ? (
        <p className="flash-warning">
          The <strong>waveshare-esp32-s3-lcd-147b</strong> image is only for the
          exact ESP32-S3-LCD-1.47B B-version. ESP32-S3 family detection and
          matching N16R8 memory do not identify the board or its display wiring.
        </p>
      ) : null}

      {selectedProfile ? (
        <div
          className="consent-list"
          aria-label="Installation acknowledgements"
        >
          {requiredConsentItems.map(({ id, label }) => (
            <label key={id}>
              <input
                type="checkbox"
                checked={consents[id]}
                onChange={(event) => updateConsent(id, event.target.checked)}
              />
              <span>{label}</span>
            </label>
          ))}
        </div>
      ) : null}

      {selectedProfile && phase !== "verified" ? (
        <button
          className="button button--primary verify-button"
          type="button"
          disabled={!everyConsent || phase === "verifying"}
          onClick={startVerification}
        >
          Verify firmware for {selectedProfile.label}
        </button>
      ) : null}

      {phase === "verifying" ? (
        <div role="status" className="verification-state">
          Verifying firmware metadata, manifest, and merged image…
        </div>
      ) : null}

      {phase === "failed" ? (
        <div role="alert" className="verification-error">
          <strong>Firmware verification failed.</strong>
          <p>{failure}</p>
          <p>No firmware was written. Check the release and try again.</p>
        </div>
      ) : null}

      {phase === "verified" && verified ? (
        <div className="verified-installer">
          <p className="verification-success">Artifacts verified.</p>
          <dl>
            <div>
              <dt>Profile</dt>
              <dd>{verified.profileId}</dd>
            </div>
            <div>
              <dt>Firmware</dt>
              <dd>
                {verified.version} · {releaseDate}
              </dd>
            </div>
          </dl>
          <p>
            Installation erases the device. Keep stable power connected and
            select only the serial port for this board.
          </p>
          {publicBeta ? (
            <p className="flash-warning">
              Browser installation and interrupted-flash recovery passed on real
              hardware for this exact profile. Complete release qualification is
              still pending.
            </p>
          ) : null}
          <a className="text-link" href={activeRelease.recoveryPath}>
            {`Version ${verified.version} recovery instructions`}
          </a>
          <esp-web-install-button manifest={verified.manifestPath}>
            <button
              className="button button--primary"
              type="button"
              slot="activate"
            >
              {publicBeta
                ? `Install PyBLE ${verified.version} beta`
                : `Install PyBLE ${verified.version}`}
            </button>
          </esp-web-install-button>
        </div>
      ) : null}
    </section>
  );
}

const previewConsentItems = [
  {
    id: "profile",
    label: "This is the exact board and memory profile I selected.",
  },
  {
    id: "backup",
    label: "I backed up the board files and previous firmware I need.",
  },
  {
    id: "erase",
    label: "I understand this operation overwrites the board firmware.",
  },
  {
    id: "power",
    label: "I am using a data-capable USB cable and stable power.",
  },
] as const;

const previewSerialConsent = {
  id: "port",
  label: "I closed serial monitors and other apps using this port.",
} as const;

const previewExactBoardConsent = {
  id: "exactBoard",
  label:
    "This is the exact ESP32-S3-LCD-1.47B B version with 16 MiB flash and 8 MiB Octal PSRAM.",
} as const;

type PreviewConsentId =
  | (typeof previewConsentItems)[number]["id"]
  | typeof previewSerialConsent.id
  | typeof previewExactBoardConsent.id;

function previewMethodLabel(profile: LocalFirmwarePreviewProfile) {
  return profile.method === "esp-web-tools"
    ? "ESP32 Web Tools · Web Serial direct install"
    : "RP2 UF2 download · BOOTSEL copy";
}

function previewWarning(profileId: LocalFirmwareProfileId) {
  if (profileId === "esp32-s3-n16r8") {
    return "Requires 16 MiB flash and 8 MiB Octal PSRAM. This lean image includes no display runtime and no splash.";
  }
  if (profileId === "waveshare-esp32-s3-lcd-147b") {
    return "Use only the exact ESP32-S3-LCD-1.47B B version. Chip-family detection does not prove its display wiring.";
  }
  if (profileId === "esp32-c3-4mb") {
    return "Use only an ESP32-C3 revision v0.3 or newer with 4 MiB flash. Production qualification is pending.";
  }
  if (profileId === "rpi-pico2-w") {
    return "Disconnect the Pico 2 W, hold BOOTSEL while you connect USB, wait for the RP2350 volume, then copy the verified UF2.";
  }
  return "Use only a classical ESP32 module with exactly 4 MiB flash and no PSRAM requirement.";
}

function LocalFlashPreview({
  capabilities: providedCapabilities,
  loadInstaller = loadEspWebTools,
  preview,
  verifyPreviewProfile = async (descriptor, profileId) =>
    verifyLocalFirmwarePreviewProfile({ descriptor, profileId }),
}: {
  capabilities?: BrowserCapabilities;
  loadInstaller?: () => Promise<void>;
  preview: LocalFirmwarePreviewDescriptor;
  verifyPreviewProfile?: (
    descriptor: LocalFirmwarePreviewDescriptor,
    profileId: LocalFirmwareProfileId,
  ) => Promise<VerifiedLocalPreviewProfile>;
}) {
  const detectedCapabilities = capabilitiesFromSnapshot(
    useSyncExternalStore(
      subscribeToBrowserCapabilities,
      browserCapabilitySnapshot,
      serverCapabilitySnapshot,
    ),
  );
  const capabilities = providedCapabilities ?? detectedCapabilities;
  const attempt = useRef(0);
  const artifactFetchCleanup = useRef<(() => void) | null>(null);
  const downloadUrl = useRef<string | null>(null);
  const [selectedId, setSelectedId] = useState<LocalFirmwareProfileId | null>(
    null,
  );
  const [consents, setConsents] = useState<Record<PreviewConsentId, boolean>>({
    profile: false,
    backup: false,
    erase: false,
    power: false,
    port: false,
    exactBoard: false,
  });
  const [phase, setPhase] = useState<InstallerPhase>("idle");
  const [verified, setVerified] = useState<VerifiedLocalPreviewProfile | null>(
    null,
  );
  const [failure, setFailure] = useState<string | null>(null);

  function clearVerifiedResources() {
    artifactFetchCleanup.current?.();
    artifactFetchCleanup.current = null;
    if (downloadUrl.current?.startsWith("blob:")) {
      URL.revokeObjectURL?.(downloadUrl.current);
    }
    downloadUrl.current = null;
  }

  useEffect(() => {
    attempt.current += 1;
    return () => {
      attempt.current += 1;
      artifactFetchCleanup.current?.();
      if (downloadUrl.current?.startsWith("blob:")) {
        URL.revokeObjectURL?.(downloadUrl.current);
      }
    };
  }, [preview]);

  const loopback =
    typeof window === "undefined" ||
    isLoopbackHostname(window.location.hostname);
  if (!loopback) {
    return (
      <section
        className="flash-status"
        aria-labelledby="installer-status-title"
      >
        <div role="status" className="flash-status__message">
          <p className="flash-status__eyebrow">Local preview refused</p>
          <h2 id="installer-status-title">Use the loopback preview URL</h2>
          <p>This unqualified harness runs only on localhost.</p>
        </div>
      </section>
    );
  }

  if (!capabilities) {
    return (
      <section
        className="flash-status"
        aria-labelledby="installer-status-title"
      >
        <div role="status" className="flash-status__message">
          <p className="flash-status__eyebrow">Local engineering preview</p>
          <h2 id="installer-status-title">Checking browser support</h2>
          <p>Detecting the browser capabilities required for verification.</p>
        </div>
      </section>
    );
  }

  const selectedProfile = preview.profiles.find(({ id }) => id === selectedId);
  const profileContract = localFirmwareProfileTable.find(
    ({ id }) => id === selectedId,
  );
  const requiredConsents = selectedProfile
    ? [
        ...previewConsentItems,
        ...(selectedProfile.method === "esp-web-tools"
          ? [previewSerialConsent]
          : []),
        ...(selectedProfile.id === "waveshare-esp32-s3-lcd-147b"
          ? [previewExactBoardConsent]
          : []),
      ]
    : [];
  const everyConsent = requiredConsents.every(({ id }) => consents[id]);
  const capabilityMessage = !capabilities.secureContext
    ? "This local preview requires a secure loopback browser context."
    : !capabilities.webCrypto
      ? "This local preview requires Web Crypto artifact verification."
      : selectedProfile?.method === "esp-web-tools" && !capabilities.webSerial
        ? "This ESP target requires a current desktop Chromium browser with Web Serial support."
        : null;

  function resetState(nextId: LocalFirmwareProfileId | null) {
    attempt.current += 1;
    clearVerifiedResources();
    setSelectedId(nextId);
    setConsents({
      profile: false,
      backup: false,
      erase: false,
      power: false,
      port: false,
      exactBoard: false,
    });
    setPhase("idle");
    setVerified(null);
    setFailure(null);
  }

  function updateConsent(id: PreviewConsentId, checked: boolean) {
    attempt.current += 1;
    clearVerifiedResources();
    setConsents((current) => ({ ...current, [id]: checked }));
    setPhase("idle");
    setVerified(null);
    setFailure(null);
  }

  async function startPreviewVerification() {
    if (!selectedProfile || !everyConsent || capabilityMessage) {
      return;
    }
    const verificationAttempt = ++attempt.current;
    clearVerifiedResources();
    setPhase("verifying");
    setVerified(null);
    setFailure(null);
    try {
      const result = await verifyPreviewProfile(preview, selectedProfile.id);
      if (verificationAttempt !== attempt.current) {
        if (result.downloadUrl?.startsWith("blob:")) {
          URL.revokeObjectURL?.(result.downloadUrl);
        }
        return;
      }
      if (result.method === "esp-web-tools") {
        if (!result.manifestPath) {
          throw new Error("Verified ESP profile has no manifest");
        }
        artifactFetchCleanup.current =
          result.verifiedManifestBytes && result.verifiedFirmwareBytes
            ? installVerifiedLocalPreviewFetch({ profile: result })
            : installReleaseKeyedArtifactFetch({
                paths: [result.manifestPath, result.firmwarePath],
                releaseKey: selectedProfile.firmware.sha256,
              });
        await loadInstaller();
      } else if (!result.downloadUrl?.startsWith("blob:")) {
        throw new Error("Verified Pico 2 W profile has no in-memory download");
      } else {
        downloadUrl.current = result.downloadUrl;
      }
      if (verificationAttempt !== attempt.current) {
        clearVerifiedResources();
        return;
      }
      setVerified(result);
      setPhase("verified");
    } catch (error) {
      clearVerifiedResources();
      if (verificationAttempt !== attempt.current) {
        return;
      }
      setFailure(error instanceof Error ? error.message : "Unknown error");
      setPhase("failed");
    }
  }

  return (
    <section
      className="flash-status flash-status--preview"
      aria-labelledby="installer-status-title"
    >
      <div
        role={phase === "idle" ? "status" : undefined}
        className="flash-status__message flash-status__message--preview"
      >
        <p className="flash-status__eyebrow">Local engineering preview</p>
        <h2 id="installer-status-title">
          Unqualified firmware v{preview.version}
        </h2>
        <p>
          LOCAL ENGINEERING PREVIEW — UNQUALIFIED. This is not a public release
          or a supported-hardware claim.
        </p>
      </div>

      <label className="profile-select" htmlFor="local-firmware-target">
        <span>Choose a firmware target</span>
        <select
          id="local-firmware-target"
          value={selectedId ?? ""}
          onChange={(event) =>
            resetState(
              (event.target.value || null) as LocalFirmwareProfileId | null,
            )
          }
        >
          <option value="">Select your exact board…</option>
          <optgroup label="ESP — direct install with Web Serial">
            {preview.profiles
              .filter(({ method }) => method === "esp-web-tools")
              .map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {localFirmwareProfileTable.find(({ id }) => id === profile.id)
                    ?.selectLabel ?? profile.label}
                </option>
              ))}
          </optgroup>
          <optgroup label="RP2 — UF2 / BOOTSEL">
            {preview.profiles
              .filter(({ method }) => method === "uf2-download")
              .map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {localFirmwareProfileTable.find(({ id }) => id === profile.id)
                    ?.selectLabel ?? profile.label}
                </option>
              ))}
          </optgroup>
        </select>
      </label>

      {selectedProfile && profileContract ? (
        <div
          className="profile-detail"
          role="region"
          aria-label="Selected firmware target details"
        >
          <div className="profile-detail__heading">
            <div>
              <p className="eyebrow">Selected target</p>
              <h3>{profileContract.selectLabel}</h3>
            </div>
            <span className="preview-badge">
              LOCAL ENGINEERING PREVIEW — UNQUALIFIED
            </span>
          </div>
          <dl>
            <div>
              <dt>Profile ID</dt>
              <dd>{selectedProfile.id}</dd>
            </div>
            <div>
              <dt>Method</dt>
              <dd>{previewMethodLabel(selectedProfile)}</dd>
            </div>
            <div>
              <dt>Firmware</dt>
              <dd>Version {preview.version}</dd>
            </div>
            <div>
              <dt>Source commit</dt>
              <dd>
                <code>{preview.sourceCommit}</code>
              </dd>
            </div>
            <div>
              <dt>Requirements</dt>
              <dd>{profileContract.requirements}</dd>
            </div>
            <div>
              <dt>Artifact</dt>
              <dd>
                {selectedProfile.firmware.path.split("/").at(-1)} ·{" "}
                {selectedProfile.firmware.size.toLocaleString("en-US")} bytes
              </dd>
            </div>
            <div>
              <dt>Firmware SHA-256</dt>
              <dd>
                <code>{selectedProfile.firmware.sha256}</code>
              </dd>
            </div>
            {selectedProfile.method === "esp-web-tools" ? (
              <div>
                <dt>Manifest SHA-256</dt>
                <dd>
                  <code>{selectedProfile.manifest.sha256}</code>
                </dd>
              </div>
            ) : null}
            <div>
              <dt>Destructive effect</dt>
              <dd>
                {selectedProfile.method === "esp-web-tools"
                  ? "Installation erases and overwrites the existing firmware and user workspace."
                  : "Copying the UF2 overwrites installed firmware; back up board files first."}
              </dd>
            </div>
            <div>
              <dt>Next action</dt>
              <dd>
                {selectedProfile.method === "esp-web-tools"
                  ? "Verify the exact local bytes, then install through Web Serial."
                  : "Verify and download the exact UF2, then copy it to the RP2350 BOOTSEL volume."}
              </dd>
            </div>
          </dl>
          <p className="flash-warning">{previewWarning(selectedProfile.id)}</p>
          {capabilityMessage ? (
            <p role="alert" className="verification-error">
              {capabilityMessage}
            </p>
          ) : null}

          <fieldset
            className="consent-list"
            aria-label="Installation acknowledgements"
          >
            <legend>Installation acknowledgements</legend>
            {requiredConsents.map(({ id, label }) => (
              <label key={id}>
                <input
                  type="checkbox"
                  checked={consents[id]}
                  onChange={(event) => updateConsent(id, event.target.checked)}
                />
                <span>
                  {id === "erase"
                    ? selectedProfile.method === "esp-web-tools"
                      ? "I understand this installation erases the existing firmware and user workspace."
                      : "I understand copying the UF2 overwrites the installed board firmware."
                    : label}
                </span>
              </label>
            ))}
          </fieldset>

          {phase !== "verified" ? (
            <button
              className="button button--primary verify-button"
              type="button"
              disabled={
                !everyConsent ||
                Boolean(capabilityMessage) ||
                phase === "verifying"
              }
              onClick={startPreviewVerification}
            >
              Verify firmware for {profileContract.selectLabel}
            </button>
          ) : null}
          {phase === "verifying" ? (
            <p role="status" className="verification-state">
              Verifying local manifest and firmware bytes…
            </p>
          ) : null}
          {phase === "failed" ? (
            <div role="alert" className="verification-error">
              <strong>Local artifact verification failed.</strong>
              <p>{failure}</p>
              <p>No firmware was written.</p>
            </div>
          ) : null}
          {phase === "verified" && verified ? (
            <div className="verified-installer">
              <p className="verification-success">Local artifacts verified.</p>
              {verified.method === "esp-web-tools" && verified.manifestPath ? (
                <esp-web-install-button manifest={verified.manifestPath}>
                  <button
                    className="button button--primary"
                    type="button"
                    slot="activate"
                  >
                    Install local PyBLE {verified.version}
                  </button>
                </esp-web-install-button>
              ) : verified.downloadUrl ? (
                <>
                  <a
                    className="button button--primary"
                    href={verified.downloadUrl}
                    download={`pyble-${verified.version}-rpi-pico2-w.uf2`}
                  >
                    Download verified UF2
                  </a>
                  <ol className="preview-steps">
                    <li>Disconnect the Pico 2 W.</li>
                    <li>
                      Keep the BOOTSEL button pressed while reconnecting USB.
                    </li>
                    <li>
                      Copy the downloaded UF2 to the mounted RP2350 volume.
                    </li>
                    <li>
                      Wait for reboot, then confirm the PyBLE BLE advertisement.
                    </li>
                  </ol>
                </>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export function FlashStatus(props: FlashStatusProps) {
  if (props.preview) {
    const previewIdentity = JSON.stringify(props.preview);
    return (
      <LocalFlashPreview
        key={previewIdentity}
        capabilities={props.capabilities}
        loadInstaller={props.loadInstaller}
        preview={props.preview}
        verifyPreviewProfile={props.verifyPreviewProfile}
      />
    );
  }
  const releaseIdentity = JSON.stringify(props.release ?? null);
  return <FlashStatusForRelease key={releaseIdentity} {...props} />;
}
