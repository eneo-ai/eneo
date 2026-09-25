import { describe, expect, it } from "vitest";
import { frameAncestorsFor, isHostSource, originSource, withFramePolicy } from "./csp";

describe("withFramePolicy", () => {
  it("adds frame-ancestors to an existing policy without touching other directives", () => {
    const csp = "script-src 'self' 'nonce-abc'; script-src-elem 'self'";
    expect(withFramePolicy(csp, { frameAncestors: "'none'" })).toBe(
      "script-src 'self' 'nonce-abc'; script-src-elem 'self'; frame-ancestors 'none'"
    );
  });

  it("creates a policy when none exists", () => {
    expect(withFramePolicy(null, { frameAncestors: "'none'" })).toBe("frame-ancestors 'none'");
  });

  it("replaces a frame-ancestors directive that is already present", () => {
    expect(
      withFramePolicy("frame-ancestors 'none'; script-src 'self'", {
        frameAncestors: "'self' https://www.kommun.se"
      })
    ).toBe("frame-ancestors 'self' https://www.kommun.se; script-src 'self'");
  });

  it("hardens the embed page without overriding directives the app already sets", () => {
    expect(
      withFramePolicy("script-src 'self'; object-src 'self'", {
        frameAncestors: "'self'",
        harden: true
      })
    ).toBe(
      "script-src 'self'; object-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'; frame-src 'none'"
    );
    expect(withFramePolicy(null, { frameAncestors: "'none'" })).not.toContain("base-uri");
  });

  it("allows blob workers only when asked", () => {
    expect(
      withFramePolicy("script-src 'self'", { frameAncestors: "'self'", allowBlobWorkers: true })
    ).toBe("script-src 'self'; frame-ancestors 'self'; worker-src 'self' blob:");
  });
});

describe("frameAncestorsFor", () => {
  it("denies when there are no sources", () => {
    expect(frameAncestorsFor([])).toBe("'none'");
    expect(frameAncestorsFor(["  "])).toBe("'none'");
  });

  it("keeps self so the stand-alone page still works and lists every source", () => {
    expect(frameAncestorsFor(["https://www.kommun.se", "https://*.kommun.se"])).toBe(
      "'self' https://www.kommun.se https://*.kommun.se"
    );
  });
});

describe("host source validation", () => {
  it("drops sources that carry directive syntax instead of emitting them", () => {
    expect(
      frameAncestorsFor(["https://a.com; report-to grp", "https://b.com c.com", "https://ok.se"])
    ).toBe("'self' https://ok.se");
    expect(frameAncestorsFor(["https://a.com;default-src"])).toBe("'none'");
    expect(isHostSource("https://*.kommun.se:*")).toBe(true);
    expect(isHostSource("https://[::1]:3000")).toBe(true);
    expect(isHostSource("https://exämple.se")).toBe(false);
  });

  it("restricts images and connections on the embed page to known origins", () => {
    expect(
      withFramePolicy("script-src 'self'", {
        frameAncestors: "'self'",
        embedSources: {
          img: ["https://cdn.kommun.se", "https://evil.tld; report-to x"],
          connect: ["https://api.eneo.se", "https://api.eneo.se"]
        }
      })
    ).toBe(
      "script-src 'self'; frame-ancestors 'self'; img-src 'self' data: blob: https://cdn.kommun.se; connect-src 'self' https://api.eneo.se"
    );
  });

  it("turns absolute URLs into origin sources", () => {
    expect(originSource("https://cdn.kommun.se/logo.png?x=1")).toBe("https://cdn.kommun.se");
    expect(originSource("http://localhost:8123")).toBe("http://localhost:8123");
    expect(originSource("")).toBeNull();
    expect(originSource("not a url")).toBeNull();
    expect(originSource("data:image/png;base64,AAAA")).toBeNull();
  });
});
