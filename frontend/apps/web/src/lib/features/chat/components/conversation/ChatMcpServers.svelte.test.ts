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
});
