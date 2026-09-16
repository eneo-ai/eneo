// Runs under `bun test`: plain JSON imports work there and in the bundlers
// that consume this package, while Node's ESM loader would need import
// attributes that older bundlers reject.
import { expect, test } from "bun:test";
import { ordered } from "../version-order.cases.json";

import { ENTRY_AREAS, ENTRY_TYPES, LOCALES, compareVersions, releases } from "./index.js";

test("vocabularies come from the schema", () => {
  expect([...ENTRY_TYPES]).toEqual(["new", "improved", "fixed"]);
  expect(ENTRY_AREAS).toContain("chat");
  expect([...LOCALES]).toEqual(["en", "sv"]);
});

test("compareVersions orders releases like semver", () => {
  for (let i = 1; i < ordered.length; i++) {
    expect(compareVersions(ordered[i - 1], ordered[i])).toBeLessThan(0);
    expect(compareVersions(ordered[i], ordered[i - 1])).toBeGreaterThan(0);
  }
  for (const version of ordered) expect(compareVersions(version, version)).toBe(0);
});

test("releases.json is newest first", () => {
  for (let i = 1; i < releases.length; i++) {
    expect(compareVersions(releases[i - 1].version, releases[i].version)).toBeGreaterThan(0);
  }
});
