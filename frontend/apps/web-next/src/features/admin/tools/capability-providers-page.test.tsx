// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { McpServer } from "../mcp/mcp";

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get, POST: post } }));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  )
}));

import { CapabilityProvidersPage } from "./capability-providers-page";

const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });
const source: McpServer = {
  id: "source",
  mcp_server_id: "source",
  name: "Search source",
  description: "",
  http_url: "https://search.example/mcp",
  http_auth_type: "none",
  purpose: "web_search",
  audience: "everyone",
  is_enabled: false,
  readiness_reason: null,
  has_credentials: false,
  tags: null,
  icon_url: null,
  documentation_url: null,
  is_org_enabled: false,
  tools_count: 1,
  is_available: false
};

/** The runtime offers every function; charts is a general server too, once added. */
const bundled = {
  items: [
    { tool: "file-analysis", purpose: "file_analysis", available: true, mcp_server_id: null },
    { tool: "file-creation", purpose: "file_creation", available: true, mcp_server_id: null },
    { tool: "charts", purpose: "charts", available: true, mcp_server_id: null },
    { tool: "compute", purpose: "compute", available: false, mcp_server_id: null },
    {
      tool: "forecast",
      purpose: "forecast",
      available: false,
      mcp_server_id: null,
      unavailable_reason: "model_missing"
    }
  ],
  count: 5,
  runtime: {
    configured: true,
    state: "ready",
    expected_version: "1.4.0",
    version: "1.4.0",
    warnings: ["confinement_unavailable"]
  }
};

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  get.mockImplementation((path?: string) => {
    if (path === "/api/v1/mcp-servers/settings/") return ok({ items: [] });
    if (path === "/api/v1/mcp-servers/bundled/") return ok(bundled);
    if (path === "/api/v1/user-groups/") return ok({ items: [] });
    if (path === "/api/v1/security-classifications/")
      return ok({ security_enabled: false, security_classifications: [] });
    return ok({ items: [] });
  });
  post.mockImplementation(() => ok({ server: source, connection: { tools_discovered: 1 } }));
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CapabilityProvidersPage />
    </QueryClientProvider>
  );
}

describe("admin function sources", () => {
  it("shows both functions before either has a source and saves a search source inactive", async () => {
    show();
    expect(await screen.findByRole("heading", { name: "web_search" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "image_generation" })).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "capability_configure" })[0]!);
    fireEvent.change(screen.getByLabelText("name"), { target: { value: "Search source" } });
    fireEvent.change(screen.getByLabelText("url"), {
      target: { value: "https://search.example/mcp" }
    });
    fireEvent.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/mcp-servers/", {
        body: expect.objectContaining({
          purpose: "web_search",
          http_url: "https://search.example/mcp",
          audience: "everyone"
        })
      })
    );
    expect(await screen.findByText("tools_saved_inactive")).toBeTruthy();
  });

  it("shows each problem at its field on save, and moves focus to the first", async () => {
    show();
    fireEvent.click((await screen.findAllByRole("button", { name: "capability_configure" }))[0]!);
    const save = screen.getByRole("button", { name: "save" }) as HTMLButtonElement;
    // Never disabled: a disabled button says nothing about what is missing.
    expect(save.disabled).toBe(false);
    const problemOf = (input: HTMLElement) =>
      document.getElementById(input.getAttribute("aria-describedby") ?? "")?.textContent;

    fireEvent.click(save);
    expect(problemOf(screen.getByLabelText("url"))).toBe("required_field");
    expect(problemOf(screen.getByLabelText("name"))).toBe("required_field");
    expect(document.activeElement).toBe(screen.getByLabelText("url"));

    fireEvent.change(screen.getByLabelText("url"), {
      target: { value: "https://search.example/mcp" }
    });
    fireEvent.change(screen.getByLabelText("name"), { target: { value: "Search source" } });
    fireEvent.change(screen.getByLabelText("mcp_audience_priority"), { target: { value: "-1" } });
    fireEvent.click(save);
    expect(screen.getByLabelText("url").getAttribute("aria-invalid")).toBeNull();
    expect(problemOf(screen.getByLabelText("mcp_audience_priority"))).toBe(
      "form_problem_whole_number_from"
    );
    expect(document.activeElement).toBe(screen.getByLabelText("mcp_audience_priority"));

    // A problem among the advanced options opens them.
    fireEvent.change(screen.getByLabelText("mcp_audience_priority"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("mcp_catalog_max_count"), { target: { value: "5000" } });
    fireEvent.click(save);
    expect(screen.getByLabelText("mcp_catalog_max_count").closest("details")?.open).toBe(true);
    expect(document.activeElement).toBe(screen.getByLabelText("mcp_catalog_max_count"));
    expect(post).not.toHaveBeenCalled();
  });

  it("offers the runtime's functions and turns one on as the default", async () => {
    show();
    expect(await screen.findByRole("heading", { name: "file_analysis" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "compute" })).toBeTruthy();
    // The runtime's state and its warnings, said once each.
    const status = await screen.findByRole("region", { name: "tools_runtime_title" });
    expect(status.textContent).toContain("tools_runtime_ready");
    expect(status.textContent).toContain("tools_runtime_confinement");
    expect(status.textContent).toContain("tools_runtime_versions");
    // Five offers: a deployment without the runtime cannot turn compute on, and a runtime
    // without the forecast model cannot turn forecast on; each says why.
    const turnOn = screen.getAllByRole("button", { name: "tools_builtin_turn_on" });
    expect(turnOn).toHaveLength(5);
    expect((turnOn[3] as HTMLButtonElement).disabled).toBe(true);
    expect((turnOn[4] as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getAllByText("tools_builtin_unavailable")).toHaveLength(2);
    expect(screen.getByText(/tools_builtin_unavailable_hint/)).toBeTruthy();
    expect(screen.getByText(/tools_builtin_model_missing_hint/)).toBeTruthy();
    fireEvent.click(turnOn[0]!);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/mcp-servers/bundled/{tool}/", {
        params: { path: { tool: "file-analysis" } },
        body: { activate: true }
      })
    );
    expect(await screen.findByText("tools_builtin_turned_on")).toBeTruthy();
  });

  it("names a bundled source after its function and keeps it out of the edit form", async () => {
    get.mockImplementation((path?: string) => {
      if (path === "/api/v1/mcp-servers/settings/")
        return ok({
          items: [
            {
              ...source,
              id: "charts",
              mcp_server_id: "charts",
              name: "Charts (bundled)",
              http_url: "http://runtime:8765/charts",
              http_auth_type: "bundled",
              purpose: "charts",
              is_enabled: true
            }
          ]
        });
      if (path === "/api/v1/mcp-servers/bundled/")
        return ok({
          ...bundled,
          items: bundled.items.map((item) => ({
            ...item,
            mcp_server_id: item.tool === "charts" ? "charts" : null
          }))
        });
      return ok({ items: [] });
    });
    show();
    expect(await screen.findByRole("heading", { level: 3, name: "charts" })).toBeTruthy();
    expect(screen.getByText("tools_builtin_charts_summary")).toBeTruthy();
    expect(screen.queryByText("Charts (bundled)")).toBeNull();
    expect(screen.queryByRole("button", { name: "tools_change" })).toBeNull();
    expect(screen.getByRole("button", { name: "deactivate" })).toBeTruthy();
  });

  it("says on an added forecast source when the runtime has lost its model, and only there", async () => {
    const added = (id: string, purpose: string) => ({
      ...source,
      id,
      mcp_server_id: id,
      name: `${id} (bundled)`,
      http_url: `http://runtime:8765/${id}`,
      http_auth_type: "bundled",
      purpose,
      is_enabled: true
    });
    const diagnose = (missing: boolean) =>
      get.mockImplementation((path?: string) => {
        if (path === "/api/v1/mcp-servers/settings/")
          return ok({ items: [added("forecast", "forecast"), added("charts", "charts")] });
        if (path === "/api/v1/mcp-servers/bundled/")
          return ok({
            ...bundled,
            items: bundled.items.map((item) =>
              item.tool === "forecast"
                ? {
                    ...item,
                    mcp_server_id: "forecast",
                    ...(missing ? {} : { available: true, unavailable_reason: null })
                  }
                : item.tool === "charts"
                  ? { ...item, mcp_server_id: "charts" }
                  : item
            )
          });
        return ok({ items: [] });
      });
    // The runtime card shows once the runtime's diagnostic has loaded.
    const loaded = () => screen.findByRole("region", { name: "tools_runtime_title" });
    diagnose(true);
    show();
    await loaded();
    expect(await screen.findAllByText("tools_builtin_model_missing_hint")).toHaveLength(1);
    cleanup();

    // Once the model is back, the hint goes.
    diagnose(false);
    show();
    await loaded();
    expect(await screen.findByRole("heading", { level: 3, name: "forecast" })).toBeTruthy();
    expect(screen.queryByText("tools_builtin_model_missing_hint")).toBeNull();
  });

  it("activates an existing source through the capability endpoint", async () => {
    get.mockImplementation((path?: string) =>
      path === "/api/v1/mcp-servers/settings/" ? ok({ items: [source] }) : ok({ items: [] })
    );
    show();
    fireEvent.click(await screen.findByRole("button", { name: "activate" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/mcp-servers/{id}/activate/", {
        params: { path: { id: "source" } }
      })
    );
  });

  it("keeps focus on a busy activate and activates once", async () => {
    get.mockImplementation((path?: string) =>
      path === "/api/v1/mcp-servers/settings/" ? ok({ items: [source] }) : ok({ items: [] })
    );
    post.mockReturnValue(new Promise(() => {}));
    show();
    const activate = await screen.findByRole("button", { name: "activate" });
    activate.focus();

    fireEvent.click(activate);

    await waitFor(() => expect(activate.getAttribute("aria-busy")).toBe("true"));
    expect(activate.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(activate);
    fireEvent.click(activate);
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("creates a built-in image source with the selected enabled model", async () => {
    get.mockImplementation((path?: string) => {
      if (path === "/api/v1/mcp-servers/settings/") return ok({ items: [] });
      if (path === "/api/v1/image-models/")
        return ok({
          items: [
            {
              id: "model",
              name: "Image model",
              nickname: "Image model",
              provider_id: "provider",
              is_org_enabled: true,
              is_deprecated: false
            }
          ]
        });
      if (path === "/api/v1/admin/model-providers/")
        return ok([{ id: "provider", name: "Provider", is_active: true }]);
      if (path === "/api/v1/security-classifications/")
        return ok({ security_enabled: false, security_classifications: [] });
      return ok({ items: [] });
    });
    show();
    fireEvent.click((await screen.findAllByRole("button", { name: "capability_configure" }))[1]!);
    fireEvent.change(screen.getByLabelText("mcp_source_label"), { target: { value: "builtin" } });
    fireEvent.change(screen.getByLabelText("name"), { target: { value: "Images" } });
    await screen.findByRole("option", { name: "Image model" });
    fireEvent.change(screen.getByLabelText("tools_source_model"), {
      target: { value: "model" }
    });
    fireEvent.click(screen.getByRole("button", { name: "tools_save_activate" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/mcp-servers/", {
        body: expect.objectContaining({
          purpose: "image_generation",
          image_model_id: "model",
          http_auth_type: "internal",
          activate: true
        })
      })
    );
  });
});
