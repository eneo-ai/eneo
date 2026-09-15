import { m } from "$lib/paraglide/messages";
import type { AuthAlertTone } from "./AuthAlert.svelte";

export type LoginStatus = {
  tone: AuthAlertTone;
  title?: string;
  description: string;
  reasons?: string[];
  footer?: string;
};

/**
 * Maps the `?message=` query value the login page receives (from logout, session
 * expiry and legacy IdP callbacks) to what the user should see. OIDC error codes
 * are handled separately by the login page because they carry extra context.
 */
export function resolveLoginStatus(message: string | null): LoginStatus | null {
  switch (message) {
    case null:
      return null;
    case "logout":
      return { tone: "success", description: m.logout_success() };
    case "password_changed":
      return { tone: "success", description: m.password_changed_login_again() };
    case "password_changed_sessions_remain":
      return { tone: "warning", description: m.password_changed_sessions_remain() };
    case "expired":
      return { tone: "warning", description: m.session_expired_please_login_again() };
    case "mobilityguard_login_error":
      return {
        tone: "error",
        title: m.authentication_failed(),
        description: m.authentication_failed_details(),
        reasons: [
          m.invalid_credentials(),
          m.account_restrictions(),
          m.system_configuration_issues()
        ],
        footer: m.try_again_contact_admin()
      };
    case "mobilityguard_oauth_error":
      return {
        tone: "error",
        title: m.authentication_provider_error(),
        description: m.authentication_service_error()
      };
    case "mobilityguard_access_denied":
      return { tone: "error", title: m.access_denied(), description: m.access_denied_eneo() };
    case "mobilityguard_invalid_request":
      return {
        tone: "warning",
        title: m.invalid_request(),
        description: m.invalid_login_request()
      };
    case "no_code_received":
    case "no_state_received":
      return {
        tone: "warning",
        title: m.login_process_interrupted(),
        description: m.authentication_incomplete()
      };
    default:
      return message.includes("error")
        ? {
            tone: "error",
            title: m.login_failed_general(),
            description: m.authentication_error_occurred()
          }
        : null;
  }
}
