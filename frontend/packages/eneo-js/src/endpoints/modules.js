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
