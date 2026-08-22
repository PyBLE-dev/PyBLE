// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { describe, expect, it } from "vitest";

import {
  createCurrentFirmwareReleaseFixture,
  createFirmwareReleaseFixture,
} from "@/test/fixtures/firmware-release";

describe("split v0.5 release schema", () => {
  it("preserves schema 3 and the exact ordered three-profile table", () => {
    const fixture = createCurrentFirmwareReleaseFixture();
    const schemaBytes = fixture.files.get("release.schema.json");
    if (!schemaBytes) {
      throw new Error("Current fixture is missing release.schema.json");
    }
    const schema = JSON.parse(new TextDecoder().decode(schemaBytes)) as {
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
    expect(fixture.release.profiles.map(({ id }) => id)).toEqual(
      schema.properties.profiles.items.properties.id.enum,
    );
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
