import { error, json } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";

/**
 * Cancel an in-progress export job.
 * Signals cancellation via Redis flag.
 */
export const POST: RequestHandler = async (event) => {
  try {
    const { id_token, environment } = event.locals;

    if (!id_token || !environment.baseUrl) {
      throw error(401, new Error("Unauthorized"));
    }

    const jobId = event.params.job_id;

    // Build backend URL
    const backendUrl = new URL(`/api/v1/audit/logs/export/${jobId}/cancel`, environment.baseUrl);

    // Make request to backend
    const response = await event.fetch(backendUrl.toString(), {
      method: "POST",
      headers: {
        Authorization: `Bearer ${id_token}`,
      },
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error("Export cancel failed:", response.status, errorText);
      throw error(response.status, new Error(`Failed to cancel export: ${response.statusText}`));
    }

    const result = await response.json();
    return json(result);
  } catch (err) {
    console.error("Export cancel failed:", err);
    if (err instanceof Response) {
      throw err;
    }
    throw error(500, new Error("Failed to cancel export"));
  }
};
