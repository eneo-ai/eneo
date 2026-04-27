import { describe, expect, it } from "vitest";

import { buildAIBuilderMcpResourceLabelMaps } from "./flowAIBuilderMcpResources";

describe("flowAIBuilderMcpResources", () => {
  it("builds human-readable server and tool labels from space MCP metadata", () => {
    const labels = buildAIBuilderMcpResourceLabelMaps([
      {
        id: "server-time",
        name: "Time MCP",
        tools: [
          { id: "tool-current-time", name: "get_current_time" },
          { id: "tool-convert-time", name: "convert_time" }
        ]
      }
    ]);

    expect(labels.serverLabels.get("server-time")).toBe("Time MCP");
    expect(labels.toolLabels.get("tool-current-time")).toBe("Time MCP: get_current_time");
    expect(labels.toolLabels.get("tool-convert-time")).toBe("Time MCP: convert_time");
  });

  it("falls back to refs when metadata names are missing", () => {
    const labels = buildAIBuilderMcpResourceLabelMaps([
      {
        id: "server-1",
        name: "",
        tools: [{ id: "tool-1", name: "" }]
      }
    ]);

    expect(labels.serverLabels.get("server-1")).toBe("server-1");
    expect(labels.toolLabels.get("tool-1")).toBe("server-1: tool-1");
  });
});
