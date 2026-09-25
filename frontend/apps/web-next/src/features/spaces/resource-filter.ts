/**
 * Free-text filtering for the space pages' search boxes: every whitespace-
 * separated term must occur (case-insensitively) in one of the values. Astryx
 * Table's filtering plugin covers per-column filters; a single "find the row
 * I am thinking of" box is plain substring matching, as in Astryx's own
 * table-page template.
 */
export type SearchValue = string | number | null | undefined;

function searchTerms(query: string): string[] {
  return query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
}

/** Whether every term of `query` occurs in one of `values`. A blank query matches. */
export function matchesSearch(values: readonly SearchValue[], query: string): boolean {
  const terms = searchTerms(query);
  if (terms.length === 0) return true;
  const haystack = values
    .filter((value) => value != null && String(value).trim().length > 0)
    .map((value) => String(value).toLocaleLowerCase())
    .join(" ");
  return terms.every((term) => haystack.includes(term));
}

export type SearchableSpaceResource = {
  name: string;
  description?: string | null;
  type?: string | null;
};

/** Assistants, apps, services and spaces by name, description and type. */
export function filterSpaceResources<T extends SearchableSpaceResource>(
  items: T[],
  query: string
): T[] {
  if (searchTerms(query).length === 0) return items;
  return items.filter((item) => matchesSearch([item.name, item.description, item.type], query));
}
