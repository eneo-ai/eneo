"use client";

import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

const KEYBOARD_STEP = 24;

export type ResizableSplitOptions = {
  /** The width both halves share (handle included), `null` until it is measured. */
  container: number | null;
  /** localStorage key the width is remembered under; none keeps it for the session. */
  storageKey?: string;
  defaultWidth: number;
  minWidth: number;
  /** The largest share of the container the panel may take. */
  maxFraction?: number;
  /** What the rest of the container keeps beside the panel, the handle included. */
  minRemaining?: number;
};

function readStored(key: string | undefined): number | null {
  if (!key) return null;
  try {
    const value = Number(window.localStorage.getItem(key));
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

/**
 * The width of a panel the user drags or keys wider and narrower beside a
 * main area, with the WAI-ARIA separator semantics on the handle. Astryx has
 * no split-pane component (0.6.4), so the behaviour lives here.
 *
 * The width the user chose is kept; what is shown is that width as far as
 * the container allows (on drag, on restore and on every resize), so a
 * window that narrows and widens again gives the panel its width back. A
 * press on the handle that does not move it changes nothing. `fits` says
 * whether the panel fits at all at its smallest, `null` until the container
 * is measured.
 *
 * Spread `separatorProps` on the handle and give the panel `width` in px.
 */
export function useResizableSplit({
  container,
  storageKey,
  defaultWidth,
  minWidth,
  maxFraction = 0.7,
  minRemaining = 0
}: ResizableSplitOptions) {
  const [chosen, setChosen] = useState(() => readStored(storageKey) ?? defaultWidth);
  const dragging = useRef<{ startX: number; startWidth: number; width: number | null } | null>(
    null
  );

  const max =
    container === null
      ? null
      : Math.floor(Math.min(container * maxFraction, container - minRemaining));
  const clamp = (next: number) => Math.round(Math.max(minWidth, Math.min(max ?? Infinity, next)));
  const width = clamp(chosen);
  const fits = max === null ? null : max >= minWidth;

  const commit = (next: number) => {
    const clamped = clamp(next);
    setChosen(clamped);
    if (!storageKey) return;
    try {
      window.localStorage.setItem(storageKey, String(clamped));
    } catch {
      // Remembering the width is a nicety.
    }
  };

  const onPointerDown = (event: PointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    dragging.current = { startX: event.clientX, startWidth: width, width: null };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: PointerEvent<HTMLElement>) => {
    const drag = dragging.current;
    if (!drag) return;
    // The panel sits at the end: dragging the handle left widens it.
    drag.width = clamp(drag.startWidth + (drag.startX - event.clientX));
    setChosen(drag.width);
  };
  const onPointerUp = (event: PointerEvent<HTMLElement>) => {
    const drag = dragging.current;
    if (!drag) return;
    dragging.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
    if (drag.width !== null) commit(drag.width);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    const steps: Record<string, number> = {
      ArrowLeft: width + KEYBOARD_STEP,
      ArrowRight: width - KEYBOARD_STEP,
      Home: Infinity,
      End: minWidth
    };
    const next = steps[event.key];
    if (next === undefined) return;
    event.preventDefault();
    commit(next);
  };

  return {
    width,
    fits,
    separatorProps: {
      role: "separator" as const,
      "aria-orientation": "vertical" as const,
      "aria-valuenow": width,
      "aria-valuemin": minWidth,
      "aria-valuemax": max !== null && max >= minWidth ? max : undefined,
      tabIndex: 0,
      onPointerDown,
      onPointerMove,
      onPointerUp,
      onPointerCancel: onPointerUp,
      onKeyDown
    }
  };
}
