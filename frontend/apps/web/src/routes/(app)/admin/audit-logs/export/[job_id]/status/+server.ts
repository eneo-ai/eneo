import { error, json } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";

/**
 * Get export job status with progress.
 * Returns status, progress percentage, and download_url when complete.
 */
export const GET: RequestHandler = async (event) => {
  try {
    const { id_token, environment } = event.locals;

    if (!id_token || !environment.baseUrl) {
      throw error(401, new Error("Unauthorized"));
    }

    const jobId = event.params.job_id;

    // Build backend URL
    const backendUrl = new URL(`/api/v1/audit/logs/export/${jobId}/status`, environment.baseUrl);

    // Make request to backend
    const response = await event.fetch(backendUrl.toString(), {
      method: "GET",
      headers: {
        Authorization: `Bearer ${id_token}`,
      },
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error("Export status check failed:", response.status, errorText);
      throw error(response.status, new Error(`Failed to get export status: ${response.statusText}`));
    }

    const result = await response.json();
    return json(result);
  } catch (err) {
    console.error("Export status check failed:", err);
    if (err instanceof Response) {
      throw err;
    }
    throw error(500, new Error("Failed to get export status"));
  }
};
