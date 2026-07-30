// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { describe, expect, it } from "vitest";

import nextConfig from "../../next.config";

describe("Next.js route policy", () => {
  it("uses slashless document routes so vinext can prerender each route", () => {
    expect(nextConfig.trailingSlash).toBe(false);
  });
});
