"use client";

import { useEffect } from "react";

/**
 * Leaves /login for the app with a full page load: a session starts in a new
 * document, so nothing an earlier session left in memory (the query cache
 * with its user, tenant and settings) renders for it. Not redirect(): reached
 * by a client-side navigation, or re-rendered by the login action once it has
 * set the session cookie, that navigates client-side too.
 */
export function ContinueSignedIn({ href }: { href: string }) {
  useEffect(() => {
    // replace: /login only bounces a signed-in visitor, so Back skips it.
    window.location.replace(href);
  }, [href]);
  return null;
}
