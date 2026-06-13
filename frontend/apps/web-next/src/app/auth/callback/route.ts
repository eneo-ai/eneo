import { NextRequest, NextResponse } from "next/server";
import { env } from "@/lib/env";
import { completeAuthorization } from "@/lib/auth/oidc";
import { safeNextPath } from "@/lib/auth/safe-next";
import { openTxn, type SessionPayload } from "@/lib/auth/session-codec";
import { sealedSessionCookie, TXN_COOKIE } from "@/lib/auth/session";

/** Completes the OIDC code exchange and establishes the session cookie. */
export async function GET(request: NextRequest) {
  const failed = NextResponse.redirect(new URL("/login/failed", env.APP_ORIGIN));
  failed.cookies.delete(TXN_COOKIE);

  // The user canceled or the IdP rejected the request.
  if (request.nextUrl.searchParams.get("error")) {
    const denied = NextResponse.redirect(new URL("/login?error=access_denied", env.APP_ORIGIN));
    denied.cookies.delete(TXN_COOKIE);
    return denied;
  }

  const rawTxn = request.cookies.get(TXN_COOKIE)?.value;
  const txn = rawTxn ? await openTxn(rawTxn, env.SESSION_SECRET) : null;
  if (!txn) return failed;

  let tokens;
  try {
    tokens = await completeAuthorization(request.nextUrl, txn);
  } catch {
    return failed;
  }

  if (!tokens.claims.email) return failed;

  const session: SessionPayload = {
    mode: "oidc",
    accessToken: tokens.accessToken,
    accessTokenExpiresAt: tokens.accessTokenExpiresAt,
    refreshToken: tokens.refreshToken,
    idToken: tokens.idToken,
    user: { email: tokens.claims.email, name: tokens.claims.name }
  };

  const target = safeNextPath(txn.next);
  const response = NextResponse.redirect(new URL(target, env.APP_ORIGIN));
  const cookie = await sealedSessionCookie(session);
  response.cookies.set(cookie.name, cookie.value, cookie.options);
  response.cookies.delete(TXN_COOKIE);
  return response;
}
