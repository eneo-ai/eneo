import { DEFAULT_LANDING_PAGE } from "$lib/core/constants";
import { decodeState, type LoginStateParam } from "$lib/features/auth/auth.server.js";
import { LoginError } from "$lib/features/auth/LoginError.js";
import {
  clearMobilityguardCookie,
  loginWithMobilityguard
} from "$lib/features/auth/mobilityguard.server";
import { clearZitadelCookie, loginWithZitadel } from "$lib/features/auth/zitadel.server";
import { loginWithOidc } from "$lib/features/auth/oidc.server";
import { redirect } from "@sveltejs/kit";

export const load = async (event) => {
  const code = event.url.searchParams.get("code");
  const state = event.url.searchParams.get("state");
  const error = event.url.searchParams.get("error");
  const errorDescription = event.url.searchParams.get("error_description");

  // Log callback parameters
  console.debug("[OIDC Callback] Received callback", {
    hasCode: !!code,
    hasState: !!state,
    error,
    errorDescription,
    origin: event.url.origin
  });

  // Handle OAuth errors from identity provider (Auth0, MobilityGuard, Zitadel, etc.)
  if (error) {
    console.error("[OIDC Callback] OAuth error received from identity provider", {
      error,
      errorDescription,
      state,
      origin: event.url.origin
    });

    // Map OAuth errors to user-friendly messages (generic OIDC)
    let message = "oidc_oauth_error";
    if (error === "access_denied") {
      message = "oidc_access_denied";
    } else if (error === "invalid_request") {
      message = "oidc_invalid_request";
    } else if (error === "unauthorized_client") {
      message = "oidc_unauthorized_client";
    } else if (error === "server_error") {
      message = "oidc_server_error";
    } else if (error === "temporarily_unavailable") {
      message = "oidc_temporarily_unavailable";
    }

    // Include error description for better debugging
    const errorParams = new URLSearchParams({
      message,
      error,
      ...(errorDescription && { details: errorDescription })
    });

    return redirect(302, `/login?${errorParams.toString()}`);
  }

  if (!code) {
    console.error("[OIDC Callback] No authorization code received");
    return redirect(302, "/login?message=no_code_received");
  }

  if (!state) {
    console.error("[OIDC Callback] No state parameter received");
    return redirect(302, "/login?message=no_state_received");
  }

  let success = false;
  let errorInfo = "";
  let errorDetails = "";
  const decodedState = decodeState<LoginStateParam>(state);
  const redirectUrl = decodedState?.next ?? DEFAULT_LANDING_PAGE;

  console.debug("[OIDC Callback] Processing login", {
    loginMethod: decodedState?.loginMethod ?? "oidc (backend-first)",
    redirectUrl
  });

  let loginError: LoginError | null = null;

  try {
    if (decodedState?.loginMethod === "mobilityguard") {
      const startTime = Date.now();
      success = await loginWithMobilityguard(code);
      const duration = Date.now() - startTime;

      console.debug("[OIDC Callback] Login attempt completed", {
        success,
        durationMs: duration
      });

      if (!success) {
        errorDetails =
          "Authentication failed. Please check your credentials and try again. If the problem persists, contact your administrator.";
      }
    } else if (decodedState?.loginMethod === "zitadel") {
      success = await loginWithZitadel(code);
    } else {
      // Generic OIDC flow (single-tenant or new backend-first flow)
      // loginMethod is undefined when using backend-generated state JWT
      console.debug("[OIDC Callback] Using generic OIDC flow (backend-first)");
      success = await loginWithOidc(code, state, event.fetch);

      if (!success) {
        errorInfo = "oidc_callback_failed";
        errorDetails =
          "Authentication failed. Check the console logs for correlation_id to help troubleshoot. " +
          "Common causes: user not found in database, email domain not allowed, or IdP configuration error. " +
          "Contact your administrator if this persists.";
      }
    }
  } catch (e) {
    const loginMethod = decodedState?.loginMethod || "oidc";

    console.error("[OIDC Callback] Login error", {
      errorType: e instanceof LoginError ? "LoginError" : "UnknownError",
      error: e instanceof Error ? e.message : String(e),
      stack: e instanceof Error ? e.stack : undefined,
      loginMethod,
      correlationId: e instanceof LoginError ? e.correlationId : undefined
    });

    if (e instanceof LoginError) {
      loginError = e;
      errorInfo = e.getErrorShortCode();
      errorDetails = e.message;
    } else if (e instanceof Error) {
      errorInfo = "unexpected_error";
      errorDetails = `${e.message}. Check console logs for more details.`;
    } else {
      errorInfo = "unknown_error";
      errorDetails = String(e);
    }
  } finally {
    // Clean up legacy auth cookies (backward compatibility)
    clearMobilityguardCookie(event.cookies);
    clearZitadelCookie(event.cookies);
  }

  if (success) {
    console.debug("[OIDC Callback] Login successful, redirecting", { redirectUrl });
    redirect(302, `/${redirectUrl.slice(1)}`);
  }

  console.error("[OIDC Callback] Login failed, redirecting to login page", {
    loginMethod: decodedState?.loginMethod || "oidc",
    errorInfo,
    errorDetails,
    correlationId: loginError?.correlationId
  });

  // For OIDC errors with LoginError, redirect to /login with structured params
  if (loginError && loginError.provider === "oidc") {
    const params = new URLSearchParams();

    // Map error code to frontend error code
    if (loginError.code === "FORBIDDEN") {
      params.set("message", "oidc_forbidden");
      params.set("detailCode", "access_denied");
    } else if (loginError.code === "UNAUTHORIZED") {
      params.set("message", "oidc_unauthorized");
      params.set("detailCode", "unauthorized");
    } else {
      params.set("message", "oidc_callback_failed");
    }

    if (loginError.correlationId) {
      params.set("correlation", loginError.correlationId);
    }

    if (loginError.rawDetail) {
      params.set("rawDetail", loginError.rawDetail);
    }

    // Try to get tenant from cookies (session storage)
    const tenantSlug = event.cookies.get("eneo-last-tenant-slug");
    if (tenantSlug) {
      params.set("tenant", tenantSlug);
    }

    redirect(302, `/login?${params.toString()}`);
  }

  // Fallback to old /login/failed for non-OIDC errors
  const loginMethod = decodedState?.loginMethod || "oidc";
  const failedUrl =
    `/login/failed?message=${loginMethod}_login_error&info=${errorInfo}` +
    (errorDetails ? `&details=${encodeURIComponent(errorDetails)}` : "");

  redirect(302, failedUrl);
};
