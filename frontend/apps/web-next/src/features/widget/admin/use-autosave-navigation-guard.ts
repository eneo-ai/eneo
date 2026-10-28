"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect } from "react";

/** What the guard needs of an autosave store. */
export type GuardedAutosave = {
  /** Edits not yet durably saved: pending, refused, held or in flight. */
  unsaved: boolean;
  /** Edits that cannot reach the server by waiting (refused, held, or a failed save). */
  stranded: boolean;
  flush: () => Promise<void>;
};

/** Whether a click on `anchor` would be an in-app navigation the router handles. */
function internalDestination(event: MouseEvent): string | null {
  if (event.defaultPrevented || event.button !== 0) return null;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
  const target = event.target;
  if (!(target instanceof Element)) return null;
  const anchor = target.closest("a[href]");
  if (!(anchor instanceof HTMLAnchorElement)) return null;
  if ((anchor.target && anchor.target !== "_self") || anchor.hasAttribute("download")) return null;
  const url = new URL(anchor.href, window.location.href);
  if (url.origin !== window.location.origin) return null;
  // A fragment on the same page is not a navigation away from the editor.
  if (url.pathname === window.location.pathname && url.search === window.location.search) {
    return null;
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * Holds in-app navigation until the autosave's queued edits have reached the
 * server, the counterpart of apps/web's guardAutosaveNavigation. The App
 * Router has no navigation hook to cancel, so the guard catches link clicks
 * before next/link does (a capturing listener; Link honours preventDefault),
 * flushes, and then navigates itself once nothing is unsaved. A failed or
 * refused save leaves the editor and its edits in place, where the error
 * shows; edits that cannot be saved by waiting ask before they are dropped.
 *
 * Browser back/forward and full unloads cannot be held this way: the store
 * flushes once more when the editor unmounts (useAutosave), and the
 * SaveStatusProvider's beforeunload warning covers reloads and closed tabs.
 */
export function useAutosaveNavigationGuard(autosave: GuardedAutosave): void {
  const router = useRouter();
  const t = useTranslations();

  useEffect(() => {
    let saving = false;
    let destination: string | null = null;

    const onClick = (event: MouseEvent) => {
      if (!autosave.unsaved) return;
      const href = internalDestination(event);
      if (href === null) return;
      event.preventDefault();
      if (autosave.stranded) {
        if (window.confirm(t("widget_admin_unsaved_leave_confirm"))) router.push(href);
        return;
      }
      // The latest click wins while one flush is in progress.
      destination = href;
      if (saving) return;
      saving = true;
      void autosave.flush().then(() => {
        saving = false;
        const next = destination;
        destination = null;
        if (!next || autosave.unsaved) return;
        router.push(next);
      });
    };

    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [autosave, router, t]);
}
