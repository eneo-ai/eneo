import { latestRelease, type Release } from "@eneo/whats-new";
import * as news from "@eneo/whats-new";
import { get } from "svelte/store";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createWhatsNewStore, type Marker } from "./whatsNewStore";

const latest = latestRelease();
if (!latest) throw new Error("releases.json must contain at least one release for these tests");
const version = latest.version;

function makeStore(
  seen: Marker = null,
  announced: Marker = null,
  enabled = true,
  installedVersion = version,
  userId = "user-1"
) {
  const client = {
    markSeen: vi.fn(async (_version: string) => ({
      seen_version: _version,
      announced_version: null
    })),
    markAnnounced: vi.fn(async (_version: string) => ({
      seen_version: null,
      announced_version: _version
    })),
    resetState: vi.fn(async () => ({ seen_version: null, announced_version: null }))
  };
  return {
    client,
    store: createWhatsNewStore({
      user: { id: userId },
      eneo: { whatsNew: client },
      whatsNewEnabled: enabled,
      whatsNewVersion: installedVersion,
      whatsNewSeenVersion: seen,
      whatsNewAnnouncedVersion: announced
    })
  };
}

beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
    removeItem: (key: string) => {
      values.delete(key);
    }
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("whatsNewStore", () => {
  it("does not announce, count, or record a release without visible entries", async () => {
    const hidden: Release = {
      version,
      entries: [
        {
          id: "assistant",
          type: "new",
          area: "assistants",
          permissions: { allOf: ["assistants"] },
          title: { en: "Assistant", sv: "Assistent" },
          body: { en: "Body", sv: "Text" }
        }
      ]
    };
    vi.spyOn(news, "releasesForVersion").mockReturnValue([hidden]);
    const { store, client } = makeStore();
    expect(store.releases).toEqual([]);
    expect(get(store.hasUnseen)).toBe(false);
    expect(store.pendingAnnouncement()).toBeNull();
    store.snoozeLatest();
    await store.markLatestSeen();
    await store.markLatestAnnounced();
    expect(client.markSeen).not.toHaveBeenCalled();
    expect(client.markAnnounced).not.toHaveBeenCalled();
    expect(localStorage.getItem(`eneo:whats-new:remind-after:user-1:${version}`)).toBeNull();

    const granted = createWhatsNewStore({
      user: {
        id: "user-1",
        roles: [{ id: "custom", name: "Custom", permissions: ["assistants"] }]
      },
      eneo: { whatsNew: client },
      whatsNewEnabled: true,
      whatsNewVersion: version,
      whatsNewSeenVersion: null,
      whatsNewAnnouncedVersion: null
    });
    expect(get(granted.hasUnseen)).toBe(true);
    expect(granted.pendingAnnouncement()).toBe(hidden);
  });

  it("counts unread visible history without announcing an older release for a hidden latest", async () => {
    const general = {
      id: "general",
      type: "new" as const,
      area: "account" as const,
      title: { en: "General", sv: "Allmänt" },
      body: { en: "Body", sv: "Text" }
    };
    vi.spyOn(news, "releasesForVersion").mockReturnValue([
      { version, entries: [{ ...general, audience: "admin" }] },
      { version: "2.1.0", entries: [general] }
    ]);
    const { store, client } = makeStore();
    expect(store.releases.map((r) => r.version)).toEqual(["2.1.0"]);
    expect(get(store.hasUnseen)).toBe(true);
    expect(store.pendingAnnouncement()).toBeNull();
    expect(get(makeStore("2.1.0").store.hasUnseen)).toBe(false);
    await store.markLatestSeen();
    expect(client.markSeen).toHaveBeenCalledWith(version);
    expect(get(store.hasUnseen)).toBe(false);
  });

  it("preserves a due reminder while permissions hide its release", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-20T10:00:00Z"));
    const restricted: Release = {
      version,
      entries: [
        {
          id: "assistant",
          type: "new",
          area: "assistants",
          permissions: { allOf: ["assistants"] },
          title: { en: "Assistant", sv: "Assistent" },
          body: { en: "Body", sv: "Text" }
        }
      ]
    };
    vi.spyOn(news, "releasesForVersion").mockReturnValue([restricted]);
    const { client } = makeStore();
    const permitted = () =>
      createWhatsNewStore({
        user: {
          id: "user-1",
          roles: [{ id: "role", name: "Custom", permissions: ["assistants"] }]
        },
        eneo: { whatsNew: client },
        whatsNewEnabled: true,
        whatsNewVersion: version,
        whatsNewSeenVersion: null,
        whatsNewAnnouncedVersion: version
      });
    permitted().snoozeLatest();
    vi.setSystemTime(new Date("2026-10-21T10:00:00Z"));
    const hidden = makeStore(null, version);
    expect(hidden.store.pendingAnnouncement()).toBeNull();
    await hidden.store.markLatestSeen();
    await hidden.store.markLatestAnnounced();
    expect(hidden.client.markSeen).not.toHaveBeenCalled();
    expect(hidden.client.markAnnounced).not.toHaveBeenCalled();
    expect(permitted().pendingAnnouncement()).toBe(restricted);
  });

  it("restores a local reminder after reload, waits 24 hours and consumes it when shown", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-20T10:00:00Z"));
    makeStore(null, version).store.snoozeLatest();
    vi.setSystemTime(new Date("2026-10-21T09:59:59Z"));
    expect(makeStore(null, version).store.pendingAnnouncement()).toBeNull();
    vi.setSystemTime(new Date("2026-10-21T10:00:00Z"));
    const returning = makeStore(null, version).store;
    expect(returning.pendingAnnouncement()?.version).toBe(version);
    await returning.markLatestAnnounced();
    expect(makeStore(null, version).store.pendingAnnouncement()).toBeNull();
  });

  it("isolates reminders by account and release, including newer versions and rollback", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-20T10:00:00Z"));
    makeStore(null, `${version}-rc.1`, true, `${version}-rc.1`).store.snoozeLatest();
    expect(
      makeStore(null, `${version}-rc.1`, true, `${version}-rc.2`).store.pendingAnnouncement()
        ?.version
    ).toBe(`${version}-rc.2`);
    vi.setSystemTime(new Date("2026-10-21T10:00:00Z"));
    expect(
      makeStore(null, `${version}-rc.1`, true, `${version}-rc.1`).store.pendingAnnouncement()
        ?.version
    ).toBe(`${version}-rc.1`);
    expect(
      makeStore(
        null,
        `${version}-rc.1`,
        true,
        `${version}-rc.1`,
        "user-2"
      ).store.pendingAnnouncement()
    ).toBeNull();
    expect(
      makeStore(null, `${version}-rc.2`, true, `${version}-rc.1`).store.pendingAnnouncement()
    ).toBeNull();
  });

  it("cancels reminders when news is read, including read progress from another browser", async () => {
    makeStore(null, version).store.snoozeLatest();
    const readElsewhere = makeStore(version, version).store;
    expect(readElsewhere.pendingAnnouncement()).toBeNull();
    // Clearing the local reminder remains effective even with stale read progress.
    expect(makeStore(null, version).store.pendingAnnouncement()).toBeNull();
    const { store } = makeStore(null, version);
    store.snoozeLatest();
    await store.markLatestSeen();
    expect(store.pendingAnnouncement()).toBeNull();
  });

  it("reset clears local postponement and server markers so the announcement returns immediately", async () => {
    const { store, client } = makeStore(null, version);
    store.snoozeLatest();
    expect(store.pendingAnnouncement()).toBeNull();
    await store.resetState();
    expect(client.resetState).toHaveBeenCalledOnce();
    expect(store.pendingAnnouncement()?.version).toBe(version);
  });

  it("keeps a reminder if an older backend does not accept the read marker", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-20T10:00:00Z"));
    const { store, client } = makeStore(null, version);
    store.snoozeLatest();
    client.markSeen.mockResolvedValueOnce({ seen_version: "0.0.1", announced_version: null });
    await store.markLatestSeen();
    expect(store.pendingAnnouncement()).toBeNull();
    vi.setSystemTime(new Date("2026-10-21T10:00:00Z"));
    expect(store.pendingAnnouncement()?.version).toBe(version);
  });

  it("reports failed storage writes and reset instead of claiming success", async () => {
    const { store, client } = makeStore(null, version);
    vi.spyOn(globalThis.localStorage, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => store.snoozeLatest()).toThrow("blocked");
    vi.spyOn(globalThis.localStorage, "removeItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    await expect(store.resetState()).rejects.toThrow("blocked");
    expect(client.resetState).not.toHaveBeenCalled();
  });

  it("ignores invalid or unavailable local storage without breaking normal announcements", () => {
    vi.spyOn(globalThis.localStorage, "getItem").mockReturnValue("invalid");
    expect(makeStore(null, version).store.pendingAnnouncement()).toBeNull();
    expect(makeStore().store.pendingAnnouncement()?.version).toBe(version);
    vi.spyOn(globalThis.localStorage, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(makeStore().store.pendingAnnouncement()?.version).toBe(version);
    vi.stubGlobal("localStorage", undefined);
    expect(makeStore().store.pendingAnnouncement()?.version).toBe(version);
  });

  it("announces every RC and the final once, and keeps read progress independent", async () => {
    let seen: Marker = "0.0.1";
    let announced: Marker = "0.0.1";
    for (const installed of [`${version}-rc.0`, `${version}-rc.1`, `${version}-rc.10`, version]) {
      const { store, client } = makeStore(seen, announced, true, installed);
      expect(store.pendingAnnouncement()?.version).toBe(installed);
      expect(get(store.hasUnseen)).toBe(true);
      await store.markLatestAnnounced();
      expect(client.markAnnounced).toHaveBeenCalledExactlyOnceWith(installed);
      announced = get(store.announcedVersion);
      expect(get(store.seenVersion)).toBe(seen);
      expect(makeStore(seen, announced, true, installed).store.pendingAnnouncement()).toBeNull();
      await store.markLatestSeen();
      expect(client.markSeen).toHaveBeenCalledExactlyOnceWith(installed);
      seen = get(store.seenVersion);
      expect(get(makeStore(seen, announced, true, installed).store.hasUnseen)).toBe(false);
    }
  });

  it("lists unreleased notes on development builds without announcing or recording them", async () => {
    const upcoming: Release = { ...latest, version: news.UNRELEASED };
    delete upcoming.date;
    vi.spyOn(news, "releasesForVersion").mockReturnValue([upcoming, latest]);

    const caughtUp = makeStore(version, version, true, "develop-0123456789ab");
    expect(caughtUp.store.releases.map((release) => release.version)).toEqual([
      news.UNRELEASED,
      version
    ]);
    expect(caughtUp.store.pendingAnnouncement()).toBeNull();
    expect(get(caughtUp.store.hasUnseen)).toBe(false);
    await caughtUp.store.markLatestSeen();
    expect(caughtUp.client.markSeen).not.toHaveBeenCalled();

    const behind = makeStore(null, null, true, "develop-0123456789ab");
    expect(behind.store.pendingAnnouncement()).toBe(latest);
    await behind.store.markLatestAnnounced();
    await behind.store.markLatestSeen();
    expect(behind.client.markAnnounced).toHaveBeenCalledExactlyOnceWith(version);
    expect(behind.client.markSeen).toHaveBeenCalledExactlyOnceWith(version);

    vi.mocked(news.releasesForVersion).mockReturnValue([upcoming]);
    const onlyUpcoming = makeStore(null, null, true, "develop-0123456789ab");
    expect(onlyUpcoming.store.pendingAnnouncement()).toBeNull();
    expect(get(onlyUpcoming.store.hasUnseen)).toBe(false);
  });

  it("does not announce an older RC or move markers backwards after rollback", async () => {
    for (const recorded of [`${version}-rc.10`, version]) {
      const { store, client } = makeStore(recorded, recorded, true, `${version}-rc.1`);
      expect(store.pendingAnnouncement()).toBeNull();
      expect(get(store.hasUnseen)).toBe(false);
      await store.markLatestSeen();
      await store.markLatestAnnounced();
      expect(client.markSeen).not.toHaveBeenCalled();
      expect(client.markAnnounced).not.toHaveBeenCalled();
    }
  });

  it("shows the dot until the newest bundled release has been seen", () => {
    expect(get(makeStore().store.hasUnseen)).toBe(true);
    expect(get(makeStore("0.0.1").store.hasUnseen)).toBe(true);
    expect(get(makeStore(version).store.hasUnseen)).toBe(false);
  });

  it("deduplicates an in-flight write and clears the dot optimistically", async () => {
    const { store, client } = makeStore();
    const first = store.markLatestSeen();
    expect(get(store.hasUnseen)).toBe(false);
    const second = store.markLatestSeen();
    expect(second).toBe(first);
    await first;
    expect(client.markSeen).toHaveBeenCalledExactlyOnceWith(version);
    expect(get(store.seenVersion)).toBe(version);
  });

  it("does nothing when the newest release is already seen", async () => {
    const { store, client } = makeStore(version);
    await store.markLatestSeen();
    expect(client.markSeen).not.toHaveBeenCalled();
  });

  it("restores the dot when the backend write fails", async () => {
    const { store, client } = makeStore();
    client.markSeen.mockRejectedValueOnce(new Error("offline"));
    vi.spyOn(console, "error").mockImplementation(() => {});
    await store.markLatestSeen();
    expect(get(store.hasUnseen)).toBe(true);
    expect(get(store.seenVersion)).toBeNull();
  });

  it("announces once and leaves the seen marker alone", async () => {
    const { store, client } = makeStore();
    expect(store.pendingAnnouncement()?.version).toBe(version);
    await store.markLatestAnnounced();
    expect(client.markAnnounced).toHaveBeenCalledExactlyOnceWith(version);
    expect(store.pendingAnnouncement()).toBeNull();
    expect(get(store.announcedVersion)).toBe(version);
    expect(get(store.seenVersion)).toBeNull();
    expect(get(store.hasUnseen)).toBe(true);
  });

  it("does not announce a release already announced or newer", () => {
    expect(makeStore(null, version).store.pendingAnnouncement()).toBeNull();
    expect(makeStore(null, "999.0.0").store.pendingAnnouncement()).toBeNull();
    expect(makeStore(null, "0.0.1").store.pendingAnnouncement()?.version).toBe(version);
  });

  it("accepts the backend's newer marker after a write from an older frontend", async () => {
    const { store, client } = makeStore();
    client.markSeen.mockResolvedValueOnce({ seen_version: "999.0.0", announced_version: null });
    client.markAnnounced.mockResolvedValueOnce({
      seen_version: null,
      announced_version: "999.0.0"
    });
    await store.markLatestSeen();
    await store.markLatestAnnounced();
    expect(get(store.seenVersion)).toBe("999.0.0");
    expect(get(store.announcedVersion)).toBe("999.0.0");
  });

  it("stays quiet when the state could not be read", async () => {
    const { client } = makeStore();
    const store = createWhatsNewStore({
      user: { id: "user-1" },
      eneo: { whatsNew: client },
      whatsNewEnabled: true,
      whatsNewVersion: version,
      whatsNewSeenVersion: undefined,
      whatsNewAnnouncedVersion: undefined
    });
    expect(get(store.hasUnseen)).toBe(false);
    expect(store.pendingAnnouncement()).toBeNull();
    await store.markLatestSeen();
    await store.markLatestAnnounced();
    expect(client.markSeen).not.toHaveBeenCalled();
    expect(client.markAnnounced).not.toHaveBeenCalled();
  });

  it("updates the menu, indicator and announcement together when the setting changes", async () => {
    const { store, client } = makeStore();
    store.setEnabled(false);
    expect(get(store.enabled)).toBe(false);
    expect(get(store.hasUnseen)).toBe(false);
    expect(store.pendingAnnouncement()).toBeNull();
    await store.markLatestSeen();
    await store.markLatestAnnounced();
    expect(client.markSeen).not.toHaveBeenCalled();
    expect(client.markAnnounced).not.toHaveBeenCalled();
    store.setEnabled(true);
    expect(get(store.enabled)).toBe(true);
    expect(get(store.hasUnseen)).toBe(true);
    expect(store.pendingAnnouncement()?.version).toBe(version);
  });

  it("retains read progress while the feature is disabled and re-enabled", async () => {
    const { store } = makeStore(version, version, false);
    expect(get(store.enabled)).toBe(false);
    store.setEnabled(true);
    expect(get(store.hasUnseen)).toBe(false);
    expect(store.pendingAnnouncement()).toBeNull();
    await store.resetState();
    expect(get(store.hasUnseen)).toBe(true);
    expect(store.pendingAnnouncement()?.version).toBe(version);
  });
});
