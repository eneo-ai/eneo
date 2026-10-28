import { useEffect, useState } from "react";

/** How long free-text search waits for typing to pause (the Svelte app's 250 ms). */
export const SEARCH_DEBOUNCE_MS = 250;

/**
 * `value`, once it has stopped changing for `ms`: a search box's draft becomes
 * the committed search this way. Callers trim, so trailing whitespace does not
 * restart the wait or change a query key.
 */
export function useDebouncedValue<T>(value: T, ms = SEARCH_DEBOUNCE_MS): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}
