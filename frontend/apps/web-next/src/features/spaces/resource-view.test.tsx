// @vitest-environment jsdom
import { act, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderHookInApp } from "@/test/render";
import { useResourceView } from "./resource-view";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

it("validates stored views and keeps the choice scoped to its resource surface", () => {
  window.localStorage.setItem("eneo:resource-view:apps", "unknown");
  const apps = renderHookInApp(() => useResourceView("apps", "cards"));
  expect(apps.result.current.view).toBe("cards");
  act(() => apps.result.current.chooseView("list"));
  apps.unmount();
  const restored = renderHookInApp(() => useResourceView("apps", "cards"));
  expect(restored.result.current.view).toBe("list");
  const assistants = renderHookInApp(() => useResourceView("assistants", "cards"));
  expect(assistants.result.current.view).toBe("cards");
});

it.each(["getItem", "setItem"] as const)(
  "keeps display controls usable when storage %s is unavailable",
  (method) => {
    if (method === "getItem") {
      const original = Storage.prototype.getItem;
      vi.spyOn(Storage.prototype, "getItem").mockImplementation(function (
        this: Storage,
        key: string
      ) {
        if (key.startsWith("eneo:resource-view:"))
          throw new DOMException("Unavailable", "SecurityError");
        return original.call(this, key);
      });
    } else {
      const original = Storage.prototype.setItem;
      vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
        this: Storage,
        key: string,
        value: string
      ) {
        if (key.startsWith("eneo:resource-view:"))
          throw new DOMException("Unavailable", "SecurityError");
        original.call(this, key, value);
      });
    }
    const { result } = renderHookInApp(() => useResourceView("spaces", "list"));
    expect(result.current.view).toBe("list");
    act(() => result.current.chooseView("cards"));
    expect(result.current.view).toBe("cards");
  }
);
