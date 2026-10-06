import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type SkillCandidate =
  | (Schema<"PublishedSkillSummaryPublic"> & { source: "organization" })
  | (Schema<"SkillSparse"> & { source: "space" });
type Source = "published" | "space";
type Cursor = { source: Source; cursor: string | null };
export type SkillCatalogPage = { items: SkillCandidate[]; next_cursor: string | null };
export const SKILL_CATALOG_PAGE_SIZE = 25;

function decodeCursor(value: string | null): Cursor {
  if (value === null) return { source: "published", cursor: null };
  try {
    const parsed: unknown = JSON.parse(decodeURIComponent(value));
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "source" in parsed &&
      "cursor" in parsed &&
      (parsed.source === "published" || parsed.source === "space") &&
      (typeof parsed.cursor === "string" || parsed.cursor === null)
    )
      return { source: parsed.source, cursor: parsed.cursor };
  } catch {
    /* This token is local to the picker; reject corrupted state. */
  }
  throw new Error("Invalid Skill catalogue cursor");
}

function encodeCursor(source: Source, cursor: string | null) {
  return encodeURIComponent(JSON.stringify({ source, cursor } satisfies Cursor));
}

function appendDistinct(local: SkillCandidate[], published: SkillCandidate[]) {
  const items = new Map(local.map((skill) => [skill.id, skill]));
  for (const skill of published) items.set(skill.id, skill);
  return [...items.values()];
}

/** One cursor traverses published organization Skills, then local Space Skills. */
export async function loadSkillBindingCatalog({
  spaceId,
  organizationSpace,
  cursor = null,
  search = "",
  limit = SKILL_CATALOG_PAGE_SIZE
}: {
  spaceId: string;
  organizationSpace: boolean;
  cursor?: string | null;
  search?: string;
  limit?: number;
}): Promise<SkillCatalogPage> {
  const state = decodeCursor(cursor);
  const query = search.trim() || undefined;
  if (state.source === "space") {
    if (organizationSpace) return { items: [], next_cursor: null };
    const page = await unwrap(
      browserApi.GET("/api/v1/spaces/{space_id}/skills/", {
        params: { path: { space_id: spaceId }, query: { limit, cursor: state.cursor, q: query } }
      })
    );
    return {
      items: page.items.map((skill) => ({ ...skill, source: "space" as const })),
      next_cursor: page.next_cursor ? encodeCursor("space", page.next_cursor) : null
    };
  }
  const publishedPage = await unwrap(
    browserApi.GET("/api/v1/skills/catalogue/", {
      params: { query: { limit, cursor: state.cursor, search: query } }
    })
  );
  const published = publishedPage.items.map((skill) => ({
    ...skill,
    source: "organization" as const
  }));
  if (publishedPage.next_cursor)
    return { items: published, next_cursor: encodeCursor("published", publishedPage.next_cursor) };
  if (organizationSpace) return { items: published, next_cursor: null };
  if (published.length >= limit)
    return { items: published, next_cursor: encodeCursor("space", null) };
  const localPage = await unwrap(
    browserApi.GET("/api/v1/spaces/{space_id}/skills/", {
      params: {
        path: { space_id: spaceId },
        query: { limit: limit - published.length, cursor: null, q: query }
      }
    })
  );
  const local = localPage.items.map((skill) => ({ ...skill, source: "space" as const }));
  return {
    items: appendDistinct(local, published),
    next_cursor: localPage.next_cursor ? encodeCursor("space", localPage.next_cursor) : null
  };
}

export function candidateRevisionId(skill: SkillCandidate) {
  return skill.source === "organization" ? skill.revision_id : skill.current_revision_id;
}

export function candidateRevisionNumber(skill: SkillCandidate) {
  return skill.source === "organization" ? skill.revision_number : skill.current_revision_number;
}

export function isAttachable(skill: SkillCandidate) {
  return skill.source === "organization" ? !skill.execution_blocked : skill.is_active;
}

export type SkillPreviewTarget = {
  id: string;
  source: "organization" | "space";
  revisionId: string;
};

export async function getSkillPreviewForRevision(spaceId: string, target: SkillPreviewTarget) {
  if (target.source === "organization") {
    const published = await unwrap(
      browserApi.GET("/api/v1/skills/catalogue/{skill_id}/", {
        params: { path: { skill_id: target.id } }
      })
    );
    if (published.revision.id !== target.revisionId)
      throw new Error(
        "The published Skill version changed. Refresh the catalogue before adding it."
      );
    return {
      id: published.id,
      revisionId: published.revision.id,
      revisionNumber: published.revision.revision_number,
      displayName: published.revision.display_name,
      description: published.revision.description,
      instructions: published.revision.instructions
    };
  }
  const revision = await unwrap(
    browserApi.GET("/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/{revision_id}/", {
      params: { path: { space_id: spaceId, skill_id: target.id, revision_id: target.revisionId } }
    })
  );
  return {
    id: target.id,
    revisionId: revision.id,
    revisionNumber: revision.revision_number,
    displayName: revision.display_name,
    description: revision.description,
    instructions: revision.instructions
  };
}

export async function getSkillPreview(spaceId: string, skill: SkillCandidate) {
  return getSkillPreviewForRevision(spaceId, {
    id: skill.id,
    source: skill.source,
    revisionId: candidateRevisionId(skill)
  });
}
