import { DEFAULT_LANDING_PAGE } from "$lib/core/constants";
import { decodeState, type LoginStateParam } from "$lib/features/auth/auth.server.js";
import { LoginError } from "$lib/features/auth/LoginError.js";
import {
  clearMobilityguardCookie,
  loginWithMobilityguard
} from "$lib/features/auth/mobilityguard.server";
import { clearZitadelCookie, loginWithZitadel } from "$lib/features/auth/zitadel.server";
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

  // Handle OAuth errors from MobilityGuard
  if (error) {
    console.error("[OIDC Callback] OAuth error received", {
      error,
      errorDescription,
      state
    });

    // Map OAuth errors to user-friendly messages
    let message = "mobilityguard_oauth_error";
    if (error === "access_denied") {
      message = "mobilityguard_access_denied";
    } else if (error === "invalid_request") {
      message = "mobilityguard_invalid_request";
    } else if (error === "unauthorized_client") {
      message = "mobilityguard_unauthorized_client";
    }

    return redirect(302, `/login?message=${message}&error=${error}`);
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
    loginMethod: decodedState?.loginMethod,
    redirectUrl
  });

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
    }

    if (decodedState?.loginMethod === "zitadel") {
      success = await loginWithZitadel(code);
    }
  } catch (e) {
    console.error("[OIDC Callback] Login error", {
      errorType: e instanceof LoginError ? "LoginError" : "UnknownError",
      error: e instanceof Error ? e.message : String(e),
      stack: e instanceof Error ? e.stack : undefined,
      loginMethod: decodedState?.loginMethod
    });

    if (e instanceof LoginError) {
      errorInfo = e.getErrorShortCode();
      errorDetails = e.message;
    } else if (e instanceof Error) {
      errorInfo = "unexpected_error";
      errorDetails = e.message;
    } else {
      errorInfo = "unknown_error";
      errorDetails = String(e);
    }
  } finally {
    clearMobilityguardCookie(event.cookies);
    clearZitadelCookie(event.cookies);
  }

  if (success) {
    console.debug("[OIDC Callback] Login successful, redirecting", { redirectUrl });
    redirect(302, `/${redirectUrl.slice(1)}`);
  }

  console.error("[OIDC Callback] Login failed, redirecting to error page", {
    loginMethod: decodedState?.loginMethod,
    errorInfo,
    errorDetails
  });

  const failedUrl =
    `/login/failed?message=${decodedState?.loginMethod}_login_error&info=${errorInfo}` +
    (errorDetails ? `&details=${encodeURIComponent(errorDetails)}` : "");

  redirect(302, failedUrl);
};
