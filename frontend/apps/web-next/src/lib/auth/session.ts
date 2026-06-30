import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { env } from "@/lib/env";
import {
  needsRefresh,
  openSession,
  sealSession,
  type SessionPayload
} from "@/lib/auth/session-codec";
import { refreshTokens } from "@/lib/auth/oidc";

export const SESSION_COOKIE = "eneo_session";
/** Short-lived cookie carrying the OIDC authorization transaction. */
export const TXN_COOKIE = "eneo_oidc_txn";

/** OIDC sessions slide with the refresh token; 30 days matches typical IdP
 * refresh-token lifetimes. Password sessions live exactly as long as the
 * backend-issued JWT (no refresh until RB-3 ships). */
export const OIDC_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;

function sessionMaxAge(session: SessionPayload): number {
  if (session.mode === "oidc") return OIDC_SESSION_MAX_AGE_SECONDS;
  return Math.max(0, session.accessTokenExpiresAt - Math.floor(Date.now() / 1000));
}

export async function sealedSessionCookie(session: SessionPayload) {
  return {
    name: SESSION_COOKIE,
    value: await sealSession(session, env.SESSION_SECRET, sessionMaxAge(session)),
    options: {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax" as const,
      path: "/",
      maxAge: sessionMaxAge(session)
    }
  };
}

export async function setSessionCookie(session: SessionPayload): Promise<void> {
  const cookie = await sealedSessionCookie(session);
  const store = await cookies();
  store.set(cookie.name, cookie.value, cookie.options);
}

export async function clearSessionCookie(): Promise<void> {
  const store = await cookies();
  store.delete(SESSION_COOKIE);
}

export async function getSession(): Promise<SessionPayload | null> {
  const store = await cookies();
  const raw = store.get(SESSION_COOKIE)?.value;
  if (!raw) return null;
  return openSession(raw, env.SESSION_SECRET);
}

export async function requireSession(): Promise<SessionPayload> {
  const session = await getSession();
  if (!session) redirect("/login");
  return session;
}

/**
 * Returns a currently-valid access token, or null when there is no session
 * left to save (no cookie, refresh rejected, or an expired password-mode
 * token — no refresh until RB-3). Refreshes when needed.
 *
 * The primary sliding refresh happens in proxy.ts (which can always write
 * cookies). This path covers everything proxy.ts skips: in route handlers
 * and server actions the refreshed session is persisted; in RSC rendering
 * cookie writes throw, so the refreshed token is used in-memory and
 * persistence is left to the next proxied request.
 */
export async function getAccessTokenOrNull(): Promise<string | null> {
  const session = await getSession();
  if (!session) return null;
  if (!needsRefresh(session)) return session.accessToken;

  if (session.mode === "oidc" && session.refreshToken) {
    let refreshed;
    try {
      refreshed = await refreshTokens(session.refreshToken);
    } catch {
      // Refresh token rejected or IdP unreachable: the session is over.
      return null;
    }
    const next: SessionPayload = {
      ...session,
      accessToken: refreshed.accessToken,
      accessTokenExpiresAt: refreshed.accessTokenExpiresAt,
      refreshToken: refreshed.refreshToken ?? session.refreshToken,
      idToken: refreshed.idToken ?? session.idToken
    };
    try {
      await setSessionCookie(next);
    } catch {
      // RSC render: cookies are read-only here; proxy.ts persists on the
      // next request.
    }
    return next.accessToken;
  }

  if (session.accessTokenExpiresAt <= Math.floor(Date.now() / 1000)) {
    return null;
  }
  return session.accessToken;
}

/** Like getAccessTokenOrNull, but redirects to /login instead of returning null. */
export async function getAccessToken(): Promise<string> {
  const token = await getAccessTokenOrNull();
  if (!token) redirect("/login");
  return token;
}
