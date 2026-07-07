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

export function policyMcpServers(config: AssistantEffectiveConfig): McpServerRef[] {
  return isMcpEnforced(config) ? (config?.available_mcp_servers ?? []) : [];
}
