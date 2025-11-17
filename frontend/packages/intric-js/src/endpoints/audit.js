/** @typedef {import('../client/client').IntricError} IntricError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initAudit(client) {
  return {
    /**
     * List audit logs with optional filtering and pagination.
     * @param {{actor_id?: string, action?: import('../types/schema').components["schemas"]["ActionType"], from_date?: string, to_date?: string, page?: number, page_size?: number}} [options]
     * @returns {Promise<import('../types/schema').components["schemas"]["AuditLogListResponse"]>}
     * @throws {IntricError}
     * */
    list: async (options) => {
      const res = await client.fetch("/api/v1/audit/logs", {
        method: "get",
        params: {
          query: options
        }
      });
      return res;
    },

    /**
     * Get audit logs for a specific user (GDPR export).
     * @param {{user_id: string, from_date?: string, to_date?: string, page?: number, page_size?: number}} options
     * @returns {Promise<import('../types/schema').components["schemas"]["AuditLogListResponse"]>}
     * @throws {IntricError}
     * */
    userLogs: async (options) => {
      const { user_id, ...query } = options;
      const res = await client.fetch("/api/v1/audit/logs/user/{user_id}", {
        method: "get",
        params: {
          path: { user_id },
          query
        }
      });
      return res;
    },

    /**
     * Export audit logs to CSV format.
     * @param {{user_id?: string, actor_id?: string, action?: import('../types/schema').components["schemas"]["ActionType"], from_date?: string, to_date?: string}} [options]
     * @returns {Promise<Blob>} CSV content as blob
     * @throws {IntricError}
     * */
    export: async (options) => {
      const res = await client.fetch("/api/v1/audit/logs/export", {
        method: "get",
        params: {
          query: options
        }
      });
      return res;
    },

    /**
     * Get retention policy for the current tenant.
     * @returns {Promise<{retention_days: number}>}
     * @throws {IntricError}
     * */
    getRetentionPolicy: async () => {
      const res = await client.fetch("/api/v1/audit/retention-policy", {
        method: "get"
      });
      return res;
    },

    /**
     * Update audit log retention policy for the current tenant. Requires admin privileges.
     * Note: Conversation retention is configured at Assistant/App/Space level, not here.
     * @param {{retention_days: number}} policy - Audit log retention in days (1-2555)
     * @returns {Promise<{retention_days: number}>}
     * @throws {IntricError}
     * */
    updateRetentionPolicy: async (policy) => {
      const res = await client.fetch("/api/v1/audit/retention-policy", {
        method: "put",
        requestBody: {
          "application/json": {
            retention_days: policy.retention_days
            // Conversation retention fields removed - only settable at Assistant/App/Space level
          }
        }
      });
      return res;
    },

    /**
     * Get audit category configuration for the current tenant. Requires admin privileges.
     * Returns all 7 audit categories with their enabled status, descriptions, action counts, and example actions.
     * @returns {Promise<{categories: Array<{category: string, enabled: boolean, description: string, action_count: number, example_actions: string[]}>}>}
     * @throws {IntricError}
     * */
    getConfig: async () => {
      const res = await client.fetch("/api/v1/audit/config", {
        method: "get"
      });
      return res;
    },

    /**
     * Update audit category configuration for the current tenant. Requires admin privileges.
     * Changes take effect immediately for new audit events. Historical logs are unaffected.
     * @param {{updates: Array<{category: string, enabled: boolean}>}} config - Category updates
     * @returns {Promise<{categories: Array<{category: string, enabled: boolean, description: string, action_count: number, example_actions: string[]}>}>}
     * @throws {IntricError}
     * */
    updateConfig: async (config) => {
      const res = await client.fetch("/api/v1/audit/config", {
        method: "patch",
        requestBody: {
          "application/json": config
        }
      });
      return res;
    }
  };
}
