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
    if (new URL(next, origin).origin !== origin) return DEFAULT_LANDING;
  } catch {
    return DEFAULT_LANDING;
  }
  return next;
}
