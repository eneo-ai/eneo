"use client";

import { useEffect, useRef, useState, type RefObject } from "react";

/**
 * The width of an element's content box, kept current by a ResizeObserver,
 * as `select` makes of it: for layout that depends on the room an element
 * has rather than on the window. The caller re-renders only when what
 * `select` returns changes, so one that needs a threshold does not re-render
 * on every pixel of a resize; `select` depends on the width alone. `null`
 * until measured. A hidden element
 * (`display: none`) keeps its last width.
 */
export function useElementWidth<T = number>(
  ref: RefObject<HTMLElement | null>,
  select?: (width: number) => T
): T | null {
  const [value, setValue] = useState<T | null>(null);
  const selectRef = useRef(select);
  useEffect(() => {
    selectRef.current = select;
  });
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const width = Math.round(entry?.contentRect.width ?? 0);
      if (width <= 0) return;
      const pick = selectRef.current;
      setValue((pick ? pick(width) : width) as T);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return value;
}
