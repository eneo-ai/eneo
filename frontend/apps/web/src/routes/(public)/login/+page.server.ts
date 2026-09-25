import { env } from "$env/dynamic/private";
import { getBackendUrl } from "$lib/core/environment.server";
import {
  clearOidcLoginDestination,
  encodeState,
  rememberOidcLoginDestination,
  resolveSafeLoginDestination
} from "$lib/features/auth/auth.server";
import { loginWithEneo } from "$lib/features/auth/eneo.server";
import { getMobilityguardLink } from "$lib/features/auth/mobilityguard.server";
import { getZitadelLink } from "$lib/features/auth/zitadel.server";
import { redirect, fail, type Actions } from "@sveltejs/kit";

export const actions: Actions = {
  login: async (event) => {
    const data = await event.request.formData();
    const username = data.get("email")?.toString() ?? null;
    const password = data.get("password")?.toString() ?? null;
    const next = data.get("next")?.toString() ?? null;
    const redirectUrl = resolveSafeLoginDestination(next);

    if (username && password) {
      const { success, correlationId } = await loginWithEneo(username, password);

      if (success) {
        clearOidcLoginDestination(event.cookies);
        redirect(302, redirectUrl);
      }

      // Return correlation ID for error tracking
      return fail(400, { failed: true, correlationId });
    }

    return fail(400, { failed: true, correlationId: null });
  }
};

async function getSingleTenantOidcLink(
  backendUrl: string,
  fetchFn: typeof fetch,
  frontendState: string
): Promise<string | undefined> {
  try {
    // Call initiate auth endpoint WITHOUT tenant parameter for single-tenant mode
    // Backend will automatically use the first active tenant with global OIDC config
    const initiateUrl = new URL(`${backendUrl.replace(/\/$/, "")}/api/v1/auth/initiate`);
    initiateUrl.searchParams.set("state", frontendState);
    const initiateResponse = await fetchFn(initiateUrl);

    if (!initiateResponse.ok) {
      console.warn(
        `[Single-tenant OIDC] Failed to initiate auth: HTTP ${initiateResponse.status}. Falling back to username/password login.`
      );
      return undefined;
    }

    const initiateData = await initiateResponse.json();
    return initiateData.authorization_url;
  } catch (error) {
    console.error("[Single-tenant OIDC] Error generating auth link:", error);
    return undefined;
  }
}

export const load = async (event) => {
  let zitadelLink: string | undefined = undefined;
  let mobilityguardLink: string | undefined = undefined;
  let singleTenantOidcLink: string | undefined = undefined;
  const requestedDestination = event.url.searchParams.get("next");
  const loginDestination =
    requestedDestination === null ? null : resolveSafeLoginDestination(requestedDestination);
  const oidcAttemptId = crypto.randomUUID();
  const oidcFrontendState = encodeState({
    loginMethod: "oidc",
    next: loginDestination,
    attemptId: oidcAttemptId
  });

  // If user is logged in already: forward to base url, as login doesn't make sense
  if (event.locals.id_token) {
    clearOidcLoginDestination(event.cookies);
    redirect(302, resolveSafeLoginDestination(requestedDestination));
  }

  // Generic OIDC returns a backend-signed state value that is intentionally
  // opaque to this server until callback exchange. Keep the already validated
  // local destination independently so provider errors can still resume it.
  rememberOidcLoginDestination(event.cookies, requestedDestination, oidcAttemptId);

  if (event.locals.featureFlags.newAuth) {
    zitadelLink = await getZitadelLink(event);
  }

  if (env.MOBILITY_GUARD_AUTH) {
    mobilityguardLink = await getMobilityguardLink(event);
  }

  // Generate single-tenant OIDC link if federation is available
  // Check if either single-tenant federation (DB) or global OIDC (env) is configured
  const { federationStatus } = event.locals.featureFlags;
  const hasSingleTenantOidc =
    federationStatus.has_single_tenant_federation || federationStatus.has_global_oidc_config;

  if (hasSingleTenantOidc) {
    singleTenantOidcLink = await getSingleTenantOidcLink(
      getBackendUrl() ?? "",
      event.fetch,
      oidcFrontendState
    );
  }

  return {
    mobilityguardLink,
    zitadelLink,
    singleTenantOidcLink,
    oidcFrontendState,
    featureFlags: event.locals.featureFlags
  };
};
