import { NextRequest } from "next/server";
import { expect, it } from "vitest";
import { env } from "@/lib/env";
import { SESSION_COOKIE } from "@/lib/auth/session";
import { sealSession } from "@/lib/auth/session-codec";
import { buildContentSecurityPolicy, proxy } from "./proxy";

const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148";
const ANDROID = "Mozilla/5.0 (Android 14; Mobile) AppleWebKit/537.36";

async function signedInRequest(path: string, userAgent: string) {
  const session = await sealSession(
    {
      mode: "password",
      accessToken: "token",
      accessTokenExpiresAt: Math.floor(Date.now() / 1000) + 3600,
      user: { email: "anna@example.se" }
    },
    env.SESSION_SECRET,
    3600
  );
  return new NextRequest(new URL(path, "http://localhost:3100"), {
    headers: { cookie: `${SESSION_COOKIE}=${session}`, "user-agent": userAgent }
  });
}

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

it("serves phones the requested page instead of redirecting them to /dashboard", async () => {
  for (const userAgent of [IPHONE, ANDROID]) {
    const response = await proxy(await signedInRequest("/spaces/personal/chat", userAgent));
    expect(response.status).toBe(200);
    expect(response.headers.get("location")).toBeNull();
  }
});

it("keeps /dashboard reachable on phones", async () => {
  const response = await proxy(await signedInRequest("/dashboard", ANDROID));
  expect(response.status).toBe(200);
  expect(response.headers.get("location")).toBeNull();
});

it("still sends signed-out visitors to the login page", async () => {
  const response = await proxy(
    new NextRequest(new URL("/spaces/personal/chat", "http://localhost:3100"), {
      headers: { "user-agent": IPHONE }
    })
  );
  expect(response.status).toBe(307);
  expect(new URL(response.headers.get("location") ?? "").pathname).toBe("/login");
});
