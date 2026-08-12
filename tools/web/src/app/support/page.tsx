// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { ExternalIcon, MailIcon } from "@/components/icons";
import { PageIntro } from "@/components/page-intro";
import { releaseIncludesWaveshareLcd147b } from "@/lib/firmware-release";
import { firmwareReleaseSelectedAtBuild } from "@/lib/firmware-release-selection";
import { pageMetadata, siteConfig } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Support",
  description:
    "Get started with the PyBLE beta, troubleshoot BLE connections, and send a useful issue report.",
  path: "/support",
});

const diagnosticItems = [
  "Exact installer profile ID (or “not installer-related”)",
  "Exact board model and module marking",
  "Flash capacity, PSRAM capacity, and PSRAM type",
  "Browser name/version and desktop OS name/version",
  "Failed installer stage and redacted error text",
  "Exact tablet or device model",
  "Tablet OS: iPadOS or Android name/version",
  "PyBLE app and agent versions",
  "The exact steps that caused the problem",
] as const;

export default function SupportPage() {
  const firmwareRelease = firmwareReleaseSelectedAtBuild();
  const publicBeta = firmwareRelease?.deployment === "public-beta";
  const qualifiedPublic =
    firmwareRelease !== null &&
    releaseIncludesWaveshareLcd147b(firmwareRelease);

  return (
    <main id="main-content">
      <PageIntro eyebrow="Beta help" title="Support">
        <p>
          Start with the quick checks below. If the problem remains, send a
          small, reproducible report and we will help you narrow it down.
        </p>
      </PageIntro>

      <div className="container support-layout">
        <article className="prose support-content">
          <section aria-labelledby="getting-started">
            <h2 id="getting-started">Get started</h2>
            <ol className="numbered-guide">
              <li>
                <span>1</span>
                <div>
                  <h3>Check firmware status before installing</h3>
                  <p>
                    {publicBeta ? (
                      <>
                        The v{firmwareRelease.version} hardware-tested beta is
                        available for the exact esp32-4mb and esp32-s3-n16r8
                        profiles. Production Chrome install and
                        interrupted-flash recovery passed on both exact
                        profiles; complete release qualification continues.
                      </>
                    ) : qualifiedPublic ? (
                      <>
                        Qualified v{firmwareRelease.version} firmware is
                        available for three exact profiles: esp32-4mb, lean
                        generic esp32-s3-n16r8, and separate
                        waveshare-esp32-s3-lcd-147b. The Waveshare image alone
                        includes its TFT runtime and fresh-install splash.
                      </>
                    ) : (
                      <>
                        The firmware installer is currently unavailable. Check
                        this status again before provisioning a board.
                      </>
                    )}{" "}
                    ESP32-C3 is not currently available. Confirm the active
                    release, exact profile, and enabled action; this initial
                    step uses a cable.
                  </p>
                </div>
              </li>
              <li>
                <span>2</span>
                <div>
                  <h3>Power the board and open PyBLE</h3>
                  <p>
                    Allow Bluetooth access, choose the nearby PyBLE board, and
                    wait for the connected workspace.
                  </p>
                </div>
              </li>
              <li>
                <span>3</span>
                <div>
                  <h3>Choose pins explicitly</h3>
                  <p>
                    Boards route LEDs, buttons, and NeoPixels differently. Check
                    your board documentation before running GPIO code.
                  </p>
                </div>
              </li>
              <li>
                <span>4</span>
                <div>
                  <h3>Save, run, and watch the console</h3>
                  <p>
                    Keep the board powered; editing, files, execution, and
                    console traffic now travel over BLE.
                  </p>
                </div>
              </li>
            </ol>
          </section>

          <section aria-labelledby="connection-help">
            <h2 id="connection-help">If the board does not appear</h2>
            <div className="help-grid">
              <article>
                <h3>Restart nearby</h3>
                <p>
                  Power-cycle the board, keep it close to the tablet, and scan
                  again after its agent starts.
                </p>
              </article>
              <article>
                <h3>Check Bluetooth access</h3>
                <p>
                  Confirm Bluetooth is on and PyBLE still has the platform
                  permission needed to scan.
                </p>
              </article>
              <article>
                <h3>Release other connections</h3>
                <p>
                  Disconnect the board from another phone, tablet, or BLE tool
                  before trying again.
                </p>
              </article>
              <article>
                <h3>Confirm the firmware</h3>
                <p>
                  Generic MicroPython alone does not advertise the PyBLE
                  service; the matching PyBLE agent firmware must be installed.
                </p>
              </article>
            </div>
          </section>

          <section aria-labelledby="code-help">
            <h2 id="code-help">If code does not behave as expected</h2>
            <ul>
              <li>
                Read the full console traceback, beginning with the first error.
              </li>
              <li>
                Confirm the GPIO number, voltage, and wiring for your exact
                board.
              </li>
              <li>
                Stop the current program or soft reboot before running a new
                one.
              </li>
              <li>
                Reduce the program to the smallest file that still reproduces
                the behavior.
              </li>
            </ul>
          </section>
        </article>

        <aside className="report-card">
          <MailIcon />
          <p className="eyebrow">Send a useful report</p>
          <h2>Include these exact details</h2>
          <ul>
            {diagnosticItems.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <a
            className="button button--primary"
            href={siteConfig.bugReportUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open the GitHub bug template
            <ExternalIcon />
          </a>
          <p className="fine-print">
            Please remove Wi-Fi passwords, access tokens, and other private data
            and personal identifiers from screenshots or code before sending.
            For a private, non-security support question, email{" "}
            <a href={`mailto:${siteConfig.supportEmail}`}>
              {siteConfig.supportEmail}
            </a>
            .
          </p>
        </aside>
      </div>
    </main>
  );
}
