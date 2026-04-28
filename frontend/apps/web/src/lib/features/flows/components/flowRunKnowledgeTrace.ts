import type { FlowRunDebugRagReference } from "@intric/intric-js";

export function getKnowledgeReferenceMatchCount(reference: FlowRunDebugRagReference): number {
  const hitCount = Number(reference.hit_count);
  if (Number.isFinite(hitCount) && hitCount >= 0) return hitCount;
  return reference.chunks?.length ?? 0;
}

export function getKnowledgeReferencePreviewReferences<T>(
  references: T[],
  limit: number
): {
  references: T[];
  hiddenCount: number;
} {
  const previewLimit = Math.max(0, limit);
  return {
    references: references.slice(0, previewLimit),
    hiddenCount: Math.max(0, references.length - previewLimit)
  };
}
