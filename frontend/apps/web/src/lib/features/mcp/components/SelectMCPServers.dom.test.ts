import { cleanup, render, screen } from "@testing-library/svelte";
import { writable } from "svelte/store";
import { afterEach, expect, it, vi } from "vitest";

const holder: { space: unknown } = vi.hoisted(() => ({ space: null }));
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({ state: { currentSpace: writable(holder.space) } })
}));

import { m } from "$lib/paraglide/messages";
import SelectMCPServers from "./SelectMCPServers.svelte";

const server = (id: string, name: string, extra: object = {}) => ({
  id,
  name,
  purpose: "general",
  is_enabled: true,
  tools: [],
  ...extra
});
const spaceWith = (mcp_servers: unknown[], canEdit: boolean) => ({
  id: "space-uuid",
  routeId: "space-1",
  mcp_servers,
  hasPermission: (action: string, resource: string) =>
    canEdit && action === "edit" && resource === "space"
});

afterEach(cleanup);
it.each([
  [true, m.mcp_picker_empty_description_editor(), "/spaces/space-1/settings"],
  [false, m.mcp_picker_empty_description(), null]
])("offers the space settings only to an editor (edit: %s)", (canEdit, sentence, href) => {
  // Kills: link or sentence chosen for the wrong permission; link built from the space id
  holder.space = spaceWith([], canEdit);
  render(SelectMCPServers, { selectedMCPServers: [] });
  const link = screen.queryByRole("link", { name: m.mcp_open_space_settings() });
  expect(link?.getAttribute("href") ?? null).toBe(href);
  expect(screen.queryByText(sentence)).not.toBeNull();
});

it("names only the stored servers the space switched off, and drops the notice once saved", async () => {
  // Kills: no notice; kept, org-disabled or capability servers named; notice outlives the save; label without name
  const kept = server("kept", "Kept");
  const org = server("org", "Org", { is_enabled: false });
  const saved = [
    kept,
    server("gone", "Gone"),
    org,
    server("web", "Web", { purpose: "web_search" })
  ];
  holder.space = spaceWith([kept], true);
  const props = { selectedMCPServers: [kept], savedMCPServers: saved };
  const { rerender } = render(SelectMCPServers, props);
  const notice = m.mcp_assistant_dropped_servers({ names: "Gone" });
  expect(screen.getByRole("status").textContent?.trim()).toBe(notice);
  screen.getByRole("button", { name: `${m.governance_mcp_show_tools()}: Kept` });
  await rerender({ ...props, savedMCPServers: [] });
  expect(screen.queryByRole("status")).toBeNull();
});
