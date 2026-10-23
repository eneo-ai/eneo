import { describe, expect, it } from "vitest";
import { safeExternalUrl } from "./external-url";

describe("safeExternalUrl", () => {
  it("keeps an absolute https address", () => {
    expect(safeExternalUrl("https://kommun.sharepoint.com/sites/avtal/Delade dokument")).toBe(
      "https://kommun.sharepoint.com/sites/avtal/Delade%20dokument"
    );
    expect(safeExternalUrl("HTTPS://kommun.atlassian.net/wiki/spaces/HR")).toBe(
      "https://kommun.atlassian.net/wiki/spaces/HR"
    );
  });

  it.each([
    ["plain http", "http://kommun.sharepoint.com/sites/avtal"],
    ["a script", "javascript:alert(document.cookie)"],
    ["a script behind spaces and case", "  JavaScript:alert(1)"],
    ["inline data", "data:text/html,<script>alert(1)</script>"],
    ["a relative path", "/sites/avtal"],
    ["a protocol-relative address", "//evil.example/sites/avtal"],
    ["a malformed address", "https://"],
    ["credentials in the address", "https://anna:hemligt@kommun.sharepoint.com/sites/avtal"],
    ["an empty string", ""],
    ["no address", null],
    ["a missing address", undefined]
  ])("drops %s", (_label, url) => {
    expect(safeExternalUrl(url)).toBeNull();
  });
});
