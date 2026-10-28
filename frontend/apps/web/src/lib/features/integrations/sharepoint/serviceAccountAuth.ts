import { m } from "$lib/paraglide/messages";

export const SHAREPOINT_SERVICE_ACCOUNT_OAUTH_KEY = "sharepoint_service_account_oauth";

export type ServiceAccountSignInStart = { auth_url: string; state: string };

/**
 * Hands the browser to Microsoft. The callback route under
 * /integrations/callback/token completes the sign-in with the stored state.
 */
export function followServiceAccountSignIn(start: ServiceAccountSignInStart): void {
  // The address comes from the backend; only ever leave for an https sign-in page.
  let url: URL;
  try {
    url = new URL(start.auth_url);
  } catch {
    throw new Error(m.sharepoint_sign_in_url_invalid());
  }
  if (url.protocol !== "https:") throw new Error(m.sharepoint_sign_in_url_invalid());
  sessionStorage.setItem(
    SHAREPOINT_SERVICE_ACCOUNT_OAUTH_KEY,
    JSON.stringify({ state: start.state })
  );
  window.location.assign(url.href);
}
