/**
 * Login via intric's own endpoints. This is a legacy login method and requires users
 * to be registered directly in intric with username and password.
 */

import { setFrontendAuthCookie } from "./auth.server";
import { getRequestEvent } from "$app/server";
import { env } from "$env/dynamic/private";

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

  const response = await fetch(`${env.INTRIC_BACKEND_URL}/api/v1/users/login/token/`, {
    body: body,
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
    }
  });

  if (!response.ok) {
    console.error("Unable to call backend service. Error: %s", response.statusText);
    return false;
  }

  try {
    const { access_token } = await response.json();
    // Bit weird renaming going on here, but that is how it is, as the backend calls this "access token"
    await setFrontendAuthCookie({ id_token: access_token });
    return true;
  } catch (e) {
    console.error("Failed to decode login response");
    return false;
  }
}
