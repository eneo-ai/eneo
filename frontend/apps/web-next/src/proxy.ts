import { NextRequest, NextResponse } from "next/server";
import { env } from "@/lib/env";
import { refreshTokens } from "@/lib/auth/oidc";
import {
  needsRefresh,
  openSession,
  sealSession,
  type SessionPayload
} from "@/lib/auth/session-codec";
import { OIDC_SESSION_MAX_AGE_SECONDS, SESSION_COOKIE } from "@/lib/auth/session";

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
const MOBILE_USER_AGENT = /Mobile|iP(hone|od|ad)|Android|BlackBerry|IEMobile/;

function createNonce(): string {
  const uuid = crypto.randomUUID();
  return typeof btoa === "function" ? btoa(uuid) : Buffer.from(uuid).toString("base64");
}

export function buildContentSecurityPolicy(
  nonce: string,
  nodeEnv: string | undefined = process.env.NODE_ENV
): string {
  const isDevelopment = nodeEnv === "development";
  const directives = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDevelopment ? " 'unsafe-eval'" : ""}`,
    `style-src 'self' 'nonce-${nonce}'${isDevelopment ? " 'unsafe-inline'" : ""}`,
    "style-src-attr 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self' data:",
    "media-src 'self' blob: data:",
    `connect-src 'self'${isDevelopment ? " ws: http: https:" : ""}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "script-src-attr 'none'",
    ...(isDevelopment ? [] : ["upgrade-insecure-requests"])
  ];
  return directives.join("; ");
}

function createSecurityRequestHeaders(request: NextRequest, nonce: string, csp: string): Headers {
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);
  return requestHeaders;
}

function withContentSecurityPolicy<T extends NextResponse>(response: T, csp: string): T {
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export function isMobileUserAgent(userAgent: string | null): boolean {
  return Boolean(userAgent && MOBILE_USER_AGENT.test(userAgent));
}

export function shouldRedirectMobileToDashboard(pathname: string, userAgent: string | null) {
  return !pathname.startsWith("/dashboard") && isMobileUserAgent(userAgent);
}

function authenticatedResponse(request: NextRequest, requestHeaders: Headers, csp: string) {
  if (
    shouldRedirectMobileToDashboard(request.nextUrl.pathname, request.headers.get("user-agent"))
  ) {
    return withContentSecurityPolicy(
      NextResponse.redirect(new URL("/dashboard", request.url)),
      csp
    );
  }
  return withContentSecurityPolicy(
    NextResponse.next({ request: { headers: requestHeaders } }),
    csp
  );
}

function isPublic(pathname: string): boolean {
  return PUBLIC_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

function loginRedirect(request: NextRequest, csp: string) {
  const url = new URL("/login", request.url);
  const next = request.nextUrl.pathname + request.nextUrl.search;
  if (next !== "/") url.searchParams.set("next", next);
  const response = NextResponse.redirect(url);
  response.cookies.delete(SESSION_COOKIE);
  return withContentSecurityPolicy(response, csp);
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const nonce = createNonce();
  const csp = buildContentSecurityPolicy(nonce);
  const securityRequestHeaders = createSecurityRequestHeaders(request, nonce, csp);

  // API routes handle auth themselves (401 JSON, not a login redirect), and
  // /api/eneo needs its trailing slash intact for the backend.
  if (pathname.startsWith("/api/")) {
    return withContentSecurityPolicy(
      NextResponse.next({ request: { headers: securityRequestHeaders } }),
      csp
    );
  }

  // skipTrailingSlashRedirect (needed for /api/eneo) disables the built-in
  // normalization, so page routes strip the trailing slash here instead.
  // Plain URL on purpose: NextURL's pathname setter re-applies the original
  // trailing slash, which would redirect to itself.
  if (pathname.length > 1 && pathname.endsWith("/")) {
    const url = new URL(request.url);
    url.pathname = pathname.replace(/\/+$/, "");
    return withContentSecurityPolicy(NextResponse.redirect(url, 308), csp);
  }

  if (isPublic(pathname)) {
    return withContentSecurityPolicy(
      NextResponse.next({ request: { headers: securityRequestHeaders } }),
      csp
    );
  }

  const raw = request.cookies.get(SESSION_COOKIE)?.value;
  if (!raw) return loginRedirect(request, csp);

  const session = await openSession(raw, env.SESSION_SECRET);
  if (!session) return loginRedirect(request, csp);

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
      return loginRedirect(request, csp);
    }

    const sealed = await sealSession(refreshed, env.SESSION_SECRET, OIDC_SESSION_MAX_AGE_SECONDS);

    // Rewrite the request cookie so RSCs in THIS request already see the
    // refreshed session, and set the response cookie to persist it.
    const rewrittenCookies = request.cookies
      .getAll()
      .map((cookie) =>
        cookie.name === SESSION_COOKIE
          ? `${SESSION_COOKIE}=${sealed}`
          : `${cookie.name}=${cookie.value}`
      )
      .join("; ");
    securityRequestHeaders.set("cookie", rewrittenCookies);

    const response = authenticatedResponse(request, securityRequestHeaders, csp);
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
    return loginRedirect(request, csp);
  }

  return authenticatedResponse(request, securityRequestHeaders, csp);
}

export const config = {
  // Everything except Next internals and static assets (anything with a file
  // extension); public paths are filtered in code above.
  matcher: ["/((?!_next/|.*\\..*).*)"]
};
