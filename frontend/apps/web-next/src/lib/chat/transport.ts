import { DefaultChatTransport, type UIMessageChunk } from "ai";
import type { ConversationBody, EneoDataParts, EneoUIMessage } from "./types";

/** Per-send request state merged into the body by sendMessage(…, { body }). */
export type ChatSendOptions = Omit<ConversationBody, "question" | "stream">;

/**
 * The custom `data-*` parts the backend emits (CONTRACT.md). Any other
 * `data-*` part fails the request: the SDK would silently append it to the
 * message, and the contract is pinned on both sides.
 */
export const DATA_PART_TYPES: ReadonlySet<string> = new Set([
  "data-session",
  "data-mcp-tool-references",
  "data-token-usage",
  "data-tool-approval",
  "data-error"
] satisfies `data-${keyof EneoDataParts}`[]);

/** The stream broke the contract (CONTRACT.md → What the client treats as failure). */
export class StreamContractError extends Error {
  override readonly name = "StreamContractError";
}

/**
 * Guards one response stream against the contract: the stream must end with
 * a terminal part (`finish`, or `error`, which the SDK turns into a failed
 * request), and may only carry known `data-*` parts. A stream that closes
 * early (backend crash, proxy timeout, dropped connection) therefore becomes
 * a failed request, never a finished answer. The user's own stop() cancels
 * the stream instead of closing it, so it is not affected.
 */
export function enforceStreamContract(): TransformStream<UIMessageChunk, UIMessageChunk> {
  let terminated = false;
  return new TransformStream({
    transform(chunk, controller) {
      if (chunk.type.startsWith("data-") && !DATA_PART_TYPES.has(chunk.type)) {
        throw new StreamContractError(`Unknown stream part type "${chunk.type}"`);
      }
      if (chunk.type === "finish" || chunk.type === "error" || chunk.type === "abort") {
        terminated = true;
      }
      controller.enqueue(chunk);
    },
    flush() {
      if (!terminated) {
        throw new StreamContractError("The answer stream closed before it finished");
      }
    }
  });
}

class EneoChatTransport extends DefaultChatTransport<EneoUIMessage> {
  protected override processResponseStream(
    stream: ReadableStream<Uint8Array>
  ): ReadableStream<UIMessageChunk> {
    return super.processResponseStream(stream).pipeThrough(enforceStreamContract());
  }
}

/**
 * Transport for the backend's v3 conversation stream. The backend owns the
 * history (session_id continues a conversation), so only the latest user
 * question is sent — never the message array.
 */
export function createChatTransport() {
  return new EneoChatTransport({
    api: "/api/chat",
    prepareSendMessagesRequest: ({ messages, body }) => {
      const lastMessage = messages[messages.length - 1];
      const question =
        lastMessage?.parts
          .filter((part): part is { type: "text"; text: string } => part.type === "text")
          .map((part) => part.text)
          .join("\n") ?? "";

      const sendOptions = (body ?? {}) as ChatSendOptions;
      const conversationBody: ConversationBody = {
        ...sendOptions,
        files: sendOptions.files ?? [],
        question,
        stream: true
      };
      return { body: conversationBody };
    }
  });
}
