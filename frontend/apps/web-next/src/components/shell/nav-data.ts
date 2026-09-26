"use client";

import { useQueries } from "@tanstack/react-query";
import { usePathname, useSearchParams } from "next/navigation";
import { browserApi } from "@/lib/api/browser";
import { recentConversationsQueryOptions, type RecentConversation } from "@/lib/api/conversations";
import { useHydrated } from "@/lib/hooks/use-hydrated";
import { spacesListQueryOptions } from "@/features/spaces/space";
import { currentNavTarget, navTarget, type NavTarget } from "./routes";

/** How many conversations the SideNav lists under "Senaste". */
export const RECENT_CONVERSATIONS_IN_NAV = 5;

const firstInNav = (conversations: RecentConversation[]) =>
  conversations.slice(0, RECENT_CONVERSATIONS_IN_NAV);

const NO_CONVERSATIONS: RecentConversation[] = [];

/*
 * The shell's lists load in the browser: before hydration (the server render
 * and the hydration render) their queries are not even created. A page that
 * prefetched the same data (the Spaces list) hydrates it during those renders
 * only into a query the cache does not hold yet; an existing one gets it after
 * mount, which the server never reaches. The shell renders before the page,
 * so a pending query it made there left the page's useSuspenseQuery to fetch
 * during the server render, with the browser's API client and its relative URL.
 */

/** Shared (non-personal, non-organisation) spaces, from the existing spaces list query. */
export function useNavSpaces() {
  const queries = useHydrated() ? [spacesListQueryOptions(browserApi)] : [];
  return useQueries({
    queries,
    combine: ([query]) => ({
      spaces: (query?.data ?? []).filter((space) => !space.personal && !space.organization),
      // Before hydration there is no query yet: loading, as the server rendered it.
      isPending: query?.isPending ?? true
    })
  });
}

/**
 * The latest conversations with any assistant or group chat: the first few
 * of the list the ⌘K palette searches (one query, one cache entry).
 */
export function useRecentConversations(): RecentConversation[] {
  const queries = useHydrated()
    ? [{ ...recentConversationsQueryOptions(browserApi), select: firstInNav }]
    : [];
  return useQueries({ queries, combine: ([query]) => query?.data ?? NO_CONVERSATIONS });
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
