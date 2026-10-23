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
      { key: "assistants", count: 1 },
      { key: "completion_models", count: 1 },
      { key: "mcp_servers", count: 1 }
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
