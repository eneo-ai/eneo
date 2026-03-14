/** @typedef {import('../client/client').IntricError} IntricError */
/** @typedef {import('../types/resources').User} User */
/** @typedef {import('../types/resources').UserSparse} UserSparse */
/** @typedef {import('../types/resources').Tenant} Tenant */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initUser(client) {
  return {
    /**
     * Get info about the currently logged in user.
     * @returns {Promise<import('../types/schema').components["schemas"]["UserPublic"]>}
     * @throws {IntricError}
     * */
    me: async () => {
      const res = await client.fetch("/api/v1/users/me/", { method: "get" });
      return res;
    },

    /**
     * Get info about the currently logged in user's tenant.
     * @returns {Promise<Tenant>}
     * @throws {IntricError}
     * */
    tenant: async () => {
      const res = await client.fetch("/api/v1/users/tenant/", { method: "get" });
      return res;
    },

    /**
     * Generate a new api-key for the currently logged in user.
     * WARNING: Will delete any old api-key!
     * @returns {Promise<{truncated_key: string; key: string;}>}
     * @throws {IntricError}
     * */
    generateApiKey: async () => {
      const res = await client.fetch("/api/v1/users/api-keys/", { method: "get" });
      return res;
    },

    /**
     * Revoke the caller's legacy (v1) API key. Permanent action.
     * @returns {Promise<boolean>} Returns true on success
     * @throws {IntricError}
     * */
    revokeLegacyApiKey: async () => {
      await client.fetch("/api/v1/users/api-keys/legacy", { method: "delete" });
      return true;
    },

    /**
     * Lists all users on this tenant.
     * @overload `{includeDetails: true}` requires super user privileges.
     * @param {{includeDetails: true, search_email?: string, search_name?: string, page?: number, page_size?: number, state_filter?: string}} options
     * @return {Promise<import('../types/resources').Paginated<User>>}
     *
     * @overload
     * @param {{includeDetails?: false, filter?: string, limit?: number, cursor?: string}} [options]
     * @return {Promise<import('../types/resources').Paginated<UserSparse>> }
     *
     * @param {{includeDetails: boolean, filter?: string, limit?: number, cursor?: string, search_email?: string, search_name?: string, page?: number, page_size?: number, state_filter?: string}} [options]
     * @throws {IntricError}
     * */
    list: async (options) => {
      if (options && options.includeDetails) {
        // Backend returns { items: User[], metadata: {...} }
        const res = await client.fetch("/api/v1/admin/users/", {
          method: "get",
          params: {
            query: {
              page: options.page,
              page_size: options.page_size,
              search_email: options.search_email,
              search_name: options.search_name,
              state_filter: options.state_filter
            }
          }
        });

        // Return full response with items and metadata (for pagination and counts)
        return res;
      }

      const res = await client.fetch("/api/v1/users/", {
        method: "get",
        params: {
          query: { email: options?.filter, limit: options?.limit, cursor: options?.cursor }
        }
      });
      return res;
    },

    /**
     * Registers a new user for the current tenant. Requires super user privileges.
     * @param {import('../types/fetch').JSONRequestBody<"post", "/api/v1/admin/users/">} user
     * @returns {Promise<User>} Returns the created user
     * @throws {IntricError}
     * */
    create: async (user) => {
      const res = await client.fetch("/api/v1/admin/users/", {
        method: "post",
        requestBody: {
          "application/json": user
        }
      });
      return res;
    },

    /**
     * "Invites" a new user for the current tenant. This will create a new user without activating it.
     * It is a prerequisite to be able to login via zitadel. On first zitadel login the user will become active.
     * The Requires super user privileges.
     * @param {import('../types/fetch').JSONRequestBody<"post", "/api/v1/users/admin/invite/">} user
     * @returns {Promise<User>} Returns the invited user
     * @throws {IntricError}
     * */
    invite: async (user) => {
      const res = await client.fetch("/api/v1/users/admin/invite/", {
        method: "post",
        requestBody: { "application/json": user }
      });
      return res;
    },

    /**
     * Delete an user by id. Requires super user privileges.
     * @param {{id: string}} user User to delete
     * @returns {Promise<boolean>} Returns true on success
     * @throws {IntricError}
     * */
    delete: async (user) => {
      const { id } = user;
      await client.fetch("/api/v1/users/admin/{id}/", {
        method: "delete",
        params: { path: { id } }
      });
      return true;
    },

    /**
     * Deactivate a user (temporary leave). Requires admin privileges.
     * @param {{user: {username: string}}} options User to deactivate
     * @returns {Promise<User>} Returns the deactivated user
     * @throws {IntricError}
     * */
    deactivate: async (options) => {
      const res = await client.fetch("/api/v1/admin/users/{username}/deactivate", {
        method: "post",
        params: { path: { username: options.user.username } }
      });
      return res;
    },

    /**
     * Reactivate a user (return from leave). Requires admin privileges.
     * @param {{user: {username: string}}} options User to reactivate
     * @returns {Promise<User>} Returns the reactivated user
     * @throws {IntricError}
     * */
    reactivate: async (options) => {
      const res = await client.fetch("/api/v1/admin/users/{username}/reactivate", {
        method: "post",
        params: { path: { username: options.user.username } }
      });
      return res;
    },

    /**
     * Update an existing user. Requires super user privileges.
     * @typedef {import('../types/fetch').JSONRequestBody<"post", "/api/v1/admin/users/{username}/">} UserLegacyUpdate
     * @typedef {import('../types/fetch').JSONRequestBody<"patch", "/api/v1/users/admin/{id}/">} UserUpdate
     * @param {{user: {id: string, username?: never}, update: UserUpdate} | {user: {username: string, id?: never}, update: UserLegacyUpdate}} params
     * @returns {Promise<User>}
     * @throws {IntricError}
     * */
    update: async (params) => {
      if ("username" in params.user && params.user.username) {
        const username = params.user.username;
        // We can cast this as we are on the "username" path
        const update = /** @type {UserLegacyUpdate} */ (params.update);
        const res = await client.fetch("/api/v1/admin/users/{username}/", {
          method: "post",
          params: { path: { username } },
          requestBody: { "application/json": update }
        });
        return res;
      }

      if ("id" in params.user && params.user.id) {
        const id = params.user.id;
        // We can cast this as we are on the "username" path
        const update = /** @type {UserUpdate} */ (params.update);
        const res = await client.fetch("/api/v1/users/admin/{id}/", {
          method: "patch",
          params: { path: { id } },
          requestBody: { "application/json": update }
        });
        return res;
      }

      throw Error("Either username or id are required to edit user");
    }
  };
}
