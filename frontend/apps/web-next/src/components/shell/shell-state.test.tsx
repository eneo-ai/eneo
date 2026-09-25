// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  resetSideNavCollapsedForTest,
  safeStorage,
  SIDE_NAV_COLLAPSED_KEY,
  useSideNavCollapsed
} from "./shell-state";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
  resetSideNavCollapsedForTest();
});

describe("safeStorage", () => {
  it("reads and writes localStorage", () => {
    expect(safeStorage.set("k", "v")).toBe(true);
    expect(safeStorage.get("k")).toBe("v");
  });

  it("never throws when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });
    expect(safeStorage.get("k")).toBeNull();
    expect(safeStorage.set("k", "v")).toBe(false);
  });
});

describe("useSideNavCollapsed", () => {
  it("starts expanded and persists the choice", () => {
    const { result } = renderHook(() => useSideNavCollapsed());
    expect(result.current[0]).toBe(false);

    act(() => result.current[1](true));
    expect(result.current[0]).toBe(true);
    expect(window.localStorage.getItem(SIDE_NAV_COLLAPSED_KEY)).toBe("1");
  });

  it("restores a stored preference", () => {
    window.localStorage.setItem(SIDE_NAV_COLLAPSED_KEY, "1");
    const { result } = renderHook(() => useSideNavCollapsed());
    expect(result.current[0]).toBe(true);
  });

  it("still toggles for the session when storage cannot be written", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });
    const { result } = renderHook(() => useSideNavCollapsed());
    act(() => result.current[1](true));
    expect(result.current[0]).toBe(true);
  });
});
