import { latestRelease } from "@eneo/whats-new";
import { get } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createWhatsNewStore, type Marker } from "./whatsNewStore";

const latest = latestRelease();
if (!latest) throw new Error("releases.json must contain at least one release for these tests");
const version = latest.version;

function makeStore(seen: Marker = null, announced: Marker = null, enabled = true) {
  const client = {
    markSeen: vi.fn(async (_version: string) => ({
      seen_version: version,
      announced_version: null
    })),
    markAnnounced: vi.fn(async (_version: string) => ({
      seen_version: null,
      announced_version: version
    })),
    resetState: vi.fn(async () => ({ seen_version: null, announced_version: null }))
  };
  return {
    client,
    store: createWhatsNewStore({
      eneo: { whatsNew: client },
      whatsNewEnabled: enabled,
      whatsNewSeenVersion: seen,
      whatsNewAnnouncedVersion: announced
    })
  };
}

afterEach(() => vi.restoreAllMocks());

describe("whatsNewStore", () => {
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
