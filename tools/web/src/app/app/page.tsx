// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

import { ArrowIcon, CheckIcon } from "@/components/icons";
import { PageIntro } from "@/components/page-intro";
import { pageMetadata, siteConfig } from "@/lib/site";

export const metadata: Metadata = pageMetadata({
  title: "PyBLE for iPad and Android",
  description:
    "Join the PyBLE iPad external beta on Apple TestFlight or the invited Android internal test on Google Play, then code compatible MicroPython boards over Bluetooth Low Energy.",
  path: "/app",
});

const gettingStartedSteps = [
  {
    number: "01",
    title: "Install a beta",
    body: "Use Apple TestFlight on iPad, or the invited-only Google Play internal test on Android.",
  },
  {
    number: "02",
    title: "Provision a supported board",
    body: "Use the browser installer once with the exact firmware profile that matches your board.",
  },
  {
    number: "03",
    title: "Connect over BLE",
    body: "Open PyBLE, select the nearby board, and edit, run, and inspect MicroPython without a USB cable.",
  },
] as const;

export default function AppPage() {
  return (
    <main id="main-content">
      <PageIntro
        eyebrow="PyBLE for iPad + Android"
        title="Install PyBLE on iPad or Android."
      >
        <p>
          Choose the public iPad external beta or the invited Android internal
          test. PyBLE is an open-source, tablet-first MicroPython IDE that
          connects to compatible boards over Bluetooth Low Energy.
        </p>
      </PageIntro>

      <section className="section app-install" aria-labelledby="install-title">
        <div className="container">
          <div className="section-heading app-install__heading">
            <p className="eyebrow">Current app testing</p>
            <h2 id="install-title">Choose your testing channel.</h2>
            <p>
              These are beta channels, not production App Store or public Google
              Play releases.
            </p>
          </div>

          <div className="app-install__channels">
            <article
              className="app-install__card"
              aria-labelledby="testflight-install-title"
            >
              <div className="app-install__copy">
                <div className="status-badge status-badge--light">
                  <span className="status-dot" aria-hidden="true" />
                  External testing is open
                </div>
                <p className="eyebrow">iPad · Apple TestFlight</p>
                <h3 id="testflight-install-title">
                  Join the iPad external beta.
                </h3>
                <p className="app-install__lede">
                  TestFlight handles installation and beta updates. Apple may
                  ask you to install the TestFlight app before accepting the
                  PyBLE invitation.
                </p>
                <a
                  className="button button--primary app-install__primary"
                  href={siteConfig.testFlightUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open PyBLE in TestFlight
                  <ArrowIcon />
                </a>
                <p className="app-install__direct">
                  If the button does not open, enter this address on your iPad:
                  <span>{siteConfig.testFlightUrl}</span>
                </p>
              </div>

              <figure className="app-install__qr">
                <a
                  className="app-install__qr-link"
                  href={siteConfig.testFlightUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Image
                    src="/testflight/pyble-testflight-qr.svg"
                    width={360}
                    height={360}
                    alt="QR code for the PyBLE beta on Apple TestFlight"
                    priority
                  />
                </a>
                <figcaption>
                  <strong>Scan with your iPad camera</strong>
                  <span>The code opens the same TestFlight invitation.</span>
                </figcaption>
              </figure>
            </article>

            <article
              className="app-install__card app-install__card--android"
              aria-labelledby="android-install-title"
              id="android"
            >
              <div className="app-install__copy">
                <div className="status-badge status-badge--light">
                  <span className="status-dot" aria-hidden="true" />
                  Internal testing is open to invited accounts
                </div>
                <p className="eyebrow">Android · Google Play</p>
                <h3 id="android-install-title">
                  Join the Android internal test.
                </h3>
                <p className="app-install__lede">
                  Only approved internal testers signed in with an invited
                  Google account can access this listing. An unapproved or
                  signed-out visitor may find it unavailable. This is not a
                  public Google Play release.
                </p>
                <a
                  className="button button--primary app-install__primary"
                  href={siteConfig.googlePlayInternalTestUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open Android internal test
                  <ArrowIcon />
                </a>
                <p className="app-install__direct">
                  Open this address on the invited Android device:
                  <span>{siteConfig.googlePlayInternalTestUrl}</span>
                </p>
              </div>

              <figure className="app-install__qr">
                <a
                  className="app-install__qr-link"
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
                  <span>Sign in with the Google account that was invited.</span>
                </figcaption>
              </figure>
            </article>
          </div>

          <div className="button-row app-install__secondary-actions app-install__support-actions">
            <Link className="button button--secondary" href="/learn/setup">
              Follow the setup tutorial
            </Link>
            <Link className="button button--secondary" href="/flash">
              Open firmware installer
            </Link>
            <Link className="button button--secondary" href="/support">
              Get support
            </Link>
          </div>
        </div>
      </section>

      <section
        className="section app-getting-started"
        aria-labelledby="getting-started-title"
      >
        <div className="container">
          <div className="section-heading section-heading--center">
            <p className="eyebrow">From install to first program</p>
            <h2 id="getting-started-title">Three steps to start coding.</h2>
          </div>
          <ol className="app-getting-started__steps">
            {gettingStartedSteps.map((step) => (
              <li key={step.number}>
                <span>{step.number}</span>
                <div>
                  <h3>{step.title}</h3>
                  <p>{step.body}</p>
                </div>
                <CheckIcon />
              </li>
            ))}
          </ol>
          <p className="app-getting-started__note">
            PyBLE requires compatible PBLE/1 agent firmware. A board running
            stock MicroPython is not automatically supported.
          </p>
        </div>
      </section>
    </main>
  );
}
