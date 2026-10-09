import { env } from "$env/dynamic/private";
import { getBackendUrl } from "$lib/core/environment.server";
import {
  clearOidcLoginAttempt,
  encodeState,
  parseJwt,
  startOidcLoginAttempt,
  resolveSafeLoginDestination
} from "$lib/features/auth/auth.server";
import { loginWithEneo } from "$lib/features/auth/eneo.server";
import { getMobilityguardLink } from "$lib/features/auth/mobilityguard.server";
import { getZitadelLink } from "$lib/features/auth/zitadel.server";
import { redirect, fail, type Actions } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";

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

      // The page tells a backend that could not answer apart from rejected
      // credentials; the correlation ID lets support find the server log.
      const failureReason = reason ?? "credentials";
      return fail(failureReason === "unavailable" ? 503 : 400, {
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

    const attemptId = crypto.randomUUID();
    const frontendState = encodeState({ loginMethod: "oidc", next: destination, attemptId });
    let authorizationUrl: string;
    try {
      const backendUrl = getBackendUrl();
      if (!backendUrl) throw new Error("Missing backend URL");
      const initiateUrl = new URL(`${backendUrl.replace(/\/$/, "")}/api/v1/auth/initiate`);
      initiateUrl.searchParams.set("state", frontendState);
      if (tenant !== null) initiateUrl.searchParams.set("tenant", tenant);
      const response = await event.fetch(initiateUrl);
      if (!response.ok) throw new Error(`OIDC initiate returned HTTP ${response.status}`);

      const responseData: unknown = await response.json();
      if (
        typeof responseData !== "object" ||
        responseData === null ||
        !("authorization_url" in responseData) ||
        typeof responseData.authorization_url !== "string" ||
        !("state" in responseData) ||
        typeof responseData.state !== "string"
      ) {
        throw new Error("Invalid OIDC initiate response");
      }
      const providerUrl = new URL(responseData.authorization_url);
      if (providerUrl.protocol !== "https:" && providerUrl.protocol !== "http:") {
        throw new Error("Invalid OIDC authorization URL");
      }
      const statePayload: unknown = await parseJwt(responseData.state);
      if (
        typeof statePayload !== "object" ||
        statePayload === null ||
        !("frontend_state" in statePayload) ||
        statePayload.frontend_state !== frontendState ||
        !("exp" in statePayload) ||
        typeof statePayload.exp !== "number" ||
        !Number.isSafeInteger(statePayload.exp) ||
        statePayload.exp <= Math.floor(Date.now() / 1000)
      ) {
        throw new Error("Invalid OIDC initiate state");
      }
      authorizationUrl = responseData.authorization_url;
      // Start the binding when authentication begins. Failed initiation and
      // GET requests for an error page preserve another tab's attempt.
      startOidcLoginAttempt(event.cookies, destination, attemptId, statePayload.exp);
    } catch (error) {
      console.error("[OIDC] Failed to initiate authentication", {
        reason: error instanceof Error ? error.message : "Unknown error"
      });
      return fail(503, { oidcFailed: true });
    }

    redirect(303, authorizationUrl);
  }
};

export const load = (async (event) => {
  let zitadelLink: string | undefined = undefined;
  let mobilityguardLink: string | undefined = undefined;
  const requestedDestination = event.url.searchParams.get("next");

  // If user is logged in already: forward to base url, as login doesn't make sense
  if (event.locals.id_token) {
    redirect(302, resolveSafeLoginDestination(requestedDestination));
  }

  if (event.locals.featureFlags.newAuth) {
    zitadelLink = await getZitadelLink(event);
  }

  if (env.MOBILITY_GUARD_AUTH) {
    mobilityguardLink = await getMobilityguardLink(event);
  }

  const { federationStatus } = event.locals.featureFlags;
  const hasSingleTenantOidc =
    !federationStatus.has_multi_tenant_federation &&
    (federationStatus.has_single_tenant_federation || federationStatus.has_global_oidc_config);

  return {
    mobilityguardLink,
    zitadelLink,
    hasSingleTenantOidc,
    featureFlags: event.locals.featureFlags
  };
}) satisfies PageServerLoad;
