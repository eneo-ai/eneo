/** @typedef {import('../types/resources').Assistant} Assistant */
/** @typedef {import('../types/resources').AssistantSession} AssistantSession */
/** @typedef {import('../types/resources').AssistantResponse} AssistantResponse */
/** @typedef {import('../types/resources').Group} Group */
/** @typedef {import('../types/resources').PromptSparse} PromptSparse */
/** @typedef {import('../client/client').IntricError} IntricError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initAssistants(client) {
  return {
    /**
     * List all assistants.
     * @param {{includeTenant?: boolean} | undefined} [options] Include all assistant's of this tenant (requires superuser)? Default to `false`
     * @returns {Promise<Assistant[]>}
     * @throws {IntricError}
     * */
    list: async (options) => {
      const for_tenant = options?.includeTenant ?? false;

      const res = await client.fetch("/api/v1/assistants/", {
        method: "get",
        params: { query: { for_tenant } }
      });
      return res.items;
    },

    /**
     * Create a new assistant
     * @param {import('../types/fetch').JSONRequestBody<"post", "/api/v1/assistants/"> | ({spaceId: string} & import('../types/fetch').JSONRequestBody<"post", "/api/v1/spaces/{id}/applications/assistants/">)} assistant
     * @throws {IntricError}
     * */
    create: async (assistant) => {
      if ("spaceId" in assistant) {
        const { spaceId: id, name, from_template } = assistant;
        const res = await client.fetch("/api/v1/spaces/{id}/applications/assistants/", {
          method: "post",
          params: {
            path: {
              id
            }
          },
          requestBody: {
            "application/json": { name, from_template }
          }
        });
        return res;
      }

      const res = await client.fetch("/api/v1/assistants/", {
        method: "post",
        requestBody: {
          "application/json": assistant
        }
      });
      return res;
    },

    /**
     * Transfer an assistant into a different space. Needs matching models to be available
     * Will throw error if not possible
     * @param {{assistant: {id: string}, targetSpace: {id: string}, moveResources?: boolean}} params
     * @throws {IntricError}
     * */
    transfer: async ({ assistant, targetSpace, moveResources }) => {
      const { id } = assistant;
      await client.fetch("/api/v1/assistants/{id}/transfer/", {
        method: "post",
        params: { path: { id } },
        requestBody: {
          "application/json": {
            target_space_id: targetSpace.id,
            move_resources: moveResources
          }
        }
      });
      return true;
    },

    /**
     * Get info of an assistant via its id.
     * @param  {{id: string} | Assistant} assistant assistant
     * @returns {Promise<Assistant>} Full info about the queried assistant
     * @throws {IntricError}
     * */
    get: async (assistant) => {
      const { id } = assistant;
      const res = await client.fetch("/api/v1/assistants/{id}/", {
        method: "get",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Update an existing assistant.
     * @param {Object} params
     * @param {{id: string} | Assistant} params.assistant The assistant you want to update
     * @param {import('../types/fetch').JSONRequestBody<"post", "/api/v1/assistants/{id}/">} params.update - Either provide the updated assistant or the parameters to update.
     * @returns {Promise<Assistant>} The updated assistant
     * */
    update: async ({ assistant, update }) => {
      const { id } = assistant;
      // We want to set the update to null instead of to an empty string
      update.description = update.description?.trim() === "" ? null : update.description;
      const res = await client.fetch("/api/v1/assistants/{id}/", {
        method: "post",
        params: { path: { id } },
        requestBody: { "application/json": update }
      });
      return res;
    },

    /**
     * Delete a specific assistant.
     * @param  {{id: string} | Assistant} assistant assistant
     * @returns {Promise<true>} true on success, otherwise throws
     * @throws {IntricError}
     * */
    delete: async (assistant) => {
      const { id } = assistant;
      await client.fetch("/api/v1/assistants/{id}/", {
        method: "delete",
        params: { path: { id } }
      });
      return true;
    },

    /**
     * Ask an assistant a question. By default the answer is streamed from the backend, you can act on partial answer updates
     * with the onChunk callback. Once the answer has been fully received a complete `Session` object will be returned.
     * @param {Object} params Ask parameters
     * @param  {{id: string} | Assistant} params.assistant Which assistant to ask
     * @param {{id: string | null} | AssistantSession | undefined} params.session Session Id of a session to continue, `null` to start a new session
     * @param {string} params.question Question to ask
     * @param {{id: string}[] | undefined} params.files Question to ask
     * @param {(partialResponse: AssistantResponse, controller: AbortController) => void} [params.onAnswer] Callback to run when a new token/word of the answer is received
     * @param {(response: Response) => Promise<void>} [params.onOpen] Callback to run once the initial response of the backend is received
     * @param {AbortController} [params.abortController] Optionally pass in an AbortController that can abort the stream
     * @returns {Promise<AssistantResponse>} Once the full answer is received it will be returned
     * @throws {IntricError}
     * */
    ask: async ({ assistant, session, question, files, onAnswer, onOpen, abortController }) => {
      const { id } = assistant;
      const session_id = session?.id ?? undefined;

      let answer = "";
      /** @type AssistantResponse */
      let response = {};

      const endpoint = session_id
        ? "/api/v1/assistants/{id}/sessions/{session_id}/"
        : "/api/v1/assistants/{id}/sessions/";

      await client.stream(
        endpoint,
        {
          params: { path: { id, session_id }, query: { version: 2 } },
          requestBody: { "application/json": { question, files, stream: true } }
        },
        {
          onOpen: async (response) => {
            if (onOpen) onOpen(response);
          },
          onMessage: (ev, controller) => {
            if (ev.data == "") return;
            try {
              const data = JSON.parse(ev.data);
              response = data;
              if (data.answer) {
                answer += data.answer;
                if (onAnswer) onAnswer(data, controller);
              }
            } catch (e) {
              return;
            }
          }
        },
        abortController
      );

      response.question = question;
      response.answer = answer;
      return response;
    },

    /**
     * List all sessions of an assistant.
     * @param {Object} params
     * @param {{id: string} | Assistant} params.assistant
     * @param {{limit?: number, cursor?: string | undefined }} [params.pagination] - The number of sessions to retrieve.
     * @throws {IntricError}
     * */
    listSessions: async ({ assistant, pagination }) => {
      const { id } = assistant;
      const res = await client.fetch("/api/v1/assistants/{id}/sessions/", {
        method: "get",
        params: { path: { id }, query: pagination }
      });
      return res;
    },

    /**
     * Get a specific session of an assistant. This will also load the message history for this specific session
     * @param {Object} params
     * @param {{id: string}} params.assistant
     * @param {{id: string}} params.session
     * @returns {Promise<AssistantSession>}
     * @throws {IntricError}
     * */
    getSession: async ({ assistant, session }) => {
      const { id } = assistant;
      const { id: session_id } = session;
      const res = await client.fetch("/api/v1/assistants/{id}/sessions/{session_id}/", {
        method: "get",
        params: { path: { id, session_id } }
      });
      return res;
    },

    /**
     * Delete a specific session of an assistant. Returns the deleted session.
     * @param {Object} params
     * @param {{id: string} | Assistant} params.assistant
     * @param {{id: string} | AssistantSession} params.session
     * @returns {Promise<AssistantSession>}
     * @throws {IntricError}
     * */
    deleteSession: async ({ assistant, session }) => {
      const { id } = assistant;
      const { id: session_id } = session;
      const res = await client.fetch("/api/v1/assistants/{id}/sessions/{session_id}/", {
        method: "delete",
        params: { path: { id, session_id } }
      });
      return res;
    },

    /**
     * Get the list of prompt history for an assistant.
     * @param  {{id: string} | Assistant} assistant
     * @returns {Promise<PromptSparse[]>}
     * */
    listPrompts: async (assistant) => {
      const { id } = assistant;
      const res = await client.fetch("/api/v1/assistants/{id}/prompts/", {
        method: "get",
        params: { path: { id } }
      });
      return res.items;
    },

    /**
     * Publish an assistant inside its space
     * @param  {{id: string} | Assistant} assistant
     * @returns {Promise<Assistant>}
     * */
    publish: async (assistant) => {
      const { id } = assistant;
      const res = await client.fetch("/api/v1/assistants/{id}/publish/", {
        method: "post",
        params: {
          path: { id },
          query: { published: true }
        }
      });

      return res;
    },

    /**
     * Unpublish an assistant inside its space
     * @param  {{id: string} | Assistant} assistant
     * @returns {Promise<Assistant>}
     * */
    unpublish: async (assistant) => {
      const { id } = assistant;
      const res = await client.fetch("/api/v1/assistants/{id}/publish/", {
        method: "post",
        params: {
          path: { id },
          query: { published: false }
        }
      });

      return res;
    },

    /**
     * Get all MCP servers associated with an assistant
     * @param {{id: string}} params
     * @returns {Promise<{items: Array}>}
     * */
    listMCPServers: async ({ id }) => {
      const res = await client.fetch("/api/v1/assistants/{id}/mcp-servers/", {
        method: "get",
        params: {
          path: { id }
        }
      });

      return res;
    },

    /**
     * Add an MCP server to an assistant
     * @param {{id: string}} assistant
     * @param {{id: string}} mcpServer
     * @returns {Promise<{success: boolean}>}
     * */
    addMCPServer: async ({ assistant, mcpServer }) => {
      const res = await client.fetch("/api/v1/assistants/{id}/mcp-servers/{mcp_server_id}/", {
        method: "post",
        params: {
          path: {
            id: assistant.id,
            mcp_server_id: mcpServer.id
          }
        }
      });

      return res;
    },

    /**
     * Remove an MCP server from an assistant
     * @param {{id: string}} assistant
     * @param {{id: string}} mcpServer
     * @returns {Promise<void>}
     * */
    removeMCPServer: async ({ assistant, mcpServer }) => {
      await client.fetch("/api/v1/assistants/{id}/mcp-servers/{mcp_server_id}/", {
        method: "delete",
        params: {
          path: {
            id: assistant.id,
            mcp_server_id: mcpServer.id
          }
        }
      });
    }
  };
}
