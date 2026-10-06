import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { env } from "@/lib/env";
import { openSession, sealSession, type SessionPayload } from "@/lib/auth/session-codec";

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

/** Read-only in RSC, handlers and actions. proxy.ts owns refresh and persistence. */
export async function getAccessTokenOrNull(): Promise<string | null> {
  const session = await getSession();
  if (!session || session.accessTokenExpiresAt <= Math.floor(Date.now() / 1000)) return null;
  return session.accessToken;
}

/** Like getAccessTokenOrNull, but redirects instead of returning null. Goes
 * through the logout route (not /login directly) so the dead-but-decryptable
 * cookie is cleared — /login bounces cookie-holders into the app. */
export async function getAccessToken(): Promise<string> {
  const token = await getAccessTokenOrNull();
  if (!token) redirect("/logout?reason=expired");
  return token;
}
