// Runs under `bun test`: plain JSON imports work there and in the bundlers
// that consume this package, while Node's ESM loader would need import
// attributes that older bundlers reject.
import { expect, test } from "bun:test";
import { ordered } from "../version-order.cases.json";

import {
  ENTRY_AREAS,
  ENTRY_TYPES,
  LOCALES,
  compareVersions,
  releases,
  visibleEntries
} from "./index.js";

test("visibility uses explicit requirements without mutating the release or granting admin a bypass", () => {
  const release = {
    version: "2.3.0",
    entries: [
      { id: "general" },
      { id: "assistant", permissions: { allOf: ["assistants"] } },
      { id: "admin", audience: "admin" },
      { id: "modules", audience: "admin", permissions: { allOf: ["modules"] } }
    ].map((entry) => ({
      type: "new",
      area: "account",
      title: { en: entry.id, sv: entry.id },
      body: { en: entry.id, sv: entry.id },
      ...entry
    }))
  };
  const before = JSON.stringify(release);
  const adminOnly = (requirement) => requirement === "admin";
  expect(visibleEntries(release, adminOnly).map((entry) => entry.id)).toEqual(["general", "admin"]);
  expect(visibleEntries(release, () => false).map((entry) => entry.id)).toEqual(["general"]);
  expect(visibleEntries({ version: "2.3.0", entries: [] }, adminOnly)).toEqual([]);
  expect(JSON.stringify(release)).toBe(before);
});

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

test("RC builds reuse their final release's content with their own identity", async () => {
  const { releasesForVersion } = await import("./index.js");
  const source = releases.find((release) => release.version === "2.3.0");
  const before = JSON.stringify(releases);
  for (const version of ["2.3.0-rc.0", "2.3.0-rc.1", "2.3.0-rc.10"]) {
    for (const installed of [version, `v${version}`]) {
      const resolved = releasesForVersion(installed);
      const candidate = resolved.find((release) => release.version === version);
      expect(candidate.entries).toBe(source.entries);
      expect(candidate.date).toBeUndefined();
      expect(resolved).toHaveLength(releases.length);
      expect(resolved.some((release) => release.version === "2.3.0")).toBe(false);
    }
  }
  expect(JSON.stringify(releases)).toBe(before);
  const dated = releases.find((release) => release.date);
  expect(dated).toBeDefined();
  expect(
    releasesForVersion(`${dated.version}-rc.1`).find(
      (release) => release.version === `${dated.version}-rc.1`
    ).date
  ).toBeUndefined();
  expect(JSON.stringify(releases)).toBe(before);
});

test("final, local and unrelated builds keep the authored release identities", async () => {
  const { releasesForVersion } = await import("./index.js");
  for (const version of ["2.3.0", "v2.3.0", "0.0.0-dev", "1.23.1", "unknown"]) {
    expect(releasesForVersion(version)).toBe(releases);
  }
  expect(releasesForVersion("9.0.0-rc.1")).toEqual(releases);
});
