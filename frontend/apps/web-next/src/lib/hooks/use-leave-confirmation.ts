import { useRouter } from "@/lib/navigation";
import { useEffect, useState } from "react";
import { useBeforeUnloadWarning } from "./use-before-unload-warning";

/** The in-app address a plain click on a link would open, or null when the click leaves it alone. */
export function inAppLinkTarget(event: MouseEvent, current: Location): string | null {
  if (event.defaultPrevented || event.button !== 0) return null;
  // A modified click opens a new tab or window; this page stays.
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
  const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
  if (!(anchor instanceof HTMLAnchorElement)) return null;
  if ((anchor.target && anchor.target !== "_self") || anchor.hasAttribute("download")) return null;
  const url = new URL(anchor.getAttribute("href") ?? "", current.href);
  // Another site unloads the page, which the before-unload warning covers.
  if (url.origin !== current.origin) return null;
  // A link to a place on this page (`#section`) does not leave it.
  if (url.pathname === current.pathname && url.search === current.search) return null;
  return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * While `active` (unsaved changes), leaving the page asks first: a reload or
 * closing the tab gets the browser's own prompt (`useBeforeUnloadWarning`),
 * and a click on a link to another page in the app is held until the user
 * answers the caller's confirmation (`pendingHref` is set; `leave()` goes on,
 * `stay()` keeps the page). The App Router has no navigation-blocking API,
 * so the click is caught on the document before Next's link handles it.
 * Navigation the app starts itself (`router.push`) and the browser's back
 * button are not held.
 */
export function useLeaveConfirmation(active: boolean) {
  const router = useRouter();
  const [pendingHref, setPendingHref] = useState<string | null>(null);
  useBeforeUnloadWarning(active);

  useEffect(() => {
    if (!active) return;
    function hold(event: MouseEvent) {
      const href = inAppLinkTarget(event, window.location);
      if (href === null) return;
      event.preventDefault();
      event.stopPropagation();
      setPendingHref(href);
    }
    document.addEventListener("click", hold, true);
    return () => document.removeEventListener("click", hold, true);
  }, [active]);

  return {
    pendingHref: active ? pendingHref : null,
    leave() {
      const href = pendingHref;
      setPendingHref(null);
      if (href) router.push(href);
    },
    stay() {
      setPendingHref(null);
    }
  };
}
