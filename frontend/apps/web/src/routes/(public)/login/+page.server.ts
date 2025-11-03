import { env } from "$env/dynamic/private";
import { DEFAULT_LANDING_PAGE } from "$lib/core/constants";
import { loginWithIntric } from "$lib/features/auth/intric.server";
import { getMobilityguardLink } from "$lib/features/auth/mobilityguard.server";
import { getZitadelLink } from "$lib/features/auth/zitadel.server";
import { redirect, fail, type Actions } from "@sveltejs/kit";

export const actions: Actions = {
  login: async ({ request }) => {
    const data = await request.formData();
    const username = data.get("email")?.toString() ?? null;
    const password = data.get("password")?.toString() ?? null;
    const next = data.get("next")?.toString() ?? null;
    const redirectUrl = next ? decodeURIComponent(next) : DEFAULT_LANDING_PAGE;

    if (username && password) {
      const { success, correlationId } = await loginWithIntric(username, password);

      if (success) {
        redirect(302, `/${redirectUrl.slice(1)}`);
      }

      // Return correlation ID for error tracking
      return fail(400, { failed: true, correlationId });
    }

    return fail(400, { failed: true, correlationId: null });
  }
};

async function getSingleTenantOidcLink(backendUrl: string): Promise<string | undefined> {
  try {
    // Call initiate auth endpoint WITHOUT tenant parameter for single-tenant mode
    // Backend will automatically use the first active tenant with global OIDC config
    const initiateUrl = `${backendUrl}/api/v1/auth/initiate`;
    const initiateResponse = await fetch(initiateUrl);

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

  // If user is logged in already: forward to base url, as login doesn't make sense
  if (event.locals.id_token) {
    redirect(302, DEFAULT_LANDING_PAGE);
  }

  if (event.locals.featureFlags.newAuth) {
    zitadelLink = await getZitadelLink(event);
  }

  if (env.MOBILITY_GUARD_AUTH) {
    mobilityguardLink = await getMobilityguardLink(event);
  }

  // Generate single-tenant OIDC link if configured
  if (event.locals.featureFlags.singleTenantOidcConfigured) {
    singleTenantOidcLink = await getSingleTenantOidcLink(env.INTRIC_BACKEND_URL);
  }

  return {
    mobilityguardLink,
    zitadelLink,
    singleTenantOidcLink,
    featureFlags: event.locals.featureFlags
  };
};
