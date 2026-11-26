import type { RequestEvent } from "@sveltejs/kit";
import { getBackendUrl } from "$lib/core/environment.server";
import { createCodePair, encodeState, parseJwt, startOidcLoginAttempt } from "./auth.server";
import { backendErrorCode } from "./LoginError";

/** A sign-in the backend started, or the code it refused with (when it gave one). */
export type OidcInitiation =
  { ok: true; authorizationUrl: string } | { ok: false; code: string | undefined };

/**
 * Starts a sign-in at the organisation's identity provider and binds it to
 * this browser. On success the caller redirects to `authorizationUrl`.
 *
 * `mfa` signs a person who is already signed in in again, for multi-factor
 * authentication: the backend adds the organisation's request for MFA, and the
 * callback gives a new session only when the provider's answer meets the
 * organisation's rule. The session the person holds tells the backend which
 * organisation to ask, so no tenant is named.
 */
export async function initiateOidcLogin(
  event: Pick<RequestEvent, "fetch" | "cookies">,
  {
    destination,
    tenant,
    mfa
  }: { destination: string | null; tenant: string | null; mfa?: { heldToken: string } }
): Promise<OidcInitiation> {
  const attemptId = crypto.randomUUID();
  const frontendState = encodeState({ loginMethod: "oidc", next: destination, attemptId });
  // The backend keeps the hash; the secret stays in this browser's HttpOnly cookie.
  const binding = await createCodePair();
  let code: string | undefined;
  try {
    const backendUrl = getBackendUrl();
    if (!backendUrl) throw new Error("Missing backend URL");
    const initiateUrl = new URL(`${backendUrl.replace(/\/$/, "")}/api/v1/auth/initiate`);
    initiateUrl.searchParams.set("state", frontendState);
    initiateUrl.searchParams.set("binding_challenge", binding.codeChallenge);
    if (tenant !== null) initiateUrl.searchParams.set("tenant", tenant);
    if (mfa) initiateUrl.searchParams.set("mfa", "true");
    const response = mfa
      ? await event.fetch(initiateUrl, { headers: { Authorization: `Bearer ${mfa.heldToken}` } })
      : await event.fetch(initiateUrl);
    if (!response.ok) {
      const body: unknown = await response.json().catch(() => null);
      code = backendErrorCode(body);
      throw new Error(`OIDC initiate returned HTTP ${response.status}`);
    }

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
    // Start the binding when authentication begins. Failed initiation and
    // GET requests for an error page preserve another tab's attempt.
    startOidcLoginAttempt(
      event.cookies,
      destination,
      attemptId,
      statePayload.exp,
      binding.codeVerifier
    );
    return { ok: true, authorizationUrl: responseData.authorization_url };
  } catch (error) {
    console.error("[OIDC] Failed to initiate authentication", {
      reason: error instanceof Error ? error.message : "Unknown error"
    });
    return { ok: false, code };
  }
}
