/**
 * Shared reader for the conversation SSE protocol (`first_chunk`, `text`,
 * `reasoning`, `image`, `eneo_event`, `token_usage`, `tool_call`, ...).
 * Used by the signed-in conversations endpoint and the anonymous widget
 * endpoint, which stream the same events from different paths.
 */

import { EneoError } from "../client/client.js";

/**
 * @typedef {Object} ConversationStreamCallbacks
 * @property {(data: import("../types/resources").SSE.FirstChunk) => void} [onFirstChunk]
 * @property {(data: import("../types/resources").SSE.Text) => void} [onText]
 * @property {(data: import("../types/resources").SSE.Reasoning) => void} [onReasoning]
 * @property {(data: import("../types/resources").SSE.Files) => void} [onImage]
 * @property {(data: import("../types/resources").SSE.Eneo | import("../types/resources").SSE.TokenUsage) => void} [onEneoEvent]
 * @property {(data: import("../types/resources").SSE.ToolCall) => void} [onToolCall]
 * @property {(data: import("../types/resources").SSE.ToolApprovalRequired) => void} [onToolApprovalRequired]
 * @property {(data: import("../types/resources").SSE.ToolApprovalTimeout) => void} [onToolApprovalTimeout]
 * @property {(response: Response) => Promise<void> | void} [onOpen]
 */

/**
 * Consume one conversation stream and return the assembled message.
 * @param {import('../client/client').Client} client
 * @param {Parameters<import('../client/client').Client["stream"]>[0]} endpoint
 * @param {Parameters<import('../client/client').Client["stream"]>[1]} args
 * @param {ConversationStreamCallbacks | undefined} callbacks
 * @param {AbortController} [abortController]
 * @returns {Promise<import("../types/resources").ConversationMessage>}
 */
export async function readConversationStream(client, endpoint, args, callbacks, abortController) {
  /** @type {import("../types/resources").ConversationMessage} */
  // @ts-expect-error We rely on the fact that the first_chunk event will initialise the response
  let response = {};

  await client.stream(
    endpoint,
    args,
    {
      onOpen: async (res) => {
        await callbacks?.onOpen?.(res);
      },
      onMessage: (ev) => {
        if (ev.data == "") return;
        let data;
        try {
          data = JSON.parse(ev.data);
        } catch (e) {
          return;
        }
        {
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

            case "eneo_event":
            case "token_usage":
              callbacks?.onEneoEvent?.(data);
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

            case "error":
              // The backend reports a failed answer as its own event and then
              // ends the stream normally; surface it so the caller does not
              // treat a truncated answer as a completed one.
              throw new EneoError(
                typeof data.error === "string" && data.error ? data.error : "The answer failed.",
                "SERVER",
                200,
                0,
                {
                  detail: {
                    code: typeof data.error_code === "string" ? data.error_code : "stream_error",
                    message: data.error
                  }
                }
              );
          }
        }
      }
    },
    abortController
  );

  return response;
}
