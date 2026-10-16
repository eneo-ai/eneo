// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { renderHookInApp } from "@/test/render";
import { useBeforeUnloadWarning } from "./use-before-unload-warning";

/** Whether the browser would ask before unloading the page now. */
function unloadIsGuarded(): boolean {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

describe("useBeforeUnloadWarning", () => {
  it("asks for confirmation while active, until unmounted", () => {
    const { unmount } = renderHookInApp(() => useBeforeUnloadWarning(true));
    expect(unloadIsGuarded()).toBe(true);

    unmount();
    expect(unloadIsGuarded()).toBe(false);
  });

  it("doesn't ask while inactive", () => {
    const { unmount } = renderHookInApp(() => useBeforeUnloadWarning(false));
    expect(unloadIsGuarded()).toBe(false);
    unmount();
  });

  it("stops asking when it turns inactive", () => {
    let active = true;
    const { rerender, unmount } = renderHookInApp(() => useBeforeUnloadWarning(active));
    expect(unloadIsGuarded()).toBe(true);

    active = false;
    rerender();
    expect(unloadIsGuarded()).toBe(false);
    unmount();
  });
});
