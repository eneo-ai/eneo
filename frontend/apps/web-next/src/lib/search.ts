/**
 * Free-text filtering for the client-side search boxes: every whitespace-
 * separated term must occur (case-insensitively) in one of the fields, in any
 * order. Astryx Table's filtering plugin covers per-column filters; a single
 * "find the row I am thinking of" box is plain substring matching, as in
 * Astryx's own table-page template. The production SvelteKit lists match the
 * query as one substring; every row that rule finds, this one finds too.
 */
export type SearchValue = string | number | null | undefined;

/** The query's lower-cased terms; none for a blank query. */
export function searchTerms(query: string): string[] {
  return query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
}

/** Whether every term of `query` occurs in one of `fields`. A blank query matches. */
export function matchesSearch(fields: readonly SearchValue[], query: string): boolean {
  const terms = searchTerms(query);
  if (terms.length === 0) return true;
  const haystack = fields
    .filter((value) => value != null && String(value).trim().length > 0)
    .map((value) => String(value).toLocaleLowerCase())
    .join(" ");
  return terms.every((term) => haystack.includes(term));
}
