/**
 * Loads the per-user MCP connection status from the backend.
 *
 * The backend endpoint is /api/v1/me/mcp-connections — newly added in
 * Phase 4 of the same-IdP MCP OAuth work. We do not gate behind the
 * SDK (intric-js) yet because it has not been regenerated against the
 * new endpoint; the fetch is direct against the configured backend.
 */

import { redirect } from "@sveltejs/kit";
import { getBackendUrl } from "$lib/core/environment.server";

type ConnectionStatus =
  | "connected"
  | "expired"
  | "not_authenticated"
  | "idp_mismatch"
  | "not_applicable";

export type MCPConnection = {
  mcp_server_id: string;
  name: string;
  auth_scope: string;
  expected_idp_issuer: string | null;
  status: ConnectionStatus;
  expires_at: string | null;
};

export const load = async (event) => {
  const token = event.locals.access_token ?? event.locals.id_token;
  if (!token) {
    redirect(302, "/login?message=session_required");
  }

  const backendOrigin = getBackendUrl();
  if (!backendOrigin) {
    return { connections: [] as MCPConnection[], errorMessage: "Backend not configured" };
  }

  let connections: MCPConnection[] = [];
  let errorMessage: string | null = null;
  try {
    const response = await event.fetch(
      `${backendOrigin.replace(/\/$/, "")}/api/v1/me/mcp-connections`,
      {
        headers: { Authorization: `Bearer ${token}` }
      }
    );
    if (!response.ok) {
      errorMessage = `Backend returned HTTP ${response.status}`;
    } else {
      const body = (await response.json()) as { items: MCPConnection[] };
      connections = body.items ?? [];
    }
  } catch (e) {
    errorMessage = e instanceof Error ? e.message : "Unknown error";
  }

  return { connections, errorMessage };
};
