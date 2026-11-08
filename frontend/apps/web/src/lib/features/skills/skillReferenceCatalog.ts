import type { Eneo } from "@eneo/eneo-js";
import {
  publishedCandidates,
  serverCandidates,
  skillCandidates,
  toolCandidates,
  type ReferenceCatalog
} from "@eneo/skill-instructions";

import { SKILL_CATALOG_PAGE_SIZE } from "./skillCatalog";

type Scope = { type: "organization" } | { type: "space"; spaceId: string };

export function skillReferenceCatalog(
  eneo: Eneo,
  scope: Scope,
  currentId?: string
): ReferenceCatalog {
  return {
    key: `${scope.type === "organization" ? "organization" : scope.spaceId}:${currentId ?? "new"}`,
    async skills(query, cursor, signal) {
      if (scope.type === "organization") {
        const page = await eneo.skills.catalogue.list({
          limit: SKILL_CATALOG_PAGE_SIZE,
          cursor,
          search: query || null
        });
        signal.throwIfAborted();
        return {
          items: publishedCandidates(page.items, currentId),
          nextCursor: page.next_cursor ?? null
        };
      }
      const page = await eneo.skills.list({
        spaceId: scope.spaceId,
        limit: SKILL_CATALOG_PAGE_SIZE,
        cursor,
        query: query.trim() || null
      });
      signal.throwIfAborted();
      return {
        items: skillCandidates(page.items, currentId),
        nextCursor: page.next_cursor ?? null
      };
    },
    async servers(signal) {
      const page = await eneo.mcpServers.list({ purpose: "general" });
      signal.throwIfAborted();
      return serverCandidates(page.items);
    },
    async tools(serverId, signal) {
      const page = await eneo.mcpServers.listTools({ mcp_server_id: serverId });
      signal.throwIfAborted();
      return toolCandidates(page.items);
    },
    async preview(candidate, signal) {
      const target = candidate.target;
      if (target.kind !== "skill") return candidate.description;
      if (scope.type === "organization") {
        const skill = await eneo.skills.catalogue.get({ skillId: target.skill_id });
        signal.throwIfAborted();
        if (skill.revision.id !== target.revision_id)
          throw new Error(
            "The published Skill version changed. Refresh the catalogue before adding it."
          );
        return skill.revision.instructions;
      }
      const revision = await eneo.skills.getRevision({
        spaceId: scope.spaceId,
        skillId: target.skill_id,
        revisionId: target.revision_id
      });
      signal.throwIfAborted();
      return revision.instructions;
    }
  };
}
