import { env } from "$env/dynamic/private";
import { fail } from "@sveltejs/kit";
import type { Actions } from "./$types";

export const actions: Actions = {
  completeServiceAccountAuth: async ({ request, locals }) => {
    const data = await request.formData();
    const authCode = data.get("auth_code") as string;
    const state = data.get("state") as string;

    if (!authCode || !state) {
      return fail(400, { error_key: "integration_callback_missing_required_fields" });
    }

    // Use internal Docker URL if available, otherwise fall back to external URL
    const backendUrl = env.INTRIC_BACKEND_SERVER_URL || env.INTRIC_BACKEND_URL;
    if (!backendUrl) {
      return fail(500, { error_key: "integration_callback_backend_url_not_configured" });
    }

    // Get auth token from locals (set by hooks.server.ts)
    const idToken = locals.id_token;
    if (!idToken) {
      return fail(401, { error_key: "integration_callback_not_authenticated" });
    }

    try {
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
          }),
        }
      );

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
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
        error_key: "integration_callback_failed_to_complete_authentication",
        error_detail: error instanceof Error ? error.message : undefined,
      });
    }
  },
};
