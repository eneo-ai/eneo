import { describe, expect, it } from "vitest";
import type { SpaceSecurityImpact } from "./security-impact";
import { securityImpactRows, securityImpactTotal } from "./security-impact";

function impact(partial: Partial<SpaceSecurityImpact>): SpaceSecurityImpact {
  return {
    assistants: [],
    group_chats: [],
    apps: [],
    services: [],
    completion_models: [],
    embedding_models: [],
    transcription_models: [],
    mcp_servers: [],
    ...partial
  };
}

describe("securityImpactRows", () => {
  it("includes capability names and treats clearing as empty impact", () => {
    expect(securityImpactRows(impact({ capabilities: ["web_search"] }))).toEqual([
      { key: "capabilities", count: 1, names: ["web_search"] }
    ]);
    expect(securityImpactTotal(impact({ capabilities: ["web_search"] }))).toBe(1);
    expect(securityImpactRows(null)).toEqual([]);
  });
  it("keeps only non-empty impact buckets", () => {
    expect(
      securityImpactRows(
        impact({
          assistants: [{ id: "assistant-1", name: "Assistant" }],
          completion_models: [{ id: "model-1", name: "Model" }],
          mcp_servers: [{ id: "mcp-1", name: "Server" }]
        } as Partial<SpaceSecurityImpact>)
      )
    ).toEqual([
      { key: "assistants", count: 1, names: ["Assistant"] },
      { key: "completion_models", count: 1, names: ["Model"] },
      { key: "mcp_servers", count: 1, names: ["Server"] }
    ]);
  });
});

describe("securityImpactTotal", () => {
  it("sums affected resources across buckets", () => {
    expect(
      securityImpactTotal(
        impact({
          apps: [{ id: "app-1", name: "App" }],
          services: [
            { id: "service-1", name: "Service" },
            { id: "service-2", name: "Other service" }
          ]
        } as Partial<SpaceSecurityImpact>)
      )
    ).toBe(3);
  });
});
