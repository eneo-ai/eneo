// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";

const server = (id: string, name: string) => ({
  id,
  name,
  description: null,
  http_url: `https://${id}.example.se/mcp`,
  icon_url: null,
  tags: [],
  tools: [],
  tools_count: 0,
  is_org_enabled: true,
  security_classification: null
});

vi.mock("next/navigation", () => import("@/test/navigation"));
const remove = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    DELETE: remove,
    GET: (path: string) =>
      Promise.resolve({
        data:
          path === "/api/v1/mcp-servers/settings/"
            ? { items: [server("diariet", "Diariet"), server("kartan", "Kartan")] }
            : { security_enabled: false, security_classifications: [] },
        response: new Response("{}")
      })
  }
}));

import { McpServersPage } from "./mcp-page";

afterEach(() => {
  cleanup();
  remove.mockReset();
});

describe("McpServersPage", () => {
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
