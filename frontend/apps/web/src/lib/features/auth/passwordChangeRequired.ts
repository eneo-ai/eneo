import { EneoError, type PasswordStatus } from "@eneo/eneo-js";
import { browser } from "$app/environment";
import { redirect } from "@sveltejs/kit";

export const PASSWORD_CHANGE_PATH = "/password-change";

/** Backend ErrorCodes.PASSWORD_CHANGE_REQUIRED: the session may only replace its password. */
export const PASSWORD_CHANGE_REQUIRED_CODE = 9070;

function isPasswordChangeRequiredError(error: unknown): boolean {
  return (
    error instanceof EneoError &&
    error.status === 403 &&
    error.code === PASSWORD_CHANGE_REQUIRED_CODE
  );
}

/** Used by the app's persistent API client, including calls after layout load. */
export function handlePasswordChangeRequired(error: EneoError, requestedUrl: URL): void {
  if (!isPasswordChangeRequiredError(error)) return;
  if (browser) {
    // The user may have navigated since this client was created.
    window.location.assign(passwordChangeUrl(new URL(window.location.href)));
  } else {
    redirect(302, passwordChangeUrl(requestedUrl));
  }
}

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

/**
 * Narrow the backend status to what the forced-change page needs. Unknown
 * shapes mean "not required"; an unknown reason on a required change is shown
 * as an administrator-set password, the generic case.
 */
export function readPasswordChangeReason(value: unknown): PasswordChangeReason | null {
  if (typeof value !== "object" || value === null) return null;
  const status = value as Record<string, unknown>;
  if (status.change_required !== true) return null;
  return status.reason === "expired" ? "expired" : "admin_set";
}
