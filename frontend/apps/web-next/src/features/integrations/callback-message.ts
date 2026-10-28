/**
 * The integration OAuth callback page: its address, which every sign-in names
 * as its redirect_uri, and the window.postMessage contract between it (in the
 * popup) and the opener running useIntegrationAuth.
 */

/**
 * The callback page's path. The backend accepts only a redirect_uri registered
 * byte for byte (OAUTH_CALLBACK_URL(S), or PUBLIC_ORIGIN plus this path), as
 * the identity provider's app registration does: keep the trailing slash.
 */
export const INTEGRATION_CALLBACK_PATH = "/integrations/callback/token/";

/** The redirect_uri of an integration sign-in started from this origin. */
export function integrationCallbackUrl(): string {
  return window.location.origin + INTEGRATION_CALLBACK_PATH;
}

export const INTEGRATION_CALLBACK_MESSAGE_TYPE = "eneo/integration-callback";

export type IntegrationCallbackMessage = {
  type: typeof INTEGRATION_CALLBACK_MESSAGE_TYPE;
  code: string | null;
  state: string | null;
  params: string;
};

export function isIntegrationCallbackMessage(data: unknown): data is IntegrationCallbackMessage {
  return (
    typeof data === "object" &&
    data !== null &&
    "type" in data &&
    data.type === INTEGRATION_CALLBACK_MESSAGE_TYPE
  );
}
