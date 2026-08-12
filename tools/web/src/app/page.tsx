// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

import { AppCapture } from "@/components/app-capture";
import { BlocksVisual } from "@/components/blocks-visual";
import {
  ArrowIcon,
  BlocksIcon,
  CheckIcon,
  CodeIcon,
  ConsoleIcon,
  ExternalIcon,
  ProtocolIcon,
  RadioIcon,
  ShieldIcon,
} from "@/components/icons";
import { WaveshareBoardPhoto } from "@/components/waveshare-board-photo";
import { releaseIncludesWaveshareLcd147b } from "@/lib/firmware-release";
import {
  firmwareReleaseSelectedAtBuild,
  localFirmwarePreviewSelectedAtBuild,
} from "@/lib/firmware-release-selection";
import {
  firmwareTargetsForLocalPreview,
  firmwareTargetsForRelease,
  siteConfig,
} from "@/lib/site";

export const metadata: Metadata = {
  title: {
    absolute: "PyBLE — Python over Bluetooth Low Energy",
  },
  description: siteConfig.description,
  alternates: {
    canonical: siteConfig.origin,
  },
};

const features = [
  {
    icon: CodeIcon,
    title: "Editor and board files",
    body: "Write MicroPython with syntax-aware editing, then move files between your tablet and connected board.",
  },
  {
    icon: ConsoleIcon,
    title: "A live console",
    body: "Run, stop, soft reboot, and follow standard output and errors without returning to a USB terminal.",
  },
  {
    icon: BlocksIcon,
    title: "Blocks that stay useful",
    body: "Start visually, inspect generated Python, and move into a deliberately supported beginner Python subset.",
  },
  {
    icon: ProtocolIcon,
    title: "An open connection",
    body: "PBLE/1 is an open protocol, and both the tablet app and board agent are released under the MIT license.",
  },
] as const;

const workflowStepsAfterProvision = [
  {
    number: "02",
    title: "Connect from your tablet",
    body: "Open PyBLE, find your nearby board, and connect directly over Bluetooth Low Energy.",
  },
  {
    number: "03",
    title: "Create without the cable",
    body: "Edit files, build with Blocks, run code, and use the console through the BLE connection.",
  },
] as const;

export default function HomePage() {
  const preview = localFirmwarePreviewSelectedAtBuild();
  const firmwareRelease = preview ? null : firmwareReleaseSelectedAtBuild();
  const publicBeta = firmwareRelease?.deployment === "public-beta";
  const waveshareLcd147b = releaseIncludesWaveshareLcd147b(firmwareRelease);
  const qualifiedPublic = firmwareRelease !== null && waveshareLcd147b;
  const firmwareTargetGroupLabel = preview
    ? `Five exact v${preview.version} engineering targets`
    : qualifiedPublic
      ? "Qualified public firmware targets"
      : "Public firmware availability";
  const firmwareTargets = preview
    ? firmwareTargetsForLocalPreview(preview)
    : firmwareTargetsForRelease(firmwareRelease);
  const steps = [
    {
      number: "01",
      title: "Provision once",
      body: preview
        ? `Use USB once with the exact v${preview.version} engineering image for your target. The four ESP targets use Web Serial; Pico 2 W uses a verified UF2 download and BOOTSEL copy. Local preview bytes are unqualified.`
        : publicBeta
          ? `Use USB once to install the exact matching v${firmwareRelease.version} hardware-tested beta. Production Chrome install and interrupted-flash recovery passed on both exact profiles; complete release qualification continues.`
          : qualifiedPublic
            ? `Use USB once to install the exact matching qualified v${firmwareRelease.version} firmware.`
            : firmwareRelease
              ? `Check the protected candidate instructions before provisioning v${firmwareRelease.version}.`
              : "Check firmware status before provisioning; the installer is currently unavailable.",
    },
    ...workflowStepsAfterProvision,
  ];

  return (
    <main id="main-content">
      <section className="hero">
        <div className="container hero__grid">
          <div className="hero__copy">
            <div className="status-badge">
              <span className="status-dot" aria-hidden="true" />
              iPad external beta + Android internal test
            </div>
            <p className="eyebrow eyebrow--light">
              Python over Bluetooth Low Energy
            </p>
            <h1>Code your MicroPython board. Leave the cable behind.</h1>
            <p className="hero__lede">
              PyBLE is a free, open-source, tablet-first IDE designed for boards
              that run MicroPython and support Bluetooth Low Energy.{" "}
              {preview ? (
                <>
                  LOCAL ENGINEERING PREVIEW v{preview.version} — UNQUALIFIED.
                  This loopback build exposes exact local artifacts for five
                  firmware targets. These bytes are not a public release or
                  support claim.
                </>
              ) : publicBeta ? (
                <>
                  Public v{firmwareRelease.version} firmware is a
                  hardware-tested beta for the exact esp32-4mb and
                  esp32-s3-n16r8 profiles. Production Chrome install and
                  interrupted-flash recovery passed on both exact profiles;
                  complete release qualification continues.
                </>
              ) : qualifiedPublic ? (
                <>
                  Qualified public v{firmwareRelease.version} firmware is
                  available for esp32-4mb, lean generic esp32-s3-n16r8, and the
                  separate waveshare-esp32-s3-lcd-147b exact-board profile.
                </>
              ) : firmwareRelease ? (
                <>
                  Protected candidate v{firmwareRelease.version} is staged for
                  access-controlled qualification. It is not a public support
                  claim.
                </>
              ) : (
                <>
                  The firmware installer is currently unavailable; check its
                  status before provisioning a board.
                </>
              )}{" "}
              {!preview ? (
                <>
                  ESP32-C3 and Raspberry Pi Pico 2 W are under engineering
                  validation and remain unavailable in the public installer.
                </>
              ) : null}
            </p>
            <div className="button-row">
              <Link className="button button--primary" href="/app">
                Install PyBLE on iPad or Android
                <ArrowIcon />
              </Link>
              <Link className="button button--ghost" href="/flash">
                {preview
                  ? "Review five-target firmware preview"
                  : "Review firmware availability"}
              </Link>
            </div>
            <ul className="hero__proof" aria-label="PyBLE principles">
              <li>
                <CheckIcon />
                MIT open source
              </li>
              <li>
                <CheckIcon />
                Offline-first
              </li>
              <li>
                <CheckIcon />
                No account
              </li>
            </ul>
          </div>
          <AppCapture />
        </div>
      </section>

      <section className="principles" aria-label="Product principles">
        <div className="container principles__grid">
          <div>
            <RadioIcon />
            <p>
              <strong>BLE-first</strong>
              The cable is for initial setup, not your everyday workflow.
            </p>
          </div>
          <div>
            <ShieldIcon />
            <p>
              <strong>Private by default</strong>
              Your code stays on your tablet and the board you connect.
            </p>
          </div>
          <div>
            <ProtocolIcon />
            <p>
              <strong>Built in the open</strong>
              App, firmware, and PBLE/1 are free under the MIT license.
            </p>
          </div>
        </div>
      </section>

      <section className="section workflow" id="workflow">
        <div className="container">
          <div className="section-heading section-heading--center">
            <p className="eyebrow">A simpler development loop</p>
            <h2>One wired setup. Then build over BLE.</h2>
            <p>
              PyBLE keeps the familiar MicroPython workflow and removes the
              cable from the part you repeat all day.
            </p>
          </div>
          <ol className="steps">
            {steps.map((step) => (
              <li key={step.number}>
                <span>{step.number}</span>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </li>
            ))}
          </ol>
          <div className="button-row">
            <Link className="button button--secondary" href="/flash">
              Open firmware installer
              <ArrowIcon />
            </Link>
          </div>
        </div>
      </section>

      <section className="section section--tint" id="features">
        <div className="container">
          <div className="section-heading">
            <p className="eyebrow">A focused MicroPython workspace</p>
            <h2>Everything in the loop, close at hand.</h2>
            <p>
              PyBLE brings the essentials together without requiring an account,
              a cloud project, or a permanent USB connection.
            </p>
          </div>
          <div className="feature-grid">
            {features.map(({ icon: Icon, title, body }) => (
              <article className="feature-card" key={title}>
                <span className="feature-card__icon">
                  <Icon />
                </span>
                <h3>{title}</h3>
                <p>{body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section blocks-section" id="blocks">
        <div className="container split-layout">
          <BlocksVisual />
          <div className="split-layout__copy">
            <p className="eyebrow">From Blocks to Python</p>
            <h2>Start visually. See the real code.</h2>
            <p>
              Build offline with eight editable beginner examples, including an
              explicit TFT display example, explicit numeric or named GPIO pins
              such as <code>Pin(&quot;LED&quot;)</code>, and the standard
              MicroPython NeoPixel API. Generated Python is always visible and
              editable.
            </p>
            <ul className="check-list">
              <li>
                <CheckIcon />
                Enter the numeric GPIO or named pin for your own board
              </li>
              <li>
                <CheckIcon />
                Reopen exact workspaces from verified sidecars
              </li>
              <li>
                <CheckIcon />
                Convert a safe, bounded Python subset all-or-nothing
              </li>
            </ul>
            <p className="fine-print">
              Python-to-Blocks is intentionally bounded: unsupported Python
              stays untouched instead of producing a partial or misleading
              workspace.
            </p>
          </div>
        </div>
      </section>

      <section className="section compatibility">
        <div className="container compatibility__grid">
          <div>
            <p className="eyebrow eyebrow--light">Platform scope</p>
            <h2>MicroPython + Bluetooth, not one chip family.</h2>
            <p>
              PyBLE is designed for boards that can run MicroPython and host
              PBLE/1 over Bluetooth Low Energy. A validated PyBLE agent port is
              still required before a board is supported.
            </p>
          </div>
          <div className="compatibility__targets">
            <p className="compatibility__target-label">
              {firmwareTargetGroupLabel}
            </p>
            <div className="target-grid" aria-label={firmwareTargetGroupLabel}>
              {firmwareTargets.map((target) => (
                <div
                  className={
                    "preview" in target
                      ? "target-grid__target target-grid__target--preview"
                      : target.planned
                        ? "target-grid__target target-grid__target--planned"
                        : "target-grid__target"
                  }
                  key={target.id}
                >
                  <span className="target-grid__chip" aria-hidden="true">
                    <i />
                    <i />
                    <i />
                    <i />
                  </span>
                  <strong>{target.id}</strong>
                  <span className="target-grid__target-name">
                    {target.target}
                  </span>
                  <small className="target-grid__constraint">
                    {target.constraint}
                  </small>
                  {"method" in target ? (
                    <small className="target-grid__method">
                      {target.method}
                    </small>
                  ) : null}
                  <small className="target-grid__status">{target.status}</small>
                </div>
              ))}
            </div>
          </div>
          {waveshareLcd147b ? <WaveshareBoardPhoto showInstallerLink /> : null}
        </div>
      </section>

      <section
        className="section source-section"
        aria-labelledby="source-section-title"
      >
        <div className="container source-section__card">
          <div className="source-section__copy">
            <p className="eyebrow">Free and open source</p>
            <h2 id="source-section-title">See how PyBLE is built.</h2>
            <p className="source-section__lede">
              The tablet app, board-agent firmware, PBLE/1 protocol, tests, and
              documentation are developed in public under the MIT license.
              Explore how the pieces fit together, build from source, or help
              bring PyBLE to another MicroPython + BLE board.
            </p>
            <a
              className="button button--primary source-section__action"
              href={siteConfig.repositoryUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              Explore PyBLE on GitHub
              <ExternalIcon />
            </a>
          </div>

          <aside
            className="source-repository"
            aria-label="Inside the PyBLE repository"
          >
            <div className="source-repository__heading">
              <span className="source-repository__icon" aria-hidden="true">
                <CodeIcon />
              </span>
              <p>
                <strong>PyBLE-dev / PyBLE</strong>
                <small>Public repository · MIT license</small>
              </p>
            </div>
            <ul>
              <li>
                <code>app/</code>
                <span>Flutter tablet IDE</span>
              </li>
              <li>
                <code>firmware/</code>
                <span>MicroPython + BLE agent</span>
              </li>
              <li>
                <code>docs/</code>
                <span>PBLE/1 and public specifications</span>
              </li>
              <li>
                <code>tests/</code>
                <span>Conformance and release gates</span>
              </li>
            </ul>
          </aside>
        </div>
      </section>

      <section
        className="section beta-invite"
        id="testflight"
        aria-labelledby="testflight-title"
      >
        <div className="container beta-invite__card">
          <div className="beta-invite__copy">
            <p className="eyebrow">External testing is open</p>
            <h2 id="testflight-title">Join the PyBLE beta on TestFlight.</h2>
            <p className="beta-invite__lede">
              Install the free iPad external beta through Apple TestFlight.
              Firmware availability and qualification depend on the exact
              target; check the firmware installer before provisioning. After
              one-time USB setup, everyday coding runs over Bluetooth Low
              Energy.
            </p>
            <div className="button-row beta-invite__actions">
              <a
                className="button button--primary"
                href={siteConfig.testFlightUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open in TestFlight
                <ArrowIcon />
              </a>
              <Link className="button button--secondary" href="/flash">
                Check firmware status
              </Link>
            </div>
          </div>
          <figure className="beta-invite__qr">
            <a
              className="beta-invite__qr-link"
              href={siteConfig.testFlightUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Image
                src="/testflight/pyble-testflight-qr.svg"
                width={360}
                height={360}
                alt="QR code for the PyBLE beta on Apple TestFlight"
              />
            </a>
            <figcaption>
              <strong>Scan with your iPad camera</strong>
              <span>Or open this address on the device:</span>
              <span className="beta-invite__url">
                testflight.apple.com/join/yU4e8s6d
              </span>
            </figcaption>
          </figure>
        </div>
      </section>

      <section
        className="section beta-invite android-invite"
        id="android-internal-test"
        aria-labelledby="android-internal-test-title"
      >
        <div className="container beta-invite__card">
          <div className="beta-invite__copy">
            <p className="eyebrow">Android internal testing</p>
            <h2 id="android-internal-test-title">
              Join the PyBLE Android internal test.
            </h2>
            <p className="beta-invite__lede">
              The Android build is available only to approved internal testers
              signed in with an invited Google account. An unapproved or
              signed-out visitor may find the listing unavailable. This is not a
              public Google Play release.
            </p>
            <div className="button-row beta-invite__actions">
              <a
                className="button button--primary"
                href={siteConfig.googlePlayInternalTestUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open Android internal test
                <ArrowIcon />
              </a>
              <Link className="button button--secondary" href="/support">
                Get support
              </Link>
            </div>
          </div>
          <figure className="beta-invite__qr">
            <a
              className="beta-invite__qr-link"
              href={siteConfig.googlePlayInternalTestUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Image
                src="/google-play/pyble-google-play-internal-test-qr.svg"
                width={360}
                height={360}
                alt="QR code for the PyBLE Android internal test on Google Play"
              />
            </a>
            <figcaption>
              <strong>Scan with your Android camera</strong>
              <span>Sign in with the Google account that was invited:</span>
              <span className="beta-invite__url">
                {siteConfig.googlePlayInternalTestUrl}
              </span>
            </figcaption>
          </figure>
        </div>
      </section>
    </main>
  );
}
