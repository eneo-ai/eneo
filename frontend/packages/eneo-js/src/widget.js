/**
 * Client for the anonymous widget surface (`/api/v1/widgets/{public_id}/…`).
 *
 * The `conversations` namespace mirrors the shape the chat UI already drives
 * (`ask`, `get`, `preflight`, …) so the same ChatService can run inside the
 * embed page without knowing it talks to a widget. Anything a visitor cannot
 * do (list, rename, delete, tool approval, diagnostics) is a harmless no-op.
 */
import { createClient, EneoError } from "./client/client.js";
import { readConversationStream } from "./endpoints/conversation-stream.js";

/** @typedef {import("./types/resources").WidgetPublicConfig} WidgetPublicConfig */
/** @typedef {import("./types/resources").WidgetVisitorSession} WidgetVisitorSession */

/**
 * @param {Object} args
 * @param {string} args.baseUrl Base URL of the Eneo backend
 * @param {string} args.publicId The widget's public id (`wgt_…`)
 * @param {() => string | null} [args.getToken] Returns the current visitor token, if any
 * @param {(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>} [args.fetch]
 */
export function createWidgetClient({ baseUrl, publicId, getToken, fetch }) {
  const path = { public_id: publicId };

  /** A fresh client per call so a rotated visitor token is always the one sent. */
  const client = () => {
    const token = getToken?.() ?? undefined;
    return createClient({ baseUrl, token: token ?? undefined, fetch });
  };

  /**
   * @param {string} what
   * @returns {never}
   */
  const unsupported = (what) => {
    throw new EneoError(`${what} is not available to widget visitors`, "CONNECTION", 0, 0);
  };

  return {
    publicId,

    /** Challenge URL for the ALTCHA widget (it fetches the challenge itself). */
    challengeUrl: `${baseUrl}/api/v1/widgets/${publicId}/challenge/`,

    /**
     * Display configuration of an active widget.
     * @returns {Promise<WidgetPublicConfig>}
     */
    config: async () => {
      return await client().fetch("/api/v1/widgets/{public_id}/config/", {
        method: "get",
        params: { path }
      });
    },

    /**
     * Mint a visitor token from a solved challenge, a previous token, or
     * nothing when the widget has bot protection switched off.
     * @param {{ altcha?: string; previousToken?: string; visitorId?: string; visitorKey?: string }} params
     * @returns {Promise<WidgetVisitorSession>}
     */
    createVisitorSession: async ({ altcha, previousToken, visitorId, visitorKey } = {}) => {
      return await client().fetch("/api/v1/widgets/{public_id}/visitor-sessions/", {
        method: "post",
        params: { path },
        requestBody: {
          "application/json": {
            altcha: altcha ?? null,
            previous_token: previousToken ?? null,
            visitor_id: visitorId ?? null,
            visitor_key: visitorKey ?? null
          }
        }
      });
    },

    conversations: {
      /**
       * @param {Object} params
       * @param {{id: string | null}} [params.conversation]
       * @param {string} params.question
       * @param {AbortController} [params.abortController]
       * @param {import("./endpoints/conversation-stream.js").ConversationStreamCallbacks} [params.callbacks]
       */
      ask: async ({ conversation, question, abortController, callbacks }) => {
        return await readConversationStream(
          client(),
          "/api/v1/widgets/{public_id}/ask/",
          {
            params: { path },
            requestBody: {
              "application/json": {
                question,
                session_id: conversation?.id ? conversation.id : null
              }
            }
          },
          callbacks,
          abortController
        );
      },

      /**
       * @param {{id: string}} conversation
       * @returns {Promise<import("./types/resources").Conversation>}
       */
      get: async (conversation) => {
        const res = await client().fetch("/api/v1/widgets/{public_id}/sessions/{session_id}/", {
          method: "get",
          params: { path: { ...path, session_id: conversation.id } }
        });
        return /** @type {import("./types/resources").Conversation} */ (res);
      },

      /**
       * @param {{ conversation: {id: string}; feedback: { value: -1 | 1; text?: string | null } }} params
       */
      leaveFeedback: async ({ conversation, feedback }) => {
        return await client().fetch("/api/v1/widgets/{public_id}/sessions/{session_id}/feedback/", {
          method: "post",
          params: { path: { ...path, session_id: conversation.id } },
          requestBody: { "application/json": feedback }
        });
      },

      /** Visitors get no token estimate; the composer simply shows nothing. */
      preflight: async () => ({
        input_tokens: 0,
        file_tokens: 0,
        prompt_tokens: 0,
        assistant_attachment_tokens: 0,
        skill_context_tokens: 0
      }),

      /** No history listing for visitors: one conversation at a time. */
      list: async () => ({ items: [], total_count: 0, next_cursor: null }),
      rename: async () => unsupported("Renaming"),
      delete: async () => unsupported("Deleting"),
      approveTools: async () => unsupported("Tool approval"),
      getTurnDiagnostics: async () => unsupported("Diagnostics"),
      getToolCallResult: async () => unsupported("Tool results")
    }
  };
}
