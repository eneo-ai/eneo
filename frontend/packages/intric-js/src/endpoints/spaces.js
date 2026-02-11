/** @typedef {import('../types/resources').Space} Space */
/** @typedef {import('../client/client').IntricError} IntricError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initSpaces(client) {
  return {
    /**
     * Lists all spaces the user can access.
     * @param {{include_personal?: boolean, include_applications?: boolean}} [options]
     * @throws {IntricError}
     * */
    list: async (options) => {
      const res = await client.fetch("/api/v1/spaces/", {
        method: "get",
        params: { query: options }
      });

      return res.items;
    },

    /**
     * Create a new space.
     * @param {import('../types/fetch').JSONRequestBody<"post", "/api/v1/spaces/">} space Pass a name for the space
     * @returns {Promise<Space>} The newly created space
     * @throws {IntricError}
     * */
    create: async (space) => {
      const res = await client.fetch("/api/v1/spaces/", {
        method: "post",
        requestBody: { "application/json": space }
      });
      return res;
    },

    /**
     * Get info of a space via its id.
     * @param  {{id: string}} space The space / id in question
     * @returns {Promise<Space>} Full info about the queried space
     * @throws {IntricError}
     * */
    get: async (space) => {
      const { id } = space;
      const res = await client.fetch("/api/v1/spaces/{id}/", {
        method: "get",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Get all applications of a space via its id.
     * @param  {{id: string}} space The space / id in question
     * @returns {Promise<Space["applications"]>} Full info about the queried space's applications
     * @throws {IntricError}
     * */
    listApplications: async (space) => {
      const { id } = space;
      const res = await client.fetch("/api/v1/spaces/{id}/applications/", {
        method: "get",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Get all applications of a space via its id.
     * @param  {{id: string}} space The space / id in question
     * @returns {Promise<Space["knowledge"]>} Full info about the queried space's applications
     * @throws {IntricError}
     * */
    listKnowledge: async (space) => {
      const { id } = space;
      const res = await client.fetch("/api/v1/spaces/{id}/knowledge/", {
        method: "get",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Get the user's personal space
     * @returns {Promise<Space>} Full info about the personal space
     * @throws {IntricError}
     * */
    getPersonalSpace: async () => {
      const res = await client.fetch("/api/v1/spaces/type/personal/", {
        method: "get"
      });
      return res;
    },

    /**
     * Get the user's organization space
     * @returns {Promise<Space>} Full info about the organization space
     * @throws {IntricError}
     * */
    getOrganizationSpace: async () => {
      const res = await client.fetch("/api/v1/spaces/type/organization/", {
        method: "get"
      });
      return res;
    },

    /**
     * Update an existing space.
     * @param {Object} params
     * @param {{id: string}} params.space The space you want to update
     * @param {import('../types/fetch').JSONRequestBody<"patch", "/api/v1/spaces/{id}/">} params.update - Either provide the updated space or the parameters to update.
     * @returns {Promise<Space>} The updated space
     * @throws {IntricError}
     * */
    update: async ({ space, update }) => {
      const { id } = space;
      const res = await client.fetch("/api/v1/spaces/{id}/", {
        method: "patch",
        params: { path: { id } },
        requestBody: { "application/json": update }
      });
      return res;
    },

    /**
     * Delete the specified space.
     * @param {{id: string}} space - Either provide the space to delete or a specified id.
     * @returns status 204 on success; should throw on error
     * @throws {IntricError}
     * */
    delete: async (space) => {
      const { id } = space;
      const res = await client.fetch("/api/v1/spaces/{id}/", {
        method: "delete",
        params: { path: { id } }
      });
      return res;
    },

    members: {
      /**
       * Add user to your space.
       * @param {{spaceId: string, user: import('../types/fetch').JSONRequestBody<"post", "/api/v1/spaces/{id}/members/">}} params - Provide a space, user id and role
       * @returns Added user
       * @throws {IntricError}
       * */
      add: async ({ spaceId, user }) => {
        const res = await client.fetch("/api/v1/spaces/{id}/members/", {
          method: "post",
          params: { path: { id: spaceId } },
          requestBody: {
            "application/json": user
          }
        });
        return res;
      },

      /**
       * Update the specified user's rola in a space.
       * @param {{spaceId: string, user: import('../types/fetch').JSONRequestBody<"post", "/api/v1/spaces/{id}/members/">}} params
       * @returns Updated user
       * @throws {IntricError}
       * */
      update: async ({ spaceId, user }) => {
        const user_id = user.id;
        const role = user.role;
        const res = await client.fetch("/api/v1/spaces/{id}/members/{user_id}/", {
          method: "patch",
          params: { path: { id: spaceId, user_id } },
          requestBody: {
            "application/json": { role }
          }
        });
        return res;
      },

      /**
       * Remove a user from a space
       * @param {{spaceId: string, user: {id: string}}} params
       * @returns {Promise<true>} True if the user was removed
       * @throws {IntricError} Throws if user can't be removed
       * */
      remove: async ({ spaceId, user }) => {
        const user_id = user.id;
        await client.fetch("/api/v1/spaces/{id}/members/{user_id}/", {
          method: "delete",
          params: { path: { id: spaceId, user_id } }
        });
        return true;
      }
    },

    groupMembers: {
      /**
       * List all user groups that are members of a space.
       * @param {{spaceId: string}} params - Space ID
       * @returns Group members list
       * @throws {IntricError}
       * */
      list: async ({ spaceId }) => {
        const res = await client.fetch("/api/v1/spaces/{id}/group-members/", {
          method: "get",
          params: { path: { id: spaceId } }
        });
        return res.items;
      },

      /**
       * Add a user group to a space.
       * @param {{spaceId: string, group: {id: string, role: string}}} params - Space ID and group with role
       * @returns Added group member
       * @throws {IntricError}
       * */
      add: async ({ spaceId, group }) => {
        const res = await client.fetch("/api/v1/spaces/{id}/group-members/", {
          method: "post",
          params: { path: { id: spaceId } },
          requestBody: {
            "application/json": group
          }
        });
        return res;
      },

      /**
       * Update the specified user group's role in a space.
       * @param {{spaceId: string, group: {id: string, role: string}}} params
       * @returns Updated group member
       * @throws {IntricError}
       * */
      update: async ({ spaceId, group }) => {
        const group_id = group.id;
        const role = group.role;
        const res = await client.fetch("/api/v1/spaces/{id}/group-members/{group_id}/", {
          method: "patch",
          params: { path: { id: spaceId, group_id } },
          requestBody: {
            "application/json": { role }
          }
        });
        return res;
      },

      /**
       * Remove a user group from a space
       * @param {{spaceId: string, group: {id: string}}} params
       * @returns {Promise<true>} True if the group was removed
       * @throws {IntricError} Throws if group can't be removed
       * */
      remove: async ({ spaceId, group }) => {
        const group_id = group.id;
        await client.fetch("/api/v1/spaces/{id}/group-members/{group_id}/", {
          method: "delete",
          params: { path: { id: spaceId, group_id } }
        });
        return true;
      }
    }
  };
}
