import {
  publishedCandidates,
  serverCandidates,
  skillCandidates,
  toolCandidates,
  type ReferenceCatalog
} from "@eneo/skill-instructions";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { SKILL_CATALOG_PAGE_SIZE } from "./skill-binding-catalog";
import type { SkillScope } from "./skill-revisions";

export function skillReferenceCatalog(scope: SkillScope, currentId?: string): ReferenceCatalog {
  return {
    key: `${scope.type === "organization" ? "organization" : scope.spaceId}:${currentId ?? "new"}`,
    async skills(query, cursor, signal) {
      if (scope.type === "organization") {
        const page = await unwrap(
          browserApi.GET("/api/v1/skills/catalogue/", {
            params: {
              query: { limit: SKILL_CATALOG_PAGE_SIZE, cursor, search: query || undefined }
            },
            signal
          })
        );
        return {
          items: publishedCandidates(page.items, currentId),
          nextCursor: page.next_cursor ?? null
        };
      }
      const page = await unwrap(
        browserApi.GET("/api/v1/spaces/{space_id}/skills/", {
          params: {
            path: { space_id: scope.spaceId },
            query: { limit: SKILL_CATALOG_PAGE_SIZE, cursor, q: query || undefined }
          },
          signal
        })
      );
      return {
        items: skillCandidates(page.items, currentId),
        nextCursor: page.next_cursor ?? null
      };
    },
    async servers(signal) {
      const page = await unwrap(
        browserApi.GET("/api/v1/mcp-servers/", {
          params: { query: { purpose: "general" } },
          signal
        })
      );
      return serverCandidates(page.items);
    },
    async tools(serverId, signal) {
      const page = await unwrap(
        browserApi.GET("/api/v1/mcp-servers/{id}/tools/", {
          params: { path: { id: serverId } },
          signal
        })
      );
      return toolCandidates(page.items);
    },
    async preview(candidate, signal) {
      const target = candidate.target;
      if (target.kind !== "skill") return candidate.description;
      if (scope.type === "organization") {
        const skill = await unwrap(
          browserApi.GET("/api/v1/skills/catalogue/{skill_id}/", {
            params: { path: { skill_id: target.skill_id } },
            signal
          })
        );
        if (skill.revision.id !== target.revision_id)
          throw new Error(
            "The published Skill version changed. Refresh the catalogue before adding it."
          );
        return skill.revision.instructions;
      }
      const revision = await unwrap(
        browserApi.GET("/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/{revision_id}/", {
          params: {
            path: {
              space_id: scope.spaceId,
              skill_id: target.skill_id,
              revision_id: target.revision_id
            }
          },
          signal
        })
      );
      return revision.instructions;
    }
  };
}
