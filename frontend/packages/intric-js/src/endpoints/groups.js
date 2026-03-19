/** @typedef {import('../types/resources').InfoBlob} InfoBlob */
/** @typedef {import('../types/resources').Group} Group */
/** @typedef {import('../client/client').IntricError} IntricError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initGroups(client) {
  return {
    /**
     * List all groups.

     * @returns {Promise<Group[]>} Will include shared groups if requested
     * @throws {IntricError}
     * */
    list: async () => {
      const res = await client.fetch("/api/v1/groups/", {
        method: "get"
      });

      return res.items;
    },

    /**
     * Create a new group.
     * @param {import('../types/fetch').JSONRequestBody<"post", "/api/v1/groups/"> | {spaceId: string, name: string, embedding_model?: {id: string}}} group
     * @returns The newly created group
     * @throws {IntricError}
     * */
    create: async (group) => {
      if ("spaceId" in group) {
        const { spaceId: id, name, embedding_model } = group;
        const res = await client.fetch("/api/v1/spaces/{id}/knowledge/groups/", {
          method: "post",
          params: {
            path: {
              id
            }
          },
          requestBody: {
            "application/json": { name, embedding_model }
          }
        });
        return res;
      }

      const res = await client.fetch("/api/v1/groups/", {
        method: "post",
        requestBody: { "application/json": group }
      });
      return res;
    },

    /**
     * Transfer a group into a different space. Needs matching embedding model to be available
     * Will throw error if not possible
     * @param {{group: {id: string}, targetSpace: {id: string}}} params
     * @throws {IntricError}
     * */
    transfer: async ({ group, targetSpace }) => {
      const { id } = group;
      await client.fetch("/api/v1/groups/{id}/transfer/", {
        method: "post",
        params: { path: { id } },
        requestBody: {
          "application/json": {
            target_space_id: targetSpace.id
          }
        }
      });
      return true;
    },

    /**
     * Get info of a group via its id.
     * @param  {{id: string} | Group} group group
     * @returns {Promise<Group>} Full info about the queried group
     * @throws {IntricError}
     * */
    get: async (group) => {
      const { id } = group;
      const res = await client.fetch("/api/v1/groups/{id}/", {
        method: "get",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Update an existing group.
     * @param {Object} params
     * @param {{id: string} | Group} params.group The group you want to update
     * @param {import('../types/fetch').JSONRequestBody<"post", "/api/v1/groups/{id}/">} params.update - Either provide the updated group or the parameters to update.
     * @returns {Promise<Group>} The updated group
     * */
    update: async ({ group, update }) => {
      const { id } = group;
      const res = await client.fetch("/api/v1/groups/{id}/", {
        method: "post",
        params: { path: { id } },
        requestBody: { "application/json": update }
      });
      return res;
    },

    /**
     * Delete the specified group.
     * @param {{id: string} | Group} group - Either provide the group to delete or a specified id.
     * @returns {Promise<any>} The deleted group
     * */
    delete: async (group) => {
      const { id } = group;
      const res = await client.fetch("/api/v1/groups/{id}/", {
        method: "delete",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * List all `InfoBlob`s associated with a group.
     * @param {{id: string} | Group} group Specify a group to list`InfoBlob`s
     * @returns {Promise<Omit<InfoBlob, "text">[]>}
     * */
    listInfoBlobs: async (group) => {
      const { id } = group;
      const res = await client.fetch("/api/v1/groups/{id}/info-blobs/", {
        method: "get",
        params: { path: { id } }
      });
      return res.items;
    }
  };
}
