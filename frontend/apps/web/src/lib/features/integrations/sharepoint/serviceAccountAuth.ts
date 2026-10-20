export const SHAREPOINT_SERVICE_ACCOUNT_OAUTH_KEY = "sharepoint_service_account_oauth";

export type ServiceAccountSignInStart = { auth_url: string; state: string };

/**
 * Hands the browser to Microsoft. The callback route under
 * /integrations/callback/token completes the sign-in with the stored state.
 */
export function followServiceAccountSignIn(start: ServiceAccountSignInStart): void {
  sessionStorage.setItem(
    SHAREPOINT_SERVICE_ACCOUNT_OAUTH_KEY,
    JSON.stringify({ state: start.state })
  );
  window.location.assign(start.auth_url);
}
