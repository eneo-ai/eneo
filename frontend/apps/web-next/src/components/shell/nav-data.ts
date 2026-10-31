"use client";

import { useQuery } from "@tanstack/react-query";
import { blockingError } from "@/components/composites/query-state";
import { usePathname, useSearchParams } from "@/lib/navigation";
import { browserApi } from "@/lib/api/browser";
import { recentConversationsQueryOptions, type RecentConversation } from "@/lib/api/conversations";
import { spacesListQueryOptions } from "@/features/spaces/space";
import { currentNavTarget, navTarget, type NavTarget } from "./routes";

/** How many conversations the SideNav lists under "Senaste". */
export const RECENT_CONVERSATIONS_IN_NAV = 5;

const firstInNav = (conversations: RecentConversation[]) =>
  conversations.slice(0, RECENT_CONVERSATIONS_IN_NAV);

const NO_CONVERSATIONS: RecentConversation[] = [];

/** Shared (non-personal, non-organisation) spaces, from the existing spaces list query. */
export function useNavSpaces() {
  const query = useQuery(spacesListQueryOptions(browserApi));
  return {
    spaces: (query.data ?? []).filter((space) => !space.personal && !space.organization),
    isPending: query.isPending,
    // Keep the error beside cached links, and through a retry without data,
    // so keyboard focus does not fall off the recovery button.
    isError: query.isError || blockingError(query),
    isFetching: query.isFetching,
    refetch: query.refetch
  };
}

/**
 * The latest conversations with any assistant or group chat: the first few
 * of the list the ⌘K palette searches (one query, one cache entry).
 */
export function useRecentConversations(): RecentConversation[] {
  return (
    useQuery({ ...recentConversationsQueryOptions(browserApi), select: firstInNav }).data ??
    NO_CONVERSATIONS
  );
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
