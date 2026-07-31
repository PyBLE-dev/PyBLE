"use client";

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { installReleaseKeyedArtifactFetch } from "@/lib/firmware-fetch-cache";
import { verifyFirmwareProfile } from "@/lib/firmware-integrity";
import {
  hasExactFirmwareProfileDescriptors,
  isExactPublicBetaFirmwareRelease,
  type FirmwareProfileDescriptor,
  type FirmwareProfileId,
  type FirmwareReleaseDescriptor,
  type VerifiedFirmwareProfile,
} from "@/lib/firmware-release";

export interface BrowserCapabilities {
  readonly secureContext: boolean;
  readonly webSerial: boolean;
  readonly webCrypto: boolean;
}

export interface FlashStatusProps {
  readonly capabilities?: BrowserCapabilities;
  readonly loadInstaller?: () => Promise<void>;
  readonly installArtifactFetch?: (
    profile: VerifiedFirmwareProfile,
    releaseKey: string,
  ) => () => void;
  readonly release?: FirmwareReleaseDescriptor | null;
  readonly verifyProfile?: (
    release: FirmwareReleaseDescriptor,
    profileId: FirmwareProfileId,
  ) => Promise<VerifiedFirmwareProfile>;
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

type ConsentId = (typeof consentItems)[number]["id"];
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
    return "ESP32-S3 · N16R8 · 16 MiB flash · 8 MiB Octal PSRAM";
  }
  return "ESP32 · 4 MiB flash · no PSRAM required";
}

function policyFailure(release: FirmwareReleaseDescriptor | null | undefined) {
  if (!release) {
    return {
      heading: "Installer unavailable",
      body: "Hardware validation is still required on both exact current release profiles before the public installer can be enabled.",
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
  if (!hasExactFirmwareProfileDescriptors(release.version, release.profiles)) {
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
  const everyConsent = consentItems.every(({ id }) => consents[id]);
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

  return (
    <section className="flash-status" aria-labelledby="installer-status-title">
      <div className="flash-status__header">
        <div>
          <p className="flash-status__eyebrow">Installer status</p>
          <h2 id="installer-status-title">
            {candidate
              ? "Protected release candidate"
              : publicBeta
                ? "Unqualified firmware beta"
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
            ? "Unqualified firmware beta: these exact v0.4.2 bytes passed the audited-candidate release gate, but full hardware-in-the-loop qualification is pending. They are not qualified. Use at your own risk."
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
        board. It requires 16 MiB flash and 8 MiB Octal PSRAM.
      </p>

      {selectedProfile ? (
        <div
          className="consent-list"
          aria-label="Installation acknowledgements"
        >
          {consentItems.map(({ id, label }) => (
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
              This is an unqualified beta with full HIL pending. Use at your own
              risk.
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
              {publicBeta ? "Install unqualified beta PyBLE" : "Install PyBLE"}{" "}
              {verified.version}
            </button>
          </esp-web-install-button>
        </div>
      ) : null}
    </section>
  );
}

export function FlashStatus(props: FlashStatusProps) {
  const releaseIdentity = JSON.stringify(props.release ?? null);
  return <FlashStatusForRelease key={releaseIdentity} {...props} />;
}
