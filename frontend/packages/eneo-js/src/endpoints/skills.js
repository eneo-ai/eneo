/** @typedef {import('../client/client').EneoError} EneoError */
/** @typedef {import('../types/resources').SkillPublic} SkillPublic */
/** @typedef {import('../types/resources').SkillRevisionPublic} SkillRevisionPublic */
/** @typedef {import('../types/resources').SkillRevisionRestorePublic} SkillRevisionRestorePublic */
/** @typedef {import('../types/resources').SkillRevisionSummaryPage} SkillRevisionSummaryPage */
/** @typedef {import('../types/resources').SkillSparse} SkillSparse */
/** @typedef {import('../types/resources').SkillBindingSummary} SkillBindingSummary */

/**
 * Skills require session authentication; API keys cannot use this surface.
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initSkills(client) {
  return {
    /**
     * List a bounded page of Skills available in a Space.
     * @param {{spaceId: string, limit?: number, cursor?: string | null, query?: string | null}} params
     * @returns {Promise<import('../types/resources').SkillCatalogPage>}
     * @throws {EneoError}
     */
    list: async ({ spaceId, limit, cursor, query }) => {
      return await client.fetch("/api/v1/spaces/{space_id}/skills/", {
        method: "get",
        params: {
          path: { space_id: spaceId },
          query: { limit, cursor, q: query }
        }
      });
    },

    /**
     * Get a Skill and its current revision.
     * @param {{spaceId: string, skillId: string}} params
     * @returns {Promise<SkillPublic>}
     * @throws {EneoError}
     */
    get: async ({ spaceId, skillId }) => {
      return await client.fetch("/api/v1/spaces/{space_id}/skills/{skill_id}/", {
        method: "get",
        params: { path: { space_id: spaceId, skill_id: skillId } }
      });
    },

    /**
     * Create a Skill and its first revision in a Space.
     * @param {{spaceId: string} & import('../types/fetch').JSONRequestBody<"post", "/api/v1/spaces/{space_id}/skills/">} params
     * @returns {Promise<SkillPublic>}
     * @throws {EneoError}
     */
    create: async ({ spaceId, ...skill }) => {
      return await client.fetch("/api/v1/spaces/{space_id}/skills/", {
        method: "post",
        params: { path: { space_id: spaceId } },
        requestBody: { "application/json": skill }
      });
    },

    /**
     * List immutable revision summaries using a stable cursor.
     * @param {{spaceId: string, skillId: string, limit?: number, cursor?: string | null}} params
     * @returns {Promise<SkillRevisionSummaryPage>}
     * @throws {EneoError}
     */
    listRevisionSummaries: async ({ spaceId, skillId, limit, cursor }) => {
      return await client.fetch("/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/", {
        method: "get",
        params: {
          path: { space_id: spaceId, skill_id: skillId },
          query: { limit, cursor }
        }
      });
    },

    /**
     * Get one immutable Skill revision with its full content.
     * @param {{spaceId: string, skillId: string, revisionId: string}} params
     * @returns {Promise<SkillRevisionPublic>}
     * @throws {EneoError}
     */
    getRevision: async ({ spaceId, skillId, revisionId }) => {
      return await client.fetch(
        "/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/{revision_id}/",
        {
          method: "get",
          params: {
            path: {
              space_id: spaceId,
              skill_id: skillId,
              revision_id: revisionId
            }
          }
        }
      );
    },

    /**
     * Create the next immutable revision for a Skill.
     * @param {{spaceId: string, skillId: string} & import('../types/fetch').JSONRequestBody<"post", "/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/">} params
     * @returns {Promise<SkillRevisionPublic>}
     * @throws {EneoError}
     */
    createRevision: async ({ spaceId, skillId, ...revision }) => {
      return await client.fetch("/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/", {
        method: "post",
        params: { path: { space_id: spaceId, skill_id: skillId } },
        requestBody: { "application/json": revision }
      });
    },

    /**
     * Copy one historical revision into the next immutable revision.
     * Existing revision-pinned bindings remain unchanged.
     * @param {{spaceId: string, skillId: string} & {sourceRevisionId: string} & import('../types/fetch').JSONRequestBody<"post", "/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/{source_revision_id}/restore/">} params
     * @returns {Promise<SkillRevisionRestorePublic>}
     * @throws {EneoError}
     */
    restoreRevision: async ({ spaceId, skillId, sourceRevisionId, ...restore }) => {
      return await client.fetch(
        "/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/{source_revision_id}/restore/",
        {
          method: "post",
          params: {
            path: {
              space_id: spaceId,
              skill_id: skillId,
              source_revision_id: sourceRevisionId
            }
          },
          requestBody: { "application/json": restore }
        }
      );
    },

    /**
     * Activate or deactivate a Skill without changing its revisions.
     * @param {{spaceId: string, skillId: string} & import('../types/fetch').JSONRequestBody<"patch", "/api/v1/spaces/{space_id}/skills/{skill_id}/active/">} params
     * @returns {Promise<SkillPublic>}
     * @throws {EneoError}
     */
    setActive: async ({ spaceId, skillId, ...update }) => {
      return await client.fetch("/api/v1/spaces/{space_id}/skills/{skill_id}/active/", {
        method: "patch",
        params: { path: { space_id: spaceId, skill_id: skillId } },
        requestBody: { "application/json": update }
      });
    },

    /**
     * Delete an unreferenced Skill.
     * @param {{spaceId: string, skillId: string}} params
     * @returns {Promise<void>}
     * @throws {EneoError}
     */
    delete: async ({ spaceId, skillId }) => {
      await client.fetch("/api/v1/spaces/{space_id}/skills/{skill_id}/", {
        method: "delete",
        params: { path: { space_id: spaceId, skill_id: skillId } }
      });
    },

    /**
     * List the ordered, revision-pinned Skills bound to an Assistant.
     * @param {{spaceId: string, assistantId: string}} params
     * @returns {Promise<SkillBindingSummary[]>}
     * @throws {EneoError}
     */
    listAssistantBindings: async ({ spaceId, assistantId }) => {
      return await client.fetch("/api/v1/spaces/{space_id}/assistants/{assistant_id}/skills/", {
        method: "get",
        params: { path: { space_id: spaceId, assistant_id: assistantId } }
      });
    },

    /**
     * List the ordered, revision-pinned Skills bound to an App.
     * @param {{spaceId: string, appId: string}} params
     * @returns {Promise<SkillBindingSummary[]>}
     * @throws {EneoError}
     */
    listAppBindings: async ({ spaceId, appId }) => {
      return await client.fetch("/api/v1/spaces/{space_id}/apps/{app_id}/skills/", {
        method: "get",
        params: { path: { space_id: spaceId, app_id: appId } }
      });
    }
  };
}
