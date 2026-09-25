import { describe, expect, it } from "vitest";
import type { GovernancePolicy } from "./governance";
import {
  type CompletionModel,
  type McpServer,
  availableServers,
  capabilityMarker,
  buildConfirmations,
  buildUpdate,
  canSave,
  defaultModelId,
  defaultValid,
  draftReducer,
  effectiveModelIdSet,
  fileDirty,
  mcpDirty,
  modelsByProvider,
  modelsDirty,
  promptDirty,
  policyServers,
  reasoningDirty,
  reasoningOptions,
  seedEditable,
  selectableServerIdSet,
  selectableToolIdSet,
  skillsDirty,
  skillsValid
} from "./policy-draft";
import { EMPTY_POLICY } from "./policy-draft";

function policy(overrides: Partial<GovernancePolicy> = {}): GovernancePolicy {
  return {
    ...EMPTY_POLICY,
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

describe("capability governance", () => {
  const source: McpServer = {
    id: "search-provider",
    name: "Search provider",
    purpose: "web_search",
    is_available: true,
    is_enabled: true,
    readiness_reason: null,
    tools: [{ id: "provider-tool", name: "search" }]
  };

  it("offers one stable function marker instead of a provider server", () => {
    const prepared = policyServers([source, ...SERVERS]);
    expect(prepared.map((server) => server.id)).toEqual([
      "s1",
      "capability:web_search",
      "capability:image_generation"
    ]);
    expect(prepared.find((server) => server.id === "capability:web_search")?.is_available).toBe(
      true
    );
    expect(
      prepared.find((server) => server.id === "capability:image_generation")?.is_available
    ).toBe(false);
    expect(prepared.flatMap((server) => server.tools ?? []).map((tool) => tool.id)).toEqual(["t1"]);
  });

  it("keeps a saved capability when its provider changes or becomes inactive", () => {
    const saved = policy({
      mcp_restriction: {
        enabled: true,
        servers: [],
        capabilities: [{ purpose: "web_search", is_default_enabled: false }],
        disabled_tool_ids: []
      }
    });
    const prepared = policyServers([]);
    const state = seedEditable(saved, [], prepared);
    expect(state.mcpSelections[capabilityMarker("web_search")]).toEqual({
      isDefaultEnabled: false
    });
    expect(
      mcpDirty(state, saved, selectableServerIdSet(prepared), selectableToolIdSet(prepared))
    ).toBe(false);
    expect(
      buildUpdate(state, { models: false, mcp: true, prompt: false }, prepared).mcp_restriction
    ).toEqual({
      enabled: true,
      servers: [],
      capabilities: [{ purpose: "web_search", is_default_enabled: false }],
      disabled_tool_ids: []
    });
  });

  it("writes capability switches independently from general server grants", () => {
    const saved = policy();
    const prepared = policyServers([source, ...SERVERS]);
    let state = seedEditable(saved, [], prepared);
    state = draftReducer(state, { type: "setMcpEnabled", on: true });
    state = draftReducer(state, {
      type: "toggleMcp",
      id: capabilityMarker("web_search"),
      on: true,
      toolIds: []
    });
    expect(
      buildUpdate(state, { models: false, mcp: true, prompt: false }, prepared).mcp_restriction
    ).toEqual({
      enabled: true,
      servers: [],
      capabilities: [{ purpose: "web_search", is_default_enabled: true }],
      disabled_tool_ids: []
    });
  });
});

describe("reasoning and attachment policy", () => {
  const reasoningModels: CompletionModel[] = [
    {
      id: "reasoning",
      name: "Reasoning",
      can_access: true,
      supported_model_kwargs: {
        reasoning_effort: { supported: true, control: "select", options: ["low", "high"] }
      }
    },
    {
      id: "locked",
      name: "Locked",
      can_access: false,
      supported_model_kwargs: {
        reasoning_effort: { supported: true, control: "select", options: ["max"] }
      }
    }
  ];

  it("offers only supported efforts for allowed, accessible models", () => {
    const saved = policy();
    let state = seedEditable(saved, reasoningModels, []);
    expect(reasoningOptions(reasoningModels, state, new Set())).toEqual(["low", "high"]);
    state = draftReducer(state, { type: "setModelsEnabled", on: true });
    expect(reasoningOptions(reasoningModels, state, new Set())).toEqual([]);
    expect(reasoningOptions(reasoningModels, state, new Set(["reasoning"]))).toEqual([
      "low",
      "high"
    ]);
  });

  it("activates reasoning without changing other policy dimensions", () => {
    const saved = policy();
    let state = seedEditable(saved, reasoningModels, []);
    state = draftReducer(state, { type: "activateReasoning" });
    state = draftReducer(state, { type: "setReasoningEffort", effort: "high" });
    state = draftReducer(state, { type: "setReasoningOverride", on: true });
    expect(reasoningDirty(state, saved)).toBe(true);
    expect(canSave(state, true, new Set(), true, ["low", "high"])).toBe(true);
    expect(canSave(state, true, new Set(), true, ["low"])).toBe(false);
    expect(
      buildUpdate(state, { models: false, mcp: false, prompt: false, reasoning: true }, [])
    ).toEqual({
      reasoning_policy: { default_effort: "high", allow_user_override: true }
    });
    expect(fileDirty(state, saved)).toBe(false);
  });

  it("preserves an already governed inline-file policy until the switch changes", () => {
    const saved = policy({ file_policy: { configured: true, inline_file_text: true } });
    const initial = seedEditable(saved, [], []);
    expect(initial.openFilesEnabled).toBe(false);
    expect(fileDirty(initial, saved)).toBe(false);
    const changed = draftReducer(initial, { type: "setOpenFiles", on: true });
    expect(fileDirty(changed, saved)).toBe(true);
    expect(
      buildUpdate(changed, { models: false, mcp: false, prompt: false, file: true }, [])
    ).toEqual({
      file_policy: { inline_file_text: false }
    });
    expect(reasoningDirty(changed, saved)).toBe(false);
  });

  it("does not submit a pristine ungoverned attachment policy", () => {
    const saved = policy();
    const state = seedEditable(saved, [], []);
    expect(fileDirty(state, saved)).toBe(false);
    expect(reasoningDirty(state, saved)).toBe(false);
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

describe("personal chat Skills", () => {
  const saved = policy({
    skills: {
      bindings: [
        {
          skill_id: "skill",
          skill_revision_id: "revision-1",
          attachable_revision_id: "revision-2",
          slug: "skill",
          revision_number: 1,
          attachable_revision_number: 2,
          display_name: "Skill",
          description: "Description",
          content_digest: "digest",
          position: 0,
          is_active: true,
          source: "organization",
          execution_blocked: false,
          activation_mode: "always"
        }
      ]
    }
  });

  it("keeps the exact saved revision until the policy draft is changed", () => {
    const state = seedEditable(saved, [], []);
    expect(state.skillBindings).toEqual([
      { skill_id: "skill", skill_revision_id: "revision-1", activation_mode: "always" }
    ]);
    expect(skillsDirty(state, saved)).toBe(false);
    const revised = draftReducer(state, {
      type: "setSkillBindings",
      bindings: [{ skill_id: "skill", skill_revision_id: "revision-2", activation_mode: "always" }]
    });
    expect(skillsDirty(revised, saved)).toBe(true);
    expect(
      buildUpdate(revised, { models: false, mcp: false, prompt: false, skills: true }, [])
    ).toEqual({ skills: { bindings: revised.skillBindings } });
    expect(buildConfirmations(revised, saved, 0)).toContain("governance_confirm_skills_changed");
  });

  it("rejects on-demand bindings while selective activation is disabled", () => {
    const state = draftReducer(seedEditable(saved, [], []), {
      type: "setSkillBindings",
      bindings: [
        { skill_id: "skill", skill_revision_id: "revision-1", activation_mode: "on_demand" }
      ]
    });
    expect(skillsValid(state, false)).toBe(false);
    expect(canSave(state, true, new Set(), false)).toBe(false);
    expect(skillsValid(state, true)).toBe(true);
  });
});
