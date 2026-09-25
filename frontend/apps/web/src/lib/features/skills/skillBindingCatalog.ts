import type { Eneo, PublishedSkillPublic } from "@eneo/eneo-js";
import { SKILL_CATALOG_PAGE_SIZE, type CatalogPage } from "./skillCatalog";
import {
  getSkillCandidateRevisionId,
  mergeSkillCatalog,
  type SkillBindingCandidate,
  type SkillBindingRevisionMetadata
} from "./skillBindings";

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

export type SkillBindingPreviewTarget = Pick<
  SkillBindingRevisionMetadata,
  "id" | "source" | "slug" | "revisionId" | "displayName" | "description"
>;

export type SkillBindingPreview = SkillBindingRevisionMetadata & {
  instructions: string;
};

export type GetSkillBindingPreview = (
  target: SkillBindingPreviewTarget
) => Promise<SkillBindingPreview>;

export function skillBindingPreviewTarget(skill: SkillBindingCandidate): SkillBindingPreviewTarget {
  return {
    id: skill.id,
    source: skill.source,
    slug: skill.slug,
    revisionId: getSkillCandidateRevisionId(skill),
    displayName: skill.display_name,
    description: skill.description
  };
}

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
    return createPage(
      page.items.map((skill) => ({ ...skill, source: "space" as const })),
      limit,
      nextCursor("space", page.next_cursor)
    );
  }

  const publishedPage = await eneo.skills.catalogue.list({
    limit,
    cursor: state.cursor,
    search: normalizedQuery
  });
  const published = publishedPage.items.map((skill) => ({
    ...skill,
    source: "organization" as const
  }));
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
    mergeSkillCatalog(
      localPage.items.map((skill) => ({ ...skill, source: "space" as const })),
      published
    ),
    limit,
    nextCursor("space", localPage.next_cursor)
  );
}

export async function loadSkillBindingPreview({
  eneo,
  spaceId,
  target
}: {
  eneo: Eneo;
  spaceId: string;
  target: SkillBindingPreviewTarget;
}): Promise<SkillBindingPreview> {
  if (target.source === "organization") {
    return publishedSkillPreview(await eneo.skills.catalogue.get({ skillId: target.id }));
  }

  const revision = await eneo.skills.getRevision({
    spaceId,
    skillId: target.id,
    revisionId: target.revisionId
  });
  return {
    id: target.id,
    source: "space",
    slug: target.slug,
    revisionId: revision.id,
    revisionNumber: revision.revision_number,
    displayName: revision.display_name,
    description: revision.description,
    instructions: revision.instructions
  };
}

export function publishedSkillPreview(skill: PublishedSkillPublic): SkillBindingPreview {
  return {
    id: skill.id,
    source: "organization",
    slug: skill.slug,
    revisionId: skill.revision.id,
    revisionNumber: skill.revision.revision_number,
    displayName: skill.revision.display_name,
    description: skill.revision.description,
    instructions: skill.revision.instructions
  };
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
