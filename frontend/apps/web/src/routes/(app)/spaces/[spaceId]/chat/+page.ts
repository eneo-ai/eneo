import type { PageLoad } from "./$types";
import { PAGINATION } from "$lib/core/constants";
import { isValidChatPartnerType } from "$lib/features/chat/isValidChatPartnerType";

export const load: PageLoad = async (event) => {
  const { eneo, currentSpace } = await event.parent();
  const partnerType = event.url.searchParams.get("type") ?? "default-assistant";

  if (!isValidChatPartnerType(partnerType)) {
    throw new Error("Unknown chat type!");
  }

  const partnerId =
    partnerType === "default-assistant"
      ? currentSpace.default_assistant.id
      : event.url.searchParams.get("id");
  const selectedSessionId = event.url.searchParams.get("session_id");

  if (!partnerId) {
    throw new Error("Not working");
  }

  const getPartner = async () => {
    switch (partnerType) {
      case "assistant":
        return eneo.assistants.get({
          id: partnerId
        });
      case "group-chat":
        return eneo.groupChats.get({
          id: partnerId
        });
      // instead of case "default-assistant"
      default:
        return currentSpace.default_assistant;
    }
  };

  const loadSession = async () => {
    if (!selectedSessionId) return null;
    return eneo.conversations.get({ id: selectedSessionId });
  };

  const listSessions = async () => {
    return (
      eneo.conversations
        .list({
          chatPartner: { id: partnerId, type: partnerType },
          pagination: { limit: PAGINATION.PAGE_SIZE }
        })
        // Need to catch the error here, otherwise the app will crash
        .catch((error) => error)
    );
  };

  const partnerPromise = getPartner();
  const historyPromise = listSessions();
  const initialSessionPromise = loadSession();

  const partner = await partnerPromise;

  return {
    chatPartner: partner,
    initialHistory: historyPromise,
    initialConversation: initialSessionPromise
  };
};
