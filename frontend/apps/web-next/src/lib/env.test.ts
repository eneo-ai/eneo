import { expect, it } from "vitest";
import { parseEnv } from "./env";

const SECRET = "test-secret-that-is-at-least-32-chars!!";

it("rejects a missing ENEO_BACKEND_URL", () => {
  expect(() => parseEnv({ SESSION_SECRET: SECRET })).toThrow(/ENEO_BACKEND_URL/);
});

it("rejects a too-short SESSION_SECRET", () => {
  expect(() =>
    parseEnv({ ENEO_BACKEND_URL: "http://localhost:8123", SESSION_SECRET: "short" })
  ).toThrow(/SESSION_SECRET/);
});

it("rejects OIDC_ISSUER without client credentials", () => {
  expect(() =>
    parseEnv({
      ENEO_BACKEND_URL: "http://localhost:8123",
      SESSION_SECRET: SECRET,
      OIDC_ISSUER: "https://idp.example.com"
    })
  ).toThrow(/OIDC_CLIENT_ID/);
});

it("accepts a minimal valid environment with defaults", () => {
  const env = parseEnv({ ENEO_BACKEND_URL: "http://localhost:8123", SESSION_SECRET: SECRET });
  expect(env.ENEO_BACKEND_URL).toBe("http://localhost:8123");
  expect(env.APP_ORIGIN).toBe("http://localhost:3100");
  expect(env.OIDC_SCOPES).toBe("openid profile email offline_access");
  expect(env.SHOW_WEB_SEARCH).toBe(false);
  expect(env.SHOW_HELP_CENTER).toBe(false);
  expect(env.OIDC_ISSUER).toBeUndefined();
});

it("parses enabled boolean feature flags", () => {
  const env = parseEnv({
    ENEO_BACKEND_URL: "http://localhost:8123",
    SESSION_SECRET: SECRET,
    SHOW_WEB_SEARCH: "true"
  });
  expect(env.SHOW_WEB_SEARCH).toBe(true);
});
