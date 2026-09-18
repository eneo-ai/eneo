import { describe, expect, it } from "vitest";
import { frameAncestorsFor, withFramePolicy } from "./csp";

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
