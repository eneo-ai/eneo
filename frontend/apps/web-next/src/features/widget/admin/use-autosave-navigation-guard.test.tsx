// @vitest-environment jsdom
import { fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHookInApp } from "@/test/render";

vi.mock("next/navigation", () => import("@/test/navigation"));

import { router } from "@/test/navigation";
import { useAutosaveNavigationGuard, type GuardedAutosave } from "./use-autosave-navigation-guard";

function store(overrides: Partial<GuardedAutosave> = {}) {
  let resolveFlush: () => void = () => {};
  const autosave: GuardedAutosave & { settle: (saved: boolean) => void } = {
    unsaved: true,
    stranded: false,
    flush: vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveFlush = resolve;
        })
    ),
    settle(saved) {
      autosave.unsaved = !saved;
      resolveFlush();
    },
    ...overrides
  };
  return autosave;
}

function link(href: string, attributes: Record<string, string> = {}) {
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.textContent = href;
  for (const [name, value] of Object.entries(attributes)) anchor.setAttribute(name, value);
  document.body.append(anchor);
  return anchor;
}

/**
 * Whether the guard stopped a click. jsdom would try to navigate on a click
 * nobody prevented, so the test's own listener (after the guard's capturing
 * one) records the guard's decision and then prevents the default itself.
 */
function guardStopped(anchor: HTMLAnchorElement, init: MouseEventInit = {}): boolean {
  let stopped = false;
  const record = (event: Event) => {
    stopped = event.defaultPrevented;
    event.preventDefault();
  };
  document.addEventListener("click", record);
  anchor.dispatchEvent(
    new MouseEvent("click", { bubbles: true, cancelable: true, button: 0, ...init })
  );
  document.removeEventListener("click", record);
  return stopped;
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

describe("useAutosaveNavigationGuard", () => {
  it("holds an internal link until the pending save lands, then navigates", async () => {
    const autosave = store();
    renderHookInApp(() => useAutosaveNavigationGuard(autosave), { route: "/admin/widgets" });
    expect(guardStopped(link("/admin/widgets/templates/t1"))).toBe(true);
    expect(autosave.flush).toHaveBeenCalledTimes(1);
    expect(router.push).not.toHaveBeenCalled();

    autosave.settle(true);
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/admin/widgets/templates/t1"));
  });

  it("keeps the editor open when the save fails", async () => {
    const autosave = store();
    renderHookInApp(() => useAutosaveNavigationGuard(autosave), { route: "/admin/widgets" });
    fireEvent.click(link("/admin"));
    autosave.settle(false);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(router.push).not.toHaveBeenCalled();
  });

  it("asks before dropping edits that cannot be saved by waiting", () => {
    const autosave = store({ stranded: true });
    renderHookInApp(() => useAutosaveNavigationGuard(autosave), { route: "/admin/widgets" });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.click(link("/admin"));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(autosave.flush).not.toHaveBeenCalled();
    expect(router.push).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    fireEvent.click(link("/admin/users"));
    expect(router.push).toHaveBeenCalledWith("/admin/users");
  });

  it("lets everything through while nothing is unsaved", () => {
    const autosave = store({ unsaved: false });
    renderHookInApp(() => useAutosaveNavigationGuard(autosave), { route: "/admin/widgets" });
    expect(guardStopped(link("/admin"))).toBe(false);
    expect(autosave.flush).not.toHaveBeenCalled();
  });

  it("ignores links the router would not handle", () => {
    const autosave = store();
    // The guard compares against the real location, which the route mock does not set.
    window.history.replaceState(null, "", "/admin/widgets");
    renderHookInApp(() => useAutosaveNavigationGuard(autosave), { route: "/admin/widgets" });
    expect(guardStopped(link("https://docs.eneo.ai/guide"))).toBe(false);
    expect(guardStopped(link("/admin", { target: "_blank" }))).toBe(false);
    expect(guardStopped(link("/admin", { download: "" }))).toBe(false);
    expect(guardStopped(link("/admin/widgets#policy"))).toBe(false);
    expect(guardStopped(link("/admin"), { metaKey: true })).toBe(false);
    expect(autosave.flush).not.toHaveBeenCalled();
  });
});
