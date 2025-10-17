import { env } from "$env/dynamic/private";
import { DEFAULT_LANDING_PAGE } from "$lib/core/constants";
import { setFrontendAuthCookie } from "$lib/features/auth/auth.server";
import { redirect } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = async ({ url, fetch }) => {
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");

  console.debug("[Federation Callback] Received callback", {
    hasCode: !!code,
    hasState: !!state,
    origin: url.origin
  });

  // If missing required parameters, return error to client
  if (!code || !state) {
    console.error("[Federation Callback] Missing required parameters");
    return {
      error: !code ? "no_code_received" : "no_state_received"
    };
  }

  try {
    // Call backend to exchange code for token
    const backendUrl = env.INTRIC_BACKEND_URL || "http://localhost:8123";
    const response = await fetch(`${backendUrl}/api/v1/auth/callback`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ code, state })
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const correlationId = response.headers.get("x-correlation-id") ?? null;

      console.error("[Federation Callback] Backend auth failed", {
        status: response.status,
        error: errorData,
        correlationId
      });

      let errorCode = "oidc_callback_failed";
      let detailCode: string | null = null;

      if (response.status === 403) {
        errorCode = "oidc_forbidden";
        detailCode = "access_denied";
      } else if (response.status === 401) {
        errorCode = "oidc_unauthorized";
        detailCode = "unauthorized";
      }

      return {
        error: errorCode,
        detailCode,
        correlationId,
        rawDetail: errorData.detail || null
      };
    }

    const data = await response.json();

    // Set auth cookie with access token
    await setFrontendAuthCookie({
      id_token: data.access_token,
      access_token: data.access_token
    });

    console.debug("[Federation Callback] Authentication successful, redirecting");

    // Redirect to home page
    redirect(302, DEFAULT_LANDING_PAGE);
  } catch (err) {
    console.error("[Federation Callback] Unexpected error", {
      error: err instanceof Error ? err.message : String(err)
    });

    return {
      error: "unexpected_error",
      details: err instanceof Error ? err.message : "An unexpected error occurred"
    };
  }
};
