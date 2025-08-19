/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

/**
 * Login via a combination of MobilityGuard and intric's own endpoints.
 */

import { dev } from "$app/environment";
import { env } from "$env/dynamic/private";
import type { Cookies } from "@sveltejs/kit";
import { createCodePair, encodeState, setFrontendAuthCookie } from "./auth.server";
import { getRequestEvent } from "$app/server";

const MobilityguardCookie = "mobilityguard-verifier" as const;
const scopes = ["openid", "email"];

export async function getMobilityguardLink(event: { url: URL; cookies: Cookies }) {
  // Only generate an url if the environment is correctly set
  if (!env.MOBILITYGUARD_CLIENT_ID || !env.MOBILITY_GUARD_AUTH) {
    // Log helpful warnings for missing configuration
    if (env.MOBILITY_GUARD_AUTH && !env.MOBILITYGUARD_CLIENT_ID) {
      console.warn("MobilityGuard is configured but MOBILITYGUARD_CLIENT_ID is not set");
    }
    if (env.MOBILITYGUARD_CLIENT_ID && !env.MOBILITY_GUARD_AUTH) {
      console.warn("MOBILITYGUARD_CLIENT_ID is set but MOBILITY_GUARD_AUTH is not configured");
    }
    return undefined;
  }

  const { codeVerifier, codeChallenge } = await createCodePair();

  event.cookies.set(MobilityguardCookie, codeVerifier, {
    path: "/",
    httpOnly: true,
    // Expires in one hour: 1 * (hour)
    expires: new Date(Date.now() + 1 * (60 * 60 * 1000)),
    secure: dev ? false : true,
    sameSite: "lax"
  });

  const searchParams = new URLSearchParams({
    scope: scopes.join(" "),
    client_id: env.MOBILITYGUARD_CLIENT_ID,
    response_type: "code",
    redirect_uri: `${event.url.origin}/login/callback`,
    state: encodeState({
      loginMethod: "mobilityguard",
      next: event.url.searchParams.get("next")
    }),
    code_challenge: codeChallenge,
    code_challenge_method: "S256"
  });

  return env.MOBILITY_GUARD_AUTH + "?" + searchParams.toString();
}

export async function loginWithMobilityguard(code: string): Promise<boolean> {
  // Only try to login if the environment is correctly set
  if (!env.MOBILITYGUARD_CLIENT_ID || !env.MOBILITY_GUARD_AUTH) {
    return false;
  }

  const event = getRequestEvent();
  const code_verifier = event.cookies.get(MobilityguardCookie);

  if (!code_verifier) {
    return false;
  }

  const body = JSON.stringify({
    code,
    code_verifier,
    scope: scopes.join("+"),
    redirect_uri: `${event.url.origin}/login/callback`
  });

  const response = await event.fetch(
    `${env.INTRIC_BACKEND_URL}/api/v1/users/login/openid-connect/mobilityguard/`,
    {
      body,
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      }
    }
  );

  if (!response.ok) {
    return false;
  }

  event.cookies.delete(MobilityguardCookie, { path: "/" });

  const data = await response.json();
  const { access_token } = data;
  // Bit weird renaming going on here, but that is how it is, as the backend calls this "access token"
  await setFrontendAuthCookie({ id_token: access_token });

  return true;
}

export function clearMobilityguardCookie(cookies: Cookies) {
  cookies.delete(MobilityguardCookie, { path: "/" });
}