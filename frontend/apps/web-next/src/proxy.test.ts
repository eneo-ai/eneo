import { expect, it } from "vitest";
import {
  buildContentSecurityPolicy,
  isMobileUserAgent,
  shouldRedirectMobileToDashboard
} from "./proxy";

function directive(csp: string, name: string): string {
  const value = csp.split("; ").find((part) => part.startsWith(`${name} `));
  if (!value) throw new Error(`missing ${name}`);
  return value;
}

it("builds a strict production script policy with a request nonce", () => {
  const csp = buildContentSecurityPolicy("test-nonce", "production");
  const script = directive(csp, "script-src");

  expect(script).toContain("'self'");
  expect(script).toContain("'nonce-test-nonce'");
  expect(script).toContain("'strict-dynamic'");
  expect(script).not.toContain("'unsafe-inline'");
  expect(script).not.toContain("'unsafe-eval'");
  expect(directive(csp, "script-src-attr")).toBe("script-src-attr 'none'");
  expect(csp).toContain("upgrade-insecure-requests");
});

it("allows React dev eval without weakening production script-src", () => {
  const csp = buildContentSecurityPolicy("dev-nonce", "development");

  expect(directive(csp, "script-src")).toContain("'unsafe-eval'");
  expect(directive(csp, "style-src")).toContain("'unsafe-inline'");
  expect(csp).not.toContain("upgrade-insecure-requests");
});

it("detects mobile user agents for dashboard redirect parity", () => {
  expect(
    isMobileUserAgent(
      "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
    )
  ).toBe(true);
  expect(
    isMobileUserAgent(
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/120 Safari/537.36"
    )
  ).toBe(false);
});

it("redirects authenticated mobile users to dashboard outside dashboard routes", () => {
  const mobile = "Mozilla/5.0 (Android 14; Mobile) AppleWebKit/537.36";

  expect(shouldRedirectMobileToDashboard("/spaces/personal/chat", mobile)).toBe(true);
  expect(shouldRedirectMobileToDashboard("/dashboard", mobile)).toBe(false);
  expect(shouldRedirectMobileToDashboard("/dashboard/app/app-1", mobile)).toBe(false);
});
