// @vitest-environment jsdom
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createTranslator } from "use-intl";
import {
  Profiler,
  useEffect,
  useState,
  type ComponentProps,
  type ProfilerOnRenderCallback,
  type ReactNode
} from "react";
import type { ChatPage } from "@/features/chat/chat-page";
import messages from "@/lib/i18n/messages/sv.json";
import { testAppContext } from "@/test/render";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { setViewport } from "@/test/setup-dom";

const navigate = vi.hoisted(() => vi.fn());
vi.mock("@/lib/navigate-to", () => ({ navigateTo: navigate }));
// These features own polling/tour tests; this suite exercises the route and session boundary.
vi.mock("@/features/jobs/use-jobs", () => ({
  JobsProvider: ({ children }: { children: ReactNode }) => children,
  useJobs: () => ({ trackJob: vi.fn() })
}));
vi.mock("@/features/whats-new/tour-provider", () => ({
  TourProvider: ({ children }: { children: ReactNode }) => children,
  useTour: () => ({ running: false, start: vi.fn() })
}));
vi.mock("@/components/shell/notification-bells", () => ({ NotificationBells: () => null }));

const GENERATION = "Eneo-Session-Generation";
const context = testAppContext({ settings: { whats_new_enabled: false } });
let replies: Map<string, unknown>;
let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  // The router scrolls the main panel; jsdom has no element scrolling implementation.
  HTMLElement.prototype.scrollTo = () => {};
  window.history.replaceState({}, "", "/does-not-exist");
  document.cookie = "eneo_sidenav_collapsed=; Path=/; Max-Age=0";
  replies = new Map<string, unknown>([
    ["/api/v1/users/me/", context.user],
    ["/api/v1/users/tenant/", context.tenant],
    ["/api/v1/settings/", context.settings],
    ["/api/v1/auth/federation-status", context.federationStatus],
    ["/api/v1/limits/", context.limits],
    ["/api/v1/whats-new/state/", { seen_version: null, announced_version: null }],
    ["/api/v1/spaces/", { items: [] }],
    ["/api/v1/spaces/type/personal/", makeSpace({ overrides: { personal: true } })]
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
  // Chat streaming has its own feature and browser tests; keep its state observable here.
  vi.doMock("@/features/chat/chat-page", async () => {
    const { replaceUrl } = await import("@/lib/navigation");
    return {
      ChatPage: ({
        sessionId,
        buildSessionUrl
      }: Required<Pick<ComponentProps<typeof ChatPage>, "sessionId" | "buildSessionUrl">>) => {
        const [answers, setAnswers] = useState(0);
        const [draft, setDraft] = useState("");
        return (
          <>
            <input
              aria-label="Draft"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
            <button
              onClick={() => {
                setAnswers((count) => count + 1);
                replaceUrl(buildSessionUrl("saved-session"));
              }}
            >
              Chat {sessionId ?? "new"}: {answers}
            </button>
          </>
        );
      }
    };
  });
  vi.doMock("@/lib/api/base", async () => ({
    ...(await import("@/lib/api/base.vite")),
    // Node's Request needs an absolute base; response/session middleware stays real.
    API_BASE: window.location.origin
  }));
});

it("opens the dashboard catalog with its title and existing app links", async () => {
  replies.set("/api/v1/dashboard/", {
    spaces: { items: [makeSpace({ apps: [{ id: "app-1", name: "Avtalsanalys" }] })] }
  });
  await renderRoute("/dashboard");
  await screen.findByRole("heading", { name: messages.assistants, level: 1 });
  await waitFor(() => expect(document.title).toBe(`${messages.assistants} · Eneo`));
  expect(screen.getByRole("link", { name: /Avtalsanalys/ }).getAttribute("href")).toBe(
    "/dashboard/app/app-1"
  );
});

it("shows a failed dashboard load and recovers through the route retry", async () => {
  replies.set(
    "/api/v1/dashboard/",
    new Response("Unavailable", { status: 500, headers: { [GENERATION]: "document-session" } })
  );
  await renderRoute("/dashboard");
  await screen.findByRole("heading", { name: messages.something_went_wrong });
  expect(screen.queryByRole("heading", { name: messages.page_not_found })).toBeNull();
  replies.set("/api/v1/dashboard/", { spaces: { items: [] } });
  fireEvent.click(screen.getByRole("button", { name: messages.try_again }));
  await screen.findByRole("heading", { name: messages.assistants, level: 1 });
});

it.each(["", "/session-1"])(
  "opens dashboard chat%s and preserves chat state when a session is saved",
  async (suffix) => {
    replies.set("/api/v1/assistants/assistant-1/", {
      id: "assistant-1",
      name: "Upphandlingsassistenten",
      groups: [],
      websites: [],
      integration_knowledge_list: [],
      mcp_servers: [],
      enabled_capabilities: [],
      available_capabilities: []
    });
    const { router } = await renderRoute(
      `/dashboard/assistant-1${suffix}`,
      undefined,
      ({ queryClient }) => {
        queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
      }
    );
    const button = await screen.findByRole("button", {
      name: `Chat ${suffix ? "session-1" : "new"}: 0`
    });
    fireEvent.click(button);
    await screen.findByRole("button", { name: "Chat saved-session: 1" });
    expect(router.state.location.pathname).toBe("/dashboard/assistant-1/saved-session");
    expect(
      requestedPaths().filter((path) => path === "/api/v1/assistants/assistant-1/")
    ).toHaveLength(1);
    expect(document.title).toBe("Eneo");
  }
);

it("clears the draft when switching to another cached dashboard assistant", async () => {
  const { router } = await renderRoute("/dashboard/assistant-1", undefined, ({ queryClient }) => {
    queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
    for (const id of ["assistant-1", "assistant-2"]) {
      queryClient.setQueryData(["assistants", id], {
        id,
        name: id,
        groups: [],
        websites: [],
        integration_knowledge_list: [],
        mcp_servers: [],
        enabled_capabilities: [],
        available_capabilities: []
      });
    }
  });
  const draft = await screen.findByRole("textbox", { name: "Draft" });
  fireEvent.change(draft, { target: { value: "Question for the first assistant" } });
  await act(() => router.navigate({ href: "/dashboard/assistant-2" }));
  expect(screen.getByRole<HTMLInputElement>("textbox", { name: "Draft" }).value).toBe("");
  expect(requestedPaths().some((path) => path.startsWith("/api/v1/assistants/"))).toBe(false);
});

it("rejects extra dashboard session segments without loading an assistant", async () => {
  await renderRoute("/dashboard/assistant-1/session-1/extra");
  await screen.findByRole("heading", { name: messages.page_not_found });
  expect(requestedPaths().some((path) => path.startsWith("/api/v1/assistants/"))).toBe(false);
});

const dashboardApp = {
  id: "app-1",
  name: "Avtalsanalys",
  input_fields: [],
  completion_model: { id: "model-1", name: "Testmodell" }
};

it("clears an app's run input when navigating to a different app", async () => {
  for (const id of ["app-1", "app-2"]) {
    replies.set(`/api/v1/apps/${id}/`, {
      ...dashboardApp,
      id,
      name: id,
      input_fields: [{ type: "text-field" }]
    });
    replies.set(`/api/v1/apps/${id}/runs/`, { items: [] });
  }
  const { router } = await renderRoute("/dashboard/app/app-1");
  const input = await screen.findByRole("textbox", { name: messages.enter_your_question_here });
  fireEvent.change(input, { target: { value: "Fråga till första appen" } });
  await act(() => router.navigate({ href: "/dashboard/app/app-2" }));
  await screen.findByRole("heading", { name: "app-2", level: 1 });
  expect(
    screen.getByRole<HTMLTextAreaElement>("textbox", { name: messages.enter_your_question_here })
      .value
  ).toBe("");
});

it("opens a dashboard app and derives its tab from the URL without reloading its guard", async () => {
  replies.set("/api/v1/apps/app-1/", dashboardApp);
  replies.set("/api/v1/apps/app-1/runs/", { items: [] });
  const { router } = await renderRoute(
    "/dashboard/app/app-1?tab=results",
    undefined,
    ({ queryClient }) => {
      queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
    }
  );
  await screen.findByRole("heading", { name: dashboardApp.name, level: 1 });
  expect(screen.getByRole("tab", { name: messages.results }).getAttribute("aria-selected")).toBe(
    "true"
  );
  expect(document.title).toBe("Avtalsanalys · Eneo");
  await act(() => router.navigate({ href: "/dashboard/app/app-1?tab=run" }));
  await waitFor(() =>
    expect(screen.getByRole("tab", { name: messages.run }).getAttribute("aria-selected")).toBe(
      "true"
    )
  );
  expect(requestedPaths().filter((path) => path === "/api/v1/apps/app-1/")).toHaveLength(1);
});

it("opens a dashboard result with the app title and its back and new-run links", async () => {
  setViewport("desktop");
  replies.set("/api/v1/apps/app-1/", dashboardApp);
  replies.set("/api/v1/app-runs/run-1/", {
    id: "run-1",
    status: "complete",
    input: { text: "Avtalsfråga", files: [] },
    output: "Svar på avtalsfrågan",
    finished_at: "2026-10-30T08:00:00Z",
    user: { id: "user-1", email: "test@example.se" },
    skill_provenance: []
  });
  await renderRoute("/dashboard/app/app-1/results/run-1");
  await screen.findByText("Svar på avtalsfrågan");
  expect(document.title).toBe("Resultat från Avtalsanalys · Eneo");
  expect(screen.getByRole("link", { name: messages.back }).getAttribute("href")).toBe(
    "/dashboard/app/app-1"
  );
  expect(screen.getByRole("link", { name: messages.new_run }).getAttribute("href")).toBe(
    "/dashboard/app/app-1"
  );
});

it.each(["/dashboard/app/missing", "/dashboard/app/app-1/results/missing"])(
  "maps a missing dashboard resource to not-found: %s",
  async (path) => {
    replies.set("/api/v1/apps/app-1/", dashboardApp);
    replies.set("/api/v1/apps/missing/runs/", { items: [] });
    for (const apiPath of ["/api/v1/apps/missing/", "/api/v1/app-runs/missing/"]) {
      replies.set(
        apiPath,
        new Response("Missing", { status: 404, headers: { [GENERATION]: "document-session" } })
      );
    }
    const { router } = await renderRoute(path);
    await screen.findByRole("heading", { name: messages.page_not_found });
    expect(router.state.matches.some((match) => match.status === "notFound")).toBe(true);
  }
);

it("redirects disabled what's new through the existing root landing route", async () => {
  const { router } = await renderRoute("/whats-new");
  await waitFor(() => expect(router.state.location.pathname).toBe("/spaces/personal/chat"));
  expect(screen.queryByRole("heading", { name: messages.whats_new })).toBeNull();
});

it("opens enabled what's new using the shared settings and marker owners", async () => {
  replies.set("/api/v1/settings/", { ...context.settings, whats_new_enabled: true });
  replies.set("/api/v1/whats-new/seen/", { seen_version: "0.0.0" });
  await renderRoute("/whats-new");
  await screen.findByRole("heading", { name: messages.whats_new, level: 1 });
  expect(document.title).toBe(`${messages.whats_new} · Eneo`);
  expect(requestedPaths().filter((path) => path === "/api/v1/settings/")).toHaveLength(1);
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
  onRender: ProfilerOnRenderCallback = () => {},
  prepare?: (state: Awaited<ReturnType<typeof createRouteRouter>>) => void
) {
  const state = await createRouteRouter(path);
  prepare?.(state);
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

it("opens the Skill reference editor in the personal space", async () => {
  await renderRoute("/spaces/personal/skills/new");
  await screen.findByRole("textbox", { name: messages.skills_instructions_label });
  expect(screen.getByRole("button", { name: messages.skills_reference_insert })).toBeTruthy();
  await waitFor(() =>
    expect(document.title).toBe(
      `${messages.skills_library_new_heading} · ${messages.personal} · Eneo`
    )
  );
});

it.each([
  { permissions: ["read"] as const, destination: "/spaces/personal/skills" },
  { permissions: [] as const, destination: "/spaces/personal/overview" }
])(
  "keeps Skill creation behind the space permission: $destination",
  async ({ permissions, destination }) => {
    replies.set(
      "/api/v1/spaces/type/personal/",
      makeSpace({ skillPermissions: [...permissions], overrides: { personal: true } })
    );
    replies.set("/api/v1/spaces/space-1/skills/", { items: [], next_cursor: null });
    const { router } = await renderRoute("/spaces/personal/skills/new");
    await waitFor(() => expect(router.state.location.pathname).toBe(destination));
    expect(screen.queryByRole("textbox", { name: messages.skills_instructions_label })).toBeNull();
  }
);

it("does not open the organization Skill editor for a non-admin", async () => {
  const { router } = await renderRoute("/spaces/organization/skills/new");
  await waitFor(() => expect(router.state.location.pathname).toBe("/spaces/personal/chat"));
  expect(requestedPaths()).not.toContain("/api/v1/spaces/type/organization/");
  expect(screen.queryByRole("textbox", { name: messages.skills_instructions_label })).toBeNull();
});

it("renders the spaces list with its document title and keeps list distinct from a space ID", async () => {
  await renderRoute("/spaces/list");
  await screen.findByRole("heading", { name: messages.spaces, level: 1 });
  await waitFor(() => expect(document.title).toBe(`${messages.spaces} · Eneo`));
  expect(requestedPaths()).not.toContain("/api/v1/spaces/list/");
});

it("keeps a cached spaces list visible when its background refresh fails", async () => {
  replies.set(
    "/api/v1/spaces/",
    new Response("Unavailable", { status: 503, headers: { [GENERATION]: "document-session" } })
  );
  const { queryClient } = await renderRoute("/spaces/list", undefined, ({ queryClient }) => {
    queryClient.setQueryData(["spaces"], []);
  });
  await screen.findByRole("heading", { name: messages.spaces, level: 1 });
  await waitFor(() => expect(queryClient.getQueryState(["spaces"])?.status).toBe("error"));
  expect(screen.getByRole("heading", { name: messages.spaces, level: 1 })).toBeTruthy();
});

function requestedPaths() {
  return fetcher.mock.calls.map(
    ([input]) =>
      new URL(input instanceof Request ? input.url : String(input), window.location.href).pathname
  );
}

it("renders the existing account profile and local password form in the Vite shell", async () => {
  setViewport("desktop");
  replies.set("/api/v1/users/me/", {
    ...context.user,
    password_change: {
      source: "eneo",
      policy: {
        min_length: 12,
        max_bytes: 72,
        requires_uppercase: false,
        requires_lowercase: false,
        requires_number: false,
        requires_symbol: false
      }
    }
  });
  await renderRoute("/account");
  await screen.findByRole("heading", { name: messages.my_account, level: 1 });
  expect(screen.getByLabelText(messages.current_password, { selector: "input" })).toBeTruthy();
  expect(screen.getByLabelText(messages.new_password, { selector: "input" })).toBeTruthy();
  expect(screen.getByRole("button", { name: messages.save })).toBeTruthy();
  await waitFor(() => expect(document.title).toBe(`${messages.my_account} · Eneo`));
});

it.each([false, true])(
  "shows not-found for a missing space, including an invalidated cached copy (%s)",
  async (cached) => {
    replies.set(
      "/api/v1/spaces/missing/",
      new Response(JSON.stringify({ message: "Not found" }), {
        status: 404,
        headers: { [GENERATION]: "document-session", "content-type": "application/json" }
      })
    );
    const { router } = await renderRoute("/spaces/missing", undefined, ({ queryClient }) => {
      if (cached) {
        queryClient.setQueryData(["spaces", "missing"], makeSpace());
        void queryClient.invalidateQueries({ queryKey: ["spaces", "missing"] });
      }
    });
    await screen.findByRole("heading", { name: messages.page_not_found });
    expect(router.state.location.pathname).toBe("/spaces/missing/overview");
    expect(
      router.state.matches.find((match) => match.routeId === "/_app/spaces/$spaceId")?.status
    ).toBe("notFound");
    expect(screen.queryAllByText("Upphandling")).toHaveLength(0);
    expect(requestedPaths().filter((path) => path === "/api/v1/spaces/missing/")).toHaveLength(1);
    expect(navigate).not.toHaveBeenCalled();
  }
);

it("uses a fresh space already in the query cache and sets the layout title", async () => {
  const { router } = await renderRoute("/spaces/space-1", undefined, ({ queryClient }) => {
    queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
    queryClient.setQueryData(["spaces", "space-1"], makeSpace());
  });
  const layout = router.state.matches.find((match) => match.routeId === "/_app/spaces/$spaceId");
  expect(layout?.meta).toContainEqual({ title: "Upphandling · Eneo" });
  await waitFor(() => expect(document.title).toBe("Upphandling · Eneo"));
  expect(requestedPaths()).not.toContain("/api/v1/spaces/space-1/");
});

it("redirects a non-admin organization child route before requesting the organization space", async () => {
  const { router } = await renderRoute("/spaces/organization/knowledge");
  await waitFor(() => expect(router.state.location.pathname).toBe("/spaces/personal/chat"));
  expect(requestedPaths()).not.toContain("/api/v1/spaces/type/organization/");
});

it("lets an administrator load the organization space", async () => {
  replies.set("/api/v1/users/me/", testAppContext({ permissions: ["admin"] }).user);
  replies.set(
    "/api/v1/spaces/type/organization/",
    makeSpace({ overrides: { organization: true } })
  );
  const { router } = await renderRoute("/spaces/organization");
  const layout = router.state.matches.find((match) => match.routeId === "/_app/spaces/$spaceId");
  expect(layout?.loaderData).toMatchObject({ organization: true });
  expect(layout?.meta).toContainEqual({ title: `${messages.organization} · Eneo` });
  expect(
    requestedPaths().filter((path) => path === "/api/v1/spaces/type/organization/")
  ).toHaveLength(1);
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
  await screen.findByRole("button", { name: "Chat new: 0" });
  expect(router.state.location.pathname).toBe("/spaces/personal/chat");
  expect(document.getElementById("main-content")).not.toBeNull();
});

it("redirects the spaces index to its list without treating it as a space ID", async () => {
  const { router } = await renderRoute("/spaces");
  await screen.findByRole("heading", { name: messages.spaces, level: 1 });
  expect(router.state.location.pathname).toBe("/spaces/list");
  expect(requestedPaths()).not.toContain("/api/v1/spaces/list/");
});

it.each([
  ["personal", "/spaces/personal/chat", `${messages.personal} · Eneo`],
  ["space-1", "/spaces/space-1/overview", "Upphandling · Eneo"]
])(
  "redirects the %s space index and inherits its space title",
  async (spaceId, destination, title) => {
    replies.set("/api/v1/spaces/space-1/", makeSpace());
    const { router } = await renderRoute(`/spaces/${spaceId}`);
    await waitFor(() => expect(router.state.location.pathname).toBe(destination));
    await waitFor(() => expect(document.title).toBe(title));
    expect(screen.queryByRole("heading", { name: messages.page_not_found })).toBeNull();
  }
);

it("keeps the space frame mounted when switching from overview to members", async () => {
  const mounts = vi.fn();
  const unmounts = vi.fn();
  vi.doMock("@/features/spaces/frame/space-frame", async (importOriginal) => {
    const { SpaceFrame } =
      await importOriginal<typeof import("@/features/spaces/frame/space-frame")>();
    return {
      SpaceFrame: ({ children }: { children: ReactNode }) => {
        useEffect(() => {
          mounts();
          return unmounts;
        }, []);
        return <SpaceFrame>{children}</SpaceFrame>;
      }
    };
  });
  replies.set("/api/v1/spaces/space-1/", makeSpace());
  try {
    const { router } = await renderRoute("/spaces/space-1/overview");
    await waitFor(() => expect(mounts).toHaveBeenCalledTimes(1));
    await act(() => router.navigate({ href: "/spaces/space-1/members" }));
    await screen.findByRole("heading", { name: messages.members });
    await waitFor(() => expect(document.title).toBe(`${messages.members} · Upphandling · Eneo`));
    expect(mounts).toHaveBeenCalledTimes(1);
    expect(unmounts).not.toHaveBeenCalled();
  } finally {
    vi.doUnmock("@/features/spaces/frame/space-frame");
  }
});

it("preserves chat state when its saved session updates the URL without another space read", async () => {
  const { router } = await renderRoute("/spaces/personal/chat", undefined, ({ queryClient }) => {
    queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
  });
  const chat = await screen.findByRole("button", { name: "Chat new: 0" });
  const initialReads = requestedPaths().filter(
    (path) => path === "/api/v1/spaces/type/personal/"
  ).length;
  fireEvent.click(chat);
  await waitFor(() =>
    expect(router.state.location.search).toMatchObject({ session_id: "saved-session" })
  );
  expect(await screen.findByRole("button", { name: "Chat saved-session: 1" })).toBe(chat);
  expect(requestedPaths().filter((path) => path === "/api/v1/spaces/type/personal/")).toHaveLength(
    initialReads
  );
});

it("flushes a settings draft to its original space and opens the next space with its own values", async () => {
  const first = makeSpace();
  const second = makeSpace({ overrides: { id: "space-2", name: "Personalfrågor" } });
  replies.set("/api/v1/spaces/space-1/", first);
  replies.set("/api/v1/spaces/space-2/", second);
  replies.set("/api/v1/security-classifications/", {
    security_enabled: false,
    security_classifications: []
  });
  replies.set("/api/v1/ai-models/", {
    completion_models: [],
    embedding_models: [],
    transcription_models: []
  });
  replies.set("/api/v1/mcp-servers/settings/", { items: [] });
  replies.set("/api/v1/api-keys/notification-subscriptions", { items: [] });
  replies.set("/api/v1/api-keys", { items: [], total_count: 0, next_cursor: null });
  const read = fetcher.getMockImplementation()!;
  const writes: { path: string; body: unknown }[] = [];
  fetcher.mockImplementation(async (input, init) => {
    if ((input instanceof Request ? input.method : init?.method) !== "PATCH")
      return read(input, init);
    const request = new Request(input, init);
    const path = new URL(request.url).pathname;
    const body: unknown = await request.json();
    writes.push({ path, body });
    return new Response(JSON.stringify({ ...first, name: "Uppdaterat namn" }), {
      headers: { "content-type": "application/json", [GENERATION]: "document-session" }
    });
  });
  const { router } = await renderRoute("/spaces/space-1/settings");
  const name = await screen.findByLabelText<HTMLInputElement>(messages.name, { selector: "input" });
  fireEvent.change(name, { target: { value: "Uppdaterat namn" } });
  await act(() => router.navigate({ href: "/spaces/space-1/settings?section=models" }));
  expect(screen.getByLabelText(messages.name, { selector: "input" })).toBe(name);
  expect(name.value).toBe("Uppdaterat namn");
  expect(writes).toHaveLength(0);
  await act(() => router.navigate({ href: "/spaces/space-2/settings" }));
  await waitFor(() =>
    expect(
      screen.getByLabelText<HTMLInputElement>(messages.name, { selector: "input" }).value
    ).toBe(second.name)
  );
  await waitFor(() =>
    expect(writes).toEqual([{ path: "/api/v1/spaces/space-1/", body: { name: "Uppdaterat namn" } }])
  );
  expect(screen.getByLabelText(messages.name, { selector: "input" })).not.toBe(name);
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

it("waits for a fresh existence check before re-entering a cached space route", async () => {
  replies.set("/api/v1/spaces/space-1/", makeSpace());
  const { router, queryClient } = await renderRoute(
    "/spaces/space-1",
    undefined,
    ({ queryClient }) => {
      queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
    }
  );
  expect(
    router.state.matches.find((match) => match.routeId === "/_app/spaces/$spaceId")?.status
  ).toBe("success");
  await act(() => router.navigate({ to: "/account" }));
  await screen.findByRole("heading", { name: messages.my_account, level: 1 });
  await queryClient.invalidateQueries({ queryKey: ["spaces", "space-1"], refetchType: "none" });
  let release!: (response: Response) => void;
  replies.set(
    "/api/v1/spaces/space-1/",
    new Promise<Response>((resolve) => {
      release = resolve;
    })
  );
  const previousReads = requestedPaths().filter(
    (path) => path === "/api/v1/spaces/space-1/"
  ).length;
  let navigation!: Promise<void>;
  await act(async () => {
    navigation = router.navigate({ to: "/spaces/$spaceId", params: { spaceId: "space-1" } });
  });
  try {
    await waitFor(() =>
      expect(requestedPaths().filter((path) => path === "/api/v1/spaces/space-1/")).toHaveLength(
        previousReads + 1
      )
    );
    expect(router.state.status).toBe("pending");
    expect(screen.queryAllByText("Upphandling")).toHaveLength(0);
  } finally {
    await act(async () => {
      release(
        new Response(JSON.stringify({ message: "Not found" }), {
          status: 404,
          headers: { [GENERATION]: "document-session", "content-type": "application/json" }
        })
      );
      await navigation;
    });
  }
  expect(
    router.state.matches.find((match) => match.routeId === "/_app/spaces/$spaceId")?.status
  ).toBe("notFound");
  expect(screen.queryAllByText("Upphandling")).toHaveLength(0);
  expect(screen.getByRole("heading", { name: messages.page_not_found })).toBeTruthy();
});

it("starts the other five session resources together without blocking the route gate", async () => {
  const paths = [...replies.keys()].filter(
    (path) => path !== "/api/v1/users/me/" && !path.startsWith("/api/v1/spaces/")
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

it.each([
  ["appearance", "account_appearance_language", "/account"],
  ["copy-format", "account_copy_format", "/account"],
  ["password", "change_password", "/account"],
  ["api-keys", "my_api_keys", "/account/api-keys"],
  ["integrations", "my_integrations", "/account/integrations"]
] as const)(
  "renders account/%s with its title and one current account link",
  async (page, titleKey, currentHref) => {
    setViewport("desktop");
    replies.set("/api/v1/users/me/", {
      ...context.user,
      password_change: {
        source: "eneo",
        policy: {
          min_length: 12,
          max_bytes: 72,
          requires_uppercase: false,
          requires_lowercase: false,
          requires_number: false,
          requires_symbol: false
        }
      }
    });
    replies.set("/api/v1/integrations/me/", { items: [] });
    replies.set("/api/v1/api-keys", { items: [], total_count: 0, next_cursor: null });
    replies.set("/api/v1/api-keys/notification-preferences", {
      enabled: false,
      days_before_expiry: [7],
      auto_follow_published_assistants: false
    });
    await renderRoute(`/account/${page}`);
    await waitFor(() => expect(document.title).toBe(`${messages[titleKey]} · Eneo`));
    const navigation = screen.getByRole("navigation", { name: messages.shell_account_nav_label });
    const current = navigation.querySelectorAll('a[aria-current="true"]');
    expect(current).toHaveLength(1);
    expect(current[0]?.getAttribute("href")).toBe(currentHref);
    switch (page) {
      case "appearance":
        await screen.findByRole("radiogroup", { name: messages.theme });
        break;
      case "copy-format":
        await screen.findByRole("radio", { name: messages.copy_format_markdown });
        break;
      case "password":
        await screen.findByLabelText(messages.current_password, { selector: "input" });
        expect(screen.getByRole("button", { name: messages.save })).toBeTruthy();
        break;
      case "api-keys":
        await screen.findByRole("heading", { name: messages.api_keys_no_keys });
        break;
      case "integrations":
        await screen.findByText(messages.no_integrations_enabled);
        break;
    }
  }
);

it("returns a signed-out account visit to login with its destination preserved", async () => {
  replies.set(
    "/api/v1/users/me/",
    new Response(JSON.stringify({ message: "Unauthorized" }), {
      status: 401,
      headers: { [GENERATION]: "document-session", "content-type": "application/json" }
    })
  );
  await renderRoute("/account");
  await waitFor(() => expect(navigate).toHaveBeenCalledExactlyOnceWith("/login?next=%2Faccount"));
  expect(document.getElementById("main-content")).toBeNull();
});
