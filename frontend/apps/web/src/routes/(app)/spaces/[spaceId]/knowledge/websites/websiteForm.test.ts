import { describe, expect, it } from "vitest";
import { isSupportedWebsiteUrl } from "./websiteForm";

describe("isSupportedWebsiteUrl", () => {
  it.each([
    "https://example.com",
    "http://intranet.local/path",
    "https://sundsvall.se/sitemap.xml"
  ])("accepts a crawlable HTTP URL: %s", (url) => {
    expect(isSupportedWebsiteUrl(url)).toBe(true);
  });

  it.each(["", "example.com", "ftp://example.com/file", "javascript:alert(1)"])(
    "rejects an unsupported URL: %s",
    (url) => {
      expect(isSupportedWebsiteUrl(url)).toBe(false);
    }
  );
});
