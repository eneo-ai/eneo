import {
  hasUnseenRelease,
  latestRelease,
  releasesForVersion,
  visibleEntries
} from "@eneo/whats-new";
import type { Release } from "@eneo/whats-new";
import { useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { sessionQueries } from "@/lib/api/session";
import { pendingAnnouncement, type Marker, type Reminder } from "./release-model";

interface WhatsNewContextValue {
  /** Releases with at least one entry visible under the user's permissions. */
  releases: Release[];
  enabled: boolean;
  seenVersion: Marker;
  hasUnseen: boolean;
  pendingRelease: ReturnType<typeof latestRelease> | null;
  markLatestSeen: () => Promise<void>;
  markLatestAnnounced: () => Promise<void>;
  /** "Later": announce the latest release again in 24 hours if it is still unread. Throws when storage fails. */
  snoozeLatest: () => void;
  resetState: () => Promise<void>;
}

type WhatsNewState = Schema<"WhatsNewStatePublic">;

const WhatsNewContext = createContext<WhatsNewContextValue | null>(null);

const markers = sessionQueries(browserApi).whatsNew;

const REMINDER_DELAY_MS = 24 * 60 * 60 * 1000;

function readReminder(key: string): Reminder {
  try {
    const remindAt = Number(globalThis.localStorage?.getItem(key) ?? "");
    if (!Number.isFinite(remindAt) || remindAt <= 0) return null;
    return Date.now() >= remindAt ? "due" : "waiting";
  } catch {
    // Storage may be unavailable; ordinary announcements must still work.
    return null;
  }
}

function forgetReminder(key: string): void {
  try {
    globalThis.localStorage?.removeItem(key);
  } catch {
    // Storage failures must not prevent reading or announcing news.
  }
}

/**
 * What's new for the signed-in user, over the session's What's new query: the
 * one owner of the markers (null when the backend could not say: unknown, not
 * "never seen"). Recording one writes the backend's answer into that query;
 * the provider holds no marker state of its own, so a marker change updates
 * what shows it and remounts nothing.
 */
export function WhatsNewProvider({ children }: { children: React.ReactNode }) {
  const { can, settings, user, versions } = useAppContext();
  const enabled = settings.whats_new_enabled !== false;
  const queryClient = useQueryClient();
  const { data: state } = useSuspenseQuery(markers);
  const seenVersion: Marker = state?.seen_version;
  const announcedVersion: Marker = state?.announced_version;
  // An installed release candidate announces and records its own version.
  const bundled = useMemo(() => releasesForVersion(versions.frontend), [versions.frontend]);
  const visibleReleases = bundled.filter((release) => visibleEntries(release, can).length > 0);
  const latest = latestRelease(bundled);
  const latestVisible = latest && visibleEntries(latest, can).length > 0;
  const seenInFlight = useRef<Promise<void> | null>(null);
  // "Later" reminders are this browser's, per account and installed release
  // (RCs included), read once per app load.
  const reminderKey = `eneo:whats-new:remind-after:${user.id}:${latest?.version}`;
  const [reminder, setReminder] = useState(() => readReminder(reminderKey));

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
    visibleReleases.some((release) => hasUnseenRelease(seenVersion, release));

  const markLatestSeen = useCallback((): Promise<void> => {
    if (!hasUnseen) return Promise.resolve();
    if (seenInFlight.current) return seenInFlight.current;
    if (!latest) return Promise.resolve();
    const previous = seenVersion ?? null;
    setMarker("seen_version", latest.version);
    const request = unwrap(
      browserApi.PUT("/api/v1/whats-new/seen/", { body: { version: latest.version } })
    )
      .then((answer) => {
        setMarker("seen_version", answer.seen_version);
        if (!hasUnseenRelease(answer.seen_version, latest)) {
          forgetReminder(reminderKey);
          setReminder(null);
        }
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
  }, [hasUnseen, latest, reminderKey, seenVersion, setMarker, setReminder]);

  const markLatestAnnounced = useCallback((): Promise<void> => {
    const pending = pendingAnnouncement(
      enabled && !!latestVisible,
      latest,
      announcedVersion,
      reminder,
      hasUnseen
    );
    if (!pending) return Promise.resolve();
    // Announcing it again uses the reminder up.
    forgetReminder(reminderKey);
    setReminder(null);
    setMarker("announced_version", pending.version);
    return unwrap(
      browserApi.PUT("/api/v1/whats-new/announced/", { body: { version: pending.version } })
    )
      .then((answer) => {
        setMarker("announced_version", answer.announced_version);
      })
      .catch((error: unknown) => {
        console.error("Could not record the What's new announcement", error);
      });
  }, [
    announcedVersion,
    enabled,
    hasUnseen,
    latest,
    latestVisible,
    reminder,
    reminderKey,
    setMarker,
    setReminder
  ]);

  const snoozeLatest = useCallback((): void => {
    if (!enabled || !latestVisible || !hasUnseen) return;
    globalThis.localStorage.setItem(reminderKey, String(Date.now() + REMINDER_DELAY_MS));
    setReminder("waiting");
  }, [enabled, hasUnseen, latestVisible, reminderKey, setReminder]);

  const resetState = useCallback(async () => {
    // Development only: unlike the cleanups above, a reset must not claim success without it.
    globalThis.localStorage.removeItem(reminderKey);
    setReminder(null);
    const answer = await unwrap(browserApi.DELETE("/api/v1/whats-new/state/"));
    queryClient.setQueryData(markers.queryKey, answer);
  }, [queryClient, reminderKey, setReminder]);

  return (
    <WhatsNewContext.Provider
      value={{
        releases: visibleReleases,
        enabled,
        seenVersion,
        hasUnseen,
        pendingRelease: pendingAnnouncement(
          enabled && !!latestVisible,
          latest,
          announcedVersion,
          reminder,
          hasUnseen
        ),
        markLatestSeen,
        markLatestAnnounced,
        snoozeLatest,
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
