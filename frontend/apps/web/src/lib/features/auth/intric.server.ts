/**
 * Login via intric's own endpoints. This is a legacy login method and requires users
 * to be registered directly in intric with username and password.
 */

import { setFrontendAuthCookie } from "./auth.server";
import { getRequestEvent } from "$app/server";
import { env } from "$env/dynamic/private";
import { logger } from "$lib/utils/logger";

/**
 * Try to login an user. If successful, the `auth` cookie will be set and the function returns `true`
 * Otherwise the function will return `false`
 */
export async function loginWithIntric(username: string, password: string): Promise<boolean> {
  // Endpoint wants urlencoded data
  const body = new URLSearchParams();

  body.append("username", username);
  body.append("password", password);

  const { fetch } = getRequestEvent();
  const loginUrl = `${env.INTRIC_BACKEND_URL}/api/v1/users/login/token/`;
  logger.log("Logging in user %s via Intric backend %s", username, env.INTRIC_BACKEND_URL);
  logger.log("[LOGIN] Calling URL: %s", loginUrl);

  const response = await fetch(loginUrl, {
    body: body,
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
    }
  });

  if (!response.ok) {
    logger.error("[LOGIN] ❌ Login failed!");
    logger.error("[LOGIN] URL: %s", loginUrl);
    logger.error("[LOGIN] Status: %d", response.status);
    logger.error("[LOGIN] Status Text: %s", response.statusText);
    logger.error("[LOGIN] Headers: %s", JSON.stringify(Object.fromEntries(response.headers.entries())));
    return false;
  }

  try {
    const { access_token } = await response.json();
    // Bit weird renaming going on here, but that is how it is, as the backend calls this "access token"
    await setFrontendAuthCookie({ id_token: access_token });
    return true;
  } catch (e) {
    logger.error("Failed to decode login response");
    return false;
  }
}
