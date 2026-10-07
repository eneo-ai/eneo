/**
 * Login via eneo's own endpoints. This is a legacy login method and requires users
 * to be registered directly in eneo with username and password.
 */

import { readTraceId } from "@eneo/eneo-js";
import { setFrontendAuthCookie } from "./auth.server";
import { getBackendServerUrl } from "$lib/core/environment.server";

export type EneoLoginResult = {
  success: boolean;
  traceId: string | null;
  correlationId: string | null;
  attemptsRemaining?: number | null;
  retryAfterSeconds?: number | null;
};

function readNonNegativeInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

async function readAttemptLimit(
  response: Response
): Promise<Pick<EneoLoginResult, "attemptsRemaining" | "retryAfterSeconds">> {
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
 * Try to login a user. If successful, the `auth` cookie will be set.
 *
 * @returns Object with success status and trace ID for error tracking.
 *   ``correlationId`` is a same-value alias for ``traceId`` retained during
 *   the migration period — prefer ``traceId`` in new code. After a failure,
 *   ``attemptsRemaining`` and ``retryAfterSeconds`` carry the attempt limit's
 *   standing when the backend reported it.
 */
export async function loginWithEneo(username: string, password: string): Promise<EneoLoginResult> {
  // Endpoint wants urlencoded data
  const body = new URLSearchParams();
  body.append("username", username);
  body.append("password", password);

  // Server-to-server call: use the internal backend URL with native fetch.
  // Do NOT use getRequestEvent().fetch + getBackendUrl() (public/same-origin):
  // SvelteKit resolves same-origin event.fetch internally, so it never reaches
  // the backend (400) behind a reverse proxy.
  const response = await fetch(`${getBackendServerUrl()}/api/v1/users/login/token/`, {
    body,
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" }
  });

  // Available on both success and failure.
  const traceId = readTraceId(response.headers) ?? null;

  if (!response.ok) {
    console.error(
      "Username/password login failed. Status: %s, Trace ID: %s",
      response.status,
      traceId || "none"
    );
    return {
      success: false,
      traceId,
      correlationId: traceId,
      ...(await readAttemptLimit(response))
    };
  }

  try {
    const { access_token } = await response.json();
    await setFrontendAuthCookie({ id_token: access_token });
    return { success: true, traceId, correlationId: traceId };
  } catch (e) {
    console.error("Failed to decode login response. Trace ID: %s", traceId || "none");
    return { success: false, traceId, correlationId: traceId };
  }
}
