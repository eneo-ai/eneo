"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { browserApi } from "@/lib/api/browser";
import { WhatsNewProvider } from "@/features/whats-new/whats-new-provider";
import { AppContextProvider, type AppContextData } from "./app-context";
import { appContextQueries } from "./app-context-queries";

/** What the deployment configures for the app context (the server's env). */
export type AppContextEnv = {
  showWebSearch: boolean;
  links: AppContextData["links"];
  frontendVersion: string;
};

const queries = appContextQueries(browserApi);

/**
 * The signed-in app context from the app-context queries, which the (app)
 * layout has loaded and hydrated: they hold data from the first render, so
 * nothing here suspends. A failed refetch keeps the previous data (a suspense
 * query throws only while it has none).
 */
export function QueryAppContextProvider({
  env,
  children
}: {
  env: AppContextEnv;
  children: React.ReactNode;
}) {
  const { data: user } = useSuspenseQuery(queries.me);
  const { data: tenant } = useSuspenseQuery(queries.tenant);
  const { data: settings } = useSuspenseQuery(queries.settings);
  const { data: federationStatus } = useSuspenseQuery(queries.federationStatus);
  const { data: limits } = useSuspenseQuery(queries.limits);
  const { data: backendVersion } = useSuspenseQuery(queries.version);
  const { data: whatsNewState } = useSuspenseQuery(queries.whatsNew);

  // Structural sharing keeps a source's data object when a refetch answers the
  // same, so the value (and every consumer) holds still.
  const value = useMemo<AppContextData>(
    () => ({
      user,
      tenant,
      settings,
      federationStatus,
      limits,
      featureFlags: { showWebSearch: env.showWebSearch },
      links: env.links,
      versions: { frontend: env.frontendVersion, backend: backendVersion }
    }),
    [user, tenant, settings, federationStatus, limits, backendVersion, env]
  );
  const whatsNewEnabled = settings.whats_new_enabled !== false;

  return (
    <AppContextProvider value={value}>
      <WhatsNewProvider
        key={`${whatsNewEnabled}:${whatsNewState?.seen_version ?? "unknown"}:${whatsNewState?.announced_version ?? "unknown"}`}
        enabled={whatsNewEnabled}
        initialSeen={whatsNewState?.seen_version}
        initialAnnounced={whatsNewState?.announced_version}
      >
        {children}
      </WhatsNewProvider>
    </AppContextProvider>
  );
}
