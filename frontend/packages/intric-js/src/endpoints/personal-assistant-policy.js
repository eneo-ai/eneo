/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initPersonalAssistantPolicy(client) {
  return {
    /**
     * Get the tenant's personal assistant policy (auto-creates an empty one if none exists).
     * Admin only.
     * @throws {IntricError}
     */
    get: async () => {
      const res = await client.fetch("/api/v1/admin/personal-assistant-policy/", {
        method: "get"
      });
      return res;
    },

    /**
     * Update the tenant's personal assistant policy. Only the provided
     * dimensions (models_restriction / mcp_restriction / prompt_enforcement)
     * are touched.
     * @param {Object} params
     * @param {{enabled: boolean, models: {completion_model_id: string, is_default: boolean}[], provider_ids: string[]} | null} [params.models_restriction]
     * @param {{enabled: boolean, server_ids: string[]} | null} [params.mcp_restriction]
     * @param {{enabled: boolean, prompt_library_id: string | null} | null} [params.prompt_enforcement]
     * @throws {IntricError}
     */
    update: async ({ models_restriction, mcp_restriction, prompt_enforcement }) => {
      /** @type {Record<string, unknown>} */
      const body = {};
      if (models_restriction !== undefined) body.models_restriction = models_restriction;
      if (mcp_restriction !== undefined) body.mcp_restriction = mcp_restriction;
      if (prompt_enforcement !== undefined) body.prompt_enforcement = prompt_enforcement;
      const res = await client.fetch("/api/v1/admin/personal-assistant-policy/", {
        method: "put",
        requestBody: { "application/json": body }
      });
      return res;
    }
  };
}
