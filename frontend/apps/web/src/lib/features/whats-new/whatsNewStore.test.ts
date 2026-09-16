import { latestRelease } from "@eneo/whats-new";
import { get } from "svelte/store";
import { describe, expect, it, vi } from "vitest";
import { createWhatsNewStore } from "./whatsNewStore";

const latest = latestRelease();
if (!latest) throw new Error("releases.json must contain at least one release for these tests");

function makeStore(
  seen: string | null | undefined,
  markSeen = vi.fn(async () => ({ seen_version: "", announced_version: null })),
  announced: string | null | undefined = null,
  markAnnounced = vi.fn(async () => ({ seen_version: null, announced_version: "" }))
) {
  const eneo = { whatsNew: { markSeen, markAnnounced } } as unknown as Parameters<
    typeof createWhatsNewStore
  >[0]["eneo"];
  return {
    store: createWhatsNewStore({
      eneo,
      whatsNewSeenVersion: seen,
      whatsNewAnnouncedVersion: announced
    }),
    markSeen,
    markAnnounced
  };
}

describe("whatsNewStore", () => {
  it("shows the dot until the newest bundled release has been seen", () => {
    expect(get(makeStore(null).store.hasUnseen)).toBe(true);
    expect(get(makeStore("0.0.1").store.hasUnseen)).toBe(true);
    expect(get(makeStore(latest.version).store.hasUnseen)).toBe(false);
  });

  it("marks the newest release seen once and clears the dot optimistically", async () => {
    const { store, markSeen } = makeStore(null);

    const first = store.markLatestSeen();
    expect(get(store.hasUnseen)).toBe(false);
    const second = store.markLatestSeen();
    await Promise.all([first, second]);

    expect(markSeen).toHaveBeenCalledTimes(1);
    expect(markSeen).toHaveBeenCalledWith(latest.version);
    expect(get(store.seenVersion)).toBe(latest.version);
  });

  it("does nothing when the newest release is already seen", async () => {
    const { store, markSeen } = makeStore(latest.version);
    await store.markLatestSeen();
    expect(markSeen).not.toHaveBeenCalled();
  });

  it("restores the dot when the backend write fails", async () => {
    const markSeen = vi.fn(async () => {
      throw new Error("offline");
    });
    const { store } = makeStore(null, markSeen);
    vi.spyOn(console, "error").mockImplementation(() => {});

    await store.markLatestSeen();

    expect(get(store.hasUnseen)).toBe(true);
    expect(get(store.seenVersion)).toBeNull();
  });

  it("announces the newest release once and leaves the seen marker alone", async () => {
    const { store, markAnnounced, markSeen } = makeStore(null);
    expect(store.pendingAnnouncement()?.version).toBe(latest.version);

    await store.markLatestAnnounced();

    expect(markAnnounced).toHaveBeenCalledWith(latest.version);
    expect(store.pendingAnnouncement()).toBeNull();
    expect(get(store.announcedVersion)).toBe(latest.version);
    expect(get(store.seenVersion)).toBeNull();
    expect(get(store.hasUnseen)).toBe(true);
    expect(markSeen).not.toHaveBeenCalled();
  });

  it("does not announce again for a release already announced or newer", () => {
    expect(makeStore(null, undefined, latest.version).store.pendingAnnouncement()).toBeNull();
    expect(makeStore(null, undefined, "999.0.0").store.pendingAnnouncement()).toBeNull();
    expect(makeStore(null, undefined, "0.0.1").store.pendingAnnouncement()?.version).toBe(
      latest.version
    );
  });

  it("stays quiet when the state could not be read", async () => {
    // Built directly: passing undefined to makeStore would hit its defaults.
    const markSeen = vi.fn();
    const markAnnounced = vi.fn();
    const store = createWhatsNewStore({
      eneo: { whatsNew: { markSeen, markAnnounced } } as unknown as Parameters<
        typeof createWhatsNewStore
      >[0]["eneo"],
      whatsNewSeenVersion: undefined,
      whatsNewAnnouncedVersion: undefined
    });
    expect(get(store.hasUnseen)).toBe(false);
    expect(store.pendingAnnouncement()).toBeNull();
    await store.markLatestSeen();
    await store.markLatestAnnounced();
    expect(markSeen).not.toHaveBeenCalled();
    expect(markAnnounced).not.toHaveBeenCalled();
  });
});
