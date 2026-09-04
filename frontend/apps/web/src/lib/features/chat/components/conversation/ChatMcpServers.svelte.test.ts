import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it } from "vitest";
import { SvelteSet } from "svelte/reactivity";
import { m } from "$lib/paraglide/messages";
import ChatMcpServers from "./ChatMcpServers.svelte";

describe("ChatMcpServers", () => {
  it("reports the complete external server selection after a user toggle", async () => {
    const selectionSnapshots: string[][] = [];
    const disabledServerIds = new SvelteSet<string>();

    render(ChatMcpServers, {
      servers: [
        { id: "server-a", name: "Server A" },
        { id: "server-b", name: "Server B" }
      ],
      disabledServerIds,
      autoAcceptTools: true,
      onSelectionChange: (disabledIds) => selectionSnapshots.push([...disabledIds].sort())
    });

    await page
      .getByRole("button", { name: m.mcp_servers_status_aria({ active: 2, total: 2 }) })
      .click();
    await page.getByRole("switch", { name: "Server A" }).click();

    expect(selectionSnapshots).toEqual([["server-a"]]);
  });

  it("renders capability providers by capability name and excludes them from all-off", async () => {
    const disabledServerIds = new SvelteSet<string>();

    render(ChatMcpServers, {
      servers: [
        { id: "server-a", name: "Server A" },
        { id: "server-b", name: "Server B" }
      ],
      capabilityServers: [{ id: "search-provider", name: "Acme Search", purpose: "web_search" }],
      disabledServerIds,
      autoAcceptTools: true
    });

    await page
      .getByRole("button", { name: m.mcp_servers_status_aria({ active: 3, total: 3 }) })
      .click();

    // The provider's own name never shows; the row is the capability.
    await expect.element(page.getByRole("switch", { name: m.web_search() })).toBeVisible();
    expect(page.getByText("Acme Search").elements()).toHaveLength(0);

    await page.getByRole("button", { name: m.mcp_all_off() }).click();

    expect([...disabledServerIds].sort()).toEqual(["server-a", "server-b"]);
  });

  it("toggles a capability row through disabledServerIds like any server", async () => {
    const disabledServerIds = new SvelteSet<string>();

    render(ChatMcpServers, {
      servers: [],
      capabilityServers: [
        { id: "image-provider", name: "Acme Images", purpose: "image_generation" }
      ],
      disabledServerIds,
      autoAcceptTools: true
    });

    await page
      .getByRole("button", { name: m.mcp_servers_status_aria({ active: 1, total: 1 }) })
      .click();
    await page.getByRole("switch", { name: m.image_generation() }).click();

    expect([...disabledServerIds]).toEqual(["image-provider"]);
  });
});
