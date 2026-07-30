// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import Image from "next/image";
import Link from "next/link";

export function Brand({ footer = false }: { footer?: boolean }) {
  return (
    <Link
      className={footer ? "brand brand--footer" : "brand"}
      href="/"
      aria-label="PyBLE home"
    >
      <Image
        className="brand__mark"
        src="/brand/pyble-prompt-chip.svg"
        alt=""
        width={40}
        height={40}
        priority={!footer}
      />
      <span className="brand__wordmark">PyBLE</span>
    </Link>
  );
}
