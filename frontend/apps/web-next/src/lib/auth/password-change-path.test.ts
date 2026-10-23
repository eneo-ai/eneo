import { describe, expect, it } from "vitest";
import { passwordChangedLogoutUrl, passwordChangeUrl } from "./password-change-path";

describe("password change paths", () => {
  it("carries the interrupted page to the password page", () => {
    expect(passwordChangeUrl("/spaces/abc?tab=files")).toBe(
      "/password-change?next=%2Fspaces%2Fabc%3Ftab%3Dfiles"
    );
  });

  it("does not chain the password page onto itself or onto the root", () => {
    expect(passwordChangeUrl("/password-change?next=%2Fx")).toBe("/password-change");
    expect(passwordChangeUrl("/")).toBe("/password-change");
    expect(passwordChangeUrl(undefined)).toBe("/password-change");
  });

  it("signs out with the password-changed notice and a safe destination", () => {
    expect(passwordChangedLogoutUrl("/spaces/abc")).toBe(
      "/logout?reason=password_changed&next=%2Fspaces%2Fabc"
    );
    expect(passwordChangedLogoutUrl(null)).toBe("/logout?reason=password_changed");
  });

  it("drops a destination that would leave the site", () => {
    expect(passwordChangedLogoutUrl("https://evil.example")).toBe(
      "/logout?reason=password_changed"
    );
    expect(passwordChangedLogoutUrl("//evil.example")).toBe("/logout?reason=password_changed");
  });
});
