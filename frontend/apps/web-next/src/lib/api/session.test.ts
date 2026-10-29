import { beforeEach, expect, it, vi } from "vitest";
import { testAppContext, testQueryClient } from "@/test/render";
import type { EneoClient } from "./browser";
import { EneoApiError } from "./errors";
import { loadSession, sessionKeys } from "./session";

const ME = "/api/v1/users/me/";
const WHATS_NEW = "/api/v1/whats-new/state/";
const signedIn = testAppContext();

// The backend's answers; a test turns one into a failure.
let failing: Set<string>;
const answers: Record<string, unknown> = {
  [ME]: signedIn.user,
  "/api/v1/users/tenant/": signedIn.tenant,
  "/api/v1/settings/": signedIn.settings,
  "/api/v1/auth/federation-status": signedIn.federationStatus,
  "/api/v1/limits/": signedIn.limits,
  [WHATS_NEW]: { seen_version: "1.0.0", announced_version: "1.0.0" }
};
const get = vi.fn(async (path: string) => {
  const response = new Response(null, { status: failing.has(path) ? 500 : 200 });
  return failing.has(path) ? { error: {}, response } : { data: answers[path], response };
});
const api = { GET: get } as unknown as EneoClient;

beforeEach(() => {
  failing = new Set();
  get.mockClear();
});

const requested = () => get.mock.calls.map(([path]) => path).sort();

it("loads the six session resources, not the backend version", async () => {
  const queryClient = testQueryClient();

  await loadSession(queryClient, api);

  expect(requested()).toEqual(Object.keys(answers).sort());
  expect(queryClient.getQueryData(sessionKeys.me)).toEqual(signedIn.user);
});

it("loads an unavailable What's new state as null: unknown markers, not a first visit", async () => {
  failing.add(WHATS_NEW);
  const queryClient = testQueryClient();

  await loadSession(queryClient, api);

  expect(queryClient.getQueryData(sessionKeys.whatsNew)).toBeNull();
});

it("fails to load when a required resource fails", async () => {
  failing.add(ME);

  await expect(loadSession(testQueryClient(), api)).rejects.toBeInstanceOf(EneoApiError);
});

// The SPA loads into a cache that lives on: a failed background refresh marks
// the queries invalidated, and must neither block nor overwrite their data.
it("returns what is cached, even after a failed refresh, without asking the backend", async () => {
  const queryClient = testQueryClient();
  await loadSession(queryClient, api);
  await queryClient.invalidateQueries({ refetchType: "none" });
  failing = new Set(Object.keys(answers));
  get.mockClear();

  await loadSession(queryClient, api);

  expect(get).not.toHaveBeenCalled();
  expect(queryClient.getQueryData(sessionKeys.me)).toEqual(signedIn.user);
  expect(queryClient.getQueryData(sessionKeys.whatsNew)).toEqual(answers[WHATS_NEW]);
});
