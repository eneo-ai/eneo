"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { browserApi } from "@/lib/api/browser";
import { sessionQueries } from "@/lib/api/session";
import { flowsAvailable } from "@/features/flows/flows-api";
import { WhatsNewProvider } from "@/features/whats-new/whats-new-provider";
import { AppContextProvider, type AppContextData } from "./app-context";

/**
 * What comes with the deployment rather than the session: in Next the server's
 * env and the backend version it read; runtime config in the Vite app.
 */
export type AppContextEnv = {
  links: AppContextData["links"];
  frontendVersion: string;
  backendVersion: string;
};

const session = sessionQueries(browserApi);

/**
 * The signed-in app context from the session queries. Next hydrates these;
 * Vite starts them together in its route gate and suspends until they arrive.
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
      limits,
      featureFlags: { flows: flowsAvailable(settings, user) },
      links: env.links,
      versions: { frontend: env.frontendVersion, backend: env.backendVersion }
    }),
    [user, tenant, settings, federationStatus, limits, env]
  );

  return (
    <AppContextProvider value={value}>
      <WhatsNewProvider>{children}</WhatsNewProvider>
    </AppContextProvider>
  );
}
