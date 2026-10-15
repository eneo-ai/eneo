import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, expect, it, vi } from "vitest";
import * as api from "$lib/test/mcpTestApi";

const error = vi.hoisted(() => vi.fn());
vi.mock("$lib/components/toast", () => ({ toast: { error } }));
vi.mock("$app/navigation", () => ({ invalidate: vi.fn() }));
vi.mock("$lib/core/Eneo", () => ({ getEneo: () => api.testEneo() }));
vi.mock("$lib/core/AppContext", () => ({
  getAppContext: () => ({ user: { hasPermission: () => true } })
}));
vi.mock("$lib/features/security-classifications/SecurityContext.js", () => ({
  getSecurityContext: () => ({ security_classifications: [] })
}));

import { m } from "$lib/paraglide/messages";
import MCPServerActions from "./MCPServerActions.svelte";
import MCPToolsPanel from "./MCPToolsPanel.svelte";
import MCPServersTable from "./MCPServersTable.svelte";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  error.mockClear();
});

const tools = [
  api.mcpTool({ id: "off", name: "off_tool" }),
  api.mcpTool({ id: "off2", name: "off_tool_2" }),
  api.mcpTool({ id: "on", name: "on_tool", is_enabled_by_default: true }),
  api.mcpTool({ id: "new", name: "new_tool", requires_approval: true })
];
// Built after fetch is stubbed: the client keeps the fetch it finds.
const panel = (server = api.mcpServer()) =>
  render(MCPToolsPanel, {
    mcpServerId: "s1",
    serverName: "S",
    tools,
    eneoClient: api.testEneo(),
    server
  });
const offSwitch = () =>
  screen.getByRole("switch", { name: m.mcp_activate_tool({ name: "off_tool" }) });
const button = (name: string) => () => screen.getByRole("button", { name });
const review = (label: string) => () => screen.getByLabelText(`${label} new_tool`);
const failed = (count: number) => `${m.mcp_tools_update_failed_plural({ count })}: Refused`;

it.each([
  ["toggle a tool", offSwitch, "Refused", true],
  ["sync", button(m.sync_tools()), "Refused"],
  ["enable all", button(m.mcp_all_on()), failed(3)],
  ["disable all", button(m.mcp_all_off()), `${m.mcp_tools_update_failed_singular()}: Refused`],
  ["approve a tool", review(m.approve()), "Refused"],
  ["reject a tool", review(m.reject()), "Refused"],
  ["approve all", button(m.approve_all()), "Refused"],
  ["reject all", button(m.reject_all()), "Refused"]
])("shows the failure of %s in one toast", async (_action, control, text, restored = false) => {
  // Kills: a failed action is only logged; a bulk failure loses its count or toasts per tool; a failed toggle keeps the flipped switch
  api.stubFetch(api.refused);
  panel();
  await fireEvent.click(control());
  await waitFor(() => expect(error).toHaveBeenCalledWith(text));
  expect(error).toHaveBeenCalledTimes(1);
  if (restored) expect(offSwitch().getAttribute("aria-checked")).toBe("false");
});

it("ignores a second activation of a tool switch during its save and keeps focus", async () => {
  // Kills: the tool switch is disabled during its save (focus lost) or sends a second request
  const requests = api.stubFetch(api.never);
  panel();
  // The panel also reads the server's flow usage; only tool saves count.
  const saves = () =>
    requests.mock.calls.filter(([url]) => String(url).includes("/settings/tools/")).length;
  await api.activateDuringSave(offSwitch(), offSwitch(), saves);
});

it("shows the server's message when a sync from the row menu fails", async () => {
  // Kills: a failed sync from the row menu is only written to the console
  api.stubFetch(api.refused);
  render(MCPServerActions, { mcpServer: api.mcpServer() });
  await fireEvent.pointerDown(screen.getByRole("button", { name: m.actions() }), { button: 0 });
  await fireEvent.click(await screen.findByRole("menuitem", { name: m.sync_tools() }));
  await waitFor(() => expect(error).toHaveBeenCalledWith("Refused"));
});

it.each([
  ["a general server", {}],
  ["a capability provider", { purpose: "web_search" }],
  ["one of Eneo's own servers", { http_auth_type: "internal" }]
] as const)("names the tools a published flow calls for %s", async (_server, kind) => {
  // Kills: the tools panel leaves out the server's flow usage, also for a server whose purpose
  // changed after flows were published with it; a tool the server no longer lists is shown by
  // its id or not at all
  const flow = {
    flow_id: "f",
    flow_name: "F",
    space_id: "x",
    space_name: "X",
    published_version: 1
  };
  const usage = { total_count: 1, items: [{ ...flow, tool_ids: ["on", "gone"] }] };
  api.stubFetch((url) =>
    Promise.resolve(Response.json(String(url).includes("/flow-usage") ? usage : { items: [] }))
  );
  panel(api.mcpServer(kind));
  await fireEvent.click(await screen.findByText(m.mcp_flow_usage_singular()));
  const named = m.mcp_flow_usage_tools({ tools: `on_tool, ${m.mcp_flow_usage_tool_not_listed()}` });
  expect(screen.getByText(named)).toBeTruthy();
});

it("opens a server without tools, where published flows may still use a tool it had", async () => {
  // Kills: a server whose catalogue has no tools cannot be expanded, so its flow usage is unreachable
  api.stubFetch((url) =>
    Promise.resolve(
      Response.json(
        String(url).includes("/flow-usage") ? { total_count: 0, items: [] } : { items: [] }
      )
    )
  );
  const server = api.mcpServer({ tools_count: 0, tools: [] });
  render(MCPServersTable, { mcpServers: [server] });
  // click() is what a person can do: a disabled button ignores it.
  screen.getByRole("button", { name: `${m.governance_mcp_show_tools()}: ${server.name}` }).click();
  expect(await screen.findByText(m.mcp_flow_usage_none())).toBeTruthy();
  expect(screen.getByText(m.no_tools_found())).toBeTruthy();
});
