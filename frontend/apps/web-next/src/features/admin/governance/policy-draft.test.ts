import { describe, expect, it } from "vitest";
import type { GovernancePolicy } from "./governance";
import {
  type CompletionModel,
  type McpServer,
  availableServers,
  buildUpdate,
  canSave,
  defaultModelId,
  defaultValid,
  draftReducer,
  effectiveModelIdSet,
  mcpDirty,
  modelsByProvider,
  modelsDirty,
  promptDirty,
  seedEditable,
  selectableServerIdSet,
  selectableToolIdSet
} from "./policy-draft";

function policy(overrides: Partial<GovernancePolicy> = {}): GovernancePolicy {
  return {
    models_restriction: { enabled: false, models: [], provider_ids: [] },
    mcp_restriction: { enabled: false, servers: [], disabled_tool_ids: [] },
    prompt_enforcement: { enabled: false, prompt_library_id: null },
    updated_at: null,
    updated_by_user_id: null,
    ...overrides
  };
}

const MODELS: CompletionModel[] = [
  { id: "m1", provider_id: "p1", name: "M1", can_access: true },
  { id: "m2", provider_id: "p1", name: "M2", can_access: true }
];

const SERVERS: McpServer[] = [
  {
    id: "s1",
    name: "S1",
    is_available: true,
    tools: [{ id: "t1", name: "t1", is_enabled_by_default: true }]
  }
];

describe("seedEditable", () => {
  it("prunes grants for servers/tools that are no longer available", () => {
    const saved = policy({
      mcp_restriction: {
        enabled: true,
        servers: [{ mcp_server_id: "disabled-server", is_default_enabled: true }],
        disabled_tool_ids: ["disabled-tool"]
      }
    });
    const available = availableServers([]); // backend returned no enabled servers

    const state = seedEditable(saved, [], available);

    expect(state.mcpSelections).toEqual({});
    expect(state.disabledMcpToolIds).toEqual([]);
    // …and the pruned baseline must not read as a pending change on load.
    expect(
      mcpDirty(state, saved, selectableServerIdSet(available), selectableToolIdSet(available))
    ).toBe(false);
  });

  it("keeps the saved per-server default-enabled flag", () => {
    const saved = policy({
      mcp_restriction: {
        enabled: true,
        servers: [{ mcp_server_id: "s1", is_default_enabled: false }],
        disabled_tool_ids: []
      }
    });
    const state = seedEditable(saved, [], availableServers(SERVERS));
    expect(state.mcpSelections.s1).toEqual({ isDefaultEnabled: false });
  });
});

describe("buildUpdate", () => {
  it("submits only the dirty dimension when just the prompt changes", () => {
    const saved = policy({
      mcp_restriction: {
        enabled: true,
        servers: [{ mcp_server_id: "disabled-server", is_default_enabled: true }],
        disabled_tool_ids: ["disabled-tool"]
      },
      prompt_enforcement: { enabled: true, prompt_library_id: "prompt-1" }
    });
    const available = availableServers([]);
    let state = seedEditable(saved, [], available);
    state = draftReducer(state, { type: "setPrompt", id: "prompt-2" });

    expect(modelsDirty(state, saved)).toBe(false);
    expect(
      mcpDirty(state, saved, selectableServerIdSet(available), selectableToolIdSet(available))
    ).toBe(false);
    expect(promptDirty(state, saved)).toBe(true);

    expect(buildUpdate(state, { models: false, mcp: false, prompt: true }, available)).toEqual({
      prompt_enforcement: { enabled: true, prompt_library_id: "prompt-2" }
    });
  });

  it("preserves is_default_enabled on each submitted MCP server", () => {
    const saved = policy({
      mcp_restriction: {
        enabled: true,
        servers: [{ mcp_server_id: "s1", is_default_enabled: false }],
        disabled_tool_ids: []
      }
    });
    const available = availableServers(SERVERS);
    const state = seedEditable(saved, [], available);

    const update = buildUpdate(state, { models: false, mcp: true, prompt: false }, available);
    expect(update.mcp_restriction?.servers).toEqual([
      { mcp_server_id: "s1", is_default_enabled: false }
    ]);
  });
});

describe("reducer + derived", () => {
  it("materialises a model row when it is set as the single default", () => {
    let state = seedEditable(policy(), MODELS, []);
    state = draftReducer(state, { type: "setModelsEnabled", on: true });
    state = draftReducer(state, { type: "setDefault", id: "m1" });

    expect(state.modelSelections.m1).toEqual({ selected: true, isDefault: true });
    expect(defaultModelId(state)).toBe("m1");
  });

  it("whitelisting a provider clears redundant individual selections but keeps the default flag", () => {
    let state = seedEditable(policy(), MODELS, []);
    state = draftReducer(state, { type: "setModelsEnabled", on: true });
    state = draftReducer(state, { type: "setDefault", id: "m1" });
    state = draftReducer(state, {
      type: "toggleProvider",
      pid: "p1",
      on: true,
      providerModelIds: ["m1", "m2"]
    });

    expect(state.providerSelections).toEqual(["p1"]);
    expect(state.modelSelections.m1).toEqual({ selected: false, isDefault: true });

    const effective = effectiveModelIdSet(state, modelsByProvider(MODELS));
    expect([...effective].sort()).toEqual(["m1", "m2"]);
    expect(defaultValid(state, effective)).toBe(true);
    expect(canSave(state, modelsDirty(state, policy()), effective)).toBe(true);
  });

  it("clears the default flag when its model is deselected", () => {
    let state = seedEditable(policy(), MODELS, []);
    state = draftReducer(state, { type: "setModelsEnabled", on: true });
    state = draftReducer(state, { type: "setDefault", id: "m1" });
    state = draftReducer(state, { type: "toggleModel", id: "m1", on: false });

    expect(state.modelSelections.m1).toEqual({ selected: false, isDefault: false });
    expect(defaultModelId(state)).toBe(null);
  });
});
