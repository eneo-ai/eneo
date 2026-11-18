// @vitest-environment jsdom
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { type ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { testAppContext } from "@/test/render";
import { testTranslator } from "@/test/i18n";

vi.unmock("@/lib/link");

vi.mock("@/features/jobs/use-jobs", () => ({
  JobsProvider: ({ children }: { children: ReactNode }) => children,
  useJobs: () => ({ trackJob: vi.fn() })
}));
vi.mock("@/features/whats-new/tour-provider", () => ({
  TourProvider: ({ children }: { children: ReactNode }) => children,
  useTour: () => ({ running: false, start: vi.fn() })
}));
vi.mock("@/components/shell/notification-bells", () => ({ NotificationBells: () => null }));
// The real router and data owners are exercised; feature suites own form behavior.
vi.mock("@/features/admin/templates/templates-page", () => ({
  TemplatesPage: () => <h1>Templates</h1>
}));
vi.mock("@/features/admin/prompt-library/prompt-library-page", () => ({
  PromptLibraryPage: () => <h1>Prompts</h1>
}));
vi.mock("@/features/admin/governance/governance-policy-page", () => ({
  GovernancePolicyPage: () => <h1>Governance</h1>
}));
vi.mock("@/features/admin/skills/admin-skills-page", () => ({
  AdminSkillsPage: () => <h1>Skills</h1>
}));
vi.mock("@/features/admin/helper-chat/helper-chat-settings-page", () => ({
  HelperChatSettingsPage: () => <h1>Helper</h1>
}));

const GENERATION = "Eneo-Session-Generation";
const context = testAppContext({ permissions: ["admin"], settings: { using_templates: true } });
let replies: Map<string, unknown>;
let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;

// The first load of the app's route graph takes seconds on a busy runner. File
// collection has no timeout, so pay it here; each beforeEach then only
// re-evaluates the graph for its fresh module registry.
await import("@/router");

beforeEach(async () => {
  vi.resetModules();
  HTMLElement.prototype.scrollTo = () => {};
  replies = new Map<string, unknown>([
    ["/api/v1/users/me/", context.user],
    ["/api/v1/users/tenant/", context.tenant],
    ["/api/v1/settings/", context.settings],
    ["/api/v1/auth/federation-status", context.federationStatus],
    ["/api/v1/limits/", context.limits],
    ["/api/v1/spaces/", { items: [] }],
    ["/api/v1/admin/templates/assistants/", { items: [] }],
    ["/api/v1/admin/templates/apps/", { items: [] }],
    ["/api/v1/admin/prompt-library/", { items: [] }],
    ["/api/v1/admin/governance-policy/", {}],
    ["/api/v1/ai-models/", {}],
    ["/api/v1/admin/model-providers/", []],
    ["/api/v1/mcp-servers/settings/", { items: [] }],
    ["/api/v1/settings/skills/runtime-policy", {}],
    [
      "/api/v1/settings/helper-chat-policy",
      { enabled: true, guidance: "", guidance_max_length: 4000, completion_model_id: null }
    ]
  ]);
  fetcher = vi.fn<typeof fetch>(async (input) => {
    const url = new URL(input instanceof Request ? input.url : String(input), window.location.href);
    const headers = new Headers({ "content-type": "application/json" });
    if (url.pathname !== "/api/v1/auth/federation-status")
      headers.set(GENERATION, "admin-route-session");
    if (url.pathname === "/api/v1/auth/session/")
      return new Response(null, { status: 204, headers });
    if (!replies.has(url.pathname)) throw new Error(`Unexpected request: ${url.pathname}`);
    const reply = await replies.get(url.pathname);
    return reply instanceof Response
      ? reply.clone()
      : new Response(JSON.stringify(reply), { headers });
  });
  vi.stubGlobal("fetch", fetcher);
  vi.doMock("@/lib/api/base", async () => ({
    ...(await vi.importActual<typeof import("@/lib/api/base")>("@/lib/api/base")),
    API_BASE: window.location.origin
  }));
  await import("@/router");
  // The first test of a file transforms the whole app graph, cold.
}, 30_000);

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function renderRoute(path: string, staleGovernance = false) {
  window.history.replaceState({}, "", path);
  const { getQueryClient } = await import("@/lib/api/query");
  const queryClient = getQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
  if (staleGovernance) queryClient.setQueryData(["admin-governance-policy"], {}, { updatedAt: 1 });
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
  const { initializeBrowserSession } = await import("@/lib/api/refusal");
  await initializeBrowserSession();
  const { createAppRouter } = await import("@/router");
  const { BootContext } = await import("@/boot-context");
  const router = createAppRouter(
    { queryClient, t: testTranslator() },
    { history: createMemoryHistory({ initialEntries: [path] }) }
  );
  render(
    <BootContext value={{ locale: "sv", messages, nonce: undefined }}>
      <RouterProvider router={router} />
    </BootContext>
  );
  await act(() => router.load());
  return { router, queryClient };
}

function requestedPaths() {
  return fetcher.mock.calls.map(
    ([input]) =>
      new URL(input instanceof Request ? input.url : String(input), window.location.href).pathname
  );
}

function failure(status: number) {
  return new Response("Unavailable", { status, headers: { [GENERATION]: "admin-route-session" } });
}

it.each([
  [
    "/admin/templates",
    "Templates",
    "templates",
    ["/api/v1/admin/templates/assistants/", "/api/v1/admin/templates/apps/"]
  ],
  ["/admin/prompt-library", "Prompts", "governance_tab_prompts", ["/api/v1/admin/prompt-library/"]],
  [
    "/admin/personal-assistant",
    "Governance",
    "governance_title",
    [
      "/api/v1/admin/governance-policy/",
      "/api/v1/ai-models/",
      "/api/v1/admin/model-providers/",
      "/api/v1/mcp-servers/settings/",
      "/api/v1/admin/prompt-library/",
      "/api/v1/settings/skills/runtime-policy"
    ]
  ],
  ["/admin/skills", "Skills", "admin_skills_page_title", []],
  [
    "/admin/help-assistants",
    "Helper",
    "admin_helper_title",
    ["/api/v1/settings/helper-chat-policy", "/api/v1/ai-models/"]
  ]
] as const)(
  "opens %s with its required data and title",
  async (path, heading, title, endpoints) => {
    await renderRoute(path);
    await screen.findByRole("heading", { name: heading, level: 1 });
    expect(document.title).toBe(`${messages[title]} · Eneo`);
    expect(requestedPaths()).toEqual(expect.arrayContaining([...endpoints]));
    expect(requestedPaths().filter((path) => path === "/api/v1/users/me/")).toHaveLength(1);
  }
);

it("leaves a failed read of the helper's settings to the page, which can retry it", async () => {
  replies.set("/api/v1/settings/helper-chat-policy", failure(500));
  const { router } = await renderRoute("/admin/help-assistants");
  await screen.findByRole("heading", { name: "Helper", level: 1 });
  expect(router.state.matches.some((match) => match.status === "error")).toBe(false);
  expect(requestedPaths()).toContain("/api/v1/settings/helper-chat-policy");
});

it.each(["prompt_guide", "unknown-kind"])(
  "answers not found at the old help assistant editor address %s without reading anything for it",
  async (kind) => {
    const { router } = await renderRoute(`/admin/help-assistants/${kind}`);
    await screen.findByRole("heading", { name: messages.page_not_found, level: 1 });
    expect(document.title).toBe(`${messages.page_not_found} · Eneo`);
    expect(router.state.matches.at(-1)?.routeId).toBe("/_app/$");
    expect(screen.queryByRole("heading", { name: "Helper", level: 1 })).toBeNull();
    expect(
      requestedPaths().filter(
        (path) =>
          path.startsWith("/api/v1/admin/help-assistants/") ||
          path.startsWith("/api/v1/assistants/") ||
          path === "/api/v1/settings/helper-chat-policy"
      )
    ).toEqual([]);
  }
);

it("fails governance when a required read cannot refresh older cached data", async () => {
  replies.set("/api/v1/admin/governance-policy/", failure(500));
  const { router } = await renderRoute("/admin/personal-assistant", true);
  await waitFor(() =>
    expect(router.state.matches.some((match) => match.status === "error")).toBe(true)
  );
  expect(screen.queryByRole("heading", { name: "Governance" })).toBeNull();
});

it("sends /admin/templates to /admin before anything renders while the organisation does not use templates", async () => {
  replies.set("/api/v1/settings/", { ...context.settings, using_templates: false });
  const { router } = await renderRoute("/admin/templates");
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin"));
  expect(screen.queryByRole("heading", { name: "Templates", level: 1 })).toBeNull();
  expect(requestedPaths()).not.toContain("/api/v1/admin/templates/assistants/");
  expect(requestedPaths()).not.toContain("/api/v1/admin/templates/apps/");
});

it("keeps a required template-list failure with the route error boundary", async () => {
  replies.set("/api/v1/admin/templates/apps/", failure(500));
  const { router } = await renderRoute("/admin/templates");
  await waitFor(() =>
    expect(router.state.matches.some((match) => match.status === "error")).toBe(true)
  );
  expect(screen.queryByRole("heading", { name: "Templates" })).toBeNull();
});
