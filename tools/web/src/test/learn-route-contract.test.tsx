// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LearnBlocksPage, {
  metadata as learnBlocksMetadata,
} from "@/app/learn/blocks/page";
import LearnConfiguredHardwarePage, {
  metadata as learnConfiguredHardwareMetadata,
} from "@/app/learn/configured-hardware/page";
import LearnExamplesPage, {
  metadata as learnExamplesMetadata,
} from "@/app/learn/examples/page";
import LearnFilesPage, {
  metadata as learnFilesMetadata,
} from "@/app/learn/files/page";
import LearnFirstProgramPage, {
  metadata as learnFirstProgramMetadata,
} from "@/app/learn/first-program/page";
import LearnGithubImportPage, {
  metadata as learnGithubImportMetadata,
} from "@/app/learn/github-import/page";
import LearnHardwarePage, {
  metadata as learnHardwareMetadata,
} from "@/app/learn/hardware/page";
import LearnPage, { metadata as learnMetadata } from "@/app/learn/page";
import LearnPico2WPage, {
  metadata as learnPico2WMetadata,
} from "@/app/learn/pico-2-w/page";
import LearnSetupPage, {
  metadata as learnSetupMetadata,
} from "@/app/learn/setup/page";
import LearnWaveshareLcd147bPage, {
  metadata as learnWaveshareLcd147bMetadata,
} from "@/app/learn/waveshare-lcd-147b/page";

const tutorialPaths = [
  "/learn/setup",
  "/learn/first-program",
  "/learn/files",
  "/learn/github-import",
  "/learn/blocks",
  "/learn/examples",
  "/learn/hardware",
  "/learn/configured-hardware",
  "/learn/pico-2-w",
  "/learn/waveshare-lcd-147b",
] as const;

const learnRoutes = [
  { path: "/learn", Page: LearnPage, metadata: learnMetadata },
  {
    path: "/learn/setup",
    Page: LearnSetupPage,
    metadata: learnSetupMetadata,
  },
  {
    path: "/learn/first-program",
    Page: LearnFirstProgramPage,
    metadata: learnFirstProgramMetadata,
  },
  {
    path: "/learn/files",
    Page: LearnFilesPage,
    metadata: learnFilesMetadata,
  },
  {
    path: "/learn/github-import",
    Page: LearnGithubImportPage,
    metadata: learnGithubImportMetadata,
  },
  {
    path: "/learn/blocks",
    Page: LearnBlocksPage,
    metadata: learnBlocksMetadata,
  },
  {
    path: "/learn/examples",
    Page: LearnExamplesPage,
    metadata: learnExamplesMetadata,
  },
  {
    path: "/learn/hardware",
    Page: LearnHardwarePage,
    metadata: learnHardwareMetadata,
  },
  {
    path: "/learn/configured-hardware",
    Page: LearnConfiguredHardwarePage,
    metadata: learnConfiguredHardwareMetadata,
  },
  {
    path: "/learn/pico-2-w",
    Page: LearnPico2WPage,
    metadata: learnPico2WMetadata,
  },
  {
    path: "/learn/waveshare-lcd-147b",
    Page: LearnWaveshareLcd147bPage,
    metadata: learnWaveshareLcd147bMetadata,
  },
] as const;

describe("static Learn route contract", () => {
  it("publishes one exact canonical and distinct metadata for every Learn route", () => {
    const titles = learnRoutes.map(({ metadata }) => metadata.title);
    const descriptions = learnRoutes.map(
      ({ metadata }) => metadata.description,
    );

    expect(
      titles.every((title) => typeof title === "string" && title.length > 0),
    ).toBe(true);
    expect(
      descriptions.every(
        (description) =>
          typeof description === "string" && description.length > 0,
      ),
    ).toBe(true);
    expect(new Set(titles).size).toBe(learnRoutes.length);
    expect(new Set(descriptions).size).toBe(learnRoutes.length);

    for (const { metadata, path } of learnRoutes) {
      expect(metadata.alternates).toEqual({
        canonical: `https://pyble.dev${path}`,
      });
      expect(metadata.openGraph).toMatchObject({
        url: `https://pyble.dev${path}`,
      });
    }
  });

  it.each(learnRoutes)("renders $path as an authored document", ({ Page }) => {
    render(<Page />);

    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/\S/);
  });

  it("links the hub to exactly the ten published tutorials", () => {
    const { container } = render(<LearnPage />);
    const linkedTutorials = Array.from(
      container.querySelectorAll<HTMLAnchorElement>('a[href^="/learn/"]'),
      (link) => link.getAttribute("href"),
    );

    expect(new Set(linkedTutorials)).toEqual(new Set(tutorialPaths));
  });
});
