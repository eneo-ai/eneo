import { NextResponse } from "next/server";
import { env } from "@/lib/env";
import { buildLogoutUrl, isOidcEnabled } from "@/lib/auth/oidc";
import { getSession, SESSION_COOKIE } from "@/lib/auth/session";

/** Clears the session; OIDC mode also ends the IdP session (RP-initiated). */
export async function GET() {
  const session = await getSession();

  let target = new URL("/login", env.APP_ORIGIN).href;
  if (session?.mode === "oidc" && isOidcEnabled()) {
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
