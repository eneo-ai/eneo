import { resolveSafeLoginDestination } from "$lib/features/auth/auth.server";
import { initiateOidcLogin } from "$lib/features/auth/oidcInitiate.server";
import { fail, redirect, type Actions } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";

/** How a sign-in for multi-factor authentication can end without one. */
export type MfaSignInEnd = "mfa_not_met" | "mfa_not_configured";

function endOf(detailCode: string | null): MfaSignInEnd | null {
  return detailCode === "mfa_not_met" || detailCode === "mfa_not_configured" ? detailCode : null;
}

function endPath(end: MfaSignInEnd, next: string): string {
  return `/login/mfa?${new URLSearchParams({ detailCode: end, next })}`;
}

/**
 * Where a signed-in person signs in again for MFA, and where that sign-in
 * ends when it gave none. Unlike /login, this page never sends a signed-in
 * person on by itself: starting the sign-in and going back are both theirs
 * to press, so a provider that keeps answering without MFA cannot loop.
 */
export const load = ((event) => {
  return {
    next: resolveSafeLoginDestination(event.url.searchParams.get("next")),
    end: endOf(event.url.searchParams.get("detailCode")),
    correlation: event.url.searchParams.get("correlation")
  };
}) satisfies PageServerLoad;

export const actions: Actions = {
  default: async (event) => {
    const data = await event.request.formData();
    const destination = resolveSafeLoginDestination(data.get("next"));
    const held = event.locals.id_token;
    // Only someone who is signed in signs in for MFA; anyone else signs in
    // the ordinary way, where they also choose their organisation.
    if (!held) redirect(303, `/login?${new URLSearchParams({ next: destination })}`);

    const started = await initiateOidcLogin(event, {
      destination,
      tenant: null,
      mfa: { heldToken: held }
    });
    if (!started.ok) {
      if (started.code === "mfa_not_configured") {
        redirect(303, endPath("mfa_not_configured", destination));
      }
      return fail(503, { failed: true, unavailable: started.code === "oidc_login_unavailable" });
    }
    redirect(303, started.authorizationUrl);
  }
};
