import { describe, expect, it } from "vitest";
import { sanitizeImageSrc, sanitizeLinkHref, sanitizeWebHref } from "./safe-url";

// Ported unchanged from the web app's markdown/sanitizeUrl.test.ts.
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

// Hidden schemes: browsers lowercase the scheme, drop ASCII tab, newline and
// CR anywhere and ignore leading control characters and spaces.
const SCRIPT_SCHEMES = [
  "javascript:alert(1)",
  "JaVaScRiPt:alert(1)",
  "java\tscript:alert(1)",
  "java\nscript:alert(1)",
  "java\rscript:alert(1)",
  " javascript:alert(1)",
  "\u0000javascript:alert(1)",
  "\u001fjavascript:alert(1)",
  "\u0000 \tjavascript:alert(1)",
  "vbscript:msgbox(1)",
  "VBScript:msgbox(1)",
  "data:text/html,<script>alert(1)</script>",
  "DATA:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
  " data:text/html,x",
  "blob:https://eneo.example/0e4c6a8e-0000-4000-8000-000000000000",
  "file:///etc/passwd",
  "eneo-file:abc"
];

describe("sanitizeLinkHref", () => {
  it.each([
    "https://kommun.se/riktlinje",
    "HTTP://KOMMUN.SE",
    "mailto:registrator@kommun.se",
    "tel:+4660191000",
    "/spaces/1/settings",
    "#bilaga",
    "?flik=2",
    "riktlinje.pdf",
    "./bilagor/1.pdf",
    "//annan.example/sida"
  ])("keeps %j", (href) => {
    expect(sanitizeLinkHref(href)).toBe(href);
  });

  it.each([...SCRIPT_SCHEMES, "", null, undefined])("drops %j", (href) => {
    expect(sanitizeLinkHref(href)).toBeUndefined();
  });
});

describe("sanitizeImageSrc", () => {
  it.each([
    "https://kommun.se/bild.png",
    "http://intranat.kommun.local/bild.png",
    "data:image/png;base64,iVBORw0KGgo=",
    "DATA:IMAGE/PNG;base64,iVBORw0KGgo=",
    "/api/v1/files/1/download/",
    "bild.png",
    "//annan.example/bild.png"
  ])("keeps %j", (src) => {
    expect(sanitizeImageSrc(src)).toBe(src);
  });

  it.each([
    ...SCRIPT_SCHEMES,
    "data:application/xhtml+xml,x",
    "data:,x",
    "mailto:registrator@kommun.se",
    "",
    null,
    undefined
  ])("drops %j", (src) => {
    expect(sanitizeImageSrc(src)).toBeUndefined();
  });
});

// Whatever passes must resolve, through the URL parser browsers use, to an
// allowed scheme on the page: an encoded scheme is no scheme at all, so it
// stays a harmless relative address.
describe("what a sanitizer lets through, the browser reads with an allowed scheme", () => {
  const PAGE = "https://eneo.example/conversations/123";
  const inputs = [
    ...SCRIPT_SCHEMES,
    "&#106;avascript:alert(1)",
    "&#x6A;avascript:alert(1)",
    "javascript&colon;alert(1)",
    "%6Aavascript:alert(1)",
    "javascript%3Aalert(1)",
    " javascript:alert(1)",
    " javascript:alert(1)",
    "jaİvascript:alert(1)",
    "https://kommun.se/riktlinje",
    "//annan.example/sida",
    "mailto:registrator@kommun.se",
    "data:image/png;base64,iVBORw0KGgo="
  ];
  const sanitizers = {
    sanitizeLinkHref: [sanitizeLinkHref, ["https:", "http:", "mailto:", "tel:"]],
    sanitizeWebHref: [sanitizeWebHref, ["https:", "http:"]],
    sanitizeImageSrc: [sanitizeImageSrc, ["https:", "http:", "data:"]]
  } as const;

  it.each(Object.keys(sanitizers).flatMap((name) => inputs.map((input) => [name, input])))(
    "%s keeps %j only with an allowed scheme",
    (name, input) => {
      const [sanitize, schemes] = sanitizers[name as keyof typeof sanitizers];
      const kept = sanitize(input);
      if (kept !== undefined) expect(schemes).toContain(new URL(kept, PAGE).protocol);
    }
  );

  it("keeps an encoded scheme as a relative address", () => {
    for (const encoded of [
      "&#106;avascript:alert(1)",
      "%6Aavascript:alert(1)",
      "javascript%3Aalert(1)"
    ]) {
      expect(sanitizeLinkHref(encoded)).toBe(encoded);
      expect(new URL(encoded, PAGE).origin).toBe("https://eneo.example");
    }
  });
});
