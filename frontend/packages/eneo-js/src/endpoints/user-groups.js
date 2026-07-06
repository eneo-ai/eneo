/** @typedef {import('../client/client').EneoError} EneoError */
/** @typedef {import('../types/resources').User} User */
/** @typedef {import('../types/resources').UserGroup} UserGroup */
/** @typedef {import('../types/resources').Tenant} Tenant */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initUserGroups(client) {
  return {
    /**
     * Lists all user-groups on this tenant.
     * @returns {Promise<UserGroup[]>}
     * @throws {EneoError}
     * */
    list: async () => {
      const res = await client.fetch("/api/v1/user-groups/", { method: "get" });
      return res.items;
    },

    /**
     * Creates a new user-group for the current tenant.
     * @param {Object} params
     * @param {string} params.name A name for the new user-group
     * @returns {Promise<UserGroup>} Returns the created user-group
     * @throws {EneoError}
     * */
    create: async ({ name }) => {
      const res = await client.fetch("/api/v1/user-groups/", {
        method: "post",
        requestBody: {
          "application/json": {
            name
          }
        }
      });
      return res;
    },

    /**
     * Get a user-group by its id.
     * @param {{id: string} | UserGroup} userGroup User group to get
     * @returns {Promise<UserGroup>}
     * @throws {EneoError}
     * */
    get: async (userGroup) => {
      const { id } = userGroup;
      const res = await client.fetch("/api/v1/user-groups/{id}/", {
        method: "get",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Delete a user-group by its id.
     * @param {{id: string} | UserGroup} userGroup User group to delete
     * @returns {Promise<UserGroup>} Returns the deleted group on success
     * @throws {EneoError}
     * */
    delete: async (userGroup) => {
      const { id } = userGroup;
      const res = await client.fetch("/api/v1/user-groups/{id}/", {
        method: "delete",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Update an existing user-group.
     * @param {Object} params
     * @param {{id: string} | UserGroup} params.userGroup Group to update
     * @param {import('../types/fetch').JSONRequestBody<"post", "/api/v1/user-groups/{id}/">} params.update Supply properties to update.
     * @returns {Promise<UserGroup>} Returns the updated group.
     * @throws {EneoError}
     * */
    update: async ({ userGroup, update }) => {
      const { id } = userGroup;
      const res = await client.fetch("/api/v1/user-groups/{id}/", {
        method: "post",
        params: { path: { id } },
        requestBody: { "application/json": update }
      });
      return res;
    },

    /**
     * Add s specific user
     * @param {Object} params
     * @param {{id: string} | UserGroup} params.userGroup Group to add to
     * @param {{id: string} | User} params.user The user to add
     * @returns {Promise<UserGroup>} Returns the updated group.
     * @throws {EneoError}
     * */
    addUser: async ({ userGroup, user }) => {
      const { id } = userGroup;
      const user_id = user.id;

      const res = await client.fetch("/api/v1/user-groups/{id}/users/{user_id}/", {
        method: "post",
        params: {
          path: {
            id,
            user_id
          }
        }
      });

      return res;
    },

    /** Remove a specific user
     * @param {Object} params
     * @param {{id: string} | UserGroup} params.userGroup Group to remove from
     * @param {{id: string} | User} params.user The user to remove
     * @returns {Promise<UserGroup>} Returns the updated group.
     * @throws {EneoError}
     * */
    removeUser: async ({ userGroup, user }) => {
      const { id } = userGroup;
      const user_id = user.id;

      const res = await client.fetch("/api/v1/user-groups/{id}/users/{user_id}/", {
        method: "delete",
        params: {
          path: {
            id,
            user_id
          }
        }
      });

      return res;
    }
  };
}
