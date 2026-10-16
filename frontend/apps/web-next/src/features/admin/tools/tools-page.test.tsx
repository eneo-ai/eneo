// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get, POST: vi.fn() } }));
vi.mock("next/navigation", () => import("@/test/navigation"));

import { ToolsPage } from "./tools-page";
import { toolsTabOf } from "./tools-tabs";

const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });

beforeEach(() => {
  get.mockReset();
  get.mockImplementation((path?: string) => {
    if (path === "/api/v1/mcp-servers/settings/")
      return ok({
        items: [
          {
            id: "jira",
            mcp_server_id: "jira",
            name: "Jira",
            description: "",
            http_url: "https://jira.example/mcp",
            http_auth_type: "none",
            purpose: "general",
            is_enabled: true,
            is_org_enabled: true,
            readiness_reason: null,
            has_credentials: false,
            tags: null,
            icon_url: null,
            documentation_url: null,
            tools_count: 2,
            is_available: true,
            tools: []
          }
        ]
      });
    if (path === "/api/v1/mcp-servers/bundled/")
      return ok({
        items: [{ tool: "compute", purpose: "general", available: true, mcp_server_id: null }],
        count: 1,
        runtime: null
      });
    if (path === "/api/v1/security-classifications/")
      return ok({ security_enabled: false, security_classifications: [] });
    return ok({ items: [] });
  });
});
afterEach(cleanup);

describe("Verktyg", () => {
  it("reads the tab from the address and opens the functions by default", () => {
    expect(toolsTabOf(undefined)).toBe("functions");
    expect(toolsTabOf("mcp-servers")).toBe("mcp-servers");
    expect(toolsTabOf("anything")).toBe("functions");
  });

  it("marks the current tab, links the other and lists the functions", async () => {
    renderInApp(<ToolsPage tab="functions" />);
    // The lists suspend until the servers have loaded.
    expect(await screen.findByRole("heading", { name: "Webbsökning" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: "Verktyg" })).toBeTruthy();
    const tabs = screen.getByRole("navigation", { name: "Verktyg" });
    const current = within(tabs).getByRole("link", { name: "Funktioner" });
    expect(current.getAttribute("aria-current")).toBe("true");
    expect(within(tabs).getByRole("link", { name: "MCP-servrar" }).getAttribute("href")).toBe(
      "/admin/tools?tab=mcp-servers"
    );
    expect(screen.getByRole("heading", { name: "Diagram" })).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("lists the servers on the other tab, with the built-in ones first in the add menu", async () => {
    renderInApp(<ToolsPage tab="mcp-servers" />);
    expect(await screen.findByRole("link", { name: "Jira" })).toBeTruthy();
    expect(screen.getByRole("switch", { name: "Visa funktionsservrar" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Lägg till MCP-server" })).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });
});
