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
import { initialFirmwareTargets, siteConfig } from "@/lib/site";

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

const steps = [
  {
    number: "01",
    title: "Provision once",
    body: "After v0.4.2 passes HIL, use USB once to install the exact matching PyBLE-enabled MicroPython profile. The public installer is unavailable during qualification.",
  },
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
  return (
    <main id="main-content">
      <section className="hero">
        <div className="container hero__grid">
          <div className="hero__copy">
            <div className="status-badge">
              <span className="status-dot" aria-hidden="true" />
              iPad beta now open
            </div>
            <p className="eyebrow eyebrow--light">
              Python over Bluetooth Low Energy
            </p>
            <h1>Code your MicroPython board. Leave the cable behind.</h1>
            <p className="hero__lede">
              PyBLE is a free, tablet-first IDE designed for boards that run
              MicroPython and support Bluetooth Low Energy. Public v0.4.2
              firmware is pending HIL for the exact esp32-4mb and esp32-s3-n16r8
              profiles. The public browser installer stays unavailable until
              both exact profiles pass HIL. ESP32-C3 and more microcontroller
              families remain planned.
            </p>
            <div className="button-row">
              <Link className="button button--primary" href="#testflight">
                Join the iPad beta
                <ArrowIcon />
              </Link>
              <Link className="button button--ghost" href="#workflow">
                See how it works
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
              Build offline with seven editable beginner examples, explicit
              numeric-GPIO blocks, and the standard MicroPython NeoPixel API.
              Generated Python is always visible and editable.
            </p>
            <ul className="check-list">
              <li>
                <CheckIcon />
                Choose the pin for your own board
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
              Initial beta firmware targets
            </p>
            <div
              className="target-grid"
              aria-label="Initial beta firmware targets"
            >
              {initialFirmwareTargets.map((target) => (
                <div
                  className={
                    target.planned
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
                  <small className="target-grid__status">{target.status}</small>
                </div>
              ))}
            </div>
          </div>
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
              Install the free iPad beta through Apple TestFlight now. Public
              board provisioning will open only after v0.4.2 passes HIL on both
              exact release profiles; after that one-time USB setup, everyday
              coding runs over Bluetooth Low Energy.
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
    </main>
  );
}
