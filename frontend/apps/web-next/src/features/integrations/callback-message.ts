/**
 * The window.postMessage contract between the OAuth callback popup
 * (/integrations/callback/token) and the opener running useIntegrationAuth.
 */

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
