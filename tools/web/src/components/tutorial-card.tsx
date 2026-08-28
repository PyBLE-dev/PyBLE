// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import Link from "next/link";

import { ArrowIcon } from "@/components/icons";
import { tutorials } from "@/lib/tutorials";

type Tutorial = (typeof tutorials)[number];

export function TutorialCard({ tutorial }: { tutorial: Tutorial }) {
  return (
    <article className="learn-card">
      <div className="learn-card__number" aria-hidden="true">
        {String(tutorial.position).padStart(2, "0")}
      </div>
      <div className="learn-card__body">
        <p className="learn-card__meta">
          {tutorial.difficulty} · {tutorial.minutes} min
        </p>
        <h2>{tutorial.title}</h2>
        <p>{tutorial.summary}</p>
        <Link className="learn-card__link" href={tutorial.href}>
          Open tutorial {tutorial.position}
          <ArrowIcon />
        </Link>
      </div>
    </article>
  );
}
