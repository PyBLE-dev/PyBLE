// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import Link from "next/link";

import { Brand } from "@/components/brand";
import { MenuIcon } from "@/components/icons";
import { navigation } from "@/lib/site";

export function SiteHeader() {
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="site-header">
        <div className="container site-header__inner">
          <Brand />

          <nav className="desktop-nav" aria-label="Primary">
            <ul>
              {navigation.map((item) => (
                <li key={item.href}>
                  <a href={item.href}>{item.label}</a>
                </li>
              ))}
            </ul>
          </nav>

          <Link className="header-cta" href="/support">
            Beta support
          </Link>

          <details className="mobile-menu">
            <summary aria-label="Open navigation menu">
              <MenuIcon />
              <span>Menu</span>
            </summary>
            <nav aria-label="Mobile">
              {navigation.map((item) => (
                <a href={item.href} key={item.href}>
                  {item.label}
                </a>
              ))}
              <Link className="mobile-menu__support" href="/privacy">
                Privacy
              </Link>
            </nav>
          </details>
        </div>
      </header>
    </>
  );
}
