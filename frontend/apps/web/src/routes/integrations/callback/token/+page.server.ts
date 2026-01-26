import { env } from "$env/dynamic/private";
import { fail } from "@sveltejs/kit";
import type { Actions } from "./$types";

export const actions: Actions = {
  completeServiceAccountAuth: async ({ request, locals }) => {
    const data = await request.formData();
    const authCode = data.get("auth_code") as string;
    const state = data.get("state") as string;
    const clientId = data.get("client_id") as string;
    const clientSecret = data.get("client_secret") as string;
    const tenantDomain = data.get("tenant_domain") as string;

    if (!authCode || !state || !clientId || !clientSecret || !tenantDomain) {
      return fail(400, { error: "Missing required fields" });
    }

    // Use internal Docker URL if available, otherwise fall back to external URL
    const backendUrl = env.INTRIC_BACKEND_SERVER_URL || env.INTRIC_BACKEND_URL;
    if (!backendUrl) {
      return fail(500, { error: "Backend URL not configured" });
    }

    // Get auth token from locals (set by hooks.server.ts)
    const idToken = locals.id_token;
    console.log("[SharePoint Callback] Auth check:", {
      hasIdToken: !!idToken,
      localsKeys: Object.keys(locals),
      cookieHeader: request.headers.get("cookie")?.substring(0, 100) + "..."
    });
    if (!idToken) {
      return fail(401, { error: "Not authenticated. Please log in and try again." });
    }

    try {
      console.log("[SharePoint Callback] Making backend request:", {
        url: `${backendUrl}/api/v1/admin/sharepoint/service-account/auth/callback`,
        hasAuthHeader: !!idToken,
        tokenLength: idToken?.length,
        tokenPreview: idToken?.substring(0, 50) + "..."
      });

      const response = await fetch(
        `${backendUrl}/api/v1/admin/sharepoint/service-account/auth/callback`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${idToken}`,
          },
          body: JSON.stringify({
            auth_code: authCode,
            state,
            client_id: clientId,
            client_secret: clientSecret,
            tenant_domain: tenantDomain,
          }),
        }
      );

      console.log("[SharePoint Callback] Backend response:", {
        status: response.status,
        statusText: response.statusText,
        ok: response.ok
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        console.log("[SharePoint Callback] Error response body:", errorData);
        return fail(response.status, {
          error: errorData.detail || `HTTP ${response.status}`,
        });
      }

      const result = await response.json();
      return {
        success: true,
        service_account_email: result.service_account_email,
      };
    } catch (error) {
      console.error("Service account auth callback error:", error);
      return fail(500, {
        error: error instanceof Error ? error.message : "Failed to complete authentication",
      });
    }
  },
};
