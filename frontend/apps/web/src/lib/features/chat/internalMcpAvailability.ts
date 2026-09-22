export type InternalMcpServerName = "knowledge" | "files";
export type EffectiveKnowledgeMode = "tool" | "inject";

type InternalMcpAvailability = {
  supportsToolCalling: boolean;
  hasKnowledge: boolean;
  storedKnowledgeMode?: string;
  /** Some file in play (upload, history, or an assistant attachment marked
   *  "open with tool") reaches the model as a signed reference URL. */
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
  hasDownloadReference
}: InternalMcpAvailability): InternalMcpServerName[] {
  if (!supportsToolCalling) return [];

  const names: InternalMcpServerName[] = [];
  if (hasKnowledge && storedKnowledgeMode === "tool") names.push("knowledge");
  // Mirrors the backend: the files server attaches whenever a reference URL
  // renders, whatever the assistant's inlining mode for uploads.
  if (hasDownloadReference) names.push("files");
  return names;
}
