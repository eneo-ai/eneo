import { latestRelease } from "@eneo/whats-new";
import { get } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createWhatsNewStore, type Marker } from "./whatsNewStore";

const latest = latestRelease();
if (!latest) throw new Error("releases.json must contain at least one release for these tests");
const version = latest.version;

function makeStore(
  seen: Marker = null,
  announced: Marker = null,
  enabled = true,
  installedVersion = version,
  remindAfter: string | null = null
) {
  const client = {
    markSeen: vi.fn(async (_version: string) => ({
      seen_version: _version,
      announced_version: null,
      remind_after: null
    })),
    markAnnounced: vi.fn(async (_version: string) => ({
      seen_version: null,
      announced_version: _version,
      remind_after: null
    })),
    snooze: vi.fn(async (_version: string) => ({
      seen_version: null,
      announced_version: _version,
      remind_after: new Date(Date.now() + 86400000).toISOString()
    })),
    resetState: vi.fn(async () => ({
      seen_version: null,
      announced_version: null,
      remind_after: null
    }))
  };
  return {
    client,
    store: createWhatsNewStore({
      eneo: { whatsNew: client },
      whatsNewEnabled: enabled,
      whatsNewVersion: installedVersion,
      whatsNewSeenVersion: seen,
      whatsNewAnnouncedVersion: announced,
      whatsNewRemindAfter: remindAfter
    })
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("whatsNewStore", () => {
  it("restores an unread reminder after 24 hours and consumes it when shown", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-20T10:00:00Z"));
    const { store, client } = makeStore(null, version);
    await store.snoozeLatest();
    expect(client.snooze).toHaveBeenCalledExactlyOnceWith(version);
    expect(store.pendingAnnouncement()).toBeNull();
    const reminder = (await client.snooze.mock.results[0].value).remind_after;
    vi.setSystemTime(new Date("2026-10-21T09:59:59Z"));
    expect(
      makeStore(null, version, true, version, reminder).store.pendingAnnouncement()
    ).toBeNull();
    vi.setSystemTime(new Date("2026-10-21T10:00:00Z"));
    const returning = makeStore(null, version, true, version, reminder).store;
    expect(returning.pendingAnnouncement()?.version).toBe(version);
    await returning.markLatestAnnounced();
    expect(returning.pendingAnnouncement()).toBeNull();
  });

  it("suppresses read reminders but lets a newer release announce immediately", () => {
    const past = "2020-01-01T00:00:00Z";
    const future = "2099-01-01T00:00:00Z";
    expect(makeStore(version, version, true, version, past).store.pendingAnnouncement()).toBeNull();
    expect(makeStore(null, "999.0.0", true, version, past).store.pendingAnnouncement()).toBeNull();
    expect(
      makeStore(null, "0.0.1", true, version, future).store.pendingAnnouncement()?.version
    ).toBe(version);
  });

  it("cancels a reminder when news is read and clears it on developer reset", async () => {
    const { store } = makeStore(null, version, true, version, "2020-01-01T00:00:00Z");
    await store.markLatestSeen();
    expect(store.pendingAnnouncement()).toBeNull();
    await store.resetState();
    expect(store.pendingAnnouncement()?.version).toBe(version);
  });

  it("reports a failed reminder write instead of pretending it was saved", async () => {
    const { store, client } = makeStore(null, version);
    client.snooze.mockRejectedValueOnce(new Error("offline"));
    await expect(store.snoozeLatest()).rejects.toThrow("offline");
    expect(store.pendingAnnouncement()).toBeNull();
  });

  it("finishes recording the announcement before postponing it", async () => {
    const { store, client } = makeStore();
    let finish: (() => void) | undefined;
    client.markAnnounced.mockImplementationOnce(async (_version) => {
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
      return { seen_version: null, announced_version: _version, remind_after: null };
    });
    const announced = store.markLatestAnnounced();
    const postponed = store.snoozeLatest();
    expect(client.snooze).not.toHaveBeenCalled();
    finish?.();
    await Promise.all([announced, postponed]);
    expect(client.snooze).toHaveBeenCalledOnce();
  });

  it("announces every RC and the final once, and keeps read progress independent", async () => {
    let seen: Marker = "2.2.0";
    let announced: Marker = "2.2.0";
    for (const installed of ["2.3.0-rc.0", "2.3.0-rc.1", "2.3.0-rc.10", "2.3.0"]) {
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

  it("does not announce an older RC or move markers backwards after rollback", async () => {
    for (const recorded of ["2.3.0-rc.10", "2.3.0"]) {
      const { store, client } = makeStore(recorded, recorded, true, "2.3.0-rc.1");
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
    client.markSeen.mockResolvedValueOnce({
      seen_version: "999.0.0",
      announced_version: null,
      remind_after: null
    });
    client.markAnnounced.mockResolvedValueOnce({
      seen_version: null,
      announced_version: "999.0.0",
      remind_after: null
    });
    await store.markLatestSeen();
    await store.markLatestAnnounced();
    expect(get(store.seenVersion)).toBe("999.0.0");
    expect(get(store.announcedVersion)).toBe("999.0.0");
  });

  it("stays quiet when the state could not be read", async () => {
    const { client } = makeStore();
    const store = createWhatsNewStore({
      eneo: { whatsNew: client },
      whatsNewEnabled: true,
      whatsNewVersion: version,
      whatsNewSeenVersion: undefined,
      whatsNewAnnouncedVersion: undefined,
      whatsNewRemindAfter: undefined
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
