import { selectEffectiveModelId } from "@/features/ai-models/select-effective-chat-model";
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

/** Resolve the ask-time model, preferring live catalog capabilities over sparse data. */
export function assistantToolModel<Model extends ToolModelRef>(
  models: Model[],
  assistant: { completion_model?: ToolModelRef | null; effective_config?: AssistantEffectiveConfig }
): ToolModelRef | null {
  const config = assistant.effective_config;
  const locked = lockedAssistantModel(models, config);
  const pickedId = locked?.id ?? selectEffectiveModelId(assistant.completion_model?.id, config);
  const policyModels = config
    ? [config.locked_model, config.default_model, ...config.available_models]
    : [];
  return (
    models.find((model) => model.id === pickedId) ??
    policyModels.find((model) => model?.id === pickedId) ??
    (assistant.completion_model?.id === pickedId ? assistant.completion_model : null) ??
    null
  );
}

export function policyMcpServers(config: AssistantEffectiveConfig): McpServerRef[] {
  return isMcpEnforced(config) ? (config?.available_mcp_servers ?? []) : [];
}
