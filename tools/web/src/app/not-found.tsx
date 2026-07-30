// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import Link from "next/link";

import { ArrowIcon } from "@/components/icons";

export default function NotFound() {
  return (
    <main className="not-found" id="main-content">
      <div className="container not-found__inner">
        <p className="eyebrow">404 · Nothing at this address</p>
        <h1>This route is not connected.</h1>
        <p>
          The page may have moved, or the link may be from an earlier PyBLE
          build.
        </p>
        <Link className="button button--primary" href="/">
          Return home
          <ArrowIcon />
        </Link>
      </div>
    </main>
  );
}
