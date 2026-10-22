import { safeNextPath } from "./safe-next";

export const PASSWORD_CHANGE_PATH = "/password-change";

/**
 * Where a session that must replace its local password is sent. `next` is the
 * page the user was on, so they come back to it after the change; the
 * password page validates it with safeNextPath before using it.
 */
export function passwordChangeUrl(next: string | null | undefined): string {
  if (!next || next === "/" || next.startsWith(PASSWORD_CHANGE_PATH)) return PASSWORD_CHANGE_PATH;
  return `${PASSWORD_CHANGE_PATH}?next=${encodeURIComponent(next)}`;
}

/**
 * Where a successful password change sends the browser: the logout route,
 * which tells the login page the password was changed and keeps `next` so the
 * user lands where they were going.
 */
export function passwordChangedLogoutUrl(next: string | null | undefined): string {
  const safe = safeNextPath(next);
  const params = new URLSearchParams({ reason: "password_changed" });
  if (next && safe === next) params.set("next", safe);
  return `/logout?${params.toString()}`;
}
