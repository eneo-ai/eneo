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
     * @param {boolean} [params.requireToolApproval] Should tool calls require user approval before execution? Defaults to false
     * @param {string[]} [params.disabledMcpServerIds] MCP server ids the user switched off for this message
     * @param {{assistants: {id: string; handle: string}[]} | undefined} [params.tools] Tool use
     * @param {Object} [params.callbacks]
     * @param {(data: import("../types/resources").SSE.FirstChunk) => void} [params.callbacks.onFirstChunk] Callback to run when the first chunk of the answer is received
     * @param {(data: import("../types/resources").SSE.Text) => void} [params.callbacks.onText] Callback to run when a new token/word of the answer is received
     * @param {(data: import("../types/resources").SSE.Reasoning) => void} [params.callbacks.onReasoning] Callback to run when a chunk of the model's reasoning/thinking text is received
     * @param {(data: import("../types/resources").SSE.Files) => void} [params.callbacks.onImage] Callback to run when generated files of the answer is received
     * @param {(data: import("../types/resources").SSE.Intric) => void} [params.callbacks.onIntricEvent] Callback to run when an intric event is received
     * @param {(data: import("../types/resources").SSE.ToolCall) => void} [params.callbacks.onToolCall] Callback to run when MCP tools are being executed
     * @param {(data: import("../types/resources").SSE.ToolApprovalRequired) => void} [params.callbacks.onToolApprovalRequired] Callback to run when MCP tools require user approval
     * @param {(data: import("../types/resources").SSE.ToolApprovalTimeout) => void} [params.callbacks.onToolApprovalTimeout] Callback to run when a pending tool approval expires
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
      requireToolApproval,
      disabledMcpServerIds,
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
              use_web_search: useWebSearch,
              require_tool_approval: requireToolApproval,
              // Spread (not a direct property) so it doesn't trip excess-property
              // checks until schema.d.ts is regenerated via `bun run update`.
              ...(disabledMcpServerIds && disabledMcpServerIds.length > 0
                ? { disabled_mcp_server_ids: disabledMcpServerIds }
                : {})
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

                case "reasoning":
                  callbacks?.onReasoning?.(data);
                  break;

                case "image":
                  response.generated_files = data.generated_files;
                  callbacks?.onImage?.(data);
                  break;

                case "intric_event":
                case "token_usage":
                  callbacks?.onIntricEvent?.(data);
                  break;

                case "tool_call":
                  callbacks?.onToolCall?.(data);
                  break;

                case "tool_approval_required":
                  callbacks?.onToolApprovalRequired?.(data);
                  break;

                case "tool_approval_timeout":
                  callbacks?.onToolApprovalTimeout?.(data);
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
    },

    /**
     * Estimate exact token cost a request would add to context, without sending.
     * Excludes RAG/web-search content (selected at request time).
     * Caller should debounce; concurrent requests aren't aborted server-side.
     * @param {Object} params
     * @param {ChatPartner} [params.chatPartner] Target assistant or group chat (used when no conversation yet)
     * @param {{id: string} | Conversation} [params.conversation] Existing conversation to continue
     * @param {string} params.question The pending input
     * @param {{id: string}[]} [params.files] Pending file attachments
     * @param {import("../types/resources").ConversationTools} [params.tools] Pending assistant target
     * @returns {Promise<import('../types/resources').PreflightResponse>}
     * @throws {IntricError}
     */
    preflight: async ({ chatPartner, conversation, question, files, tools }) => {
      /** @type {{session_id?: string, assistant_id?: string, group_chat_id?: string}} */
      const target = { session_id: undefined, assistant_id: undefined, group_chat_id: undefined };

      if (conversation?.id && conversation.id.trim() !== "") {
        target.session_id = conversation.id;
      } else if (chatPartner?.id) {
        if (chatPartner.type === "assistant" || chatPartner.type === "default-assistant") {
          target.assistant_id = chatPartner.id;
        } else target.group_chat_id = chatPartner.id;
      } else {
        throw new IntricError(
          "Preflight requires one of session, assistant, or groupChat",
          "CONNECTION",
          0,
          0
        );
      }

      const res = await client.fetch("/api/v1/conversations/preflight", {
        method: "post",
        requestBody: {
          "application/json": {
            ...target,
            question,
            file_ids: (files ?? []).map((f) => f.id),
            tools
          }
        }
      });
      return res;
    },

    /**
     * Submit approval decisions for pending tool calls.
     * @param {Object} params Approval parameters
     * @param {string} params.approvalId The approval ID from the tool_approval_required event
     * @param {Array<{tool_call_id: string, approved: boolean}>} params.decisions Approval decisions for each tool
     * @returns {Promise<{status: string}>} Status response
     * @throws {IntricError}
     * */
    approveTools: async ({ approvalId, decisions }) => {
      /** @type {{status: string}} */
      // @ts-ignore - response type is unknown in schema
      const res = await client.fetch("/api/v1/conversations/approve-tools/", {
        method: "post",
        params: { query: { approval_id: approvalId } },
        // @ts-ignore - requestBody is optional in schema but we always send decisions
        requestBody: {
          "application/json": decisions
        }
      });
      return res;
    }
  };
}
