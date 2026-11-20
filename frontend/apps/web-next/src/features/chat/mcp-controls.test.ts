import { describe, expect, it } from "vitest";
import type { Schema } from "@/lib/api/models";
import { activeMcpServerCount, mcpServerUnavailableReason } from "./mcp-controls";

const server = (id: string, name = id): Schema<"MCPServerPublicDict"> => ({
  id,
  name,
  description: null,
  http_url: null,
  http_auth_type: null,
  purpose: "general",
  is_enabled: true,
  readiness_reason: null,
  tags: null,
  icon_url: null,
  security_classification: null,
  tools: []
});

describe("MCP chat controls", () => {
  it("counts no server as active when the model cannot call tools", () => {
    const servers = [server("a"), { ...server("b"), is_enabled: false }];
    expect(mcpServerUnavailableReason(servers[0]!, true)).toBeNull();
    expect(mcpServerUnavailableReason(servers[0]!, false)).toBe("model_no_tool_calling");
    // An administrator's deactivation is the more specific reason.
    expect(mcpServerUnavailableReason(servers[1]!, false)).toBe("server_disabled");
    expect(activeMcpServerCount(servers, new Set())).toBe(1);
    expect(activeMcpServerCount(servers, new Set(), false)).toBe(0);
  });

  it("preserves the backend's classification reason and excludes that tool from the active count", () => {
    const unavailable = { ...server("tool"), available: false, reason: "classification" };
    expect(mcpServerUnavailableReason(unavailable, true)).toBe("classification");
    expect(activeMcpServerCount([unavailable], new Set())).toBe(0);
  });
});
