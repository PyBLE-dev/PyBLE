// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import HomePage from "@/app/page";
import SupportPage from "@/app/support/page";
import LearnPage from "@/app/learn/page";
import FilesPage from "@/app/learn/files/page";
import FirstProgramPage from "@/app/learn/first-program/page";
import { firmwareProfileDescriptors, type FirmwareReleaseDescriptor } from "@/lib/firmware-release";
import * as selection from "@/lib/firmware-release-selection";
import { firmwareTargetsForRelease } from "@/lib/site";

const release: FirmwareReleaseDescriptor = {
  deployment: "owner-confirmed", accessControlled: false, version: "0.6.1",
  builtAt: "2026-09-11T03:59:01Z", hilStatus: "pending",
  releaseJson: { path: "/firmware/v0.6.1/release.json", sha256: "71f6aca6df07e31a1f54c7f70a48d82c7fe26b1c8ca0626a8ffc57c804fbb1bd" },
  schemaPath: "/firmware/v0.6.1/release.schema.json",
  recoveryPath: "/firmware/v0.6.1/RECOVERY.md",
  profiles: firmwareProfileDescriptors("0.6.1"),
};
afterEach(() => vi.restoreAllMocks());
describe("current v0.6.1 website consistency", () => {
  it.each([HomePage, SupportPage])("presents the owner-confirmed release as available", (Page) => {
    vi.spyOn(selection, "firmwareReleaseSelectedAtBuild").mockReturnValue(release);
    const {container} = render(<Page />);
    expect(container).toHaveTextContent(/v0.6.1 firmware is available/i);
    expect(container).not.toHaveTextContent(/Protected candidate v0.6.1|installer is currently unavailable/i);
  });
  it("gives all five target cards the same release status", () => {
    const targets=firmwareTargetsForRelease(release);
    expect(targets).toHaveLength(5);
    for(const target of targets) {
      expect(target.status).toBe("v0.6.1 public release · owner-confirmed");
      expect(target.planned).toBe(false);
    }
  });
  it("separates current tutorial guidance from historic captures", () => {
    render(<FilesPage />);
    expect(screen.getByRole("region", {name:"Tutorial overview"})).toHaveTextContent(/firmware 0.6.1/i);
    expect(screen.getByText(/historical screenshots/i)).toBeVisible();
    expect(screen.getByText(/all five official profiles use LFS2/i)).toBeVisible();
  });
  it("updates the Learn hub and explains fresh globals", () => {
    const hub=render(<LearnPage />);
    expect(hub.container).toHaveTextContent(/firmware 0.6.1/i);
    hub.unmount();
    const first=render(<FirstProgramPage />);
    expect(first.container).toHaveTextContent(/fresh globals/i);
  });
});
