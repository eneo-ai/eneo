import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  const { eneo } = await event.parent();
  const selectedAssistantId = event.params.assistantId;
  const selectedSessionId = event.params.sessionId;

  const loadSession = async () => {
    return selectedSessionId
      ? eneo.assistants.getSession({
          assistant: { id: selectedAssistantId },
          session: { id: selectedSessionId }
        })
      : null;
  };

  const listSessions = async () => {
    return eneo.conversations.list({
      chatPartner: { id: selectedAssistantId, type: "assistant" },
      pagination: { limit: 20 }
    });
  };

  // Observe all failures immediately and let SvelteKit render its error page.
  // ChatService must never receive a promise that can reject outside this load.
  const [assistant, initialConversation, initialHistory] = await Promise.all([
    eneo.assistants.get({ id: selectedAssistantId }),
    loadSession(),
    listSessions()
  ]);

  return {
    chatPartner: assistant,
    initialConversation,
    initialHistory
  };
};
