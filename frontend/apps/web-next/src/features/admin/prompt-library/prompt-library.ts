import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { matchesSearch } from "@/features/spaces/resource-filter";

/** A list row: the text is left out for payload size. */
export type Entry = Schema<"PromptLibraryEntrySparse">;
/** One prompt with its text. */
export type EntryFull = Schema<"PromptLibraryEntryPublic">;
/** One saved version of a prompt: every save creates one. */
export type Version = Schema<"PromptLibraryVersionPublic">;

/**
 * Prefix of every prompt library query key, so one invalidation refreshes the
 * list, the entries and their version histories together.
 */
export const PROMPT_LIBRARY_KEY = ["admin-prompt-library"];

export function promptLibraryQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: PROMPT_LIBRARY_KEY,
    queryFn: async (): Promise<Entry[]> => {
      const page = await unwrap(api.GET("/api/v1/admin/prompt-library/"));
      return page.items;
    }
  });
}

export function promptLibraryEntryQueryOptions(api: EneoClient, id: string) {
  return queryOptions({
    queryKey: [...PROMPT_LIBRARY_KEY, id],
    queryFn: (): Promise<EntryFull> =>
      unwrap(api.GET("/api/v1/admin/prompt-library/{id}/", { params: { path: { id } } }))
  });
}

/**
 * The prompt's versions, newest first. A 404 from the versions endpoint is an
 * empty history, as the SvelteKit page treats it, not a failure to show.
 */
export function promptLibraryVersionsQueryOptions(api: EneoClient, id: string) {
  return queryOptions({
    queryKey: [...PROMPT_LIBRARY_KEY, id, "versions"],
    queryFn: async (): Promise<Version[]> => {
      try {
        const page = await unwrap(
          api.GET("/api/v1/admin/prompt-library/{id}/versions/", { params: { path: { id } } })
        );
        return [...page.items].sort((a, b) => b.version - a.version);
      } catch (error) {
        if (error instanceof EneoApiError && error.status === 404) return [];
        throw error;
      }
    }
  });
}

/**
 * The rows a search leaves: every term must occur in the name or the
 * description. The list endpoint has no search parameter, so the filter is
 * client-side, like the SvelteKit page's.
 */
export function filterEntries(entries: readonly Entry[], query: string): Entry[] {
  return entries.filter((entry) => matchesSearch([entry.name, entry.description], query));
}
