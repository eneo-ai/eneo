import { act, fireEvent, waitFor } from "@testing-library/react";
import { expect, onTestFinished } from "vitest";

type PointerType = "touch" | "mouse";

/**
 * jsdom has no PointerEvent, so a pointer event is a MouseEvent with its name,
 * the button and the pointer type a library reads.
 */
function pointerEvent(type: "pointerdown" | "pointerup", pointerType: PointerType) {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, button: 0 });
  Object.defineProperty(event, "pointerType", { value: pointerType });
  return event;
}

/**
 * Presses and releases `element` as a finger (or a mouse) does. The click
 * carries detail 1: Astryx reads a click with detail 0 as keyboard or
 * assistive-technology activation, which takes another path.
 */
export function tap(element: HTMLElement, pointerType: PointerType = "touch") {
  fireEvent(element, pointerEvent("pointerdown", pointerType));
  fireEvent(element, pointerEvent("pointerup", pointerType));
  fireEvent.click(element, { detail: 1 });
}

/**
 * Opens the menu of `button` as a finger does and returns it, checking that
 * the press alone opened nothing (2.5.2: a menu opens on release, so a finger
 * that slides off cancels) and that the menu itself has focus: a pointer open
 * highlights no item, unlike a keyboard open, which focuses the first one.
 */
export async function openMenuOnRelease(button: HTMLElement, pointerType: PointerType = "touch") {
  const id = button.getAttribute("aria-controls") ?? "";
  // Astryx mounts the menu a render after its button. Opened before that, the menu
  // opens but never takes focus; a person cannot press that fast, a test can.
  await waitFor(() => expect(document.getElementById(id)).not.toBeNull());
  fireEvent(button, pointerEvent("pointerdown", pointerType));
  expect(button.getAttribute("aria-expanded")).toBe("false");
  fireEvent(button, pointerEvent("pointerup", pointerType));
  fireEvent.click(button, { detail: 1 });
  await waitFor(() => expect(button.getAttribute("aria-expanded")).toBe("true"));
  // Astryx focuses the opened menu in an animation frame after the open, the next one
  // or, after a layout change or a remount, a later one. Waiting for that focus itself,
  // not for a frame count or a wall-clock timeout, keeps a loaded runner from failing it.
  await menuFocus(id);
  const menu = document.getElementById(id)!;
  expect(document.activeElement).toBe(menu);
  return menu;
}

/**
 * Resolves once the element with `id` has focus: at once, or on its focusin. A menu
 * that never gets focus fails at the test's timeout; the wait then ends with the test,
 * so its listener and its act() scope do not outlive it into the next test.
 */
export function menuFocus(id: string): Promise<void> {
  return act(
    () =>
      new Promise<void>((resolve) => {
        const focused = () => document.activeElement?.id === id;
        if (focused()) return resolve();
        const done = () => {
          document.removeEventListener("focusin", onFocus, true);
          resolve();
        };
        const onFocus = () => {
          if (focused()) done();
        };
        document.addEventListener("focusin", onFocus, true);
        onTestFinished(done);
      })
  );
}
