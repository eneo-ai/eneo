import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type Entry = Schema<"PromptLibraryEntrySparse">;

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
