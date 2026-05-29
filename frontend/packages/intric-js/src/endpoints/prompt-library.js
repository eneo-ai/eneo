/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initPromptLibrary(client) {
  return {
    /**
     * List all prompt library entries for the current tenant (admin only).
     * @throws {IntricError}
     */
    list: async () => {
      const res = await client.fetch("/api/v1/admin/prompt-library/", {
        method: "get"
      });
      return res;
    },

    /**
     * Get a single prompt library entry by ID (admin only).
     * @param {Object} params
     * @param {string} params.id Entry ID
     * @throws {IntricError}
     */
    get: async ({ id }) => {
      const res = await client.fetch("/api/v1/admin/prompt-library/{id}/", {
        method: "get",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * List saved versions for a prompt library entry (admin only).
     * @param {Object} params
     * @param {string} params.id Entry ID
     * @throws {IntricError}
     */
    versions: async ({ id }) => {
      const res = await client.fetch("/api/v1/admin/prompt-library/{id}/versions/", {
        method: "get",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Create a new prompt library entry (admin only).
     * @param {Object} params
     * @param {string} params.name Display name (unique per tenant)
     * @param {string} params.text Prompt text
     * @param {string | null} [params.description] Optional description
     * @throws {IntricError}
     */
    create: async ({ name, text, description = null }) => {
      const res = await client.fetch("/api/v1/admin/prompt-library/", {
        method: "post",
        requestBody: {
          "application/json": { name, text, description }
        }
      });
      return res;
    },

    /**
     * Update an existing prompt library entry (admin only).
     * Only the provided fields are changed.
     * @param {Object} params
     * @param {string} params.id Entry ID
     * @param {string} [params.name] New display name
     * @param {string} [params.text] New prompt text
     * @param {string | null} [params.description] New description; pass null to clear
     * @throws {IntricError}
     */
    update: async ({ id, name, text, description }) => {
      /** @type {Record<string, unknown>} */
      const body = {};
      if (name !== undefined) body.name = name;
      if (text !== undefined) body.text = text;
      if (description !== undefined) body.description = description;
      const res = await client.fetch("/api/v1/admin/prompt-library/{id}/", {
        method: "put",
        params: { path: { id } },
        requestBody: { "application/json": body }
      });
      return res;
    },

    /**
     * Delete a prompt library entry (admin only).
     * Fails with 409 if the entry is referenced by a personal assistant governance policy.
     * @param {Object} params
     * @param {string} params.id Entry ID
     * @throws {IntricError}
     */
    delete: async ({ id }) => {
      await client.fetch("/api/v1/admin/prompt-library/{id}/", {
        method: "delete",
        params: { path: { id } }
      });
    }
  };
}
