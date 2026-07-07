export type SearchableSpaceResource = {
  name: string;
  description?: string | null;
  type?: string | null;
};

function searchableText(item: SearchableSpaceResource): string {
  return [item.name, item.description, item.type]
    .filter((value): value is string => typeof value === "string" && value.trim().length > 0)
    .join(" ")
    .toLocaleLowerCase();
}

export function filterSpaceResources<T extends SearchableSpaceResource>(
  items: T[],
  query: string
): T[] {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);

  if (terms.length === 0) return items;
  return items.filter((item) => {
    const haystack = searchableText(item);
    return terms.every((term) => haystack.includes(term));
  });
}
