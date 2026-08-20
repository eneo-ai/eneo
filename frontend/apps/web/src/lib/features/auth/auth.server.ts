import { dev } from "$app/environment";
import { getRequestEvent } from "$app/server";
import { DEFAULT_LANDING_PAGE } from "$lib/core/constants";
import { type Cookies, type RequestEvent } from "@sveltejs/kit";

export const EneoIdTokenCookie = "auth";
export const EneoAccessTokenCookie = "acc";
export const OidcLoginResumeCookie = "oidc-login-resume";

const OIDC_LOGIN_RESUME_MAX_AGE_SECONDS = 10 * 60;
// Leave room for the cookie name and attributes below the common 4 KiB limit.
const OIDC_LOGIN_RESUME_MAX_ENCODED_LENGTH = 3000;

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

  cookies.set(EneoIdTokenCookie, tokens.id_token, {
    path: "/",
    httpOnly: true,
    maxAge,
    secure: !dev,
    sameSite: "lax"
  });

  if (tokens.access_token) {
    cookies.set(EneoAccessTokenCookie, tokens.access_token, {
      path: "/",
      httpOnly: true,
      maxAge,
      secure: !dev,
      sameSite: "lax"
    });
  } else {
    // `acc` is a provider access token (currently Zitadel), not a second copy
    // of the Eneo session JWT. Authentication methods without such a token
    // must remove a stale value left by an earlier provider login.
    cookies.delete(EneoAccessTokenCookie, { path: "/" });
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
  const id_token = cookies.get(EneoIdTokenCookie);
  const access_token = cookies.get(EneoAccessTokenCookie);

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

// Helpers for state shared by every login provider.
type LoginMethod = "zitadel" | "mobilityguard" | "oidc";

export type LoginStateParam = {
  loginMethod: LoginMethod;
  next: string | null;
  /** Server-generated correlation value for the HttpOnly resume cookie. */
  attemptId?: string;
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

/**
 * Resolve an untrusted post-login destination without rewriting its encoding.
 *
 * `next` crosses form fields and OIDC state. Validation may decode a copy to
 * catch browser path ambiguities, but the returned value is always the exact
 * original string so opaque module state is not double-decoded.
 */
export function resolveSafeLoginDestination(destination: unknown): string {
  return resolveValidatedLoginDestination(destination) ?? DEFAULT_LANDING_PAGE;
}

function resolveValidatedLoginDestination(destination: unknown): string | null {
  if (
    typeof destination !== "string" ||
    !destination.startsWith("/") ||
    destination.startsWith("//") ||
    destination.includes("\\") ||
    containsControlCharacter(destination)
  ) {
    return null;
  }

  try {
    const decodedForValidation = decodeURIComponent(destination);
    if (
      decodedForValidation.startsWith("//") ||
      decodedForValidation.includes("\\") ||
      containsControlCharacter(decodedForValidation)
    ) {
      return null;
    }

    const validationOrigin = "https://login-destination.invalid";
    if (new URL(destination, validationOrigin).origin !== validationOrigin) {
      return null;
    }
  } catch {
    return null;
  }

  return destination;
}

function containsControlCharacter(value: string): boolean {
  return Array.from(value).some((character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return codePoint <= 31 || codePoint === 127;
  });
}

export function resolveLoginStateDestination(state: string | null): string {
  return resolveOptionalLoginStateDestination(state) ?? DEFAULT_LANDING_PAGE;
}

export function resolveOptionalLoginStateDestination(state: string | null): string | null {
  const decodedState = decodeState<LoginStateParam>(state);
  return resolveValidatedLoginDestination(decodedState?.next);
}

/**
 * Remember one already-validated local destination while the browser is away
 * at a generic OIDC provider. The value is HttpOnly and can never carry an
 * external redirect. Oversized values are discarded instead of risking a
 * rejected Set-Cookie header.
 */
type OidcLoginResumeBinding = {
  attemptId: string;
  destination: string;
};

const OIDC_ATTEMPT_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function rememberOidcLoginDestination(
  cookies: Cookies,
  destination: unknown,
  attemptId: string
): void {
  const safeDestination = resolveValidatedLoginDestination(destination);
  const binding: OidcLoginResumeBinding = {
    attemptId,
    destination: safeDestination ?? ""
  };
  const serializedBinding = JSON.stringify(binding);

  try {
    if (
      safeDestination === null ||
      !OIDC_ATTEMPT_ID_PATTERN.test(attemptId) ||
      encodeURIComponent(serializedBinding).length > OIDC_LOGIN_RESUME_MAX_ENCODED_LENGTH
    ) {
      clearOidcLoginDestination(cookies);
      return;
    }
  } catch {
    clearOidcLoginDestination(cookies);
    return;
  }

  cookies.set(OidcLoginResumeCookie, serializedBinding, {
    path: "/",
    httpOnly: true,
    maxAge: OIDC_LOGIN_RESUME_MAX_AGE_SECONDS,
    secure: !dev,
    sameSite: "lax"
  });
}

/**
 * Read a one-shot generic OIDC resume destination bound to this callback.
 *
 * The signed state is still validated by the backend before authentication.
 * Here its unverified frontend payload is used only as a correlation value
 * against an HttpOnly cookie. A mismatch is left untouched so a parallel
 * login attempt cannot consume another tab's destination.
 */
export async function consumeOidcLoginDestination(
  cookies: Cookies,
  callbackState: string | null
): Promise<string | null> {
  const encodedBinding = cookies.get(OidcLoginResumeCookie);
  if (encodedBinding === undefined) {
    return null;
  }

  let binding: OidcLoginResumeBinding;
  try {
    const candidate = JSON.parse(encodedBinding) as Partial<OidcLoginResumeBinding>;
    if (
      typeof candidate.attemptId !== "string" ||
      !OIDC_ATTEMPT_ID_PATTERN.test(candidate.attemptId) ||
      typeof candidate.destination !== "string"
    ) {
      clearOidcLoginDestination(cookies);
      return null;
    }
    binding = {
      attemptId: candidate.attemptId,
      destination: candidate.destination
    };
  } catch {
    clearOidcLoginDestination(cookies);
    return null;
  }

  const destination = resolveValidatedLoginDestination(binding.destination);
  if (destination === null) {
    clearOidcLoginDestination(cookies);
    return null;
  }
  if (callbackState === null) {
    return null;
  }

  const statePayload = (await parseJwt(callbackState)) as { frontend_state?: unknown };
  const frontendState =
    typeof statePayload.frontend_state === "string"
      ? decodeState<LoginStateParam>(statePayload.frontend_state)
      : null;
  if (frontendState?.attemptId !== binding.attemptId) {
    return null;
  }

  clearOidcLoginDestination(cookies);
  return destination;
}

export function clearOidcLoginDestination(cookies: Cookies): void {
  cookies.delete(OidcLoginResumeCookie, { path: "/" });
}
