/*
    Generic OIDC authentication for single-tenant mode.
    Uses backend federation router endpoints (/api/v1/auth/initiate and /api/v1/auth/callback).
*/

import { readTraceId } from "@eneo/eneo-js";
import { getBackendUrl } from "$lib/core/environment.server";
import { setFrontendAuthCookie } from "./auth.server";
import { backendErrorCode, LoginError } from "./LoginError";

export type OidcLoginResult = {
  frontendState: string;
};

export async function loginWithOidc(
  code: string,
  state: string,
  // The secret whose hash initiate stored: only this browser can redeem the code.
  bindingVerifier: string,
  fetchFn: typeof fetch = fetch,
  // The provider's RFC 9207 issuer from the redirect; the backend checks it.
  iss: string | null = null
): Promise<OidcLoginResult | null> {
  const resolvedBackendUrl = getBackendUrl();
  if (!resolvedBackendUrl) {
    console.error("[OIDC] Missing ENEO_BACKEND_URL configuration");
    return null;
  }

  const backendUrl = `${resolvedBackendUrl}/api/v1/auth/callback`;

  console.debug("[OIDC] Starting backend callback", {
    hasCode: !!code,
    hasState: !!state,
    backendUrl
  });

  try {
    const response = await fetchFn(backendUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        code,
        state,
        ...(iss !== null && { iss }),
        binding_verifier: bindingVerifier
      })
    });

    if (!response.ok) {
      const responseText = await response.text();
      let errorDetails;
      try {
        errorDetails = JSON.parse(responseText);
      } catch {
        errorDetails = responseText;
      }

      const traceId = readTraceId(response.headers);
      // Typed refusals carry `message`; other errors carry `detail`.
      const rawDetail =
        typeof errorDetails === "object" && errorDetails
          ? (errorDetails.detail ?? errorDetails.message ?? undefined)
          : undefined;
      const refusal = backendErrorCode(errorDetails);

      console.error("[OIDC] Backend callback failed", {
        status: response.status,
        statusText: response.statusText,
        error: errorDetails,
        traceId
      });

      if (refusal === "oidc_login_unavailable") {
        throw new LoginError("oidc", "LOGIN_UNAVAILABLE", "", {
          traceId,
          statusCode: response.status,
          rawDetail
        });
      }
      if (refusal === "oidc_transaction_invalid") {
        throw new LoginError("oidc", "ATTEMPT_EXPIRED", "", {
          traceId,
          statusCode: response.status,
          rawDetail
        });
      }

      // Map status codes to specific error codes and throw LoginError
      if (response.status === 400) {
        console.error(
          `[OIDC] Invalid or expired state - user took too long to authenticate. ` +
            `Backend trace_id: ${traceId || "N/A"}`
        );
        throw new LoginError("oidc", "DECODE_ERROR", "", {
          traceId,
          statusCode: response.status,
          rawDetail
        });
      } else if (response.status === 401) {
        console.error(
          `[OIDC] Token validation failed - IdP rejected authentication. ` +
            `Backend trace_id: ${traceId || "N/A"}`
        );
        throw new LoginError("oidc", "UNAUTHORIZED", "", {
          traceId,
          statusCode: response.status,
          rawDetail
        });
      } else if (response.status === 403) {
        console.error(
          `[OIDC] Access forbidden - domain not allowed or user not found. ` +
            `Backend trace_id: ${traceId || "N/A"}`
        );
        throw new LoginError("oidc", "FORBIDDEN", "", {
          traceId,
          statusCode: response.status,
          rawDetail
        });
      } else if (response.status === 404) {
        console.error(
          `[OIDC] User or tenant not found. ` + `Backend trace_id: ${traceId || "N/A"}`
        );
        throw new LoginError("oidc", "NO_TOKEN", "", {
          traceId,
          statusCode: response.status,
          rawDetail
        });
      } else if (response.status === 500) {
        console.error(
          `[OIDC] Server configuration error - check backend logs for trace_id: ${traceId || "N/A"}`
        );
        throw new LoginError("oidc", "SERVER_ERROR", "", {
          traceId,
          statusCode: response.status,
          rawDetail
        });
      }

      // Fallback for unknown status codes
      throw new LoginError("oidc", "CALLBACK_FAILED", "", {
        traceId,
        statusCode: response.status,
        rawDetail
      });
    }

    console.debug("[OIDC] Backend callback successful");

    const data = (await response.json()) as {
      access_token?: unknown;
      frontend_state?: unknown;
    };
    const accessToken = data.access_token;

    if (typeof accessToken !== "string" || accessToken.length === 0) {
      console.error("[OIDC] No access token in response", { responseKeys: Object.keys(data) });
      return null;
    }

    // The backend token is Eneo's frontend session JWT. It is not the
    // provider access token used by Zitadel's activation and profile flows.
    await setFrontendAuthCookie({ id_token: accessToken });

    console.debug("[OIDC] Login complete, auth cookie set");
    return {
      // Empty fallback keeps authentication compatible during rolling upgrades;
      // safe destination resolution will send the user to the normal landing page.
      frontendState: typeof data.frontend_state === "string" ? data.frontend_state : ""
    };
  } catch (error) {
    // Re-throw LoginError so it propagates to the callback handler with metadata
    if (error instanceof LoginError) {
      throw error;
    }

    console.error("[OIDC] Unexpected error during callback", {
      error: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack : undefined
    });
    return null;
  }
}
