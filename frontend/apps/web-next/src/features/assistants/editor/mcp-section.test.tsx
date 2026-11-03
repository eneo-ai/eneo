// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
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
