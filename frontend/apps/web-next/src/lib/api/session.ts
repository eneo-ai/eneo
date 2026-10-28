import { queryOptions, type QueryClient } from "@tanstack/react-query";
import type { EneoClient } from "./browser";
import { unwrap } from "./errors";
import type { Schema } from "./models";

/**
 * The signed-in session's resources: the user, their organisation and its
 * settings, federation status, upload limits and the What's new markers. One
 * query each, under the key every other reader uses (keys mirror the backend
 * paths; ["users", "me"] is also refetched when a job finishes, for the
 * quota). The backend version is not one: it comes with the deployment.
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
 * Loads the session into `queryClient`, cache first: a resource already
 * cached is used as it is, even after a failed background refresh (which
 * marks it invalidated); mounted observers refresh it. Rejects when a required
 * resource has no data and cannot be read.
 */
export async function loadSession(queryClient: QueryClient, api: EneoClient): Promise<void> {
  const session = sessionQueries(api);
  await Promise.all([
    queryClient.query({ ...session.me, staleTime: "static" }),
    queryClient.query({ ...session.tenant, staleTime: "static" }),
    queryClient.query({ ...session.settings, staleTime: "static" }),
    queryClient.query({ ...session.federationStatus, staleTime: "static" }),
    queryClient.query({ ...session.limits, staleTime: "static" }),
    // Optional during rolling deployments; an unavailable marker must not look
    // like "never seen", and must not replace markers already known.
    queryClient.query({ ...session.whatsNew, staleTime: "static" }).catch(() => {
      if (queryClient.getQueryData(sessionKeys.whatsNew) === undefined) {
        queryClient.setQueryData(sessionKeys.whatsNew, null);
      }
    })
  ]);
}
