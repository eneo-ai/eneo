import { describe, expect, it } from "vitest";
import { safeExternalUrl } from "./externalUrl";

describe("safeExternalUrl", () => {
  it.each([
    ["https://kommun.sharepoint.com/sites/hr/Delade%20dokument/Rutin.docx", true],
    ["https://kommun.atlassian.net/wiki/spaces/HR", true],
    ["http://kommun.sharepoint.com/sites/hr", false],
    ["javascript:alert(1)", false],
    ["JavaScript:alert(1)", false],
    ["data:text/html,<script>alert(1)</script>", false],
    ["/spaces/s1/knowledge", false],
    ["//evil.example/x", false],
    ["not a url", false],
    ["", false],
    [null, false],
    [undefined, false]
  ])("%s → kept: %s", (url, kept) => {
    expect(safeExternalUrl(url) !== null).toBe(kept);
  });
});
