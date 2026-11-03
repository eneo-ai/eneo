import { useAnnounce } from "@astryxdesign/core/hooks";
import { useRouter } from "@tanstack/react-router";
import { useEffect } from "react";

/**
 * Tells screen readers which page a navigation opened: the new document
 * title, once the page has rendered and
 * `HeadContent` has set it. Focus stays where it was. The first page load
 * and a change of only the query or hash (a tab, a filter) say nothing.
 */
export function RouteAnnouncer() {
  const router = useRouter();
  const announce = useAnnounce();

  useEffect(
    () =>
      router.subscribe("onRendered", ({ fromLocation, pathChanged }) => {
        if (!fromLocation || !pathChanged) return;
        // The title element commits with the page; read it in the next frame.
        requestAnimationFrame(() => announce(document.title));
      }),
    [router, announce]
  );

  return null;
}
