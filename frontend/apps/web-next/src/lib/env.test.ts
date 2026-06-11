import { expect, it } from "vitest";
import { parseEnv } from "./env";

it("rejects a missing ENEO_BACKEND_URL", () => {
  expect(() => parseEnv({})).toThrow(/ENEO_BACKEND_URL/);
});

it("accepts a minimal valid environment and defaults the feature flags off", () => {
  const env = parseEnv({ ENEO_BACKEND_URL: "http://localhost:8123" });
  expect(env.ENEO_BACKEND_URL).toBe("http://localhost:8123");
  expect(env.SHOW_WEB_SEARCH).toBe(false);
  expect(env.SHOW_HELP_CENTER).toBe(false);
});
