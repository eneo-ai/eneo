/**
 * The MCP server credential rule, mirrored so the admin form can explain it
 * before submit. The backend (mcp_servers/domain/credential_transport.py)
 * stays the authority: a server that sends an admin-supplied credential (from
 * its auth type, or a user name and password in the URL) needs an https URL,
 * and plain http is accepted only for a loopback host, which the backend
 * reaches directly, never through a proxy.
 */

// Auth types that send no admin-supplied credential; every other type does.
const AUTH_TYPES_WITHOUT_ADMIN_CREDENTIAL = new Set(["none", "internal", "bundled"]);
// WHATWG URL keeps the brackets around an IPv6 hostname.
const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** Whether saving this pair would send the credential over plain http. */
export function sendsCredentialOverPlainHttp(authType: string, url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    // A URL still being typed has nothing to explain yet.
    return false;
  }
  // The backend sends a user name or password in the URL as Basic auth.
  const carriesUserinfo = parsed.username !== "" || parsed.password !== "";
  if (AUTH_TYPES_WITHOUT_ADMIN_CREDENTIAL.has(authType) && !carriesUserinfo) return false;
  return parsed.protocol === "http:" && !LOOPBACK_HOSTS.has(parsed.hostname);
}
