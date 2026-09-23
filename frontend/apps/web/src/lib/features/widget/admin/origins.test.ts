import { describe, expect, it } from "vitest";
import { MAX_ALLOWED_ORIGINS, normalizeOrigin, parseOrigins } from "./origins";

// Expected values are what the backend's normalize_origin_pattern returns
// (null where it raises), so the field refuses exactly what a save would.
// backend/tests/unit/test_origin_matching.py holds the same table.
const BACKEND: [string, string | null][] = [
  ["https://www.kommun.se", "https://www.kommun.se"],
  ["https://www.kommun.se/", "https://www.kommun.se"],
  ["https://www.kommun.se/kontakt", null],
  ["HTTPS://WWW.Kommun.SE//", "https://www.kommun.se"],
  ["https://*.kommun.se", "https://*.kommun.se"],
  ["http://localhost:*", "http://localhost:*"],
  ["http://localhost:3000", "http://localhost:3000"],
  ["http://localhost:", null],
  ["http://localhost:99999", null],
  ["http://localhost:65535", "http://localhost:65535"],
  ["https://user@kommun.se", null],
  ["https://kommun.se?x=1", null],
  ["https://kommun.se#frag", null],
  ["ftp://kommun.se", null],
  ["kommun.se", null],
  ["https://", null],
  ["https://[::1]", null],
  ["https://[::1]:8080", "https://[::1]:8080"],
  ["https://[::1]:*", "https://[::1]:*"],
  ["https://kom mun.se", null],
  ["https://kommun.se;script", null],
  ["https://-bad.se", null],
  ["https://bad-.se", null],
  ["https://a..se", null],
  ["https://*.*.se", null],
  ["https://xn--bcher-kva.example", "https://xn--bcher-kva.example"],
  ["https://1.2.3.4:443", "https://1.2.3.4:443"],
  ["http://localhost:08", "http://localhost:08"],
  ["https://kommun.se:abc", null],
  ["https://[zz]", null],
  ["https://example.com?", null],
  ["https://example.com#", null],
  ["https://@example.com", null],
  ["https://example.com:000080", "https://example.com:000080"],
  ["https://[abc.def]:80", null],
  ["https://[1.2.3.4]:80", null],
  ["https://[:::]:80", null],
  ["https://[::ffff:1.2.3.4]:80", "https://[::ffff:1.2.3.4]:80"]
];

describe("allowed origins", () => {
  it.each(BACKEND)("%s matches the API's rule", (input, expected) => {
    expect(normalizeOrigin(input)).toBe(expected);
  });

  it("splits lines, keeps the canonical form once and names the refused lines", () => {
    const parsed = parseOrigins(
      "https://www.kommun.se/\n\n  https://WWW.kommun.se \nhttps://www.kommun.se/kontakt\n"
    );
    expect(parsed.origins).toEqual(["https://www.kommun.se"]);
    expect(parsed.invalid).toEqual(["https://www.kommun.se/kontakt"]);
    expect(parsed.tooMany).toBe(false);
  });

  it("flags more origins than the API stores", () => {
    const lines = Array.from({ length: MAX_ALLOWED_ORIGINS + 1 }, (_, i) => `https://s${i}.se`);
    expect(parseOrigins(lines.join("\n")).tooMany).toBe(true);
    expect(parseOrigins(lines.slice(1).join("\n")).tooMany).toBe(false);
  });
});
