import { error, json } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";

/**
 * Request async audit log export.
 * Returns job_id for status polling.
 */
export const POST: RequestHandler = async (event) => {
  try {
    const { id_token, environment } = event.locals;

    if (!id_token || !environment.baseUrl) {
      throw error(401, new Error("Unauthorized"));
    }

    // Parse request body
    const body = await event.request.json();

    // Build backend URL
    const backendUrl = new URL("/api/v1/audit/logs/export/async", environment.baseUrl);

    // Make request to backend
    const response = await event.fetch(backendUrl.toString(), {
      method: "POST",
      headers: {
        Authorization: `Bearer ${id_token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error("Async export request failed:", response.status, errorText);
      throw error(response.status, new Error(`Failed to request export: ${response.statusText}`));
    }

    const result = await response.json();
    return json(result);
  } catch (err) {
    console.error("Async export request failed:", err);
    if (err instanceof Response) {
      throw err;
    }
    throw error(500, new Error("Failed to request export"));
  }
};
