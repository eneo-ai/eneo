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
