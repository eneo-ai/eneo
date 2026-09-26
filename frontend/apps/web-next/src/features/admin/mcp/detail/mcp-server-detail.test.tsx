// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";

vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
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

afterEach(cleanup);

describe("McpServerDetail", () => {
  it("names the page's menu after the server", async () => {
    renderInApp(<McpServerDetail serverId="diariet" />);

    expect(await screen.findByRole("heading", { level: 1, name: "Diariet" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fler åtgärder för Diariet" })).toBeTruthy();
  });
});
