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
    console.error("[OIDC] Missing configuration (MobilityGuard):", {
      hasClientId: !!env.MOBILITYGUARD_CLIENT_ID,
      hasAuthUrl: !!env.MOBILITY_GUARD_AUTH
    });
    return false;
  }

  const event = getRequestEvent();
  const code_verifier = event.cookies.get(MobilityguardCookie);

  if (!code_verifier) {
    console.error(
      "[OIDC] No code_verifier cookie found. Cookies may be disabled or expired (MobilityGuard).",
      {
        cookieName: MobilityguardCookie,
        origin: event.url.origin
      }
    );
    return false;
  }

  console.debug("[OIDC] Starting login (MobilityGuard)", {
    hasCode: !!code,
    hasCodeVerifier: !!code_verifier,
    redirectUri: `${event.url.origin}/login/callback`,
    backendUrl: env.INTRIC_BACKEND_URL
  });

  const body = JSON.stringify({
    code,
    code_verifier,
    scope: scopes.join("+"),
    redirect_uri: `${event.url.origin}/login/callback`,
    client_id: env.MOBILITYGUARD_CLIENT_ID
  });

  const backendUrl = `${env.INTRIC_BACKEND_URL}/api/v1/users/login/openid-connect/mobilityguard/`;
  console.debug("[OIDC] Calling backend (MobilityGuard)", {
    url: backendUrl,
    redirectUri: `${event.url.origin}/login/callback`
  });

  try {
    const response = await event.fetch(backendUrl, {
      body,
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      }
    });

    if (!response.ok) {
      const responseText = await response.text();
      let errorDetails;
      try {
        errorDetails = JSON.parse(responseText);
      } catch {
        errorDetails = responseText;
      }

      console.error("[OIDC] Backend login failed (MobilityGuard)", {
        status: response.status,
        statusText: response.statusText,
        error: errorDetails,
        url: backendUrl
      });

      // Log different error scenarios
      if (response.status === 401) {
        console.error("[OIDC] Authentication failed - invalid credentials or token");
      } else if (response.status === 403) {
        console.error("[OIDC] Access forbidden - user may be inactive or tenant suspended");
      } else if (response.status === 500) {
        console.error("[OIDC] Server configuration error - check backend logs");
      } else if (response.status === 502) {
        console.error("[OIDC] Network/gateway error - check provider connectivity");
      }

      return false;
    }

    console.debug("[OIDC] Backend login successful");

    event.cookies.delete(MobilityguardCookie, { path: "/" });

    const data = await response.json();
    const { access_token } = data;

    if (!access_token) {
      console.error("[OIDC] No access token in response", { responseKeys: Object.keys(data) });
      return false;
    }

    // Bit weird renaming going on here, but that is how it is, as the backend calls this "access token"
    await setFrontendAuthCookie({ id_token: access_token });

    console.debug("[OIDC] Login complete, auth cookie set");
    return true;
  } catch (error) {
    console.error("[OIDC] Unexpected error during login (MobilityGuard)", {
      error: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack : undefined
    });
    return false;
  }
}

export function clearMobilityguardCookie(cookies: Cookies) {
  cookies.delete(MobilityguardCookie, { path: "/" });
}
