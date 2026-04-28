import type { PageLoad } from "./$types";
import { PAGINATION } from "$lib/core/constants";
import { isValidChatPartnerType } from "$lib/features/chat/isValidChatPartnerType";

export const load: PageLoad = async (event) => {
  const { intric, currentSpace } = await event.parent();
  const partnerType = event.url.searchParams.get("type") ?? "default-assistant";

  if (!isValidChatPartnerType(partnerType)) {
    throw new Error("Unknown chat type!");
  }

  const partnerId =
    partnerType === "default-assistant"
      ? (currentSpace.default_assistant?.id ?? null)
      : event.url.searchParams.get("id");
  const selectedSessionId = event.url.searchParams.get("session_id");

  if (!partnerId) {
    throw new Error("Not working");
  }

  const getPartner = async () => {
    switch (partnerType) {
      case "assistant":
        return intric.assistants.get({
          id: partnerId
        });
      case "group-chat":
        return intric.groupChats.get({
          id: partnerId
        });
      // instead of case "default-assistant"
      default:
        if (!currentSpace.default_assistant) {
          throw new Error("No default assistant available for this space");
        }
        return currentSpace.default_assistant;
    }
  };

  const loadSession = async () => {
    if (!selectedSessionId) return null;
    return intric.conversations.get({ id: selectedSessionId });
  };

  const listSessions = async () => {
    return (
      intric.conversations
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
