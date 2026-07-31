// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import Link from "next/link";

import { Brand } from "@/components/brand";
import { siteConfig } from "@/lib/site";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="container site-footer__grid">
        <div>
          <Brand footer />
          <p className="site-footer__tagline">{siteConfig.expandedName}</p>
        </div>

        <nav className="site-footer__links" aria-label="Footer">
          <a
            href={siteConfig.repositoryUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            GitHub
          </a>
          <Link href="/flash">Firmware</Link>
          <Link href="/support">Support</Link>
          <Link href="/privacy">Privacy</Link>
        </nav>

        <p className="site-footer__legal">
          © 2026 PyBLE contributors.
          <br />
          MIT licensed · A SciLabPro open-source project.
        </p>
      </div>
    </footer>
  );
}
