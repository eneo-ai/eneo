// @vitest-environment jsdom
import { latestRelease } from "@eneo/whats-new";
import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import type { EneoClient } from "@/lib/api/browser";
import { loadSession, sessionKeys } from "@/lib/api/session";
import { renderInApp, renderToHtml, testAppContext, testQueryClient } from "@/test/render";
import { useWhatsNew } from "@/features/whats-new/whats-new-provider";
import { useAppContext, type AppContextValue } from "./app-context";
import { QueryAppContextProvider, type AppContextEnv } from "./app-context-from-queries";

const ME = "/api/v1/users/me/";
const TENANT = "/api/v1/users/tenant/";
const SETTINGS = "/api/v1/settings/";
const FEDERATION = "/api/v1/auth/federation-status";
const LIMITS = "/api/v1/limits/";
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
const browserPut = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: browserGet, PUT: browserPut } }));
// The (app) layout loads with the server's client.
const serverApi = { GET: vi.fn(request) } as unknown as EneoClient;

const env: AppContextEnv = {
  links: { accessibilityStatement: null, helpCenter: null, legacyApp: null },
  frontendVersion: "0.1.0",
  backendVersion: "1.2.3"
};
const signedIn = testAppContext();

beforeEach(() => {
  browserGet.mockReset().mockImplementation(request);
  browserPut.mockReset();
  backend = new Map([
    [ME, ok(signedIn.user)],
    [TENANT, ok(signedIn.tenant)],
    [SETTINGS, ok(signedIn.settings)],
    [FEDERATION, ok(signedIn.federationStatus)],
    [LIMITS, ok(signedIn.limits)],
    [WHATS_NEW, ok({ seen_version: "1.0.0", announced_version: "1.0.0" })]
  ]);
});

let contextValues: AppContextValue[] = [];

/** Reads the context and holds state of its own, as the app under WhatsNewProvider does. */
function Probe() {
  const context = useAppContext();
  const { seenVersion, markLatestSeen } = useWhatsNew();
  const [clicks, setClicks] = useState(0);
  contextValues.push(context);
  return (
    <div>
      <span data-testid="user">{context.user.username}</span>
      <span data-testid="tenant">{context.tenant.display_name}</span>
      <span data-testid="seen">{seenVersion === undefined ? "unknown" : String(seenVersion)}</span>
      <button onClick={() => setClicks(clicks + 1)}>{`Klick ${clicks}`}</button>
      <button onClick={() => void markLatestSeen()}>Markera sedd</button>
    </div>
  );
}

/** What the (app) layout does: load on the server, hydrate, provide. */
async function load() {
  const server = testQueryClient();
  await loadSession(server, serverApi);
  return dehydrate(server);
}

/** `browser`: the browser's query client (a fresh one unless the test brings its own). */
async function renderApp(browser = testQueryClient()) {
  let state = await load();
  const tree = () => (
    <HydrationBoundary state={state}>
      <QueryAppContextProvider env={env}>
        <Probe />
      </QueryAppContextProvider>
    </HydrationBoundary>
  );
  const html = renderToHtml(tree(), { queryClient: testQueryClient() });
  contextValues = [];
  const view = renderInApp(tree(), { queryClient: browser });
  return {
    ...view,
    html,
    rerender: () => view.rerender(tree()),
    /** A fresh server layout snapshot reaches the mounted hydration boundary. */
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
  await queryClient.invalidateQueries({ refetchType: "none" });

  window.dispatchEvent(new Event("focus"));
  document.dispatchEvent(new Event("visibilitychange", { bubbles: true }));
  await settle();

  expect(browserGet).not.toHaveBeenCalled();
});

it("keeps the context value when a refetch answers the same, so consumers need not re-render", async () => {
  const { queryClient, rerender } = await renderApp();
  const before = contextValues.at(-1);

  await queryClient.invalidateQueries();
  await settle();
  rerender();

  expect(requested()).toEqual([ME, TENANT, SETTINGS, FEDERATION, LIMITS, WHATS_NEW].sort());
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

it("keeps known What's new markers when a refreshed layout could not read them", async () => {
  const { queryClient, refresh } = await renderApp();
  backend.set(WHATS_NEW, failure);
  backend.set(TENANT, ok({ ...signedIn.tenant, display_name: "Timrå kommun" }));

  await refresh();

  await waitFor(() => expect(screen.getByTestId("tenant").textContent).toBe("Timrå kommun"));
  expect(queryClient.getQueryData(sessionKeys.whatsNew)).toEqual({
    seen_version: "1.0.0",
    announced_version: "1.0.0"
  });
  expect(screen.getByTestId("seen").textContent).toBe("1.0.0");
});

it("keeps the previous data and the app mounted when a refetch fails", async () => {
  const { queryClient } = await renderApp();
  fireEvent.click(screen.getByRole("button", { name: "Klick 0" }));
  backend.set(TENANT, failure);
  backend.set(WHATS_NEW, failure);

  await queryClient.invalidateQueries();
  await settle();

  expect(queryClient.getQueryState(sessionKeys.tenant)?.status).toBe("error");
  expect(queryClient.getQueryState(sessionKeys.whatsNew)?.status).toBe("error");
  expect(screen.getByTestId("tenant").textContent).toBe("Sundsvalls kommun");
  // The What's new markers held, and nothing remounted.
  expect(screen.getByTestId("seen").textContent).toBe("1.0.0");
  expect(screen.getByRole("button", { name: "Klick 1" })).toBeTruthy();
});

// What's new markers change while editors and chats are open: they must not
// remount the app (nothing keys it on them).
it("takes changed What's new markers without remounting the app", async () => {
  const { queryClient } = await renderApp();
  fireEvent.click(screen.getByRole("button", { name: "Klick 0" }));
  backend.set(WHATS_NEW, ok({ seen_version: "2.0.0", announced_version: "2.0.0" }));

  await queryClient.invalidateQueries({ queryKey: sessionKeys.whatsNew });

  await waitFor(() => expect(screen.getByTestId("seen").textContent).toBe("2.0.0"));
  expect(screen.getByRole("button", { name: "Klick 1" })).toBeTruthy();
});

it("records What's new as seen in the session's markers, with the app still mounted", async () => {
  const latest = latestRelease()!.version;
  backend.set(WHATS_NEW, ok({ seen_version: null, announced_version: null }));
  browserPut.mockResolvedValue({
    data: { seen_version: latest, announced_version: null },
    response: new Response(null, { status: 200 })
  });
  const { queryClient } = await renderApp();
  fireEvent.click(screen.getByRole("button", { name: "Klick 0" }));

  fireEvent.click(screen.getByRole("button", { name: "Markera sedd" }));

  await waitFor(() => expect(browserPut).toHaveBeenCalledOnce());
  await waitFor(() =>
    expect(queryClient.getQueryData(sessionKeys.whatsNew)).toEqual({
      seen_version: latest,
      announced_version: null
    })
  );
  expect(screen.getByTestId("seen").textContent).toBe(latest);
  expect(screen.getByRole("button", { name: "Klick 1" })).toBeTruthy();
});

it("loads an unavailable What's new state as null: unknown markers, not a first visit", async () => {
  backend.set(WHATS_NEW, failure);

  const { queryClient, refresh } = await renderApp();

  expect(queryClient.getQueryData(sessionKeys.whatsNew)).toBeNull();
  expect(screen.getByTestId("seen").textContent).toBe("unknown");

  // Any answer the backend gives later supersedes the fallback.
  backend.set(WHATS_NEW, ok({ seen_version: "1.0.0", announced_version: "1.0.0" }));
  await refresh();
  await waitFor(() => expect(screen.getByTestId("seen").textContent).toBe("1.0.0"));
});

// Why every sign-in continues in a new document (ContinueSignedIn): a client
// that outlives a client-side navigation still holds the previous user, and
// HydrationBoundary applies newer data for a query it already holds only
// after the first commit, so that commit (and its effects) shows the old one.
it("renders the cached previous user first when a new user's data hydrates into the same client", async () => {
  const sameClient = testQueryClient();
  sameClient.setQueryData(sessionKeys.me, signedIn.user);
  backend.set(ME, ok({ ...signedIn.user, username: "Bo Ek" }));

  await renderApp(sameClient);

  expect(contextValues[0]?.user.username).toBe("Anna Lind");
  await waitFor(() => expect(screen.getByTestId("user").textContent).toBe("Bo Ek"));
});
