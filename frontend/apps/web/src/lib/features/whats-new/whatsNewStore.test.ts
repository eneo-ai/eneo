import { latestRelease } from "@eneo/whats-new";
import { get } from "svelte/store";
import { describe, expect, it, vi } from "vitest";
import { createWhatsNewStore } from "./whatsNewStore";

const latest = latestRelease();
if (!latest) throw new Error("releases.json must contain at least one release for these tests");

function makeStore(
  seen: string | null,
  markSeen = vi.fn(async () => ({ version: "", seen_at: null }))
) {
  const eneo = { whatsNew: { markSeen } } as unknown as Parameters<
    typeof createWhatsNewStore
  >[0]["eneo"];
  return { store: createWhatsNewStore({ eneo, whatsNewSeenVersion: seen }), markSeen };
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
});
