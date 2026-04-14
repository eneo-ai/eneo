import { describe, expect, it } from "vitest";

import {
  createEmptyFlowStepMcpSummary,
  shouldShowStepMcpSection,
  summarizeAssistantMcp
} from "./flowStepMcpConfig";

describe("flowStepMcpConfig", () => {
  it("hides the MCP section for non-LLM step output modes", () => {
    expect(shouldShowStepMcpSection("transcribe_only")).toBe(false);
    expect(shouldShowStepMcpSection("template_fill")).toBe(false);
    expect(shouldShowStepMcpSection("pass_through")).toBe(true);
  });

  it("summarizes MCP server and enabled tool counts from assistant config", () => {
    expect(
      summarizeAssistantMcp({
        mcp_servers: [
          {
            id: "server-1",
            name: "Weather",
            tools: [
              { id: "tool-1", name: "forecast", is_enabled: true },
              { id: "tool-2", name: "history", is_enabled: false }
            ]
          },
          {
            id: "server-2",
            name: "Maps",
            tools: [{ id: "tool-3", name: "geocode", is_enabled: true }]
          }
        ]
      })
    ).toEqual({
      serverCount: 2,
      enabledToolCount: 2,
      hasConfiguredMcp: true
    });
  });

  it("returns an empty summary when no MCP servers are configured", () => {
    expect(summarizeAssistantMcp({ mcp_servers: [] })).toEqual({
      serverCount: 0,
      enabledToolCount: 0,
      hasConfiguredMcp: false
    });
  });

  it("provides a reusable empty MCP summary", () => {
    expect(createEmptyFlowStepMcpSummary()).toEqual({
      serverCount: 0,
      enabledToolCount: 0,
      hasConfiguredMcp: false
    });
  });
});
