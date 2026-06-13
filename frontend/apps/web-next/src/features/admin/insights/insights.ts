import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type Counts = Schema<"Counts">;

export function insightCountsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["admin-insights-counts"],
    queryFn: (): Promise<Counts> => unwrap(api.GET("/api/v1/analysis/counts/"))
  });
}
