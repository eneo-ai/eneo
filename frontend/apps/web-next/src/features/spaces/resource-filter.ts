import { matchesSearch, searchTerms } from "@/lib/search";

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
