// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { MailIcon, ShieldIcon } from "@/components/icons";
import { PageIntro } from "@/components/page-intro";
import { pageMetadata, siteConfig } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Privacy",
  description:
    "How the PyBLE app and pyble.dev handle code, device information, and ordinary website request data.",
  path: "/privacy",
});

export default function PrivacyPage() {
  return (
    <main id="main-content">
      <PageIntro eyebrow="Plain-language privacy" title="Privacy">
        <p>
          PyBLE is designed to work locally. This policy separates what happens
          in the tablet app from what happens when you visit this website.
        </p>
        <p className="page-intro__meta">
          Effective <time dateTime="2026-07-29">29 July 2026</time>
        </p>
      </PageIntro>

      <div className="container policy-layout">
        <article className="prose policy">
          <section aria-labelledby="app-privacy">
            <span className="section-icon">
              <ShieldIcon />
            </span>
            <h2 id="app-privacy">PyBLE app</h2>
            <p>
              The PyBLE app has no account, advertising, analytics, or
              telemetry. It does not require a cloud workflow to edit and run
              your code.
            </p>
            <h3>Code and files</h3>
            <p>
              Your source code, files, and settings stay on your tablet or the
              connected board you choose. PyBLE transfers board files directly
              over Bluetooth Low Energy; it does not upload them to a PyBLE
              server.
            </p>
            <h3>Nearby boards</h3>
            <p>
              To discover and connect, the app processes nearby PyBLE board
              names, device identifiers or suffixes, capabilities, and Bluetooth
              signal strength locally on your tablet. That information is used
              to show the connection interface and is not sent to us.
            </p>
            <h3>Board labels</h3>
            <p>
              A label you assign to a board may be included in that board&apos;s
              nearby Bluetooth advertisement. Other devices in range may see it,
              so do not use a person&apos;s name, email address, or other
              sensitive information as a board label.
            </p>
            <h3>Platform permissions</h3>
            <p>
              iPadOS and Android control Bluetooth permission prompts. PyBLE
              uses the permissions you grant only to find, connect to, and
              communicate with compatible boards.
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
              Like ordinary hosted websites, our hosting and security providers
              may process ordinary request data—such as your IP address,
              user-agent, requested URL, timestamp, and security signals—to
              deliver the pages, prevent abuse, and keep the service reliable.
            </p>
            <p>
              The launch site does not load marketing scripts, remote web fonts,
              or embedded social media. Following a link to another site makes
              that site&apos;s policy apply.
            </p>
          </section>

          <section aria-labelledby="retention-security">
            <h2 id="retention-security">Retention and security</h2>
            <p>
              PyBLE does not receive app project data to retain. Website
              infrastructure may keep limited operational logs according to the
              hosting or security provider&apos;s settings and legal
              obligations. We use HTTPS and keep the public site static to
              reduce the data and attack surface involved.
            </p>
          </section>

          <section aria-labelledby="policy-changes">
            <h2 id="policy-changes">Changes to this policy</h2>
            <p>
              If a future site feature collects new information—such as
              analytics, a form, an account, or embedded media—we will update
              this policy and its effective date before that feature is
              deployed.
            </p>
          </section>
        </article>

        <aside className="policy-contact">
          <MailIcon />
          <h2>Privacy questions</h2>
          <p>
            Ask the project maintainer if you have a question about this policy
            or a privacy concern.
          </p>
          <a href={`mailto:${siteConfig.supportEmail}`}>
            {siteConfig.supportEmail}
          </a>
        </aside>
      </div>
    </main>
  );
}
