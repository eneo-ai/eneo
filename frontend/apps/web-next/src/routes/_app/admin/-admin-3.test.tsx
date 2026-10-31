// @vitest-environment jsdom
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { type ReactNode } from "react";
import { createTranslator } from "use-intl";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { testAppContext } from "@/test/render";

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
vi.mock("@/features/admin/help-assistants/help-assistants-page", () => ({
  HelpAssistantsPage: () => <h1>Helpers</h1>
}));

const GENERATION = "Eneo-Session-Generation";
const context = testAppContext({ permissions: ["admin"] });
let replies: Map<string, unknown>;
let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;

beforeEach(async () => {
  vi.resetModules();
  vi.doMock("@/features/admin/help-assistants/help-assistant-editor", async () => {
    const { useSpace } = await import("@/features/spaces/use-space");
    return {
      HelpAssistantEditor: ({
        assistantId,
        helperKind
      }: {
        assistantId: string;
        helperKind: string;
      }) => {
        const { space, routeId } = useSpace();
        return (
          <h1>
            Helper {helperKind}: {assistantId} in {routeId} ({space.id})
          </h1>
        );
      }
    };
  });
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
    ["/api/v1/admin/help-assistants/roles/", { items: [] }],
    ["/api/v1/admin/help-assistants/templates/", { items: [] }],
    [
      "/api/v1/admin/help-assistants/roles/prompt_guide/",
      { id: "role-1", kind: "prompt_guide", assistant_id: "helper-1" }
    ],
    ["/api/v1/assistants/helper-1/", { id: "helper-1" }],
    ["/api/v1/spaces/type/organization/", { id: "organization-space", organization: true }]
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
});

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
    { queryClient, t: createTranslator({ locale: "sv", messages }) },
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
    "Helpers",
    "admin_help_assistants_nav_label",
    ["/api/v1/admin/help-assistants/roles/", "/api/v1/admin/help-assistants/templates/"]
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

it("renders the installed helper inside the organization SpaceProvider", async () => {
  await renderRoute("/admin/help-assistants/prompt_guide");
  await screen.findByRole("heading", {
    name: "Helper prompt_guide: helper-1 in organization (organization-space)",
    level: 1
  });
  expect(document.title).toBe(`${messages.admin_help_assistants_nav_label} · Eneo`);
  expect(requestedPaths()).toContain("/api/v1/assistants/helper-1/");
  expect(requestedPaths()).toContain("/api/v1/spaces/type/organization/");
});

it("rejects an unknown helper kind as not-found without making an invalid API request", async () => {
  replies.set("/api/v1/admin/help-assistants/roles/unknown-kind/", failure(422));
  const { router } = await renderRoute("/admin/help-assistants/unknown-kind");
  await screen.findByRole("heading", { name: messages.page_not_found });
  expect(router.state.matches.some((match) => match.status === "notFound")).toBe(true);
  expect(requestedPaths()).not.toContain("/api/v1/admin/help-assistants/roles/unknown-kind/");
});

it("reports an uninstalled known helper as not-found before loading its editor data", async () => {
  replies.set("/api/v1/admin/help-assistants/roles/prompt_guide/", null);
  const { router } = await renderRoute("/admin/help-assistants/prompt_guide");
  await screen.findByRole("heading", { name: messages.page_not_found });
  expect(router.state.matches.some((match) => match.status === "notFound")).toBe(true);
  expect(requestedPaths()).toContain("/api/v1/admin/help-assistants/roles/prompt_guide/");
  expect(requestedPaths()).not.toContain("/api/v1/assistants/helper-1/");
  expect(requestedPaths()).not.toContain("/api/v1/spaces/type/organization/");
});

it("keeps a refused helper read with the route error boundary", async () => {
  replies.set("/api/v1/admin/help-assistants/roles/prompt_guide/", failure(403));
  const { router } = await renderRoute("/admin/help-assistants/prompt_guide");
  await waitFor(() =>
    expect(router.state.matches.some((match) => match.status === "error")).toBe(true)
  );
  expect(router.state.matches.some((match) => match.status === "notFound")).toBe(false);
  expect(requestedPaths()).not.toContain("/api/v1/spaces/type/organization/");
});

it("fails governance when a required read cannot refresh older cached data", async () => {
  replies.set("/api/v1/admin/governance-policy/", failure(500));
  const { router } = await renderRoute("/admin/personal-assistant", true);
  await waitFor(() =>
    expect(router.state.matches.some((match) => match.status === "error")).toBe(true)
  );
  expect(screen.queryByRole("heading", { name: "Governance" })).toBeNull();
});

it("keeps a required template-list failure with the route error boundary", async () => {
  replies.set("/api/v1/admin/templates/apps/", failure(500));
  const { router } = await renderRoute("/admin/templates");
  await waitFor(() =>
    expect(router.state.matches.some((match) => match.status === "error")).toBe(true)
  );
  expect(screen.queryByRole("heading", { name: "Templates" })).toBeNull();
});
