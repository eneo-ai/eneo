"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { browserApi } from "@/lib/api/browser";
import { sessionQueries } from "@/lib/api/session";
import { WhatsNewProvider } from "@/features/whats-new/whats-new-provider";
import { AppContextProvider, type AppContextData } from "./app-context";

/**
 * Deployment metadata, kept separate from the signed-in session queries.
 */
export type AppContextEnv = {
  links: AppContextData["links"];
  frontendVersion: string;
  frontendRevision?: string | null;
  backendVersion: string;
  federationEnabled?: boolean;
};

const session = sessionQueries(browserApi);

/**
 * The signed-in app context from the session queries. The route gate starts
 * them together and the mounted readers suspend until they arrive.
 * A failed refetch keeps the previous data (a suspense query throws only
 * while it has none).
 */
export function QueryAppContextProvider({
  env,
  children
}: {
  env: AppContextEnv;
  children: React.ReactNode;
}) {
  const { data: user } = useSuspenseQuery(session.me);
  const { data: tenant } = useSuspenseQuery(session.tenant);
  const { data: settings } = useSuspenseQuery(session.settings);
  const { data: federationStatus } = useSuspenseQuery(session.federationStatus);
  const { data: limits } = useSuspenseQuery(session.limits);

  // Structural sharing keeps a source's data object when a refetch answers the
  // same, so the value (and every consumer) holds still.
  const value = useMemo<AppContextData>(
    () => ({
      user,
      tenant,
      settings,
      federationStatus,
      featureFlags: { federation: env.federationEnabled ?? false },
      limits,
      links: env.links,
      versions: {
        frontend: env.frontendVersion,
        frontendRevision: env.frontendRevision,
        backend: env.backendVersion
      }
    }),
    [user, tenant, settings, federationStatus, limits, env]
  );

  return (
    <AppContextProvider value={value}>
      <WhatsNewProvider>{children}</WhatsNewProvider>
    </AppContextProvider>
  );
}
