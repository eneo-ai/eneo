"use client";

import { queryOptions, useQuery } from "@tanstack/react-query";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { spaceQueryOptions, spacesListQueryOptions } from "@/features/spaces/space";

/** How many personal conversations the SideNav lists under "Senaste". */
export const RECENT_CONVERSATIONS_IN_NAV = 5;

/**
 * The latest conversations of one assistant. The key extends the chat
 * history's key (["conversations", "assistant", id]), so the chat's
 * invalidation after every answer refreshes these lists too.
 */
export function recentConversationsQueryOptions(
  api: EneoClient,
  assistantId: string,
  limit: number
) {
  return queryOptions({
    queryKey: ["conversations", "assistant", assistantId, "recent", limit],
    queryFn: async () => {
      const page = await unwrap(
        api.GET("/api/v1/conversations/", {
          params: { query: { assistant_id: assistantId, limit } }
        })
      );
      return page.items;
    }
  });
}

/** Shared (non-personal, non-organisation) spaces, from the existing spaces list query. */
export function useNavSpaces() {
  const query = useQuery(spacesListQueryOptions(browserApi));
  return {
    ...query,
    spaces: (query.data ?? []).filter((space) => !space.personal && !space.organization)
  };
}

/**
 * The personal assistant's latest conversations. The conversations endpoint
 * needs an assistant id (there is no cross-assistant history), so this lists
 * the personal (default) assistant only.
 */
export function useRecentConversations(limit = RECENT_CONVERSATIONS_IN_NAV) {
  const personal = useQuery(spaceQueryOptions(browserApi, "personal"));
  const assistantId = personal.data?.default_assistant?.id;
  const recent = useQuery({
    ...recentConversationsQueryOptions(browserApi, assistantId ?? "", limit),
    enabled: Boolean(assistantId)
  });
  return recent.data ?? [];
}
