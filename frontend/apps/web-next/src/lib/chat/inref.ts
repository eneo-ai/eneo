/**
 * Backend RAG answers cite sources inline with `<inref id="xxxxxxxx"/>` tags,
 * where the id is an 8-hex prefix of the referenced source's id (backend
 * REFERENCE_PATTERN in assistant_service.py). These helpers rewrite the tags
 * to private markers the citation remark plugin renders as numbered chips,
 * hide a tag that is still streaming in, and strip tags for clipboard copy.
 */

const INREF_TAG = /<inref\s+id="([0-9a-fA-F]{8})"\s*(?:\/>|>\s*<\/inref>)/g;
const INREF_STRIP_TAG = /<inref\s+id="[0-9a-fA-F]{8}"\s*(?:\/>|>\s*<\/inref>|>)/g;

/** Render-only marker; plain `[N]` in the model's prose is never a citation. */
export const RESOLVED_INREF = /\uE000(\d{1,3})\uE001/g;

function sourceIndex(id: string, sourceIds: (string | undefined)[]): number {
  const prefix = id.toLowerCase();
  return sourceIds.findIndex((sourceId) => sourceId?.startsWith(prefix));
}

/** Indices of sources cited by complete tags, in first-citation order. */
export function citedSourceIndices(text: string, sourceIds: (string | undefined)[]): number[] {
  const indices: number[] = [];
  const seen = new Set<number>();
  for (const match of text.matchAll(INREF_TAG)) {
    const index = sourceIndex(match[1]!, sourceIds);
    if (index < 0 || seen.has(index)) continue;
    seen.add(index);
    indices.push(index);
  }
  return indices;
}

/**
 * Replaces complete inref tags with private numbered markers (1-based index
 * into `sourceIds`, prefix-matched). Tags with no known source are dropped.
 */
export function resolveInrefs(text: string, sourceIds: (string | undefined)[]): string {
  if (!text.includes("<inref")) return text;
  return text.replace(INREF_TAG, (_tag, id: string) => {
    const index = sourceIndex(id, sourceIds);
    return index === -1 ? "" : `\uE000${index + 1}\uE001`;
  });
}

/** Removes inref tags without replacement (clipboard copy). */
export function stripInrefs(text: string): string {
  return text.replace(INREF_STRIP_TAG, "");
}

/**
 * Hides a partially-streamed `<inref …` fragment at the end of the text so a
 * half-received tag never flashes as raw markup mid-stream.
 */
export function trimPartialInref(text: string): string {
  const start = text.lastIndexOf("<");
  if (start === -1) return text;
  const fragment = text.slice(start);
  if (
    /^<inref\b[^>]*$/.test(fragment) ||
    /^<inref\b[^>]*[^/]>$/.test(fragment) ||
    "<inref".startsWith(fragment)
  ) {
    return text.slice(0, start);
  }
  return text;
}
