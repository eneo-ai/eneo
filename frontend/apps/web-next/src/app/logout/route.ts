import { NextRequest, NextResponse } from "next/server";
import { env } from "@/lib/env";
import { buildLogoutUrl, isOidcEnabled } from "@/lib/auth/oidc";
import { safeNextPath } from "@/lib/auth/safe-next";
import { getSession, SESSION_COOKIE } from "@/lib/auth/session";

/** Login-page notices the logout route can hand over; anything else means a plain logout. */
const REASONS = new Set(["expired", "password_changed"]);

/** Clears the session; OIDC mode also ends the IdP session (RP-initiated).
 * `?reason=expired` marks a session the backend rejected: skip the IdP logout
 * (the IdP session may be fine — let the user re-enter with one SSO click)
 * and tell the login page why they landed there. `?reason=password_changed`
 * is the sign-out after a local password change: the session was invalidated
 * by the change itself, and `?next=` carries the page the user was heading to. */
export async function GET(request: NextRequest) {
  const session = await getSession();
  const requested = request.nextUrl.searchParams.get("reason");
  const reason = requested && REASONS.has(requested) ? requested : null;

  const login = new URL("/login", env.APP_ORIGIN);
  login.searchParams.set("message", reason ?? "logout");
  const next = request.nextUrl.searchParams.get("next");
  if (reason === "password_changed" && next && safeNextPath(next) === next) {
    login.searchParams.set("next", next);
  }
  let target = login.href;
  if (reason === null && session?.mode === "oidc" && isOidcEnabled()) {
    try {
      target = (await buildLogoutUrl(session.idToken)) ?? target;
    } catch {
      // IdP unreachable: still log out locally.
    }
  }

  const response = NextResponse.redirect(target);
  response.cookies.delete(SESSION_COOKIE);
  return response;
}
