"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useCallback, useState } from "react";

/**
 * Next keeps a page mounted when only its search params change, and the chat
 * keeps its conversation in state. So when a shell link (Senaste, Ny
 * konversation, the palette) opens another conversation on the page that is
 * already showing, the page is remounted once the URL has arrived and starts
 * from it. Other query changes (the chat's own URL updates) never remount.
 *
 * Key the page content with `pageKey`; call `prepareNavigation(href)` before
 * navigating from a shell link.
 */
export function usePageRemount() {
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const url = search ? `${pathname}?${search}` : pathname;
  const [state, setState] = useState<{ url: string; pending: string | null; key: number }>({
    url,
    pending: null,
    key: 0
  });
  if (state.url !== url) {
    setState({ url, pending: null, key: state.pending === url ? state.key + 1 : state.key });
  }

  const prepareNavigation = useCallback((href: string) => {
    const target = new URL(href, window.location.href);
    const next = target.pathname + target.search;
    const current = window.location.pathname + window.location.search;
    if (target.pathname !== window.location.pathname || next === current) return;
    setState((previous) => ({ ...previous, pending: next }));
  }, []);

  return { pageKey: state.key, prepareNavigation };
}
