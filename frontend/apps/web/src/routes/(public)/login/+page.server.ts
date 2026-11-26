import { env } from "$env/dynamic/private";
import { clearOidcLoginAttempt, resolveSafeLoginDestination } from "$lib/features/auth/auth.server";
import { loginWithEneo, type EneoLoginFailureReason } from "$lib/features/auth/eneo.server";
import { initiateOidcLogin } from "$lib/features/auth/oidcInitiate.server";
import { getZitadelLink } from "$lib/features/auth/zitadel.server";
import { redirect, fail, type Actions } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";

/** The form action's status per failure reason: a backend that could not
 * answer is a 503, a blocked account a 403, everything else the user's 400. */
const LOGIN_FAILURE_STATUS: Record<EneoLoginFailureReason, number> = {
  credentials: 400,
  rate_limited: 400,
  deactivated: 403,
  unavailable: 503
};

export const actions: Actions = {
  login: async (event) => {
    const data = await event.request.formData();
    const username = data.get("email")?.toString() ?? null;
    const password = data.get("password")?.toString() ?? null;
    const next = data.get("next")?.toString() ?? null;
    const redirectUrl = resolveSafeLoginDestination(next);

    if (username && password) {
      const { success, correlationId, attemptsRemaining, retryAfterSeconds, reason } =
        await loginWithEneo(username, password);

      if (success) {
        clearOidcLoginAttempt(event.cookies);
        redirect(302, redirectUrl);
      }

      // The page tells a backend that could not answer and a blocked account
      // apart from rejected credentials; the correlation ID lets support find
      // the server log.
      const failureReason = reason ?? "credentials";
      return fail(LOGIN_FAILURE_STATUS[failureReason], {
        failed: true,
        reason: failureReason,
        correlationId,
        attemptsRemaining: attemptsRemaining ?? null,
        retryAfterSeconds: retryAfterSeconds ?? null
      });
    }

    return fail(400, { failed: true, correlationId: null });
  },
  oidc: async (event) => {
    const data = await event.request.formData();
    const requestedDestination = data.get("next");
    const destination =
      requestedDestination === null ? null : resolveSafeLoginDestination(requestedDestination);
    if (event.locals.id_token) {
      redirect(303, resolveSafeLoginDestination(destination));
    }

    const tenant = data.get("tenant");
    if (tenant !== null && (typeof tenant !== "string" || !/^[a-z0-9-]+$/.test(tenant))) {
      return fail(400, { oidcFailed: true });
    }

    const started = await initiateOidcLogin(event, {
      destination,
      tenant: typeof tenant === "string" ? tenant : null
    });
    if (!started.ok) {
      return fail(503, {
        oidcFailed: true,
        unavailable: started.code === "oidc_login_unavailable"
      });
    }

    redirect(303, started.authorizationUrl);
  }
};

export const load = (async (event) => {
  let zitadelLink: string | undefined = undefined;
  const requestedDestination = event.url.searchParams.get("next");

  // If user is logged in already: forward to base url, as login doesn't make sense
  if (event.locals.id_token) {
    redirect(302, resolveSafeLoginDestination(requestedDestination));
  }

  if (event.locals.featureFlags.newAuth) {
    zitadelLink = await getZitadelLink(event);
  }

  const { federationStatus } = event.locals.featureFlags;
  const hasSingleTenantOidc =
    !federationStatus.has_multi_tenant_federation &&
    (federationStatus.has_single_tenant_federation || federationStatus.has_global_oidc_config);
  // The removed MobilityGuard link still being set means people are meant to
  // sign in through their organisation, which this page cannot offer now
  // unless another single sign-on is available.
  const organisationSignInUnavailable =
    Boolean(env.MOBILITY_GUARD_AUTH?.trim()) &&
    !zitadelLink &&
    !hasSingleTenantOidc &&
    !federationStatus.has_multi_tenant_federation;

  return {
    zitadelLink,
    hasSingleTenantOidc,
    organisationSignInUnavailable,
    featureFlags: event.locals.featureFlags
  };
}) satisfies PageServerLoad;
