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
     * Update retention policy for the current tenant. Requires admin privileges.
     * @param {{retention_days: number}} policy
     * @returns {Promise<{retention_days: number}>}
     * @throws {IntricError}
     * */
    updateRetentionPolicy: async (policy) => {
      const res = await client.fetch("/api/v1/audit/retention-policy", {
        method: "put",
        params: {
          query: {
            retention_days: policy.retention_days
          }
        }
      });
      return res;
    }
  };
}
