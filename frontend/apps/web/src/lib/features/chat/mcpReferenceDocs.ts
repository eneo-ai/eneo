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
  meta?: Record<string, unknown> | null;
};

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
