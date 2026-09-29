import { describe, expect, test, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>({}, { get: (_target, key) => () => String(key) })
}));

import { resolveLoginStatus } from "./loginStatus";

describe("resolveLoginStatus", () => {
  test("returns nothing without a message", () => {
    expect(resolveLoginStatus(null)).toBeNull();
  });

  test("maps logout and expiry to non-error tones", () => {
    expect(resolveLoginStatus("logout")).toEqual({
      tone: "success",
      description: "logout_success"
    });
    expect(resolveLoginStatus("expired")).toEqual({
      tone: "warning",
      description: "session_expired_please_login_again"
    });
  });

  test("confirms a password change and prompts the user to log in again", () => {
    expect(resolveLoginStatus("password_changed")).toEqual({
      tone: "success",
      description: "password_changed_login_again"
    });
  });

  test("warns when sessions remain after a password change", () => {
    expect(resolveLoginStatus("password_changed_sessions_remain")).toEqual({
      tone: "warning",
      description: "password_changed_sessions_remain"
    });
  });

  test("keeps the legacy IdP reasons list", () => {
    expect(resolveLoginStatus("mobilityguard_login_error")).toMatchObject({
      tone: "error",
      title: "authentication_failed",
      reasons: ["invalid_credentials", "account_restrictions", "system_configuration_issues"],
      footer: "try_again_contact_admin"
    });
  });

  test("treats unknown codes containing 'error' as a generic failure", () => {
    expect(resolveLoginStatus("some_new_error")).toMatchObject({
      tone: "error",
      title: "login_failed_general"
    });
    expect(resolveLoginStatus("something_else")).toBeNull();
  });
});
