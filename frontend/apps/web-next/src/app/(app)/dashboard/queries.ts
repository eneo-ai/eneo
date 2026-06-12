import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type SpaceDashboard = components["schemas"]["SpaceDashboard"];

/**
 * Takes the client as a parameter so the same options (and query key) serve
 * both sides: the server component prefetches with eneoApi(), the client
 * component hydrates with browserApi.
 */
export function dashboardQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["dashboard"],
    queryFn: () => unwrap(api.GET("/api/v1/dashboard/"))
  });
}
