import { NextResponse } from "next/server";
import { env } from "@/lib/env";
import { isOidcEnabled } from "@/lib/auth/oidc";
import { SESSION_COOKIE, TXN_COOKIE } from "@/lib/auth/session";

/**
 * Switch organisation: clear the local session and restart OIDC with the IdP's
 * account/org chooser (prompt=select_account) so the user can pick a different
 * organisation. Non-OIDC tenants just land back on the login page.
 */
export async function GET() {
  const target = isOidcEnabled()
    ? new URL("/auth/login?prompt=select_account", env.APP_ORIGIN)
    : new URL("/login", env.APP_ORIGIN);

  const response = NextResponse.redirect(target.href);
  response.cookies.delete(SESSION_COOKIE);
  response.cookies.delete(TXN_COOKIE);
  return response;
}
