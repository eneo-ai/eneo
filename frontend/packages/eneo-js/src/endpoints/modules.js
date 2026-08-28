/**
 * Administration contract for modules installed in the authenticated user's
 * organization. Tenant identity is intentionally never accepted here.
 *
 * @param {import('../client/client').Client} client
 */
export function initModules(client) {
  return {
    /**
     * @returns {Promise<import('../types/resources').ModuleInstallationList>}
     */
    list: async () => {
      return await client.fetch("/api/v1/admin/modules/", { method: "get" });
    },

    /**
     * List one bounded page of service keys eligible for module binding.
     * @param {{limit?: number, cursor?: string, search?: string}} [params]
     * @returns {Promise<import('../types/resources').ApiKeyListResponse>}
     */
    listServiceKeys: async (params) => {
      return await client.fetch("/api/v1/admin/modules/service-keys/", {
        method: "get",
        params: { query: params }
      });
    },

    /**
     * Resolve one service key only when it remains eligible for module binding.
     * @param {{serviceKeyId: string}} params
     * @returns {Promise<import('../types/resources').ApiKeyV2>}
     */
    getServiceKey: async ({ serviceKeyId }) => {
      return await client.fetch("/api/v1/admin/modules/service-keys/{service_key_id}/", {
        method: "get",
        params: { path: { service_key_id: serviceKeyId } }
      });
    },

    /**
     * Register, enable and fully configure a module in one idempotent command.
     * @param {{moduleKey: string, config: import('../types/resources').ModuleInstallationConfig}} params
     * @returns {Promise<import('../types/resources').ModuleInstallation>}
     */
    install: async ({ moduleKey, config }) => {
      return await client.fetch("/api/v1/admin/modules/{module_key}/", {
        method: "put",
        params: { path: { module_key: moduleKey } },
        requestBody: { "application/json": config }
      });
    },

    /**
     * @param {{moduleKey: string}} params
     * @returns {Promise<import('../types/resources').ModuleInstallationChange>}
     */
    uninstall: async ({ moduleKey }) => {
      return await client.fetch("/api/v1/admin/modules/{module_key}/", {
        method: "delete",
        params: { path: { module_key: moduleKey } }
      });
    }
  };
}

/** @typedef {import('../client/client').EneoError} EneoError */
