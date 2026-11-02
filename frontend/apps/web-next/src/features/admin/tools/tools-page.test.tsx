// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { flushAnnouncements, recordAnnouncements, renderInApp } from "@/test/render";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get, POST: vi.fn() } }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

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
  it.each(["functions", "mcp-servers"] as const)(
    "shows one runtime status above the %s tab",
    async (tab) => {
      get.mockImplementation((path?: string) => {
        if (path === "/api/v1/mcp-servers/bundled/")
          return ok({
            items: [],
            count: 0,
            runtime: {
              configured: true,
              state: "ready",
              expected_version: "1.4.0",
              version: "1.4.0",
              warnings: []
            }
          });
        if (path === "/api/v1/security-classifications/")
          return ok({ security_enabled: false, security_classifications: [] });
        return ok({ items: [] });
      });
      renderInApp(<ToolsPage tab={tab} />);
      const runtime = await screen.findByRole("heading", { name: "Eneos verktygstjänst" });
      expect(screen.getAllByRole("heading", { name: "Eneos verktygstjänst" })).toHaveLength(1);
      const tabs = screen.getByRole("navigation", { name: "Verktyg" });
      expect(runtime.compareDocumentPosition(tabs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  );
  it("keeps the runtime status's place while it is read, and shows the status there", async () => {
    // The status arrives after the page (the backend probes the runtime for it): its place is
    // held from the first paint, so the card does not push the tabs and the list down.
    let answer!: (reply: unknown) => void;
    get.mockImplementation((path?: string) => {
      if (path === "/api/v1/mcp-servers/bundled/")
        return new Promise((resolve) => (answer = resolve));
      if (path === "/api/v1/security-classifications/")
        return ok({ security_enabled: false, security_classifications: [] });
      return ok({ items: [] });
    });
    const said = recordAnnouncements();
    const { container } = renderInApp(<ToolsPage tab="functions" />);
    expect(await screen.findByRole("heading", { name: "Webbsökning" })).toBeTruthy();
    const area = container.querySelector('[data-slot="runtime-status"]');
    expect(area).toBeTruthy();
    expect(area!.className).toContain("min-h-");
    // Decorative while pending: no heading, no busy announcement.
    expect(area!.firstElementChild!.getAttribute("aria-hidden")).toBe("true");
    expect(within(area as HTMLElement).queryByRole("heading")).toBeNull();
    // Nothing busy is said while the status is read, politely or assertively.
    await flushAnnouncements();
    expect(said).toEqual([]);
    expect(document.querySelector("[data-astryx-live-region='assertive']")?.textContent ?? "").toBe(
      ""
    );

    answer(
      await ok({
        items: [],
        count: 0,
        runtime: {
          configured: true,
          state: "ready",
          expected_version: "1.4.0",
          version: "1.4.0",
          warnings: []
        }
      })
    );
    const runtime = await screen.findByRole("heading", { name: "Eneos verktygstjänst" });
    expect(container.querySelector('[data-slot="runtime-status"]')).toBe(area);
    expect(area!.contains(runtime)).toBe(true);
  });

  it("shows a failed read of the built-in tools in the runtime status's place", async () => {
    get.mockImplementation((path?: string) => {
      if (path === "/api/v1/mcp-servers/bundled/")
        return Promise.resolve({
          error: { message: "Down", code: "internal" },
          response: new Response("{}", { status: 500 })
        });
      if (path === "/api/v1/security-classifications/")
        return ok({ security_enabled: false, security_classifications: [] });
      return ok({ items: [] });
    });
    const { container } = renderInApp(<ToolsPage tab="functions" />);
    const failure = await screen.findByText("Det gick inte att läsa Eneos inbyggda verktyg");
    const area = container.querySelector('[data-slot="runtime-status"]');
    expect(area!.className).toContain("min-h-");
    expect(area!.contains(failure)).toBe(true);
  });

  it("says when the built-in tools cannot be read, and reads them again on request", async () => {
    let down = true;
    get.mockImplementation((path?: string) => {
      if (path === "/api/v1/mcp-servers/bundled/")
        return down
          ? Promise.resolve({
              error: { message: "Down", code: "internal" },
              response: new Response("{}", { status: 500 })
            })
          : ok({ items: [], count: 0, runtime: null });
      if (path === "/api/v1/security-classifications/")
        return ok({ security_enabled: false, security_classifications: [] });
      return ok({ items: [] });
    });
    renderInApp(<ToolsPage tab="functions" />);
    expect(await screen.findByText("Det gick inte att läsa Eneos inbyggda verktyg")).toBeTruthy();

    down = false;
    fireEvent.click(screen.getByRole("button", { name: /Försök igen/ }));
    await waitFor(() =>
      expect(screen.queryByText("Det gick inte att läsa Eneos inbyggda verktyg")).toBeNull()
    );
  });

  it("shows a 404 in the runtime status's place, like any failed read", async () => {
    get.mockImplementation((path?: string) => {
      if (path === "/api/v1/mcp-servers/bundled/")
        return Promise.resolve({
          error: { message: "Not Found", code: "http_404" },
          response: new Response("{}", { status: 404 })
        });
      if (path === "/api/v1/security-classifications/")
        return ok({ security_enabled: false, security_classifications: [] });
      return ok({ items: [] });
    });
    renderInApp(<ToolsPage tab="functions" />);
    expect(await screen.findByRole("heading", { name: "Webbsökning" })).toBeTruthy();
    const area = document.querySelector('[data-slot="runtime-status"]');
    expect(
      await within(area as HTMLElement).findByText("Det gick inte att läsa Eneos inbyggda verktyg")
    ).toBeTruthy();
  });

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
