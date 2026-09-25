"use client";

import { hasUnseenRelease, latestRelease } from "@eneo/whats-new";
import { createContext, useCallback, useContext, useRef, useState } from "react";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
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

const WhatsNewContext = createContext<WhatsNewContextValue | null>(null);

export function WhatsNewProvider({
  enabled,
  initialSeen,
  initialAnnounced,
  children
}: {
  enabled: boolean;
  initialSeen: Marker;
  initialAnnounced: Marker;
  children: React.ReactNode;
}) {
  const [seenVersion, setSeenVersion] = useState<Marker>(initialSeen);
  const [announcedVersion, setAnnouncedVersion] = useState<Marker>(initialAnnounced);
  const seenInFlight = useRef<Promise<void> | null>(null);

  const markLatestSeen = useCallback((): Promise<void> => {
    if (!enabled || seenVersion === undefined || !hasUnseenRelease(seenVersion))
      return Promise.resolve();
    if (seenInFlight.current) return seenInFlight.current;
    const latest = latestRelease();
    if (!latest) return Promise.resolve();
    const previous = seenVersion;
    setSeenVersion(latest.version);
    const request = unwrap(
      browserApi.PUT("/api/v1/whats-new/seen/", { body: { version: latest.version } })
    )
      .then((state) => setSeenVersion(state.seen_version))
      .catch((error: unknown) => {
        setSeenVersion(previous);
        console.error("Could not record What's new as seen", error);
      })
      .finally(() => {
        seenInFlight.current = null;
      });
    seenInFlight.current = request;
    return request;
  }, [enabled, seenVersion]);

  const markLatestAnnounced = useCallback((): Promise<void> => {
    const latest = pendingAnnouncement(enabled, latestRelease(), announcedVersion);
    if (!latest) return Promise.resolve();
    setAnnouncedVersion(latest.version);
    return unwrap(
      browserApi.PUT("/api/v1/whats-new/announced/", { body: { version: latest.version } })
    )
      .then((state) => setAnnouncedVersion(state.announced_version))
      .catch((error: unknown) => {
        console.error("Could not record the What's new announcement", error);
      });
  }, [announcedVersion, enabled]);

  const resetState = useCallback(async () => {
    await unwrap(browserApi.DELETE("/api/v1/whats-new/state/"));
    setSeenVersion(null);
    setAnnouncedVersion(null);
  }, []);

  return (
    <WhatsNewContext.Provider
      value={{
        enabled,
        seenVersion,
        hasUnseen: enabled && seenVersion !== undefined && hasUnseenRelease(seenVersion),
        pendingRelease: pendingAnnouncement(enabled, latestRelease(), announcedVersion),
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
