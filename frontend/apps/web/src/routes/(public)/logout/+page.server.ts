import { redirect } from "@sveltejs/kit";
import {
  clearFrontendCookies,
  decodeState,
  encodeState,
  type LogoutStateParam
} from "$lib/features/auth/auth.server";
import { env } from "$env/dynamic/private";
import { getBackendUrl } from "$lib/core/environment.server";

/**
 * Get the configured public origin for OIDC redirect URIs.
 *
 * SECURITY: Uses explicit PUBLIC_ORIGIN configuration instead of
 * event.url.origin to prevent redirect_uri mismatches behind reverse proxies.
 *
 * @returns The configured public origin (e.g., "https://eneo.sundsvall.se")
 * @throws Error if PUBLIC_ORIGIN is not configured
 */
function getPublicOrigin(): string {
  const publicOrigin = (env as Record<string, string | undefined>).PUBLIC_ORIGIN;
  if (!publicOrigin) {
    throw new Error(
      "[OIDC] PUBLIC_ORIGIN environment variable is required for OIDC authentication. " +
        "Set it to the externally-reachable URL for this application. " +
        "Example: PUBLIC_ORIGIN=https://eneo.sundsvall.se"
    );
  }

  // Validate format (basic check)
  if (!publicOrigin.startsWith("https://")) {
    throw new Error(
      "[OIDC] PUBLIC_ORIGIN must be an https:// URL for security. " + `Got: ${publicOrigin}`
    );
  }

  // Remove trailing slash if present
  return publicOrigin.replace(/\/$/, "");
}

async function revokeBackendOidcTokens(event: Parameters<typeof load>[0]) {
  // Tell the backend to zero the user's persisted IdP refresh/access tokens
  // before we drop the local session cookies. Failure is non-fatal; the
  // refresh token will still age out on its own, but we surface the error
  // in the server log so operators notice if revocation is misconfigured.
  const accessToken = event.locals.access_token ?? event.locals.id_token;
  if (!accessToken) {
    return;
  }
  const backendOrigin = getBackendUrl();
  if (!backendOrigin) {
    return;
  }
  try {
    await event.fetch(`${backendOrigin.replace(/\/$/, "")}/api/v1/auth/oidc/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` }
    });
  } catch (e) {
    console.warn("[auth] Failed to revoke backend OIDC tokens at logout", e);
  }
}

export const load = async (event) => {
  // Revoke backend-stored IdP tokens BEFORE the cookies are dropped so the
  // bearer header is still available for the call.
  await revokeBackendOidcTokens(event);

  // always delete cookies
  clearFrontendCookies(event);

  // Message to show, we just pass this on
  const message = event.url.searchParams.get("message") ?? undefined;

  // Feature flag should guarantee ZITADEL_PROJECT_CLIENT_ID and ZITADEL_INSTANCE_URL to be set
  if (event.locals.featureFlags.newAuth) {
    const state = decodeState<LogoutStateParam>(event.url.searchParams.get("state"));

    // If we are coming back from Zitadel (state.completed === true),
    // We return and the +page.svelte will be rendered with the message like a normal page load
    if (state && state.completed) {
      return {
        message: state.message ?? "logout"
      };
    }

    // Otherwise we first redirect to Zitadel for logout and wait until we come back from there
    const searchParams = new URLSearchParams({
      client_id: env.ZITADEL_PROJECT_CLIENT_ID!,
      post_logout_redirect_uri: `${getPublicOrigin()}/logout`,
      state: encodeState({
        completed: true,
        message
      })
    });

    if (event.locals.id_token) {
      searchParams.append("id_token_hint", event.locals.id_token);
    }

    const redirectUrl =
      env.ZITADEL_INSTANCE_URL! + "/oidc/v1/end_session?" + searchParams.toString();

    redirect(302, redirectUrl);
  }

  // Fallback for old auth
  redirect(302, `/login?message=${message ?? "logout"}`);
};
