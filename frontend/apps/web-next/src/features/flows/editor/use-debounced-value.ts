import { useEffect, useState } from "react";

/**
 * `value` once it has held still for `delay` ms. Pass a primitive (a JSON
 * string): a new object each render never holds still. Astryx has no
 * debounce hook (AGENTS.md → Reuse before you build).
 */
export function useDebouncedValue<T extends string | number | boolean | null>(
  value: T,
  delay: number
): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}
