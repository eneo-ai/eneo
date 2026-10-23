import { modelSupportsToolCalling } from "$lib/features/mcp/readiness";
import { effectiveKnowledgeMode, type EffectiveKnowledgeMode } from "./internalMcpAvailability";
import { selectEffectiveChatModel } from "./selectEffectiveChatModel";

export type NamedSource = { id: string; name: string };

export type PartnerKnowledgeSources = {
  collections: NamedSource[];
  websites: NamedSource[];
  integrations: NamedSource[];
};

function named(value: unknown, fallbackKey?: string): NamedSource[] {
  if (!Array.isArray(value)) return [];
  return value.map((source: Record<string, unknown>) => ({
    id: String(source.id),
    name: String(source.name ?? (fallbackKey ? (source[fallbackKey] ?? "") : ""))
  }));
}

/** The knowledge attached to an assistant or group chat, by kind. */
export function getPartnerKnowledgeSources(partner: unknown): PartnerKnowledgeSources {
  const record = (partner ?? {}) as Record<string, unknown>;
  return {
    collections: named(record.groups),
    websites: named(record.websites, "url"),
    integrations: named(record.integration_knowledge_list)
  };
}

export function hasKnowledgeSources(sources: PartnerKnowledgeSources): boolean {
  return sources.collections.length + sources.websites.length + sources.integrations.length > 0;
}

/** The runtime knowledge mode of a partner, after the backend's no-tool fallback. */
export function getPartnerKnowledgeMode(partner: unknown): EffectiveKnowledgeMode {
  const record = (partner ?? {}) as Record<string, unknown>;
  const stored = typeof record.knowledge_mode === "string" ? record.knowledge_mode : undefined;
  type ToolModel = { id: string; supports_tool_calling?: boolean | null };
  const model =
    "completion_model" in record
      ? selectEffectiveChatModel<ToolModel>(
          record.completion_model as ToolModel | null | undefined,
          record.effective_config as Parameters<typeof selectEffectiveChatModel<ToolModel>>[1]
        )
      : undefined;
  return effectiveKnowledgeMode(stored, modelSupportsToolCalling(model));
}

/**
 * In inject mode the backend retrieves from the attached knowledge on every
 * turn, so a finished answer without references means retrieval found
 * nothing. Tool mode has its own indicators and is left alone.
 */
export function shouldShowNoSourcesNotice({
  hasKnowledge,
  knowledgeMode,
  referenceCount,
  isLoading
}: {
  hasKnowledge: boolean;
  knowledgeMode: EffectiveKnowledgeMode;
  referenceCount: number;
  isLoading: boolean;
}): boolean {
  return hasKnowledge && knowledgeMode === "inject" && referenceCount === 0 && !isLoading;
}
