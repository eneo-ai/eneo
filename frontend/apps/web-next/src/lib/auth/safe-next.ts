/**
 * A post-login `next` target is only honored when it is a same-origin absolute
 * path. Rejects protocol-relative (`//host`, `/\host`) values and absolute
 * URLs so a crafted `?next=` can't turn login into an open redirect
 * (`new URL("//evil.com", origin)` resolves to `https://evil.com`).
 */
export const DEFAULT_LANDING = "/spaces/personal/chat";

export function safeNextPath(next: string | null | undefined): string {
  if (typeof next !== "string" || next.length === 0 || next[0] !== "/") return DEFAULT_LANDING;
  try {
    const decoded = decodeURIComponent(next);
    for (const value of [next, decoded]) {
      if (
        value.startsWith("//") ||
        value.includes("\\") ||
        Array.from(value).some((character) => {
          const code = character.charCodeAt(0);
          return code <= 31 || code === 127;
        })
      )
        return DEFAULT_LANDING;
    }
    const origin = "https://login-destination.invalid";
    const url = new URL(next, origin);
    if (url.origin !== origin) return DEFAULT_LANDING;
    // Sign-ins continue through /login: never back to it (a nested next), and
    // never to /login/switch-organisation or /logout, which end the session
    // (an auth redirect loop). Never to a route that is not a page either: the
    // API (the BFF, and FastAPI itself under Vite), the SSO handlers or Next's
    // assets. The continuation is a same-origin navigation, so it would carry
    // Sec-Fetch-Site: same-origin past the browser-session gate. Both paths a
    // server may route on are checked: the parsed path decoded (`/%61pi` is
    // `/api`; `/%3F/../%61pi` parses to `/%61pi`), which keeps every literal
    // prefix, and the decoded value parsed, for servers that decode before
    // resolving dot segments (`/x/%2E%2E%2Fapi`). No page has an empty segment,
    // and servers and proxies merge `//` (Next answers with a 308), so `/.//api`
    // is refused too.
    const pathnames = [decodeURIComponent(url.pathname), new URL(decoded, origin).pathname];
    for (const pathname of pathnames) {
      if (pathname.includes("//")) return DEFAULT_LANDING;
      for (const prefix of ["/login", "/logout", "/api", "/auth", "/_next"]) {
        if (pathname === prefix || pathname.startsWith(`${prefix}/`)) return DEFAULT_LANDING;
      }
    }
  } catch {
    return DEFAULT_LANDING;
  }
  return next;
}

/**
 * Where a sign-in finished by a route handler (the SSO callbacks) continues:
 * the login page, which loads `next` in a new document (ContinueSignedIn).
 */
export function signedInContinuation(next: string | null | undefined): string {
  return `/login?next=${encodeURIComponent(safeNextPath(next))}`;
}
