"use client";

import { hasUnseenRelease, latestRelease, releases, visibleEntries } from "@eneo/whats-new";
import { useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useRef } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { sessionQueries } from "@/lib/api/session";
import { pendingAnnouncement, type Marker } from "./release-model";

interface WhatsNewContextValue {
  enabled: boolean;
  seenVersion: Marker;
  hasUnseen: boolean;
  pendingRelease: ReturnType<typeof latestRelease> | null;
  markLatestSeen: () => Promise<void>;
  markLatestAnnounced: () => Promise<void>;
  resetState: () => Promise<void>;
}

type WhatsNewState = Schema<"WhatsNewStatePublic">;

const WhatsNewContext = createContext<WhatsNewContextValue | null>(null);

const markers = sessionQueries(browserApi).whatsNew;

/**
 * What's new for the signed-in user, over the session's What's new query: the
 * one owner of the markers (null when the backend could not say: unknown, not
 * "never seen"). Recording one writes the backend's answer into that query;
 * the provider holds no marker state of its own, so a marker change updates
 * what shows it and remounts nothing.
 */
export function WhatsNewProvider({ children }: { children: React.ReactNode }) {
  const { can, settings } = useAppContext();
  const enabled = settings.whats_new_enabled !== false;
  const queryClient = useQueryClient();
  const { data: state } = useSuspenseQuery(markers);
  const seenVersion: Marker = state?.seen_version;
  const announcedVersion: Marker = state?.announced_version;
  const latest = latestRelease();
  const latestVisible = latest && visibleEntries(latest, can).length > 0;
  const seenInFlight = useRef<Promise<void> | null>(null);

  // One marker at a time, so an answer never overwrites the other marker's
  // pending change. Unknown markers (null) stay unknown.
  const setMarker = useCallback(
    (marker: keyof WhatsNewState, version: string | null) =>
      queryClient.setQueryData(markers.queryKey, (current) =>
        current ? { ...current, [marker]: version } : current
      ),
    [queryClient]
  );

  const hasUnseen =
    enabled &&
    seenVersion !== undefined &&
    releases.some(
      (release) => visibleEntries(release, can).length > 0 && hasUnseenRelease(seenVersion, release)
    );

  const markLatestSeen = useCallback((): Promise<void> => {
    if (!hasUnseen) return Promise.resolve();
    if (seenInFlight.current) return seenInFlight.current;
    const latest = latestRelease();
    if (!latest) return Promise.resolve();
    const previous = seenVersion ?? null;
    setMarker("seen_version", latest.version);
    const request = unwrap(
      browserApi.PUT("/api/v1/whats-new/seen/", { body: { version: latest.version } })
    )
      .then((answer) => {
        setMarker("seen_version", answer.seen_version);
      })
      .catch((error: unknown) => {
        setMarker("seen_version", previous);
        console.error("Could not record What's new as seen", error);
      })
      .finally(() => {
        seenInFlight.current = null;
      });
    seenInFlight.current = request;
    return request;
  }, [hasUnseen, seenVersion, setMarker]);

  const markLatestAnnounced = useCallback((): Promise<void> => {
    const latest = pendingAnnouncement(
      enabled && !!latestVisible,
      latestRelease(),
      announcedVersion
    );
    if (!latest) return Promise.resolve();
    setMarker("announced_version", latest.version);
    return unwrap(
      browserApi.PUT("/api/v1/whats-new/announced/", { body: { version: latest.version } })
    )
      .then((answer) => {
        setMarker("announced_version", answer.announced_version);
      })
      .catch((error: unknown) => {
        console.error("Could not record the What's new announcement", error);
      });
  }, [announcedVersion, enabled, latestVisible, setMarker]);

  const resetState = useCallback(async () => {
    const answer = await unwrap(browserApi.DELETE("/api/v1/whats-new/state/"));
    queryClient.setQueryData(markers.queryKey, answer);
  }, [queryClient]);

  return (
    <WhatsNewContext.Provider
      value={{
        enabled,
        seenVersion,
        hasUnseen,
        pendingRelease: pendingAnnouncement(enabled && !!latestVisible, latest, announcedVersion),
        markLatestSeen,
        markLatestAnnounced,
        resetState
      }}
    >
      {children}
    </WhatsNewContext.Provider>
  );
}

export function useWhatsNew(): WhatsNewContextValue {
  const value = useContext(WhatsNewContext);
  if (!value) throw new Error("useWhatsNew must be used inside the app layout");
  return value;
}

/** For UI that is also rendered without the app layout (tests, previews): null there. */
export function useOptionalWhatsNew(): WhatsNewContextValue | null {
  return useContext(WhatsNewContext);
}
