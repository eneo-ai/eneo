// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
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
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
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

afterEach(cleanup);

describe("McpServersPage", () => {
  it("names each server's menu after the server", async () => {
    renderInApp(<McpServersPage />);

    expect(await screen.findByRole("button", { name: "Fler åtgärder för Diariet" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fler åtgärder för Kartan" })).toBeTruthy();
  });
});
