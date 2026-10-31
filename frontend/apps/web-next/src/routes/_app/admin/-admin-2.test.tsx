// @vitest-environment jsdom
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { createTranslator } from "use-intl";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { testAppContext } from "@/test/render";

vi.mock("@/features/jobs/use-jobs", () => ({
  JobsProvider: ({ children }: { children: ReactNode }) => children,
  useJobs: () => ({ trackJob: vi.fn() })
}));
vi.mock("@/features/whats-new/tour-provider", () => ({
  TourProvider: ({ children }: { children: ReactNode }) => children,
  useTour: () => ({ running: false, start: vi.fn() })
}));
vi.mock("@/components/shell/notification-bells", () => ({ NotificationBells: () => null }));
// Feature suites own the forms; these probes expose route data, titles and identity.
vi.mock("@/features/admin/models/models-page", () => ({ ModelsPage: () => <h1>Models</h1> }));
vi.mock("@/features/admin/security-classifications/classifications-page", () => ({
  SecurityClassificationsPage: () => <h1>Classifications</h1>
}));
vi.mock("@/features/admin/tools/tools-page", () => ({
  ToolsPage: ({ tab }: { tab: string }) => <h1>Tools {tab}</h1>
}));
vi.mock("@/features/admin/integrations/admin-integrations-page", () => ({
  AdminIntegrationsPage: () => <h1>Integrations</h1>
}));
vi.mock("@/features/admin/modules/modules-page", () => ({
  ModulesPage: ({ title }: { title: string }) => <h1>{title}</h1>
}));
vi.mock("@/features/admin/insights/insights-page", () => ({
  InsightsPage: () => <h1>Insights</h1>
}));
vi.mock("@/features/admin/insights/assistant-insights-page", () => ({
  AssistantInsightsPage: ({ assistantId }: { assistantId: string }) => (
    <h1>Insights {assistantId}</h1>
  )
}));
vi.mock("@/features/admin/overview/overview-page", () => ({
  AdminOverviewPage: () => <h1>Administration</h1>
}));
vi.mock("@/features/admin/mcp/detail/mcp-server-detail", () => ({
  McpServerDetail: ({ serverId, initialTab }: { serverId: string; initialTab?: string }) => {
    const [draft, setDraft] = useState("");
    return (
      <>
        <h1>
          MCP {serverId}: {initialTab ?? "overview"}
        </h1>
        <input aria-label="Server draft" value={draft} onChange={(e) => setDraft(e.target.value)} />
      </>
    );
  }
}));

const GENERATION = "Eneo-Session-Generation";
const context = testAppContext({ permissions: ["admin", "modules"] });
let replies: Map<string, unknown>;
let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;

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
    [
      "/api/v1/security-classifications/",
      { security_enabled: false, security_classifications: [] }
    ],
    ["/api/v1/ai-models/", {}],
    ["/api/v1/admin/model-providers/", []],
    ["/api/v1/admin/model-providers/capabilities/", {}],
    ["/api/v1/mcp-servers/settings/", { items: [{ id: "server-1" }] }],
    ["/api/v1/mcp-servers/server-1/tools/", { items: [] }],
    ["/api/v1/mcp-servers/bundled/", { items: [], count: 0, runtime: null }],
    ["/api/v1/integrations/tenant/", { items: [] }],
    ["/api/v1/analysis/counts/", {}],
    ["/api/v1/assistants/assistant-1/", { id: "assistant-1" }]
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
  vi.doMock("@/lib/navigation", () => import("@/lib/navigation.tanstack"));
  vi.doMock("@/lib/link", () => import("@/lib/link.tanstack"));
  vi.doMock("@/lib/api/base", async () => ({
    ...(await import("@/lib/api/base.vite")),
    API_BASE: window.location.origin
  }));
  await import("@/router");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function renderRoute(path: string, staleModels = false) {
  window.history.replaceState({}, "", path);
  const { getQueryClient } = await import("@/lib/api/query");
  const queryClient = getQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
  if (staleModels) queryClient.setQueryData(["admin-models"], {}, { updatedAt: 1 });
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
  ["/admin/models", "Models", "models", "/api/v1/ai-models/"],
  [
    "/admin/security-classifications",
    "Classifications",
    "security_classifications",
    "/api/v1/security-classifications/"
  ],
  ["/admin/tools", "Tools functions", "tools", "/api/v1/mcp-servers/settings/"],
  ["/admin/integrations", "Integrations", "integrations", "/api/v1/integrations/tenant/"],
  ["/admin/modules", messages.module_admin_title, "module_admin_title", "/api/v1/users/me/"],
  ["/admin/insights", "Insights", "insights", "/api/v1/analysis/counts/"],
  [
    "/admin/insights/assistant/assistant-1",
    "Insights assistant-1",
    "insights",
    "/api/v1/assistants/assistant-1/"
  ]
] as const)("opens %s with its required data and title", async (path, heading, title, endpoint) => {
  await renderRoute(path);
  await screen.findByRole("heading", { name: heading, level: 1 });
  expect(document.title).toBe(`${messages[title]} · Eneo`);
  expect(requestedPaths()).toContain(endpoint);
});

it("redirects an admin without modules permission without reading me again", async () => {
  replies.set("/api/v1/users/me/", testAppContext({ permissions: ["admin"] }).user);
  const { router } = await renderRoute("/admin/modules");
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin"));
  expect(requestedPaths().filter((path) => path === "/api/v1/users/me/")).toHaveLength(1);
  expect(requestedPaths()).not.toContain("/api/v1/admin/modules/");
});

it("reports an unknown MCP server before requesting its tools", async () => {
  replies.set("/api/v1/mcp-servers/unknown/tools/", failure(422));
  const { router } = await renderRoute("/admin/mcp-servers/unknown");
  await screen.findByRole("heading", { name: messages.page_not_found });
  expect(router.state.matches.some((match) => match.status === "notFound")).toBe(true);
  expect(requestedPaths()).toContain("/api/v1/mcp-servers/settings/");
  expect(requestedPaths()).not.toContain("/api/v1/mcp-servers/unknown/tools/");
});

it("replaces the legacy MCP index with the tools MCP tab", async () => {
  const { router } = await renderRoute("/admin/mcp-servers");
  await screen.findByRole("heading", { name: "Tools mcp-servers" });
  expect(router.state.location.pathname).toBe("/admin/tools");
  expect(router.state.location.search).toEqual({ tab: "mcp-servers" });
  expect(router.history.length).toBe(1);
});

it("opens models when the optional provider read fails", async () => {
  replies.set("/api/v1/admin/model-providers/", failure(500));
  const { queryClient } = await renderRoute("/admin/models");
  await screen.findByRole("heading", { name: "Models" });
  await waitFor(() =>
    expect(queryClient.getQueryState(["admin-model-providers"])?.status).toBe("error")
  );
});

it("does not wait for optional provider metadata", async () => {
  replies.set("/api/v1/admin/model-providers/capabilities/", new Promise(() => {}));
  await renderRoute("/admin/models");
  await screen.findByRole("heading", { name: "Models" });
});

it("fails the route when stale required model data cannot be refreshed", async () => {
  replies.set("/api/v1/ai-models/", failure(503));
  const { router } = await renderRoute("/admin/models", true);
  await waitFor(() =>
    expect(router.state.matches.some((match) => match.status === "error")).toBe(true)
  );
  expect(screen.queryByRole("heading", { name: "Models" })).toBeNull();
});

it("derives tools tabs from history without reloading required data", async () => {
  const { router } = await renderRoute("/admin/tools");
  await screen.findByRole("heading", { name: "Tools functions" });
  await act(() => router.navigate({ href: "/admin/tools?tab=mcp-servers" }));
  await screen.findByRole("heading", { name: "Tools mcp-servers" });
  await act(() => router.history.back());
  await screen.findByRole("heading", { name: "Tools functions" });
  await act(() => router.history.forward());
  await screen.findByRole("heading", { name: "Tools mcp-servers" });
  expect(requestedPaths().filter((path) => path === "/api/v1/mcp-servers/settings/")).toHaveLength(
    1
  );
});

it("updates MCP tabs from history without remounting the editor or repeating tools reads", async () => {
  const { router } = await renderRoute("/admin/mcp-servers/server-1?tab=tools");
  await screen.findByRole("heading", { name: "MCP server-1: tools" });
  fireEvent.change(screen.getByRole("textbox", { name: "Server draft" }), {
    target: { value: "Draft" }
  });
  await act(() => router.navigate({ href: "/admin/mcp-servers/server-1?tab=credentials" }));
  await screen.findByRole("heading", { name: "MCP server-1: credentials" });
  await act(() => router.history.back());
  await screen.findByRole("heading", { name: "MCP server-1: tools" });
  expect((screen.getByRole("textbox", { name: "Server draft" }) as HTMLInputElement).value).toBe(
    "Draft"
  );
  expect(
    requestedPaths().filter((path) => path === "/api/v1/mcp-servers/server-1/tools/")
  ).toHaveLength(1);
});

it("keeps an assistant insights 404 with the route error boundary", async () => {
  replies.set("/api/v1/assistants/missing/", failure(404));
  const { router } = await renderRoute("/admin/insights/assistant/missing");
  await waitFor(() =>
    expect(router.state.matches.some((match) => match.status === "error")).toBe(true)
  );
  expect(router.state.matches.some((match) => match.status === "notFound")).toBe(false);
});

it("keeps a refused MCP tools read with the route error boundary", async () => {
  replies.set("/api/v1/mcp-servers/server-1/tools/", failure(403));
  const { router } = await renderRoute("/admin/mcp-servers/server-1");
  await waitFor(() =>
    expect(router.state.matches.some((match) => match.status === "error")).toBe(true)
  );
  expect(router.state.matches.some((match) => match.status === "notFound")).toBe(false);
});
