// Mirrors the production form's credentialTransport rule. The backend remains
// authoritative; this explains a refusal before an admin submits credentials.
const AUTH_TYPES_WITHOUT_ADMIN_CREDENTIAL = new Set(["none", "internal", "bundled"]);
const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

export function sendsCredentialOverPlainHttp(authType: string, url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  const carriesUserinfo = parsed.username !== "" || parsed.password !== "";
  if (AUTH_TYPES_WITHOUT_ADMIN_CREDENTIAL.has(authType) && !carriesUserinfo) return false;
  return parsed.protocol === "http:" && !LOOPBACK_HOSTS.has(parsed.hostname);
}
