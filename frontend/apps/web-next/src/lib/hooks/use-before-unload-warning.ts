import { useEffect } from "react";

/**
 * While `active`, the browser asks for confirmation before a reload or tab
 * close, so unsaved work isn't lost without warning. `preventDefault()` is how
 * a page asks for that prompt in every browser web-next supports; the legacy
 * `returnValue` is deprecated and not needed.
 */
export function useBeforeUnloadWarning(active: boolean) {
  useEffect(() => {
    if (!active) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [active]);
}
