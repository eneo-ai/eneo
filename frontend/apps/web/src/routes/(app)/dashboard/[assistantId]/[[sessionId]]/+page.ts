import type { PageLoad } from "./$types";
import {
  loadInitialConversation,
  NO_INITIAL_CONVERSATION
} from "$lib/features/chat/initialConversation";

export const load: PageLoad = async (event) => {
  const { eneo } = await event.parent();
  const selectedAssistantId = event.params.assistantId;
  const selectedSessionId = event.params.sessionId;

  const loadSession = async () => {
    if (!selectedSessionId) return NO_INITIAL_CONVERSATION;
    return loadInitialConversation(() =>
      eneo.assistants.getSession({
        assistant: { id: selectedAssistantId },
        session: { id: selectedSessionId }
      })
    );
  };

  const listSessions = async () => {
    return eneo.conversations.list({
      chatPartner: { id: selectedAssistantId, type: "assistant" },
      pagination: { limit: 20 }
    });
  };

  // Observe all failures immediately and let SvelteKit render its error page.
  // ChatService must never receive a promise that can reject outside this load.
  const [assistant, session, initialHistory] = await Promise.all([
    eneo.assistants.get({ id: selectedAssistantId }),
    loadSession(),
    listSessions()
  ]);

  return {
    chatPartner: assistant,
    initialHistory,
    ...session
  };
};
