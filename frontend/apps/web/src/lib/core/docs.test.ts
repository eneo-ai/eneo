import { describe, expect, it, vi } from "vitest";
import { docsUrl, docsVersionPath } from "./docs";

const catalog = vi.hoisted(() => ({
  releases: [
    {
      version: "next",
      date: undefined as string | undefined,
      entries: [{ id: "web-widgets" }, { id: "admin-sign-in-settings" }]
    },
    { version: "2.3.0", date: "2026-11-02", entries: [] }
  ]
}));
vi.mock("@eneo/whats-new", () => ({
  releases: catalog.releases,
  latestRelease: () => catalog.releases[1]
}));

describe("docs links", () => {
  it("point at the release line once the release is dated, else at the development docs", () => {
    expect(docsVersionPath({ version: "2.3.0", date: "2026-10-01" })).toBe("/v2.3");
    expect(docsVersionPath({ version: "2.3.1", date: "2026-10-20" })).toBe("/v2.3");
    expect(docsVersionPath({ version: "2.3.0" })).toBe("/dev");
    expect(docsVersionPath(undefined)).toBe("/dev");
  });

  it("keeps unreleased widget instructions on development docs while storage follows the release", () => {
    expect(docsUrl("guides/embed-widget", "sv", "for-the-website-team")).toBe(
      "https://docs.eneo.ai/dev/sv/guides/embed-widget#for-the-website-team"
    );
    expect(docsUrl("guides/object-content-storage", "en")).toBe(
      "https://docs.eneo.ai/v2.3/guides/object-content-storage"
    );
  });

  it("keeps the unreleased sign-in settings section on development docs", () => {
    expect(
      docsUrl("guides/oidc-federation/single-tenant", "sv", "move-the-settings-into-eneo")
    ).toBe(
      "https://docs.eneo.ai/dev/sv/guides/oidc-federation/single-tenant#move-the-settings-into-eneo"
    );
  });

  it("links widget instructions to the version that releases the feature", () => {
    const widgetRelease = catalog.releases[0];
    widgetRelease.version = "2.4.0";
    widgetRelease.date = "2026-12-01";
    try {
      expect(docsUrl("guides/embed-widget", "en")).toBe(
        "https://docs.eneo.ai/v2.4/guides/embed-widget"
      );
    } finally {
      widgetRelease.version = "next";
      widgetRelease.date = undefined;
    }
  });
});
