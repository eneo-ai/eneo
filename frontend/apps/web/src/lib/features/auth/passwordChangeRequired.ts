import type { PasswordStatus } from "@eneo/eneo-js";

export const PASSWORD_CHANGE_PATH = "/password-change";

/** Where a signed-in user goes to replace a one-time or expired password. */
export function passwordChangeUrl(current?: URL): string {
  if (!current) return PASSWORD_CHANGE_PATH;
  const destination = current.pathname + current.search;
  if (destination === "/" || destination.startsWith(PASSWORD_CHANGE_PATH)) {
    return PASSWORD_CHANGE_PATH;
  }
  return `${PASSWORD_CHANGE_PATH}?next=${encodeURIComponent(destination)}`;
}

export type PasswordChangeReason = NonNullable<PasswordStatus["reason"]>;

/** Narrow the backend status to what the forced-change page needs; unknown shapes mean "not required". */
export function readPasswordChangeReason(value: unknown): PasswordChangeReason | null {
  if (typeof value !== "object" || value === null) return null;
  const status = value as Record<string, unknown>;
  if (status.change_required !== true) return null;
  return status.reason === "expired" ? "expired" : "admin_set";
}
