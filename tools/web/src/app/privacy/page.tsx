// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { MailIcon, ShieldIcon } from "@/components/icons";
import { PageIntro } from "@/components/page-intro";
import { pageMetadata, siteConfig } from "@/lib/site";

export const metadata = pageMetadata({
  title: "PyBLE Privacy Policy",
  description:
    "How the PyBLE app, direct board transfers, and pyble.dev handle user and device data.",
  path: "/privacy",
});

export default function PrivacyPage() {
  return (
    <main id="main-content">
      <PageIntro eyebrow="Plain-language privacy" title="PyBLE Privacy Policy">
        <p>
          PyBLE is designed to work locally. This policy explains what the app
          handles on your tablet, what you choose to send to a board, and what
          happens when you visit this website.
        </p>
        <p className="page-intro__meta">
          Effective <time dateTime="2026-08-07">7 August 2026</time>
        </p>
      </PageIntro>

      <div className="container policy-layout">
        <article className="prose policy">
          <section aria-labelledby="maintainer-identity">
            <h2 id="maintainer-identity">Who maintains PyBLE</h2>
            <p>
              PyBLE is an independent open-source project maintained by Viwat
              Vchirawongkwin under the SciLabPro project name. It is not an
              official Chulalongkorn University project or app.
            </p>
          </section>

          <section aria-labelledby="app-privacy">
            <span className="section-icon">
              <ShieldIcon />
            </span>
            <h2 id="app-privacy">PyBLE app</h2>
            <p>
              The PyBLE app has no account, advertising, analytics, telemetry,
              or crash reporting. It also has no payment or cloud service. The
              current production app makes no HTTP request and does not send
              your app project content to PyBLE, SciLabPro, or the maintainer.
            </p>
            <h3>Data sent to your board</h3>
            <p>
              When you choose Save, Run, a Files operation, or send console
              input, PyBLE sends the relevant source code, path or filename,
              file content, Blocks companion data, or console input directly
              over BLE to the board you selected. Board output, files, and
              device information can return to the app as part of the same
              requested workflow. This is direct communication with your
              selected hardware, not an upload to a PyBLE or SciLabPro server.
              PyBLE does not sell this content or share it with advertisers or
              data brokers.
            </p>
            <h3>BLE transport security</h3>
            <p>
              PBLE/1 does not require Bluetooth pairing or BLE link encryption,
              so a board connection may operate without an authenticated,
              encrypted link. Do not send passwords, API keys, tokens, private
              keys, or other secrets unless you have separately verified your
              physical environment and transport security.
            </p>
            <h3>Nearby boards and platform permissions</h3>
            <p>
              To discover and connect, the app processes nearby PyBLE board
              names or labels, platform device identifiers or suffixes,
              capabilities, and Bluetooth signal strength locally on your
              tablet. The app uses this information for the connection interface
              and does not send it to the developer.
            </p>
            <p>
              On Android 11 and earlier, the legacy Android location permission
              is requested only because those Android versions require it for
              BLE scanning. PyBLE does not derive, store, or transmit your
              physical location. Android 12 and later use Nearby devices
              permissions, and iPadOS uses Bluetooth permission, for the same
              find-and-connect purpose.
            </p>
            <p>
              If a board has a custom label, that board may include it in a
              nearby Bluetooth advertisement visible to other devices in range.
              Do not put a person&apos;s name, email address, or other sensitive
              information in a board label.
            </p>
            <h3>Retention and deletion</h3>
            <p>
              App working data stays on your tablet for use by the app. On
              Android, clear PyBLE&apos;s app storage or uninstall it; on
              iPadOS, delete the app. This removes data held only by the
              installed app but does not delete files on a board or exported
              copies. Device and operating-system backup behavior depends on
              your platform settings.
            </p>
            <p>
              Files saved to a board remain there until you overwrite or delete
              them or erase the board. You can delete board files through Files
              → Delete in PyBLE or manage and erase the board directly. Because
              the developer receives no app project content, there is no PyBLE
              server-side copy of your app project content to retain or delete.
            </p>
            <h3>Third-party components and platform services</h3>
            <p>
              The app contains no advertising, analytics, crash-reporting, or
              account SDK that receives your app project content. Your operating
              system and app-distribution service may independently process
              installation, system, or store information under their own privacy
              policies.
            </p>
          </section>

          <section aria-labelledby="website-privacy">
            <span className="section-icon">
              <ShieldIcon />
            </span>
            <h2 id="website-privacy">This website</h2>
            <p>
              pyble.dev has no account, advertising, analytics, tracking pixel,
              contact form, or non-essential cookie. The site does not build a
              visitor profile.
            </p>
            <p>
              Cloudflare and the VPS hosting infrastructure may process ordinary
              request data—such as your IP address, user-agent, requested URL,
              timestamp, and security signals—to deliver the pages, prevent
              abuse, and keep the service reliable.
            </p>
            <p>
              The site does not load marketing scripts, remote web fonts, or
              embedded social media. Following a link to another site makes that
              site&apos;s policy apply.
            </p>
            <p>
              Website infrastructure may keep limited operational logs according
              to provider settings and legal obligations. No separate fixed
              retention period is promised. We use HTTPS and keep the public
              site static to reduce the data and attack surface involved.
            </p>
          </section>

          <section aria-labelledby="policy-changes">
            <h2 id="policy-changes">Changes to this policy</h2>
            <p>
              If a future app or site feature handles information differently—
              such as analytics, a form, an account, a functional network
              import, or embedded media—we will update this policy and its
              effective date before that feature is deployed.
            </p>
          </section>
        </article>

        <aside className="policy-contact">
          <MailIcon />
          <h2>Privacy and deletion questions</h2>
          <p>
            Contact the project maintainer about this policy, a privacy concern,
            or deletion of website data under the maintainer&apos;s control.
          </p>
          <a href={`mailto:${siteConfig.supportEmail}`}>
            {siteConfig.supportEmail}
          </a>
        </aside>
      </div>
    </main>
  );
}
