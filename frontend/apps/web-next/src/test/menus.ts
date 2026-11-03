import { act, fireEvent, waitFor } from "@testing-library/react";
import { expect } from "vitest";

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
  fireEvent(button, pointerEvent("pointerdown", pointerType));
  expect(button.getAttribute("aria-expanded")).toBe("false");
  fireEvent(button, pointerEvent("pointerup", pointerType));
  fireEvent.click(button, { detail: 1 });
  await waitFor(() => expect(button.getAttribute("aria-expanded")).toBe("true"));
  const menu = document.getElementById(button.getAttribute("aria-controls") ?? "")!;
  // Astryx focuses the opened menu on the next animation frame. Waiting for that
  // frame, not for a wall-clock timeout, keeps a loaded runner from failing it.
  await nextFrame();
  expect(document.activeElement).toBe(menu);
  return menu;
}

/**
 * Resolves after the next animation frame. jsdom runs frames in the order they
 * were asked for, so every frame a component asked for before this one has run.
 */
function nextFrame(): Promise<void> {
  return act(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
}
