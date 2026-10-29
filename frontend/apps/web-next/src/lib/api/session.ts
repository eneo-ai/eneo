import { queryOptions, type QueryClient } from "@tanstack/react-query";
import type { EneoClient } from "./browser";
import { unwrap } from "./errors";
import type { Schema } from "./models";
import { readCached } from "./query";

/**
 * The signed-in session's resources: the user, their organisation and its
 * settings, federation status, upload limits and the What's new markers. One
 * query each, under the key every other reader uses (keys mirror the backend
 * paths; ["users", "me"] is also refetched, for the quota, when a job
 * finishes and when the upload dialog opens). The backend version is not one:
 * it comes with the deployment.
 */
export const sessionKeys = {
  me: ["users", "me"],
  tenant: ["users", "tenant"],
  settings: ["settings"],
  federationStatus: ["auth", "federation-status"],
  limits: ["limits"],
  whatsNew: ["whats-new", "state"]
} as const;

/*
 * Changed only by what invalidates them (a saved setting, a finished job):
 * never stale, never refetched on focus. Errors are not caught in the
 * queryFns, so a failed refetch keeps the data it had.
 */
const held = { staleTime: Infinity, refetchOnWindowFocus: false } as const;

export function sessionQueries(api: EneoClient) {
  return {
    me: queryOptions({
      ...held,
      queryKey: sessionKeys.me,
      queryFn: () => unwrap(api.GET("/api/v1/users/me/"))
    }),
    tenant: queryOptions({
      ...held,
      queryKey: sessionKeys.tenant,
      queryFn: () => unwrap(api.GET("/api/v1/users/tenant/"))
    }),
    settings: queryOptions({
      ...held,
      queryKey: sessionKeys.settings,
      queryFn: () => unwrap(api.GET("/api/v1/settings/"))
    }),
    federationStatus: queryOptions({
      ...held,
      queryKey: sessionKeys.federationStatus,
      queryFn: () => unwrap(api.GET("/api/v1/auth/federation-status"))
    }),
    limits: queryOptions({
      ...held,
      queryKey: sessionKeys.limits,
      queryFn: () => unwrap(api.GET("/api/v1/limits/"))
    }),
    whatsNew: queryOptions({
      ...held,
      queryKey: sessionKeys.whatsNew,
      // null: unavailable when the session loaded (see loadSession).
      queryFn: (): Promise<Schema<"WhatsNewStatePublic"> | null> =>
        unwrap(api.GET("/api/v1/whats-new/state/"))
    })
  };
}

/**
 * Loads the session into `queryClient`, cache first (`readCached`): a
 * resource already cached is used as it is, even after a failed background
 * refresh; mounted observers refresh it. Rejects when a required resource has
 * no data and cannot be read.
 */
export async function loadSession(queryClient: QueryClient, api: EneoClient): Promise<void> {
  const session = sessionQueries(api);
  await Promise.all([
    readCached(queryClient, session.me),
    readCached(queryClient, session.tenant),
    readCached(queryClient, session.settings),
    readCached(queryClient, session.federationStatus),
    readCached(queryClient, session.limits),
    // Optional during rolling deployments; an unavailable marker must not look
    // like "never seen", and must not replace markers already known: not here,
    // and not where this cache is hydrated into one that knows them (a
    // refreshed Next layout), so it is dated as the oldest possible answer.
    readCached(queryClient, session.whatsNew).catch(() => {
      if (queryClient.getQueryData(sessionKeys.whatsNew) === undefined) {
        queryClient.setQueryData(sessionKeys.whatsNew, null, { updatedAt: 0 });
      }
    })
  ]);
}
