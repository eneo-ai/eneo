/**
 * A post-login `next` target is only honored when it is a same-origin absolute
 * path. Rejects protocol-relative (`//host`, `/\host`) values and absolute
 * URLs so a crafted `?next=` can't turn login into an open redirect
 * (`new URL("//evil.com", origin)` resolves to `https://evil.com`).
 */
export const DEFAULT_LANDING = "/dashboard";

export function safeNextPath(next: string | null | undefined): string {
  if (typeof next !== "string" || next.length === 0 || next[0] !== "/") return DEFAULT_LANDING;
  // Second char "/" or "\" would make it protocol-relative (→ another origin).
  if (next[1] === "/" || next[1] === "\\") return DEFAULT_LANDING;
  return next;
}
