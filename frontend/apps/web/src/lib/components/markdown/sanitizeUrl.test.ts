import { describe, expect, it } from "vitest";
import { sanitizeLinkHref, sanitizeWebHref } from "./sanitizeUrl";

describe("sanitizeWebHref", () => {
  it.each([
    "https://kommun.se/riktlinje",
    "http://intranat.kommun.local/sida",
    "HTTPS://KOMMUN.SE",
    "https://kommun.se/riktlinje?q=a%20b#avsnitt",
    "https://räksmörgås.se/riktlinje",
    "http://[::1]:8080/riktlinje"
  ])("keeps the http(s) address %j", (href) => {
    expect(sanitizeWebHref(href)).toBe(href);
    // Accepted source links must resolve independently of the current page.
    expect(new URL(href, "https://eneo.example/conversations/123").href).toBe(new URL(href).href);
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
    "https:/spaces/1/settings",
    "https:settings",
    "http:settings",
    "ht tps://kommun.se/riktlinje",
    "ht\u0000tps://kommun.se/riktlinje",
    "https://",
    "https://kommun se/riktlinje",
    "https://[invalid]/riktlinje",
    "https://kommun.se:99999/riktlinje",
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
