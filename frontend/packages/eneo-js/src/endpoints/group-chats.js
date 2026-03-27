/** @typedef {import('../client/client').EneoError} EneoError */
/** @typedef {import('../types/resources').GroupChat} GroupChat */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initGroupChats(client) {
  return {
    /**
     * Create a new Group Chat
     * @param {{spaceId: string, name: string}} groupChat
     * @throws {EneoError}
     * */
    create: async (groupChat) => {
      const { spaceId: id, name } = groupChat;
      const res = await client.fetch("/api/v1/spaces/{id}/applications/group-chats/", {
        method: "post",
        params: {
          path: {
            id
          }
        },
        requestBody: {
          "application/json": { name }
        }
      });
      return res;
    },

    /**
     * Get info of an group chat via its id.
     * @param  {{id: string} | GroupChat} groupChat group chat
     * @returns {Promise<GroupChat>} Full info about the queried group chat
     * @throws {EneoError}
     * */
    get: async (groupChat) => {
      const { id } = groupChat;
      const res = await client.fetch("/api/v1/group-chats/{id}/", {
        method: "get",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Update a Group Chat
     * @param {Object} params
     * @param {{id: string} | GroupChat} params.groupChat The group chat you want to update
     * @param {import('../types/fetch').JSONRequestBody<"patch","/api/v1/group-chats/{id}/">} params.update - Either provide the updated group chat or the parameters to update.
     * @returns {Promise<GroupChat>}
     * @throws {EneoError}
     * */
    update: async ({ groupChat, update }) => {
      const res = await client.fetch("/api/v1/group-chats/{id}/", {
        method: "patch",
        params: {
          path: {
            id: groupChat.id
          }
        },
        requestBody: {
          "application/json": update
        }
      });
      return res;
    },

    /**
     * Delete a specific group chat
     * @param  {{id: string} | GroupChat} groupChat group chat
     * @returns {Promise<true>} true on success, otherwise throws
     * @throws {EneoError}
     * */
    delete: async (groupChat) => {
      const { id } = groupChat;
      await client.fetch("/api/v1/group-chats/{id}/", {
        method: "delete",
        params: { path: { id } }
      });
      return true;
    },

    /**
     * Publish an group chat inside its space
     * @param  {{id: string} | GroupChat} groupChat chat
     * @returns {Promise<GroupChat>}
     * */
    publish: async (groupChat) => {
      const { id } = groupChat;
      const res = await client.fetch("/api/v1/group-chats/{id}/publish/", {
        method: "post",
        params: {
          path: { id },
          query: { published: true }
        }
      });

      return res;
    },

    /**
     * Unpublish an group chat inside its space
     * @param  {{id: string} | GroupChat} groupChat chat
     * @returns {Promise<GroupChat>}
     * */
    unpublish: async (groupChat) => {
      const { id } = groupChat;
      const res = await client.fetch("/api/v1/group-chats/{id}/publish/", {
        method: "post",
        params: {
          path: { id },
          query: { published: false }
        }
      });

      return res;
    }
  };
}
