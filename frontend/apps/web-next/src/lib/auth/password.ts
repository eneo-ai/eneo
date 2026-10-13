import { decodeJwt } from "jose";
import { env } from "@/lib/env";
import type { SessionPayload } from "@/lib/auth/session-codec";

/**
 * The attempt limit's standing after a refused password login, when the
 * backend reported it (it counts failed attempts per account). `null` when
 * the response did not say.
 */
export interface LoginAttemptLimit {
  /** Failed attempts left before the account is blocked for a while. */
  attemptsRemaining: number | null;
  /** How long the account stays blocked, in seconds. */
  retryAfterSeconds: number | null;
}

export type PasswordLoginResult =
  | { ok: true; session: SessionPayload }
  | {
      ok: false;
      error: "invalid_credentials" | "too_many_attempts" | "deactivated" | "unavailable";
      limit?: LoginAttemptLimit;
    };

function readNonNegativeInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

/** The limit fields the backend puts at the top of a 401 or 429 body. */
async function readAttemptLimit(response: Response): Promise<LoginAttemptLimit> {
  try {
    const body: unknown = await response.json();
    if (typeof body !== "object" || body === null) {
      return { attemptsRemaining: null, retryAfterSeconds: null };
    }
    const fields = body as Record<string, unknown>;
    return {
      attemptsRemaining: readNonNegativeInteger(fields.attempts_remaining),
      retryAfterSeconds: readNonNegativeInteger(fields.retry_after_seconds)
    };
  } catch {
    return { attemptsRemaining: null, retryAfterSeconds: null };
  }
}

/**
 * Password login against the backend's OAuth2 password flow. The returned
 * Eneo JWT carries sub = email and exp; there is no refresh (RB-3), so the
 * session lives exactly as long as the token. A refused login carries the
 * attempt limit's standing when the backend reported it.
 */
export async function passwordLogin(email: string, password: string): Promise<PasswordLoginResult> {
  let response: Response;
  try {
    response = await fetch(`${env.ENEO_BACKEND_URL}/api/v1/users/login/token/`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ username: email, password })
    });
  } catch {
    return { ok: false, error: "unavailable" };
  }

  if (response.status === 401) {
    return { ok: false, error: "invalid_credentials", limit: await readAttemptLimit(response) };
  }
  if (response.status === 429) {
    return { ok: false, error: "too_many_attempts", limit: await readAttemptLimit(response) };
  }
  if (response.status === 403) return { ok: false, error: "deactivated" };
  if (!response.ok) return { ok: false, error: "unavailable" };

  const body = (await response.json()) as { access_token: string };
  const session = sessionFromEneoJwt(body.access_token);
  if (!session) return { ok: false, error: "unavailable" };
  return { ok: true, session };
}

/** Builds a password-mode session from a backend-issued Eneo JWT. */
export function sessionFromEneoJwt(accessToken: string): SessionPayload | null {
  try {
    const claims = decodeJwt(accessToken);
    if (typeof claims.sub !== "string" || typeof claims.exp !== "number") return null;
    return {
      mode: "password",
      accessToken,
      accessTokenExpiresAt: claims.exp,
      user: { email: claims.sub }
    };
  } catch {
    return null;
  }
}
