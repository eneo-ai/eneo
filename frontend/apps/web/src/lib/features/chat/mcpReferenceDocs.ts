/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

/**
 * Document-level grouping for MCP tool references.
 *
 * A tool that returns several passages from the same document (e.g. knowledge
 * search chunks, distinguished only by a `#chunk-N` uri fragment) produces one
 * reference row per passage. For display we collapse those to one entry per
 * document: same uri minus fragment, and same section/pageRange annotation
 * when the server provides one (so sectioned references from external servers
 * stay distinct).
 */

type McpRefLike = {
  id: string;
  uri: string;
  content?: string | null;
  mime_type?: string | null;
  meta?: Record<string, unknown> | null;
};

/**
 * References that render as text-snippet chips. Image references render as a
 * thumbnail strip instead, so they must not consume citation numbers; every
 * place that numbers references (chip list, inline pills) must count over
 * this same filtered list.
 */
export function textDocumentReferences<T extends McpRefLike>(refs: T[]): T[] {
  return refs.filter((ref) => !(ref.mime_type ?? "").startsWith("image/"));
}

const INREF_PATTERN = /<inref id="([0-9a-f]{8})"\/>/g;

/**
 * Text references the answer actually cites inline, in first-citation order.
 *
 * The backend persists cited-only references, but a live streamed message
 * accumulates every reference from TOOL_CALL events before the answer text
 * exists — this narrows the display to the same list a reload would show.
 * Image references are excluded here like in textDocumentReferences; they
 * render as thumbnails and are never cited.
 */
export function citedTextDocumentReferences<T extends McpRefLike>(refs: T[], answer: string): T[] {
  const textRefs = textDocumentReferences(refs);
  const seen = new Set<string>();
  const cited: T[] = [];
  for (const match of answer.matchAll(INREF_PATTERN)) {
    const prefix = match[1];
    if (seen.has(prefix)) continue;
    seen.add(prefix);
    const ref = textRefs.find((candidate) => candidate.id.startsWith(prefix));
    if (ref) cited.push(ref);
  }
  return cited;
}

export type CitationMerge<T> = {
  /** Id prefixes whose chip must not render. */
  suppressed: Set<string>;
  /**
   * References each surviving chip took over, keyed by the surviving id
   * prefix and in citation order. Their passages belong in that chip's
   * snippet so nothing a suppressed chip would have shown is lost.
   */
  absorbedBy: Map<string, T[]>;
};

/**
 * Fold inline citations that would render a chip identical to their neighbour.
 *
 * Citation numbers are per document, so a model citing two passages of the
 * same document back to back ("...API:er. [1] [1]") produces two chips with
 * the same number, indistinguishable to the reader. Runs are detected on the
 * answer text — consecutive inrefs separated by whitespace only — and within a
 * run every citation after the first of a given document folds into that
 * first one. Citing the same document again later in the answer is left alone:
 * it marks a different claim, and its chip stands on its own.
 *
 * A citation is only suppressed when *every* one of its occurrences is
 * redundant, so one that also appears alone somewhere still renders — and is
 * then not absorbed either, since its passage is already reachable.
 */
export function mergeAdjacentCitations<T extends McpRefLike>(
  refs: T[],
  answer: string
): CitationMerge<T> {
  const textRefs = textDocumentReferences(refs);
  const occurrences: { prefix: string; ref: T | undefined; lead: string | null }[] = [];
  const allOccurrencesRedundant = new Map<string, boolean>();

  let leadOfDocumentInRun = new Map<string, string>();
  let previousEnd = -1;
  for (const match of answer.matchAll(INREF_PATTERN)) {
    const start = match.index ?? 0;
    const continuesRun = previousEnd > -1 && answer.slice(previousEnd, start).trim() === "";
    if (!continuesRun) leadOfDocumentInRun = new Map<string, string>();

    const prefix = match[1];
    const ref = textRefs.find((candidate) => candidate.id.startsWith(prefix));
    // An unresolved id is never suppressed: better a stray chip than a
    // silently dropped citation.
    const key = ref ? canonicalDocKey(ref) : null;
    const lead = key !== null ? (leadOfDocumentInRun.get(key) ?? null) : null;
    if (key !== null && lead === null) leadOfDocumentInRun.set(key, prefix);

    occurrences.push({ prefix, ref, lead });
    allOccurrencesRedundant.set(prefix, (allOccurrencesRedundant.get(prefix) ?? true) && !!lead);
    previousEnd = start + match[0].length;
  }

  const suppressed = new Set(
    [...allOccurrencesRedundant].filter(([, always]) => always).map(([id]) => id)
  );

  // A lead is by definition the first citation of its document in its run, so
  // it is never itself suppressed and is always a safe home for the passages.
  const absorbedBy = new Map<string, T[]>();
  const assigned = new Set<string>();
  for (const { prefix, ref, lead } of occurrences) {
    if (!lead || !ref || !suppressed.has(prefix) || assigned.has(prefix)) continue;
    assigned.add(prefix);
    absorbedBy.set(lead, [...(absorbedBy.get(lead) ?? []), ref]);
  }

  return { suppressed, absorbedBy };
}

export function canonicalDocKey(ref: McpRefLike): string {
  const uri = ref.uri ?? "";
  const hashIndex = uri.indexOf("#");
  const base = hashIndex > -1 ? uri.slice(0, hashIndex) : uri;
  const meta = (ref.meta ?? {}) as { section?: unknown; pageRange?: unknown };
  return [base || ref.id, meta.section ?? "", meta.pageRange ?? ""].join("|");
}

/**
 * One reference per document, in first-occurrence order.
 *
 * Of a document's references, the one with the most content wins: a search
 * hit carries a single passage while a full-document read carries pages, and
 * the snippet modal opened from the chip should show the richest capture.
 */
export function dedupeByDocument<T extends McpRefLike>(refs: T[]): T[] {
  const byKey = new Map<string, T>();
  const order: string[] = [];
  for (const ref of refs) {
    const key = canonicalDocKey(ref);
    const existing = byKey.get(key);
    if (!existing) {
      order.push(key);
      byKey.set(key, ref);
    } else if ((ref.content ?? "").length > (existing.content ?? "").length) {
      byKey.set(key, ref);
    }
  }
  return order.map((key) => byKey.get(key) as T);
}

/** 1-based display number of a reference's document within the deduped list. */
export function documentNumber(refs: McpRefLike[], ref: McpRefLike): number {
  const key = canonicalDocKey(ref);
  let number = 0;
  const seen = new Set<string>();
  for (const candidate of refs) {
    const candidateKey = canonicalDocKey(candidate);
    if (!seen.has(candidateKey)) {
      seen.add(candidateKey);
      number += 1;
    }
    if (candidateKey === key) return number;
  }
  return number;
}
