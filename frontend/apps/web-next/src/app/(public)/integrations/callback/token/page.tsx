import { CallbackHandoff } from "./callback-handoff.client";

/**
 * OAuth callback landing for integration connects. Popup flow only: the
 * opener (useIntegrationAuth) registers the auth code. The Svelte app's
 * service-account branch belongs to the Phase 7 admin area.
 */
export default function IntegrationCallbackPage() {
  return <CallbackHandoff />;
}
