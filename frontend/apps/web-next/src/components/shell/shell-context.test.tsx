// @vitest-environment jsdom
import { cleanup, fireEvent, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { isEditableTarget, isPaletteShortcut, usePaletteShortcut } from "./shell-context";

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

function keydown(init: KeyboardEventInit) {
  return new KeyboardEvent("keydown", { key: "k", ...init });
}

describe("isPaletteShortcut", () => {
  it("accepts ⌘K and Ctrl+K only", () => {
    expect(isPaletteShortcut(keydown({ metaKey: true }))).toBe(true);
    expect(isPaletteShortcut(keydown({ ctrlKey: true }))).toBe(true);
    expect(isPaletteShortcut(keydown({ ctrlKey: true, key: "K" }))).toBe(true);
    expect(isPaletteShortcut(keydown({}))).toBe(false);
    expect(isPaletteShortcut(keydown({ ctrlKey: true, shiftKey: true }))).toBe(false);
    expect(isPaletteShortcut(keydown({ metaKey: true, altKey: true }))).toBe(false);
    expect(isPaletteShortcut(keydown({ metaKey: true, key: "j" }))).toBe(false);
  });
});

describe("isEditableTarget", () => {
  it("treats text fields and editable content as typing targets", () => {
    const input = document.createElement("input");
    const textarea = document.createElement("textarea");
    const editable = document.createElement("div");
    editable.contentEditable = "true";
    // jsdom does not implement isContentEditable.
    Object.defineProperty(editable, "isContentEditable", { value: true });
    expect(isEditableTarget(input)).toBe(true);
    expect(isEditableTarget(textarea)).toBe(true);
    expect(isEditableTarget(editable)).toBe(true);
  });

  it("does not treat buttons, checkboxes or the page as typing targets", () => {
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    expect(isEditableTarget(checkbox)).toBe(false);
    expect(isEditableTarget(document.createElement("button"))).toBe(false);
    expect(isEditableTarget(document.body)).toBe(false);
    expect(isEditableTarget(null)).toBe(false);
  });
});

describe("usePaletteShortcut", () => {
  it("toggles on ⌘K / Ctrl+K from the page", () => {
    const toggle = vi.fn();
    renderHook(() => usePaletteShortcut(false, toggle));
    const event = keydown({ ctrlKey: true, bubbles: true, cancelable: true });
    window.dispatchEvent(event);
    expect(toggle).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(true);
  });

  it("does not hijack the keys while the user types in a field", () => {
    const toggle = vi.fn();
    renderHook(() => usePaletteShortcut(false, toggle));
    const textarea = document.body.appendChild(document.createElement("textarea"));
    fireEvent.keyDown(textarea, { key: "k", metaKey: true });
    expect(toggle).not.toHaveBeenCalled();
  });

  it("still closes an open palette from its own search field", () => {
    const toggle = vi.fn();
    renderHook(() => usePaletteShortcut(true, toggle));
    const input = document.body.appendChild(document.createElement("input"));
    fireEvent.keyDown(input, { key: "k", metaKey: true });
    expect(toggle).toHaveBeenCalledTimes(1);
  });

  it("ignores held keys and events another handler already used", () => {
    const toggle = vi.fn();
    renderHook(() => usePaletteShortcut(false, toggle));
    window.dispatchEvent(keydown({ metaKey: true, repeat: true }));
    const handled = keydown({ metaKey: true, cancelable: true });
    handled.preventDefault();
    window.dispatchEvent(handled);
    expect(toggle).not.toHaveBeenCalled();
  });
});
