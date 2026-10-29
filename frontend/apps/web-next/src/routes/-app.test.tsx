// @vitest-environment jsdom
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createTranslator } from "use-intl";
import { Profiler, useState, type ProfilerOnRenderCallback, type ReactNode } from "react";
import messages from "@/lib/i18n/messages/sv.json";
import { testAppContext } from "@/test/render";

const navigate = vi.hoisted(() => vi.fn());
vi.mock("@/lib/navigate-to", () => ({ navigateTo: navigate }));
// These features own polling/tour tests; this suite exercises the route and session boundary.
vi.mock("@/features/jobs/use-jobs", () => ({
  JobsProvider: ({ children }: { children: ReactNode }) => children
}));
vi.mock("@/features/whats-new/tour-provider", () => ({
  TourProvider: ({ children }: { children: ReactNode }) => children
}));
vi.mock("@/components/shell/notification-bells", () => ({ NotificationBells: () => null }));

const GENERATION = "Eneo-Session-Generation";
const context = testAppContext({ settings: { whats_new_enabled: false } });
let replies: Map<string, unknown>;
let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/does-not-exist");
  document.cookie = "eneo_sidenav_collapsed=; Path=/; Max-Age=0";
  replies = new Map<string, unknown>([
    ["/api/v1/users/me/", context.user],
    ["/api/v1/users/tenant/", context.tenant],
    ["/api/v1/settings/", context.settings],
    ["/api/v1/auth/federation-status", context.federationStatus],
    ["/api/v1/limits/", context.limits],
    ["/api/v1/whats-new/state/", { seen_version: null, announced_version: null }],
    ["/api/v1/spaces/", { items: [] }]
  ]);
  fetcher = vi.fn<typeof fetch>(async (input) => {
    const url = new URL(input instanceof Request ? input.url : String(input), window.location.href);
    const headers = new Headers({ "content-type": "application/json" });
    // Public discovery does not authenticate a session or emit its generation.
    if (url.pathname !== "/api/v1/auth/federation-status")
      headers.set(GENERATION, "document-session");
    if (url.pathname === "/api/v1/auth/session/")
      return new Response(null, { status: 204, headers });
    if (!replies.has(url.pathname)) throw new Error(`Unexpected request: ${url.pathname}`);
    const reply = await replies.get(url.pathname);
    return reply instanceof Response
      ? reply.clone()
      : new Response(JSON.stringify(reply), { headers });
  });
  vi.stubGlobal("fetch", fetcher);
  vi.doMock("@/lib/navigation", () => import("@/lib/navigation.tanstack"));
  vi.doMock("@/lib/link", () => import("@/lib/link.tanstack"));
  vi.doMock("@/lib/api/base", async () => ({
    ...(await import("@/lib/api/base.vite")),
    // Node's Request needs an absolute base; response/session middleware stays real.
    API_BASE: window.location.origin
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function createRouteRouter(path = "/does-not-exist") {
  window.history.replaceState({}, "", path);
  const { getQueryClient } = await import("@/lib/api/query");
  const queryClient = getQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  const { setRuntimeConfig } = await import("@/lib/runtime-config");
  setRuntimeConfig({
    version: "1.2.3",
    revision: "test",
    help_center_url: null,
    legacy_app_url: null,
    accessibility_statement_url: null,
    request_integration_form_url: null,
    mcp_app_content_origin: null,
    federation_enabled: false
  });
  const owner = await import("@/lib/api/refusal");
  await owner.initializeBrowserSession();
  const { createAppRouter } = await import("@/router");
  const { BootContext } = await import("@/boot-context");
  const router = createAppRouter(
    { queryClient, t: createTranslator({ locale: "sv", messages }) },
    { history: createMemoryHistory({ initialEntries: [path] }) }
  );
  return { router, queryClient, owner, BootContext };
}

async function renderRoute(
  path = "/does-not-exist",
  onRender: ProfilerOnRenderCallback = () => {}
) {
  const state = await createRouteRouter(path);
  const { router, BootContext } = state;
  render(
    <BootContext value={{ locale: "sv", messages, nonce: undefined }}>
      <Profiler id="app" onRender={onRender}>
        <RouterProvider router={router} />
      </Profiler>
    </BootContext>
  );
  await act(() => router.load());
  return state;
}

it("renders an authenticated unknown path inside the shared shell", async () => {
  await renderRoute();
  const heading = await screen.findByRole("heading", { name: messages.page_not_found });
  expect(heading.closest("main")?.id).toBe("main-content");
  expect(navigate).not.toHaveBeenCalled();
});

it("uses the stored collapsed preference on the first shell commit", async () => {
  document.cookie = "eneo_sidenav_collapsed=1; Path=/";
  const commits: string[] = [];
  await renderRoute(undefined, () => {
    const toggle = document.querySelector(
      'button[aria-label="Fäll ihop sidomenyn"], button[aria-label="Fäll ut sidomenyn"]'
    );
    if (toggle) commits.push(toggle.getAttribute("aria-expanded")!);
  });
  await screen.findByRole("button", { name: "Fäll ut sidomenyn" });
  expect(commits[0]).toBe("false");
});

it("redirects the root to the signed-in landing path", async () => {
  const { router } = await renderRoute("/");
  await screen.findByRole("heading", { name: messages.page_not_found });
  expect(router.state.location.pathname).toBe("/spaces/personal/chat");
  expect(document.getElementById("main-content")).not.toBeNull();
});

it("preloads the session using only GET requests", async () => {
  const { router } = await createRouteRouter();
  fetcher.mockClear();
  await router.preloadRoute({ to: "/$", params: { _splat: "another" } });
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(6));
  for (const [input, init] of fetcher.mock.calls) {
    expect(input instanceof Request ? input.method : (init?.method ?? "GET")).toBe("GET");
  }
  expect(navigate).not.toHaveBeenCalled();
});

it("starts the other five session resources together without blocking the route gate", async () => {
  const paths = [...replies.keys()].filter(
    (path) => path !== "/api/v1/users/me/" && path !== "/api/v1/spaces/"
  );
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  for (const path of paths) {
    const reply = replies.get(path);
    replies.set(
      path,
      pending.then(() => reply)
    );
  }
  await renderRoute();
  const requested = fetcher.mock.calls.map(
    ([input]) =>
      new URL(input instanceof Request ? input.url : String(input), window.location.href).pathname
  );
  expect(requested).toEqual(expect.arrayContaining(paths));
  expect(document.getElementById("main-content")).toBeNull();
  await act(async () => release());
  await screen.findByRole("heading", { name: messages.page_not_found });
});

it("leaves a me 401 to the single refusal owner and never renders the shell", async () => {
  replies.set(
    "/api/v1/users/me/",
    new Response(JSON.stringify({ message: "Unauthorized" }), {
      status: 401,
      headers: { [GENERATION]: "document-session", "content-type": "application/json" }
    })
  );
  await renderRoute();
  await waitFor(() =>
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/login?next=%2Fdoes-not-exist")
  );
  expect(document.getElementById("main-content")).toBeNull();
});

it("keeps page state mounted through marker changes and a failed session refresh", async () => {
  function StatefulPage() {
    const [count, setCount] = useState(0);
    return <button onClick={() => setCount(count + 1)}>Edited {count}</button>;
  }
  const { Route } = await import("./_app/$");
  Route.update({ component: StatefulPage });
  const { queryClient } = await renderRoute();
  const button = await screen.findByRole("button", { name: "Edited 0" });
  fireEvent.click(button);
  const main = button.closest("main");
  const { sessionKeys } = await import("@/lib/api/session");
  await act(async () => {
    queryClient.setQueryData(sessionKeys.whatsNew, { seen_version: "1", announced_version: "2" });
  });
  replies.set("/api/v1/users/tenant/", new Response("Unavailable", { status: 500 }));
  await act(() => queryClient.invalidateQueries({ queryKey: sessionKeys.tenant }));
  expect(queryClient.getQueryState(sessionKeys.tenant)?.status).toBe("error");
  expect(screen.getByRole("button", { name: "Edited 1" })).toBe(button);
  expect(button.closest("main")).toBe(main);
  expect(navigate).not.toHaveBeenCalled();
});

it("holds a cache-only navigation for the resume check and blocks a changed session", async () => {
  const { router, queryClient, owner } = await renderRoute();
  await screen.findByRole("heading", { name: messages.page_not_found });
  const { sessionKeys } = await import("@/lib/api/session");
  expect(queryClient.getQueryData(sessionKeys.me)).toBeDefined();
  let release!: (response: Response) => void;
  fetcher.mockImplementationOnce(
    () =>
      new Promise<Response>((resolve) => {
        release = resolve;
      })
  );
  const check = owner.checkBrowserSession().catch((error: unknown) => error);
  let finished = false;
  let navigation!: Promise<void>;
  await act(async () => {
    navigation = router.navigate({ to: "/$", params: { _splat: "another" } });
    void navigation.then(() => {
      finished = true;
    });
  });
  expect(router.state.status).toBe("pending");
  expect(finished).toBe(false);
  await act(async () => {
    release(new Response(null, { status: 204, headers: { [GENERATION]: "another-session" } }));
    await check;
    await navigation;
  });
  expect(navigate).toHaveBeenCalledExactlyOnceWith("/login?next=%2Fdoes-not-exist");
  expect(queryClient.getQueryData(sessionKeys.me)).toBeUndefined();
  expect(document.getElementById("main-content")).toBeNull();
});
