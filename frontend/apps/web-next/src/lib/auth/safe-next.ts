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
    // API, the SSO handlers or static assets. The continuation is a same-origin navigation, so it would carry
    // Sec-Fetch-Site: same-origin past the browser-session gate.
    //
    // The rule reads the path the browser sends (already parsed, so its own dot
    // segments are resolved) as a server decodes it (`/%61pi` is `/api`). In that
    // path, an empty segment (`/.//api`; proxies may merge `//`) or a `.` or
    // `..` segment can only come from an encoded slash (`/x/%2E%2E%2Fapi`), and
    // no page has either, so both are refused: whatever a server then merges or
    // resolves, it routes the same path this check reads.
    const path = decodeURIComponent(url.pathname);
    if (
      path.includes("//") ||
      path.split("/").some((segment) => segment === "." || segment === "..")
    )
      return DEFAULT_LANDING;
    for (const prefix of ["/login", "/logout", "/api", "/auth", "/_next"]) {
      if (path === prefix || path.startsWith(`${prefix}/`)) return DEFAULT_LANDING;
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
