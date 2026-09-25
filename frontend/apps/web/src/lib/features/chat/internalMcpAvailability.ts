export type InternalMcpServerName = "knowledge" | "files";
export type EffectiveKnowledgeMode = "tool" | "inject";

type InternalMcpAvailability = {
  supportsToolCalling: boolean;
  hasKnowledge: boolean;
  storedKnowledgeMode?: string;
  inlineFileText: boolean;
  hasDownloadReference: boolean;
};

/** Runtime mode after applying the backend's no-tool fallback. */
export function effectiveKnowledgeMode(
  storedMode: string | undefined,
  supportsToolCalling: boolean
): EffectiveKnowledgeMode {
  return storedMode === "tool" && supportsToolCalling ? "tool" : "inject";
}

/** Internal servers the backend can attach for the current composer state. */
export function internalMcpServerNames({
  supportsToolCalling,
  hasKnowledge,
  storedKnowledgeMode,
  inlineFileText,
  hasDownloadReference
}: InternalMcpAvailability): InternalMcpServerName[] {
  if (!supportsToolCalling) return [];

  const names: InternalMcpServerName[] = [];
  if (hasKnowledge && storedKnowledgeMode === "tool") names.push("knowledge");
  if (!inlineFileText && hasDownloadReference) names.push("files");
  return names;
}
