// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import type { ReactNode } from "react";

export function TutorialCallout({
  title,
  tone = "note",
  children,
}: {
  title: string;
  tone?: "note" | "safety" | "privacy" | "warning";
  children: ReactNode;
}) {
  return (
    <aside
      className={`tutorial-callout tutorial-callout--${tone}`}
      aria-label={title}
    >
      <h3>{title}</h3>
      <div>{children}</div>
    </aside>
  );
}
