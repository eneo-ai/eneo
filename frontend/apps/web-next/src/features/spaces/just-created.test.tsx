// @vitest-environment jsdom
import { cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { clearJustCreated, isJustCreated, markJustCreated, useJustCreated } from "./just-created";

afterEach(() => {
  cleanup();
  clearJustCreated("assistant", "a1");
});

describe("useJustCreated", () => {
  it("is true for the editor that opens after the creation, then cleared on unmount", () => {
    markJustCreated("assistant", "a1");
    const { result, rerender, unmount } = renderHook(() => useJustCreated("assistant", "a1"));
    expect(result.current).toBe(true);
    // Re-renders agree, so the editor does not re-announce or refocus.
    rerender();
    expect(result.current).toBe(true);
    expect(isJustCreated("assistant", "a1")).toBe(true);

    unmount();
    expect(isJustCreated("assistant", "a1")).toBe(false);
    expect(renderHook(() => useJustCreated("assistant", "a1")).result.current).toBe(false);
  });

  it("is false for any other visit, and keeps kinds apart", () => {
    markJustCreated("app", "a1");
    expect(renderHook(() => useJustCreated("assistant", "a1")).result.current).toBe(false);
    expect(renderHook(() => useJustCreated("app", "a1")).result.current).toBe(true);
  });
});
