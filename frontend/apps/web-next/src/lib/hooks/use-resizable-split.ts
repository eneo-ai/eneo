"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent
} from "react";

const KEYBOARD_STEP = 24;

export type ResizableSplitOptions = {
  /** localStorage key the width is remembered under; none keeps it for the session. */
  storageKey?: string;
  defaultWidth: number;
  minWidth: number;
  /** The largest share of the container the panel may take. */
  maxFraction?: number;
  /** Whether the panel is shown: the container is watched for size changes only then. */
  enabled?: boolean;
};

function readStored(key: string | undefined): number | null {
  if (!key || typeof window === "undefined") return null;
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
 * Attach `containerRef` to the element both halves share, spread
 * `separatorProps` on the handle and give the panel `width` in px.
 */
export function useResizableSplit({
  storageKey,
  defaultWidth,
  minWidth,
  maxFraction = 0.7,
  enabled = true
}: ResizableSplitOptions) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(() => readStored(storageKey) ?? defaultWidth);
  const [containerWidth, setContainerWidth] = useState<number | null>(null);
  const dragging = useRef<{ startX: number; startWidth: number } | null>(null);

  const clamp = useCallback(
    (next: number) => {
      const container = containerRef.current?.clientWidth ?? Infinity;
      const max = Math.max(minWidth, Math.floor(container * maxFraction));
      return Math.round(Math.min(max, Math.max(minWidth, next)));
    },
    [minWidth, maxFraction]
  );

  const commit = useCallback(
    (next: number) => {
      const clamped = clamp(next);
      setWidth(clamped);
      if (!storageKey) return;
      try {
        window.localStorage.setItem(storageKey, String(clamped));
      } catch {
        // Remembering the width is a nicety.
      }
    },
    [clamp, storageKey]
  );

  // A window that shrinks under a wide panel narrows the panel with it.
  useEffect(() => {
    const container = containerRef.current;
    if (!enabled || !container || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      setContainerWidth(container.clientWidth);
      setWidth((current) => clamp(current));
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [clamp, enabled]);

  const onPointerDown = (event: PointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    dragging.current = { startX: event.clientX, startWidth: width };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: PointerEvent<HTMLElement>) => {
    const drag = dragging.current;
    if (!drag) return;
    // The panel sits at the end: dragging the handle left widens it.
    setWidth(clamp(drag.startWidth + (drag.startX - event.clientX)));
  };
  const onPointerUp = (event: PointerEvent<HTMLElement>) => {
    if (!dragging.current) return;
    dragging.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
    commit(width);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    const container = containerRef.current?.clientWidth ?? width;
    const steps: Record<string, number> = {
      ArrowLeft: width + KEYBOARD_STEP,
      ArrowRight: width - KEYBOARD_STEP,
      Home: container,
      End: minWidth
    };
    const next = steps[event.key];
    if (next === undefined) return;
    event.preventDefault();
    commit(next);
  };

  return {
    width,
    containerRef,
    separatorProps: {
      role: "separator" as const,
      "aria-orientation": "vertical" as const,
      "aria-valuenow": width,
      "aria-valuemin": minWidth,
      "aria-valuemax": containerWidth ? Math.floor(containerWidth * maxFraction) : undefined,
      tabIndex: 0,
      onPointerDown,
      onPointerMove,
      onPointerUp,
      onPointerCancel: onPointerUp,
      onKeyDown
    }
  };
}
