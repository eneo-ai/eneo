import type { FlowRunDebugRag, FlowRunDebugRagReference, RetrievedPassage } from "@eneo/eneo-js";

/** A passage whose verbatim text this reader is allowed to see. */
export type DisclosedPassage = RetrievedPassage & { text: string };

// Counts are read defensively: a reference is evidence, and a missing count
// must never be shown as "nothing was retrieved".
type RuntimeKnowledgeReference = Omit<
  FlowRunDebugRagReference,
  "matched_chunk_count" | "recorded_passage_count"
> & {
  matched_chunk_count?: number | null;
  recorded_passage_count?: number | null;
};

export type KnowledgeReferenceCounts = {
  matchedCount: number;
  recordedCount: number;
  disclosedCount: number;
  withheldCount: number;
  truncated: boolean;
};

export function isPassageWithheld(passage: RetrievedPassage): boolean {
  return (passage.disclosure ?? "text_disclosed") !== "text_disclosed";
}

export function getDisclosedPassages(
  passages: RetrievedPassage[] | null | undefined
): DisclosedPassage[] {
  return (passages ?? []).filter(
    (passage): passage is DisclosedPassage =>
      typeof passage.text === "string" && passage.text.trim().length > 0
  );
}

export function getWithheldPassages(
  passages: RetrievedPassage[] | null | undefined
): RetrievedPassage[] {
  return (passages ?? []).filter(isPassageWithheld);
}

export function getKnowledgeReferenceCounts(
  reference: RuntimeKnowledgeReference
): KnowledgeReferenceCounts {
  const passages = reference.passages ?? [];
  const disclosedCount = getDisclosedPassages(passages).length;
  const withheldCount = getWithheldPassages(passages).length;
  const recordedCount = normalizeKnowledgeMatchedCount(
    reference.recorded_passage_count,
    passages.length
  );
  // A source can match more passages than the evidence policy records.
  const matchedCount = normalizeKnowledgeMatchedCount(reference.matched_chunk_count, recordedCount);

  return {
    matchedCount,
    recordedCount,
    disclosedCount,
    withheldCount,
    truncated: matchedCount > recordedCount
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

/** A retrieved source plus the mapped call it came from, when there was one. */
export type KnowledgeTraceSource = {
  reference: FlowRunDebugRagReference;
  /** 1-based position of the mapped call, or null for a direct retrieval. */
  callNumber: number | null;
  /** Stable across duplicate source ids appearing in several mapped calls. */
  key: string;
};

const MAPPED_CALL_KEYS = ["items", "sources"] as const;

function isUsableReference(reference: FlowRunDebugRagReference | undefined): boolean {
  return typeof reference?.id === "string" && reference.id.length > 0;
}

/**
 * Every source a step retrieved, whether it ran once or once per document.
 *
 * A mapped step records one payload per provider call, so reading only the top
 * level would report a fan-out step as having retrieved nothing. The same
 * source id can legitimately appear in several calls, so each entry keeps its
 * call number and a key that stays unique across them.
 */
export function flattenKnowledgeTraceSources(
  rag: FlowRunDebugRag | null | undefined
): KnowledgeTraceSource[] {
  const sources: KnowledgeTraceSource[] = [];

  const visit = (payload: FlowRunDebugRag, callNumber: number | null): void => {
    for (const reference of payload.references ?? []) {
      if (!isUsableReference(reference)) continue;
      sources.push({
        reference,
        callNumber,
        key: callNumber === null ? reference.id : `${callNumber}:${reference.id}`
      });
    }
    for (const collectionKey of MAPPED_CALL_KEYS) {
      const calls = payload[collectionKey];
      if (!Array.isArray(calls)) continue;
      calls.forEach((call, index) => {
        if (call) visit(call, index + 1);
      });
    }
  };

  if (rag) visit(rag, null);
  return sources;
}

/** Sources a step retrieved, as reported by the payload or counted directly. */
export function getKnowledgeTraceSourceTotal(
  rag: FlowRunDebugRag | null | undefined,
  flattenedCount: number
): number {
  const reported = rag?.sources_total ?? rag?.unique_sources;
  return typeof reported === "number" && reported >= flattenedCount ? reported : flattenedCount;
}

/** Whether a mapped fan-out recorded every call it intended to run. */
export function isMappedFanOutIncomplete(rag: FlowRunDebugRag | null | undefined): boolean {
  if (!rag) return false;
  if (rag.mapped_calls_complete === false) return true;
  for (const collectionKey of MAPPED_CALL_KEYS) {
    const calls = rag[collectionKey];
    if (!Array.isArray(calls)) continue;
    if (calls.some((call) => call && isMappedFanOutIncomplete(call))) return true;
  }
  return false;
}
