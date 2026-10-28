import { toastApiError } from "@/lib/api/toast";
import type { Schema } from "@/lib/api/models";
import { toast } from "@/lib/toast";
import { SHAREPOINT_OAUTH_STATE_KEY } from "./integrations";

type Translate = (key: string) => string;

/** The backend's sign-in address is not one to leave for. */
export class SignInAddressError extends Error {}

/**
 * Hands the browser to Microsoft; the callback page (integrations/callback/token)
 * completes the sign-in with the stored state. The address comes from the
 * backend; only an https sign-in page is ever followed.
 */
export function followServiceAccountSignIn(
  start: Pick<Schema<"ServiceAccountAuthStartResponse">, "auth_url" | "state">,
  t: Translate
): void {
  let url: URL;
  try {
    url = new URL(start.auth_url);
  } catch {
    throw new SignInAddressError(t("sharepoint_sign_in_url_invalid"));
  }
  if (url.protocol !== "https:") throw new SignInAddressError(t("sharepoint_sign_in_url_invalid"));
  sessionStorage.setItem(SHAREPOINT_OAUTH_STATE_KEY, JSON.stringify({ state: start.state }));
  window.location.assign(url.href);
}

/** A failed sign-in start: the refused address in its own words, anything else as usual. */
export function toastSignInError(error: unknown, t: Translate): void {
  if (error instanceof SignInAddressError) toast.error(error.message);
  else toastApiError(error, t);
}
