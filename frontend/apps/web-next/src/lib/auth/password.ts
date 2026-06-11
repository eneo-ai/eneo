import { decodeJwt } from "jose";
import { env } from "@/lib/env";
import type { SessionPayload } from "@/lib/auth/session-codec";

export type PasswordLoginResult =
  | { ok: true; session: SessionPayload }
  | { ok: false; error: "invalid_credentials" | "deactivated" | "unavailable" };

/**
 * Password login against the backend's OAuth2 password flow. The returned
 * Eneo JWT carries sub = email and exp; there is no refresh (RB-3), so the
 * session lives exactly as long as the token.
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

  if (response.status === 401) return { ok: false, error: "invalid_credentials" };
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
