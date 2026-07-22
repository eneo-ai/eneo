import type { Eneo } from "@eneo/eneo-js";
import { SKILL_CATALOG_PAGE_SIZE, type CatalogPage } from "./skillCatalog";
import { mergeSkillCatalog, type SkillBindingCandidate } from "./skillBindings";

type CatalogSource = "published" | "space";
type CatalogCursor = { source: CatalogSource; cursor: string | null };

export type SkillBindingCatalogPage = CatalogPage<SkillBindingCandidate> & {
  count: number;
  limit: number;
};

export type ListSkillBindingCatalog = (params: {
  limit: number;
  cursor?: string | null;
  query?: string | null;
}) => Promise<SkillBindingCatalogPage>;

export function emptySkillBindingCatalogPage(): SkillBindingCatalogPage {
  return {
    items: [],
    count: 0,
    limit: SKILL_CATALOG_PAGE_SIZE,
    next_cursor: null
  };
}

/**
 * Presents approved organisation Skills and local Space Skills as one bounded
 * catalogue. The opaque cursor finishes the approved source before advancing
 * into local Skills, so every request remains server-paginated and searchable.
 */
export async function loadSkillBindingCatalogPage({
  eneo,
  spaceId,
  organizationSpace,
  limit = SKILL_CATALOG_PAGE_SIZE,
  cursor = null,
  query = null
}: {
  eneo: Eneo;
  spaceId: string;
  organizationSpace: boolean;
  limit?: number;
  cursor?: string | null;
  query?: string | null;
}): Promise<SkillBindingCatalogPage> {
  const state = decodeCursor(cursor);
  const normalizedQuery = query?.trim() || null;

  if (state.source === "space") {
    if (organizationSpace) return emptySkillBindingCatalogPage();
    const page = await eneo.skills.list({
      spaceId,
      limit,
      cursor: state.cursor,
      query: normalizedQuery
    });
    return createPage(page.items, limit, nextCursor("space", page.next_cursor));
  }

  const publishedPage = await eneo.skills.catalogue.list({
    limit,
    cursor: state.cursor,
    search: normalizedQuery
  });
  const published = publishedPage.items;
  if (publishedPage.next_cursor) {
    return createPage(published, limit, encodeCursor("published", publishedPage.next_cursor));
  }
  if (organizationSpace) return createPage(published, limit, null);
  if (published.length >= limit) {
    return createPage(published, limit, encodeCursor("space", null));
  }

  const localPage = await eneo.skills.list({
    spaceId,
    limit: limit - published.length,
    cursor: null,
    query: normalizedQuery
  });
  return createPage(
    mergeSkillCatalog(localPage.items, published),
    limit,
    nextCursor("space", localPage.next_cursor)
  );
}

function createPage(
  items: SkillBindingCandidate[],
  limit: number,
  nextCursorValue: string | null
): SkillBindingCatalogPage {
  return {
    items,
    count: items.length,
    limit,
    next_cursor: nextCursorValue
  };
}

function nextCursor(source: CatalogSource, cursor: string | null | undefined): string | null {
  return cursor ? encodeCursor(source, cursor) : null;
}

function encodeCursor(source: CatalogSource, cursor: string | null): string {
  return encodeURIComponent(JSON.stringify({ source, cursor } satisfies CatalogCursor));
}

function decodeCursor(value: string | null): CatalogCursor {
  if (value === null) return { source: "published", cursor: null };
  try {
    const parsed: unknown = JSON.parse(decodeURIComponent(value));
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "source" in parsed &&
      (parsed.source === "published" || parsed.source === "space") &&
      "cursor" in parsed &&
      (typeof parsed.cursor === "string" || parsed.cursor === null)
    ) {
      return { source: parsed.source, cursor: parsed.cursor };
    }
  } catch {
    // The cursor is an internal UI continuation token; reject corrupted state.
  }
  throw new Error("Invalid Skill catalogue cursor");
}
