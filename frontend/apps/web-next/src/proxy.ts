import { NextRequest, NextResponse } from "next/server";
import { env } from "@/lib/env";
import { refreshTokens } from "@/lib/auth/oidc";
import {
  needsRefresh,
  openSession,
  sealSession,
  type SessionPayload
} from "@/lib/auth/session-codec";
import { SESSION_COOKIE } from "@/lib/auth/session";

/**
 * Optimistic auth gating + the sliding OIDC refresh. Real authorization is
 * the backend's job; this only keeps logged-out users away from app pages and
 * keeps the access token in the session cookie fresh (proxy is the one place
 * that can always write cookies, unlike RSC rendering).
 */

const PUBLIC_PREFIXES = [
  "/login",
  "/auth",
  "/logout",
  "/healthz",
  "/deactivated",
  "/activate",
  "/invite",
  "/integrations/callback"
];

const OIDC_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;

function isPublic(pathname: string): boolean {
  return PUBLIC_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

function loginRedirect(request: NextRequest) {
  const url = new URL("/login", request.url);
  const next = request.nextUrl.pathname + request.nextUrl.search;
  if (next !== "/") url.searchParams.set("next", next);
  const response = NextResponse.redirect(url);
  response.cookies.delete(SESSION_COOKIE);
  return response;
}

export async function proxy(request: NextRequest) {
  if (isPublic(request.nextUrl.pathname)) return NextResponse.next();

  const raw = request.cookies.get(SESSION_COOKIE)?.value;
  if (!raw) return loginRedirect(request);

  const session = await openSession(raw, env.SESSION_SECRET);
  if (!session) return loginRedirect(request);

  if (session.mode === "oidc" && session.refreshToken && needsRefresh(session)) {
    let refreshed: SessionPayload;
    try {
      const tokens = await refreshTokens(session.refreshToken);
      refreshed = {
        ...session,
        accessToken: tokens.accessToken,
        accessTokenExpiresAt: tokens.accessTokenExpiresAt,
        refreshToken: tokens.refreshToken ?? session.refreshToken,
        idToken: tokens.idToken ?? session.idToken
      };
    } catch {
      // Refresh token rejected or IdP unreachable: the session is over.
      return loginRedirect(request);
    }

    const sealed = await sealSession(refreshed, env.SESSION_SECRET, OIDC_SESSION_MAX_AGE_SECONDS);

    // Rewrite the request cookie so RSCs in THIS request already see the
    // refreshed session, and set the response cookie to persist it.
    const requestHeaders = new Headers(request.headers);
    const rewrittenCookies = request.cookies
      .getAll()
      .map((cookie) =>
        cookie.name === SESSION_COOKIE
          ? `${SESSION_COOKIE}=${sealed}`
          : `${cookie.name}=${cookie.value}`
      )
      .join("; ");
    requestHeaders.set("cookie", rewrittenCookies);

    const response = NextResponse.next({ request: { headers: requestHeaders } });
    response.cookies.set(SESSION_COOKIE, sealed, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: OIDC_SESSION_MAX_AGE_SECONDS
    });
    return response;
  }

  // Password mode has no refresh (until RB-3): an expired token means login.
  if (session.accessTokenExpiresAt <= Math.floor(Date.now() / 1000)) {
    return loginRedirect(request);
  }

  return NextResponse.next();
}

export const config = {
  // Everything except Next internals and static assets (anything with a file
  // extension); public paths are filtered in code above.
  matcher: ["/((?!_next/|.*\\..*).*)"]
};
