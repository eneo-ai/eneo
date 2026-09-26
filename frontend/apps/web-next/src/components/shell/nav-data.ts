"use client";

import { useQuery } from "@tanstack/react-query";
import { usePathname, useSearchParams } from "next/navigation";
import { browserApi } from "@/lib/api/browser";
import { recentConversationsQueryOptions, type RecentConversation } from "@/lib/api/conversations";
import { spacesListQueryOptions } from "@/features/spaces/space";
import { currentNavTarget, navTarget, type NavTarget } from "./routes";

/** How many conversations the SideNav lists under "Senaste". */
export const RECENT_CONVERSATIONS_IN_NAV = 5;

const firstInNav = (conversations: RecentConversation[]) =>
  conversations.slice(0, RECENT_CONVERSATIONS_IN_NAV);

/** Shared (non-personal, non-organisation) spaces, from the existing spaces list query. */
export function useNavSpaces() {
  const query = useQuery(spacesListQueryOptions(browserApi));
  return {
    ...query,
    spaces: (query.data ?? []).filter((space) => !space.personal && !space.organization)
  };
}

/**
 * The latest conversations with any assistant or group chat: the first few
 * of the list the ⌘K palette searches (one query, one cache entry).
 */
export function useRecentConversations(): RecentConversation[] {
  const { data } = useQuery({ ...recentConversationsQueryOptions(browserApi), select: firstInNav });
  return data ?? [];
}

/**
 * The main-navigation destination the current URL belongs to (for
 * aria-current): a saved conversation while "Senaste" lists it, else the
 * place it belongs to.
 */
export function useNavTarget(): NavTarget {
  const target = navTarget(usePathname(), useSearchParams());
  const listed = useRecentConversations().map((conversation) => conversation.id);
  return currentNavTarget(target, listed);
}
