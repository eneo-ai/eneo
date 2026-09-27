import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanupExpiredEntries, dismiss, isDismissed } from "./expirationPrefs";

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    key: (index) => [...values.keys()][index] ?? null,
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => void values.set(key, String(value)),
    removeItem: (key) => void values.delete(key),
    clear: () => values.clear()
  };
}

const ctx = { tenantId: "tenant", userId: "user" };
const DAY = 24 * 60 * 60 * 1000;

describe("cleanupExpiredEntries", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", memoryStorage());
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("drops dismissals older than 90 days and keeps recent ones", () => {
    vi.setSystemTime(0);
    dismiss(ctx, "old-key", "", "warning");
    vi.setSystemTime(60 * DAY);
    dismiss(ctx, "recent-key", "", "warning");

    vi.setSystemTime(91 * DAY);
    cleanupExpiredEntries();

    expect(isDismissed(ctx, "old-key", "", "warning")).toBe(false);
    expect(isDismissed(ctx, "recent-key", "", "warning")).toBe(true);
  });

  it("removes corrupt entries and leaves unrelated keys alone", () => {
    localStorage.setItem("eneo:api-key-expiry:v1:dismiss:broken", "{not json");
    localStorage.setItem("other-app:setting", "keep");

    cleanupExpiredEntries();

    expect(localStorage.getItem("eneo:api-key-expiry:v1:dismiss:broken")).toBeNull();
    expect(localStorage.getItem("other-app:setting")).toBe("keep");
  });
});
