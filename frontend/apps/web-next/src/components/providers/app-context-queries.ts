import { queryOptions, type QueryClient } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { backendVersionFrom } from "@/lib/api/version";

/**
 * The signed-in app context's seven sources, under one prefix so
 * invalidateAppContext refreshes them together.
 */
export const appContextKeys = {
  all: ["app-context"],
  me: ["app-context", "me"],
  tenant: ["app-context", "tenant"],
  settings: ["app-context", "settings"],
  federationStatus: ["app-context", "federation-status"],
  limits: ["app-context", "limits"],
  version: ["app-context", "version"],
  whatsNew: ["app-context", "whats-new"]
} as const;

/*
 * The context changes only when something invalidates it: never stale, never
 * refetched on focus. Errors are not caught in the queryFns, so a failed
 * refetch keeps the data it had and the WhatsNewProvider key (and with it the
 * whole app) holds still.
 */
const held = { staleTime: Infinity, refetchOnWindowFocus: false } as const;

export function appContextQueries(api: EneoClient) {
  return {
    me: queryOptions({
      ...held,
      queryKey: appContextKeys.me,
      queryFn: () => unwrap(api.GET("/api/v1/users/me/"))
    }),
    tenant: queryOptions({
      ...held,
      queryKey: appContextKeys.tenant,
      queryFn: () => unwrap(api.GET("/api/v1/users/tenant/"))
    }),
    settings: queryOptions({
      ...held,
      queryKey: appContextKeys.settings,
      queryFn: () => unwrap(api.GET("/api/v1/settings/"))
    }),
    federationStatus: queryOptions({
      ...held,
      queryKey: appContextKeys.federationStatus,
      queryFn: () => unwrap(api.GET("/api/v1/auth/federation-status"))
    }),
    limits: queryOptions({
      ...held,
      queryKey: appContextKeys.limits,
      queryFn: () => unwrap(api.GET("/api/v1/limits/"))
    }),
    version: queryOptions({
      ...held,
      queryKey: appContextKeys.version,
      queryFn: () => unwrap(api.GET("/version")).then(backendVersionFrom)
    }),
    whatsNew: queryOptions({
      ...held,
      queryKey: appContextKeys.whatsNew,
      // null: unavailable when the context loaded (see loadAppContext).
      queryFn: (): Promise<Schema<"WhatsNewStatePublic"> | null> =>
        unwrap(api.GET("/api/v1/whats-new/state/"))
    })
  };
}

/**
 * Loads the app context into `queryClient` for the (app) layout to hydrate.
 * Rejects when a required source fails.
 */
export async function loadAppContext(queryClient: QueryClient, api: EneoClient): Promise<void> {
  const queries = appContextQueries(api);
  await Promise.all([
    queryClient.query(queries.me),
    queryClient.query(queries.tenant),
    queryClient.query(queries.settings),
    queryClient.query(queries.federationStatus),
    queryClient.query(queries.limits),
    queryClient.query(queries.version),
    // Optional during rolling deployments; an unavailable marker must not look like "never seen".
    queryClient.query(queries.whatsNew).catch(() => {
      queryClient.setQueryData(queries.whatsNew.queryKey, null);
    })
  ]);
}

/**
 * Refetches the app context in place, after a change to the user, tenant or
 * settings. Not the backend version: it changes only with a deploy (and a
 * reload), and the beta host does not route /version to the backend.
 */
export function invalidateAppContext(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({
    queryKey: appContextKeys.all,
    predicate: (query) => query.queryKey[1] !== appContextKeys.version[1]
  });
}
