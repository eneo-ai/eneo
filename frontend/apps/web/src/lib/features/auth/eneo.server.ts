/**
 * Login via eneo's own endpoints. This is a legacy login method and requires users
 * to be registered directly in eneo with username and password.
 */

import { setFrontendAuthCookie } from "./auth.server";
import { getRequestEvent } from "$app/server";
import { getBackendUrl } from "$lib/core/environment.server";

/**
 * Try to login a user. If successful, the `auth` cookie will be set.
 *
 * @returns Object with success status and trace ID for error tracking.
 *   ``correlationId`` is a same-value alias for ``traceId`` retained during
 *   the migration period — prefer ``traceId`` in new code.
 */
export async function loginWithEneo(
  username: string,
  password: string
): Promise<{ success: boolean; traceId: string | null; correlationId: string | null }> {
  // Endpoint wants urlencoded data
  const body = new URLSearchParams();

  body.append("username", username);
  body.append("password", password);

  const { fetch } = getRequestEvent();

  const response = await fetch(`${getBackendUrl()}/api/v1/users/login/token/`, {
    body: body,
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
    }
  });

  // Extract trace ID from response headers (available on both success and failure).
  // Prefer X-Trace-Id; fall back to legacy X-Correlation-ID during the migration period.
  const traceId =
    response.headers.get("X-Trace-Id") || response.headers.get("X-Correlation-ID") || null;

  if (!response.ok) {
    console.error(
      "Username/password login failed. Status: %s, Trace ID: %s",
      response.status,
      traceId || "none"
    );
    return { success: false, traceId, correlationId: traceId };
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
