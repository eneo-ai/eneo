/** @typedef {import('../client/client').IntricError} IntricError */
/** @typedef {import('../types/resources').TenantMetadataField} TenantMetadataField */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initSettings(client) {
  return {
    /**
     * Get settings for the current tenant
     * @throws {IntricError}
     * @returns {Promise<import('../types/resources').Settings>}
     */
    get: async () => {
      const res = await client.fetch("/api/v1/settings/", {
        method: "get"
      });
      return res;
    },

    /**
     * Update user settings
     * @param {import('../types/resources').SettingsInput} settings
     * @throws {IntricError}
     * @returns {Promise<import('../types/resources').Settings>}
     */
    update: async (settings) => {
      const res = await client.fetch("/api/v1/settings/", {
        method: "post",
        requestBody: { "application/json": settings }
      });
      return res;
    },

    /**
     * List tenant metadata field definitions
     * @throws {IntricError}
     * @returns {Promise<TenantMetadataField[]>}
     */
    listMetadataFields: async () => {
      const fetchAny = /** @type {any} */ (client.fetch);
      const res = /** @type {{ items?: TenantMetadataField[] }} */ (
        await fetchAny("/api/v1/settings/metadata-fields/", {
          method: "get"
        })
      );
      return res.items ?? [];
    },

    /**
     * @param {{name: string, field_type: import('../types/resources').MetadataFieldType, visible_on_assistants: boolean, visible_on_spaces: boolean}} field
     * @throws {IntricError}
     * @returns {Promise<TenantMetadataField>}
     */
    createMetadataField: async (field) => {
      const fetchAny = /** @type {any} */ (client.fetch);
      const res = await fetchAny("/api/v1/settings/metadata-fields/", {
        method: "post",
        requestBody: { "application/json": field }
      });
      return res;
    },

    /**
     * @param {{id: string} & {name: string, field_type: import('../types/resources').MetadataFieldType, visible_on_assistants: boolean, visible_on_spaces: boolean}} field
     * @throws {IntricError}
     * @returns {Promise<TenantMetadataField>}
     */
    updateMetadataField: async ({ id, ...field }) => {
      const fetchAny = /** @type {any} */ (client.fetch);
      const res = await fetchAny("/api/v1/settings/metadata-fields/{field_id}/", {
        method: "patch",
        params: { path: { field_id: id } },
        requestBody: { "application/json": field }
      });
      return res;
    },

    /**
     * @param {{id: string}} field
     * @throws {IntricError}
     * @returns {Promise<true>}
     */
    deleteMetadataField: async ({ id }) => {
      const fetchAny = /** @type {any} */ (client.fetch);
      await fetchAny("/api/v1/settings/metadata-fields/{field_id}/", {
        method: "delete",
        params: { path: { field_id: id } }
      });
      return true;
    },

    /**
     * Update template feature setting for the tenant
     * @param {boolean} enabled Whether to enable templates
     * @throws {IntricError}
     * @returns {Promise<import('../types/resources').Settings>}
     */
    updateTemplates: async (enabled) => {
      const res = await client.fetch("/api/v1/settings/templates", {
        method: "patch",
        requestBody: { "application/json": { enabled } }
      });
      return res;
    },

    /**
     * Update audit logging feature setting for the tenant
     * @param {boolean} enabled Whether to enable audit logging
     * @throws {IntricError}
     * @returns {Promise<import('../types/resources').Settings>}
     */
    updateAuditLogging: async (enabled) => {
      const res = await client.fetch("/api/v1/settings/audit-logging", {
        method: "patch",
        requestBody: { "application/json": { enabled } }
      });
      return res;
    },

    /**
     * Update JIT provisioning setting for the tenant
     * @param {boolean} enabled Whether to enable JIT provisioning (auto-create users on SSO login)
     * @throws {IntricError}
     * @returns {Promise<import('../types/resources').Settings>}
     */
    updateProvisioning: async (enabled) => {
      const res = await client.fetch("/api/v1/settings/provisioning", {
        method: "patch",
        requestBody: { "application/json": { enabled } }
      });
      return res;
    },

    /**
     * Update API key expiry notifications setting for the tenant
     * @param {boolean} enabled Whether to enable API key expiry notifications
     * @throws {IntricError}
     * @returns {Promise<import('../types/resources').Settings>}
     */
    updateApiKeyExpiryNotifications: async (enabled) => {
      const res = await client.fetch("/api/v1/settings/api-key-expiry-notifications", {
        method: "patch",
        requestBody: { "application/json": { enabled } }
      });
      return res;
    },

    /**
     * Set whether model input/output prices are shown to regular users (org-wide).
     * @param {boolean} enabled Whether to show model pricing to users
     * @throws {IntricError}
     * @returns {Promise<{ show_model_pricing: boolean }>}
     */
    updateModelPricingVisibility: async (enabled) => {
      const res = await client.fetch("/api/v1/admin/settings/model-pricing-visibility", {
        method: "put",
        requestBody: { "application/json": { show_model_pricing: enabled } }
      });
      return res;
    }
  };
}
