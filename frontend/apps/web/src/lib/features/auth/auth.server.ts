import { dev } from "$app/environment";
import { getRequestEvent } from "$app/server";
import { type RequestEvent } from "@sveltejs/kit";

export const IntricIdTokenCookie = "auth";
export const IntricAccessTokenCookie = "acc";

export const setFrontendAuthCookie = async (tokens: {
  id_token: string;
  access_token?: string;
}) => {
  const { cookies } = getRequestEvent();

  // Decode token to get expiry
  const token_info = (await parseJwt(tokens.id_token)) as { exp?: number | string };
  const nowSec = Math.floor(Date.now() / 1000);

  // Robust exp extraction with type guarding (handles string exp from JWT parsing)
  const expSecCandidate = token_info?.exp;
  const expSec = Number.isFinite(Number(expSecCandidate))
    ? Number(expSecCandidate)
    : (() => {
        console.warn("[Auth] JWT exp missing/invalid – using 2h fallback", {
          hasExp: Boolean(expSecCandidate),
          expType: typeof expSecCandidate
        });
        return nowSec + 7200; // fallback: now + 2 hours
      })();

  // Calculate maxAge with 10-minute buffer (expires before server token)
  const maxAge = Math.max(0, expSec - nowSec - 600);

  cookies.set(IntricIdTokenCookie, tokens.id_token, {
    path: "/",
    httpOnly: true,
    maxAge,
    secure: !dev,
    sameSite: "lax"
  });

  if (tokens.access_token) {
    cookies.set(IntricAccessTokenCookie, tokens.access_token, {
      path: "/",
      httpOnly: true,
      maxAge,
      secure: !dev,
      sameSite: "lax"
    });
  }
};

/**
 * Checks if any auth cookie is set and return the id_token if found.
 * Not checking for validity; backend requests will fail if the jwt is not valid and we just throw out the user
 */
export function authenticateUser(event: RequestEvent): {
  id_token?: string;
  access_token?: string;
} {
  const { cookies } = event;
  const id_token = cookies.get(IntricIdTokenCookie);
  const access_token = cookies.get(IntricAccessTokenCookie);

  return {
    id_token,
    access_token
  };
}

/**
 * Will clear any cookie previously set
 */
export const clearFrontendCookies = (event: RequestEvent) => {
  event.cookies.getAll().forEach((cookie) => {
    event.cookies.delete(cookie.name, { path: "/" });
  });
};

// -------- HELPER functions ---------------------------------------------------------------------------
/** Will try to parse a JWT, returns an empty object on failure */
export async function parseJwt(token: string) {
  try {
    const raw = atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"));
    const buffer = Uint8Array.from(raw, (m) => m.codePointAt(0) ?? 0);
    return await JSON.parse(new TextDecoder().decode(buffer));
  } catch {
    return {};
  }
}

/** Create a codepair for OIDC PCKE flow */
export async function createCodePair() {
  const codeVerifier = generateCodeVerifier();
  const codeChallenge = await generateCodeChallenge(codeVerifier);
  return { codeVerifier, codeChallenge };
}

// We can't use regualar base64, as it includes the + and / characters.
// We replace them in this implementation. We also remove the added = padding in the end.
// https://datatracker.ietf.org/doc/html/rfc7636#page-8
function base64Encode(data: Uint8Array) {
  return btoa(String.fromCharCode(...data))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");
}

function generateCodeVerifier() {
  const data = new Uint8Array(32);
  crypto.getRandomValues(data);
  const verifier = base64Encode(data);

  return verifier;
}

async function generateCodeChallenge(verifier: string) {
  const data = new TextEncoder().encode(verifier);
  const hashed = new Uint8Array(await crypto.subtle.digest("SHA-256", data));
  const challenge = base64Encode(hashed);

  return challenge;
}

// Helpers for state to send/receive via zitadel
type LoginMehtod = "zitadel" | "mobilityguard";

export type LoginStateParam = {
  loginMethod: LoginMehtod;
  next: string | null;
};

export type LogoutStateParam = {
  completed: boolean;
  message?: string;
};

// This is just a "typesafe" wrapper around JSON.stringify; as we're using URLSearchParams to construct
// the url, the outputted string will automatically get URLencoded and we dont need to do it manually.
export function encodeState<T extends LoginStateParam | LogoutStateParam>(state: T): string {
  return JSON.stringify(state);
}

// This is just a "typesafe" wrapper around JSON.parse; as we're using searchParams.get() to retrieve
// the state, the outputted string will automatically get URLdecoded and we dont need to do it manually.
export function decodeState<T extends LoginStateParam | LogoutStateParam>(
  state: string | null
): T | null {
  if (state) {
    try {
      return JSON.parse(state) as T;
    } catch {
      return null;
    }
  }
  return null;
}
