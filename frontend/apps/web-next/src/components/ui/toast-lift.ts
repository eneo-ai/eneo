"use client";

import { type RefObject, useEffect, useState } from "react";

/*
 * The toasts sit at the bottom edge, where a dialog keeps its primary button,
 * the chat docks its composer and a form keeps its save bar, and errors and
 * warnings stay until they are closed. Whatever has keyboard focus must stay
 * in view (WCAG 2.4.11), so while the toasts would cover the focused element
 * they rise to just above it, and settle back once focus moves on. No fixed
 * place would do: any spot on the edge holds some page's controls.
 */

/**
 * A group the toasts clear as a whole while focus is anywhere in it (the chat
 * composer): they neither cover its other controls, such as Send while the
 * user types, nor jump between its text field and its buttons.
 */
const CLEAR_GROUP = "[data-clear-of-toasts]";

/** An element's edges in viewport coordinates, as getBoundingClientRect() gives them. */
export type Box = Pick<DOMRectReadOnly, "top" | "right" | "bottom" | "left">;

/**
 * Space the raised toasts leave above what they clear, room for its focus
 * outline (2 px at a 3 px offset), and the least they keep from the top edge.
 */
const CLEARANCE = 8;

/**
 * How far (px) to raise the toasts from where they rest (`stack`) to clear
 * `target`: 0 while they cover none of what shows of it, and 0 when clearing
 * it would take them off the screen (an element that tall stays mostly in view).
 */
export function liftToClear(
  stack: Box,
  target: Box,
  viewport: { width: number; height: number }
): number {
  const top = Math.max(target.top, 0);
  const bottom = Math.min(target.bottom, viewport.height);
  const left = Math.max(target.left, 0);
  const right = Math.min(target.right, viewport.width);
  if (bottom <= top || right <= left) return 0;
  const covered =
    left - CLEARANCE < stack.right &&
    right + CLEARANCE > stack.left &&
    top - CLEARANCE < stack.bottom &&
    bottom + CLEARANCE > stack.top;
  if (!covered) return 0;
  const lift = Math.ceil(stack.bottom - (top - CLEARANCE));
  return stack.top - lift >= CLEARANCE ? lift : 0;
}

/** The inline `translate` style that raises the toasts by `lift` px. */
export function liftStyle(lift: number): string | undefined {
  return lift > 0 ? `0 ${-lift}px` : undefined;
}

/** The lift set on sonner's list (the inverse of liftStyle). */
function appliedLift(list: HTMLElement): number {
  const [, y = "0"] = list.style.translate.split(" ");
  return -Number.parseFloat(y) || 0;
}

/**
 * Where the toasts in sonner's list rest when not raised, or null when it
 * shows none. Sonner stacks them on the list's lower edge and slides them in
 * and out with transforms, so their layout boxes (offset*) are where they come
 * to rest; behind the front toast each collapsed one shows `--gap` px above it.
 */
export function restingStack(list: HTMLElement): Box | null {
  const toasts = list.querySelectorAll<HTMLElement>(
    '[data-sonner-toast][data-visible="true"]:not([data-removed="true"])'
  );
  if (toasts.length === 0) return null;
  const box = list.getBoundingClientRect();
  let left = Infinity;
  let right = -Infinity;
  let height = 0;
  for (const toast of toasts) {
    left = Math.min(left, box.left + toast.offsetLeft);
    right = Math.max(right, box.left + toast.offsetLeft + toast.offsetWidth);
    height = Math.max(height, toast.offsetHeight);
  }
  const gap = Number.parseFloat(list.style.getPropertyValue("--gap")) || 0;
  const bottom = box.bottom + appliedLift(list);
  return { left, right, bottom, top: bottom - height - gap * (toasts.length - 1) };
}

/**
 * The lift (px) for the toasts in `toaster` (sonner's <section>; apply it with
 * liftStyle). While toasts are shown it follows focus, the size of the focused
 * element and of the modal, scrolling, the window size and animations coming
 * to an end; otherwise it only watches the toaster for toasts.
 */
export function useToastLift(
  toaster: RefObject<HTMLElement | null>,
  modal: HTMLDialogElement | null
): number {
  const [lift, setLift] = useState(0);

  useEffect(() => {
    const section = toaster.current;
    if (!section) return;
    let frame = 0;
    let listening: AbortController | null = null;
    let watched: Element | null = null;
    const schedule = () => {
      frame ||= requestAnimationFrame(update);
    };
    const sizes = new ResizeObserver(schedule);
    const toasts = new MutationObserver(schedule);

    function listen(on: boolean) {
      if (on === (listening !== null)) return;
      if (!on) {
        listening?.abort();
        listening = null;
        sizes.disconnect();
        watched = null;
        return;
      }
      listening = new AbortController();
      const options = { capture: true, passive: true, signal: listening.signal };
      document.addEventListener("focusin", schedule, options);
      document.addEventListener("focusout", schedule, options);
      window.addEventListener("scroll", schedule, options);
      window.addEventListener("resize", schedule, options);
      // Once things settle: a dialog scales in (and a toaster inside it moves
      // with it until then), a toast slides in.
      document.addEventListener("animationend", schedule, options);
      document.addEventListener("transitionend", schedule, options);
      // A dialog that grows or shrinks moves its footer.
      if (modal) sizes.observe(modal);
    }

    function watch(target: Element | null) {
      if (target === watched) return;
      if (watched && watched !== modal) sizes.unobserve(watched);
      watched = target;
      if (target) sizes.observe(target);
    }

    function update() {
      frame = 0;
      const list = section?.querySelector<HTMLElement>("[data-sonner-toaster]");
      const stack = list ? restingStack(list) : null;
      listen(stack !== null);
      const focused = document.activeElement;
      if (!list || !stack || !focused || focused === document.body) {
        watch(null);
        setLift(0);
        return;
      }
      // Hold still while the user is in the toasts (closing one, say).
      if (list.contains(focused)) return;
      const group = focused.closest(CLEAR_GROUP);
      watch(group ?? focused);
      const viewport = { width: window.innerWidth, height: window.innerHeight };
      setLift(
        (group && liftToClear(stack, group.getBoundingClientRect(), viewport)) ||
          liftToClear(stack, focused.getBoundingClientRect(), viewport)
      );
    }

    toasts.observe(section, { childList: true, subtree: true });
    schedule();
    return () => {
      cancelAnimationFrame(frame);
      toasts.disconnect();
      listen(false);
    };
  }, [toaster, modal]);

  return lift;
}
