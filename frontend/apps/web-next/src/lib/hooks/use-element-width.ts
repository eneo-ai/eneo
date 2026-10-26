import { useCallback, useRef, useState, useSyncExternalStore } from "react";

/**
 * The width of an element, followed through a ResizeObserver: null until the
 * element is mounted and laid out (a hidden element measures 0, which counts
 * as not laid out). Returns a callback ref, so an element that mounts after
 * the component, or is swapped, is observed too.
 *
 * The width is an external store read during render, not state set from an
 * effect, so no render paints with a width the layout has already left
 * behind. Astryx has no hook for an element's size (`useOverflow` counts
 * children, `useMediaQuery` reads the window).
 */
export function useElementWidth<T extends HTMLElement>(): [
  (element: T | null) => void,
  number | null
] {
  const [element, setElement] = useState<T | null>(null);
  // The last width the observer reported; the snapshot reads it, and measures
  // the element itself until the first report.
  const observed = useRef<number | null>(null);

  const subscribe = useCallback(
    (onChange: () => void) => {
      if (!element || typeof ResizeObserver === "undefined") return () => {};
      const observer = new ResizeObserver(([entry]) => {
        if (!entry) return;
        observed.current = entry.contentRect.width;
        onChange();
      });
      observer.observe(element);
      return () => {
        observer.disconnect();
        observed.current = null;
      };
    },
    [element]
  );
  const read = useCallback(() => {
    if (!element) return null;
    const width = observed.current ?? element.getBoundingClientRect().width;
    return width > 0 ? width : null;
  }, [element]);

  return [setElement, useSyncExternalStore(subscribe, read, () => null)];
}
