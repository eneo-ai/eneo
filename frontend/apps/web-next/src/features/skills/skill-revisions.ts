import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { ORGANIZATION_SKILLS_KEY } from "./organization-skills";

export type SkillScope = { type: "organization" } | { type: "space"; spaceId: string };

export function skillQueryKey(scope: SkillScope): readonly string[] {
  return scope.type === "organization" ? ORGANIZATION_SKILLS_KEY : ["space-skills", scope.spaceId];
}

export function listSkillRevisions(scope: SkillScope, skillId: string, cursor: string | null) {
  if (scope.type === "organization")
    return unwrap(
      browserApi.GET("/api/v1/skills/organization/{skill_id}/revisions/", {
        params: { path: { skill_id: skillId }, query: { cursor } }
      })
    );
  return unwrap(
    browserApi.GET("/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/", {
      params: { path: { space_id: scope.spaceId, skill_id: skillId }, query: { cursor } }
    })
  );
}

export function getSkillRevision(scope: SkillScope, skillId: string, revisionId: string) {
  if (scope.type === "organization")
    return unwrap(
      browserApi.GET("/api/v1/skills/organization/{skill_id}/revisions/{revision_id}/", {
        params: { path: { skill_id: skillId, revision_id: revisionId } }
      })
    );
  return unwrap(
    browserApi.GET("/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/{revision_id}/", {
      params: { path: { space_id: scope.spaceId, skill_id: skillId, revision_id: revisionId } }
    })
  );
}

export function restoreSkillRevision(
  scope: SkillScope,
  skillId: string,
  sourceRevisionId: string,
  reviewedCurrentRevisionId: string
) {
  const body = { reviewed_current_revision_id: reviewedCurrentRevisionId };
  if (scope.type === "organization")
    return unwrap(
      browserApi.POST(
        "/api/v1/skills/organization/{skill_id}/revisions/{source_revision_id}/restore/",
        {
          params: { path: { skill_id: skillId, source_revision_id: sourceRevisionId } },
          body
        }
      )
    );
  return unwrap(
    browserApi.POST(
      "/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/{source_revision_id}/restore/",
      {
        params: {
          path: { space_id: scope.spaceId, skill_id: skillId, source_revision_id: sourceRevisionId }
        },
        body
      }
    )
  );
}
