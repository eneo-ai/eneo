/**
 * Pure, framework-free model of the governance-policy editor.
 *
 * Holds the editable state shape, the reducer that mutates it, and every
 * derived value (selections, dirty tracking against the saved baseline,
 * validation, the PUT payload and the confirm-before-apply messages). The
 * React hook (`use-policy-draft`) wires this to component state + the save
 * mutation; keeping the logic here makes it unit-testable in isolation.
 */
import type { GovernancePolicy, GovernancePolicyUpdate } from "./governance";
import { disabledToolIdsForSelectedServers } from "./mcp-policy";

export type CompletionModel = {
  id: string;
  provider_id?: string | null;
  nickname?: string | null;
  name: string;
  // Mirrors the backend accept set: the policy PUT rejects any model whose
  // `can_access` is false, so the picker must only offer accessible models.
  can_access?: boolean;
};
export type ModelProviderLite = { id: string; name: string; is_active?: boolean };
export type McpTool = {
  id: string;
  name: string;
  description?: string | null;
  is_enabled_by_default?: boolean;
  removed_from_remote?: boolean;
};
export type McpServer = {
  id: string;
  name: string;
  description?: string | null;
  is_available?: boolean;
  tools?: McpTool[] | null;
};
export type PromptOption = { id: string; name: string; description?: string | null };

export type ModelSelection = { selected: boolean; isDefault: boolean };

export type EditableState = {
  modelsEnabled: boolean;
  modelSelections: Record<string, ModelSelection>;
  providerSelections: string[];
  mcpEnabled: boolean;
  /** Selected (allowed) servers → whether they start switched ON in users' chat. */
  mcpSelections: Record<string, { isDefaultEnabled: boolean }>;
  /** Deny-set of tool ids switched off on allowed servers. */
  disabledMcpToolIds: string[];
  promptEnabled: boolean;
  selectedPromptId: string | null;
};

export type SelectedModel = { completion_model_id: string; is_default: boolean };

export const EMPTY_POLICY: GovernancePolicy = {
  models_restriction: { enabled: false, models: [], provider_ids: [] },
  mcp_restriction: { enabled: false, servers: [], disabled_tool_ids: [] },
  prompt_enforcement: { enabled: false, prompt_library_id: null },
  updated_at: null,
  updated_by_user_id: null
};

// ---- Source-list preparation -----------------------------------------------

/** Only models the backend will accept (`can_access`). */
export function selectableModels(models: CompletionModel[]): CompletionModel[] {
  return models.filter((model) => model.can_access);
}

export function activeProviders(providers: ModelProviderLite[]): ModelProviderLite[] {
  return providers.filter((provider) => provider.is_active);
}

/**
 * Servers the policy can legally reference, with their full tool lists intact.
 * `is_available` mirrors tenant enablement; the PUT is rejected for a server
 * that is not currently enabled, so a since-disabled server is pruned here.
 */
export function availableServers(servers: McpServer[]): McpServer[] {
  return servers.filter((server) => server.is_available);
}

/**
 * The same servers prepared for display: globally-disabled / remotely-removed
 * tools are hidden (they never run regardless of this policy).
 */
export function displayServers(available: McpServer[]): McpServer[] {
  return available.map((server) => ({
    ...server,
    tools: (server.tools ?? []).filter(
      (tool) => tool.is_enabled_by_default !== false && !tool.removed_from_remote
    )
  }));
}

export function selectableServerIdSet(available: McpServer[]): Set<string> {
  return new Set(available.map((server) => server.id));
}

export function selectableToolIdSet(available: McpServer[]): Set<string> {
  return new Set(available.flatMap((server) => (server.tools ?? []).map((tool) => tool.id)));
}

// ---- Seeding ---------------------------------------------------------------

/** Build the editable state from the saved policy + the selectable source lists. */
export function seedEditable(
  policy: GovernancePolicy,
  models: CompletionModel[],
  available: McpServer[]
): EditableState {
  const serverIds = selectableServerIdSet(available);
  const toolIds = selectableToolIdSet(available);

  const modelSelections: Record<string, ModelSelection> = {};
  for (const model of models) {
    const existing = policy.models_restriction.models.find(
      (entry) => entry.completion_model_id === model.id
    );
    modelSelections[model.id] = { selected: !!existing, isDefault: existing?.is_default ?? false };
  }

  const mcpSelections: Record<string, { isDefaultEnabled: boolean }> = {};
  // Skip grants whose server is no longer enabled — they cannot be rendered or
  // re-saved, so carrying them would only break the save and inflate counts.
  for (const server of policy.mcp_restriction.servers) {
    if (!serverIds.has(server.mcp_server_id)) continue;
    mcpSelections[server.mcp_server_id] = { isDefaultEnabled: server.is_default_enabled };
  }

  return {
    modelsEnabled: policy.models_restriction.enabled,
    modelSelections,
    providerSelections: [...(policy.models_restriction.provider_ids ?? [])],
    mcpEnabled: policy.mcp_restriction.enabled,
    mcpSelections,
    disabledMcpToolIds: (policy.mcp_restriction.disabled_tool_ids ?? []).filter((id) =>
      toolIds.has(id)
    ),
    promptEnabled: policy.prompt_enforcement.enabled,
    selectedPromptId: policy.prompt_enforcement.prompt_library_id ?? null
  };
}

// ---- Derived selection state -----------------------------------------------

export function modelsByProvider(models: CompletionModel[]): Map<string | null, CompletionModel[]> {
  const map = new Map<string | null, CompletionModel[]>();
  for (const model of models) {
    const key = model.provider_id ?? null;
    const list = map.get(key);
    if (list) list.push(model);
    else map.set(key, [model]);
  }
  return map;
}

export function selectedModels(state: EditableState): SelectedModel[] {
  return Object.entries(state.modelSelections)
    .filter(([, value]) => value.selected)
    .map(([id, value]) => ({ completion_model_id: id, is_default: value.isDefault }));
}

/** Effective allowed set = explicit models ∪ all models from selected providers. */
export function effectiveModelIdSet(
  state: EditableState,
  byProvider: Map<string | null, CompletionModel[]>
): Set<string> {
  const out = new Set<string>(selectedModels(state).map((entry) => entry.completion_model_id));
  for (const pid of state.providerSelections) {
    for (const model of byProvider.get(pid) ?? []) out.add(model.id);
  }
  return out;
}

export function defaultModelId(state: EditableState): string | null {
  return selectedModels(state).find((entry) => entry.is_default)?.completion_model_id ?? null;
}

// ---- Dirty tracking (against the last-saved baseline) ----------------------

export function modelsDirty(state: EditableState, policy: GovernancePolicy): boolean {
  const initialIds = new Set(
    policy.models_restriction.models.map((entry) => entry.completion_model_id)
  );
  const initialDefault =
    policy.models_restriction.models.find((entry) => entry.is_default)?.completion_model_id ?? null;
  const initialProviders = new Set(policy.models_restriction.provider_ids ?? []);
  const selected = selectedModels(state);

  return (
    state.modelsEnabled !== policy.models_restriction.enabled ||
    selected.length !== initialIds.size ||
    selected.some((entry) => !initialIds.has(entry.completion_model_id)) ||
    defaultModelId(state) !== initialDefault ||
    state.providerSelections.length !== initialProviders.size ||
    state.providerSelections.some((pid) => !initialProviders.has(pid))
  );
}

export function mcpDirty(
  state: EditableState,
  policy: GovernancePolicy,
  serverIds: Set<string>,
  toolIds: Set<string>
): boolean {
  // Intersect the baseline with the selectable set so an orphaned (since-disabled)
  // server in the saved policy does not register as a pending change on load.
  const initialServers = new Map(
    policy.mcp_restriction.servers
      .filter((server) => serverIds.has(server.mcp_server_id))
      .map((server) => [server.mcp_server_id, server.is_default_enabled] as const)
  );
  const initialDisabled = new Set(
    (policy.mcp_restriction.disabled_tool_ids ?? []).filter((id) => toolIds.has(id))
  );
  const selectedEntries = Object.entries(state.mcpSelections);

  return (
    state.mcpEnabled !== policy.mcp_restriction.enabled ||
    selectedEntries.length !== initialServers.size ||
    selectedEntries.some(([id, value]) => initialServers.get(id) !== value.isDefaultEnabled) ||
    state.disabledMcpToolIds.length !== initialDisabled.size ||
    state.disabledMcpToolIds.some((id) => !initialDisabled.has(id))
  );
}

export function promptDirty(state: EditableState, policy: GovernancePolicy): boolean {
  return (
    state.promptEnabled !== policy.prompt_enforcement.enabled ||
    (state.promptEnabled
      ? state.selectedPromptId !== (policy.prompt_enforcement.prompt_library_id ?? null)
      : false)
  );
}

// ---- Validation ------------------------------------------------------------

export function defaultValid(state: EditableState, effective: Set<string>): boolean {
  const id = defaultModelId(state);
  return !state.modelsEnabled || id === null || effective.has(id);
}

export function mcpValid(state: EditableState): boolean {
  return !state.mcpEnabled || Object.keys(state.mcpSelections).length > 0;
}

export function canSave(state: EditableState, dirty: boolean, effective: Set<string>): boolean {
  return (
    dirty &&
    (!state.modelsEnabled || effective.size > 0) &&
    defaultValid(state, effective) &&
    mcpValid(state) &&
    (!state.promptEnabled || state.selectedPromptId !== null)
  );
}

// ---- Save payload + confirmations ------------------------------------------

export type DirtyFlags = { models: boolean; mcp: boolean; prompt: boolean };

export function buildUpdate(
  state: EditableState,
  flags: DirtyFlags,
  available: McpServer[]
): GovernancePolicyUpdate {
  const update: GovernancePolicyUpdate = {};
  if (flags.models) {
    update.models_restriction = {
      enabled: state.modelsEnabled,
      models: selectedModels(state),
      provider_ids: [...state.providerSelections]
    };
  }
  if (flags.mcp) {
    update.mcp_restriction = {
      enabled: state.mcpEnabled,
      servers: Object.entries(state.mcpSelections).map(([id, value]) => ({
        mcp_server_id: id,
        is_default_enabled: value.isDefaultEnabled
      })),
      disabled_tool_ids: disabledToolIdsForSelectedServers(
        available,
        Object.keys(state.mcpSelections),
        state.disabledMcpToolIds
      )
    };
  }
  if (flags.prompt) {
    update.prompt_enforcement = {
      enabled: state.promptEnabled,
      prompt_library_id: state.promptEnabled ? state.selectedPromptId : null
    };
  }
  return update;
}

export type ConfirmKey =
  | "governance_confirm_models_hidden"
  | "governance_confirm_mcp_disabled"
  | "governance_confirm_prompt_forced";

export function buildConfirmations(
  state: EditableState,
  policy: GovernancePolicy,
  effectiveSize: number
): ConfirmKey[] {
  const out: ConfirmKey[] = [];
  // "Locked single-model" UX only triggers when the effective set is exactly one.
  if (
    state.modelsEnabled &&
    effectiveSize === 1 &&
    (!policy.models_restriction.enabled ||
      policy.models_restriction.models.length +
        (policy.models_restriction.provider_ids ?? []).length >
        1)
  ) {
    out.push("governance_confirm_models_hidden");
  }
  // Turning the grant OFF removes every MCP server from the personal assistant.
  if (!state.mcpEnabled && policy.mcp_restriction.enabled) {
    out.push("governance_confirm_mcp_disabled");
  }
  if (state.promptEnabled && !policy.prompt_enforcement.enabled) {
    out.push("governance_confirm_prompt_forced");
  }
  return out;
}

// ---- Reducer ---------------------------------------------------------------

export type DraftAction =
  | { type: "reseed"; state: EditableState }
  | { type: "setModelsEnabled"; on: boolean }
  | { type: "toggleModel"; id: string; on: boolean }
  | { type: "setDefault"; id: string }
  | { type: "toggleProvider"; pid: string; on: boolean; providerModelIds: string[] }
  | { type: "setMcpEnabled"; on: boolean }
  | { type: "toggleMcp"; id: string; on: boolean; toolIds: string[] }
  | { type: "toggleMcpDefault"; id: string; on: boolean }
  | { type: "toggleMcpTool"; toolId: string; on: boolean }
  | { type: "setPromptEnabled"; on: boolean }
  | { type: "setPrompt"; id: string | null };

export function draftReducer(state: EditableState, action: DraftAction): EditableState {
  switch (action.type) {
    case "reseed":
      return action.state;

    case "setModelsEnabled":
      return { ...state, modelsEnabled: action.on };

    case "toggleModel": {
      const cur = state.modelSelections[action.id];
      if (!cur) return state;
      return {
        ...state,
        modelSelections: {
          ...state.modelSelections,
          [action.id]: action.on
            ? { selected: true, isDefault: cur.isDefault }
            : { selected: false, isDefault: false }
        }
      };
    }

    case "setDefault": {
      // The default flag must travel on a materialised row, so flip the target's
      // `selected` bit on too; a whitelisted provider keeps covering its other models.
      const next: Record<string, ModelSelection> = {};
      for (const [key, value] of Object.entries(state.modelSelections)) {
        next[key] = {
          selected: key === action.id ? true : value.selected,
          isDefault: key === action.id
        };
      }
      return { ...state, modelSelections: next };
    }

    case "toggleProvider": {
      if (!action.on) {
        return {
          ...state,
          providerSelections: state.providerSelections.filter((pid) => pid !== action.pid)
        };
      }
      // When a provider is whitelisted, individual selections under it become
      // redundant — clear them so the UI doesn't show duplicate state.
      const next = { ...state.modelSelections };
      for (const mid of action.providerModelIds) {
        const cur = next[mid];
        if (cur) next[mid] = { selected: false, isDefault: cur.isDefault };
      }
      return {
        ...state,
        providerSelections: state.providerSelections.includes(action.pid)
          ? state.providerSelections
          : [...state.providerSelections, action.pid],
        modelSelections: next
      };
    }

    case "setMcpEnabled":
      return { ...state, mcpEnabled: action.on };

    case "toggleMcp": {
      if (action.on) {
        return {
          ...state,
          mcpSelections: { ...state.mcpSelections, [action.id]: { isDefaultEnabled: true } }
        };
      }
      const next = { ...state.mcpSelections };
      delete next[action.id];
      // Tool overrides only make sense for allowed servers — drop them so a later
      // re-select starts from "all tools on".
      return {
        ...state,
        mcpSelections: next,
        disabledMcpToolIds: state.disabledMcpToolIds.filter((id) => !action.toolIds.includes(id))
      };
    }

    case "toggleMcpDefault": {
      if (!state.mcpSelections[action.id]) return state;
      return {
        ...state,
        mcpSelections: {
          ...state.mcpSelections,
          [action.id]: { isDefaultEnabled: action.on }
        }
      };
    }

    case "toggleMcpTool": {
      if (action.on) {
        return {
          ...state,
          disabledMcpToolIds: state.disabledMcpToolIds.filter((id) => id !== action.toolId)
        };
      }
      return state.disabledMcpToolIds.includes(action.toolId)
        ? state
        : { ...state, disabledMcpToolIds: [...state.disabledMcpToolIds, action.toolId] };
    }

    case "setPromptEnabled":
      return { ...state, promptEnabled: action.on };

    case "setPrompt":
      return { ...state, selectedPromptId: action.id };

    default:
      return state;
  }
}
