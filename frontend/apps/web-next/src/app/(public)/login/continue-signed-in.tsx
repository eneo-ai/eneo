"use client";

import { useEffect } from "react";
import { announceIdentityChange } from "@/lib/session/identity-broadcast";

/**
 * Leaves /login for the app with a full page load: a session starts in a new
 * document, so nothing an earlier session left in memory (the query cache
 * with its user, tenant and settings) renders for it, and every other tab
 * reloads too. Every sign-in continues here: the password login re-renders
 * this page, and the SSO callbacks redirect to it. Not redirect(): reached by
 * a client-side navigation, or re-rendered by the login action once it has
 * set the session cookie, that navigates client-side too.
 */
export function ContinueSignedIn({ href }: { href: string }) {
  useEffect(() => {
    announceIdentityChange();
    // replace: /login only bounces a signed-in visitor, so Back skips it.
    window.location.replace(href);
  }, [href]);
  return null;
}
