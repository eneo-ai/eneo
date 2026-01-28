export const load = async (event) => {
  const { intric } = await event.parent();
  const selectedAssistantId = event.params.assistantId;
  const selectedSessionId = event.params.sessionId;

  const loadSession = async () => {
    return selectedSessionId
      ? intric.assistants.getSession({
          assistant: { id: selectedAssistantId },
          session: { id: selectedSessionId }
        })
      : null;
  };

  const listSessions = async () => {
    return intric.conversations
      .list({
        chatPartner: { id: selectedAssistantId, type: "assistant" },
        pagination: { limit: 20 }
      })
      .catch((error) => error);
  };

  const assistantPromise = intric.assistants.get({ id: selectedAssistantId });
  const sessionPromise = loadSession();
  const historyPromise = listSessions();

  const assistant = await assistantPromise;

  return {
    chatPartner: assistant,
    initialConversation: sessionPromise,
    initialHistory: historyPromise
  };
};
