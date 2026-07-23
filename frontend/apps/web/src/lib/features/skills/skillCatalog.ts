import type { SkillCatalogPage, SkillSparse } from "@eneo/eneo-js";

export type { SkillCatalogPage } from "@eneo/eneo-js";

export const SKILL_CATALOG_PAGE_SIZE = 25;
export const SKILL_CATALOG_SEARCH_DEBOUNCE_MS = 250;

export type CatalogItem = { id: string };

export type CatalogPage<T extends CatalogItem> = {
  items: T[];
  next_cursor?: string | null;
};

export type ListCatalogPage<T extends CatalogItem> = (params: {
  limit: number;
  cursor?: string | null;
  query?: string | null;
}) => Promise<CatalogPage<T>>;

export type ListSkills = ListCatalogPage<SkillSparse>;

export function emptySkillCatalogPage(): SkillCatalogPage {
  return {
    items: [],
    count: 0,
    total_count: 0,
    limit: SKILL_CATALOG_PAGE_SIZE,
    next_cursor: null,
    previous_cursor: null
  };
}

export function mergeCatalogPages<T extends CatalogItem>(current: T[], incoming: T[]): T[] {
  const merged = new Map(current.map((skill) => [skill.id, skill]));
  for (const skill of incoming) merged.set(skill.id, skill);
  return [...merged.values()];
}
