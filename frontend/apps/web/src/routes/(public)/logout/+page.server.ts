import { redirect } from "@sveltejs/kit";
import {
  clearFrontendCookies,
  decodeState,
  encodeState,
  EneoAccessTokenCookie,
  EneoIdTokenCookie,
  type LogoutStateParam
} from "$lib/features/auth/auth.server";
import { env } from "$env/dynamic/private";
import type { Actions, PageServerLoad } from "./$types";

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

// Navigation, image requests and IdP callbacks only read the current state.
// In particular, an old callback must not clear a newer login session.
export const load = (({ url, locals }) => {
  const state = decodeState<LogoutStateParam>(url.searchParams.get("state"));
  const message = state?.completed ? state.message : url.searchParams.get("message");
  return {
    message: message === "expired" ? "expired" : "logout",
    signedIn: Boolean(locals.id_token)
  };
}) satisfies PageServerLoad;

// SvelteKit form actions require form-encoded POSTs and enforce its origin
// check before any cookies change. Keep the three user intents distinct:
// recovery and organisation switching must not end the provider's session.
export const actions = {
  logout: async (event) => {
    const form = await event.request.formData();
    const message = form.get("message") === "expired" ? "expired" : "logout";
    clearFrontendCookies(event);

    if (event.locals.featureFlags.newAuth) {
      const searchParams = new URLSearchParams({
        client_id: env.ZITADEL_PROJECT_CLIENT_ID!,
        post_logout_redirect_uri: `${getPublicOrigin()}/logout`,
        state: encodeState({ completed: true, message })
      });
      if (event.locals.id_token) searchParams.set("id_token_hint", event.locals.id_token);
      redirect(303, `${env.ZITADEL_INSTANCE_URL}/oidc/v1/end_session?${searchParams}`);
    }

    redirect(303, `/login?message=${message}`);
  },
  clearCookies: (event) => {
    clearFrontendCookies(event);
    redirect(303, "/login");
  },
  switchOrganisation: ({ cookies }) => {
    cookies.delete(EneoIdTokenCookie, { path: "/" });
    cookies.delete(EneoAccessTokenCookie, { path: "/" });
    redirect(303, "/login");
  }
} satisfies Actions;
