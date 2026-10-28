// @vitest-environment jsdom
import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import type { EneoClient } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { renderInApp, renderToHtml, testAppContext, testQueryClient } from "@/test/render";
import { useWhatsNew } from "@/features/whats-new/whats-new-provider";
import { useAppContext, type AppContextValue } from "./app-context";
import { QueryAppContextProvider, type AppContextEnv } from "./app-context-from-queries";
import { appContextKeys, invalidateAppContext, loadAppContext } from "./app-context-queries";

const ME = "/api/v1/users/me/";
const TENANT = "/api/v1/users/tenant/";
const SETTINGS = "/api/v1/settings/";
const FEDERATION = "/api/v1/auth/federation-status";
const LIMITS = "/api/v1/limits/";
const VERSION = "/version";
const WHATS_NEW = "/api/v1/whats-new/state/";

type Reply = { status: number; body: unknown };
const ok = (body: unknown): Reply => ({ status: 200, body });
const failure: Reply = { status: 500, body: { message: "Internal error" } };

// The backend's current answers; a test changes them between requests.
let backend: Map<string, Reply>;

/** Answers with the backend's state at request time, after a network delay. */
function request(path: string) {
  const { status, body } = backend.get(path)!;
  const data = structuredClone(body);
  return new Promise((resolve) =>
    setTimeout(() => {
      const response = new Response(null, { status });
      resolve(status < 400 ? { data, response } : { error: data, response });
    }, 5)
  );
}

const browserGet = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: browserGet } }));
// The (app) layout loads with the server's client.
const serverApi = { GET: vi.fn(request) } as unknown as EneoClient;

const env: AppContextEnv = {
  showWebSearch: true,
  links: { accessibilityStatement: null, helpCenter: null, legacyApp: null },
  frontendVersion: "0.1.0"
};
const signedIn = testAppContext();

beforeEach(() => {
  browserGet.mockReset().mockImplementation(request);
  backend = new Map([
    [ME, ok(signedIn.user)],
    [TENANT, ok(signedIn.tenant)],
    [SETTINGS, ok(signedIn.settings)],
    [FEDERATION, ok(signedIn.federationStatus)],
    [LIMITS, ok(signedIn.limits)],
    [VERSION, ok({ version: "1.2.3" })],
    [WHATS_NEW, ok({ seen_version: "1.0.0", announced_version: "1.0.0" })]
  ]);
});

let contextValues: AppContextValue[] = [];

/** Reads the context and holds state of its own, as the app under WhatsNewProvider does. */
function Probe() {
  const context = useAppContext();
  const { seenVersion } = useWhatsNew();
  const [clicks, setClicks] = useState(0);
  contextValues.push(context);
  return (
    <div>
      <span data-testid="user">{context.user.username}</span>
      <span data-testid="tenant">{context.tenant.display_name}</span>
      <span data-testid="seen">{seenVersion === undefined ? "unknown" : String(seenVersion)}</span>
      <button onClick={() => setClicks(clicks + 1)}>{`Klick ${clicks}`}</button>
    </div>
  );
}

/** What the (app) layout does: load on the server, hydrate, provide. */
async function load() {
  const server = testQueryClient();
  await loadAppContext(server, serverApi);
  return dehydrate(server);
}

async function renderApp() {
  let state = await load();
  const tree = () => (
    <HydrationBoundary state={state}>
      <QueryAppContextProvider env={env}>
        <Probe />
      </QueryAppContextProvider>
    </HydrationBoundary>
  );
  contextValues = [];
  const html = renderToHtml(tree(), { queryClient: testQueryClient() });
  const view = renderInApp(tree(), { queryClient: testQueryClient() });
  return {
    ...view,
    html,
    rerender: () => view.rerender(tree()),
    /** router.refresh(): the layout loads again and its new snapshot reaches the mounted boundary. */
    refresh: async () => {
      state = await load();
      view.rerender(tree());
    }
  };
}

/** Longer than any request takes. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 30));

const requested = () => browserGet.mock.calls.map(([path]) => path as string).sort();

it("server-renders and hydrates the loaded context without a request", async () => {
  const { html } = await renderApp();

  expect(html).toContain("Anna Lind");
  expect(screen.getByTestId("user").textContent).toBe("Anna Lind");
  await settle();
  expect(browserGet).not.toHaveBeenCalled();
});

it("does not refetch when the window regains focus, even once stale", async () => {
  const { queryClient } = await renderApp();
  // Stale, as after a failed refetch: only refetchOnWindowFocus: false holds them.
  await queryClient.invalidateQueries({ queryKey: appContextKeys.all, refetchType: "none" });

  window.dispatchEvent(new Event("focus"));
  document.dispatchEvent(new Event("visibilitychange", { bubbles: true }));
  await settle();

  expect(browserGet).not.toHaveBeenCalled();
});

it("refetches every source but the backend version on invalidateAppContext", async () => {
  const { queryClient } = await renderApp();
  backend.set(TENANT, ok({ ...signedIn.tenant, display_name: "Timrå kommun" }));

  await invalidateAppContext(queryClient);

  expect(requested()).toEqual([ME, TENANT, SETTINGS, FEDERATION, LIMITS, WHATS_NEW].sort());
  await waitFor(() => expect(screen.getByTestId("tenant").textContent).toBe("Timrå kommun"));
});

it("keeps the context value when a refetch answers the same, so consumers need not re-render", async () => {
  const { queryClient, rerender } = await renderApp();
  const before = contextValues.at(-1);

  await invalidateAppContext(queryClient);
  await settle();
  rerender();

  expect(requested()).toHaveLength(6);
  expect(contextValues.at(-1)).toBe(before);
});

it("takes a refreshed layout's newer data without remounting the app", async () => {
  const { refresh } = await renderApp();
  fireEvent.click(screen.getByRole("button", { name: "Klick 0" }));
  backend.set(TENANT, ok({ ...signedIn.tenant, display_name: "Timrå kommun" }));

  await refresh();

  await waitFor(() => expect(screen.getByTestId("tenant").textContent).toBe("Timrå kommun"));
  expect(screen.getByRole("button", { name: "Klick 1" })).toBeTruthy();
  expect(browserGet).not.toHaveBeenCalled();
});

it("keeps the previous data and the app mounted when a refetch fails", async () => {
  const { queryClient } = await renderApp();
  fireEvent.click(screen.getByRole("button", { name: "Klick 0" }));
  backend.set(TENANT, failure);
  backend.set(WHATS_NEW, failure);

  await invalidateAppContext(queryClient);
  await settle();

  expect(queryClient.getQueryState(appContextKeys.tenant)?.status).toBe("error");
  expect(queryClient.getQueryState(appContextKeys.whatsNew)?.status).toBe("error");
  expect(screen.getByTestId("tenant").textContent).toBe("Sundsvalls kommun");
  // The What's new markers held, so WhatsNewProvider's key did and nothing remounted.
  expect(screen.getByTestId("seen").textContent).toBe("1.0.0");
  expect(screen.getByRole("button", { name: "Klick 1" })).toBeTruthy();
});

it("loads an unavailable What's new state as null: unknown markers, not a first visit", async () => {
  backend.set(WHATS_NEW, failure);

  const { queryClient } = await renderApp();

  expect(queryClient.getQueryData(appContextKeys.whatsNew)).toBeNull();
  expect(screen.getByTestId("seen").textContent).toBe("unknown");
});

it("fails to load when a required source fails", async () => {
  backend.set(ME, failure);

  await expect(loadAppContext(testQueryClient(), serverApi)).rejects.toBeInstanceOf(EneoApiError);
});
