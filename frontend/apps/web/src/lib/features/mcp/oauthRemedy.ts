/**
 * The structured remedy a tool result carries when an OAuth MCP server has
 * no usable authorization for the acting user. The backend puts it under the
 * result's meta; the chat renders it as a connect action on the tool step.
 */

export const AUTHORIZATION_REMEDY_KEY = "eneo/authorization_required";

export type AuthorizationRemedy = {
  code: "mcp_authorization_required";
  mcp_server_id: string;
  server_name: string;
  /** "per_user": the user connects; "shared": an administrator must. */
  auth_scope: "per_user" | "shared";
  scopes?: string[];
  connect_url?: string;
  reason?: string;
};

export function authorizationRemedy(
  toolCall: { meta?: Record<string, unknown> | null } | null | undefined
): AuthorizationRemedy | null {
  const raw = toolCall?.meta?.[AUTHORIZATION_REMEDY_KEY];
  if (!raw || typeof raw !== "object") return null;
  const remedy = raw as Partial<AuthorizationRemedy>;
  if (remedy.code !== "mcp_authorization_required" || !remedy.mcp_server_id) return null;
  return {
    code: remedy.code,
    mcp_server_id: remedy.mcp_server_id,
    server_name: remedy.server_name ?? "",
    auth_scope: remedy.auth_scope === "shared" ? "shared" : "per_user",
    scopes: remedy.scopes,
    connect_url: remedy.connect_url,
    reason: remedy.reason
  };
}
