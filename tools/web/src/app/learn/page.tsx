// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import Link from "next/link";

import { PageIntro } from "@/components/page-intro";
import { TutorialCallout } from "@/components/tutorial-callout";
import { TutorialCard } from "@/components/tutorial-card";
import {
  compatibilityLabels,
  examplesSnapshot,
  firmwareProfiles,
  tutorials,
} from "@/lib/tutorials";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Learn PyBLE",
  description:
    "Follow ten static, release-reviewed PyBLE tutorials from exact firmware setup and a first MicroPython program through Files, Blocks, examples, and bounded hardware work.",
  path: "/learn",
});

export default function LearnPage() {
  return (
    <main id="main-content">
      <PageIntro eyebrow="Ten tutorials · one careful path" title="Learn PyBLE">
        <p>
          Start with the exact firmware for your board, prove the BLE coding
          loop without hardware, then add files, reviewed source, Blocks, and
          physical components one boundary at a time.
        </p>
      </PageIntro>

      <div className="container learn-hub">
        <section className="learn-hub__intro" aria-labelledby="learning-path">
          <div className="section-heading">
            <p className="eyebrow">Beginner progression</p>
            <h2 id="learning-path">Follow the path in order.</h2>
            <p>
              Lessons are complete static pages: no sign-in, analytics, remote
              media, or client-side tutorial fetch is required. Allow about two
              hours for the full path, plus time for careful wiring reviews.
            </p>
          </div>

          <TutorialCallout
            title="Check the release before you begin"
            tone="note"
          >
            <p>
              Tutorial review baseline: PyBLE app 0.2.0 beta, PBLE/1, and
              firmware 0.6.0. That baseline is not a live installer promise.
              Always check the active version, exact profile, and enabled action
              on the <Link href="/flash">current firmware page</Link>.
            </p>
          </TutorialCallout>
        </section>

        <section className="learn-path" aria-label="PyBLE tutorial path">
          <div className="learn-grid">
            {tutorials.map((tutorial) => (
              <TutorialCard key={tutorial.slug} tutorial={tutorial} />
            ))}
          </div>
        </section>

        <section className="learn-legend" aria-labelledby="learning-legend">
          <div className="section-heading">
            <p className="eyebrow">Read claims precisely</p>
            <h2 id="learning-legend">
              Compatibility and evidence are separate.
            </h2>
          </div>
          <dl className="learn-legend__items">
            <div>
              <dt>{compatibilityLabels.qualifiedFirmware}</dt>
              <dd>
                A firmware-release state backed by the project&apos;s release
                and hardware gates. Confirm it on the current installer.
              </dd>
            </div>
            <div>
              <dt>{compatibilityLabels.designed}</dt>
              <dd>
                The lesson or example was authored for that profile. This is not
                evidence that a physical run passed.
              </dd>
            </div>
            <div>
              <dt>{compatibilityLabels.exactBoardOnly}</dt>
              <dd>
                A documented carrier-board surface is required; a matching chip
                family is not enough.
              </dd>
            </div>
            <div>
              <dt>{compatibilityLabels.developmentUnvalidated}</dt>
              <dd>
                Source exists in the reviewed development snapshot, but no HIL
                record or examples release promotes it.
              </dd>
            </div>
            <div>
              <dt>{compatibilityLabels.notApplicable}</dt>
              <dd>The lesson intentionally does not target that profile.</dd>
            </div>
          </dl>
        </section>

        <section
          className="learn-baselines"
          aria-labelledby="learning-baselines"
        >
          <div className="section-heading">
            <p className="eyebrow">Immutable review points</p>
            <h2 id="learning-baselines">
              Know what these pages were checked against.
            </h2>
          </div>
          <div className="learn-baselines__grid">
            <article>
              <h3>Five firmware profiles</h3>
              <p>
                The lessons preserve this order and never infer a carrier pin
                map from a generic chip profile.
              </p>
              <code>{firmwareProfiles.map(({ id }) => id).join(" · ")}</code>
            </article>
            <article>
              <h3>Examples development snapshot</h3>
              <p>
                All {examplesSnapshot.examples.length} entries are reviewed at
                one exact commit. They remain development-only, unreleased, and
                not HIL-validated.
              </p>
              <a
                href={`${examplesSnapshot.repositoryUrl}/tree/${examplesSnapshot.commit}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open examples snapshot {examplesSnapshot.commit.slice(0, 12)}…
              </a>
            </article>
          </div>
        </section>

        <section className="learn-help" aria-labelledby="learning-help">
          <h2 id="learning-help">A step does not match your screen?</h2>
          <p>
            Stop before writing or wiring anything else. Record the exact board
            profile and versions, then use the{" "}
            <Link href="/support">support and recovery checklist</Link>.
          </p>
        </section>
      </div>
    </main>
  );
}
