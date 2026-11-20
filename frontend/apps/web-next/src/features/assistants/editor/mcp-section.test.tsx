// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { assistantWidgetStatusQueryOptions } from "@/features/widget/admin/queries";
import { browserApi } from "@/lib/api/browser";
import { renderInApp, testQueryClient } from "@/test/render";
import { McpSection } from "./mcp-section";
import type { Assistant } from "./use-assistant";
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
const can = vi.hoisted(() => vi.fn(() => true));
const space = vi.hoisted(() => ({ mcp_servers: [] as unknown[], completion_models: [] }));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({ routeId: "space", can, space })
}));
afterEach(() => {
  cleanup();
  can.mockReturnValue(true);
  space.mcp_servers = [];
});
const assistant = {
  id: "assistant",
  groups: [],
  websites: [],
  integration_knowledge_list: [],
  mcp_servers: [],
  mcp_tools: []
} as unknown as Assistant;
it("names policy capability providers by capability", () => {
  renderInApp(
    <McpSection
      assistant={
        {
          ...assistant,
          effective_config: {
            mcp_enforced: true,
            available_models: [],
            available_mcp_servers: [
              { id: "provider", name: "Provider name", purpose: "web_search" }
            ]
          }
        } as unknown as Assistant
      }
    />
  );
  expect(screen.getByText("Webbsökning")).toBeTruthy();
  expect(screen.queryByText("Provider name")).toBeNull();
});
it.each([true, false])("explains empty tools and links only for space editors (%s)", (editable) => {
  can.mockReturnValue(editable);
  renderInApp(<McpSection assistant={assistant} />);
  expect(screen.getByText(/Inga MCP-servrar/)).toBeTruthy();
  if (editable) expect(screen.queryByRole("link")).not.toBeNull();
  else expect(screen.queryByRole("link")).toBeNull();
  if (editable)
    expect(screen.getByRole("link").getAttribute("href")).toBe(
      "/spaces/space/settings?section=tools"
    );
});
it("lists a deactivated server the assistant still has, so it can be switched off", () => {
  space.mcp_servers = [{ id: "search", name: "Sök", is_enabled: true, tools: [] }];
  renderInApp(
    <McpSection
      assistant={
        {
          ...assistant,
          mcp_servers: [{ id: "archive", name: "Arkiv", is_enabled: false, tools: [] }]
        } as unknown as Assistant
      }
    />
  );
  const archive = screen.getByRole("switch", { name: /Arkiv/ });
  expect(archive.getAttribute("aria-checked")).toBe("true");
  expect((archive as HTMLButtonElement).disabled).toBe(false);
  expect(within(archive.closest("label")!).getByText("Inaktiverad")).toBeTruthy();
});

it.each([true, false])(
  "shows the public widget notice at the tool picker when active is %s",
  (active) => {
    const queryClient = testQueryClient();
    const status = assistantWidgetStatusQueryOptions(browserApi, assistant.id);
    queryClient.setQueryData(status.queryKey, { serves_active_widget: active });
    space.mcp_servers = [{ id: "search", name: "Sök", is_enabled: true, tools: [] }];

    renderInApp(<McpSection assistant={assistant} />, { queryClient });

    expect(
      Boolean(screen.queryByText(/sparas automatiskt och gäller från besökarens nästa fråga/))
    ).toBe(active);
    expect(Boolean(screen.queryByText(/Om assistenten används i en aktiv widget/))).toBe(!active);
  }
);

it("explains the publication risk when widget status cannot be read", async () => {
  const request = vi.spyOn(browserApi, "GET").mockRejectedValue(new Error("offline"));
  try {
    renderInApp(<McpSection assistant={assistant} />);
    const note = await screen.findByText(
      /Det gick inte att kontrollera widgetens publiceringsstatus/
    );
    expect(note.textContent).toContain("Om assistenten används i en aktiv widget");
  } finally {
    request.mockRestore();
  }
});
