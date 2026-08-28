// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { TutorialAppCapture } from "@/components/tutorial-app-capture";
import { TutorialCallout } from "@/components/tutorial-callout";
import { TutorialPage, type TutorialStep } from "@/components/tutorial-page";
import {
  compatibilityLabels,
  examplesSnapshot,
  firmwareProfiles,
} from "@/lib/tutorials";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "PyBLE examples catalog tutorial",
  description:
    "Browse all 32 PyBLE development examples by planned release, designed firmware profiles, immutable source, and accurately empty validation state.",
  path: "/learn/examples",
});

const plannedReleases = ["0.1.0", "0.2.0", "0.3.0"] as const;

const categoryNames = {
  basics: "Basics",
  workflow: "Workflow",
  data: "Data",
  gpio: "GPIO",
  buses: "Buses",
  neopixel: "NeoPixel",
  display: "Display",
  projects: "Projects",
} as const;

const profileNames = Object.fromEntries(
  firmwareProfiles.map((profile) => [profile.id, profile.shortLabel]),
);

const steps: readonly TutorialStep[] = [
  {
    title: "Start with evidence, not the title",
    body: (
      <p>
        Read the snapshot banner, planned release, classification, designed
        profiles, and validation line before choosing an entry. A familiar board
        name or an official repository does not promote planned source.
      </p>
    ),
    expected:
      "every card says that physical validation is not recorded and no card claims a validated profile.",
  },
  {
    title: "Choose the smallest relevant slice",
    body: (
      <p>
        Begin with a portable Basics or Workflow entry. Use the 0.1.0, 0.2.0,
        and 0.3.0 headings as planned content slices, not as published examples
        releases. Capability and project entries add explicit hardware review.
      </p>
    ),
    expected:
      "you can identify one bounded example whose summary matches the concept you want to practice.",
  },
  {
    title: "Check designed scope profile by profile",
    body: (
      <p>
        Portable entries list all five profiles. Generic capabilities still
        require explicit pins. ESP NeoPixel entries list the four ESP profiles,
        never Pico 2 W. Exact-board entries list only Pico 2 W or the Waveshare
        B-version profile.
      </p>
    ),
    stopIf:
      "your exact profile is absent from Designed profiles or the required hardware and wiring have not been reviewed.",
  },
  {
    title: "Open the immutable source",
    body: (
      <p>
        Use the Source at reviewed commit link on the chosen card. Confirm the
        browser URL contains the full snapshot commit, then read the README and
        complete Python source in the examples repository.
      </p>
    ),
    expected:
      "the source URL contains the exact 40-character commit rather than a moving main branch.",
  },
  {
    title: "Import into a disposable child folder",
    body: (
      <p>
        Return to the GitHub import workflow, create the exact destination
        first, pin this snapshot commit, browse one folder, and review every
        selected source and target. Import does not make the example validated.
      </p>
    ),
    visual: <TutorialAppCapture capture="examplesImportComplete" />,
    expected:
      "the terminal import result and refreshed Files list agree without any automatic open or Run.",
  },
  {
    title: "Run only within the documented boundary",
    body: (
      <p>
        Open and read the imported source. For hardware examples, repeat the
        electrical checklist and define every documented configuration value.
        Choose Run explicitly, observe only the bounded effect, then Stop and
        perform the example&apos;s cleanup.
      </p>
    ),
    expected:
      "the observed result stays within the reviewed summary; your personal test is not represented as project HIL evidence.",
  },
];

export default function ExamplesTutorial() {
  return (
    <TutorialPage
      slug="examples"
      steps={steps}
      compatibility={{
        "esp32-4mb": "developmentUnvalidated",
        "esp32-s3-n16r8": "developmentUnvalidated",
        "waveshare-esp32-s3-lcd-147b": "developmentUnvalidated",
        "esp32-c3-4mb": "developmentUnvalidated",
        "rpi-pico2-w": "developmentUnvalidated",
      }}
      compatibilityNote={
        <p>
          Designed profiles record author intent. Validated profiles are empty
          for every entry in this snapshot, so no example below is presented as
          physically validated or supported.
        </p>
      }
    >
      <section aria-labelledby="examples-before">
        <h2 id="examples-before">Before you begin</h2>
        <TutorialCallout
          title="Development snapshot, not a release"
          tone="warning"
        >
          <p>
            These 32 entries are development-only, unreleased, and not
            HIL-validated. Their catalog status is planned. The source is
            reviewed at immutable commit <code>{examplesSnapshot.commit}</code>;
            there is no examples release tag or physical validation record for
            this snapshot.
          </p>
        </TutorialCallout>
        <p>
          Full runnable <code>.py</code> source, catalog metadata, future
          release tags, and HIL records belong to{" "}
          <a
            href={examplesSnapshot.repositoryUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            the separate PyBLE examples repository
          </a>
          . This site shows metadata and immutable links rather than duplicating
          complete programs.
        </p>
      </section>

      <section aria-labelledby="examples-snapshot">
        <h2 id="examples-snapshot">Reviewed snapshot</h2>
        <dl className="tutorial-snapshot">
          <div>
            <dt>Repository state</dt>
            <dd>Development · unreleased</dd>
          </div>
          <div>
            <dt>Examples</dt>
            <dd>{examplesSnapshot.examples.length}</dd>
          </div>
          <div>
            <dt>Firmware baseline</dt>
            <dd>{examplesSnapshot.firmwareBaseline}</dd>
          </div>
          <div>
            <dt>Protocol</dt>
            <dd>{examplesSnapshot.protocol}</dd>
          </div>
          <div>
            <dt>Commit</dt>
            <dd>
              <code>{examplesSnapshot.commit}</code>
            </dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="examples-all">
        <div className="section-heading">
          <p className="eyebrow">Complete static index</p>
          <h2 id="examples-all">All 32 authored examples</h2>
        </div>
        <div className="example-slices">
          {plannedReleases.map((plannedRelease) => {
            const examples = examplesSnapshot.examples.filter(
              (example) => example.plannedRelease === plannedRelease,
            );

            return (
              <section
                className="example-slice"
                aria-labelledby={"examples-planned-" + plannedRelease}
                key={plannedRelease}
              >
                <div className="example-slice__heading">
                  <h3 id={"examples-planned-" + plannedRelease}>
                    Planned {plannedRelease}
                  </h3>
                  <p>{examples.length} entries · planning label only</p>
                </div>
                <div className="example-grid">
                  {examples.map((example) => (
                    <article className="example-card" key={example.id}>
                      <p className="example-card__meta">
                        {categoryNames[example.category]} ·{" "}
                        {example.classification} · planned{" "}
                        {example.plannedRelease}
                      </p>
                      <h4>{example.title}</h4>
                      <p>{example.summary}</p>
                      <dl>
                        <div>
                          <dt>Designed profiles</dt>
                          <dd>
                            {example.designedProfiles
                              .map(
                                (profile) => profileNames[profile] ?? profile,
                              )
                              .join(" · ")}
                          </dd>
                        </div>
                        <div>
                          <dt>Validated profiles</dt>
                          <dd>None recorded</dd>
                        </div>
                        <div>
                          <dt>Status</dt>
                          <dd>{compatibilityLabels.developmentUnvalidated}</dd>
                        </div>
                      </dl>
                      <a
                        href={example.sourceUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        Source at reviewed commit
                      </a>
                    </article>
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      </section>
    </TutorialPage>
  );
}
