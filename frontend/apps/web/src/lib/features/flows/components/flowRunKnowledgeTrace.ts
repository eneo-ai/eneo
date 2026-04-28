import type { FlowRunDebugRagReference, FlowRunDebugRagReferenceChunk } from "@intric/intric-js";

export type KnowledgeReferenceCounts = {
  matchedCount: number;
  displayedCount: number;
  truncated: boolean;
};

export function getDisplayableKnowledgeChunks(
  chunks: FlowRunDebugRagReferenceChunk[] | null | undefined
): FlowRunDebugRagReferenceChunk[] {
  return (chunks ?? []).filter(
    (chunk) => typeof chunk.snippet === "string" && chunk.snippet.trim().length > 0
  );
}

export function getKnowledgeReferenceCounts(
  reference: FlowRunDebugRagReference
): KnowledgeReferenceCounts {
  const displayedCount = getDisplayableKnowledgeChunks(reference.chunks).length;
  // Matched chunks can be larger because evidence stores a capped display subset.
  const matchedCount = coerceNonNegativeInteger(reference.matched_chunk_count) ?? displayedCount;
  const normalizedMatchedCount = normalizeKnowledgeMatchedCount(matchedCount, displayedCount);

  return {
    matchedCount: normalizedMatchedCount,
    displayedCount,
    truncated: normalizedMatchedCount > displayedCount
  };
}

export function normalizeKnowledgeMatchedCount(
  matchedCount: number | null | undefined,
  displayedCount: number
): number {
  if (matchedCount === null || matchedCount === undefined) {
    return displayedCount;
  }
  if (!Number.isInteger(matchedCount) || matchedCount < 0) {
    return displayedCount;
  }
  return Math.max(matchedCount, displayedCount);
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

function coerceNonNegativeInteger(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  const numericValue = Number(value);
  if (!Number.isInteger(numericValue) || numericValue < 0) return null;
  return numericValue;
}
