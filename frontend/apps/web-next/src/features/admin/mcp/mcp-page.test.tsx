// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";

type Tool = {
  id: string;
  name: string;
  requires_approval: boolean;
  is_enabled_by_default: boolean;
};

const server = (id: string, name: string, tools: Tool[] = []) => ({
  id,
  name,
  description: null,
  http_url: `https://${id}.example.se/mcp`,
  icon_url: null,
  tags: [],
  tools,
  tools_count: tools.length,
  is_org_enabled: true,
  security_classification: null
});

const servers = vi.hoisted(() => ({ items: [] as unknown[] }));

vi.mock("next/navigation", () => import("@/test/navigation"));
const remove = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    DELETE: remove,
    GET: (path: string) =>
      Promise.resolve({
        data:
          path === "/api/v1/mcp-servers/settings/"
            ? { items: servers.items }
            : { security_enabled: false, security_classifications: [] },
        response: new Response("{}")
      })
  }
}));

import { McpServersPage } from "./mcp-page";

beforeEach(() => {
  servers.items = [server("diariet", "Diariet"), server("kartan", "Kartan")];
});

afterEach(() => {
  cleanup();
  remove.mockReset();
});

const pendingTile = async () => {
  const label = await screen.findByText("Väntar på granskning");
  return label.closest("div[class], button")!;
};

describe("McpServersPage", () => {
  it("keeps the pending-review tile neutral at zero", async () => {
    renderInApp(<McpServersPage />);
    const tile = await pendingTile();
    expect(tile.textContent).toContain("0");
    expect(tile.className).not.toContain("warning");
    expect(tile.tagName).toBe("DIV");
  });

  it("colours the pending-review tile as a warning once a tool waits", async () => {
    servers.items = [
      server("diariet", "Diariet", [
        { id: "t1", name: "search", requires_approval: true, is_enabled_by_default: false }
      ])
    ];
    renderInApp(<McpServersPage />);
    const tile = await pendingTile();
    expect(tile.textContent).toContain("1");
    expect(tile.className).toContain("bg-warning/10");
    expect(tile.tagName).toBe("BUTTON");
  });

  it("names each server's menu after the server", async () => {
    renderInApp(<McpServersPage />);

    expect(await screen.findByRole("button", { name: "Fler åtgärder för Diariet" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fler åtgärder för Kartan" })).toBeTruthy();
  });

  it("keeps focus on a switch while it saves, and saves each press once", async () => {
    remove.mockReturnValue(new Promise(() => {}));
    renderInApp(<McpServersPage />);
    const toggle = await screen.findByRole("switch", { name: "Aktivera Diariet" });
    toggle.focus();

    fireEvent.click(toggle);

    await waitFor(() => expect(toggle.getAttribute("aria-busy")).toBe("true"));
    // Shown at once, and never disabled, so it keeps focus.
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    expect(toggle.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(toggle);
    expect(remove).toHaveBeenCalledTimes(1);

    // Pressed again: shown at once, and sent once the first save is done.
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle.getAttribute("aria-checked")).toBe("true"));
    expect(remove).toHaveBeenCalledTimes(1);
  });
});
