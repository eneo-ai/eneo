import { latestRelease } from "@eneo/whats-new";
import { describe, expect, it } from "vitest";
import { docsUrl, docsVersionPath } from "./docs";

describe("docs links", () => {
  it("point at the release line once the release is dated, else at the development docs", () => {
    expect(docsVersionPath({ version: "2.3.0", date: "2026-10-01" })).toBe("/v2.3");
    expect(docsVersionPath({ version: "2.3.1", date: "2026-10-20" })).toBe("/v2.3");
    expect(docsVersionPath({ version: "2.3.0" })).toBe("/dev");
    expect(docsVersionPath(undefined)).toBe("/dev");
  });

  it("put the language after the version, as the versioned site is laid out", () => {
    const version = docsVersionPath(latestRelease());
    expect(docsUrl("guides/embed-widget", "sv", "for-the-website-team")).toBe(
      `https://docs.eneo.ai${version}/sv/guides/embed-widget#for-the-website-team`
    );
    expect(docsUrl("guides/object-content-storage", "en")).toBe(
      `https://docs.eneo.ai${version}/guides/object-content-storage`
    );
  });
});
