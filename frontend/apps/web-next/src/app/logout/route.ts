import { NextRequest, NextResponse } from "next/server";
import { env } from "@/lib/env";
import { buildLogoutUrl, isOidcEnabled } from "@/lib/auth/oidc";
import { getSession, SESSION_COOKIE } from "@/lib/auth/session";

/** Clears the session; OIDC mode also ends the IdP session (RP-initiated).
 * `?reason=expired` marks a session the backend rejected: skip the IdP logout
 * (the IdP session may be fine — let the user re-enter with one SSO click)
 * and tell the login page why they landed there. */
export async function GET(request: NextRequest) {
  const session = await getSession();
  const expired = request.nextUrl.searchParams.get("reason") === "expired";

  let target = new URL(`/login?message=${expired ? "expired" : "logout"}`, env.APP_ORIGIN).href;
  if (!expired && session?.mode === "oidc" && isOidcEnabled()) {
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
