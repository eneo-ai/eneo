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
/** @typedef {import('../types/schema').components['schemas']['ExpiringKeysSummary']} ExpiringKeysSummary */
/** @typedef {import('../types/schema').components['schemas']['ApiKeyNotificationPreferencesResponse']} ApiKeyNotificationPreferences */
/** @typedef {import('../types/schema').components['schemas']['ApiKeyNotificationPreferencesUpdate']} ApiKeyNotificationPreferencesUpdate */
/** @typedef {import('../types/schema').components['schemas']['ApiKeyNotificationPolicyResponse']} ApiKeyNotificationPolicy */
/** @typedef {import('../types/schema').components['schemas']['ApiKeyNotificationPolicyUpdate']} ApiKeyNotificationPolicyUpdate */
/** @typedef {import('../types/schema').components['schemas']['ApiKeyExactLookupResponse']} ApiKeyExactLookupResponse */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initApiKeys(client) {
  return {
    /**
     * List API keys for the current user (scoped by permissions).
     * @param {{limit?: number, cursor?: string, previous?: boolean, scope_type?: ApiKeyScopeType | null, scope_id?: string, state?: ApiKeyState | null, key_type?: ApiKeyType | null, ownership?: "user" | "service" | null}} [params]
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
     * Rotate an API key. Optionally also change the expiration in the same call.
     * @param {{id: string, update_expiration?: boolean, expires_at?: string | null}} params
     * @returns {Promise<ApiKeyCreatedResponse>}
     * @throws {IntricError}
     * */
    rotate: async ({ id, update_expiration, expires_at }) => {
      if (update_expiration) {
        const options = /** @type {any} */ ({
          method: "post",
          params: { path: { id } },
          requestBody: {
            "application/json": { update_expiration: true, expires_at: expires_at ?? null }
          }
        });
        return await client.fetch("/api/v1/api-keys/{id}/rotate", options);
      }
      return await client.fetch("/api/v1/api-keys/{id}/rotate", {
        method: "post",
        params: { path: { id } }
      });
    },

    /**
     * Change the expiration of an API key. Pass null to remove expiration if policy allows.
     * @param {{id: string, expires_at: string | null}} params
     * @returns {Promise<ApiKeyV2>}
     * @throws {IntricError}
     * */
    extend: async ({ id, expires_at }) => {
      const options = /** @type {any} */ ({
        method: "post",
        params: { path: { id } },
        requestBody: { "application/json": { expires_at } }
      });
      return await client.fetch("/api/v1/api-keys/{id}/extend", options);
    },

    /**
     * Permanently delete a revoked or expired API key.
     * @param {{id: string}} params
     * @returns {Promise<void>}
     * @throws {IntricError}
     * */
    purge: async ({ id }) => {
      await client.fetch("/api/v1/api-keys/{id}/purge", {
        method: "post",
        params: { path: { id } }
      });
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
     * Get API key usage timeline.
     * @param {{id: string, limit?: number, cursor?: string}} params
     * @returns {Promise<{summary: object, items: object[], limit: number, next_cursor?: string | null}>}
     * @throws {IntricError}
     * */
    getUsage: async ({ id, limit, cursor }) => {
      const res = await client.fetch("/api/v1/api-keys/{id}/usage", {
        method: "get",
        params: {
          path: { id },
          query: { limit, cursor }
        }
      });
      return res;
    },

    /**
     * Get tenant API key policy constraints (expiration limits, rate limit ceiling,
     * rotation grace). Applies to creation, rotation, and expiration changes.
     * @returns {Promise<ApiKeyCreationConstraints>}
     * @throws {IntricError}
     * */
    getPolicyConstraints: async () => {
      const res = await client.fetch("/api/v1/api-keys/policy-constraints", {
        method: "get"
      });
      return res;
    },

    /**
     * Get expiring API key summary (user-scoped visibility).
     * @param {{days?: number, mode?: "all"|"subscribed"}} [params]
     * @returns {Promise<ExpiringKeysSummary>}
     * @throws {IntricError}
     * */
    expiringSoon: async (params) => {
      const res = await client.fetch("/api/v1/api-keys/expiring-soon", {
        method: "get",
        params: { query: params }
      });
      return res;
    },

    /**
     * Get API key notification preferences for current user.
     * @returns {Promise<ApiKeyNotificationPreferences>}
     * @throws {IntricError}
     * */
    getNotificationPreferences: async () => {
      const res = await client.fetch("/api/v1/api-keys/notification-preferences", {
        method: "get"
      });
      return res;
    },

    /**
     * Update API key notification preferences for current user.
     * @param {ApiKeyNotificationPreferencesUpdate} updates
     * @returns {Promise<ApiKeyNotificationPreferences>}
     * @throws {IntricError}
     * */
    updateNotificationPreferences: async (updates) => {
      const res = await client.fetch("/api/v1/api-keys/notification-preferences", {
        method: "put",
        requestBody: {
          "application/json": updates
        }
      });
      return res;
    },

    /**
     * List followed notification targets for subscribed mode.
     * @returns {Promise<{items: Array<{target_type: "key"|"assistant"|"app"|"space", target_id: string}>}>}
     * @throws {IntricError}
     * */
    listNotificationSubscriptions: async () => {
      const res = await client.fetch("/api/v1/api-keys/notification-subscriptions", {
        method: "get"
      });
      return res;
    },

    /**
     * Follow a notification target.
     * @param {{target_type: "key"|"assistant"|"app"|"space", target_id: string}} params
     * @returns {Promise<{items: Array<{target_type: "key"|"assistant"|"app"|"space", target_id: string}>}>}
     * @throws {IntricError}
     * */
    followNotificationTarget: async ({ target_type, target_id }) => {
      const res = await client.fetch(
        "/api/v1/api-keys/notification-subscriptions/{target_type}/{target_id}",
        {
          method: "put",
          params: {
            path: { target_type, target_id }
          }
        }
      );
      return res;
    },

    /**
     * Unfollow a notification target.
     * @param {{target_type: "key"|"assistant"|"app"|"space", target_id: string}} params
     * @returns {Promise<{items: Array<{target_type: "key"|"assistant"|"app"|"space", target_id: string}>}>}
     * @throws {IntricError}
     * */
    unfollowNotificationTarget: async ({ target_type, target_id }) => {
      const res = await client.fetch(
        "/api/v1/api-keys/notification-subscriptions/{target_type}/{target_id}",
        {
          method: "delete",
          params: {
            path: { target_type, target_id }
          }
        }
      );
      return res;
    },

    admin: {
      /**
       * List all API keys in the tenant (admin only).
       * @param {{limit?: number, cursor?: string, previous?: boolean, scope_type?: ApiKeyScopeType | null, scope_id?: string, state?: ApiKeyState | null, key_type?: ApiKeyType | null, owner_user_id?: string, created_by_user_id?: string, user_relation?: "owner"|"creator", search?: string, expires_within_days?: number}} [params]
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
       * Get expiring API key summary (tenant-wide, admin only).
       * @param {{days?: number}} [params]
       * @returns {Promise<ExpiringKeysSummary>}
       * @throws {IntricError}
       * */
      expiringSoon: async (params) => {
        const res = await client.fetch("/api/v1/admin/api-keys/expiring-soon", {
          method: "get",
          params: { query: params }
        });
        return res;
      },

      /**
       * Find an API key by exact full secret within current tenant (admin only).
       * @param {{secret: string}} params
       * @returns {Promise<ApiKeyExactLookupResponse>}
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
       * Rotate an API key (admin only). Optionally also change the expiration in the same call.
       * @param {{id: string, update_expiration?: boolean, expires_at?: string | null}} params
       * @returns {Promise<ApiKeyCreatedResponse>}
       * @throws {IntricError}
       * */
      rotate: async ({ id, update_expiration, expires_at }) => {
        if (update_expiration) {
          const options = /** @type {any} */ ({
            method: "post",
            params: { path: { id } },
            requestBody: {
              "application/json": { update_expiration: true, expires_at: expires_at ?? null }
            }
          });
          return await client.fetch("/api/v1/admin/api-keys/{id}/rotate", options);
        }
        return await client.fetch("/api/v1/admin/api-keys/{id}/rotate", {
          method: "post",
          params: { path: { id } }
        });
      },

      /**
       * Change the expiration of an API key (admin only).
       * @param {{id: string, expires_at: string | null}} params
       * @returns {Promise<ApiKeyV2>}
       * @throws {IntricError}
       * */
      extend: async ({ id, expires_at }) => {
        const options = /** @type {any} */ ({
          method: "post",
          params: { path: { id } },
          requestBody: { "application/json": { expires_at } }
        });
        return await client.fetch("/api/v1/admin/api-keys/{id}/extend", options);
      },

      /**
       * Permanently delete a revoked or expired API key (admin only).
       * @param {{id: string}} params
       * @returns {Promise<void>}
       * @throws {IntricError}
       * */
      purge: async ({ id }) => {
        await client.fetch("/api/v1/admin/api-keys/{id}/purge", {
          method: "post",
          params: { path: { id } }
        });
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
       * Fetch tenant API key notification policy (admin only).
       * @returns {Promise<ApiKeyNotificationPolicy>}
       * @throws {IntricError}
       * */
      getNotificationPolicy: async () => {
        const res = await client.fetch("/api/v1/admin/api-keys/notification-policy", {
          method: "get"
        });
        return res;
      },

      /**
       * Update tenant API key notification policy (admin only).
       * @param {ApiKeyNotificationPolicyUpdate} updates
       * @returns {Promise<ApiKeyNotificationPolicy>}
       * @throws {IntricError}
       * */
      updateNotificationPolicy: async (updates) => {
        const res = await client.fetch("/api/v1/admin/api-keys/notification-policy", {
          method: "put",
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
