/**
 * Login via intric's own endpoints. This is a legacy login method and requires users
 * to be registered directly in intric with username and password.
 */

import { setFrontendAuthCookie } from "./auth.server";
import { getRequestEvent } from "$app/server";
import { env } from "$env/dynamic/private";

/**
 * Try to login a user. If successful, the `auth` cookie will be set.
 *
 * @returns Object with success status and correlation ID for error tracking
 */
export async function loginWithIntric(
  username: string,
  password: string
): Promise<{ success: boolean; correlationId: string | null }> {
  // Endpoint wants urlencoded data
  const body = new URLSearchParams();

  body.append("username", username);
  body.append("password", password);

  const { fetch } = getRequestEvent();

  const response = await fetch(`${env.INTRIC_BACKEND_URL}/api/v1/users/login/token/`, {
    body: body,
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
    }
  });

  // Extract correlation ID from response headers (available on both success and failure)
  const correlationId = response.headers.get("X-Correlation-ID") || null;

  if (!response.ok) {
    console.error(
      "Username/password login failed. Status: %s, Correlation ID: %s",
      response.status,
      correlationId || "none"
    );
    return { success: false, correlationId };
  }

  try {
    const { access_token } = await response.json();
    // Bit weird renaming going on here, but that is how it is, as the backend calls this "access token"
    await setFrontendAuthCookie({ id_token: access_token });
    return { success: true, correlationId };
  } catch (e) {
    console.error("Failed to decode login response. Correlation ID: %s", correlationId || "none");
    return { success: false, correlationId };
  }
}
