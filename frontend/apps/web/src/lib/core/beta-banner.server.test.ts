import { beforeEach, expect, it, vi } from "vitest";

const env = vi.hoisted(() => ({ NEW_APP_URL: "", SHOW_NEW_APP_BANNER: "" }));
vi.mock("$env/dynamic/private", () => ({ env }));
import { getNewAppUrl } from "./environment.server";
import { getFeatureFlags } from "./flags.server";
const fetchStatus = vi.fn(async () => new Response("{}", { status: 503 }));

beforeEach(() => {
  env.NEW_APP_URL = "";
  env.SHOW_NEW_APP_BANNER = "";
});

it("keeps the invitation off by default, including when a beta URL is configured", async () => {
  env.NEW_APP_URL = "https://beta.example";
  expect((await getFeatureFlags(fetchStatus)).showNewAppBanner).toBe(false);
});

it("requires both the opt-in flag and a valid destination", async () => {
  env.SHOW_NEW_APP_BANNER = "true";
  expect((await getFeatureFlags(fetchStatus)).showNewAppBanner).toBe(false);
  env.NEW_APP_URL = "https://beta.example";
  expect(getNewAppUrl()).toBe("https://beta.example/");
  expect((await getFeatureFlags(fetchStatus)).showNewAppBanner).toBe(true);
  env.SHOW_NEW_APP_BANNER = "false";
  expect((await getFeatureFlags(fetchStatus)).showNewAppBanner).toBe(false);
});

it.each([
  "javascript:alert(1)",
  "data:text/html,test",
  "https://user:pass@beta.example",
  "//beta.example",
  "invalid"
])("does not expose an unsafe beta destination: %s", async (url) => {
  env.SHOW_NEW_APP_BANNER = "true";
  env.NEW_APP_URL = url;
  expect(getNewAppUrl()).toBeUndefined();
  expect((await getFeatureFlags(fetchStatus)).showNewAppBanner).toBe(false);
});
