import { error } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";

/**
 * Proxy MCP resource HTML from the backend for iframe embedding.
 *
 * Returns raw HTML with a permissive CSP so inline scripts in the
 * MCP App content can execute (the parent page's strict CSP would
 * block them if we used srcdoc or blob URLs).
 */
export const GET: RequestHandler = async (event) => {
  const { id_token, environment } = event.locals;

  if (!id_token || !environment.baseUrl) {
    throw error(401, new Error("Unauthorized"));
  }

  const serverId = event.params.serverId;
  const uri = event.url.searchParams.get("uri");

  if (!uri) {
    throw error(400, new Error("Missing uri parameter"));
  }

  const backendUrl = new URL(
    `/api/v1/mcp-servers/${serverId}/resources/read`,
    environment.baseUrl
  );
  backendUrl.searchParams.set("uri", uri);

  const response = await event.fetch(backendUrl.toString(), {
    method: "GET",
    headers: {
      Authorization: `Bearer ${id_token}`
    }
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw error(response.status, new Error(errorText));
  }

  const data = await response.json();

  return new Response(data.content, {
    status: 200,
    headers: {
      "Content-Type": data.mime_type || "text/html",
      "Content-Security-Policy":
        "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob: https:; img-src * data: blob:; connect-src *; font-src * data:; style-src 'self' 'unsafe-inline' https:;"
    }
  });
};
