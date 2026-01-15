import { error, redirect } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";

/**
 * Download completed export file.
 * Proxies the file download from the backend.
 */
export const GET: RequestHandler = async (event) => {
  try {
    const { id_token, environment } = event.locals;

    if (!id_token || !environment.baseUrl) {
      throw error(401, new Error("Unauthorized"));
    }

    const jobId = event.params.job_id;

    // Build backend URL
    const backendUrl = new URL(`/api/v1/audit/logs/export/${jobId}/download`, environment.baseUrl);

    // Make request to backend
    const response = await event.fetch(backendUrl.toString(), {
      method: "GET",
      headers: {
        Authorization: `Bearer ${id_token}`,
      },
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error("Export download failed:", response.status, errorText);
      throw error(response.status, new Error(`Failed to download export: ${response.statusText}`));
    }

    // Get content type and filename from backend response
    const contentType = response.headers.get("Content-Type") || "application/octet-stream";
    const contentDisposition = response.headers.get("Content-Disposition");

    // Stream the file content to the client
    const body = await response.arrayBuffer();

    return new Response(body, {
      status: 200,
      headers: {
        "Content-Type": contentType,
        ...(contentDisposition && { "Content-Disposition": contentDisposition }),
      },
    });
  } catch (err) {
    console.error("Export download failed:", err);
    if (err instanceof Response) {
      throw err;
    }
    throw error(500, new Error("Failed to download export"));
  }
};
