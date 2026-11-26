import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";
import { PAGINATION } from "$lib/core/constants";
import { isValidChatPartnerType } from "$lib/features/chat/isValidChatPartnerType";
import {
  loadInitialConversation,
  NO_INITIAL_CONVERSATION
} from "$lib/features/chat/initialConversation";

export const load: PageLoad = async (event) => {
  const { eneo, currentSpace } = await event.parent();
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

  // The personal chat (default assistant) is gated by the personal_chat
  // permission. Without read access we render a no-access state instead of
  // firing conversation calls that would 403 — and this is the default landing
  // page, so a user with no permissions must land here gracefully, not crash.
  const accessDenied =
    partnerType === "default-assistant" &&
    !(currentSpace.default_assistant?.permissions?.includes("read") ?? false);

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
        if (!currentSpace.default_assistant) {
          throw new Error("No default assistant available for this space");
        }
        return currentSpace.default_assistant;
    }
  };

  const loadSession = async () => {
    if (accessDenied || !selectedSessionId) return NO_INITIAL_CONVERSATION;
    return loadInitialConversation(() => eneo.conversations.get({ id: selectedSessionId }));
  };

  const listSessions = async () => {
    if (accessDenied) {
      return { items: [], total_count: 0, count: 0, next_cursor: null };
    }
    return eneo.conversations.list({
      chatPartner: { id: partnerId, type: partnerType },
      pagination: { limit: PAGINATION.PAGE_SIZE }
    });
  };

  // Keep every request inside SvelteKit's load lifecycle. A rejected nested
  // promise can otherwise terminate the SSR process, even before rendering.
  const [partner, initialHistory, session] = await Promise.all([
    getPartner(),
    listSessions(),
    loadSession()
  ]);

  // Help assistants run behind the scenes to support users and must never be
  // opened as a chat (the backend ask-guard also blocks the actual ask). This
  // covers any stale or hand-built chat URL pointing at a helper.
  if (
    partnerType === "assistant" &&
    (partner as { is_help_assistant?: boolean })?.is_help_assistant
  ) {
    throw error(404);
  }

  return {
    chatPartner: partner,
    accessDenied,
    initialHistory,
    ...session
  };
};
