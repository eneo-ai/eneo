import { error } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";

export const GET: RequestHandler = async (event) => {
  try {
    const { id_token, environment } = event.locals;

    if (!id_token || !environment.baseUrl) {
      throw error(401, new Error("Unauthorized"));
    }

    // Build query params from URL
    const searchParams = event.url.searchParams;
    const queryParams: Record<string, string> = {};

    for (const [key, value] of searchParams.entries()) {
      // Skip "all" values for action and outcome
      if ((key === "action" || key === "outcome") && value === "all") {
        continue;
      }
      queryParams[key] = value;
    }

    // Make request to backend using event.fetch (goes through SvelteKit proxy)
    const backendUrl = new URL("/api/v1/audit/logs/export", environment.baseUrl);

    // Add query parameters
    Object.entries(queryParams).forEach(([key, value]) => {
      backendUrl.searchParams.set(key, value);
    });

    const response = await event.fetch(backendUrl.toString(), {
      method: "GET",
      headers: {
        Authorization: `Bearer ${id_token}`,
      },
    });

    if (!response.ok) {
      throw error(response.status, new Error(`Failed to export audit logs: ${response.statusText}`));
    }

    // Get the CSV content
    const csvContent = await response.text();

    // Return CSV response with proper headers
    return new Response(csvContent, {
      status: 200,
      headers: {
        "Content-Type": "text/csv;charset=utf-8",
        "Content-Disposition": `attachment; filename=tenant_audit_logs_${new Date().toISOString()}.csv`,
      },
    });
  } catch (err) {
    console.error("CSV export failed:", err);
    throw error(500, new Error("Failed to export audit logs"));
  }
};
