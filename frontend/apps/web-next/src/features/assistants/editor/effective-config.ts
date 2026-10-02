import type { Schema } from "@/lib/api/models";

export type AssistantEffectiveConfig = Schema<"EffectiveConfigPublic"> | null | undefined;

type ModelRef = {
  id: string;
  name: string;
  nickname?: string | null;
};

type McpServerRef = {
  id: string;
  name: string;
  description?: string | null;
};

export function isPromptLocked(config: AssistantEffectiveConfig): boolean {
  return config?.prompt_locked === true;
}

export function isModelsEnforced(config: AssistantEffectiveConfig): boolean {
  return config?.models_enforced === true;
}

export function isMcpEnforced(config: AssistantEffectiveConfig): boolean {
  return config?.mcp_enforced === true;
}

export function effectiveAssistantModels<Model extends ModelRef>(
  models: Model[],
  config: AssistantEffectiveConfig
): Model[] {
  if (!isModelsEnforced(config)) return models;
  const allowedIds = new Set(config?.available_models.map((model) => model.id) ?? []);
  return models.filter((model) => allowedIds.has(model.id));
}

export function lockedAssistantModel<Model extends ModelRef>(
  models: Model[],
  config: AssistantEffectiveConfig
): ModelRef | null {
  if (!isModelsEnforced(config) || !config?.locked_model) return null;
  return models.find((model) => model.id === config.locked_model?.id) ?? config.locked_model;
}

type ToolModelRef = ModelRef & { supports_tool_calling?: boolean | null };

/**
 * The model whose tool-calling support gates the tool pickers: a policy-locked
 * model overrides the assistant's pick at ask time, the space catalog entry
 * carries the capability flags, and the stored sparse model is the fallback
 * when the model is no longer offered in the space. Null when no model is
 * picked at all, which the editor treats as a separate state.
 */
export function assistantToolModel<Model extends ToolModelRef>(
  models: Model[],
  assistant: { completion_model?: ToolModelRef | null; effective_config?: AssistantEffectiveConfig }
): ToolModelRef | null {
  const locked = lockedAssistantModel(models, assistant.effective_config);
  const pickedId = locked?.id ?? assistant.completion_model?.id;
  return (
    models.find((model) => model.id === pickedId) ?? locked ?? assistant.completion_model ?? null
  );
}

export function policyMcpServers(config: AssistantEffectiveConfig): McpServerRef[] {
  return isMcpEnforced(config) ? (config?.available_mcp_servers ?? []) : [];
}
