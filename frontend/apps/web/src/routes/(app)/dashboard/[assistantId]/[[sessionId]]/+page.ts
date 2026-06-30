export const load = async (event) => {
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
    return eneo.conversations
      .list({
        chatPartner: { id: selectedAssistantId, type: "assistant" },
        pagination: { limit: 20 }
      })
      .catch((error) => error);
  };

  const assistantPromise = eneo.assistants.get({ id: selectedAssistantId });
  const sessionPromise = loadSession();
  const historyPromise = listSessions();

  const assistant = await assistantPromise;

  return {
    chatPartner: assistant,
    initialConversation: sessionPromise,
    initialHistory: historyPromise
  };
};
