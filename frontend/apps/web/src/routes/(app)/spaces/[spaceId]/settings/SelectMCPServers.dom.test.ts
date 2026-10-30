import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";
import { afterEach, expect, it, vi } from "vitest";

const holder: { space: unknown } = vi.hoisted(() => ({ space: null }));
const updateSpace = vi.hoisted(() => vi.fn());
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({ state: { currentSpace: writable(holder.space) }, updateSpace })
}));

import { activateDuringSave } from "$lib/test/mcpTestApi";
import { m } from "$lib/paraglide/messages";
import { getLocale, setLocale } from "$lib/paraglide/runtime";
import SelectMCPServers from "./SelectMCPServers.svelte";

const server = { id: "s1", name: "Server one", tools: [] };
const other = { id: "s2", name: "Server two", tools: [] };
const space = (s: unknown[], x = {}) => ({ mcp_servers: s, security_classification: null, ...x });
const named = (name: string) => screen.getByRole("switch", { name: new RegExp(name) });

afterEach(() => {
  cleanup();
  updateSpace.mockReset();
});
it.each([
  ["a server twice", "Server two", "Server two"],
  ["a tool twice", "Tool one", "Tool one"],
  ["a tool while its own server is saved", "Server one", "Tool one"]
])("ignores input during a save and keeps focus: %s", async (_case, first, second) => {
  // Kills: a switch is disabled during its save (focus lost), or a switch or tool sends a second request
  updateSpace.mockReturnValue(new Promise(() => {}));
  holder.space = space([{ ...server, tools: [{ id: "t1", name: "Tool one", is_enabled: false }] }]);
  render(SelectMCPServers, { selectableServers: [server, other] });
  await fireEvent.click(screen.getAllByRole("button", { name: m.governance_mcp_show_tools() })[0]);
  await activateDuringSave(named(first), named(second), () => updateSpace.mock.calls.length);
});

it("marks a server below the space's classification as unavailable and sends nothing", async () => {
  // Kills: the dimmed switch can be activated, or is not announced as unavailable
  holder.space = space([], { security_classification: { security_level: 3 } });
  const low = { ...server, security_classification: { security_level: 1 } };
  render(SelectMCPServers, { selectableServers: [low] });
  await fireEvent.click(named("Server one"));
  expect(named("Server one").getAttribute("aria-disabled")).toBe("true");
  expect(updateSpace).not.toHaveBeenCalled();
});

it("shows the stored state again when the save fails", async () => {
  // Kills: the switch keeps showing the flipped state after a failed save
  updateSpace.mockResolvedValue(undefined);
  holder.space = space([]);
  render(SelectMCPServers, { selectableServers: [server] });
  await fireEvent.click(named("Server one"));
  await waitFor(() => expect(named("Server one").hasAttribute("aria-busy")).toBe(false));
  expect(named("Server one").getAttribute("aria-checked")).toBe("false");
});

it.each([
  [false, m.mcp_settings_row_description()],
  [true, m.mcp_settings_row_description_personal()]
])("describes an empty row for the kind of space (personal: %s)", (personal, sentence) => {
  // Kills: the enable hint shows with nothing to enable; a personal space is told its assistants stop
  holder.space = space([], { personal });
  render(SelectMCPServers, { selectableServers: [] });
  expect(screen.queryByText(sentence)).not.toBeNull();
  expect(screen.queryByText(m.mcp_no_org_servers_to_enable())).not.toBeNull();
  expect(screen.queryByText(m.mcp_enable_server_hint())).toBeNull();
});

it.each([
  [1, "(1 tool)"],
  [2, "(2 tools)"]
])("counts a server's tools in words that fit the sentence (%i)", (count, words) => {
  // Kills: the count is followed by the capitalised section title, or one
  // tool is counted in the plural (Swedish has one form, so English shows it)
  const previous = getLocale();
  setLocale("en", { reload: false });
  try {
    const tools = [1, 2]
      .slice(0, count)
      .map((n) => ({ id: `t${n}`, name: `T${n}`, is_enabled: true }));
    holder.space = space([{ ...server, tools }]);
    render(SelectMCPServers, { selectableServers: [server] });
    expect(screen.getByText(words)).toBeTruthy();
  } finally {
    setLocale(previous, { reload: false });
  }
});
