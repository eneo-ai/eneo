/**
 * Backend RAG answers cite sources inline with `<inref id="xxxxxxxx"/>` tags,
 * where the id is an 8-hex prefix of the referenced source's id (backend
 * REFERENCE_PATTERN in assistant_service.py). These helpers rewrite the tags
 * to the `[N]` markers the citation remark plugin renders as superscript
 * chips, hide a tag that is still streaming in, and strip tags for clipboard
 * copy.
 */

const INREF_TAG = /<inref\s+id="([0-9a-fA-F]{8})"\s*(?:\/>|>\s*<\/inref>|>)/g;

/**
 * Replaces complete inref tags with `[N]` (1-based index into `sourceIds`,
 * prefix-matched). Tags that reference no known source are dropped.
 */
export function resolveInrefs(text: string, sourceIds: (string | undefined)[]): string {
  if (!text.includes("<inref")) return text;
  return text.replace(INREF_TAG, (_tag, id: string) => {
    const index = sourceIds.findIndex((sourceId) => sourceId?.startsWith(id.toLowerCase()));
    return index === -1 ? "" : `[${index + 1}]`;
  });
}

/** Removes inref tags without replacement (clipboard copy). */
export function stripInrefs(text: string): string {
  return text.replace(INREF_TAG, "");
}

/**
 * Hides a partially-streamed `<inref …` fragment at the end of the text so a
 * half-received tag never flashes as raw markup mid-stream.
 */
export function trimPartialInref(text: string): string {
  const start = text.lastIndexOf("<");
  if (start === -1) return text;
  const fragment = text.slice(start);
  if (/^<inref\b[^>]*$/.test(fragment) || "<inref".startsWith(fragment)) {
    return text.slice(0, start);
  }
  return text;
}
