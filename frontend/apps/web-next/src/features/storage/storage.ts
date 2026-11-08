import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type StorageModel = Schema<"StorageModel">;

/** The session's organisation total; session changes clear the query cache. */
export function storageQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["storage"],
    queryFn: (): Promise<StorageModel> => unwrap(api.GET("/api/v1/storage/"))
  });
}
