import { describe, expect, it } from "vitest";
import { sanitizeLinkHref, sanitizeWebHref } from "./sanitizeUrl";

describe("sanitizeWebHref", () => {
  it.each([
    "https://kommun.se/riktlinje",
    "http://intranat.kommun.local/sida",
    "HTTPS://KOMMUN.SE"
  ])("keeps the http(s) address %j", (href) => {
    expect(sanitizeWebHref(href)).toBe(href);
  });

  it.each([
    "javascript:alert(1)",
    "java\tscript:alert(1)",
    " javascript:alert(1)",
    "vbscript:msgbox(1)",
    "data:text/html,x",
    "mailto:registrator@kommun.se",
    "tel:+4660191000",
    "/spaces/1/settings",
    "//annan.example/sida",
    "riktlinje.pdf",
    "",
    null,
    undefined
  ])("drops %j", (href) => {
    expect(sanitizeWebHref(href)).toBeUndefined();
  });

  it("is stricter than a Markdown link, which may be relative or a mail link", () => {
    expect(sanitizeLinkHref("/spaces/1/settings")).toBe("/spaces/1/settings");
    expect(sanitizeLinkHref("mailto:registrator@kommun.se")).toBe("mailto:registrator@kommun.se");
  });
});
