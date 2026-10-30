import { error } from "@sveltejs/kit";
import { EneoError, type Conversation } from "@eneo/eneo-js";
import { toAppError } from "$lib/core/errors/toAppError";

export type InitialConversation = {
  initialConversation: Conversation | null;
  /** The URL named a conversation that no longer exists: deleted, or a stale link. */
  missingConversation: boolean;
};

export const NO_INITIAL_CONVERSATION: InitialConversation = {
  initialConversation: null,
  missingConversation: false
};

/**
 * Settle the conversation lookup behind a chat URL inside the page load.
 *
 * A missing conversation (404) is a state the chat page renders itself: the
 * partner still exists, so the user can start a new conversation there. Other
 * client errors, such as 403, become expected SvelteKit errors so the response
 * status and the server log match what the backend answered. Server and
 * network failures stay unexpected errors and are logged as such.
 */
export async function loadInitialConversation(
  lookup: () => Promise<Conversation>
): Promise<InitialConversation> {
  try {
    return { initialConversation: await lookup(), missingConversation: false };
  } catch (cause) {
    if (!(cause instanceof EneoError) || cause.status < 400 || cause.status >= 500) {
      throw cause;
    }
    if (cause.status === 404) {
      return { initialConversation: null, missingConversation: true };
    }
    throw error(
      cause.status,
      toAppError(cause, { status: cause.status, message: cause.getReadableMessage() })
    );
  }
}
