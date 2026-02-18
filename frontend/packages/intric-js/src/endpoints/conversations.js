/** @typedef {import('../types/resources').Assistant} Assistant */
/** @typedef {import('../types/resources').GroupChat} GroupChat */
/** @typedef {import('../types/resources').ChatPartner} ChatPartner */
/** @typedef {import('../types/resources').Conversation} Conversation */
/** @typedef {import('../types/resources').AssistantResponse} AssistantResponse */
/** @typedef {import('../types/resources').Group} Group */
/** @typedef {import('../types/resources').PromptSparse} PromptSparse */

import { IntricError } from "../client/client";

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initConversations(client) {
  return {
    /**
     * List all conversations of an assistant / group chat.
     * @param {Object} params
     * @param {ChatPartner} params.chatPartner
     * @param {{limit?: number, cursor?: string | undefined }} [params.pagination] - The number of sessions to retrieve.
     * @returns {Promise<import('../types/resources').Paginated<import("../types/resources").ConversationSparse>>} - Paginated list of sessions. Combines the pagination info with the items.
     * @throws {IntricError}
     * */
    list: async ({ chatPartner, pagination }) => {
      /**  @type {{assistant_id?: string, group_chat_id?: string}} */
      const target = { assistant_id: undefined, group_chat_id: undefined };

      if (chatPartner.type === "assistant" || chatPartner.type === "default-assistant") {
        target.assistant_id = chatPartner.id;
      } else if (chatPartner.type === "group-chat") {
        target.group_chat_id = chatPartner.id;
      } else {
        throw new IntricError(
          "Asking a question requires one of 'assistant' or 'groupChat' to be specified",
          "CONNECTION",
          0,
          0
        );
      }

      const res = await client.fetch("/api/v1/conversations/", {
        method: "get",
        params: { query: { ...pagination, ...target } }
      });
      return res;
    },

    /**
     * Get info of an conversatino via its id.
     * @param  {{id: string} | Conversation} conversation conversation
     * @returns {Promise<Conversation>} Full info about the queried assistant
     * @throws {IntricError}
     * */
    get: async (conversation) => {
      const { id: session_id } = conversation;
      const res = await client.fetch("/api/v1/conversations/{session_id}/", {
        method: "get",
        params: { path: { session_id } }
      });
      return res;
    },

    /**
     * Rename a conversation.
     * NOTE: This endpoint exists in backend, but the generated schema types may lag behind.
     * We intentionally bypass type checking here to keep runtime behavior working until types are regenerated.
     * @param  {{id: string} | Conversation} conversation conversation
     * @param  {{name: string}} body rename payload
     * @returns {Promise<Conversation>} Updated conversation
     * @throws {IntricError}
     * */
    rename: async (conversation, body) => {
      const { id: session_id } = conversation;

      const res = await client.fetch("/api/v1/conversations/{session_id}/name/", {
        method: "patch",
        params: { path: { session_id } },
        requestBody: {
          "application/json": body
        }
      });

      return res;
    },

    /**
     * Delete a specific conversation.
     * @param  {{id: string} | Conversation} conversation conversation
     * @returns {Promise<true>} true on success, otherwise throws
     * @throws {IntricError}
     * */
    delete: async (conversation) => {
      const { id: session_id } = conversation;
      await client.fetch("/api/v1/conversations/{session_id}/", {
        method: "delete",
        params: { path: { session_id } }
      });
      return true;
    },

    /**
     * Ask an assistant a question. By default the answer is streamed from the backend, you can act on partial answer updates
     * with the onChunk callback. Once the answer has been fully received a complete `Session` object will be returned.
     * @param {Object} params Ask parameters
     * @param {ChatPartner} [params.chatPartner] Which assistant to ask
     * @param {{id: string} | Conversation} [params.conversation]  Id of a conversation to continue
     * @param {string} params.question Question to ask
     * @param {{id: string}[] | undefined} params.files Files to pass on
     * @param {boolean} [params.useWebSearch] Should the assistant search the web? Defaults to false
     * @param {{assistants: {id: string; handle: string}[]} | undefined} [params.tools] Tool use
     * @param {Object} [params.callbacks]
     * @param {(data: import("../types/resources").SSE.FirstChunk) => void} [params.callbacks.onFirstChunk] Callback to run when the first chunk of the answer is received
     * @param {(data: import("../types/resources").SSE.Text) => void} [params.callbacks.onText] Callback to run when a new token/word of the answer is received
     * @param {(data: import("../types/resources").SSE.Files) => void} [params.callbacks.onImage] Callback to run when generated files of the answer is received
     * @param {(data: import("../types/resources").SSE.Intric) => void} [params.callbacks.onIntricEvent] Callback to run when an intric event is received
     * @param {(response: Response) => Promise<void>} [params.callbacks.onOpen] Callback to run once the initial response of the backend is received
     * @param {AbortController} [params.abortController] Optionally pass in an AbortController that can abort the stream
     * @throws {IntricError}
     * */
    ask: async ({
      chatPartner,
      conversation,
      question,
      files,
      tools,
      useWebSearch,
      abortController,
      callbacks
    }) => {
      /**  @type { {session_id?: string, assistant_id?: string, group_chat_id?: string}} */
      const target = { session_id: undefined, assistant_id: undefined, group_chat_id: undefined };

      if (conversation?.id && conversation.id.trim() !== "") {
        target.session_id = conversation.id;
      } else if (chatPartner?.id) {
        if (chatPartner.type === "assistant" || chatPartner.type === "default-assistant") {
          target.assistant_id = chatPartner.id;
        } else target.group_chat_id = chatPartner.id;
      } else {
        throw new IntricError(
          "Asking a question requires on of 'session', 'assistant', 'groupChat' to be specified",
          "CONNECTION",
          0,
          0
        );
      }

      /** @type {import("../types/resources").ConversationMessage} */
      // @ts-expect-error We rely on the fact that the first_chunk event will initialise the response
      let response = {};

      await client.stream(
        "/api/v1/conversations/",
        {
          params: { query: { version: 2 } },
          requestBody: {
            "application/json": {
              ...target,
              question,
              files,
              tools,
              stream: true,
              use_web_search: useWebSearch
            }
          }
        },
        {
          onOpen: async (response) => {
            callbacks?.onOpen?.(response);
          },
          onMessage: (ev) => {
            if (ev.data == "") return;
            try {
              const data = JSON.parse(ev.data);

              switch (ev.event) {
                case "first_chunk":
                  response = data;
                  callbacks?.onFirstChunk?.(data);
                  break;

                case "text":
                  response.answer += data.answer;
                  response.references = data.references;
                  callbacks?.onText?.(data);
                  break;

                case "image":
                  response.generated_files = data.generated_files;
                  callbacks?.onImage?.(data);
                  break;

                case "intric_event":
                  callbacks?.onIntricEvent?.(data);
                  break;
              }
            } catch (e) {
              return;
            }
          }
        },
        abortController
      );

      return response;
    }
  };
}
