// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { MailIcon } from "@/components/icons";
import { PageIntro } from "@/components/page-intro";
import { pageMetadata, siteConfig } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Support",
  description:
    "Get started with the PyBLE beta, troubleshoot BLE connections, and send a useful issue report.",
  path: "/support",
});

const diagnosticItems = [
  "Board and chip family",
  "PyBLE app and agent versions",
  "iPadOS or Android version",
  "The exact steps that caused the problem",
  "Relevant console text and a screenshot",
] as const;

export default function SupportPage() {
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
                  <h3>Install the matching firmware once</h3>
                  <p>
                    The initial beta firmware supports ESP32, ESP32-S3, and
                    ESP32-C3. Use the reviewed image supplied for your exact
                    target; this initial step uses a cable.
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
          <h2>Include these five things</h2>
          <ul>
            {diagnosticItems.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <a
            className="button button--primary"
            href={`mailto:${siteConfig.supportEmail}`}
          >
            {siteConfig.supportEmail}
          </a>
          <p className="fine-print">
            Please remove Wi-Fi passwords, access tokens, and other private data
            from screenshots or code before sending.
          </p>
        </aside>
      </div>
    </main>
  );
}
