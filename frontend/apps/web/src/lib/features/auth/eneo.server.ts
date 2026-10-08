/**
 * Login via eneo's own endpoints. This is a legacy login method and requires users
 * to be registered directly in eneo with username and password.
 */

import { readTraceId } from "@eneo/eneo-js";
import { setFrontendAuthCookie } from "./auth.server";
import { getRequestEvent } from "$app/server";
import { getBackendUrl } from "$lib/core/environment.server";

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

type LoginFailure = Pick<EneoLoginResult, "attemptsRemaining" | "retryAfterSeconds"> & {
  /** The backend's error code, when the body carried one. */
  code: string | null;
};

function readCode(fields: Record<string, unknown>): string | null {
  if (typeof fields.code === "string") return fields.code;
  // FastAPI's own HTTPException shape: `{ "detail": { "code": ... } }`.
  const detail = fields.detail;
  if (typeof detail === "object" && detail !== null) {
    const code = (detail as Record<string, unknown>).code;
    if (typeof code === "string") return code;
  }
  return null;
}

async function readFailure(response: Response): Promise<LoginFailure> {
  const empty: LoginFailure = { attemptsRemaining: null, retryAfterSeconds: null, code: null };
  try {
    const body: unknown = await response.json();
    if (typeof body !== "object" || body === null) {
      return empty;
    }
    const fields = body as Record<string, unknown>;
    return {
      attemptsRemaining: readNonNegativeInteger(fields.attempts_remaining),
      retryAfterSeconds: readNonNegativeInteger(fields.retry_after_seconds),
      code: readCode(fields)
    };
  } catch {
    return empty;
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

  // `event.fetch` goes through `handleFetch`, which turns this into a
  // server-to-server call against ENEO_BACKEND_SERVER_URL.
  const { fetch } = getRequestEvent();

  let response: Response;
  try {
    response = await fetch(`${getBackendUrl()}/api/v1/users/login/token/`, {
      body,
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
      }
    });
  } catch (error) {
    // The backend never answered (wrong internal URL, DNS, closed socket), so
    // there is no trace id. The form shows the generic failure instead of a
    // 500 page; the reason is in the server log.
    console.error(
      "Username/password login failed before reaching the backend: %s",
      error instanceof Error ? error.message : String(error)
    );
    return { success: false, traceId: null, correlationId: null };
  }

  // Available on both success and failure.
  const traceId = readTraceId(response.headers) ?? null;

  if (!response.ok) {
    const { code, ...attemptLimit } = await readFailure(response);
    // The code tells a misconfiguration (`disallowed_cors_origin`) apart from
    // wrong credentials (`invalid_credentials`) without logging the body.
    console.error(
      "Username/password login failed. Status: %s, Code: %s, Trace ID: %s",
      response.status,
      code ?? "none",
      traceId || "none"
    );
    return { success: false, traceId, correlationId: traceId, ...attemptLimit };
  }

  try {
    const { access_token } = await response.json();
    // Bit weird renaming going on here, but that is how it is, as the backend calls this "access token"
    await setFrontendAuthCookie({ id_token: access_token });
    return { success: true, traceId, correlationId: traceId };
  } catch (e) {
    console.error("Failed to decode login response. Trace ID: %s", traceId || "none");
    return { success: false, traceId, correlationId: traceId };
  }
}
