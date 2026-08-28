// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import type { ReactNode } from "react";
import Link from "next/link";

import { PageIntro } from "@/components/page-intro";
import {
  compatibilityLabels,
  firmwareProfiles,
  tutorials,
} from "@/lib/tutorials";

type TutorialSlug = (typeof tutorials)[number]["slug"];
type CompatibilityKind =
  "designed" | "exactBoardOnly" | "developmentUnvalidated" | "notApplicable";

export type TutorialStep = {
  title: string;
  body: ReactNode;
  code?: string;
  expected?: ReactNode;
  stopIf?: ReactNode;
};

const profileNames: Record<string, string> = {
  "esp32-4mb": "Classic ESP32 (4 MiB)",
  "esp32-s3-n16r8": "ESP32-S3 N16R8 · lean generic",
  "waveshare-esp32-s3-lcd-147b": "Waveshare ESP32-S3-LCD-1.47B",
  "esp32-c3-4mb": "ESP32-C3 (4 MiB)",
  "rpi-pico2-w": "Raspberry Pi Pico 2 W",
};

function compatibilityText(kind: CompatibilityKind): string {
  return compatibilityLabels[kind];
}

export function TutorialPage({
  slug,
  steps,
  compatibility = {},
  compatibilityNote,
  children,
}: {
  slug: TutorialSlug;
  steps: readonly TutorialStep[];
  compatibility?: Partial<Record<string, CompatibilityKind>>;
  compatibilityNote: ReactNode;
  children: ReactNode;
}) {
  const tutorialIndex = tutorials.findIndex((entry) => entry.slug === slug);
  const tutorial = tutorials[tutorialIndex];

  if (!tutorial) {
    throw new Error(`Unknown tutorial slug: ${slug}`);
  }

  const previous = tutorials[tutorialIndex - 1];
  const next = tutorials[tutorialIndex + 1];

  return (
    <main id="main-content">
      <PageIntro
        eyebrow={`Tutorial ${tutorial.position} of ${tutorials.length}`}
        title={tutorial.title}
      >
        <p>{tutorial.summary}</p>
      </PageIntro>

      <div className="container tutorial-layout">
        <nav className="tutorial-breadcrumbs" aria-label="Breadcrumb">
          <Link href="/learn">Learn</Link>
          <span aria-hidden="true">/</span>
          <span aria-current="page">{tutorial.title}</span>
        </nav>

        <article className="tutorial-content">
          <section className="tutorial-overview" aria-label="Tutorial overview">
            <dl className="tutorial-facts">
              <div>
                <dt>Difficulty</dt>
                <dd>{tutorial.difficulty}</dd>
              </div>
              <div>
                <dt>Time</dt>
                <dd>{tutorial.minutes} min</dd>
              </div>
              <div>
                <dt>Review baseline</dt>
                <dd>App 0.2.0 beta · firmware 0.6.0 · PBLE/1</dd>
              </div>
            </dl>

            <div className="tutorial-goals">
              <section aria-labelledby={`${slug}-prerequisites`}>
                <h2 id={`${slug}-prerequisites`}>Prerequisites</h2>
                <ul>
                  {tutorial.prerequisites.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </section>
              <section aria-labelledby={`${slug}-outcomes`}>
                <h2 id={`${slug}-outcomes`}>Outcomes</h2>
                <ul>
                  {tutorial.outcomes.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </section>
            </div>
          </section>

          <nav className="tutorial-toc" aria-label="On this page">
            <strong>On this page</strong>
            <a href="#compatibility">Compatibility</a>
            <a href="#lesson">Before you begin</a>
            <a href="#steps">Steps</a>
            <a href="#next-lesson">Continue learning</a>
          </nav>

          <section id="compatibility" aria-labelledby="compatibility-title">
            <div className="section-heading">
              <p className="eyebrow">Release-aware guidance</p>
              <h2 id="compatibility-title">Compatibility</h2>
            </div>
            <p>
              The review baseline above is not a promise about the installer
              currently being served. Confirm the active version, exact profile,
              and enabled action on the{" "}
              <Link href="/flash">current firmware and flash page</Link> before
              provisioning or changing hardware.
            </p>
            <p>
              <strong>{compatibilityLabels.qualifiedFirmware}</strong> describes
              firmware evidence. The table below describes this lesson&apos;s
              scope; it does not turn designed compatibility into hardware
              validation.
            </p>
            <div className="tutorial-table-wrap">
              <table className="tutorial-table">
                <caption>Lesson scope for the five firmware profiles</caption>
                <thead>
                  <tr>
                    <th scope="col">Firmware profile</th>
                    <th scope="col">Lesson scope</th>
                  </tr>
                </thead>
                <tbody>
                  {firmwareProfiles.map((profile) => (
                    <tr key={profile.id}>
                      <th scope="row">
                        <span>{profileNames[profile.id] ?? profile.id}</span>
                        <code>{profile.id}</code>
                      </th>
                      <td>
                        {compatibilityText(
                          compatibility[profile.id] ?? "designed",
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="tutorial-compatibility-note">
              {compatibilityNote}
            </div>
          </section>

          <div id="lesson" className="tutorial-lesson">
            {children}
          </div>

          <section id="steps" aria-labelledby="steps-title">
            <div className="section-heading">
              <p className="eyebrow">Follow in order</p>
              <h2 id="steps-title">Tutorial steps</h2>
            </div>
            <ol className="tutorial-steps" aria-label="Tutorial steps">
              {steps.map((step, index) => (
                <li key={`${index}-${step.title}`}>
                  <div className="tutorial-step__number" aria-hidden="true">
                    {String(index + 1).padStart(2, "0")}
                  </div>
                  <div className="tutorial-step__body">
                    <h3>{step.title}</h3>
                    <div>{step.body}</div>
                    {step.code ? (
                      <pre>
                        <code>{step.code}</code>
                      </pre>
                    ) : null}
                    {step.expected ? (
                      <p className="tutorial-step__result">
                        <strong>Expected:</strong> {step.expected}
                      </p>
                    ) : (
                      <p className="tutorial-step__result tutorial-step__result--stop">
                        <strong>Stop if:</strong> {step.stopIf}
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </section>

          <section
            className="tutorial-recovery"
            aria-labelledby="recovery-title"
          >
            <h2 id="recovery-title">Need recovery help?</h2>
            <p>
              Stop at the current step, record the exact profile, board
              identity, app and firmware versions, and the first useful error.
              Then use the{" "}
              <Link href="/support">PyBLE support and recovery guide</Link>.
            </p>
          </section>

          <nav
            id="next-lesson"
            className="tutorial-navigation"
            aria-label="Tutorial navigation"
          >
            {previous ? (
              <Link
                className="tutorial-navigation__previous"
                href={previous.href}
              >
                <span>Previous</span>
                <strong>{previous.title}</strong>
              </Link>
            ) : (
              <span aria-hidden="true" />
            )}
            <Link className="tutorial-navigation__all" href="/learn">
              All tutorials
            </Link>
            {next ? (
              <Link className="tutorial-navigation__next" href={next.href}>
                <span>Next</span>
                <strong>{next.title}</strong>
              </Link>
            ) : (
              <span aria-hidden="true" />
            )}
          </nav>
        </article>
      </div>
    </main>
  );
}
