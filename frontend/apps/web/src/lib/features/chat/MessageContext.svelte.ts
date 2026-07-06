import { createContext } from "$lib/core/context";
import type { ConversationMessage } from "@eneo/eneo-js";

export const [getMessageContext, setMessageContext] = createContext<{
  current: () => ConversationMessage;
  isLoading: () => boolean;
  isLast: () => boolean;
}>("messageContext");
