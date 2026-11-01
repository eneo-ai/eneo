// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { expectNoAxeViolations } from "@/test/axe";
import messages from "@/lib/i18n/messages/sv.json";
import type { Schema } from "@/lib/api/models";
import type { McpServer, McpServerTool } from "@/features/admin/mcp/mcp";
import type { Space } from "../space";
import { makeSpace } from "../testing/space-fixture";

const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));
const state = vi.hoisted(() => ({ space: null as unknown as Space }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space) };
});
vi.mock("@/features/api-keys/resource-api-keys-section", () => ({
  ResourceApiKeysSection: () => null
}));
import { SpaceSettings } from "./space-settings";

type Update = Schema<"PartialUpdateSpaceRequest">;
const tool = (id: string, name: string, serverId = "saved"): McpServerTool => ({
  id,
  name,
  mcp_server_id: serverId,
  description: null,
  input_schema: null,
  is_enabled_by_default: true
});
const server = (id: string, name: string, tools: McpServerTool[] = []): McpServer => ({
  id,
  name,
  tools,
  tools_count: tools.length,
  mcp_server_id: id,
  description: null,
  http_url: "https://mcp.example.test",
  http_auth_type: "none",
  has_credentials: false,
  is_org_enabled: true,
  is_available: true,
  tags: ["Avtal"],
  icon_url: null,
  documentation_url: null,
  security_classification: { id: "high", name: "Hemlig", description: null, security_level: 3 }
});
const savedServer = (
  item: McpServer,
  settings: Schema<"MCPToolSetting">[]
): Schema<"MCPServerPublicDict"> => ({
  id: item.id,
  name: item.name,
  description: item.description,
  http_url: item.http_url,
  http_auth_type: item.http_auth_type,
  purpose: item.purpose ?? "general",
  is_enabled: item.is_available,
  readiness_reason: item.readiness_reason ?? null,
  tags: item.tags,
  icon_url: item.icon_url,
  security_classification: item.security_classification ?? null,
  tools: (item.tools ?? []).map((entry) => ({
    ...entry,
    is_enabled:
      settings.find((setting) => setting.tool_id === entry.id)?.is_enabled ??
      entry.is_enabled_by_default
  }))
});
let catalog: McpServer[];
let completeServers: McpServer[];
const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });
function applyUpdate(body: Update): Space {
  const savedServers = state.space.mcp_servers ?? [];
  const ids = body.mcp_servers?.map((ref) => ref.id) ?? savedServers.map((item) => item.id);
  const settings =
    body.mcp_tools ??
    savedServers.flatMap((item) =>
      item.tools.map((entry) => ({
        tool_id: String(entry.id),
        is_enabled: entry.is_enabled === true
      }))
    );
  state.space = {
    ...state.space,
    mcp_servers: ids.flatMap((id) => {
      const item = completeServers.find((entry) => entry.id === id);
      if (item) return [savedServer(item, settings)];
      const saved = savedServers.find((entry) => entry.id === id);
      return saved ? [saved] : [];
    })
  };
  return state.space;
}
function deferredPatch() {
  let resolve!: (body: Update) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<{ data: Space; response: Response }>((success, failure) => {
    resolve = (body) => success({ data: applyUpdate(body), response: new Response("{}") });
    reject = failure;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  const saved = server("saved", "Sparad server", [
    tool("off", "Avstängt verktyg"),
    tool("on", "Påslaget verktyg")
  ]);
  catalog = [saved];
  completeServers = [saved];
  state.space = makeSpace({
    overrides: {
      mcp_servers: [
        savedServer(saved, [
          { tool_id: "off", is_enabled: false },
          { tool_id: "on", is_enabled: true }
        ])
      ]
    }
  });
  api.GET.mockImplementation((path: string, options?: { params?: { path?: { id?: string } } }) => {
    if (path === "/api/v1/mcp-servers/settings/") return ok({ items: catalog });
    if (path === "/api/v1/mcp-servers/{id}/tools/")
      return ok({
        items: completeServers.find((item) => item.id === options?.params?.path?.id)?.tools ?? []
      });
    if (path === "/api/v1/security-classifications/")
      return ok({ security_enabled: false, security_classifications: [] });
    if (path === "/api/v1/ai-models/")
      return ok({ completion_models: [], embedding_models: [], transcription_models: [] });
    return ok({ items: [] });
  });
  api.PATCH.mockImplementation((_path: string, { body }: { body: Update }) =>
    ok(applyUpdate(body))
  );
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
async function expand(name = "Sparad server") {
  fireEvent.click(await screen.findByRole("button", { name: `Verktyg för ${name}` }));
  return screen.findByRole("group", { name: `Verktyg för ${name}` });
}

it.each(["saved", "failed"])(
  "adds a server after a delayed catalog read without undoing an intervening %s tool save",
  async (outcome) => {
    const added = server("added", "Ny server", [tool("new", "Nytt verktyg", "added")]);
    completeServers.push(added);
    catalog.push({ ...added, tools: undefined });
    let finish!: (result: { data: { items: McpServerTool[] }; response: Response }) => void;
    const read = new Promise<{ data: { items: McpServerTool[] }; response: Response }>(
      (resolve) => {
        finish = resolve;
      }
    );
    const originalGet = api.GET.getMockImplementation()!;
    api.GET.mockImplementation((path: string, options: unknown) =>
      path === "/api/v1/mcp-servers/{id}/tools/" ? read : originalGet(path, options)
    );
    const first = deferredPatch();
    api.PATCH.mockReturnValueOnce(first.promise);
    renderInApp(<SpaceSettings />);
    const group = await expand();
    fireEvent.click(screen.getByRole("switch", { name: "Ny server" }));
    await waitFor(() =>
      expect(api.GET).toHaveBeenCalledWith("/api/v1/mcp-servers/{id}/tools/", {
        params: { path: { id: "added" } }
      })
    );
    fireEvent.click(within(group).getByRole("switch", { name: "Påslaget verktyg" }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
    await act(async () => {
      if (outcome === "saved")
        first.resolve({
          mcp_tools: [
            { tool_id: "off", is_enabled: false },
            { tool_id: "on", is_enabled: false }
          ]
        });
      else first.reject(new Error("Tool save refused"));
    });
    await waitFor(() =>
      expect(within(group).getByRole("switch", { name: "Påslaget verktyg" })).toHaveProperty(
        "checked",
        outcome !== "saved"
      )
    );
    await act(async () =>
      finish({ data: { items: added.tools ?? [] }, response: new Response("{}") })
    );
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(2));
    await within(screen.getByRole("banner")).findByText(messages.all_changes_saved, {
      selector: "span"
    });
    expect.soft(api.PATCH.mock.calls[1]?.[1].body).toEqual({
      mcp_servers: [{ id: "saved" }, { id: "added" }],
      mcp_tools: [
        { tool_id: "off", is_enabled: false },
        { tool_id: "on", is_enabled: outcome !== "saved" },
        { tool_id: "new", is_enabled: true }
      ]
    });
    expect
      .soft(within(group).getByRole("switch", { name: "Påslaget verktyg" }))
      .toHaveProperty("checked", outcome !== "saved");
  }
);

it.each(["failed", "saved"])(
  "dispatches a complete tool selection after an earlier %s server removal",
  async (outcome) => {
    const other = server("other", "Annan server", [tool("other-tool", "Annat verktyg", "other")]);
    catalog.push(other);
    completeServers.push(other);
    state.space = {
      ...state.space,
      mcp_servers: [
        ...(state.space.mcp_servers ?? []),
        savedServer(other, [{ tool_id: "other-tool", is_enabled: false }])
      ]
    };
    const removal = deferredPatch();
    api.PATCH.mockReturnValueOnce(removal.promise);
    renderInApp(<SpaceSettings />);
    await expand();
    const otherGroup = await expand("Annan server");
    fireEvent.click(screen.getByRole("switch", { name: "Sparad server" }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
    fireEvent.click(within(otherGroup).getByRole("switch", { name: "Annat verktyg" }));
    await act(async () => {
      if (outcome === "saved") removal.resolve({ mcp_servers: [{ id: "other" }] });
      else removal.reject(new Error("Server removal refused"));
    });
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(2));
    await within(screen.getByRole("banner")).findByText(messages.all_changes_saved, {
      selector: "span"
    });
    const retained =
      outcome === "failed"
        ? [
            { tool_id: "off", is_enabled: false },
            { tool_id: "on", is_enabled: true }
          ]
        : [];
    expect
      .soft(api.PATCH.mock.calls[1]?.[1].body)
      .toEqual({ mcp_tools: [...retained, { tool_id: "other-tool", is_enabled: true }] });
    expect
      .soft(screen.getByRole("switch", { name: "Sparad server" }))
      .toHaveProperty("checked", outcome === "failed");
    expect
      .soft(within(otherGroup).getByRole("switch", { name: "Annat verktyg" }))
      .toHaveProperty("checked", true);
    if (outcome === "failed") {
      expect
        .soft(screen.getByRole("switch", { name: "Avstängt verktyg" }))
        .toHaveProperty("checked", false);
      expect
        .soft(
          state.space.mcp_servers
            ?.find((item) => item.id === "saved")
            ?.tools.find((item) => item.id === "off")?.is_enabled
        )
        .toBe(false);
    } else expect(state.space.mcp_servers?.map((item) => item.id)).toEqual(["other"]);
  }
);

it("shows tags and saved tool flags and saves only the complete tool selection", async () => {
  renderInApp(<SpaceSettings />);
  const group = await expand();
  expect(screen.getByText("Avtal")).toBeTruthy();
  expect(within(group).getByRole("switch", { name: "Avstängt verktyg" })).toHaveProperty(
    "checked",
    false
  );
  const enabled = within(group).getByRole("switch", { name: "Påslaget verktyg" });
  enabled.focus();
  fireEvent.click(enabled);
  await waitFor(() =>
    expect(api.PATCH).toHaveBeenCalledExactlyOnceWith("/api/v1/spaces/{id}/", {
      params: { path: { id: "space-1" } },
      body: {
        mcp_tools: [
          { tool_id: "off", is_enabled: false },
          { tool_id: "on", is_enabled: false }
        ]
      }
    })
  );
  expect(document.activeElement).toBe(enabled);
  await expectNoAxeViolations(document.getElementById("tools")!);
});

it("loads an incomplete tool catalog on addition and enables every new tool in the same PATCH", async () => {
  const added = server("added", "Ny server", [
    tool("new-a", "Nytt A", "added"),
    tool("new-b", "Nytt B", "added")
  ]);
  completeServers.push(added);
  catalog.push({ ...added, tools: undefined });
  renderInApp(<SpaceSettings />);
  const add = await screen.findByRole("switch", { name: "Ny server" });
  expect(api.GET.mock.calls.filter(([path]) => path.endsWith("/tools/"))).toHaveLength(0);
  fireEvent.click(add);
  await waitFor(() =>
    expect(api.PATCH).toHaveBeenCalledExactlyOnceWith("/api/v1/spaces/{id}/", {
      params: { path: { id: "space-1" } },
      body: {
        mcp_servers: [{ id: "saved" }, { id: "added" }],
        mcp_tools: [
          { tool_id: "off", is_enabled: false },
          { tool_id: "on", is_enabled: true },
          { tool_id: "new-a", is_enabled: true },
          { tool_id: "new-b", is_enabled: true }
        ]
      }
    })
  );
  expect(api.GET).toHaveBeenCalledWith("/api/v1/mcp-servers/{id}/tools/", {
    params: { path: { id: "added" } }
  });
  const group = await expand("Ny server");
  expect(within(group).getByRole("switch", { name: "Nytt A" })).toHaveProperty("checked", true);
});

it("keeps an addition unchecked after a tool read failure and can retry without a partial PATCH", async () => {
  const added = server("added", "Ny server", [tool("new", "Nytt verktyg", "added")]);
  completeServers.push(added);
  catalog.push({ ...added, tools: undefined });
  const originalGet = api.GET.getMockImplementation()!;
  let reads = 0;
  api.GET.mockImplementation((path: string, options: unknown) => {
    if (path === "/api/v1/mcp-servers/{id}/tools/" && ++reads === 1) {
      return Promise.resolve({
        error: { message: "Tool read refused" },
        response: new Response("{}", { status: 503 })
      });
    }
    return originalGet(path, options);
  });
  renderInApp(<SpaceSettings />);
  const add = await screen.findByRole("switch", { name: "Ny server" });
  add.focus();
  fireEvent.click(add);
  const retry = await screen.findByRole("button", { name: "Försök igen" });
  expect(add).toHaveProperty("checked", false);
  expect(api.PATCH).not.toHaveBeenCalled();
  expect(document.activeElement).toBe(add);
  fireEvent.click(retry);
  await waitFor(() => expect(add.getAttribute("aria-busy")).not.toBe("true"));
  fireEvent.click(add);
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
  expect(api.PATCH.mock.calls[0]?.[1].body.mcp_tools).toContainEqual({
    tool_id: "new",
    is_enabled: true
  });
});

it("does not add a server if its tool read completes after leaving settings", async () => {
  const added = server("added", "Ny server", [tool("new", "Nytt verktyg", "added")]);
  completeServers.push(added);
  catalog.push({ ...added, tools: undefined });
  let finish!: (result: { data: { items: McpServerTool[] }; response: Response }) => void;
  const read = new Promise<{ data: { items: McpServerTool[] }; response: Response }>((resolve) => {
    finish = resolve;
  });
  const originalGet = api.GET.getMockImplementation()!;
  api.GET.mockImplementation((path: string, options: unknown) =>
    path === "/api/v1/mcp-servers/{id}/tools/" ? read : originalGet(path, options)
  );
  const view = renderInApp(<SpaceSettings />);
  fireEvent.click(await screen.findByRole("switch", { name: "Ny server" }));
  await waitFor(() =>
    expect(api.GET).toHaveBeenCalledWith("/api/v1/mcp-servers/{id}/tools/", {
      params: { path: { id: "added" } }
    })
  );
  view.unmount();
  await act(async () => {
    finish({ data: { items: added.tools ?? [] }, response: new Response("{}") });
  });
  expect(api.PATCH).not.toHaveBeenCalled();
});

it("blocks classified additions, keeps saved unavailable resources removable and rolls back backend refusal", async () => {
  const missing = server("missing", "Saknad server", [
    tool("missing-tool", "Saknat verktyg", "missing")
  ]);
  const blocked = { ...server("blocked", "Låg klassning"), security_classification: null };
  catalog.push(blocked, { ...server("capability", "Funktionskälla"), purpose: "web_search" });
  state.space = {
    ...state.space,
    security_classification: { id: "high", name: "Hemlig", description: null, security_level: 3 },
    mcp_servers: [
      ...(state.space.mcp_servers ?? []),
      savedServer(missing, [{ tool_id: "missing-tool", is_enabled: true }])
    ]
  };
  api.PATCH.mockRejectedValueOnce(new Error("Server is disabled"));
  renderInApp(<SpaceSettings />);
  const low = await screen.findByRole("switch", { name: "Låg klassning" });
  expect(low.getAttribute("aria-disabled")).toBe("true");
  expect(
    screen.getByText("Denna MCP-server uppfyller inte den valda säkerhetsklassificeringen", {
      selector: "p"
    })
  ).toBeTruthy();
  fireEvent.click(low);
  expect(api.PATCH).not.toHaveBeenCalled();
  expect(screen.queryByRole("switch", { name: "Funktionskälla" })).toBeNull();
  const missingSwitch = screen.getByRole("switch", { name: "Saknad server" });
  expect(screen.getByText("Källan är inte tillgänglig.", { selector: "p" })).toBeTruthy();
  const tools = await expand("Saknad server");
  fireEvent.click(within(tools).getByRole("switch", { name: "Saknat verktyg" }));
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
  await waitFor(() =>
    expect(within(tools).getByRole("switch", { name: "Saknat verktyg" })).toHaveProperty(
      "checked",
      true
    )
  );
  fireEvent.click(missingSwitch);
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(2));
  expect(api.PATCH.mock.calls[1]?.[1].body.mcp_servers).toEqual([{ id: "saved" }]);
});

it.each(["failed", "saved"])(
  "queues tool intents and recovers after an earlier %s save and a failed last save",
  async (firstOutcome) => {
    const first = deferredPatch();
    const second = deferredPatch();
    api.PATCH.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    renderInApp(<SpaceSettings />);
    const group = await expand();
    fireEvent.click(within(group).getByRole("switch", { name: "Avstängt verktyg" }));
    fireEvent.click(within(group).getByRole("switch", { name: "Påslaget verktyg" }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
    await act(async () => {
      if (firstOutcome === "failed") first.reject(new Error("First refused"));
      else
        first.resolve({
          mcp_tools: [
            { tool_id: "off", is_enabled: true },
            { tool_id: "on", is_enabled: true }
          ]
        });
    });
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(2));
    // The later intent must not retry an earlier failed tool change.
    expect(api.PATCH.mock.calls[1]?.[1].body).toEqual({
      mcp_tools: [
        { tool_id: "off", is_enabled: firstOutcome === "saved" },
        { tool_id: "on", is_enabled: false }
      ]
    });
    await act(async () => second.reject(new Error("Second refused")));
    await waitFor(() =>
      expect(within(group).getByRole("switch", { name: "Avstängt verktyg" })).toHaveProperty(
        "checked",
        firstOutcome === "saved"
      )
    );
    expect(within(group).getByRole("switch", { name: "Påslaget verktyg" })).toHaveProperty(
      "checked",
      true
    );
    fireEvent.click(within(group).getByRole("switch", { name: "Påslaget verktyg" }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(3));
    expect(api.PATCH.mock.calls[2]?.[1].body).toEqual({
      mcp_tools: [
        { tool_id: "off", is_enabled: firstOutcome === "saved" },
        { tool_id: "on", is_enabled: false }
      ]
    });
  }
);
