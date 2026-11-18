import { describe, expect, it } from "vitest";
import { readWebsiteContentSearch, websiteContentHref } from "./website-content-search";

describe("website content URLs", () => {
  it("keeps a URL directory and bounds title/URL search to the API contract", () => {
    const params = new URLSearchParams({
      tab: "blobs",
      prefix: "https://example.test/docs/",
      q: `  ${"a".repeat(210)}  `
    });
    expect(readWebsiteContentSearch(params)).toEqual({
      tab: "blobs",
      prefix: "https://example.test/docs/",
      q: "a".repeat(200)
    });
  });

  it.each([
    "javascript:alert(1)",
    "https://example.test/no-slash",
    "https://example.test/docs/?q=x",
    `https://example.test/${"a".repeat(2048)}/`
  ])("ignores a prefix the API cannot accept: %s", (prefix) => {
    expect(readWebsiteContentSearch(new URLSearchParams({ prefix, tab: "unknown" }))).toEqual({
      tab: "crawls",
      prefix: "",
      q: ""
    });
  });

  it("keeps other URL state and escapes content values inside this page's query", () => {
    const href = websiteContentHref(
      "/spaces/s/knowledge/websites/w",
      new URLSearchParams("other=value&q=old"),
      { tab: "blobs", prefix: "https://example.test/docs/", q: "<script>&value" }
    );
    const url = new URL(href, "https://eneo.test");
    expect(url.origin).toBe("https://eneo.test");
    expect(url.searchParams.get("other")).toBe("value");
    expect(readWebsiteContentSearch(url.searchParams)).toEqual({
      tab: "blobs",
      prefix: "https://example.test/docs/",
      q: "<script>&value"
    });
  });
});

it("keeps the Problems tab in a reloadable website URL", () => {
  expect(readWebsiteContentSearch(new URLSearchParams("tab=problems")).tab).toBe("problems");
});
