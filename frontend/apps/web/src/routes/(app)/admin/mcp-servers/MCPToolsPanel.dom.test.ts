import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, expect, it, vi } from "vitest";
import * as api from "$lib/test/mcpTestApi";

const error = vi.hoisted(() => vi.fn());
vi.mock("$lib/components/toast", () => ({ toast: { error } }));
vi.mock("$app/navigation", () => ({ invalidate: vi.fn() }));
vi.mock("$lib/core/Eneo", () => ({ getEneo: () => api.testEneo() }));
vi.mock("$lib/features/security-classifications/SecurityContext.js", () => ({
  getSecurityContext: () => ({ security_classifications: [] })
}));

import { m } from "$lib/paraglide/messages";
import MCPServerActions from "./MCPServerActions.svelte";
import MCPToolsPanel from "./MCPToolsPanel.svelte";

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
  await api.activateDuringSave(offSwitch(), offSwitch(), () => requests.mock.calls.length);
});

it("shows the server's message when a sync from the row menu fails", async () => {
  // Kills: a failed sync from the row menu is only written to the console
  api.stubFetch(api.refused);
  render(MCPServerActions, { mcpServer: api.mcpServer() });
  await fireEvent.pointerDown(screen.getByRole("button", { name: m.actions() }), { button: 0 });
  await fireEvent.click(await screen.findByRole("menuitem", { name: m.sync_tools() }));
  await waitFor(() => expect(error).toHaveBeenCalledWith("Refused"));
});
