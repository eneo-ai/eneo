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
  installedVersion = version
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
      eneo: { whatsNew: client },
      whatsNewEnabled: enabled,
      whatsNewVersion: installedVersion,
      whatsNewSeenVersion: seen,
      whatsNewAnnouncedVersion: announced
    })
  };
}

afterEach(() => vi.restoreAllMocks());

describe("whatsNewStore", () => {
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
