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
