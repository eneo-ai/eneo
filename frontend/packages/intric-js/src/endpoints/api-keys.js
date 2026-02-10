/** @typedef {import('../client/client').IntricError} IntricError */
/** @typedef {import('../types/resources').ApiKeyV2} ApiKeyV2 */
/** @typedef {import('../types/resources').ApiKeyCreateRequest} ApiKeyCreateRequest */
/** @typedef {import('../types/resources').ApiKeyUpdateRequest} ApiKeyUpdateRequest */
/** @typedef {import('../types/resources').ApiKeyStateChangeRequest} ApiKeyStateChangeRequest */
/** @typedef {import('../types/resources').ApiKeyCreatedResponse} ApiKeyCreatedResponse */
/** @typedef {import('../types/resources').ApiKeyPolicy} ApiKeyPolicy */
/** @typedef {import('../types/resources').SuperApiKeyStatus} SuperApiKeyStatus */
/** @typedef {import('../types/resources').ApiKeyCreationConstraints} ApiKeyCreationConstraints */
/** @typedef {import('../types/resources').ApiKeyListResponse} ApiKeyPage */
/** @typedef {import('../types/resources').ApiKeyAdminListResponse} AdminApiKeyPage */
/** @typedef {import('../types/resources').ApiKeyScopeType} ApiKeyScopeType */
/** @typedef {import('../types/resources').ApiKeyState} ApiKeyState */
/** @typedef {import('../types/resources').ApiKeyType} ApiKeyType */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initApiKeys(client) {
  return {
    /**
     * List API keys for the current user (scoped by permissions).
     * @param {{limit?: number, cursor?: string, previous?: boolean, scope_type?: ApiKeyScopeType | null, scope_id?: string, state?: ApiKeyState | null, key_type?: ApiKeyType | null}} [params]
     * @returns {Promise<ApiKeyPage>}
     * @throws {IntricError}
     * */
    list: async (params) => {
      const res = await client.fetch("/api/v1/api-keys", {
        method: "get",
        params: { query: params }
      });
      return res;
    },

    /**
     * Get a specific API key by id.
     * @param {{id: string}} key
     * @returns {Promise<ApiKeyV2>}
     * @throws {IntricError}
     * */
    get: async (key) => {
      const { id } = key;
      const res = await client.fetch("/api/v1/api-keys/{id}", {
        method: "get",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Create a new API key.
     * @param {ApiKeyCreateRequest} request
     * @returns {Promise<ApiKeyCreatedResponse>}
     * @throws {IntricError}
     * */
    create: async (request) => {
      const res = await client.fetch("/api/v1/api-keys", {
        method: "post",
        requestBody: {
          "application/json": request
        }
      });
      return res;
    },

    /**
     * Update an API key.
     * @param {{id: string, update: ApiKeyUpdateRequest}} params
     * @returns {Promise<ApiKeyV2>}
     * @throws {IntricError}
     * */
    update: async ({ id, update }) => {
      const res = await client.fetch("/api/v1/api-keys/{id}", {
        method: "patch",
        params: { path: { id } },
        requestBody: {
          "application/json": update
        }
      });
      return res;
    },

    /**
     * Revoke an API key.
     * @param {{id: string, request?: ApiKeyStateChangeRequest}} params
     * @returns {Promise<ApiKeyV2>}
     * @throws {IntricError}
     * */
    revoke: async ({ id, request }) => {
      if (request) {
        const options = /** @type {any} */ ({
          method: "post",
          params: { path: { id } },
          requestBody: { "application/json": request }
        });
        return await client.fetch("/api/v1/api-keys/{id}/revoke", options);
      }
      return await client.fetch("/api/v1/api-keys/{id}/revoke", {
        method: "post",
        params: { path: { id } }
      });
    },

    /**
     * Rotate an API key.
     * @param {{id: string}} params
     * @returns {Promise<ApiKeyCreatedResponse>}
     * @throws {IntricError}
     * */
    rotate: async ({ id }) => {
      const res = await client.fetch("/api/v1/api-keys/{id}/rotate", {
        method: "post",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Suspend an API key.
     * @param {{id: string, request?: ApiKeyStateChangeRequest}} params
     * @returns {Promise<ApiKeyV2>}
     * @throws {IntricError}
     * */
    suspend: async ({ id, request }) => {
      if (request) {
        const options = /** @type {any} */ ({
          method: "post",
          params: { path: { id } },
          requestBody: { "application/json": request }
        });
        return await client.fetch("/api/v1/api-keys/{id}/suspend", options);
      }
      return await client.fetch("/api/v1/api-keys/{id}/suspend", {
        method: "post",
        params: { path: { id } }
      });
    },

    /**
     * Reactivate an API key.
     * @param {{id: string}} params
     * @returns {Promise<ApiKeyV2>}
     * @throws {IntricError}
     * */
    reactivate: async ({ id }) => {
      const res = await client.fetch("/api/v1/api-keys/{id}/reactivate", {
        method: "post",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Get creation constraints (policy limits) for the current user.
     * @returns {Promise<ApiKeyCreationConstraints>}
     * @throws {IntricError}
     * */
    getCreationConstraints: async () => {
      const res = await client.fetch("/api/v1/api-keys/creation-constraints", {
        method: "get"
      });
      return res;
    },

    admin: {
      /**
       * List all API keys in the tenant (admin only).
       * @param {{limit?: number, cursor?: string, previous?: boolean, scope_type?: ApiKeyScopeType | null, scope_id?: string, state?: ApiKeyState | null, key_type?: ApiKeyType | null, owner_user_id?: string, created_by_user_id?: string, user_relation?: "owner"|"creator", search?: string}} [params]
       * @returns {Promise<AdminApiKeyPage>}
       * @throws {IntricError}
       * */
      list: async (params) => {
        const res = await client.fetch("/api/v1/admin/api-keys", {
          method: "get",
          params: { query: params }
        });
        return res;
      },

      /**
       * Find an API key by exact full secret within current tenant (admin only).
       * @param {{secret: string}} params
       * @returns {Promise<{api_key: ApiKeyV2, match_reason: string}>}
       * @throws {IntricError}
       * */
      lookup: async ({ secret }) => {
        const res = await client.fetch("/api/v1/admin/api-keys/lookup", {
          method: "post",
          requestBody: {
            "application/json": { secret }
          }
        });
        return res;
      },

      /**
       * Get an API key by id (admin only).
       * @param {{id: string}} key
       * @returns {Promise<ApiKeyV2>}
       * @throws {IntricError}
       * */
      get: async ({ id }) => {
        const res = await client.fetch("/api/v1/admin/api-keys/{id}", {
          method: "get",
          params: { path: { id } }
        });
        return res;
      },

      /**
       * Update an API key (admin only).
       * @param {{id: string, update: ApiKeyUpdateRequest}} params
       * @returns {Promise<ApiKeyV2>}
       * @throws {IntricError}
       * */
      update: async ({ id, update }) => {
        const res = await client.fetch("/api/v1/admin/api-keys/{id}", {
          method: "patch",
          params: { path: { id } },
          requestBody: {
            "application/json": update
          }
        });
        return res;
      },

      /**
       * Revoke an API key (admin only).
       * @param {{id: string, request?: ApiKeyStateChangeRequest}} params
       * @returns {Promise<ApiKeyV2>}
       * @throws {IntricError}
       * */
      revoke: async ({ id, request }) => {
        if (request) {
          const options = /** @type {any} */ ({
            method: "post",
            params: { path: { id } },
            requestBody: { "application/json": request }
          });
          return await client.fetch("/api/v1/admin/api-keys/{id}/revoke", options);
        }
        return await client.fetch("/api/v1/admin/api-keys/{id}/revoke", {
          method: "post",
          params: { path: { id } }
        });
      },

      /**
       * Suspend an API key (admin only).
       * @param {{id: string, request?: ApiKeyStateChangeRequest}} params
       * @returns {Promise<ApiKeyV2>}
       * @throws {IntricError}
       * */
      suspend: async ({ id, request }) => {
        if (request) {
          const options = /** @type {any} */ ({
            method: "post",
            params: { path: { id } },
            requestBody: { "application/json": request }
          });
          return await client.fetch("/api/v1/admin/api-keys/{id}/suspend", options);
        }
        return await client.fetch("/api/v1/admin/api-keys/{id}/suspend", {
          method: "post",
          params: { path: { id } }
        });
      },

      /**
       * Reactivate an API key (admin only).
       * @param {{id: string}} params
       * @returns {Promise<ApiKeyV2>}
       * @throws {IntricError}
       * */
      reactivate: async ({ id }) => {
        const res = await client.fetch("/api/v1/admin/api-keys/{id}/reactivate", {
          method: "post",
          params: { path: { id } }
        });
        return res;
      },

      /**
       * Rotate an API key (admin only).
       * @param {{id: string}} params
       * @returns {Promise<ApiKeyCreatedResponse>}
       * @throws {IntricError}
       * */
      rotate: async ({ id }) => {
        const res = await client.fetch("/api/v1/admin/api-keys/{id}/rotate", {
          method: "post",
          params: { path: { id } }
        });
        return res;
      },

      /**
       * Get API key usage timeline for a key (admin only).
       * @param {{id: string, limit?: number, cursor?: string}} params
       * @returns {Promise<{summary: object, items: object[], limit: number, next_cursor?: string | null}>}
       * @throws {IntricError}
       * */
      getUsage: async ({ id, limit, cursor }) => {
        const res = await client.fetch("/api/v1/admin/api-keys/{id}/usage", {
          method: "get",
          params: {
            path: { id },
            query: { limit, cursor }
          }
        });
        return res;
      },

      /**
       * Fetch current tenant API key policy (admin only).
       * @returns {Promise<ApiKeyPolicy>}
       * @throws {IntricError}
       * */
      getPolicy: async () => {
        const res = await client.fetch("/api/v1/admin/api-key-policy", {
          method: "get"
        });
        return res;
      },

      /**
       * Update tenant API key policy (admin only).
       * @param {Partial<ApiKeyPolicy>} updates
       * @returns {Promise<ApiKeyPolicy>}
       * @throws {IntricError}
       * */
      updatePolicy: async (updates) => {
        const res = await client.fetch("/api/v1/admin/api-key-policy", {
          method: "patch",
          requestBody: {
            "application/json": updates
          }
        });
        return res;
      },

      /**
       * Fetch super key status (admin only).
       * @returns {Promise<SuperApiKeyStatus>}
       * @throws {IntricError}
       * */
      getSuperKeyStatus: async () => {
        const res = await client.fetch("/api/v1/admin/super-api-key-status", {
          method: "get"
        });
        return res;
      }
    }
  };
}
