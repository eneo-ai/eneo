// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Permission } from "@/lib/auth/permissions";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import { FlowUsageSection } from "./flow-usage-section";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

const USAGE = {
  total_count: 102,
  items: [
    {
      flow_id: "flow-1",
      flow_name: "Protokoll från nämnd",
      space_id: "space-member",
      space_name: "Kommunstyrelsen",
      published_version: 3,
      tool_ids: ["tool-search", "tool-gone"]
    },
    {
      flow_id: "flow-2",
      flow_name: "Bygglovsbeslut",
      space_id: "space-other",
      space_name: "Bygg och miljö",
      published_version: 1,
      tool_ids: ["tool-search"]
    }
  ]
};

function respond(usage: unknown = USAGE) {
  api.GET.mockImplementation((path: string) => {
    if (path.endsWith("/flow-usage")) return ok(usage);
    if (path.endsWith("/tools/"))
      return ok({ items: [{ id: "tool-search", name: "search", title: "Sök i arkivet" }] });
    if (path === "/api/v1/spaces/") return ok({ items: [{ id: "space-member" }] });
    throw new Error(`Unexpected GET ${path}`);
  });
}

function show({ flows = true, permissions = ["admin"] as Permission[] } = {}) {
  return renderInApp(<FlowUsageSection serverId="server-1" />, {
    // The tenant's switch decides; the admin holds no flow permission here.
    appContext: testAppContext({
      permissions,
      settings: { flows_enabled: flows },
      featureFlags: { flows: false }
    })
  });
}

beforeEach(() => respond());
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("FlowUsageSection", () => {
  it("lists the published flows that call the server's tools", async () => {
    const { container } = show({ permissions: ["admin", "flows_manage"] });

    const trigger = await screen.findByRole("button", {
      name: /Används av 102 publicerade flöden/
    });
    fireEvent.click(trigger);

    const list = screen.getByRole("list", { name: "Flöden som använder servern" });
    // A flow in a space the admin belongs to opens; the other is named only.
    const open = within(list).getByRole("link", { name: /Protokoll från nämnd/ });
    expect(open.getAttribute("href")).toBe("/spaces/space-member/flows/flow-1");
    expect(within(list).queryByRole("link", { name: /Bygglovsbeslut/ })).toBeNull();
    expect(within(list).getByText("Bygglovsbeslut")).toBeTruthy();
    expect(within(list).getByText("Kommunstyrelsen · version 3")).toBeTruthy();
    expect(
      within(list).getByText("Verktyg: Sök i arkivet, Ett verktyg som servern inte längre listar")
    ).toBeTruthy();
    expect(screen.getByText("Visar de första 2 av 102.")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("links no flow without flows_manage", async () => {
    show();
    fireEvent.click(await screen.findByRole("button", { name: /Används av 102/ }));
    expect(screen.queryByRole("link")).toBeNull();
    expect(api.GET).not.toHaveBeenCalledWith("/api/v1/spaces/");
  });

  it("says when no published flow uses the server", async () => {
    respond({ total_count: 0, items: [] });
    show();
    expect(
      await screen.findByText("Inget publicerat flöde använder serverns verktyg.")
    ).toBeTruthy();
  });

  it("shows the usage to an admin without flows_view", async () => {
    show({ permissions: ["admin"] });
    expect(await screen.findByRole("button", { name: /Används av 102/ })).toBeTruthy();
  });

  it("asks nothing when the tenant has no flows", () => {
    const { container } = show({ flows: false });
    expect(container.textContent).toBe("");
    expect(api.GET).not.toHaveBeenCalled();
  });
});
