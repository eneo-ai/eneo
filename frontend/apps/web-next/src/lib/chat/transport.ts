import { DefaultChatTransport } from "ai";
import type { ConversationBody, EneoUIMessage } from "./types";

/** Per-send request state merged into the body by sendMessage(…, { body }). */
export type ChatSendOptions = Omit<ConversationBody, "question" | "stream">;

/**
 * Transport for the backend's v3 conversation stream. The backend owns the
 * history (session_id continues a conversation), so only the latest user
 * question is sent — never the message array.
 */
export function createChatTransport() {
  return new DefaultChatTransport<EneoUIMessage>({
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
