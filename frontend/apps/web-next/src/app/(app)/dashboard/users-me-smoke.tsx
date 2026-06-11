import { env } from "@/lib/env";
import { getAccessToken } from "@/lib/auth/session";

/**
 * Phase 2 smoke probe: proves the session's bearer token is accepted by the
 * backend (IdP token via RB-1 in OIDC mode, Eneo JWT in password mode).
 * Removed in Phase 3 when the typed API client lands.
 */
export async function UsersMeSmoke() {
  const token = await getAccessToken();

  let result: string;
  try {
    const response = await fetch(`${env.ENEO_BACKEND_URL}/api/v1/users/me/`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store"
    });
    if (response.ok) {
      const body = (await response.json()) as { email?: string };
      result = `GET /users/me/ → 200 (${body.email ?? "no email in response"})`;
    } else {
      result = `GET /users/me/ → ${response.status}`;
    }
  } catch {
    result = "GET /users/me/ → backend unreachable";
  }

  return <p className="text-muted-foreground font-mono text-xs">{result}</p>;
}
