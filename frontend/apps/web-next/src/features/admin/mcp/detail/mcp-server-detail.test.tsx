// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";

vi.mock("next/navigation", () => import("@/test/navigation"));
const remove = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    DELETE: remove,
    GET: (path: string) =>
      Promise.resolve({
        data:
          path === "/api/v1/mcp-servers/settings/"
            ? {
                items: [
                  {
                    id: "diariet",
                    name: "Diariet",
                    description: null,
                    http_url: "https://diariet.example.se/mcp",
                    icon_url: null,
                    tags: [],
                    tools: [],
                    tools_count: 0,
                    is_org_enabled: true,
                    security_classification: null
                  }
                ]
              }
            : path === "/api/v1/security-classifications/"
              ? { security_enabled: false, security_classifications: [] }
              : { items: [] },
        response: new Response("{}")
      })
  }
}));

import { McpServerDetail } from "./mcp-server-detail";

afterEach(() => {
  cleanup();
  remove.mockReset();
});

describe("McpServerDetail", () => {
  it("names the page's menu after the server", async () => {
    renderInApp(<McpServerDetail serverId="diariet" />);

    expect(await screen.findByRole("heading", { level: 1, name: "Diariet" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fler åtgärder för Diariet" })).toBeTruthy();
  });

  it("keeps focus on the switch while it saves, and saves the press once", async () => {
    remove.mockReturnValue(new Promise(() => {}));
    renderInApp(<McpServerDetail serverId="diariet" />);
    const toggle = await screen.findByRole("switch", { name: "Aktivera Diariet" });
    toggle.focus();

    fireEvent.click(toggle);

    await waitFor(() => expect(toggle.getAttribute("aria-busy")).toBe("true"));
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    expect(toggle.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(toggle);
    expect(remove).toHaveBeenCalledTimes(1);
  });
});
