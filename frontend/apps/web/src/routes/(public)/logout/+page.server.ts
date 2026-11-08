import { fail, redirect } from "@sveltejs/kit";
import {
  clearFrontendCookies,
  decodeState,
  encodeState,
  endEneoSession,
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
 * @returns The configured public origin (e.g., "https://eneo.example.com")
 * @throws Error if PUBLIC_ORIGIN is not configured
 */
function getPublicOrigin(): string {
  const publicOrigin = (env as Record<string, string | undefined>).PUBLIC_ORIGIN;
  if (!publicOrigin) {
    throw new Error(
      "[OIDC] PUBLIC_ORIGIN environment variable is required for OIDC authentication. " +
        "Set it to the externally-reachable URL for this application. " +
        "Example: PUBLIC_ORIGIN=https://eneo.example.com"
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

type SignOutAction = "logout" | "switchOrganisation" | "clearCookies";

/** The session is still signed in, so its cookies stay and the page offers
 * the same action again. */
function signOutFailed(action: SignOutAction, message: "expired" | "logout" = "logout") {
  return fail(503, { signOutFailed: action, message });
}

// SvelteKit form actions require form-encoded POSTs and enforce its origin
// check before any cookies change. Keep the three user intents distinct:
// recovery and organisation switching must not end the provider's session.
// Each ends the Eneo session first, so a copy of its token stops working.
export const actions = {
  logout: async (event) => {
    const form = await event.request.formData();
    const message = form.get("message") === "expired" ? "expired" : "logout";
    if (!(await endEneoSession(event))) return signOutFailed("logout", message);
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
  clearCookies: async (event) => {
    if (!(await endEneoSession(event))) return signOutFailed("clearCookies");
    clearFrontendCookies(event);
    redirect(303, "/login");
  },
  switchOrganisation: async (event) => {
    if (!(await endEneoSession(event))) return signOutFailed("switchOrganisation");
    event.cookies.delete(EneoIdTokenCookie, { path: "/" });
    event.cookies.delete(EneoAccessTokenCookie, { path: "/" });
    redirect(303, "/login");
  }
} satisfies Actions;
