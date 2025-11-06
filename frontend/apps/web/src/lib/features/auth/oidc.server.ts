/*
    Generic OIDC authentication for single-tenant mode.
    Uses backend federation router endpoints (/api/v1/auth/initiate and /api/v1/auth/callback).
*/

import { env } from "$env/dynamic/private";
import { getCorrelationId, isDebugMode, sanitizeHeaders, setFrontendAuthCookie } from "./auth.server";
import { LoginError } from "./LoginError";

export async function loginWithOidc(code: string, state: string): Promise<boolean> {
  const startTime = performance.now();
  if (!env.INTRIC_BACKEND_URL) {
    console.error("[OIDC] Missing INTRIC_BACKEND_URL configuration");
    return false;
  }

  const backendUrl = `${env.INTRIC_BACKEND_URL}/api/v1/auth/callback`;

  console.debug("[OIDC] Starting backend callback", {
    hasCode: !!code,
    hasState: !!state,
    backendUrl,
    timestamp: new Date().toISOString()
  });

  try {
    const response = await fetch(backendUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        code,
        state
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

      const correlationId = getCorrelationId(response) || undefined;
      const errorKind = response.headers.get("x-error-kind") || undefined;
      const rawDetail = typeof errorDetails === 'object' && errorDetails?.detail
        ? errorDetails.detail
        : undefined;

      // Debug mode: Log response metadata
      if (isDebugMode()) {
        console.debug("[OIDC] Response metadata (debug)", {
          correlationId,
          errorKind,
          status: response.status,
          contentType: response.headers.get("content-type"),
          responseSize: response.headers.get("content-length"),
          headers: sanitizeHeaders(response.headers)
        });
      }

      console.error("[OIDC] Backend callback failed", {
        status: response.status,
        statusText: response.statusText,
        error: errorDetails,
        correlationId,
        errorKind
      });

      // Map status codes to specific error codes and throw LoginError
      if (response.status === 400) {
        console.error(
          `[OIDC] Invalid or expired state - user took too long to authenticate. ` +
          `Backend correlation_id: ${correlationId || "N/A"}`
        );
        throw new LoginError("oidc", "DECODE_ERROR", "", {
          correlationId,
          statusCode: response.status,
          rawDetail
        });
      } else if (response.status === 401) {
        console.error(
          `[OIDC] Token validation failed - IdP rejected authentication. ` +
          `Backend correlation_id: ${correlationId || "N/A"}`
        );
        throw new LoginError("oidc", "UNAUTHORIZED", "", {
          correlationId,
          statusCode: response.status,
          rawDetail
        });
      } else if (response.status === 403) {
        console.error(
          `[OIDC] Access forbidden - domain not allowed or user not found. ` +
          `Backend correlation_id: ${correlationId || "N/A"}`
        );
        throw new LoginError("oidc", "FORBIDDEN", "", {
          correlationId,
          statusCode: response.status,
          rawDetail
        });
      } else if (response.status === 404) {
        console.error(
          `[OIDC] User or tenant not found. ` +
          `Backend correlation_id: ${correlationId || "N/A"}`
        );
        throw new LoginError("oidc", "NO_TOKEN", "", {
          correlationId,
          statusCode: response.status,
          rawDetail
        });
      } else if (response.status === 500) {
        console.error(
          `[OIDC] Server configuration error - check backend logs for correlation_id: ${correlationId || "N/A"}`
        );
        throw new LoginError("oidc", "SERVER_ERROR", "", {
          correlationId,
          statusCode: response.status,
          rawDetail
        });
      }

      // Fallback for unknown status codes
      throw new LoginError("oidc", "CALLBACK_FAILED", "", {
        correlationId,
        statusCode: response.status,
        rawDetail
      });
    }

    const duration = Math.round(performance.now() - startTime);
    console.debug("[OIDC] Backend callback successful", { durationMs: duration });

    const data = await response.json();
    const { access_token } = data;

    if (!access_token) {
      console.error("[OIDC] No access token in response", { responseKeys: Object.keys(data) });
      return false;
    }

    // Set frontend auth cookie (backend returns "access_token", frontend calls it "id_token")
    await setFrontendAuthCookie({ id_token: access_token });

    console.debug("[OIDC] Login complete, auth cookie set", { totalDurationMs: Math.round(performance.now() - startTime) });
    return true;
  } catch (error) {
    const duration = Math.round(performance.now() - startTime);

    // Re-throw LoginError so it propagates to the callback handler with metadata
    if (error instanceof LoginError) {
      console.error("[OIDC] Login failed (LoginError)", { durationMs: duration, code: error.code });
      throw error;
    }

    console.error("[OIDC] Unexpected error during callback", {
      durationMs: duration,
      error: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack : undefined
    });
    return false;
  }
}
