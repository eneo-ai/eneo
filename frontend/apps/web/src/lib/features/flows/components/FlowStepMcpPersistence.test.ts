// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { readable } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";

import FlowStepMcpPersistenceHarness from "./test-harnesses/FlowStepMcpPersistenceHarness.svelte";

vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    state: {
      currentSpace: readable({
        mcp_servers: [
          {
            id: "server-weather",
            name: "Weather Server",
            description: "Forecast tools",
            tools: [
              { id: "tool-forecast", name: "forecast_tool", is_enabled: true },
              { id: "tool-history", name: "history_tool", is_enabled: false }
            ]
          }
        ]
      })
    }
  })
}));

afterEach(() => {
  cleanup();
});

describe("Flow step MCP persistence wiring", () => {
  it("saves MCP server selection as one batched payload with tool settings", async () => {
    render(FlowStepMcpPersistenceHarness);

    await fireEvent.click(screen.getByRole("button", { name: "Weather Server" }));

    expect(screen.getByTestId("save-call-count").textContent).toBe("1");
    expect(screen.getByTestId("last-save").textContent).toContain('"mcp_servers"');
    expect(screen.getByTestId("last-save").textContent).toContain('"mcp_tools"');
    expect(screen.getByTestId("last-save").textContent).toContain('"assistantId":"assistant-1"');
    expect(screen.getByTestId("last-save").textContent).toContain('"tool_id":"tool-forecast"');
  });

  it("drops stale MCP servers that are no longer available in the space before saving", async () => {
    render(FlowStepMcpPersistenceHarness, {
      initialServers: [
        {
          id: "server-stale",
          name: "Disabled Server",
          tools: [{ id: "tool-stale", name: "disabled_tool", is_enabled: false }]
        }
      ],
      initialTools: [{ tool_id: "tool-stale", is_enabled: false }]
    });

    await fireEvent.click(screen.getByRole("button", { name: "Weather Server" }));

    expect(screen.getByTestId("save-call-count").textContent).toBe("1");
    expect(screen.getByTestId("last-save").textContent).not.toContain("server-stale");
    expect(screen.getByTestId("last-save").textContent).not.toContain("tool-stale");
    expect(screen.getByTestId("last-save").textContent).toContain("server-weather");
    expect(screen.getByTestId("last-save").textContent).toContain("tool-forecast");
  });

  it("saves MCP tool toggles as one batched payload", async () => {
    render(FlowStepMcpPersistenceHarness);

    await fireEvent.click(screen.getByRole("button", { name: "Weather Server" }));
    await fireEvent.click(screen.getByRole("button", { name: "Visa verktyg" }));
    await fireEvent.click(screen.getByRole("button", { name: "history_tool" }));

    expect(screen.getByTestId("save-call-count").textContent).toBe("2");
    expect(screen.getByTestId("last-save").textContent).toContain('"tool_id":"tool-history"');
    expect(screen.getByTestId("last-save").textContent).toContain('"is_enabled":true');
  });

  it("does not auto-save on load or when switching between preconfigured assistants", async () => {
    render(FlowStepMcpPersistenceHarness, {
      initialServers: [
        {
          id: "server-weather",
          name: "Weather Server",
          tools: [{ id: "tool-forecast", name: "forecast_tool", is_enabled: true }]
        }
      ],
      initialTools: [{ tool_id: "tool-forecast", is_enabled: true }],
      switchedServers: [
        {
          id: "server-weather",
          name: "Weather Server",
          tools: [{ id: "tool-history", name: "history_tool", is_enabled: false }]
        }
      ],
      switchedTools: [{ tool_id: "tool-history", is_enabled: false }]
    });

    expect(screen.getByTestId("save-call-count").textContent).toBe("0");

    await fireEvent.click(screen.getByTestId("switch-assistant"));

    expect(screen.getByTestId("save-call-count").textContent).toBe("0");
  });
});
