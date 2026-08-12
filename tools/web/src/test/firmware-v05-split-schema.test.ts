// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  createCurrentFirmwareReleaseFixture,
  createFirmwareReleaseFixture,
} from "@/test/fixtures/firmware-release";

describe("split v0.5 release schema", () => {
  it("uses schema 3 and the exact ordered three-profile table", async () => {
    const schema = JSON.parse(
      await readFile(
        join(process.cwd(), "src", "lib", "firmware-release-schema.json"),
        "utf8",
      ),
    ) as {
      properties: {
        schema_version: { const: number };
        profiles: {
          minItems: number;
          maxItems: number;
          items: { properties: { id: { enum: string[] } } };
        };
      };
    };

    expect(schema.properties.schema_version.const).toBe(3);
    expect(schema.properties.profiles).toMatchObject({
      minItems: 3,
      maxItems: 3,
    });
    expect(schema.properties.profiles.items.properties.id.enum).toEqual([
      "esp32-4mb",
      "esp32-s3-n16r8",
      "waveshare-esp32-s3-lcd-147b",
    ]);
    expect(
      createCurrentFirmwareReleaseFixture().release.profiles.map(
        ({ id }) => id,
      ),
    ).toEqual(schema.properties.profiles.items.properties.id.enum);
  });

  it("preserves immutable v0.4.2 as schema 2 with exactly two profiles", () => {
    const historical = createFirmwareReleaseFixture();
    expect(historical.release.schema_version).toBe(2);
    expect(historical.release.identity.version).toBe("0.4.2");
    expect(historical.release.profiles.map(({ id }) => id)).toEqual([
      "esp32-4mb",
      "esp32-s3-n16r8",
    ]);
  });
});
